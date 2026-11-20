"""Render source/guide-bound ongoing contact into a verified H3 prompt."""
from copy import deepcopy

from . import h3_asset_flow_v2 as flow
from . import h3_active_contact_v1 as contact

VERSION='h3_contact_performance_prompt/v1'


def apply(manifest,graph):
    if (flow.digest(graph)!=manifest['graph_sha256']
            or graph['condition']['inputs']['prompt']!=manifest['compiled_prompt']
            or flow.core.sha(manifest['compiled_prompt'])!=manifest['compiled_prompt_utf8_sha256']):
        raise ValueError('unchanged_verified_performance_package_required')
    spec=flow._bound(manifest['spec']);binding=spec.get('contact_plan')
    if not isinstance(binding,dict):raise ValueError('pinned_contact_plan_required')
    plan=flow._bound(binding);entry=flow.core._entries(manifest['source_case'])[0]
    state=flow._bound(manifest['state_plan_binding']);guide=manifest['guide']
    case=dict(schema=contact.CASE,entry=entry,state_plan=state,guide=guide)
    resolved=contact.resolve(case,plan)
    if (resolved.get('status')!='ready' or flow.digest(resolved['entry'])!=flow.digest(entry)
            or flow.digest(resolved['state_plan'])!=flow.digest(state)):
        raise ValueError('contact_closure_must_be_materialized_in_source_before_compile')
    names=entry['character_names'];beats=manifest['actor_state']['camera_beats']
    rows=contact.render_contacts(resolved,names)
    if len(rows)!=len(beats):raise ValueError('all_camera_contact_paragraphs_required')
    text=manifest['compiled_prompt'];origin=text;rendered=[]
    for i,(beat,row) in enumerate(zip(beats,rows)):
        if row['beat_index']!=i:raise ValueError('ordered_contact_paragraphs_required')
        expected=set(resolved['visible_actor_ids_by_beat'][i]['actor_ids'])
        if set(beat['actors'])!=expected:raise ValueError('actual_camera_must_include_contact_endpoints')
        marker=f"{beat['start']:g}—{beat['end']:g}秒，"
        matches=[line for line in text.splitlines() if line.startswith(marker)]
        if len(matches)!=1:raise ValueError('unique_actual_camera_header_required')
        lines=[row['text']]
        for c in resolved['active_contacts_by_beat'][i]['contacts']:
            performer=c['performer_actor_id'];owner=c['owner_actor_id']
            label=guide['review']['screen_identity_map'].get(owner)
            if not label:raise ValueError('observed_contact_owner_visual_label_required')
            visible=c['contact_id'] in resolved['active_contacts_by_beat'][i]['visible_contact_ids']
            if visible:
                lines.append('护理对象的外形承接实际尾帧中的'+label+'，也就是'+names[owner]+'；当前镜头里的被扶前臂、肩和衣袖延续他本人的身体与衣着。')
                gaze=manifest['actor_state']['state_plan_result']['beats'][i]['after'][performer]['gaze']
                for other in beat['actors']:
                    if other not in (performer,owner) and (other in gaze or names[other] in gaze):
                        other_label=guide['review']['screen_identity_map'].get(other)
                        if not other_label:raise ValueError('observed_gaze_target_visual_label_required')
                        lines.append(names[performer]+'的目光对象对应承接帧中'+other_label+'，也就是'+names[other]+'；被注视的人与被护理的'+names[owner]+'分别延续各自原有身体、位置和衣色。')
                speaking=any(a['speaker']==performer and a['start']<beat['end'] and a['end']>beat['start'] for a in entry['audio'])
                if speaking:
                    lines.append(names[performer]+'本镜抬头说话时，手仍接着扶'+names[owner]+'的同一只前臂。')
                else:
                    lines.append(names[performer]+'保持已形成的视线与扶臂状态，护理对象仍是'+names[owner]+'。')
            else:
                lines.append('画外的'+names[performer]+'与'+names[owner]+'保持刚才的护理位置和接触对象，后镜继续这一状态。')
        if flow.core.QUOTE.search('\n'.join(lines)):raise ValueError('contact_direction_cannot_add_spoken_quote')
        paragraph='\n'.join(lines)
        text=text.replace(matches[0],matches[0]+'\n'+paragraph,1)
        rendered.append(dict(beat_index=i,text=paragraph))
    if (flow.core.QUOTE.findall(text)!=flow.core.QUOTE.findall(origin)
            or any(v['instance_id'] in text for v in state['initial'].values())):
        raise ValueError('exact_quotes_and_natural_contact_directions_required')
    patched=deepcopy(graph);patched['condition']['inputs']['prompt']=text
    value=deepcopy(manifest);value.update(compiled_prompt=text,compiled_prompt_utf8_sha256=flow.core.sha(text),
        graph_sha256=flow.digest(patched),contact_continuity=dict(schema=VERSION,plan_binding=binding,
        resolution=resolved,rendered_contact_beats=rendered,origin_graph_sha256=manifest['graph_sha256'],
        origin_prompt_sha256=manifest['compiled_prompt_utf8_sha256'],source_and_state_unchanged=True,
        actual_contact_pixels_generated=False,model_quality_passed=False))
    flow.validate_graph(patched,value['references'],value['voice_resolution'],value['scope'])
    return dict(manifest=value,graph=patched)
