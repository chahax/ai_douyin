from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.operations_accounts.maintenance import AccountMaintenanceService
from src.platform_adapter.douyin_playback import PlaybackOptions
from src.platform_adapter import douyin_recommendation_playback as feed


def profile():
    return AccountProfile(account_uuid=stable_account_uuid("test-feed"), account_key="test-feed",
        display_name="法律", domain_strategy_id="legal_services",
        seed_keywords=["法律", "劳动争议"], domain_config={"practice_areas": ["劳动争议"]})


def video(vid="123456789", **extra):
    return dict(found=True, kind="video", video_id=vid, title="劳动争议 法律 律师 辞职 赔偿 合同",
                author="律师", current_time=0., duration=100., paused=False, seeking=False,
                ready_state=4, playback_rate=1, **extra)


class Page:
    def __init__(self, cards, *, stalled=False, jump=False, block_after=None):
        self.cards, self.index, self.time = cards, 0, 0.
        self.stalled, self.jump, self.block_after = stalled, jump, block_after
        self.switches = 0

    def locator(self, selector):
        page = self
        class Locator:
            def evaluate(self, script):
                if script == feed.FEED_SNAPSHOT_JS:
                    return dict(page.cards[page.index])
                if script == feed.FEED_PLAY_JS:
                    return {"found": True}
                return ""
            def click(self):
                assert selector == '[data-e2e="video-switch-next-arrow"]'
                page.switches += 1
                page.index = min(page.index + 1, len(page.cards) - 1)
        return Locator()

    def wait_for_timeout(self, ms):
        self.time += ms / 1000
        if not self.stalled and self.cards[self.index].get("kind") == "video":
            self.cards[self.index]["current_time"] += 30 if self.jump else ms / 1000

    def interact_visible_exact_text(self, text, *, operation):
        assert text == "我知道了" and operation == "click"
        return False  # The tutorial is optional and may already be dismissed.


class Session:
    def __init__(self, page):
        self.page, self.urls = page, []
    def open_page(self, url):
        self.urls.append(url)
        return self.page
    def stop(self):
        pass


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr("src.operations_accounts.browser_control_runtime.enabled", lambda: False)
    monkeypatch.setattr("src.operations_accounts.browser_control_runtime.background_safe_point", lambda *_: 0)
    monkeypatch.setattr(feed, "confirmed_douyin_challenge", lambda page: {
        "blocking": page.block_after is not None and page.time >= page.block_after,
        "confirmations": 0,
    })


def test_skips_live_and_irrelevant_without_search_then_verifies_progress():
    irrelevant = video("111111111")
    irrelevant["title"] = "快乐唱歌"
    page = Page([{"found": True, "kind": "live", "card_key": "live-author"}, irrelevant, video()])
    session = Session(page)
    result = feed.DouyinRecommendationPlaybackController(session, clock=lambda: page.time).run(
        profile(), PlaybackOptions(max_videos=1, per_video_seconds=3, total_minutes=1))
    assert session.urls == [feed.FEED_URL]
    assert page.switches == 2
    assert result.status == "completed" and result.verified_videos == 1
    assert result.actual_watch_seconds == 3
    assert result.likes_performed == result.comments_sent == 0


def test_delayed_challenge_is_classified_before_feed_timeout(monkeypatch):
    page=Page([{'found':False}],block_after=5)
    controller=feed.DouyinRecommendationPlaybackController(Session(page))
    monkeypatch.setattr(feed,'confirmed_douyin_challenge',lambda p:{
        'blocking':p.time>=5,'confirmations':2 if p.time>=5 else 0})
    state,code=controller._ready(page)
    assert not state and code=='human_required' and page.time==5


def test_late_redirect_entry_is_followed_once_within_loading_window(monkeypatch):
    from src.platform_adapter import recommendation_entry
    page=Page([{'found':False}]);calls=[]
    def enter(p):
        calls.append(p.time)
        if p.time>=1:
            p.cards=[video()]
            return {'clicked':True}
        return {'clicked':False}
    monkeypatch.setattr(recommendation_entry,'enter_recommendation',enter)
    controller=feed.DouyinRecommendationPlaybackController(Session(page))
    state,code=controller._ready(page)
    assert not code and state['found'] and calls==[0,.5,1]
    controller._ready(page)
    assert calls==[0,.5,1]


def test_loading_failure_keeps_original_surface_without_private_frame_data():
    page=Page([{'found':False}])
    page._cmd=lambda action:{'evidence':{'page':{'path':'/','feed_cards':0},'active_feed':{'found':False},'frames':[{'text':'PRIVATE'}]}}
    result=feed.DouyinRecommendationPlaybackController(Session(page),clock=lambda:page.time).run(
        profile(),PlaybackOptions(max_videos=1,per_video_seconds=3,total_minutes=1))
    assert result.error_code=='feed_not_ready'
    assert result.feed_surface_evidence['page']['feed_cards']==0
    assert 'frames' not in result.feed_surface_evidence


@pytest.mark.parametrize('stalled',[False,True])
def test_unavailable_duration_requires_actual_progress_and_never_invents_completion(stalled):
    card=video();card['duration']=0
    page=Page([card],stalled=stalled)
    session=Session(page);background=[]
    session.keep_background=lambda:background.append(True) or {'minimized':True,'muted':True}
    result=feed.DouyinRecommendationPlaybackController(session,clock=lambda:page.time).run(
        profile(),PlaybackOptions(max_videos=1,per_video_seconds=3,total_minutes=1))
    assert result.verified_videos==(0 if stalled else 1)
    assert result.actual_watch_seconds==(0 if stalled else 3)
    assert result.items[0].completion_ratio==0 and result.items[0].duration_seconds==0
    assert 'duration_unavailable' in result.items[0].watch_plan_basis
    assert background==[True]
    assert result.feed_surface_evidence['background_window']['minimized'] is True


@pytest.mark.parametrize('keyboard_changes',[True,False])
def test_next_card_fallback_is_once_and_requires_identity_change(keyboard_changes):
    from unittest.mock import Mock
    page=Page([video(),video('987654321')]);original=page.locator
    pressed=[]
    def locator(selector):
        if selector=='[data-e2e="video-switch-next-arrow"]':return Mock()
        if selector=='body':
            def press(key):
                pressed.append(key)
                if keyboard_changes:page.index=1
            return SimpleNamespace(press=press)
        return original(selector)
    page.locator=locator
    controller=feed.DouyinRecommendationPlaybackController(Session(page))
    state,code=controller._advance(page,video())
    assert pressed==['ArrowDown']
    assert code==('' if keyboard_changes else 'feed_did_not_advance')
    if keyboard_changes:assert state['video_id']=='987654321'


def test_feed_loading_wait_is_bounded():
    page=Page([{'found':False}])
    state,code=feed.DouyinRecommendationPlaybackController(Session(page))._ready(page)
    assert not state and code=='feed_not_ready' and page.time==15


@pytest.mark.parametrize("stalled,jump", [(True, False), (False, True)])
def test_stall_and_seek_never_count_as_watch(stalled, jump):
    page = Page([video()], stalled=stalled, jump=jump)
    result = feed.DouyinRecommendationPlaybackController(Session(page), clock=lambda: page.time).run(
        profile(), PlaybackOptions(max_videos=1, per_video_seconds=3, total_minutes=1))
    assert result.verified_videos == 0 and result.actual_watch_seconds == 0
    assert result.error_code == "playback_unverified"


def test_blocking_unconfirmed_verification_stops_before_next_card():
    page = Page([video(), video("987654321")], block_after=2)
    result = feed.DouyinRecommendationPlaybackController(Session(page), clock=lambda: page.time).run(
        profile(), PlaybackOptions(max_videos=2, per_video_seconds=3, total_minutes=1))
    assert result.error_code == "verification_ui_unconfirmed"
    assert result.verified_videos == 0 and page.switches == 0
    assert result.actual_watch_seconds == 1
    assert result.challenge_evidence == {"blocking": True, "confirmations": 0}


def test_page_error_after_first_watch_preserves_verified_receipt(monkeypatch):
    page = Page([video()])
    controller = feed.DouyinRecommendationPlaybackController(Session(page), clock=lambda: page.time)
    monkeypatch.setattr(controller, "_advance", lambda *a: (_ for _ in ()).throw(TimeoutError()))
    result = controller.run(profile(), PlaybackOptions(max_videos=2, per_video_seconds=3, total_minutes=1))
    assert result.status == "failed" and result.verified_videos == 1
    assert result.actual_watch_seconds == 3 and result.error_code == "feed_page_error"


@pytest.mark.parametrize("change", [
    {"video_id": "999999999"}, {"seeking": True}, {"playback_rate": 2}, {"current_time": 50},
])
def test_media_delta_rejects_changed_video_seeks_and_rate(change):
    before = video()
    after = dict(before, current_time=1)
    after.update(change)
    assert feed.measured_delta(before, after, 1) == 0


def test_maintenance_default_does_not_construct_research_and_logs_real_watch(tmp_path):
    page, policy = Page([video()]), profile()
    session = Session(page)
    context = SimpleNamespace(account_key=policy.account_key, account_uuid=policy.account_uuid,
        profile=policy, identity_label="test", binding=SimpleNamespace(status="active", public_uid="test"),
        create_browser_session=lambda **k: session)
    class Runtime:
        def resolve(self, key): return context
        @contextmanager
        def operation_lease(self, *a, **kw):
            assert kw["daily_limit"] == 0
            yield "test"
        def verify_identity(self, *a, **kw): return SimpleNamespace(healthy=True)
    def no_research():
        raise AssertionError("Recommendation viewing must never invoke research")
    service = AccountMaintenanceService(runtime=Runtime(), research_factory=no_research,
        playback_factory=lambda s: feed.DouyinRecommendationPlaybackController(s, clock=lambda: page.time),
        log_dir=tmp_path)
    result = service.run(policy.account_key, "playback",
        playback_options=PlaybackOptions(max_videos=1, per_video_seconds=3, total_minutes=1))
    assert result.status == "completed"
    assert result.collected_count == 0 and result.research_keywords == []
    assert result.playback_source == "recommend_feed"
    assert result.success_criteria["verified_playback_completed"]
    assert "relevant_distinct_content_collected" not in result.success_criteria
    assert result.actual_watch_seconds == 3
