"""Window preferences change display/lifetime only, never create business work."""
import streamlit as st


def render_window_supervision(account, key):
    from src.web.components.auth import get_current_user, get_current_role, has_permission
    if not get_current_user():
        return
    from src.operations_accounts import window_supervision as windows
    admin = has_permission(get_current_role(), 'admin')
    with st.expander(f'常驻监管窗口 · {key}'):
        if not windows.rollout_enabled():
            st.caption('常驻监管模式尚未启用，需先完成部署验收。')
            return
        try:
            pref = windows.preference(account)
            current = windows.live_runtime(account)
        except Exception:
            st.warning('监管窗口状态暂不可用；当前不能确认窗口在线。')
            return
        st.caption('窗口静音，首次启动最小化；展开查看后，自动导航不会再次最小化。可从任务栏查看同一个账号窗口。')
        with st.form('window_supervision_'+account):
            selected = st.checkbox('保留原账号窗口，空闲时也不回收', value=bool(pref['enabled']), disabled=not admin)
            if st.form_submit_button('保存窗口设置', disabled=not admin) and admin:
                try:
                    windows.save_from_web(account, key, selected, 'background', expected_revision=pref['revision'])
                except Exception:
                    st.error('窗口设置未能保存，请刷新后核对账号状态。')
                else:
                    st.success('设置已保存。兼容的可见会话在安全点接入；旧版本或无头会话待正常交还后加载，不中断当前任务，也不新增业务。')
                    st.rerun()
        if not pref['enabled']:
            return
        if current:
            st.caption('原窗口在线、静音。查看只改变窗口显示；自动流程仍会操作其任务页面。')
            for mode, label in (('watch', '查看原运行窗口'), ('background', '收起到后台')):
                if st.button(label, key='window_'+mode+'_'+account, disabled=not admin) and admin:
                    try:
                        windows.save_from_web(account, key, True, mode, expected_revision=pref['revision'], display=True)
                    except Exception:
                        st.warning('原窗口或设置已变化，未登记显示操作，请刷新。')
                    else:
                        st.info('显示请求已登记，在原任务的下一个浏览器安全点生效；任务栏可直接查看。')
                        st.rerun()
            if current['applied_revision'] != pref['revision']:
                st.caption('显示请求尚未获得原窗口确认，请勿重复提交。')
        else:
            st.caption('尚无新鲜的原窗口在线回执；设置已保留。不会为查看而重开环境或重新派发任务。')
        if st.button('申请暂停自动操作，准备人工接管', key='window_pause_'+account, disabled=not admin) and admin:
            try:
                windows.pause_from_web(account, key)
            except Exception:
                st.error('暂停请求未能登记，请核对账号状态。')
            else:
                st.info('已登记暂停；原任务及运行锁交还前，请勿同时点击或输入。')
                st.rerun()
        try:
            ready = windows.takeover_ready(account)
        except Exception:
            ready = False
        if ready and current:
            st.success('该账号已暂停，原任务和运行锁已交还，可以人工操作。完成后由本人点击“处理完成，继续运行”。')
        else:
            st.caption('现在可以观察。人工操作前须暂停并等待任务交还；结果未知时保持原记录，不自动强行接管。')
