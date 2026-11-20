from streamlit.testing.v1 import AppTest


def test_failed_surface_hides_partial_forms_and_never_leaks_exception():
    app = AppTest.from_string('''
import streamlit as st
from src.web.components.page_boundary import render_content
def broken():
    st.button('unavailable mutation', key='old_action')
    raise RuntimeError('PRIVATE_TOKEN_VALUE')
render_content(broken)
''').run()
    assert not app.exception
    assert [b.label for b in app.button] == ['重新读取本页']
    assert any('无法确认' in item.value for item in app.error)
    assert all('PRIVATE_TOKEN_VALUE' not in item.value for item in app.error)
    app.button(key='management_page_read_retry').click().run()
    assert not app.exception and len(app.button) == 1


def test_successful_surface_preserves_widgets_and_normal_reruns():
    app = AppTest.from_string('''
import streamlit as st
from src.web.components.page_boundary import render_content
def page():
    st.session_state.setdefault('clicks', 0)
    if st.button('local action'):
        st.session_state.clicks += 1
        st.rerun()
    st.write('saved: ' + str(st.session_state.clicks))
render_content(page)
''').run()
    app.button[0].click().run()
    assert not app.exception and app.session_state['clicks'] == 1
    assert not app.error
