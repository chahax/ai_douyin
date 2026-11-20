"""Read current book cards and an exact book's application options only.

No search guesses, alias input, option selection, submission, chapter reading,
browser creation or task-eligibility claim. Callers supply the managed guard.
"""
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

VERSION = 'fanqie_promotion_preflight/v1'
CONTENT_URL = 'https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1'
VIEW_JS = r"""() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const text=e=>(e?.innerText||e?.textContent||'').trim();
 const books=Array.from(document.querySelectorAll('.book-hQ7GYr')).filter(visible)
  .map(c=>text(c.querySelector('.book-title-txt-_CIhYa')).slice(0,180)).filter(Boolean).slice(0,100);
 const controls=Array.from(document.querySelectorAll('input,textarea,[role=searchbox]')).filter(visible)
  .filter(e=>!['hidden','password','file'].includes((e.type||'').toLowerCase()))
  .filter(e=>!/(username|password|one-time-code)/i.test(e.getAttribute('autocomplete')||''))
  .map(e=>({type:(e.type||e.getAttribute('role')||e.tagName.toLowerCase()).slice(0,30),
    placeholder:(e.getAttribute('placeholder')||'').slice(0,120),
    aria_label:(e.getAttribute('aria-label')||'').slice(0,120),disabled:!!e.disabled}))
  .filter(e=>!/密码|验证码|手机|邮箱|登录|password|token|session|cookie|auth|phone|email/i.test(e.placeholder+' '+e.aria_label))
  .filter(e=>e.type==='search'||e.type==='searchbox'||/搜索|书名|书籍|作者|关键词|search/i.test(e.placeholder+' '+e.aria_label)).slice(0,20);
 const filters=Array.from(document.querySelectorAll('.task-menu-second .task-menu-second-item,[class*="filter-row"] button,[class*="filter-row"] label,[role=tab]'))
  .filter(visible).map(text).filter(t=>t&&t.length<=80).slice(0,80);
 return {book_titles:books,search_controls:controls,filter_buttons:[...new Set(filters)],
  visible_modal_count:Array.from(document.querySelectorAll('.arco-modal-content')).filter(visible).length};
}"""


def validate_target(book_id, book_name):
    if (not isinstance(book_id, str) or not re.fullmatch(r'[0-9]{10,24}', book_id)
            or not isinstance(book_name, str) or not book_name.strip()
            or book_name != book_name.strip() or len(book_name) > 120
            or any(ord(c) < 32 for c in book_name)):
        raise ValueError('exact_preflight_book_id_and_name_required')


def _location(page):
    u = urlsplit(page.url)
    if (u.scheme != 'https' or u.hostname != 'kol.fanqieopen.com'
            or u.port not in (None, 443) or u.username or u.password
            or u.path != '/page/content' or parse_qs(u.query).get('tab_type') != ['2']):
        raise ValueError('preflight_requires_original_novel_content_page')
    return {'origin': 'https://kol.fanqieopen.com', 'path': u.path}


def _open_js(name):
    return r"""() => {const wanted=""" + json.dumps(name, ensure_ascii=False) + r""";
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const text=e=>(e?.innerText||e?.textContent||'').trim();
 const cards=Array.from(document.querySelectorAll('.book-hQ7GYr')).filter(visible)
  .filter(c=>text(c.querySelector('.book-title-txt-_CIhYa'))===wanted);
 if(cards.length!==1)return {opened:false,reason:'exact_book_not_unique',count:cards.length};
 const buttons=Array.from(cards[0].querySelectorAll('.c-promotions button,button'))
  .filter(e=>visible(e)&&text(e)==='别名推广'&&!e.disabled);
 if(buttons.length!==1)return {opened:false,reason:'exact_alias_promotion_button_not_unique'};
 buttons[0].click();return {opened:true,entry_label:'别名推广'};}"""


def _form_js(book_id, book_name):
    from .fanqie_form_feedback_v1 import PUBLIC_FORM_HELPERS_JS
    wanted = json.dumps(book_name + '（' + book_id + '）', ensure_ascii=False)
    return r"""() => {const wanted=""" + wanted + r""",expectedID=""" + json.dumps(book_id) + ';' + PUBLIC_FORM_HELPERS_JS + r"""
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const text=e=>(e?.innerText||e?.textContent||'').trim();
 const modals=Array.from(document.querySelectorAll('.arco-modal-content')).filter(visible);
 if(modals.length!==1)return {ready:false,reason:'exact_modal_not_unique',modal_count:modals.length};
 const modal=modals[0],content=text(modal).slice(0,8192);
 const identities=Array.from(content.matchAll(/（([0-9]{10,24})）/g)).map(m=>m[1]).slice(0,10);
 const identityLines=content.split(/\r?\n/).map(line=>line.trim()).filter(line=>line===wanted);
 if(identities.length!==1||identities[0]!==expectedID||identityLines.length!==1)
  return {ready:false,reason:'modal_book_identity_mismatch',observed_book_ids:identities};
 const fields=Array.from(modal.querySelectorAll('.arco-form-item')).filter(e=>text(e.querySelector('.arco-form-item-label'))==='发文类型');
 const all=Array.from(modal.querySelectorAll('.arco-select')).filter(visible);
 const labelled=fields.length===1?Array.from(fields[0].querySelectorAll('.arco-select')).filter(visible):[];
 const selects=labelled.length===1?labelled:(fields.length===0&&all.length===1?all:[]);
 if(selects.length!==1)return {ready:false,reason:'publish_type_control_not_unique',observed_book_ids:identities};
 const public_form_inventory=fqInventory(modal);
 selects[0].click();return {ready:true,book_identity_verified:true,book_identity_line:identityLines[0],
  observed_book_ids:identities,public_form_inventory};}"""


OPTIONS_JS = r"""() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 return Array.from(document.querySelectorAll('.arco-select-option,[role=option]')).filter(visible)
  .map(e=>({text:(e.innerText||e.textContent||'').trim().slice(0,100),
   disabled:e.getAttribute('aria-disabled')==='true'||/disabled/.test(e.className)})).slice(0,50);
}"""
CLOSE_JS = r"""() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const modals=Array.from(document.querySelectorAll('.arco-modal-content')).filter(visible);
 if(modals.length!==1)return {closed:false,reason:'owned_modal_not_unique'};
 const scope=modals[0].closest('.arco-modal')||modals[0];
 const close=Array.from(scope.querySelectorAll('.arco-modal-close-icon,button[aria-label="关闭"]')).filter(visible);
 if(close.length!==1)return {closed:false,reason:'owned_close_control_not_unique'};
 close[0].click();return {closed:true};}"""
MODAL_STATE_JS = r"""() => ({visible_modal_count:Array.from(document.querySelectorAll('.arco-modal-content'))
 .filter(e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden').length})"""


def inspect_preflight(page, *, book_id, book_name, guard, checkpoint, locate=False):
    validate_target(book_id, book_name)
    if type(locate) is not bool:
        raise ValueError('explicit_exact_book_UI_search_scope_required')
    result = {'schema': VERSION, 'book_id': book_id, 'book_name': book_name,
        'status': 'book_not_in_current_view', 'preflight_passed': False,
        'promotion_submitted': False, 'promotion_task_active': False,
        'alias_filled': False, 'chapters_read': 0, 'search_executed': False,
        'platform_book_availability': None, 'modal_opened': False, 'modal_close_confirmed': None}
    def evaluate(js):
        guard(); result['page_location'] = _location(page)
        return page.evaluate(js)
    def save(stage, value):
        checkpoint(stage, value)
        result[stage] = value
        return value
    if locate:
        from .fanqie_exact_book_locator_v1 import locate_exact_book
        location = locate_exact_book(page, book_id=book_id, book_name=book_name,
            guard=guard, checkpoint=save, search_allowed=True)
        result['book_location'] = location
        result['search_executed'] = location['enter_pressed']
        view = location['view_ready']
        if location['status'] not in {'located_current_view', 'located_after_exact_search'}:
            result['status'] = location['status']
            return result
    else:
        view = save('view_initial', evaluate(VIEW_JS))
        for _ in range(5):
            if view.get('book_titles') or view.get('visible_modal_count'):
                break
            guard(); page.wait_for_timeout(250)
            view = evaluate(VIEW_JS)
        save('view_ready', view)
    if view.get('visible_modal_count'):
        result['status'] = 'existing_modal_requires_review'
        return result
    count = view.get('book_titles', []).count(book_name)
    if count != 1:
        result['status'] = 'book_not_in_current_view' if count == 0 else 'book_ambiguous_in_current_view'
        return result
    opened = save('open_card', evaluate(_open_js(book_name)))
    if not opened.get('opened'):
        result['status'] = opened.get('reason', 'book_card_unavailable')
        return result
    result['modal_opened'] = True
    try:
        guard(); page.wait_for_timeout(300)
        form = save('form', evaluate(_form_js(book_id, book_name)))
        if not form.get('ready'):
            result['status'] = form.get('reason', 'form_unavailable')
            return result
        guard(); page.wait_for_timeout(150)
        options = save('publish_types', evaluate(OPTIONS_JS))
        result['aigc_available'] = any(o.get('text') == 'AIGC' and o.get('disabled') is False for o in options)
        result['status'] = 'form_options_verified' if result['aigc_available'] else 'aigc_unavailable'
    finally:
        closed = save('close_modal', evaluate(CLOSE_JS))
        result['modal_close_origin_status'] = result['status']
        result['modal_close_observations'] = []
        result['modal_close_confirmed'] = False
        if closed.get('closed'):
            # A successful close click starts an animation, not proof of closure.
            # Observe only: the close control is never clicked a second time.
            for index in range(1, 21):
                guard(); page.wait_for_timeout(100)
                state = evaluate(MODAL_STATE_JS)
                observation = dict(index=index, waited_ms=index * 100, observed_at=time.time(),
                    original_status=result['modal_close_origin_status'], observed=state)
                save('close_observation_%02d' % index, observation)
                result['modal_close_observations'].append(observation)
                count = state.get('visible_modal_count')
                if type(count) is int and count == 0:
                    result['modal_close_confirmed'] = True
                    break
        if not result['modal_close_confirmed']:
            result['status'] = 'modal_close_unconfirmed'
    result['preflight_passed'] = result['status'] == 'form_options_verified' and result['modal_close_confirmed'] is True
    return result
