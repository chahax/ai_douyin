from streamlit.testing.v1 import AppTest
from types import SimpleNamespace

import pytest


def test_trend_dashboard_renders_without_side_effects(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TREND_DB_PATH", str(tmp_path / "trend.db"))
    monkeypatch.setenv("ACCOUNT_PROFILE_DB_PATH", str(tmp_path / "accounts.db"))
    # The dashboard initializes multiple SQLite-backed services on a cold Windows
    # process; allow enough time for the first-run path while still bounding hangs.
    app = AppTest.from_file("src/web/trend_dashboard.py", default_timeout=30)
    app.run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "账号策略",
        "采集与分析",
        "选题卡",
        "运营复盘",
    ]
    assert len(app.metric) >= 5
    assert "扩展一层相关标签族" in [item.label for item in app.checkbox]
    assert "每个关键词最多扩展标签" in [item.label for item in app.slider]
    assert "领域策略" in [item.label for item in app.selectbox]
    assert "运行完整研究流程" in [item.label for item in app.button]


def test_playback_maintenance_controls_render(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TREND_DB_PATH", str(tmp_path / "trend.db"))
    monkeypatch.setenv("ACCOUNT_PROFILE_DB_PATH", str(tmp_path / "accounts.db"))
    from src.operations_accounts import (
        AccountProfile,
        AccountProfileRepository,
        stable_account_uuid,
    )

    AccountProfileRepository().save(
        AccountProfile(
            account_uuid=stable_account_uuid("account01"),
            account_key="account01",
            display_name="法律号",
            domain_strategy_id="legal_services",
            seed_keywords=["法律"],
        )
    )
    app = AppTest.from_file("src/web/trend_dashboard.py", default_timeout=30).run()
    next(item for item in app.selectbox if "account01" in item.options).select(
        "account01"
    )
    app.run(timeout=30)
    mode = next(
        item
        for item in app.selectbox
        if any("playback" in str(option) for option in item.options)
    )
    mode.set_value("playback")
    app.run(timeout=30)

    assert not app.exception
    assert {
        "视频数",
        "单条上限（秒）",
        "总时长（分钟）",
        "最低相关度",
    }.issubset({item.label for item in app.number_input})
    assert {"基础点赞比例（%）", "基础评论比例（%）"}.issubset(
        {item.label for item in app.slider}
    )
    assert {"使用可见浏览器", "自动点赞", "安全自动评论"}.issubset(
        {item.label for item in app.checkbox}
    )


def test_metadata_only_sources_show_missing_media_and_disable_script_generation(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from src.operations_accounts import AccountProfile, AccountProfileRepository, stable_account_uuid
    from src.trend_intelligence.models import TrendObservation
    from src.trend_intelligence.repository import TrendRepository
    from src.trend_intelligence.content_analysis import ContentAnalysisRequest
    from src.trend_intelligence.content_analysis.metadata import MetadataContentAnalysisProvider

    monkeypatch.setenv("TREND_DB_PATH", str(tmp_path / "trend.db"))
    monkeypatch.setenv("ACCOUNT_PROFILE_DB_PATH", str(tmp_path / "accounts.db"))
    profile = AccountProfile(account_uuid=stable_account_uuid("legal"), account_key="legal",
        display_name="法律号", domain_strategy_id="legal_services", seed_keywords=["法律", "合同"],
        domain_config={"practice_areas": ["合同"]})
    AccountProfileRepository().save(profile)
    repository = TrendRepository()
    rows = [TrendObservation(item_id=f"video:{i}", video_id=str(i),
        url=f"https://www.douyin.com/video/{i}", title="合同纠纷法律案例", author=f"作者{i}",
        keyword="法律" if i % 2 else "合同", sort_key="most_liked", sort_label="最多点赞",
        rank=i + 1, metric_value=100_000, metric_kind="likes", hashtags=["合同", "法律"],
        collected_at=datetime.now(timezone.utc).isoformat()) for i in range(20)]
    repository.save_collection(rows, provider="fixture", keywords=["法律", "合同"], account_uuid=profile.account_uuid)
    for row in rows:
        repository.save_content_analysis(MetadataContentAnalysisProvider().analyze(
            ContentAnalysisRequest(item_id=row.item_id, video_id=row.video_id, title=row.title,
                author=row.author, hashtags=row.hashtags, account_profile=profile)))
    app = AppTest.from_string('''
import streamlit as st
from src.operations_accounts import stable_account_uuid
st.session_state['active_account_uuid'] = stable_account_uuid('legal')
from src.web.trend_dashboard import _render_briefs
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.service import TrendOperationsService
from src.operations_accounts import AccountProfileRepository
repo = TrendRepository()
_render_briefs(repo, TrendOperationsService(repository=repo), AccountProfileRepository())
''', default_timeout=30).run()
    assert not app.exception
    assert any("0/20" in warning.value for warning in app.warning)
    assert any("不能当作剧本参考贡献率" in caption.value for caption in app.caption)
    assert "获取所选原片" in [button.label for button in app.button]
    generate = next((button for button in app.button if button.label == "生成短版 + 长版剧本"), None)
    assert generate is None or generate.disabled


def _selected_acquisition_fixture(monkeypatch):
    import src.web.trend_dashboard as dashboard
    profile = SimpleNamespace(account_uuid="account-legal", account_key="legal")
    request = SimpleNamespace(account_key="legal", collection_run_id="selected-run")
    rows = [SimpleNamespace(item_id=f"item-{index}", video_id=str(10000000 + index), run_id="selected-run",
                            url=f"https://www.douyin.com/video/{10000000 + index}", title=f"source {index}") for index in range(50)]
    selected = {"ready": False, "message": "原视频音画分析 0/20", "sample_gate": {"run_id": "selected-run"},
                "selected_item_ids": [row.item_id for row in rows[10:30]]}
    class ScriptService:
        def source_media_readiness(self, received, **kwargs):
            assert received is request
            return selected
        def generate(self, *args, **kwargs):
            raise AssertionError("acquisition must never generate a script")
    reads = []
    def read_batch(repository, *, account_uuid, run_id):
        reads.append((repository, account_uuid, run_id))
        assert account_uuid == profile.account_uuid
        assert run_id == "selected-run"
        return rows
    monkeypatch.setattr(dashboard, "batch_observations", read_batch)
    return dashboard, profile, request, rows, selected, ScriptService(), reads


def test_acquisition_uses_exact_script_selection_and_keeps_same_session_after_verification(monkeypatch):
    dashboard, profile, request, rows, selected, script_service, reads = _selected_acquisition_fixture(monkeypatch)
    constructed, calls = [], []
    session = object()
    class FakeAcquisition:
        def __init__(self, **kwargs):
            constructed.append(self)
            self.session = None
        def acquire(self, candidates, **kwargs):
            calls.append((candidates, kwargs))
            self.session = kwargs["session"] or session
            first = len(calls) == 1
            payload = {"status": "human_required" if first else "completed", "manifest_path": "data/fake/manifest.json",
                       "selected_count": len(candidates), "acquired_count": 0 if first else 3,
                       "cached_count": 0 if first else 17, "attempted_count": 1 if first else 3,
                       "stopped_reason": "请在当前页完成验证" if first else "", "session_left_open": True}
            return SimpleNamespace(to_dict=lambda: payload)
    state, repository = {}, object()
    first = dashboard._acquire_selected_script_media(script_service, request, profile, repository, state,
        expected_readiness=selected, service_factory=FakeAcquisition)
    second = dashboard._acquire_selected_script_media(script_service, request, profile, repository, state,
        expected_readiness=selected, service_factory=FakeAcquisition)
    assert len(constructed) == 1
    assert len(calls) == 2
    for candidates, kwargs in calls:
        assert candidates == rows[10:30]  # Never acquire the whole 50-source batch or first 20.
        assert kwargs["collection_run_id"] == "selected-run"
        assert kwargs["account_uuid"] == profile.account_uuid
        assert kwargs["max_items"] == 20
        assert kwargs["policy"].max_pages_per_run == 20
    assert calls[0][1]["session"] is None
    assert calls[1][1]["session"] is session
    assert calls[1][1]["pages_used_today"] == 1
    assert state["pre_video_source_acquisition_sessions"][profile.account_uuid]["session"] is session
    assert first["status"] == "human_required"
    assert second["acquired_count"] == 3 and second["cached_count"] == 17
    assert all(second[key] is False for key in ("analysis_submitted", "script_generation_submitted", "video_generation_submitted"))
    assert second["selected_item_ids"] == selected["selected_item_ids"]
    assert len(reads) == 2


def test_selected_acquisition_rejects_selection_drift_and_foreign_batch_without_opening_session(monkeypatch):
    dashboard, profile, request, rows, selected, script_service, _ = _selected_acquisition_fixture(monkeypatch)
    def no_browser(**kwargs):
        raise AssertionError("invalid selection must not construct a browser service")
    expected = {**selected, "selected_item_ids": [row.item_id for row in rows[:20]]}
    with pytest.raises(ValueError, match="筛选已变化"):
        dashboard._acquire_selected_script_media(script_service, request, profile, object(), {},
            expected_readiness=expected, service_factory=no_browser)
    rows[10].run_id = "foreign-run"
    with pytest.raises(ValueError, match="同一批次"):
        dashboard._acquire_selected_script_media(script_service, request, profile, object(), {},
            expected_readiness=selected, service_factory=no_browser)


def test_selected_acquisition_preserves_created_session_when_service_raises(monkeypatch):
    dashboard, profile, request, _, selected, script_service, _ = _selected_acquisition_fixture(monkeypatch)
    session = object()
    class FailingService:
        def __init__(self, **kwargs):
            self.session = None
        def acquire(self, candidates, **kwargs):
            self.session = session
            raise RuntimeError("fixture validation pending")
    state = {}
    with pytest.raises(RuntimeError, match="fixture"):
        dashboard._acquire_selected_script_media(script_service, request, profile, object(), state,
            expected_readiness=selected, service_factory=FailingService)
    assert state["pre_video_source_acquisition_sessions"][profile.account_uuid]["session"] is session
    assert state["pre_video_source_acquisition_sessions"][profile.account_uuid]["service"].session is session
