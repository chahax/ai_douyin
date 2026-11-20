"""Actual worker/Chrome navigation and fail-closed search recovery, without platform IO."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from src.platform_adapter.browser_session import BrowserSession, BrowserNavigationTimeout, Page
from src.platform_adapter.models import BrowserSessionConfig
from src.shared.browser_navigation import clean_navigation_evidence
from src.trend_intelligence.providers import douyin_web as web


@pytest.fixture
def local_browser(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/pending':
                time.sleep(2)
            if self.path == '/identity-pending':
                time.sleep(5)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            body = '<html><body><a href="https://www.douyin.com/video/7531234567890123456" title="法律知识测试">法律知识测试</a>'
            if self.path == '/identity':
                body += '<h1>测试法律号</h1><p>抖音号：local-test-account</p>'
            if self.path == '/identity':
                body += '<script>fetch("/identity-pending")</script>'
            if self.path == '/search':
                body += '<script>fetch("/pending")</script>'
            body += '</body></html>'
            try:
                self.wfile.write(body.encode())
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    session = BrowserSession(BrowserSessionConfig(base_url=url, home_url=url,
        user_data_dir=str(tmp_path/'profile'), storage_state_path=str(tmp_path/'state.json'),
        headless=True, browser_channel='chrome'))
    try:
        yield session, url
    finally:
        session.stop()
        server.shutdown()
        server.server_close()


def collect(provider, session):
    return provider._collect_sort(session, query='法律', root_keywords=['法律'], query_kind='keyword',
        query_depth=0, sort=web.DOUYIN_SORTS[0], limit=1, retain_raw=False)


def test_actual_worker_honors_wait_condition_and_keeps_same_tab(local_browser):
    session, url = local_browser
    page = session.open_page(url)
    original = page.tab_id
    with pytest.raises(BrowserNavigationTimeout) as caught:
        page.goto(url+'/search', wait_until='networkidle', timeout=200)
    error = caught.value
    assert error.page is page and page.tab_id == original
    assert error.navigation_evidence['target_matched']
    assert error.navigation_evidence['navigation_committed']
    assert error.navigation_evidence['wait_until'] == 'networkidle'
    assert error.navigation_evidence['ready_state'] in {'interactive', 'complete'}
    assert page.locator('a[href*="/video/"]').count() == 1
    assert session.active


def test_actual_chrome_search_recovers_only_same_target_with_visible_results(local_browser, monkeypatch):
    session, url = local_browser
    page = session.open_page(url)
    calls = []
    class Borrowed:
        def open_page(self, target):
            calls.append(target)
            page.goto(target, wait_until='networkidle', timeout=200)
            return page
    monkeypatch.setattr(web, 'build_douyin_search_url', lambda _: url+'/search')
    rows, issue = collect(web.DouyinWebTrendProvider(), Borrowed())
    assert len(rows) == 1 and issue == ''
    assert calls == [url+'/search']
    assert issue.navigation_evidence['target_matched']


def test_actual_chrome_identity_timeout_retains_same_document(local_browser, monkeypatch):
    from src.platform_adapter import douyin_identity as identity
    session, url = local_browser
    page = session.open_page(url)
    original = page.tab_id
    calls = []
    class Borrowed:
        def open_page(self, target):
            calls.append(target)
            page.goto(target, wait_until='networkidle', timeout=1000)
            return page
    monkeypatch.setattr(identity, 'DOUYIN_SELF_URL', url+'/identity')
    result = identity.DouyinPageIdentityVerifier().probe(Borrowed())
    assert result.public_uid == 'local-test-account'
    assert result.nickname == '测试法律号'
    assert calls == [url+'/identity'] and page.tab_id == original


@pytest.mark.parametrize('change', ['target', 'commit', 'loading', 'empty'])
def test_partial_navigation_never_uses_previous_results_or_empty_page(monkeypatch, change):
    proof = dict(target_matched=True, navigation_committed=True, ready_state='complete')
    if change == 'target': proof['target_matched'] = False
    if change == 'commit': proof['navigation_committed'] = False
    if change == 'loading': proof['ready_state'] = 'loading'
    page = SimpleNamespace(locator=lambda _:SimpleNamespace(count=lambda:0 if change=='empty' else 1))
    error = BrowserNavigationTimeout(proof)
    error.page = page
    def open_page(_): raise error
    monkeypatch.setattr(web.DouyinWebTrendProvider, '_wait_until_ready', staticmethod(lambda _:''))
    monkeypatch.setattr(web.DouyinWebTrendProvider, '_blocked_detection', staticmethod(lambda _:''))
    with pytest.raises(BrowserNavigationTimeout):
        collect(web.DouyinWebTrendProvider(), SimpleNamespace(open_page=open_page))


def test_timeout_with_challenge_preserves_human_gate_in_same_page(monkeypatch):
    error = BrowserNavigationTimeout(dict(target_matched=True, navigation_committed=True, ready_state='complete'))
    error.page = object()
    def open_page(_): raise error
    detection = web._PageDetection('verification_ui_unconfirmed', {'blocking':True,'version':3})
    monkeypatch.setattr(web.DouyinWebTrendProvider, '_wait_until_ready', staticmethod(lambda _:detection))
    rows, issue = collect(web.DouyinWebTrendProvider(), SimpleNamespace(open_page=open_page))
    assert not rows and issue == 'human_required'
    assert issue.stop_code == 'verification_ui_unconfirmed'
    assert issue.navigation_evidence['target_matched']


def test_navigation_receipt_has_no_raw_url_text_or_unknown_fields():
    proof = clean_navigation_evidence(dict(target_matched='yes', navigation_committed=True,
        ready_state='complete', url='https://secret.invalid/?token=private', body='private',
        timeout_ms=True, elapsed_ms=80, wait_until='load'))
    assert proof['target_matched'] is False and proof['navigation_committed'] is True
    assert 'private' not in json.dumps(proof) and 'url' not in proof and 'body' not in proof
    assert 'timeout_ms' not in proof


def test_page_invalid_wait_rejected_before_worker_command():
    page = Page(SimpleNamespace(cmd=lambda *a,**k:pytest.fail('invalid wait dispatched')))
    with pytest.raises(ValueError):
        page.goto('http://127.0.0.1', wait_until='anything')
