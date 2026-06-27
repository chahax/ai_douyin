"""
browser_session.py — Playwright 浏览器会话管理

使用独立子进程运行 Playwright 浏览器，解决 Python 3.14 Windows
WindowsSelectorEventLoop / ProactorEventLoop 不支持 subprocess_exec 的问题。
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from src.platform_adapter.models import BrowserSessionConfig, SessionState
from src.shared.config import settings
from src.shared.logger import logger


# ─── 子进程 bootstrap（独立 Python 进程，无 Streamlit 事件循环）──────────────
# 关键：不用 asyncio.run()，避免 Playwright sync API 报错
# "using Sync API inside asyncio loop"

_PW_SCRIPT = r"""
import json
import sys
import threading
import time


def main():
    init_line = sys.stdin.readline()
    if not init_line:
        return
    init = json.loads(init_line)

    user_data_dir = init.get("user_data_dir", "")
    headless = init.get("headless", False)
    slow_mo = init.get("slow_mo", 0)
    timeout_ms = init.get("timeout_ms", 30000)
    channel = init.get("channel", "")
    chromium_sandbox = init.get("chromium_sandbox", False)

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    kwargs = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "slow_mo": slow_mo,
    }
    if channel:
        kwargs["channel"] = channel
    if chromium_sandbox:
        kwargs["chromium_sandbox"] = True

    context = pw.chromium.launch_persistent_context(**kwargs)
    context.set_default_timeout(timeout_ms)
    page = context.pages[0] if context.pages else context.new_page()

    # 确认就绪
    sys.stdout.write(json.dumps({"status": "ready"}) + "\n")
    sys.stdout.flush()

    # 主循环：处理命令
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        cmd = json.loads(line)
        action = cmd.get("action", "")

        try:
            if action == "goto":
                page.goto(cmd["url"], wait_until="domcontentloaded", timeout=timeout_ms)
                sys.stdout.write(json.dumps({"status": "ok", "url": page.url}) + "\n")

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
                if idx >= 0:
                    page.locator(cmd["selector"]).nth(idx).click()
                else:
                    page.locator(cmd["selector"]).first.click()
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

            elif action == "evaluate":
                idx = cmd.get("index", 0)
                if idx >= 0:
                    val = page.locator(cmd["selector"]).nth(idx).evaluate(cmd["js"])
                else:
                    val = page.evaluate(cmd["js"])
                sys.stdout.write(json.dumps({"status": "ok", "value": val}) + "\n")

            elif action == "inner_text":
                txt = page.locator(cmd["selector"]).first.inner_text().strip()
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
                context.storage_state(path=cmd.get("path", ""))
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "wait_for_close":
                timeout_sec = cmd.get("timeout", 1800)
                start = time.time()
                while time.time() - start < timeout_sec:
                    try:
                        pages = context.pages
                        if not pages or all(p.is_closed() for p in pages):
                            break
                    except Exception:
                        break
                    time.sleep(1)
                sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

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
                # 原子操作：一次定位 + 连续键盘动作（避免 DOM 重渲染导致后续操作失败）
                selectors = cmd.get("selectors", [])
                tag = cmd.get("tag", "")
                timeout_ms = cmd.get("timeout", 30000)

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
                    # 连续执行多个键盘操作，中间不重新查 DOM
                    editor.click()
                    editor.press("End")
                    editor.type(" #" + tag)
                    editor.press("Enter")
                    page.wait_for_timeout(500)
                    sys.stdout.write(json.dumps({"status": "ok"}) + "\n")

            elif action == "stop":
                break

            else:
                sys.stdout.write(json.dumps({"status": "error", "msg": f"unknown action: {action}"}) + "\n")
        except Exception as exc:
            sys.stdout.write(json.dumps({"status": "error", "msg": str(exc)}) + "\n")

        sys.stdout.flush()

    context.close()
    pw.stop()


if __name__ == "__main__":
    # 在独立线程中运行，避免 asyncio.run() 将事件循环标记为 is_running()
    # Playwright sync API 在检测到 is_running() == True 时会拒绝启动
    t = threading.Thread(target=main, daemon=True)
    t.start()
    t.join()
"""


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
    ) -> SessionState:
        target_url = (url or self.config.home_url).strip()
        if not target_url:
            raise RuntimeError("缺少目标登录地址。")

        self.config.headless = False
        self._start()
        self._send({"action": "goto", "url": target_url})
        logger.info(
            "抖音登录窗口已打开，用户关闭浏览器窗口后视为登录流程结束。 "
            f"url={target_url}, user_data_dir={self.config.user_data_dir}"
        )

        try:
            self._send({"action": "wait_for_close", "timeout": timeout_seconds})
            try:
                self.save_storage_state()
            except Exception as exc:
                logger.warning(f"保存 storage_state 失败，已保留浏览器用户目录登录态: {exc}")
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

    def open_page(self, url: str) -> "Page":
        """打开指定 URL，返回兼容 Page 对象（命令转发器）"""
        self._start()
        result = self._send({"action": "goto", "url": url})
        page = Page(self)
        page.url = result.get("url", url)
        return page

    def save_storage_state(self) -> None:
        if self._proc is None or self._closed:
            return
        self._send({"action": "save_state", "path": self.config.storage_state_path})
        logger.info(f"登录态已保存到: {self.config.storage_state_path}")

    # ─── 内部方法（供 Page 包装器调用）──────────────────────────────

    def cmd(self, action: str, **kwargs) -> dict:
        """发送命令到 Playwright 子进程并返回结果"""
        with self._lock:
            return self._send({**kwargs, "action": action})

    def _start(self) -> None:
        if self._proc is not None:
            return
        self._ensure_runtime_paths()

        cmd = [sys.executable, "-c", _PW_SCRIPT]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._build_child_env(),
        )

        # 发送初始化配置
        init = {
            "user_data_dir": self.config.user_data_dir,
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo_ms,
            "timeout_ms": self.config.timeout_ms,
            "channel": self.config.browser_channel or self._detect_browser_channel(),
            "chromium_sandbox": self.config.chromium_sandbox,
        }
        self._proc.stdin.write(json.dumps(init).encode())
        self._proc.stdin.write(b"\n")
        self._proc.stdin.flush()

        # 等待就绪确认
        resp = self._proc.stdout.readline()
        if not resp:
            stderr = self._proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"Playwright 子进程启动失败: {stderr}")
        result = json.loads(resp)
        if result.get("status") != "ready":
            raise RuntimeError(f"Playwright 子进程未就绪: {result}")

        self.active = True

    def _send(self, cmd: dict) -> dict:
        """发送 JSON 命令到子进程，返回解析后的响应"""
        if self._proc is None or self._closed:
            raise RuntimeError("Playwright 子进程未运行")

        msg = json.dumps(cmd).encode()
        self._proc.stdin.write(msg + b"\n")
        self._proc.stdin.flush()

        resp = self._proc.stdout.readline()
        if not resp:
            raise RuntimeError("Playwright 子进程已终止")
        result = json.loads(resp)
        if result.get("status") == "error":
            raise RuntimeError(result.get("msg", "Unknown error"))
        return result

    def _ensure_runtime_paths(self) -> None:
        storage_state = Path(self.config.storage_state_path)
        user_data_dir = Path(self.config.user_data_dir)
        if storage_state.parent:
            storage_state.parent.mkdir(parents=True, exist_ok=True)
        user_data_dir.mkdir(parents=True, exist_ok=True)

    def _build_child_env(self) -> dict:
        env = os.environ.copy()
        project_root = Path(__file__).resolve().parents[2]
        local_site_packages = project_root / ".local_py" / "site-packages"
        pythonpath_parts = [str(project_root)]
        if local_site_packages.exists():
            pythonpath_parts.insert(0, str(local_site_packages))
        if env.get("PYTHONPATH"):
            pythonpath_parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        return env

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
        if self.active:
            logger.info("Browser session stopped.")
        self.active = False


# ─── Page 包装器（把 Playwright Page API 调用转发到子进程）───────────────


class Page:
    """将 Playwright Page API 转发到子进程调用的 Page 对象"""

    def __init__(self, session: BrowserSession):
        self._session = session
        self._url: str = ""

    @property
    def url(self) -> str:
        try:
            result = self._session.cmd("current_url")
            self._url = result.get("url", self._url)
        except Exception:
            pass
        return self._url

    @url.setter
    def url(self, value: str) -> None:
        self._url = value

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> None:
        result = self._session.cmd("goto", url=url, timeout=timeout)
        self.url = result.get("url", url)

    def wait_for_load_state(self, state: str) -> None:
        # domcontentloaded 已在 goto 时等待
        pass

    def wait_for_selector(self, selector: str, timeout: int = 30000) -> "Page":
        self._session.cmd("wait_for_selector", selector=selector, timeout=timeout)
        return self

    def wait_for_timeout(self, ms: int) -> None:
        self._session.cmd("wait_for_timeout", ms=ms)

    def locator(self, selector: str) -> "_Locator":
        return _Locator(self._session, selector)

    def click_button_by_text(self, texts: list[str]) -> dict:
        return self._session.cmd("click_button_by_text", texts=texts)

    @property
    def request(self) -> "APIRequestContext":
        return APIRequestContext(self._session)

    @property
    def inner_text(self) -> str:
        return ""

    def first(self) -> "_Locator":
        return _Locator(self._session, "")


class _Locator:
    """部分 Playwright Locator API 转发"""

    def __init__(self, session: BrowserSession, selector: str, index: int = -1):
        self._session = session
        self._selector = selector
        self._index = index

    def count(self) -> int:
        result = self._session.cmd("locator_count", selector=self._selector)
        return result.get("count", 0)

    def first(self) -> "_Locator":
        return _Locator(self._session, self._selector, index=0)

    def nth(self, n: int) -> "_Locator":
        """返回第 n 个匹配元素（下标从 0 开始）"""
        return _Locator(self._session, self._selector, index=n)

    def fill(self, value: str) -> None:
        self._session.cmd("fill", selector=self._selector, value=value, index=self._index)

    def click(self) -> None:
        self._session.cmd("click", selector=self._selector, index=self._index)

    def inner_text(self) -> str:
        result = self._session.cmd("inner_text", selector=self._selector, index=self._index)
        return result.get("text", "")

    def get_attribute(self, name: str) -> str | None:
        result = self._session.cmd(
            "get_attribute",
            selector=self._selector,
            index=self._index,
            name=name,
        )
        return result.get("value")

    def set_input_files(self, file_path: str) -> None:
        idx = self._index if self._index >= 0 else 0
        self._session.cmd("set_input_files", selector=self._selector, file_path=file_path, index=idx)

    def filter(self, has_text: str = "", **kwargs) -> "_Locator":
        """支持 filter(has_text='...')"""
        if has_text:
            self._session.cmd("locator_filter_text", selector=self._selector, text=has_text)
        return self

    def all(self):
        result = self._session.cmd("locator_all_text", selector=self._selector)
        return [_FakeElement(t) for t in result.get("texts", [])]

    def press(self, key: str) -> None:
        """键盘按键（支持 Enter、End 等）"""
        self._session.cmd("press", selector=self._selector, key=key, index=self._index)

    def type(self, text: str) -> None:
        """输入文本（追加到当前内容）"""
        self._session.cmd("type_text", selector=self._selector, text=text, index=self._index)

    def type_hashtag(self, tag: str, selectors: list[str] = None) -> None:
        """
        原子操作：定位简介编辑器，一次性完成 click→End→type→Enter 全流程。
        避免多次查 DOM 时 placeholder selector 失效的问题。
        """
        self._session.cmd(
            "type_hashtag",
            selectors=selectors or [self._selector],
            tag=tag,
        )

    def evaluate(self, js: str) -> Any:
        """执行 JavaScript"""
        result = self._session.cmd("evaluate", selector=self._selector, js=js, index=self._index)
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
        result = self._session.cmd(
            "api_request",
            url=url,
            method="GET",
            headers=headers or {},
            timeout=timeout,
        )
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
