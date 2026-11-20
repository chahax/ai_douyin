"""The scheduler client must not finish a running cooperative checkpoint."""
import threading
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore, BrowserCommandResult, BrowserControlRejected


@pytest.mark.parametrize('priority', [False, True])
def test_real_actor_client_waits_past_transient_checkpoint_before_finishing_background(tmp_path, monkeypatch, priority):
    store = BrowserControlStore(tmp_path / 'control.sqlite')
    monkeypatch.setattr(bridge, '_store', lambda: store)
    account = {'paused': False}
    observed, checkpoint = threading.Event(), threading.Event()
    result_holder, events, client_errors = [], [], []
    original = store.submit('review:A', 'binding', 'maintenance', 'original', {}, 0)
    def client():
        try:
            # Production waits up to 3h. Actor setup and nested metadata IO can
            # exceed 8s under parallel disk-heavy checks; only the >0.2s paused
            # observation window below is the behavior under test.
            result = bridge._await(original, timeout=60)
            result_holder.append(result)
            if result['state'] == 'paused':
                account['paused'] = True  # The actual legacy scheduler's early finish.
        except Exception as exc:
            client_errors.append(exc)
        finally:
            observed.set()
    def hold_checkpoint():
        checkpoint.set()
        # More than two actual 0.2s client polling intervals. If it returns here,
        # the false scheduler pause blocks the actor's following resume gate.
        assert not observed.wait(.55)
    def publish(ctx, payload):
        events.append('priority')
        hold_checkpoint()
        return {'known': True}
    def background(ctx, payload):
        if priority:
            store.submit('review:A', 'binding', 'publish', 'priority', {}, 100)
        ctx.safe_point({'stage': 'playback_before_candidate', 'next_candidate_index': 0})
        events.append('resumed')
        return {'maintenance_result': {'status': 'completed'}}
    def admission(ctx, phase):
        if phase == 'resume' and not priority:
            hold_checkpoint()  # Still paused even with no nested priority task.
        return not account['paused']
    actor = BrowserControlActor(store, 'review:A', 'binding', 'owner',
        {'maintenance': background, 'publish': publish}, admission=admission)
    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    try:
        assert actor.run_next()['state'] == 'succeeded'
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not client_errors
        assert checkpoint.is_set() and not account['paused']
        assert result_holder[0]['state'] == 'succeeded'
        assert events == (['priority', 'resumed'] if priority else ['resumed'])
    finally:
        try:
            actor.close()
        except BrowserControlRejected:
            actor.stop_heartbeat()


def test_real_actor_terminal_suspended_pause_still_finishes_client_with_known_failure(tmp_path, monkeypatch):
    store = BrowserControlStore(tmp_path / 'control.sqlite')
    monkeypatch.setattr(bridge, '_store', lambda: store)
    original = store.submit('review:A', 'binding', 'maintenance', 'original', {}, 0)
    def background(ctx, payload):
        store.submit('review:A', 'binding', 'publish', 'priority', {}, 100)
        ctx.safe_point({'next_candidate_index': 0})
        pytest.fail('Stopped priority must not resume')
    actor = BrowserControlActor(store, 'review:A', 'binding', 'owner',
        {'maintenance': background, 'publish': lambda *_: BrowserCommandResult('failed', {})})
    try:
        stopped = actor.run_next()
        assert stopped['state'] == 'paused' and stopped['error_code']
        assert bridge._await(original, timeout=1)['command_id'] == original['command_id']
    finally:
        actor.stop_heartbeat()


@pytest.mark.parametrize('closed', [False, True])
def test_verified_manual_page_normal_closure_is_observed_even_without_live_task_maps(closed):
    calls = []
    resource = NS(manual_tasks={}, console_tasks={}, headless=False,
        session=NS(window_status=lambda: {'closed': closed, 'context_closed': closed,
            'tabs': [{'tab_id': 'verified-page', 'role': 'manual', 'closed': closed}]}),
        shutdown=lambda: calls.append('original_shutdown'))
    actor = NS(store=NS(complete_waiting=lambda *_a, **_kw: pytest.fail('No active task should be rewritten')))
    bridge._poll_manual_windows(actor, resource)
    assert calls == (['original_shutdown'] if closed else [])
    assert resource.headless is (True if closed else False)


def test_verified_page_status_unknown_does_not_close_or_release_it():
    def unknown():
        raise RuntimeError('window status unavailable')
    resource = NS(manual_tasks={}, console_tasks={}, session=NS(window_status=unknown),
        shutdown=lambda: pytest.fail('Unknown window must not be called closed'))
    with pytest.raises(RuntimeError):
        bridge._poll_manual_windows(NS(), resource)
