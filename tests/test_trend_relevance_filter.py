from __future__ import annotations

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.trend_intelligence.models import TrendObservation
from src.trend_intelligence.providers.base import TrendCollectionRequest, TrendCollectionResult
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.service import TrendOperationsService
from src.trend_intelligence.source_policy import PolicyStatus, SourcePolicy, SourceProvider


class _Provider:
    provider_id = "fixture"

    def collect(self, request, *, policy):
        return TrendCollectionResult(
            observations=[
                TrendObservation(
                    item_id="douyin:law",
                    video_id="7531234567890123456",
                    url="https://www.douyin.com/video/7531234567890123456",
                    title="离婚时夫妻共同债务如何认定",
                    author="@律师",
                    keyword="法律",
                    sort_key="latest",
                    sort_label="最新发布",
                    rank=1,
                    hashtags=["法律科普"],
                    duration_seconds=15,
                ),
                TrendObservation(
                    item_id="douyin:food",
                    video_id="7541234567890123456",
                    url="https://www.douyin.com/video/7541234567890123456",
                    title="三分钟学会番茄炒蛋",
                    author="@厨师",
                    keyword="法律",
                    sort_key="latest",
                    sort_label="最新发布",
                    rank=2,
                    hashtags=["美食"],
                ),
            ]
        )


def test_collection_skips_irrelevant_content_before_persistence(tmp_path) -> None:
    profile = AccountProfile(
        account_uuid=stable_account_uuid("legal-account"),
        account_key="legal-account",
        display_name="法律号",
        domain_strategy_id="legal_services",
        seed_keywords=["法律"],
        domain_config={"practice_areas": ["婚姻家事"]},
    )
    repository = TrendRepository(tmp_path / "trend.db")
    service = TrendOperationsService(repository=repository)
    run_id, result = service.collect(
        _Provider(),
        TrendCollectionRequest(keywords=["法律"]),
        policy=SourcePolicy(
            policy_id="fixture",
            provider=SourceProvider.MANUAL_IMPORT,
            status=PolicyStatus.APPROVED,
            max_pages_per_run=1,
            daily_page_cap=1,
        ),
        account_profile=profile,
    )

    assert run_id
    assert [item.video_id for item in result.observations] == ["7531234567890123456"]
    assert result.observations[0].duration_seconds == 15
    assert result.observations[0].relevance_score >= 30
    assert any("跳过 1 条" in warning for warning in result.warnings)
    stored = repository.list_observations(account_uuid=profile.account_uuid)
    assert len(stored) == 1
    assert stored[0].relevance_terms
