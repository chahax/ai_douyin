"""Synthetic real DOM custom settings; never a claim about platform HTML."""
import pytest

from src.platform_adapter.ai_content_declaration import read_ai_declaration, set_ai_declaration
from test_ai_declaration_committed_row_dom import browser_context, page


def html(*, after='', wrapper='', below=False, opens=True, retained=False, pointer=True):
    row='''<div id="row"><div id="label">自主声明</div>
      <div id="value" style="cursor:POINTER" onclick="openDeclaration()"><span>请选择自主声明</span></div></div>'''.replace('POINTER','pointer' if pointer else 'default')
    if not pointer:
        row=row.replace(' onclick="openDeclaration()"','')
    if wrapper:
        row=wrapper.replace('SLOT',row)
    return '''<!doctype html><meta charset="utf-8"><title>Local custom setting</title>
    <script>window.counts={opens:0,confirms:0};
    function openDeclaration(){counts.opens++;''' + ("document.querySelector('#modal').hidden=false;" if opens else
        "document.querySelector('#value').textContent='内容由AI生成';")+'''}
    function commit(){counts.confirms++;document.querySelector('#value').innerHTML='<span>内容由AI生成</span>';'''+after+(
        "document.querySelector('#modal').hidden=true;" if retained else "document.querySelector('#modal').remove();")+'''}</script>'''+(
        '<div style="height:1800px"></div>' if below else '')+row+'''
    <div id="modal" hidden><h2>对作品内容添加声明</h2>
      <label><input type="radio" name="declaration">内容由AI生成</label>
      <button onclick="commit()">确定</button><button onclick="this.parentElement.hidden=true">取消</button>
    </div>'''


@pytest.mark.parametrize('below',[False,True])
def test_custom_original_outer_value_with_replaced_inner_leaf_and_native_popup_confirmation(page,below):
    page.set_content(html(below=below))
    assert not read_ai_declaration(page)['verified']
    result=set_ai_declaration(page)
    assert result=={'verified':True,'label':'内容由AI生成','method':'confirmed_original_custom_setting_value'}
    assert read_ai_declaration(page)==result
    assert page.evaluate('counts')=={'opens':1,'confirms':1}


@pytest.mark.parametrize('case',['caption','pseudo_row','no_popup','replace_value','navigation','duplicate','connected_contrary'])
def test_custom_identity_and_confirmation_counterexamples_fail_closed_with_safe_diagnostics(page,case):
    options={}
    if case=='caption':options['wrapper']='<div contenteditable="true" aria-label="作品简介">SLOT</div>'
    elif case=='pseudo_row':options['pointer']=False
    elif case=='no_popup':options['opens']=False
    elif case=='replace_value':options['after']="document.querySelector('#value').replaceWith(document.querySelector('#value').cloneNode(true));"
    elif case=='navigation':options['after']="location.hash='different-step';"
    elif case=='duplicate':options['after']="document.querySelector('#row').after(document.querySelector('#row').cloneNode(true));"
    else:
        options['retained']=True
        options['after']="document.querySelector('#modal input').checked=false;"
    page.set_content(html(**options))
    result=set_ai_declaration(page)
    assert not result['verified']
    diagnostic=result.get('diagnostic',{})
    assert diagnostic.get('schema')=='ai_setting_identity/v1'
    assert diagnostic.get('stage')
    assert not any('请选择' in str(value) or '内容由AI' in str(value) for value in diagnostic.values())
    assert not read_ai_declaration(page)['verified']


def test_actual_worker_custom_setting_command_returns_original_bound_value(tmp_path,monkeypatch):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    import test_upload_check_transition_dom as route_fixture
    owner=BrowserSession(BrowserSessionConfig('http://127.0.0.1','http://127.0.0.1',
        str(tmp_path/'state.json'),str(tmp_path/'profile'),headless=True,timeout_ms=5000))
    monkeypatch.setattr(route_fixture,'HTML',html())
    route_fixture.intercept_test_worker(monkeypatch,owner)
    try:
        page=owner.get_page();page.goto(route_fixture.EDITOR_URL)
        result=page.ai_content_declaration(set_selected=True)
        assert result['verified'] and result['method']=='confirmed_original_custom_setting_value'
        assert page.ai_content_declaration()['verified']
        assert page.evaluate('counts')=={'opens':1,'confirms':1}
    finally:
        owner.stop()


def test_navigation_dispatched_during_original_row_read_cannot_return_stale_success(page,monkeypatch):
    import src.platform_adapter.ai_content_declaration as module
    page.set_content(html())
    assert set_ai_declaration(page)['verified']
    row=module._CONFIRMED_ROW[page]['rows'][0][0]
    actual=row.evaluate
    def read_then_navigate(*args,**kwargs):
        result=actual(*args,**kwargs)
        page.evaluate("location.hash='during-original-row-read'")
        return result
    monkeypatch.setattr(row,'evaluate',read_then_navigate)
    result=read_ai_declaration(page)
    assert not result['verified']
    assert result['diagnostic']['identity']=='navigation_or_proof_changed'
