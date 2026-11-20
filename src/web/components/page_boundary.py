"""Replace a failed management surface with a safe, explicit unknown state."""
import logging

import streamlit as st


def render_content(render):
    region = st.empty()
    try:
        with region.container():
            render()
    except Exception:
        # Streamlit stop/rerun signals inherit BaseException and are not caught.
        # Clear partially built forms, not merely append a raw traceback to them.
        logging.getLogger(__name__).exception('Management page rendering failed')
        with region.container():
            st.error('此页状态读取失败，当前无法确认任务或配置是否正常。已停止展示本轮操作表单，请刷新后核对。')
            st.caption('刷新只重新读取页面；后台原任务继续按原状态保留。详细原因请由管理员核对本地后台日志。')
            if st.button('重新读取本页', key='management_page_read_retry'):
                st.rerun()
