"""Close click is observed once through delayed UI animation, never retried."""
import os

import pytest

from src.platform_adapter import fanqie_promotion_preflight_v1 as m
from test_fanqie_promotion_preflight_v1 import Page,BOOK,NAME


class ClosingPage(Page):
    def __init__(self,*,remaining=0,disabled=False,count_override=None,click_success=True):
        super().__init__(disabled=disabled)
        self.remaining=remaining;self.polls=0;self.count_override=count_override;self.click_success=click_success
    def evaluate(self,js):
        if js==m.CLOSE_JS:self.closed+=1;return dict(closed=self.click_success)
        if js==m.MODAL_STATE_JS:
            self.polls+=1
            return dict(visible_modal_count=self.count_override if self.count_override is not None else int(self.polls<=self.remaining))
        return super().evaluate(js)


def inspect(page):
    steps=[];guards=[]
    result=m.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=lambda:guards.append(True),
        checkpoint=lambda stage,value:steps.append((stage,value)))
    return result,steps,guards


def test_delayed_close_polls_only_then_keeps_original_form_success():
    page=ClosingPage(remaining=4);result,steps,guards=inspect(page)
    assert page.closed==1 and page.polls==5 and result['preflight_passed']
    assert result['status']==result['modal_close_origin_status']=='form_options_verified'
    observations=result['modal_close_observations']
    assert [o['observed']['visible_modal_count']for o in observations]==[1,1,1,1,0]
    assert [o['waited_ms']for o in observations]==[100,200,300,400,500]
    assert all(o['observed_at']>0 and o['original_status']=='form_options_verified'for o in observations)
    assert len([stage for stage,_ in steps if stage.startswith('close_observation_')])==5
    assert len(guards)>=page.polls*2


def test_never_close_or_unreadable_count_remains_unconfirmed_no_retry():
    for kwargs in [dict(remaining=99),dict(count_override=False)]:
        page=ClosingPage(**kwargs);result,_,_=inspect(page)
        assert page.closed==1 and page.polls==20
        assert result['status']=='modal_close_unconfirmed' and not result['preflight_passed']
        assert result['modal_close_confirmed'] is False and result['modal_close_observations'][-1]['waited_ms']==2000
        assert result['modal_close_origin_status']=='form_options_verified'


def test_failed_close_click_does_not_poll_and_failed_AIGC_stage_is_not_upgraded():
    page=ClosingPage(click_success=False);result,_,_=inspect(page)
    assert page.closed==1 and page.polls==0 and not result['preflight_passed']
    assert result['status']=='modal_close_unconfirmed' and result['modal_close_observations']==[]
    page=ClosingPage(remaining=2,disabled=True);result,_,_=inspect(page)
    assert page.closed==1 and page.polls==3 and result['modal_close_confirmed']
    assert result['status']==result['modal_close_origin_status']=='aigc_unavailable'
    assert not result['preflight_passed']


@pytest.mark.skipif(os.environ.get('RUN_LOCAL_PREFLIGHT_DOM_TEST')!='1',reason='Fresh isolated local DOM opt-in')
def test_real_local_DOM_delayed_close_and_never_close_click_once_zero_write():
    from playwright.sync_api import sync_playwright
    with sync_playwright()as pw:
        browser=pw.chromium.launch(channel='chrome',headless=True,args=['--mute-audio','--disable-background-networking',
            '--disable-component-update','--no-first-run','--host-resolver-rules=MAP * ~NOTFOUND'])
        try:
            for delay,expected in [(650,'form_options_verified'),(None,'modal_close_unconfirmed')]:
                close="setTimeout(()=>{document.querySelector('#modal').style.display='none';document.querySelector('#options').style.display='none';},%s)"%delay if delay is not None else ''
                html=f'''<meta charset="utf-8"><script>window.closeClicks=window.aliasWrites=window.submits=0</script>
                 <div class="book-hQ7GYr"><span class="book-title-txt-_CIhYa">{NAME}</span><button onclick="document.querySelector('#modal').style.display='block'">别名推广</button></div>
                 <div id="modal" class="arco-modal" style="display:none"><button class="arco-modal-close-icon" onclick="window.closeClicks++;{close}">关闭</button>
                 <div class="arco-modal-content"><div>{NAME}（{BOOK}）</div><input class="alias-input-EBp1Sw" oninput="window.aliasWrites++">
                 <div class="arco-form-item"><label class="arco-form-item-label">发文类型</label><div class="arco-select" onclick="document.querySelector('#options').style.display='block'">请选择</div></div>
                 <button onclick="window.submits++">提交</button></div></div><div id="options" style="display:none"><div role="option">AIGC</div></div>'''
                context=browser.new_context();page=context.new_page()
                context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
                page.goto(m.CONTENT_URL)
                steps=[];result=m.inspect_preflight(page,book_id=BOOK,book_name=NAME,guard=lambda:None,
                    checkpoint=lambda stage,value:steps.append((stage,value)))
                assert result['status']==expected and result['modal_close_origin_status']=='form_options_verified'
                assert page.evaluate('({close:closeClicks,alias:aliasWrites,submit:submits})')==dict(close=1,alias=0,submit=0)
                counts=[o['observed']['visible_modal_count']for o in result['modal_close_observations']]
                assert counts[0]==1
                if delay is None:assert counts==[1]*20 and not result['preflight_passed']
                else:assert counts[-1]==0 and len(counts)<20 and result['preflight_passed']
                context.close()
        finally:browser.close()
