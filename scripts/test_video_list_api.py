"""
scripts/test_video_list_api.py — 直接调用视频列表 API
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright
from src.platform_adapter.browser_session import build_default_browser_session_config


def main():
    config = build_default_browser_session_config()

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=config.user_data_dir,
            headless=False,
            slow_mo=config.slow_mo_ms,
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        # 先获取 msToken（从页面 JS）
        page.goto("https://creator.douyin.com/creator-micro/content/manage", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # 直接调用视频列表 API
        api_url = "https://creator.douyin.com/janus/douyin/creator/pc/work_list"
        params = {
            "status": 0,
            "count": 20,
            "max_cursor": 0,
            "scene": "star_atlas",
            "device_platform": "android",
            "aid": 1128,
        }

        print(f"调用 API: {api_url}")
        print(f"参数: {json.dumps(params, ensure_ascii=False)}")

        # 构造完整 URL
        import urllib.parse
        full_url = api_url + "?" + urllib.parse.urlencode(params)
        print(f"完整 URL: {full_url}")

        response = page.request.get(full_url)
        print(f"\n状态码: {response.status}")

        try:
            data = response.json()
            print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)[:3000]}")
        except Exception as e:
            print(f"解析失败: {e}")
            print(f"原始响应: {response.text()[:500]}")

        browser.close()


if __name__ == "__main__":
    main()
