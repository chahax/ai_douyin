"""Resolve an account-bound handling page and explicitly open its repair window.

Only generated Douyin URLs are returned. Scheduler receipt paths, item URLs and
authentication data are never navigation inputs. The shared window entry point
retains the original browser environment, account lease and recovery workflow.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from src.platform_adapter.douyin_identity import DOUYIN_SELF_URL
from src.trend_intelligence.providers.douyin_web import build_douyin_search_url


DEFAULT_MAINTENANCE_LOG_ROOT = Path(__file__).resolve().parents[2] / "data" / "account_maintenance"
CREATOR_CONTENT_URL = "https://creator.douyin.com/creator-micro/content/manage"
_MAINTENANCE_ID = re.compile(r"maintenance:[0-9a-f]{32}\Z")
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_ACCOUNT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_TERMINAL = frozenset({"failed", "blocked", "partial", "completed"})
_LEGACY_SMART_RESEARCH_WARNING = "本轮关联视频搜索需要人工验证；继续同步作品后台数据，运营报告使用最近成功采集的缓存样本。"
_SEARCH_SORT_LABELS = {"comprehensive": "综合排序", "most_liked": "最多点赞", "latest": "最新发布"}
_SEARCH_DETECTION_LABELS = {
    "visible_challenge": "验证界面阻塞记录",
    "verification_ui_unconfirmed": "验证容器内容未确认",
    "security_text_without_results": "安全提示且无搜索结果",
    "login_prompt_without_results": "登录提示且无搜索结果",
    "unclassified": "未分类",
}


def _safe_search_query(value) -> str | None:
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 200:
        return None
    if re.search(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff\u2028-\u202e\u2066-\u2069]|[\\]|[a-z][a-z0-9+.-]*:|^\s*//", value, re.I):
        return None
    return value.strip()


def _blocked_search_target(receipt, run_id, maintenance_id) -> ManualHandlingTarget:
    search = receipt.get("blocked_search")
    if not isinstance(search, Mapping) or set(search) != {"query", "query_kind", "sort_key", "detection"}:
        return _fallback()
    query = _safe_search_query(search.get("query"))
    kind, sort, detection = search.get("query_kind"), search.get("sort_key"), search.get("detection")
    if (query is None or not isinstance(kind, str) or kind not in {"keyword", "hashtag"}
            or not isinstance(sort, str) or sort not in _SEARCH_SORT_LABELS
            or not isinstance(detection, str) or detection not in _SEARCH_DETECTION_LABELS
            or (kind == "hashtag" and (not query.startswith("#") or not query[1:].strip()))):
        return _fallback()
    # One encoded path component, never a receipt-provided URL or undocumented sort parameter.
    url = f"https://www.douyin.com/search/{quote(query, safe='')}?type=video"
    display_query = re.sub(r"([\\`*_{}\[\]()<>#+.!|])", r"\\\1", query)
    evidence = receipt.get('challenge_evidence')
    summary = '旧记录未保存祖先可见性、遮挡与连续确认依据，不能仅凭此确认当前需要验证码。'
    if isinstance(evidence, Mapping) and evidence.get('version') in (2, 3):
        fields = ('frame_count','actionable_frames','visible_dialogs','confirmations')
        if all(type(evidence.get(k)) is int and 0 <= evidence[k] <= 10000 for k in fields):
            summary = (f"检测证据v{evidence['version']}：候选验证帧{evidence['frame_count']}，可交互帧{evidence['actionable_frames']}，"
                f"可见验证对话框{evidence['visible_dialogs']}，连续确认{evidence['confirmations']}次。")
    if isinstance(evidence, Mapping) and evidence.get('version') == 3:
        state = evidence.get('surface_state')
        label = {'blank':'空白','loading':'加载中','load_failed':'加载失败','unavailable':'内容不可读取',
            'unconfirmed':'内容未确认','challenge_ready':'已识别验证提示及可操作控件'}.get(state, '状态未确认')
        summary += f'验证内容：{label}。'
        if state != 'challenge_ready':
            summary += '未确认可操作验证码，不应反复要求完成验证码；请先核对页面加载和网络。'
    elif isinstance(evidence, Mapping) and evidence.get('version') == 2:
        summary += '旧v2只确认容器几何可见与命中，未确认其中已显示可操作验证码。'
    return ManualHandlingTarget(url,
        f"将打开原回执记录的确切查询“{display_query}”；原请求排序为“{_SEARCH_SORT_LABELS[sort]}”。"
        "这里只恢复查询，未自动恢复排序，页面可能仍为综合排序，请按需手动选择。"
        f"原记录分类：{_SEARCH_DETECTION_LABELS[detection]}；不代表当前页面仍有同一提示。" + summary,
        "blocked_search", run_id, maintenance_id)


@dataclass(frozen=True, slots=True)
class ManualHandlingTarget:
    url: str
    message: str
    source: str = "fallback"
    run_id: str = ""
    maintenance_run_id: str = ""


@dataclass(frozen=True, slots=True)
class ManualHandlingWindowResult:
    target: ManualHandlingTarget
    closed: bool = True
    message: str = "人工处理窗口已结束。请点击“处理完成，继续运行”，由后台核验原账号会话。"


def _handling_snapshot():
    from src.scheduler.account_refresh import snapshot

    return snapshot()


def _pause_for_handling(account_uuid: str, account_key: str) -> None:
    from src.scheduler.account_refresh import pause_account

    pause_account(account_uuid, account_key, "管理员打开原环境处理登录或安全验证",
        preserve_existing_pause=True)


def _same_local_path(first, second, *, allow_relative_first: bool = False) -> bool:
    if not isinstance(first, str) or not first or not isinstance(second, str) or not second:
        return False
    if first.startswith(("\\\\", "//")) or second.startswith(("\\\\", "//")):
        return False
    try:
        first_path, second_path = Path(first), Path(second)
        if not second_path.is_absolute() or (not first_path.is_absolute() and not allow_relative_first):
            return False
        # Legacy warmup configs use data/... relative to the app's project cwd.
        # Drive-relative C:... paths have a separate implicit cwd and are refused.
        if first_path.drive and not first_path.is_absolute():
            return False
        return first_path.resolve() == second_path.resolve()
    except (OSError, ValueError):
        return False


def _open_bound_manual_handling_window(
    account_uuid: str, account_key: str, *, runtime=None, snapshot_data: Mapping | None = None,
    trace: dict | None = None, on_progress: Callable[[str], None] | None = None,
) -> ManualHandlingWindowResult:
    """Open one bound account's actual visible repair window under its lease.

    This administrator action pauses scheduling while preserving an existing
    error. Closing the window does not probe identity, rebind an account or
    submit a handling-complete request. The browser retains its normal state
    checkpoint behavior; the separate backend recovery verifies the session.
    """
    if on_progress is not None:
        on_progress('validating')
    from src.operations_accounts.runtime import AccountRuntimeError, AccountRuntimeService

    if not isinstance(account_uuid, str) or not account_uuid or not isinstance(account_key, str) or not _ACCOUNT_KEY.fullmatch(account_key):
        raise AccountRuntimeError("account_uuid_mismatch", "人工处理需要有效且一致的原账号标识。")
    service = runtime if runtime is not None else AccountRuntimeService()
    context = service.resolve(account_key, require_healthy=False)
    profile, binding = _value(context, "profile"), _value(context, "binding")
    if binding is None:
        raise AccountRuntimeError("binding_required", "请先确认原账号身份绑定。")
    if any(_value(source, "account_uuid") != account_uuid or _value(source, "account_key") != account_key
            for source in (context, profile, binding)):
        raise AccountRuntimeError("account_uuid_mismatch", "所选账号与原浏览器身份绑定不一致，已拒绝打开。")
    original_environment = _value(binding, "browser_environment_key")
    if (not original_environment or _value(context, "browser_environment_key") != original_environment
            or not _same_local_path(_value(context, "browser_profile_dir"), _value(binding, "browser_profile_dir"))
            or not _same_local_path(_value(context, "storage_state_path"), _value(binding, "storage_state_path"))):
        raise AccountRuntimeError("browser_environment_mismatch", "原浏览器环境或登录态文件与绑定不一致。")
    if on_progress is not None:
        on_progress('preparing')
    data = snapshot_data if snapshot_data is not None else _handling_snapshot()
    target = resolve_manual_handling_target(profile, account_uuid=account_uuid,
        account_key=account_key, snapshot=data)
    if trace is not None:
        trace.update(source=target.source, run_id=target.run_id)
    _pause_for_handling(account_uuid, account_key)
    if on_progress is not None:
        on_progress('acquiring')
    with service.manual_browser_environment(account_key) as prepared:
        prepared_profile = _value(prepared, "profile")
        if (_value(prepared_profile, "account_uuid") != account_uuid
                or _value(prepared_profile, "account_key") != account_key):
            raise AccountRuntimeError("account_uuid_mismatch", "互斥环境对应的账号已变化，已拒绝打开。")
        if (_value(prepared, "browser_environment_key") != original_environment
                or not _same_local_path(_value(prepared, "browser_profile_dir"), _value(binding, "browser_profile_dir"))
                or not _same_local_path(_value(prepared, "storage_state_path"), _value(binding, "storage_state_path"))):
            raise AccountRuntimeError("browser_environment_mismatch", "互斥环境与原绑定环境不一致，已拒绝打开。")
        if on_progress is not None:
            on_progress('starting_browser')
        session = prepared.create_browser_session(headless=False)
        open_error = None
        opened = False
        def page_opened():
            nonlocal opened
            if opened:
                return
            opened = True
            _manual_window_event('page_opened', account_key, target.source, target.run_id)
            on_progress('window_open_waiting_close')
        try:
            config = _value(session, "config")
            if (_value(config, "headless") is not False
                    or not _same_local_path(_value(config, "user_data_dir"), _value(binding, "browser_profile_dir"), allow_relative_first=True)
                    or not _same_local_path(_value(config, "storage_state_path"), _value(binding, "storage_state_path"), allow_relative_first=True)):
                raise AccountRuntimeError("browser_environment_mismatch", "实际窗口的原账号profile或登录态配置不一致。")
            _manual_window_event("opening", account_key, target.source, target.run_id)
            callbacks = {'on_opened': page_opened} if on_progress is not None else {}
            session.open_for_manual_login_until_closed(target.url, timeout_seconds=1800, **callbacks)
            if on_progress is not None and not opened:
                raise AccountRuntimeError('manual_window_not_opened', '未收到原浏览器页面已打开的确认，不能将窗口写为已打开。')
        except BaseException as exc:
            open_error = exc
            raise
        finally:
            try:
                session.stop()
            except Exception as exc:
                if open_error is None:
                    raise
                _manual_window_event("cleanup_failed", account_key, target.source, target.run_id, type(exc).__name__)
    _manual_window_event("closed", account_key, target.source, target.run_id)
    if on_progress is not None:
        on_progress('closed')
    return ManualHandlingWindowResult(target=target)


def _manual_window_event(event: str, account_key: str, source: str, run_id: str, error_type: str = "") -> None:
    from src.shared.logger import logger

    write = logger.warning if event in {"failed", "cleanup_failed"} else logger.info
    write("manual_handling_window event={} account_key={} target_source={} run_id={} error_type={}",
        event, account_key, source, run_id, error_type)


def open_bound_manual_handling_window(
    account_uuid: str, account_key: str, *, runtime=None, snapshot_data: Mapping | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ManualHandlingWindowResult:
    """Shared administrator entry point; lifecycle logs contain no URL or exception payload."""
    from .browser_control_runtime import enabled, is_managed_account, queue_manual_window
    if enabled() and not is_managed_account(account_key):
        queued = queue_manual_window(account_uuid, account_key, 'explicit:manual_handling')
        return ManualHandlingWindowResult(target=_fallback(), closed=False,
            message=f"人工窗口已交给原账号管控队列，尚未确认打开。任务：{queued['job_id']}")
    safe_key = account_key if isinstance(account_key, str) and _ACCOUNT_KEY.fullmatch(account_key) else "invalid"
    trace = {"source": "unresolved", "run_id": ""}
    _manual_window_event("requested", safe_key, trace["source"], trace["run_id"])
    try:
        return _open_bound_manual_handling_window(account_uuid, account_key, runtime=runtime,
            snapshot_data=snapshot_data, trace=trace, on_progress=on_progress)
    except Exception as exc:
        _manual_window_event("failed", safe_key, trace["source"], trace["run_id"], type(exc).__name__)
        raise


def _fallback() -> ManualHandlingTarget:
    return ManualHandlingTarget(DOUYIN_SELF_URL,
        "没有可可靠绑定当前异常的处理页面，将打开原账号主页；按页面提示人工处理登录或安全验证。")


def _value(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
        return converted if math.isfinite(converted) else None
    except OverflowError:
        return None


def _rows(snapshot: Mapping, field: str):
    value = snapshot.get(field, ())
    return value if isinstance(value, (list, tuple)) else None


def _receipt_time(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OSError, OverflowError):
        return None


def _read_receipt(root: Path, key: str, maintenance_id: str) -> Mapping | None:
    """Derive one fixed filename; never read a path supplied by a run receipt."""
    try:
        if not root.is_absolute() or str(root).startswith(("\\\\", "//")):
            return None
        root = root.resolve()
        if {part.lower() for part in root.parts} & {".aws", ".ssh", ".azure", ".kube"}:
            return None
        account_dir = root / key
        expected_name = maintenance_id.replace(":", "_") + ".json"
        path = (account_dir / expected_name).resolve()
        if not path.is_relative_to(root) or path.parent != account_dir or path.name != expected_name:
            return None
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            return None
        receipt = json.loads(data.decode("utf-8"))
        return receipt if isinstance(receipt, Mapping) else None
    except (OSError, ValueError, UnicodeError):
        return None


def resolve_manual_handling_target(
    profile=None, *, account_uuid: str | None = None, account_key: str | None = None,
    snapshot: Mapping | None = None, maintenance_receipts: Mapping | None = None,
    log_root: str | Path = DEFAULT_MAINTENANCE_LOG_ROOT,
) -> ManualHandlingTarget:
    """Find a useful handling page only from the current paused run's evidence.

    ``maintenance_receipts`` may inject a mapping of maintenance IDs to decoded
    receipts for tests. It does not accept filenames. Missing or ambiguous
    context falls back to the original account's self page. Explicit caller
    identity disagreement is rejected, rather than selecting another account.
    """
    profile_uuid, profile_key = _value(profile, "account_uuid"), _value(profile, "account_key")
    if profile is not None and ((account_uuid is not None and account_uuid != profile_uuid)
            or (account_key is not None and account_key != profile_key)):
        raise ValueError("人工处理账号与所选账号不一致。")
    uuid, key = account_uuid or profile_uuid, account_key or profile_key
    if not isinstance(uuid, str) or not uuid or not isinstance(key, str) or not _ACCOUNT_KEY.fullmatch(key):
        raise ValueError("人工处理需要有效的原账号UUID与账号标识。")
    if not isinstance(snapshot, Mapping):
        return _fallback()
    control_rows = _rows(snapshot, "controls")
    if control_rows is None:
        return _fallback()
    controls = [row for row in control_rows if isinstance(row, Mapping)
        and row.get("account_uuid") == uuid and row.get("account_key") == key]
    if len(controls) != 1 or controls[0].get("state") != "paused" or controls[0].get("error_code") not in {"human_required", "verification_ui_unconfirmed", "feed_not_ready"}:
        return _fallback()
    paused_at = _number(controls[0].get("updated_at"))
    if paused_at is None:
        return _fallback()
    candidates = []
    for field, mode in (("runs", "post-publish"), ("smart_runs", "smart-operations"), ("playback_runs", "playback")):
        run_rows = _rows(snapshot, field)
        if run_rows is None:
            return _fallback()
        for run in run_rows:
            if isinstance(run, Mapping) and run.get("account_uuid") == uuid and run.get("account_key") == key:
                started = _number(run.get("started_at"))
                if started is None:
                    return _fallback()
                # An unfinished later run makes the current context ambiguous.
                candidates.append((started, run, mode))
    if not candidates:
        return _fallback()
    latest_start = max(row[0] for row in candidates)
    latest = [row for row in candidates if row[0] == latest_start]
    if len(latest) != 1:
        return _fallback()
    started, run, mode = latest[0]
    finished = _number(run.get("finished_at"))
    run_id = run.get("run_id")
    if (run.get("status") not in _TERMINAL or finished is None or finished < started
            or finished != paused_at or not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id)):
        return _fallback()
    detail = run.get("detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            return _fallback()
    if not isinstance(detail, Mapping) or detail.get("error_code") != controls[0].get("error_code"):
        return _fallback()
    maintenance_id = detail.get("maintenance_run_id")
    if not isinstance(maintenance_id, str) or not _MAINTENANCE_ID.fullmatch(maintenance_id):
        return _fallback()
    if maintenance_receipts is not None:
        if not isinstance(maintenance_receipts, Mapping):
            return _fallback()
        receipt = maintenance_receipts.get(maintenance_id)
    else:
        if not isinstance(log_root, (str, Path)):
            return _fallback()
        receipt = _read_receipt(Path(log_root), key, maintenance_id)
    if (not isinstance(receipt, Mapping) or receipt.get("run_id") != maintenance_id
            or receipt.get("account_uuid") != uuid or receipt.get("account_key") != key
            or receipt.get("mode") != mode or receipt.get("status") not in _TERMINAL
            or receipt.get("error_code") != controls[0].get("error_code") or receipt.get("runtime_lease_acquired") is False):
        return _fallback()
    receipt_started, receipt_finished = _receipt_time(receipt.get("started_at")), _receipt_time(receipt.get("finished_at"))
    if (receipt_started is None or receipt_finished is None or receipt_finished < receipt_started
            or receipt_started < started - 1 or receipt_finished > finished + 1):
        return _fallback()
    if mode == "post-publish":
        if controls[0].get('error_code') == 'feed_not_ready':
            return _fallback()
        return ManualHandlingTarget(CREATOR_CONTENT_URL,
            "原维护回执显示后台数据同步需要人工验证，将打开原账号的创作者内容管理页。",
            "creator_content", run_id, maintenance_id)
    stage = receipt.get("failure_stage", "")
    if not isinstance(stage, str):
        return _fallback()
    research_stage = stage in {"research", "trend_collection"}
    if controls[0].get('error_code') == 'feed_not_ready' and not (
            mode == 'playback' and receipt.get('playback_source') == 'recommend_feed'):
        return _fallback()
    if "blocked_search" in receipt and receipt["blocked_search"] != {}:
        if not research_stage or receipt.get("login_healthy") is not True:
            return _fallback()
        return _blocked_search_target(receipt, run_id, maintenance_id)
    if mode == "playback" and receipt.get("playback_source") == "recommend_feed":
        if stage != "playback" or receipt.get("login_healthy") is not True:
            return _fallback()
        from src.platform_adapter.douyin_recommendation_playback import FEED_URL
        return ManualHandlingTarget(FEED_URL,
            "原账号身份核验已通过，异常发生在首页推荐流；将打开原账号首页供人工检查。",
            "recommend_feed", run_id, maintenance_id)
    items = receipt.get("playback_items", [])
    if mode == "playback" and not isinstance(items, list):
        return _fallback()
    if mode == "playback" and items:
        blocked = [item for item in items if isinstance(item, Mapping) and item.get("error_code") in {"human_required", "verification_ui_unconfirmed"}]
        if len(blocked) != 1 or blocked[0].get("playback_verified") is True:
            return _fallback()
        video_id = blocked[0].get("video_id")
        if isinstance(video_id, int) and not isinstance(video_id, bool):
            video_id = str(video_id)
        if isinstance(video_id, str) and re.fullmatch(r"[0-9]{8,32}", video_id):
            return ManualHandlingTarget(f"https://www.douyin.com/video/{video_id}",
                "原播放回执记录此视频需要人工验证，将在原账号环境打开对应视频页。",
                "playback_video", run_id, maintenance_id)
        return _fallback()
    keywords = receipt.get("research_keywords")
    warnings = receipt.get("warnings")
    legacy_smart_research = (mode == "smart-operations" and stage == ""
        and isinstance(warnings, list) and _LEGACY_SMART_RESEARCH_WARNING in warnings)
    research_context = (research_stage or legacy_smart_research
        or (mode == "playback" and stage == "" and receipt.get("playback_candidates", 0) == 0))
    if research_context and receipt.get("login_healthy") is True and isinstance(keywords, list) and keywords:
        keyword = _safe_search_query(keywords[0])
        if keyword is not None:
            return ManualHandlingTarget(build_douyin_search_url(keyword),
                "将打开原回执记录的首个调研关键词搜索页；这不是精确失败查询，请按页面提示人工处理。",
                "recorded_research_keyword", run_id, maintenance_id)
    return _fallback()
