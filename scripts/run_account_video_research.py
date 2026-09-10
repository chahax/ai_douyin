"""Run the account-scoped Douyin collection and analysis workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.operations_accounts import AccountRuntimeService, AccountProfileRepository
from src.trend_intelligence.providers import (
    DouyinWebTrendProvider,
    TrendCollectionRequest,
    estimate_douyin_planned_pages,
)
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.research_workflow import AccountVideoResearchWorkflow
from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourceProvider,
)
from scripts.acquire_source_media import DEFAULT_AUTHORIZATION_REFERENCE, acquire_for_saved_run, run_cli_acquisition


COLLECTED_FIELDS = frozenset(
    {
        "video_id",
        "url",
        "title",
        "author",
        "keyword",
        "sort",
        "rank",
        "displayed_metrics",
        "published_at",
        "hashtags",
        "duration_seconds",
        "tag_relationships",
        "tag_traffic_snapshots",
    }
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--keywords", default="", help="逗号分隔关键词；续用已保存批次时可省略")
    parser.add_argument(
        "--sorts",
        default="comprehensive,most_liked,latest",
        help="comprehensive,most_liked,latest 的逗号分隔子集",
    )
    parser.add_argument("--limit-per-sort", type=int, default=10)
    parser.add_argument("--max-content-candidates", type=int, default=50)
    parser.add_argument("--content-analysis-implementation", choices=("metadata_heuristic", "local_qwen_paraformer"),
        default=None, help="默认只筛选元数据；提供 local-media-manifest 时默认使用本地音画分析")
    parser.add_argument("--local-media-manifest", default="", help="research_local_media/v1 本地原视频清单；自动复用清单绑定的采集批次")
    parser.add_argument("--acquire-source-media", action="store_true", help="在同一浏览器会话逐条获取所选批次原视频；缓存续用，验证或身份不明时停止")
    parser.add_argument("--max-source-media-items", type=int, default=20, help="本次最多新访问的来源数；已获取缓存不重复下载")
    parser.add_argument("--source-media-output-root", default="", help="可选原视频获取缓存目录")
    parser.add_argument("--no-hold-browser", action="store_true", help="非交互集成：原片获取遇验证时关闭本次浏览器并退出")
    parser.add_argument("--run-local-toolchain", action="store_true", help="执行本地抽帧、Qwen 视觉理解和 Paraformer 转写；只读取显式绑定的本地原视频")
    parser.add_argument("--authorization-reference", default=DEFAULT_AUTHORIZATION_REFERENCE,
                        help="默认沿用用户对本项目来源内容分析的既有授权")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--resume-collection-run", default="", help="继续指定已保存批次的分析和编剧，保留采集时间")
    parser.add_argument("--editor-feedback-file", default="", help="实际读稿后的修改意见文件，由模型据此重写")
    parser.add_argument("--resume-draft", default="", help="继续校验并审阅相同输入下已保存的模型草稿，避免重复编写")
    parser.add_argument("--baseline-draft", default="", help="以项目保存的完整双剧本为基线，在新证据下定点修订；需提供 revision-feedback-file")
    parser.add_argument("--revision-feedback-file", default="", help="对 --resume-draft 的新增读稿意见，交回模型定点修订")
    parser.add_argument("--resume-revision", default="", help="续用与保存草稿严格匹配的真实模型修订文件，并重新完整审稿")
    parser.add_argument("--wait-for-verification", type=int, default=0, help="在同一采集窗口等待人工验证的秒数，最多 600 秒")
    parser.add_argument("--expand-related-tags", action="store_true")
    parser.add_argument("--generate-script-pair", action="store_true", help="达标后生成短版和长版剧本，停在生成视频前")
    parser.add_argument("--script-reference-source-id", action="append", default=[],
                        help="可重复：仅向编剧展开指定来源原证据，保留完整20源门禁、概览与高值对照")
    parser.add_argument("--staged-screenplay-bundle", default="",
                        help="核验已审故事与摄影工件后仅作最终双稿复核；失败退回原阶段，不自动改写")
    parser.add_argument("--short-seconds", type=int, default=45)
    parser.add_argument("--long-seconds", type=int, default=180)
    parser.add_argument("--continuous-short", action="store_true", help="短版固定双人机位，严格承接相邻首尾状态，每段4—15秒")
    parser.add_argument("--review-only", action="store_true", help="只读复核相同输入的 resume-draft，失败不调用编剧重写")
    args = parser.parse_args(argv)
    if args.staged_screenplay_bundle:
        if not args.generate_script_pair:
            parser.error('--staged-screenplay-bundle 须与 --generate-script-pair 同用')
        if any((args.resume_draft, args.baseline_draft, args.revision_feedback_file, args.resume_revision)):
            parser.error('--staged-screenplay-bundle 不能混用 baseline/resume/revision 参数')
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.acquire_source_media and not 1 <= args.max_source_media_items <= 200:
        raise ValueError("max-source-media-items 必须在 1—200 之间")
    if args.acquire_source_media and args.local_media_manifest:
        raise ValueError("原片自动获取与手填本地媒体清单不可混用；获取器会自动复用该批次缓存")
    if args.acquire_source_media and args.content_analysis_implementation == "metadata_heuristic":
        raise ValueError("获取原片后须使用 local_qwen_paraformer；仅获取探测请运行 acquire_source_media.py")
    if args.local_media_manifest:
        media_header = json.loads(Path(args.local_media_manifest).read_text(encoding="utf-8-sig"))
        bound_run = str(media_header.get("collection_run_id") or "")
        if not bound_run:
            raise ValueError("本地媒体清单缺少 collection_run_id")
        if args.resume_collection_run and args.resume_collection_run != bound_run:
            raise ValueError("命令行续用批次与媒体清单不一致")
        args.resume_collection_run = bound_run
    content_implementation = args.content_analysis_implementation or (
        "local_qwen_paraformer" if args.local_media_manifest or args.acquire_source_media else "metadata_heuristic")
    if args.run_local_toolchain and (not (args.local_media_manifest or args.acquire_source_media) or content_implementation != "local_qwen_paraformer"):
        raise ValueError("执行本地音画工具链须提供原视频清单并选择 local_qwen_paraformer")

    keywords = _split(args.keywords)[:10]
    if not keywords and not args.resume_collection_run:
        raise ValueError("新采集须提供 keywords；已有来源请指定 resume-collection-run")
    sorts = tuple(_split(args.sorts))
    request = TrendCollectionRequest(
        keywords=keywords,
        sorts=sorts,
        limit_per_sort=max(1, min(args.limit_per_sort, 20)),
        headless=args.headless,
        manual_verification_timeout_seconds=args.wait_for_verification,
        web_crawler_enabled=True,
        expand_related_tags=args.expand_related_tags,
    )
    planned_pages = estimate_douyin_planned_pages(request)
    if planned_pages > 30 and not args.resume_collection_run:
        raise ValueError(f"计划页面数 {planned_pages} 超过单次上限 30，请拆批运行。")

    profile = (AccountProfileRepository().get(args.account_id) if args.resume_collection_run
        else AccountRuntimeService().resolve(args.account_id).profile)
    provider = DouyinWebTrendProvider.for_account(args.account_id)
    policy = _build_policy(
        args.authorization_reference,
        planned_pages=planned_pages,
    )
    repository = TrendRepository()
    workflow = AccountVideoResearchWorkflow(repository)
    result = workflow.run(
        profile,
        provider,
        request,
        policy=policy,
        max_content_candidates=args.max_content_candidates,
        resume_collection_run_id=args.resume_collection_run,
        content_analysis_implementation="metadata_heuristic" if args.acquire_source_media else content_implementation,
        local_media_manifest=args.local_media_manifest or None,
        run_local_toolchain=False if args.acquire_source_media else args.run_local_toolchain,
    )
    acquisition_summary = None
    acquisition_blocked = False
    if args.acquire_source_media:
        if result.status in {"completed", "partial", "awaiting_media_analysis"} and result.sample_gate.get('passed'):
            acquired, lifecycle = run_cli_acquisition(lambda holder: acquire_for_saved_run(profile,
                collection_run_id=result.collection_run_id, repository=repository,
                max_content_candidates=args.max_content_candidates, max_items=args.max_source_media_items,
                output_root=args.source_media_output_root or None, headless=args.headless,
                authorization_reference=args.authorization_reference, service_holder=holder),
                no_hold_browser=args.no_hold_browser)
            acquisition_summary = acquired.to_dict()
            acquisition_summary.update(lifecycle)
            acquisition_blocked = acquired.status not in {"completed", "partial"}
            if not acquisition_blocked and acquired.acquired_count + acquired.cached_count > 0:
                result = workflow.run(profile, provider, request, policy=policy,
                    max_content_candidates=args.max_content_candidates,
                    resume_collection_run_id=result.collection_run_id,
                    content_analysis_implementation=content_implementation,
                    local_media_manifest=acquired.manifest_path,
                    run_local_toolchain=args.run_local_toolchain)
        else:
            acquisition_blocked = True
            acquisition_summary = {"status": "blocked_by_research", "stopped_reason": result.stopped_reason}
    payload = asdict(result)
    if acquisition_summary is not None:
        payload['source_media_acquisition'] = acquisition_summary
        payload['video_generation_submitted'] = False
        if acquisition_blocked:
            payload.update(status='awaiting_source_media', script_generation_submitted=False,
                           stopped_reason=acquisition_summary.get('stopped_reason', 'source_media_acquisition_incomplete'))
    if args.generate_script_pair:
        payload['video_generation_submitted'] = False
        payload['script_stage'] = 'blocked_by_research'
        if not acquisition_blocked and result.status in {'completed', 'partial', 'awaiting_media_analysis'} and result.sample_gate.get('passed'):
            from src.trend_intelligence.pre_video_script import PreVideoScriptRequest, PreVideoScriptService
            script_service = PreVideoScriptService()
            payload['research_finished_at'] = result.finished_at
            payload['script_started_at'] = datetime.now(timezone.utc).isoformat()
            payload['script_stage'] = 'running'
            Path(result.log_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            try:
                types = tuple(script_service.recent_video_type_counts(profile.account_key, collection_run_id=result.collection_run_id))
                script_request = PreVideoScriptRequest(
                    account_key=profile.account_key, recent_video_types=types,
                    collection_run_id=result.collection_run_id,
                    script_reference_source_ids=tuple(args.script_reference_source_id),
                    staged_screenplay_bundle_path=args.staged_screenplay_bundle,
                    editor_feedback=Path(args.editor_feedback_file).read_text(encoding='utf-8') if args.editor_feedback_file else '',
                    initial_draft_path=args.resume_draft,
                    baseline_draft_path=args.baseline_draft,
                    continuous_short=args.continuous_short,
                    review_only=args.review_only,
                    revision_feedback=Path(args.revision_feedback_file).read_text(encoding='utf-8') if args.revision_feedback_file else '',
                    initial_revision_path=args.resume_revision,
                    short_seconds=args.short_seconds, long_seconds=args.long_seconds)
                readiness = script_service.source_media_readiness(script_request, verify_artifacts=True)
                payload['selected_source_media_readiness'] = readiness
                if not readiness['ready']:
                    payload.update(script_stage='blocked_by_source_media', script_generation_submitted=False,
                                   script_error=readiness['message'])
                else:
                    pair = script_service.generate(script_request)
                    payload.update(script_stage='completed', short_script_path=pair.short.script_path,
                                   long_script_path=pair.long.script_path, script_pair_manifest=pair.manifest_path,
                                   paused_at='before_video_generation')
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                payload.update(script_stage='failed', script_error=str(exc))
            except KeyboardInterrupt:
                payload.update(script_stage='cancelled', script_error='编剧运行已中止，草稿保留供检查')
            payload['script_finished_at'] = datetime.now(timezone.utc).isoformat()
            payload['finished_at'] = payload['script_finished_at']
        Path(result.log_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    elif acquisition_summary is not None and result.log_path:
        Path(result.log_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.generate_script_pair and payload['script_stage'] != 'completed':
        return 1
    if acquisition_blocked:
        return 1
    return 0 if result.status in {"completed", "partial"} else 1


def _build_policy(reference: str, *, planned_pages: int) -> SourcePolicy:
    reference_hash = "sha256:" + hashlib.sha256(
        reference.strip().encode("utf-8")
    ).hexdigest()
    return SourcePolicy(
        policy_id=(
            "douyin-account-research-"
            f"{datetime.now(timezone.utc).date().isoformat()}"
        ),
        provider=SourceProvider.AUTHORIZED_WEB,
        status=PolicyStatus.APPROVED,
        allowed_hosts=("www.douyin.com",),
        allowed_path_prefixes=("/search",),
        allowed_fields=COLLECTED_FIELDS,
        allowed_purposes=frozenset({"trend_analysis"}),
        min_interval_seconds=1,
        max_pages_per_run=max(1, min(30, planned_pages)),
        daily_page_cap=90,
        raw_retention_days=0,
        authorization_reference_hash=reference_hash,
    )


def _split(value: str) -> list[str]:
    output: list[str] = []
    for item in value.replace("，", ",").split(","):
        item = item.strip()
        if item and item not in output:
            output.append(item)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
