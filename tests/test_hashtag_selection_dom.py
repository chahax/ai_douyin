"""Local real worker/native keyboard tests, not platform Slate acceptance."""
import json
from types import SimpleNamespace

import pytest

from src.platform_adapter import browser_session as browser_module
from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.platform_adapter.publish_workflow import PublishWorkflow
import test_upload_check_transition_dom as local_routes


DESCRIPTION = '剧情虚构，非真实事件。\n原简介第二行保留。'
HTML = '''<!doctype html><meta charset="utf-8"><title>Local caret fixture</title>
<style>#editor{width:500px;min-height:180px;border:1px solid} [contenteditable=false]{background:#ddd}</style>
<button id="outside">Outside</button>
<div id="editor" contenteditable="true" data-slate-editor="true"><p>剧情虚构，非真实事件。</p><p>原简介第二行保留。<span data-slate-inline="true" contenteditable="false">#原有话题</span><span>\u200b</span></p></div>
<script>
const root=document.querySelector('#editor');
root.addEventListener('keydown',event=>{
 if(event.key!=='Enter') return;
 const sel=getSelection(), node=sel.anchorNode;
 if(!node || node.nodeType!==3) return;
 const match=node.textContent.match(/ #([^\\s#]+)$/u);
 if(!match) return;
 event.preventDefault();
 const start=node.textContent.length-match[0].length;
 node.deleteData(start,match[0].length);
 const chip=document.createElement('span');chip.contentEditable='false';
 chip.dataset.slateInline='true';chip.textContent='#'+match[1];
 const tail=document.createTextNode(' \u200b');node.after(chip,tail);
 const range=document.createRange();range.setStart(tail,tail.length);range.collapse(true);
 sel.removeAllRanges();sel.addRange(range);
});
</script>'''


@pytest.fixture(scope='module')
def worker(tmp_path_factory):
    root = tmp_path_factory.mktemp('hashtag_native_worker')
    owner = BrowserSession(BrowserSessionConfig('http://127.0.0.1','http://127.0.0.1',
        str(root/'state.json'), str(root/'isolated_profile'),headless=True,timeout_ms=5000))
    patch = pytest.MonkeyPatch()
    patch.setattr(local_routes,'HTML',HTML)
    local_routes.intercept_test_worker(patch,owner)
    try:
        yield owner
    finally:
        owner.stop()
        patch.undo()


@pytest.fixture
def page(worker):
    page = worker.get_page()
    page.goto(local_routes.EDITOR_URL)
    return page


def rendered(page):
    return page.locator('#editor').inner_text()


def test_multiline_five_tags_accumulate_and_existing_chip_description_preserved(page,tmp_path):
    value = PublishWorkflow(SimpleNamespace())
    value._journal_path=tmp_path/'form-only.jsonl'
    tags=['劳动法','劳动权益','离职避坑','普法知识','AI剧情']
    value._add_hashtags(page,tags,expected_description=DESCRIPTION)
    text=rendered(page)
    for tag in ['原有话题']+tags:
        assert text.count('#'+tag)==1
    assert value._description_preserved({'text':text},DESCRIPTION)
    last=json.loads(value._journal_path.read_text(encoding='utf-8').splitlines()[-1])
    assert last['phase']=='complete' and not last['missing']


def test_previous_center_chip_selection_is_not_replaced(page):
    page.evaluate('''()=>{const chip=document.querySelector('[contenteditable=false]');
      const selection=getSelection(), range=document.createRange();range.selectNodeContents(chip);
      selection.removeAllRanges();selection.addRange(range);}''')
    page.locator('#editor').type_hashtag('劳动法')
    assert '#原有话题' in rendered(page) and '#劳动法' in rendered(page)


def test_each_call_refocuses_from_outside_with_old_caret_at_start(page):
    for tag in ['劳动法','劳动权益']:
        page.evaluate('''()=>{const selection=getSelection(),range=document.createRange();
          range.selectNodeContents(document.querySelector('#editor'));range.collapse(true);
          selection.removeAllRanges();selection.addRange(range);document.querySelector('#outside').focus();}''')
        page.locator('#editor').type_hashtag(tag)
    assert rendered(page).endswith('#劳动权益 \u200b')
    assert '#劳动法' in rendered(page) and '#原有话题' in rendered(page)


def test_unknown_native_selection_stops_before_typing(page):
    before=rendered(page)
    page.evaluate('document.getSelection=()=>null')
    with pytest.raises(RuntimeError,match='end selection'):
        page.locator('#editor').type_hashtag('劳动法')
    assert rendered(page)==before


def test_focus_stolen_before_end_validation_stops_without_typing(page):
    before=rendered(page)
    page.evaluate('''document.querySelector('#editor').addEventListener('focus',
      ()=>document.querySelector('#outside').focus())''')
    with pytest.raises(RuntimeError,match='end selection'):
        page.locator('#editor').type_hashtag('劳动法')
    assert rendered(page)==before
