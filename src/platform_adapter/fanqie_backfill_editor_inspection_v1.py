"""Open the observed native backfill editor without entering or submitting data.

Only the original dedicated owner may call this adapter.  A fresh exact alias
detail and its retained public link are checked before one opener click.  The
returned projection is evidence for a later adapter, never an append approval.
"""
import json
from .fanqie_filled_details_controls_v2 import (
    _PUBLIC_DOM, _target, BODY_JS, inspect_filled_details_controls,
)


class BackfillEditorNotConfirmed(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise BackfillEditorNotConfirmed(reason)


def opener_script(target, retained_url):
    return '() => {' + _PUBLIC_DOM + r'''
 if(!allowed())return {eligible:false,reason:'origin'};
 const target=TARGET,retained=RETAINED;
 const publicText=e=>text(e).replace(/https?:\/\/[^\s<>"']+/g,s=>{const u=publicUrl(s);return u?u.origin+u.path:'[url omitted]'});
 const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&text(e)==='回填发文');
 const button=buttons.length===1?buttons[0]:null;let scope=null;
 if(button)for(let p=button.parentElement,d=0;p&&d<14&&!p.matches('body,html');p=p.parentElement,d++){
   const t=text(p);
   if(t.includes('推广计划')&&t.includes('基础信息')&&t.includes(target.book_name)&&t.includes(target.alias)&&t.includes('AIGC')&&t.includes('发文链接')&&t.includes(retained)) {scope=p;break;}}
 const editable=scope?[...scope.querySelectorAll('input:not([type="hidden"]),textarea,select,[contenteditable="true"]')].filter(visible):[];
 const all=scope?[...scope.querySelectorAll('button')].filter(visible):[];
 return {schema:'fanqie_backfill_editor_opener/v1',location:{origin:location.origin,path:location.pathname},
   eligible:!!scope&&buttons.length===1&&button.type==='button'&&!button.disabled&&getComputedStyle(button).pointerEvents!=='none'&&editable.length===0,
   button_count:buttons.length,button:button?meta(button):null,scope:scope?{tag:scope.tagName.toLowerCase(),class_name:(scope.getAttribute('class')||'').slice(0,300),visible_text:publicText(scope).slice(0,12000)}:null,
   visible_editable_count:editable.length,scope_buttons:all.map(meta),retained_link_observed:!!scope,
   values_entered:false,submission_dispatched:false,append_capability_verified:false};
 }'''.replace('TARGET', json.dumps(target, ensure_ascii=False)).replace('RETAINED', json.dumps(retained_url))


def editor_script(target):
    return '() => {' + _PUBLIC_DOM + r'''
 if(!allowed())return {schema:'fanqie_backfill_editor_projection/v1',blocked:true};
 const target=TARGET;
 const publicText=e=>text(e).replace(/https?:\/\/[^\s<>"']+/g,s=>{const u=publicUrl(s);return u?u.origin+u.path:'[url omitted]'});
 const candidates=[...document.querySelectorAll('[role="dialog"],.arco-modal,.arco-drawer')].filter(e=>visible(e)&&text(e).includes(target.book_name)&&text(e).includes(target.alias));
 const minimal=candidates.filter(e=>!candidates.some(other=>other!==e&&e.contains(other))),scope=minimal.length===1?minimal[0]:null;
 const inputs=scope?[...scope.querySelectorAll('input:not([type="hidden"]):not([type="password"]),textarea,select')].filter(visible):[];
 const safeValue=e=>{if(e.type==='file')return {value_read:false};
   const v=String(e.value||'');if(!v)return {value_read:true,public_value:''};
   const u=publicUrl(v);if(u&&['https://www.douyin.com','https://douyin.com'].includes(u.origin)&&/^\/video\/\d+\/?$/.test(u.path))return {value_read:true,public_value:u.origin+u.path};
   if(/^\d{4}[-./]\d{1,2}[-./]\d{1,2}$/.test(v))return {value_read:true,public_value:v};
   return {value_read:false,value_omitted:true};};
 return {schema:'fanqie_backfill_editor_projection/v1',location:{origin:location.origin,path:location.pathname},
   surfaces:candidates.slice(0,10).map(e=>({tag:e.tagName.toLowerCase(),role:e.getAttribute('role'),class_name:(e.getAttribute('class')||'').slice(0,300),visible_text:publicText(e).slice(0,16000)})),
   exact_editor_scope_count:minimal.length,
   inputs:inputs.slice(0,80).map((e,index)=>({index,tag:e.tagName.toLowerCase(),type:e.type||'',placeholder:e.getAttribute('placeholder')||'',
     disabled:e.disabled===true,read_only:e.readOnly===true,class_name:(e.getAttribute('class')||'').slice(0,300),...safeValue(e)})),
   buttons:[...document.querySelectorAll('button')].filter(visible).slice(0,80).map(meta),
   truncated:candidates.length>10||inputs.length>80,private_values_returned:false,
   fields_written:false,files_selected:false,submission_dispatched:false,append_capability_verified:false};
 }'''.replace('TARGET',json.dumps(target,ensure_ascii=False))


def inspect_open_editor_from_details(page, *, book_id, book_name, alias,
                                     retained_url, guard, checkpoint):
    target = _target(book_id, book_name, alias)
    need(retained_url.startswith('https://www.douyin.com/video/')
         and retained_url.removeprefix('https://www.douyin.com/video/').isdigit(), 'canonical_retained_link_required')
    original, tab = getattr(page, '_session', None), getattr(page, 'tab_id', None)

    def rpc(method, *args, **kwargs):
        guard()
        need(getattr(page, '_session', None) is original and getattr(page, 'tab_id', None) == tab, 'original_page_changed')
        value = method(*args, **kwargs)
        guard()
        return value

    def save(stage, value):
        guard(); checkpoint(stage, value); guard()

    script = opener_script(target, retained_url)
    proof = rpc(page.evaluate, script)
    save('editor_opener_before', proof)
    if proof.get('eligible') is not True:
        return dict(schema='fanqie_backfill_editor_inspection/v1', status='opener_not_confirmed',
                    target=target, opener_clicks=0, append_capability_verified=False, submitted=False)
    before = rpc(page.evaluate, BODY_JS)
    save('editor_body_before', before)
    save('editor_open_intent', dict(target=target, retained_url=retained_url,
                                  opener=proof, opener_click_limit=1, data_entry_allowed=False))
    need(rpc(page.evaluate, script) == proof, 'editor_opener_changed_at_boundary')
    # Exact text is selected through XPath, so the toolbar's 批量回填发文
    # cannot be dispatched even if the site's layout changes.
    button = page.locator('button:visible >> xpath=self::*[normalize-space(.)="回填发文"]')
    need(rpc(button.count) == 1, 'editor_opener_not_unique')
    rpc(button.click, timeout=8000)
    samples, previous, stable = [], None, 0
    for _ in range(10):
        body, controls = rpc(page.evaluate, BODY_JS), rpc(page.evaluate, editor_script(target))
        samples.append(dict(body=body, controls=controls))
        signature = json.dumps(samples[-1], ensure_ascii=False, sort_keys=True)
        stable = stable + 1 if signature == previous else 1
        previous = signature
        if stable >= 2:
            break
        rpc(page.wait_for_timeout, 200)
    save('editor_observation', dict(target=target, samples=samples, opener_clicks=1))
    return dict(schema='fanqie_backfill_editor_inspection/v1', status='editor_controls_observed',
                target=target, opener_clicks=1, observation=samples[-1], stable=stable >= 2,
                fields_written=False, files_selected=False, submitted=False, deleted=False,
                append_capability_verified=False, old_ledger_changed=False)


def inspect_backfill_editor(page, *, book_id, book_name, alias, retained_url, guard, checkpoint):
    details = inspect_filled_details_controls(page, book_id=book_id, book_name=book_name,
                                             alias=alias, guard=guard, checkpoint=checkpoint)
    checkpoint('editor_details_receipt', details)
    if details.get('status') != 'visible_change_observed':
        return dict(schema='fanqie_backfill_editor_inspection/v1', status='details_not_confirmed',
                    details=details, opener_clicks=0, submitted=False, append_capability_verified=False)
    return inspect_open_editor_from_details(page, book_id=book_id, book_name=book_name,
        alias=alias, retained_url=retained_url, guard=guard, checkpoint=checkpoint)
