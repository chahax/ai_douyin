"""Browser DOM checks only. Unknown layouts remain unverified; no platform API."""
import re
import time
from urllib.parse import urlparse
from src.shared.published_work_discovery import canonical_video

FICTION_NOTICE = '剧情虚构，非真实事件。'
EDITORS = ("[contenteditable][data-placeholder='添加作品简介']",
           ".editor[contenteditable='true']", "div[data-slate-editor='true']")


def declared_description(description, fictional_story):
    if not fictional_story:
        return description
    body = description.replace(FICTION_NOTICE, '').strip()
    return FICTION_NOTICE + ('\n' + body if body else '')


def video_id(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.douyin.com', 'douyin.com'):
        return ''
    match = re.fullmatch(r'/video/(\d+)/?', parsed.path)
    return match.group(1) if match else ''


def inspect_published_video(page, expected_id, ai_required=True, fiction_required=True,
                            required_hashtags=None, expected_title=None):
    result = {'verified': False, 'url': page.url, 'expected_post_id': expected_id,
              'expected_title':expected_title,'expected_hashtags':list(required_hashtags)if required_hashtags is not None else None}
    if not expected_id or video_id(page.url) != expected_id:
        return dict(result, reason='未进入对应作品详情页')
    # A single semantic work container is required; never scan the entire feed/body.
    layout_read = getattr(page,'evaluate',None)
    result['layout'] = layout_read('''() => {
        const visible=n=>!!n.getClientRects().length && getComputedStyle(n).visibility!=='hidden';
        const nodes=Array.from(document.querySelectorAll('article,[role=article],[data-e2e-vid],[data-video-id]'));
        return {visibleVideos:Array.from(document.querySelectorAll('video')).filter(visible).length,
          candidates:nodes.filter(visible).slice(0,12).map(n=>({tag:['ARTICLE','DIV','SECTION','LI'].includes(n.tagName)?n.tagName:'OTHER',
            role:n.getAttribute('role')==='article'?'article':'other',videos:n.querySelectorAll('video').length,
            captions:n.querySelectorAll('figcaption,[data-e2e="video-desc"]').length,
            explicitId:n.hasAttribute('data-e2e-vid')||n.hasAttribute('data-video-id')})),truncated:nodes.length>12};
    }''') if callable(layout_read) else {'unavailable':True}
    articles = page.get_by_role('article').filter(has=page.locator('video'))
    if articles.count()==0:
        # These explicit work identity attributes already occur in the project
        # playback UI reader. Never substitute an unscoped feed/body container.
        candidates=page.locator('[data-e2e-vid], [data-video-id]')
        if candidates.count()>12:return dict(result,reason='作品身份容器过多，待核验')
        matching=[]
        for i in range(min(candidates.count(),12)):
            node=candidates.nth(i)
            if node.is_visible() and node.evaluate('(el,id)=>(el.getAttribute("data-e2e-vid")||el.getAttribute("data-video-id"))===id',expected_id) and node.locator('video').count()==1:
                matching.append(node)
        if len(matching)==1:
            work=matching[0]
        else:
            if not matching and isinstance(expected_title,str) and expected_title:
                from src.shared.published_work_scope import inspect_observed_public_work
                observed=inspect_observed_public_work(page,expected_id,expected_title,required_hashtags=required_hashtags,
                    ai_required=ai_required,fiction_required=fiction_required)
                return dict(result,**observed)
            return dict(result,reason='准确作品容器未唯一绑定，待核验')
    elif articles.count()==1 and articles.nth(0).is_visible():
        work=articles.nth(0)
    else:
        return dict(result,reason='无法唯一定位作品正文，待核验')
    videos = work.locator('video')
    if videos.count() != 1:
        return dict(result, reason='作品播放器不唯一')
    text = work.inner_text()
    if len(text)>12000:return dict(result,reason='作品正文超出有界核验')
    markers = [m for m in ('审核中', '审核不通过', '未通过审核', '暂不可见', '视频已删除', '作品不存在') if m in text]
    ai = work.get_by_text(re.compile(r'^(?:作者声明[：:]?\s*)?(?:内容由AI生成|作品含AI生成内容|内容含AI生成)$'))
    ai_visible = any(ai.nth(i).is_visible() for i in range(ai.count()))
    fiction_visible = FICTION_NOTICE in text
    caption_text=''
    if required_hashtags is not None or expected_title is not None:
        captions=work.locator('figcaption,[data-e2e="video-desc"]')
        if captions.count()>8:return dict(result,reason='作品说明候选过多')
        visible=[captions.nth(i) for i in range(min(captions.count(),8)) if captions.nth(i).is_visible()]
        if len(visible)!=1:
            return dict(result,reason='作品说明未唯一绑定，不能用推荐或评论话题代替')
        caption_text=visible[0].inner_text()
        if len(caption_text)>6000:return dict(result,reason='作品说明超出有界读回')
        fiction_visible=FICTION_NOTICE in caption_text
    tokens=set(re.findall(r'(?<![#＃])[#＃]\s*(\w+)',caption_text))
    tags_verified=required_hashtags is None or all(tag in tokens for tag in required_hashtags)
    title_verified=expected_title is None or expected_title in caption_text or work.get_by_text(expected_title,exact=True).count()==1
    player = videos.nth(0).evaluate('(v) => ({ready: v.readyState >= 2, error: !!v.error, duration: v.duration > 0})')
    result.update(ai_label_visible=ai_visible, fiction_notice_visible=fiction_visible,
                  moderation_markers=markers, player=player, hashtags_verified=tags_verified,
                  title_verified=title_verified,review_status='clear' if not markers else 'not_clear',
                  ai_label_origin='unknown; creator selection is recorded separately before submission')
    result['verified'] = bool(not markers and player['ready'] and not player['error'] and player['duration']
                              and (not ai_required or ai_visible) and (not fiction_required or fiction_visible)
                              and tags_verified and title_verified)
    result['reason'] = '作品展示检查通过（不等于完整声画审核）' if result['verified'] else '声明、播放器或审核状态尚未核实完整'
    return result


def wait_for_published_video(page,expected_id,*,ai_required=True,fiction_required=True,
        required_hashtags=None,expected_title=None,evidence_path=None,dispatch_guard=None):
    """At most eight guarded UI reads/20 seconds, never a navigation or action retry."""
    expected=f'https://www.douyin.com/video/{expected_id}'
    started=time.monotonic();observations=[];attempts=0;latest={'verified':False};stop='read_limit'
    for index in range(8):
        if time.monotonic()-started>=20:stop='time_limit';break
        if dispatch_guard:dispatch_guard()
        if canonical_video(page.url)!=expected:
            latest={'verified':False,'reason':'作品URL已变化','expected_post_id':expected_id};stop='wrong_work';break
        try:
            attempts+=1
            read=getattr(page,'inspect_published_video',None)
            kwargs=dict(ai_required=ai_required,fiction_required=fiction_required,
                required_hashtags=required_hashtags,expected_title=expected_title)
            latest=read(expected_id,**kwargs) if callable(read) else inspect_published_video(page,expected_id,**kwargs)
        except Exception as exc:
            latest={'verified':False,'reason':'作品UI读取尚未确认','error_type':type(exc).__name__}
        if dispatch_guard:dispatch_guard()
        if canonical_video(page.url)!=expected:
            latest=dict(latest,verified=False,reason='核验读取时作品URL已变化');stop='wrong_work'
            observations.append({'attempt':attempts,'verified':False,'reason':'wrong_work'});break
        if time.monotonic()-started>=20:
            latest=dict(latest,verified=False,reason='作品UI读取超出等待窗口');stop='time_limit';break
        blocked=bool(latest.get('moderation_markers')) or latest.get('review_status')=='not_clear'
        player_error=(latest.get('player')or{}).get('error') is True
        observations.append({'attempt':index+1,'verified':latest.get('verified') is True,
            'reason':str(latest.get('reason',''))[:160],'player_ready':(latest.get('player')or{}).get('ready') is True,
            'review_blocked':blocked})
        if blocked:stop='moderation_pending_or_rejected';break
        if player_error:stop='player_error';break
        if latest.get('verified') is True:stop='verified';break
        if latest.get('human_required') is True:stop='human_required';break
        if index<7:
            remaining=20-(time.monotonic()-started)
            if remaining<=0:stop='time_limit';break
            if dispatch_guard:dispatch_guard()
            page.wait_for_timeout(min(2000,int(remaining*1000)))
    if evidence_path and stop!='wrong_work':
        try:
            if dispatch_guard:dispatch_guard()
            if canonical_video(page.url)!=expected:
                latest=dict(latest,verified=False,reason='保存证据前作品URL已变化');stop='wrong_work'
            elif callable(getattr(page,'screenshot',None)):
                page.screenshot(path=evidence_path,full_page=False)
            else:page._cmd('screenshot',path=evidence_path,full_page=False)
            if dispatch_guard:dispatch_guard()
            if canonical_video(page.url)!=expected:
                latest=dict(latest,verified=False,reason='保存证据时作品URL已变化');stop='wrong_work'
        except Exception as exc:
            latest=dict(latest,verified=False,reason='作品UI证据未保存',error_type=type(exc).__name__);stop='evidence_unavailable'
    return dict(latest,verification_wait={'attempts':attempts,
        'elapsed_seconds':round(time.monotonic()-started,3),'stop_reason':stop,'observations':observations})
