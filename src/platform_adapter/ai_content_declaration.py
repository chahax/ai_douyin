"""Select the creator's AI declaration and verify a committed form control.

Text in a caption, hashtag, help message or platform-generated badge is never
evidence of the author's declaration. Unknown/custom UI fails closed.
"""
import re
from weakref import WeakKeyDictionary, ref


AI_LABEL = re.compile(r"^(?:内容由\s*AI\s*生成|内容含\s*AI\s*生成|包含\s*AI\s*生成内容|含有\s*AI\s*生成内容)$", re.I)
ENTRY_LABELS = ("发文助手自主声明", "添加自主声明", "自主声明", "作品声明", "内容声明")
ENTRY = re.compile("^(?:" + "|".join(ENTRY_LABELS) + ")$")
CONTROL_ROLES = ("checkbox", "radio", "switch")
DECLARATION_TITLE = '对作品内容添加声明'
_CONFIRMED_NATIVE = WeakKeyDictionary()
_CONFIRMED_ROW = WeakKeyDictionary()
_ROW_PAGE_GUARDS = WeakKeyDictionary()
_DIAGNOSTICS = WeakKeyDictionary()

# Only semantic declaration entries are scanned, never arbitrary page AI text.
# All row reads are bounded and read-only. No class names or platform layout
# guesses participate in this proof.
_ROW_DOM_HELPERS = r"""
const entryNames = ['发文助手自主声明','添加自主声明','自主声明','作品声明','内容声明'];
const aiValue = /^(?:内容由\s*AI\s*生成|内容含\s*AI\s*生成|包含\s*AI\s*生成内容|含有\s*AI\s*生成内容)$/i;
const text = el => (el.innerText || '').trim().replace(/\s+/g, ' ');
const excluded = el => {
    let p=el, depth=0;
    for (; p && depth<40; p=p.parentElement,depth++) {
        if (p.matches('input,textarea,video,audio,canvas,article,p,blockquote,pre,[role=article],[role=document],'+
            '[contenteditable]:not([contenteditable=false])')) return true;
        const area=(p.getAttribute('aria-label')||'')+' '+(p.getAttribute('title')||'');
        if (/预览|简介|作品描述|正文|作者|\bpreview\b|\bdescription\b|\bcaption\b|\bauthor\b/i.test(area)) return true;
    }
    return !!p;
};
const visible = el => {
    if (!el || !el.isConnected || !el.getClientRects().length) return false;
    let p=el, depth=0;
    for (; p && depth<40; p=p.parentElement,depth++) {
        const s=getComputedStyle(p);
        if (p.hidden || p.hasAttribute('inert') || p.getAttribute('aria-hidden')==='true' ||
            s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0) return false;
    }
    return !p;
};
const semanticEntry = el => {
    if (!el || !visible(el) || excluded(el)) return false;
    const clickable = el.tagName==='BUTTON' || el.getAttribute('role')==='button' ||
        (el.tagName==='A' && (el.hasAttribute('href') || typeof el.onclick==='function'));
    if (!clickable || el.disabled || el.getAttribute('aria-disabled')==='true') return false;
    const name=(el.getAttribute('aria-label')||text(el)).trim();
    return entryNames.includes(name) && (!text(el) || entryNames.includes(text(el)));
};
const smallRow = row => row && !['BODY','HTML','MAIN','FORM','ARTICLE','P','NAV','ASIDE','HEADER','FOOTER'].includes(row.tagName)
    && !row.matches('[role=dialog],[role=listbox],[role=menu]') && visible(row) && !excluded(row)
    && row.querySelectorAll('*').length<=24 && text(row).length<=160
    && !row.querySelector('input,textarea,select,video,audio,canvas,article,[role=article],'+
        '[contenteditable]:not([contenteditable=false])');
"""

_CUSTOM_ROW_DOM = r"""
const exactLabels=()=>{
    const nodes=Array.from(document.querySelectorAll('span,div,label,dt,button,a,[role=button]'));
    if(nodes.length>1200) return [];
    const known=nodes.filter(el=>visible(el) && !excluded(el) && entryNames.includes(text(el)));
    return known.filter(el=>!known.some(other=>other!==el && el.contains(other)));
};
const usableTrigger=el=>{
    if(!el || !visible(el) || excluded(el) || el.disabled || el.getAttribute('aria-disabled')==='true') return false;
    if(!['DIV','SPAN','BUTTON','A'].includes(el.tagName)) return false;
    const style=getComputedStyle(el);
    if(style.pointerEvents==='none' || !(el.tagName==='BUTTON' || el.getAttribute('role')==='button' ||
        typeof el.onclick==='function' || style.cursor==='pointer' ||
        (el.hasAttribute('tabindex') && el.tabIndex>=0))) return false;
    const r=el.getBoundingClientRect();
    // Native ElementHandle.click scrolls this exact original trigger into view.
    // Offscreen binding itself is never success; unique popup confirmation is
    // still mandatory. An onscreen occluded trigger is rejected now.
    if(r.right<=0 || r.bottom<=0 || r.left>=innerWidth || r.top>=innerHeight) return true;
    const hit=document.elementFromPoint((Math.max(0,r.left)+Math.min(innerWidth,r.right))/2,
        (Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2);
    return !!hit && (hit===el || el.contains(hit));
};
const customParts=(row,label,expected)=>{
    if(!smallRow(row) || !visible(label) || excluded(label) || !entryNames.includes(text(label))) return null;
    const branches=Array.from(row.children).filter(visible);
    if(branches.length!==2) return null;
    const a=branches.find(el=>el===label || el.contains(label));
    const b=branches.find(el=>el!==a);
    if(!a || !b || text(a)!==text(label) || text(b)!==expected) return null;
    const nodes=[b,...b.querySelectorAll('span,div,output,dd,strong,em,small')];
    if(nodes.length>7) return null;
    const values=nodes.filter(el=>visible(el) && !excluded(el) && text(el)===expected);
    const leaves=values.filter(el=>!values.some(other=>other!==el && el.contains(other)));
    if(leaves.length!==1) return null;
    const compact=s=>s.replace(/\s+/g,'');
    if(compact(text(row))!==compact(text(a)+text(b)) && compact(text(row))!==compact(text(b)+text(a))) return null;
    return {value:leaves[0],branch:b};
};
"""


def _diagnostic(page, stage, **details):
    previous = _DIAGNOSTICS.get(page, {})
    _DIAGNOSTICS[page] = dict(previous, schema='ai_setting_identity/v1', stage=stage, **details)


def _unverified(page, reason):
    result = {'verified': False, 'reason': reason}
    if page in _DIAGNOSTICS:
        result['diagnostic'] = dict(_DIAGNOSTICS[page])
    return result


def _capture_custom_setting(page, entry, guard):
    """Bind the original exact label, placeholder slot and actionable trigger."""
    _diagnostic(page, 'custom_capture', bound=False)
    try:
        candidate = entry.evaluate_handle('label => {' + _ROW_DOM_HELPERS + _CUSTOM_ROW_DOM + r"""
            const labels=exactLabels();
            const diagnostic={labelCount:labels.length,rowCandidates:0,matchedRows:0,triggerFound:false,offscreen:false};
            if(labels.length!==1 || labels[0]!==label) return {diagnostic};
            let row=label.parentElement;
            for(let depth=0;row && depth<3;row=row.parentElement,depth++) {
                diagnostic.rowCandidates++;
                const parts=customParts(row,label,'请选择自主声明');
                if(!parts) continue;
                diagnostic.matchedRows++;
                // The original value branch is the stable clickable shell;
                // cursor styling inherited by an inner text leaf is not its identity.
                let trigger=parts.branch;
                for(let distance=0;trigger && distance<4;trigger=trigger.parentElement,distance++) {
                    if(usableTrigger(trigger) && (trigger===parts.branch || trigger.contains(parts.branch))) {
                        const rect=trigger.getBoundingClientRect();diagnostic.triggerFound=true;
                        diagnostic.offscreen=rect.right<=0 || rect.bottom<=0 || rect.left>=innerWidth || rect.top>=innerHeight;
                        return {label,row,value:parts.branch,trigger,document:document.documentElement,diagnostic};
                    }
                    if(trigger===row) break;
                }
            }
            return {diagnostic};
        }""")
        details = candidate.get_property('diagnostic').json_value()
        if isinstance(details, dict):
            _diagnostic(page, 'custom_capture', **{key: details.get(key) for key in
                ('labelCount','rowCandidates','matchedRows','triggerFound','offscreen')})
        if not isinstance(details, dict) or details.get('triggerFound') is not True:
            _diagnostic(page, 'custom_capture_rejected', identity='original_structure_not_qualified')
            return None
        handles = {key: candidate.get_property(key).as_element()
                   for key in ('label', 'row', 'value', 'trigger', 'document')}
        if any(handle is None for handle in handles.values()):
            _diagnostic(page, 'custom_capture_rejected', identity='missing_original_parts')
            return None
        _diagnostic(page, 'custom_captured', bound=True, identity='original_label_row_value_trigger')
        return dict(kind='custom', entry=handles['label'], trigger=handles['trigger'],
                    document=handles['document'], rows=[(handles['row'], handles['value'])],
                    url=page.url, generation=guard['generation'], clicked=False)
    except Exception:
        _diagnostic(page, 'custom_capture_rejected', identity='structure_unknown')
        return None


def _read_custom_setting(page, proof, row, value):
    observed = row.evaluate('(row,args)=>{' + _ROW_DOM_HELPERS + _CUSTOM_ROW_DOM + r"""
        const {label,value,trigger,originalDocument,originalContainer}=args;
        const d={document:false,label:false,value:false,trigger:false,unique:false,
            declarationPopupClosed:!visible(originalContainer),structure:false,
            globalVisibleRoleCount:0,globalRolesTruncated:false};
        d.document=originalDocument===document.documentElement && originalDocument.isConnected;
        d.label=label.isConnected && label.ownerDocument===document && row.contains(label);
        d.value=value.isConnected && value.ownerDocument===document && row.contains(value);
        d.trigger=trigger.isConnected && trigger.ownerDocument===document &&
            (trigger===row || row.contains(trigger)) && usableTrigger(trigger);
        const labels=exactLabels();d.unique=labels.length===1 && labels[0]===label;
        const popups=Array.from(document.querySelectorAll('[role=dialog],[role=listbox],[role=menu]'));
        // Unrelated creator menus are diagnostic only. The proof belongs to
        // this exact declaration container, not every role popup on the page.
        d.globalVisibleRoleCount=popups.slice(0,40).filter(visible).length;
        d.globalRolesTruncated=popups.length>40;
        if(!d.document || !d.label || !d.value || !d.trigger || !d.unique || !d.declarationPopupClosed) return d;
        const parts=customParts(row,label,'内容由AI生成');
        d.structure=!!parts && parts.branch===value &&
            (trigger===value || trigger.contains(value) || value.contains(trigger));
        return d;
    }""", {'label': proof['entry'], 'value': value, 'trigger': proof['trigger'],
            'originalDocument': proof['document'], 'originalContainer': proof['container']})
    if not isinstance(observed, dict):
        _diagnostic(page, 'custom_read_rejected', identity='structure_unknown')
        return None
    _diagnostic(page, 'custom_read', **{key: observed.get(key) is True for key in
                ('document', 'label', 'value', 'trigger', 'unique', 'declarationPopupClosed', 'structure')},
                globalVisibleRoleCount=max(0,min(40,int(observed.get('globalVisibleRoleCount',0)))),
                globalRolesTruncated=observed.get('globalRolesTruncated') is True)
    # The native read RPC can dispatch a navigation callback. Do not return its
    # earlier snapshot after that callback cleared or fenced this exact proof.
    guard = _ROW_PAGE_GUARDS.get(page)
    if (guard is None or guard['generation'] != proof['generation'] or page.url != proof['url']
            or _CONFIRMED_ROW.get(page) is not proof):
        _diagnostic(page, 'custom_read_rejected', identity='navigation_or_proof_changed')
        return None
    if all(observed.get(key) is True for key in ('document','label','value','trigger','unique','declarationPopupClosed','structure')):
        return {'verified': True, 'label': '内容由AI生成',
                'method': 'confirmed_original_custom_setting_value'}
    return None


def _row_guard(page):
    guard = _ROW_PAGE_GUARDS.get(page)
    if guard is not None:
        return guard
    try:
        weak_page = ref(page)
        guard = {'generation': 0}
        def navigated(frame):
            current = weak_page()
            if current is not None and frame == current.main_frame:
                guard['generation'] += 1
                _CONFIRMED_ROW.pop(current, None)
                _CONFIRMED_NATIVE.pop(current, None)
                _diagnostic(current, 'navigation_invalidated', identity='generation_changed')
        page.on('framenavigated', navigated)
        _ROW_PAGE_GUARDS[page] = guard
        return guard
    except Exception:
        return None


def _capture_setting_entry(page, entry):
    """Bind before clicking this invocation's actual declaration entry."""
    guard = _row_guard(page)
    if guard is None:
        return None
    try:
        resolved = entry.evaluate_handle("el => {" + _ROW_DOM_HELPERS + """
            let p=el;
            for(let depth=0;p && depth<3;p=p.parentElement,depth++) {
                if(semanticEntry(p)) return p;
            }
            return null;
        }""")
        original = resolved.as_element()
        if original is None:
            return _capture_custom_setting(page, entry, guard)
        candidates = original.evaluate_handle("entry => {" + _ROW_DOM_HELPERS + r"""
            const rows=[];
            let p=entry.parentElement;
            for(let depth=0;p && depth<3;p=p.parentElement,depth++) {
                if(!smallRow(p)) continue;
                const branches=Array.from(p.children).filter(visible);
                if(branches.length!==2) continue;
                const value=branches.find(branch=>branch!==entry && !branch.contains(entry));
                if(!value || !['SPAN','DIV','OUTPUT','DD','STRONG','EM','SMALL'].includes(value.tagName)
                    || excluded(value) || value.querySelectorAll('*').length>6 || text(value).length>40
                    || aiValue.test(text(value)) || value.matches('button,a,[role=button]')
                    || value.querySelector('button,a,input,textarea,select,[role=button]')) continue;
                const compact = s=>s.replace(/\s+/g,'');
                if(compact(text(p))!==compact(text(entry)+text(value)) && compact(text(p))!==compact(text(value)+text(entry))) continue;
                rows.push({row:p,value});
                break;
            }
            return rows;
        }""")
        rows = []
        for key, handle in candidates.get_properties().items():
            if key.isdigit():
                row, value = handle.get_property('row').as_element(), handle.get_property('value').as_element()
                if row is not None and value is not None:
                    rows.append((row, value))
        if not rows:
            return None
        return {'entry': original, 'rows': rows, 'url': page.url,
                'generation': guard['generation']}
    except Exception:
        return None


def _read_confirmed_row(page):
    proof = _CONFIRMED_ROW.get(page)
    if proof is None:
        return None
    guard = _ROW_PAGE_GUARDS.get(page)
    try:
        if (guard is None or guard['generation'] != proof['generation'] or page.url != proof['url']
                or proof['container'].is_visible()):
            _CONFIRMED_ROW.pop(page, None)
            _diagnostic(page, 'row_rejected', identity='navigation_or_popup_changed')
            return None
        # This is solely an unmounted-native fallback. A retained original
        # radio/checkbox with contrary or unknown state cannot be overridden by
        # a rendered value beside the entry.
        if proof['original'].evaluate('el => el.isConnected') is not False:
            _diagnostic(page, 'row_rejected', identity='native_still_connected')
            return None
        for row, original_value in proof['rows']:
            if proof.get('kind') == 'custom':
                return _read_custom_setting(page, proof, row, original_value)
            value = row.evaluate("(row, args) => {" + _ROW_DOM_HELPERS + r"""
                const {entry,value}=args;
                if(!smallRow(row) || !semanticEntry(entry) || entry.ownerDocument!==document || !row.contains(entry)
                    || !value || !visible(value) || excluded(value) || !row.contains(value)
                    || entry.contains(value) || value.contains(entry) || !aiValue.test(text(value))) return null;
                const entries=Array.from(document.querySelectorAll('button,[role=button],a'));
                if(entries.length>120) return null;
                const known=entries.filter(semanticEntry);
                if(known.length!==1 || known[0]!==entry) return null;
                const popups=Array.from(document.querySelectorAll('[role=dialog],[role=listbox],[role=menu]'));
                if(popups.length>40 || popups.some(visible)) return null;
                const controls=Array.from(row.querySelectorAll('button,[role=button],a,[role=checkbox],[role=radio],[role=switch]'));
                if(controls.some(control=>visible(control) && control!==entry && !entry.contains(control))) return null;
                const candidates=Array.from(row.querySelectorAll('span,div,output,dd,strong,em,small')).filter(el=>
                    el!==entry && !entry.contains(el) && !el.contains(entry) && visible(el) && !excluded(el) && aiValue.test(text(el)));
                const leaves=candidates.filter(el=>!candidates.some(other=>other!==el && el.contains(other)));
                if(leaves.length!==1 || (leaves[0]!==value && !value.contains(leaves[0]))) return null;
                let a=entry,b=value;
                while(a.parentElement!==row && a.parentElement) a=a.parentElement;
                while(b.parentElement!==row && b.parentElement) b=b.parentElement;
                if(a.parentElement!==row || b.parentElement!==row || a===b) return null;
                const branches=Array.from(row.children).filter(visible);
                const compact=s=>s.replace(/\s+/g,'');
                if(branches.length!==2 || (compact(text(row))!==compact(text(entry)+text(value))
                    && compact(text(row))!==compact(text(value)+text(entry)))) return null;
                // The smallest common setting row, with independent branches,
                // is required; ordinary page prose is never read as the value.
                return text(value);
            }""", {'entry': proof['entry'], 'value': original_value})
            if isinstance(value, str) and AI_LABEL.fullmatch(value):
                return {'verified': True, 'label': value,
                        'method': 'confirmed_original_setting_row_value'}
    except Exception:
        _diagnostic(page, 'row_rejected', identity='original_structure_unreadable')
        return None
    return None


def _visible(locator):
    if locator.count() > 40:
        raise ValueError('声明候选过多，无法有界确认')
    return [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]


def _controls(page):
    found = []
    for role in CONTROL_ROLES:
        found.extend((role, item) for item in _visible(page.get_by_role(role, name=AI_LABEL)))
    return found


def _selected(role, control):
    if role == "switch":
        state = control.get_attribute("aria-checked")
        if state not in ('true', 'false'):
            raise ValueError('AI 声明开关状态未知')
        return state == "true"
    state = control.is_checked()
    if type(state) is not bool:
        raise ValueError('AI 声明控件状态未知')
    return state


def _popup(control):
    return control.evaluate("el => !!el.closest('[role=dialog], [role=listbox], [role=menu]')")


def _nonrole_dialog(page):
    """An exact visible title blocks readback even when structure is unknown."""
    titles = _visible(page.get_by_text(DECLARATION_TITLE, exact=True))
    if not titles:
        return None
    if len(titles) != 1:
        return {'container': None, 'reason': 'AI 声明弹窗标题不唯一'}
    candidate = titles[0]
    for _ in range(8):
        candidate = candidate.locator('xpath=..')
        if candidate.count() != 1 or candidate.evaluate('el => el.tagName') in ('BODY', 'HTML'):
            break
        if not candidate.is_visible():
            break
        same_titles = _visible(candidate.get_by_text(DECLARATION_TITLE, exact=True))
        controls = _controls(candidate)
        confirms = _visible(candidate.get_by_role('button', name=re.compile(r'^(确定|确认)$')))
        cancels = _visible(candidate.get_by_role('button', name=re.compile(r'^取消$')))
        if len(same_titles) == len(controls) == len(confirms) == len(cancels) == 1:
            return {'container': candidate, 'control': controls[0], 'confirm': confirms[0]}
    return {'container': None, 'reason': '可见声明弹层结构未唯一绑定'}


def _native_state(original):
    return original.evaluate("""el => ({connected:el.isConnected, tag:el.tagName,
        type:el.getAttribute('type'), checked:el.checked,
        aria_label:(el.getAttribute('aria-label')||'').slice(0,100),
        labels:Array.from(el.labels||[]).slice(0,3).map(label =>
            (label.innerText||label.textContent||'').trim().slice(0,100))})""")


def _label_identity(state):
    return state.get('aria_label', ''), tuple(state.get('labels', []))


def _read_confirmed_native(page):
    proof = _CONFIRMED_NATIVE.get(page)
    if proof is None:
        return None
    role, original, container = proof['role'], proof['original'], proof['container']
    try:
        if (page.url != proof['url'] or container.is_visible() or not container.evaluate(
                '(container, original) => container.isConnected && container.contains(original)', original)):
            return None
        state = _native_state(original)
        if (isinstance(state, dict) and state.get('connected') is True and state.get('tag') == 'INPUT'
                and state.get('type') == role and state.get('checked') is True
                and _label_identity(state) == proof['label_identity']
                and any(AI_LABEL.fullmatch(text.strip()) for text in
                    [state.get('aria_label', ''), *state.get('labels', [])] if isinstance(text, str))):
            return {'verified': True, 'label': '内容由AI生成',
                    'method': 'confirmed_hidden_original_control'}
    except Exception:
        pass
    return None


def read_ai_declaration(page):
    """Read only. An unchecked option or an unconfirmed dialog is not success."""
    pending = _nonrole_dialog(page)
    if pending is not None:
        _CONFIRMED_ROW.pop(page, None)
        _CONFIRMED_NATIVE.pop(page, None)
        _diagnostic(page, 'pending_popup', identity='not_committed')
        return _unverified(page, pending.get('reason', 'AI 声明弹窗尚未提交'))
    known = _CONFIRMED_NATIVE.get(page)
    if known is not None and (page.url != known['url'] or known['container'].is_visible()):
        _CONFIRMED_ROW.pop(page, None)
        _CONFIRMED_NATIVE.pop(page, None)
        return _unverified(page, '声明页面已导航或原声明弹窗再次可见，未确认提交')
    controls = _controls(page)
    if len(controls) > 1:
        return _unverified(page, 'AI 声明控件不唯一，未确认声明')
    if len(controls) == 1:
        role, control = controls[0]
        if _selected(role, control) and not _popup(control):
            return {"verified": True, "label": "内容由AI生成", "method": role + "_checked"}
    if not controls:
        committed = _read_confirmed_native(page)
        if committed is not None:
            return committed
        committed = _read_confirmed_row(page)
        if committed is not None:
            return committed
    # Native selects expose their selected option; custom comboboxes must expose
    # both a declaration label and the committed value, with the popup closed.
    for control in _visible(page.get_by_role("combobox", name=ENTRY)):
        if control.get_attribute("aria-expanded") == "true" or _popup(control):
            continue
        value = control.evaluate("""el => el.tagName === 'SELECT'
            ? (el.selectedOptions[0]?.textContent || '')
            : (el.innerText || el.getAttribute('aria-valuetext') || '')""")
        if AI_LABEL.fullmatch((value or "").strip()):
            return {"verified": True, "label": value.strip(), "method": "declaration_selected_value"}
    return _unverified(page, "未读到已生效的作者 AI 声明控件；页面出现 AI 字样不算声明成功")


def _current_option(page, role, original):
    """Resolve again, but never switch to a replacement or another named option."""
    controls = _controls(page)
    if len(controls) != 1 or controls[0][0] != role:
        raise ValueError('AI 声明控件缺失或不唯一，停止选择')
    control = controls[0][1]
    if not original.evaluate('el => el.isConnected') or not control.evaluate(
            '(el, original) => el === original', original):
        raise ValueError('AI 声明原控件已脱离或替换，停止选择')
    return control, _selected(role, control)


def _wait_selected(page, role, original):
    for index in range(10):
        control, selected = _current_option(page, role, original)
        if selected:
            return True
        if index < 9:
            page.wait_for_timeout(200)
    return False


def _bound_visible_label(page, original):
    # Native labels is the browser's actual association, not nearby AI text.
    indices = original.evaluate("""el => {
        const all=Array.from(document.querySelectorAll('label'));
        return Array.from(el.labels || []).filter(label => {
            let p=label, d=0;
            for (; p && d<40; p=p.parentElement,d++) {
                const s=getComputedStyle(p);
                if (p.hidden || p.hasAttribute('inert') || s.display==='none' || s.visibility==='hidden' || Number(s.opacity)===0) return false;
            }
            return !p && label.getClientRects().length>0;
        }).map(label=>all.indexOf(label));
    }""")
    if not isinstance(indices, list) or len(indices) != 1 or type(indices[0]) is not int or indices[0] < 0:
        return None
    labels = page.locator('label')
    if indices[0] >= labels.count():
        return None
    label = labels.nth(indices[0])
    if not label.is_visible() or not label.evaluate(
            '(label, original) => Array.from(original.labels || []).includes(label)', original):
        return None
    return label


def _choose(page):
    controls = _controls(page)
    if len(controls) > 1:
        raise ValueError("AI 声明控件不唯一，停止以免选择错误")
    if controls:
        role, control = controls[0]
        if not _selected(role, control):
            original = control.element_handle(timeout=5000)
            if original is None:
                raise ValueError('AI 声明原控件无法绑定')
            try:
                if role == "switch":
                    control.click(timeout=5000)
                else:
                    control.set_checked(True, timeout=5000)
            except Exception:
                # Playwright can throw before an asynchronous checked state commits.
                # Read first; a successful delayed selection must never be toggled twice.
                pass
            if not _wait_selected(page, role, original):
                label = _bound_visible_label(page, original)
                if label is None:
                    return None  # Existing control failed; never reopen an entry to retry it.
                _, selected = _current_option(page, role, original)
                if not selected:
                    try:
                        label.click(timeout=5000)  # One bound-label fallback, never force.
                    except Exception:
                        pass  # Observe the resulting state before deciding; never retry.
                if not _wait_selected(page, role, original):
                    return None
        return True
    for control in _visible(page.get_by_role("combobox", name=ENTRY)):
        if control.evaluate("el => el.tagName") == "SELECT":
            labels = control.locator("option").all_text_contents()
            matches = [label for label in labels if AI_LABEL.fullmatch(label.strip())]
            if len(matches) != 1:
                raise ValueError("AI 声明下拉项缺失或不唯一")
            control.select_option(label=matches[0], timeout=5000)
            return True
        control.click(timeout=5000)
        break
    options = _visible(page.get_by_role("option", name=AI_LABEL))
    if len(options) == 1:
        options[0].click(timeout=5000)
        return True
    if len(options) > 1:
        raise ValueError("AI 声明选项不唯一")
    return False


def _confirm_dialog(page, entry_proof=None):
    # Only confirm a dialog actually containing the named AI declaration control.
    # Never click a page-wide '确认', '发布' or unrelated agreement button.
    pending = _nonrole_dialog(page)
    if pending is not None:
        _row_guard(page)  # Invalidate cached native/row proof on later navigation.
        if pending['container'] is None:
            raise ValueError(pending['reason'])
        role, control = pending['control']
        if not _selected(role, control):
            raise ValueError('声明弹层中的AI选项未选中，停止确认')
        original = control.element_handle(timeout=5000)
        container = pending['container'].element_handle(timeout=5000)
        if original is None or container is None:
            raise ValueError('声明原控件无法绑定，停止确认')
        native = _native_state(original) if role in ('radio', 'checkbox') else None
        pending['confirm'].click(timeout=5000)
        pending['container'].wait_for(state='hidden', timeout=5000)
        if _nonrole_dialog(page) is not None:
            raise ValueError('声明弹窗尚未关闭，停止发布')
        if isinstance(native, dict):
            _CONFIRMED_NATIVE[page] = {'role': role, 'original': original, 'container': container,
                'label_identity': _label_identity(native), 'url': page.url}
        guard = _ROW_PAGE_GUARDS.get(page)
        if (entry_proof is not None and guard is not None and isinstance(native, dict)
                and native.get('tag') == 'INPUT' and native.get('type') == role
                and guard['generation'] == entry_proof['generation'] and page.url == entry_proof['url']
                and (entry_proof.get('kind') != 'custom' or entry_proof.get('clicked') is True)):
            _CONFIRMED_ROW[page] = dict(entry_proof, container=container, original=original)
            _diagnostic(page, 'popup_confirmed_closed', identity='original_radio_and_row_bound')
        return
    dialogs = [dialog for dialog in _visible(page.get_by_role("dialog")) if _controls(dialog)]
    if len(dialogs) > 1:
        raise ValueError('AI 声明弹窗不唯一，停止发布')
    for dialog in dialogs:
        buttons = _visible(dialog.get_by_role("button", name=re.compile(r"^(确定|确认|完成|保存)$")))
        if len(buttons) == 1:
            buttons[0].click(timeout=5000)
            dialog.wait_for(state="hidden", timeout=5000)
        elif len(buttons) > 1:
            raise ValueError("声明弹窗有多个确认按钮，停止发布")


def set_ai_declaration(page):
    current = read_ai_declaration(page)
    if current["verified"]:
        return current  # Do not toggle a declaration already selected.
    entry_proof = None
    chosen = _choose(page)
    if chosen is None:
        return _unverified(page, 'AI 声明原控件未确认选中；有限补救后停止')
    if not chosen and _controls(page):
        return _unverified(page, 'AI 声明原控件未确认选中；有限补救后停止')
    if not chosen:
        # Support the publishing-page entry and the older Advanced Settings entry.
        for title in (*ENTRY_LABELS, "高级设置", *ENTRY_LABELS):
            entries = _visible(page.get_by_text(title, exact=True))
            if len(entries) > 1:
                raise ValueError("声明入口不唯一，停止发布")
            if entries:
                entry_proof = _capture_setting_entry(page, entries[0]) if title in ENTRY_LABELS else None
                trigger = entry_proof['trigger'] if entry_proof and entry_proof.get('kind') == 'custom' else entries[0]
                trigger.click(timeout=5000)
                if entry_proof and entry_proof.get('kind') == 'custom':
                    entry_proof['clicked'] = True
                    _diagnostic(page, 'custom_trigger_clicked', identity='original_trigger')
                attempt = _choose(page)
                if attempt is None:
                    return _unverified(page, 'AI 声明原控件未确认选中；有限补救后停止')
                if attempt:
                    chosen = True
                    break
                if entry_proof and entry_proof.get('kind') == 'custom':
                    _diagnostic(page, 'custom_popup_rejected', identity='unique_ai_option_not_bound')
                    return _unverified(page, '原设置入口未打开可唯一确认的AI声明弹层，停止')
    if chosen:
        try:
            _confirm_dialog(page, entry_proof)
        except Exception as exc:
            if not entry_proof or entry_proof.get('kind') != 'custom':
                raise
            _diagnostic(page, 'custom_confirm_rejected', identity='popup_not_committed',
                        error_type=type(exc).__name__[:40])
            return _unverified(page, '原AI声明弹层未唯一确认并关闭，停止发布')
    # Allow the committed form state to render, but never infer it from a click.
    for _ in range(10):
        current = read_ai_declaration(page)
        if current["verified"]:
            return current
        page.wait_for_timeout(200)
    return current
