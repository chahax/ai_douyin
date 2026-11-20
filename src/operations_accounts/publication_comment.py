"""One authorized explanatory comment on an exact, verified published work.

Browser UI only. A durable claim precedes the sole submit click; uncertainty
retains that claim. No automatic retry or synthetic content approval.
"""
import hashlib
import json
import time
from pathlib import Path

from src.platform_adapter.publish_verification import video_id

WORKSPACE = Path(__file__).resolve().parents[2]

_SCOPED_EDITOR_JS=r"""scope=>{
  const visible=n=>n.isConnected&&getComputedStyle(n).visibility!=='hidden'&&n.getBoundingClientRect().width>80&&n.getBoundingClientRect().height>18;
  scope.querySelectorAll('[data-account-playback-comment-editor]').forEach(n=>n.removeAttribute('data-account-playback-comment-editor'));
  const selectors=['[data-e2e="comment-input"] [contenteditable="true"]','[data-e2e="comment-input"] textarea',
    '.comment-input-container [contenteditable="true"]','div[contenteditable="true"][aria-label*="评论"]','div[contenteditable="true"][data-placeholder*="评论"]'];
  const lists=scope.querySelectorAll('[data-e2e="comment-list"]'),panel=lists.length===1?lists[0].parentElement:null;
  const drafts=panel&&panel!==scope&&scope.contains(panel)?Array.from(panel.querySelectorAll('div.public-DraftEditor-content[role="combobox"][contenteditable="true"]'))
    .filter(n=>!lists[0].contains(n)&&!n.closest('form,[data-e2e="comment-item"],[data-e2e="comment-content"],[data-e2e="detail-video-info"],h1')):[];
  const candidates=Array.from(new Set(selectors.flatMap(s=>Array.from(scope.querySelectorAll(s))).concat(drafts)))
    .filter(n=>visible(n)&&!n.disabled&&!n.closest('[inert],[aria-disabled=true],[disabled]'));
  const mountedEditors=Array.from(scope.querySelectorAll('textarea,[contenteditable]:not([contenteditable=false]),[role=textbox]')).filter(visible);
  if(candidates.length!==1||mountedEditors.length>1){
    const shown=n=>n.isConnected&&getComputedStyle(n).visibility!=='hidden'&&n.getBoundingClientRect().width>0&&n.getBoundingClientRect().height>0;
    const clean=s=>String(s||'').replace(/https?:\/\/\S+/gi,'[url]').replace(/\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*\S+/gi,'[redacted]').replace(/\s+/g,' ').trim().slice(0,80);
    const shape=n=>{const r=n.getBoundingClientRect(),style=getComputedStyle(n),inViewport=r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;
      const hit=inViewport?document.elementFromPoint(r.x+r.width/2,r.y+r.height/2):null;
      return {tag:n.tagName,role:clean(n.getAttribute('role')),
      class_tokens:Array.from(n.classList).filter(c=>/^[A-Za-z_-][A-Za-z0-9_-]{0,63}$/.test(c)&&!/(token|password|authorization|cookie|session)/i.test(c)).slice(0,8),
      data_e2e:clean(n.getAttribute('data-e2e')),aria_label:clean(n.getAttribute('aria-label')),placeholder:clean(n.getAttribute('placeholder')),
      data_placeholder:clean(n.getAttribute('data-placeholder')),contenteditable:['true','false','plaintext-only',''].includes(n.getAttribute('contenteditable'))?n.getAttribute('contenteditable'):null,
      in_detail:scope.contains(n),in_dialog:!!n.closest('[role=dialog],dialog'),visible:!!shown(n),
      disabled:!!n.disabled||n.getAttribute('aria-disabled')==='true',inert:!!n.closest('[inert]'),
      width:Math.round(r.width),height:Math.round(r.height),in_viewport:inViewport,cursor_pointer:style.cursor==='pointer',
      pointer_events:style.pointerEvents==='none'?'none':'enabled',hit_self_or_descendant:!!hit&&(hit===n||n.contains(hit))};};
    const allEditors=Array.from(document.querySelectorAll('textarea,[contenteditable]:not([contenteditable=false]),[role=textbox],input[placeholder*="评论"]'));
    const editors=allEditors.filter(shown);
    const named=n=>{if(!n.matches('button,[role=button],[role=tab]')||n.querySelector('input,textarea,[contenteditable]'))return '';
      const text=(n.innerText||'').trim();return /^(评论(?:\s*[（(]?\d+[)）]?)?|写评论|发表评论|查看评论|展开评论|发送|发布)$/.test(text)?text:'';};
    const controls=Array.from(document.querySelectorAll('button,[role=button],[role=tab],[data-e2e],[aria-label]')).filter(n=>shown(n)&&
      !n.closest('input,textarea,[contenteditable]')&&(/comment/i.test(n.getAttribute('data-e2e')||'')||(n.getAttribute('aria-label')||'').includes('评论')||named(n)));
    const firstPrompts=Array.from(scope.querySelectorAll('div,span,p')).slice(0,2000).filter(n=>!n.children.length&&shown(n)&&!n.closest('[contenteditable]')&&n.innerText.trim()==='抢首评').slice(0,4);
    const seeds=Array.from(new Set(editors.filter(n=>scope.contains(n)).concat(editors.filter(n=>!scope.contains(n)),firstPrompts,controls.filter(n=>scope.contains(n)),controls.filter(n=>!scope.contains(n)))));
    const loginNames=['登录后评论','登录后发表评论','登录后即可评论','登录后发评论','登录'];
    const loginLeaves=Array.from(document.querySelectorAll('div,span,p,button,a')).slice(0,4000)
      .filter(n=>!n.children.length&&shown(n)&&!n.closest('input,textarea,[contenteditable]'));
    const pageLogin={},detailLogin={};for(const name of loginNames){const matching=loginLeaves.filter(n=>n.innerText.trim()===name);
      pageLogin[name]=Math.min(25,matching.length);detailLogin[name]=Math.min(25,matching.filter(n=>scope.contains(n)).length);}
    const items=seeds.slice(0,12).map(n=>{const ancestors=[];for(let el=n,depth=0;el&&depth<3;el=el.parentElement,depth++){
      if(el.matches('body,html'))break;const children=Array.from(el.children);ancestors.push({...shape(el),depth,children:children.slice(0,8).map(shape),children_truncated:children.length>8});}
      return {...shape(n),kind:editors.includes(n)?'editor':firstPrompts.includes(n)?'first_comment_prompt':'comment_control',fixed_control_text:firstPrompts.includes(n)?'抢首评':named(n),ancestors};});
    return {found:false,candidates:candidates.length,diagnostic:{schema:'scoped_comment_editor_diagnostic/v1',
      page_editor_nodes:Math.min(25,allEditors.length),page_visible_editors:Math.min(25,editors.length),
      detail_editor_nodes:Math.min(25,allEditors.filter(n=>scope.contains(n)).length),detail_visible_editors:Math.min(25,editors.filter(n=>scope.contains(n)).length),
      outside_dialog_visible_editors:Math.min(25,editors.filter(n=>!scope.contains(n)&&n.closest('[role=dialog],dialog')).length),
      page_visible_login_marker_counts:pageLogin,detail_visible_login_marker_counts:detailLogin,
      candidates:items,candidates_truncated:seeds.length>12}};
  }
  candidates[0].setAttribute('data-account-playback-comment-editor','1');return {found:true};
}"""

_SCOPED_SUBMIT_JS=r"""scope=>{
  const visible=n=>n.isConnected&&getComputedStyle(n).visibility!=='hidden'&&n.getBoundingClientRect().width>8&&n.getBoundingClientRect().height>8;
  scope.querySelectorAll('[data-account-playback-comment-submit]').forEach(n=>n.removeAttribute('data-account-playback-comment-submit'));
  const editors=scope.querySelectorAll('[data-account-playback-comment-editor="1"]');if(editors.length!==1)return false;
  if(editors[0].matches('div.public-DraftEditor-content[role="combobox"][contenteditable="true"]')){
    const lists=scope.querySelectorAll('[data-e2e="comment-list"]'),panel=lists.length===1?lists[0].parentElement:null;
    const clean=s=>String(s||'').replace(/https?:\/\/\S+/gi,'[url]').replace(/\s+/g,' ').slice(0,80);
    const shape=n=>{const r=n.getBoundingClientRect(),style=getComputedStyle(n),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      return {tag:n.tagName,role:clean(n.getAttribute('role')),data_e2e:clean(n.getAttribute('data-e2e')),
        class_tokens:Array.from(n.classList).filter(c=>/^[A-Za-z_-][A-Za-z0-9_-]{0,63}$/.test(c)&&!/(token|password|authorization|cookie|session)/i.test(c)).slice(0,6),
        fixed_text:/^(发送|发布)$/.test((n.innerText||'').trim())?n.innerText.trim():null,
        visible:!!visible(n),disabled:!!n.disabled||!!n.closest('[disabled],[aria-disabled=true],[inert]'),
        width:Math.round(r.width),height:Math.round(r.height),in_viewport:r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
        cursor_pointer:style.cursor==='pointer',hit_self_or_descendant:!!hit&&(hit===n||n.contains(hit)),pointer_enabled:style.pointerEvents!=='none'};};
    const iconDiagnostic=()=>{
      if(!panel||panel===scope||!scope.contains(panel)||!panel.contains(editors[0])||lists.length!==1||lists[0].contains(editors[0]))return {reason:'panel_unbound',candidates:[]};
      const safe=s=>clean(s).replace(/\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*\S+/gi,'[redacted]');
      const iconShape=n=>{
        const result={...shape(n),aria_label:safe(n.getAttribute('aria-label')),title:safe(n.getAttribute('title')),data_icon:safe(n.getAttribute('data-icon'))};
        if(n.tagName.toLowerCase()==='svg'){
          const paths=Array.from(n.querySelectorAll('path')),uses=Array.from(n.querySelectorAll('use'));
          result.svg={view_box:safe(n.getAttribute('viewBox')),width:safe(n.getAttribute('width')),height:safe(n.getAttribute('height')),
            title:safe(Array.from(n.children).find(c=>c.tagName.toLowerCase()==='title')?.textContent),
            paths:paths.slice(0,4).map(p=>{const d=p.getAttribute('d')||'';return {d_length:d.length,
              d:/^[MmZzLlHhVvCcSsQqTtAa0-9eE+.,\s-]*$/.test(d)?d.slice(0,1024):null,d_truncated:d.length>1024};}),paths_truncated:paths.length>4,
            uses:uses.slice(0,4).map(u=>{const href=u.getAttribute('href')||u.getAttribute('xlink:href')||'';
              return {fragment:/^#[A-Za-z_][A-Za-z0-9_.:-]{0,79}$/.test(href)?href:null,non_fragment_omitted:!!href&&!href.startsWith('#')};}),uses_truncated:uses.length>4};
        }
        return result;
      };
      const all=Array.from(new Set(Array.from(panel.querySelectorAll('svg')).concat(Array.from(panel.querySelectorAll('button,[role="button"],[role="img"],[data-icon]')))));
      const seeds=all.slice(0,2000).filter(n=>{const r=n.getBoundingClientRect();return n.isConnected&&getComputedStyle(n).visibility!=='hidden'&&r.width>0&&r.height>0&&
        !lists[0].contains(n)&&!n.closest('form,[contenteditable=true],[data-e2e="comment-item"],[data-e2e="comment-content"],[data-e2e="comment-item-content"],[data-e2e="detail-video-info"],h1');});
      return {schema:'scoped_draft_submit_icon_diagnostic/v1',candidates:seeds.slice(0,12).map(n=>{
        const ancestors=[];for(let parent=n.parentElement,depth=1;parent&&depth<=2&&panel.contains(parent);parent=parent.parentElement,depth++){
          ancestors.push({...iconShape(parent),depth});if(parent===panel)break;}
        return {...iconShape(n),ancestors};}),truncated:seeds.length>12||all.length>2000};
    };
    const reject=(reason,nodes=[])=>({found:false,diagnostic:{schema:'scoped_draft_submit_diagnostic/v1',reason,
      comment_list_count:lists.length,candidates:nodes.slice(0,12).map(shape),truncated:nodes.length>12,icons:iconDiagnostic()}});
    if(!panel||panel===scope||!scope.contains(panel)||!panel.contains(editors[0])||lists[0].contains(editors[0]))return reject('editor_panel_unbound');
    const allNodes=Array.from(panel.querySelectorAll('button,[role="button"],[data-e2e="comment-submit"],div,span'));
    if(allNodes.length>2000)return reject('panel_truncated');
    const nodes=allNodes
      .filter(n=>!lists[0].contains(n)&&!n.closest('form,[contenteditable=true],[data-e2e="comment-item"],[data-e2e="comment-content"],[data-e2e="comment-item-content"],[data-e2e="detail-video-info"],h1')&&
        (/^(发送|发布)$/.test((n.innerText||n.getAttribute('aria-label')||'').trim())||n.matches('[data-e2e="comment-submit"]'))&&
        (n.matches('button,[role="button"],[data-e2e="comment-submit"]')||(!n.children.length&&!n.getAttribute('role')&&!n.closest('button,[role="button"],[data-e2e="comment-submit"]'))));
    const candidates=nodes.filter(n=>{const v=shape(n);return v.visible&&!v.disabled&&v.in_viewport&&v.hit_self_or_descendant&&v.pointer_enabled&&
      (n.matches('button,[role="button"],[data-e2e="comment-submit"]')||v.cursor_pointer)});
    if(nodes.length===0&&candidates.length===0){
      const nativeSignature={"schema":"observed_comment_send_svg/20261019/gen28","view_box":"0 0 36 36","width":"36","height":"36","paths":["M17.5 30C23.851 30 29 24.851 29 18.5S23.851 7 17.5 7 6 12.149 6 18.5 11.149 30 17.5 30zm-5.16-13.883a1.16 1.16 0 0 0 1.64 1.64l2.395-2.394v8.838a1.16 1.16 0 0 0 2.321 0v-8.839l1.028 1.028 1.368 1.368a1.16 1.16 0 1 0 1.64-1.641l-4.219-4.22a1.382 1.382 0 0 0-1.954 0l-4.22 4.22h.001z","M12.34 16.117a1.16 1.16 0 0 0 1.64 1.64l2.395-2.394v8.838a1.16 1.16 0 0 0 2.321 0v-8.839l1.028 1.028 1.368 1.368a1.16 1.16 0 1 0 1.64-1.641l-4.219-4.22a1.382 1.382 0 0 0-1.954 0l-4.22 4.22h.001z"]};
      const icons=Array.from(panel.querySelectorAll('svg'));
      if(icons.length>2000)return reject('native_icon_population_truncated');
      const matches=icons.filter(svg=>{
        if(lists[0].contains(svg)||svg.closest('form,[contenteditable=true],[data-e2e="comment-item"],[data-e2e="comment-content"],[data-e2e="comment-item-content"],[data-e2e="detail-video-info"],h1'))return false;
        const paths=Array.from(svg.querySelectorAll('path'));
        return svg.getAttribute('viewBox')===nativeSignature.view_box&&svg.getAttribute('width')===nativeSignature.width&&
          svg.getAttribute('height')===nativeSignature.height&&paths.length===2&&svg.querySelectorAll('use').length===0&&
          paths.every((path,index)=>path.getAttribute('d')===nativeSignature.paths[index]);
      });
      if(matches.length!==1)return reject('native_send_signature_not_unique');
      const svg=matches[0],control=svg.parentElement,group=control?.parentElement;
      const active=document.activeElement,editor=editors[0];
      const operable=n=>{const v=shape(n);return v.visible&&!v.disabled&&v.in_viewport&&v.cursor_pointer&&v.hit_self_or_descendant&&v.pointer_enabled;};
      if(!control||control.tagName!=='SPAN'||control.children.length!==1||control.querySelectorAll('svg').length!==1||
        !group||group.tagName!=='DIV'||!panel.contains(group)||lists[0].contains(control)||
        control.closest('form,[contenteditable=true],[data-e2e="comment-item"],[data-e2e="comment-content"],[data-e2e="comment-item-content"],[data-e2e="detail-video-info"],h1')||
        (active!==editor&&!editor.contains(active))||!operable(svg)||!operable(control)||
        Array.from(group.querySelectorAll('svg')).filter(visible).length!==3)return reject('native_send_control_unusable');
      control.setAttribute('data-account-playback-comment-submit','1');
      return {found:true,source:'observed_native_send_svg',signature:nativeSignature.schema};
    }
    if(candidates.length!==1)return reject('submit_not_unique_or_usable',nodes);
    candidates[0].setAttribute('data-account-playback-comment-submit','1');return {found:true};
  }
  const area=editors[0].closest('[data-e2e="comment-input"],.comment-input-container')||editors[0].parentElement?.parentElement;
  if(!area||!scope.contains(area))return false;
  const buttons=Array.from(area.querySelectorAll('button,[role="button"]')).filter(n=>/^(发送|发布)$/.test((n.innerText||n.getAttribute('aria-label')||'').trim()));
  const candidates=Array.from(new Set(buttons.concat(Array.from(scope.querySelectorAll('[data-e2e="comment-submit"]')))))
    .filter(n=>visible(n)&&!n.disabled&&!n.closest('[inert],[aria-disabled=true]'));
  if(candidates.length!==1)return false;candidates[0].setAttribute('data-account-playback-comment-submit','1');return true;
}"""

_SCROLL_COMMENT_LIST_JS=r"""(el,postId)=>{
  const detail=el.closest('[data-e2e="video-detail"]'),players=detail?.querySelectorAll('[data-e2e="player-container"]');
  const url=new URL(location.href),r=el.getBoundingClientRect();
  if(url.protocol!=='https:'||!['www.douyin.com','douyin.com'].includes(url.host)||url.pathname!=='/video/'+postId||
    document.querySelectorAll('[data-e2e="video-detail"]').length!==1||!detail||players.length!==1||!players[0].classList.contains('video_'+postId)||
    detail.querySelectorAll('[data-e2e="comment-list"]').length!==1||!el.isConnected||el.ownerDocument!==document||
    el.closest('form,[inert],[contenteditable=true]')||getComputedStyle(el).visibility==='hidden'||r.width<=0||r.height<=0)return {scrolled:false,reason:'comment_list_identity_invalid'};
  el.scrollIntoView({behavior:'instant',block:'center',inline:'nearest'});
  return {scrolled:true};
}"""


_COMMENT_ACTIVATION_JS=r"""(el,arg)=>{
  const stamp={url:location.href,time_origin:performance.timeOrigin};
  const reject=reason=>({qualified:false,reason,document:stamp});
  const detail=el.closest('[data-e2e="video-detail"]'),url=new URL(location.href);
  if(url.protocol!=='https:'||!['www.douyin.com','douyin.com'].includes(url.host)||url.pathname!=='/video/'+arg.id||
    document.querySelectorAll('[data-e2e="video-detail"]').length!==1||!detail||!el.isConnected||el.ownerDocument!==document)return reject('document_or_scope');
  const players=detail.querySelectorAll('[data-e2e="player-container"]'),lists=detail.querySelectorAll('[data-e2e="comment-list"]');
  if(players.length!==1||!players[0].classList.contains('video_'+arg.id)||lists.length!==1)return reject('work_or_list_identity');
  if(el.children.length||el.innerText.trim()!==arg.text||
    el.closest('form,button,a,input,textarea,[contenteditable=true],[role=textbox],[inert],[aria-disabled=true],[disabled],[data-e2e="comment-item"],[data-e2e="comment-content"],[data-e2e="comment-item-content"],[data-e2e="detail-video-info"],h1'))return reject('not_activation_leaf');
  if(arg.kind==='placeholder'&&(!lists[0].parentElement.contains(el)||lists[0].contains(el)))return reject('outside_comment_panel');
  if(arg.kind==='first_comment'&&el.tagName!=='SPAN')return reject('not_observed_prompt');
  const r=el.getBoundingClientRect(),style=getComputedStyle(el);
  if(style.visibility==='hidden'||style.display==='none'||style.pointerEvents==='none'||r.width<=0||r.height<=0||
    r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight)return reject('not_in_viewport');
  if(arg.kind==='first_comment'&&style.cursor!=='pointer')return reject('not_pointer');
  const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
  if(hit!==el&&!el.contains(hit))return reject('occluded');
  const editors=Array.from(detail.querySelectorAll('textarea,[contenteditable]:not([contenteditable=false]),[role=textbox]'))
    .filter(n=>{const r=n.getBoundingClientRect();return n.isConnected&&getComputedStyle(n).visibility!=='hidden'&&r.width>80&&r.height>18});
  if(editors.length)return reject(editors.length>1?'multiple_editors':'editor_already_mounted');
  return {qualified:true,kind:arg.kind,document:stamp};
}"""


def _activate_scoped_comment_editor(page,scoped_selector,post_id,title,tags,guard,deadline,before_evidence=None):
    """Open the observed input shell once; this never submits a comment."""
    from src.shared.published_work_scope import inspect_observed_public_work
    result={'attempted':False,'qualified':False,'candidates':[]}
    def checked():
        if callable(guard):guard()
        return inspect_observed_public_work(page,str(post_id),title,required_hashtags=tags)
    before=before_evidence or checked()
    if not before.get('verified'):
        return dict(result,terminal_status='human_required'if before.get('human_required')else'work_scope_unverified',scope_evidence=before)
    options=[('placeholder','留下你的精彩评论吧',scoped_selector+' :is(div,section):has(> [data-e2e="comment-list"]) :is(span,div,p):text-is("留下你的精彩评论吧"):not(:has(*))'),
             ('first_comment','抢首评',scoped_selector+' span:text-is("抢首评"):not(:has(*))')]
    for kind,text,selector in options:
        target=page.locator(selector);count=target.count()
        result['candidates'].append({'kind':kind,'count':min(25,count)})
        if count>1:return dict(result,reason='activation_not_unique')
        if count!=1:continue
        script='el=>('+_COMMENT_ACTIVATION_JS+')(el,'+json.dumps({'id':str(post_id),'text':text,'kind':kind},ensure_ascii=False)+')'
        qualification=target.evaluate(script)
        result['candidates'][-1]['reason']=qualification.get('reason')
        if not qualification.get('qualified'):
            if qualification.get('reason')in('multiple_editors','editor_already_mounted'):return dict(result,reason=qualification['reason'])
            continue
        # A second full proof and leaf read fence asynchronous navigation/rendering.
        final=checked();again=target.evaluate(script)
        if not final.get('verified')or not again.get('qualified')or again.get('document')!=qualification.get('document'):
            return dict(result,terminal_status='human_required'if final.get('human_required')else'work_scope_unverified',reason='before_activation_identity_changed',scope_evidence=final)
        remaining=deadline-time.monotonic()
        if remaining<=0:return dict(result,reason='time_limit')
        result.update(attempted=True,qualified=True,kind=kind)
        try:
            if callable(guard):guard()
            target.click(timeout=min(5000,max(1,int(remaining*1000))))
        except Exception as exc:return dict(result,reason='activation_click_unknown',error_type=type(exc).__name__)
        after=checked()
        stamp=page.evaluate('()=>({url:location.href,time_origin:performance.timeOrigin})')
        if not after.get('verified')or stamp!=qualification.get('document'):
            return dict(result,terminal_status='human_required'if after.get('human_required')else'work_scope_unverified',reason='after_activation_identity_changed',scope_evidence=after)
        return dict(result,reason='activation_dispatched')
    return dict(result,reason='no_qualified_activation')


def _wait_scoped_comment_editor(page,scope,scoped_selector,post_id,title,tags,guard):
    from src.shared.published_work_scope import inspect_observed_public_work
    started=time.monotonic();observations=[];scrolled=False;activation=None;marker={'found':False}
    def finish(status=None,reason=None,evidence=None):
        if status or reason=='time_limit':marker['found']=False
        marker['editor_wait']={'reads':len(observations),'elapsed_seconds':round(time.monotonic()-started,3),
            'scroll_attempted':scrolled,'activation':activation,'observations':observations,'reason':reason or('found'if marker.get('found')else'read_limit')}
        if status:marker.update(terminal_status=status,scope_evidence=evidence)
        return marker
    for index in range(8):
        if time.monotonic()-started>=20:return finish(reason='time_limit')
        if callable(guard):guard()
        checked=inspect_observed_public_work(page,str(post_id),title,required_hashtags=tags)
        if not checked.get('verified'):
            return finish('human_required'if checked.get('human_required')else'work_scope_unverified','identity_changed',checked)
        marker=scope.evaluate(_SCOPED_EDITOR_JS)or{'found':False}
        observations.append({'found':marker.get('found')is True,'qualifying_editors':marker.get('candidates',1 if marker.get('found')else 0),
            'detail_visible_editors':(marker.get('diagnostic')or{}).get('detail_visible_editors')})
        if time.monotonic()-started>=20:return finish(reason='time_limit')
        if marker.get('found'):return finish()
        if marker.get('candidates',0)>=2 or(marker.get('diagnostic')or{}).get('detail_visible_editors',0)>=2:
            return finish(reason='multiple_editors')
        lists=page.locator(scoped_selector+' [data-e2e="comment-list"]')
        count=lists.count()
        if count>1:return finish(reason='comment_list_not_unique')
        if not scrolled and count==1:
            if callable(guard):guard()
            before=inspect_observed_public_work(page,str(post_id),title,required_hashtags=tags)
            if not before.get('verified'):
                return finish('human_required'if before.get('human_required')else'work_scope_unverified','before_scroll_identity_changed',before)
            scrolled=True
            try:
                outcome=lists.evaluate('el=>('+_SCROLL_COMMENT_LIST_JS+')(el,'+json.dumps(str(post_id))+')')
            except Exception as exc:return finish('work_scope_unverified','scroll_unknown',{'error_type':type(exc).__name__})
            after=inspect_observed_public_work(page,str(post_id),title,required_hashtags=tags)
            if not outcome.get('scrolled')or not after.get('verified'):
                return finish('human_required'if after.get('human_required')else'work_scope_unverified','after_scroll_identity_changed',after)
            if callable(guard):guard()
            checked=after
        if scrolled and activation is None:
            activation=_activate_scoped_comment_editor(page,scoped_selector,post_id,title,tags,guard,started+20,before_evidence=checked)
            if activation.get('terminal_status'):
                return finish(activation['terminal_status'],activation.get('reason'),activation.get('scope_evidence'))
            if activation.get('reason')in('activation_click_unknown','activation_not_unique','multiple_editors'):
                return finish(reason=activation['reason'])
            # No second trigger choice/click in subsequent reads, even if activation is unknown.
            if activation.get('reason')=='activation_dispatched':continue
        if index<7:page.wait_for_timeout(min(2000,max(1,int((20-(time.monotonic()-started))*1000))))
    return finish()


def _wait_observed_comment_work(page,post_id,title,tags,guard):
    from src.shared.published_work_scope import inspect_observed_public_work
    started=time.monotonic();result={'verified':False}
    for index in range(8):
        if time.monotonic()-started>=20:break
        if callable(guard):guard()
        result=inspect_observed_public_work(page,post_id,title,required_hashtags=tags)
        if callable(guard):guard()
        if time.monotonic()-started>=20:return dict(result,verified=False,reason='comment_verification_timeout')
        if result.get('verified')or result.get('human_required')or result.get('moderation_markers'):break
        if index<7:page.wait_for_timeout(min(2000,max(1,int((20-(time.monotonic()-started))*1000))))
    return result


def post_authorized_publication_comment(adapter, frozen_command, post_id, *, receipt_dir=None):
    text = str(frozen_command.get('comment') or '').strip()
    context = adapter.runtime_context
    evidence = frozen_command.get('publish_evidence') or {}
    if (not context or not text or not frozen_command.get('authorization')
            or frozen_command.get('account_key') != context.account_key
            or frozen_command.get('account_uuid') != context.account_uuid
            or evidence.get('verified') is not True
            or str(evidence.get('expected_post_id') or evidence.get('post_id') or '') != str(post_id)):
        raise ValueError('Comment requires explicit authorization, exact account and verified published work')
    url = f'https://www.douyin.com/video/{post_id}'
    if video_id(url) != str(post_id):
        raise ValueError('Comment requires an exact numeric video ID')
    identity = {'account_uuid': context.account_uuid, 'post_id': str(post_id),
                'comment_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    root = Path(receipt_dir or WORKSPACE / 'data/publish_comments').resolve()
    if not root.is_relative_to(WORKSPACE):
        raise ValueError('Comment receipts must remain in the workspace')
    root.mkdir(parents=True, exist_ok=True)
    claim, receipt = root / f'{key}.submitted.json', root / f'{key}.receipt.json'
    if claim.exists():
        if receipt.exists():
            prior = json.loads(receipt.read_text(encoding='utf-8'))
            if prior.get('identity') != identity:
                raise ValueError('Comment receipt identity mismatch')
            return prior
        return {'status': 'outcome_unknown', 'identity': identity, 'submission_lock_retained': True}

    editor_wait_evidence=None;submit_control_evidence=None
    def persist(status, **details):
        value = {'schema': 'authorized_publication_comment/v1', 'identity': identity,
                 'post_url': url, 'comment': text, 'status': status,
                 'submission_lock_retained': claim.exists(), **details}
        if editor_wait_evidence is not None:value['editor_wait']=editor_wait_evidence
        if submit_control_evidence is not None:value['submit_control']=submit_control_evidence
        temporary = receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(receipt)
        return value

    if adapter._require_runtime_identity(force=True) is not None:
        return persist('identity_unverified', submitted=False)
    page = adapter.session.open_page(url)
    if video_id(page.url) != str(post_id):
        return persist('wrong_work', submitted=False)
    title=frozen_command.get('title');tags=frozen_command.get('hashtags')
    frozen_bound=isinstance(title,str)and bool(title)and isinstance(tags,list)and evidence.get('expected_title')==title and evidence.get('expected_hashtags')==tags
    article_count=page.locator('article').count()
    observed=page.locator('[data-e2e="video-detail"]').count()>0 or(article_count==0 and frozen_bound)
    detail_selector='[data-e2e="video-detail"]'
    guard=getattr(adapter.session,'_guard',None)
    if observed:
        if not frozen_bound:
            return persist('work_scope_unverified',submitted=False,reason='frozen_title_or_hashtags_not_bound')
        checked=_wait_observed_comment_work(page,str(post_id),title,tags,guard)
        if not checked.get('verified'):
            return persist('human_required'if checked.get('human_required')else'work_scope_unverified',submitted=False,scope_evidence=checked)
    elif article_count != 1:
        return persist('work_scope_unverified', submitted=False)
    # Markers operate only on visible UI. No API or direct posting request.
    from src.platform_adapter.douyin_playback import _MARK_COMMENT_EDITOR_JS, _MARK_COMMENT_SUBMIT_JS
    seen_script = """() => Array.from(document.querySelectorAll('[data-e2e="comment-item"]'))
      .filter(n => n.getBoundingClientRect().width > 0 && n.getBoundingClientRect().height > 0)
      .map(n => ({text:(n.querySelector('[data-e2e="comment-content"], [data-e2e="comment-item-content"]')?.innerText || '').trim(),
                 id:n.getAttribute('data-comment-id') || n.querySelector('[id^="tooltip_"]')?.id || null}))"""
    scoped_selector=detail_selector+f':has([data-e2e="player-container"].video_{post_id})'
    scope=page.locator(scoped_selector if observed else'body')
    if observed:seen_script=seen_script.replace('() =>','scope =>').replace('document.querySelectorAll','scope.querySelectorAll')
    before = scope.evaluate(seen_script) or []
    if any(item.get('text') == text for item in before):
        return persist('matching_comment_already_visible', submitted=False, ownership_verified=False)
    marker = (_wait_scoped_comment_editor(page,scope,scoped_selector,post_id,title,tags,guard)if observed
              else scope.evaluate(_MARK_COMMENT_EDITOR_JS))or{}
    editor_wait_evidence=marker.get('editor_wait')if observed else None
    if not marker.get('found'):
        ui_details={}
        if observed and marker.get('terminal_status','comment_editor_unavailable')=='comment_editor_unavailable':
            ui_path=root/f'{key}.comment-ui.png'
            try:
                if callable(guard):guard()
                if callable(getattr(page,'screenshot',None)):page.screenshot(path=str(ui_path),full_page=False)
                else:page._cmd('screenshot',path=str(ui_path),full_page=False)
                ui_details['ui_evidence_path']=str(ui_path)
            except Exception as exc:ui_details['ui_evidence_error_type']=type(exc).__name__
        return persist(marker.get('terminal_status','comment_editor_unavailable'), submitted=False,
            **({'scope_diagnostic':marker.get('diagnostic'),'editor_wait':marker.get('editor_wait'),'scope_evidence':marker.get('scope_evidence'),**ui_details}if observed else{}))
    prefix=scoped_selector+' 'if observed else''
    editor = page.locator(prefix+'[data-account-playback-comment-editor="1"]')
    if observed and editor.count()!=1:return persist('comment_editor_unavailable',submitted=False)
    editor.fill(text)
    if observed:
        from src.shared.published_work_scope import read_observed_work_scope
        after_fill=read_observed_work_scope(page,str(post_id),title)
        if not after_fill.get('verified')or editor.count()!=1:
            return persist('human_required'if after_fill.get('human_required')else'work_scope_unverified',submitted=False,scope_evidence=after_fill)
    value = editor.evaluate("n => (n.value || n.innerText || '').trim()")
    if value != text:
        return persist('comment_text_unverified', submitted=False)
    submit_marker=scope.evaluate(_SCOPED_SUBMIT_JS if observed else _MARK_COMMENT_SUBMIT_JS)
    if not(submit_marker.get('found')if isinstance(submit_marker,dict)else submit_marker):
        ui_details={}
        if observed:
            ui_path=root/f'{key}.comment-ui.png'
            try:
                if callable(guard):guard()
                if callable(getattr(page,'screenshot',None)):page.screenshot(path=str(ui_path),full_page=False)
                else:page._cmd('screenshot',path=str(ui_path),full_page=False)
                ui_details['ui_evidence_path']=str(ui_path)
            except Exception as exc:ui_details['ui_evidence_error_type']=type(exc).__name__
        return persist('comment_submit_unavailable', submitted=False,
            **({'submit_diagnostic':submit_marker.get('diagnostic')}if isinstance(submit_marker,dict)else{}),**ui_details)
    if isinstance(submit_marker,dict)and submit_marker.get('source')=='observed_native_send_svg':
        submit_control_evidence={key:submit_marker[key]for key in('source','signature')}
    if video_id(page.url) != str(post_id):
        return persist('wrong_work', submitted=False)
    if observed:
        from src.shared.published_work_scope import inspect_observed_public_work
        if callable(guard):guard()
        final=inspect_observed_public_work(page,str(post_id),title,required_hashtags=tags)
        if not final.get('verified')or editor.count()!=1 or editor.evaluate("n => (n.value || n.innerText || '').trim()")!=text or page.locator(prefix+'[data-account-playback-comment-submit="1"]').count()!=1:
            return persist('human_required'if final.get('human_required')else'work_scope_unverified',submitted=False,scope_evidence=final)
        if callable(guard):guard()
    # Exclusive creation also protects two callers racing after their UI reads.
    try:
        with claim.open('x', encoding='utf-8') as handle:
            json.dump({'identity': identity, 'status': 'submission_started'}, handle)
    except FileExistsError:
        return {'status': 'outcome_unknown', 'identity': identity, 'submission_lock_retained': True}
    try:
        page.locator(prefix+'[data-account-playback-comment-submit="1"]').click()
        page.wait_for_timeout(1200)
        after = scope.evaluate(seen_script) or []
        matched = [item for item in after if item.get('text') == text]
        if observed and matched:
            from src.shared.published_work_scope import read_observed_work_scope
            if not read_observed_work_scope(page,str(post_id),title).get('verified'):
                return persist('outcome_unknown',submitted=None,reason='work identity changed after sole submit')
        if matched and video_id(page.url) == str(post_id):
            return persist('sent_visible', submitted=True, visible_comment=matched[0],
                           verification='new exact text visible after sole submit; not independent author identity proof')
        return persist('outcome_unknown', submitted=None, reason='submit result not visibly confirmed')
    except Exception as exc:
        return persist('outcome_unknown', submitted=None, error_type=type(exc).__name__)
