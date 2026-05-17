"""
scripts/capture_video_list_api.py — 使用 BrowserSession 捕获视频列表 API
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.platform_adapter.browser_session import BrowserSession, build_default_browser_session_config
from src.shared.logger import logger


MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"


def main():
    session = BrowserSession(build_default_browser_session_config())

    logger.info(f"打开管理页: {MANAGE_URL}")
    page = session.open_page(MANAGE_URL)
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(3000)

    captured = []

    def on_response(response):
        url = response.url
        # 关注视频列表相关的 API
        if any(k in url.lower() for k in ["aweme", "video", "post", "item", "manage", "content"]):
            try:
                body = response.json()
                body_str = json.dumps(body, ensure_ascii=False)
                captured.append({
                    "url": url,
                    "status": response.status,
                    "body_preview": body_str[:1000],
                })
            except Exception:
                pass

    page.on("response", on_response)

    # 触发视频列表请求（刷新页面）
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(3000)

    print(f"\n=== 捕获到 {len(captured)} 个相关响应 ===\n")
    for i, r in enumerate(captured):
        print(f"--- [{i+1}] {r['status']} ---")
        print(f"URL: {r['url']}")
        if r.get('body_preview'):
            print(f"Body: {r['body_preview'][:600]}")
        print()

    session.stop()


if __name__ == "__main__":
    main()
