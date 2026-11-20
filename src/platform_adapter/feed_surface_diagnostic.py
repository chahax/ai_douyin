"""Read-only, bounded diagnostics of the fixed recommendation homepage."""
import json
from pathlib import Path

FRAME_SELECTOR = 'iframe[src*="/verifycenter/"], iframe[src*="/captcha/"], iframe[src*="captcha"]'

CONTENT = r'''() => ({
  ready_state:document.readyState,
  text:(document.body?.innerText||'').slice(0,800),
  controls:Array.from(document.querySelectorAll('button,input,[role="slider"],[role="button"],[class*="drag"],[class*="slider"]')).slice(0,30).map(n=>({
    tag:n.tagName,role:n.getAttribute('role'),classes:String(n.className).slice(0,150),
    width:Math.round(n.getBoundingClientRect().width),height:Math.round(n.getBoundingClientRect().height)})),
  media:Array.from(document.querySelectorAll('img,canvas')).slice(0,12).map(n=>({tag:n.tagName,
    complete:n.complete===true,natural_width:n.naturalWidth||0,width:n.width,height:n.height}))
})'''


def inspect_worker_page(page):
    """No click, play, token, input value, URL query, or storage access."""
    from .douyin_challenge import probe_challenge_page
    result = {'challenge': probe_challenge_page(page)}
    result['page'] = page.evaluate('''() => ({host:location.hostname,path:location.pathname,
        ready_state:document.readyState,visibility:document.visibilityState,viewport_width:innerWidth,viewport_height:innerHeight,
        feed_cards:document.querySelectorAll('[data-e2e="feed-item"]').length,
        videos:Array.from(document.querySelectorAll('video')).slice(0,6).map(v=>({
          current_time:v.currentTime,paused:v.paused,muted:v.muted,ready_state:v.readyState}))})''')
    from .douyin_recommendation_playback import FEED_SNAPSHOT_JS
    feed = page.evaluate(FEED_SNAPSHOT_JS) or {}
    result['active_feed'] = {k: feed[k] for k in ('found','reason','kind','video_id',
        'current_time','duration','paused','ready_state') if k in feed}
    result['video_layout'] = page.evaluate('''() => Array.from(document.querySelectorAll('video')).slice(0,6).map(v=>{
        const ancestors=[];let n=v;for(let i=0;n&&i<6;i++,n=n.parentElement){
          const r=n.getBoundingClientRect();ancestors.push({tag:n.tagName,e2e:n.getAttribute('data-e2e'),
            vid:n.getAttribute('data-e2e-vid'),x:r.x,y:r.y,width:r.width,height:r.height});}
        return {ancestors};})''')
    result['frames'] = []
    for metric in result['challenge'].get('frames', [])[:6]:
        if metric.get('reason') != 'actionable':
            continue
        item = {'index': metric['index']}
        try:
            element = page.locator(FRAME_SELECTOR).nth(metric['index']).element_handle(timeout=1000)
            frame = element.content_frame() if element else None
            item['content'] = frame.evaluate(CONTENT) if frame else {'error': 'frame_unavailable'}
        except Exception as exc:
            item['error_type'] = type(exc).__name__
        result['frames'].append(item)
    return result


def capture_feed_surface(page, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    samples = []
    for delay in (0, 3000, 7000):
        if delay:
            page.wait_for_timeout(delay)
        samples.append(page._cmd('inspect_feed_surface').get('evidence', {}))
    screenshots = []
    for item in samples[-1].get('frames', [])[:2]:
        index = item['index']
        target = directory / f'verification_{index}.png'
        try:
            page._cmd('screenshot', path=str(target), selector=f':nth-match(:is({FRAME_SELECTOR}), {index+1})', full_page=False)
        except Exception as exc:
            screenshots.append({'index': index, 'error_type': type(exc).__name__})
        else:
            screenshots.append({'index': index, 'path': str(target)})
    result = {'samples': samples, 'screenshots': screenshots,
              'clicked': False, 'play_requested': False, 'account_resume_requested': False}
    (directory/'EVIDENCE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'evidence_path':str(directory/'EVIDENCE.json'), 'sample_count':len(samples),
            'screenshots':screenshots, 'clicked':False, 'play_requested':False}
