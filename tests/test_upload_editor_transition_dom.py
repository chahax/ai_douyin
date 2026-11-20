"""Ten local intercepted-route cases, with zero requests sent to the platform."""
import json
import uuid

import pytest

from src.shared import upload_check_transition as module
from test_upload_check_transition_dom import (
    HTML, UPLOAD_URL, EDITOR_URL, context, page, select_and_arm, clean)


def arm_upload(page, tmp_path):
    page.goto(UPLOAD_URL)
    fixture = tmp_path/'fixture.bin'; fixture.write_bytes(b'local nonmedia fixture')
    page.locator('#file').set_input_files(str(fixture))
    nonce = uuid.uuid4().hex
    assert module.begin_upload_check(page, nonce)['state'] == 'armed_upload'
    return nonce


def checking(page):
    page.locator('#status').evaluate("el=>el.textContent='检测中5%'")


def test_upload_parsing_diagnostics_then_one_direct_editor_document_and_stable_clean(page, tmp_path):
    nonce = arm_upload(page, tmp_path)
    page.evaluate("""document.body.insertAdjacentHTML('beforeend',
        '<section><span>文件解析中，请稍等...</span><span>0%</span><button>取消上传</button></section>')""")
    page.evaluate('history.replaceState(null,"",location.href)')
    waiting = module.observe_upload_check(page, nonce)
    assert waiting['state'] == 'armed_upload' and not waiting['checking_observed']
    assert waiting['diagnostic']['upload_ui']['cancel_upload_present']
    assert waiting['diagnostic']['upload_ui']['parsing_present']
    assert waiting['diagnostic']['upload_ui']['independent_percent_count'] == 1
    page.goto(EDITOR_URL)
    checking(page)
    bound = module.observe_upload_check(page, nonce)
    assert bound['state'] == 'checking'
    assert [row['route'] for row in bound['diagnostic']['routes']] == ['upload','upload','editor']
    assert bound['diagnostic']['editor_document_fixed'] is True
    clean(page)
    assert module.observe_upload_check(page, nonce)['verified'] is False
    assert module.observe_upload_check(page, nonce)['verified'] is True


def test_same_editor_url_event_preserving_original_document_is_allowed_only_while_armed(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    page.evaluate('history.replaceState(null,"",location.href)')
    bound = module.observe_upload_check(page, nonce)
    assert bound['state']=='checking'
    assert bound['diagnostic']['armed_document_retained'] is True
    assert bound['diagnostic']['routes'][-1]['event']=='same_route_event'
    clean(page)
    module.observe_upload_check(page, nonce)
    assert module.observe_upload_check(page, nonce)['verified'] is True


def test_same_editor_url_reload_cannot_reuse_this_selections_document(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    page.reload()
    checking(page)
    result = module.observe_upload_check(page, nonce)
    assert result['state']=='invalid' and not result['verified']
    assert result['reason']=='armed_document_replaced_or_unknown'


@pytest.mark.parametrize('departure', ['other_origin','other_path','extra_query'])
def test_leaving_and_returning_never_erases_route_history(page, tmp_path, departure):
    nonce = select_and_arm(page, tmp_path)
    if departure=='other_origin':
        page.goto('data:text/html,<title>Isolated opaque origin</title>')
        page.goto(EDITOR_URL)
    else:
        url = 'https://creator.douyin.com/creator-micro/content/manage' if departure=='other_path' else EDITOR_URL+'&other=1'
        page.evaluate('url=>history.replaceState(null,"",url)', url)
        page.evaluate('url=>history.replaceState(null,"",url)', EDITOR_URL)
    checking(page)
    result = module.observe_upload_check(page, nonce)
    assert result['state']=='invalid' and not result['verified']
    assert 'other' in [row['route'] for row in result['diagnostic']['routes']]
    assert len(result['diagnostic']['routes'])<=8


def test_formally_bound_check_rejects_same_url_same_document_navigation(page, tmp_path):
    nonce = select_and_arm(page, tmp_path)
    assert module.observe_upload_check(page, nonce)['state']=='checking'
    page.evaluate('history.replaceState(null,"",location.href)')
    clean(page)
    result = module.observe_upload_check(page, nonce)
    assert result['state']=='invalid' and result['reason']=='navigation_after_check_binding'


def test_legal_editor_route_with_only_old_clean_never_creates_a_check_witness(page, tmp_path):
    nonce = arm_upload(page, tmp_path)
    page.goto(EDITOR_URL)
    clean(page)
    first = module.observe_upload_check(page, nonce)
    assert first['state']=='armed_editor' and not first['checking_observed']
    assert module.observe_upload_check(page, nonce)['verified'] is False


def test_unobserved_multiple_editor_documents_are_ambiguous_not_qualified(page, tmp_path):
    nonce = arm_upload(page, tmp_path)
    page.goto(EDITOR_URL)
    page.reload()
    checking(page)
    result = module.observe_upload_check(page, nonce)
    assert result['state']=='invalid'
    assert result['reason']=='unobserved_document_history_ambiguous'


def test_same_url_navigation_during_bound_reupload_read_cannot_overwrite_invalid(page, tmp_path, monkeypatch):
    nonce = select_and_arm(page, tmp_path)
    assert module.observe_upload_check(page, nonce)['state']=='checking'
    clean(page)
    assert module.observe_upload_check(page, nonce)['state']=='clean_wait'
    original, calls = module._reupload, []
    def read_and_navigate(current):
        calls.append(True)
        if len(calls)==2:
            current.evaluate('history.replaceState(null,"",location.href)')
        return original(current)
    monkeypatch.setattr(module, '_reupload', read_and_navigate)
    result = module.observe_upload_check(page, nonce)
    assert len(calls)==2
    assert result['state']=='invalid' and result['reason']=='navigation_after_check_binding'
    assert not result['verified'] and result['stable_observations']==[]
