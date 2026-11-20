"""Bounded native viewport preparation; no reupload click or real platform."""
import pytest
from playwright.sync_api import ElementHandle

from src.shared import upload_check_transition as module
from test_upload_check_transition_dom import context,page,select_and_arm,clean


def offscreen(page):
    page.locator('#reupload').evaluate("el=>el.style.marginTop='1800px'")


def test_one_scroll_preserves_original_control_then_checking_clean_and_static_clean_stays_unqualified(page,tmp_path,monkeypatch):
    actual=ElementHandle.scroll_into_view_if_needed;calls=[]
    def scroll(self,**kwargs):
        calls.append(True);return actual(self,**kwargs)
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',scroll)
    offscreen(page);nonce=select_and_arm(page,tmp_path)
    first=module.observe_upload_check(page,nonce)
    assert first['state']=='checking' and len(calls)==1
    assert first['diagnostic']['reupload']['reason']=='offscreen'
    assert first['diagnostic']['reupload_after_scroll']['reason']=='usable'
    clean(page);module.observe_upload_check(page,nonce)
    assert module.observe_upload_check(page,nonce)['verified'] and len(calls)==1
    page.reload();offscreen(page)
    nonce=select_and_arm(page,tmp_path,checking=False);clean(page)
    assert not module.observe_upload_check(page,nonce)['verified']
    assert not module.observe_upload_check(page,nonce)['verified']
    assert len(calls)==2  # Once per new successful selection, never a retry.


def test_onscreen_occlusion_does_not_scroll_or_bypass_hit_test(page,tmp_path,monkeypatch):
    nonce=select_and_arm(page,tmp_path)
    page.evaluate("document.body.insertAdjacentHTML('beforeend','<div style=\"position:fixed;inset:0;z-index:999;background:white\"></div>')")
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',lambda *_a,**_k:pytest.fail('no onscreen scroll'))
    result=module.observe_upload_check(page,nonce)
    assert not result['checking_observed']
    assert result['diagnostic']['reupload']['reason']=='occluded'


def test_disabled_and_inert_controls_are_not_scrolled_or_qualified(page,tmp_path,monkeypatch):
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',lambda *_a,**_k:pytest.fail('no disabled scroll'))
    for attribute in ['disabled','inert']:
        page.reload();offscreen(page);nonce=select_and_arm(page,tmp_path)
        page.locator('#reupload').evaluate(f"el=>el.setAttribute('{attribute}','')")
        result=module.observe_upload_check(page,nonce)
        assert not result['checking_observed']
        assert result['diagnostic']['reupload']['reason']==attribute


@pytest.mark.parametrize('change,reason',[
    ('replace','reupload_scroll_candidate_changed'),('navigation','reupload_scroll_document_changed'),
    ('unknown','reupload_scroll_identity_unknown')])
def test_native_scroll_identity_uncertainty_is_terminal(page,tmp_path,monkeypatch,change,reason):
    offscreen(page);nonce=select_and_arm(page,tmp_path)
    actual=ElementHandle.scroll_into_view_if_needed
    def scroll(self,**kwargs):
        actual(self,**kwargs)
        if change=='replace':page.locator('#reupload').evaluate('el=>el.replaceWith(el.cloneNode(true))')
        elif change=='navigation':page.evaluate('history.replaceState(null,"",location.href)')
        else:raise RuntimeError('synthetic native uncertainty')
    monkeypatch.setattr(ElementHandle,'scroll_into_view_if_needed',scroll)
    result=module.observe_upload_check(page,nonce)
    assert result['state']=='invalid' and result['reason']==reason and not result['verified']


@pytest.mark.parametrize('reason',['reupload_scroll_document_changed','reupload_scroll_candidate_changed','reupload_scroll_identity_unknown'])
def test_prior_bytes_witness_cannot_override_native_scroll_terminal_failure(tmp_path,monkeypatch,reason):
    from test_publish_upload_completion import setup,TRANSFER,READY,rows
    w,p,captures=setup(tmp_path,monkeypatch,[TRANSFER,READY,READY])
    nonce='a'*32;w._upload_fast_selection=(p,w._journal_path,nonce)
    def observe(*_):
        return {'schema':'upload_check_transition/v2','selection_nonce':nonce,'verified':False,
            'state':'armed_editor' if p.index==0 else 'invalid','reason':None if p.index==0 else reason}
    p.upload_check_proof=observe
    assert not w._wait_for_upload_complete(p,timeout=10)
    assert any(r['stage']=='upload_transfer_observed' for r in rows(w))
    assert not any(r['stage']=='upload_completion_verified' for r in rows(w))
    assert captures[-1]['event']=='scroll_identity_failed' and p.index==1


def test_real_worker_bytes_to_stable_clean_after_native_scroll(tmp_path,monkeypatch):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    from src.platform_adapter.publish_workflow import PublishWorkflow
    import test_upload_check_transition_dom as fixture
    markup=fixture.HTML.replace('<button id="reupload">','<button id="reupload" style="margin-top:1800px">')
    markup+='<section id="transport">已上传：3MB/8MB<button>取消上传</button></section>'
    owner=BrowserSession(BrowserSessionConfig('http://127.0.0.1','http://127.0.0.1',
        str(tmp_path/'state.json'),str(tmp_path/'profile'),headless=True,timeout_ms=5000))
    monkeypatch.setattr(fixture,'HTML',markup);fixture.intercept_test_worker(monkeypatch,owner)
    try:
        page=owner.get_page();page.goto(fixture.EDITOR_URL)
        file=tmp_path/'fixture.bin';file.write_bytes(b'no media fixture')
        workflow=PublishWorkflow(owner);workflow._journal_path=tmp_path/'local.jsonl'
        workflow._capture_upload_diagnostic=lambda *_a,**_k:True
        workflow._upload_video_file(page,str(file))
        page.evaluate("setTimeout(()=>{document.querySelector('#transport').remove();document.querySelector('#status').textContent='作品未见异常'},1500)")
        assert workflow._wait_for_upload_complete(page,timeout=12)
        import json
        rows=[json.loads(row) for row in workflow._journal_path.read_text(encoding='utf-8').splitlines()]
        assert any(row['stage']=='upload_transfer_observed' for row in rows)
        assert rows[-1]['method']=='visible_transfer_then_stable_check'
    finally:
        owner.stop()
