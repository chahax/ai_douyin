"""Acquire selected original source videos; never invoke analysis or generation models."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.operations_accounts import AccountProfileRepository
from src.trend_intelligence.providers.base import TrendCollectionResult
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.research_workflow import _unique_video_candidates
from src.trend_intelligence.sample_gate import batch_observations
from src.trend_intelligence.source_policy import PolicyStatus, SourcePolicy, SourceProvider


DEFAULT_AUTHORIZATION_REFERENCE = (
    "本会话用户已要求本项目获取参考原视频、逐条分析音画表达并修复剧本工作流；"
    "仅用于所选账号同批来源内容研究，不发布、不互动、不生成视频。"
)


def build_acquisition_policy(reference: str, *, max_items: int) -> SourcePolicy:
    """Scope source pages and their observed detail request; downloads use an exact derived URL scope."""
    if not reference.strip():
        raise ValueError("来源分析授权记录不能为空")
    return SourcePolicy(
        policy_id=f"douyin-source-media-{datetime.now(timezone.utc).date().isoformat()}",
        provider=SourceProvider.AUTHORIZED_WEB, status=PolicyStatus.APPROVED,
        allowed_hosts=("www.douyin.com",),
        allowed_path_prefixes=("/video", "/aweme/v1/web/aweme/detail"),
        allowed_fields=frozenset({"video_id", "url", "original_video"}),
        allowed_purposes=frozenset({"trend_analysis"}), min_interval_seconds=1,
        max_pages_per_run=max_items, daily_page_cap=200, raw_retention_days=0,
        authorization_reference_hash="sha256:" + hashlib.sha256(reference.strip().encode("utf-8")).hexdigest(),
    )


def acquire_for_saved_run(profile, *, collection_run_id: str, repository=None,
                          max_content_candidates: int = 50, max_items: int = 1,
                          output_root=None, headless: bool = False,
                          authorization_reference: str = DEFAULT_AUTHORIZATION_REFERENCE,
                          session=None, service_factory=None, service=None, service_holder=None):
    """Use exactly the research workflow's account/batch selection, retaining download caches."""
    if not collection_run_id.strip():
        raise ValueError("原片获取必须绑定已保存的 collection_run_id")
    if not 1 <= max_items <= 200 or not 1 <= max_content_candidates <= 200:
        raise ValueError("max_items 与 max_content_candidates 必须在 1—200 之间")
    repository = repository or TrendRepository()
    rows = batch_observations(repository, account_uuid=profile.account_uuid, run_id=collection_run_id)
    if not rows:
        raise ValueError("指定采集批次不存在或不属于该账号")
    candidates = _unique_video_candidates(TrendCollectionResult(observations=rows))[:max_content_candidates]
    if not candidates:
        raise ValueError("该批次没有已筛选且可识别 video_id 的来源")
    service = service or (service_holder or {}).get('service')
    if service is None:
        if service_factory is None:
            from src.trend_intelligence.source_media_acquisition import SourceMediaAcquisitionService
            service_factory = SourceMediaAcquisitionService
        from src.trend_intelligence.providers.douyin_web import build_account_douyin_trend_session
        service = service_factory(output_root=output_root,
            session_factory=lambda: build_account_douyin_trend_session(profile.account_key, headless=headless))
    if service_holder is not None:
        service_holder['service'] = service
    return service.acquire(candidates, account_uuid=profile.account_uuid,
        collection_run_id=collection_run_id,
        policy=build_acquisition_policy(authorization_reference, max_items=max_items),
        session=session, max_items=max_items)


def run_cli_acquisition(acquire_action, *, no_hold_browser=False, input_fn=None, on_pause=None):
    """Keep the parent process/session alive during verification; retry only on explicit resume."""
    read_command = input_fn or input
    emit = on_pause or (lambda payload: print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True))
    holder = {}
    resumes = 0
    exit_reason = 'cli_exit_completed'
    result = None
    try:
        result = acquire_action(holder)
        while result.status == 'human_required':
            if no_hold_browser:
                exit_reason = 'cli_exit_no_hold_browser'
                break
            pause = result.to_dict()
            pause.update(cli_state='paused_waiting_for_user', session_left_open=True,
                instructions='浏览器保持当前验证页面。完成后输入 resume 继续；输入 stop 停止并关闭本次会话。',
                analysis_submitted=False, script_generation_submitted=False, video_generation_submitted=False)
            emit(pause)
            while True:
                try:
                    command = read_command('resume / stop > ').strip().lower()
                except (EOFError, OSError):
                    command, exit_reason = 'stop', 'cli_exit_stdin_eof'
                except KeyboardInterrupt:
                    command, exit_reason = 'stop', 'cli_exit_interrupted'
                if command in {'resume', '继续'}:
                    resumes += 1
                    result = acquire_action(holder)
                    break
                if command in {'stop', '停止'}:
                    if exit_reason == 'cli_exit_completed':
                        exit_reason = 'cli_exit_user_stop'
                    break
                emit({'cli_state': 'paused_waiting_for_user', 'session_left_open': True,
                      'instructions': '仅接受 resume 或 stop；没有重新请求验证或打开页面。'})
            if command in {'stop', '停止'}:
                break
        if result.status != 'human_required' and result.status not in {'completed', 'partial'}:
            exit_reason = 'cli_exit_acquisition_stopped'
    finally:
        service = holder.get('service')
        active_session = getattr(service, 'session', None) if service is not None else None
        if active_session is not None:
            active_session.stop()
            service.session = None
        if result is not None:
            result.session_left_open = False
    return result, {'session_left_open': False, 'cli_state': 'exited',
                    'cli_exit_reason': exit_reason, 'manual_resume_count': resumes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="获取本账号指定批次原视频；复用缓存，验证或身份不明时停在当前页面。")
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--resume-collection-run", "--collection-run", dest="collection_run_id", required=True)
    parser.add_argument("--max-items", type=int, default=1, help="本次最多新访问多少来源；默认单条探测")
    parser.add_argument("--max-content-candidates", type=int, default=50)
    parser.add_argument("--output-root", default="", help="可选项目内缓存目录；默认复用该账号批次的获取缓存")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-hold-browser", action="store_true",
                        help="非交互集成：遇验证立即关闭本次会话并退出，清单缓存保留")
    parser.add_argument("--authorization-reference", default=DEFAULT_AUTHORIZATION_REFERENCE,
                        help="默认沿用本会话用户对来源内容分析的既有授权，不需重复确认")
    args = parser.parse_args(argv)
    profile = AccountProfileRepository().get(args.account_id)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result, lifecycle = run_cli_acquisition(lambda holder: acquire_for_saved_run(profile,
        collection_run_id=args.collection_run_id, max_content_candidates=args.max_content_candidates,
        max_items=args.max_items, output_root=args.output_root or None, headless=args.headless,
        authorization_reference=args.authorization_reference, service_holder=holder),
        no_hold_browser=args.no_hold_browser)
    payload = result.to_dict()
    payload.update(lifecycle)
    payload.update(analysis_submitted=False, script_generation_submitted=False, video_generation_submitted=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.status in {"completed", "partial"} and result.acquired_count + result.cached_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
