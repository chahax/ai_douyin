from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ConfigDict

from src.operations_accounts import (
    AccountProfile,
    AccountProfileConflict,
    AccountProfileRepository,
)
from src.trend_intelligence.analysis import TrendAnalyzer, stable_item_id
from src.trend_intelligence.domain import (
    AccountFitEvidence,
    DomainBriefBlueprint,
    DomainQueryPlan,
    DomainStrategyConfigError,
    DomainStrategyRegistry,
    DomainTopicContext,
    LegalServicesStrategy,
    NovelPromotionStrategy,
    PydanticDomainStrategy,
    get_default_domain_registry,
)
from src.trend_intelligence.models import TrendObservation


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc).isoformat()


def _profile(
    strategy_id: str,
    *,
    account_key: str,
    seed_keywords: list[str],
    domain_config: dict | None = None,
) -> AccountProfile:
    return AccountProfile(
        account_uuid=f"account:{account_key}",
        account_key=account_key,
        domain_strategy_id=strategy_id,
        strategy_version="v1",
        display_name=account_key,
        business_mode=strategy_id,
        seed_keywords=seed_keywords,
        domain_config=domain_config or {},
    )


def _observation(
    video_id: str,
    title: str,
    *,
    keyword: str,
    hashtags: list[str],
) -> TrendObservation:
    return TrendObservation(
        item_id=stable_item_id(video_id=video_id),
        video_id=video_id,
        url=f"https://www.douyin.com/video/{video_id}",
        title=title,
        author="@样本作者",
        keyword=keyword,
        sort_key="most_liked",
        sort_label="最多点赞",
        rank=1,
        run_id="run-domain",
        metric_text="2.5万",
        metric_value=25_000,
        collected_at=NOW,
        root_keywords=[keyword],
        hashtags=hashtags,
    )


def test_builtin_registry_exposes_legal_and_novel_schema() -> None:
    available = get_default_domain_registry().list_available()
    assert [(item.strategy_id, item.version) for item in available] == [
        ("legal_services", "v1"),
        ("novel_promotion", "v1"),
    ]
    assert all(item.config_schema["type"] == "object" for item in available)
    assert all(item.config_schema["additionalProperties"] is False for item in available)


def test_legal_and_novel_build_different_query_and_brief_contracts() -> None:
    legal = LegalServicesStrategy()
    legal_profile = _profile(
        "legal_services",
        account_key="legal_01",
        seed_keywords=["夫妻共同债务"],
        domain_config={"practice_areas": ["婚姻家事"]},
    )
    novel = NovelPromotionStrategy()
    novel_profile = _profile(
        "novel_promotion",
        account_key="novel_01",
        seed_keywords=["重生复仇"],
        domain_config={"genres": ["大女主"]},
    )

    legal_plan = legal.build_query_plan(legal_profile)
    novel_plan = novel.build_query_plan(novel_profile)
    assert "夫妻共同债务" in legal_plan.root_keywords
    assert "婚姻家事" in legal_plan.root_keywords
    assert any("证据" in item for item in legal_plan.related_keywords)
    assert "重生复仇" in novel_plan.root_keywords
    assert "大女主" in novel_plan.root_keywords
    assert any("反转" in item for item in novel_plan.related_keywords)

    topic = DomainTopicContext(
        title="重生复仇",
        keywords=["小说"],
        representative_titles=["她重生回订婚宴开始清算"],
    )
    legal_brief = legal.build_brief_blueprint(legal_profile, topic)
    novel_brief = novel.build_brief_blueprint(novel_profile, topic)
    assert any("证据" in item for item in legal_brief.script_structure)
    assert any("反转" in item for item in novel_brief.script_structure)
    assert "授权章节" in " ".join(novel_brief.risks)


def test_strategy_rejects_unknown_domain_config_fields() -> None:
    profile = _profile(
        "legal_services",
        account_key="legal_invalid",
        seed_keywords=["劳动仲裁"],
        domain_config={"unknown_switch": True},
    )
    with pytest.raises(DomainStrategyConfigError, match="invalid legal_services/v1"):
        get_default_domain_registry().resolve(profile)


def test_analyzer_is_account_scoped_and_uses_domain_specific_briefs() -> None:
    legal_rows = [
        _observation(
            "901",
            "夫妻共同债务如何认定 #婚姻法律 #借款证据",
            keyword="夫妻共同债务",
            hashtags=["婚姻法律", "借款证据"],
        )
    ]
    novel_rows = [
        _observation(
            "902",
            "重生回订婚宴她当众开始复仇 #小说推文 #大女主",
            keyword="重生复仇",
            hashtags=["小说推文", "大女主"],
        )
    ]
    legal_profile = _profile(
        "legal_services",
        account_key="legal_02",
        seed_keywords=["夫妻共同债务"],
    )
    novel_profile = _profile(
        "novel_promotion",
        account_key="novel_02",
        seed_keywords=["重生复仇"],
    )

    legal_clusters, legal_briefs = TrendAnalyzer().analyze(
        legal_rows,
        account_profile=legal_profile,
    )
    novel_clusters, novel_briefs = TrendAnalyzer().analyze(
        novel_rows,
        account_profile=novel_profile,
    )

    assert legal_clusters[0].account_uuid == legal_profile.account_uuid
    assert novel_clusters[0].account_uuid == novel_profile.account_uuid
    assert legal_clusters[0].cluster_id != novel_clusters[0].cluster_id
    assert legal_briefs[0].domain_strategy_id == "legal_services"
    assert novel_briefs[0].domain_strategy_id == "novel_promotion"
    assert legal_briefs[0].source_scope["domain"] == "legal"
    assert novel_briefs[0].source_scope["domain"] == "novel"
    assert "处理结果" in legal_briefs[0].recommended_hook
    assert "秘密" in novel_briefs[0].recommended_hook


class EducationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str


class EducationStrategy(PydanticDomainStrategy):
    strategy_id = "education_content"
    version = "v1"
    label = "测试教育领域"
    config_model = EducationConfig

    def build_query_plan(self, profile: AccountProfile) -> DomainQueryPlan:
        config = self.validate_profile(profile)
        return DomainQueryPlan(root_keywords=[config["subject"]])

    def score_account_fit(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> AccountFitEvidence:
        config = self.validate_profile(profile)
        score = 100 if config["subject"] in topic.searchable_text else 20
        return AccountFitEvidence(score=score, matched_terms=[config["subject"]])

    def build_brief_blueprint(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> DomainBriefBlueprint:
        config = self.validate_profile(profile)
        return DomainBriefBlueprint(
            audience_questions=[f"如何理解{config['subject']}？"],
            angles=["概念解释"],
            recommended_hook=f"一分钟理解{config['subject']}。",
            script_structure=["问题", "解释", "例子"],
            risks=["核验教学内容"],
            source_scope={"domain": "education"},
        )


def test_third_domain_registers_without_core_changes() -> None:
    registry = DomainStrategyRegistry()
    registry.register(EducationStrategy())
    profile = _profile(
        "education_content",
        account_key="education_01",
        seed_keywords=["函数"],
        domain_config={"subject": "函数"},
    )
    strategy = registry.resolve(profile)
    assert strategy.build_query_plan(profile).root_keywords == ["函数"]

    rows = [
        _observation(
            "903",
            "函数为什么是高中数学的关键概念",
            keyword="函数",
            hashtags=["高中数学"],
        )
    ]
    clusters, briefs = TrendAnalyzer(domain_registry=registry).analyze(
        rows,
        account_profile=profile,
    )
    assert clusters[0].score_breakdown["account_fit"] == 100
    assert briefs[0].source_scope["domain"] == "education"
    assert "一分钟理解函数" in briefs[0].recommended_hook


def test_account_profile_repository_keeps_immutable_versions(tmp_path) -> None:
    repository = AccountProfileRepository(tmp_path / "accounts.db")
    version_one = _profile(
        "legal_services",
        account_key="legal_persisted",
        seed_keywords=["劳动仲裁"],
    )
    repository.save(version_one)
    assert repository.get("legal_persisted") == version_one
    assert repository.next_profile_version("legal_persisted") == 2

    version_two = AccountProfile(
        account_uuid=version_one.account_uuid,
        account_key=version_one.account_key,
        domain_strategy_id="legal_services",
        strategy_version="v1",
        profile_version=2,
        seed_keywords=["劳动仲裁", "违法辞退"],
    )
    repository.save(version_two)
    assert repository.get("legal_persisted") == version_two
    assert repository.get("legal_persisted", profile_version=1) == version_one
    assert repository.list_active() == [version_two]

    changed_version_one = AccountProfile(
        account_uuid=version_one.account_uuid,
        account_key=version_one.account_key,
        domain_strategy_id="legal_services",
        strategy_version="v1",
        profile_version=1,
        seed_keywords=["不能覆盖历史版本"],
    )
    with pytest.raises(AccountProfileConflict, match="immutable"):
        repository.save(changed_version_one)


def test_account_repository_validates_domain_plugin_before_activation(tmp_path) -> None:
    repository = AccountProfileRepository(tmp_path / "accounts.db")
    invalid = _profile(
        "novel_promotion",
        account_key="novel_invalid_config",
        seed_keywords=["小说推文"],
        domain_config={"not_in_schema": True},
    )
    with pytest.raises(DomainStrategyConfigError):
        repository.save(invalid)

    registry = DomainStrategyRegistry()
    registry.register(EducationStrategy())
    custom_repository = AccountProfileRepository(
        tmp_path / "custom-accounts.db",
        domain_registry=registry,
    )
    education = _profile(
        "education_content",
        account_key="education_persisted",
        seed_keywords=["函数"],
        domain_config={"subject": "函数"},
    )
    custom_repository.save(education)
    assert custom_repository.get("education_persisted") == education
