"""Bounded, credential-free evidence for an actually exposed verification UI."""
import math


class DouyinChallengeProbeError(RuntimeError):
    code = 'page_probe_failed'


VERIFICATION_STOP_CODES = frozenset({'human_required', 'verification_ui_unconfirmed'})


class DouyinVerificationSurfaceError(RuntimeError):
    code = 'verification_ui_unconfirmed'

    def __init__(self, evidence):
        super().__init__('验证容器阻塞页面，但未确认可操作验证码；可能空白、加载失败或读取不明，请核对页面与网络。')
        self.evidence = evidence


# This runs inside a known verification frame/dialog. It returns no text or URLs.
CONTENT_PROBE_FUNCTION = r'''(root => {
  if (!root) return 'blank';
  const visible = (el, interactive=false) => {
    const r=el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom <= 0 || r.right <= 0
        || r.top >= innerHeight || r.left >= innerWidth) return false;
    let opacity=1;
    for (let n=el;n;n=n.parentElement) {
      const s=getComputedStyle(n);
      opacity*=Number(s.opacity || 1);
      if (s.display==='none' || s.visibility==='hidden' || opacity<=.01001) return false;
    }
    if (interactive) {
      if (getComputedStyle(el).pointerEvents==='none') return false;
      const x=Math.max(0,r.left), y=Math.max(0,r.top);
      const w=Math.min(innerWidth,r.right)-x, h=Math.min(innerHeight,r.bottom)-y;
      if (![[.5,.5],[.25,.25],[.75,.75]].some(([fx,fy])=>{
        const hit=document.elementFromPoint(x+w*fx,y+h*fy);
        return hit===el || el.contains(hit);
      })) return false;
    }
    return true;
  };
  const text=(root.innerText || '').slice(0,8192);
  if (/加载失败|网络异常|网络错误|无法加载|请求失败|load failed|network error/i.test(text)) return 'load_failed';
  const instructions=/拖动滑块|按住滑块|完成拼图|依次点击|点击两个|选择.*相同|请完成.*验证|安全验证|验证你是人类/.test(text);
  const controls=Array.from(root.querySelectorAll('button,input,[role="slider"],[role="button"],[draggable="true"],[tabindex="0"][class*="slider"],[class*="drag-icon"],[class*="drag-block"],.captcha-slider-btn'))
    .filter(el=>visible(el,true) && !el.disabled && el.getAttribute('aria-disabled')!=='true'
      && !/^(关闭|取消|返回|刷新|重试|close|cancel|retry)$/i.test((el.innerText || el.getAttribute('aria-label') || '').trim()));
  const media=Array.from(root.querySelectorAll('img,canvas')).filter(el=>visible(el));
  const loaded=media.some(el=>el.tagName==='IMG' ? el.complete && el.naturalWidth>16 : el.width>16 && el.height>16);
  const slider=controls.some(el=>el.getAttribute('role')==='slider');
  if (instructions && controls.length && (loaded || slider || controls.some(el=>el.tagName==='INPUT'))) return 'challenge_ready';
  if (/加载中|正在加载|loading/i.test(text) || media.some(el=>el.tagName==='IMG' && !el.complete)) return 'loading';
  if (!text.trim() && !loaded && !controls.length) return 'blank';
  return 'unconfirmed';
})'''


CHALLENGE_PROBE_SCRIPT = r'''(() => {
  // data-douyin-visible-challenge: v2 checks ancestors, clipping and hit testing.
  const selector = 'iframe[src*="/verifycenter/"], iframe[src*="/captcha/"], iframe[src*="captcha"]';
  const frames = Array.from(document.querySelectorAll(selector));
  const excluded = {}, metrics = [];
  let actionable = 0, dialogs = 0;
  const dialogStates = [];
  const parent = el => el.parentElement || el.getRootNode()?.host || null;
  function exposed(el) {
    const box = el.getBoundingClientRect();
    let left = Math.max(0, box.left), top = Math.max(0, box.top);
    let right = Math.min(innerWidth, box.right), bottom = Math.min(innerHeight, box.bottom);
    let reason = '';
    let opacity = 1;
    if (box.width < 24 || box.height < 24) reason = 'too_small';
    if (!reason && (right-left < 24 || bottom-top < 24)) reason = 'outside_viewport';
    for (let node = el; node; node = parent(node)) {
      const style = getComputedStyle(node);
      opacity *= Number(style.opacity || 1);
      if (style.display === 'none' || (node === el && (style.visibility === 'hidden'
          || style.visibility === 'collapse')) || opacity <= 0.01001) {
        reason = 'ancestor_hidden'; break;
      }
      if (node !== el && (/(hidden|clip|scroll|auto)/.test(style.overflowX)
          || /(hidden|clip|scroll|auto)/.test(style.overflowY))) {
        const clip = node.getBoundingClientRect();
        if (/(hidden|clip|scroll|auto)/.test(style.overflowX)) {
          left = Math.max(left, clip.left); right = Math.min(right, clip.right);
        }
        if (/(hidden|clip|scroll|auto)/.test(style.overflowY)) {
          top = Math.max(top, clip.top); bottom = Math.min(bottom, clip.bottom);
        }
        if (!reason && (right-left < 24 || bottom-top < 24)) reason = 'clipped';
      }
    }
    let hits = 0;
    if (!reason) {
      if (getComputedStyle(el).pointerEvents === 'none') reason = 'not_interactive';
      else {
        for (const [fx,fy] of [[.5,.5],[.25,.25],[.75,.25],[.25,.75],[.75,.75]]) {
          const hit = document.elementFromPoint(left+(right-left)*fx, top+(bottom-top)*fy);
          if (hit === el || el.contains(hit)) hits++;
        }
        if (!hits) reason = 'occluded';
      }
    }
    return {reason:reason || 'actionable', x:Math.round(box.x), y:Math.round(box.y),
      width:Math.round(box.width), height:Math.round(box.height), hit_points:hits};
  }
  for (const frame of frames) {
    const data = exposed(frame);
    if (data.reason === 'actionable') actionable++;
    else excluded[data.reason] = (excluded[data.reason] || 0)+1;
    if (metrics.length < 6) metrics.push({kind:'verification_iframe',index:frames.indexOf(frame),...data});
  }
  // Text in a video title is not a verification dialog.
  for (const dialog of document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')) {
    if (/安全验证|请完成验证|拖动滑块|点击两个形状相同的物体/.test(dialog.innerText || '')
        && exposed(dialog).reason === 'actionable') {
      dialogs++;
      dialogStates.push(CONTENT_PROBE_PLACEHOLDER(dialog));
    }
  }
  return {version:2, blocking:actionable > 0 || dialogs > 0, frame_count:frames.length,
    actionable_frames:actionable, visible_dialogs:dialogs, excluded, frames:metrics, dialog_states:dialogStates};
})()'''.replace('CONTENT_PROBE_PLACEHOLDER', CONTENT_PROBE_FUNCTION)


def probe_challenge_page(page):
    """Worker-side read only inspection; isolated from account/task state."""
    raw = page.evaluate(CHALLENGE_PROBE_SCRIPT)
    states = list(raw.pop('dialog_states', []))
    # Inspect exposed frames only, bounded even on a malformed page.
    for metric in raw.get('frames', []):
        if metric['reason'] != 'actionable':
            continue
        try:
            element = page.locator('iframe[src*="/verifycenter/"], iframe[src*="/captcha/"], iframe[src*="captcha"]').nth(metric['index']).element_handle(timeout=500)
            frame = element.content_frame() if element else None
            state = frame.evaluate(f'({CONTENT_PROBE_FUNCTION})(document.body)') if frame else 'unavailable'
        except Exception:
            state = 'unavailable'
        metric['content_state'] = state
        states.append(state)
    raw.update(version=3, surface_states=states)
    return raw

_REASONS = {'too_small','outside_viewport','ancestor_hidden','clipped','not_interactive','occluded','actionable'}


def _number(value, lower=0, upper=10000):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise DouyinChallengeProbeError('验证界面探测返回无效几何数据。')
    return max(lower,min(upper,int(value)))


def probe_douyin_challenge(page):
    try:
        method = getattr(page, 'probe_douyin_challenge', None)
        raw = method() if callable(method) else page.locator('').evaluate(CHALLENGE_PROBE_SCRIPT)
    except Exception as exc:
        raise DouyinChallengeProbeError('无法读取验证界面状态；未据此判定需要验证码或登录失效。') from exc
    if not isinstance(raw,dict) or not isinstance(raw.get('blocking'),bool):
        raise DouyinChallengeProbeError('验证界面探测回执不完整；未将未知状态写成无验证。')
    try:
        result = dict(version=3,blocking=raw['blocking'],frame_count=_number(raw['frame_count']),
            actionable_frames=_number(raw['actionable_frames']),visible_dialogs=_number(raw['visible_dialogs']))
        if result['blocking'] != bool(result['actionable_frames'] or result['visible_dialogs']):
            raise ValueError('inconsistent probe')
        result['excluded']={k:_number(v) for k,v in raw.get('excluded',{}).items() if k in _REASONS}
        result['frames']=[]
        allowed_states = {'challenge_ready','loading','load_failed','blank','unavailable','unconfirmed'}
        states = raw.get('surface_states', [])
        if not isinstance(states, list) or any(s not in allowed_states for s in states):
            raise ValueError('invalid content states')
        states = states[:12]
        # Legacy geometric evidence is never sufficient for a ready CAPTCHA.
        result['surface_state'] = ('clear' if not result['blocking'] else
            'challenge_ready' if 'challenge_ready' in states else
            next((s for s in ('load_failed','unavailable','loading','blank') if s in states), 'unconfirmed'))
        result['surface_states'] = states
        for frame in raw.get('frames',[])[:6]:
            if frame.get('reason') not in _REASONS: continue
            result['frames'].append(dict(kind='verification_iframe',reason=frame['reason'],
                x=_number(frame['x'],-1000000,1000000),y=_number(frame['y'],-1000000,1000000),
                width=_number(frame['width'],0,1000000),height=_number(frame['height'],0,1000000),
                hit_points=_number(frame['hit_points'],0,5)))
            state = frame.get('content_state')
            if state in allowed_states:
                result['frames'][-1]['content_state'] = state
        return result
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        raise DouyinChallengeProbeError('验证界面探测回执不完整。') from exc


def confirmed_douyin_challenge(page):
    first=probe_douyin_challenge(page)
    first['observations']=1
    first['confirmations']=0
    if not first['blocking']: return first
    ready = first['surface_state'] == 'challenge_ready'
    current = first
    for observation, delay in enumerate((400, 800, 1600, 3200), start=2):
        page.wait_for_timeout(delay)
        current=probe_douyin_challenge(page)
        current['observations']=observation
        current['confirmations']=0
        if not current['blocking']:
            return current
        if current['surface_state'] == 'challenge_ready':
            if ready:
                current['confirmations']=2
                return current
            ready=True
        else:
            ready=False
    # A surface without confirmed usable content remains blocked, never clear.
    if current['surface_state'] == 'challenge_ready':
        current['surface_state']='unconfirmed'
    return current
