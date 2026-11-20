"""Explicit administrator activation, separate from ordinary read-only views."""
def render_feedback_upgrade():
    import streamlit as st
    from src.web.components.auth import get_current_user,get_current_role,has_permission
    if not get_current_user() or not has_permission(get_current_role(),'admin'):
        return
    from src.scheduler import runner
    from src.scheduler.handling_fast_lane import JOB_ID,install_from_web
    scheduler=getattr(getattr(runner,'scheduler_instance',None),'_scheduler',None)
    if scheduler is None or not scheduler.running:
        return
    with st.sidebar.expander('人工处理反馈'):
        if scheduler.get_job(JOB_ID) is not None:
            st.caption('快速受理通道已登记。身份核验仍以原请求结果为准。')
            return
        st.caption('加快已登记完成请求的受理与进度更新，无需关闭账号窗口或重启后台。')
        if st.button('启用快速核验反馈',key='activate_handling_feedback'):
            try:
                install_from_web()
            except Exception:
                st.error('未能确认快速通道已加载，请核对后台；原账号状态保持。')
            else:
                st.success('快速受理已启用。')
                st.rerun()
