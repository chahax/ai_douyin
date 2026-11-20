"""Host-side, rendered-UI-only creator-card locator over the existing Page RPC.

It discovers a native URL; it never declares publication/review quality clear.
The caller must retain the original identity, detail verification and settlement.
"""
import hashlib
import json
import uuid
from urllib.parse import urlsplit

from .published_work_discovery import canonical_video, is_manage_url, _native_modal_id
from .published_work_scope import read_observed_work_scope

SCOPE_FIELDS = ('account_uuid', 'owner_id', 'generation', 'command_id', 'tab_id')
MAX_POLLS = 8

# Actual classes and four operations observed in SAMPLE_03/299fa4b2. Status is
# captured independently, because "流量减少" does not mean "已发布" or clear.
_BIND_JS = r'''arg=>{
 const visible=e=>!!(e&&e.isConnected&&e.ownerDocument===document&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
 const norm=s=>String(s||'').normalize('NFKC').replace(/\s+/g,' ').trim().replace(/\s*\|\s*/g,'|');
 const result={schema:'original_work_card_binding/v1',ready:false,review_status_evaluated:false};
 const bad=reason=>({...result,reason});
 const u=new URL(location.href);
 if(u.origin!=='https://creator.douyin.com'||u.pathname!=='/creator-micro/content/manage'||
   !['','?enter_from=publish'].includes(u.search)||u.hash)return bad('manage_route_invalid');
 const challenge=['安全验证','请完成验证','请完成下列验证','请完成安全验证','拖动滑块完成拼图'];
 const all=Array.from(document.querySelectorAll('div,span,p'));
 if(all.length>4000)return bad('card_scan_truncated');
 if(all.some(e=>visible(e)&&!e.children.length&&challenge.includes(e.innerText.trim())))return {...bad('native_challenge_visible'),human_required:true};
 const matches=all.filter(e=>visible(e)&&!e.children.length&&!e.closest('form,input,textarea,[contenteditable=true],nav,header,footer,aside')&&
   (norm(e.innerText)===norm(arg.title)||norm(e.innerText).startsWith(norm(arg.title)+' '+norm('剧情虚构，非真实事件。'))));
 result.title_candidates=matches.length;
 if(matches.length!==1)return bad(matches.length?'title_not_unique':'title_candidate_missing');
 const label=matches[0],card=label.closest('.video-card-content-Xt386b'),wrapper=card?.parentElement;
 if(!card||card.tagName!=='DIV'||!visible(card)||!wrapper?.classList.contains('video-card-sfaSzz')||
   wrapper.querySelectorAll('.video-card-content-Xt386b').length!==1||wrapper.querySelectorAll('*').length>160||
   card.closest('form,[inert],[contenteditable=true]'))return bad('independent_card_unbound');
 if(Array.from(card.querySelectorAll('article,li,[role=article],[role=listitem],.video-card-content-Xt386b,.video-card-sfaSzz')).some(e=>!e.contains(label)))return bad('foreign_work_in_card');
 const leaves=Array.from(card.querySelectorAll('div,span')).filter(e=>visible(e)&&!e.children.length);
 if(!['编辑作品','设置权限','作品置顶','删除作品'].every(text=>leaves.filter(e=>e.innerText.trim()===text).length===1))return bad('operation_shell_unbound');
 const status=Array.from(card.querySelectorAll('.info-status-QukAhD')).filter(visible);
 if(status.length!==1||status[0].innerText.length>100)return bad('card_status_not_unique');
 result.card_status=status[0].innerText.trim();
 result.restriction_warning=result.card_status==='流量减少'?{visible:true,text:'流量减少',meaning:'platform_distribution_restriction_not_review_clear'}:null;
 const restriction=Array.from(card.querySelectorAll('.notpass-info-upwAoZ')).filter(e=>visible(e)&&e.innerText.trim()==='查看详情');
 result.restriction_detail_available=restriction.length===1;
 const covers=Array.from(card.querySelectorAll('div')).filter(e=>Array.from(e.classList).some(c=>/^video-card-cover-[A-Za-z0-9_-]+$/.test(c)));
 if(covers.length!==1)return bad('cover_not_unique');
 const cover=covers[0],has=prefix=>Array.from(cover.querySelectorAll('div')).some(e=>Array.from(e.classList).some(c=>c.startsWith(prefix)));
 if(!visible(cover)||!has('video-card-top-')||!has('video-card-bottom-')||cover.contains(label)||cover.closest('form,[inert],[contenteditable=true],[aria-disabled=true]')||
   cover.disabled||/编辑|删除|发布|权限|置顶|统计/.test(cover.innerText)||cover.querySelector('a,button,input,[role=button]'))return bad('cover_is_not_view_only');
 const r=cover.getBoundingClientRect(),s=getComputedStyle(cover),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
 if(s.cursor!=='pointer'||s.pointerEvents==='none'||r.width<=0||r.height<=0||r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight||!hit||!(hit===cover||cover.contains(hit)))return bad('cover_not_interactable');
 const key='__originalWorkLocatorV1';
 if(arg.phase==='arm'){
   const previous=window[key];
   if(previous?.click_dispatched)return bad('detail_click_already_dispatched');
   if(previous&&previous.nonce!==arg.nonce)return bad('existing_card_binding_requires_new_page');
   window[key]={nonce:arg.nonce,document,card,cover,label,title:arg.title,scope_digest:arg.scope_digest,click_dispatched:false,event_rejected:false};
   cover.setAttribute('data-original-work-locator',arg.nonce);
   // A capture gate prevents React replacement/clone between the final RPC
   // check and the native click from reaching any platform click handler.
   const record=window[key];
   const gate=event=>{
     const target=event.target?.closest?.('[data-original-work-locator="'+arg.nonce+'"]');
     if(!target)return;
     const text=norm(record.label.innerText);
     const sameTitle=text===norm(record.title)||text.startsWith(norm(record.title)+' '+norm('剧情虚构，非真实事件。'));
     const pure=visible(record.cover)&&visible(record.card)&&record.card.parentElement===wrapper&&
       !record.cover.closest('form,[inert],[contenteditable=true],[aria-disabled=true]')&&!record.cover.disabled&&
       !record.cover.querySelector('a,button,input,[role=button]')&&!/编辑|删除|发布|权限|置顶|统计/.test(record.cover.innerText)&&
       !event.target.closest('a,button,input,[role=button]')&&
       getComputedStyle(record.cover).cursor==='pointer'&&getComputedStyle(record.cover).pointerEvents!=='none'&&
       wrapper.querySelectorAll('.video-card-content-Xt386b').length===1&&wrapper.querySelectorAll('*').length<=160&&
       ['编辑作品','设置权限','作品置顶','删除作品'].every(text=>Array.from(record.card.querySelectorAll('div,span')).filter(e=>visible(e)&&!e.children.length&&e.innerText.trim()===text).length===1);
     if(target!==record.cover||!record.card.isConnected||!record.label.isConnected||!record.cover.isConnected||
       !record.card.contains(record.label)||!record.card.contains(record.cover)||record.document!==document||!sameTitle||!pure){
       event.preventDefault();event.stopImmediatePropagation();record.event_rejected=true;
     }
   };
   for(const name of ['pointerdown','mousedown','mouseup','click'])document.addEventListener(name,gate,true);
 }else{
   const record=window[key];
   if(!record||record.nonce!==arg.nonce||record.document!==document||record.card!==card||record.cover!==cover||record.label!==label||
     record.title!==arg.title||record.scope_digest!==arg.scope_digest||record.click_dispatched||cover.getAttribute('data-original-work-locator')!==arg.nonce)return bad('bound_card_or_document_changed');
   if(arg.phase==='claim')record.click_dispatched=true;
 }
 return {...result,ready:true,reason:'exact_title_and_view_only_cover_bound'};
}'''

_SURFACE_JS = r'''()=>{
 const visible=e=>e.isConnected&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const markers=['安全验证','请完成验证','请完成下列验证','请完成安全验证','拖动滑块完成拼图','登录后观看','登录后可查看','请先登录'];
 const nodes=Array.from(document.querySelectorAll('div,span,p')).slice(0,4000);
 return {url:location.href,ready:document.readyState!=='loading',human_required:nodes.some(e=>visible(e)&&!e.children.length&&markers.includes(e.innerText.trim()))};
}'''


def _evaluate(page, js, arg=None):
    return page.evaluate('(' + js + ')(' + (json.dumps(arg, ensure_ascii=False) if arg is not None else '') + ')')


def _scope(scope, page):
    if (not isinstance(scope, dict) or set(scope) != set(SCOPE_FIELDS)
            or type(scope['generation']) is not int or scope['generation'] < 1
            or any(not isinstance(scope[k], str) or not scope[k] for k in SCOPE_FIELDS if k != 'generation')
            or getattr(page, 'tab_id', None) != scope['tab_id']):
        raise ValueError('exact_managed_page_scope_required')


def discover_original_work(page, title, *, guard, scope, popup_access=None):
    """Discover over RPC; ``popup_access`` supplies guarded snapshot/page/close.

    Snapshot rows are {tab_id,url,closed}; only the unique tab created by our
    single cover click may be inspected/closed. No worker Python import/reload.
    """
    guard(); _scope(scope, page)
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError('exact_original_title_required')
    result = dict(schema='published_work_discovery/v1', verified=False, post_id='', publish_url='',
                  diagnostic={'locator':'host_rpc_original_work/v1','scope':dict(scope),
                              'review_status_evaluated':False,'cover_click_dispatched':False})
    def reject(reason):
        return dict(result, reason=reason)
    surface = _evaluate(page, _SURFACE_JS)
    if not is_manage_url(surface.get('url', '')):return reject('manage_route_or_title_invalid')
    if surface.get('human_required'):return dict(reject('native_challenge_visible'), human_required=True)
    if popup_access is None:return reject('popup_observation_capability_missing')
    nonce = uuid.uuid4().hex
    scope_digest = hashlib.sha256(json.dumps(scope,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    argument = dict(title=title,nonce=nonce,scope_digest=scope_digest,phase='arm')
    bound = _evaluate(page, _BIND_JS, argument)
    result['diagnostic']['card_binding'] = bound
    result['restriction_warning'] = bound.get('restriction_warning')
    if not bound.get('ready'):return dict(reject(bound.get('reason','card_unbound')),human_required=bound.get('human_required',False))
    guard()
    before = popup_access.snapshot()
    before_ids = {row['tab_id'] for row in before}
    selector = '[data-original-work-locator="' + nonce + '"]'
    if page.locator(selector).count() != 1:return reject('bound_cover_not_unique')
    # Last check runs on the same element that Locator.click will resolve. The
    # DOM record keeps object identity: a React replacement cannot borrow it.
    argument['phase'] = 'claim'
    claim = page.locator(selector).evaluate('(el)=>{const r=(' + _BIND_JS + ')(' + json.dumps(argument,ensure_ascii=False)
        + ');return {...r,same_target:window.__originalWorkLocatorV1?.cover===el};}')
    if not claim.get('ready') or claim.get('same_target') is not True:return reject('bound_card_or_document_changed')
    guard()
    result['diagnostic']['cover_click_dispatched'] = True
    try:page.locator(selector).click(timeout=5000)
    except Exception as exc:
        result['diagnostic']['click_error_type']=type(exc).__name__
        return reject('observed_cover_click_result_unknown')
    if page.evaluate('()=>window.__originalWorkLocatorV1?.event_rejected===true'):
        return reject('bound_card_or_document_changed')
    page.wait_for_timeout(250); guard()
    after = popup_access.snapshot()
    additions = [row for row in after if not row.get('closed') and row['tab_id'] not in before_ids]
    result['diagnostic']['new_popup_count'] = len(additions)
    if len(additions)!=1:return reject('detail_pages_ambiguous' if additions else 'detail_popup_missing')
    original_surface = _evaluate(page,_SURFACE_JS)
    if original_surface.get('human_required'):return dict(reject('observed_cover_human_required'),human_required=True)
    if not is_manage_url(original_surface.get('url','')):return reject('original_manage_route_changed')
    popup_id = additions[0]['tab_id']
    target = popup_access.page(popup_id)
    if popup_id and getattr(target,'tab_id',None)!=popup_id:return reject('popup_page_scope_changed')
    keep_popup = False
    try:
        for _ in range(MAX_POLLS):
            guard(); current = _evaluate(target, _SURFACE_JS)
            if current.get('human_required'):
                keep_popup=True
                return dict(reject('observed_cover_human_required'),human_required=True)
            url = current.get('url','')
            canonical = canonical_video(url)
            if canonical and current.get('ready'):
                result.update(verified=True,post_id=canonical.rsplit('/',1)[1],publish_url=canonical,
                              reason='exact_title_card_native_canonical_id')
                return result  # Original core still verifies title/player/review.
            modal_id = _native_modal_id(url)
            if modal_id and current.get('ready'):
                canonical = 'https://www.douyin.com/video/' + modal_id
                guard()
                try:target.goto(canonical,wait_until='domcontentloaded',timeout=6000)
                except Exception as exc:
                    result['diagnostic']['canonical_navigation_error_type']=type(exc).__name__
                    return reject('canonical_navigation_unknown')
                for _ in range(MAX_POLLS):
                    guard(); state=_evaluate(target,_SURFACE_JS)
                    if state.get('human_required'):
                        keep_popup=True
                        return dict(reject('observed_cover_human_required'),human_required=True)
                    if canonical_video(state.get('url',''))!=canonical:return reject('canonical_route_changed')
                    identity=read_observed_work_scope(target,modal_id,title)
                    result['diagnostic']['native_modal_identity']={k:v for k,v in identity.items() if k!='caption_text'}
                    if identity.get('human_required'):
                        keep_popup=True
                        return dict(reject('observed_cover_human_required'),human_required=True)
                    if identity.get('verified'):
                        result.update(verified=True,post_id=modal_id,publish_url=canonical,reason='original_native_modal_id_and_caption')
                        return result
                    target.wait_for_timeout(500)
                return reject('canonical_identity_unverified')
            parsed=urlsplit(url)
            if parsed.scheme not in {'http','https','about'} or (parsed.scheme in {'http','https'} and parsed.netloc not in {'creator.douyin.com','www.douyin.com','douyin.com'}):
                return reject('detail_origin_unexpected')
            target.wait_for_timeout(500)
        return reject('observed_cover_exact_url_not_unique')
    finally:
        if popup_id and not keep_popup:
            guard()
            popup_access.close(popup_id)

