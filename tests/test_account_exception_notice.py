"""Cross-page authenticated notices never visit the platform or recover tasks."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

from streamlit.testing.v1 import AppTest

from src.web import account_exception_notice as notice


def _issue(issue_id, key='a', status='open'):
    return {'id': issue_id, 'account_uuid': key.upper(), 'account_key': key, 'status': status,
            'message': f'{key}需要完成安全验证', 'error_code': 'human_required', 'created_at': 100}


def _app(monkeypatch, *, issues=None, user='operator-test', role='admin', fail_read=False, with_detail=False):
    from src.scheduler import account_refresh
    from src.web.components import auth
    data = {'issues': [_issue(1)] if issues is None else issues,
            'controls': [{'account_uuid': key.upper(), 'account_key': key, 'state': 'paused'} for key in ('a', 'b')],
            'accounts': [], 'smart_accounts': [], 'playback_accounts': [], 'runs': [], 'smart_runs': [], 'playback_runs': []}
    if with_detail:
        data.update(policy={'enabled': 1, 'interval_seconds': 14400},
                    smart_policy={'enabled': 1, 'interval_seconds': 86400},
                    service={})
        monkeypatch.setattr(notice.st, 'dataframe', lambda *args, **kwargs: None)
    calls, links = [], []
    def read():
        calls.append(('read',))
        if fail_read:
            raise RuntimeError('private diagnostic omitted')
        return deepcopy(data)
    def close(issue_id, uuid, key, **kwargs):
        calls.append(('close', (issue_id, uuid, key), kwargs))
        next(row for row in data['issues'] if row['id'] == issue_id)['status'] = 'closed'
        return True
    monkeypatch.setattr(account_refresh, 'snapshot', read)
    monkeypatch.setattr(account_refresh, 'close_account_issue', close)
    def complete(uuid, key, **kwargs):
        calls.append(('complete', (uuid, key), kwargs))
        next(row for row in data['controls'] if row['account_uuid'] == uuid)['state'] = 'recovery_requested'
        return {'accepted': True, 'state': 'recovery_requested', 'message': '等待核验'}
    monkeypatch.setattr(account_refresh, 'complete_account_handling', complete, raising=False)
    jobs = data.setdefault('_window_jobs', {})
    def get_job(uuid, key):
        data['_window_reads'] = data.get('_window_reads', 0) + 1
        return deepcopy(jobs.get(uuid))
    def open_window(uuid, key, requested_by, **kwargs):
        calls.append(('open_window', (uuid, key), {'requested_by': requested_by, **kwargs}))
        jobs[uuid] = {'job_id': 'job-' + uuid, 'account_uuid': uuid, 'account_key': key, 'state': 'closed', 'phase': 'closed'}
        return dict(jobs[uuid])
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.manual_window_jobs',
                        SimpleNamespace(get_manual_window_job=get_job, start_manual_window_job=open_window))
    monkeypatch.setattr(auth, 'get_current_user', lambda: user)
    monkeypatch.setattr(auth, 'get_current_role', lambda: role)
    monkeypatch.setattr(notice.st, 'switch_page', lambda target: links.append(target))
    target = object()
    monkeypatch.setattr(notice, '_test_destination', target, raising=False)
    app = AppTest.from_string(
        "import streamlit as st\n"
        "st.session_state.setdefault('active_account_uuid', 'A')\n"
        "from src.web import account_exception_notice as notice\n"
        "notice.render_account_exception_notice(notice._test_destination)\n" + (
            "from src.web.account_refresh_dashboard import render_account_refresh\nrender_account_refresh()\n" if with_detail else ''),
        default_timeout=15).run()
    assert not app.exception
    return app, data, calls, links, target


def test_global_notice_shows_all_open_accounts_and_registered_page(monkeypatch):
    app, _, calls, links, target = _app(monkeypatch, issues=[_issue(1), _issue(2, 'b'), _issue(3, status='closed')])
    assert len(app.warning) == 2
    assert all('待人工处理' in item.value for item in app.warning)
    assert any('账号 b' in item.value for item in app.warning)
    assert any('北京时间' in item.value for item in app.caption)
    assert links == []
    assert 'global_account_issue_open_2' in {item.key for item in app.button}
    assert 'global_account_issue_close_3' not in {item.key for item in app.button}
    assert calls == [('read',)]


def test_same_account_incidents_have_one_set_of_actions_and_individual_closure(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch, issues=[_issue(1), {**_issue(2), 'created_at': 200}])
    keys = [item.key for item in app.button]
    assert [key for key in keys if key.startswith('global_account_issue_open_')] == ['global_account_issue_open_2']
    assert [key for key in keys if key.startswith('global_account_handling_complete_')] == ['global_account_handling_complete_2']
    assert {'global_account_issue_close_1', 'global_account_issue_close_2'} <= set(keys)
    app.button(key='global_account_issue_close_1').click().run()
    assert next(row for row in data['issues'] if row['id'] == 2)['status'] == 'open'
    assert not any(event[0] in ('complete', 'open_window') for event in calls)


def test_stale_owner_disables_reveal_and_completion_without_old_probe_claim(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    data['_window_jobs']['A'] = {'job_id': 'original-stale', 'account_uuid': 'A', 'account_key': 'a',
        'state': 'running', 'phase': 'window_owner_unconfirmed', 'managed': True,
        'handoff_ready': False, 'owner_status': 'stale', 'owner_heartbeat_at': 100}
    app.run()
    assert app.button(key='global_account_issue_open_1').disabled
    assert app.button(key='global_account_handling_complete_1').disabled
    assert any('原窗口服务' in item.value for item in app.warning)
    assert any('最后心跳' in item.value for item in app.caption)
    assert not any('当前未检测到验证' in item.value for item in app.info)
    assert not any(event[0] in ('complete', 'open_window') for event in calls)


def test_old_boot_cleanup_requires_exact_explicit_confirmation_and_never_resumes(monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    app, data, calls, _, _ = _app(monkeypatch)
    data['_window_jobs']['A'] = {'job_id': 'old-original', 'account_uuid': 'A', 'account_key': 'a',
        'state': 'running', 'phase': 'window_owner_unconfirmed', 'handoff_ready': False, 'managed': True,
        'previous_boot_cleanup': {'available': True, 'proof_sha': 'fixture-proof'}}
    actions = []
    def settle(*args):
        actions.append(args)
        data['_window_jobs']['A'].update(state='closed', phase='closed_by_previous_boot', session_saved=False)
    monkeypatch.setattr(bridge, 'close_manual_before_previous_boot', settle)
    app.run()
    assert app.button(key='global_account_issue_open_1_boot_settle').disabled
    app.checkbox(key='global_account_issue_open_1_boot_confirm_old-original').check()
    app.button(key='global_account_issue_open_1_boot_settle').click().run()
    assert actions == [('A', 'a', 'old-original', 'fixture-proof', 'operator-test')]
    assert not app.exception and not any(event[0] in ('complete', 'open_window') for event in calls)
    assert any('会话保存情况未确认' in x.value for x in app.info)


def test_no_open_issues_occupies_no_page_space(monkeypatch):
    app, _, calls, links, _ = _app(monkeypatch, issues=[])
    assert not app.warning and not app.markdown and not app.caption and not app.button
    assert links == [] and calls == [('read',)]


def test_detail_pages_global_notice_is_summary_without_duplicate_actions(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    summary = AppTest.from_string('from src.web.account_exception_notice import render_account_exception_notice\n'
                                 'render_account_exception_notice(summary_only=True)').run()
    assert not summary.exception and not summary.button
    assert any('待处理账号' in item.value for item in summary.info)
    assert not any(event[0] in ('complete', 'open_window') for event in calls)


def test_unauthenticated_view_does_not_read_or_reveal_account_data(monkeypatch):
    app, _, calls, links, _ = _app(monkeypatch, user=None)
    assert not app.warning and not app.button and not app.caption
    assert calls == [] and links == []


def test_fragment_rechecks_authentication_after_logout(monkeypatch):
    from src.scheduler import account_refresh
    from src.web.components import auth
    monkeypatch.setattr(auth, 'get_current_user', lambda: None)
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: (_ for _ in ()).throw(AssertionError('read after logout')))
    monkeypatch.setattr(notice, 'st', SimpleNamespace(empty=lambda: SimpleNamespace(empty=lambda: None)))
    notice._render_account_exception_notice()
    notice._render_handling_completion('A', 'a', 'completion_after_logout')


def test_viewer_has_read_only_notice(monkeypatch):
    app, _, calls, _, _ = _app(monkeypatch, role='viewer')
    assert app.button(key='global_account_issue_close_1').disabled
    assert app.button(key='global_account_issue_open_1').disabled
    assert app.button(key='global_account_handling_complete_1').disabled
    assert calls == [('read',)]


def test_close_is_exact_local_action_and_new_issue_reappears(monkeypatch):
    from src.scheduler import account_refresh
    def forbidden(*args, **kwargs):
        raise AssertionError('close must not resume tasks')
    monkeypatch.setattr(account_refresh, 'request_account_recovery', forbidden)
    monkeypatch.setattr(account_refresh, 'pause_account', forbidden)
    app, data, calls, _, _ = _app(monkeypatch)
    monkeypatch.setattr(account_refresh, 'complete_account_handling', forbidden)
    app.button(key='global_account_issue_close_1').click().run()
    assert not app.exception
    assert [item for item in calls if item[0] == 'close'] == [('close', (1, 'A', 'a'), {'closed_by': 'operator-test'})]
    assert not app.warning, ([item.value for item in app.warning], calls)
    data['issues'].append(_issue(2))
    app.run()
    assert any('安全验证' in item.value for item in app.warning)
    assert 'global_account_issue_close_2' in {item.key for item in app.button}
    assert 'global_account_issue_close_1' not in {item.key for item in app.button}


def test_go_handle_directly_opens_exception_account_without_navigation(monkeypatch):
    app, _, calls, links, target = _app(monkeypatch, issues=[_issue(2, 'b')])
    assert app.session_state['active_account_uuid'] == 'A'
    app.button(key='global_account_issue_open_2').click().run()
    assert not app.exception
    assert app.session_state['active_account_uuid'] == 'B'
    assert links == []
    assert [item for item in calls if item[0] == 'open_window'] == [('open_window', ('B', 'b'), {'requested_by': 'operator-test'})]
    assert any('人工窗口已关闭' in item.value for item in app.info)
    assert not any(item[0] in ('complete', 'close') for item in calls)
    app.run()
    assert len([item for item in calls if item[0] == 'open_window']) == 1


def test_open_window_failure_is_explicit_and_does_not_complete_or_close(monkeypatch):
    jobs = sys.modules.get('src.operations_accounts.manual_window_jobs')
    app, _, calls, links, _ = _app(monkeypatch)
    jobs = sys.modules['src.operations_accounts.manual_window_jobs']
    error = RuntimeError('private transport or cookie diagnostics')
    error.code = 'locked'
    def fail_open(*args, **kwargs):
        raise error
    monkeypatch.setattr(jobs, 'start_manual_window_job', fail_open)
    app.button(key='global_account_issue_open_1').click().run()
    assert not app.exception
    assert any('原账号任务或窗口仍持有运行锁' in item.value for item in app.error)
    assert not any('private transport' in item.value for item in app.error)
    assert not app.info and links == []
    assert not any(item[0] in ('complete', 'close') for item in calls)


def test_job_polling_changes_opened_to_closed_without_new_start(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    job = {'job_id': 'original-window', 'account_uuid': 'A', 'account_key': 'a',
           'state': 'running', 'phase': 'window_open_waiting_close'}
    data['_window_jobs']['A'] = job
    app.run()
    assert any('窗口已打开' in item.value for item in app.info)
    assert app.button(key='global_account_issue_open_1').disabled
    assert app.button(key='global_account_handling_complete_1').disabled
    job.update(state='closed', phase='closed')
    app.run()
    assert any('人工窗口已关闭' in item.value for item in app.info)
    assert not any('窗口已打开' in item.value for item in app.info)
    assert not app.button(key='global_account_handling_complete_1').disabled
    assert not any(item[0] in ('open_window', 'complete', 'close') for item in calls)


def test_managed_open_window_allows_completion_without_duplicate_open(monkeypatch):
    from src.operations_accounts import manual_window_visibility
    app, data, calls, _, _ = _app(monkeypatch)
    data['_window_jobs']['A'] = {'job_id': 'original-managed-window',
        'account_uuid': 'A', 'account_key': 'a', 'state': 'running',
        'phase': 'window_current_no_challenge', 'managed': True, 'handoff_ready': True}
    app.run()
    assert not app.button(key='global_account_issue_open_1').disabled
    assert app.button(key='global_account_issue_open_1').label == '重新显示原账号处理窗口'
    assert not app.button(key='global_account_handling_complete_1').disabled
    assert any('无需关闭窗口' in item.value for item in app.caption)
    app.run()
    assert not app.exception
    assert not any(item[0] in ('open_window', 'complete', 'close') for item in calls)
    assert not app.button(key='global_account_handling_complete_1').disabled
    reveal_requests = []
    monkeypatch.setattr(manual_window_visibility, 'queue', lambda uuid, key: reveal_requests.append((uuid,key)))
    app.button(key='global_account_issue_open_1').click().run()
    assert reveal_requests == [('A','a')]
    assert not any(item[0] == 'open_window' for item in calls)
    app.button(key='global_account_handling_complete_1').click().run()
    assert len([item for item in calls if item[0] == 'complete']) == 1
    assert not any(item[0] == 'open_window' for item in calls)


def test_unknown_window_task_keeps_original_id_and_blocks_reopen(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    data['_window_jobs']['A'] = {'job_id': 'unknown-original', 'account_uuid': 'A', 'account_key': 'a',
                                'state': 'outcome_unknown', 'phase': 'outcome_unknown'}
    app.run()
    assert app.button(key='global_account_issue_open_1').disabled
    assert app.button(key='global_account_handling_complete_1').disabled
    assert any('结果未知' in item.value for item in app.warning)
    assert any('unknown-original' in item.value for item in app.caption)
    assert not any(item[0] == 'open_window' for item in calls)


def test_real_browser_worker_startup_timeout_code_is_clear_on_poll(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    data['_window_jobs']['A'] = {'job_id': 'failed-worker', 'account_uuid': 'A', 'account_key': 'a',
                                'state': 'failed', 'phase': 'failed', 'error_code': 'browser_start_timeout',
                                'error_type': 'BrowserWorkerStartupTimeout'}
    app.run()
    assert any('超时' in item.value and '未自动重试' in item.value for item in app.error)
    assert 'Chrome 启动失败' in notice._manual_window_error('browser_start_failed')
    assert not any(item[0] in ('open_window', 'complete') for item in calls)


def test_completion_registers_original_issue_account_and_waits_without_duplicate(monkeypatch):
    app, _, calls, _, _ = _app(monkeypatch, issues=[_issue(2, 'b')])
    app.button(key='global_account_handling_complete_2').click().run()
    assert not app.exception
    assert [item for item in calls if item[0] == 'complete'] == [('complete', ('B', 'b'), {'handled_by': 'operator-test'})]
    assert app.button(key='global_account_handling_complete_2').disabled
    assert any('等待后台核验' in item.value for item in app.caption)
    assert not app.success
    app.run()
    assert len([item for item in calls if item[0] == 'complete']) == 1


def test_unknown_original_run_disables_completion(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    data['playback_runs'].append({'account_uuid': 'A', 'status': 'outcome_unknown'})
    app.run()
    assert app.button(key='global_account_handling_complete_1').disabled
    assert any('原运行结果未知' in item.value for item in app.caption)
    assert not any(item[0] == 'complete' for item in calls)


def test_completion_race_rejection_does_not_claim_restored(monkeypatch):
    from src.scheduler import account_refresh
    app, _, _, _, _ = _app(monkeypatch)
    monkeypatch.setattr(account_refresh, 'complete_account_handling',
                        lambda *args, **kwargs: {'accepted': False, 'state': 'busy', 'message': '原任务仍在运行'})
    app.button(key='global_account_handling_complete_1').click().run()
    assert any('原任务仍在运行' in item.value for item in app.warning)
    assert not app.info and not app.success


def test_handling_guard_preserves_unknown_and_unsettled_probe():
    for code in ('outcome_unknown', 'recovery_outcome_unknown'):
        data = {'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'recovery_requested', 'error_code': code}]}
        assert notice._handling_state(data, 'A', 'a')[0] == 'outcome_unknown'
        assert notice._handling_state(data, 'A', 'a')[2] is False
    data = {'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused', 'recovery_lease_until': 1}]}
    assert notice._handling_state(data, 'A', 'a')[0] == 'busy'
    assert notice._handling_state(data, 'A', 'a')[2] is False


@pytest.mark.parametrize('status,error_code', [('failed', ''), ('degraded', 'scheduler_database_busy'),
                                              ('healthy', 'scheduler_database_busy')])
def test_stopped_backend_disables_completion_and_never_registers_request(monkeypatch, status, error_code):
    app, data, calls, _, _ = _app(monkeypatch)
    data['service'] = {'scheduler': {'status': status, 'error_code': error_code, 'updated_at': notice.time.time()}}
    app.run()
    assert app.button(key='global_account_handling_complete_1').disabled
    assert any('后台服务异常' in item.value for item in app.caption)
    assert not any(item[0] == 'complete' for item in calls)


def test_stale_healthy_heartbeat_cannot_enable_completion(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch)
    data['service'] = {'account_refresh': {'status': 'healthy', 'updated_at': notice.time.time() - 181}}
    app.run()
    assert app.button(key='global_account_handling_complete_1').disabled
    assert any('心跳过期' in item.value for item in app.caption)
    assert not any(item[0] == 'complete' for item in calls)


def test_missing_service_is_compatible_and_fresh_service_does_not_claim_recovery():
    data = {'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused'}]}
    assert notice._handling_state(data, 'A', 'a')[2] is True
    data['service'] = {'scheduler': {'status': 'healthy', 'updated_at': notice.time.time()}}
    _, message, ready = notice._handling_state(data, 'A', 'a')
    assert ready is True and '先核验原会话' in message and '已恢复' not in message


def test_close_false_is_visible_without_success_claim(monkeypatch):
    from src.scheduler import account_refresh
    app, _, _, _, _ = _app(monkeypatch)
    monkeypatch.setattr(account_refresh, 'close_account_issue', lambda *args, **kwargs: False)
    app.button(key='global_account_issue_close_1').click().run()
    assert any('未关闭本条提示' in item.value for item in app.warning)
    assert not app.success


def test_failed_read_is_unknown_not_empty_or_raw_diagnostics(monkeypatch):
    app, _, _, links, _ = _app(monkeypatch, fail_read=True)
    assert any('状态暂不可用' in item.value for item in app.warning)
    assert not any('private diagnostic' in item.value for item in app.warning)
    assert not app.button and links == []


def test_partial_malformed_open_issue_does_not_break_page(monkeypatch):
    app, _, _, _, _ = _app(monkeypatch, issues=[{**_issue(1), 'created_at': 'invalid timestamp'}])
    assert not app.exception
    assert any('状态暂不可用' in item.value for item in app.warning)
    assert not app.button


def test_global_and_detail_notice_keys_are_independent(monkeypatch):
    app, _, _, _, _ = _app(monkeypatch, with_detail=True)
    keys = [item.key for item in app.button]
    assert 'global_account_issue_close_1' in keys and 'account_issue_close_1' in keys
    assert len(keys) == len(set(keys))


def test_notice_refresh_is_periodic_and_preserves_destination(monkeypatch):
    from src.web.components import auth
    calls = []
    monkeypatch.setattr(auth, 'get_current_user', lambda: 'operator-test')
    def fragment(**kwargs):
        calls.append(kwargs)
        return lambda function: function
    monkeypatch.setattr(notice, 'st', SimpleNamespace(fragment=fragment))
    monkeypatch.setattr(notice, '_render_account_exception_notice', lambda target: calls.append(target))
    target = object()
    notice.render_account_exception_notice(target)
    assert calls == [{'run_every': 15}, target]


def test_app_notice_runs_after_authentication_before_navigation_content():
    app_file = Path(__file__).resolve().parents[1] / 'src/web/app.py'
    tree = ast.parse(app_file.read_text(encoding='utf-8-sig'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    login = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'render_login_page')
    banner = next(node for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'render_account_exception_notice')
    navigate = next(node for node in calls if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'navigation' and node.func.attr == 'run')
    assert login.lineno < banner.lineno < navigate.lineno
    assert ast.unparse(banner.args[0]) == "studio_destinations.get('accounts')"


def _backend_issue(issue_id=4, key='a', code='scheduler_database_busy'):
    return {**_issue(issue_id, key), 'error_code': code,
            'message': notice._LEGACY_PLAYBACK_SCAN_MESSAGE}


def test_recovered_backend_history_has_current_state_without_browser_action(monkeypatch):
    app, data, calls, _, _ = _app(monkeypatch, issues=[_backend_issue()])
    now = notice.time.time()
    data['service'] = {name: {'status': 'healthy', 'updated_at': now - 1}
                       for name in ('scheduler', 'playback_schedule')}
    app.run()
    assert any('后台故障历史' in item.value for item in app.info)
    assert any('相关后台扫描已恢复' in item.value and '账号暂停不会自动解除' in item.value for item in app.caption)
    assert any('播放计划扫描：正常' in item.value for item in app.caption)
    keys = {item.key for item in app.button}
    assert 'global_account_issue_open_4' not in keys
    assert 'global_account_issue_close_4' in keys and 'global_account_handling_complete_4' in keys
    assert not app.button(key='global_account_handling_complete_4').disabled
    assert not any(item[0] in ('open_window', 'complete', 'close') for item in calls)
    app.button(key='global_account_handling_complete_4').click().run()
    assert not app.exception
    assert [item for item in calls if item[0] == 'complete'] == [('complete', ('A', 'a'), {'handled_by': 'operator-test'})]
    assert app.button(key='global_account_handling_complete_4').disabled
    assert not any(item[0] in ('open_window', 'close') for item in calls)


@pytest.mark.parametrize('condition', ['missing', 'stale', 'failed', 'running', 'before_incident'])
def test_backend_recovery_requires_fresh_postincident_normal_components(monkeypatch, condition):
    app, data, _, _, _ = _app(monkeypatch, issues=[_backend_issue()])
    now = notice.time.time()
    data['issues'][0]['created_at'] = now - 300
    data['service'] = {name: {'status': 'healthy', 'updated_at': now - 1}
                       for name in ('scheduler', 'playback_schedule')}
    if condition == 'missing':
        del data['service']['playback_schedule']
    elif condition == 'stale':
        data['service']['playback_schedule']['updated_at'] = now - 181
    elif condition == 'failed':
        data['service']['playback_schedule']['status'] = 'failed'
    elif condition == 'running':
        data['service']['playback_schedule']['status'] = 'running'
    else:
        data['issues'][0]['created_at'] = now - 1
        data['service']['playback_schedule']['updated_at'] = now - 2
    app.run()
    assert not any('相关后台扫描已恢复' in item.value for item in app.caption)
    assert any('尚无足够证据' in item.value for item in app.caption)
    assert 'global_account_issue_open_4' not in {item.key for item in app.button}
    assert app.button(key='global_account_handling_complete_4').disabled


def test_backend_and_other_account_platform_issues_keep_separate_actions(monkeypatch):
    app, _, calls, _, _ = _app(monkeypatch, issues=[_backend_issue(), _issue(5, 'b')])
    keys = {item.key for item in app.button}
    assert 'global_account_issue_open_4' not in keys and 'global_account_issue_open_5' in keys
    app.button(key='global_account_issue_close_4').click().run()
    assert not app.exception
    assert any('账号 b' in item.value for item in app.warning)
    assert [item for item in calls if item[0] == 'close'] == [('close', (4, 'A', 'a'), {'closed_by': 'operator-test'})]
    assert 'global_account_issue_open_5' in {item.key for item in app.button}
    assert not any(item[0] in ('open_window', 'complete') for item in calls)


def test_backend_issue_viewer_is_read_only_and_platform_entry_remains(monkeypatch):
    app, _, calls, _, _ = _app(monkeypatch, issues=[_backend_issue(), _issue(5, 'b')], role='viewer')
    assert app.button(key='global_account_issue_close_4').disabled
    assert app.button(key='global_account_handling_complete_4').disabled
    assert app.button(key='global_account_issue_open_5').disabled
    assert not any(item[0] in ('open_window', 'complete', 'close') for item in calls)


def test_backend_classification_uses_explicit_codes_and_exact_legacy_message():
    assert notice._incident_components(_backend_issue(code='account_refresh_unavailable')) == ('scheduler', 'account_refresh')
    assert notice._incident_components(_backend_issue(code='playback_schedule_unavailable')) == ('scheduler', 'playback_schedule')
    assert notice._incident_components(_backend_issue(code='unexpected_error')) == ('scheduler', 'playback_schedule')
    assert notice._incident_components({**_backend_issue(code='unexpected_error'), 'message': notice._LEGACY_PLAYBACK_SCAN_MESSAGE + '其他'}) == ()
    assert notice._incident_components(_backend_issue(code='human_required')) == ()
    assert notice._incident_components(_backend_issue(code='other_error')) == ()


@pytest.mark.parametrize('updated,status', [(1001, 'healthy'), (float('nan'), 'healthy'),
                                          (True, 'healthy'), (999, 'running')])
def test_backend_recovery_rejects_future_invalid_and_running_receipts(updated, status):
    issue = {**_backend_issue(), 'created_at': 900}
    data = {'service': {'scheduler': {'status': 'healthy', 'updated_at': 999},
                        'playback_schedule': {'status': status, 'updated_at': updated}}}
    recovered, _ = notice._backend_incident_state(issue, data, notice._incident_components(issue), 1000)
    assert recovered is False
