from unittest.mock import Mock
import pytest
from src.platform_adapter.recommendation_entry import enter_recommendation


@pytest.mark.parametrize('mode',['good','other_path','external','ambiguous','changed'])
def test_only_unique_observed_same_site_recommendation_link_is_clicked(mode):
    state={'host':'www.douyin.com','path':'/jingxuan','links':[{'index':4,'label':'推荐','visible':True,'host':'www.douyin.com','protocol':'https:'}]}
    if mode=='other_path':state['path']='/user/self'
    if mode=='external':state['links'][0]['host']='evil.example'
    if mode=='ambiguous':state['links']*=2
    page=Mock();page.locator.return_value.evaluate.side_effect=[state,{} if mode=='changed' else state]
    result=enter_recommendation(page)
    assert result['clicked']==(mode=='good')
    if mode=='good':page.locator.return_value.nth.return_value.click.assert_called_once_with(timeout=3000)
    else:page.locator.return_value.nth.return_value.click.assert_not_called()


def test_real_chrome_clicks_observed_navigation_link():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--mute-audio'])
        try:
            page=browser.new_page()
            page.route('https://www.douyin.com/**',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body='<a href="/?recommend=1">推荐</a>'))
            page.goto('https://www.douyin.com/jingxuan')
            assert enter_recommendation(page)['clicked']
            page.wait_for_url('https://www.douyin.com/?recommend=1')
        finally:browser.close()
