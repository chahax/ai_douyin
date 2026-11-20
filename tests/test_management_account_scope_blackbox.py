from streamlit.testing.v1 import AppTest


def test_two_account_selectors_remain_consistent_across_callbacks_and_reruns():
    app = AppTest.from_string('''
import streamlit as st
from types import SimpleNamespace as NS
from src.web.components.account_scope import select_account_scope
profiles=[NS(account_uuid='A',account_key='a',display_name='甲'),NS(account_uuid='B',account_key='b',display_name='乙')]
with st.sidebar:
    select_account_scope(profiles,key='global',allow_unassigned=True)
selected=select_account_scope(profiles,key='local',allow_all=False)
st.write('selected='+str(selected))
st.write('active='+str(st.session_state.get('active_account_uuid','*')))
''').run()
    app.selectbox(key='local').set_value('A').run()
    assert app.selectbox(key='global').value == 'A'
    assert [x.value for x in app.markdown] == ['selected=A', 'active=A']
    app.run()
    assert [x.value for x in app.markdown] == ['selected=A', 'active=A']
    app.selectbox(key='global').set_value('B').run()
    assert app.selectbox(key='local').value == 'B'
    assert [x.value for x in app.markdown] == ['selected=B', 'active=B']
    app.selectbox(key='global').set_value('*').run()
    assert app.selectbox(key='local').value == '?'
    assert [x.value for x in app.markdown] == ['selected=?', 'active=*']
