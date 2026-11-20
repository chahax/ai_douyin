"""Real worker protocol, SQLite actor and Streamlit widgets; no production DB."""
from contextlib import nullcontext
import io
import json
from types import SimpleNamespace as NS

import pytest
from streamlit.testing.v1 import AppTest

from src.platform_adapter import browser_session as module
from src.shared.browser_startup_diagnostics import clean, classify


@pytest.mark.parametrize('message,code', [
    ("Executable doesn't exist at private/path?token=secret", 'executable_missing'),
    ('ProcessSingleton private-profile', 'profile_lock_unavailable'),
    ('ProcessSingleton Access is denied private-profile', 'permission_denied'),
    ('ProcessSingleton Lock file can not be created: 拒绝访问。 (0x5)', 'permission_denied'),
    ('Access is denied cookie=private', 'permission_denied'),
    ('Target page, context or browser has been closed', 'browser_closed'),
    ('unknown private response', 'unknown')])
def test_only_allowlisted_failure_facts_survive(message, code):
    proof = classify(RuntimeError(message))
    assert proof['code'] == code
    assert not any(x in json.dumps(proof) for x in ('private', 'secret', 'cookie'))
    assert clean(dict(proof, msg=message, argv=message)) == proof


def test_real_worker_protocol_reports_launch_failure_before_parent_cleanup(monkeypatch):
    from types import ModuleType
    api = ModuleType('playwright.sync_api')
    def fail(**kwargs):
        raise RuntimeError("Executable doesn't exist at profile/secret")
    api.sync_playwright = lambda: NS(start=lambda: NS(chromium=NS(launch_persistent_context=fail)))
    monkeypatch.setitem(__import__('sys').modules, 'playwright.sync_api', api)
    stdin = io.StringIO('{}\n')
    output = io.StringIO()
    monkeypatch.setattr(__import__('sys'), 'stdin', stdin)
    monkeypatch.setattr(__import__('sys'), 'stdout', output)
    monkeypatch.setattr(__import__('sys'), 'stderr', io.StringIO())
    ns = {'__name__': 'isolated_worker'}
    exec(compile(module._PW_SCRIPT, '<worker>', 'exec'), ns)
    ns['_guarded_main']()
    receipt = json.loads(output.getvalue())
    assert receipt == {'status':'error', 'startup_evidence':
        {'code':'executable_missing', 'error_type':'RuntimeError', 'stage':'launching_browser'}}
    assert 'secret' not in output.getvalue()


@pytest.mark.parametrize('cleanup', [True, False])
@pytest.mark.parametrize('stage', ['launching_browser','ready'])
def test_actor_keeps_unknown_unless_exact_never_ready_startup_is_reaped(tmp_path, monkeypatch, cleanup, stage):
    from src.operations_accounts import browser_control_runtime as bridge, manual_handling, interactive_desktop
    from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore
    from src.operations_accounts.browser_host_retirement import retire_host
    from src.scheduler import account_refresh
    from src.web.components import auth
    calls = []
    error = module.BrowserWorkerStartupError(stage)
    error.startup_evidence = dict(code='browser_closed', stage=stage,
        ready_received=False, cleanup_verified=cleanup)
    def fail(role):
        calls.append(role)
        raise error
    session = NS(config=NS(headless=False), new_tab=fail, _proc=None,
                 _worker_stage=stage, _startup_cleanup_verified=cleanup)
    resource = NS(account_uuid='a', account_key='one', session=session, headless=False,
        context=NS(profile=NS()), runtime=NS(operation_lease=lambda *a,**k:nullcontext()),
        ensure_session=lambda:session, manual_tasks={},console_tasks={})
    resource.shutdown=lambda:setattr(resource,'session',None)
    monkeypatch.setattr(interactive_desktop,'require_interactive_desktop',lambda:None)
    monkeypatch.setattr(account_refresh,'snapshot',lambda:{})
    monkeypatch.setattr(manual_handling,'resolve_manual_handling_target',lambda *a,**k:NS(url='about:blank'))
    monkeypatch.setattr(manual_handling,'_pause_for_handling',lambda *a:None)
    store=BrowserControlStore(tmp_path/'queue.db')
    command=store.submit('a','binding','manual','original',{'account_key':'one'})
    actor=BrowserControlActor(store,'a','binding','original-owner',{'manual':bridge._manual},context=resource)
    try:
        receipt=actor.run_next()
        known=cleanup and stage!='ready'
        assert receipt['state']==('failed' if known else 'outcome_unknown')
        assert receipt['command_id']==command['command_id'] and calls==['manual']
        assert receipt['result']['startup_evidence']==error.startup_evidence
        assert receipt['result']['identity_verified'] is False
        assert actor.run_next() is None and calls==['manual']  # never requeued
        public=bridge._manual_public(receipt)
        assert public['error_code']=='browser_start_failed'
        assert public['startup_evidence']['cleanup_verified'] is cleanup
        monkeypatch.setattr(auth,'get_current_user',lambda:'qa')
        monkeypatch.setattr(auth,'get_current_role',lambda:'admin')
        from src.operations_accounts import manual_window_jobs
        monkeypatch.setattr(manual_window_jobs,'get_manual_window_job',lambda *a: public)
        app=AppTest.from_string("from src.web.account_exception_notice import render_account_manual_window_controls\n"
            "render_account_manual_window_controls('a','one',key='open',poll=False)", default_timeout=15).run()
        assert not app.exception
        visible=' '.join(x.value for seq in (app.info,app.error,app.caption,app.warning) for x in seq)
        assert '排队' not in visible and '失败阶段' in visible
        assert app.button(key='open').disabled is (not known)
        assert retire_host(actor,resource) is known
        assert store.get(command['command_id'])==receipt  # no retrospective rewrite
    finally:
        actor.stop_heartbeat()


def test_old_unknown_without_new_proof_is_not_reclassified():
    from src.operations_accounts.browser_control_runtime import _manual_public
    c=dict(command_id='old',account_id='a',payload={'account_key':'one'},state='outcome_unknown',
           result={'error_type':'BrowserWorkerStartupError'},error_code='handler_exception:BrowserWorkerStartupError',
           created_at=1,updated_at=2)
    public=_manual_public(c)
    assert public['state']=='outcome_unknown' and 'startup_evidence' not in public


@pytest.mark.parametrize('value', [None, [], {'code': [], 'stage': {}, 'error_type': []},
    {'cleanup_verified':'true', 'ready_received':0, 'browser_exit_code':True, 'msg':'private'}])
def test_malformed_diagnostics_fail_closed_without_payload(value):
    assert clean(value)=={'code':'unknown'}
