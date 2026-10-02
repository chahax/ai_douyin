from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import json

import pytest

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.trend_intelligence.analysis import stable_item_id
from src.trend_intelligence.models import TrendObservation
from src.trend_intelligence.providers.base import (
    TrendCollectionRequest,
    TrendCollectionResult,
)
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.research_workflow import (
    AccountVideoResearchWorkflow, load_local_media_manifest, cohort_media_readiness,
)
from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourceProvider,
)


def _profile(key: str = "legal_account") -> AccountProfile:
    return AccountProfile(
        account_uuid=stable_account_uuid(key),
        account_key=key,
        display_name="法律号",
        domain_strategy_id="legal_services",
        seed_keywords=["法律", "婚姻"],
        service_scope=["婚姻家事"],
        target_audiences=["有法律咨询需求的普通用户"],
        workflow_profile="legal_presenter",
        domain_config={"practice_areas": ["婚姻家事"]},
    )


def _observation(video_id: str = "7531234567890123456") -> TrendObservation:
    now = datetime.now(timezone.utc).isoformat()
    return TrendObservation(
        item_id=stable_item_id(video_id=video_id),
        video_id=video_id,
        url=f"https://www.douyin.com/video/{video_id}",
        title="夫妻共同债务如何认定 #法律科普",
        author="@律师",
        keyword="法律",
        sort_key="most_liked",
        sort_label="最多点赞",
        rank=1,
        metric_text="8.8万",
        metric_value=88_000,
        collected_at=now,
        hashtags=["法律科普", "夫妻共同债务"],
    )


def _policy() -> SourcePolicy:
    return SourcePolicy(
        policy_id="test-research",
        provider=SourceProvider.MANUAL_IMPORT,
        status=PolicyStatus.APPROVED,
        max_pages_per_run=10,
        daily_page_cap=10,
    )


class FakeProvider:
    provider_id = "fake_provider"

    def __init__(self, observations: list[TrendObservation]):
        self.observations = observations

    def collect(self, request, *, policy):
        return TrendCollectionResult(observations=self.observations)


def test_account_video_research_workflow_runs_all_stages(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    workflow = AccountVideoResearchWorkflow(
        repository,
        log_dir=tmp_path / "logs",
    )

    result = workflow.run(
        _profile(),
        FakeProvider([replace(_observation(str(7531234567890123456 + i)), keyword=("法律" if i % 2 else "婚姻"), metric_kind="views") for i in range(20)]),
        TrendCollectionRequest(keywords=["法律"]),
        policy=_policy(),
    )

    assert result.status == "awaiting_media_analysis"
    assert result.stopped_reason == "incomplete_source_media_analysis"
    assert result.media_readiness["ready"] is False
    assert result.media_readiness["ready_count"] == 0
    assert result.media_readiness["required_count"] == 20
    assert result.unique_videos == 20
    assert result.content_analyses == 20
    assert result.opportunities >= 1
    assert {stage.stage for stage in result.stages} >= {
        "trend_collection",
        "content_validation",
        "topic_analysis",
        "content_analysis",
        "opportunity_ranking",
    }
    assert Path(result.log_path).is_file()


def test_account_video_research_workflow_rejects_non_video_page(tmp_path) -> None:
    invalid = _observation()
    invalid.video_id = ""
    invalid.url = "https://www.douyin.com/search/%E6%B3%95%E5%BE%8B?type=video"
    repository = TrendRepository(tmp_path / "trend.db")
    result = AccountVideoResearchWorkflow(
        repository,
        log_dir=tmp_path / "logs",
    ).run(
        _profile(),
        FakeProvider([invalid]),
        TrendCollectionRequest(keywords=["法律"]),
        policy=_policy(),
    )

    assert result.status == "failed"
    assert result.unique_videos == 0
    assert result.stopped_reason == "no_valid_videos"
    assert result.stages[-1].implementation_id == "distinct_video_gate"


def test_workflow_blocks_small_sample_before_analysis(tmp_path):
    repository = TrendRepository(tmp_path / "trend.db")
    result = AccountVideoResearchWorkflow(repository, log_dir=tmp_path / "logs").run(
        _profile(), FakeProvider([_observation()]),
        TrendCollectionRequest(keywords=["法律"]), policy=_policy())
    assert result.status == "blocked"
    assert result.sample_gate["passed"] is False
    assert result.clusters == result.content_analyses == result.opportunities == 0
    assert repository.list_content_analyses() == []
    assert "topic_analysis" not in {stage.stage for stage in result.stages}


def test_resume_saved_batch_does_not_recollect(tmp_path):
    from unittest.mock import Mock
    repository = TrendRepository(tmp_path / 'trend.db')
    run = repository.save_collection([_observation()], provider='fixture', keywords=['法律'],
                                      account_uuid=_profile().account_uuid)
    provider = Mock(provider_id='fixture')
    result = AccountVideoResearchWorkflow(repository, log_dir=tmp_path / 'logs').run(
        _profile(), provider, TrendCollectionRequest(keywords=['法律']), policy=_policy(),
        resume_collection_run_id=run)
    provider.collect.assert_not_called()
    assert result.collection_run_id == run
    assert result.stages[0].status == 'reused'
    assert result.status == 'blocked'  # Reuse still enforces the sample gate.


def test_local_media_manifest_binds_account_batch_identity_and_local_file(tmp_path):
    candidate = _observation()
    media = tmp_path / "source.mp4"
    media.write_bytes(b"fixture")
    manifest = {"schema": "research_local_media/v1", "collection_run_id": "batch-1",
        "account_uuid": _profile().account_uuid,
        "items": [{"item_id": candidate.item_id, "video_id": candidate.video_id,
                   "video": "source.mp4"}]}
    manifest_path = tmp_path / "media.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = load_local_media_manifest(manifest_path, collection_run_id="batch-1",
        account_uuid=_profile().account_uuid, candidates=[candidate])
    assert result[candidate.item_id]["video"] == str(media.resolve())
    with pytest.raises(ValueError, match="账号或采集批次"):
        load_local_media_manifest(manifest_path, collection_run_id="batch-2",
            account_uuid=_profile().account_uuid, candidates=[candidate])
    manifest["items"][0]["video_id"] = "wrong-video"
    with pytest.raises(ValueError, match="不属于本批"):
        load_local_media_manifest(manifest, collection_run_id="batch-1",
            account_uuid=_profile().account_uuid, candidates=[candidate])
    manifest["items"][0]["video_id"] = candidate.video_id
    manifest["items"][0]["video"] = "https://example.com/video.mp4"
    with pytest.raises(ValueError, match="远程 URL"):
        load_local_media_manifest(manifest, collection_run_id="batch-1",
            account_uuid=_profile().account_uuid, candidates=[candidate])
    second = _observation("7531234567890123457")
    manifest["items"] = [{"item_id": row.item_id, "video_id": row.video_id, "video": str(media)}
        for row in (candidate, second)]
    with pytest.raises(ValueError, match="重复绑定"):
        load_local_media_manifest(manifest, collection_run_id="batch-1",
            account_uuid=_profile().account_uuid, candidates=[candidate, second])


def test_cohort_media_readiness_counts_missing_results(tmp_path):
    candidates = [_observation(str(7531234567890123456 + i)) for i in range(25)]
    report = cohort_media_readiness([], candidates)
    assert report["ready"] is False
    assert report["ready_count"] == 0
    assert report["required_count"] == 25
    assert len(report["missing"]) == 25


def test_acquisition_selection_limits_analysis_to_its_actual_sources():
    from src.trend_intelligence.research_workflow import select_manifest_candidates
    rows=[_observation(str(7531234567890123456+i)) for i in range(50)]
    payload={'schema':'research_local_media/v1','account_uuid':_profile().account_uuid,
        'collection_run_id':'batch-1','items':[],
        'selection':[{'item_id':r.item_id,'video_id':r.video_id} for r in rows[10:30]]}
    selected=select_manifest_candidates(payload,rows,collection_run_id='batch-1',
        account_uuid=_profile().account_uuid,max_candidates=50)
    assert selected==rows[10:30]  # Pending downloads remain in the selected 20, not the unselected 30.
    with pytest.raises(ValueError,match='账号或采集批次'):
        select_manifest_candidates(payload,rows,collection_run_id='other',
            account_uuid=_profile().account_uuid,max_candidates=50)
    payload['selection'].append(payload['selection'][0])
    with pytest.raises(ValueError,match='重复来源'):
        select_manifest_candidates(payload,rows,collection_run_id='batch-1',
            account_uuid=_profile().account_uuid,max_candidates=50)


@pytest.mark.parametrize('corruption',['video','receipt','identity','batch'])
def test_download_receipt_is_verified_before_local_analysis(tmp_path,corruption):
    from src.trend_intelligence.media_evidence import file_sha256
    source=_observation()
    video=tmp_path/'source.mp4'
    video.write_bytes(b'original_source_fixture')
    receipt_path=tmp_path/'receipt.json'
    receipt={'schema':'source_media_receipt/v1','account_uuid':_profile().account_uuid,
        'collection_run_id':'batch-1','item_id':source.item_id,'video_id':source.video_id,
        'identity_confirmed':True,'source_video_sha256':file_sha256(video),'video':str(video.resolve())}
    receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
    entry={'item_id':source.item_id,'video_id':source.video_id,'video':str(video),
        'source_video_sha256':file_sha256(video),'acquisition_receipt':str(receipt_path),
        'acquisition_receipt_sha256':file_sha256(receipt_path)}
    manifest={'schema':'research_local_media/v1','collection_run_id':'batch-1',
        'account_uuid':_profile().account_uuid,'items':[entry]}
    load=lambda:load_local_media_manifest(manifest,collection_run_id='batch-1',
        account_uuid=_profile().account_uuid,candidates=[source])
    assert load()[source.item_id]['acquisition_receipt']==str(receipt_path.resolve())
    if corruption=='video': video.write_bytes(b'different_source')
    elif corruption=='receipt': receipt_path.write_text('{}',encoding='utf-8')
    else:
        receipt['video_id' if corruption=='identity' else 'collection_run_id']='wrong'
        receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
        entry['acquisition_receipt_sha256']=file_sha256(receipt_path)
    with pytest.raises(ValueError,match='获取回执'):
        load()


def test_workflow_passes_explicit_local_media_without_metadata_fallback(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from src.trend_intelligence.models import ContentAnalysisBatchResult
    from src.trend_intelligence.content_analysis import ContentAnalysisBatchService

    profile = _profile()
    observations = [replace(_observation(str(7531234567890123456 + i)),
        keyword=("法律" if i % 2 else "婚姻"), metric_kind="views") for i in range(20)]
    repository = TrendRepository(tmp_path / "trend.db")
    run_id = repository.save_collection(observations, provider="fixture", keywords=["法律", "婚姻"],
        account_uuid=profile.account_uuid)
    media = tmp_path / "source.mp4"
    media.write_bytes(b"fixture")
    first = observations[0]
    manifest = {"schema": "research_local_media/v1", "collection_run_id": run_id,
        "account_uuid": profile.account_uuid,
        "items": [{"item_id": first.item_id, "video_id": first.video_id, "video": str(media)}]}
    batch_call = Mock(return_value=ContentAnalysisBatchResult(batch_id="batch-test",
        implementation_id="local_qwen_paraformer", account_uuid=profile.account_uuid,
        requested_count=20, failed_count=20, completed_count=0, degraded_count=0, cached_count=0))
    monkeypatch.setattr(ContentAnalysisBatchService, "analyze", batch_call)
    provider = Mock(provider_id="fixture")
    result = AccountVideoResearchWorkflow(repository, log_dir=tmp_path / "logs").run(
        profile, provider, TrendCollectionRequest(keywords=["法律"]), policy=_policy(),
        content_analysis_implementation="local_qwen_paraformer", resume_collection_run_id=run_id,
        local_media_manifest=manifest, run_local_toolchain=True)
    provider.collect.assert_not_called()
    assert result.status == "awaiting_media_analysis"
    assert len(result.media_readiness["missing"]) == 20
    requests = batch_call.call_args.args[0]
    assert all(item.media_access_mode == "local_media_authorized" for item in requests)
    assert next(item for item in requests if item.item_id == first.item_id).local_video_path == str(media.resolve())
    assert batch_call.call_args.kwargs["allow_metadata_fallback"] is False
    assert batch_call.call_args.kwargs["run_local_toolchain"] is True
    assert batch_call.call_args.kwargs["collection_run_id"] == run_id
    template = json.loads(Path(result.local_media_template_path).read_text(encoding="utf-8"))
    assert len(template["items"]) == 20
    assert template["collection_run_id"] == run_id
    assert all(not row["video"] for row in template["items"])


def test_cli_resumes_manifest_batch_and_passes_local_toolchain(tmp_path, monkeypatch, capsys):
    from unittest.mock import Mock
    from scripts import run_account_video_research as cli
    from src.trend_intelligence.research_workflow import AccountVideoResearchResult

    profile = _profile()
    manifest = tmp_path / "media.json"
    manifest.write_text(json.dumps({"schema": "research_local_media/v1",
        "collection_run_id": "saved-run", "account_uuid": profile.account_uuid, "items": []}), encoding="utf-8")
    workflow = Mock()
    workflow.run.return_value = AccountVideoResearchResult(workflow_run_id="test",
        account_uuid=profile.account_uuid, account_key=profile.account_key, profile_version=1,
        status="awaiting_media_analysis")
    monkeypatch.setattr(cli, "AccountVideoResearchWorkflow", Mock(return_value=workflow))
    profiles = Mock()
    profiles.get.return_value = profile
    monkeypatch.setattr(cli, "AccountProfileRepository", Mock(return_value=profiles))
    runtime = Mock()
    monkeypatch.setattr(cli, "AccountRuntimeService", runtime)
    monkeypatch.setattr(cli, "TrendRepository", Mock())
    monkeypatch.setattr(cli.sys, "argv", ["research", "--account-id", profile.account_key,
        "--keywords", "法律,婚姻", "--authorization-reference", "本地研究",
        "--local-media-manifest", str(manifest), "--run-local-toolchain"])
    assert cli.main() == 1
    runtime.assert_not_called()
    kwargs = workflow.run.call_args.kwargs
    assert kwargs["resume_collection_run_id"] == "saved-run"
    assert kwargs["content_analysis_implementation"] == "local_qwen_paraformer"
    assert kwargs["local_media_manifest"] == str(manifest)
    assert kwargs["run_local_toolchain"] is True
