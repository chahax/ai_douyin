"""Account information automation status and persisted execution log."""
import json
import time
from math import isfinite
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st


def _scope_rows(rows, scope):
    return [row for row in rows if scope == '*' or row.get('account_uuid') == scope]


def _stamp(value):
    if type(value) is bool:
        return '时间无法确认'
    if value is None or value == 0:
        return '未记录'
    if not _valid_time(value):
        return '时间无法确认'
    try:
        return datetime.fromtimestamp(value, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    except (OSError, OverflowError, ValueError):
        return '时间无法确认'


def _valid_time(value):
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value) and value >= 0
    except OverflowError:
        return False


def _detail(row):
    value = row.get('detail') or {}
    if isinstance(value, dict):
        return value
    try:
        value = json.loads(value)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _run_status(row, statuses):
    if row.get('correction'):
        return '原结果需复核'
    if row.get('status') == 'completed' and _detail(row).get('error_code'):
        return '已有结果，附异常记录'
    return statuses.get(row['status'], row['status'])


def _service_rows(service, now):
    rows = []
    names = list(dict.fromkeys(('scheduler', 'worker', 'account_refresh', *sorted(service))))
    for name in names:
        item = service.get(name) or {}
        updated = item.get('updated_at')
        fresh = _valid_time(updated) and 0 <= now - updated <= 180
        status = item.get('status')
        if not item:
            label = '未知 / 未记录启动'
        elif not _valid_time(updated) or updated > now:
            label = '心跳时间无法确认 / 需核对后台记录'
        elif not fresh and name == 'account_refresh' and status == 'running':
            label = '执行中 / 最近检查较久，需核对运行日志'
        elif not fresh:
            label = '心跳过期 / 需检查后台进程'
        else:
            label = {'running': '心跳正常', 'healthy': '本轮调度检查正常', 'started': '已启动', 'idle': '等待任务',
                     'stopped': '已停止', 'failed': '异常', 'error': '异常',
                     'blocked': '受阻', 'human_required': '待人工处理',
                     'manual_required': '待人工处理', 'stale': '心跳过期'}.get(status, str(status or '未知'))
        rows.append({'服务': name, '状态': label, '最近心跳（北京时间）': _stamp(updated),
                     '说明': item.get('message', ''), '错误码': item.get('error_code', '')})
    return rows


def render_account_refresh():
    # Refresh only this local database fragment; never rerun platform actions.
    fragment = getattr(st, 'fragment', None)
    if callable(fragment):
        fragment(run_every=15)(_render_account_refresh)()
    else:
        _render_account_refresh()


def _render_account_refresh():
    from src.scheduler.account_refresh import snapshot, set_policy, set_smart_policy
    from src.web.components.auth import get_current_role, has_permission
    st.subheader('账号信息自动更新')
    try:
        data = snapshot()
        for key in ('accounts', 'runs', 'smart_accounts', 'smart_runs', 'controls', 'issues'):
            if not isinstance(data.get(key), list) or any(not isinstance(row, dict) for row in data[key]):
                raise ValueError('incomplete account snapshot')
        for key in ('policy', 'smart_policy'):
            policy = data.get(key)
            if (not isinstance(policy, dict) or 'enabled' not in policy
                    or type(policy.get('interval_seconds')) is not int or policy['interval_seconds'] <= 0):
                raise ValueError('incomplete policy snapshot')
    except Exception:
        st.warning('自动化状态读取失败或记录不完整；当前无法确认任务是否正常。请检查后台后刷新，暂不开放设置或恢复操作。')
        return
    st.caption('启动即检查到期任务，运行期间每分钟检查一次。默认每 4 小时更新身份、作品和评论，每 24 小时研究已发布内容的相关视频并生成运营报告；离线各补一次，不补跑发布、互动或付费生成。')
    admin = has_permission(get_current_role(), 'admin')
    scope = st.session_state.get('active_account_uuid', '*')
    from src.web.account_browser_control_dashboard import render_browser_control
    render_browser_control(data, scope)
    st.caption('此区域每 15 秒读取本地状态；关闭网页不停止后台。心跳正常不代表登录有效或任务已成功。')
    with st.expander('自动更新设置', expanded=False):
        with st.form('account_refresh_policy'):
            enabled = st.checkbox('启用账号信息自动更新', value=bool(data['policy']['enabled']), disabled=not admin)
            hours = st.number_input('同步间隔（小时）', min_value=1, max_value=168,
                                    value=data['policy']['interval_seconds']//3600, disabled=not admin)
            if st.form_submit_button('保存自动更新设置', disabled=not admin) and admin:
                set_policy(enabled, int(hours)*3600)
                st.rerun()
        with st.form('smart_operations_policy'):
            smart_enabled = st.checkbox('启用每日智能运营分析', value=bool(data['smart_policy']['enabled']), disabled=not admin)
            smart_hours = st.number_input('分析间隔（小时）', min_value=6, max_value=168,
                                          value=data['smart_policy']['interval_seconds']//3600, disabled=not admin)
            if st.form_submit_button('保存智能运营设置', disabled=not admin) and admin:
                set_smart_policy(smart_enabled, int(smart_hours)*3600)
                st.rerun()
        _render_playback_settings(data, scope, admin)
    stamp = _stamp
    statuses = {'running': '执行中', 'completed': '完成', 'blocked': '受阻，查看原因',
                'failed': '失败', 'interrupted': '上次中断，已记录'}
    _render_automation_controls(data, scope, admin)
    controls = {row['account_uuid']: row for row in _scope_rows(data.get('controls') or [], scope)}
    runs = [r for r in data['runs'] if scope == '*' or r['account_uuid'] == scope]
    states = [r for r in data['accounts'] if scope == '*' or r['account_uuid'] == scope]
    smart_runs = [r for r in data['smart_runs'] if scope == '*' or r['account_uuid'] == scope]
    smart_states = [r for r in data['smart_accounts'] if scope == '*' or r['account_uuid'] == scope]
    if states:
        st.dataframe([{'账号': r['account_key'], '下次到期（北京时间）': stamp(r['next_due']),
                       '执行状态': _schedule_status(r, controls)} for r in states], hide_index=True, width='stretch')
    if runs:
        st.dataframe([{'账号': r['account_key'], '触发': '启动补跑' if r['reason']=='startup_catchup' else '定期同步',
                       '开始（北京时间）': stamp(r['started_at']), '结束（北京时间）': stamp(r['finished_at']),
                       '结果': _run_status(r, statuses),
                       '说明': r.get('correction') or _detail(r).get('message', ''),
                       '作品数': _detail(r).get('videos'),
                       '评论数': _detail(r).get('comments'), '运行编号': r['run_id']}
                      for r in runs], hide_index=True, width='stretch')
    else:
        st.info('当前范围暂无自动更新记录；未绑定的账号不会启动平台同步。')
    st.markdown('**智能运营分析**')
    if smart_states:
        st.dataframe([{'账号': r['account_key'], '下次分析（北京时间）': stamp(r['next_due']),
                       '执行状态': _schedule_status(r, controls)} for r in smart_states], hide_index=True, width='stretch')
    if smart_runs:
        st.dataframe([{'账号': r['account_key'], '触发': '启动补跑' if r['reason']=='startup_catchup' else '定期分析',
                       '开始（北京时间）': stamp(r['started_at']), '结束（北京时间）': stamp(r['finished_at']),
                       '结果': _run_status(r, statuses),
                       '说明': _detail(r).get('message', ''),
                       '主题': '、'.join(_detail(r).get('topics', [])),
                       '关联视频': _detail(r).get('related_videos'),
                       '报告': _detail(r).get('report_markdown', ''),
                       '运行编号': r['run_id']} for r in smart_runs], hide_index=True, width='stretch')
    _render_playback_status(data, scope, controls)
    st.caption('失败不会写成同步成功。异常按后台策略退避或暂停；暂停不会取消已在途操作。恢复请求须先核验原会话，未知外部结果须先核对原运行。')
    if st.button('刷新自动更新日志', key='account_refresh_logs'):
        st.rerun()


_CONTROL_LABELS = {'active': '计划已放行', 'paused': '已暂停，待处理',
                   'recovery_requested': '等待后台核验原会话', 'recovering': '正在核验原会话'}


def _playback_identity(data, scope):
    if scope == '*':
        return None
    for key in ('playback_policies', 'playback_accounts', 'playback_runs',
                'accounts', 'smart_accounts', 'controls', 'issues'):
        match = next((row for row in data.get(key) or [] if row.get('account_uuid') == scope), None)
        if match:
            return match['account_key']
    # Local profile lookup also lets an existing account save its first policy.
    from src.operations_accounts import AccountProfileRepository
    return next((profile.account_key for profile in AccountProfileRepository().list_active(status=None)
                 if profile.account_uuid == scope), None)


def _render_playback_settings(data, scope, admin):
    st.markdown('**自动养号播放设置**')
    st.caption('按账号持久保存，到期直接浏览推荐流，不先搜索。根据当前视频文案与账号主题的相关性决定停留，并核对实际播放进度。纯观看不限每日运行次数，每轮仍按设置结束；自动播放始终关闭点赞和评论。')
    st.caption('正常任务在后台静默、静音运行；关闭网页不停止后台。异常时以原窗口任务的最新状态为准；若已打开处理页，按提示处理后申请核验。窗口服务失联时需先处理后台恢复。')
    if scope == '*':
        st.caption('汇总视图只查看各账号计划；请选择一个具体账号后修改，不会批量套用设置。')
        return
    account_key = _playback_identity(data, scope)
    if not account_key:
        st.caption('未能确认当前所选账号，请先选择已有运营账号。')
        return
    policy = next(iter(_scope_rows(data.get('playback_policies') or [], scope)), {})
    options = _detail({'detail': policy.get('options')})
    suffix = f'account_playback_{scope}'
    st.caption(f'当前设置账号：{account_key}。下方运行表显示实际保存的策略；未配置账号默认关闭。')
    with st.form(f'{suffix}_policy'):
        enabled = st.checkbox('启用自动养号播放', value=bool(policy.get('enabled', False)),
                              key=f'{suffix}_enabled', disabled=not admin)
        mode = st.selectbox('播放安排', ['固定间隔', '每天三个随机时段'],
                            index=1 if policy.get('schedule') else 0,
                            key=f'{suffix}_mode', disabled=not admin)
        st.caption('随机模式：北京时间09–12、14–17、19–22点各一次，每天最多3次（受阻也计一次），错过整个时段不补跑。固定间隔仅在固定模式生效。')
        interval = st.number_input('自动播放间隔（小时）', min_value=8, max_value=168,
                                   value=int(policy.get('interval_seconds', 86400))//3600,
                                   key=f'{suffix}_interval', disabled=not admin)
        videos = st.number_input('每轮最多播放视频数', min_value=1, max_value=100,
                                 value=int(options.get('max_videos', 20)), key=f'{suffix}_videos', disabled=not admin)
        seconds = st.number_input('单条播放上限（秒）', min_value=1, max_value=600,
                                  value=int(options.get('per_video_seconds', 90)), key=f'{suffix}_seconds', disabled=not admin)
        minutes = st.number_input('每轮播放上限（分钟）', min_value=1, max_value=120,
                                  value=int(options.get('total_minutes', 20)), key=f'{suffix}_minutes', disabled=not admin)
        relevance = st.number_input('最低播放相关度', min_value=0.0, max_value=100.0,
                                    value=float(options.get('min_relevance_score', 60)),
                                    key=f'{suffix}_relevance', disabled=not admin)
        if st.form_submit_button('保存此账号自动播放计划', key=f'{suffix}_save', disabled=not admin) and admin:
            from src.scheduler.account_refresh import set_playback_policy
            from src.web.components.auth import get_current_user
            try:
                set_playback_policy(scope, account_key, enabled, int(interval)*3600,
                                    {'max_videos': int(videos), 'per_video_seconds': int(seconds),
                                     'total_minutes': int(minutes), 'min_relevance_score': float(relevance),
                                     'auto_like': False, 'auto_comment': False},
                                    authorization_reference=f'管理员 {get_current_user() or "admin"} 在前端保存自动播放计划',
                                    schedule={'mode': 'random_daily_three'} if mode == '每天三个随机时段' else None)
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            else:
                st.success('已保存此账号播放计划；后台按到期时间执行，暂停或未知运行仍需先处理。')
                st.rerun()


def _playback_state(policy, account, control, runs, *, busy=False):
    if any(row.get('status') == 'outcome_unknown' for row in runs):
        return '结果未知，需核对原运行'
    running = account.get('run_id') or any(row.get('status') == 'running' for row in runs)
    state = control.get('state', 'active')
    if running:
        return '执行中（已暂停后续派发）' if state != 'active' or not policy.get('enabled') else '执行中'
    if state != 'active':
        return _CONTROL_LABELS.get(state, state)
    if not policy:
        return '未配置，未启用'
    if not policy.get('enabled'):
        return '已停用'
    if busy:
        return '等待账号空闲'
    if not account:
        return '等待后台登记'
    return '已到期，等待后台派发' if account.get('next_due', 0) <= time.time() else '等待到期'


def _playback_run_status(row, statuses):
    detail = _detail(row)
    if row.get('status') == 'skipped' and detail.get('error_code') == 'no_playback_candidates' and detail.get('playback_verified_videos') == 0:
        return '无候选，本轮未播放'
    return _run_status(row, statuses)


def _render_playback_status(data, scope, controls):
    st.markdown('**自动养号播放计划与记录**')
    if not isinstance(data.get('playback_policies'), list):
        st.caption('自动播放策略数据暂不可用，不能据此判断已经启用或执行。')
        return
    policies = {row['account_uuid']: row for row in _scope_rows(data['playback_policies'], scope)}
    accounts = {row['account_uuid']: row for row in _scope_rows(data.get('playback_accounts') or [], scope)}
    runs = _scope_rows(data.get('playback_runs') or [], scope)
    known = {row['account_uuid']: row['account_key'] for row in [*policies.values(), *accounts.values(), *runs]}
    rows = []
    for uuid, key in sorted(known.items(), key=lambda pair: pair[1]):
        policy, account = policies.get(uuid, {}), accounts.get(uuid, {})
        options = _detail({'detail': policy.get('options')})
        own_runs = sorted((row for row in runs if row['account_uuid'] == uuid),
                          key=lambda row: row.get('started_at') or 0, reverse=True)
        verified = next((row for row in own_runs if _detail(row).get('playback_verified_videos') is not None), None)
        busy = any(item.get('account_uuid') == uuid and item.get('run_id')
                   for group in ('accounts', 'smart_accounts') for item in data.get(group) or [])
        rows.append({'账号': key, '计划状态': _playback_state(policy, account, controls.get(uuid, {}), own_runs, busy=busy),
                     '已保存启用': bool(policy.get('enabled')),
                     '执行方式': '每天三个随机时段' if policy.get('schedule') else '固定间隔',
                     '间隔（小时）': None if policy.get('schedule') else policy.get('interval_seconds', 0)/3600,
                     '最多视频数': options.get('max_videos'), '单条上限（秒）': options.get('per_video_seconds'),
                     '每轮上限（分钟）': options.get('total_minutes'), '最低相关度': options.get('min_relevance_score'),
                     '下次执行（北京时间）': _stamp(account.get('next_due')),
                     '最近实际验证播放数': _detail(verified).get('playback_verified_videos') if verified else '未记录',
                     '验证记录编号': verified.get('run_id') if verified else '',
                     '授权来源': policy.get('authorization_reference', '')})
    if rows:
        st.dataframe(rows, hide_index=True, width='stretch')
    else:
        st.caption('当前账号范围暂无自动播放计划；未配置不会自动开启。')
    if runs:
        statuses = {'running': '执行中', 'completed': '完成', 'skipped': '已跳过，未记作成功观看',
                    'cancelled': '派发前取消', 'failed': '失败', 'blocked': '受阻',
                    'outcome_unknown': '结果未知，需核对原运行'}
        st.dataframe([{'账号': row['account_key'], '开始（北京时间）': _stamp(row.get('started_at')),
                       '结束（北京时间）': _stamp(row.get('finished_at')), '结果': _playback_run_status(row, statuses),
                       '实际验证播放数': _detail(row).get('playback_verified_videos', '未记录'),
                       '实际观看（秒）': _detail(row).get('actual_watch_seconds', '未记录'),
                       '说明': _detail(row).get('message', ''), '错误码': _detail(row).get('error_code', ''),
                       '运行编号': row['run_id']} for row in runs], hide_index=True, width='stretch')
    st.caption('播放数量以服务实际验证记录为准；计划条数和接口完成不代表成功观看。后台按账号身份与暂停状态检查后执行，自动点赞和评论始终关闭。')


def _schedule_status(row, controls):
    control = controls.get(row['account_uuid'], {})
    state = control.get('state')
    if not state:
        return '控制状态未知，需核对后台记录'
    if state != 'active':
        return _CONTROL_LABELS.get(state, state)
    return '执行中' if row.get('run_id') else '等待到期'


def _render_automation_controls(data, scope, admin):
    from src.scheduler.account_refresh import pause_account
    from src.web.account_exception_notice import (render_account_handling_completion,
        render_account_manual_window_controls, _incident_components)
    st.markdown('**后台服务与人工处理**')
    st.dataframe(_service_rows(data.get('service') or {}, time.time()), hide_index=True, width='stretch')
    keys = ('accounts', 'runs', 'smart_accounts', 'smart_runs', 'controls', 'issues',
            'playback_policies', 'playback_accounts', 'playback_runs')
    scoped = {key: _scope_rows(data.get(key) or [], scope) for key in keys}
    issues_available = isinstance(data.get('issues'), list)
    known = {row['account_uuid']: row['account_key'] for key in keys for row in scoped[key]}
    controls = {row['account_uuid']: row for row in scoped['controls']}
    for uuid, account_key in sorted(known.items(), key=lambda pair: pair[1]):
        control = controls.get(uuid, {})
        state = control.get('state', '控制状态未知')
        runs = [row for row in scoped['runs'] + scoped['smart_runs'] + scoped['playback_runs'] if row['account_uuid'] == uuid]
        successes = [row.get('finished_at') or 0 for row in runs
                     if row.get('status') == 'completed' and not row.get('correction') and not _detail(row).get('error_code')]
        running = sum(row.get('status') == 'running' for row in runs)
        st.write(f"{account_key} · {_CONTROL_LABELS.get(state, state)} · 当前执行 {running} 项")
        st.caption('已加载记录中最近成功（北京时间）：' + _stamp(max(successes, default=0)))
        from src.web.account_window_supervision import render_window_supervision
        render_window_supervision(uuid, account_key)
        open_issues = [row for row in scoped['issues']
                       if row.get('account_uuid') == uuid and row.get('status') == 'open']
        if state != 'active' and not open_issues:
            st.caption(('当前提示已人工关闭或暂无待处理提示；' if issues_available else '异常提示记录暂不可用；')
                       + '账号仍保留原暂停/核验状态，恢复须另行请求核验。')
        if any(not _incident_components(row) for row in open_issues):
            render_account_manual_window_controls(uuid, account_key,
                key=f'account_refresh_window_{uuid}', label='打开此账号处理窗口', poll=False)
        pause, recover = st.columns(2)
        with pause:
            if st.button('暂停此账号后台计划', key=f'account_refresh_pause_{uuid}',
                         disabled=not admin or state == 'paused') and admin:
                pause_account(uuid, account_key, '管理员在前端暂停后台计划')
                st.rerun()
        with recover:
            render_account_handling_completion(uuid, account_key, key=f'account_refresh_recover_{uuid}', data=data)
    st.info('登录会话保存在账号专属环境。请按原窗口任务的当前状态操作，仅页面要求时重新登录。受管窗口处理后可保持打开并点击“处理完成，继续运行”；后台核验原身份通过后才继续。')
    if not admin:
        st.caption('只有管理员可暂停账号、请求恢复或人工关闭异常提示。')
    _render_account_issues(scoped['issues'], admin, available=issues_available)


def _render_account_issues(issues, admin, *, available=True):
    from src.scheduler.account_refresh import close_account_issue
    from src.web.components.auth import get_current_user

    st.markdown('**当前异常提示**')
    if not available:
        st.caption('异常提示记录暂不可用，不能据此判断账号无异常；请检查后台状态。')
        return
    current = [row for row in issues if row.get('status') == 'open']
    history = [row for row in issues if row.get('status') in ('closed', 'resolved')]
    if not current:
        st.caption('当前账号范围暂无待处理异常提示。')
    for row in current:
        st.warning(f"{row['account_key']} · {row.get('message') or '待人工处理'}（{row.get('error_code') or '未分类'}）")
        st.caption(f"异常编号 {row['id']} · 发生（北京时间）：{_stamp(row.get('created_at'))}")
        if st.button('仅关闭此提示', key=f"account_issue_close_{row['id']}", disabled=not admin) and admin:
            try:
                closed = close_account_issue(row['id'], row['account_uuid'], row['account_key'],
                                             closed_by=get_current_user() or 'admin')
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            else:
                if closed:
                    st.success('已关闭本条提示并保留处置记录；账号运行状态未改变，之后新异常仍会展示。')
                    st.rerun()
                else:
                    st.warning('未关闭本条提示：记录状态已变化，请刷新查看；其他异常仍需分别处理。')
    st.caption('人工关闭只处理本次提示，保留历史；不会恢复账号、执行平台操作或屏蔽之后的新异常。')
    with st.expander(f'已关闭 / 已解决异常历史（{len(history)}）', expanded=False):
        if history:
            st.dataframe([{'异常编号': row['id'], '账号': row['account_key'],
                           '状态': '人工关闭' if row.get('status') == 'closed' else '已解决',
                           '错误码': row.get('error_code'), '原说明': row.get('message'),
                           '发生（北京时间）': _stamp(row.get('created_at')),
                           '处理（北京时间）': _stamp(row.get('closed_at') or row.get('updated_at')),
                           '操作者': row.get('closed_by') or '未记录',
                           '处置说明': row.get('closure_note') or ''} for row in history],
                         hide_index=True, width='stretch')
        else:
            st.caption('暂无已关闭或已解决的异常记录。')
