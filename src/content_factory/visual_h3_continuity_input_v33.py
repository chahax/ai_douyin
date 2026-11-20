"""Source-bound camera/audio contract and first-image identity coverage.

CPU-only validation/compilation. Reanchor is an upstream asset-stage work order,
never a fabricated claim that canonical portraits entered an I2V request.
"""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re
from PIL import Image, __version__ as PILLOW_VERSION
from . import visual_opening_frame as opening

SCHEMA='h3_continuity_input/v33'
REVIEW='h3_continuity_coverage_review/v33'
QUOTE=re.compile('“[^”]*”|「[^」]*」')
KINDS={'action','camera','audio','context'}
PARTS={'face','mouth','head','shoulders','torso','hands','legs','feet','back'}
FRAMINGS={'face_close','hands_close','medium','wide','detail'}
MODES={'onscreen','inner_voice','voiceover','offscreen_dialogue'}

class ContinuityError(ValueError):pass

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def binding(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
def check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or binding(value['path'])!=value:raise ContinuityError('bound_input_changed')
    return Path(value['path'])
def read(value):return json.loads(check(value).read_bytes().decode('utf-8'))
def image(value):
    path=check(value)
    with Image.open(path) as im:
        if getattr(im,'n_frames',1)!=1:raise ContinuityError('single_actual_png_required')
        size=list(im.size);im.verify()
    return size
def _number(v):return type(v) in (int,float) and v==v and abs(v)!=float('inf')
def _tri(v):return v is None or type(v) is bool

def validate_entry(entry):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',entry.get('shot_id','')):raise ContinuityError('safe_explicit_shot_id_required')
    # Offsets are Unicode character positions after universal-newline decoding;
    # the source binding independently authenticates every original file byte.
    source=check(entry['source']).read_text(encoding='utf-8');scope=entry['source_scope'];a,b=scope['start'],scope['end']
    if type(a) is not int or type(b) is not int or not 0<=a<b<=len(source):raise ContinuityError('exact_source_scope_required')
    spans=entry['source_spans'];by={};cursor=a;gaps=[];classification=[]
    for span in spans:
        x,y=span['start'],span['end'];kind=span['kind'];sid=span['id']
        if (kind not in KINDS or not isinstance(sid,str) or not sid or sid in by or type(x) is not int or type(y) is not int
                or not cursor<=x<y<=b or span['text']!=source[x:y] or span['sha256']!=sha(source[x:y])):raise ContinuityError('source_span_identity_position_or_sha_changed')
        if source[cursor:x].strip():gaps.append(dict(start=cursor,end=x,text=source[cursor:x],sha256=sha(source[cursor:x])))
        if kind=='action' and (QUOTE.search(span['text']) or re.search('镜头|特写|中近景|面部近景|平顺切|结束在',span['text'])):
            classification.append(dict(span_id=sid,reason='old_camera_or_audio_still_inside_action'))
        by[sid]=span;cursor=y
    if source[cursor:b].strip():gaps.append(dict(start=cursor,end=b,text=source[cursor:b],sha256=sha(source[cursor:b])))
    duration=entry['duration']
    if not _number(duration) or not 0<duration<=15:raise ContinuityError('bounded_source_duration_required')
    names=entry['character_names'];canon=entry['canonical_characters']
    if (not isinstance(names,dict) or not names or not isinstance(canon,dict) or not set(canon)<=set(names)
            or any(not isinstance(v,str) or not v.strip() or re.search('[“”「」\n\r]',v) for v in names.values())):raise ContinuityError('explicit_character_identity_mapping_required')
    for v in canon.values():image(v)
    image(entry['canonical_room']);image(entry['actual_first_image'])
    states=entry.get('source_state_span_ids',[])
    if not isinstance(states,list) or len(states)!=len(set(states)) or any(s not in by or by[s]['kind'] not in ('action','context') for s in states):raise ContinuityError('source_current_state_reference_required')
    state_material=''.join(by[s]['text'] for s in states)
    beats=entry['camera_beats'];previous=0;used=[];required_faces=set();visible=set();room_required=False
    for index,beat in enumerate(beats):
        start,end=beat['start'],beat['end']
        if (not _number(start) or not _number(end) or start!=previous or not start<end<=duration or type(beat['cut']) is not bool
                or index==0 and beat['cut'] or beat['framing'] not in FRAMINGS or not isinstance(beat['actors'],dict)):
            raise ContinuityError('explicit_contiguous_camera_beats_required')
        previous=end;ids=beat['source_span_ids']
        if not isinstance(ids,list) or any(s not in by or by[s]['kind']!='action' or s in used for s in ids):raise ContinuityError('each_action_span_assigned_once_required')
        used+=ids;material=''.join(by[s]['text'] for s in ids)
        for cid,actor in beat['actors'].items():
            parts=actor['visible_parts'];pose=actor['pose']
            if (cid not in canon or not isinstance(parts,list) or len(parts)!=len(set(parts)) or not set(parts)<=PARTS or not parts
                    or not isinstance(pose,str) or not pose.strip() or pose not in material and pose not in state_material):raise ContinuityError('visible_actor_parts_and_source_exact_pose_required')
            visible.add(cid)
            if 'face' in parts or 'mouth' in parts:required_faces.add(cid)
        if beat['framing'] in ('medium','wide'):room_required=True
    if not beats or previous!=duration or used!=[s['id'] for s in spans if s['kind']=='action']:raise ContinuityError('complete_ordered_action_and_camera_coverage_required')
    descriptions=entry.get('character_description_span_ids',{})
    if (not isinstance(descriptions,dict) or set(descriptions)-set(canon) or not visible<=set(descriptions)
            or any(not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(s not in by or by[s]['kind']!='context' for s in ids) for ids in descriptions.values())):
        raise ContinuityError('source_bound_visible_actor_descriptions_required')
    if any(QUOTE.search(by[s]['text']) or re.search('镜头|特写|中近景|面部近景|平顺切|结束在',by[s]['text']) for ids in descriptions.values() for s in ids):raise ContinuityError('actor_description_contains_legacy_camera_or_audio')
    audio_context=entry.get('audio_context_span_ids',[])
    if (not isinstance(audio_context,list) or len(audio_context)!=len(set(audio_context))
            or any(s not in by or by[s]['kind']!='context' or QUOTE.search(by[s]['text'])
                or re.search('镜头|特写|中近景|面部近景|平顺切|结束在',by[s]['text']) for s in audio_context)):
        raise ContinuityError('source_bound_audio_context_without_camera_required')
    if entry.get('audio_format','plain_zh')!='plain_zh':raise ContinuityError('explicit_plain_zh_audio_contract_required')
    quotes=list(QUOTE.finditer(source));audio=entry['audio'];seen=[];audio_spans=[s for s in spans if s['kind']=='audio']
    for item in audio:
        qi=item['quote_index']
        if type(qi) is not int or not 0<=qi<len(quotes) or qi in seen:raise ContinuityError('explicit_unique_quote_occurrence_required')
        quote=quotes[qi];seen.append(qi)
        if (item['quote_sha256']!=sha(quote.group()) or not any(s['start']==quote.start() and s['end']==quote.end() for s in audio_spans)
                or item['mode'] not in MODES or item['speaker'] not in names
                or not _number(item['start']) or not _number(item['end']) or not 0<=item['start']<item['end']<=duration):raise ContinuityError('source_bound_audio_occurrence_speaker_mode_required')
        if item['mode']=='onscreen' and not any(beat['start']<item['end'] and beat['end']>item['start']
                and item['speaker'] in beat['actors'] and set(beat['actors'][item['speaker']]['visible_parts']) & {'face','mouth'} for beat in beats):raise ContinuityError('onscreen_audio_has_no_planned_visible_face')
    if any(q.start()<b and q.end()>a and not a<=q.start()<q.end()<=b for q in quotes):raise ContinuityError('source_scope_cuts_quote_occurrence')
    scoped_quotes=[i for i,q in enumerate(quotes) if q.start()>=a and q.end()<=b]
    if seen!=scoped_quotes or len(audio)!=len(audio_spans):raise ContinuityError('all_source_quote_occurrences_once_in_order_required')
    if entry.get('postproduction_subtitles') is not False:raise ContinuityError('separate_postproduction_subtitle_track_must_be_disabled')
    opening.contract(entry)  # Explicit policies are validated; legacy stays byte compatible.
    return dict(source=source,spans=by,quotes=quotes,source_gaps=gaps,classification_issues=classification,source_coverage_complete=not gaps and not classification,required_faces=sorted(required_faces),visible_actors=sorted(visible),room_required=room_required)

def _review(entry,target,review_binding,requirements):
    review=read(review_binding);checks=review.get('checks',{});faces=checks.get('faces',{});identities=checks.get('identities',{})
    if (review.get('schema')!=REVIEW or not isinstance(review.get('reviewed_by'),str) or not review['reviewed_by'].strip()
            or review.get('target_image')!=target or review.get('canonical_characters')!=entry['canonical_characters']
            or review.get('canonical_room')!=entry['canonical_room'] or set(faces)!=set(entry['canonical_characters'])
            or set(identities)!=set(entry['canonical_characters']) or not _tri(checks.get('topology_coherent'))
            or not _tri(checks.get('room_identity')) or any(not _tri(v) for v in [*faces.values(),*identities.values()])
            or not isinstance(review.get('evidence'),list) or not review['evidence'] or any(not isinstance(e,str) or not e.strip() for e in review['evidence'])):
        raise ContinuityError('actual_image_canonical_bound_tristate_review_required')
    if any(v is True for v in [checks.get('topology_coherent'),checks.get('room_identity'),*faces.values(),*identities.values()]) and (review.get('completion_known') is not True or review.get('outcome_unknown') is not False):
        raise ContinuityError('true_coverage_requires_known_bound_observation')
    reasons=[]
    if checks.get('topology_coherent') is not True:reasons.append('head_body_topology_bad_or_unknown')
    if requirements['room_required'] and checks.get('room_identity') is not True:reasons.append('required_room_identity_bad_or_unknown')
    for cid in requirements['required_faces']:
        if faces[cid] is not True:reasons.append('required_face_missing_or_unknown:'+cid)
        if identities[cid] is not True:reasons.append('required_face_identity_bad_or_unknown:'+cid)
    if requirements.get('opening_frame'):
        reasons.extend(opening.review_reasons(requirements['opening_frame'],review))
    return review,reasons

def _base(entry):return {k:v for k,v in entry.items() if k!='reanchor'}

def _work_order(entry,requirements,reasons):
    value=dict(schema='h3_identity_reanchor_work_order/v33',shot_id=entry['shot_id'],entry_base_sha256=digest(_base(entry)),source=entry['source'],source_scope=entry['source_scope'],source_state=[requirements['spans'][s] for s in entry.get('source_state_span_ids',[])],camera_beats=entry['camera_beats'],original_tail=entry['actual_first_image'],original_coverage_review=entry['coverage_review'],canonical_characters=entry['canonical_characters'],canonical_room=entry['canonical_room'],required_faces=requirements['required_faces'],visible_actors=requirements['visible_actors'],reasons=reasons,target_stage='existing_first_frame_asset_generation_and_review',tail_role='continuity_context_only_not_truth_for_bad_or_unknown_topology',direct_video_reference_slots=0,model_calls=0)
    if requirements.get('opening_frame'):value['opening_frame']=requirements['opening_frame']
    return value

def _generation_receipt(entry,reanchor,work_order,requirements):
    receipt=reanchor['generation_receipt']
    if receipt.get('kind')=='derived_opening_crop/v1':return _derived_opening_crop_receipt(entry,reanchor,work_order,requirements)
    if receipt.get('kind')=='spatial_still_v24':return _spatial_receipt(entry,reanchor,work_order,requirements)
    if (receipt.get('kind')!='asset_ready' or receipt.get('ready')!=binding(Path(receipt.get('asset_run',''))/'H3_INPUT_READY.json')
            or reanchor.get('work_order_sha256')!=digest(work_order)):
        raise ContinuityError('actual_upstream_asset_generation_receipt_required')
    from . import visual_h3_handoff_v3 as native
    snapshot,ready,bindings=native.validate_ready(receipt['asset_run'])
    sid=receipt['shot_id'];matches=[s for s in bindings['shots'] if s['id']==sid]
    if len(matches)!=1 or {k:ready['first_frames'][sid][k] for k in ('path','sha256')}!=reanchor['image']:raise ContinuityError('reanchor_not_actual_reviewed_asset_output')
    refs=matches[0]['references']
    for cid in requirements['visible_actors']:
        if not any(r.get('kind')=='character' and r.get('entity_id')==cid and r.get('sha256')==entry['canonical_characters'][cid]['sha256'] for r in refs):raise ContinuityError('canonical_actor_not_in_verified_still_generation')
    if not any(r.get('kind')=='place' and r.get('sha256')==entry['canonical_room']['sha256'] for r in refs):raise ContinuityError('canonical_room_not_in_verified_still_generation')
    # Legacy READY records can contain reviewed metadata with no native image
    # generation proof. They are intentionally insufficient for a new reanchor.
    frame=ready['first_frames'][sid];proof=frame.get('generation_reference',{});native_result=frame.get('generation_receipt')
    if not proof.get('job_dir') or not isinstance(native_result,dict):raise ContinuityError('native_still_generation_proof_required')
    from . import visual_image_jobs_v3 as jobs
    job,plan,graph,output,consumed=_native_still(proof['job_dir'],reanchor['image'])
    if jobs._read(job/'RESULT.json')!=native_result:raise ContinuityError('actual_still_saved_receipt_changed')
    if consumed!={i['input_name'] for i in plan['inputs']}:raise ContinuityError('canonical_input_orphaned_from_still_output')
    crops=frame.get('static_start',{}).get('identity_crops',[])
    for cid in requirements['visible_actors']:
        expected=entry['canonical_characters'][cid]['sha256']
        valid={expected}|{c['crop_sha256'] for c in crops if c.get('source_identity',{}).get('entity_id')==cid
            and c.get('source_identity',{}).get('sha256')==expected}
        if not any(i['sha256'] in valid and i['input_name'] in consumed for i in plan['inputs']):raise ContinuityError('canonical_actor_pixels_not_consumed_by_still')
    actual_room=any(i['sha256']==entry['canonical_room']['sha256'] for i in plan['inputs'])
    if not actual_room and snapshot['plan']['config'].get('generation_reference_policy')!='geometry_materials_only/v1':raise ContinuityError('room_pixels_or_verified_geometry_material_qualification_required')
    return dict(kind='asset_ready',asset_run=str(Path(receipt['asset_run']).resolve()),ready=receipt['ready'],shot_id=sid,
        actual_generation_inputs_verified=True,native_job=dict(plan=binding(job/'PLAN.json'),request=binding(job/'REQUEST.json'),
        history=binding(job/'HISTORY.json'),result=binding(job/'RESULT.json')),
        consumed_inputs=[{k:i[k] for k in ('path','input_name','sha256','staged_path')} for i in plan['inputs']],
        canonical_room_role='actual_pixel_input' if actual_room else 'verified_existing_asset_geometry_material_qualification')


def _derived_opening_crop_receipt(entry,reanchor,work_order,requirements):
    """Authenticate a CPU framing derivative without relabeling it as native.

    Native parent history/inputs stay subject to the normal spatial producer
    proof. The parent need not have passed composition review; the derivative
    still needs its own target-bound visual observation in evaluate().
    """
    r=reanchor['generation_receipt'];first=requirements.get('opening_frame')
    if (not first or first.get('policy')!=opening.POLICY
            or first['opening_camera_beat']['framing']!='face_close'
            or len(first['opening_visible_actors'])!=1
            or r.get('parent_generation_receipt',{}).get('kind')!='spatial_still_v24'):
        raise ContinuityError('single_subject_source_opening_crop_required')
    parent=dict(image=r['parent_image'],generation_receipt=r['parent_generation_receipt'],
                work_order_sha256=reanchor.get('work_order_sha256'))
    parent_proof=_spatial_receipt(entry,parent,work_order,requirements)
    result=read(r['crop_result']);expected=digest(first)
    if (result.get('schema')!='story_opening_crop/v1' or result.get('parent_image')!=r['parent_image'] or result.get('image')!=reanchor['image']
            or result.get('opening_contract_sha256')!=expected
            or result.get('resampler')!='PIL.Image.Resampling.LANCZOS'
            or result.get('pillow_version')!=PILLOW_VERSION):
        raise ContinuityError('derived_crop_source_contract_or_algorithm_changed')
    detection=read(result['detection'])
    if (detection.get('schema')!='story_opening_face_detection/v1' or detection.get('status')!='unique_face_consensus'
            or detection.get('bbox_source')!='algorithm_auto_multirotation_consensus'
            or detection.get('method')!='opencv_yunet_rotation_consensus/v1'
            or detection.get('detector')!='opencv_yunet'
            or detection.get('source')!=r['parent_image']
            or detection.get('opening_contract_sha256')!=expected
            or detection.get('opening_contract')!=first
            or detection.get('box')!=result.get('box')):
        raise ContinuityError('derived_crop_requires_bound_automatic_unique_detection')
    model=detection.get('model',{})
    if model.get('sha256')!='8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4':
        raise ContinuityError('official_yunet_model_binding_required')
    check(model)
    check(detection['code'])
    consensus=detection.get('consensus',{});angles=consensus.get('supporting_angles',[])
    minimum=consensus.get('minimum_distinct_angles');threshold=detection.get('score_threshold');confidence=detection.get('confidence')
    if (type(minimum) is not int or minimum<2 or not isinstance(angles,list) or len(angles)<minimum
            or any(not _number(angle) for angle in angles) or len(set(angles))<minimum
            or not _number(threshold) or not .85<=threshold<=1
            or not _number(confidence) or not threshold<=confidence<=1):
        raise ContinuityError('derived_crop_requires_high_score_multirotation_consensus')
    candidates=detection.get('candidates');indices=consensus.get('candidate_indices')
    if (not isinstance(candidates,list) or not isinstance(indices,list) or len(indices)<minimum
            or any(type(i) is not int or not 0<=i<len(candidates) for i in indices) or len(indices)!=len(set(indices))):
        raise ContinuityError('bound_yunet_consensus_candidates_required')
    supported=[candidates[i] for i in indices]
    if (any(not isinstance(row,dict) or not _number(row.get('angle')) or not _number(row.get('score'))
            or not threshold<=row['score']<=1 for row in supported)
            or set(row['angle'] for row in supported)!=set(angles)
            or abs(min(row['score'] for row in supported)-confidence)>.0002):
        raise ContinuityError('bound_yunet_consensus_candidates_required')
    box=result.get('box',{});target=result.get('target_size')
    if (not isinstance(box,dict) or set(box)!={'x','y','width','height'}
            or any(type(v) is not int for v in box.values())
            or not isinstance(target,list) or len(target)!=2
            or any(type(v) is not int or not 1<=v<=2048 for v in target)):
        raise ContinuityError('exact_integer_crop_and_target_required')
    parent_size=image(r['parent_image']);output_size=image(reanchor['image'])
    if detection.get('source_size')!=parent_size:raise ContinuityError('detection_parent_dimensions_changed')
    landmarks=detection.get('landmarks')
    if (detection.get('landmark_geometry_valid') is not True or not isinstance(landmarks,list) or len(landmarks)!=5
            or any(not isinstance(p,list) or len(p)!=2 or any(not _number(v) for v in p)
                   or not 0<=p[0]<parent_size[0] or not 0<=p[1]<parent_size[1] for p in landmarks)
            or len({tuple(p) for p in landmarks})!=5):
        raise ContinuityError('valid_five_point_yunet_landmarks_required')
    x,y,w,h=(box[k] for k in ('x','y','width','height'))
    if (x<0 or y<0 or w<1 or h<1 or x+w>parent_size[0] or y+h>parent_size[1]
            or output_size!=target or target!=parent_size
            or abs(w/h/(target[0]/target[1])-1)>max(1/w,1/h)):
        raise ContinuityError('crop_bounds_aspect_or_native_canvas_changed')
    if any(not x<=p[0]<x+w or not y<=p[1]<y+h for p in landmarks):
        raise ContinuityError('automatic_crop_does_not_contain_detected_face_landmarks')
    with Image.open(check(r['parent_image'])) as source:
        expected_pixels=source.convert('RGB').crop((x,y,x+w,y+h)).resize(tuple(target),Image.Resampling.LANCZOS)
    with Image.open(check(reanchor['image'])) as actual:
        if actual.convert('RGB').tobytes()!=expected_pixels.tobytes():
            raise ContinuityError('derived_image_not_exact_parent_crop_resize_pixels')
    return dict(kind='derived_opening_crop/v1',parent_image=r['parent_image'],
        parent_generation_proof=parent_proof,crop_result=r['crop_result'],detection=result['detection'],
        box=box,target_size=target,resampler=result['resampler'],pillow_version=PILLOW_VERSION,
        image=reanchor['image'],opening_contract_sha256=expected,exact_pixels_verified=True,
        native_output=False,parent_visual_approval_inherited=False,production_approved=False)


def _native_still(job_dir,target):
    """Read native submission, staged pixels and saved history; never poll/collect."""
    from . import visual_image_jobs_v3 as jobs
    job,plan,graph=jobs._load(job_dir);jobs._inputs_ok(plan);state=jobs._state(job,plan)
    saved=jobs._read(job/'RESULT.json');pid=state.get('prompt_id');history=jobs._read(job/'HISTORY.json').get(pid,{})
    if (state.get('status')!='saved' or saved.get('prompt_id')!=pid or saved.get('job_id')!=plan['job_id']
            or saved.get('graph_sha256')!=jobs.digest(graph) or saved.get('inputs_sha256')!=jobs.digest(plan['inputs'])
            or saved.get('production_approved') is not False or history.get('prompt',[None,None,None])[2]!=graph
            or history.get('status',{}).get('completed') is not True or history.get('status',{}).get('status_str')!='success'):
        raise ContinuityError('actual_still_request_history_result_not_complete')
    selected=[i for i in saved.get('images',[]) if {k:i[k] for k in ('path','sha256')}==target]
    if len(selected)!=1 or not Path(selected[0]['path']).resolve().is_relative_to(job/'artifacts'):raise ContinuityError('reanchor_not_native_still_saved_image')
    output=selected[0];size=image(target);save_node=graph.get(output.get('save_node'),{})
    declarations=history.get('outputs',{}).get(output.get('save_node'),{}).get('images',[])
    origin=Path(output.get('source_path','')).resolve();expected_origin=None
    for declared in declarations:
        if declared.get('type')!='output':continue
        filename=declared.get('filename');subfolder=declared.get('subfolder','').replace('\\','/')
        if not isinstance(filename,str) or Path(filename).name!=filename:raise ContinuityError('native_still_output_filename_invalid')
        actual=jobs._bound(plan['config']['output_root'],subfolder+'/'+filename if subfolder else filename)
        if actual==origin:expected_origin=actual
    if (save_node.get('class_type')!='SaveImage' or expected_origin is None or not origin.is_file()
            or binding(origin)['sha256']!=target['sha256'] or Path(output['path']).name!=origin.name or output.get('dimensions')!=size):
        raise ContinuityError('native_still_history_output_pixels_not_proven')
    ancestors=set()
    def visit(nid):
        if nid in ancestors:return
        if nid not in graph:raise ContinuityError('actual_still_graph_dependency_missing')
        ancestors.add(nid)
        for val in graph[nid]['inputs'].values():
            if isinstance(val,list) and len(val)==2 and isinstance(val[0],str) and type(val[1]) is int:visit(val[0])
    visit(output['save_node'])
    consumed={graph[n]['inputs']['image'] for n in ancestors if graph[n]['class_type']=='LoadImage'}
    return job,plan,graph,output,consumed


def _spatial_source_review(entry,work_order,plan,item,value):
    review=read(value)
    if (review.get('schema')!='h3_reanchor_source_state_review/v33' or review.get('work_order_sha256')!=digest(work_order)
            or review.get('entry_base_sha256')!=digest(_base(entry)) or review.get('spatial_plan')!=plan['spatial_plan']
            or review.get('item_id')!=item['id'] or review.get('state_sha256')!=digest(item['state'])
            or review.get('canonical_characters')!=entry['canonical_characters'] or review.get('canonical_room')!=entry['canonical_room']
            or review.get('source_current_state_matches') is not True or review.get('room_identity_matches') is not True
            or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
            or not isinstance(review.get('reviewed_by'),str) or not review['reviewed_by'].strip()
            or not isinstance(review.get('evidence'),list) or not review['evidence'] or any(not isinstance(e,str) or not e.strip() for e in review['evidence'])):
        raise ContinuityError('source_bound_spatial_state_review_required')
    return review


def _spatial_receipt(entry,reanchor,work_order,requirements):
    from . import visual_spatial_stills_v24 as stills
    r=reanchor['generation_receipt'];run,p,folder,b=stills._batch(r['run'],r['batch_id'])
    # Validate the real Blender source and all of its image/hash lineage too.
    _,render_result,_,_,spatial,portraits,metadata,material=stills._source(*(p['source'][k]['path'] for k in ('handoff','render_result','inputs','authorization')),
        require_material_policy=p.get('material_contract',{}).get('policy'))
    candidates=read(r['candidates']);item_ids=b['item_ids']
    rows=[i for i in p['items'] if i['id']==r['item_id']]
    if len(rows)!=1 or r['item_id'] not in item_ids or r['candidates']!=binding(folder/'CANDIDATES.json'):
        raise ContinuityError('actual_spatial_still_item_required')
    item=rows[0];_spatial_source_review(entry,work_order,p,item,r['source_binding_review'])
    render=[v for v in metadata['renders'] if v['name']==r['item_id']]
    stage=[v for v in render_result['files'] if Path(v['path']).stem==r['item_id']]
    if (len(render)!=1 or len(stage)!=1 or item['stage']!=stage[0] or item['render']!=render[0]
            or item['state']!=stills._state(spatial,r['item_id'])):raise ContinuityError('reanchor_not_actual_bound_blender_stage')
    source_shot=next((s for s in spatial['shots'] if item['id']==s['id']+'_start'),None)
    source_opening=source_shot.get('opening_frame') if source_shot else None
    if item.get('opening_frame')!=source_opening:raise ContinuityError('spatial_opening_receipt_changed')
    if source_opening is not None:opening.validate_selection(source_opening)
    slots=stills._screen_slots(spatial,item['state'],render[0]) if p.get('reference_packing')==stills.SCREEN_PACKING else None
    ordered=[v['entity_id'] for v in slots] if slots is not None else item['visible_cast']
    expected_refs=[dict(kind='stage',image=stage[0])]+[dict(kind='character',entity_id=who,image=portraits[who]['image']) for who in ordered]
    if item['references']!=expected_refs or item['prompt']!=stills._prompt(item['id'],item['state'],item['visible_cast'],material,slots,**({'opening_frame':item['opening_frame']} if item.get('opening_frame') else {})):raise ContinuityError('spatial_prompt_or_reference_order_changed')
    if requirements.get('opening_frame'):
        expected=requirements['opening_frame']
        if (not item.get('opening_frame') or item['opening_frame'].get('camera_beat')!=expected['opening_camera_beat']
                or sorted(item['opening_frame'].get('in_frame_actor_ids',[]))!=expected['opening_visible_actors']):
            raise ContinuityError('spatial_opening_not_first_source_camera_beat')
    if (reanchor.get('work_order_sha256')!=digest(work_order) or candidates.get('schema')!=stills.SCHEMA
            or candidates.get('batch')!=binding(folder/'BATCH.json') or candidates.get('native_result')!=binding(folder/'RESULT.json')):
        raise ContinuityError('spatial_native_candidate_receipt_changed')
    selected=[i for i in candidates['items'] if i['id']==r['item_id'] and i['image']==reanchor['image']]
    if len(selected)!=1 or set(item['visible_cast'])!=set(requirements['visible_actors']):raise ContinuityError('spatial_reanchor_actual_cast_changed')
    job,plan,graph,output,consumed=_native_still(folder,reanchor['image'])
    from . import visual_image_jobs_v3 as jobs
    scope=stills.PREFIX+'/'+plan['job_id'];byid={v['id']:v for v in p['items']};batch_items=[];expected_inputs={}
    for name in b['item_ids']:
        row=byid[name];rr=[]
        for ref in row['references']:
            key='stage_'+name if ref['kind']=='stage' else 'cast_'+ref['entity_id'];input_name=scope+'/references/'+key+'.png'
            rr.append(dict(input_name=input_name));expected_inputs[input_name]=dict(input_name=input_name,**ref['image'])
        batch_items.append(dict(id=name,prompt=row['prompt'],seed=row['seed'],references=rr))
    expected_graph=jobs.build_graph(batch_items,scope,width=p['width'],height=p['height'],steps=p['steps'])
    if graph!=expected_graph or {i['input_name']:{k:i[k] for k in ('path','sha256','input_name')} for i in plan['inputs']}!=expected_inputs:
        raise ContinuityError('spatial_actual_native_conditioning_mapping_changed')
    if selected[0]['save_node']!=output['save_node'] or selected[0]['prompt_id']!=stills.read(folder/'RESULT.json')['prompt_id']:
        raise ContinuityError('spatial_reanchor_native_branch_changed')
    expected=[]
    for ref in item['references']:
        if ref['kind']=='character' and ref['image']!=entry['canonical_characters'].get(ref['entity_id']):raise ContinuityError('canonical_actor_not_spatial_still_input')
        expected.append(ref['image']['sha256'])
    actual=[i for i in plan['inputs'] if i['input_name'] in consumed]
    if sorted(i['sha256'] for i in actual)!=sorted(expected):raise ContinuityError('spatial_actual_four_image_conditioning_changed')
    # This producer uses a rendered geometry stage plus portraits. Room identity
    # is reviewed against the canonical room, never falsely called a pixel input.
    return dict(kind='spatial_still_v24',plan=binding(run/'PLAN.json'),batch=binding(folder/'BATCH.json'),
        candidates=r['candidates'],source_binding_review=r['source_binding_review'],
        native_job={k:binding(folder/f) for k,f in [('plan','PLAN.json'),('request','REQUEST.json'),('history','HISTORY.json'),('result','RESULT.json')]},
        consumed_inputs=actual,actual_generation_inputs_verified=True,
        canonical_room_role='source_bound_review_of_designed_geometry_stage_not_direct_room_pixels',production_approved=False)

def compile_entry(entry,requirements):
    names=entry['character_names'];pieces=['真人写实摄影剧情。人物身体、服装和房间材料按已审核首图及下列真实动作呈现；叙事通过表演和声音传达。对白文字仅作为声音轨的发音内容，画面按摄影镜头呈现。']
    parts=dict(face='面部',mouth='嘴部',head='头部',shoulders='肩部',torso='躯干',hands='双手',legs='双腿',feet='双脚',back='背部')
    framings=dict(face_close='头肩近景',hands_close='手部及所持物近景',medium='中景',wide='全景',detail='局部细节镜头')
    descriptions={s for cid,ids in entry['character_description_span_ids'].items() if cid in requirements['visible_actors'] for s in ids}
    if descriptions:
        description=''.join(s['text'] for s in entry['source_spans'] if s['id'] in descriptions).strip()
        if entry.get('first_frame_policy')==opening.POLICY:
            # Old technical annotations assumed an all-cast first picture.
            # Their identity facts remain; later actors are not asserted to
            # exist in the newly framed opening image.
            description=description.replace('首图中的','本段的')
        pieces.append('人物身份与服装：'+description)
    states=[requirements['spans'][s]['text'] for s in entry.get('source_state_span_ids',[]) if requirements['spans'][s]['kind']=='context' and s not in descriptions]
    if states:pieces.append('开场承接：'+''.join(states).strip())
    if entry.get('first_frame_policy')==opening.POLICY:
        pieces.append('首图就是下列0秒开始的第一个剧情镜头，人物按当时动作与注意对象演出；随后按时间推进并切换镜头。')
    for beat in entry['camera_beats']:
        actions=''.join(requirements['spans'][sid]['text'] for sid in beat['source_span_ids'])
        # A source action is scheduled once. A pose already present in that action
        # is not repeated as a second instruction; inherited states stay states.
        actors='；'.join('画面呈现'+names[cid]+'的'+'、'.join(parts[p] for p in actor['visible_parts']) for cid,actor in beat['actors'].items())
        pieces.append(f"{beat['start']:g}—{beat['end']:g}秒，"+('明确切到' if beat['cut'] else '以')+framings[beat['framing']]+'呈现。'+actors+'。'+actions)
    pieces.append('声音轨按原句依次演出：')
    audio_context=set(entry.get('audio_context_span_ids',[]))
    if audio_context:pieces.append(''.join(s['text'] for s in entry['source_spans'] if s['id'] in audio_context).strip())
    for item in entry['audio']:
        subject=names[item['speaker']];quote=requirements['quotes'][item['quote_index']].group()
        if item['mode']=='onscreen':voice=subject+'本人开口说：'+quote
        elif item['mode']=='inner_voice':voice=subject+'的内心独白，以'+subject+'的画外音呈现：'+quote+'；'+subject+'入镜时嘴唇自然闭合，保持原动作与表情。'
        elif item['mode']=='offscreen_dialogue':voice='画外的'+subject+'说：'+quote
        else:voice=subject+'的画外音：'+quote
        pieces.append(f"{item['start']:g}—{item['end']:g}秒，"+voice)
    text='\n'.join(pieces)
    if [m.group() for m in QUOTE.finditer(text)]!=[requirements['quotes'][x['quote_index']].group() for x in entry['audio']]:raise ContinuityError('compiled_audio_changed_or_duplicated')
    return text

def compile_prompt(entry):
    req=validate_entry(entry)
    text=compile_entry(entry,req)
    return dict(schema=SCHEMA,shot_id=entry['shot_id'],status='draft_not_dispatchable',dispatchable=False,
        compiled_prompt=text,compiled_prompt_utf8_sha256=sha(text),entry_sha256=digest(entry),
        source_coverage_complete=req['source_coverage_complete'],source_gaps=req['source_gaps'],
        classification_issues=req['classification_issues'],required_faces=req['required_faces'],model_calls=0,
        native_text_absence_guaranteed=False,production_approved=False)

def evaluate(entry,actual_first_image=None):
    req=validate_entry(entry);base=dict(schema=SCHEMA,shot_id=entry['shot_id'],entry_sha256=digest(entry),required_faces=req['required_faces'],visible_actors=req['visible_actors'],source_coverage_complete=req['source_coverage_complete'],source_gaps=req['source_gaps'],classification_issues=req['classification_issues'],direct_video_reference_slots=0,postproduction_subtitles=False,native_text_absence_guaranteed=False,model_calls=0)
    if not req['source_coverage_complete']:return dict(base,status='source_classification_required')
    coverage=opening.requirements(entry,req)
    if coverage.get('opening_frame'):
        base['first_frame_requirements']={k:coverage[k] for k in ('required_faces','visible_actors','room_required','opening_frame')}
    _,reasons=_review(entry,entry['actual_first_image'],entry['coverage_review'],coverage)
    selected=entry['actual_first_image'];selected_review=entry['coverage_review'];receipt=None
    if reasons:
        work=_work_order(entry,coverage,reasons)
        if not entry.get('reanchor'):return dict(base,status='reanchor_required',work_order=work,work_order_sha256=digest(work))
        anchor=entry['reanchor'];image(anchor['image']);receipt=_generation_receipt(entry,anchor,work,coverage)
        review,remaining=_review(entry,anchor['image'],anchor['coverage_review'],coverage)
        if review.get('work_order_sha256')!=digest(work) or review.get('source_current_state_matches') is not True or remaining:raise ContinuityError('reanchor_same_source_identity_review_not_true')
        selected=anchor['image'];selected_review=anchor['coverage_review']
    elif entry.get('reanchor'):raise ContinuityError('unnecessary_unbound_reanchor_refused')
    if actual_first_image is not None and actual_first_image!=selected:raise ContinuityError('handoff_png_not_selected_reviewed_first_image')
    image(selected);text=compile_entry(entry,req)
    return dict(base,status='ready',first_image=selected,coverage_review=selected_review,generation_receipt=receipt,compiled_prompt=text,
        compiled_prompt_utf8_sha256=sha(text),dispatchable=False,handoff_requires_current_mapping_check=True)

def _entries(plan_binding):
    plan=read(plan_binding)
    if plan.get('schema')!=SCHEMA or not isinstance(plan.get('shots'),list) or not plan['shots'] or len({s['shot_id'] for s in plan['shots']})!=len(plan['shots']):raise ContinuityError('explicit_unique_continuity_shots_required')
    return plan['shots']
def preflight(plan_binding,shot_id,actual_first_image=None):
    rows=[s for s in _entries(plan_binding) if s['shot_id']==shot_id]
    if len(rows)!=1:raise ContinuityError('continuity_shot_missing')
    return dict(evaluate(rows[0],actual_first_image),plan=plan_binding)

def preview_prompt(plan_binding,shot_id):
    rows=[s for s in _entries(plan_binding) if s['shot_id']==shot_id]
    if len(rows)!=1:raise ContinuityError('continuity_shot_missing')
    return dict(compile_prompt(rows[0]),plan=plan_binding)
def load_for(packet,plan_binding,shot,frame,timing):
    rows=[s for s in _entries(plan_binding) if s['shot_id']==shot['id']]
    if len(rows)!=1:raise ContinuityError('continuity_shot_missing')
    entry=rows[0]
    if packet.get('schema')=='h3_continuity_packet/v33':
        expected=handoff_snapshot(plan_binding,packet['service_config'])[2]
        if packet['source']!=plan_binding or shot not in expected['shots']:raise ContinuityError('actual_continuity_shot_not_bound')
    elif entry.get('handoff_binding')!=dict(packet_sha256=digest(packet),shot_sha256=digest(shot)):raise ContinuityError('actual_packet_shot_not_bound')
    if entry['duration']!=timing['requested_seconds']:raise ContinuityError('source_camera_audio_timing_changed')
    actual=dict(path=str(Path(frame['path']).resolve()),sha256=frame['sha256'])
    result=evaluate(entry,actual)
    return dict(result,plan=plan_binding,handoff_eligible=result['status']=='ready')


def handoff_snapshot(plan_binding,config):
    """Explicit v33 adapter, not a v3 READY or a relaxed max-two cast packet."""
    entries=_entries(plan_binding);shots=[];frames={};reports=[]
    keys=('service_url','input_root','output_root','gpu_lock_root','protected_pause_path')
    if any(k not in config for k in keys):raise ContinuityError('explicit_shared_service_and_protected_scope_required')
    service={k:config[k] for k in keys};base=dict(image_service={k:service[k] for k in ('service_url','input_root','output_root')},
        gpu_lock_root=service['gpu_lock_root'],protected_pause_path=service['protected_pause_path'])
    for entry in entries:
        req=validate_entry(entry);report=evaluate(entry);reports.append(report)
        first=report.get('first_image',entry['actual_first_image']);sid=entry['shot_id']
        shot=dict(id=sid,source_entry_sha256=digest(entry),start=0,end=entry['duration'],
            visible_cast=req['visible_actors'],visual_prompt=''.join(s['text'] for s in entry['source_spans'] if s['kind']=='action'),
            audio=[dict(speaker=i['speaker'],mode=i['mode'],text=req['quotes'][i['quote_index']].group()[1:-1]) for i in entry['audio']],
            camera_beats=deepcopy(entry['camera_beats']),references=[dict(entity_id=cid,kind='character',**entry['canonical_characters'][cid]) for cid in req['visible_actors']])
        shot['binding_sha256']=digest(shot);shots.append(shot)
        frames[sid]=dict(first,binding_sha256=shot['binding_sha256'])
    packet=dict(schema='h3_continuity_packet/v33',source=plan_binding,shots=shots,service_config=service)
    snapshot=dict(plan=dict(schema=SCHEMA,packet=packet,config=base),state=dict(status='v33_continuity_preflight'),reports=reports)
    ready=dict(schema='h3_continuity_selected_inputs/v33',source=plan_binding,first_frames=frames)
    bindings=dict(schema='h3_continuity_shot_bindings/v33',shots=shots)
    return snapshot,ready,bindings


def prepare_reanchor(plan_binding,shot_id,run,*,handoff,render_result,inputs,authorization,config,item_id,source_binding_review):
    """Prepare the existing three-person Klein producer; this never calls tick."""
    from . import visual_spatial_stills_v24 as stills
    rows=[s for s in _entries(plan_binding) if s['shot_id']==shot_id]
    if len(rows)!=1:raise ContinuityError('continuity_shot_missing')
    entry=rows[0];report=evaluate(entry)
    if report['status']!='reanchor_required':raise ContinuityError('reanchor_work_order_required')
    # Producer preparation validates Blender/canonical lineage and stages real
    # image bytes. The old v3 cast limit and old frozen job files stay untouched.
    result=stills.prepare(run,handoff=handoff,render_result=render_result,inputs=inputs,authorization=authorization,config=config,
        reference_packing=stills.SCREEN_PACKING)
    _,p=stills._load(run);items=[i for i in p['items'] if i['id']==item_id]
    if len(items)!=1:raise ContinuityError('actual_spatial_still_item_required')
    item=items[0];_spatial_source_review(entry,report['work_order'],p,item,source_binding_review)
    image_cast=report.get('first_frame_requirements',{}).get('visible_actors',report['visible_actors'])
    if set(item['visible_cast'])!=set(image_cast):raise ContinuityError('spatial_reanchor_actual_cast_changed')
    if entry.get('first_frame_policy')==opening.POLICY:
        first=entry['camera_beats'][0]
        if not item.get('opening_frame') or item['opening_frame'].get('camera_beat')!=first:
            raise ContinuityError('spatial_opening_not_first_source_camera_beat')
        opening.validate_selection(item['opening_frame'])
    for ref in item['references']:
        if ref['kind']=='character' and ref['image']!=entry['canonical_characters'].get(ref['entity_id']):raise ContinuityError('canonical_actor_not_spatial_still_input')
    from .visual_h3_handoff_v3 import freeze
    freeze(Path(run)/'REANCHOR_WORK_ORDER.json',report['work_order'])
    freeze(Path(run)/'SOURCE_STATE_REVIEW_BINDING.json',source_binding_review)
    batch=stills.prepare_batch(run,'reanchor_'+shot_id,[item_id])
    return dict(status='image_job_prepared_not_submitted',work_order_sha256=report['work_order_sha256'],producer=result,batch=batch,
        receipt_template=dict(kind='spatial_still_v24',run=str(Path(run).resolve()),batch_id='reanchor_'+shot_id,item_id=item_id,
        candidates=dict(path=str((Path(run)/'batches'/('reanchor_'+shot_id)/'CANDIDATES.json').resolve()),sha256=None),source_binding_review=source_binding_review),
        model_calls=0,production_approved=False)
def prepare(plan_binding,out):
    out=Path(out).resolve();rows=_entries(plan_binding);reports=[dict(evaluate(row),plan=plan_binding) for row in rows]
    out.mkdir(parents=True,exist_ok=True)
    from .visual_h3_handoff_v3 import freeze
    for report in reports:freeze(out/(report['shot_id']+'.json'),report)
    value=dict(schema=SCHEMA,plan=plan_binding,shots=reports,ready=sum(r['status']=='ready' for r in reports),model_calls=0,production_approved=False)
    freeze(out/'PREFLIGHT.json',value);return value
