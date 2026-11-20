"""Native rendered creator-card discovery only; no posting or platform API."""
import re
import time
from urllib.parse import urlsplit,parse_qsl
from weakref import WeakKeyDictionary

_DETAIL_CLICKS=WeakKeyDictionary()

_COVER_BIND_JS=r"""(label,arg)=>{
    const visible=el=>el&&el.isConnected&&el.ownerDocument===document&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
    const normalize=s=>s.normalize('NFKC').replace(/\s+/g,' ').trim().replace(/\s*\|\s*/g,'|');
    const text=normalize(label.innerText),title=normalize(arg.title),notice=normalize('剧情虚构，非真实事件。');
    if(!visible(label)||!(text===title||text.startsWith(title+' '+notice))||label.closest('form,[contenteditable=true]'))return null;
    let card=null;
    for(let p=label,depth=0;p&&depth<6;p=p.parentElement,depth++){
        if(p.classList.contains('video-card-content-Xt386b')){card=p;break;}
        if(p.matches('body,html,main,form'))break;
    }
    if(!card||card.tagName!=='DIV'||!visible(card)||!card.parentElement?.classList.contains('video-card-sfaSzz')||
        card.querySelectorAll('*').length>160||card.closest('form,[inert],[contenteditable=true]'))return null;
    const wrapper=card.parentElement;
    if(wrapper.querySelectorAll('.video-card-content-Xt386b').length!==1||wrapper.querySelectorAll('*').length>160)return null;
    const cards=Array.from(card.querySelectorAll('article,li,[role=article],[role=listitem],.video-card-content-Xt386b,.video-card-sfaSzz'));
    if(cards.some(el=>!el.contains(label)))return null;
    const leaves=Array.from(card.querySelectorAll('div,span')).filter(el=>visible(el)&&!el.children.length);
    const exact=value=>leaves.filter(el=>el.innerText.trim()===value).length===1;
    if(!['已发布','编辑作品','设置权限','作品置顶','删除作品'].every(exact))return null;
    const covers=Array.from(card.querySelectorAll('div')).filter(el=>Array.from(el.classList).some(c=>/^video-card-cover-[A-Za-z0-9_-]+$/.test(c)));
    if(covers.length!==1)return null;
    const cover=covers[0];
    const has=prefix=>Array.from(cover.querySelectorAll('div')).some(el=>Array.from(el.classList).some(c=>c.startsWith(prefix)));
    if(!has('video-card-top-')||!has('video-card-bottom-')||!visible(cover)||cover.contains(label)||
        cover.closest('form,[inert],[contenteditable=true],[aria-disabled=true]')||cover.disabled||
        /编辑|删除|发布|权限|置顶|统计/.test(cover.innerText)||cover.querySelector('a,button,input,[role=button]'))return null;
    const r=cover.getBoundingClientRect(),style=getComputedStyle(cover);
    if(style.cursor!=='pointer'||style.pointerEvents==='none'||r.width<=0||r.height<=0||r.x<0||r.y<0||r.right>innerWidth||r.bottom>innerHeight)return null;
    const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
    if(!hit||!(hit===cover||cover.contains(hit)))return null;
    if(arg.expectedCard&&(card!==arg.expectedCard||cover!==arg.expectedCover||document!==arg.capturedDocument))return null;
    return {card,cover,document};
}"""

_OPEN_RESULT_JS=r"""()=>{
    const visible=el=>el.isConnected&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
    const clean=s=>String(s||'').replace(/https?:\/\/\S+/gi,'[url]').replace(/\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*\S+/gi,'[redacted]').replace(/\s+/g,' ').trim().slice(0,80);
    const safeUrl=raw=>{try{const u=new URL(raw,location.href);return u.protocol==='https:'&&['creator.douyin.com','www.douyin.com','douyin.com'].includes(u.host)&&!u.username&&!/(token|password|authorization|cookie|session)/i.test(u.pathname)?u.origin+u.pathname:'';}catch{return '';}};
    const dialogs=Array.from(document.querySelectorAll('[role=dialog],dialog')).filter(visible).slice(0,4);
    const scope=dialogs.length===1?dialogs[0]:document;
    const securityNames=['安全验证','请完成验证','请完成下列验证','请完成安全验证','拖动滑块完成拼图'];
    const security=Array.from(document.querySelectorAll('span,div,p')).slice(0,2000).filter(el=>!el.children.length&&visible(el))
        .map(el=>el.innerText.trim()).filter(text=>securityNames.includes(text));
    const params=new URLSearchParams(location.search),keys=Array.from(params.keys());
    return {final_url:safeUrl(location.href),query_removed:!!location.search||!!location.hash,security_verification_markers:Array.from(new Set(security)),
        query_keys:keys.filter(k=>/^[A-Za-z_][A-Za-z0-9_]{0,39}$/.test(k)).slice(0,20),query_keys_truncated:keys.length>20,
        numeric_modal_ids:params.getAll('modal_id').filter(value=>/^[0-9]{1,25}$/.test(value)).slice(0,2),
        modal_id_count:params.getAll('modal_id').length,
        ui_ready:document.readyState!=='loading'&&!!(document.title.trim()||dialogs.length||Array.from(document.querySelectorAll('video,figcaption,[data-e2e="video-desc"]')).some(visible)),
        document_title:clean(document.title),visible_dialogs:dialogs.map(el=>({tag:el.tagName,role:el.getAttribute('role')||'',aria_label:clean(el.getAttribute('aria-label')),
            headings:Array.from(el.querySelectorAll('h1,h2,h3,[role=heading]')).filter(visible).slice(0,4).map(el=>clean(el.innerText))})),
        native_controls:Array.from(scope.querySelectorAll('a,button,[role=button]')).filter(visible).slice(0,12).map(el=>({tag:el.tagName,role:el.getAttribute('role')||'',
            text:clean(el.innerText),aria_label:clean(el.getAttribute('aria-label')),href:el.matches('a[href]')?safeUrl(el.href):'',disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true'}))};
}"""

_MODAL_IDENTITY_JS=r"""({postId,title})=>{
    const visible=el=>el.isConnected&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
    const normalize=s=>s.normalize('NFKC').replace(/\s+/g,' ').trim().replace(/\s*\|\s*/g,'|');
    const clean=s=>String(s||'').replace(/https?:\/\/\S+/gi,'[url]').replace(/\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*\S+/gi,'[redacted]').replace(/\s+/g,' ').trim().slice(0,80);
    const nodes=Array.from(document.querySelectorAll('div,span,p,h1,h2,h3,figcaption,[data-e2e]'));
    const titleMatches=[],uiMarkers=new Set(),diagnosticExpected=normalize(title),diagnosticNotice=normalize('剧情虚构，非真实事件。');
    const markerNames=new Set(['登录后观看','登录后可查看','登录即可观看','扫码登录','登录/注册','请先登录','加载中','加载中，请稍候...','正在加载']);
    for(const el of nodes.slice(0,3000)){
        if(!visible(el)||el.closest('input,textarea,select,[contenteditable=true],footer,header,nav,aside'))continue;
        const raw=el.innerText||'';
        if(!el.children.length&&markerNames.has(raw.trim()))uiMarkers.add(raw.trim());
        if(raw.length>6000)continue;
        const text=normalize(raw);
        if((text===diagnosticExpected||text.startsWith(diagnosticExpected+' '+diagnosticNotice))&&titleMatches.length<64)titleMatches.push(el);
    }
    const leaves=titleMatches.filter(el=>!titleMatches.some(other=>other!==el&&el.contains(other)));
    const videos=Array.from(document.querySelectorAll('video')),visibleVideos=videos.filter(visible);
    const shape=el=>({tag:el.tagName,role:clean(el.getAttribute('role')),
        class_tokens:Array.from(el.classList).filter(value=>/^[A-Za-z_-][A-Za-z0-9_-]{0,63}$/.test(value)&&!/(token|password|authorization|cookie|session)/i.test(value)).slice(0,8),
        data_e2e:clean(el.getAttribute('data-e2e')),contains_title:leaves.some(titleNode=>el===titleNode||el.contains(titleNode)),
        video_nodes:Math.min(13,el.querySelectorAll('video').length+(el.tagName==='VIDEO'?1:0)),
        caption_nodes:Math.min(13,el.querySelectorAll('figcaption,[data-e2e="video-desc"]').length)});
    const titleH1s=Array.from(new Set(leaves.map(el=>el.closest('h1')).filter(el=>el&&visible(el))));
    const seeds=titleH1s.slice(0,1).map(el=>({el,kind:'title_h1'})).concat(visibleVideos.slice(0,6).map(el=>({el,kind:'video'})),leaves.slice(0,5).map(el=>({el,kind:'title_leaf'})));
    const rendered={schema:'public_rendered_layout/v2',ready_state:document.readyState,total_videos:Math.min(13,videos.length),
        visible_videos:Math.min(13,visibleVideos.length),title_leaf_matches:Math.min(13,leaves.length),
        matching_title_h1s:Math.min(13,titleH1s.length),
        iframe_nodes:Math.min(13,document.querySelectorAll('iframe').length),
        visible_iframes:Math.min(13,Array.from(document.querySelectorAll('iframe')).filter(visible).length),
        native_ui_markers:Array.from(uiMarkers),scan_truncated:nodes.length>3000,candidates_truncated:visibleVideos.length>6||leaves.length>5||titleH1s.length>1,candidates:[]};
    for(const seed of seeds){
        const ancestors=[];
        for(let el=seed.el,depth=0;el&&depth<8;el=el.parentElement,depth++){
            if(el.matches('body,html,form,[contenteditable=true]'))break;
            const descendants=el.querySelectorAll('*').length;
            const children=Array.from(el.children).filter(child=>visible(child)&&!child.matches('input,textarea,select,script,style,[contenteditable=true]'));
            ancestors.push({...shape(el),depth,descendant_nodes:Math.min(10001,descendants),scope_truncated:descendants>240,
                children:children.slice(0,12).map(shape),children_truncated:children.length>12});
        }
        rendered.candidates.push({kind:seed.kind,ancestors});
    }
    rendered.common_scope=[];
    if(titleH1s.length===1&&visibleVideos.length===1){
        let common=titleH1s[0];
        for(let depth=0;common&&depth<24&&!common.contains(visibleVideos[0]);depth++)common=common.parentElement;
        if(common&&!common.matches('body,html')&&common.contains(visibleVideos[0])){
            const markerValues=['内容由AI生成','剧情虚构，非真实事件。','审核中','审核不通过','未通过审核','暂不可见','视频已删除','作品不存在'];
            for(let level=0;common&&level<3&&!common.matches('body,html,form,[contenteditable=true]');level++,common=common.parentElement){
                const scoped=Array.from(common.querySelectorAll('div,span,p,h1,h2,h3')).filter(visible).slice(0,4000);
                const markerCounts={};
                for(const marker of markerValues){
                    const expectedMarker=normalize(marker).replace(/\s/g,'');
                    const matches=scoped.filter(el=>{const raw=el.innerText||'';if(raw.length>6000)return false;
                        const value=normalize(raw).replace(/\s/g,'');
                        return marker==='剧情虚构，非真实事件。'?value.includes(expectedMarker):
                            value===expectedMarker||value==='作者声明:'+expectedMarker;}).slice(0,64);
                    markerCounts[marker]=Math.min(13,matches.filter(el=>!matches.some(other=>other!==el&&el.contains(other))).length);
                }
                rendered.common_scope.push({...shape(common),parent_level:level,descendant_nodes:Math.min(10001,common.querySelectorAll('*').length),
                    h1_nodes:Math.min(13,common.querySelectorAll('h1').length+(common.tagName==='H1'?1:0)),
                    visible_video_nodes:Math.min(13,Array.from(common.querySelectorAll('video')).filter(visible).length),
                    fixed_visible_marker_counts:markerCounts,marker_scan_truncated:common.querySelectorAll('div,span,p,h1,h2,h3').length>4000});
            }
        }
    }
    const all=Array.from(document.querySelectorAll('[data-e2e-vid],[data-video-id]')).filter(visible);
    const matching=all.filter(el=>el.getAttribute('data-e2e-vid')===postId||el.getAttribute('data-video-id')===postId);
    const diagnostic={explicit_id_nodes:all.length,matching_id_nodes:matching.length,verified:false,rendered_layout:rendered};
    let root;
    if(all.length){
        if(all.length>12||matching.length!==1)return {...diagnostic,reason:'explicit_work_id_not_unique'};
        root=matching[0];diagnostic.scope_source='explicit_id';
        if(['data-e2e-vid','data-video-id'].some(attr=>root.hasAttribute(attr)&&root.getAttribute(attr)!==postId))return {...diagnostic,reason:'explicit_work_id_conflict'};
    }else{
        const articles=Array.from(document.querySelectorAll('article,[role=article]')).filter(el=>visible(el)&&el.querySelector('video'));
        diagnostic.article_nodes=articles.length;
        if(articles.length!==1)return {...diagnostic,reason:'semantic_work_not_unique'};
        root=articles[0];diagnostic.scope_source='semantic_article';
    }
    const captions=Array.from(root.querySelectorAll('figcaption,[data-e2e="video-desc"]')).filter(visible);
    diagnostic.caption_nodes=captions.length;diagnostic.video_nodes=Array.from(root.querySelectorAll('video')).filter(visible).length;
    if(captions.length!==1||diagnostic.video_nodes!==1)return {...diagnostic,reason:'work_caption_or_player_not_unique'};
    const text=normalize(captions[0].innerText),expected=normalize(title),notice=normalize('剧情虚构，非真实事件。');
    return {...diagnostic,verified:text===expected||text.startsWith(expected+' '+notice),reason:'explicit_id_and_caption_checked'};
}"""


def _native_modal_id(url):
    if len(url)>4096:return ''
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.netloc!='www.douyin.com' or parsed.path!='/user/self':return ''
    try:pairs=parse_qsl(parsed.query,keep_blank_values=True,max_num_fields=32)
    except ValueError:return ''
    values=[value for key,value in pairs if key=='modal_id']
    if any(key in ('video_id','aweme_id','item_id') for key,_ in pairs):return ''
    return values[0] if len(values)==1 and re.fullmatch(r'[0-9]{1,25}',values[0]) else ''


def _read_modal_identity(page,post_id,title):
    identity=page.evaluate(_MODAL_IDENTITY_JS,{'postId':post_id,'title':title})
    if identity.get('verified'):return identity
    from src.shared.published_work_scope import read_observed_work_scope
    observed=read_observed_work_scope(page,post_id,title)
    identity['observed_scope']=observed
    if observed.get('human_required'):identity.update(human_required=True,verified=False)
    elif observed.get('verified'):identity.update(verified=True,scope_source='observed_video_detail')
    return identity


def _resolve_native_popup(popup,title):
    deadline=time.monotonic()+12
    evidence={'budget_seconds':12,'observations':[],'verified':False}
    while time.monotonic()<deadline and len(evidence['observations'])<9:
        snapshot=popup.evaluate(_OPEN_RESULT_JS)
        evidence['observations'].append({key:snapshot.get(key) for key in
            ('final_url','query_keys','numeric_modal_ids','modal_id_count','ui_ready','security_verification_markers')})
        if time.monotonic()>=deadline:evidence['reason']='popup_wait_budget_elapsed';return evidence
        if snapshot['security_verification_markers']:
            evidence.update(reason='security_verification_visible',human_required=True,block_discovery=True);return evidence
        if canonical_video(popup.url):evidence['reason']='direct_canonical_route';return evidence
        candidate_id=_native_modal_id(popup.url)
        if candidate_id and snapshot['ui_ready']:
            evidence.update(candidate_post_id=candidate_id,candidate_source='original_native_self_modal_url',requires_identity=True)
            url=f'https://www.douyin.com/video/{candidate_id}'
            try:popup.goto(url,wait_until='domcontentloaded',timeout=max(1,min(6000,int((deadline-time.monotonic())*1000))))
            except Exception as exc:evidence.update(reason='canonical_navigation_unknown',error_type=type(exc).__name__);return evidence
            for _ in range(8):
                if time.monotonic()>=deadline:break
                if canonical_video(popup.url)!=url:evidence['reason']='canonical_route_changed';return evidence
                security=popup.evaluate(_OPEN_RESULT_JS)['security_verification_markers']
                if security:
                    evidence.update(reason='security_verification_visible',human_required=True,block_discovery=True,security_verification_markers=security);return evidence
                identity=_read_modal_identity(popup,candidate_id,title)
                evidence['identity']=identity
                if identity.get('human_required'):
                    evidence.update(human_required=True,block_discovery=True,reason='native_challenge_visible');return evidence
                if identity['verified'] and time.monotonic()<deadline:
                    evidence.update(verified=True,publish_url=url,reason='canonical_native_id_caption_verified');return evidence
                popup.wait_for_timeout(max(1,min(1000,int((deadline-time.monotonic())*1000))))
            evidence['reason']='canonical_identity_unverified';return evidence
        popup.wait_for_timeout(max(1,min(1500,int((deadline-time.monotonic())*1000))))
    evidence['reason']='popup_ui_or_modal_field_unverified'
    return evidence


def _discover_observed_cover(page,original,title,result):
    def reject(reason):return dict(result,reason=reason)
    original_url=page.url
    binding=original.evaluate_handle(_COVER_BIND_JS,{'title':title})
    if not binding.evaluate('value=>!!value'):return reject('independent_card_unbound')
    result['diagnostic']['observed_cover']={'qualified':True,'source':'frozen_native_fe45c682_discovery8'}
    if page in _DETAIL_CLICKS:return reject('detail_click_already_dispatched')
    card=binding.get_property('card').as_element();cover=binding.get_property('cover').as_element()
    captured=binding.get_property('document')
    if page.url!=original_url or not is_manage_url(page.url) or not original.evaluate('(label,arg)=>!!('+_COVER_BIND_JS+')(label,arg)',
            {'title':title,'expectedCard':card,'expectedCover':cover,'capturedDocument':captured}):
        return reject('observed_cover_identity_changed')
    before=set(page.context.pages)
    _DETAIL_CLICKS[page]=title
    result['diagnostic']['observed_cover']['click_dispatched']=True
    click_error=None
    try:
        cover.click(timeout=5000)
        page.wait_for_timeout(1000)
    except Exception as exc:click_error=type(exc).__name__
    new_pages=[p for p in page.context.pages if p not in before]
    pages=[page]+new_pages
    result['diagnostic']['observed_cover']['new_pages']=len(new_pages)
    modal_resolution=None
    if len(new_pages)==1 and not click_error:
        try:
            modal_resolution=_resolve_native_popup(new_pages[0],title)
            result['diagnostic']['native_popup_resolution']=modal_resolution
        except Exception as exc:
            modal_resolution={'verified':False,'block_discovery':True,'reason':'popup_resolution_unknown','error_type':type(exc).__name__}
            result['diagnostic']['native_popup_resolution']=modal_resolution
    result['diagnostic']['cover_open_pages']=[]
    for candidate in pages[:2]:
        if candidate.is_closed():continue
        try:result['diagnostic']['cover_open_pages'].append(candidate.evaluate(_OPEN_RESULT_JS))
        except Exception as exc:result['diagnostic']['cover_open_pages'].append({'diagnostic_error':type(exc).__name__})
    if any(item.get('security_verification_markers') for item in result['diagnostic']['cover_open_pages']):
        modal_resolution=dict(modal_resolution or {},human_required=True,block_discovery=True,verified=False,reason='security_verification_visible')
        result['diagnostic']['native_popup_resolution']=modal_resolution
    def finish(reason=None,url=None):
        if len(new_pages)==1 and modal_resolution and modal_resolution.get('human_required'):
            result['diagnostic']['observed_cover']['new_page_retained_for_human']=True
        elif len(new_pages)==1:
            try:
                if not new_pages[0].is_closed():new_pages[0].close()
                result['diagnostic']['observed_cover']['new_page_closed']=True
            except Exception as exc:
                result['diagnostic']['observed_cover']['new_page_close_error']=type(exc).__name__
                return reject('observed_cover_new_page_close_unknown')
        if reason:return reject(reason)
        return dict(result,verified=True,post_id=url.rsplit('/',1)[1],publish_url=url,reason='observed_title_card_cover_canonical_id')
    if click_error:
        result['diagnostic']['observed_cover']['click_error']=click_error
        return finish('observed_cover_click_result_unknown')
    if len(pages)>2:return finish('detail_pages_ambiguous')
    if modal_resolution and modal_resolution.get('human_required'):
        return finish('observed_cover_human_required')
    if modal_resolution and (modal_resolution.get('requires_identity') or modal_resolution.get('block_discovery')) and not modal_resolution.get('verified'):
        return finish('observed_cover_modal_identity_unverified')
    urls={url for candidate in pages if not candidate.is_closed() and (url:=canonical_video(candidate.url))}
    if len(urls)!=1:return finish('observed_cover_exact_url_not_unique')
    url=urls.pop()
    if modal_resolution and modal_resolution.get('requires_identity'):
        if url!=modal_resolution.get('publish_url'):return finish('observed_cover_modal_route_changed')
        try:
            if new_pages[0].evaluate(_OPEN_RESULT_JS)['security_verification_markers']:
                modal_resolution.update(human_required=True,verified=False,block_discovery=True)
                return finish('observed_cover_human_required')
            final_identity=_read_modal_identity(new_pages[0],modal_resolution['candidate_post_id'],title)
            result['diagnostic']['native_popup_resolution']['final_identity']=final_identity
            if final_identity.get('human_required'):
                modal_resolution.update(human_required=True,verified=False,block_discovery=True)
                return finish('observed_cover_human_required')
            if not final_identity['verified'] or canonical_video(new_pages[0].url)!=url:
                return finish('observed_cover_modal_identity_unverified')
        except Exception as exc:
            result['diagnostic']['native_popup_resolution']['final_identity_error']=type(exc).__name__
            return finish('observed_cover_modal_identity_unverified')
    return finish(url=url)

_TITLE_DIAGNOSTIC_JS=r"""label=>{
    const visible=el=>el.isConnected&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
    const clean=(s,n=80)=>String(s||'').replace(/https?:\/\/\S+/gi,'[url]')
        .replace(/\b(token|access_token|authorization|cookie|session|password)\s*[:=]\s*\S+/gi,'[redacted]')
        .replace(/\s+/g,' ').trim().slice(0,n);
    const href=el=>{try{const u=new URL(el.getAttribute('href'),location.href);
        return u.protocol==='https:'&&['creator.douyin.com','www.douyin.com','douyin.com'].includes(u.host)&&!u.username&&
            !/(token|password|authorization|cookie|session)/i.test(u.pathname)?u.origin+u.pathname:'';}catch{return '';}};
    const classes=el=>Array.from(el.classList).filter(s=>/^[A-Za-z_-][A-Za-z0-9_-]{0,63}$/.test(s)&&
        !/(token|password|authorization|cookie|session)/i.test(s)).slice(0,8);
    const ownText=el=>Array.from(el.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(' ');
    const operationText=el=>{const text=clean(ownText(el));return /^(编辑作品|设置权限|作品置顶|删除作品|查看作品|查看详情|作品详情|更多|已发布)$/.test(text)?text:'';};
    const shape=el=>{const r=el.getBoundingClientRect(),style=getComputedStyle(el);
        const inViewport=r.width>0&&r.height>0&&r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;
        const hit=inViewport?document.elementFromPoint(r.left+r.width/2,r.top+r.height/2):null;
        return {tag:el.tagName,role:clean(el.getAttribute('role'),24),visible:!!visible(el),
            class_tokens:classes(el),data_e2e:clean(el.getAttribute('data-e2e')),alt:el.tagName==='IMG'?clean(el.getAttribute('alt')):'',
            title:clean(el.getAttribute('title')),aria_label:clean(el.getAttribute('aria-label')),
            disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true',inert:!!el.closest('[inert]'),
            in_viewport:inViewport,hit_self_or_descendant:!!hit&&(hit===el||el.contains(hit)),
            pointer_events:style.pointerEvents==='none'?'none':'enabled',cursor:style.cursor==='pointer'?'pointer':'other',
            tabindex:/^-?\d{1,4}$/.test(el.getAttribute('tabindex')||'')?el.getAttribute('tabindex'):null,
            onclick_attribute:el.hasAttribute('onclick')};};
    const control=el=>{const r=el.getBoundingClientRect(),style=getComputedStyle(el);
        const inViewport=r.width>0&&r.height>0&&r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;
        const hit=inViewport?document.elementFromPoint(r.left+r.width/2,r.top+r.height/2):null;
        return {...shape(el),text:clean(el.innerText),title:clean(el.getAttribute('title')),aria_label:clean(el.getAttribute('aria-label')),
            href:el.matches('a[href]')?href(el):'',href_query_removed:el.matches('a[href]')&&/[?#]/.test(el.getAttribute('href')),
            disabled:!!el.disabled||el.getAttribute('aria-disabled')==='true',inert:!!el.closest('[inert]'),
            in_viewport:inViewport,hit_self_or_descendant:!!hit&&(hit===el||el.contains(hit)),
            pointer_events:style.pointerEvents==='none'?'none':'enabled',cursor:style.cursor==='pointer'?'pointer':'other',
            tabindex:/^-?\d{1,4}$/.test(el.getAttribute('tabindex')||'')?el.getAttribute('tabindex'):null,onclick_attribute:el.hasAttribute('onclick')};};
    const shell=el=>{const tag=['A','BUTTON','DIV','SPAN','P','SECTION','ARTICLE','LI','H1','H2','H3','FIGCAPTION','IMG'].includes(el.tagName)?el.tagName.toLowerCase():'div';
        const node=document.createElement(tag);
        for(const attr of ['role','aria-label','title','tabindex','aria-disabled']){
            if(el.hasAttribute(attr))node.setAttribute(attr,clean(el.getAttribute(attr),80));}
        if(el.matches('a[href]')&&href(el))node.setAttribute('href',href(el));
        if(classes(el).length)node.setAttribute('class',classes(el).join(' '));
        if(el.hasAttribute('data-e2e'))node.setAttribute('data-e2e',clean(el.getAttribute('data-e2e')));
        if(el.tagName==='IMG')node.setAttribute('alt',clean(el.getAttribute('alt'))||'[image]');
        return node;};
    let projectionNodes=0;
    const projected=(el,depth=0)=>{const node=shell(el);
        if(++projectionNodes>64)return node;
        if(el===label){node.textContent=clean(el.innerText,500);return node;}
        if(el.tagName==='IMG')return node;
        if(operationText(el))node.appendChild(document.createTextNode(operationText(el)));
        if(depth>=6)return node;
        for(const child of Array.from(el.children).slice(0,16)){
            if(child.matches('input,textarea,select,[contenteditable=true],script,style,video,audio'))continue;
            if(child===label||child.contains(label))node.appendChild(projected(child,depth+1));
            else if(child.matches('a,button,[role=button]')){const c=shell(child);c.textContent=clean(child.innerText);node.appendChild(c);}
            else node.appendChild(projected(child,depth+1));
        }
        return node;};
    const ancestors=[];
    for(let p=label,depth=0;p&&depth<6;p=p.parentElement,depth++){
        if(p.matches('body,html,main,form,footer,header,nav,aside,[contenteditable=true]'))break;
        const all=p.querySelectorAll('*');
        if(all.length>160){ancestors.push({...shape(p),depth,nodes:161,scope_truncated:true});break;}
        const foreign=Array.from(p.querySelectorAll('article,li,[role=article],[role=listitem]')).some(el=>!el.contains(label)&&
            (el.querySelector('video,a[href]')||Array.from(el.querySelectorAll('button,[role=button]')).some(c=>/^(查看作品|查看详情|作品详情)$/.test((c.innerText||'').trim()))));
        if(foreign){ancestors.push({...shape(p),depth,nodes:all.length,foreign_work_boundary:true});break;}
        const controls=Array.from(p.querySelectorAll('a,button,[role=button]')).filter(visible);
        const local=Array.from(all).filter(el=>visible(el)&&el.matches('div,span,img,a,button,p,[role]')&&
            !el.closest('input,textarea,select,[contenteditable=true]'));
        const ordered=local.filter(el=>el.tagName==='IMG'||getComputedStyle(el).cursor==='pointer')
            .concat(local.filter(el=>el.tagName!=='IMG'&&getComputedStyle(el).cursor!=='pointer'));
        const localNodes=ordered.slice(0,64).map(el=>{const r=el.getBoundingClientRect(),text=ownText(el);
            const coordinate=n=>Math.max(-100000,Math.min(100000,Math.round(n*10)/10));
            return {...shape(el),own_text:clean(text),own_text_truncated:clean(text,1000).length>80,
                image_children:Math.min(25,el.querySelectorAll('img').length),
                rect:{x:coordinate(r.x),y:coordinate(r.y),width:coordinate(r.width),height:coordinate(r.height)}};});
        projectionNodes=0;
        const html=projected(p).outerHTML;
        ancestors.push({...shape(p),depth,nodes:all.length,controls:controls.slice(0,8).map(control),
            local_nodes:localNodes,local_nodes_truncated:local.length>64,
            controls_truncated:controls.length>8,projected_outer_html:html.slice(0,1400),html_truncated:html.length>1400});
    }
    return {schema:'bound_title_structure/v2',connected:label.isConnected,projection:'title_path_control_shells_known_operation_text_and_image_alt_only',ancestors};
}"""

_TITLE_CANDIDATES_JS=r"""title=>{
    const normalize=s=>s.normalize('NFKC').replace(/\s+/g,' ').trim().replace(/\s*\|\s*/g,'|');
    const expected=normalize(title),notice=normalize('剧情虚构，非真实事件。');
    const match=text=>{const value=normalize(text);return value===expected?'normalized_exact':
        value.startsWith(expected+' '+notice)?'complete_title_caption_prefix':'';};
    const visible=el=>el.isConnected && el.getClientRects().length && getComputedStyle(el).visibility!=='hidden';
    const excluded=el=>el.closest('footer,header,nav,aside,[contenteditable=true],textarea,input');
    const canonical=a=>{try{const u=new URL(a.href,location.href);return u.protocol==='https:' &&
        ['www.douyin.com','douyin.com'].includes(u.host) && !u.username && /^\/video\/\d+\/?$/.test(u.pathname);}catch{return false;}};
    const shape=el=>({tag:el.tagName,role:['article','listitem','button','link'].includes(el.getAttribute('role'))?el.getAttribute('role'):'other',
        canonical_links:Math.min(25,Array.from(el.querySelectorAll('a[href]')).filter(a=>visible(a)&&canonical(a)).length),
        detail_controls:Math.min(25,Array.from(el.querySelectorAll('a,button,[role=button]')).filter(a=>visible(a)&&/^(查看作品|查看详情|作品详情)$/.test((a.innerText||'').trim())).length)});
    const loadingText=new Set(['加载中','加载中...','加载中，请稍候...','正在加载','请稍候'].map(normalize));
    let scanned=0,loading=0,excessive=false,all=[],semantic=[];
    const walker=document.createTreeWalker(document.documentElement,NodeFilter.SHOW_ELEMENT);
    let el=walker.nextNode();
    for(;el && scanned<4000;el=walker.nextNode()){
        scanned++;
        if(!visible(el)||excluded(el))continue;
        const text=typeof el.innerText==='string'?el.innerText:'';
        if(el.matches('[role=progressbar],[aria-busy=true]') || (!el.children.length&&loadingText.has(normalize(text))))loading=Math.min(25,loading+1);
        if(el.matches('article,li,[role=article],[role=listitem]') && semantic.length<12)semantic.push(shape(el));
        if(!['SPAN','P','DIV','SECTION','ARTICLE','LI','H1','H2','H3','A','FIGCAPTION'].includes(el.tagName))continue;
        if(text.length>6000)continue;
        const kind=match(text);if(kind){if(all.length>=64){excessive=true;break;}all.push({el,kind});}
    }
    const leaves=all.filter(a=>!all.some(b=>a!==b&&a.el.contains(b.el)));
    return {nodes:leaves.slice(0,25).map(a=>a.el),diagnostic:{title_candidates:leaves.length,
        candidates_excessive:excessive||leaves.length>24,scan_truncated:!!el&&scanned>=4000,scanned_nodes:scanned,
        loading_markers:loading,visible_semantic_candidates:semantic,
        title_candidate_structure:leaves.slice(0,12).map(a=>({...shape(a.el),match:a.kind}))}};
}"""



def is_manage_url(url):
    p=urlsplit(url)
    return (p.scheme=='https' and p.netloc=='creator.douyin.com'
        and p.path=='/creator-micro/content/manage' and p.query in ('','enter_from=publish') and not p.fragment)


def canonical_video(url):
    p=urlsplit(url)
    match=re.fullmatch(r'/video/(\d+)/?',p.path)
    return f'https://www.douyin.com/video/{match[1]}' if (p.scheme=='https'
        and p.netloc in ('www.douyin.com','douyin.com') and match) else ''


def discover_published_work(page,title):
    result={'schema':'published_work_discovery/v1','verified':False,'post_id':'','publish_url':'',
            'diagnostic':{'route':'manage' if is_manage_url(page.url) else 'other'}}
    def reject(reason):
        return dict(result,reason=reason)
    if not is_manage_url(page.url) or not isinstance(title,str) or not title.strip() or len(title)>200:
        return reject('manage_route_or_title_invalid')
    candidates=page.evaluate_handle(_TITLE_CANDIDATES_JS,title)
    result['diagnostic'].update(candidates.get_property('diagnostic').json_value())
    if result['diagnostic']['scan_truncated']:return reject('title_scan_truncated')
    if result['diagnostic']['candidates_excessive']:return reject('title_candidates_excessive')
    nodes=candidates.get_property('nodes')
    visible=[value.as_element() for key,value in nodes.get_properties().items() if key.isdigit()]
    if len(visible)!=1:
        if len(visible)>1:return reject('title_not_unique')
        return reject('manage_loading' if result['diagnostic']['loading_markers'] else 'title_candidate_missing')
    original=visible[0]
    try:
        result['diagnostic']['bound_title_structure']=original.evaluate(_TITLE_DIAGNOSTIC_JS)
    except Exception as exc:
        result['diagnostic']['bound_title_structure']={'available':False,'error_type':type(exc).__name__}
    card=original.evaluate_handle(r'''(label,title)=>{
        const visible=el=>el.isConnected && el.getClientRects().length && getComputedStyle(el).visibility!=='hidden';
        const excluded=el=>el.closest('footer,header,nav,aside,[contenteditable=true],textarea,input');
        const canonical=href=>{try{const u=new URL(href,location.href);
            return u.protocol==='https:' && ['www.douyin.com','douyin.com'].includes(u.host) && !u.username &&
                /^\/video\/\d+\/?$/.test(u.pathname);}catch{return false;}};
        const normalize=s=>s.normalize('NFKC').replace(/\s+/g,' ').trim().replace(/\s*\|\s*/g,'|');
        const text=normalize(label.innerText),expected=normalize(title),notice=normalize('剧情虚构，非真实事件。');
        if(!visible(label) || excluded(label) || !(text===expected || text.startsWith(expected+' '+notice)))return null;
        for(let p=label,d=0;p && d<6;p=p.parentElement,d++){
            if(['BODY','HTML','MAIN','FORM'].includes(p.tagName))break;
            if(!['DIV','SECTION','ARTICLE','LI'].includes(p.tagName) || excluded(p) || !visible(p))continue;
            if(p.querySelectorAll('*').length>160 || p.innerText.length>5000)continue;
            const foreignWork=Array.from(p.querySelectorAll('article,li,[role=article],[role=listitem]')).some(child=>
                !child.contains(label) && (child.querySelector('video') ||
                    Array.from(child.querySelectorAll('a[href]')).some(a=>canonical(a.href)) ||
                    Array.from(child.querySelectorAll('a,button,[role=button]')).some(a=>
                        /^(查看作品|查看详情|作品详情)$/.test(a.innerText.trim()))));
            if(foreignWork)continue;
            const links=Array.from(p.querySelectorAll('a[href]')).filter(a=>visible(a) && canonical(a.href));
            const details=Array.from(p.querySelectorAll('a,button,[role=button]')).filter(a=>visible(a) &&
                /^(查看作品|查看详情|作品详情)$/.test(a.innerText.trim()));
            if(links.length || details.length || p.matches('article,li,[role=article],[role=listitem]'))return p;
        }
        return null;
    }''',title).as_element()
    if card is None:return _discover_observed_cover(page,original,title,result)
    snapshot=card.evaluate(r'''card=>({tag:card.tagName,nodes:Math.min(161,card.querySelectorAll('*').length),
        hrefs:Array.from(card.querySelectorAll('a[href]')).filter(a=>a.getClientRects().length)
            .slice(0,40).map(a=>a.href)})''')
    urls={value for href in snapshot.pop('hrefs',[]) if (value:=canonical_video(href))}
    result['diagnostic'].update(card_tag=snapshot['tag'],card_nodes=snapshot['nodes'],canonical_ids=len(urls))
    if len(urls)>1:return reject('card_video_id_ambiguous')
    if len(urls)==1:
        url=urls.pop()
        if not original.evaluate('(el,card)=>el.isConnected && card.isConnected && card.ownerDocument===document && card.contains(el)',card):
            return reject('original_card_changed')
        if not is_manage_url(page.url):return reject('manage_document_changed')
    else:
        details=card.evaluate_handle('''card=>Array.from(card.querySelectorAll('a,button,[role=button]'))
            .filter(el=>el.getClientRects().length && !el.disabled && el.getAttribute('aria-disabled')!=='true' &&
                /^(查看作品|查看详情|作品详情)$/.test(el.innerText.trim())).slice(0,11)''')
        targets=[value.as_element() for key,value in details.get_properties().items() if key.isdigit()]
        result['diagnostic']['detail_candidates']=len(targets)
        if len(targets)!=1:return reject('canonical_id_missing')
        if page in _DETAIL_CLICKS:return reject('detail_click_already_dispatched')
        target=targets[0]
        if target.evaluate("el=>!!el.closest('form')"):return reject('detail_form_action_rejected')
        before=set(page.context.pages)
        if not original.evaluate('(el,card)=>el.isConnected && card.isConnected && card.contains(el)',card):
            return reject('original_card_changed')
        _DETAIL_CLICKS[page]=title
        try:
            target.click(timeout=5000)
            page.wait_for_timeout(1000)
        except Exception:
            return reject('detail_click_result_unknown')
        candidates=[page]+[p for p in page.context.pages if p not in before]
        if len(candidates)>2:return reject('detail_pages_ambiguous')
        urls={url for p in candidates if not p.is_closed() and (url:=canonical_video(p.url))}
        if len(urls)!=1:return reject('detail_exact_url_not_unique')
        url=urls.pop()
    result.update(verified=True,post_id=url.rsplit('/',1)[1],publish_url=url,reason='exact_title_card_canonical_id')
    return result
