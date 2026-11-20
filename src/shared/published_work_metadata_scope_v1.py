"""Frozen complete-caption verification on the existing observed work scope.

The pinned old reader supplies every structural/identity/challenge gate. Only
its fiction-first prefix condition is deferred to a complete metadata equality
check below. No navigation, request, field, framework state or media URL reads.
"""
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata


ROOT=Path(__file__).resolve().parents[2]
_PREFIX="""    const expected=normalize(arg.title),text=normalize(captionText),notice=normalize('剧情虚构，非真实事件。');
    diagnostic.title_verified=text===expected||text.startsWith(expected+' '+notice);
    if(!diagnostic.title_verified)return reject('native_caption_title_mismatch');"""
_CAPTURE="""    diagnostic.caption_text=captionText;
    diagnostic.url=url.origin+url.pathname;
    diagnostic.origin=url.origin;
    diagnostic.path=url.pathname;
    diagnostic.complete_metadata_contract_deferred=true;"""
_PLAYER="player:{ready:video.readyState>=2,error:!!video.error,duration:video.duration>0}"
_NUMERIC="""player:{ready:video.readyState>=2,error:!!video.error,duration:video.duration>0,
            numeric_duration:Number.isFinite(video.duration)?video.duration:null,ready_state:video.readyState,
            video_width:video.videoWidth,video_height:video.videoHeight,visible_video_count:videos.length,src_read:false}"""


def _bytes(ref):
    if not isinstance(ref,dict) or set(ref)!={'path','sha256'}:
        raise ValueError('scope_reference_invalid')
    raw=Path(ref['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('scope_source_changed')
    return raw


def _scope_script(base_scope_source,base_scope_snapshot):
    if Path(base_scope_source['path']).resolve()!=ROOT/'src/shared/published_work_scope.py':
        raise ValueError('scope_source_path_invalid')
    source=_bytes(base_scope_source)
    if source!=_bytes(base_scope_snapshot):
        raise ValueError('scope_snapshot_changed')
    tree=ast.parse(source.decode('utf-8-sig'))
    candidates=[node.value for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='_READ_SCOPE_JS' for t in node.targets)]
    if len(candidates)!=1:
        raise ValueError('scope_script_not_unique')
    script=ast.literal_eval(candidates[0])
    if not isinstance(script,str) or script.count(_PREFIX)!=1 or script.count(_PLAYER)!=1:
        raise ValueError('scope_script_contract_changed')
    return script.replace(_PREFIX,_CAPTURE).replace(_PLAYER,_NUMERIC)


def normalized_caption_core(value):
    """Only NFKC, known U+200B formatting and whitespace are ignored."""
    return ''.join(unicodedata.normalize('NFKC',value).replace('\u200b','').split())


def build_metadata_scope_script(post_id,metadata,*,base_scope_source,base_scope_snapshot):
    if not isinstance(post_id,str) or not re.fullmatch(r'\d{10,24}',post_id):
        raise ValueError('post_id_invalid')
    if not isinstance(metadata.get('title'),str) or not metadata['title'] or len(metadata['title'])>1000:
        raise ValueError('metadata_title_invalid')
    if not isinstance(metadata.get('description'),str) or not metadata['description'] or len(metadata['description'])>6000:
        raise ValueError('metadata_description_invalid')
    tags=metadata.get('hashtags')
    if not isinstance(tags,list) or len(tags)!=5 or len(set(tags))!=5 or any(not isinstance(t,str) or not re.fullmatch(r'\w{1,100}',t) for t in tags):
        raise ValueError('metadata_hashtags_invalid')
    args=json.dumps(dict(postId=post_id,title=metadata['title']),ensure_ascii=False)
    return '()=>('+_scope_script(base_scope_source,base_scope_snapshot)+')('+args+')'


def inspect_current_metadata_scope(page,post_id,metadata,*,base_scope_source,base_scope_snapshot,
                                   expected_duration_seconds,duration_tolerance_seconds=.5):
    script=build_metadata_scope_script(post_id,metadata,base_scope_source=base_scope_source,base_scope_snapshot=base_scope_snapshot)
    if (type(expected_duration_seconds) not in {int,float} or not math.isfinite(expected_duration_seconds) or expected_duration_seconds<=0
            or type(duration_tolerance_seconds) not in {int,float} or not math.isfinite(duration_tolerance_seconds) or not 0<=duration_tolerance_seconds<=.5):
        raise ValueError('expected_duration_invalid')
    value=page.evaluate(script)
    if not isinstance(value,dict):
        raise ValueError('scope_response_invalid')
    result=dict(value)
    structural=result.get('verified') is True
    caption=result.get('caption_text')
    raw=caption if isinstance(caption,str) and len(caption)<=6000 else ''
    normalized=unicodedata.normalize('NFKC',raw).replace('\u200b','')
    tokens=re.findall(r'(?<!#)#\s*(\w+)',normalized)
    core=re.sub(r'(?<!#)#\s*\w+','',normalized)
    expected=normalized_caption_core(metadata['title']+metadata['description'])
    tags_ok=sorted(tokens)==sorted(metadata['hashtags']) and len(tokens)==len(set(tokens))==5
    full=bool(raw and normalized_caption_core(core)==expected and tags_ok)
    player=result.get('player',{})
    d=player.get('numeric_duration')
    numeric=(structural and type(d) in {int,float} and math.isfinite(d) and abs(d-expected_duration_seconds)<=duration_tolerance_seconds
             and type(player.get('ready_state')) is int and player['ready_state']>=2 and player.get('error') is False
             and type(player.get('video_width')) is int and player['video_width']>0 and type(player.get('video_height')) is int and player['video_height']>0)
    result.update(schema='published_work_metadata_scope/v1',structure_verified=structural,expected_post_id=post_id,
        expected_title=metadata['title'],expected_hashtags=metadata['hashtags'],
        caption_text=raw,hashtag_tokens=tokens,hashtags_verified=tags_ok,full_caption_verified=full,title_verified=full,
        numeric_duration_verified=bool(numeric),base_scope_source=base_scope_source,base_scope_snapshot=base_scope_snapshot,
        private_state_read=False,media_src_read=False,whole_body_caption_fallback=False)
    passed=bool(structural and full and numeric and result.get('ai_label_visible') is True and result.get('fiction_notice_visible') is True
                and result.get('review_status')=='clear' and result.get('moderation_markers')==[])
    result['verified']=passed
    if structural:
        result['reason']='frozen_full_caption_scope_verified' if passed else 'frozen_full_caption_mismatch' if not full else 'scoped_work_display_incomplete'
    return result
