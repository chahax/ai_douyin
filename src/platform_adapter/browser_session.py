"""
browser_session.py — Playwright 浏览器会话管理

使用独立子进程运行 Playwright 浏览器，解决 Python 3.14 Windows
WindowsSelectorEventLoop / ProactorEventLoop 不支持 subprocess_exec 的问题。
"""

import json
import hashlib
import ipaddress
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.platform_adapter.models import BrowserSessionConfig, SessionState
from src.shared.config import settings
from src.shared.logger import logger
from src.shared.browser_worker_state import (
    checkpoint_open_login_pages as _checkpoint_open_login_pages,
    missing_snapshot_cookies as _missing_snapshot_cookies,
)


class BinaryDownloadError(RuntimeError):
    """A download failed validation; its message contains no signed URL/body."""


class BrowserWorkerUnavailable(RuntimeError):
    code = "browser_worker_unavailable"


class BrowserNavigationTimeout(RuntimeError):
    code = 'browser_navigation_timeout'

    def __init__(self, evidence):
        from src.shared.browser_navigation import clean_navigation_evidence
        self.navigation_evidence = clean_navigation_evidence(evidence)
        self.page = None
        super().__init__('页面跳转等待超时，尚未确认页面可用；请检查网络与当前页面。')


class BrowserWorkerStartupTimeout(TimeoutError):
    code = "browser_start_timeout"

    def __init__(self, stage: str, seconds: float):
        self.stage = stage
        self.startup_evidence = {}
        super().__init__(f"浏览器启动在 {stage} 阶段超过 {seconds:g} 秒，未收到就绪回执；本次启动已停止，请检查本机浏览器环境后再打开。")


class BrowserWorkerStartupError(RuntimeError):
    code = "browser_start_failed"

    def __init__(self, stage: str):
        self.stage = stage
        self.startup_evidence = {}
        super().__init__(f"浏览器启动在 {stage} 阶段失败，尚未确认页面已打开，请检查本机浏览器环境。")


def _sanitize_browser_error_message(value: object) -> str:
    """Keep the useful first line while dropping request headers and signed URLs."""
    first_line = str(value or "Unknown browser error").splitlines()[0].strip()
    first_line = re.sub(r"https?://\S+", "<url>", first_line)
    return first_line[:500] or "Unknown browser error"


def _download_target(value: str | Path, workspace_root: str | Path | None = None) -> Path:
    root = Path(workspace_root or Path(__file__).resolve().parents[2]).resolve()
    target = Path(value).resolve()
    if target == root or not target.is_relative_to(root):
        raise BinaryDownloadError("binary download target must be inside the project workspace")
    if target.is_dir():
        raise BinaryDownloadError("binary download target is a directory")
    return target


def _url_identity(url: str) -> dict:
    parsed = urlsplit(url)
    # Queries/fragments and userinfo can contain signed credentials. Neither
    # logging nor the subprocess JSON reply needs those values.
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return {"safe_url": urlunsplit((parsed.scheme, host + port, parsed.path, "", "")),
            "sha256": hashlib.sha256(url.encode("utf-8")).hexdigest()}


def _validate_download_url(url: str, allowed_hosts: list[str], *, allow_loopback: bool = False) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or parsed.username or parsed.password or parsed.scheme not in {"https", "http"}:
        raise BinaryDownloadError("binary download requires an HTTP(S) URL without embedded credentials")
    permitted = False
    for pattern in allowed_hosts:
        pattern = str(pattern).lower().rstrip(".")
        if pattern.startswith("*."):
            permitted = permitted or (host.endswith(pattern[1:]) and host != pattern[2:])
        else:
            permitted = permitted or host == pattern
    if not permitted:
        raise BinaryDownloadError("binary download redirect host is outside the allowed hosts")
    try:
        addresses = {ipaddress.ip_address(item[4][0].split("%", 1)[0]) for item in
                     socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except (OSError, ValueError):
        raise BinaryDownloadError("binary download host could not be validated") from None
    is_loopback_fixture = allow_loopback and addresses and all(address.is_loopback for address in addresses)
    if parsed.scheme != "https" and not is_loopback_fixture:
        raise BinaryDownloadError("binary download requires HTTPS on every redirect")
    if not addresses or (not is_loopback_fixture and any(not address.is_global for address in addresses)):
        raise BinaryDownloadError("binary download rejects private or non-public network addresses")


def _download_binary_response(request_context, url: str, output_path: str | Path,
                              headers: dict | None = None, timeout: int = 30000, *,
                              max_bytes: int = 256 * 1024 * 1024,
                              expected_content_types: list[str] | None = None,
                              allowed_hosts: list[str] | None = None, max_redirects: int = 3,
                              overwrite: bool = False, workspace_root: str | Path | None = None,
                              _allow_loopback_fixture: bool = False) -> dict:
    """Use an existing authenticated context and write its unmodified bytes.

    APIRequestContext buffers the response internally. The explicit limit bounds
    accepted/saved bodies; Content-Length is rejected before calling body().
    """
    import tempfile

    if type(max_bytes) is not int or max_bytes <= 0:
        raise BinaryDownloadError("max_bytes must be a positive integer")
    if type(max_redirects) is not int or not 0 <= max_redirects <= 10:
        raise BinaryDownloadError("max_redirects must be between 0 and 10")
    if type(timeout) is not int or timeout <= 0:
        raise BinaryDownloadError("timeout must be a positive millisecond value")
    target = _download_target(output_path, workspace_root)
    if target.exists() and not overwrite:
        raise BinaryDownloadError("binary download target already exists")
    hosts = list(allowed_hosts) if allowed_hosts is not None else [urlsplit(url).hostname or ""]
    expected = [value.lower().split(";", 1)[0].strip() for value in (expected_content_types or [])]
    original_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
    current, redirect_count = url, 0
    current_headers = dict(headers or {})
    temporary = None
    while True:
        _validate_download_url(current, hosts, allow_loopback=_allow_loopback_fixture)
        response = None
        try:
            try:
                response = request_context.get(current, headers=current_headers, timeout=timeout,
                                               max_redirects=0, fail_on_status_code=False)
            except Exception as exc:
                raise BinaryDownloadError(f"binary request failed ({type(exc).__name__}; request_sha256={original_id[:16]})") from None
            status = int(response.status)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            if status in {301, 302, 303, 307, 308}:
                if redirect_count >= max_redirects:
                    raise BinaryDownloadError("binary download exceeded its redirect limit")
                location = response_headers.get("location")
                if not location:
                    raise BinaryDownloadError("binary download redirect has no Location")
                next_url = urljoin(current, location)
                before, after = urlsplit(current), urlsplit(next_url)
                if (before.scheme, before.netloc) != (after.scheme, after.netloc):
                    # Context cookies still follow their real domain rules.
                    # Explicit credentials must not follow a cross-origin hop.
                    current_headers = {key: value for key, value in current_headers.items()
                                       if key.lower() not in {"authorization", "proxy-authorization", "cookie"}}
                current = next_url
                redirect_count += 1
                continue
            # Do not accept 206 partial media or empty 204 as a whole source.
            if status != 200:
                raise BinaryDownloadError(f"binary download HTTP status {status}; no output saved")
            content_type = response_headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if expected and not any(content_type == value or
                    (value.endswith("/*") and content_type.startswith(value[:-1])) for value in expected):
                raise BinaryDownloadError("binary download Content-Type is not allowed")
            length = response_headers.get("content-length")
            if length is not None:
                try:
                    declared_length = int(length)
                except (ValueError, TypeError):
                    raise BinaryDownloadError("binary download has an invalid Content-Length") from None
                if declared_length <= 0 or declared_length > max_bytes:
                    raise BinaryDownloadError("binary download declared size is empty or exceeds max_bytes")
            body = response.body()
            if not isinstance(body, bytes):
                raise BinaryDownloadError("binary response body was not raw bytes")
            if not 0 < len(body) <= max_bytes:
                raise BinaryDownloadError("binary download body is empty or exceeds max_bytes")
            if length is not None and not response_headers.get("content-encoding") and len(body) != declared_length:
                raise BinaryDownloadError("binary download body differs from declared Content-Length")
            final_url = response.url
            _validate_download_url(final_url, hosts, allow_loopback=_allow_loopback_fixture)
            identity = _url_identity(final_url)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Check the resolved parent again after creation, before writing.
            target = _download_target(target, workspace_root)
            fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
            with os.fdopen(fd, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            if target.exists() and not overwrite:
                raise BinaryDownloadError("binary download target appeared during download")
            os.replace(temporary, target)
            temporary = None
            return {"status": status, "path": str(target), "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(), "content_type": content_type,
                    "final_url": identity["safe_url"], "final_url_sha256": identity["sha256"],
                    "request_url_sha256": original_id, "redirect_count": redirect_count,
                    "final_url_redacted": True}
        except BinaryDownloadError:
            raise
        except Exception as exc:
            raise BinaryDownloadError(f"binary download failed ({type(exc).__name__}; request_sha256={original_id[:16]})") from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
            if response is not None:
                try:
                    response.dispose()
                except Exception:
                    pass


# ─── 子进程 bootstrap（独立 Python 进程，无 Streamlit 事件循环）──────────────
# 关键：不用 asyncio.run()，避免 Playwright sync API 报错
# "using Sync API inside asyncio loop"

_PW_SCRIPT = r"""
import json
import sys
import threading
import time

_bootstrap_started = time.monotonic()
_last_stage = 'spawning_worker'

def _stage(name):
    global _last_stage
    _last_stage = name
    sys.stderr.write(json.dumps({"browser_worker_stage": name,
        "elapsed_ms": round((time.monotonic() - _bootstrap_started) * 1000)}) + "\n")
    sys.stderr.flush()


def main():
    init_line = sys.stdin.readline()
    if not init_line:
        return
    init = json.loads(init_line)
    sys.dont_write_bytecode = True
    sys.path[:0] = init.get("python_paths", [])
    _stage("importing_playwright")

    user_data_dir = init.get("user_data_dir", "")
    headless = init.get("headless", False)
    slow_mo = init.get("slow_mo", 0)
    timeout_ms = init.get("timeout_ms", 30000)
    channel = init.get("channel", "")
    chromium_sandbox = init.get("chromium_sandbox", False)
    storage_state_path = init.get("storage_state_path", "")

    from playwright.sync_api import sync_playwright

    _stage("starting_driver")
    from playwright._impl._driver import compute_driver_executable
    from src.shared.browser_startup_diagnostics import driver_start_watch
    with driver_start_watch(*compute_driver_executable()):
        pw = sync_playwright().start()
    kwargs = {"headless": headless, "slow_mo": slow_mo}
    if headless or init.get("mute_audio", False):
        # Background playback and explicitly muted verification windows stay silent.
        kwargs["args"] = ["--mute-audio"]
    if not headless and init.get("start_minimized", False):
        kwargs.setdefault("args", []).append("--start-minimized")
    if channel:
        kwargs["channel"] = channel
    if chromium_sandbox:
        kwargs["chromium_sandbox"] = True

    _stage("launching_browser")
    context = pw.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        **kwargs,
    )
    context.set_default_timeout(timeout_ms)
    _stage("restoring_state")

    # 恢复 storage state（cookies + localStorage）
    restored_cookies = 0
    restored_origins = 0
    restored_cookie_domains = []
    restored_origin_names = []
    if storage_state_path:
        import os as _os
        if _os.path.exists(storage_state_path):
            try:
                with open(storage_state_path, "r", encoding="utf-8") as _f:
                    _state = json.loads(_f.read())
            except json.JSONDecodeError as _exc:
                sys.stdout.write(json.dumps({"status": "error", "msg": "storage_state JSON 损坏: " + str(_exc)}) + "\n")
                sys.stdout.flush()
                context.close()
                pw.stop()
                return
            except OSError as _exc:
                sys.stdout.write(json.dumps({"status": "error", "msg": "storage_state 读取失败: " + str(_exc)}) + "\n")
                sys.stdout.flush()
                context.close()
                pw.stop()
                return

            _cookies = _state.get("cookies", [])
            if _cookies:
                _allowed = {"name", "value", "url", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
                _clean = []
                for _c in _cookies:
                    _clean.append({_k: _v for _k, _v in _c.items() if _k in _allowed})
                from src.shared.browser_worker_state import missing_snapshot_cookies as _missing_snapshot_cookies
                _clean = _missing_snapshot_cookies(_clean, context.cookies())
                if _clean:
                    context.add_cookies(_clean)
                restored_cookies = len(_clean)
                restored_cookie_domains = sorted(set(_c.get("domain", "") for _c in _clean if _c.get("domain")))

            _origins = _state.get("origins", [])
            if _origins:
                _origin_map = {}
                for _o in _origins:
                    _on = _o.get("origin", "")
                    _ls = _o.get("localStorage", [])
                    if _on and _ls:
                        _entries = {}
                        for _li in _ls:
                            if "name" in _li and "value" in _li:
                                _entries[_li["name"]] = _li["value"]
                        if _entries:
                            _origin_map[_on] = _entries
                if _origin_map:
                    _script = "(function(){\nvar _m=" + json.dumps(_origin_map) + ";\nvar _d=_m[window.location.origin];\nif(_d){for(var _k in _d){try{if(localStorage.getItem(_k)===null){localStorage.setItem(_k,_d[_k]);}}catch(_e){}}}\n})()"
                    context.add_init_script(_script)
                    restored_origins = len(_origin_map)
                    restored_origin_names = sorted(_origin_map.keys())

    page = context.pages[0] if context.pages else context.new_page()
    # Handles name a particular Page for its whole lifetime. Switching another
    # task to a new tab never changes an existing Page/Locator's target.
    tabs = {}
    tab_roles = {}
    context_closed = False
    import uuid
    tab_namespace = uuid.uuid4().hex

    def register_tab(tab, role="unclaimed"):
        for tab_id, existing in tabs.items():
            if existing is tab:
                return tab_id
        tab_id = "tab-" + tab_namespace + "-" + str(len(tabs) + 1)
        tabs[tab_id] = tab
        tab_roles[tab_id] = role
        return tab_id

    default_tab_id = register_tab(page, "default")
    fanqie_identity_observers = {}
    fanqie_promotion_observers = {}
    for existing in context.pages:
        register_tab(existing)

    def on_context_closed(*_):
        nonlocal context_closed
        context_closed = True

    if hasattr(context, "on"):
        context.on("page", register_tab)
        context.on("close", on_context_closed)

    def tab_snapshot():
        from urllib.parse import urlsplit, urlunsplit
        result = []
        for tab_id, tab in tabs.items():
            closed = context_closed or tab.is_closed()
            url = ""
            if not closed:
                parsed = urlsplit(tab.url)
                # A queue/status view must not expose signed query strings.
                host = parsed.hostname or ""
                if ":" in host:
                    host = "[" + host + "]"
                if parsed.port:
                    host += ":" + str(parsed.port)
                url = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
            result.append({"tab_id": tab_id, "role": tab_roles[tab_id],
                "closed": closed, "url": url})
        return result

    def pump_window_events():
        # Sync Playwright dispatches desktop closes during an API call. This is
        # bounded to one millisecond, unlike legacy wait_for_close.
        if not context_closed:
            for tab in tabs.values():
                if not tab.is_closed():
                    try:
                        tab.wait_for_timeout(1)
                    except Exception:
                        if not context_closed and not tab.is_closed():
                            raise
                    break

    context_actions = {"new_tab", "list_tabs", "close_tab", "window_status",
        "save_state", "save_visible_state", "wait_for_close", "api_download",
        "api_request", "stop"}
    _stage("ready")

    # 确认就绪
    sys.stdout.write(json.dumps({
        "status": "ready",
        "restored_cookies": restored_cookies,
        "restored_origins": restored_origins,
        "restored_cookie_domains": restored_cookie_domains,
        "restored_origin_names": restored_origin_names,
        "default_tab_id": default_tab_id,
        "supervision_protocol": 1,
    }) + "\n")
    sys.stdout.flush()

    # 主循环：处理命令
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        cmd = json.loads(line)
        action = cmd.get("action", "")

        try:
            if action not in context_actions:
                tab_id = cmd.get("tab_id", default_tab_id)
                if tab_id not in tabs or context_closed or tabs[tab_id].is_closed():
                    raise RuntimeError("browser tab is missing or closed")
                page = tabs[tab_id]

            if action == "new_tab":
                role = cmd.get("role")
                if not isinstance(role, str) or not role.strip() or len(role) > 80:
                    raise ValueError("tab role must be a nonempty string of at most 80 characters")
                if context_closed:
                    raise RuntimeError("browser context is closed")
                tab = context.new_page()
                tab_id = register_tab(tab, role)
                tab_roles[tab_id] = role
                sys.stdout.write(json.dumps({"status": "ok", "tab_id": tab_id, "role": role}) + "\n")

            elif action == "list_tabs":
                pump_window_events()
                sys.stdout.write(json.dumps({"status": "ok", "tabs": tab_snapshot()}) + "\n")

            elif action == "close_tab":
                tab_id = cmd.get("tab_id")
                if tab_id not in tabs:
                    raise RuntimeError("browser tab is missing")
                if not context_closed and not tabs[tab_id].is_closed():
                    tabs[tab_id].close()
                sys.stdout.write(json.dumps({"status": "ok", "tab_id": tab_id, "closed": True}) + "\n")

            elif action == "window_status":
                pump_window_events()
                snapshot = tab_snapshot()
                count = sum(not item["closed"] for item in snapshot)
                sys.stdout.write(json.dumps({"status": "ok", "open": count > 0,
                    "closed": count == 0, "context_closed": context_closed,
                    "tab_count": count, "tabs": snapshot}) + "\n")

            elif action == "goto":
                from src.shared.browser_navigation import navigate
                response = navigate(page, cmd["url"], wait_until=cmd.get("wait_until", "domcontentloaded"),
                    timeout=cmd.get("timeout", timeout_ms))
                sys.stdout.write(json.dumps(response) + "\n")

            elif action == "minimize_window":
                from src.operations_accounts.retained_feed_session import minimize
                result = minimize(page)
                sys.stdout.write(json.dumps(dict(status="ok", **result)) + "\n")

            elif action == "supervision_window":
                if headless:
                    raise RuntimeError('A headless session cannot be displayed')
                from src.operations_accounts.window_supervision import set_window
                result = set_window(page, cmd.get('mode'))
                sys.stdout.write(json.dumps(dict(status="ok", **result)) + "\n")

            elif action == "supervision_window_state":
                if headless:
                    raise RuntimeError('A headless session has no visible window')
                from src.operations_accounts.window_supervision import window_state
                result = window_state(page)
                sys.stdout.write(json.dumps(dict(status="ok", **result)) + "\n")

            elif action == "reveal_manual_window":
                if headless or tab_roles.get(tab_id) != 'manual':
                    raise RuntimeError('Only the original headed manual tab may be displayed')
                from src.operations_accounts.manual_window_visibility import restore_native_window
                result = restore_native_window(page)
                sys.stdout.write(json.dumps(dict(status="ok", **result)) + "\n")

            elif action == "wait_for_selector":
                page.wait_for_selector(cmd["selector"], timeout=cmd.get("timeout", timeout_ms))
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "set_input_files":
                idx = cmd.get("index", 0)
                locator = page.locator("input[type=file]").nth(idx)
                locator.set_input_files(cmd["file_path"])
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "fill":
                idx = cmd.get("index", 0)
                if idx >= 0:
                    page.locator(cmd["selector"]).nth(idx).fill(cmd["value"])
                else:
                    page.locator(cmd["selector"]).first.fill(cmd["value"])
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "click":
                idx = cmd.get("index", 0)
                options = {
                    "force": bool(cmd.get("force", False)),
                    "timeout": cmd.get("timeout", timeout_ms),
                }
                if idx >= 0:
                    page.locator(cmd["selector"]).nth(idx).click(**options)
                else:
                    page.locator(cmd["selector"]).first.click(**options)
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "hover":
                idx = cmd.get("index", 0)
                options = {
                    "force": bool(cmd.get("force", False)),
                    "timeout": cmd.get("timeout", timeout_ms),
                }
                if idx >= 0:
                    page.locator(cmd["selector"]).nth(idx).hover(**options)
                else:
                    page.locator(cmd["selector"]).first.hover(**options)
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "locator_count":
                cnt = page.locator(cmd["selector"]).count()
                sys.stdout.write(json.dumps({"status": "ok", "count": cnt}) + "\n")

            elif action == "locator_first_text":
                txt = page.locator(cmd["selector"]).first.inner_text().strip()
                sys.stdout.write(json.dumps({"status": "ok", "text": txt}) + "\n")

            elif action == "locator_filter_text":
                els = page.locator(cmd["selector"]).filter(has_text=cmd["text"])
                cnt = els.count()
                if cnt > 0:
                    els.first.click()
                sys.stdout.write(json.dumps({"status": "ok", "count": cnt}) + "\n")

            elif action == "click_button_by_text":
                texts = cmd.get("texts", [])
                buttons = page.locator("button")
                candidates = []
                clicked = None
                for i in range(buttons.count()):
                    btn = buttons.nth(i)
                    try:
                        text = btn.inner_text().strip()
                        visible = btn.is_visible()
                        enabled = btn.is_enabled()
                        cls = btn.get_attribute("class") or ""
                    except Exception as exc:
                        candidates.append({"index": i, "error": str(exc)})
                        continue

                    item = {
                        "index": i,
                        "text": text,
                        "visible": visible,
                        "enabled": enabled,
                        "class": cls[:120],
                    }
                    candidates.append(item)
                    if clicked is None and visible and enabled and text in texts:
                        btn.click()
                        clicked = item
                        break

                sys.stdout.write(json.dumps({
                    "status": "ok",
                    "clicked": clicked,
                    "candidates": candidates,
                }, ensure_ascii=False) + "\n")

            elif action == "interact_visible_exact_text":
                text = str(cmd.get("text", ""))
                operation = str(cmd.get("operation", "inspect"))
                prefer_parent = bool(cmd.get("prefer_parent", False))
                if operation not in {"inspect", "hover", "click"}:
                    raise ValueError(f"unsupported visible-text operation: {operation}")

                candidates = page.get_by_text(text, exact=True)
                matched = None
                candidate_count = candidates.count()
                for index in range(candidate_count - 1, -1, -1):
                    candidate = candidates.nth(index)
                    if not candidate.is_visible():
                        continue
                    target = candidate
                    if prefer_parent:
                        interactive = candidate.locator(
                            "xpath=ancestor-or-self::*["
                            "@tabindex or self::button or @role='button'"
                            "][1]"
                        )
                        if interactive.count() > 0:
                            target = interactive
                    matched = {
                        "index": index,
                        "tag": candidate.evaluate("element => element.tagName"),
                    }
                    if operation == "hover":
                        target.hover()
                    elif operation == "click":
                        target.click()
                    break
                sys.stdout.write(json.dumps({
                    "status": "ok",
                    "matched": matched,
                    "candidate_count": candidate_count,
                }, ensure_ascii=False) + "\n")

            elif action == "wait_for_timeout":
                page.wait_for_timeout(cmd["ms"])
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "press":
                idx = cmd.get("index", 0)
                if idx >= 0:
                    page.locator(cmd["selector"]).nth(idx).press(cmd["key"])
                else:
                    page.locator(cmd["selector"]).first.press(cmd["key"])
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "type_text":
                idx = cmd.get("index", 0)
                if idx >= 0:
                    page.locator(cmd["selector"]).nth(idx).type(cmd["text"])
                else:
                    page.locator(cmd["selector"]).first.type(cmd["text"])
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "inspect_published_video":
                from src.platform_adapter.publish_verification import inspect_published_video
                evidence = inspect_published_video(page, cmd['post_id'], cmd['ai_required'], cmd['fiction_required'],
                    required_hashtags=cmd.get('required_hashtags'), expected_title=cmd.get('expected_title'))
                if cmd.get('evidence_path'):
                    page.screenshot(path=cmd['evidence_path'], full_page=True)
                    evidence['screenshot'] = cmd['evidence_path']
                sys.stdout.write(json.dumps({'status': 'ok', 'evidence': evidence}, ensure_ascii=False) + '\n')

            elif action == "discover_published_work":
                from src.shared.published_work_discovery import discover_published_work
                evidence = discover_published_work(page, cmd['title'])
                sys.stdout.write(json.dumps({'status':'ok','evidence':evidence},ensure_ascii=False)+'\n')

            elif action == "ai_content_declaration":
                from src.platform_adapter.ai_content_declaration import set_ai_declaration, read_ai_declaration
                try:
                    evidence = set_ai_declaration(page) if cmd.get("set_selected") else read_ai_declaration(page)
                except Exception as exc:
                    evidence = {"verified": False, "reason": "AI 声明操作或提交状态未确认，已停止发布",
                                "error_type": type(exc).__name__}
                    try:
                        observed = read_ai_declaration(page)
                        evidence["observed_after_error"] = {"verified": observed.get("verified") is True,
                            "method": str(observed.get("method", ""))[:80]}
                    except Exception as read_exc:
                        evidence["read_error_type"] = type(read_exc).__name__
                if cmd.get("evidence_path"):
                    try:
                        page.screenshot(path=cmd["evidence_path"], full_page=True)
                        evidence["screenshot"] = cmd["evidence_path"]
                    except Exception as screenshot_exc:
                        evidence = {"verified": False, "reason": "AI 声明界面证据保存失败，已停止发布",
                                    "screenshot_error_type": type(screenshot_exc).__name__,
                                    "observed_before_screenshot": evidence}
                sys.stdout.write(json.dumps({"status": "ok", "evidence": evidence}, ensure_ascii=False) + "\n")

            elif action == "fanqie_identity":
                from src.platform_adapter.fanqie_identity import FanqieIdentityObserver
                observer = fanqie_identity_observers.get(tab_id)
                if observer is None:
                    observer = FanqieIdentityObserver(page)
                    fanqie_identity_observers[tab_id] = observer
                if cmd.get("reset"):
                    observer.reset()
                evidence = observer.observe()
                sys.stdout.write(json.dumps({"status": "ok", "evidence": evidence}) + "\n")

            elif action == "fanqie_promotion_observer":
                from src.platform_adapter.fanqie_promotion_observer_v1 import worker_action
                evidence = worker_action(page, fanqie_promotion_observers, tab_id,
                    mode=cmd.get("mode"), subject=cmd.get("subject"),
                    endpoint_paths=cmd.get("endpoint_paths"))
                sys.stdout.write(json.dumps({"status": "ok", "evidence": evidence}, ensure_ascii=False) + "\n")

            elif action == "inspect_feed_surface":
                from src.platform_adapter.feed_surface_diagnostic import inspect_worker_page
                evidence = inspect_worker_page(page)
                sys.stdout.write(json.dumps({"status": "ok", "evidence": evidence}, ensure_ascii=False) + "\n")

            elif action == "probe_douyin_challenge":
                from src.platform_adapter.douyin_challenge import probe_challenge_page
                evidence = probe_challenge_page(page)
                sys.stdout.write(json.dumps({"status": "ok", "evidence": evidence}) + "\n")

            elif action == "upload_check_proof":
                from src.shared.upload_check_transition import begin_upload_check, observe_upload_check
                operation = cmd.get("operation")
                if operation not in {"begin", "observe"}:
                    raise ValueError("unsupported upload proof operation")
                handler = begin_upload_check if operation == "begin" else observe_upload_check
                proof = handler(page, cmd.get("selection_nonce"))
                sys.stdout.write(json.dumps({"status": "ok", "proof": proof}) + "\n")

            elif action == "evaluate":
                idx = cmd.get("index", 0)
                if cmd.get("selector"):
                    val = page.locator(cmd["selector"]).nth(max(0, idx)).evaluate(cmd["js"])
                else:
                    val = page.evaluate(cmd["js"])
                sys.stdout.write(json.dumps({"status": "ok", "value": val}) + "\n")

            elif action == "screenshot":
                # 截图：selector="" 截整页；否则截指定元素
                out_path = cmd.get("path")
                if not out_path:
                    sys.stdout.write(json.dumps({"status": "error", "msg": "screenshot 需要 path 参数"}) + "\n")
                    continue
                full_page = bool(cmd.get("full_page", False))
                sel = cmd.get("selector", "")
                if sel:
                    page.locator(sel).first.screenshot(path=out_path)
                else:
                    page.screenshot(path=out_path, full_page=full_page)
                sys.stdout.write(json.dumps({"status": "ok", "path": out_path}) + "\n")

            elif action == "inner_text":
                txt = page.locator(cmd["selector"]).nth(max(0, cmd.get("index", 0))).inner_text().strip()
                sys.stdout.write(json.dumps({"status": "ok", "text": txt}) + "\n")

            elif action == "get_attribute":
                idx = cmd.get("index", 0)
                if idx >= 0:
                    value = page.locator(cmd["selector"]).nth(idx).get_attribute(cmd["name"])
                else:
                    value = page.locator(cmd["selector"]).first.get_attribute(cmd["name"])
                sys.stdout.write(json.dumps({"status": "ok", "value": value}) + "\n")

            elif action == "current_url":
                sys.stdout.write(json.dumps({"status": "ok", "url": page.url}) + "\n")

            elif action == "locator_all_text":
                texts = [e.inner_text().strip() for e in page.locator(cmd["selector"]).all()]
                sys.stdout.write(json.dumps({"status": "ok", "texts": texts}) + "\n")

            elif action == "save_state":
                from src.shared.browser_worker_state import checkpoint_open_login_pages as _checkpoint_open_login_pages
                saved = _checkpoint_open_login_pages(context, cmd['path'], {})
                sys.stdout.write(json.dumps({"status": "ok", "state_saved": saved}) + "\n")

            elif action == "save_visible_state":
                from src.shared.browser_worker_state import checkpoint_open_login_pages as _checkpoint_open_login_pages
                saved = _checkpoint_open_login_pages(context, cmd['path'], {})
                sys.stdout.write(json.dumps({"status": "ok", "state_saved": saved}) + "\n")

            elif action == "wait_for_close":
                from src.shared.browser_worker_state import checkpoint_open_login_pages as _checkpoint_open_login_pages
                timeout_sec = cmd.get("timeout", 1800)
                login_state_path = cmd.get("path") or storage_state_path
                login_origins = {}
                state_saved = False
                start = time.time()
                while time.time() - start < timeout_sec:
                    try:
                        pages = context.pages
                        if not pages or all(p.is_closed() for p in pages):
                            break
                        # Drive Playwright's event loop so user-initiated closes
                        # are observed. Preserve login state while the context
                        # is still alive; saving only after close is too late.
                        if login_state_path:
                            state_saved = _checkpoint_open_login_pages(
                                context, login_state_path, login_origins) or state_saved
                        next(p for p in pages if not p.is_closed()).wait_for_timeout(1000)
                    except Exception:
                        break
                sys.stdout.write(json.dumps({"status": "ok", "state_saved": state_saved}) + "\n")

            elif action == "api_download":
                from src.platform_adapter.browser_session import _download_binary_response
                summary = _download_binary_response(
                    context.request, cmd["url"], cmd["output_path"],
                    headers=cmd.get("headers"), timeout=cmd.get("timeout", 30000),
                    max_bytes=cmd.get("max_bytes", 256 * 1024 * 1024),
                    expected_content_types=cmd.get("expected_content_types"),
                    allowed_hosts=cmd.get("allowed_hosts"), max_redirects=cmd.get("max_redirects", 3),
                    overwrite=bool(cmd.get("overwrite", False)),
                )
                sys.stdout.write(json.dumps({"status": "ok", "download": summary}) + "\n")

            elif action == "api_request":
                req_url = cmd["url"]
                req_method = cmd.get("method", "GET")
                req_headers = cmd.get("headers", {})
                req_body = cmd.get("body")
                timeout_ms = cmd.get("timeout", 30000)
                if req_method.upper() == "POST":
                    resp = context.request.post(req_url, headers=req_headers, data=req_body, timeout=timeout_ms)
                else:
                    resp = context.request.get(req_url, headers=req_headers, timeout=timeout_ms)
                body_bytes = resp.body()
                sys.stdout.write(json.dumps({
                    "status": "ok",
                    "response": {
                        "status": resp.status,
                        "body": body_bytes.decode("utf-8") if isinstance(body_bytes, bytes) else body_bytes,
                        "text": resp.text(),
                    }
                }) + "\n")

            elif action == "type_hashtag":
                # One editor, an explicitly verified collapsed end caret, and
                # continuous native keyboard input. Locator.type/press each
                # refocus independently and can reset a Slate selection.
                selectors = cmd.get("selectors", [])
                tag = cmd.get("tag", "")
                import re
                if not isinstance(tag, str) or not re.fullmatch(r"\w+", tag):
                    raise ValueError("invalid hashtag name")

                editor = None
                for sel in selectors:
                    els = page.locator(sel)
                    cnt = els.count()
                    if cnt > 0:
                        editor = els.first
                        break

                if editor is None:
                    sys.stdout.write(json.dumps({"status": "error", "msg": "未找到简介编辑器"}) + "\n")
                else:
                    from src.shared.hashtag_caret import HASHTAG_CARET_JS as caret
                    editor.focus()
                    page.keyboard.press("Control+End")
                    before = editor.evaluate(caret)
                    if not isinstance(before, dict) or before.get("ok") is not True:
                        raise RuntimeError("hashtag end selection could not be confirmed " +
                            json.dumps(before, ensure_ascii=True, separators=(",", ":")))
                    page.keyboard.type(" #" + tag)
                    after = editor.evaluate(caret)
                    if not isinstance(after, dict) or after.get("ok") is not True:
                        raise RuntimeError("hashtag end selection changed before commit " +
                            json.dumps(after, ensure_ascii=True, separators=(",", ":")))
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(500)
                    sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "stop":
                break

            else:
                sys.stdout.write(json.dumps({"status": "error", "msg": f"unknown action: {action}"}) + "\n")
        except Exception as exc:
            if action == "api_download" and type(exc).__name__ != "BinaryDownloadError":
                message = "binary download failed (" + type(exc).__name__ + ")"
            else:
                message = str(exc)
            sys.stdout.write(json.dumps({"status": "error", "msg": message}) + "\n")

        sys.stdout.flush()

    context.close()
    pw.stop()


def _guarded_main():
    try:
        main()
    except Exception as exc:
        # The original traceback includes browser launch argv and profile data.
        # Return only fixed categories before EOF so the parent can diagnose it.
        from src.shared.browser_startup_diagnostics import classify
        evidence = dict(classify(exc), stage=_last_stage)
        sys.stdout.write(json.dumps({'status': 'error', 'startup_evidence': evidence}) + '\n')
        sys.stdout.flush()
        # Keep this failed family observable until the parent captures and reaps
        # it. Exiting before that capture loses proof about inherited children.
        sys.stdin.readline()


if __name__ == "__main__":
    # 在独立线程中运行，避免 asyncio.run() 将事件循环标记为 is_running()
    # Playwright sync API 在检测到 is_running() == True 时会拒绝启动
    t = threading.Thread(target=_guarded_main, daemon=True)
    t.start()
    t.join()
"""


def _worker_script_path(cache_dir: Path | None = None) -> Path:
    """Materialize the authoritative worker without exceeding Windows argv limits.

    Publish complete UTF-8 bytes atomically; an existing content-addressed file is
    evidence, never silently repaired or overwritten.
    """
    payload = _PW_SCRIPT.encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    directory = cache_dir or Path(__file__).resolve().parents[2] / 'data/browser_worker_cache'
    directory = Path(directory)
    if directory.is_symlink():
        raise RuntimeError('browser_worker_cache_symlink')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory.resolve() / (digest + '.py')
    if not target.exists():
        fd, temporary = tempfile.mkstemp(prefix='.worker-', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass  # Another starter published; verify its exact bytes below.
        finally:
            Path(temporary).unlink(missing_ok=True)
    if target.is_symlink() or target.read_bytes() != payload:
        raise RuntimeError('browser_worker_cache_integrity_mismatch')
    return target


# ─── 纯辅助函数（从 _PW_SCRIPT 逻辑中提取，供测试使用）──────────────────


def _sanitize_cookies_for_add(cookies: list[dict]) -> list[dict]:
    """Pure helper: strip unsupported fields from cookies before add_cookies().

    Extracted for testability -- mirrors the logic inside _PW_SCRIPT.
    """
    _allowed = {"name", "value", "url", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
    result = []
    for _c in cookies:
        result.append({_k: _v for _k, _v in _c.items() if _k in _allowed})
    return result


def _build_storage_state_init_script(origins: list[dict]) -> str | None:
    """Pure helper: build a JS init script that restores localStorage per exact origin.

    Returns None if origins contain no usable localStorage entries.
    Extracted for testability -- mirrors the logic inside _PW_SCRIPT.
    """
    origin_map: dict[str, dict[str, str]] = {}
    for _o in origins:
        _on = _o.get("origin", "")
        _ls = _o.get("localStorage", [])
        if _on and _ls:
            _entries: dict[str, str] = {}
            for _li in _ls:
                if "name" in _li and "value" in _li:
                    _entries[_li["name"]] = _li["value"]
            if _entries:
                origin_map[_on] = _entries
    if not origin_map:
        return None
    return (
        "(function(){"
        "var _m=" + json.dumps(origin_map) + ";"
        "var _d=_m[window.location.origin];"
        "if(_d){for(var _k in _d){try{if(localStorage.getItem(_k)===null){localStorage.setItem(_k,_d[_k]);}}catch(_e){}}}"
        "})()"
    )


def build_default_browser_session_config() -> BrowserSessionConfig:
    return BrowserSessionConfig(
        base_url=settings.DOUYIN_CREATOR_BASE_URL,
        home_url=settings.DOUYIN_HOME_URL,
        storage_state_path=settings.DOUYIN_STORAGE_STATE_PATH,
        user_data_dir=settings.DOUYIN_USER_DATA_DIR,
        browser_channel=settings.BROWSER_CHANNEL,
        headless=settings.BROWSER_HEADLESS,
        slow_mo_ms=settings.BROWSER_SLOW_MO_MS,
        timeout_ms=settings.BROWSER_TIMEOUT_MS,
    )


class BrowserSession:
    def __init__(self, config: BrowserSessionConfig | None = None):
        self.config = config or build_default_browser_session_config()
        self.active = False
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._worker_stage = "not_started"
        self._default_tab_id: str | None = None

    def start(self) -> SessionState:
        self._ensure_runtime_paths()
        self.active = True
        logger.info(
            "Browser session prepared: "
            f"base_url={self.config.base_url}, "
            f"headless={self.config.headless}, "
            f"storage_state={self.config.storage_state_path}"
        )
        return self.get_state()

    def get_state(self) -> SessionState:
        return SessionState(
            active=self.active,
            authenticated=self.is_authenticated(),
            base_url=self.config.base_url,
            storage_state_path=self.config.storage_state_path,
            user_data_dir=self.config.user_data_dir,
        )

    def is_authenticated(self) -> bool:
        user_data = Path(self.config.user_data_dir)
        return user_data.exists() and any(user_data.iterdir()) if user_data.exists() else False

    def require_authenticated(self) -> None:
        if not self.is_authenticated():
            raise RuntimeError(
                "未检测到可用登录态，请先完成抖音创作者后台登录并保存 storage state。"
            )

    def open_for_manual_login(
        self,
        url: str | None = None,
        pause_seconds: int = 600,
        wait_for_enter: bool = False,
    ) -> SessionState:
        target_url = (url or self.config.home_url).strip()
        if not target_url:
            raise RuntimeError("缺少目标登录地址。")

        self._start()
        self._send({"action": "goto", "url": target_url})
        logger.info(
            f"浏览器已打开并停留在目标页面。 url={target_url}, user_data_dir={self.config.user_data_dir}"
        )

        try:
            if wait_for_enter:
                input("浏览器已暂停，完成查看或登录后按回车继续...")
            elif pause_seconds > 0:
                logger.info(f"浏览器将保持打开 {pause_seconds} 秒。")
                time.sleep(pause_seconds)

            self.save_storage_state()
            return self.get_state()
        finally:
            self.stop()

    def open_for_manual_login_until_closed(
        self,
        url: str | None = None,
        timeout_seconds: int = 1800,
        *,
        on_opened: Callable[[], None] | None = None,
    ) -> SessionState:
        target_url = (url or self.config.home_url).strip()
        if not target_url:
            raise RuntimeError("缺少目标登录地址。")

        self.config.headless = False
        try:
            self._start()
            self._send({"action": "goto", "url": target_url})
            logger.info("browser_manual_window stage=page_opened_waiting_close")
            if on_opened is not None:
                on_opened()
            result = self._send({"action": "wait_for_close", "timeout": timeout_seconds,
                                 "path": self.config.storage_state_path})
            if result.get("state_saved"):
                logger.info("登录窗口状态已保存。")
            else:
                logger.warning("登录窗口关闭前未能导出状态，已保留浏览器用户目录登录态。")
            return self.get_state()
        finally:
            self.stop()

    def open_page_and_click_button(
        self,
        url: str,
        button_text: str,
        pause_seconds: int = 600,
        wait_for_enter: bool = False,
    ) -> SessionState:
        target_url = url.strip()
        if not target_url:
            raise RuntimeError("缺少目标页面地址。")
        if not button_text.strip():
            raise RuntimeError("缺少按钮文本。")

        self._start()
        self._send({"action": "goto", "url": target_url})
        logger.info(f"浏览器已打开目标页面: {target_url}")

        # 点击按钮
        self._send({"action": "locator_filter_text", "selector": "button", "text": button_text})
        logger.info(f"已点击按钮: {button_text}")

        try:
            if wait_for_enter:
                input("浏览器已暂停，完成查看后按回车继续...")
            elif pause_seconds > 0:
                logger.info(f"浏览器将保持打开 {pause_seconds} 秒。")
                time.sleep(pause_seconds)

            self.save_storage_state()
            return self.get_state()
        finally:
            self.stop()

    # Harness Engineering Layer 5: 约束与安全 — 浏览器域名白名单
    # 只允许访问 KOL 运营相关的域，防止 LLM 误调用到其他域
    _ALLOWED_DOMAINS = (
        "kol.fanqieopen.com",       # 番茄达人中心
        "fanqienovel.com",          # 番茄小说主站（search API）
        "creator.douyin.com",       # 抖音创作者中心
        "www.douyin.com",           # 抖音主站
        "127.0.0.1",                # 本地（开发用）
        "localhost",
    )

    def _check_domain_allowed(self, url: str) -> None:
        """域名白名单检查。失败抛 PermissionError（被 SkillRegistry 捕获为 skill_error）。"""
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if not host:
            raise PermissionError(f"浏览器沙箱：URL 无效域名 ({url})")
        for allowed in self._ALLOWED_DOMAINS:
            if host == allowed or host.endswith("." + allowed):
                return
        raise PermissionError(
            f"浏览器沙箱：禁止访问 {host}（白名单：{', '.join(self._ALLOWED_DOMAINS)}）"
        )

    def open_page(self, url: str) -> "Page":
        """打开指定 URL，返回兼容 Page 对象（命令转发器）

        Harness Engineering Layer 5: 域名白名单检查。
        """
        self._start()
        self._check_domain_allowed(url)
        page = Page(self)
        try:
            result = self._send({"action": "goto", "url": url})
        except BrowserNavigationTimeout as exc:
            exc.page = page
            raise
        page.url = result.get("url", url)
        return page

    def save_storage_state(self) -> None:
        if self._proc is None or self._closed:
            return
        self._send({"action": "save_state", "path": self.config.storage_state_path})
        logger.info(f"登录态已保存到: {self.config.storage_state_path}")

    def new_tab(self, role: str) -> "Page":
        """Create a task-owned Page in this owner's existing context."""
        if not isinstance(role, str) or not role.strip() or len(role) > 80:
            raise ValueError("tab role must be a nonempty string of at most 80 characters")
        with self._lock:
            self._start()
            result = self._send({"action": "new_tab", "role": role})
        return Page(self, tab_id=result["tab_id"])

    def list_tabs(self) -> list[dict]:
        """Read existing tabs; this never starts a new browser."""
        return self.cmd("list_tabs")["tabs"]

    def get_page(self, tab_id: str | None = None) -> "Page":
        with self._lock:
            self._start()
            selected = self._default_tab_id if tab_id is None else tab_id
            tabs = self._send({"action": "list_tabs"})["tabs"]
            if not any(item["tab_id"] == selected and not item["closed"] for item in tabs):
                raise RuntimeError("browser tab is missing or closed")
        return Page(self, tab_id=selected)

    def close_tab(self, tab_id: str) -> dict:
        """Close only the named tab, retaining other task pages and context."""
        return self.cmd("close_tab", tab_id=tab_id)

    def window_status(self) -> dict:
        """Short RPC. A missing/unknown worker raises; it is never called closed."""
        return self.cmd("window_status")

    def worker_failure(self) -> str:
        """Local process evidence only; never starts or restarts a browser."""
        if self._closed:
            return "response_channel_closed"
        if self._proc is not None and self._proc.poll() is not None:
            return "worker_exited"
        return ""

    # ─── 内部方法（供 Page 包装器调用）──────────────────────────────

    def cmd(self, action: str, **kwargs) -> dict:
        """发送命令到 Playwright 子进程并返回结果"""
        with self._lock:
            return self._send({**kwargs, "action": action})

    def _start(self) -> None:
        if self.worker_failure():
            raise BrowserWorkerUnavailable("原浏览器worker已失效；需在任务结清后由管控层回收。")
        if self._proc is not None:
            return
        self._ensure_runtime_paths()

        started = time.monotonic()
        self._worker_stage = "spawning_worker"
        self._startup_cleanup_verified = False
        self._startup_evidence = {'code': 'unknown', 'ready_received': False}
        startup_seconds = max(45.0, float(self.config.timeout_ms) / 1000.0 + 15.0)
        logger.info("browser_worker_start stage=spawning_worker timeout_seconds={}", startup_seconds)
        init = {
            "user_data_dir": self.config.user_data_dir,
            "headless": self.config.headless,
            "mute_audio": bool(getattr(self.config, "mute_audio", False)),
            "start_minimized": bool(getattr(self.config, "start_minimized", False)),
            "slow_mo": self.config.slow_mo_ms,
            "timeout_ms": self.config.timeout_ms,
            "channel": self.config.browser_channel or self._detect_browser_channel(),
            "chromium_sandbox": self.config.chromium_sandbox,
            "storage_state_path": self.config.storage_state_path,
            "python_paths": self._child_python_paths(),
        }
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-S", str(_worker_script_path())],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self._build_child_env(),
                # Hide the worker console even when invoked from python.exe.
                # This does not hide the explicit headless=False repair browser.
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            threading.Thread(target=self._read_worker_stages, args=(self._proc,), daemon=True).start()
            self._proc.stdin.write(json.dumps(init).encode())
            self._proc.stdin.write(b"\n")
            self._proc.stdin.flush()
            resp = self._read_child_line(startup_seconds, label="start")
            if not resp:
                raise BrowserWorkerStartupError(self._worker_stage)
            result = json.loads(resp)
            if not isinstance(result, dict):
                raise BrowserWorkerStartupError(self._worker_stage)
            if result.get("status") != "ready":
                from src.shared.browser_startup_diagnostics import clean
                self._startup_evidence.update(clean(result.get('startup_evidence')))
                if self._startup_evidence.get('stage'):
                    self._worker_stage = self._startup_evidence['stage']
                raise BrowserWorkerStartupError(self._worker_stage)
            protocol = result.get('supervision_protocol', 0)
            if type(protocol) is not int or protocol not in (0, 1):
                raise BrowserWorkerStartupError(self._worker_stage)
            self._supervision_protocol = protocol
            self._default_tab_id = result.get("default_tab_id")
        except TimeoutError as exc:
            stage = self._worker_stage
            self._discard_starting_worker()
            logger.warning("browser_worker_start stage={} outcome=timeout elapsed_ms={}", stage, round((time.monotonic()-started)*1000))
            failure = BrowserWorkerStartupTimeout(stage, startup_seconds)
            failure.startup_evidence = self._startup_failure_evidence(stage, 'startup_timeout')
            raise failure from exc
        except Exception as exc:
            stage = self._worker_stage
            self._discard_starting_worker()
            logger.warning("browser_worker_start stage={} outcome=failed error_type={} elapsed_ms={}",
                stage, type(exc).__name__, round((time.monotonic()-started)*1000))
            failure = exc if isinstance(exc, BrowserWorkerStartupError) else BrowserWorkerStartupError(stage)
            failure.startup_evidence = self._startup_failure_evidence(stage)
            if failure is exc:
                raise
            raise failure from exc

        if result.get("restored_cookies"):
            logger.info(
                "storage_state 已加载: "
                f"cookies={result['restored_cookies']} "
                f"(domains: {result.get('restored_cookie_domains', [])}), "
                f"origins={result.get('restored_origins', 0)} "
                f"(names: {result.get('restored_origin_names', [])})"
            )

        self.active = True
        self._worker_stage = "ready"
        logger.info("browser_worker_start stage=ready elapsed_ms={}", round((time.monotonic()-started)*1000))

    def _startup_failure_evidence(self, stage, code=None):
        from src.shared.browser_startup_diagnostics import clean
        evidence = dict(self._startup_evidence, stage=stage,
                        cleanup_verified=self._startup_cleanup_verified, ready_received=False)
        if code:
            evidence['code'] = code
        evidence.update(getattr(self, '_startup_process_evidence', {}))
        evidence = clean(evidence)
        self._startup_evidence = evidence
        logger.warning('browser_worker_start failure_evidence={}', json.dumps(evidence, sort_keys=True))
        return evidence

    def _read_worker_stages(self, process) -> None:
        allowed = {"importing_playwright", "starting_driver", "launching_browser", "restoring_state", "ready"}
        try:
            for line in process.stderr:
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict) and isinstance(event.get('browser_driver_diagnostics'), dict):
                    from src.shared.browser_startup_diagnostics import clean
                    facts=clean(event['browser_driver_diagnostics'])
                    current=getattr(self,'_startup_evidence',{})
                    self._startup_evidence=dict(current,**{k:v for k,v in facts.items() if k!='code'})
                    continue
                if not isinstance(event, dict) or event.get("browser_worker_stage") not in allowed:
                    continue
                elapsed = event.get("elapsed_ms")
                if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not 0 <= elapsed <= 86_400_000:
                    continue
                if self._proc is not process:
                    return
                self._worker_stage = event["browser_worker_stage"]
                logger.info("browser_worker_start stage={} worker_elapsed_ms={}", self._worker_stage, elapsed)
        except (OSError, ValueError, TypeError):
            return

    def _discard_starting_worker(self) -> None:
        process = self._proc
        self._startup_process_evidence = {}
        self._startup_cleanup_verified = False
        descendants = None
        if process is not None:
            try:
                import psutil
                descendants = psutil.Process(process.pid).children(recursive=True)
                from src.shared.browser_startup_diagnostics import child_driver_facts
                self._startup_process_evidence.update(child_driver_facts(descendants))
            except psutil.NoSuchProcess:
                descendants = None  # Parent exit alone cannot rule out orphaned children.
            except Exception:
                descendants = None
        self._closed = True
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            if descendants is not None:
                # Only this not-yet-ready worker's captured descendants, never
                # unrelated account windows or a process-name-wide kill.
                for child in reversed(descendants):
                    try:
                        if child.is_running():child.kill()
                    except psutil.NoSuchProcess:
                        pass
                    except Exception:
                        pass
                try:
                    _, alive = psutil.wait_procs(descendants, timeout=5)
                    self._startup_cleanup_verified = process.poll() is not None and not alive
                except Exception:
                    self._startup_cleanup_verified = False
            # A reader holds BufferedReader's lock until EOF. Closing its pipe
            # before reaping an inherited driver pipe can hang forever. Reap
            # captured children first, then bound stream closure as well. An
            # unproven child family keeps cleanup_verified=False for the host.
            for pipe in (process.stdin, process.stdout, process.stderr):
                def close_stream(stream=pipe):
                    try:
                        stream.close()
                    except Exception:
                        pass
                closer = threading.Thread(target=close_stream, daemon=True,
                                          name='BrowserStartupPipeCloser')
                closer.start()
                closer.join(timeout=.1)
        else:
            self._startup_cleanup_verified = True
        self._proc = None
        if process is not None:
            self._startup_process_evidence.update(worker_pid=getattr(process, 'pid', None),
                worker_exit_code=process.poll() if callable(getattr(process, 'poll', None)) else None)
        self.active = False
        self._default_tab_id = None
        self._closed = False

    def _send(self, cmd: dict) -> dict:
        """发送 JSON 命令到子进程，返回解析后的响应"""
        if self._proc is None or self._closed:
            raise BrowserWorkerUnavailable("Playwright 子进程未运行")

        msg = json.dumps(cmd).encode()
        self._proc.stdin.write(msg + b"\n")
        self._proc.stdin.flush()

        resp = self._read_child_line(
            self._response_timeout_seconds(cmd),
            label=str(cmd.get("action") or "unknown"),
        )
        if not resp:
            raise RuntimeError("Playwright 子进程已终止")
        result = json.loads(resp)
        if result.get("status") == "error":
            if result.get('code') == 'browser_navigation_timeout':
                raise BrowserNavigationTimeout(result.get('navigation_evidence'))
            raise RuntimeError(_sanitize_browser_error_message(result.get("msg")))
        return result

    def _read_child_line(self, timeout_seconds: float, *, label: str) -> bytes:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("Playwright 子进程未运行")
        process = self._proc
        response_queue: queue.Queue[bytes] = queue.Queue(maxsize=1)
        def read_line():
            try:
                response_queue.put(process.stdout.readline())
            except (OSError, ValueError):
                response_queue.put(b"")
        reader = threading.Thread(target=read_line, daemon=True)
        reader.start()
        try:
            return response_queue.get(timeout=max(1.0, timeout_seconds))
        except queue.Empty as exc:
            self._closed = True
            if label != 'start':
                try:
                    process.kill()
                except Exception:
                    pass
            # Startup owns a scoped descendant cleanup. Killing its parent
            # here would orphan the driver before that family can be captured.
            raise TimeoutError(f"浏览器命令 {label} 等待响应超时。") from exc

    def _response_timeout_seconds(self, cmd: dict) -> float:
        action = str(cmd.get("action") or "")
        if action in {"window_status", "list_tabs"}:
            return 5.0
        if action == "wait_for_close":
            return max(15.0, float(cmd.get("timeout") or 0) + 15.0)
        if action == "wait_for_timeout":
            return max(15.0, float(cmd.get("ms") or 0) / 1000.0 + 15.0)
        timeout_ms = cmd.get("timeout", self.config.timeout_ms)
        try:
            timeout_seconds = float(timeout_ms) / 1000.0
        except (TypeError, ValueError):
            timeout_seconds = float(self.config.timeout_ms) / 1000.0
        return max(15.0, timeout_seconds + 15.0)

    def _ensure_runtime_paths(self) -> None:
        storage_state = Path(self.config.storage_state_path)
        user_data_dir = Path(self.config.user_data_dir)
        if storage_state.parent:
            storage_state.parent.mkdir(parents=True, exist_ok=True)
        user_data_dir.mkdir(parents=True, exist_ok=True)

    def _build_child_env(self) -> dict:
        env = os.environ.copy()
        # The interactive account can have an unusable inherited Windows TEMP
        # (EPERM from Playwright mkdtemp). Use a distinct project-owned scratch
        # directory for this worker family, without changing system ACLs/TEMP.
        root = Path(__file__).resolve().parents[2]
        # .local_py precedes the venv for optional Python dependencies. Its
        # bundled node.exe can inherit a Low integrity label and then drag the
        # browser down to Low as well. Use the installed project venv runtime;
        # do not relabel executables or user profile directories. Explicit
        # administrator/user configuration keeps precedence.
        project_node = root / '.venv/Lib/site-packages/playwright/driver/node.exe'
        if sys.platform == 'win32' and project_node.is_file():
            env.setdefault('PLAYWRIGHT_NODEJS_PATH', str(project_node))
        scratch = root / 'data/browser_runtime/temporary'
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.mkdtemp(prefix='worker_', dir=scratch)
        env['TEMP'] = env['TMP'] = env['TMPDIR'] = temporary
        env["PYTHONPATH"] = os.pathsep.join(self._child_python_paths())
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYDANTIC_DISABLE_PLUGINS"] = "__all__"
        return env

    def _child_python_paths(self) -> list[str]:
        root = Path(__file__).resolve().parents[2]
        candidates = [root / ".local_py" / "site-packages", root / ".venv" / "Lib" / "site-packages",
            Path(sys.prefix) / "Lib" / "site-packages",
            Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages", root]
        paths = []
        for candidate in candidates:
            value = str(candidate.resolve())
            if candidate.is_dir() and value not in paths:
                paths.append(value)
        return paths

    def _detect_browser_channel(self) -> str:
        chrome_paths = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
        if any(path.exists() for path in chrome_paths):
            return "chrome"

        edge_paths = [
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ]
        if any(path.exists() for path in edge_paths):
            return "msedge"

        return ""

    def stop(self) -> None:
        if self._proc is None:
            return

        try:
            self._send({"action": "stop"})
        except Exception:
            pass

        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()

        self._proc = None
        self._closed = False
        self._default_tab_id = None
        if self.active:
            logger.info("Browser session stopped.")
        self.active = False


# ─── Page 包装器（把 Playwright Page API 调用转发到子进程）───────────────


class Page:
    """将 Playwright Page API 转发到子进程调用的 Page 对象"""

    def __init__(self, session: BrowserSession, tab_id: str | None = None):
        self._session = session
        self._url: str = ""
        self.tab_id = (tab_id if tab_id is not None else
            getattr(session, "tab_id", None) or getattr(session, "_default_tab_id", None))

    def _cmd(self, action: str, **kwargs) -> dict:
        if self.tab_id is not None:
            kwargs["tab_id"] = self.tab_id
        return self._session.cmd(action, **kwargs)

    @property
    def url(self) -> str:
        try:
            result = self._cmd("current_url")
            self._url = result.get("url", self._url)
        except Exception:
            pass
        return self._url

    @url.setter
    def url(self, value: str) -> None:
        self._url = value

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> None:
        if wait_until not in {'commit', 'domcontentloaded', 'load', 'networkidle'}:
            raise ValueError('Invalid navigation wait condition')
        try:
            result = self._cmd("goto", url=url, timeout=timeout, wait_until=wait_until)
        except BrowserNavigationTimeout as exc:
            exc.page = self
            raise
        self.url = result.get("url", url)

    def wait_for_load_state(self, state: str, timeout: int = 30000) -> None:
        # domcontentloaded 已在 goto 时等待
        pass

    def evaluate(self, js: str) -> Any:
        result = self._cmd("evaluate", selector="", js=js, index=-1)
        return result.get("value")

    def upload_check_proof(self, operation: str, selection_nonce: str) -> dict:
        """Read-only upload UI transition in this exact worker Page."""
        return self._cmd("upload_check_proof", operation=operation,
            selection_nonce=selection_nonce).get("proof", {})

    def probe_douyin_challenge(self) -> dict:
        return self._cmd("probe_douyin_challenge").get("evidence", {})

    def fanqie_promotion_observer(self, mode: str, *, subject=None,
                                  endpoint_paths=None) -> dict:
        """Opt-in passive metadata discovery on this exact worker Page."""
        if mode not in {'resources', 'arm', 'snapshot', 'stop'}:
            raise ValueError('Invalid promotion observer mode')
        return self._cmd('fanqie_promotion_observer', mode=mode, subject=subject,
                         endpoint_paths=endpoint_paths).get('evidence', {})

    def wait_for_selector(self, selector: str, timeout: int = 30000) -> "Page":
        self._cmd("wait_for_selector", selector=selector, timeout=timeout)
        return self

    def wait_for_timeout(self, ms: int) -> None:
        self._cmd("wait_for_timeout", ms=ms)

    def locator(self, selector: str) -> "_Locator":
        return _Locator(self._session, selector, tab_id=self.tab_id)

    def click_button_by_text(self, texts: list[str]) -> dict:
        return self._cmd("click_button_by_text", texts=texts)

    def ai_content_declaration(self, *, set_selected=False, evidence_path=None) -> dict:
        return self._cmd("ai_content_declaration", set_selected=set_selected,
                                 evidence_path=evidence_path).get("evidence", {})

    def inspect_published_video(self, post_id, *, ai_required, fiction_required, evidence_path=None,
                                required_hashtags=None, expected_title=None):
        return self._cmd('inspect_published_video', post_id=post_id,
                                 ai_required=ai_required, fiction_required=fiction_required,
                                 evidence_path=evidence_path, required_hashtags=required_hashtags,
                                 expected_title=expected_title).get('evidence', {})

    def discover_published_work(self, title):
        return self._cmd('discover_published_work',title=title).get('evidence',{})

    def interact_visible_exact_text(
        self,
        text: str,
        *,
        operation: str = "inspect",
        prefer_parent: bool = False,
    ) -> bool:
        """Inspect, hover, or click the last visible exact-text match."""
        result = self._cmd(
            "interact_visible_exact_text",
            text=text,
            operation=operation,
            prefer_parent=prefer_parent,
        )
        return bool(result.get("matched"))

    @property
    def request(self) -> "APIRequestContext":
        return APIRequestContext(self._session)

    @property
    def inner_text(self) -> str:
        return ""

    def first(self) -> "_Locator":
        return _Locator(self._session, "", tab_id=self.tab_id)


class _Locator:
    """部分 Playwright Locator API 转发"""

    def __init__(self, session: BrowserSession, selector: str, index: int = -1,
                 tab_id: str | None = None):
        self._session = session
        self._selector = selector
        self._index = index
        self.tab_id = tab_id

    def _cmd(self, action: str, **kwargs) -> dict:
        if self.tab_id is not None:
            kwargs["tab_id"] = self.tab_id
        return self._session.cmd(action, **kwargs)

    def count(self) -> int:
        result = self._cmd("locator_count", selector=self._selector)
        return result.get("count", 0)

    def first(self) -> "_Locator":
        return _Locator(self._session, self._selector, index=0, tab_id=self.tab_id)

    def nth(self, n: int) -> "_Locator":
        """返回第 n 个匹配元素（下标从 0 开始）"""
        return _Locator(self._session, self._selector, index=n, tab_id=self.tab_id)

    def fill(self, value: str) -> None:
        self._cmd("fill", selector=self._selector, value=value, index=self._index)

    def click(self, *, force: bool = False, timeout: int = 30000) -> None:
        self._cmd(
            "click", selector=self._selector, index=self._index,
            force=force, timeout=timeout,
        )

    def hover(self, *, force: bool = False, timeout: int = 30000) -> None:
        self._cmd(
            "hover", selector=self._selector, index=self._index,
            force=force, timeout=timeout,
        )

    def inner_text(self) -> str:
        result = self._cmd("inner_text", selector=self._selector, index=self._index)
        return result.get("text", "")

    def get_attribute(self, name: str) -> str | None:
        result = self._cmd(
            "get_attribute",
            selector=self._selector,
            index=self._index,
            name=name,
        )
        return result.get("value")

    def set_input_files(self, file_path: str) -> None:
        idx = self._index if self._index >= 0 else 0
        self._cmd("set_input_files", selector=self._selector, file_path=file_path, index=idx)

    def filter(self, has_text: str = "", **kwargs) -> "_Locator":
        """支持 filter(has_text='...')"""
        if has_text:
            self._cmd("locator_filter_text", selector=self._selector, text=has_text)
        return self

    def all(self):
        result = self._cmd("locator_all_text", selector=self._selector)
        return [_FakeElement(t) for t in result.get("texts", [])]

    def press(self, key: str) -> None:
        """键盘按键（支持 Enter、End 等）"""
        self._cmd("press", selector=self._selector, key=key, index=self._index)

    def type(self, text: str) -> None:
        """输入文本（追加到当前内容）"""
        self._cmd("type_text", selector=self._selector, text=text, index=self._index)

    def type_hashtag(self, tag: str, selectors: list[str] = None) -> None:
        """
        原子操作：定位简介编辑器，一次性完成 click→End→type→Enter 全流程。
        避免多次查 DOM 时 placeholder selector 失效的问题。
        """
        self._cmd(
            "type_hashtag",
            selectors=selectors or [self._selector],
            tag=tag,
        )

    def evaluate(self, js: str) -> Any:
        """执行 JavaScript"""
        result = self._cmd("evaluate", selector=self._selector, js=js, index=self._index)
        return result.get("value")


class _FakeElement:
    def __init__(self, text: str):
        self._text = text

    def inner_text(self) -> str:
        return self._text


class APIResponse:
    """Playwright APIResponse 的兼容包装"""

    def __init__(self, session: BrowserSession, response_data: dict):
        self._session = session
        self._data = response_data

    @property
    def status(self) -> int:
        return self._data.get("status", 0)

    def json(self):
        import json as _json
        return _json.loads(self._data.get("body", "{}"))

    @property
    def text(self) -> str:
        return self._data.get("text", "")

    def body(self) -> bytes:
        body_str = self._data.get("body", "")
        if isinstance(body_str, str):
            return body_str.encode("utf-8")
        return body_str


class APIRequestContext:
    """
    Playwright APIRequestContext 的兼容包装（复用浏览器 context 的认证 cookies）。
    支持 get / post 方法，响应为 APIResponse。
    """

    def __init__(self, session: BrowserSession):
        self._session = session

    def get(self, url: str, headers: dict = None, timeout: int = 30000) -> APIResponse:
        for attempt in range(2):
            try:
                result = self._session.cmd(
                    "api_request",
                    url=url,
                    method="GET",
                    headers=headers or {},
                    timeout=timeout,
                )
                break
            except RuntimeError as exc:
                if attempt or not any(term in str(exc).lower() for term in (
                    "socket disconnected", "connection reset", "timed out", "timeout",
                )):
                    raise
                time.sleep(1)
        return APIResponse(self._session, result.get("response", {}))

    def post(self, url: str, headers: dict = None, data: str = None, timeout: int = 30000) -> APIResponse:
        result = self._session.cmd(
            "api_request",
            url=url,
            method="POST",
            headers=headers or {},
            body=data,
            timeout=timeout,
        )
        return APIResponse(self._session, result.get("response", {}))

    def download(self, url: str, output_path: str | Path, headers: dict | None = None,
                 timeout: int = 30000, *, max_bytes: int = 256 * 1024 * 1024,
                 expected_content_types: list[str] | None = None,
                 allowed_hosts: list[str] | None = None, max_redirects: int = 3,
                 overwrite: bool = False) -> dict:
        """Save binary bytes in the existing authenticated subprocess.

        final_url in the returned summary is redacted; final_url_sha256 binds
        the complete actual URL. The old get/post text interface is unchanged.
        """
        target = _download_target(output_path)
        result = self._session.cmd(
            "api_download", url=url, output_path=str(target), headers=headers or {}, timeout=timeout,
            max_bytes=max_bytes, expected_content_types=expected_content_types,
            allowed_hosts=allowed_hosts, max_redirects=max_redirects, overwrite=overwrite,
        )
        return result.get("download", {})
