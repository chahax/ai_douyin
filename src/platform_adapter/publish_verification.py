"""Browser DOM checks only. Unknown layouts remain unverified; no platform API."""
import re
from urllib.parse import urlparse

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


def inspect_published_video(page, expected_id, ai_required=True, fiction_required=True):
    result = {'verified': False, 'url': page.url, 'expected_post_id': expected_id}
    if not expected_id or video_id(page.url) != expected_id:
        return dict(result, reason='未进入对应作品详情页')
    # A single semantic work container is required; never scan the entire feed/body.
    articles = page.get_by_role('article').filter(has=page.locator('video'))
    if articles.count() != 1 or not articles.nth(0).is_visible():
        return dict(result, reason='无法唯一定位作品正文，待核验')
    work = articles.nth(0)
    videos = work.locator('video')
    if videos.count() != 1:
        return dict(result, reason='作品播放器不唯一')
    text = work.inner_text()
    markers = [m for m in ('审核中', '审核不通过', '未通过审核', '暂不可见', '视频已删除', '作品不存在') if m in text]
    ai = work.get_by_text(re.compile(r'^(?:作者声明[：:]?\s*)?(?:内容由AI生成|作品含AI生成内容|内容含AI生成)$'))
    ai_visible = any(ai.nth(i).is_visible() for i in range(ai.count()))
    fiction_visible = FICTION_NOTICE in text
    player = videos.nth(0).evaluate('(v) => ({ready: v.readyState >= 2, error: !!v.error, duration: v.duration > 0})')
    result.update(ai_label_visible=ai_visible, fiction_notice_visible=fiction_visible,
                  moderation_markers=markers, player=player,
                  ai_label_origin='unknown; creator selection is recorded separately before submission')
    result['verified'] = bool(not markers and player['ready'] and not player['error'] and player['duration']
                              and (not ai_required or ai_visible) and (not fiction_required or fiction_visible))
    result['reason'] = '作品展示检查通过（不等于完整声画审核）' if result['verified'] else '声明、播放器或审核状态尚未核实完整'
    return result
