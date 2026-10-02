from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

import pytest
from script_pair_fixture import FixtureClient
from source_media_fixture import complete_media_analysis

from src.operations_accounts import AccountProfile
from src.trend_intelligence.models import (
    AccountContentRelevance,
    TrendObservation,
    VideoContentAnalysis,
)
from src.trend_intelligence.pre_video_script import (
    PreVideoScriptRequest,
    PreVideoScriptService,
    render_script_markdown,
)
from src.trend_intelligence import pre_video_script as pre_video_module


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_pre_video_output_stays_inside_project_data(tmp_path, monkeypatch):
    monkeypatch.setattr(pre_video_module, "PROJECT_ROOT", tmp_path)
    with pytest.raises(ValueError, match="project data directory"):
        PreVideoScriptService._resolve_output_dir(
            PreVideoScriptRequest(account_key="account01", recent_video_types=("mixed",),
                                  output_dir=str(tmp_path / "outside"))
        )
    allowed = tmp_path / "data" / "script_pair"
    assert PreVideoScriptService._resolve_output_dir(
        PreVideoScriptRequest(account_key="account01", recent_video_types=("mixed",),
                              output_dir=str(allowed))
    ) == allowed.resolve()


class _Profiles:
    def get(self, account_key: str) -> AccountProfile:
        assert account_key == "account01"
        return AccountProfile(
            account_uuid="account:legal-test",
            account_key="account01",
            domain_strategy_id="legal_services",
            service_scope=["婚姻家事", "劳动争议"],
            publishing_windows=["19:00-22:00"],
            domain_config={
                "practice_areas": ["婚姻家事", "劳动争议"],
                "consultation_cta": "整理证据后再做个案咨询",
            },
        )


class _Repository:
    def __init__(self, observations, analyses):
        self.observations = observations
        self.analyses = analyses
        self.saved_opportunity = None

    def list_observations(self, **kwargs):
        return self.observations

    def list_collection_runs(self, **kwargs):
        return [{"run_id": self.observations[0].run_id}] if self.observations else []

    def list_content_analyses(self, **kwargs):
        return self.analyses

    def save_opportunity(self, value):
        self.saved_opportunity = value

def _row(
    item: str,
    title: str,
    *,
    video_type: str,
    metric: int,
    days_ago: int = 1,
    relevance: float = 75.0,
    author: str = "author",
    media_access_mode: str = "metadata_only",
    visual_summary: str = "",
):
    published_at = (NOW - timedelta(days=days_ago)).isoformat()
    observation = TrendObservation(
        item_id=item,
        video_id=item,
        url=f"https://example.test/{item}",
        title=title,
        author=author,
        keyword="婚姻" if "marriage" in item else "劳动",
        run_id="test-batch",
        metric_kind="views",
        sort_key="latest",
        sort_label="最新发布",
        rank=1,
        metric_value=metric,
        published_at=published_at,
        hashtags=["法律咨询"],
        relevance_score=relevance,
    )
    analysis = VideoContentAnalysis(
        analysis_id=f"analysis:{item}",
        item_id=item,
        video_id=item,
        account_uuid="account:legal-test",
        profile_version=1,
        provider_id="metadata_heuristic",
        provider_version="v1",
        input_fingerprint=item,
        status="degraded",
        media_access_mode=media_access_mode,
        title=title,
        content_summary=title,
        visual_summary=visual_summary,
        topic_labels=["法律咨询"],
        user_intents=["证据准备"],
        hook_type="question",
        presentation_type=video_type,
        pacing="balanced",
        relevance=AccountContentRelevance(
            score=relevance,
            confidence=0.8,
        ),
    )
    return observation, analysis


def test_recent_video_type_input_produces_detailed_script_only_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(pre_video_module, "PROJECT_ROOT", tmp_path)
    labor = _row(
        "labor",
        "被老板辞退后，公司又按旷工解除合同",
        video_type="mixed",
        metric=25_000,
        author="劳动律师甲",
    )
    marriage = _row(
        "marriage",
        "离婚后抚养费应该怎么处理",
        video_type="mixed",
        metric=2_000,
        author="家事律师乙",
    )
    ignored = _row(
        "ignored",
        "劳动合同问题",
        video_type="talking_head",
        metric=1_000_000,
        author="律师丙",
    )
    rows = _expanded_rows([labor, marriage]) + [ignored]
    rows = [(o,complete_media_analysis(a,tmp_path/'media'/o.video_id)) for o,a in rows]
    repository = _Repository([r[0] for r in rows], [r[1] for r in rows])
    service = PreVideoScriptService(
        repository=repository,
        profile_repository=_Profiles(), script_client=FixtureClient(),
    )

    assert service.recent_video_type_counts(
        "account01", now=NOW, window_days=7
    ) == {"mixed": 20, "talking_head": 1}

    artifact = service.generate(
        PreVideoScriptRequest(short_seconds=60, window_days=7, 
            account_key="account01",
            recent_video_types=("mixed",),
            output_dir=str(tmp_path / "data"),
        ),
        now=NOW,
    )

    assert artifact.long.script.target_duration_seconds == 180
    artifact = artifact.short
    markdown = render_script_markdown(artifact.script)
    assert artifact.script.schema == "detailed_video_script/v4"
    assert artifact.script.core_message and artifact.script.resolution
    assert "0—10 秒" in markdown and "50—60 秒" in markdown
    assert "人物定妆与表演弧线" in markdown
    assert "情绪" in markdown
    assert "准确口型" in markdown
    assert "环境声音由视频模型一次生成" in markdown
    assert "分析" not in markdown
    assert repository.saved_opportunity is not None
    assert Path(artifact.script_json_path).exists()
    audit = Path(artifact.audit_path).read_text(encoding="utf-8")
    assert '"schema": "pre_video_script_audit/v3"' in audit
    assert "cross_video_and_author_overlap_mining" in audit
    assert "creative_expansion" in audit


def test_media_traits_require_real_media_analysis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pre_video_module, "PROJECT_ROOT", tmp_path)
    first = _row(
        "media-1",
        "员工被辞退后怎么办？",
        video_type="mixed",
        metric=30_000,
        author="律师甲",
        media_access_mode="local_media_authorized",
        visual_summary="办公室里当事人与律师面对面咨询，律师递出合同，神情冷静",
    )
    second = _row(
        "media-2",
        "老板解除合同要看什么证据？",
        video_type="mixed",
        metric=20_000,
        author="律师乙",
        media_access_mode="local_media_authorized",
        visual_summary="律所咨询室里律师与员工对话并展示合同，表情沉稳",
    )
    metadata = _row(
        "metadata",
        "办公室里怎么处理劳动纠纷？",
        video_type="mixed",
        metric=10_000,
        author="律师丙",
    )
    second[0].keyword = "婚姻"
    rows = _expanded_rows([first, second])
    rows = [(o,complete_media_analysis(a,tmp_path/'media'/o.video_id)) for o,a in rows]
    service = PreVideoScriptService(
        repository=_Repository([r[0] for r in rows], [r[1] for r in rows]),
        profile_repository=_Profiles(), script_client=FixtureClient(),
    )

    # A title mentioning an office is not an observed visual trait.
    from types import SimpleNamespace
    traits = list(service._candidate_traits(_Profiles().get('account01'),
        SimpleNamespace(observation=metadata[0], analysis=metadata[1])))
    assert not any(level == 'observed_media' for _,_,level in traits)

    artifact = service.generate(
        PreVideoScriptRequest(short_seconds=60, window_days=7, 
            account_key="account01",
            recent_video_types=("mixed",),
            high_traffic_percentile=0.5,
            output_dir=str(tmp_path / "data"),
        ),
        now=NOW,
    )

    audit = Path(artifact.short.audit_path).read_text(encoding="utf-8")
    assert '"evidence_level": "observed_media"' in audit
    assert '"办公室/咨询室"' in audit


def test_overlap_requires_twenty_high_traffic_videos() -> None:
    only = _row(
        "only",
        "被辞退怎么办",
        video_type="mixed",
        metric=100_000,
    )
    service = PreVideoScriptService(
        repository=_Repository([only[0]], [only[1]]),
        profile_repository=_Profiles(), script_client=FixtureClient(),
    )

    with pytest.raises(ValueError, match="视频 1/20"):
        service.generate(
            PreVideoScriptRequest(short_seconds=60, window_days=7, 
                account_key="account01",
                recent_video_types=("mixed",),
            ),
            now=NOW,
        )


def test_missing_publish_time_is_not_treated_as_recent() -> None:
    observation, analysis = _row(
        "missing-time",
        "被辞退怎么办",
        video_type="mixed",
        metric=100_000,
    )
    observation.published_at = ""
    service = PreVideoScriptService(
        repository=_Repository([observation], [analysis]),
        profile_repository=_Profiles(), script_client=FixtureClient(),
    )

    with pytest.raises(ValueError, match="没有类型"):
        service.generate(
            PreVideoScriptRequest(short_seconds=60, window_days=7, 
                account_key="account01",
                recent_video_types=("mixed",),
            ),
            now=NOW,
        )


def _expanded_rows(seeds):
    rows = []
    for i in range(20):
        observation, analysis = seeds[i % len(seeds)]
        identity = f"{observation.item_id}-{i}"
        rows.append((replace(observation, item_id=identity, video_id=identity,
                             metric_value=max(50_000, observation.metric_value * 25)),
                     replace(analysis, item_id=identity, video_id=identity, analysis_id=f"analysis:{identity}")))
    return rows


def test_batch_selection_preserves_unknown_publish_time():
    observation, analysis = _row('unknown-date', '被辞退怎么办', video_type='mixed', metric=100_000)
    observation.published_at = ''
    service = PreVideoScriptService(repository=_Repository([observation], [analysis]),
                                    profile_repository=_Profiles(), script_client=FixtureClient())
    request = PreVideoScriptRequest(account_key='account01', recent_video_types=('mixed',))
    candidates = service._recent_candidates(_Profiles().get('account01'), request, NOW)
    assert len(candidates) == 1
    assert candidates[0].published_at is None and candidates[0].age_hours is None
    assert candidates[0].observation.published_at == ''


def test_unobserved_presentation_does_not_exclude_valid_topic_evidence():
    observation, analysis = _row('unknown-style', '签合同应该注意什么', video_type='unknown', metric=100_000)
    service = PreVideoScriptService(repository=_Repository([observation], [analysis]),
                                    profile_repository=_Profiles(), script_client=FixtureClient())
    assert service.recent_video_type_counts('account01', now=NOW) == {'unknown': 1}
