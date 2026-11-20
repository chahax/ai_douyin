"""Candidate UI acceptance sandbox. Synthetic state, no production actions."""
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
import sys
from types import SimpleNamespace
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

st.set_page_config(page_title='管理页整改 · 隔离验收', layout='wide')
from src.web.components.ui import inject_app_theme
inject_app_theme()
st.title('管理页整改 · 隔离验收')
st.info('这是合成数据预览。所有操作只改变本页测试状态，不连接生产账号、浏览器、发布或生成服务。')
scenario = st.selectbox('验收场景', ['旧窗口失联', '当前窗口就绪', '原窗口已结清', '状态读取失败'])
from src.scheduler import account_refresh
from src.web.components import auth
from src.operations_accounts import browser_control_runtime as bridge
from src.web import account_exception_notice as notice

now = time.time()
issues = [{'id': n, 'account_uuid': 'preview-A', 'account_key': '演示账号',
           'status': 'open', 'error_code': 'verification_ui_unconfirmed',
           'message': '历史验证界面未就绪，原探测不能证明当前页面仍有验证码。',
           'created_at': now - 86400 * (3 if n == 1 else 2)} for n in (1, 2)]
data = {'issues': issues, 'controls': [{'account_uuid': 'preview-A', 'account_key': '演示账号', 'state': 'paused'}],
        'accounts': [], 'runs': [], 'smart_accounts': [], 'smart_runs': [], 'playback_accounts': [], 'playback_runs': []}
job = {'job_id': 'preview-original-manual', 'account_uuid': 'preview-A', 'account_key': '演示账号',
       'state': 'running', 'phase': 'window_owner_unconfirmed', 'managed': True,
       'handoff_ready': False, 'owner_status': 'stale', 'owner_heartbeat_at': now - 86400 * 2,
       'previous_boot_cleanup': {'available': True, 'proof_sha': 'preview-no-production-authority'}}
if scenario == '当前窗口就绪':
    job.update(phase='window_current_no_challenge', handoff_ready=True, owner_status='fresh', owner_heartbeat_at=now,
               current_verification={'surface_state':'clear','frame_count':0,'actionable_frames':0,'visible_dialogs':0,'confirmations':0})
    job.pop('previous_boot_cleanup', None)
elif scenario == '原窗口已结清':
    job.update(state='closed', phase='closed_by_previous_boot', session_saved=False)
    job.pop('previous_boot_cleanup', None)


def snapshot():
    if scenario == '状态读取失败':
        raise RuntimeError('synthetic read failure')
    return deepcopy(data)


def event(*args, **kwargs):
    st.session_state['preview_last_action'] = '已记录测试点击；生产数据与账号状态未改变。'
    return {'accepted': True, 'state': 'recovery_requested', 'message': '合成请求已受理；不会恢复任何真实账号。'}


with ExitStack() as sandbox:
    for target, name, value in (
        (account_refresh, 'snapshot', snapshot),
        (account_refresh, 'close_account_issue', lambda *a, **k: event() and True),
        (account_refresh, 'complete_account_handling', event),
        (auth, 'get_current_user', lambda: '隔离验收'),
        (auth, 'get_current_role', lambda: 'admin'),
        (bridge, 'close_manual_before_previous_boot', event),
        (notice, '_render_publication_recovery_status', lambda: None),
        (notice, '_render_handling_context', lambda *a: st.caption('合成停点：原账号首页；不会打开平台。')),
        # Disable timer fragments in the sandbox: every action is a full rerun
        # inside these process-local replacements, never a later unpatched poll.
        (st, 'fragment', lambda *a, **k: lambda function: function),
    ):
        sandbox.enter_context(patch.object(target, name, value))
    sandbox.enter_context(patch.dict(sys.modules, {
        'src.operations_accounts.manual_window_jobs': SimpleNamespace(
            get_manual_window_job=lambda *a, **k: deepcopy(job),
            start_manual_window_job=lambda *a, **k: event() and deepcopy(job)),
        'src.operations_accounts.manual_window_visibility': SimpleNamespace(queue=event),
    }))
    st.session_state['active_account_uuid'] = 'preview-A'
    notice.render_account_exception_notice()
if st.session_state.get('preview_last_action'):
    st.success(st.session_state['preview_last_action'])
st.caption('验收重点：一个账号一组处理按钮、旧证据不冒充当前探测、禁用原因可见、历史诊断折叠、读取失败不显示操作表单。')
