from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.trend_intelligence.analysis import TrendAnalyzer
from src.trend_intelligence.content_analysis import (
    ContentAnalysisBatchService,
    ContentAnalysisRequest,
)
from src.trend_intelligence.models import (
    ContentOpportunity,
    FeedbackLearningReport,
    OpportunityScript,
    ScriptBeat,
    TrendObservation,
)
from src.trend_intelligence.opportunity import (
    ContentOpportunityService,
    DomainScriptStrategyRegistry,
)
from src.trend_intelligence.repository import TREND_SCHEMA_VERSION, TrendRepository


def _profile(domain: str = "legal_services") -> AccountProfile:
    key = f"opportunity_{domain}"
    return AccountProfile(
        account_uuid=stable_account_uuid(key),
        account_key=key,
        display_name=key,
        domain_strategy_id=domain,
        seed_keywords=["婚姻", "债务"] if domain == "legal_services" else ["重生", "复仇"],
        service_scope=["离婚咨询"] if domain == "legal_services" else ["小说推文"],
        target_audiences=["已婚人群"] if domain == "legal_services" else ["爽文读者"],
        publishing_windows=["20:00-22:00"],
        workflow_profile="legal_presenter" if domain == "legal_services" else "novel_drama",
        domain_config=(
            {
                "practice_areas": ["婚姻", "债务"],
                "consultation_cta": "整理证据后再做个案咨询",
            }
            if domain == "legal_services"
            else {
                "genres": ["重生", "复仇"],
                "reading_cta": "在番茄小说搜索书名继续阅读",
            }
        ),
    )


def _observation(
    item: str,
    *,
    metric: int,
    rank: int,
    captured: str,
) -> TrendObservation:
    return TrendObservation(
        item_id=f"douyin:{item}",
        video_id=item,
        url=f"https://www.douyin.com/video/{item}",
        title="律师告诉你：夫妻共同债务怎么留证据？",
        author="律师甲",
        keyword="婚姻",
        sort_key="latest",
        sort_label="最新发布",
        rank=rank,
        metric_text=str(metric),
        metric_value=metric,
        metric_kind="views",
        collected_at=captured,
        published_at="2026-08-31T00:00:00+00:00",
        root_keywords=["婚姻", "债务"],
        hashtags=["婚姻", "债务"],
    )


def _seed_legal_opportunity(repository: TrendRepository):
    profile = _profile()
    repository.save_collection(
        [
            _observation(
                "1", metric=100, rank=12, captured="2026-08-31T00:00:00+00:00"
            ),
            _observation(
                "2", metric=500, rank=8, captured="2026-08-31T00:00:00+00:00"
            ),
        ],
        provider="fixture",
        keywords=["婚姻", "债务"],
        account_uuid=profile.account_uuid,
        profile_version=profile.profile_version,
        domain_strategy_id=profile.domain_strategy_id,
        strategy_version=profile.strategy_version,
    )
    repository.save_collection(
        [
            _observation(
                "1", metric=10_000, rank=2, captured="2026-09-01T00:00:00+00:00"
            ),
            _observation(
                "2", metric=900, rank=6, captured="2026-09-01T00:00:00+00:00"
            ),
        ],
        provider="fixture",
        keywords=["婚姻", "债务"],
        account_uuid=profile.account_uuid,
        profile_version=profile.profile_version,
        domain_strategy_id=profile.domain_strategy_id,
        strategy_version=profile.strategy_version,
    )
    observations = repository.list_observations(limit=1000)
    clusters, briefs = TrendAnalyzer().analyze(
        observations, account_profile=profile
    )
    repository.save_analysis(clusters, briefs)
    latest = {}
    for item in observations:
        latest.setdefault(item.item_id, item)
    requests = [
        ContentAnalysisRequest(
            item_id=item.item_id,
            video_id=item.video_id,
            title=item.title,
            author=item.author,
            hashtags=item.hashtags,
            raw_text=item.title,
            account_profile=profile,
        )
        for item in latest.values()
    ]
    ContentAnalysisBatchService(repository).analyze(requests)
    opportunities = ContentOpportunityService(repository).build_opportunities(profile)
    return profile, opportunities


def test_opportunity_score_combines_time_content_relevance_and_feasibility(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile, opportunities = _seed_legal_opportunity(repository)
    assert opportunities
    opportunity = opportunities[0]
    assert opportunity.account_uuid == profile.account_uuid
    assert opportunity.opportunity_score > 50
    assert opportunity.score_breakdown["temporal_momentum"] > 50
    assert opportunity.score_breakdown["account_relevance"] >= 80
    assert opportunity.recommended_presentation == "talking_head"
    assert opportunity.recommended_publish_window == "20:00-22:00"
    assert opportunity.recommended_workflow_profile == "legal_presenter"
    validity_hours = (
        datetime.fromisoformat(opportunity.valid_until)
        - datetime.fromisoformat(opportunity.valid_from)
    ).total_seconds() / 3600
    assert validity_hours == 48
    assert opportunity.selected_item_ids[0] == "douyin:1"
    assert repository.get_opportunity(opportunity.opportunity_id) is not None
    assert TREND_SCHEMA_VERSION >= 5


def test_legal_ab_scripts_are_exactly_three_five_second_beats(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile, opportunities = _seed_legal_opportunity(repository)
    service = ContentOpportunityService(repository)
    scripts = service.generate_scripts(profile, opportunities[0].opportunity_id)

    assert [item.variant_id for item in scripts] == ["A", "B"]
    for script in scripts:
        assert script.target_duration_seconds == 15
        assert [
            (beat.start_seconds, beat.end_seconds) for beat in script.beats
        ] == [(0, 5), (5, 10), (10, 15)]
        assert script.fact_check_requirements
        assert script.originality_requirements
        assert script.workflow_snapshot["workflow_profile"] == "legal_presenter"
    stored = repository.list_opportunity_scripts(
        opportunity_id=opportunities[0].opportunity_id
    )
    assert len(stored) == 2
    assert isinstance(stored[0].beats[0], ScriptBeat)
    assert service.approve_script(stored[0].script_id)
    assert repository.list_opportunity_scripts(status="approved")[0].status == "approved"


def test_novel_strategy_generates_authorized_source_placeholders_not_fake_facts(
    tmp_path,
) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile = _profile("novel_promotion")
    opportunity = ContentOpportunity(
        opportunity_id="opportunity:novel",
        account_uuid=profile.account_uuid,
        account_key=profile.account_key,
        profile_version=profile.profile_version,
        domain_strategy_id=profile.domain_strategy_id,
        strategy_version=profile.strategy_version,
        cluster_id="cluster:novel",
        brief_id="brief:novel",
        title="重生复仇",
        status="candidate",
        opportunity_score=88,
        score_breakdown={},
        selected_item_ids=["douyin:n1"],
        recommended_presentation="story_drama",
        recommended_hook_type="conflict",
        recommended_pacing="fast",
        recommended_duration_seconds=15,
        recommended_publish_window="20:00-22:00",
        recommended_workflow_profile="novel_drama",
        valid_until="2026-09-03T00:00:00+00:00",
    )
    repository.save_opportunity(opportunity)

    scripts = ContentOpportunityService(repository).generate_scripts(
        profile, opportunity.opportunity_id
    )

    assert all(script.domain_strategy_id == "novel_promotion" for script in scripts)
    assert all("授权章节" in " ".join(script.source_requirements) for script in scripts)
    assert all(
        "【主角】" in " ".join(beat.voiceover for beat in script.beats)
        for script in scripts
    )
    assert scripts[0].cta == "在番茄小说搜索书名继续阅读"


def test_opportunity_and_script_status_transitions_are_persisted(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile, opportunities = _seed_legal_opportunity(repository)
    service = ContentOpportunityService(repository)
    opportunity = opportunities[0]
    assert service.approve_opportunity(opportunity.opportunity_id)
    assert repository.get_opportunity(opportunity.opportunity_id).status == "approved"
    assert service.reject_opportunity(opportunity.opportunity_id)
    assert repository.get_opportunity(opportunity.opportunity_id).status == "rejected"
    with pytest.raises(ValueError, match="invalid"):
        repository.update_opportunity_status(opportunity.opportunity_id, "bad")
    assert profile.account_uuid == opportunity.account_uuid


def test_feedback_learning_adjusts_the_next_opportunity_score(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    profile, opportunities = _seed_legal_opportunity(repository)
    before = opportunities[0]
    keys = [
        f"topic:{before.cluster_id}",
        f"hook:{before.recommended_hook_type}",
        f"presentation:{before.recommended_presentation}",
        f"workflow:{before.recommended_workflow_profile}",
        f"publish_window:{before.recommended_publish_window}",
    ]
    repository.save_feedback_learning_report(
        FeedbackLearningReport(
            report_id="feedback:high",
            account_uuid=profile.account_uuid,
            profile_version=profile.profile_version,
            sample_size=10,
            status="ready",
            dimensions=[],
            score_adjustments={key: 90.0 for key in keys},
            proven_topics=[before.cluster_id],
            next_cycle_allocation={
                "proven": 0.7,
                "adjacent": 0.2,
                "experiment": 0.1,
            },
            summary="fixture",
            created_at="2099-01-01T00:00:00+00:00",
        )
    )
    after = ContentOpportunityService(repository).build_opportunities(profile)[0]
    assert before.score_breakdown["feedback_prior"] == 50
    assert after.score_breakdown["feedback_prior"] == 90
    assert after.opportunity_score > before.opportunity_score


class _EducationScriptStrategy:
    domain_strategy_id = "education"
    strategy_version = "v1"

    def build(self, profile, opportunity, *, variant_id):
        return OpportunityScript(
            script_id=f"script:education:{variant_id}",
            opportunity_id=opportunity.opportunity_id,
            account_uuid=profile.account_uuid,
            domain_strategy_id=self.domain_strategy_id,
            strategy_version=self.strategy_version,
            variant_id=variant_id,
            title="教育脚本",
            status="draft",
            target_duration_seconds=15,
            beats=[ScriptBeat(0, 15, "lesson", "板书", "讲解", "知识点")],
            cta="收藏",
            source_requirements=[],
            fact_check_requirements=[],
            originality_requirements=[],
            workflow_snapshot={},
        )


def test_script_registry_accepts_a_third_domain_without_core_changes() -> None:
    registry = DomainScriptStrategyRegistry()
    registry.register(_EducationScriptStrategy())
    legal = _profile()
    education_profile = replace(
        legal,
        account_uuid=stable_account_uuid("education_account"),
        account_key="education_account",
        domain_strategy_id="education",
        domain_config={},
    )
    assert registry.resolve(education_profile).domain_strategy_id == "education"
    with pytest.raises(KeyError, match="no script strategy"):
        registry.resolve(legal)
