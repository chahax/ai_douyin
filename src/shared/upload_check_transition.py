"""One file-selection's native UI node transition, held outside the webpage.

No media, input values, network, storage or DOM writes. Unknown UI cannot create
positive evidence. This is independent of the retained bytes/cancel witness.
"""
import re
import time
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary, ref


_ATTEMPTS = WeakKeyDictionary()
_GUARDS = WeakKeyDictionary()
_CHECKING = re.compile(r'^(?:检测中|正在检测)(?:\s*\d+(?:\.\d+)?\s*%)?[.…。]*$')
_STATE = re.compile(r'^(?:作品未见异常|(?:检测中|正在检测)(?:\s*\d+(?:\.\d+)?\s*%)?[.…。]*)$')
_UPLOAD = '/creator-micro/content/upload'
_EDITOR = '/creator-micro/content/post/video'


def _route(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'creator.douyin.com' or parsed.fragment):
            return 'other'
        if parsed.path == _UPLOAD and not parsed.query:
            return 'upload'
        if parsed.path == _EDITOR and parsed.query == 'enter_from=publish_page':
            return 'editor'
    except (ValueError, TypeError):
        pass
    return 'other'


def _navigation(proof, generation, route):
    proof['generation'], proof['current_route'] = generation, route
    if len(proof['routes']) >= 8:
        proof['route_history_truncated'] = True
        _invalidate(proof, 'route_history_limit')
        return
    previous = proof['routes'][-1]['route']
    proof['routes'].append({'route': route, 'generation': generation,
        'event': 'same_route_event' if route == previous else 'route_change'})
    if proof['state'] == 'invalid':
        return
    if proof.get('bound') is not None:
        _invalidate(proof, 'navigation_after_check_binding')
    elif route == 'other' or previous == 'editor' and route == 'upload':
        _invalidate(proof, 'route_not_directed_upload_to_editor')
    else:
        proof['state'] = 'armed_' + route

_DOM = r"""
const excluded=el=>{
    let p=el,d=0;
    for(;p && d<40;p=p.parentElement,d++) {
        if(p.matches('script,style,noscript,template,input,textarea,video,audio,canvas,article,footer,nav,blockquote,pre,[role=article],'+
            '[contenteditable]:not([contenteditable=false])')) return true;
        const area=(p.getAttribute('aria-label')||'')+' '+(p.getAttribute('title')||'');
        if(/预览|简介|作品描述|正文|作者|\bpreview\b|\bdescription\b|\bcaption\b|\bauthor\b/i.test(area)) return true;
    }
    return !!p;
};
const visible=el=>{
    if(!el || !el.isConnected || excluded(el) || !el.getClientRects().length) return false;
    let p=el,d=0;
    for(;p && d<40;p=p.parentElement,d++) {
        const s=getComputedStyle(p);
        if(p.hidden || p.hasAttribute('inert') || p.getAttribute('aria-hidden')==='true' ||
            s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0) return false;
    }
    return !p;
};
const text=el=>(el.innerText||'').trim();
const usable=el=>{
    if(!visible(el)) return false;
    let p=el,d=0;
    for(;p && d<40;p=p.parentElement,d++) {
        if(p.disabled || p.getAttribute('aria-disabled')==='true' || p.hasAttribute('inert') || getComputedStyle(p).pointerEvents==='none') return false;
    }
    const r=el.getBoundingClientRect();
    if(r.right<=0 || r.bottom<=0 || r.left>=innerWidth || r.top>=innerHeight) return false;
    const hit=document.elementFromPoint((Math.max(0,r.left)+Math.min(innerWidth,r.right))/2,
        (Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2);
    return !!hit && (hit===el || el.contains(hit));
};
"""


def _reply(proof, state=None, reason=None):
    return {'schema': 'upload_check_transition/v2', 'selection_nonce': proof['nonce'],
        'state': state or proof['state'], 'verified': (state or proof['state']) == 'verified',
        'reason': reason, 'stable_observations': list(proof.get('stable', [])),
        'checking_observed': proof.get('bound') is not None,
        'diagnostic': dict(proof.get('diagnostic', {}), initial_route=proof.get('initial_route'),
            current_route=proof.get('current_route'), routes=list(proof.get('routes', [])),
            route_history_truncated=proof.get('route_history_truncated', False),
            generation=proof.get('generation'), bound_generation=proof.get('bound_generation'))}


def _invalidate(proof, reason):
    proof['state'], proof['reason'], proof['stable'] = 'invalid', reason, []
    return _reply(proof, reason=reason)


def _visible(items):
    if items.count() > 24:
        raise ValueError('upload_check_candidates_excessive')
    return [items.nth(i) for i in range(items.count()) if items.nth(i).is_visible()]


def begin_upload_check(page, selection_nonce):
    if not isinstance(selection_nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', selection_nonce):
        raise ValueError('upload_selection_nonce_invalid')
    if page not in _GUARDS:
        weak_page, guard = ref(page), {'generation': 0}
        def navigated(frame):
            current = weak_page()
            if current is not None and frame == current.main_frame:
                guard['generation'] += 1
                proof = _ATTEMPTS.get(current)
                if proof is not None:
                    _navigation(proof, guard['generation'], _route(frame.url))
        def closed():
            current = weak_page()
            if current is not None:
                _ATTEMPTS.pop(current, None)
                _GUARDS.pop(current, None)
        page.on('framenavigated', navigated)
        page.on('close', closed)
        _GUARDS[page] = guard
    route, generation = _route(page.url), _GUARDS[page]['generation']
    proof = {'nonce': selection_nonce, 'state': 'armed_' + route, 'url': None,
        'document': None, 'begin_document': None, 'deadline': time.monotonic() + 120,
        'armed_document': None, 'armed_document_route': route, 'armed_generation': generation,
        'generation': generation, 'bound_generation': None, 'bound': None, 'stable': [],
        'initial_route': route, 'current_route': route,
        'routes': [{'route': route, 'generation': generation, 'event': 'begin'}],
        'route_history_truncated': False, 'diagnostic': {}}
    _ATTEMPTS[page] = proof
    if route == 'other':
        return _invalidate(proof, 'selection_started_outside_known_upload_flow')
    try:
        original = page.locator('html').element_handle(timeout=1500)
        if generation == _GUARDS[page]['generation'] and _route(page.url) == route:
            proof['begin_document'] = original
            proof['armed_document'] = original
    except Exception:
        proof['diagnostic']['begin_document_capture'] = 'unknown'
    return _reply(proof)


def _document_retained(original):
    if original is None:
        return None
    try:
        return original.evaluate('el => el.isConnected && el===document.documentElement') is True
    except Exception:
        return None


def _arm_document(page, proof):
    """A same-route event alone is never proof that a document was retained."""
    route = proof['current_route']
    retained = _document_retained(proof['armed_document'])
    proof['diagnostic']['armed_document_retained'] = retained
    if route == proof['armed_document_route']:
        if retained is not True:
            return 'armed_document_replaced_or_unknown'
        # Only events whose document identity was actually observed may be
        # discounted before a later single upload-to-editor document change.
        proof['armed_generation'] = proof['generation']
        return None
    if proof['armed_document_route'] != 'upload' or route != 'editor':
        return 'armed_route_not_directed'
    events = [item for item in proof['routes'] if item['generation'] > proof['armed_generation']]
    if len(events) != 1 and retained is not True:
        return 'unobserved_document_history_ambiguous'
    document = page.locator('html').element_handle(timeout=1500)
    if _document_retained(document) is not True:
        return 'editor_document_unknown'
    proof['armed_document'], proof['armed_document_route'] = document, 'editor'
    proof['armed_generation'] = proof['generation']
    proof['diagnostic']['editor_document_fixed'] = True
    return None


def _surface_flags(page):
    return page.evaluate("() => {" + _DOM + r"""
        const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
        let node,n=0,size=0,failed=false,transfer=false,cancel=false,parsing=false,percent=0;
        const reply=truncated=>({truncated,failed,transfer,cancel_upload_present:cancel,
            parsing_present:parsing,independent_percent_count:percent});
        while((node=walker.nextNode())) {
            if(++n>5000) return reply(true);
            if(!visible(node.parentElement)) continue;
            const t=(node.textContent||'').trim();
            if((size+=t.length)>16000) return reply(true);
            if(/^取消\s*上传$/.test(t)) cancel=true;
            if(/^文件解析中[，,]?\s*请稍等[.…。]*$/.test(t)) parsing=true;
            if(/^\d+(?:\.\d+)?\s*%$/.test(t)) percent=Math.min(25,percent+1);
            if(/^(?:上传失败|上传出错|重新上传失败)(?:[，,：:。.!！].*)?$/.test(t)) failed=true;
            if(/^(?:正在上传|上传中|上传处理中)(?:\s*\d+(?:\.\d+)?\s*%)?[.…。]*$/.test(t)
                || /^取消\s*上传$/.test(t)
                || /^已上传\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:[KMGT]?B)?\s*\/\s*\d+(?:\.\d+)?\s*[KMGT]?B$/i.test(t)) transfer=true;
        }
        return reply(false);
    }""")


def _reupload(page):
    matches = _visible(page.get_by_text('重新上传', exact=True))
    if len(matches) != 1:
        return None
    handle = matches[0].evaluate_handle("el => {" + _DOM + """
        for(let p=el,d=0;p && d<4 && p!==document.body;p=p.parentElement,d++) {
            if(p.tagName==='BUTTON' || (p.tagName==='A' && p.hasAttribute('href')) || p.getAttribute('role')==='button'
                || (p.hasAttribute('tabindex') && p.tabIndex>=0) || getComputedStyle(p).cursor==='pointer') {
                return text(p)==='重新上传' && usable(p) ? p : null;
            }
        }
        return null;
    }""").as_element()
    return handle


def _reupload_shape(page):
    """Resolve original exact leaf/control even when offscreen, without actions."""
    matches = _visible(page.get_by_text('重新上传', exact=True))
    diagnostic = {'candidates':len(matches), 'reason':'ambiguous' if len(matches)>1 else 'absent'}
    if len(matches)!=1:
        return None, None, diagnostic
    leaf = matches[0].element_handle(timeout=1500)
    resolved = leaf.evaluate_handle('el => {' + _DOM + r"""
        let control=null;
        for(let p=el,d=0;p && d<4 && p!==document.body;p=p.parentElement,d++) {
            if(p.tagName==='BUTTON' || p.tagName==='A' && p.hasAttribute('href') || p.getAttribute('role')==='button'
                || p.hasAttribute('tabindex') && p.tabIndex>=0 || getComputedStyle(p).cursor==='pointer') {control=p;break;}
        }
        let reason='noninteractive';
        if(control) {
            reason='usable';
            if(text(control)!=='重新上传') reason='label_mismatch';
            else if(excluded(control)) reason='excluded';
            else {
                for(let p=control,d=0;p && d<40;p=p.parentElement,d++) {
                    if(p.disabled || p.getAttribute('aria-disabled')==='true') {reason='disabled';break;}
                    if(p.hasAttribute('inert')) {reason='inert';break;}
                    if(getComputedStyle(p).pointerEvents==='none') {reason='pointer_none';break;}
                }
                if(reason==='usable' && !visible(control)) reason='hidden';
                if(reason==='usable') {
                    const r=control.getBoundingClientRect();
                    if(r.right<=0 || r.bottom<=0 || r.left>=innerWidth || r.top>=innerHeight) reason='offscreen';
                    else if(!usable(control)) reason='occluded';
                }
            }
        }
        return {control,reason};
    }""")
    diagnostic['reason'] = resolved.get_property('reason').json_value()
    return leaf, resolved.get_property('control').as_element(), diagnostic


def _prepare_reupload_view(page, proof):
    """One native scroll for this selection's exact offscreen original control."""
    leaf, control, diagnostic = _reupload_shape(page)
    proof['diagnostic']['reupload'] = diagnostic
    diagnostic['scroll_attempted'] = bool(proof.get('reupload_scroll_attempted'))
    if diagnostic['reason']!='offscreen' or control is None:
        return None
    if proof.get('reupload_scroll_attempted'):
        return None
    proof['reupload_scroll_attempted'] = True
    diagnostic['scroll_attempted'] = True
    try:
        generation, url = _GUARDS[page]['generation'], page.url
        document = page.locator('html').element_handle(timeout=1500)
        if document is None or document.evaluate('''(el,nodes)=>el.isConnected && el===document.documentElement &&
            nodes.every(node=>node.isConnected && node.ownerDocument===document)''',[leaf,control]) is not True:
            return 'reupload_scroll_identity_unknown'
        if proof['state']=='invalid' or _GUARDS[page]['generation']!=generation or page.url!=url:
            return 'reupload_scroll_document_changed'
        control.scroll_into_view_if_needed(timeout=1500)
        live_leaf, live_control, after = _reupload_shape(page)
        proof['diagnostic']['reupload_after_scroll'] = after
        same_leaf = live_leaf is not None and live_leaf.evaluate('(el,original)=>el===original',leaf)
        same_control = live_control is not None and live_control.evaluate('(el,original)=>el===original',control)
        retained = _document_retained(document)
        if (proof['state']=='invalid' or _GUARDS[page]['generation']!=generation or page.url!=url or retained is not True):
            return 'reupload_scroll_document_changed'
        if not same_leaf or not same_control:
            return 'reupload_scroll_candidate_changed'
        return None
    except Exception as exc:
        diagnostic['error_type'] = type(exc).__name__
        return 'reupload_scroll_identity_unknown'


def _bind_checking(page):
    diagnostic = {'quick_check_titles': 0, 'reupload_candidates': 0,
                  'reupload_usable': False, 'check_candidates': []}
    titles = _visible(page.get_by_text('快速检测', exact=True))
    diagnostic['quick_check_titles'] = len(titles)
    diagnostic['reupload_candidates'] = len(_visible(page.get_by_text('重新上传', exact=True)))
    if len(titles) != 1:
        return None, diagnostic
    title, candidate = titles[0].element_handle(timeout=1500), titles[0]
    reupload = _reupload(page)
    diagnostic['reupload_usable'] = reupload is not None
    if title is None or reupload is None:
        return None, diagnostic
    for _ in range(5):
        candidate = candidate.locator('xpath=..')
        if candidate.count() != 1 or candidate.evaluate('el => el.tagName') in ('BODY', 'HTML', 'MAIN', 'FORM'):
            break
        shape = candidate.evaluate("el => {" + _DOM + """
            const count=el.querySelectorAll('*').length, role=el.getAttribute('role')||'none';
            return {tag:['DIV','SPAN','SECTION','ASIDE','HEADER','P','UL','LI'].includes(el.tagName)?el.tagName:'OTHER',
                role:['none','region','group','status','progressbar'].includes(role)?role:'other',
                nodes:Math.min(81,count), visible:visible(el),
                eligible:visible(el) && !el.matches('p,header') && count<=80 && text(el).length<=1600};
        }""")
        diagnostic['check_candidates'].append(shape)
        if not shape.get('eligible'):
            continue
        states = _visible(candidate.get_by_text(_STATE))
        same_titles = _visible(candidate.get_by_text('快速检测', exact=True))
        shape.update(status_candidates=len(states), title_candidates=len(same_titles),
                     checking_candidates=sum(bool(_CHECKING.fullmatch(item.inner_text().strip())) for item in states))
        if len(states) == len(same_titles) == 1 and _CHECKING.fullmatch(states[0].inner_text().strip()):
            state = states[0].element_handle(timeout=1500)
            container = candidate.element_handle(timeout=1500)
            if state is not None and container is not None and state.evaluate(
                    '(el,title) => el!==title && !el.contains(title) && !title.contains(el)', title):
                return {'container': container, 'title': title, 'status': state, 'reupload': reupload}, diagnostic
    return None, diagnostic


def observe_upload_check(page, selection_nonce):
    proof = _ATTEMPTS.get(page)
    if proof is None or proof['nonce'] != selection_nonce:
        return {'schema': 'upload_check_transition/v2', 'selection_nonce': selection_nonce,
            'state': 'invalid', 'verified': False, 'reason': 'selection_not_bound',
            'checking_observed': False, 'stable_observations': [], 'diagnostic': {}}
    try:
        proof['current_route'] = _route(page.url)
        proof['generation'] = _GUARDS[page]['generation']
        proof['diagnostic']['begin_document_retained'] = _document_retained(proof['begin_document'])
        proof['diagnostic']['bound_document_retained'] = _document_retained(proof['document'])
        # A rejected observation still reports safe structure on a known route;
        # arbitrary-origin pages are never inspected.
        if proof['current_route'] not in ('upload', 'editor'):
            return _invalidate(proof, 'current_route_outside_known_upload_flow')
        flags = _surface_flags(page)
        if (not isinstance(flags, dict) or any(type(flags.get(key)) is not bool for key in
                ('truncated','failed','transfer','cancel_upload_present','parsing_present'))
                or type(flags.get('independent_percent_count')) is not int):
            return _invalidate(proof, 'surface_unknown')
        proof['diagnostic']['upload_ui'] = flags
        if (proof['state']!='invalid' and proof['bound'] is None and proof['current_route']=='editor'
                and not flags['truncated'] and not flags['failed'] and time.monotonic()<=proof['deadline']
                and proof['routes'][-1]['route']==proof['current_route']):
            error = _arm_document(page, proof)
            if error:
                return _invalidate(proof, error)
            scroll_error = _prepare_reupload_view(page, proof)
            if scroll_error:
                return _invalidate(proof, scroll_error)
        try:
            candidate, structure = _bind_checking(page)
        except Exception as exc:
            proof['diagnostic']['structure'] = {'unknown': True, 'error_type': type(exc).__name__}
            return _invalidate(proof, 'candidate_structure_unknown')
        proof['diagnostic']['structure'] = structure
        if proof['state'] == 'invalid':
            return _reply(proof, reason=proof['reason'])
        if time.monotonic() > proof['deadline']:
            return _invalidate(proof, 'selection_proof_deadline')
        if proof['routes'][-1]['route'] != proof['current_route']:
            return _invalidate(proof, 'route_event_history_unknown')
        if flags['truncated'] or flags['failed']:
            return _invalidate(proof, 'surface_failure_or_truncated')
        if proof['bound'] is None:
            error = _arm_document(page, proof)
            if error:
                return _invalidate(proof, error)
            if proof['current_route'] != 'editor' or flags['transfer'] or candidate is None:
                return _reply(proof)
            generation = _GUARDS[page]['generation']
            document = page.locator('html').element_handle(timeout=1500)
            if (proof['state'] == 'invalid' or _GUARDS[page]['generation'] != generation
                    or _document_retained(document) is not True or _route(page.url) != 'editor'):
                return _invalidate(proof, 'navigation_during_check_binding')
            if not candidate['container'].evaluate('''(container,nodes) =>
                container.isConnected && container.ownerDocument===document &&
                [nodes.title,nodes.status,nodes.reupload].every(el=>el.isConnected && el.ownerDocument===document)
            ''', {key: candidate[key] for key in ('title','status','reupload')}):
                return _invalidate(proof, 'check_binding_nodes_changed')
            proof.update(bound=candidate, document=document, url=page.url,
                bound_generation=generation, state='checking')
            return _reply(proof)
        if (proof['generation'] != proof['bound_generation'] or page.url != proof['url']
                or _document_retained(proof['document']) is not True):
            return _invalidate(proof, 'formal_check_document_or_navigation_changed')
        if flags['transfer']:
            return _invalidate(proof, 'transfer_after_check_binding')
        bound = proof['bound']
        live_reupload = _reupload(page)
        if live_reupload is None or not live_reupload.evaluate('(el,original) => el===original', bound['reupload']):
            return _invalidate(proof, 'original_reupload_changed_or_unusable')
        snapshot = bound['container'].evaluate("(container, nodes) => {" + _DOM + r"""
            const {title,status}=nodes;
            if(!visible(container) || !visible(title) || !visible(status) ||
                !container.contains(title) || !container.contains(status) || text(title)!=='快速检测') return null;
            if(container.querySelectorAll('*').length>80 || text(container).length>1600) return null;
            const values=Array.from(container.querySelectorAll('*')).filter(el=>visible(el) &&
                /^(?:作品未见异常|(?:检测中|正在检测)(?:\s*\d+(?:\.\d+)?\s*%)?[.…。]*)$/.test(text(el)));
            const leaves=values.filter(el=>!values.some(other=>other!==el && el.contains(other)));
            if(leaves.length!==1 || leaves[0]!==status) return null;
            return {checking:/^(?:检测中|正在检测)/.test(text(status)),clean:text(status)==='作品未见异常'};
        }""", {'title': bound['title'], 'status': bound['status']})
        if (not isinstance(snapshot, dict) or any(type(snapshot.get(key)) is not bool for key in ('checking','clean'))):
            return _invalidate(proof, 'original_check_nodes_missing_changed_or_unknown')
        if snapshot['checking']:
            if proof['stable']:
                return _invalidate(proof, 'new_check_after_completion')
            return _reply(proof)
        if not snapshot['clean']:
            return _invalidate(proof, 'original_check_state_unknown')
        # The last native read can dispatch a main-frame navigation callback.
        # No further Page RPC may occur between this final fence and commit.
        retained = _document_retained(proof['document'])
        if proof['state'] == 'invalid':
            return _reply(proof, reason=proof['reason'])
        if (_GUARDS[page]['generation'] != proof['bound_generation'] or page.url != proof['url']
                or retained is not True):
            return _invalidate(proof, 'formal_check_changed_before_stable_commit')
        if time.monotonic() > proof['deadline']:
            return _invalidate(proof, 'selection_proof_deadline')
        proof['stable'] = (proof['stable'] + [dict(snapshot, observation=len(proof['stable'])+1)])[-2:]
        proof['state'] = 'verified' if len(proof['stable']) == 2 else 'clean_wait'
        return _reply(proof)
    except Exception as exc:
        proof['diagnostic']['native_error_type'] = type(exc).__name__
        return _invalidate(proof, 'native_ui_observation_unknown')
