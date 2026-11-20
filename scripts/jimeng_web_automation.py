"""Automate Jimeng's web video generator through a user-owned Chrome session.

The browser is launched separately with a persistent ``--user-data-dir`` and a
localhost-only CDP port.  This module deliberately never exports cookies,
passwords, storage state, or other authentication material.

Examples::

    python scripts/jimeng_web_automation.py inspect --text 视频生成
    python scripts/jimeng_web_automation.py enter-video
    python scripts/jimeng_web_automation.py prepare --shot S01
    python scripts/jimeng_web_automation.py submit --confirm-spend
    python scripts/jimeng_web_automation.py status
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from playwright.sync_api import Browser, Page, Playwright, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = (
    PROJECT_ROOT
    / "data"
    / "pre_video_scripts"
    / "detailed-script_1f5d963fdb68751096f87b55.md"
)
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
JIMENG_HOST = "jimeng.jianying.com"
GENERATOR_URL = "https://jimeng.jianying.com/ai-tool/generate"


@dataclass
class Session:
    playwright: Playwright
    browser: Browser
    page: Page

    def close(self) -> None:
        # Do not call browser.close(): this is an attached, user-owned Chrome.
        self.playwright.stop()


def connect(cdp_url: str) -> Session:
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
    except Exception:
        playwright.stop()
        raise

    pages = [page for context in browser.contexts for page in context.pages]
    jimeng_pages = [page for page in pages if JIMENG_HOST in page.url]
    if not jimeng_pages:
        playwright.stop()
        raise RuntimeError("9222 上没有即梦页面；请先运行持久化 Chrome 启动命令。")

    page = jimeng_pages[-1]
    page.set_default_timeout(8_000)
    return Session(playwright=playwright, browser=browser, page=page)


def _clean(value: str | None, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def visible_controls(page: Page) -> list[dict[str, Any]]:
    return page.locator(
        "button, input, textarea, [role=button], [role=textbox], "
        "[contenteditable=true], [aria-label]"
    ).evaluate_all(
        """
        els => els.filter(e => {
          const r = e.getBoundingClientRect();
          const s = getComputedStyle(e);
          return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' &&
                 s.display !== 'none';
        }).map((e, index) => ({
          index,
          tag: e.tagName,
          type: e.getAttribute('type') || '',
          role: e.getAttribute('role') || '',
          text: (e.innerText || e.value || '').replace(/\\s+/g, ' ').trim().slice(0, 240),
          placeholder: e.getAttribute('placeholder') || '',
          ariaLabel: e.getAttribute('aria-label') || '',
          title: e.getAttribute('title') || '',
          className: String(e.className || '').slice(0, 240),
          parentText: (e.parentElement?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120),
          grandparentText: (e.parentElement?.parentElement?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
          rect: (() => {
            const r = e.getBoundingClientRect();
            return {
              x: Math.round(r.x), y: Math.round(r.y),
              width: Math.round(r.width), height: Math.round(r.height),
              inViewport: r.bottom > 0 && r.right > 0 &&
                          r.top < innerHeight && r.left < innerWidth
            };
          })()
        }))
        """
    )


def ancestors_for_text(page: Page, text: str) -> list[dict[str, Any]]:
    locator = page.get_by_text(text, exact=True)
    for index in range(locator.count()):
        item = locator.nth(index)
        if not item.is_visible():
            continue
        return item.evaluate(
            """
            e => {
              const out = [];
              let n = e;
              for (let depth = 0; depth < 7 && n; depth++, n = n.parentElement) {
                const r = n.getBoundingClientRect();
                const s = getComputedStyle(n);
                out.push({
                  depth,
                  tag: n.tagName,
                  text: (n.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 320),
                  role: n.getAttribute('role') || '',
                  ariaLabel: n.getAttribute('aria-label') || '',
                  className: String(n.className || '').slice(0, 300),
                  cursor: s.cursor,
                  width: Math.round(r.width),
                  height: Math.round(r.height)
                });
              }
              return out;
            }
            """
        )
    return []


def click_visible_exact_text(page: Page, text: str) -> None:
    locator = page.get_by_text(text, exact=True)
    for index in range(locator.count()):
        item = locator.nth(index)
        if not item.is_visible():
            continue
        # Playwright's pointer action is trusted; Jimeng ignores HTMLElement.click()
        # on this menu even though the element advertises cursor:pointer.
        item.click(force=True, timeout=5_000, no_wait_after=True)
        return
    raise RuntimeError(f"找不到可见文本控件：{text}")


def _viewport_items(locator: Any, page: Page) -> list[Any]:
    viewport = page.viewport_size or {"width": 10_000, "height": 10_000}
    items: list[tuple[float, Any]] = []
    for index in range(locator.count()):
        item = locator.nth(index)
        box = item.bounding_box()
        if not box:
            continue
        if (
            box["x"] + box["width"] <= 0
            or box["y"] + box["height"] <= 0
            or box["x"] >= viewport["width"]
            or box["y"] >= viewport["height"]
        ):
            continue
        items.append((float(box["y"]), item))
    return [item for _, item in sorted(items, key=lambda pair: pair[0])]


def click_viewport_exact_text(page: Page, text: str) -> None:
    items = _viewport_items(page.get_by_text(text, exact=True), page)
    if not items:
        raise RuntimeError(f"视口内找不到文本控件：{text}")
    items[0].click(timeout=5_000)


def wait_for_any_text(page: Page, values: tuple[str, ...], timeout_ms: int = 12_000) -> str:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        body = page.locator("body").inner_text(timeout=3_000)
        for value in values:
            if value in body:
                return value
        page.wait_for_timeout(300)
    raise RuntimeError(f"页面未出现预期文本：{', '.join(values)}")


def enter_video_workspace(page: Page) -> None:
    body = page.locator("body").inner_text(timeout=5_000)
    if "type=video" in page.url and "视频生成" in body:
        return
    if "视频生成" not in body:
        page.goto(GENERATOR_URL, wait_until="domcontentloaded")
        body = page.locator("body").inner_text(timeout=5_000)
    if "type=video" not in page.url:
        click_visible_exact_text(page, "视频生成")
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if "type=video" in page.url:
                return
            page.wait_for_timeout(300)
        raise RuntimeError("点击视频生成后 URL 未进入 type=video")


def set_model(page: Page, model: str) -> None:
    body = page.locator("body").inner_text(timeout=5_000)
    toolbar_prefix = "视频生成\n"
    if f"{toolbar_prefix}{model}\n" in body:
        return
    combo_items = _viewport_items(
        page.locator('[role="combobox"]').filter(has_text="Seedance"), page
    )
    if not combo_items:
        raise RuntimeError("找不到模型下拉框")
    combo_items[0].click(timeout=5_000)
    page.wait_for_timeout(250)
    click_viewport_exact_text(page, model)
    wait_for_any_text(page, (model,), timeout_ms=5_000)


def set_dimensions(page: Page, aspect: str, resolution: str) -> None:
    body = page.locator("body").inner_text(timeout=5_000)
    if f"\n{aspect}\n{resolution}\n1\n5s\n" in body:
        return

    setting_buttons = page.locator("button").filter(
        has_text=re.compile(r"(?:21:9|16:9|4:3|1:1|3:4|9:16)")
    )
    button_items = _viewport_items(setting_buttons, page)
    if not button_items:
        raise RuntimeError("找不到比例/分辨率设置按钮")
    button_items[0].click(timeout=5_000)
    page.wait_for_timeout(250)

    body = page.locator("body").inner_text(timeout=5_000)
    if "选择比例" not in body or "选择分辨率" not in body:
        raise RuntimeError("比例/分辨率设置面板未打开")
    if f"\n{aspect}\n" not in body:
        raise RuntimeError(f"站点不提供目标比例：{aspect}")
    click_viewport_exact_text(page, aspect)
    page.wait_for_timeout(150)
    click_viewport_exact_text(page, resolution)
    page.wait_for_timeout(250)


def set_video_defaults(
    page: Page,
    *,
    model: str = "即梦 Seedance 2.5",
    aspect: str = "9:16",
    resolution: str = "480P",
) -> None:
    enter_video_workspace(page)
    set_model(page, model)
    set_dimensions(page, aspect, resolution)
    body = page.locator("body").inner_text(timeout=5_000)
    required = (model, aspect, resolution, "5s")
    missing = [value for value in required if value not in body]
    if missing:
        raise RuntimeError(f"默认设置复核失败，缺少：{missing}")


def extract_shot(script_path: Path, shot: str) -> str:
    source = script_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^###\s+{re.escape(shot)}\b[^\n]*\n+(.*?)(?=^###\s+|^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        raise RuntimeError(f"剧本中找不到镜头 {shot}: {script_path}")
    paragraphs = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    if not paragraphs:
        raise RuntimeError(f"镜头 {shot} 没有生成提示词")
    return "\n".join(paragraphs)


def editable_candidates(page: Page) -> Iterator[Any]:
    selector = "textarea, [contenteditable=true], [role=textbox]"
    locator = page.locator(selector)
    for index in range(locator.count()):
        item = locator.nth(index)
        if item.is_visible() and item.is_editable():
            yield item


def fill_prompt(page: Page, prompt: str) -> None:
    candidates = list(editable_candidates(page))
    if not candidates:
        raise RuntimeError("找不到可编辑的提示词输入框")
    # Prefer the largest visible editor instead of search or hidden chat clones.
    editor = max(
        candidates,
        key=lambda item: item.evaluate(
            "e => e.getBoundingClientRect().width * e.getBoundingClientRect().height"
        ),
    )
    tag = editor.evaluate("e => e.tagName")
    if tag in {"TEXTAREA", "INPUT"}:
        editor.fill(prompt)
    else:
        editor.click()
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(prompt)


def body_excerpt(page: Page, limit: int = 14_000) -> str:
    return page.locator("body").inner_text(timeout=5_000)[:limit]


def submit_button_and_cost(page: Page) -> tuple[Any, int]:
    candidates = _viewport_items(page.locator("button.submit-button-W8QkOc"), page)
    if not candidates:
        raise RuntimeError("找不到已启用的生成提交按钮")
    observed: list[str] = []
    for button in candidates:
        if button.is_disabled():
            continue
        nearby = button.evaluate(
            "e => e.parentElement?.parentElement?.innerText || "
            "e.parentElement?.innerText || ''"
        )
        observed.append(nearby)
        match = re.search(r"\b(\d{1,5})\b", nearby)
        if match:
            return button, int(match.group(1))
    raise RuntimeError(f"无法读取本次积分消耗：{observed!r}")


def command_inspect(page: Page, text: str | None) -> None:
    payload = {
        "url": page.url,
        "title": page.title(),
        "text_ancestors": ancestors_for_text(page, text) if text else [],
        "controls": visible_controls(page),
        "body": body_excerpt(page),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_prepare(page: Page, script_path: Path, shot: str) -> None:
    set_video_defaults(page)
    prompt = extract_shot(script_path, shot)
    fill_prompt(page, prompt)
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    _, cost = submit_button_and_cost(page)
    print(
        json.dumps(
            {
                "status": "prepared_not_submitted",
                "shot": shot,
                "prompt_chars": len(prompt),
                "url": page.url,
                "settings": {
                    "mode": "视频生成",
                    "model": "即梦 Seedance 2.5",
                    "aspect": "9:16",
                    "resolution": "480P",
                    "count": 1,
                    "duration": "5s",
                },
                "estimated_cost_credits": cost,
                "body": body_excerpt(page),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def command_submit(page: Page, confirm_spend: bool) -> None:
    if not confirm_spend:
        raise RuntimeError("拒绝提交：必须显式提供 --confirm-spend")
    # Calibrated after prepare; choose the top editor's enabled arrow and read
    # the adjacent cost instead of relying on duplicated sticky-editor nodes.
    button, cost = submit_button_and_cost(page)
    button.click(timeout=5_000)
    page.wait_for_timeout(1_500)
    print(
        json.dumps(
            {
                "status": "submitted",
                "estimated_cost_credits": cost,
                "url": page.url,
                "body": body_excerpt(page),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("inspect", "enter-video", "prepare", "submit", "status")
    )
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--shot", default="S01")
    parser.add_argument("--text")
    parser.add_argument("--confirm-spend", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = connect(args.cdp_url)
    try:
        if args.command == "inspect":
            command_inspect(session.page, args.text)
        elif args.command == "enter-video":
            enter_video_workspace(session.page)
            command_inspect(session.page, None)
        elif args.command == "prepare":
            command_prepare(session.page, args.script.resolve(), args.shot)
        elif args.command == "submit":
            command_submit(session.page, args.confirm_spend)
        else:
            print(json.dumps({"url": session.page.url, "body": body_excerpt(session.page)}, ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
