"""Twelve decisive local Chrome DOM cases; no platform or media inspection."""
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from playwright.sync_api import sync_playwright

from src.shared.upload_check_transition import begin_upload_check, observe_upload_check
from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.platform_adapter.publish_workflow import PublishWorkflow
from src.platform_adapter import browser_session as browser_module

UPLOAD_URL = 'https://creator.douyin.com/creator-micro/content/upload'
EDITOR_URL = 'https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page'


HTML = """<!doctype html><meta charset="utf-8"><title>Local upload UI fixture</title>
<input id="file" type="file">
<button id="reupload">重新上传</button>
<section id="check"><h2>快速检测</h2><span id="status">等待选择</span></section>
<footer>点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。</footer>
"""


@pytest.fixture(scope='module')
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp('native_upload_ui')
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(root), channel='chrome', headless=True,
            args=['--mute-audio'])
        yield context
        context.close()


@pytest.fixture
def page(context):
    page = context.new_page()
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML)
        if route.request.url in (UPLOAD_URL, EDITOR_URL) else route.abort())
    page.goto(EDITOR_URL)
    yield page
    page.close()


def select_and_arm(page, tmp_path, *, checking=True):
    # The fixture input's actual change handler creates the UI checking state.
    # Helper never reads file values or bytes.
    if checking:
        page.evaluate("document.querySelector('#file').onchange=()=>document.querySelector('#status').textContent='检测中5%'")
    fixture = tmp_path/'selection.bin'
    fixture.write_bytes(b'isolated non-media fixture')
    page.locator('#file').set_input_files(str(fixture))
    nonce = uuid.uuid4().hex
    assert begin_upload_check(page, nonce)['state'] == 'armed_editor'
    return nonce


def clean(page):
    page.locator('#status').evaluate("el => el.textContent='作品未见异常'")


def test_fast_check_then_two_stable_original_node_observations(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    assert observe_upload_check(page, nonce)['state'] == 'checking'
    clean(page)
    assert observe_upload_check(page, nonce)['verified'] is False
    result = observe_upload_check(page, nonce)
    assert result['verified'] and len(result['stable_observations']) == 2
    assert result['selection_nonce'] == nonce


def test_old_stable_clean_draft_cannot_create_this_selections_check_witness(page, tmp_path):
    clean(page)
    nonce = select_and_arm(page, tmp_path, checking=False)
    assert not any(observe_upload_check(page, nonce)['verified'] for _ in range(3))


@pytest.mark.parametrize('area', ['footer', 'description'])
def test_matching_text_in_footer_or_editable_description_cannot_bind_checking(page, tmp_path, area):
    page.evaluate("""area => {
        const holder=document.createElement(area==='footer'?'footer':'div');
        if(area==='description') {holder.contentEditable='true';holder.setAttribute('aria-label','作品描述');}
        document.body.append(holder);holder.append(document.querySelector('#check'));
    }""", area)
    nonce = select_and_arm(page, tmp_path)
    assert observe_upload_check(page, nonce)['checking_observed'] is False
    clean(page)
    assert observe_upload_check(page, nonce)['verified'] is False


def test_current_transport_cannot_pass_even_with_clean_check_node(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    assert observe_upload_check(page, nonce)['checking_observed']
    clean(page)
    page.evaluate("document.body.insertAdjacentHTML('beforeend','<div>正在上传</div>')")
    assert observe_upload_check(page, nonce)['state'] == 'invalid'


def test_truncated_ui_never_creates_a_positive_witness(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    page.evaluate("""() => {const div=document.createElement('div');
        for(let i=0;i<5002;i++) div.append(document.createTextNode('x'), document.createElement('br'));
        document.body.append(div);} """)
    assert observe_upload_check(page, nonce)['state'] == 'invalid'


@pytest.mark.parametrize('node', ['check', 'status', 'reupload'])
def test_replacing_original_check_container_status_or_reupload_never_rebinds(page, tmp_path, node):
    nonce = select_and_arm(page, tmp_path)
    assert observe_upload_check(page, nonce)['checking_observed']
    clean(page)
    page.locator('#'+node).evaluate('el=>el.replaceWith(el.cloneNode(true))')
    assert observe_upload_check(page, nonce)['state'] == 'invalid'
    assert observe_upload_check(page, nonce)['verified'] is False


def test_navigation_away_and_back_invalidates_same_url_and_surviving_nodes(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    assert observe_upload_check(page, nonce)['checking_observed']
    original = page.url
    page.evaluate("location.hash='temporary'")
    page.wait_for_timeout(30)
    page.evaluate('history.replaceState(null,"",'+json.dumps(EDITOR_URL)+')')
    assert page.url == original
    clean(page)
    assert observe_upload_check(page, nonce)['state'] == 'invalid'


def test_new_check_after_first_clean_breaks_the_original_transition(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    observe_upload_check(page, nonce)
    clean(page)
    assert observe_upload_check(page, nonce)['state'] == 'clean_wait'
    page.locator('#status').evaluate("el => el.textContent='检测中1%'")
    assert observe_upload_check(page, nonce)['state'] == 'invalid'
    clean(page)
    assert observe_upload_check(page, nonce)['verified'] is False


def intercept_test_worker(monkeypatch, owner):
    # Test-only bootstrap: install a route on the real isolated Chrome context,
    # fulfill precisely two known creator URLs from this local HTML, abort all
    # other requests. Production worker and public browser API are unchanged.
    prefix = "import sys\nsys.path[:0]=" + repr(owner._child_python_paths()) + "\n"
    prefix += 'import playwright.sync_api as _fixture_api\n_fixture_actual_sync=_fixture_api.sync_playwright\n'
    prefix += '_fixture_html=' + repr(HTML) + '\n_fixture_urls=' + repr((UPLOAD_URL, EDITOR_URL)) + '\n'
    prefix += '''
class _FixtureManager:
    def start(self):
        actual=_fixture_actual_sync().start()
        class Chromium:
            def launch_persistent_context(self, **kwargs):
                context=actual.chromium.launch_persistent_context(**kwargs)
                def route_fixture(route):
                    if route.request.url in _fixture_urls:
                        route.fulfill(status=200, content_type='text/html', body=_fixture_html)
                    else:
                        route.abort()
                context.route('**/*',route_fixture)
                return context
        class Started:
            chromium=Chromium()
            def stop(self): actual.stop()
        return Started()
_fixture_api.sync_playwright=lambda:_FixtureManager()
'''
    monkeypatch.setattr(browser_module, '_PW_SCRIPT', prefix + browser_module._PW_SCRIPT)


def test_actual_worker_rpc_workflow_uses_this_successful_file_selection_and_original_page(tmp_path, monkeypatch):
    owner = BrowserSession(BrowserSessionConfig('http://127.0.0.1', 'http://127.0.0.1',
        str(tmp_path/'state.json'), str(tmp_path/'rpc_profile'), headless=True, timeout_ms=5000))
    try:
        intercept_test_worker(monkeypatch, owner)
        page = owner.get_page()
        page.goto(EDITOR_URL)
        page.evaluate("""document.querySelector('#file').onchange=()=>{
            document.querySelector('#status').textContent='检测中5%';
        }""")
        fixture = tmp_path/'local_fixture.bin'; fixture.write_bytes(b'no media content')
        workflow = PublishWorkflow(owner)
        workflow._journal_path = tmp_path/'local_attempt.jsonl'
        workflow._capture_upload_diagnostic = lambda *_a, **_kw: True
        workflow._upload_video_file(page, str(fixture))
        page.evaluate("setTimeout(()=>document.querySelector('#status').textContent='作品未见异常',1000)")
        assert workflow._wait_for_upload_complete(page, timeout=12)
        rows = [json.loads(line) for line in workflow._journal_path.read_text(encoding='utf-8').splitlines()]
        verified = next(row for row in rows if row['stage']=='upload_completion_verified')
        assert verified['method']=='original_check_nodes_then_stable_clean'
        assert len(verified['proof']['stable_observations']) == 2
        assert verified['selection_nonce'] == workflow._upload_fast_selection[2]
        # Borrowing another native page cannot reuse this worker-held nonce.
        other = owner.new_tab('unrelated-local-page')
        assert other.upload_check_proof('observe', verified['selection_nonce'])['verified'] is False
    finally:
        owner.stop()
