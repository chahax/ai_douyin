"""Real local DOM contract fixtures, never a claim about platform HTML.

Only synthetic HTML is rendered in an isolated D-drive Chrome profile. Fixture
frontend handlers change their own form; helper readback must stay read-only.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from src.platform_adapter.ai_content_declaration import read_ai_declaration, set_ai_declaration


@pytest.fixture(scope="module")
def browser_context(tmp_path_factory):
    profile = tmp_path_factory.mktemp("isolated_chrome_committed_row")
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(profile), channel="chrome",
            headless=True, args=["--mute-audio"])
        yield context
        context.close()


@pytest.fixture
def page(browser_context):
    page = browser_context.new_page()
    page.set_default_timeout(1500)
    yield page
    page.close()


def form(page, *, entry_tag="button", wrapper="", initial="未声明", after="",
         remove_modal=True, extra=""):
    entry = f'<{entry_tag} id="entry" ' + (
        'href="#" ' if entry_tag == "a" else "") + f'onclick="openDeclaration(); return false;">自主声明</{entry_tag}>'
    row_tag = 'span' if wrapper.startswith('<p>') else 'div'
    row = f'<{row_tag} id="setting-row">{entry}<output id="setting-value">{initial}</output></{row_tag}>'
    if wrapper:
        row = wrapper.replace("SLOT", row)
    page.set_content("""<!doctype html><meta charset="utf-8"><title>Local declaration fixture</title>
        <script>
        window.fixtureCounts={opens:0, confirms:0};
        function openDeclaration(){
            fixtureCounts.opens++;
            document.querySelector('#modal').hidden=false;
        }
        function commit(){
            fixtureCounts.confirms++;
            document.querySelector('#setting-value').textContent='内容由AI生成';
            """ + after + ("document.querySelector('#modal').remove();" if remove_modal else
                           "document.querySelector('#modal').hidden=true;") + """
        }
        </script>""" + row + extra + """
        <div id="modal" hidden>
          <h2>对作品内容添加声明</h2>
          <label><input type="radio" name="declaration">内容由AI生成</label>
          <button onclick="commit()">确定</button>
          <button onclick="document.querySelector('#modal').hidden=true">取消</button>
        </div>""")


@pytest.mark.parametrize("entry_tag", ["button", "a"])
def test_unmounted_native_radio_requires_original_same_row_value_after_unique_confirmation(page, entry_tag):
    form(page, entry_tag=entry_tag)
    assert read_ai_declaration(page)["verified"] is False
    result = set_ai_declaration(page)
    assert result == {"verified": True, "label": "内容由AI生成",
                      "method": "confirmed_original_setting_row_value"}
    assert page.locator("#modal").count() == 0
    assert page.get_by_role("radio").count() == 0
    assert read_ai_declaration(page) == result
    assert set_ai_declaration(page) == result
    assert page.evaluate("fixtureCounts") == {"opens": 1, "confirms": 1}


def test_native_hidden_original_proof_remains_the_stronger_path(page):
    form(page, remove_modal=False)
    assert set_ai_declaration(page)["method"] == "confirmed_hidden_original_control"


def test_reopening_retained_native_modal_requires_new_confirmation(page):
    form(page, remove_modal=False)
    assert set_ai_declaration(page)["method"] == "confirmed_hidden_original_control"
    page.get_by_text("自主声明", exact=True).click()
    assert read_ai_declaration(page)["verified"] is False
    page.get_by_role("button", name="取消", exact=True).click()
    assert read_ai_declaration(page)["verified"] is False


def test_rendered_row_never_overrides_retained_unchecked_native_control(page):
    form(page, remove_modal=False)
    assert set_ai_declaration(page)["method"] == "confirmed_hidden_original_control"
    page.locator('#modal input').evaluate('el => el.checked=false')
    assert page.locator('#setting-value').inner_text() == '内容由AI生成'
    assert read_ai_declaration(page)['verified'] is False


def test_matching_setting_row_without_this_invocations_confirmation_is_not_success(page):
    form(page, initial="内容由AI生成")
    assert read_ai_declaration(page)["verified"] is False
    # Existing AI-like value cannot become the newly-bound slot by opening and
    # closing a declaration; this fallback requires an actual slot transition.
    assert set_ai_declaration(page)["verified"] is False


@pytest.mark.parametrize("wrapper", [
    '<article>SLOT</article>',
    '<div role="article">SLOT</div>',
    '<div contenteditable="true">SLOT</div>',
    '<div aria-label="视频预览">SLOT</div>',
    '<section aria-label="作品简介">SLOT</section>',
    '<div aria-label="作者信息">SLOT</div>',
    '<div title="preview">SLOT</div>',
    '<p>SLOT</p>',
    '<div style="opacity:0">SLOT</div>',
])
def test_author_preview_editor_prose_or_hidden_areas_cannot_supply_a_setting_value(page, wrapper):
    form(page, wrapper=wrapper)
    # An invisible entry cannot be clicked through the actual set helper. Its
    # read remains false; visible counterexamples must complete confirmation.
    if "opacity:0" in wrapper:
        assert read_ai_declaration(page)["verified"] is False
    else:
        assert set_ai_declaration(page)["verified"] is False


@pytest.mark.parametrize("after", [
    "document.querySelector('#entry').replaceWith(document.querySelector('#entry').cloneNode(true));",
    "document.querySelector('#setting-value').replaceWith(document.querySelector('#setting-value').cloneNode(true));",
    "document.querySelector('#setting-value').setAttribute('aria-label','作者AI角标');",
    "document.querySelector('#setting-value').hidden=true;",
    "document.querySelector('#setting-row').insertAdjacentHTML('beforeend','<span>内容由AI生成</span>');",
    "document.querySelector('#setting-row').insertAdjacentHTML('beforeend','<button>作品声明</button>');",
    "document.querySelector('#setting-value').textContent='未声明'; document.body.insertAdjacentHTML('beforeend','<span>内容由AI生成</span>');",
])
def test_changed_original_slot_entry_ambiguity_and_unrelated_ai_text_fail_closed(page, after):
    form(page, after=after)
    assert set_ai_declaration(page)["verified"] is False
    assert page.evaluate("fixtureCounts.confirms") == 1


def test_clickable_plain_span_does_not_manufacture_a_semantic_setting_entry(page):
    form(page, entry_tag="span")
    assert set_ai_declaration(page)["verified"] is False
    assert page.evaluate("fixtureCounts.confirms") == 1


def test_reopened_dialog_invalidates_prior_row_proof_even_when_closed_again(page):
    form(page)
    assert set_ai_declaration(page)["verified"] is True
    page.evaluate("""document.body.insertAdjacentHTML('beforeend',
        '<div id="reopened"><h2>对作品内容添加声明</h2><span>choose again</span></div>')""")
    assert read_ai_declaration(page)["verified"] is False
    page.locator("#reopened").evaluate("el=>el.remove()")
    assert read_ai_declaration(page)["verified"] is False


def test_same_url_reload_and_another_page_cannot_reuse_prior_entry_proof(page, browser_context):
    form(page)
    assert set_ai_declaration(page)["verified"] is True
    html = page.content()
    other = browser_context.new_page()
    try:
        other.set_content(html)
        assert read_ai_declaration(other)["verified"] is False
    finally:
        other.close()
    page.set_content(html)
    assert read_ai_declaration(page)["verified"] is False


def test_navigation_away_and_back_invalidates_even_when_original_nodes_survive(page):
    form(page)
    assert set_ai_declaration(page)["verified"] is True
    # A fragment navigation preserves the document and original ElementHandles.
    original = page.url
    page.evaluate("location.hash='another-step'")
    page.wait_for_timeout(50)
    page.evaluate("history.replaceState(null,'','about:blank')")
    page.wait_for_timeout(50)
    assert page.url == original
    assert read_ai_declaration(page)["verified"] is False


def test_pending_modal_and_global_caption_badge_never_replace_row_binding(page):
    form(page, extra='<article aria-label="作品预览"><span>内容由AI生成</span></article>')
    page.get_by_text("自主声明", exact=True).click()
    page.get_by_role("radio", name="内容由AI生成").check()
    assert read_ai_declaration(page)["verified"] is False
    assert page.evaluate("fixtureCounts.confirms") == 0
