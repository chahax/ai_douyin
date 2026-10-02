"""Shared account selection; selection changes do not rewrite persisted jobs."""
import streamlit as st


def select_account_scope(profiles, *, key, allow_all=True, allow_unassigned=False):
    labels = {p.account_uuid: f'{p.display_name or p.account_key} · {p.account_key}' for p in profiles}
    options = (['*'] if allow_all else ['?']) + list(labels)
    if allow_unassigned:
        options.append('')
    labels.update({'*': '全部账号汇总', '': '历史未归属 / 归属待核对', '?': '请选择运营账号'})
    active = st.session_state.get('active_account_uuid', '*')
    marker = key + '_observed_scope'
    if marker not in st.session_state or st.session_state[marker] != active or st.session_state.get(key) not in options:
        st.session_state[key] = active if active in options else options[0]

    def changed():
        value = st.session_state[key]
        st.session_state['active_account_uuid'] = value
        st.session_state[marker] = value

    value = st.selectbox('账号范围' if allow_all else '当前运营账号', options,
                         format_func=lambda item: labels[item], key=key, on_change=changed)
    st.session_state[marker] = st.session_state.get('active_account_uuid', '*')
    return None if value == '*' else value
