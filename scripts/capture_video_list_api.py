"""
scripts/capture_video_list_api.py — 捕获视频列表 API

用法：python scripts/capture_video_list_api.py
"""

import json

from playwright.sync_api import sync_playwright

MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"


def main():
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        def on_response(response):
            url = response.url
            # 关注列表类、aweme、video、item 相关的 API
            if any(k in url.lower() for k in ["aweme", "video", "item", "list", "feed"]):
                try:
                    body = response.json()
                except Exception:
                    body = None
                captured.append({
                    "url": url,
                    "status": response.status,
                    "body_preview": json.dumps(body)[:500] if body else None,
                })

        page.on("response", on_response)

        print(f"打开管理页: {MANAGE_URL}")
        page.goto(MANAGE_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        print(f"\n=== 捕获到 {len(captured)} 个相关响应 ===\n")
        for i, r in enumerate(captured):
            print(f"--- [{i+1}] {r['status']} ---")
            print(f"URL: {r['url']}")
            if r['body_preview']:
                print(f"Body: {r['body_preview'][:300]}")
            print()

        # 尝试直接访问视频列表 API
        print("\n=== 尝试直接访问视频列表 API ===")
        # 抖音创作者后台常见的视频列表 API
        test_apis = [
            "https://creator.douyin.com/aweme/v1/web/aweme/post/",
            "https://creator.douyin.com/aweme/v1/creator/pc/aweme/list/",
            "https://creator.douyin.com/aweme/v1/web/item/list/",
        ]
        for api_url in test_apis:
            try:
                resp = page.request.get(api_url)
                print(f"  {resp.status} {api_url[:80]}")
                print(f"  Body: {resp.text()[:200]}")
            except Exception as e:
                print(f"  失败 {api_url}: {e}")

        browser.close()


if __name__ == "__main__":
    main()
