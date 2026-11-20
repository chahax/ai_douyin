"""Exercise the live dashboard branch, not its unused legacy opportunity page."""
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.web import trend_dashboard as dashboard
from src.web import account_novel_creation_panel as panel


def _setup(monkeypatch, opportunities=None):
    profile = AccountProfile(
        account_uuid=stable_account_uuid("route_novel"), account_key="route_novel",
        domain_strategy_id="novel_promotion", seed_keywords=["校园"],
        domain_config={"genres": ["校园"]},
    )
    if opportunities is None:
        opportunities = [SimpleNamespace(
            opportunity_id="op:novel", title="校园关系反转", opportunity_score=83,
            status="candidate", evidence=["离线页面路由夹具"], valid_until="2026-10-17T12:00:00+08:00",
        )]
    calls = []
    repository = SimpleNamespace(
        list_opportunities=lambda **kwargs: opportunities,
    )
    service = SimpleNamespace(analyze=lambda **kwargs: calls.append(("analyze", kwargs)))
    accounts = SimpleNamespace(list_active=lambda: [profile])
    monkeypatch.setattr(dashboard, "_novel_route_test_context", (repository, service, accounts), raising=False)
    monkeypatch.setattr(panel, "render_account_novel_creation", lambda *args: calls.append(("panel", args)))
    from src.trend_intelligence.pre_video_script import PreVideoScriptService

    def no_legal_service(*args, **kwargs):
        raise AssertionError("novel account entered the legal-only detailed script service")

    monkeypatch.setattr(PreVideoScriptService, "__init__", no_legal_service)
    app = AppTest.from_string(
        "from src.web import trend_dashboard as page\n"
        "page._render_briefs(*page._novel_route_test_context)\n",
        default_timeout=20,
    ).run()
    assert not app.exception
    app.selectbox(key="pre_video_script_scope").set_value(profile.account_uuid).run()
    return app, calls, profile


def test_live_novel_dashboard_reaches_full_creation_before_legal_service(monkeypatch):
    app, calls, profile = _setup(monkeypatch)
    assert not app.exception
    assert len(calls) == 1 and calls[0][0] == "panel"
    assert calls[0][1][0] == profile
    assert calls[0][1][1].opportunity_id == "op:novel"
    assert not any(button.label == "生成短版 + 长版剧本" for button in app.button)


def test_novel_dashboard_without_opportunity_does_not_launch_creator(monkeypatch):
    app, calls, _ = _setup(monkeypatch, [])
    assert not app.exception and calls == []
    assert any("还没有机会卡" in item.value for item in app.info)


def test_novel_opportunity_refresh_failure_is_visible_and_keeps_saved_opportunity(monkeypatch):
    app, calls, _ = _setup(monkeypatch)

    def failed_analysis(**kwargs):
        raise ValueError("fixture: 同批研究样本不足")

    dashboard._novel_route_test_context[1].analyze = failed_analysis
    app.button(key="novel_creation_refresh_opportunities").click().run()
    assert not app.exception
    assert any("同批研究样本不足" in item.value for item in app.error)
    assert [call[0] for call in calls] == ["panel", "panel"]
