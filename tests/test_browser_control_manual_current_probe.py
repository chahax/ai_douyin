"""Current manual page evidence, real bounded challenge probe, no platform I/O."""
from contextlib import contextmanager
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore


def raw(state):
    return {'blocking': state != 'clear', 'frame_count': 1 if state != 'clear' else 0,
        'actionable_frames': 1 if state != 'clear' else 0, 'visible_dialogs': 0,
        'surface_states': [] if state == 'clear' else [state],
        'frames': [], 'excluded': {}, 'body': 'CAPTCHA_SECRET',
        'url': 'https://www.douyin.com/?credential=SECRET'}


class Page:
    tab_id = 'manual-original-tab'

    def __init__(self, state, events):
        self.state, self.events = state, events

    def goto(self, url):
        self.events.append(('goto', url))

    def _cmd(self, action):
        assert action == 'reveal_manual_window'
        self.events.append(('reveal', self.tab_id))
        return {'restored': True}

    def probe_douyin_challenge(self):
        self.events.append(('probe', self.tab_id))
        if self.state == 'error':
            raise RuntimeError('CAPTCHA_SECRET https://www.douyin.com/?credential=SECRET')
        if self.state == 'malformed':
            return {'blocking': 'unknown', 'body': 'CAPTCHA_SECRET'}
        return raw(self.state)

    def wait_for_timeout(self, ms):
        self.events.append(('wait', ms))

    def screenshot(self, *args, **kwargs):
        pytest.fail('captcha screenshots are forbidden')


@pytest.mark.parametrize('state,status,observations,waits', [
    ('clear', 'current_no_challenge', 1, []),
    ('clear_rebuilt', 'current_no_challenge', 1, []),
    ('challenge_ready', 'challenge_controls_confirmed', 2, [400]),
    ('loading', 'verification_unknown', 5, [400, 800, 1600, 3200]),
    ('load_failed', 'verification_unknown', 5, [400, 800, 1600, 3200]),
    ('error', 'verification_unknown', None, []),
    ('malformed', 'verification_unknown', None, []),
    ('navigation_timeout', 'verification_unknown', None, []),
])
def test_actor_persists_current_same_tab_probe_without_completing_human_task(
        tmp_path, monkeypatch, state, status, observations, waits):
    from src.operations_accounts import manual_handling
    from src.scheduler import account_refresh
    from src.operations_accounts import clear_feed_resume
    monkeypatch.setattr(clear_feed_resume, 'latest_observation', lambda *a, **k: None)
    monkeypatch.setattr('src.operations_accounts.interactive_desktop.require_interactive_desktop', lambda: None)
    events = []
    page = Page('clear' if state == 'clear_rebuilt' else state, events)
    if state == 'navigation_timeout':
        from src.platform_adapter.browser_session import BrowserNavigationTimeout
        def timed_out(url):
            events.append(('goto',url))
            exc=BrowserNavigationTimeout({'target_matched':False,'navigation_committed':False,'ready_state':'loading'})
            exc.page=page
            raise exc
        page.goto=timed_out
    lease_active = []

    @contextmanager
    def lease(context, **options):
        assert options == {'operation': 'manual-session', 'daily_limit': 20,
            'cooldown_seconds': 0, 'allow_manual_verification': True}
        lease_active.append(True)
        yield
        lease_active.pop()

    original_probe = page.probe_douyin_challenge
    def probe():
        assert lease_active
        return original_probe()
    page.probe_douyin_challenge = probe
    owner = NS(config=NS(headless=state == 'clear_rebuilt'), new_tab=lambda role: page)
    resource = NS(session=owner, headless=False, context=NS(profile=object()),
        account_uuid='account:one', account_key='one', manual_tasks={},
        runtime=NS(operation_lease=lease), ensure_session=lambda: owner)
    def shutdown():
        events.append(('shutdown_old_headless_context',))
        resource.session = None
    resource.shutdown = shutdown
    target = manual_handling.ManualHandlingTarget(
        'https://www.douyin.com/search/law?type=video', 'old history',
        'recommend_feed' if state == 'navigation_timeout' else 'blocked_search', 'old-run', 'maintenance:old-run')
    monkeypatch.setattr(manual_handling, 'resolve_manual_handling_target', lambda *a, **k: target)
    monkeypatch.setattr(manual_handling, '_pause_for_handling', lambda *a: events.append(('pause', a)))
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: {})
    store = BrowserControlStore(tmp_path / 'control.db')
    command = store.submit('account:one', 'binding-original', 'manual', 'manual-once', {'account_key': 'one'})
    actor = BrowserControlActor(store, 'account:one', 'binding-original', 'owner-original',
        {'manual': bridge._manual}, context=resource)
    try:
        actor.run_next()
        saved = store.get(command['command_id'])
        assert saved['state'] == 'waiting_human'
        result = saved['result']
        assert result['current_verification']['status'] == status
        assert result['current_verification'].get('observations') == observations
        assert result['target'] == {'source': target.source, 'run_id': target.run_id,
            'maintenance_run_id': target.maintenance_run_id,
            'url_sha256': hashlib.sha256(target.url.encode()).hexdigest()}
        assert result['navigation'] == 'new_target_navigation'
        assert resource.manual_tasks == {command['command_id']: page.tab_id}
        assert ('goto', target.url) in events
        assert any(e[0] == 'shutdown_old_headless_context' for e in events) == (state == 'clear_rebuilt')
        assert [e[1] for e in events if e[0] == 'wait'] == waits
        assert [e[1] for e in events if e[0] == 'probe'] == ([] if state == 'navigation_timeout' else [page.tab_id] * (observations or 1))
        assert '原验证页已保留' not in result['message']
        public = bridge._manual_public(saved)
        assert public['state'] == 'running' and public['handoff_ready'] is True
        assert public['phase'] == 'window_' + status
        assert public['target_source'] == target.source
        combined = json.dumps([result, public], ensure_ascii=False)
        assert 'CAPTCHA_SECRET' not in combined and 'credential' not in combined
        assert target.url not in combined
    finally:
        actor.stop_heartbeat()  # Waiting-human retains its owner, as in production.


def test_public_projection_rejects_untrusted_status_message_and_source():
    command = {'command_id': 'id', 'account_id': 'account:one',
        'payload': {'account_key': 'one'}, 'state': 'waiting_human',
        'created_at': 1, 'updated_at': 2,
        'result': {'message': 'CAPTCHA_SECRET', 'target': {'source': 'CAPTCHA_SECRET'},
            'current_verification': {'status': 'challenge_controls_confirmed',
                'blocking': True, 'surface_state': 'CAPTCHA_SECRET',
                'confirmations': 'CAPTCHA_SECRET', 'frame_count': True,
                'visible_dialogs': -1, 'body': 'CAPTCHA_SECRET'}}}
    public = bridge._manual_public(command)
    assert public['phase'] == 'window_verification_unknown'
    assert public['current_verification'] == {'surface_state': 'unknown', 'status': 'verification_unknown'}
    assert public['target_source'] == 'unresolved'
    assert 'CAPTCHA_SECRET' not in json.dumps(public)


@pytest.mark.parametrize('phase,expected', [
    ('window_challenge_controls_confirmed', '可操作控件'),
    ('window_current_no_challenge', '当前未检测到验证控件'),
    ('window_verification_unknown', '尚未确认'),
    ('window_open_waiting_handling', '尚无当前验证控件的探测回执'),
])
def test_ui_renders_finite_phase_without_untrusted_body(monkeypatch, phase, expected):
    from src.web import account_exception_notice as notice
    messages = []
    ui = NS(info=messages.append, caption=messages.append, session_state={})
    monkeypatch.setattr(notice, 'st', ui)
    notice._render_manual_window_job({'state': 'running', 'phase': phase,
        'job_id': 'id', 'message': 'CAPTCHA_SECRET',
        'current_verification': {'frame_count': 2, 'visible_dialogs': 'CAPTCHA_SECRET'}}, True, 'one')
    text = '\n'.join(messages)
    assert expected in text
    assert '原验证页已打开并保留' not in text and 'CAPTCHA_SECRET' not in text
    if phase != 'window_open_waiting_handling':
        assert '不会完成验证或恢复账号' in text and '候选验证帧 2' in text
