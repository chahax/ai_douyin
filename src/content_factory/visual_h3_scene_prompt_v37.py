"""Source-bound multi-view identity and current-run continuation prompt contract.

CPU text compilation only. Source images and videos remain user-review-pending;
this module never opens an image, calls a model, or contacts a service.
"""
from copy import deepcopy
from pathlib import Path
from . import visual_h3_scene_prompt_v36 as source_text

PROJECT=Path(__file__).resolve().parents[2]
SOURCE=source_text.SOURCE
OUT=PROJECT/'data/video_generation/h3_multiview_continuity_minute_20261109_v3/source_prompts'
SCHEMA='h3_multiview_continuity_prompts/v37'
IDS=source_text.IDS
sha=source_text.sha
digest=source_text.digest
binding=source_text.binding
check=source_text.check
read=source_text.read
PromptError=source_text.PromptError
STYLE='真人写实中国家庭短剧，竖屏9:16，普通话对白与原生同步音轨。'
PERFORMANCE='开场立即进入本段正在发生的动作或说话。人物睁眼交流时看向场景内的对话对象或当下的面包，离场时视线随行进方向与房门移动；交流以自然侧面和三分之二侧面展开。镜头随剧情中的动作、说话和反应衔接。'
TEXT_POLICY=source_text.TEXT_POLICY
OPENING='人物的脸、衣服和同一卧室的空间关系沿用输入画面，直接从当前动作继续。'
CONTINUATION='延续输入画面里上一刻的同一场戏，承接已经发生的动作、持物和人物关系。人物的脸、衣服、房间布局与当前动作前后连续，直接接着表演。'


def _continuity(sid):
    if sid=='S01':return dict(kind='source_opening_with_canonical_identity',requires_current_run_previous_video_last=False)
    return dict(kind='previous_native_last_minimal_identity_edit',predecessor_segment=IDS[IDS.index(sid)-1],
                requires_current_run_previous_video_last=True,last_pixels_must_enter_image_edit=True,
                last_provenance_only_is_insufficient=True,
                identity_multiview_role='same_actor_identity_and_clothing_not_standing_pose',
                actual_input_image_verification='coordinator_native_input_binding_not_a_text_review')


def compile_segment(entry):
    source,by,body_start,body,states,descriptions,voice,audio=source_text._materials(entry)
    sid=entry['shot_id'];names=entry['character_names']
    if len(names)!=3 or len(set(names.values()))!=3:raise PromptError('three_explicit_source_mapped_actors_required')
    cast='本场角色仅为'+ '、'.join(names.values())+'；人物按本段动作入画或离场。'
    identity='同一人物的正面、侧面与细节参考只是该演员的身份和衣着依据；实际站位、朝向和动作由本段剧情决定。'
    parts=[STYLE,cast,identity,OPENING if sid=='S01' else CONTINUATION,PERFORMANCE,TEXT_POLICY]
    mapped=[]
    def append(span,role):
        start=sum(len(p)+1 for p in parts);parts.append(span['text'])
        mapped.append(dict(role=role,span_id=span['id'],source_range=dict(start=span['start'],end=span['end']),
                           prompt_range=dict(start=start,end=start+len(span['text'])),sha256=span['sha256']))
    # Establish the source name/appearance mapping at the opening. Later
    # segments continue the actual current input; portraits do not recast a
    # fresh group or prescribe their pose each time.
    if sid=='S01':
        for span in descriptions:append(span,'opening_identity_mapping')
    for span in voice:
        if span['text'] not in STYLE:append(span,'source_voice_and_cinematography')
    for span in states:append(span,'opening_state')
    offset=sum(len(p)+1 for p in parts);parts.append(body);text='\n'.join(parts)
    for span in by.values():
        if span['start']>=body_start:
            mapped.append(dict(role='source_'+span['kind'],span_id=span['id'],source_range=dict(start=span['start'],end=span['end']),
                               prompt_range=dict(start=offset+span['start']-body_start,end=offset+span['end']-body_start),sha256=span['sha256']))
    if [m.group() for m in source_text.QUOTE.finditer(text)]!=[a['text'] for a in audio]:
        raise PromptError('compiled_quotes_changed_duplicated_or_reordered')
    for m in mapped:
        a,b=m['prompt_range']['start'],m['prompt_range']['end'];x,y=m['source_range']['start'],m['source_range']['end']
        if text[a:b]!=source[x:y] or sha(text[a:b])!=m['sha256']:raise PromptError('source_to_prompt_map_changed')
    actions=[s['id'] for s in by.values() if s['kind']=='action']
    if {m['span_id'] for m in mapped if m['role']=='source_action'}!=set(actions):raise PromptError('source_action_coverage_incomplete')
    identity_sources=[dict(span_id=s['id'],source_range=dict(start=s['start'],end=s['end']),text=s['text'],sha256=s['sha256']) for s in descriptions]
    return dict(id=sid,source=entry['source'],source_entry_sha256=digest(entry),duration=entry['duration'],
                prompt_text=text,prompt_utf8_sha256=sha(text),audio=audio,source_map=mapped,
                mapped_actor_ids=list(names),mapped_actor_names=deepcopy(names),identity_sources=identity_sources,
                continuity_input_requirement=_continuity(sid),
                audit=dict(original_quote_count=len(audio),compiled_quote_count=len(list(source_text.QUOTE.finditer(text))),
                           ordered_quotes_exact=True,all_source_actions_copied=True,source_body_verbatim=True,
                           source_body_range=dict(start=body_start,end=entry['source_scope']['end']),prompt_body_range=dict(start=offset,end=len(text)),
                           identity_material_usage='establish_source_mapping' if sid=='S01' else 'continue_current_input_identity'),
                user_review_pending=True,native_text_absence_guaranteed=False,semantic_review_performed=False,
                model_calls=0,media_POSTs=0,production_approved=False)


def prepare(source_file=SOURCE,output_dir=OUT,*,node_capability=None):
    source_case=binding(source_file);spec=read(source_case);entries=spec.get('shots',[])
    if tuple(e.get('shot_id') for e in entries)!=IDS:raise PromptError('original_four_ordered_segments_required')
    rows=[compile_segment(e) for e in entries]
    if sum(len(r['audio']) for r in rows)!=10:raise PromptError('all_ten_original_quotes_required')
    if any(r['mapped_actor_names']!=rows[0]['mapped_actor_names'] for r in rows):raise PromptError('same_three_source_mapped_actors_required')
    output=Path(output_dir).resolve();segments=[]
    for row in rows:
        file=output/(row['id']+'.prompt.txt');source_text._bytes(file,row['prompt_text'].encode('utf8'))
        segments.append(dict({k:deepcopy(v) for k,v in row.items() if k!='prompt_text'},prompt=binding(file)))
    if node_capability is not None:check(node_capability)
    plan=dict(schema=SCHEMA,source_case=source_case,implementation=binding(__file__),source_validator=binding(source_text.__file__),
              segments=segments,audio_quote_count=10,node_capability=node_capability,
              identity_reference_usage='front_plus_shot_angle_same_identity_not_pose',
              continuity_policy='S02_S04_current_run_native_last_pixels_enter_minimal_identity_edit_before_H3_first',
              native_negative_prompt_used=False,native_fields={},postproduction_subtitles=False,
              user_review_pending=True,semantic_review_performed=False,native_text_absence_guaranteed=False,
              model_calls=0,media_POSTs=0,production_approved=False,publication=False)
    file=output/'PROMPT_PLAN.json';source_text._freeze(file,plan);return binding(file)


def validate(plan_binding):
    plan=read(plan_binding)
    if (plan.get('schema')!=SCHEMA or plan.get('audio_quote_count')!=10 or plan.get('user_review_pending') is not True
            or any(plan.get(k) is not False for k in ('production_approved','publication','semantic_review_performed','native_text_absence_guaranteed','native_negative_prompt_used'))
            or plan.get('native_fields')!={} or plan.get('model_calls')!=0 or plan.get('media_POSTs')!=0):
        raise PromptError('source_bound_user_review_pending_plan_required')
    check(plan['implementation']);check(plan['source_validator']);spec=read(plan['source_case'])
    if [r.get('id') for r in plan['segments']]!=list(IDS) or [s.get('shot_id') for s in spec['shots']]!=list(IDS):
        raise PromptError('original_four_prompt_files_required')
    for entry,row in zip(spec['shots'],plan['segments']):
        expected=compile_segment(entry);text=check(row['prompt']).read_bytes().decode('utf8')
        if text!=expected.pop('prompt_text') or {k:v for k,v in row.items() if k!='prompt'}!=expected:
            raise PromptError('compiled_prompt_continuity_or_source_audit_changed')
    if plan.get('node_capability') is not None:check(plan['node_capability'])
    return plan
