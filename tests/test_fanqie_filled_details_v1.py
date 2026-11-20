"""Isolated real browser checks; every request is fulfilled locally."""
import pytest
from playwright.sync_api import sync_playwright
from src.platform_adapter import fanqie_filled_details_v1 as subject


BOOK = '7302660145530539062'
NAME = '你敢惹我？我有六个反派儿子'
ALIAS = '从旧饭桌开始改命'


def html(rows=1, book=BOOK):
    row = f'''<tr><td>{ALIAS}</td><td><div class="book-name-iHil3A">{NAME}</div>ID：{book}</td>
    <td><div style="cursor:pointer" onclick="window.detailsClicks++;document.querySelector('[role=dialog]').style.display='block'">已填写（1条）</div></td></tr>'''
    return '''<!doctype html><meta charset=utf-8><script>window.detailsClicks=0</script>
    <table><thead><tr><th>关键词</th><th>书本信息</th><th>发文详情</th></tr></thead><tbody>'''+row*rows+'''</tbody></table>
    <div role="dialog" style="display:none"><h2>发文详情</h2><a href="https://www.douyin.com/video/7709043480894524722">已提交作品</a><button>添加链接</button></div>'''


class Page:
    def __init__(self, page):
        self.raw = page

    def _cmd(self, action):
        assert action == 'current_url'
        return {'url': self.raw.url}

    def __getattr__(self, name):
        return getattr(self.raw, name)


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True)
        yield browser
        browser.close()


def open_page(browser, content):
    context = browser.new_context()
    context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=content))
    page = context.new_page()
    page.goto('https://kol.fanqieopen.com/page/promotion-list?tab_type=2')
    return context, Page(page)


def inspect(page, records):
    return subject.inspect_filled_details(page, book_id=BOOK, book_name=NAME, alias=ALIAS,
                                          guard=lambda: None, checkpoint=lambda stage, value: records.append((stage, value)))


def test_exact_row_native_click_reads_old_link_without_accepting_append(browser):
    context, page = open_page(browser, html())
    try:
        records = []
        result = inspect(page, records)
        assert page.evaluate('()=>window.detailsClicks') == 1
        assert [stage for stage, _ in records] == ['panel_before', 'table', 'row', 'click_intent', 'panel']
        assert result['previous_count'] == 1
        assert result['panel']['links'] == [{'text': '已提交作品', 'origin': 'https://www.douyin.com',
                                            'path': '/video/7709043480894524722'}]
        assert result['append_capability_verified'] is False
        assert result['submitted'] is result['uploaded'] is False
    finally:
        context.close()


def test_preexisting_details_panel_cannot_be_attributed_to_target(browser):
    context, page = open_page(browser, html().replace('role="dialog" style="display:none"', 'role="dialog" style="display:block"'))
    try:
        with pytest.raises(subject.DetailsNotConfirmed, match='preexisting_details_panel_requires_review'):
            inspect(page, [])
        assert page.evaluate('()=>window.detailsClicks') == 0
    finally:
        context.close()


@pytest.mark.parametrize('content', [html(rows=2), html(book='7302660145530539999')], ids=['ambiguous-row', 'wrong-book'])
def test_ambiguous_or_wrong_book_never_opens_details(browser, content):
    context, page = open_page(browser, content)
    try:
        with pytest.raises(subject.DetailsNotConfirmed, match='exact_filled_alias_row_not_unique'):
            inspect(page, [])
        assert page.evaluate('()=>window.detailsClicks') == 0
    finally:
        context.close()


def test_original_owner_routes_typed_details_read_without_backfill(tmp_path, monkeypatch):
    from test_fanqie_managed_promotion_v1 import accounts, Session
    from src.operations_accounts.fanqie_account_control import run_owner
    account, env = accounts.__wrapped__(tmp_path)
    calls = []
    def reader(page, *, book_id, book_name, alias, guard, checkpoint):
        guard()
        assert (book_id, book_name, alias) == (BOOK, NAME, ALIAS)
        assert page.url.startswith('https://kol.fanqieopen.com/page/promotion-list')
        calls.append((book_id, alias))
        value = dict(schema='fanqie_filled_details_observation/v1', uploaded=False, submitted=False,
                     append_capability_verified=False, old_ledger_changed=False)
        checkpoint('panel', value)
        return value
    monkeypatch.setattr(subject, 'inspect_filled_details', reader)
    for extra in [dict(promotion_request={}), dict(observer_request={}), dict(chapters=1),
                  dict(locate=True), dict(lookup_request={}), dict(snapshot_version='v2')]:
        with pytest.raises(ValueError):
            account.queue(env['resource_id'], 'fanqie_filled_details', book_id=BOOK, book_name=NAME,
                          lookup_alias=ALIAS, **extra)
    command = account.queue(env['resource_id'], 'fanqie_filled_details', book_id=BOOK, book_name=NAME,
                            lookup_alias=ALIAS)
    assert command['payload'] == dict(environment_key=env['environment_key'], book_id=BOOK,
                                     book_name=NAME, lookup_alias=ALIAS)
    result = run_owner(env['resource_id'], account, session_factory=Session)
    assert result['state'] == 'succeeded' and calls == [(BOOK, ALIAS)]
    assert result['result']['backfill_submitted'] is False
    assert result['result']['promotion_submitted'] is False
    assert result['result']['append_capability_verified'] is False
    assert Session.submit_count == 0
