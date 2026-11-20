"""Native worker with test-only real DOM selection shapes, no platform requests."""
import json

import pytest

from test_hashtag_selection_dom import worker, page, rendered


def after_native_end(page, script):
    # Test-only event changes a real Selection after native Ctrl+End, before
    # the production readonly guard. Production never writes Selection.
    page.evaluate('''(()=>{const script='''+json.dumps(script)+''';
        document.querySelector('#editor').addEventListener('keyup',event=>{
        if(event.key==='End' && event.ctrlKey) (new Function(script))();
    });})()''')


@pytest.mark.parametrize('shape',['root_end','paragraph_end','before_zwsp','before_feff'])
def test_equivalent_element_offsets_and_format_placeholder_are_logical_end(page,shape):
    if shape=='before_feff':
        page.evaluate("document.querySelector('#editor p:last-child span:last-child').textContent='\\ufeff'")
    if shape=='root_end':
        point="const n=root,offset=root.childNodes.length;"
    elif shape=='paragraph_end':
        point="const n=root.lastElementChild,offset=n.childNodes.length;"
    else:
        point="const n=root.lastElementChild,offset=n.childNodes.length-1;"
    after_native_end(page,"const root=document.querySelector('#editor');"+point+'''
        const range=document.createRange(),selection=getSelection();
        range.setStart(n,offset);range.collapse(true);selection.removeAllRanges();selection.addRange(range);''')
    page.locator('#editor').type_hashtag('劳动法')
    text=rendered(page)
    assert '#原有话题' in text and '#劳动法' in text
    assert text.startswith('剧情虚构，非真实事件。')


@pytest.mark.parametrize('shape,reason',[
    ('middle_text','tail_text'),('before_chip','tail_void'),
    ('inside_chip','anchor_void'),('unknown_tail','tail_unknown')])
def test_middle_text_original_chip_or_unknown_tail_reject_with_safe_evidence(page,shape,reason):
    if shape=='unknown_tail':
        page.evaluate("document.querySelector('#editor p:last-child').insertAdjacentHTML('beforeend','<img alt=unread>')")
    if shape=='middle_text':
        point="const n=root.firstElementChild.firstChild,offset=1;"
    elif shape=='inside_chip':
        point="const n=root.querySelector('[contenteditable=false]').firstChild,offset=2;"
    elif shape=='before_chip':
        point="const n=root.lastElementChild,offset=1;"
    else:
        point="const n=root.lastElementChild,offset=n.childNodes.length-1;"
    after_native_end(page,"const root=document.querySelector('#editor');"+point+'''
        const range=document.createRange(),selection=getSelection();range.setStart(n,offset);
        range.collapse(true);selection.removeAllRanges();selection.addRange(range);''')
    before=rendered(page)
    with pytest.raises(RuntimeError,match='end selection') as caught:
        page.locator('#editor').type_hashtag('劳动法')
    message=str(caught.value)
    diagnostic=json.loads(message[message.index('{'):])
    assert diagnostic['reason']==reason and not diagnostic['ok']
    assert diagnostic['rangeCount']==1 and diagnostic['collapsed']
    assert diagnostic['focusRoot'] and diagnostic['inRoot']
    assert not any(word in message for word in ['剧情虚构','原有话题','劳动法'])
    assert len(message)<500 and rendered(page)==before
