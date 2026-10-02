"""Capture read-only Douyin warmup DOM diagnostics for one saved account."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.douyin_warmup import DouyinWarmupService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--click-comment", action="store_true")
    args = parser.parse_args()

    service = DouyinWarmupService()
    account = service.get_account(args.account_id)
    session = BrowserSession(service._build_session_config(account))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/douyin_warmup/debug") / f"{args.account_id}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        page = session.open_page("https://www.douyin.com/jingxuan")
        page.wait_for_timeout(5000)
        service._prepare_recommend_page(page)
        page.wait_for_timeout(3000)
        session.cmd("screenshot", path=str(output_dir / "before.png"), full_page=False)

        js = r"""
        (() => {
          const visible = el => {
            const s = getComputedStyle(el), r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
          };
          const compact = el => {
            const r = el.getBoundingClientRect();
            return {
              tag: el.tagName,
              id: el.id || '',
              cls: String(el.className || '').slice(0, 240),
              role: el.getAttribute('role') || '',
              aria: el.getAttribute('aria-label') || '',
              title: el.getAttribute('title') || '',
              text: String(el.innerText || el.textContent || '').trim().slice(0, 120),
              rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
              svgViewBox: el.querySelector('svg')?.getAttribute('viewBox') || '',
              svgPath: el.querySelector('svg path')?.getAttribute('d')?.slice(0, 180) || ''
            };
          };
          const all = [...document.querySelectorAll('button,[role=button],svg,div,p,span')].filter(visible);
          const candidates = all.filter(el => {
            const blob = [el.innerText, el.textContent, el.getAttribute('aria-label'), el.getAttribute('title')]
              .filter(Boolean).join(' ');
            const svg = el.matches('svg') ? el : el.querySelector('svg');
            const r = el.getBoundingClientRect();
            const nearVideoActions = r.x > innerWidth * 0.65 && r.width < 240 && r.height < 180;
            return /评论|comment/i.test(blob) || svg?.getAttribute('viewBox') === '0 0 99 99' || nearVideoActions;
          }).slice(0, 100).map(compact);
          const panels = [...document.querySelectorAll('aside,[role=dialog],[class*=comment],[class*=Comment],#videoSideCard,#relatedVideoCard')]
            .filter(visible).slice(0, 40).map(compact);
          const videos = [...document.querySelectorAll('video')].filter(visible).map((v, i) => ({
            index: i, src: v.currentSrc || v.src || '', currentTime: v.currentTime,
            duration: v.duration, poster: v.poster || '', rect: compact(v).rect
          }));
          return {url: location.href, title: document.title, candidates, panels, videos};
        })()
        """
        diagnostics = page.locator("").evaluate(js)
        if args.click_comment:
            click_js = r"""
            (() => {
              const visible = el => {
                const s = getComputedStyle(el), r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
              };
              const numeric = /^\s*[\d.]+(?:万|亿)?\s*$/;
              const groups = [...document.querySelectorAll('div')].filter(el => {
                const r = el.getBoundingClientRect();
                const text = String(el.innerText || '').trim();
                return visible(el) && r.x > innerWidth * .82 && r.y > 180 && r.y < innerHeight - 100
                  && r.width >= 30 && r.width <= 100 && r.height >= 40 && r.height <= 100
                  && numeric.test(text) && el.querySelector('svg');
              }).sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);
              const unique = groups.filter((el, i) => !groups.some((other, j) => j < i && other.contains(el)));
              const target = unique[1];
              if (!target) return {clicked:false, groups:unique.map(el => (el.innerText || '').trim())};
              target.setAttribute('data-codex-debug-comment', '1');
              return {clicked:true, groups:unique.map(el => (el.innerText || '').trim())};
            })()
            """
            click_info = page.locator("").evaluate(click_js)
            if click_info.get("clicked"):
                page.locator('[data-codex-debug-comment="1"]').click()
                page.wait_for_timeout(2500)
            session.cmd("screenshot", path=str(output_dir / "after_click.png"), full_page=False)
            panel_js = r"""
            (() => [...document.querySelectorAll('aside,[role=dialog],div')].filter(el => {
              const r=el.getBoundingClientRect(), s=getComputedStyle(el), t=(el.innerText||'').trim();
              return s.display!=='none' && s.visibility!=='hidden' && r.width>250 && r.height>200
                && (/评论/.test(t) || /条评论/.test(t) || el.querySelector('textarea,input[placeholder*=评论]'));
            }).slice(0,20).map(el => ({tag:el.tagName,id:el.id||'',cls:String(el.className||'').slice(0,200),text:(el.innerText||'').trim().slice(0,300),rect:(()=>{const r=el.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()})))()
            """
            diagnostics["click_info"] = click_info
            diagnostics["opened_panels"] = page.locator("").evaluate(panel_js)
        (output_dir / "dom.json").write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps({"output_dir": str(output_dir), **diagnostics}, ensure_ascii=False, indent=2))
    finally:
        session.stop()


if __name__ == "__main__":
    main()
