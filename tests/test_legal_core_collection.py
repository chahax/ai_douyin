from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.parse import unquote
import pytest

from src.operations_accounts.models import AccountProfile
from src.trend_intelligence.collection.legal_core import build_legal_core_plan, legal_related_terms
from src.trend_intelligence.domain.legal import LegalServicesStrategy
from src.trend_intelligence.domain.base import DomainTopicContext
from src.trend_intelligence.models import TrendObservation
from src.trend_intelligence.providers.base import TrendCollectionRequest, TrendCollectionResult
from src.trend_intelligence.providers.douyin_web import DouyinWebTrendProvider
from src.trend_intelligence.service import TrendOperationsService
from tests.test_douyin_trend_provider import FakeSession, _policy

NOW = "2026-10-07T04:00:00+00:00"


def profile():
    return AccountProfile("legal:offline", "legal-offline", "legal_services", seed_keywords=["法律"],
        service_scope=["劳动争议"], negative_keywords=["保证胜诉"], domain_config={"practice_areas": ["劳动争议"]})


def rows():
    output = []
    for i in range(20):
        tags = ["拖欠工资", "加班费"] if i < 10 else ["离职补偿"]
        output.append(TrendObservation(item_id=f"i{i}", video_id=f"v{i}", url=f"https://example.test/{i}",
            title="劳动争议：工资、加班与离职争议", author=f"作者{i % 5}",
            keyword="劳动争议" if i % 2 else "工资", sort_key="latest", sort_label="最新发布", rank=i+1,
            run_id="offline-batch", collected_at="2026-10-07T03:00:00+00:00",
            metric_kind="views", metric_value=60_000, hashtags=[*tags, "正能量", "法律科普"]))
    return output


def plan(observations=None, **kwargs):
    return build_legal_core_plan(profile(), rows() if observations is None else observations,
                                "劳动争议", now=NOW, **kwargs)


def test_no_legal_content_gets_no_positive_domain_fit():
    strategy = LegalServicesStrategy()
    unrelated = strategy.score_account_fit(profile(), DomainTopicContext("番茄炒蛋", [], [], ["美食"]))
    related = strategy.score_account_fit(profile(), DomainTopicContext("拖欠工资的劳动争议", [], [], []))
    assert unrelated.score == 0 and related.score >= 30


def test_service_filters_related_queries_before_provider_without_mutating_request():
    class Capture:
        def collect(self, request, *, policy):
            self.request = request
            return TrendCollectionResult([])
    provider = Capture(); request = TrendCollectionRequest(["法律"], expand_related_tags=True)
    original = asdict(request)
    run_id, result = TrendOperationsService(repository=object()).collect(provider, request, policy=_policy(), account_profile=profile())
    assert run_id is None
    assert "工资" in provider.request.related_tag_filter_terms
    assert provider.request.min_related_tag_support_videos >= 2
    assert provider.request.min_related_tag_unique_authors >= 2
    assert "保证胜诉" in provider.request.related_tag_excluded_terms
    assert asdict(request) == original


@pytest.mark.parametrize("same_author", [True, False])
def test_fake_browser_only_opens_supported_legal_related_tag(same_author):
    session = FakeSession()
    session.page.rows_by_sort = {key: dict(value,
        title="劳动合同工资争议 #拖欠工资 #热点新闻 #明星八卦",
        author="@同一个作者" if same_author else f"@作者{n}",
        rawText="法律讨论 #拖欠工资 #热点新闻 #明星八卦")
        for n,(key,value) in enumerate(session.page.rows_by_sort.items())}
    request = TrendCollectionRequest(["法律"], limit_per_sort=1, web_crawler_enabled=True,
        expand_related_tags=True, max_related_tags_per_keyword=1,
        related_tag_filter_terms=("工资",), min_related_tag_support_videos=2, min_related_tag_unique_authors=2)
    result = DouyinWebTrendProvider(session_factory=lambda _: session).collect(request, policy=_policy())
    associated_urls = [unquote(u) for u in session.urls if "%23" in u]
    assert not any("明星" in u or "热点新闻" in u for u in associated_urls)
    if same_author:
        assert associated_urls == [] and len(result.observations) == 3
    else:
        assert len(associated_urls) == 3 and all("#拖欠工资" in u for u in associated_urls)


def test_rebuild_understands_real_hashtag_kind_and_no_expand_flags():
    source = rows()[:3]
    source[0].keyword = source[1].keyword = "劳动争议"
    source[0].hashtags = ["拖欠工资"]
    source[1].hashtags = ["拖欠工资"]
    source[2].query_kind = "hashtag"; source[2].query_depth = 1
    source[2].query_value = "拖欠工资"; source[2].hashtags = ["拖欠工资", "借款证据"]
    result = TrendCollectionResult(source)
    request = TrendCollectionRequest(["劳动争议"], expand_related_tags=True,
        related_tag_filter_terms=("工资",), min_related_tag_support_videos=2, min_related_tag_unique_authors=2)
    TrendOperationsService._rebuild_filtered_tag_graph(result, request)
    assert result.tag_traffic_snapshots
    assert any(r.relation_kind == "video_cooccurrence" for r in result.tag_relations)
    request.expand_related_tags = False
    TrendOperationsService._rebuild_filtered_tag_graph(result, request)
    assert not any(r.expanded for r in result.tag_relations)


def test_one_core_multiple_related_direct_evidence_and_same_batch_request():
    output = plan(max_related_tags=2)
    assert output["core_tag"] == "劳动争议"
    assert len(output["related_tags"]) == 2
    assert "正能量" not in output["related_tags"] and "法律科普" not in output["related_tags"]
    assert output["collection_request"]["keywords"] == ["劳动争议", *output["related_tags"]]
    assert output["estimated_pages"] == 9
    assert output["collection_request"]["expand_related_tags"] is False
    assert output["source_sample_gate"]["passed"] is True
    assert output["current_hot_topic_verified"] is False and output["submitted"] is False
    assert all(c["supporting_item_ids"] for c in output["candidates"] if c["selected"])


def test_diversity_avoids_identical_evidence_when_an_alternative_exists():
    output = plan(max_related_tags=2)
    assert "离职补偿" in output["related_tags"]
    assert not {"拖欠工资", "加班费"} <= set(output["related_tags"])


def test_video_hits_and_metrics_not_multiplied_across_sorts_or_alias_item_ids():
    source = rows(); extra = deepcopy(source[0]);extra.sort_key="most_liked";extra.item_id="another-hit-id"
    output = plan([*source,extra])
    candidate = next(c for c in output["candidates"] if c["tag"] == "拖欠工资")
    assert candidate["support_unique_videos"] == 10
    assert output["source_unique_videos"] == 20
    assert output["typed_metric_evidence"]["views"]["confirmed_total"] == 1_200_000


def test_same_author_and_unknown_tag_do_not_become_automatic_associations():
    source = rows()
    for r in source:
        r.author = "一个账号";r.hashtags.append("打工人")
    output = plan(source)
    assert output["related_tags"] == []
    assert any("legal_tag_meaning_unverified" in c["rejection_reasons"] for c in output["candidates"] if c["tag"]=="打工人")


def test_keywords_do_not_manufacture_visible_core_or_legal_evidence():
    source = rows()
    for r in source:
        r.title="明星新作品";r.hashtags=["明星", "娱乐"]
    output = plan(source)
    assert output["core_legal_unique_videos"] == 0 and output["related_tags"] == []


def test_off_core_legal_content_is_not_attached_to_specific_core():
    source = rows()
    for r in source:
        r.title="离婚彩礼返还";r.hashtags=["彩礼", "离婚"]
    assert plan(source)["core_legal_unique_videos"] == 0


def test_stale_associations_seed_new_searches_but_never_prove_current_heat():
    source = rows()
    for r in source: r.collected_at="2026-09-01T00:00:00+00:00"
    output = plan(source)
    assert output["related_tags"]
    assert "source_sample_stale_or_missing" in output["creative_handoff_blockers"]
    assert output["current_hot_topic_verified"] is False


def test_likes_and_views_remain_separate_and_unknown_counts_ignored():
    source = rows()
    for r in source[:10]: r.metric_kind="likes"
    source[0].metric_kind="displayed_unknown";source[0].metric_value=9_000_000
    output = plan(source)
    assert output["typed_metric_evidence"]["views"]["confirmed_total"] == 600_000
    assert output["typed_metric_evidence"]["likes"]["confirmed_total"] == 540_000
    assert output["source_sample_gate"]["passed"] is False


@pytest.mark.parametrize("fault", ["mixed_batch", "future", "identity_conflict"])
def test_source_faults_stop_plan(fault):
    source = rows()
    if fault=="mixed_batch": source[0].run_id="other"
    elif fault=="future": source[0].collected_at="2027-01-01T00:00:00+00:00"
    else: source.append(deepcopy(source[0]));source[-1].video_id="other-video"
    with pytest.raises(ValueError):plan(source)


def test_new_collection_bound_never_splits_or_silently_expands():
    with pytest.raises(ValueError,match="page cap"):plan(max_pages=3)
    with pytest.raises(ValueError):plan(max_related_tags=7)
    assert plan([])["collection_request"]["keywords"] == ["劳动争议"]
    assert "related_tag_evidence_insufficient" in plan([])["creative_handoff_blockers"]


def test_saved_plan_roundtrip_is_revalidated_before_browser():
    import json
    from src.trend_intelligence.collection.legal_core import request_from_legal_core_plan
    output=json.loads(json.dumps(plan()))
    request=request_from_legal_core_plan(output,profile(),headless=True)
    assert request.keywords==["劳动争议",*output["related_tags"]] and request.web_crawler_enabled
    output["collection_request"]["keywords"].append("明星八卦")
    with pytest.raises(ValueError,match="changed"):
        request_from_legal_core_plan(output,profile())


def test_account_strategy_change_closes_saved_plan():
    from src.trend_intelligence.collection.legal_core import request_from_legal_core_plan
    changed=profile();changed.profile_version=2
    with pytest.raises(ValueError,match="changed account"):
        request_from_legal_core_plan(plan(),changed)


def test_creator_brand_tags_are_not_selected_as_legal_issues():
    source=rows()
    for r in source:r.hashtags.append("南京劳动法律师")
    output=plan(source)
    assert "南京劳动法律师" not in output["related_tags"]
    row=next(c for c in output["candidates"] if c["tag"]=="南京劳动法律师")
    assert "creator_or_location_brand_tag" in row["rejection_reasons"]


def test_shared_browser_gate_distinguishes_brand_and_issue_tags():
    from src.trend_intelligence.providers.base import related_tag_selection_options
    request=TrendCollectionRequest(["法律"],related_tag_domain="legal_services",related_tag_filter_terms=("律师","工资"))
    check=related_tag_selection_options(request)["candidate_filter"]
    assert check("拖欠工资") and check("律师费")
    assert not check("南京劳动法律师")


@pytest.mark.parametrize("extra", [["--keywords","无关热点"], ["--generate-script-pair"],
    ["--acquire-source-media"], ["--resume-collection-run","old"], ["--expand-related-tags"]])
def test_core_research_mode_refuses_mixed_or_paid_stages_before_runtime(extra, monkeypatch):
    from scripts import run_account_video_research as cli
    def never_runtime(*args,**kwargs):raise AssertionError("runtime must not open")
    monkeypatch.setattr(cli,"AccountRuntimeService",never_runtime)
    with pytest.raises(ValueError,match="法律核心计划"):
        cli.main(["--account-id","offline","--legal-core-plan","missing.json",*extra])


@pytest.mark.parametrize("status,reason,expected_exit", [
    ("failed", "human_required", 1), ("completed", "", 0),
])
def test_core_cli_persists_binding_on_success_or_human_block_without_redispatch(
        tmp_path, monkeypatch, status, reason, expected_exit):
    import hashlib
    import json
    from types import SimpleNamespace
    from scripts import run_account_video_research as cli
    from src.trend_intelligence.research_workflow import AccountVideoResearchResult

    source = tmp_path / "plan.json"
    source.write_text(json.dumps(plan(), ensure_ascii=False), encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    log = tmp_path / "research.json"
    calls = []
    result = AccountVideoResearchResult(
        workflow_run_id="research:offline", account_uuid=profile().account_uuid,
        account_key=profile().account_key, profile_version=profile().profile_version,
        status=status, stopped_reason=reason, log_path=str(log),
    )

    class FakeWorkflow:
        def run(self, actual_profile, provider, request, **kwargs):
            calls.append((actual_profile, request, kwargs))
            log.write_text(json.dumps(asdict(result)), encoding="utf-8")
            return result

    monkeypatch.setattr(cli, "AccountRuntimeService", lambda: SimpleNamespace(
        resolve=lambda account_key: SimpleNamespace(profile=profile())))
    monkeypatch.setattr(cli, "DouyinWebTrendProvider", SimpleNamespace(
        for_account=lambda account_key: object()))
    monkeypatch.setattr(cli, "TrendRepository", lambda: object())
    monkeypatch.setattr(cli, "AccountVideoResearchWorkflow", lambda repository: FakeWorkflow())

    assert cli.main(["--account-id", profile().account_key,
                     "--legal-core-plan", str(source), "--headless"]) == expected_exit
    saved = json.loads(log.read_text(encoding="utf-8"))
    binding = saved["legal_core_plan"]
    assert saved["status"] == status and saved["stopped_reason"] == reason
    assert binding["file_sha256"] == source_hash
    assert binding["plan_id"] == plan()["plan_id"]
    assert binding["metadata_only"] is True
    assert binding["script_generation_submitted"] is False
    assert len(calls) == 1 and not calls[0][1].expand_related_tags
    assert calls[0][2]["content_analysis_implementation"] == "metadata_heuristic"
    assert calls[0][2]["run_local_toolchain"] is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
