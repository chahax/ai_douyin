"""Authenticated, read-only account browser ownership/queue view."""
def render_browser_control(data, scope):
    import time
    import streamlit as st
    from src.web.components.auth import get_current_user
    if not get_current_user():
        return
    from src.operations_accounts.browser_control_runtime import enabled, operational_snapshot
    if not enabled():
        return
    kinds = {'publish': '发布', 'maintenance': '后台维护', 'manual': '人工验证',
             'recovery': '身份核验', 'read': '作品查询', 'official_console': '官方后台'}
    states = {'queued': '排队中', 'running': '执行中', 'paused': '已保存进度，待继续',
              'waiting_human': '等待人工处理', 'succeeded': '本步骤已完成',
              'failed': '本步骤未完成', 'outcome_unknown': '结果待核对'}
    owners = {'active': '已托管', 'released': '已交还', 'outcome_unknown': '待核对'}
    with st.expander('账号浏览器管控与发布队列', expanded=True):
        st.caption('同账号业务串行；发布仅在已保存进度的安全点优先。验证页可保留，点击处理完成后核验原身份。')
        rows = []
        for control in data.get('controls', []):
            if scope != '*' and control['account_uuid'] != scope:
                continue
            try:
                current = operational_snapshot(control['account_key'])
                owner = current.get('owner') or {}
                owner_stale = bool(owner and owner.get('state') != 'released'
                    and time.time() - owner.get('heartbeat', 0) > 90)
                owner_label = '旧执行者心跳过期，任务待核对' if owner_stale else owners.get(owner.get('state'), '尚未启动')
                account_label = '可调度（不代表任务已完成）' if control.get('state') == 'active' else '未恢复 · ' + str(control.get('state'))
                st.caption(f"{control['account_key']} · 浏览器：{owner_label} · 账号业务：{account_label}")
                for command in current['commands']:
                    label = ('查看中，关闭官方后台标签页后继续'
                             if command['kind'] == 'official_console' and command['state'] == 'waiting_human'
                             else states.get(command['state'], command['state']))
                    if owner_stale and command['state'] in {'running','paused','waiting_human'}:
                        label = '原任务待核对，无法确认仍在执行'
                    rows.append({'账号': control['account_key'], '任务': kinds.get(command['kind'], command['kind']),
                        '状态': label, '任务编号': command['command_id'],
                        '执行阶段': {'admission_pending':'尚未调用业务', 'admission_wait':'额度/条件等待',
                            'handler_entered':'已进入业务', 'legacy_unrecorded':'旧任务无阶段证据',
                            'recovered_before_handler':'已恢复原排队请求'}.get(command.get('phase'), command.get('phase')),
                        '等待重查秒数': max(0, round(command.get('next_retry_at', 0) - time.time())),
                        '停点已保存': bool(command.get('has_cursor')), '原因': command.get('error_code') or ''})
            except Exception:
                st.warning(f"{control['account_key']} 管控状态读取失败，不能据此放行或重开浏览器。")
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption('暂无已登记的浏览器任务。')
