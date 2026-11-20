"""Local status rendering and guarded recovery controls, without platform calls."""
from copy import deepcopy
from types import SimpleNamespace
import sys
import pytest

from streamlit.testing.v1 import AppTest

from src.web import account_refresh_dashboard as page


@pytest.mark.parametrize('value', [True, False, 'yesterday', float('nan'), float('inf'), -1, 10**100, 10**1000])
def test_invalid_times_never_crash_or_claim_a_fresh_service(value):
    assert page._stamp(value) == '时间无法确认'
    rows = page._service_rows({'scheduler': {'status': 'healthy', 'updated_at': value}}, 1000)
    assert '无法确认' in rows[0]['状态'] or '过期' in rows[0]['状态']


def test_absent_control_does_not_imply_active_schedule():
    assert '未知' in page._schedule_status({'account_uuid': 'A'}, {})


@pytest.mark.parametrize('value', [None, {}, {'accounts': []}, RuntimeError('PRIVATE')])
def test_snapshot_failure_is_visible_without_action_controls(monkeypatch, value):
    from src.scheduler import account_refresh
    def read():
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(account_refresh, 'snapshot', read)
    app = AppTest.from_string('from src.web.account_refresh_dashboard import render_account_refresh\nrender_account_refresh()').run()
    assert not app.exception
    assert any('无法确认' in item.value for item in app.warning)
    assert not app.button and not app.success
    assert not any('PRIVATE' in item.value for item in app.warning)


def _data():
    def account(uuid):
        return {'account_uuid': uuid, 'account_key': uuid.lower(), 'next_due': 100, 'run_id': None}
    return {
        'policy': {'enabled': 1, 'interval_seconds': 14400},
        'smart_policy': {'enabled': 1, 'interval_seconds': 86400},
        'accounts': [account('A'), account('B')], 'smart_accounts': [],
        'runs': [{'account_uuid': 'A', 'account_key': 'a', 'run_id': 'r1',
                  'reason': 'periodic', 'started_at': 50, 'finished_at': 60,
                  'status': 'completed', 'detail': '{}'}], 'smart_runs': [],
        'controls': [{**account('A'), 'state': 'paused', 'reason': '请完成安全验证',
                      'error_code': 'human_required'},
                     {**account('B'), 'state': 'active'}],
        'issues': [{'id': 1, 'account_uuid': 'A', 'account_key': 'a', 'status': 'open',
                    'error_code': 'human_required', 'message': '请完成安全验证', 'created_at': 70}],
        'service': {},
        'playback_policies': [], 'playback_accounts': [], 'playback_runs': [],
    }


def _app(monkeypatch, *, admin=True, data=None, scope='A'):
    from src.scheduler import account_refresh
    from src.web.components import auth
    # This fixture exercises legacy plan/incident controls without a browser
    # store. Managed queue rendering has its own isolated test fixture.
    from src.operations_accounts import browser_control_runtime
    monkeypatch.setattr(browser_control_runtime, 'enabled', lambda: False)
    calls = []
    frames = []
    data = _data() if data is None else data
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.manual_window_jobs',
                        SimpleNamespace(get_manual_window_job=lambda *args: None))
    # Capture the table contract directly. AppTest still exercises real widgets
    # and fragment reruns without requiring the unrelated pandas/Arrow runtime.
    monkeypatch.setattr(page.st, 'dataframe', lambda rows, **kwargs: frames.append(rows))
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: deepcopy(data))
    monkeypatch.setattr(account_refresh, 'pause_account', lambda *args: calls.append(('pause', args)))
    monkeypatch.setattr(account_refresh, 'request_account_recovery', lambda *args: calls.append(('recover', args)) or True)
    def complete(uuid, account_key, **kwargs):
        calls.append(('complete', (uuid, account_key), kwargs))
        next(row for row in data['controls'] if row['account_uuid'] == uuid)['state'] = 'recovery_requested'
        return {'accepted': True, 'state': 'recovery_requested', 'message': '等待核验'}
    monkeypatch.setattr(account_refresh, 'complete_account_handling', complete, raising=False)
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'admin' if admin else 'viewer')
    monkeypatch.setattr(auth, 'get_current_user', lambda: 'operator-test')
    def close(issue_id, uuid, account_key, **kwargs):
        calls.append(('close', (issue_id, uuid, account_key), kwargs))
        row = next(row for row in data['issues'] if row['id'] == issue_id)
        row.update(status='closed', closed_by=kwargs['closed_by'], closed_at=80,
                   closure_note='人工判断无异常，关闭本次提示')
        return True
    monkeypatch.setattr(account_refresh, 'close_account_issue', close, raising=False)
    def save_playback(uuid, key, enabled, interval, options, **kwargs):
        calls.append(('playback_policy', (uuid, key, enabled, interval, options), kwargs))
        policies = data.setdefault('playback_policies', [])
        policies[:] = [row for row in policies if row['account_uuid'] != uuid]
        policies.append({'account_uuid': uuid, 'account_key': key, 'enabled': enabled,
                         'interval_seconds': interval, 'options': options, **kwargs})
    monkeypatch.setattr(account_refresh, 'set_playback_policy', save_playback, raising=False)
    app = AppTest.from_string(
        "import streamlit as st\n"
        f"st.session_state['active_account_uuid'] = {scope!r}\n"
        "from src.web.account_refresh_dashboard import render_account_refresh\n"
        "render_account_refresh()\n", default_timeout=15).run()
    assert not app.exception
    return app, calls, frames


def test_status_render_is_scoped_and_read_only(monkeypatch):
    app, calls, frames = _app(monkeypatch)
    assert calls == []
    assert any('安全验证' in item.value for item in app.warning)
    assert any('最近成功' in item.value for item in app.caption)
    assert 'account_refresh_pause_B' not in {item.key for item in app.button}
    assert any('未知 / 未记录启动' in str(rows) for rows in frames)
    assert any('每 15 秒' in item.value for item in app.caption)


def test_recovery_only_registers_request_for_scoped_account(monkeypatch):
    app, calls, _ = _app(monkeypatch)
    app.button(key='account_refresh_recover_A').click().run()
    assert not app.exception
    assert calls == [('complete', ('A', 'a'), {'handled_by': 'operator-test'})]
    assert app.button(key='account_refresh_recover_A').disabled


def test_viewer_controls_disabled(monkeypatch):
    app, calls, _ = _app(monkeypatch, admin=False)
    assert app.button(key='account_refresh_recover_A').disabled
    assert app.button(key='account_refresh_pause_A').disabled
    assert app.button(key='account_issue_close_1').disabled
    assert calls == []


def test_recovery_rejection_is_visible_without_success_claim(monkeypatch):
    from src.scheduler import account_refresh
    app, _, _ = _app(monkeypatch)
    monkeypatch.setattr(account_refresh, 'complete_account_handling',
                        lambda *args, **kwargs: {'accepted': False, 'state': 'busy', 'message': '未登记新请求，原任务未结束'})
    app.button(key='account_refresh_recover_A').click().run()
    assert not app.exception
    assert any('未登记新请求' in item.value for item in app.warning)
    assert not any('已登记恢复请求' in item.value for item in app.success)


def test_closed_issue_still_allows_completion_from_account_details(monkeypatch):
    data = _data()
    data['issues'][0]['status'] = 'closed'
    app, calls, _ = _app(monkeypatch, data=data)
    assert not app.button(key='account_refresh_recover_A').disabled
    app.button(key='account_refresh_recover_A').click().run()
    assert calls == [('complete', ('A', 'a'), {'handled_by': 'operator-test'})]


def test_detail_completion_blocks_unknown_and_nonterminal_original_runs(monkeypatch):
    data = _data()
    data['accounts'][0]['run_id'] = 'original-inflight'
    app, calls, _ = _app(monkeypatch, data=data)
    assert app.button(key='account_refresh_recover_A').disabled
    assert any('未结束的原运行' in item.value for item in app.caption)
    assert calls == []


def test_stale_or_missing_service_is_never_healthy():
    service = {'scheduler': {'updated_at': 100, 'status': 'running'}}
    assert page._service_rows(service, 101)[0]['状态'] == '心跳正常'
    assert '心跳过期' in page._service_rows(service, 281)[0]['状态']
    assert '未知' in page._service_rows({}, 101)[0]['状态']
    service['task_schedule'] = {'updated_at': 100, 'status': 'failed', 'message': 'migration failed'}
    assert page._service_rows(service, 101)[-1]['说明'] == 'migration failed'


def test_refresh_fragment_is_local_and_periodic(monkeypatch):
    calls = []
    def fragment(**kwargs):
        calls.append(kwargs)
        return lambda function: function
    monkeypatch.setattr(page, 'st', SimpleNamespace(fragment=fragment))
    monkeypatch.setattr(page, '_render_account_refresh', lambda: calls.append('local'))
    page.render_account_refresh()
    assert calls == [{'run_every': 15}, 'local']


def test_paused_plan_does_not_display_waiting_or_executing():
    row = {'account_uuid': 'A', 'run_id': None}
    assert page._schedule_status(row, {'A': {'state': 'paused'}}) == '已暂停，待处理'


def test_completed_partial_result_keeps_error_visible():
    row = {'status': 'completed', 'detail': {'error_code': 'human_required'}}
    assert page._run_status(row, {'completed': '完成'}) == '已有结果，附异常记录'


def test_issue_close_hides_only_current_warning_and_keeps_pause_and_history(monkeypatch):
    data = _data()
    app, calls, frames = _app(monkeypatch, data=data)
    app.button(key='account_issue_close_1').click().run()
    assert not app.exception
    assert calls == [('close', (1, 'A', 'a'), {'closed_by': 'operator-test'})]
    assert not any('安全验证' in item.value for item in app.warning)
    assert any('已暂停' in item.value for item in app.markdown)
    assert any('已人工关闭' in item.value for item in app.caption)
    assert any(item.label == '已关闭 / 已解决异常历史（1）' for item in app.expander)
    assert any('operator-test' in str(rows) and '人工判断无异常' in str(rows) for rows in frames)
    assert data['controls'][0]['state'] == 'paused'


def test_new_same_error_reappears_after_closure(monkeypatch):
    data = _data()
    app, calls, _ = _app(monkeypatch, data=data)
    app.button(key='account_issue_close_1').click().run()
    data['issues'].append({**data['issues'][0], 'id': 2, 'status': 'open', 'message': '再次安全验证'})
    app.run()
    assert not app.exception
    assert any('再次安全验证' in item.value for item in app.warning)
    assert 'account_issue_close_2' in {button.key for button in app.button}
    assert len(calls) == 1


def test_closing_old_issue_preserves_concurrent_open_and_scope(monkeypatch):
    data = _data()
    data['issues'].extend([
        {**data['issues'][0], 'id': 2, 'message': '新到达异常'},
        {**data['issues'][0], 'id': 3, 'account_uuid': 'B', 'account_key': 'b', 'message': '其他账号异常'},
        {**data['issues'][0], 'id': 4, 'account_uuid': 'B', 'account_key': 'b', 'status': 'closed'},
    ])
    app, calls, frames = _app(monkeypatch, data=data)
    app.button(key='account_issue_close_1').click().run()
    assert not app.exception
    assert any('新到达异常' in item.value for item in app.warning)
    assert not any('其他账号' in item.value for item in app.warning)
    assert 'account_issue_close_3' not in {button.key for button in app.button}
    assert not any("'账号': 'b'" in str(rows) for rows in frames)
    assert len(calls) == 1


def test_issue_close_false_does_not_claim_success(monkeypatch):
    from src.scheduler import account_refresh
    app, calls, _ = _app(monkeypatch)
    monkeypatch.setattr(account_refresh, 'close_account_issue', lambda *args, **kwargs: False)
    app.button(key='account_issue_close_1').click().run()
    assert not app.exception
    assert any('未关闭本条提示' in item.value for item in app.warning)
    assert not any('已关闭本条提示' in item.value for item in app.success)
    assert calls == []


def test_missing_legacy_issue_data_shows_unknown_and_blocks_actions(monkeypatch):
    data = _data()
    del data['issues']
    app, _, _ = _app(monkeypatch, data=data)
    assert any('记录不完整' in item.value for item in app.warning)
    assert not app.button
    assert not any('暂无待处理异常' in item.value for item in app.caption)


def test_automatic_playback_defaults_are_not_saved_or_enabled_by_render(monkeypatch):
    app, calls, _ = _app(monkeypatch)
    assert app.checkbox(key='account_playback_A_enabled').value is False
    assert app.number_input(key='account_playback_A_interval').value == 24
    assert app.number_input(key='account_playback_A_videos').value == 20
    assert app.number_input(key='account_playback_A_seconds').value == 90
    assert app.number_input(key='account_playback_A_minutes').value == 20
    assert app.number_input(key='account_playback_A_relevance').value == 60
    app.run()
    assert not app.exception
    assert calls == []


def test_automatic_playback_save_is_scoped_persistent_and_has_no_interactions(monkeypatch):
    data = _data()
    app, calls, frames = _app(monkeypatch, data=data)
    app.checkbox(key='account_playback_A_enabled').check()
    app.number_input(key='account_playback_A_interval').set_value(12)
    app.number_input(key='account_playback_A_videos').set_value(5)
    app.button(key='account_playback_A_save').click().run()
    assert not app.exception
    assert len(calls) == 1 and calls[0][0] == 'playback_policy'
    uuid, key, enabled, interval, options = calls[0][1]
    assert (uuid, key, enabled, interval) == ('A', 'a', True, 43200)
    assert options == {'max_videos': 5, 'per_video_seconds': 90, 'total_minutes': 20,
                       'min_relevance_score': 60.0, 'auto_like': False, 'auto_comment': False}
    assert calls[0][2]['authorization_reference'] == '管理员 operator-test 在前端保存自动播放计划'
    assert any("'已保存启用': True" in str(rows) and "'最多视频数': 5" in str(rows) for rows in frames)
    app.run()
    assert len(calls) == 1


def test_summary_playback_settings_are_read_only(monkeypatch):
    app, calls, _ = _app(monkeypatch, scope='*')
    assert 'account_playback_*_enabled' not in {item.key for item in app.checkbox}
    assert not any(item.label == '保存此账号自动播放计划' for item in app.button)
    assert any('汇总视图只查看' in item.value for item in app.caption)
    assert calls == []


def test_random_playback_form_saves_mode_and_displays_actual_arrangement(monkeypatch):
    app, calls, frames = _app(monkeypatch)
    app.checkbox(key='account_playback_A_enabled').check()
    app.selectbox(key='account_playback_A_mode').select('每天三个随机时段')
    app.button(key='account_playback_A_save').click().run()
    assert not app.exception
    assert calls[0][2]['schedule'] == {'mode': 'random_daily_three'}
    assert calls[0][1][4]['auto_like'] is False
    assert calls[0][1][4]['auto_comment'] is False
    assert any("'执行方式': '每天三个随机时段'" in str(rows) and "'间隔（小时）': None" in str(rows)
               for rows in frames)


def test_playback_viewer_cannot_save_or_enable(monkeypatch):
    app, calls, _ = _app(monkeypatch, admin=False)
    assert app.checkbox(key='account_playback_A_enabled').disabled
    assert app.button(key='account_playback_A_save').disabled
    assert calls == []


def test_playback_fields_read_saved_policy_and_hide_other_accounts(monkeypatch):
    data = _data()
    data['playback_policies'] = [
        {'account_uuid': uuid, 'account_key': uuid.lower(), 'enabled': True,
         'interval_seconds': 43200, 'options': {'max_videos': 7, 'per_video_seconds': 45,
                                               'total_minutes': 10, 'min_relevance_score': 75}}
        for uuid in ('A', 'B')]
    app, calls, frames = _app(monkeypatch, data=data)
    assert app.checkbox(key='account_playback_A_enabled').value is True
    assert app.number_input(key='account_playback_A_videos').value == 7
    assert app.number_input(key='account_playback_A_seconds').value == 45
    assert app.number_input(key='account_playback_A_relevance').value == 75
    assert not any("'账号': 'b'" in str(rows) for rows in frames)
    assert calls == []


def test_playback_actual_count_and_no_candidate_skip_are_honest(monkeypatch):
    data = _data()
    data['playback_runs'] = [{'account_uuid': 'A', 'account_key': 'a', 'run_id': 'play1',
                             'started_at': 100, 'finished_at': 110, 'status': 'skipped',
                             'detail': {'requested_max_videos': 20, 'playback_verified_videos': 0,
                                        'error_code': 'no_playback_candidates', 'message': '本轮无候选'}}]
    app, calls, frames = _app(monkeypatch, data=data)
    assert not app.exception
    assert any("'最近实际验证播放数': 0" in str(rows) for rows in frames)
    assert any('无候选，本轮未播放' in str(rows) for rows in frames)
    assert calls == []


def test_playback_states_distinguish_due_busy_paused_and_unknown():
    policy = {'enabled': True}
    account = {'next_due': 0}
    assert page._playback_state(policy, account, {}, [], busy=True) == '等待账号空闲'
    assert '已到期' in page._playback_state(policy, account, {}, [])
    assert '暂停' in page._playback_state(policy, account, {'state': 'paused'}, [])
    assert '结果未知' in page._playback_state(policy, account, {'state': 'paused'}, [{'status': 'outcome_unknown'}])
