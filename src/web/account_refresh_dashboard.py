"""Account information automation status and persisted execution log."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st


def render_account_refresh():
    from src.scheduler.account_refresh import snapshot, set_policy, set_smart_policy
    from src.web.components.auth import get_current_role, has_permission
    data = snapshot()
    st.subheader('账号信息自动更新')
    st.caption('启动即检查到期任务，运行期间每分钟检查一次。默认每 4 小时更新身份、作品和评论，每 24 小时研究已发布内容的相关视频并生成运营报告；离线各补一次，不补跑发布、互动或付费生成。')
    admin = has_permission(get_current_role(), 'admin')
    with st.expander('自动更新设置', expanded=False):
        with st.form('account_refresh_policy'):
            enabled = st.checkbox('启用账号信息自动更新', value=bool(data['policy']['enabled']), disabled=not admin)
            hours = st.number_input('同步间隔（小时）', min_value=1, max_value=168,
                                    value=data['policy']['interval_seconds']//3600, disabled=not admin)
            if st.form_submit_button('保存自动更新设置', disabled=not admin):
                set_policy(enabled, int(hours)*3600)
                st.rerun()
        with st.form('smart_operations_policy'):
            smart_enabled = st.checkbox('启用每日智能运营分析', value=bool(data['smart_policy']['enabled']), disabled=not admin)
            smart_hours = st.number_input('分析间隔（小时）', min_value=6, max_value=168,
                                          value=data['smart_policy']['interval_seconds']//3600, disabled=not admin)
            if st.form_submit_button('保存智能运营设置', disabled=not admin):
                set_smart_policy(smart_enabled, int(smart_hours)*3600)
                st.rerun()
    stamp = lambda t: datetime.fromtimestamp(t, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S') if t else '未记录'
    statuses = {'running': '执行中', 'completed': '完成', 'blocked': '受阻，需处理登录/环境',
                'failed': '失败，稍后重试', 'interrupted': '上次中断，已记录'}
    scope = st.session_state.get('active_account_uuid', '*')
    runs = [r for r in data['runs'] if scope == '*' or r['account_uuid'] == scope]
    states = [r for r in data['accounts'] if scope == '*' or r['account_uuid'] == scope]
    smart_runs = [r for r in data['smart_runs'] if scope == '*' or r['account_uuid'] == scope]
    smart_states = [r for r in data['smart_accounts'] if scope == '*' or r['account_uuid'] == scope]
    if states:
        st.dataframe([{'账号': r['account_key'], '下次到期（北京时间）': stamp(r['next_due']),
                       '执行状态': '执行中' if r['run_id'] else '等待到期'} for r in states], hide_index=True, width='stretch')
    if runs:
        st.dataframe([{'账号': r['account_key'], '触发': '启动补跑' if r['reason']=='startup_catchup' else '定期同步',
                       '开始（北京时间）': stamp(r['started_at']), '结束（北京时间）': stamp(r['finished_at']),
                       '结果': '原结果需复核' if r.get('correction') else statuses.get(r['status'], r['status']),
                       '说明': r.get('correction') or json.loads(r['detail']).get('message', ''),
                       '作品数': json.loads(r['detail']).get('videos'),
                       '评论数': json.loads(r['detail']).get('comments'), '运行编号': r['run_id']}
                      for r in runs], hide_index=True, width='stretch')
    else:
        st.info('当前范围暂无自动更新记录；未绑定的账号不会启动平台同步。')
    st.markdown('**智能运营分析**')
    if smart_states:
        st.dataframe([{'账号': r['account_key'], '下次分析（北京时间）': stamp(r['next_due']),
                       '执行状态': '执行中' if r['run_id'] else '等待到期'} for r in smart_states], hide_index=True, width='stretch')
    if smart_runs:
        st.dataframe([{'账号': r['account_key'], '触发': '启动补跑' if r['reason']=='startup_catchup' else '定期分析',
                       '开始（北京时间）': stamp(r['started_at']), '结束（北京时间）': stamp(r['finished_at']),
                       '结果': statuses.get(r['status'], r['status']),
                       '说明': json.loads(r['detail']).get('message', ''),
                       '主题': '、'.join(json.loads(r['detail']).get('topics', [])),
                       '关联视频': json.loads(r['detail']).get('related_videos'),
                       '报告': json.loads(r['detail']).get('report_markdown', ''),
                       '运行编号': r['run_id']} for r in smart_runs], hide_index=True, width='stretch')
    st.caption('失败不会被写为同步成功。普通异常约 30 分钟后重试；后台数据每 4 小时同步，关联视频分析默认每天一次，并按账号串行处理。')
    if st.button('刷新自动更新日志', key='account_refresh_logs'):
        st.rerun()
