"""Inspect the active Douyin feed item without changing account state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.douyin_warmup import DouyinWarmupService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--url", default="")
    parser.add_argument("--screenshot", default="")
    args = parser.parse_args()

    service = DouyinWarmupService()
    account = service.get_account(args.account_id)
    config = service._build_session_config(account)
    config.headless = not args.headed
    session = BrowserSession(config)
    try:
        page = session.open_page(args.url or "https://www.douyin.com/jingxuan")
        page.wait_for_timeout(6000)
        if not args.url:
            service._prepare_recommend_page(page)
            page.wait_for_timeout(2500)
        if args.screenshot:
            session.cmd("screenshot", path=args.screenshot, full_page=False)
        js = r"""
        (() => {
          const visible = element => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return style.display !== 'none' && style.visibility !== 'hidden'
              && rect.width > 0 && rect.height > 0;
          };
          const video = Array.from(document.querySelectorAll('video')).find(visible);
          const ancestors = [];
          let element = video;
          for (let depth = 0; element && depth < 9; depth += 1, element = element.parentElement) {
            ancestors.push({
              tag: element.tagName,
              id: element.id || '',
              className: String(element.className || '').slice(0, 120),
              attributes: Array.from(element.attributes)
                .map(attr => [attr.name, attr.value.slice(0, 180)])
                .filter(pair => /id|item|video|aweme|data|href|key/i.test(pair.join(' ')))
                .slice(0, 20),
            });
          }
          const scopeHtml = video?.parentElement?.parentElement?.parentElement?.outerHTML || '';
          const links = Array.from(document.querySelectorAll('a[href]'))
            .map(link => {
              const parsed = new URL(link.href, location.origin);
              return {
                path: parsed.pathname,
                videoId: parsed.pathname.match(/\/video\/(\d+)/)?.[1] || '',
                awemeId: parsed.searchParams.get('aweme_id') || '',
                gid: parsed.searchParams.get('gid') || '',
                text: String(link.innerText || '').trim().slice(0, 160),
              };
            })
            .filter(item => item.videoId || item.awemeId)
            .slice(0, 40);
          const videoIdElements = Array.from(
            document.querySelectorAll('[data-e2e-vid], [class*="video_"]')
          ).slice(0, 40).map(element => ({
            tag: element.tagName,
            id: element.id || '',
            className: String(element.className || '').slice(0, 180),
            dataE2e: element.getAttribute('data-e2e') || '',
            dataE2eVid: element.getAttribute('data-e2e-vid') || '',
            text: String(element.innerText || '').trim().slice(0, 240),
          }));
          const frames = Array.from(document.querySelectorAll('iframe')).slice(0, 20).map(frame => {
            const parsed = frame.src ? new URL(frame.src, location.origin) : null;
            return {
              host: parsed?.host || '',
              path: parsed?.pathname || '',
              id: frame.id || '',
              title: frame.title || '',
              name: frame.name || '',
              className: String(frame.className || '').slice(0, 160),
            };
          });
          return {
            url: location.href,
            bodyText: String(document.body?.innerText || '').trim().slice(0, 600),
            ancestors,
            scopeIds: Array.from(new Set(scopeHtml.match(/\b\d{17,22}\b/g) || [])).slice(0, 30),
            links,
            videoIdElements,
            frames,
          };
        })()
        """
        diagnostics = page.locator("").evaluate(js)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
    finally:
        session.stop()


if __name__ == "__main__":
    main()
