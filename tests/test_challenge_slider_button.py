import pytest

from src.platform_adapter.douyin_challenge import probe_challenge_page, confirmed_douyin_challenge


@pytest.fixture(scope='module')
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--mute-audio'])
        yield browser
        browser.close()


@pytest.mark.parametrize('control_style,media,expected', [
    ('',True,'challenge_ready'),
    ('display:none',True,'unconfirmed'),
    ('pointer-events:none',True,'unconfirmed'),
    ('opacity:0',True,'unconfirmed'),
    ('',False,'unconfirmed'),
])
def test_observed_slider_style_requires_exposed_control_and_loaded_media(browser,control_style,media,expected):
    page=browser.new_page()
    try:
        picture='<canvas width="300" height="150"></canvas>' if media else ''
        html=f'<meta charset="utf-8"><p>请完成下列验证后继续</p>{picture}<p>按住左边按钮拖动完成上方拼图</p><div class="captcha-slider-btn" style="width:64px;height:40px;{control_style}">→</div>'
        page.route('**/captcha/test',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body=html))
        page.set_content('<iframe src="https://example.test/captcha/test" style="width:380px;height:384px"></iframe>')
        page.frames[-1].locator('.captcha-slider-btn').wait_for(state='attached')
        result=probe_challenge_page(page)
        assert result['blocking']
        assert result['surface_states']==[expected]
        if expected=='challenge_ready':
            class Probe:
                def probe_douyin_challenge(self): return probe_challenge_page(page)
                def wait_for_timeout(self,ms): page.wait_for_timeout(ms)
            confirmed=confirmed_douyin_challenge(Probe())
            assert confirmed['confirmations']==2
    finally:
        page.close()
