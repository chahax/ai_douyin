"""Authenticated, cross-page notices for local account exceptions."""
from datetime import datetime
from math import isfinite
import time
from zoneinfo import ZoneInfo

import streamlit as st


def render_account_exception_notice(accounts_page=None, *, summary_only=False):
    from src.web.components.auth import get_current_user
    if not get_current_user():
        return
    fragment = getattr(st, 'fragment', None)
    if callable(fragment):
        interval = 2 if getattr(st, 'session_state', {}).get('handling_fast_poll', False) else 15
        options = {'summary_only': True} if summary_only else {}
        if interval == 2:
            options['poll_pending'] = True
        fragment(run_every=interval)(_render_account_exception_notice)(accounts_page, **options)
    else:
        _render_account_exception_notice(accounts_page, **({'summary_only': True} if summary_only else {}))


def _render_account_exception_notice(accounts_page=None, *, summary_only=False, poll_pending=False):
    # Recheck authentication on every timed fragment run, including after logout.
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    user = get_current_user()
    placeholder = st.empty()
    if not user:
        placeholder.empty()
        return
    _render_publication_recovery_status()
    from src.scheduler.account_refresh import snapshot, close_account_issue
    try:
        data = snapshot()
        issues = data.get('issues')
        if not isinstance(issues, list) or any(not isinstance(row, dict) for row in issues):
            raise ValueError('unavailable exception snapshot')
        current = []
        for row in issues:
            if row.get('status') != 'open':
                continue
            if not isinstance(row.get('id'), int) or isinstance(row['id'], bool) or row['id'] <= 0:
                raise ValueError('invalid issue identity')
            if any(not isinstance(row.get(key), str) or not row[key].strip() for key in ('account_uuid', 'account_key')):
                raise ValueError('invalid account identity')
            created = row.get('created_at')
            if created is not None and (not isinstance(created, (int, float)) or isinstance(created, bool)):
                raise ValueError('invalid exception timestamp')
            stamp = datetime.fromtimestamp(created, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S') if created is not None else '未记录'
            current.append({**row, '_display_time': stamp})
    except Exception:
        placeholder.warning('后台账号异常状态暂不可用，请检查后台日志；当前不能据此判断无异常。')
        return
    pending = any(r.get('status') in ('requested','probing') for r in data.get('handling_requests') or [])
    if pending != st.session_state.get('handling_fast_poll', False):
        st.session_state['handling_fast_poll'] = pending
        st.rerun()
    from src.web.account_handling_feedback import feedback
    for control in data.get('controls') or []:
        account = control.get('account_uuid')
        receipt = st.session_state.get('handling_receipt:'+str(account))
        if receipt:
            current_feedback = feedback(data, account, control.get('account_key'))
            if current_feedback and current_feedback['request_id'] == receipt:
                if current_feedback['status']=='completed' and control.get('state')=='active':
                    st.success(control['account_key']+' · '+current_feedback['message'])
                elif current_feedback['status'] in ('failed','invalidated'):
                    st.warning(control['account_key']+' · '+current_feedback['message'])
    if not current:
        placeholder.empty()
        return
    if summary_only:
        names = list(dict.fromkeys(row['account_key'] for row in current))
        placeholder.info(f"待处理账号：{'、'.join(names)} · {len(current)} 条异常记录。请在本页对应账号的处理区查看最新状态与操作，历史异常不代表当前页面仍有验证提示。")
        return

    admin = has_permission(get_current_role(), 'admin')
    with placeholder.container():
        _render_open_issues(current, user, admin, accounts_page, close_account_issue, data)


def _render_publication_recovery_status():
    from pathlib import Path
    import os
    from src.operations_accounts.browser_control_runtime import DB, _store
    from src.operations_accounts.publication_verification_recovery import public_status
    if not Path(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB',DB)).exists():
        return
    try:
        rows=public_status(_store())
    except Exception:
        return  # The ordinary account/service notice reports DB availability.
    stages={'identity_check':'核验原账号身份','work_discovery':'获取并定位原作品',
            'detail_verification':'核验准确作品详情','saving_result':'保存对应结果'}
    for row in rows:
        name=row['account_key']
        if row['status']=='verified_published':
            st.info(f"发布后核验 · 账号 {name} · 已确认作品 {row['post_id']}，原发布任务已对应。")
            if row['projection_state']=='completed':
                st.caption('本地作品列表已同步对应；账号原有暂停与其他异常须分别核验。')
            elif row['projection_error']:
                st.warning('平台作品已确认，但本地作品对应失败；后台保留独立回填任务。请核对本地重复记录或账号归属，无需重新发布。')
            else:
                st.caption('正在回填本地作品对应；不会重新上传或发布。')
        elif row['state']=='running':
            st.info(f"发布后核验 · 账号 {name} · {stages.get(row['phase'],'正在读取原作品状态')}。")
        elif row['status']=='human_required':
            st.warning(f'发布后核验 · 账号 {name} · 原账号需要人工核验，请处理已登记的原账号窗口；后台不会代做验证或重新发布。')
        elif row['status']=='verification_blocked' or row['state']=='outcome_unknown':
            st.warning(f'发布后核验 · 账号 {name} · 原核验依据或任务回执需要核对，已停止自动接续；保留原任务，不重新发布。')
        elif row['state']=='queued':
            st.info(f'发布后核验 · 账号 {name} · 第 {row["attempt"]} 次作品补查已登记，等待原账号安全接管条件。')
        else:
            st.warning(f'发布后核验 · 账号 {name} · 尚未唯一确认准确作品；已检查 {row["attempt"]}/3 次。不会据此判断发布失败或重新上传。')
        st.caption('对应原发布任务：' + row['original_command_id'])


def _render_open_issues(current, user, admin, accounts_page, close_account_issue, data):
    groups = {}
    for row in sorted(current, key=lambda row: (row.get('created_at') or 0, row['id']), reverse=True):
        groups.setdefault((row['account_uuid'], row['account_key']), []).append(row)
    st.markdown(f'**后台账号异常 · 待人工处理（{len(current)}） · {len(groups)} 个账号**')
    for identity, rows in groups.items():
        with st.container(border=True):
            latest = rows[0]
            control = next((item for item in data.get('controls') or []
                            if item.get('account_uuid') == identity[0] and item.get('account_key') == identity[1]), {})
            label = {'active': '计划已放行', 'paused': '计划已暂停', 'recovering': '正在核验',
                     'recovery_requested': '等待核验'}.get(control.get('state'), '控制状态未知')
            st.markdown(f'**账号 {identity[1]} · {label}**')
            st.caption(f"{len(rows)} 条待处理记录 · 最近异常发生（北京时间）：{latest['_display_time']}")
            with st.expander(f"异常记录与处理详情 · {identity[1]}（{len(rows)}）", expanded=False):
                for row in rows:
                    _render_issue_record(row, data)
                    if st.button('仅关闭此提示', key=f"global_account_issue_close_{row['id']}", disabled=not admin) and admin:
                        try:
                            closed = close_account_issue(row['id'], row['account_uuid'], row['account_key'], closed_by=str(user))
                        except Exception:
                            st.error('本次提示未能关闭，请刷新状态或查看后台日志。')
                        else:
                            if closed:
                                st.success('已关闭本条提示，处置历史已保留；账号暂停与原任务状态不变。')
                                st.rerun()
                            else:
                                st.warning('未关闭本条提示：记录状态已变化，请刷新查看；其他异常仍需分别处理。')
            window_row = next((row for row in rows if not _incident_components(row)), None)
            if window_row:
                render_account_manual_window_controls(*identity,
                    key=f"global_account_issue_open_{window_row['id']}", label='打开此账号处理窗口', poll=False)
            backend_blocked = any(_incident_components(event) and not _backend_incident_state(
                event, data, _incident_components(event), time.time())[0] for event in rows)
            if backend_blocked:
                st.caption('后台状态尚待核实，暂不能核验继续；请先检查后台服务。')
                st.button('处理完成，继续运行', key=f"global_account_handling_complete_{latest['id']}", disabled=True)
            else:
                render_account_handling_completion(*identity,
                    key=f"global_account_handling_complete_{latest['id']}", data=data)
    st.caption('提示覆盖所有账号。人工处理后点击“处理完成，继续运行”，后台核验原身份通过后才继续；仅关闭提示不恢复账号或重派任务。')


def _render_issue_record(row, data):
    """Historical diagnostics stay in details, separate from current controls."""
    components = _incident_components(row)
    if components:
        recovered, status = _backend_incident_state(row, data, components, time.time())
        if recovered:
            st.info(f"后台故障历史 · 账号 {row['account_key']} · {row.get('message') or '原因待核对'}")
            st.caption('相关后台扫描已恢复；这是历史后台故障，不证明当前抖音页面或登录异常。账号暂停不会自动解除，继续运行仍须另行核验原身份。')
        else:
            st.warning(f"后台调度故障 · 待人工处理 · 账号 {row['account_key']} · {row.get('message') or '原因待核对'}")
            st.caption('尚无足够证据确认后台扫描恢复，请核对后台服务与本地记录；此类故障不需要通过打开抖音浏览器处理。')
        st.caption(status)
    elif row.get('error_code') in {'human_required', 'verification_ui_unconfirmed'}:
        if row.get('error_code') == 'verification_ui_unconfirmed':
            st.caption('验证界面未就绪或无法确认内容：可能空白、加载失败或网络问题；不表示已显示可操作验证码。')
        st.warning(f"历史平台事件 · 待人工处理与核验 · 账号 {row['account_key']} · 原记录：{row.get('message') or '原因待核对'}")
        st.caption('此为历史事件待核验，不表示当前页面仍在要求安全验证；原身份是否可用须在处理完成后由后台核验。')
        st.caption('历史异常不代表当前窗口已打开；是否排队、已打开或失联，以下方原窗口任务的最新回执为准。')
        _render_handling_context(row, data)
    else:
        if row.get('error_code') == 'browser_navigation_timeout':
            st.caption('页面跳转超时，尚未确认可用内容；请检查网络和原页面。当前没有据此认定验证码或登录失效，后台不会自动重复打开验证窗口。')
        st.warning(f"待人工处理 · 账号 {row['account_key']} · {row.get('message') or '原因待核对'}")
    st.caption(f"异常编号 {row['id']} · {row.get('error_code') or '未分类'} · 发生（北京时间）：{row['_display_time']}")
    _render_previous_recovery(row, data)


def _render_handling_context(row, data):
    """Show the same receipt-bound destination used by the manual worker."""
    try:
        from src.operations_accounts.manual_handling import resolve_manual_handling_target
        target = resolve_manual_handling_target(account_uuid=row['account_uuid'],
            account_key=row['account_key'], snapshot=data)
    except Exception:
        st.caption('原异常处理停点暂不可读取；当前无法确认具体失败页面，请核对后台记录。')
        return
    st.caption('人工处理入口：' + target.message)
    if target.source in ('blocked_search', 'recorded_research_keyword'):
        st.caption('主页身份核验通过后，原搜索仍可能再次要求人工处理；应先在对应搜索页核对提示。')


def _render_previous_recovery(row, data):
    created = row.get('created_at')
    if not isinstance(created, (int, float)) or isinstance(created, bool) or not isfinite(created):
        return
    completed = []
    for request in data.get('handling_requests') or []:
        if not isinstance(request, dict) or request.get('status') != 'completed':
            continue
        finished = request.get('finished_at')
        if (request.get('account_uuid') == row['account_uuid'] and request.get('account_key') == row['account_key']
                and isinstance(finished, (int, float)) and not isinstance(finished, bool)
                and isfinite(finished) and 0 <= finished < created):
            completed.append(finished)
    if completed:
        stamp = datetime.fromtimestamp(max(completed), ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        st.caption(f'此前完成请求已于北京时间 {stamp} 通过原身份核验；当前异常产生于该请求之后。')


_LEGACY_PLAYBACK_SCAN_MESSAGE = '自动播放调度异常，请人工核对本地记录；未重新派发原运行。'
_INCIDENT_COMPONENT_LABELS = {'scheduler': '调度服务', 'account_refresh': '账号计划扫描',
                              'playback_schedule': '播放计划扫描'}


def _incident_components(row):
    code = row.get('error_code')
    if code == 'account_refresh_unavailable':
        return ('scheduler', 'account_refresh')
    if code in ('scheduler_database_busy', 'playback_schedule_unavailable'):
        return ('scheduler', 'playback_schedule')
    if code == 'unexpected_error' and row.get('message') == _LEGACY_PLAYBACK_SCAN_MESSAGE:
        return ('scheduler', 'playback_schedule')
    return ()


def _valid_timestamp(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def _backend_incident_state(row, data, components, now):
    services = data.get('service')
    services = services if isinstance(services, dict) else {}
    created = row.get('created_at')
    recovered = _valid_timestamp(created)
    labels = []
    for name in components:
        value = services.get(name)
        item = value if isinstance(value, dict) else {}
        updated = item.get('updated_at')
        state = item.get('status')
        if not item:
            label, normal = '状态未记录', False
        elif state != 'healthy' or item.get('error_code'):
            label = {'stopped': '已停止', 'failed': '失败', 'error': '异常', 'manual_required': '需人工处理',
                     'blocked': '受阻', 'degraded': '暂时降级，等待下次扫描', 'healthy': '附异常记录，尚未确认恢复',
                     'running': '正在执行，尚无本轮正常结束回执'}.get(state, str(state or '未知'))
            normal = False
        elif not _valid_timestamp(updated):
            label, normal = '心跳时间未知', False
        elif now - updated < 0:
            label, normal = '心跳时间待核对', False
        elif now - updated > 180:
            label, normal = '心跳过期', False
        elif not _valid_timestamp(created) or updated <= created:
            label, normal = '尚无晚于本次故障的正常回执', False
        else:
            label, normal = f'正常，最近心跳 {int(now - updated)} 秒前', True
        recovered = recovered and normal
        labels.append(f'{_INCIDENT_COMPONENT_LABELS.get(name, name)}：{label}')
    return bool(recovered), '当前相关组件状态 · ' + '；'.join(labels)


_LIVE_WINDOW_STATES = {'starting', 'running', 'outcome_unknown'}
_WINDOW_PHASE_LABELS = {
    'window_owner_unconfirmed': '原窗口服务状态无法确认，旧开窗与探测记录不能代表当前页面；请核对原会话收尾与后台恢复记录。',
    'window_observation_stale': '原窗口服务仍有心跳，但页面探测已过期；当前是否有验证提示未知，请查看原窗口，完成后申请身份核验。',
    'window_display_unconfirmed': '原账号页面已建立，但窗口显示尚未确认；请点击“重新显示原账号处理窗口”。这不表示验证码已处理，也不会自动恢复账号。',
    'queued': '人工窗口任务正在排队，尚未打开浏览器；需要核对原账号队列与未结束任务，不是等待关闭窗口。',
    'feed_recommendation_navigation': '网站跳到了精选页，正在通过页面上的推荐入口进入推荐流。',
    'feed_ready_for_confirmation': '推荐内容已加载，正在连续确认页面状态；确认后自动核验身份并接续观看。',
    'feed_challenge_present': '当前处理页仍检测到验证遮挡，请按页面提示处理；完成后保持窗口打开。',
    'feed_feed_not_loaded': '当前未确认验证码遮挡，但推荐视频尚未就绪；这是页面加载或视频定位问题，不要求重复登录。',
    'feed_resume_already_attempted': '本次自动接续已尝试，保留原结果，正在等待核查；不会循环重派。',
    'feed_observation_stale': '当前页面检测回执已过期或不可用；不能把开窗时的结果当作当前状态。',
    'validating': '正在核对原账号身份与环境…',
    'preparing': '正在准备原账号会话与处理页面…',
    'acquiring': '正在获取原账号窗口互斥…',
    'starting_browser': '正在启动 Chrome 并打开原账号页面…',
    'window_open_waiting_close': '窗口已打开，请在 Chrome 中处理，完成后关闭窗口。',
    'window_open_waiting_handling': '处理页面已打开；尚无当前验证控件的探测回执，请核对网页。处理后由后台核验原身份。',
    'window_challenge_controls_confirmed': '已在原账号环境重新打开处理目标，当前已连续识别到验证提示和可操作控件，请按网页提示人工处理。',
    'window_current_no_challenge': '已在原账号环境重新打开处理目标，当前未检测到验证控件；不代表旧异常已解决或账号已恢复，请核对页面。',
    'window_verification_unknown': '已在原账号环境重新打开处理目标，当前验证界面加载情况或可操作控件尚未确认，请先核对网页。',
    'closing': '正在保存会话并关闭原环境，请稍候…',
}


def _read_manual_window_job(account_uuid, account_key):
    from src.web.components.auth import get_current_user
    if not get_current_user():
        return None, False
    try:
        from src.operations_accounts.manual_window_jobs import get_manual_window_job
        job = get_manual_window_job(account_uuid, account_key)
        if job is not None and (not isinstance(job, dict) or job.get('account_uuid') != account_uuid
                                or job.get('account_key') != account_key
                                or job.get('state') not in {'starting', 'running', 'closed', 'failed', 'outcome_unknown', 'verified'}
                                or not isinstance(job.get('job_id'), str) or not job['job_id']):
            raise ValueError('window job account mismatch')
        return job, True
    except Exception:
        return None, False


def _manual_window_error(code, error_type=''):
    reasons = {
        'locked': '原账号任务或窗口仍持有运行锁，请核对原任务，不能重复打开。',
        'binding_required': '账号尚未完成原身份绑定，请先在账号页完成绑定。',
        'account_uuid_mismatch': '账号编号与原绑定不一致，请先核对账号归属。',
        'browser_environment_mismatch': '当前环境与原绑定环境不一致，已停止打开。',
        'account_disabled': '运营账号已暂停或停用，请先检查账号配置。',
        'daily_quota_exceeded': '历史每日次数限制记录；当前默认已取消次数拦截，请核对原任务与服务版本。',
        'cooldown': '原账号正在冷却，请稍后再试。',
        'circuit_open': '账号运行保护已开启，请先核对后台异常记录。',
        'manual_window_not_opened': '尚未收到原浏览器页面打开确认，请检查后台启动日志。',
        'browser_start_failed': 'Chrome 启动失败，未确认窗口已打开；请检查后台启动记录。',
        'manual_window_noninteractive_desktop': '后台窗口服务不在正常桌面，未打开不可见窗口；需通过项目已登记的 Windows 自启任务启动后台。',
    }
    if error_type in ('TimeoutError', 'BrowserWorkerStartupTimeout') or code in ('startup_timeout', 'browser_startup_timeout', 'browser_start_timeout', 'manual_window_timeout'):
        return '浏览器启动或窗口等待超时，本次已停止；请核对原窗口和后台日志，未自动重试。'
    return reasons.get(code, '原账号窗口任务失败，请检查后台日志；暂停与原异常仍保留。')


def _render_manual_window_job(job, available, account_key):
    if not available:
        st.caption('人工窗口任务状态暂不可用，不能重复开启或据此判断窗口已关闭。')
        return
    if job is None:
        return
    state = job.get('state')
    if job.get('phase') == 'window_owner_unconfirmed':
        if (job.get('previous_boot_cleanup') or {}).get('available') is True:
            st.info('已核对旧窗口所属环境已退出。请先结清旧窗口记录，再核验原账号身份。')
        else:
            st.warning(_WINDOW_PHASE_LABELS['window_owner_unconfirmed'])
            st.caption('如果原窗口还开着，请先在该窗口完成操作并正常关闭。后台服务重启后会核对旧进程是否退出，再显示结清旧记录的入口。')
        heartbeat = job.get('owner_heartbeat_at')
        if _valid_timestamp(heartbeat):
            st.caption('原窗口服务最后心跳（北京时间）：' + datetime.fromtimestamp(
                heartbeat, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'))
        st.caption(f"人工窗口任务编号：{job.get('job_id') or '未记录'}")
        return
    if state == 'verified':
        st.info('此前人工任务已完成原身份核验；这不是当前账号已恢复或原窗口仍打开的证明。当前计划状态与新异常须分别核对。')
    elif state == 'closed':
        st.session_state.pop(f'pending_douyin_identity_{account_key}', None)
        if job.get('phase') == 'closed_by_previous_backend':
            st.info('旧后台和窗口已退出，窗口记录已结清。登录状态仍需在原账号环境重新核验。')
        elif job.get('phase') == 'closed_by_previous_boot':
            st.info('系统重启前的旧窗口记录已结清。会话保存情况未确认；请重新打开原账号环境核对登录，处理后再申请身份核验。')
        else:
            st.info('人工窗口已关闭；会话已保留并退出原环境。请点击“处理完成，继续运行”，后台核验原身份通过后才继续。')
    elif state == 'failed':
        st.error('打开人工处理窗口失败：' + _manual_window_error(job.get('error_code'), job.get('error_type')))
    elif state == 'outcome_unknown':
        st.warning('原人工窗口任务结果未知，请核对原任务编号和原窗口；不能重新开启。')
    else:
        label = _WINDOW_PHASE_LABELS.get(job.get('phase'), '人工窗口任务已登记，等待后台执行…')
        st.info(label)
        blocker = job.get('queue_blocker')
        reasons = {
            'publication_verification_pending': '原发布结果仍待作品核验，后台只读补查不会重新发布；此人工窗口尚未打开，关闭浏览器或重复点击完成不能代替作品核验。',
            'publication_human_required': '发布补查确认原账号需要人工核验；后台会串行打开已登记的处理窗口，完成后仍需核验准确作品。',
            'original_outcome_unknown': '原任务结果未知，正在保留原请求；此窗口尚未打开，请先核对下方原任务。',
            'owner_recovery_blocked': '原浏览器 owner 尚无可靠退出证明，后台保留原会话，不会另开重复窗口。',
            'status_unavailable': '当前阻塞原因读取失败，不能据此认定窗口已打开或关闭。',
        }
        if blocker in reasons:
            st.warning(reasons[blocker])
            stages = {'identity_check':'核验原账号身份','work_discovery':'获取并定位原作品',
                      'detail_verification':'核验准确作品详情','saving_result':'保存原任务核验结果'}
            if job.get('verification_state') == 'running' and job.get('verification_phase') in stages:
                st.caption('后台作品补查：' + stages[job['verification_phase']])
            if job.get('verification_status') == 'verification_blocked':
                st.caption('补查依据或声明证据不完整，已停止自动接续；请核对原任务记录，重复验证登录不能替代缺失证据。')
            if job.get('owner_stale'):
                st.caption('原 owner 心跳已过期；过期不等于原进程已退出，不能仅凭此接管。')
            if job.get('blocking_command_id'):
                st.caption('阻塞原任务编号：' + job['blocking_command_id'])
            if job.get('verification_attempts', 0) >= 3 and job.get('verification_status') != 'verified_published':
                st.caption('本轮自动作品补查已达 3 次上限，保留待核验；不会循环发布或反复弹窗。需要核对原作品与后台证据。')
        if job.get('phase') in {'window_challenge_controls_confirmed',
                'window_current_no_challenge', 'window_verification_unknown'}:
            st.caption('本次只读探测不会完成验证或恢复账号。处理后可点击“处理完成，继续运行”，由后台核验原身份，无需关闭窗口。')
            evidence = job.get('current_verification')
            if isinstance(evidence, dict):
                surface_labels = {'clear': '当前未检测到验证', 'challenge_ready': '已识别可操作控件',
                    'loading': '加载中', 'load_failed': '加载失败', 'blank': '内容空白',
                    'unavailable': '内容不可读取', 'unconfirmed': '内容未确认', 'unknown': '探测未知'}
                surface = evidence.get('surface_state')
                if isinstance(surface, str) and surface in surface_labels:
                    st.caption('当前验证内容：' + surface_labels[surface])
                counts = [('候选验证帧', 'frame_count'), ('可交互帧', 'actionable_frames'),
                    ('可见验证对话框', 'visible_dialogs'), ('连续确认', 'confirmations')]
                values = [f'{label} {evidence[name]}' for label, name in counts
                    if type(evidence.get(name)) is int and 0 <= evidence[name] <= 10000]
                if values:
                    st.caption('当前探测计数：' + '；'.join(values))
        st.caption('正在复用当前人工窗口任务；此页面每 15 秒读取任务进度，不会重复打开窗口。')
    proof = job.get('startup_evidence')
    if state in {'failed', 'outcome_unknown'} and isinstance(proof, dict):
        stages = {'spawning_worker': '创建浏览器进程', 'importing_playwright': '加载浏览器依赖',
                  'starting_driver': '启动浏览器驱动', 'launching_browser': '启动 Chrome',
                  'restoring_state': '恢复原会话'}
        causes = {'executable_missing': '浏览器可执行文件不存在', 'profile_in_use': '原浏览器目录正在使用',
                  'profile_lock_unavailable': '浏览器目录互斥创建失败，需核对占用与访问权限',
                  'permission_denied': '启动访问被拒绝', 'browser_closed': '浏览器启动期间退出',
                  'startup_timeout': '启动超时'}
        stage = stages.get(proof.get('stage'), '浏览器启动')
        cause = causes.get(proof.get('code'), '具体原因尚未确认')
        st.caption(f'开窗失败阶段：{stage}；{cause}。没有收到窗口就绪回执，不表示需要处理验证码。')
        if proof.get('cleanup_verified') is True:
            st.caption('本次未就绪进程的退出已核实；账号暂停及原异常保持，未申请恢复。')
        else:
            st.caption('本次进程收尾尚未可靠核实，保留原任务，不能重复开窗。')
    st.caption(f"人工窗口任务编号：{job.get('job_id') or '未记录'}")


def open_account_manual_handling(account_uuid, account_key, *, runtime=None):
    """Register one worker job promptly; all browser work stays outside Streamlit."""
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    user = get_current_user()
    if not user or not has_permission(get_current_role(), 'admin'):
        st.error('只有管理员可打开账号人工处理窗口。')
        return None
    marker = f'manual_window_ui_error_{account_uuid}'
    try:
        from src.operations_accounts.manual_window_jobs import start_manual_window_job
        options = {'runtime': runtime} if runtime is not None else {}
        job = start_manual_window_job(account_uuid, account_key, str(user), **options)
        if not isinstance(job, dict) or job.get('account_uuid') != account_uuid or job.get('account_key') != account_key:
            raise ValueError('invalid window job receipt')
    except Exception as exc:
        st.session_state[marker] = _manual_window_error(getattr(exc, 'code', ''), type(exc).__name__)
        return None
    st.session_state.pop(marker, None)
    return job


def render_account_manual_window_controls(account_uuid, account_key, *, key,
                                           label='打开原环境处理登录 / 安全验证', runtime=None, poll=True):
    if poll and callable(getattr(st, 'fragment', None)):
        st.fragment(run_every=15)(_render_manual_window_controls)(account_uuid, account_key, key, label, runtime)
    else:
        _render_manual_window_controls(account_uuid, account_key, key, label, runtime)


def _render_manual_window_controls(account_uuid, account_key, key, label, runtime):
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    placeholder = st.empty()
    if not get_current_user():
        placeholder.empty()
        return
    job, available = _read_manual_window_job(account_uuid, account_key)
    admin = has_permission(get_current_role(), 'admin')
    with placeholder.container():
        _render_manual_window_job(job, available, account_key)
        error = st.session_state.get(f'manual_window_ui_error_{account_uuid}')
        if error:
            st.error('人工窗口任务未能登记：' + error)
        cleanup = job.get('previous_boot_cleanup') if isinstance(job, dict) else None
        if isinstance(cleanup, dict) and cleanup.get('available') is True and admin:
            if cleanup.get('reason') == 'proven_previous_backend_exit':
                st.caption('已核对原后台、浏览器和工作进程退出。可结清旧窗口记录，再申请身份核验。')
            else:
                st.caption('系统启动时间已证明旧窗口早于本次开机，可结清该旧人工任务，再申请身份核验。')
            agreed = st.checkbox('确认结清系统重启前的这条旧窗口记录', key=key + '_boot_confirm_' + job['job_id'])
            if st.button('结清重启前的旧窗口记录', key=key + '_boot_settle', disabled=not agreed):
                try:
                    from src.operations_accounts.browser_control_runtime import close_manual_before_previous_boot
                    close_manual_before_previous_boot(account_uuid, account_key, job['job_id'],
                        cleanup['proof_sha'], str(get_current_user()))
                except Exception:
                    st.warning('旧窗口记录未能结清：证据或状态可能已变化，请刷新后核对；未申请账号恢复。')
                else:
                    st.rerun()
        blocked = not available or (job is not None and job.get('state') in _LIVE_WINDOW_STATES)
        can_reveal = (available and job is not None and job.get('managed') is True
                      and job.get('state') == 'running' and job.get('handoff_ready') is True)
        shown_label = '重新显示原账号处理窗口' if can_reveal else label
        if not admin:
            st.caption('当前为只读权限，打开窗口或提交处理完成需要管理员操作。')
        elif blocked and not can_reveal and not (isinstance(cleanup, dict) and cleanup.get('available') is True):
            st.caption('暂不能开窗：' + (_unfinished_window_message(job) if job else '窗口状态读取失败，请检查后台。'))
        if st.button(shown_label, key=key, disabled=not admin or (blocked and not can_reveal)) and admin:
            st.session_state['active_account_uuid'] = account_uuid
            if can_reveal:
                try:
                    from src.operations_accounts.manual_window_visibility import queue
                    queue(account_uuid, account_key)
                    st.info('已登记显示原窗口；后台会复用原标签页，不新建账号环境。')
                except Exception:
                    st.error('未能登记显示请求，请刷新后核对原窗口任务；未重复开窗。')
            elif not blocked:
                open_account_manual_handling(account_uuid, account_key, runtime=runtime)
            # A full app rerun synchronizes sidebar and account-page selectors.
            # Periodic reads never rewrite the user's later account selection.
            st.rerun()


def _handling_state(data, uuid, account_key):
    control = next((row for row in data.get('controls') or [] if row.get('account_uuid') == uuid), None)
    if not control:
        return 'unknown', '账号后台控制状态未登记或暂不可用，请先核对绑定与后台状态。', False
    if control.get('account_key') != account_key:
        return 'binding_mismatch', '账号与控制记录归属不一致，须先人工核对。', False
    state = control.get('state')
    runs = [row for group in ('runs', 'smart_runs', 'playback_runs') for row in data.get(group) or []
            if row.get('account_uuid') == uuid]
    queued = {row['run_id'] for row in data.get('queued_refresh_waits') or [] if row.get('account_uuid')==uuid}
    if control.get('error_code') in ('outcome_unknown', 'recovery_outcome_unknown') or any(row.get('status') == 'outcome_unknown' for row in runs):
        return 'outcome_unknown', '原运行结果未知，须核对原任务；不能重新派发。', False
    if any(row.get('status') == 'running' for row in runs) or any(
            row.get('account_uuid') == uuid and row.get('run_id') and not (group=='accounts' and row['run_id'] in queued)
            for group in ('accounts', 'smart_accounts', 'playback_accounts') for row in data.get(group) or []):
        return 'busy', '尚有未结束的原运行，请等待或核对原任务后再提交。', False
    if state == 'paused' and (control.get('recovery_lease_until') or 0) > 0:
        return 'busy', '原身份核验尚未结束，请核对原核验编号；不能重复提交。', False
    services = data.get('service') or {}
    components = ['scheduler', 'account_refresh']
    if any(row.get('account_uuid') == uuid and row.get('enabled')
           for row in data.get('playback_policies') or []):
        components.append('playback_schedule')
    for component in components:
        service = services.get(component) or {}
        if service.get('status') in ('stopped', 'failed', 'error', 'manual_required', 'blocked', 'degraded') or service.get('error_code'):
            return 'service_unavailable', '后台服务异常，暂不能核验继续，请检查后台服务。', False
        updated = service.get('updated_at')
        if (isinstance(updated, (int, float)) and not isinstance(updated, bool)
                and isfinite(updated) and updated >= 0 and time.time() - updated > 180):
            return 'service_unavailable', '后台服务心跳过期，暂不能核验继续，请检查后台服务。', False
    if state == 'recovery_requested':
        from src.web.account_handling_feedback import feedback
        progress = feedback(data, uuid, account_key)
        return state, progress['message'] if progress and progress['status']=='requested' else '完成请求已受理，等待后台核验原会话；请勿重复提交。', False
    if state == 'recovering':
        from src.web.account_handling_feedback import feedback
        progress = feedback(data, uuid, account_key)
        return state, progress['message'] if progress and progress['status']=='probing' else '正在核验原会话，通过后自动继续；请勿重复提交。', False
    if state == 'paused':
        return state, '人工处理完成后可继续；系统会先核验原会话，通过后接续符合条件的运营计划。', True
    if state == 'active':
        from src.web.account_handling_feedback import feedback
        progress = feedback(data, uuid, account_key)
        return state, progress['message'] if progress and progress['status']=='completed' else '后台计划已放行，按设置执行；实际运行结果请查看日志。', False
    return state or 'unknown', '账号状态暂不可用，请先核对后台记录。', False


def _unfinished_window_message(job):
    if (job.get('previous_boot_cleanup') or {}).get('available') is True:
        return '请先结清重启前的旧窗口记录，再在原账号环境申请身份核验。'
    if job.get('phase') == 'window_owner_unconfirmed':
        return '原窗口服务失联或归属无法确认，请先核对原会话与后台恢复记录；当前不能重新开窗或提交继续。'
    if job.get('phase') == 'queued':
        return '人工窗口仍在排队，尚未开窗；请核对原账号队列和未结束任务。重复点击不会新建窗口。'
    if job.get('state') == 'outcome_unknown':
        return '原人工窗口结果未知，请核对原任务记录；不能据此认定窗口仍打开，也不能重复派发。'
    if job.get('phase') in {'preparing', 'validating', 'acquiring', 'starting_browser'}:
        return '原人工窗口仍在准备或启动，尚未收到打开确认；请核对原任务进度。'
    return '原人工窗口任务尚未确认结束，请等待关闭回执或核对原任务编号后再继续。'


def render_account_handling_completion(account_uuid, account_key, *, key, data=None):
    if data is None:
        fragment = getattr(st, 'fragment', None)
        if callable(fragment):
            interval = 2 if getattr(st, 'session_state', {}).get('handling_fast_poll', False) else 15
            fragment(run_every=interval)(_render_handling_completion)(account_uuid, account_key, key)
        else:
            _render_handling_completion(account_uuid, account_key, key)
    else:
        _render_handling_completion(account_uuid, account_key, key, data)


def _render_handling_completion(account_uuid, account_key, key, data=None):
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    user = get_current_user()
    placeholder = st.empty()
    if not user:
        placeholder.empty()
        return
    if data is None:
        from src.scheduler.account_refresh import snapshot
        try:
            data = snapshot()
        except Exception:
            placeholder.caption('账号处理状态暂不可用，请刷新或检查后台日志。')
            return
    try:
        _, message, ready = _handling_state(data, account_uuid, account_key)
    except (TypeError, ValueError, AttributeError):
        placeholder.caption('账号处理状态暂不可用，请刷新或检查后台日志。')
        return
    job, available = _read_manual_window_job(account_uuid, account_key)
    if not available:
        message, ready = '人工窗口任务状态暂不可用，请核对原任务后再继续。', False
    elif job is not None and job.get('state') in _LIVE_WINDOW_STATES and not job.get('handoff_ready'):
        message, ready = _unfinished_window_message(job), False
    with placeholder.container():
        _render_handling_action(account_uuid, account_key, key, user, message, ready,
                                has_permission(get_current_role(), 'admin'))


def _render_handling_action(account_uuid, account_key, key, user, message, ready, admin):
    st.caption(message)
    if st.button('处理完成，继续运行', key=key, disabled=not admin or not ready) and admin and ready:
        from src.scheduler.account_refresh import complete_account_handling
        began = time.time()
        try:
            with st.spinner('正在登记本次完成请求…'):
                result = complete_account_handling(account_uuid, account_key, handled_by=str(user))
        except Exception:
            st.error('本次登记结果暂未确认，请刷新核对原请求；请勿重复提交。')
            return
        if isinstance(result, dict) and result.get('accepted') is True:
            st.session_state['handling_fast_poll'] = True
            receipt = result.get('request_id')
            if not receipt:
                from src.scheduler.handling_fast_lane import latest_receipt
                try:
                    receipt = latest_receipt(account_uuid,account_key,after=began-1)
                except Exception:
                    receipt = None
            if receipt:
                st.session_state['handling_receipt:'+account_uuid] = receipt
            st.info('已登记处理完成；等待后台核验原会话，通过后才会继续运行。')
            st.rerun()
        else:
            st.warning(result.get('message') or '未登记新请求，请刷新查看原运行状态。'
                       if isinstance(result, dict) else '未登记新请求，后台返回状态暂不可用。')
