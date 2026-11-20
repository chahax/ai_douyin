"""Only the bound declaration popup gates its custom setting proof."""
import pytest

import src.platform_adapter.ai_content_declaration as module
from test_ai_custom_setting_dom import html
from test_ai_declaration_committed_row_dom import browser_context, page


def unrelated(role='menu'):
    return f'<div role="{role}" style="margin-top:100px">其他设置</div>'


@pytest.mark.parametrize('role',['menu','dialog'])
def test_real_worker_unrelated_persistent_role_does_not_veto_confirmed_original_declaration(tmp_path,monkeypatch,role):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    import test_upload_check_transition_dom as route_fixture
    owner=BrowserSession(BrowserSessionConfig('http://127.0.0.1','http://127.0.0.1',
        str(tmp_path/'state.json'),str(tmp_path/'profile'),headless=True,timeout_ms=5000))
    monkeypatch.setattr(route_fixture,'HTML',html()+unrelated(role))
    route_fixture.intercept_test_worker(monkeypatch,owner)
    try:
        page=owner.get_page();page.goto(route_fixture.EDITOR_URL)
        assert page.ai_content_declaration(set_selected=True)['verified']
        assert page.ai_content_declaration()['verified']
        assert page.locator(f'[role={role}]').count()==1
        assert page.evaluate('counts')=={'opens':1,'confirms':1}
    finally:
        owner.stop()


def test_global_role_count_is_diagnostic_only_and_original_popup_is_closed(page):
    page.set_content(html()+unrelated())
    assert module.set_ai_declaration(page)['verified']
    diagnostic=module._DIAGNOSTICS[page]
    assert diagnostic['declarationPopupClosed'] is True
    assert diagnostic['globalVisibleRoleCount']==1
    assert diagnostic['structure'] is True
    assert 'popupsClear' not in diagnostic


@pytest.mark.parametrize('case',['original_reopened','new_ai_popup','unconfirmed','connected_contrary'])
def test_related_ai_popup_or_unconfirmed_native_state_still_rejects_with_unrelated_menu(page,case):
    options={}
    if case in ('original_reopened','connected_contrary'):
        options['retained']=True
    if case=='unconfirmed':options['opens']=False
    if case=='connected_contrary':options['after']="document.querySelector('#modal input').checked=false;"
    page.set_content(html(**options)+unrelated())
    first=module.set_ai_declaration(page)
    if case in ('unconfirmed','connected_contrary'):
        assert not first['verified']
    else:
        assert first['verified']
        if case=='original_reopened':
            page.evaluate("document.querySelector('#modal').hidden=false")
        else:
            # No exact declaration title: the visible AI native option in a
            # distinct popup is independently blocked by the outer read gate.
            page.evaluate('''document.body.insertAdjacentHTML('beforeend',
              '<div role="dialog"><label><input type="radio" checked>内容由AI生成</label></div>')''')
        assert not module.read_ai_declaration(page)['verified']
