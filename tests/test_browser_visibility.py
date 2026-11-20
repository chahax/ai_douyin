import sqlite3

import pytest

from src.scheduler.browser_visibility import automatic_window_allowed, set_automatic_windows


def test_preference_only_suppresses_selected_account_and_is_reversible(tmp_path):
    path = tmp_path / 'control.db'
    sqlite3.connect(path).close()
    assert automatic_window_allowed('novel', path=path)
    set_automatic_windows('novel', False, authorization='hidden test requested', path=path)
    assert not automatic_window_allowed('novel', path=path)
    assert automatic_window_allowed('legal', path=path)
    set_automatic_windows('novel', True, authorization='restore requested', path=path)
    assert automatic_window_allowed('novel', path=path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM account_browser_preference_history').fetchone()[0] == 2


def test_unreadable_preference_does_not_allow_visible_window(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.Error):
        automatic_window_allowed('novel', path=path)


def test_hidden_account_skips_automatic_window_dispatch(tmp_path, monkeypatch):
    from src.scheduler import account_refresh, account_manual_windows
    path = tmp_path / 'control.db'
    sqlite3.connect(path).close()
    set_automatic_windows('novel', False, authorization='hidden test requested', path=path)
    monkeypatch.setattr(account_refresh, 'snapshot', lambda **kw: {'issues': [dict(account_uuid='novel', account_key='novel02', id=1)]})
    monkeypatch.setattr(account_manual_windows, '_eligible', lambda *a: True)
    from src.operations_accounts import manual_window_jobs
    monkeypatch.setattr(manual_window_jobs, 'get_incident_window_job', lambda *a, **kw: pytest.fail('Must not enter window scheduling'))
    assert account_manual_windows.dispatch_human_windows(path=path) == []


def test_queued_automatic_window_rechecks_hidden_preference_before_browser(monkeypatch):
    from types import SimpleNamespace
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts.browser_control import BrowserControlRejected
    from src.scheduler import browser_visibility, account_refresh
    monkeypatch.setattr(browser_visibility, 'automatic_window_allowed', lambda account_uuid, **kwargs: False)
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: {'issues': []})
    context = SimpleNamespace(resource=SimpleNamespace(account_uuid='novel'))
    with pytest.raises(BrowserControlRejected) as error:
        bridge._manual(context, {'incident_id': 1})
    assert error.value.code == 'automatic_window_disabled'


def test_confirmed_only_mode_keeps_unconfirmed_and_other_accounts_silent(tmp_path):
    path=tmp_path/'control.db'
    sqlite3.connect(path).close()
    set_automatic_windows('novel',True,confirmed_only=True,authorization='Popup when confirmed CAPTCHA',path=path)
    issue={'account_uuid':'novel','status':'open','error_code':'human_required'}
    assert automatic_window_allowed('novel',issue=issue,path=path)
    assert not automatic_window_allowed('novel',path=path)
    for changes in ({'error_code':'verification_ui_unconfirmed'},{'status':'resolved'},{'account_uuid':'other'}):
        assert not automatic_window_allowed('novel',issue=issue|changes,path=path)


@pytest.mark.parametrize('error_code,expected_lookups',[('human_required',1),('verification_ui_unconfirmed',0)])
def test_scanner_honors_confirmed_only_mode_and_existing_incident_dedup(tmp_path,monkeypatch,error_code,expected_lookups):
    from src.scheduler import account_refresh,account_manual_windows
    from src.operations_accounts import manual_window_jobs
    path=tmp_path/'control.db';sqlite3.connect(path).close()
    set_automatic_windows('novel',True,confirmed_only=True,authorization='Confirmed only',path=path)
    issue=dict(id=1,account_uuid='novel',account_key='novel02',status='open',error_code=error_code)
    monkeypatch.setattr(account_refresh,'snapshot',lambda **kw:{'issues':[issue]})
    monkeypatch.setattr(account_manual_windows,'_eligible',lambda *a:True)
    calls=[]
    def original(*a,**kw):
        calls.append(1)
        return {'state':'closed'}
    monkeypatch.setattr(manual_window_jobs,'get_incident_window_job',original)
    monkeypatch.setattr(manual_window_jobs,'start_manual_window_job',lambda *a,**kw:pytest.fail('Must not reopen original'))
    assert account_manual_windows.dispatch_human_windows(path=path)==[]
    assert len(calls)==expected_lookups
