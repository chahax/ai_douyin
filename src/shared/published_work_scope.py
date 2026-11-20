"""Observed public UI scope, shared by discovery, inspection and comment gates."""
import json
import re


DETAIL_SELECTOR='[data-e2e="video-detail"]'

_READ_SCOPE_JS=r"""arg=>{
    const diagnostic={scope_kind:'observed_video_detail',verified:false};
    const reject=reason=>({...diagnostic,reason});
    const url=new URL(location.href);
    if(url.protocol!=='https:'||!['www.douyin.com','douyin.com'].includes(url.host)||
        url.pathname!=='/video/'+arg.postId||!/^[0-9]{1,25}$/.test(arg.postId)||!arg.title)return reject('canonical_or_frozen_title_missing');
    const visible=el=>el.isConnected&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
    const normalize=s=>s.normalize('NFKC').replace(/\s+/g,' ').trim().replace(/\s*\|\s*/g,'|');
    const challengeNames=['安全验证','请完成验证','请完成下列验证','请完成安全验证','拖动滑块完成拼图','登录后观看','登录后可查看','登录即可观看','请先登录'];
    const challenge=Array.from(document.querySelectorAll('div,span,p')).slice(0,4000)
        .filter(el=>!el.children.length&&visible(el)&&challengeNames.includes(el.innerText.trim())).map(el=>el.innerText.trim());
    if(challenge.length)return {...reject('native_challenge_visible'),human_required:true,native_challenge_markers:Array.from(new Set(challenge))};
    const details=Array.from(document.querySelectorAll('[data-e2e="video-detail"]'));
    diagnostic.detail_nodes=details.length;
    if(details.length!==1||!visible(details[0]))return reject('video_detail_not_unique');
    const detail=details[0];
    diagnostic.detail_descendants=detail.querySelectorAll('*').length;
    if(diagnostic.detail_descendants>3000||detail.closest('form,[contenteditable=true],[inert]'))return reject('video_detail_scope_invalid');
    const players=Array.from(detail.querySelectorAll('[data-e2e="player-container"]'));
    diagnostic.player_nodes=players.length;
    if(players.length!==1||!visible(players[0]))return reject('native_player_not_unique');
    const player=players[0],ids=Array.from(player.classList).filter(c=>/^video_[0-9]+$/.test(c));
    diagnostic.player_id_matches=ids.length===1&&ids[0]==='video_'+arg.postId;
    if(!diagnostic.player_id_matches)return reject('native_player_id_mismatch');
    const infos=Array.from(detail.querySelectorAll('[data-e2e="detail-video-info"]'));
    if(infos.length!==1||!visible(infos[0]))return reject('video_info_not_unique');
    const info=infos[0],headings=Array.from(info.querySelectorAll('h1'));
    diagnostic.caption_nodes=headings.length;
    if(headings.length!==1||!visible(headings[0]))return reject('native_caption_not_unique');
    const caption=headings[0],captionText=caption.innerText;
    if(captionText.length>6000)return reject('native_caption_too_large');
    const expected=normalize(arg.title),text=normalize(captionText),notice=normalize('剧情虚构，非真实事件。');
    diagnostic.title_verified=text===expected||text.startsWith(expected+' '+notice);
    if(!diagnostic.title_verified)return reject('native_caption_title_mismatch');
    const videos=Array.from(player.querySelectorAll('video'));
    if(videos.length!==1||!visible(videos[0]))return reject('native_video_not_unique');
    let work=info;
    for(let depth=0;work&&depth<16&&!work.contains(player);depth++)work=work.parentElement;
    if(!work||work===detail||!detail.contains(work)||work.matches('body,html,form,[inert],[contenteditable=true]'))return reject('native_common_scope_missing');
    diagnostic.work_descendants=work.querySelectorAll('*').length;
    if(diagnostic.work_descendants>2000||work.querySelectorAll('video').length!==1||work.querySelectorAll('h1').length!==1||
        work.querySelectorAll('[data-e2e="player-container"]').length!==1||work.querySelectorAll('[data-e2e="detail-video-info"]').length!==1)return reject('native_common_scope_ambiguous');
    const workText=work.innerText;
    if(workText.length>12000)return reject('native_work_text_too_large');
    const aiNodes=Array.from(work.querySelectorAll('span,div,p')).filter(el=>visible(el)&&/^(?:作者声明[：:]?\s*)?(?:内容由\s*AI\s*生成|作品含\s*AI\s*生成内容|内容含\s*AI\s*生成)$/.test(el.innerText.trim()));
    const markers=['审核中','审核不通过','未通过审核','暂不可见','视频已删除','作品不存在'].filter(marker=>workText.includes(marker));
    const video=videos[0];
    if(!visible(work)||!work.isConnected||!player.isConnected||!caption.isConnected||location.pathname!=='/video/'+arg.postId)return reject('native_scope_changed');
    return {...diagnostic,verified:true,reason:'native_id_caption_scope_verified',caption_text:captionText,
        ai_label_visible:aiNodes.length>0,fiction_notice_visible:captionText.includes('剧情虚构，非真实事件。'),
        moderation_markers:markers,review_status:markers.length?'not_clear':'clear',
        player:{ready:video.readyState>=2,error:!!video.error,duration:video.duration>0}};
}"""


def read_observed_work_scope(page,post_id,expected_title):
    """One read-only UI snapshot. Identity success is not full publication proof."""
    args=json.dumps({'postId':str(post_id),'title':expected_title if isinstance(expected_title,str) else ''},ensure_ascii=False)
    result=page.evaluate('()=>('+_READ_SCOPE_JS+')('+args+')')
    caption=result.pop('caption_text','')
    result['hashtag_tokens']=sorted(set(re.findall(r'(?<![#＃])[#＃]\s*(\w+)',caption)))
    return result


def inspect_observed_public_work(page,post_id,expected_title,*,required_hashtags=None,ai_required=True,fiction_required=True):
    result=read_observed_work_scope(page,post_id,expected_title)
    result.update(expected_post_id=str(post_id),expected_title=expected_title,
                  expected_hashtags=list(required_hashtags) if required_hashtags is not None else None)
    if not result.get('verified'):return result
    tags_ok=required_hashtags is None or all(tag in result['hashtag_tokens'] for tag in required_hashtags)
    player=result['player']
    result.update(hashtags_verified=tags_ok,ai_label_origin='unknown; creator selection is recorded separately before submission')
    result['verified']=bool(tags_ok and not result['moderation_markers'] and player['ready'] and not player['error'] and player['duration']
        and (not ai_required or result['ai_label_visible'])and(not fiction_required or result['fiction_notice_visible']))
    result['reason']='observed_work_display_verified'if result['verified']else'observed_work_display_incomplete'
    return result
