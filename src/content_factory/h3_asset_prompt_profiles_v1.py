"""Explicit production presentation of a verified offline asset/state package.

The structured state remains in the manifest. Only condition.prompt changes:
natural performance directions replace debug IDs/tables, and pinned child voice
descriptions are explicit soft prompts, never approved waveform references.
"""
from copy import deepcopy

from . import h3_asset_flow_v2 as flow

VERSION='h3_asset_performance_prompt/v1'
WORDS=dict(left_bed_edge='左侧床沿',center_bed_edge='中央床沿',
    rear_right_of_younger_brother='弟弟身后偏右',low_front_right='右前方低位',
    source_previous_gaze='前镜中的注视方向',own_right_wrist='自己的右手腕',
    own_left_wrist='自己的左手腕',own_hands='自己的双手',toward_door='门的方向',
    cotton_swab='棉签',seated='坐着',standing='站立',kneeling='低位屈膝',
    lying='躺着',crouching='蹲着',unknown='姿态沿用实际承接画面')
PARTS=dict(right_wrist='右手腕',left_wrist='左手腕',wrist='手腕',
    right_hand='右手',left_hand='左手',hand='手',hands='双手',wrists='双手腕',
    forearm='前臂',left_forearm='左前臂',right_forearm='右前臂')


def _phrase(value,names):
    text=WORDS.get(value,value) if isinstance(value,str) else str(value)
    for cid,name in sorted(names.items(),key=lambda p:-len(p[0])):
        text=text.replace(cid,name)
    return text


def apply(manifest,graph,profile_binding):
    original=manifest['compiled_prompt']
    if (flow.digest(graph)!=manifest['graph_sha256'] or graph['condition']['inputs']['prompt']!=original
            or flow.core.sha(original)!=manifest['compiled_prompt_utf8_sha256']
            or manifest['voice_resolution']['control_mode']!='prompt_only'
            or manifest['voice_resolution']['voices'] or manifest['routes']['audio_references']!=0
            or manifest['routes']['audio_vae_input_connected'] is not False):
        raise ValueError('verified_explicit_prompt_only_package_required')
    entry=flow.core._entries(manifest['source_case'])[0]
    req=flow.core.validate_entry(entry);names=entry['character_names']
    cast=manifest['required_actor_assets'];profiles=flow._bound(profile_binding)
    if profiles.get('schema')!='library_voice_profiles/v1' or set(profiles.get('profiles',{}))!=set(cast):
        raise ValueError('fixed_full_cast_child_voice_profiles_required')
    pp=profiles['profiles']
    for cid,p in pp.items():
        if (p.get('actor')!=cid or p.get('type') not in ('male_child','female_child')
                or not isinstance(p.get('description'),str) or not p['description'].strip()
                or flow.core.QUOTE.search(p['description']) or '<' in p['description']):
            raise ValueError('matched_child_voice_profile_description_required')
    lib=manifest['library_resolution'];refs=manifest['references'];guide=manifest['guide']
    state=manifest['actor_state'];rows=state['state_plan_result']['beats']
    camera=state['camera_beats'];framing=dict(face_close='头肩近景',hands_close='手部近景',medium='中景',wide='全景',detail='局部细节')
    if len(camera)!=len(rows):raise ValueError('complete_camera_state_pairing_required')
    lines=['真人写实中国家庭短剧，竖屏9:16，普通话、原生同步对白与现场声。引号内是实际台词，其余是表演与摄影说明。人物看着互动对象，自由正常切镜。',
        '时间与地点：'+entry.get('story_time','同一傍晚')+'，'+lib['environment_description'].get('name','孩子们的房间')+'。']
    for cid in cast:
        tags='、'.join(r['tag'] for r in refs if r.get('actor_id')==cid)
        lines.append(names[cid]+'的身份参考是'+tags+'，这些视角是同一人。外形衣着：'+lib['character_descriptions'][cid]['description'])
    lines.append('环境参考为'+'、'.join(r['tag'] for r in refs if r['kind']=='place')+'。'+lib['environment_description']['description'])
    lines.append(refs[-1]['tag']+'是前段真实尾帧，当前房间布局、人物位置与身体姿态从这里继续。角色肖像只提供身份，当前身体沿用此尾帧。')
    for cid in guide['review']['guide_visible_actor_ids']:
        lines.append(refs[-1]['tag']+'中'+guide['review']['screen_identity_map'][cid]+'是'+names[cid]+'。')
    for cid in cast:
        lines.append('开场状态，'+names[cid]+'：'+guide['review']['world_actor_state'][cid])
    lines.append('声音设计：以下署名人物各自自然说出其台词，其他人在旁倾听与反应。')
    for cid in cast:lines.append(names[cid]+'的声线：'+pp[cid]['description'])
    emitted=set()
    for i,(beat,row) in enumerate(zip(camera,rows)):
        if row['beat_index']!=i or (row['start'],row['end'])!=(beat['start'],beat['end']):
            raise ValueError('ordered_carried_state_and_camera_time_required')
        visible=list(beat['actors'])
        lines.append(f"{beat['start']:g}—{beat['end']:g}秒，"+framing[beat['framing']]+'，'+ '、'.join(names[c] for c in visible)+'入镜。')
        for cid in visible:
            s=row['before'][cid]
            text=names[cid]+'仍是前镜中同一个孩子，位于'+_phrase(s['position'],names)+'，'+_phrase(s['posture'],names)+'，目光朝向'+_phrase(s['gaze'],names)
            if s['held_items']:text+='，手中保持'+ '、'.join(_phrase(v,names) for v in s['held_items'])
            lines.append(text+'。')
        lines.extend(req['spans'][sid]['text'] for sid in beat['source_span_ids'])
        for action in row['body_actions']:
            performer=action['performer_actor_id'];owner=action['owner_actor_id']
            part=PARTS.get(action['body_part'],action['body_part'])
            target='自己这具身体的'+part if action['relation']=='self' else names[owner]+'的'+part
            lines.append(names[performer]+'的这次动作作用于'+target+'，摄影跟随原来的'+names[owner]+'及其身体。')
        for cid,after in row['after'].items():
            before=row['before'][cid];changes=[]
            for key,label in [('position','位置转到'),('posture','姿态变为'),('gaze','视线转向')]:
                if before[key]!=after[key]:changes.append(label+_phrase(after[key],names))
            if before['held_items']!=after['held_items']:
                changes.append('手中'+('持有'+'、'.join(_phrase(v,names) for v in after['held_items']) if after['held_items'] else '保持空手'))
            if changes:lines.append(names[cid]+'在本镜内'+ '、'.join(changes)+'，后镜继续这一状态。')
        for ai,a in enumerate(entry['audio']):
            if ai in emitted or not beat['start']<=a['start']<beat['end']:continue
            emitted.add(ai);cid=a['speaker'];voice='女孩童声' if pp[cid]['type']=='female_child' else '男童声'
            quote=req['quotes'][a['quote_index']].group()[1:-1]
            if a['mode']!='onscreen':raise ValueError('this_child_profile_adapter_requires_onscreen_source')
            lines.append(f"{a['start']:g}—{a['end']:g}秒，"+names[cid]+'本人以自然稚嫩的'+voice+'开口说：“'+quote+'”身旁人物以动作和表情回应。')
        lines.append('切镜后仍承接以上同一人物及各自身体的位置、姿态、视线和持物。')
    text='\n'.join(lines)
    if (len(emitted)!=len(entry['audio']) or flow.core.QUOTE.findall(text)!=flow.core.QUOTE.findall(original)
            or any(s['instance_id'] in text for s in state['state_plan_result']['initial'].values())):
        raise ValueError('exact_quotes_and_natural_non_debug_state_prompt_required')
    patched=deepcopy(graph);patched['condition']['inputs']['prompt']=text
    result=deepcopy(manifest);result.update(compiled_prompt=text,compiled_prompt_utf8_sha256=flow.core.sha(text),
        graph_sha256=flow.digest(patched),presentation=dict(schema=VERSION,profile_binding=profile_binding,
        origin_graph_sha256=manifest['graph_sha256'],origin_prompt_sha256=manifest['compiled_prompt_utf8_sha256'],
        structured_state_preserved=True,debug_instance_ids_in_prompt=False,
        voice_control_mode='prompt_only',voice_identity_locked=False,audio_references=0))
    flow.validate_graph(patched,refs,result['voice_resolution'],result['scope'])
    return dict(manifest=result,graph=patched)
