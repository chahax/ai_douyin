"""Feed transition contract tests; no real account or platform interaction."""
from types import SimpleNamespace

import pytest

from src.platform_adapter import douyin_recommendation_playback as feed
from src.platform_adapter.douyin_playback import PlaybackOptions
from test_recommendation_playback import Page, Session, profile, video


def scope():
    return SimpleNamespace(account_id=profile().account_uuid, task_id='task-feed',
        actor=SimpleNamespace(owner_id='backend:test', generation=7), binding_version='binding-test',
        resource=SimpleNamespace(context=SimpleNamespace(binding=SimpleNamespace(public_uid='original-uid'))))


def proof(ctx, stamp):
    return dict(schema='feed_transition_identity/v1', source='runtime.verify_identity',
        account_uuid=ctx.account_id, command_id=ctx.task_id, owner_id=ctx.actor.owner_id,
        generation=ctx.actor.generation, binding_version=ctx.binding_version,
        feed_tab_id='feed-tab', identity_tab_id='identity-tab',
        expected_public_uid='original-uid', actual_public_uid='original-uid',
        healthy=True, status='active', verified_at=stamp)


class TransitionPage(Page):
    tab_id='feed-tab'
    def __init__(self, *, transition_at=2):
        super().__init__([video('111111111'),video('222222222')])
        self.transition_at=transition_at
        self.location={'origin':'https://www.douyin.com','path':'/'}
    def locator(self, selector):
        original=super().locator(selector)
        old=original.evaluate
        original.evaluate=lambda js:self.location.copy() if js==feed.FEED_LOCATION_JS else old(js)
        return original
    def wait_for_timeout(self, ms):
        super().wait_for_timeout(ms)
        if self.index==0 and self.time>=self.transition_at:
            self.index=1
            self.cards[1]['current_time']=0.


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr('src.operations_accounts.browser_control_runtime.background_safe_point',lambda *_:0)
    monkeypatch.setattr(feed,'confirmed_douyin_challenge',lambda _:dict(blocking=False,confirmations=0))


def controller(page, *, hook=True):
    session=Session(page)
    session.origin_context=scope()
    session.calls=[]
    def verify():
        session.calls.append('identity')
        return proof(session.origin_context,100+page.time)
    if hook:session.verify_feed_transition_identity=verify
    return feed.DouyinRecommendationPlaybackController(session,clock=lambda:page.time,
        wall_clock=lambda:100+page.time)


def test_legitimate_transition_preserves_partial_and_does_not_advance():
    page=TransitionPage();c=controller(page)
    result=c.run(profile(),PlaybackOptions(max_videos=1,per_video_seconds=3,total_minutes=1))
    assert result.status=='completed' and result.verified_videos==1
    assert [x.video_id for x in result.items]==['111111111','222222222']
    assert result.items[0].actual_watch_seconds==1 and not result.items[0].playback_verified
    assert result.items[1].playback_verified and result.actual_watch_seconds==4
    assert page.switches==0 and c.session.calls==['identity']
    event=result.feed_surface_evidence['transitions'][0]
    assert event['decision']=='verified_same_account_feed_transition'
    assert event['observed']['video_id']=='222222222'
    assert result.likes_performed==result.comments_sent==0


def test_all_short_natural_transitions_use_existing_nonfailure_skip():
    class ShortPage(TransitionPage):
        def __init__(self):
            super().__init__()
            self.cards=[video(str(111111111+i)) for i in range(25)]
            self.next_change=2
        def wait_for_timeout(self,ms):
            Page.wait_for_timeout(self,ms)
            if self.time>=self.next_change:
                self.index+=1;self.next_change+=2
                self.cards[self.index]['current_time']=0.
    page=ShortPage();c=controller(page)
    result=c.run(profile(),PlaybackOptions(max_videos=1,per_video_seconds=90,total_minutes=1))
    assert result.status=='skipped' and result.error_code=='no_playback_candidates'
    assert result.verified_videos==0 and result.actual_watch_seconds==20
    assert all(not x.playback_verified for x in result.items)
    assert page.switches==0


def test_missing_identity_recheck_does_not_count_gap_or_call_identity(monkeypatch):
    page=TransitionPage(transition_at=100);c=controller(page)
    samples=iter([{'found':False,'reason':'video_identity_missing'},video('111111111',)])
    monkeypatch.setattr(c,'_snapshot',lambda _:next(samples))
    current,code,changed=c._observe_change(page,profile(),video('111111111'),
        {'found':False,'reason':'active_card_ambiguous'},'111111111')
    assert not code and not changed and current['video_id']=='111111111'
    assert page.time==.5 and c.session.calls==[]
    assert c._feed_surface_evidence['transitions'][0]['watch_time_during_recheck']==0


def test_persistent_missing_identity_stops_with_diagnostic(monkeypatch):
    page=TransitionPage();c=controller(page)
    monkeypatch.setattr(c,'_snapshot',lambda _:dict(found=False,reason='active_card_ambiguous'))
    _,code,changed=c._observe_change(page,profile(),video('111111111'),{'found':False},'111111111')
    assert code=='feed_identity_unavailable' and not changed and page.time==.75
    assert c.session.calls==[] and len(c._feed_surface_evidence['transitions'][0]['rechecks'])==3


def test_missing_managed_hook_is_explicit_capability_gap():
    page=TransitionPage();c=controller(page,hook=False)
    _,code,changed=c._observe_change(page,profile(),video('111111111'),video('222222222'),'111111111')
    assert code=='feed_transition_identity_unavailable' and not changed


def test_identity_probe_exception_is_typed_and_does_not_advance():
    page=TransitionPage();c=controller(page)
    def unavailable():raise RuntimeError('synthetic unreadable identity')
    c.session.verify_feed_transition_identity=unavailable
    _,code,changed=c._observe_change(page,profile(),video('111111111'),video('222222222'),'111111111')
    assert code=='feed_transition_identity_unavailable' and not changed and page.switches==0
    assert c._feed_surface_evidence['transitions'][0]['identity_error_type']=='RuntimeError'


@pytest.mark.parametrize('mutation',[
    {'command_id':'other'}, {'owner_id':'other'}, {'generation':8},
    {'binding_version':'other'}, {'verified_at':0},
    {'identity_tab_id':'feed-tab'},
    {'expected_public_uid':'different','actual_public_uid':'different'},
])
def test_stale_or_other_subject_proof_is_rejected(mutation):
    page=TransitionPage();c=controller(page)
    c.session.verify_feed_transition_identity=lambda:dict(proof(c.session.origin_context,100),**mutation)
    _,code,changed=c._observe_change(page,profile(),video('111111111'),video('222222222'),'111111111')
    assert code in {'feed_transition_scope_mismatch','identity_mismatch'} and not changed


def test_wrong_origin_does_not_call_identity():
    page=TransitionPage();page.location['origin']='https://other.invalid';c=controller(page)
    _,code,changed=c._observe_change(page,profile(),video('111111111'),video('222222222'),'111111111')
    assert code=='feed_origin_mismatch' and not changed and c.session.calls==[]


def test_card_changes_again_during_identity_not_assumed_current(monkeypatch):
    page=TransitionPage();c=controller(page)
    monkeypatch.setattr(c,'_snapshot',lambda _:video('333333333'))
    _,code,changed=c._observe_change(page,profile(),video('111111111'),video('222222222'),'111111111')
    assert code=='feed_transition_unstable' and not changed and page.switches==0


def test_challenge_after_identity_is_not_a_success(monkeypatch):
    page=TransitionPage();c=controller(page)
    monkeypatch.setattr(c,'_block',lambda _:'human_required')
    _,code,changed=c._observe_change(page,profile(),video('111111111'),video('222222222'),'111111111')
    assert code=='human_required' and not changed


@pytest.mark.parametrize('raises',[False,True])
def test_managed_hook_closes_only_identity_tab_even_on_error(monkeypatch,raises):
    from src.operations_accounts import browser_control_runtime as runtime
    cls=runtime.BorrowedSession
    borrowed=object.__new__(cls);closed=[];opened=[];expected_owner=object()
    ctx=scope();ctx.command={'kind':'maintenance','payload':{'mode':'playback'}}
    borrowed.origin_context=ctx;borrowed.owner=expected_owner
    borrowed.page=SimpleNamespace(tab_id='feed-tab')
    borrowed._guard=lambda:None
    def verify(context,*,session):
        assert session.page.tab_id=='identity-tab' and borrowed.page.tab_id=='feed-tab'
        if raises:raise RuntimeError('synthetic verification failure')
        return SimpleNamespace(healthy=True,status='active',actual=SimpleNamespace(public_uid='original-uid'))
    borrowed.resource=SimpleNamespace(context=ctx.resource.context,runtime=SimpleNamespace(verify_identity=verify))
    class Identity:
        def __init__(self,resource,role):
            assert resource is borrowed.resource and role=='feed_transition_identity'
            self.owner=expected_owner;self.page=SimpleNamespace(tab_id='identity-tab');opened.append(role)
        def stop(self):closed.append(self.page.tab_id)
    monkeypatch.setattr(runtime,'BorrowedSession',Identity)
    if raises:
        with pytest.raises(RuntimeError,match='synthetic'):borrowed.verify_feed_transition_identity()
    else:
        p=borrowed.verify_feed_transition_identity()
        assert p['healthy'] and p['actual_public_uid']=='original-uid' and p['command_id']==ctx.task_id
    assert opened==['feed_transition_identity'] and closed==['identity-tab']
    assert borrowed.page.tab_id=='feed-tab'


def test_real_isolated_chrome_transition_uses_actual_dom_without_network(tmp_path):
    """Intercepted in-memory HTML on a synthetic origin, never a real platform page."""
    from playwright.sync_api import sync_playwright
    intercepted=[]
    html='''<meta charset="utf-8"><style>body{margin:0}[data-e2e=feed-item],video{position:absolute;inset:0;width:100vw;height:100vh}</style>
    <div data-e2e="feed-item"><div data-e2e="feed-active-video" data-e2e-vid="111111111">
    <video></video><div data-e2e="video-desc">劳动争议法律合同</div></div></div><script>
    window.t=0;window.media=0;const v=document.querySelector('video');
    for(const [key,get] of Object.entries({currentTime:()=>media,duration:()=>100,paused:()=>false,
    ended:()=>false,seeking:()=>false,readyState:()=>4,playbackRate:()=>1}))Object.defineProperty(v,key,{get});
    v.play=()=>Promise.resolve();
    window.tick=ms=>{t+=ms/1000;media+=ms/1000;if(t>=2&&document.querySelector('[data-e2e-vid]').getAttribute('data-e2e-vid')==='111111111'){
    document.querySelector('[data-e2e-vid]').setAttribute('data-e2e-vid','222222222');media=0;}};</script>'''
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(tmp_path/'profile'),channel='chrome',
            headless=True,args=['--disable-background-networking'])
        def route(r):
            intercepted.append(r.request.url)
            if r.request.url=='https://www.douyin.com/?recommend=1':r.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
            else:r.abort()
        context.route('**/*',route)
        raw=context.new_page();raw.goto(feed.FEED_URL)
        class LocalPage:
            tab_id='feed-tab'
            switches=0
            @property
            def time(self):return raw.evaluate('() => window.t')
            def locator(self,selector):
                def click():
                    self.switches+=1
                    raise AssertionError('No next-card click after spontaneous transition')
                return SimpleNamespace(evaluate=lambda js:raw.evaluate(js),click=click)
            def wait_for_timeout(self,ms):raw.evaluate('(ms)=>tick(ms)',ms)
            def interact_visible_exact_text(self,*a,**kw):return False
        page=LocalPage();c=controller(page)
        result=c.run(profile(),PlaybackOptions(max_videos=1,per_video_seconds=3,total_minutes=1))
        if result.status!='completed':
            import json
            pytest.fail(json.dumps(result.to_dict(),ensure_ascii=True))
        assert result.verified_videos==1 and page.switches==0
        assert result.items[0].actual_watch_seconds==1 and result.items[1].playback_verified
        assert result.feed_surface_evidence['transitions'][0]['after_identity']['video_id']=='222222222'
        assert intercepted==[feed.FEED_URL]
        context.close()
