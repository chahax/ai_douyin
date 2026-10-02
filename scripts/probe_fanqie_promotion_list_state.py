from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
if str(P0_ROOT) not in sys.path:
    sys.path.insert(0, str(P0_ROOT))

from src.platform_adapter.fanqie_promotion import (  # noqa: E402
    FANQIE_NOVEL_LIST_URL,
    LIST_PROMOTIONS_JS,
    FanqiePromotionService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostic probe for the Fanqie promotion list page."
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        default=r"D:\IT\ai_douyin\data\fanqie_promotion\audit\promotion_list_probe",
    )
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir) / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    screenshot_path = output_dir / "page.png"
    report_path = output_dir / "report.json"

    service = FanqiePromotionService(
        root_dir=Path(r"D:\IT\ai_douyin\data\fanqie_promotion")
    )
    session = service._open_browser_cache_session(headless=False)
    report: dict = {
        "schema_version": "fanqie_promotion_list_probe/v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_url": FANQIE_NOVEL_LIST_URL,
        "timeout_seconds": max(1, args.timeout),
        "read_only": True,
    }
    try:
        page = session.open_page(FANQIE_NOVEL_LIST_URL)
        deadline = time.monotonic() + max(1, args.timeout)
        parsed: dict = {}
        while time.monotonic() < deadline:
            parsed = page.locator("").evaluate(LIST_PROMOTIONS_JS) or {}
            if parsed.get("items"):
                break
            if (
                parsed.get("table_ready")
                and parsed.get("empty_state")
                and not parsed.get("loading")
            ):
                break
            page.wait_for_timeout(1000)

        diagnostics = page.locator("").evaluate(
            """
            () => {
              const text = (document.body && document.body.innerText || '');
              const has = (pattern) => pattern.test(text);
              return {
                ready_state: document.readyState,
                current_url: location.href,
                title: document.title,
                body_text_length: text.length,
                iframe_count: document.querySelectorAll('iframe').length,
                table_count: document.querySelectorAll('table').length,
                login_signal: has(/登录|扫码登录|手机号登录/),
                captcha_signal: has(/验证码|安全验证|请完成验证/),
                error_signal: has(/系统繁忙|加载失败|网络异常|稍后重试/),
                promotion_signal: has(/推广列表|关键词|书本信息|别名状态/)
              };
            }
            """
        )
        session.cmd("screenshot", path=str(screenshot_path), full_page=True)
        report.update(
            {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "parsed": {
                    "count": len(parsed.get("items") or []),
                    "items": [
                        {
                            key: item.get(key)
                            for key in (
                                "alias",
                                "book_name",
                                "book_id",
                                "publish_type",
                                "alias_status",
                                "book_status",
                                "fill_status",
                                "has_fill_link",
                                "valid_range",
                            )
                        }
                        for item in (parsed.get("items") or [])
                    ],
                    "table_ready": bool(parsed.get("table_ready")),
                    "loading": bool(parsed.get("loading")),
                    "empty_state": bool(parsed.get("empty_state")),
                    "parse_error": parsed.get("parse_error") or "",
                    "headers": parsed.get("all_headers") or [],
                },
                "diagnostics": diagnostics,
                "screenshot_path": str(screenshot_path),
                "success": bool(parsed.get("items"))
                or bool(
                    parsed.get("table_ready")
                    and parsed.get("empty_state")
                    and not parsed.get("loading")
                ),
            }
        )
    except Exception as exc:
        report.update(
            {
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    finally:
        session.stop()

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**report, "report_path": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
