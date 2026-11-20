"""Source/asset-independent directing policy for verified video input packages.

Only the positive prompt may change. The plan is a production instruction and
an explicit visual-QA obligation, never evidence that generated pixels passed.
Legacy packages use source camera/audio only; no portrait-derived state or
unstructured-prose contact inference is performed.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

from . import h3_asset_flow_v2 as flow
from . import h3_active_contact_v1 as contact

SCHEMA='video_directing_policy/v1'
APPLICATION='video_directing_policy_application/v1'
PLAN='video_directing_plan/v1'
RULES=('identifiable_subjects','clean_offscreen_boundary','compact_solo_with_offscreen_contact',
       'recognizable_contact_endpoints','owned_detail_insert','audio_visual_separation',
       'asset_identity_and_props','spatial_transition_continuity','sound_caption_separation')
DEFAULT_POLICY=dict(schema=SCHEMA,rules=list(RULES),max_static_chars=160,max_per_beat_chars=420)
STATIC='人物身份、衣着、道具持有人与场景布局沿绑定资料和前态承接。入镜人物可辨认，镜外人物完整留在画外。署名台词沿原说话人、声音模式和时窗发声；摄影说明用于画面，字幕策略沿原稿，语言信息通过声音轨呈现。'
PART_NAMES=dict(hand='手',hands='双手',wrist='手腕',wrists='双手腕',forearm='前臂',
    left_hand='左手',right_hand='右手',left_wrist='左手腕',right_wrist='右手腕',shoulder='肩部')
DETAIL={'hands_close','detail'}
MODES={'onscreen','dialogue','voiceover','inner_voice','offscreen_dialogue'}


class DirectingPolicyError(ValueError):pass


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _require(ok,message):
    if not ok:raise DirectingPolicyError(message)
def _text(value):return isinstance(value,str) and bool(value.strip())
def _ids(value):return isinstance(value,list) and len(value)==len(set(value)) and all(_text(v) for v in value)
def _names(ids,names):return '、'.join(names[c] for c in ids)


def validate_policy(policy):
    _require(isinstance(policy,dict) and set(policy)==set(DEFAULT_POLICY),'generic_policy_exact_keys_required')
    _require(policy['schema']==SCHEMA and _ids(policy['rules']) and set(policy['rules'])==set(RULES),'all_generic_directing_rules_required')
    _require(type(policy['max_static_chars']) is int and 80<=policy['max_static_chars']<=240
        and type(policy['max_per_beat_chars']) is int and 160<=policy['max_per_beat_chars']<=700,'bounded_directing_text_budget_required')
    _require(len(STATIC)<=policy['max_static_chars'],'static_directing_text_exceeds_policy_budget')
    return deepcopy(policy)


def _contact_rows(manifest,entry,state_plan):
    package=manifest.get('contact_continuity')
    if package is None:return None
    _require(isinstance(package,dict) and isinstance(package.get('resolution'),dict),'explicit_contact_continuity_resolution_required')
    _require(state_plan is not None and manifest.get('guide') is not None,'contact_requires_bound_actor_state_and_guide')
    plan=flow._bound(package['plan_binding'])
    fresh=contact.resolve(dict(schema=contact.CASE,entry=entry,state_plan=state_plan,guide=manifest['guide']),plan)
    _require(fresh['status']=='ready' and fresh==package['resolution'],'contact_continuity_must_replay_same_bound_resolution')
    return fresh['active_contacts_by_beat']


def build_directing_plan(manifest,entry,policy,*,contact_rows=None):
    """Pure planning helper; apply authenticates files/graph before calling it.

    contact_rows must be a replayed contact resolution, or None (unknown). It is
    deliberately never inferred from narrative wording, gaze, or portraits.
    """
    policy=validate_policy(policy);names=entry['character_names']
    _require(isinstance(names,dict) and names and all(_text(v) and not re.search('[“”「」\n\r]',v) for v in names.values()),'safe_source_character_names_required')
    state=manifest.get('actor_state');has_state=state is not None
    if has_state:
        _require(state.get('status')=='ready','verified_actor_state_required')
        camera=state['camera_beats'];rows=state['state_plan_result']['beats'];initial=state['state_plan_result']['initial']
        cast=list(initial)
        _require(len(camera)==len(rows),'complete_camera_state_pairing_required')
    else:
        camera=entry['camera_beats'];rows=[None]*len(camera)
        cast=list(entry.get('full_clip_actor_ids',entry.get('canonical_characters',{})))
        if not cast:cast=list(dict.fromkeys(c for b in camera for c in b['actors']))
    _require(_ids(cast) and set(cast)<=set(names),'source_cast_identity_required')
    _require(camera and isinstance(entry.get('audio'),list),'source_camera_audio_required')
    if contact_rows is not None:
        _require(len(contact_rows)==len(camera) and [r['beat_index'] for r in contact_rows]==list(range(len(camera))),
            'complete_contact_camera_pairing_required')
    beats=[];previous=0
    for index,(beat,row) in enumerate(zip(camera,rows)):
        start,end=beat['start'],beat['end'];visible=list(beat['actors'])
        _require(type(start) in (int,float) and type(end) in (int,float) and math.isfinite(start) and math.isfinite(end) and start==previous and start<end
            and _ids(visible) and set(visible)<=set(cast),'bounded_contiguous_source_camera_required')
        previous=end
        if row is not None:
            _require(row['beat_index']==index and (row['start'],row['end'])==(start,end)
                and set(row['before'])==set(cast) and set(row['after'])==set(cast),'same_ordered_actor_state_required')
            _require(set(row['visible_instance_map'])==set(visible) and all(row['before'][c]['instance_id']==row['after'][c]['instance_id']
                and row['visible_instance_map'].get(c,row['before'][c]['instance_id'])==row['before'][c]['instance_id'] for c in cast),
                'camera_must_reference_same_carried_actor_instances')
        offscreen=[c for c in cast if c not in visible]
        audio=[dict(a,source_audio_index=i) for i,a in enumerate(entry['audio']) if a['start']<end and a['end']>start]
        _require(all(a['mode'] in MODES and a['speaker'] in names for a in audio),'source_audio_mode_and_identity_required')
        onscreen=list(dict.fromkeys(a['speaker'] for a in audio if a['mode'] in ('onscreen','dialogue')))
        _require(set(onscreen)<=set(visible),'onscreen_speaker_must_be_in_planned_frame')
        actions=deepcopy(row['body_actions']) if row is not None else []
        _require(all(a['performer_actor_id'] in cast and a['owner_actor_id'] in cast and _text(a['body_part']) for a in actions),
            'explicit_body_action_ownership_required')
        cr=contact_rows[index] if contact_rows is not None else None
        contacts=deepcopy(cr['contacts']) if cr else []
        visible_contacts=[];offscreen_contacts=[]
        for item in contacts:
            pair={item['performer_actor_id'],item['owner_actor_id']}
            _require(pair<=set(cast),'known_contact_endpoints_required')
            if pair & set(visible):
                _require(pair<=set(visible),'visible_contact_requires_both_planned_endpoints')
                visible_contacts.append(item)
            else:offscreen_contacts.append(item)
        focus=onscreen or list(dict.fromkeys(a['performer_actor_id'] for a in actions if a['performer_actor_id'] in visible)) or visible
        held_before={c:deepcopy(row['before'][c]['held_items']) for c in cast} if row is not None else None
        held_after={c:deepcopy(row['after'][c]['held_items']) for c in cast} if row is not None else None
        prop_risk=any(held_before[c] or held_after[c] for c in cast) if has_state else any('hands' in a.get('visible_parts',[]) for a in beat['actors'].values())
        current_place=(entry.get('place_id') or manifest.get('place',{}).get('id')
            or manifest.get('script_fields',{}).get('location',{}).get('place_id'))
        previous_scene=manifest.get('previous_scene_state',manifest.get('guide',{}).get('previous_scene_state',{}))
        previous_place=previous_scene.get('place_id') if isinstance(previous_scene,dict) else None
        selection=manifest.get('segment_selection',{})
        explicit_scene_start=(manifest.get('guide_kind')=='generated_scene'
            or isinstance(selection,dict) and selection.get('mode')=='scene_cut')
        scene_change=index==0 and bool(explicit_scene_start or current_place and previous_place and current_place!=previous_place)
        framing=beat['framing'];composition=framing;risks=[];rules=['identifiable_subjects','clean_offscreen_boundary','audio_visual_separation']
        if prop_risk:rules.append('asset_identity_and_props');risks.append('prop_holder_or_handoff_continuity_check')
        if scene_change:rules.append('spatial_transition_continuity');risks.append('new_scene_must_use_current_scene_start')
        if audio:rules.append('sound_caption_separation')
        boundary_mode='participants_identifiable_others_fully_outside'
        if len(visible)==1 and framing=='medium' and (offscreen_contacts or offscreen):
            composition='compact_upper_body';risks.append('solo_medium_foreground_fragment_risk')
            rules.append('compact_solo_with_offscreen_contact')
        if visible_contacts:
            risks.append('contact_endpoint_identity_boundary_risk');rules.append('recognizable_contact_endpoints')
            if framing not in DETAIL:composition='recognizable_contact_group'
        ownership=[dict(performer_actor_id=a['performer_actor_id'],owner_actor_id=a['owner_actor_id'],body_part=a['body_part'],relation=a['relation']) for a in actions]
        for item in visible_contacts:
            ownership.append(dict(performer_actor_id=item['performer_actor_id'],owner_actor_id=item['owner_actor_id'],body_part=item['body_part'],relation='other'))
        if framing in DETAIL:
            rules.append('owned_detail_insert');risks.append('detail_body_identity_anchor_required')
            if not ownership:
                ownership=[dict(performer_actor_id=c,owner_actor_id=c,body_part='hands' if framing=='hands_close' else 'source_visible_detail',relation='self') for c in visible]
            composition='face_and_owned_detail' if onscreen else 'owned_detail_insert'
        if onscreen and framing in DETAIL:risks.append('onscreen_speech_requires_identifiable_face')
        guide_visible=manifest.get('guide',{}).get('review',{}).get('guide_visible_actor_ids',[])
        anchors={c:dict(actual_guide_visible=c in guide_visible,
            earlier_shot_visible=any(c in prior['visible_actor_ids'] for prior in beats),
            source_identity_registered=c in entry.get('canonical_characters',{}) or c in manifest.get('required_actor_assets',[])) for c in visible}
        checks=['subject_identity_and_clean_frame_boundary','source_action_state_and_asset_identity_preserved','audio_mode_speaker_and_timing_preserved']
        if composition=='compact_upper_body':checks+=['single_subject_head_shoulders_and_owned_hands_visible','offscreen_people_fully_outside_no_orphan_leg_or_torso']
        if visible_contacts:checks+=['contact_participants_identifiable_and_same_owned_action_endpoints']
        if framing in DETAIL:checks+=['detail_returns_to_same_owner_identity','onscreen_speaking_face_visible' if onscreen else 'detail_has_clear_owner_anchor']
        if prop_risk:checks+=['prop_holder_and_source_handoff_continuity']
        if scene_change:checks+=['current_scene_layout_and_start_state_separate_from_previous_scene']
        if audio:checks+=['source_caption_policy_separate_from_dialogue_and_narration']
        beats.append(dict(beat_index=index,start=start,end=end,source_framing=framing,composition=composition,
            focus_actor_ids=focus,visible_actor_ids=visible,offscreen_actor_ids=offscreen,boundary_mode=boundary_mode,
            identity_anchors=anchors,
            contact_knowledge='structured_replayed_contact' if contact_rows is not None else 'unknown_no_structured_contact_plan',
            visible_contacts=visible_contacts,offscreen_contacts=offscreen_contacts,body_ownership=ownership,
            prop_holders_before=held_before,prop_holders_after=held_after,prop_knowledge='bound_actor_state' if has_state else 'unknown_source_actions_only',
            spatial=dict(current_place_id=current_place,previous_place_id=previous_place,explicit_scene_change=scene_change,
                scene_change_evidence='bound_scene_start_or_scene_cut' if scene_change and explicit_scene_start else
                    'different_explicit_place_ids' if scene_change else 'same_or_unknown_prior_scene'),
            caption_policy=dict(postproduction_subtitles=entry.get('postproduction_subtitles'),source_policy_changed=False,language_is_audio_not_camera_direction=True),
            sound=audio,risks=risks,selected_rules=list(dict.fromkeys(rules)),visual_qa_checks=checks,
            actor_state_source='bound_carried_state' if has_state else 'source_camera_audio_only_no_pose_inference',
            actual_pixels_checked=False,model_quality_passed=False))
    return dict(schema=PLAN,beats=beats,free_camera=True,all_cast_in_every_shot_required=False,
        source_audio_preserved=True,actor_state_modified=False,assets_modified=False,
        actual_pixels_checked=False,model_quality_passed=False)


def render_plan(plan,entry,policy):
    names=entry['character_names'];rendered=[]
    for beat in plan['beats']:
        visible=beat['visible_actor_ids'];off=beat['offscreen_actor_ids'];mode=beat['composition'];lines=[]
        if not visible:lines.append('本镜以原场景与原文环境细节为主体，人物按原调度在画外承接。')
        elif mode=='compact_upper_body':
            person=names[visible[0]]
            lines.append('构图收紧到'+person+'完整可辨的头肩和上身，动作手部与自己的身体同框，画面边界围绕这个单人主体。')
        elif mode=='recognizable_contact_group':
            lines.append('取景清楚保留'+_names(visible,names)+'各自可辨认的头肩与互动位置，接触双方的手臂和动作端点在同一空间内承接。')
        elif mode=='owned_detail_insert':
            lines.append('本镜保留原文所需局部特写，以前后镜已建立的人物身份和各自位置承接这些身体细节。')
        elif mode=='face_and_owned_detail':
            lines.append('在局部动作构图中同时保留'+_names(list(dict.fromkeys(a['speaker'] for a in beat['sound'] if a['mode'] in ('onscreen','dialogue'))),names)+'可辨认的发声面部及属于本人的动作部位。')
        else:lines.append('本镜主体是'+_names(beat['focus_actor_ids'],names)+'，入镜人物以各自可辨认的头肩或完整人物轮廓承接，景别沿原调度自由切换。')
        if off:lines.append(_names(off,names)+'的身体整体处于本镜取景范围之外，各自状态和既有接触在画外延续。')
        if 'asset_identity_and_props' in beat['selected_rules']:
            lines.append('道具的拿放与交接按本镜原文发生，持有人与物件承接既有动作。')
        if beat['spatial']['explicit_scene_change']:
            lines.append('本场取景建立当前场景的布局与人物起点，前场信息作为前情承接。')
        for item in beat['body_ownership']:
            owner=item['owner_actor_id'];performer=item['performer_actor_id'];part=PART_NAMES.get(item['body_part'],'原文对应身体细节')
            if owner==performer:lines.append(names[performer]+'的'+part+'与其同一身体连续，摄影承接原来的本人。')
            else:lines.append(names[performer]+'的接触动作清楚作用于'+names[owner]+'本人的'+part+'，双方仍是各自原来的人物。')
        voiceover=list(dict.fromkeys(a['speaker'] for a in beat['sound'] if a['mode']=='voiceover'))
        inner=list(dict.fromkeys(a['speaker'] for a in beat['sound'] if a['mode']=='inner_voice'))
        off_dialogue=list(dict.fromkeys(a['speaker'] for a in beat['sound'] if a['mode']=='offscreen_dialogue'))
        onsite=list(dict.fromkeys(a['speaker'] for a in beat['sound'] if a['mode'] in ('onscreen','dialogue')))
        if onsite:lines.append(_names(onsite,names)+'在原台词时窗自然开口，画面清楚交代其发声面部和交流对象。')
        if voiceover:lines.append(_names(voiceover,names)+'的叙述保留画外声，画面由原场景、动作与神情传达信息。')
        if inner:lines.append(_names(inner,names)+'的心声保留内心画外声，表演以原有目光和神情承接。')
        if off_dialogue:lines.append(_names(off_dialogue,names)+'的声音从原指定画外位置传来，画面承接当前主体。')
        if beat['sound']:lines.append('本镜语言信息通过原声音轨呈现，画面保持原场景与表演内容。')
        text=''.join(dict.fromkeys(lines))
        _require(len(text)<=policy['max_per_beat_chars'],'per_beat_directing_text_exceeds_policy_budget')
        rendered.append(dict(beat_index=beat['beat_index'],start=beat['start'],end=beat['end'],text=text))
    return rendered


def _insert(original,rendered):
    lines=original.splitlines();insertions={}
    time=re.compile(r'^\s*(\d+(?:\.\d+)?)\s*[—–-]\s*(\d+(?:\.\d+)?)秒\s*[，,]')
    for item in rendered:
        matches=[]
        for index,line in enumerate(lines):
            match=time.match(line)
            if not match or (float(match[1]),float(match[2]))!=(item['start'],item['end']):continue
            if ('画面人物' in line or '入镜' in line or '呈现' in line or '取景' in line) and re.search('景|特写|细节',line) and not flow.core.QUOTE.search(line):
                matches.append(index)
        _require(len(matches)==1,'one_exact_camera_prompt_anchor_per_beat_required')
        insertions[matches[0]]=item['text']
    result=[STATIC]
    for index,line in enumerate(lines):
        result.append(line)
        if index in insertions:result.append(insertions[index])
    return '\n'.join(result)


def apply(manifest,graph,policy_binding):
    """Authenticate a bound package and change only condition.prompt."""
    try:
        _require('directing_policy' not in manifest,'directing_policy_already_applied_use_bound_result')
        original=manifest['compiled_prompt']
        _require(digest(graph)==manifest['graph_sha256'] and graph['condition']['inputs']['prompt']==original
            and flow.core.sha(original)==manifest['compiled_prompt_utf8_sha256'],'verified_graph_and_positive_prompt_hashes_required')
        policy=validate_policy(flow._bound(policy_binding))
        entries=flow.core._entries(manifest['source_case']);_require(len(entries)==1,'single_bound_source_entry_required')
        entry=entries[0];flow.core.validate_entry(entry)
        state_plan=flow._bound(manifest['state_plan_binding']) if manifest.get('actor_state') is not None else None
        if state_plan is not None:
            original_state=manifest['actor_state'];cast=list(state_plan['initial'])
            carried=contact.continuity.carry_states(cast,entry['camera_beats'],entry['audio'],entry['source_spans'],state_plan)
            _require(carried['status']=='ready' and carried['camera_beats']==original_state['camera_beats']
                and carried['state_plan_result']==original_state['state_plan_result'],'actor_state_must_replay_same_bound_source_and_state_plan')
        contact_rows=_contact_rows(manifest,entry,state_plan)
        plan=build_directing_plan(manifest,entry,policy,contact_rows=contact_rows)
        rendered=render_plan(plan,entry,policy);text=_insert(original,rendered)
        _require(flow.core.QUOTE.findall(text)==flow.core.QUOTE.findall(original),'source_dialogue_quote_bytes_must_remain_unchanged')
        patched=deepcopy(graph);patched['condition']['inputs']['prompt']=text
        probe=deepcopy(patched);probe['condition']['inputs']['prompt']=original
        _require(digest(probe)==digest(graph),'only_positive_prompt_may_change')
        checklist=[dict(beat_index=b['beat_index'],start=b['start'],end=b['end'],checks=b['visual_qa_checks'],
            status='requires_actual_pixel_review',actual_pixels_checked=False) for b in plan['beats']]
        receipt=dict(schema=APPLICATION,policy_binding=deepcopy(policy_binding),plan=plan,rendered_beats=rendered,checklist=checklist,
            origin_graph_sha256=manifest['graph_sha256'],origin_prompt_sha256=manifest['compiled_prompt_utf8_sha256'],
            bound_input_hashes_authenticated=True,source_audio_state_and_assets_preserved=True,
            actual_pixels_checked=False,model_quality_passed=False,model_calls=0,ASR_calls=0)
        updated=deepcopy(manifest);updated.update(compiled_prompt=text,compiled_prompt_utf8_sha256=flow.core.sha(text),
            graph_sha256=digest(patched),directing_policy=receipt)
        return dict(manifest=updated,graph=patched,directing_plan=plan,rendered_text=text,checklist=checklist)
    except DirectingPolicyError:raise
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
        raise DirectingPolicyError('invalid_bound_directing_input:'+str(error)) from error
