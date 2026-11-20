"""Execute the real collector JS on inert DOM: no website or media requests."""
import json
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from src.trend_intelligence.providers.douyin_web import EXTRACT_SCRIPT, VERIFIED_SEARCH_LIKE_PATHS

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"data/qa/legal_new_batch_script_flow_20261007/round_01/SEARCH_METRIC_DOM.json"

@pytest.fixture(scope="module")
def page():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="chrome",headless=True)
        context=browser.new_context()
        context.route("**/*",lambda route:route.abort())
        page=context.new_page()
        yield page
        context.close();browser.close()

def extract(page,html):
    page.set_content(html)
    return page.evaluate(EXTRACT_SCRIPT)

def card(body):
    return '<li><a href="https://www.douyin.com/video/1234567890">'+body+'</a></li>'

def heart(number="23.6万",path=None):
    shape=VERIFIED_SEARCH_LIKE_PATHS[0] if path is None else path
    return '<div><svg viewBox="0 0 24 24"><path d="'+shape+'"></path></svg><span>'+number+'</span></div>'

def test_real_eight_search_cards_match_observed_heart_counts(page):
    # Source cards are visible metadata evidence. External resources are aborted.
    cards=json.loads(SOURCE.read_text(encoding="utf-8"))["cards"]
    rows=extract(page,'<ul>'+''.join(c['html'] for c in cards)+'</ul>')
    assert len(rows)==8 and all(r['metricKind']=='likes' for r in rows)
    assert rows[0]['metricText']=='1.5万' and rows[1]['metricText']=='23.6万'

@pytest.mark.parametrize('body',[
    '<span>23.6万</span>',heart(path='M0 0L24 24'),
    heart().replace('</span></div>', '</span><span>99万</span></div>'),
    '<div><svg viewBox="0 0 24 24"><path d="'+VERIFIED_SEARCH_LIKE_PATHS[0]+'"></path></svg></div><div>23.6万</div>',
])
def test_unknown_or_unassociated_numbers_stay_unknown(page,body):
    row=extract(page,card(body))[0]
    assert row['metricKind']=='displayed_unknown'

def test_known_heart_numeric_sibling_and_old_aria_contract(page):
    assert extract(page,card(heart()))[0]['metricKind']=='likes'
    row=extract(page,card('<span aria-label="点赞 18.5万">18.5万</span>'))[0]
    assert row['metricKind']=='likes' and row['metricText']=='18.5万'
