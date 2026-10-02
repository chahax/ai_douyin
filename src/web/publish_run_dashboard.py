"""Read-only upload receipts; a missing receipt is never displayed as success."""
import json
from pathlib import Path
import streamlit as st
from src.web.production_insights import display_time


@st.fragment(run_every='2s')
def render_publish_runs(account_uuid, root=None):
    root = root or Path(__file__).resolve().parents[2]
    labels = {'prepared': '准备中', 'checking_login': '检查登录', 'login_required': '需要登录',
              'uploading': '上传中', 'file_selected': '已选文件', 'upload_complete': '已确认上传完成',
              'form_prepared': '发布资料已填写', 'submission_started': '已开始提交，待核对',
              'setting_ai_declaration': '设置作者 AI 声明', 'ai_declaration_verified': '已核验作者 AI 声明',
              'ai_declaration_unverified': 'AI 声明未确认，已停止发布',
              'fiction_declaration_verified': '简介虚构声明已确认',
              'fiction_declaration_unverified': '虚构声明未确认，已停止发布',
              'post_publish_checked': '发布后检查已记录',
              'post_publish_verification_pending': '已提交，作品展示与声明待核验，禁止重传',
              'submission_unknown': '提交结果未知，禁止直接重传', 'pending_review': '平台已接受，审核中',
              'published': '已有作品 ID', 'failed': '提交前异常', 'upload_failed': '上传未确认成功', 'error': '异常'}
    rows = []
    from src.web.components.auth import get_current_role, has_permission
    for batch in (root/'data/publish_runs').glob('batch_*.json'):
        try:
            job = json.loads(batch.read_text(encoding='utf-8'))
            if account_uuid and job.get('account_uuid') != account_uuid:
                continue
            with st.container(border=True):
                st.write('本次上传：' + str(job.get('title', '两条成片')))
                st.write(job.get('message', '准备中'))
                for warning in job.get('warnings', []):
                    st.warning(warning)
                st.caption('状态：' + str(job.get('status', 'unknown')) + ' · ' + display_time(job.get('updated_at')))
                if job.get('results'):
                    st.dataframe(job['results'], hide_index=True, width='stretch')
                if job.get('status') in {'running', 'paused'} and has_permission(get_current_role(), 'admin'):
                    pause = batch.with_suffix('.pause')
                    if st.button('继续执行' if pause.exists() else '暂停后续步骤', key=batch.stem+'_pause'):
                        if pause.exists():
                            pause.unlink()
                        else:
                            pause.touch()
                        st.rerun(scope='fragment')
                st.caption('暂停在下一步生效，不会撤销正在上传或已经提交的平台操作。')
        except (OSError, ValueError):
            continue
    for path in (root/'data/publish_runs').glob('*.jsonl'):
        try:
            events = []
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except ValueError:
                    continue
            if not events:
                continue
            first, last = events[0], events[-1]
            if account_uuid and first.get('account_uuid') != account_uuid:
                continue
            rows.append({'标题': first.get('title', ''), '状态': labels.get(last.get('stage'), last.get('stage', '未记录')),
                         '更新时间（北京时间）': display_time(last.get('at_bjt')),
                         '作品 ID': last.get('post_id', ''), '说明': last.get('message') or last.get('error_type', ''),
                         '回执': path.name})
        except OSError:
            continue
    st.subheader('上传与发布回执')
    st.caption('上传完成、平台接受、已发布分别记录。提交结果未知时保留防重复锁，先核对平台作品与草稿。')
    st.caption('AI 视频发布前主动选择“内容由AI生成”，并读回声明状态；未确认声明时停止发布。')
    if rows:
        st.dataframe(sorted(rows, key=lambda r:r['更新时间（北京时间）'], reverse=True)[:100], hide_index=True, width='stretch')
    else:
        st.info('此账号暂无项目上传回执，不能据此认为视频已上传。')


def page_upload_monitor():
    from src.web.components.ui import page_header
    page_header('上传实时监控', '每 2 秒刷新执行状态与回执，可同时观察弹出的账号专属浏览器。', icon='↑')
    scope = st.session_state.get('active_account_uuid', '*')
    render_publish_runs(None if scope == '*' else scope)
