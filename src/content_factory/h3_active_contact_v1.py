"""Pure-CPU carry of observed, source-bound contact relationships.

The caller supplies the semantic source/guide observation. This module checks
its identities and provenance, carries it across cuts independently of gaze,
and closes only the currently visible interaction endpoints. It neither guesses
contact from prose nor submits media. Release is supported at shot boundaries;
mid-shot changes require an upstream camera split rather than guessed timing.
"""
from copy import deepcopy
import hashlib
import json
import re
from . import shot_actor_continuity_v1 as continuity

VERSION='h3_active_contact/v1'
CASE='h3_active_contact_case/v1'
PLAN='h3_active_contact_plan/v1'
OBSERVATION_FIELDS=('contact_id','performer_actor_id','performer_instance_id','owner_actor_id','owner_instance_id','body_part','tool_id','source_span_ids')
PARTS={'face','mouth','head','shoulders','torso','hands','legs','feet','back'}
CLOSE={'face_close','hands_close','detail','close','closeup'}


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _need(code,**details):return dict(code=code,**details)
def _result(status,notices,**values):
    return dict(schema=VERSION,status=status,notices=notices,model_calls=0,ASR_calls=0,media_calls=0,
        production_ready=False,free_camera=True,all_actors_in_every_frame_required=False,**values)
def _string(value):return isinstance(value,str) and bool(value.strip())
def _ids(value):return isinstance(value,list) and bool(value) and all(_string(v) for v in value) and len(value)==len(set(value))
def _observation(contact):return {k:deepcopy(contact[k]) for k in OBSERVATION_FIELDS}
def _source(ids,spans,*,action=False):
    return _ids(ids) and all(i in spans and spans[i].get('kind') in (('action',) if action else ('action','context')) for i in ids)


def resolve(case,plan):
    """Return a new source entry plus persistent contacts, never mutate inputs.

    case={schema:CASE,entry,state_plan,guide}; plan uses PLAN with an exact
    initial_basis, observed initial_contacts, source-backed release authorities,
    boundary events and exact-source actor_pose_spans for missing endpoints.
    guide.review.observed_contacts is the separately observed initial authority.
    """
    try:
        if case.get('schema')!=CASE or plan.get('schema')!=PLAN:
            return _result('needs_material',[_need('explicit_contact_case_and_plan_required')])
        entry=deepcopy(case['entry']);state=deepcopy(case['state_plan']);guide=case['guide']
        actors=entry.get('full_clip_actor_ids',list(state.get('initial',{})))
        if not _ids(actors) or set(actors)!=set(state.get('initial',{})):
            return _result('needs_material',[_need('contact_cast_and_initial_state_required')])
        initial=state['initial'];instances={c:initial[c]['instance_id'] for c in actors}
        if any(not _string(v) for v in instances.values()) or len(set(instances.values()))!=len(instances):
            return _result('needs_contact_repair',[_need('unique_contact_actor_instances_required')])
        basis=dict(guide_image=guide['image'],native_result=guide['native_result'],guide_review_sha256=digest(guide['review']))
        if plan.get('initial_basis')!=basis or state.get('initial_basis')!=basis:
            return _result('needs_material',[_need('contact_initial_actual_guide_basis_required')])
        observed=guide['review'].get('observed_contacts')
        if (not isinstance(observed,list) or any(not isinstance(v,dict) or not _string(v.get('contact_id')) for v in observed)
                or len({v['contact_id'] for v in observed})!=len(observed)):
            return _result('needs_material',[_need('unique_observed_contact_authority_required')])
        spans={s['id']:s for s in entry['source_spans']}
        if len(spans)!=len(entry['source_spans']):return _result('needs_material',[_need('unique_contact_source_spans_required')])
        contacts=plan.get('initial_contacts')
        if not isinstance(contacts,list):return _result('needs_material',[_need('explicit_initial_contact_list_required')])
        by_id={};notices=[]
        for contact in contacts:
            cid=contact.get('contact_id');performer=contact.get('performer_actor_id');owner=contact.get('owner_actor_id')
            if (not _string(cid) or cid in by_id or performer not in actors or owner not in actors or performer==owner
                    or contact.get('performer_instance_id')!=instances[performer] or contact.get('owner_instance_id')!=instances[owner]
                    or not _string(contact.get('body_part')) or 'tool_id' not in contact
                    or not _source(contact.get('source_span_ids'),spans)):
                notices.append(_need('contact_identity_owner_or_source_invalid',contact_id=cid));continue
            if _observation(contact) not in observed:
                notices.append(_need('contact_must_match_initial_guide_observation',contact_id=cid));continue
            text=''.join(spans[i].get('text','') for i in contact['source_span_ids'])
            action=contact.get('action_text')
            if not _string(action) or action not in text or re.search('[“”「」\n\r]',action):
                notices.append(_need('contact_action_text_must_be_exact_source',contact_id=cid));continue
            tool=contact['tool_id'];held=initial[performer].get('held_items',[])
            held_ids=[v.get('id') if isinstance(v,dict) else v for v in held]
            if tool is not None and (not _string(tool) or tool not in held_ids or not _string(contact.get('tool_name'))
                    or re.search('[“”「」\n\r]',contact['tool_name'])):
                notices.append(_need('contact_tool_must_be_actually_held',contact_id=cid));continue
            by_id[cid]=deepcopy(contact)
        if notices:return _result('needs_contact_repair',notices)
        if {c['contact_id'] for c in observed}!={c['contact_id'] for c in contacts}:
            return _result('needs_contact_repair',[_need('all_observed_initial_contacts_must_be_carried')])
        beats=entry['camera_beats'];state_rows=state.get('beats',[])
        if not isinstance(beats,list) or len(beats)!=len(state_rows):
            return _result('needs_material',[_need('contact_camera_and_state_beats_required')])
        carried_states=continuity.carry_states(actors,beats,entry.get('audio',[]),entry['source_spans'],state)
        if carried_states['status']!='ready':
            return _result('needs_contact_repair',[_need('contact_requires_valid_actor_state_carry',state_notices=carried_states['notices'])])
        releases=plan.get('source_releases',[]);authorities={}
        if not isinstance(releases,list) or not isinstance(plan.get('events',[]),list):
            return _result('needs_material',[_need('explicit_contact_boundary_events_required')])
        for release in releases:
            rid=release.get('release_id');cid=release.get('contact_id');contact=by_id.get(cid)
            source_authority=[a for a in state.get('source_actions',[]) if a.get('source_span_id') in release.get('source_span_ids',[])
                and a.get('actor_id')==release.get('performer_actor_id') and a.get('contact_effect')=='release'
                and a.get('contact_id')==cid and release.get('body_part') in a.get('body_parts',[])
                and release.get('owner_actor_id') in a.get('target_actor_ids',[])]
            if (not _string(rid) or rid in authorities or contact is None
                    or any(release.get(k)!=contact[k] for k in ('performer_actor_id','owner_actor_id','body_part'))
                    or not _source(release.get('source_span_ids'),spans,action=True)
                    or {a['source_span_id'] for a in source_authority}!=set(release.get('source_span_ids',[]))
                    or not _string(release.get('action_text'))
                    or release['action_text'] not in ''.join(spans[i].get('text','') for i in release['source_span_ids'])):
                notices.append(_need('release_requires_same_contact_and_explicit_source_action',release_id=rid));continue
            authorities[rid]=release
        events={};seen=set()
        for event in plan.get('events',[]):
            index=event.get('beat_index');rid=event.get('release_id');release=authorities.get(rid)
            if (type(index) is not int or not 0<=index<len(beats) or event.get('phase')!='after_beat'
                    or release is None or rid in seen
                    or not set(release['source_span_ids'])<=set(beats[index].get('source_span_ids',[]))):
                notices.append(_need('release_event_requires_bound_action_at_camera_boundary',release_id=rid,beat_index=index));continue
            events.setdefault(index,[]).append(release);seen.add(rid)
        if notices:return _result('needs_contact_repair',notices)
        pose_sources=plan.get('actor_pose_spans',{});active=deepcopy(by_id);carried=[];focus=[];visible=[];changes=[]
        for index,beat in enumerate(beats):
            if not isinstance(beat.get('actors'),dict) or not set(beat['actors'])<=set(actors):
                return _result('needs_contact_repair',[_need('contact_camera_extra_actor',beat_index=index)])
            for cid,visual in beat['actors'].items():
                if visual.get('instance_id',instances[cid])!=instances[cid]:
                    return _result('needs_contact_repair',[_need('camera_contact_instance_mismatch',beat_index=index,actor_id=cid)])
            original=deepcopy(beat)
            actor_state=carried_states['state_plan_result']['beats'][index]
            releasing={r['contact_id'] for r in events.get(index,[])}
            for contact in active.values():
                tool=contact['tool_id'];performer=contact['performer_actor_id']
                if tool is None:continue
                for phase in ('before','after'):
                    if phase=='after' and contact['contact_id'] in releasing:continue
                    held=actor_state[phase][performer]['held_items']
                    held_ids=[v.get('id') if isinstance(v,dict) else v for v in held]
                    if tool not in held_ids:
                        return _result('needs_contact_repair',[_need('active_contact_tool_lost_without_source_release',
                            beat_index=index,contact_id=contact['contact_id'],phase=phase)])
            speakers=list(dict.fromkeys(a['speaker'] for a in entry.get('audio',[]) if a.get('mode') in ('onscreen','dialogue')
                and a['start']<beat['end'] and a['end']>beat['start']))
            focus.append(dict(beat_index=index,actor_ids=speakers or list(original['actors'])))
            closure=set(beat['actors']);needed=True
            while needed:
                needed=False
                for contact in active.values():
                    pair={contact['performer_actor_id'],contact['owner_actor_id']}
                    if pair & closure and not pair<=closure:closure|=pair;needed=True
            for cid in actors:
                if cid not in closure or cid in beat['actors']:continue
                source=pose_sources.get(cid,{})
                sid=source.get('source_span_id');text=source.get('text');parts=source.get('visible_parts')
                if (sid not in spans or spans[sid].get('kind') not in ('action','context') or not _string(text) or text not in spans[sid].get('text','')
                        or not _ids(parts) or not set(parts)<=PARTS or not {'torso','hands'}<=set(parts)):
                    return _result('needs_material',[_need('missing_contact_endpoint_requires_exact_source_pose',beat_index=index,actor_id=cid)])
                beat['actors'][cid]=dict(pose=text,visible_parts=deepcopy(parts),instance_id=instances[cid])
            for contact in active.values():
                pair={contact['performer_actor_id'],contact['owner_actor_id']}
                if pair & closure:
                    for cid in pair:
                        parts=beat['actors'][cid].setdefault('visible_parts',[])
                        for part in ('torso','hands'):
                            if part not in parts:parts.append(part)
                    if beat['framing'] in CLOSE:beat['framing']='medium'
            if beat!=original:changes.append(dict(beat_index=index,before=original,after=deepcopy(beat)))
            carried.append(dict(beat_index=index,contacts=deepcopy(list(active.values())),
                visible_contact_ids=[c['contact_id'] for c in active.values() if {c['performer_actor_id'],c['owner_actor_id']}<=closure],
                released_after_beat=[r['contact_id'] for r in events.get(index,[])]))
            visible.append(dict(beat_index=index,actor_ids=list(beat['actors'])))
            for release in events.get(index,[]):
                cid=release['contact_id']
                if cid not in active:return _result('needs_contact_repair',[_need('already_released_contact',contact_id=cid)])
                del active[cid]
        value=_result('ready',[],entry=entry,state_plan=state,focus_actor_ids_by_beat=focus,
            visible_actor_ids_by_beat=visible,active_contacts_by_beat=carried,final_active_contacts=deepcopy(list(active.values())),
            changes=changes,semantic_authority='caller_observed_actual_guide_and_source_contract',
            portrait_pose_used=False,gaze_changes_contact_owner=False)
        value['resolved_sha256']=digest(value)
        return value
    except (KeyError,TypeError,ValueError,AttributeError,IndexError) as error:
        return _result('needs_material',[_need('malformed_contact_input',error_type=type(error).__name__)])


def render_contacts(result,character_names):
    """Per-camera text for the same prompt paragraph as state/action/dialogue."""
    if (result.get('status')!='ready' or result.get('resolved_sha256')!=digest({k:v for k,v in result.items() if k!='resolved_sha256'})):
        raise ValueError('ready_unchanged_contact_resolution_required')
    actors=result['state_plan']['initial']
    if set(actors)-set(character_names) or any(not _string(character_names[c]) or re.search('[“”「」\n\r]',character_names[c]) for c in actors):
        raise ValueError('all_safe_contact_actor_names_required')
    parts=dict(forearm='前臂',wrist='手腕',hand='手',hands='双手',shoulder='肩部')
    rendered=[]
    for row in result['active_contacts_by_beat']:
        lines=[]
        for contact in row['contacts']:
            performer=contact['performer_actor_id'];owner=contact['owner_actor_id']
            prefix='本镜持续接触：' if contact['contact_id'] in row['visible_contact_ids'] else '本镜画外接触继续承接：'
            tool='持'+contact['tool_name']+'，' if contact['tool_id'] is not None else ''
            lines.append(prefix+character_names[performer]+tool
                +contact['action_text']+character_names[owner]+'同一身体的'
                +parts.get(contact['body_part'],contact['body_part'])+'，接触双方沿用各自已有位置。')
        if row['released_after_beat']:lines.append('本镜原文解除动作完成后，以下接触关系在镜末结束：'+'、'.join(row['released_after_beat'])+'。')
        if not lines:lines.append('本镜没有仍在持续的已登记接触关系。')
        rendered.append(dict(beat_index=row['beat_index'],text='\n'.join(lines)))
    return rendered
