"""Chat management: read-only views, scoped session actions, exact-plan buttons."""
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

import streamlit as st
from src.web.components.ui import page_header
from src.web.components.action_feedback import remember, render
from src.web import chat_sessions as sessions


def _change(operation, message):
    try:
        changed = operation()
    except Exception:
        logging.getLogger(__name__).exception('Chat session action failed')
        st.error('会话操作未确认成功，请重新读取后核对。')
        return
    if not changed:
        st.warning('未修改会话：标题为空、归属不符或记录已变化，请核对后再操作。')
        return
    st.session_state['chat_scope'] = None
    remember('chat_sessions',message)
    st.rerun()


def _progress():
    try:
        from src.platform_adapter.fanqie_batch import read_progress
        value = read_progress()
        if not isinstance(value,dict) or not (value.get('running') or value.get('completed')):
            return
        total,current = value.get('total'),value.get('current')
        if type(total) is not int or type(current) is not int or total<0 or current<0:
            raise ValueError('Invalid progress counters')
        stamp=datetime.fromisoformat(str(value.get('updated_at','')))
        if stamp.tzinfo is None:
            stamp=stamp.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        age=(datetime.now(ZoneInfo('Asia/Shanghai'))-stamp).total_seconds()
        if value.get('completed') and age>30:
            return  # Presentation expiry does not delete the shared receipt.
        st.caption(f'最近采集进度记录：{current}/{total}；记录状态：'+('已完成' if value.get('completed') else '运行中'))
        st.progress(min(1.0,current/max(total,1)))
        if age<0 or age>180:
            st.warning('采集进度时间已过期或无法确认，不能据此判断原任务仍在运行。')
    except Exception:
        st.caption('采集进度暂不可确认，请从原任务记录核对；未清除或重派任务。')


def _redacted(value):
    if isinstance(value,dict):
        return {key: ('[已隐藏]' if any(word in str(key).lower() for word in
            ('password','token','cookie','secret','authorization','api_key')) else _redacted(part)) for key,part in value.items()}
    if isinstance(value,list):
        return [_redacted(part) for part in value]
    return value


def _pending(user, active, editable):
    if not active or not active.get('pending'):
        return
    plan = active['pending']
    try:
        sha = sessions.digest(plan)
        if not isinstance(plan,dict) or not isinstance(plan.get('plan'),dict):
            raise ValueError('Invalid pending plan')
    except (ValueError,TypeError):
        st.warning('待确认计划格式无法核对，暂不开放执行；请核对原会话记录。')
        return
    claimed = bool(active.get('receipt'))
    if claimed:
        st.warning('该计划已有受理回执，结果须核对原记录；不会重复提交或自动重试。')
    else:
        st.info('当前会话有待确认计划，尚未执行。请先核对具体操作；取消只撤销本计划，不调用模型。')
    with st.expander('待确认计划参数'):
        st.caption(f"本地确认标识：会话 #{active['id']} · 计划 {sha[:12]}")
        st.json(_redacted(plan['plan']))
    left,right=st.columns(2)
    with left:
        confirm=st.button('✅ 确认执行',key=f"chat_confirm_{active['id']}_{sha}",type='primary',disabled=not editable or claimed)
    with right:
        cancel=st.button('❌ 取消',key=f"chat_cancel_{active['id']}_{sha}",disabled=not editable or claimed)
    if not editable:
        st.caption('当前为查看权限；发送请求或确认计划需要编辑者权限。')
    if (confirm or cancel) and editable and not claimed:
        try:
            def execute(session_id):
                from src.agent import Agent
                return Agent(user_id=user).chat('确认',session_id=session_id)
            sessions.resolve(user,active['id'],sha,'confirm' if confirm else 'cancel',execute)
        except Exception:
            st.error('未确认本次计划操作完成。计划可能已变化或已有原受理记录，请核对，勿重复提交执行。')
            return
        st.session_state['chat_scope']=None
        st.rerun()


def page_chat():
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    page_header('AI 助手','用自然语言调度内容、运营和工作流能力。',icon='✦',eyebrow='COPILOT')
    user=get_current_user()
    if not user:
        st.warning('请先登录后查看自己的会话。')
        return
    editable=has_permission(get_current_role(),'editor')
    if not editable:
        st.caption('当前为查看权限；编辑会话、发送请求和确认计划需要编辑者权限。')
    try:
        data=sessions.view(user)
    except Exception:
        st.warning('会话状态读取失败，当前无法确认历史或待执行计划；暂不开放操作。')
        return
    _progress()
    render('chat_sessions')
    if data['unresolved']:
        st.warning('存在尚未结清的计划受理记录，请核对原执行结果；这不表示原任务仍在运行。系统不会自动重试该计划。')
        with st.expander('原计划受理标识'):
            st.dataframe([{'会话':r['session_id'],'计划指纹':r['plan_sha'][:12],
                '受理状态':'执行结果未知' if r['status']=='outcome_unknown' else '尚无返回回执'} for r in data['unresolved']],hide_index=True)
    active=data['active']
    scope=(user,active['id'] if active else None,active['token'] if active else None)
    if st.session_state.get('chat_scope')!=scope:
        st.session_state['chat_history']=data['messages']
        st.session_state['chat_scope']=scope
    with st.sidebar:
        st.markdown('### 💬 会话窗口')
        if st.button('➕ 新建会话',key='new_session',disabled=not editable) and editable:
            _change(lambda:sessions.new(user),'已新建会话，原会话保留在历史归档。')
        if active:
            st.caption('🟢 '+(active['title'] or '新会话'))
            if st.button('📝',key=f"rename_active_{active['id']}",help='重命名',disabled=not editable) and editable:
                st.session_state[f"show_rename_{active['id']}"]=True
            if st.session_state.get(f"show_rename_{active['id']}"):
                title=st.text_input('新标题',value=active['title'] or '',key=f"rename_input_{active['id']}")
                if st.button('保存',key=f"save_rename_{active['id']}",disabled=not editable) and editable:
                    _change(lambda:sessions.rename(user,active['id'],title),'会话标题已保存。')
            if st.button('📦 归档当前',key='archive_active',disabled=not editable) and editable:
                _change(lambda:sessions.new(user,expected_active=active['id']),'原会话已归档，已创建新会话。')
        for row in data['archived']:
            if st.button('📄 '+(row['title'] or f"会话 #{row['id']}"),key=f"hist_{row['id']}",disabled=not editable) and editable:
                _change(lambda:sessions.activate(user,row['id']),'已恢复所选历史会话。')
            if row['delete_blocked']:
                st.caption('该会话仍有待确认或结果未知的计划，请先核对原记录；当前不能删除。')
            confirmed=st.checkbox('确认永久删除此历史会话及其消息',key=f"delete_session_confirm_{row['id']}_{row['token']}",disabled=not editable or row['delete_blocked'])
            if st.button('🗑',key=f"del_{row['id']}",disabled=not editable or not confirmed or row['delete_blocked']) and editable and confirmed and not row['delete_blocked']:
                _change(lambda:sessions.delete(user,row['id'],confirmed=confirmed,expected_token=row['token']),'所选历史会话及消息已删除。')
        if data['archived']:
            st.caption('删除会话不清除独立记忆或已登记的任务执行回执。')
        if st.button('🧹 仅清空当前显示'):
            st.session_state['chat_history']=[]
            st.rerun()
    for message in st.session_state['chat_history']:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
    pending=bool(active and active.get('pending'))
    user_input=st.chat_input('输入你的需求...',disabled=not editable or pending)
    if user_input and editable and not pending:
        st.session_state['chat_history'].append({'role':'user','content':user_input})
        with st.chat_message('user'):
            st.markdown(user_input)
        try:
            with sessions.user_lock(user):
                fresh=sessions.view(user)['active']
                if fresh and fresh.get('pending'):
                    raise ValueError('A pending plan appeared before dispatch')
                if not fresh:
                    sessions.new(user)
                    fresh=sessions.view(user)['active']
                from src.agent import Agent
                agent=Agent(user_id=user)
                with st.chat_message('assistant'):
                    accumulated=st.write_stream(agent.chat_stream(user_input,session_id=fresh['id']))
                response=agent.last_streaming_response
                text=response.text if response is not None else str(accumulated or '')
                st.session_state['chat_history'].append({'role':'assistant','content':text})
                data=sessions.view(user)
                active=data['active']
        except Exception:
            st.error('本轮助手调用未确认完成。请核对会话和原任务记录，勿重复提交执行。')
            try:
                active=sessions.view(user)['active']
            except Exception:
                return
    _pending(user,active,editable)
