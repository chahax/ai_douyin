"""
scripts/find_video_id.py — 搜索视频ID在管理页 DOM 中的出现位置

用法：python scripts/find_video_id.py <video_id>
"""

import sys
import re

from playwright.sync_api import sync_playwright

# 管理页 URL
MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"

# 用户提供的视频ID
VIDEO_ID = sys.argv[1] if len(sys.argv) > 1 else input("请输入视频ID: ").strip()
print(f"搜索视频ID: {VIDEO_ID}")


def find_in_page(page):
    results = {
        "video_id": VIDEO_ID,
        "found": False,
        "occurrences": [],
    }

    # 1. 搜索 DOM text 和 attributes
    all_elements = page.query_selector_all("*")

    for el in all_elements:
        try:
            # 检查 innerText
            text = el.inner_text() or ""
            if VIDEO_ID in text:
                results["occurrences"].append({
                    "type": "text",
                    "tag": el.tag_name,
                    "class": el.get_attribute("class") or "",
                    "text_preview": text[:100].replace("\n", " "),
                })

            # 检查属性
            attrs = el.evaluate("""el => {
                let result = {};
                for (let attr of el.attributes) {
                    if (attr.value.includes(arguments[0])) {
                        result[attr.name] = attr.value.substring(0, 100);
                    }
                }
                return result;
            }""", VIDEO_ID)
            if attrs:
                results["occurrences"].append({
                    "type": "attribute",
                    "tag": el.tag_name,
                    "class": el.get_attribute("class") or "",
                    "attrs": attrs,
                })
        except Exception:
            pass

    # 2. 搜索 page source
    html = page.content()
    if VIDEO_ID in html:
        results["found_in_html"] = True
        # 找周围上下文
        idx = html.index(VIDEO_ID)
        results["html_context"] = html[max(0, idx-100):idx+100]
    else:
        results["found_in_html"] = False

    return results


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 启用请求监听
        api_requests = []
        def on_request(req):
            if "video" in req.url.lower() or "aweme" in req.url.lower() or "item" in req.url.lower():
                api_requests.append({"url": req.url, "method": req.method})

        page.on("request", on_request)

        print(f"打开管理页: {MANAGE_URL}")
        page.goto(MANAGE_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        print("\n=== 搜索 DOM ===")
        results = find_in_page(page)

        print(f"HTML 中找到: {results.get('found_in_html', False)}")
        print(f"DOM 匹配次数: {len(results.get('occurrences', []))}")

        for i, occ in enumerate(results.get("occurrences", [])[:20]):
            print(f"\n--- 匹配 {i+1} ---")
            print(f"  类型: {occ['type']}")
            print(f"  标签: <{occ['tag']}> class={occ['class'][:60]}")
            if occ["type"] == "text":
                print(f"  文本: {occ['text_preview']}")
            elif occ["type"] == "attribute":
                print(f"  属性: {occ['attrs']}")

        if results.get("html_context"):
            print(f"\n=== HTML 上下文 ===")
            print(results["html_context"])

        print(f"\n=== 相关 API 请求 ({len(api_requests)}) ===")
        for req in api_requests[:20]:
            print(f"  {req['method']} {req['url'][:120]}")

        browser.close()


if __name__ == "__main__":
    main()
