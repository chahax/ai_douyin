"""Real local Chrome DOM qualification; no account/profile/platform access."""
import json

from test_browser_navigation_repair import local_browser
from src.platform_adapter.douyin_recommendation_playback import FEED_SNAPSHOT_JS


def test_real_browser_keyboard_fallback_changes_card_after_noop_arrow(local_browser,monkeypatch):
    from types import SimpleNamespace
    from src.platform_adapter.douyin_recommendation_playback import DouyinRecommendationPlaybackController
    session,url=local_browser;page=session.open_page(url)
    page.evaluate('''() => {document.body.innerHTML='<button data-e2e="video-switch-next-arrow">Next</button>';document.body.dataset.vid='123456789';document.body.addEventListener('keydown',e=>{if(e.key==='ArrowDown')document.body.dataset.vid='987654321';});}''')
    controller=DouyinRecommendationPlaybackController(SimpleNamespace())
    monkeypatch.setattr(controller,'_ready',lambda p:({'found':True,'kind':'video','video_id':p.evaluate('() => document.body.dataset.vid')},''))
    state,code=controller._advance(page,{'found':True,'kind':'video','video_id':'123456789'})
    assert not code and state['video_id']=='987654321'


def test_active_feed_dom_ignores_preloads_and_fails_closed_on_overlap(local_browser):
    session, url = local_browser
    page = session.open_page(url)
    html = """
    <style>body{margin:0}.card{position:absolute;left:0;width:100vw;height:100vh}
    video{width:100%;height:100%}</style>
    <div data-e2e="feed-item" class="card" style="top:120vh">
      <div data-e2e="feed-active-video" data-e2e-vid="111111111"><video></video></div>
    </div>
    <div data-e2e="feed-item" id="active" class="card" style="top:0">
      <div data-e2e="feed-active-video" data-e2e-vid="222222222">
        <video></video><div data-e2e="video-desc">劳动争议法律</div>
        <div data-e2e="feed-video-nickname">测试作者</div>
      </div>
    </div>
    <div data-e2e="feed-item" id="live" class="card" style="top:240vh">
      <div data-e2e="feed-live"><a href="/user/local-live">直播</a><video></video></div>
    </div>
    """
    page.evaluate("() => {document.body.innerHTML=" + json.dumps(html) + ";}")
    snapshot = page.evaluate(FEED_SNAPSHOT_JS)
    assert snapshot["video_id"] == "222222222" and snapshot["title"] == "劳动争议法律"
    page.evaluate("() => {document.getElementById('live').style.top='0';}")
    assert page.evaluate(FEED_SNAPSHOT_JS) == {"found": False, "reason": "active_card_ambiguous"}
    page.evaluate("() => {document.getElementById('active').style.top='-120vh';}")
    snapshot = page.evaluate(FEED_SNAPSHOT_JS)
    assert snapshot["kind"] == "live" and snapshot["card_key"] == "/user/local-live"
    page.evaluate("() => {document.getElementById('live').style.display='none';}")
    assert not page.evaluate(FEED_SNAPSHOT_JS)["found"]
