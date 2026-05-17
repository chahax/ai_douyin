"""
scripts/parse_video_api.py — 解析视频列表 API 响应，找到 video_id 字段
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
        page.goto("https://creator.douyin.com/creator-micro/content/manage", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        import urllib.parse
        api_url = "https://creator.douyin.com/janus/douyin/creator/pc/work_list"
        params = {
            "status": 0, "count": 20, "max_cursor": 0,
            "scene": "star_atlas", "device_platform": "android", "aid": 1128,
        }
        full_url = api_url + "?" + urllib.parse.urlencode(params)
        response = page.request.get(full_url)
        data = response.json()

        aweme_list = data.get("aweme_list", [])
        print(f"共 {len(aweme_list)} 个视频\n")

        for i, v in enumerate(aweme_list[:3]):
            print(f"=== 视频 {i+1} ===")
            # 打印所有顶级字段
            print(f"顶级字段: {list(v.keys())}")

            # 尝试找 video_id
            video_id = v.get("video_id") or v.get("aweme_id") or v.get("aweme_id_str") or v.get("id")
            print(f"可能的 video_id: {video_id}")

            # 也找其他关键字段
            desc = v.get("desc") or v.get("title") or v.get("share_desc") or ""
            print(f"desc: {desc[:80]}")

            create_time = v.get("create_time") or v.get("createTime")
            print(f"create_time: {create_time}")

            # 打印完整 JSON（只取第一个视频的前500字符）
            if i == 0:
                print(f"\n完整第一条视频 JSON:")
                print(json.dumps(v, ensure_ascii=False)[:2000])

            print()

        browser.close()


if __name__ == "__main__":
    main()
