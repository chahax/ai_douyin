"""Keep local mutation feedback visible across the successful rerun."""
import streamlit as st


def remember(key, message):
    st.session_state['_action_feedback_' + key] = message


def render(key):
    message = st.session_state.pop('_action_feedback_' + key, None)
    if isinstance(message, str):
        st.success(message)


def perform_local(key, message, operation):
    """For boolean-returning local settings services, not external tasks."""
    try:
        saved = operation()
    except Exception:
        st.error('操作未确认成功，请刷新记录并核对本地后台日志。')
        return False
    if saved is not True:
        st.warning('操作未保存：目标不存在、记录冲突或状态已变化，请核对当前记录。')
        return False
    remember(key, message)
    st.rerun()
