"""Build H3 shot inputs only from signed-off source mappings and local reference assets."""
import hashlib
import json
from pathlib import Path

PERSON_VIEWS = ('canonical', 'front_full', 'side_full', 'back_full', 'face_detail')
PLACE_VIEWS = ('canonical', 'front', 'reverse', 'side', 'layout')
QUALITY = ('cast', 'age_appearance', 'space_props', 'audio_channels', 'no_baked_text', 'transition')
CHANNELS = {'旁白': 'narration', '心声': 'inner_voice', '对白': 'dialogue', '画外对白': 'dialogue', '画外童声': 'dialogue'}


def fingerprint(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def check(value, message):
    if not value:
        raise ValueError(message)


def bound(root, item):
    check(isinstance(item, dict) and item.get('path') and item.get('sha256'), '缺少文件或校验值')
    path = (root / item['path']).resolve()
    check(path.is_relative_to(root.resolve()) and path.is_file(), '引用文件缺失或越界')
    check(hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], '引用文件已变化')
    return path


def evidence(root, receipt, target):
    record = json.loads(bound(root, receipt).read_text(encoding='utf8'))
    check(record.get('approved') is True and record.get('reviewer') and record.get('target') == target, '审核对象或版本不符')
    return record


def approved_asset(root, key, card, kind):
    slots = PERSON_VIEWS if kind == 'person' else PLACE_VIEWS
    check(card.get('id') == key and card.get('kind') == kind and card.get('status') == 'approved', '未批准的参考资产 '+key)
    check(card.get('origin') == ('individual_turnaround' if kind == 'person' else 'empty_scene_plate'), '参考图类型不符')
    if kind == 'person':
        check(card.get('age_source') and card.get('appearance_design'), '缺年龄依据或造型')
    else:
        check(card.get('layout_design'), '场景缺少布局')
    views = card['views']
    for slot in slots:
        bound(root, views.get(slot))
    check(len({views[s]['sha256'] for s in slots if s != 'canonical'}) == len(slots)-1, '多个角度复用了同一图')
    check(card.get('canonical_sha256') == views['canonical']['sha256'], '基准图不匹配')
    subject = {k:v for k,v in card.items() if k != 'review'}
    evidence(root, card.get('review'), fingerprint(subject))
    return views['canonical']


def voice_items(units):
    result = []
    for u in units:
        check(hashlib.sha256(u['text'].encode()).hexdigest()==u['sha256'], '原段文字校验失败')
        end = u['start']
        for a in u['audio_items']:
            lo, hi = a['start'], a['end']
            check(end<=lo<hi<=u['start']+len(u['text']) and a['parent']==u['parent'], '声音区间重叠或越界')
            check(u['text'][lo-u['start']:hi-u['start']]==a['text'], '声音文字偏离原段')
            check(a['channel'] in CHANNELS and a['speaker'], '未知声道或缺署名')
            channel = CHANNELS[a['channel']]
            result.append(dict(channel=channel, speaker=a['speaker'], text=a['text'], unit=u['id'], start=lo, end=hi,
                               delivery='on_screen' if a['channel']=='对白' else 'off_screen'))
            end = hi
    return result


def compile_shot(root, project, shot, units, mode):
    check(mode in ('pilot','batch'), '未知生产阶段')
    check([s for s in project['shots'] if s['id']==shot['id']]==[shot], '分镜不在当前方案内')
    check(shot['units'] == [u['id'] for u in units] and shot['source_hash']==fingerprint(units), '分镜原文已变化')
    mapping = {k:v for k,v in shot.items() if k != 'review'}
    evidence(root, shot.get('review'), fingerprint(mapping))
    cast = shot['visible']
    check(isinstance(cast,list) and len(cast)==len(set(cast)) and shot['visual'].strip(), '可见角色或动作不明确')
    scene=project['places'][shot['place']]
    refs=[dict(subject=scene['id'],asset=approved_asset(root,scene['id'],scene,'place'))]
    for name in cast:
        refs.append(dict(subject=name,asset=approved_asset(root,name,project['people'][name],'person')))
    check(len(refs)<=9 and len({r['asset']['sha256'] for r in refs})==len(refs), '参考超过上限或多个身份共用基准图')
    audio=voice_items(units)
    aliases=project.get('aliases',{})
    check(all(key not in project['people'] and value in project['people'] for key,value in aliases.items()), '别称与角色卡冲突')
    check(shot.get('voice_placement') is not None and len(shot['voice_placement'])==len(audio), '声画位置未逐句核对')
    for line,placement in zip(audio,shot['voice_placement']):
        check(placement in ('on_screen','off_screen'), '不明声音位置')
        if line['delivery']=='off_screen':
            check(placement=='off_screen','画外声或心声被改为口型')
        names=[aliases.get(n,n) for n in line['speaker'].split('／')]
        roles=[n for n in names if n in project['people']]
        if placement=='on_screen':
            check(len(roles)==len(names) and all(n in cast for n in roles),'有口型的说话人未在镜内')
        line['role_ids']=roles
        line['delivery']=placement
    if mode=='batch':
        verify_pilot(root,project)
    return dict(id=shot['id'], visual=dict(place=scene['id'],visible_people=cast,action=shot['visual'],refs=refs,
                                           composition='rebuild_from_approved_references',render_text=False),
                audio=[{k:a[k] for k in ('speaker','role_ids','text','channel','delivery')} for a in audio],
                subtitles=dict(stage='postproduction',lines=[a['text'] for a in audio]))


def verify_pilot(root,project):
    payload={k:v for k,v in project.items() if k!='pilot_review'}
    review=evidence(root,project.get('pilot_review'),fingerprint(payload))
    cuts=review.get('clips',[])
    shots={s['id']:s for s in project['shots']}
    check(len(cuts)>=2,'跨场试片不足')
    places=[]
    sequence=[s['id'] for s in project['shots']]
    positions=[]
    for clip in cuts:
        shot=shots[clip['shot']]
        check(shot['place']==clip['place'],'试片场景不匹配')
        path=bound(root,clip['file'])
        check(path.suffix.lower()=='.mp4','缺少实生成试片')
        places.append(clip['place'])
        positions.append(sequence.index(clip['shot']))
    check(any(b==a+1 and places[i]!=places[i+1] for i,(a,b) in enumerate(zip(positions,positions[1:]))) and len(set(places))>=2 and len({c['file']['sha256'] for c in cuts})==len(cuts)
          and all(review.get('checks',{}).get(k) is True for k in QUALITY), '跨场实测未通过')



