"""One full-book-name UI search on an already owned content Page.

Selectors come from the bound a722 preflight observation. No API replay,
ranking index, fuzzy title, alias input, promotion submit or cross-run cache.
Fresh post-Enter card generation is mandatory; BookID is verified by the
caller's existing exact modal gate before any alias field can be written.
"""
import json
import secrets

from .fanqie_promotion_preflight_v1 import VIEW_JS, _location, validate_target

VERSION = 'fanqie_exact_book_locator/v2'
PLACEHOLDER = '请输入作者名/书名/BookID'
TAB_SELECTOR = '.task-menu-second .task-menu-second-item:visible >> xpath=self::*[normalize-space(.)="全部内容"]'
INPUT_SELECTOR = 'input[placeholder="请输入作者名/书名/BookID"]:visible'
CONTROL_STATE_JS = r"""() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const tabs=Array.from(document.querySelectorAll('.task-menu-second .task-menu-second-item'))
  .filter(e=>visible(e)&&(e.innerText||e.textContent||'').trim()==='全部内容');
 const inputs=Array.from(document.querySelectorAll('input[placeholder="请输入作者名/书名/BookID"]')).filter(visible);
 const tab=tabs.length===1?tabs[0]:null,input=inputs.length===1?inputs[0]:null;
 return {tab_count:tabs.length,tab_usable:!!tab&&!tab.disabled&&tab.getAttribute('aria-disabled')!=='true'&&!/disabled/.test(tab.className),
  input_count:inputs.length,input_type:input?(input.type||'').toLowerCase():null,
  input_usable:!!input&&!input.disabled&&!input.readOnly&&input.getAttribute('aria-disabled')!=='true'};
}"""


def _query_state_js(query):
    return r"""() => {const wanted=""" + json.dumps(query) + r""";
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const items=Array.from(document.querySelectorAll('input[placeholder="请输入作者名/书名/BookID"]')).filter(visible);
 return {unique:items.length===1,value_matches:items.length===1&&items[0].type==='text'&&items[0].value===wanted};}"""


def _arm_search_js(token, query):
    return r"""() => { // fanqie_exact_search_arm/v2
 const token=""" + json.dumps(token) + ',query=' + json.dumps(query) + r""";
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const inputs=Array.from(document.querySelectorAll('input[placeholder="请输入作者名/书名/BookID"]')).filter(visible);
 const roots=Array.from(document.querySelectorAll('.books-YEBPOv')),shown=roots.filter(visible);
 const page_location={origin:location.origin,path:location.pathname};
 const initial={result_root_count:roots.length,visible_result_root_count:shown.length,page_location,
  search_result_id_count:document.querySelectorAll('#search-area-scroll-box.books-YEBPOv').length};
 if(inputs.length!==1||inputs[0].value!==query||roots.length>1||(roots.length===1&&shown.length!==1))
  return {armed:false,reason:'exact_result_scope_unavailable',...initial};
 window.__fqExactSearch?.dispose();
 const s={token,query,input:inputs[0],initial_root_count:roots.length,entered:false,fresh:false,revision:0};
 const read=()=>{const all=Array.from(document.querySelectorAll('.books-YEBPOv')),shown=all.filter(visible);
  const root=all.length===1&&shown.length===1?shown[0]:null,scope=root?.closest('.kol-page');
  const headers=scope?Array.from(scope.querySelectorAll('.kol-page-header-title')).filter(e=>visible(e)&&(e.textContent||'').trim()==='搜索结果'):[];
  const search_id_count=document.querySelectorAll('#search-area-scroll-box.books-YEBPOv').length;
  const search_scope_valid=!!root&&root.id==='search-area-scroll-box'&&search_id_count===1&&headers.length===1;
  const cards=root?Array.from(root.querySelectorAll('.book-hQ7GYr')).filter(visible):[];
  const titles=cards.map(c=>(c.querySelector('.book-title-txt-_CIhYa')?.textContent||'').trim());
  return {root,scope,root_count:all.length,visible_root_count:shown.length,search_id_count,
   search_header_count:headers.length,search_scope_valid,cards,titles};};
 const different=(a,b)=>!a||a.root!==b.root||a.search_scope_valid!==b.search_scope_valid||a.cards.length!==b.cards.length||a.cards.some((n,i)=>n!==b.cards[i])||JSON.stringify(a.titles)!==JSON.stringify(b.titles);
 s.observe=()=>{const now=read();if(s.entered&&different(s.last,now)&&(s.initial_root_count===1||now.search_scope_valid)){s.revision++;s.fresh=true;}s.last=now;return now;};
 const entered=e=>{if(e.key==='Enter'&&e.target===s.input&&s.input.value===s.query){s.entered=true;s.fresh=false;s.revision=0;s.last=read();}};
 document.addEventListener('keydown',entered,true);
 const observer=new MutationObserver(()=>s.observe());
 observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true});
 s.dispose=()=>{observer.disconnect();document.removeEventListener('keydown',entered,true);if(window.__fqExactSearch===s)delete window.__fqExactSearch;};
 s.last=read();window.__fqExactSearch=s;
 return {armed:true,token,...initial,baseline_titles:s.last.titles,observation_scope:'document.documentElement',
  initial_scope:roots.length?'existing_result_root':'await_observed_search_result_scope',
  search_header_count:s.last.search_header_count};
}"""


def _search_observation_js(token):
    return r"""() => { // fanqie_exact_search_observation/v2
 const token=""" + json.dumps(token) + r""",s=window.__fqExactSearch;
 if(!s||s.token!==token)return {valid:false,reason:'search_observer_not_current'};
 const now=s.observe(),inputs=Array.from(document.querySelectorAll('input[placeholder="请输入作者名/书名/BookID"]'))
  .filter(e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
 const exact_input=inputs.length===1&&inputs[0].value===s.query;
 const input_scope_verified=exact_input&&(inputs[0]===s.input||
  (s.initial_root_count===0&&now.search_scope_valid&&now.scope.contains(inputs[0])&&!s.input.isConnected));
 const view=(""" + VIEW_JS + r""")();view.book_titles=now.titles;
 return {valid:true,entered:s.entered,fresh:s.fresh,render_revision:s.revision,
  query_matches:input_scope_verified,result_root_count:now.root_count,
  visible_result_root_count:now.visible_root_count,search_result_id_count:now.search_id_count,
  search_header_count:now.search_header_count,search_scope_verified:now.search_scope_valid,
  input_replaced:exact_input&&inputs[0]!==s.input,
  page_location:{origin:location.origin,path:location.pathname},
  required_scope_ready:s.initial_root_count===1||now.search_scope_valid,view};
}"""


def _dispose_search_js(token):
    return '() => {const s=window.__fqExactSearch;if(s?.token===' + json.dumps(token) + ')s.dispose();return {disposed:true};}'


def locate_exact_book(page, *, book_id, book_name, guard, checkpoint, search_allowed):
    validate_target(book_id, book_name)
    if type(search_allowed) is not bool:
        raise ValueError('explicit_exact_book_UI_search_scope_required')
    result = dict(schema=VERSION, book_id=book_id, book_name=book_name,
        status='book_not_in_current_view', search_attempted=False,
        all_content_clicked=False, query_filled=False, enter_pressed=False,
        search_count=0, search_mode='exact_public_book_name',
        platform_book_availability=None, api_requests_issued=0,
        alias_filled=False, promotion_submitted=False,
        book_id_verification='requires_exact_modal_identity', result_freshness_verified=False)
    armed_token = None
    rpc = getattr(page, 'page', page)
    def checked():
        guard(); _location(page)
    def evaluate(js):
        checked(); return page.evaluate(js)
    def save(stage, value):
        checkpoint(stage, value);return value
    def finish(view, status):
        result['view_ready']=save('view_ready',view)
        result['status']=status
        if armed_token is not None:
            save('search_observer_disposed',evaluate(_dispose_search_js(armed_token)))
        return result
    view=save('view_initial',evaluate(VIEW_JS));result['view_initial']=view
    for _ in range(5):
        if view.get('book_titles') or view.get('visible_modal_count'):
            break
        checked();page.wait_for_timeout(250);view=evaluate(VIEW_JS)
    count=view.get('book_titles',[]).count(book_name)
    if view.get('visible_modal_count'):
        return finish(view,'existing_modal_requires_review')
    if not search_allowed:
        return finish(view,'located_current_view' if count==1 else
            'book_ambiguous_in_current_view' if count>1 else 'book_not_in_current_view')
    controls=save('search_controls_before',evaluate(CONTROL_STATE_JS))
    if (controls.get('tab_count') not in (0,1)
            or (controls.get('tab_count')==1 and controls.get('tab_usable') is not True)
            or controls.get('input_count')!=1 or controls.get('input_type')!='text'
            or controls.get('input_usable') is not True):
        return finish(view,'exact_search_controls_unavailable')
    if controls.get('tab_count')==1:
        checked();tab=rpc.locator(TAB_SELECTOR)
        if tab.count()!=1 or tab.inner_text().strip()!='全部内容':
            return finish(view,'exact_all_content_tab_not_unique')
        checked();tab.click(timeout=5000);result['all_content_clicked']=True
        save('all_content_clicked',{'clicked':True,'label':'全部内容'})
    # React may recreate/disable the input during a normal tab transition.
    for _ in range(5):
        checked();page.wait_for_timeout(100)
        controls=evaluate(CONTROL_STATE_JS)
        if (controls.get('input_count')==1 and controls.get('input_type')=='text'
                and controls.get('input_usable') is True):
            break
    save('search_controls_after',controls)
    if (controls.get('input_count')!=1 or controls.get('input_type')!='text'
            or controls.get('input_usable') is not True):
        return finish(view,'exact_search_input_unavailable_after_tab')
    checked();search=rpc.locator(INPUT_SELECTOR)
    if search.count()!=1:
        return finish(view,'exact_search_input_not_unique')
    result['search_attempted']=True
    checked();search.fill(book_name);result['query_filled']=True
    query=save('search_query_confirmed',evaluate(_query_state_js(book_name)))
    if query.get('unique') is not True or query.get('value_matches') is not True:
        return finish(view,'exact_search_query_not_confirmed')
    token=secrets.token_hex(16)
    armed=save('search_observer_armed',evaluate(_arm_search_js(token,book_name)))
    if armed.get('armed') is not True:
        return finish(view,'exact_result_scope_unavailable')
    armed_token=token
    checked();search.press('Enter');result['enter_pressed']=True;result['search_count']=1
    save('search_entered',{'key':'Enter','count':1,'query_kind':'public_expected_book_name'})
    stable_key=None;stable_reads=0;fresh_seen=False
    for index in range(1,21):
        checked();page.wait_for_timeout(250)
        observed=save('search_observation_%02d'%index,evaluate(_search_observation_js(token)))
        result['search_freshness']=observed
        if (observed.get('valid') is not True or observed.get('entered') is not True
                or observed.get('query_matches') is not True or observed.get('result_root_count')!=1
                or observed.get('required_scope_ready') is False):
            stable_reads=0;continue
        view=observed.get('view') or {}
        if view.get('visible_modal_count'):
            return finish(view,'unexpected_modal_after_search')
        if observed.get('fresh') is not True:
            stable_reads=0;continue
        fresh_seen=True
        key=(observed.get('render_revision'),tuple(view.get('book_titles',[])))
        stable_reads=stable_reads+1 if key==stable_key else 1;stable_key=key
        if stable_reads<2:continue
        result['result_freshness_verified']=True
        count=view.get('book_titles',[]).count(book_name)
        if count==1:
            return finish(view,'located_after_exact_search')
        if count>1:
            return finish(view,'book_ambiguous_in_current_view')
    return finish(view,'book_not_in_current_view' if fresh_seen else 'search_results_not_fresh')
