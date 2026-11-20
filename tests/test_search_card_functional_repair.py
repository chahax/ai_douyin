"""Real Chrome exercises for the observed linkless public search layout."""
import json
from types import SimpleNamespace

import pytest

from test_browser_navigation_repair import local_browser
from src.trend_intelligence.providers import douyin_web as web
from src.operations_accounts.browser_control_runtime import _open_manual_target
from src.platform_adapter.browser_session import BrowserNavigationTimeout


CARD_HTML = """
<div id="waterFallScrollContainer">
 <div id="waterfall_item_7612317567030614863">
  <div class="search-result-card"><div>01:34</div><div>1.1万</div>
   <div>为了恶心你扣你工资，怎么能最快要到工资？ #劳动纠纷</div>
   <div>@广州劳动律师陈通</div><div>· 3月2日</div></div>
 </div>
 <div id="waterfall_item_6964340406784300303">
  <div>相关搜索</div><div>劳动仲裁律师免费24小时在线咨询</div>
 </div>
 <div id="waterfall_item_6964340406784300315">
  <div class="search-result-card">相关搜索</div>
 </div>
 <div id="waterfall_item_invalid"><div class="search-result-card">
  <div>01:34</div><div>@坏ID</div></div></div>
</div>
<article><a href="https://www.douyin.com/video/7531234567890123456"
 title="原有链接式搜索结果仍可读取">旧版视频</a><div>00:20</div><div>@旧版作者</div></article>
"""


def test_actual_chrome_collects_new_and_old_cards_without_related_search(local_browser):
    session, url = local_browser
    page = session.open_page(url)
    page.evaluate("document.body.innerHTML = " + json.dumps(CARD_HTML))
    assert web.DouyinWebTrendProvider._blocked_detection(page) == ""
    rows, issue = web.DouyinWebTrendProvider()._collect_sort(
        SimpleNamespace(open_page=lambda _: page), query="劳动争议",
        root_keywords=["劳动争议"], query_kind="keyword", query_depth=0,
        sort=web.DOUYIN_SORTS[0], limit=2, retain_raw=True)
    assert issue == ""
    assert {row.video_id for row in rows} == {"7612317567030614863", "7531234567890123456"}
    new = next(row for row in rows if row.video_id == "7612317567030614863")
    assert new.title.startswith("为了恶心你扣你工资")
    assert new.author == "@广州劳动律师陈通"
    assert new.duration_seconds == 94
    assert new.metric_value == 11000 and new.metric_kind == "displayed_unknown"
    assert new.published_at_text == "3月2日" and new.published_at
    assert new.hashtags == ["劳动纠纷"]
    # Adding a link to a new card must not duplicate the video.
    page.evaluate("""document.querySelector('.search-result-card').insertAdjacentHTML(
      'beforeend', '<a href="https://www.douyin.com/video/7612317567030614863">打开</a>')""")
    extracted = page.locator("body").evaluate(web.EXTRACT_SCRIPT)
    assert len(extracted) == 2


def test_actual_chrome_manual_timeout_retains_original_committed_document(local_browser):
    session, url = local_browser
    page = session.open_page(url)
    original_goto, calls = page.goto, []
    def delayed_goto(target):
        calls.append(target)
        # /pending stays in flight for 2s. Allow the actual Chrome document to
        # commit on a busy desktop, while still forcing network-idle timeout.
        return original_goto(target, wait_until="networkidle", timeout=1000)
    page.goto = delayed_goto
    proof = _open_manual_target(page, url + "/search")
    assert proof["target_matched"] and proof["navigation_committed"]
    assert proof['wait_until'] == 'networkidle' and proof['timeout_ms'] == 1000
    assert page.locator('a[href*="/video/"]').count() == 1
    assert calls == [url + "/search"]


@pytest.mark.parametrize("change", ["different_page", "target_matched", "navigation_committed", "ready_state"])
def test_manual_timeout_cannot_accept_wrong_or_unloaded_page(change):
    proof = dict(target_matched=True, navigation_committed=True, ready_state="complete")
    if change in ("target_matched", "navigation_committed"):
        proof[change] = False
    if change == "ready_state":
        proof[change] = "loading"
    error = BrowserNavigationTimeout(proof)
    def go(_):
        raise error
    page = SimpleNamespace(goto=go)
    error.page = object() if change == "different_page" else page
    with pytest.raises(BrowserNavigationTimeout):
        _open_manual_target(page, "https://www.douyin.com/")


@pytest.mark.parametrize("label,expected", [
    ("· 3月2日", "2026-03-01T16:00:00+00:00"),
    ("· 12月30日", "2025-12-29T16:00:00+00:00"),
    ("· 2025年10月17日", "2025-10-16T16:00:00+00:00"),
    ("· 13月2日", ""),
])
def test_visible_chinese_dates(label, expected):
    assert web.parse_visible_publish_time(label, collected_at="2026-10-20T12:00:00+00:00") == expected
