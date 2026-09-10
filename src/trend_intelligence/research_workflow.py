"""Account-scoped video research workflow with an auditable stage log."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.operations_accounts import AccountProfile

from .content_analysis import ContentAnalysisBatchService, ContentAnalysisRequest
from .opportunity import ContentOpportunityService
from .providers.base import (
    TrendCollectionRequest,
    TrendCollectionResult,
    TrendProvider,
)
from .repository import TrendRepository
from .service import TrendOperationsService
from .source_policy import SourcePolicy
from .sample_gate import require_sample, SampleGateError, primary_tag, batch_observations
from .media_evidence import batch_media_readiness


DEFAULT_RUN_LOG_DIR = Path("data/trend_research_runs")


@dataclass(slots=True)
class ResearchStageResult:
    stage: str
    implementation_id: str
    status: str
    item_count: int = 0
    message: str = ""


@dataclass(slots=True)
class AccountVideoResearchResult:
    workflow_run_id: str
    account_uuid: str
    account_key: str
    profile_version: int
    status: str = "running"
    started_at: str = ""
    finished_at: str = ""
    collection_run_id: str = ""
    collected_observations: int = 0
    unique_videos: int = 0
    tag_relations: int = 0
    tag_traffic_snapshots: int = 0
    clusters: int = 0
    briefs: int = 0
    content_analyses: int = 0
    opportunities: int = 0
    stopped_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    stages: list[ResearchStageResult] = field(default_factory=list)
    log_path: str = ""
    video_records: list[dict[str, object]] = field(default_factory=list)
    sample_gate: dict[str, object] = field(default_factory=dict)
    metric_confirmations: list[dict] = field(default_factory=list)
    media_readiness: dict[str, object] = field(default_factory=dict)
    local_media_manifest: dict[str, object] = field(default_factory=dict)
    local_media_template_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AccountVideoResearchWorkflow:
    """Run collection, content understanding and opportunity ranking as one unit."""

    def __init__(
        self,
        repository: TrendRepository | None = None,
        *,
        log_dir: str | Path = DEFAULT_RUN_LOG_DIR,
    ) -> None:
        self.repository = repository or TrendRepository()
        self.operations = TrendOperationsService(repository=self.repository)
        self.log_dir = Path(log_dir)

    def run(
        self,
        profile: AccountProfile,
        provider: TrendProvider,
        request: TrendCollectionRequest,
        *,
        policy: SourcePolicy,
        content_analysis_implementation: str = "metadata_heuristic",
        max_content_candidates: int = 50,
        resume_collection_run_id: str = "",
        local_media_manifest: str | Path | dict | None = None,
        run_local_toolchain: bool = False,
    ) -> AccountVideoResearchResult:
        started_at = _utc_now()
        result = AccountVideoResearchResult(
            workflow_run_id=f"research:{uuid.uuid4().hex}",
            account_uuid=profile.account_uuid,
            account_key=profile.account_key,
            profile_version=profile.profile_version,
            started_at=started_at,
        )
        safe_candidate_limit = max(1, min(int(max_content_candidates), 200))

        try:
            if resume_collection_run_id:
                rows = batch_observations(self.repository, account_uuid=profile.account_uuid,
                                          run_id=resume_collection_run_id)
                if not rows:
                    raise ValueError('指定批次不存在或不属于该账号')
                collection_run_id = resume_collection_run_id
                collection = TrendCollectionResult(observations=rows, policy_code='allowed')
            else:
                collection_run_id, collection = self.operations.collect(
                    provider, request, policy=policy, account_profile=profile)
            self._record_collection(result, collection_run_id, collection, provider)
            if resume_collection_run_id:
                result.stages[-1].status = 'reused'
                result.stages[-1].message = '继续已保存批次；原始采集时间保持不变，未重新打开采集浏览器。'
            result.metric_confirmations = self.repository.list_metric_confirmations(
                run_id=collection_run_id or '', account_uuid=profile.account_uuid)
            if collection.policy_code != "allowed":
                result.status = "blocked"
                result.stopped_reason = collection.policy_code
                return self._finish(result)

            candidates = _unique_video_candidates(collection)
            candidates = select_manifest_candidates(local_media_manifest, candidates,
                collection_run_id=collection_run_id, account_uuid=profile.account_uuid,
                max_candidates=safe_candidate_limit)
            result.unique_videos = len(candidates)
            result.video_records = [
                {
                    "item_id": item.item_id,
                    "video_id": item.video_id,
                    "run_id": item.run_id,
                    "primary_tag": primary_tag(item),
                    "collected_at": item.collected_at,
                    "title": item.title,
                    "author": item.author,
                    "hashtags": list(item.hashtags),
                    "duration_seconds": item.duration_seconds,
                    "associated_keywords": list(
                        dict.fromkeys(
                            [item.keyword, *item.root_keywords, *item.relevance_terms]
                        )
                    ),
                    "relevance_score": item.relevance_score,
                    "visible_metric": item.metric_value,
                    "visible_metric_text": item.metric_text,
                    "visible_metric_kind": item.metric_kind,
                    "source_sort": item.sort_key,
                    "published_at": item.published_at,
                    "url": item.url,
                }
                for item in candidates
            ]
            if not collection_run_id or not candidates:
                result.status = "failed"
                result.stopped_reason = collection.stopped_reason or "no_valid_videos"
                result.stages.append(
                    ResearchStageResult(
                        stage="content_validation",
                        implementation_id="distinct_video_gate",
                        status="failed",
                        message="未获得包含真实 video_id 的不同视频，后续分析已停止。",
                    )
                )
                return self._finish(result)

            # Validate the actual analysis subset before any topic or content work.
            candidates = candidates[:safe_candidate_limit]
            result.sample_gate = require_sample(candidates).to_dict()
            result.stages.append(
                ResearchStageResult(
                    stage="content_validation",
                    implementation_id="research_sample_gate",
                    status="succeeded",
                    item_count=len(candidates),
                    message="同批次视频数、主要标签和单一口径指标均达到分析门槛。",
                )
            )
            template_path = self.log_dir / f"local_media_{result.workflow_run_id.replace(':', '_')}.json"
            result.local_media_template_path = str(write_local_media_manifest_template(
                template_path, collection_run_id=collection_run_id,
                account_uuid=profile.account_uuid, candidates=candidates))
            media_mapping = load_local_media_manifest(
                local_media_manifest,
                collection_run_id=collection_run_id,
                account_uuid=profile.account_uuid,
                candidates=candidates,
            )
            if media_mapping and content_analysis_implementation != "local_qwen_paraformer":
                raise ValueError("本地媒体清单须配合 local_qwen_paraformer 内容分析实现")
            result.local_media_manifest = {
                "collection_run_id": collection_run_id,
                "account_uuid": profile.account_uuid,
                "items": list(media_mapping.values()),
            } if local_media_manifest is not None else {}

            clusters, briefs = self.operations.analyze(
                preferred_topics=request.keywords,
                account_profile=profile,
                limit=100_000,
                collection_run_id=collection_run_id,
            )
            result.clusters = len(clusters)
            result.briefs = len(briefs)
            result.stages.append(
                ResearchStageResult(
                    stage="topic_analysis",
                    implementation_id="account_scoped_rules",
                    status="succeeded" if clusters else "partial",
                    item_count=len(clusters),
                    message=f"生成 {len(briefs)} 张账号选题卡。",
                )
            )

            analysis_requests = [
                ContentAnalysisRequest(
                    item_id=item.item_id,
                    video_id=item.video_id,
                    title=item.title,
                    author=item.author,
                    hashtags=item.hashtags,
                    raw_text=item.raw_text,
                    duration_seconds=item.duration_seconds,
                    account_profile=profile,
                    media_access_mode=("local_media_authorized"
                        if content_analysis_implementation == "local_qwen_paraformer"
                        else "metadata_only"),
                    local_video_path=str(media_mapping.get(item.item_id, {}).get("video", "")),
                    qwen_analysis_path=str(media_mapping.get(item.item_id, {}).get("qwen", "")),
                    transcript_path=str(media_mapping.get(item.item_id, {}).get("transcript", "")),
                    scene_alignment_path=str(media_mapping.get(item.item_id, {}).get("scenes", "")),
                )
                for item in candidates[:safe_candidate_limit]
            ]
            content_batch = ContentAnalysisBatchService(self.repository).analyze(
                analysis_requests,
                implementation_id=content_analysis_implementation,
                allow_metadata_fallback=False,
                run_local_toolchain=run_local_toolchain,
                collection_run_id=collection_run_id,
            )
            result.content_analyses = len(content_batch.analyses)
            result.warnings.extend(content_batch.errors)
            result.media_readiness = cohort_media_readiness(content_batch.analyses, candidates)
            result.stages.append(
                ResearchStageResult(
                    stage="content_analysis",
                    implementation_id=content_analysis_implementation,
                    status=(
                        "succeeded" if result.media_readiness["ready"] else "awaiting_media_analysis"
                    ),
                    item_count=len(content_batch.analyses),
                    message=(
                        f"音画表达证据齐全 {result.media_readiness['ready_count']}/{len(candidates)}，"
                        f"仅元数据或证据不足 {len(candidates) - result.media_readiness['ready_count']}，"
                        f"失败 {content_batch.failed_count}。"
                    ),
                )
            )

            opportunities = ContentOpportunityService(
                self.repository
            ).build_opportunities(profile, collection_run_id=collection_run_id)
            result.opportunities = len(opportunities)
            result.stages.append(
                ResearchStageResult(
                    stage="opportunity_ranking",
                    implementation_id="explainable_rules",
                    status="succeeded" if opportunities else "partial",
                    item_count=len(opportunities),
                    message="机会分包含流量、时间、相关度、内容证据和风险分项。",
                )
            )
            result.status = (
                "completed"
                if opportunities and result.media_readiness["ready"]
                else "awaiting_media_analysis"
            )
            if not result.media_readiness["ready"]:
                result.stopped_reason = "incomplete_source_media_analysis"
                result.warnings.append("采集与筛选已保存；原视频音画表达分析不足，不能进入剧本生成。")
        except SampleGateError as exc:
            result.status = "blocked"
            result.stopped_reason = "insufficient_research_sample"
            result.sample_gate = exc.result.to_dict()
            result.warnings.append(str(exc))
            result.stages.append(ResearchStageResult(
                stage="content_validation", implementation_id="research_sample_gate",
                status="blocked", item_count=exc.result.unique_videos, message=str(exc)))
        except Exception as exc:
            result.status = "failed"
            result.stopped_reason = f"{type(exc).__name__}: {exc}"
            result.warnings.append(result.stopped_reason)
            result.stages.append(
                ResearchStageResult(
                    stage="workflow",
                    implementation_id="account_video_research_v1",
                    status="failed",
                    message=result.stopped_reason,
                )
            )
        return self._finish(result)

    @staticmethod
    def _record_collection(
        result: AccountVideoResearchResult,
        collection_run_id: str | None,
        collection: TrendCollectionResult,
        provider: TrendProvider,
    ) -> None:
        result.collection_run_id = collection_run_id or ""
        result.collected_observations = len(collection.observations)
        result.tag_relations = len(collection.tag_relations)
        result.tag_traffic_snapshots = len(collection.tag_traffic_snapshots)
        result.warnings.extend(collection.warnings)
        result.stages.append(
            ResearchStageResult(
                stage="trend_collection",
                implementation_id=provider.provider_id,
                status=(
                    "succeeded"
                    if collection_run_id and collection.observations
                    else "blocked"
                    if collection.policy_code != "allowed"
                    else "failed"
                ),
                item_count=len(collection.observations),
                message=collection.stopped_reason or collection.policy_code,
            )
        )

    def _finish(
        self, result: AccountVideoResearchResult
    ) -> AccountVideoResearchResult:
        result.finished_at = _utc_now()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_id = result.workflow_run_id.replace(":", "_")
        log_path = self.log_dir / f"{safe_id}.json"
        result.log_path = str(log_path)
        log_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result


def _unique_video_candidates(
    collection: TrendCollectionResult,
):
    candidates = {}
    for item in collection.observations:
        if not item.video_id or f"/video/{item.video_id}" not in item.url:
            continue
        current = candidates.get(item.video_id)
        if current is None or (item.metric_value or 0, -item.rank) > (
            current.metric_value or 0,
            -current.rank,
        ):
            candidates[item.video_id] = item
    return sorted(
        candidates.values(),
        key=lambda item: (-(item.metric_value or 0), item.rank, item.video_id),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def select_manifest_candidates(value, candidates, *, collection_run_id, account_uuid, max_candidates):
    """Honor an acquisition's explicit source set before the sample/media gates."""
    if value is None:
        return candidates
    payload = (json.loads(Path(value).read_text(encoding="utf-8-sig"))
        if isinstance(value, (str, Path)) else value)
    if not isinstance(payload, dict) or "selection" not in payload:
        return candidates  # Legacy/manual partial manifests keep their original batch scope.
    if (payload.get("schema") != "research_local_media/v1"
            or payload.get("account_uuid") != account_uuid
            or payload.get("collection_run_id") != collection_run_id):
        raise ValueError("原片清单选集与账号或采集批次不匹配")
    selection = payload["selection"]
    if not isinstance(selection, list) or not selection or len(selection) > max_candidates:
        raise ValueError("原片清单选集为空或超过本次候选上限")
    known = {(item.item_id, item.video_id): item for item in candidates}
    selected, seen = [], set()
    for row in selection:
        key = (row.get("item_id"), row.get("video_id")) if isinstance(row, dict) else (None, None)
        if key not in known or key in seen:
            raise ValueError("原片清单选集包含重复来源或不属于本批的视频")
        seen.add(key)
        selected.append(known[key])
    return selected


def load_local_media_manifest(
    value: str | Path | dict | None, *, collection_run_id: str,
    account_uuid: str, candidates,
) -> dict[str, dict]:
    """Bind explicitly supplied local files to this account and collection cohort."""
    if value is None:
        return {}
    base_dir = Path.cwd()
    if isinstance(value, (str, Path)):
        manifest_path = Path(value).resolve(strict=True)
        base_dir = manifest_path.parent
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    else:
        payload = value
    if not isinstance(payload, dict) or payload.get("schema") != "research_local_media/v1":
        raise ValueError("本地媒体清单须使用 research_local_media/v1 格式")
    if payload.get("collection_run_id") != collection_run_id or payload.get("account_uuid") != account_uuid:
        raise ValueError("本地媒体清单账号或采集批次不匹配")
    entries = payload.get("items")
    if not isinstance(entries, list):
        raise ValueError("本地媒体清单 items 必须为数组")
    identities = {(item.item_id, item.video_id) for item in candidates}
    mapping = {}
    video_paths = set()
    for entry in entries:
        if not isinstance(entry, dict) or (entry.get("item_id"), entry.get("video_id")) not in identities:
            raise ValueError("本地媒体清单包含不属于本批候选的视频")
        item_id = entry["item_id"]
        if item_id in mapping:
            raise ValueError("本地媒体清单包含重复 item_id")
        row = {"item_id": item_id, "video_id": entry["video_id"]}
        if not entry.get("video"):
            raise ValueError("每条本地媒体清单必须绑定原视频 video 路径")
        for name in ("video", "qwen", "transcript", "scenes"):
            if entry.get(name):
                raw = str(entry[name])
                if "://" in raw:
                    raise ValueError("本地媒体清单不能使用远程 URL")
                path = Path(raw)
                path = (base_dir / path).resolve(strict=True) if not path.is_absolute() else path.resolve(strict=True)
                if not path.is_file():
                    raise ValueError(f"本地媒体产物不是文件：{name}")
                if name == "video":
                    if path in video_paths:
                        raise ValueError("不同来源不能重复绑定同一个原视频文件")
                    video_paths.add(path)
                row[name] = str(path)
        if entry.get("acquisition_receipt"):
            from .media_evidence import file_sha256
            receipt_path = Path(str(entry["acquisition_receipt"]))
            receipt_path = (base_dir / receipt_path).resolve(strict=True) if not receipt_path.is_absolute() else receipt_path.resolve(strict=True)
            if file_sha256(receipt_path) != entry.get("acquisition_receipt_sha256"):
                raise ValueError("原片获取回执已变化，不能继续分析")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            digest = file_sha256(row["video"])
            if (receipt.get("schema") != "source_media_receipt/v1"
                    or receipt.get("account_uuid") != account_uuid
                    or receipt.get("collection_run_id") != collection_run_id
                    or receipt.get("item_id") != item_id or receipt.get("video_id") != entry["video_id"]
                    or receipt.get("identity_confirmed") is not True
                    or receipt.get("source_video_sha256") != digest
                    or entry.get("source_video_sha256") != digest
                    or Path(str(receipt.get("video") or "")).resolve() != Path(row["video"])):
                raise ValueError("原片获取回执与账号、批次、来源身份或视频文件不一致")
            row.update(acquisition_receipt=str(receipt_path),
                acquisition_receipt_sha256=entry["acquisition_receipt_sha256"], source_video_sha256=digest)
        mapping[item_id] = row
    return mapping


def write_local_media_manifest_template(path, *, collection_run_id, account_uuid, candidates) -> Path:
    """Export source identities with deliberately empty paths; no guessed media."""
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "research_local_media/v1", "collection_run_id": collection_run_id,
        "account_uuid": account_uuid,
        "instructions": "仅填写该来源的原视频本地路径；生成片或其他来源不能代替。缺失项保留为空，须补齐后再分析。",
        "media_acquisition": {"status": "awaiting_authorized_local_sources",
            "provider_extension": "授权来源获取器输出同一 collection_run_id/account_uuid/item_id/video_id 对应的原视频本地路径；随后由本地分析器记录 SHA-256、时长和音画证据。"},
        "items": [{"item_id": item.item_id, "video_id": item.video_id,
            "source_url": item.url, "title": item.title, "video": ""} for item in candidates]}
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def cohort_media_readiness(analyses, candidates, *, verify_artifacts=True) -> dict:
    """Count the selected cohort, including videos with no analysis result."""
    identities = {(item.item_id, item.video_id) for item in candidates}
    latest = {}
    for analysis in analyses:
        identity = (analysis.item_id, analysis.video_id)
        if identity in identities:
            latest.setdefault(identity, analysis)
    report = batch_media_readiness(list(latest.values()),
        required_count=max(20, len(identities)), verify_artifacts=verify_artifacts)
    absent = identities - set(latest)
    report["missing"] = list(report.get("missing", [])) + [
        {"item_id": item_id, "video_id": video_id, "reasons": ["尚无原视频音画表达分析"]}
        for item_id, video_id in sorted(absent)
    ]
    report["required_count"] = max(20, len(identities))
    report["ready"] = bool(report["ready"] and not absent and report["ready_count"] == len(identities))
    report["message"] = f"原视频音画表达分析 {report['ready_count']}/{report['required_count']}；不足时停在待分析，不调用编剧。"
    return report
