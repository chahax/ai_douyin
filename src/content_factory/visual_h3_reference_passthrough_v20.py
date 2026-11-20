"""Pure raw-text + reviewed-reference adapter for a new Ref2VA graph.

No text model, media submission, input staging, registry write or executor.
The existing v15/v19 handoff and all its frozen graphs remain independent.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from PIL import Image
from . import visual_h3_reference_bundle_v20 as bundles

CONTRACT='raw_prompt_reviewed_references/v20'
REF2VA_MODEL='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
NODE='MiniMaxH3ReferenceToVideo'
MAX_IMAGES=9
COMPLETE_FIELDS=('complete_video_prompt','full_video_prompt','video_prompt','source_video_prompt')


class ReferencePassthroughError(ValueError):
    pass


def _sha(data):return hashlib.sha256(data).hexdigest()


def _check_file(value):
    if (not isinstance(value,dict) or set(value)!={'path','sha256'}
            or not Path(value['path']).is_file() or _sha(Path(value['path']).read_bytes())!=value['sha256']):
        raise ReferencePassthroughError('bound_reference_file_changed')
    return Path(value['path'])


def _relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:
        raise ReferencePassthroughError('relative_staged_input_or_scope_required')
    path=PurePosixPath(value)
    if path.is_absolute() or any(p in ('..','.') for p in value.split('/')) or str(path)!=value:
        raise ReferencePassthroughError('relative_staged_input_or_scope_required')
    return value


def source_text(value):
    """UTF-8 only, with BOM/CRLF retained; never trim or normalize a raw request."""
    if isinstance(value,bytes):
        try:text=value.decode('utf-8')
        except UnicodeDecodeError as error:raise ReferencePassthroughError('UTF8_source_prompt_required') from error
    elif isinstance(value,str):text=value
    else:raise ReferencePassthroughError('explicit_original_prompt_required')
    if not text.strip():raise ReferencePassthroughError('explicit_original_prompt_required')
    return text


def audio_records_from_shot(shot):
    """All original audio metadata is kept, including optional directions."""
    records=shot.get('audio',[])
    if not isinstance(records,list):raise ReferencePassthroughError('source_audio_list_required')
    for record in records:
        if (not isinstance(record,dict) or not isinstance(record.get('speaker'),str)
                or not isinstance(record.get('mode'),str) or not isinstance(record.get('text'),str)
                or not record['text'].strip()):
            raise ReferencePassthroughError('complete_source_audio_record_required')
    return deepcopy(records)


def prompt_from_source_window(scene,window):
    """Render accepted source rows, never the asset planner's rewritten prose.

    Only current action IDs plus still-running earlier actions enter this
    window. Audio IDs select complete original utterances. Description/text
    strings are concatenated directly so quotes and newlines stay unchanged.
    """
    if not isinstance(scene.get('id'),str) or not scene['id'] or window.get('scene_id')!=scene['id']:
        raise ReferencePassthroughError('source_window_scene_mismatch')
    start,end=window.get('start'),window.get('end')
    if (any(type(n) not in (int,float) or not math.isfinite(n) for n in (start,end))
            or not 0<=start<end or 'seconds' in scene and end>scene['seconds']):
        raise ReferencePassthroughError('valid_original_source_window_required')
    selected={}
    for kind,key in (('actions','action_ids'),('audio','audio_ids')):
        rows=scene.get(kind,[]);ids=window.get(key,[])
        if (not isinstance(rows,list) or not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids))
                or any(not isinstance(row,dict) or not isinstance(row.get('id'),str) for row in rows)):
            raise ReferencePassthroughError('explicit_unique_source_window_ids_required')
        by={row['id']:row for row in rows}
        if len(by)!=len(rows) or not set(ids)<=set(by):
            raise ReferencePassthroughError('source_window_unknown_or_duplicate_id')
        chosen=[]
        for i,row in enumerate(rows):
            a,b=row.get('start'),row.get('end')
            if any(type(n) not in (int,float) or not math.isfinite(n) for n in (a,b)) or not 0<=a<b:
                raise ReferencePassthroughError('original_source_row_interval_required')
            overlap=a<end and b>start
            if row['id'] in ids and not overlap:raise ReferencePassthroughError('source_row_outside_current_window')
            include=row['id'] in ids or kind=='actions' and a<start and overlap
            if not include:continue
            content=row.get('description' if kind=='actions' else 'text')
            if not isinstance(content,str) or not content.strip():raise ReferencePassthroughError('original_source_row_text_required')
            if kind=='audio' and (a<start or b>end):raise ReferencePassthroughError('source_audio_cannot_be_split_across_window')
            if kind=='audio':audio_records_from_shot(dict(audio=[row]))
            chosen.append((a,i,row))
        selected[kind]=[row for _,_,row in sorted(chosen,key=lambda x:(x[0],x[1]))]
    context={k:deepcopy(scene[k]) for k in ('timeline','story_time','place_id','location','time') if k in scene}
    lines=['原场景：'+str(scene['id']),'原时空资料：'+json.dumps(context,ensure_ascii=False),
        '本窗原时间：'+json.dumps(dict(start=start,end=end),ensure_ascii=False),
        '本段相对时间范围：'+json.dumps(dict(start=0,end=round(end-start,9)),ensure_ascii=False)]
    if 'camera' in scene:
        camera=scene['camera'];lines+=['原机位说明：',camera if isinstance(camera,str) else json.dumps(camera,ensure_ascii=False)]
    events=[]
    for rank,(kind,label,content_key) in enumerate((('actions','原动作资料','description'),('audio','原音频资料','text'))):
        for index,row in enumerate(selected[kind]):
            events.append((max(row['start'],start),row['start'],rank,index,label,content_key,row))
    for _,_,_,_,label,content_key,row in sorted(events,key=lambda item:item[:4]):
        interval=dict(start=round(max(row['start'],start)-start,9),end=round(min(row['end'],end)-start,9))
        lines.append(label+'（本段相对时间）：'+json.dumps(interval,ensure_ascii=False))
        metadata={k:deepcopy(v) for k,v in row.items() if k!=content_key}
        lines.append('原记录元数据：'+json.dumps(metadata,ensure_ascii=False))
        lines.append(row[content_key])
    return '\n'.join(lines)


def prompt_from_shot(shot):
    """Deterministic fallback for structured source, never a motion rewrite.

    A declared complete video field is returned verbatim and must contain its
    original spoken sentences.  Otherwise keep visual_prompt verbatim and add
    the unchanged source audio records once. Opening/static fields are ignored.
    Explicit raw-file bytes passed to build_graph bypass this renderer entirely.
    """
    records=audio_records_from_shot(shot)
    for key in COMPLETE_FIELDS:
        if key in shot:
            text=source_text(shot[key])
            if any(record['text'] not in text for record in records):
                raise ReferencePassthroughError('declared_complete_video_prompt_missing_source_audio')
            return text
    if shot.get('staging_provenance',{}).get('schema')=='continuous_source_home_staging/v6':
        raise ReferencePassthroughError('legacy_v6_staging_requires_explicit_original_video_prompt')
    if 'visual_prompt' not in shot:
        raise ReferencePassthroughError('complete_video_or_dynamic_visual_prompt_required')
    text=source_text(shot['visual_prompt'])
    if records:
        lines=['原音频资料：']
        for record in records:
            lines.append(json.dumps({k:deepcopy(value) for k,value in record.items() if k!='text'},ensure_ascii=False))
            lines.append(record['text'])
        text+='\n\n'+'\n'.join(lines)
    return text


def _references(bundle,auxiliary_tail):
    if bundle.get('schema')!=bundles.SCHEMA:raise ReferencePassthroughError('reviewed_reference_bundle_required')
    references=deepcopy(bundle.get('references',[]));index={r['reference_id']:r for r in references}
    if len(index)!=len(references):raise ReferencePassthroughError('duplicate_reference_identity')
    characters=bundle.get('characters',[]);environment=bundle.get('environment',{})
    visible=bundle.get('source_shot',{}).get('visible_cast')
    actual=[r.get('entity_id') for r in characters]
    if (not isinstance(visible,list) or len(visible)!=len(set(visible)) or len(actual)!=len(set(actual))
            or set(actual)!=set(visible)):
        raise ReferencePassthroughError('character_references_must_exactly_match_source_visible_cast')
    required=[]
    for actor in characters:
        for role in ('canonical_reference','shot_reference'):
            rid=actor.get(role);record=index.get(rid,{})
            if record.get('kind')!='character' or record.get('entity_id')!=actor['entity_id']:
                raise ReferencePassthroughError('canonical_and_shot_character_reference_required')
            required.append(rid)
    for role in ('canonical_reference','shot_reference'):
        rid=environment.get(role);record=index.get(rid,{})
        if record.get('kind')!='place' or record.get('entity_id')!=environment.get('entity_id'):
            raise ReferencePassthroughError('canonical_and_shot_environment_reference_required')
        required.append(rid)
    if set(index)!=set(required):raise ReferencePassthroughError('reference_outside_current_cast_or_environment')
    # This is the authoritative asset/library validation, not a synthetic pass.
    bundles.validate(bundle)
    if auxiliary_tail is not None:
        for key in ('image','native_result','review'):_check_file(auxiliary_tail[key])
        receipt=json.loads(Path(auxiliary_tail['native_result']['path']).read_text(encoding='utf-8'))
        decision=json.loads(Path(auxiliary_tail['review']['path']).read_text(encoding='utf-8'))
        last=receipt.get('files',{}).get('last',{})
        if ({key:last.get(key) for key in ('path','sha256')}!=auxiliary_tail['image']
                or not isinstance(receipt.get('prompt_id'),str) or not receipt['prompt_id']
                or decision.get('schema')!='reviewed_h3_auxiliary_tail/v20'
                or decision.get('accepted_for_continuity') is not True
                or decision.get('source')!=bundle['source'] or str(decision.get('book_id'))!=str(bundle['book_id'])
                or decision.get('image')!=auxiliary_tail['image']
                or decision.get('native_result')!=auxiliary_tail['native_result']):
            raise ReferencePassthroughError('explicit_reviewed_known_tail_required')
        references.append(dict(reference_id='auxiliary_tail',entity_id='previous_segment',kind='continuity',
            view='tail',display_name='前段画面承接',image=deepcopy(auxiliary_tail['image'])))
    if not 1<=len(references)<=MAX_IMAGES:
        raise ReferencePassthroughError('local_ref2va_maximum_nine_images_no_truncation')
    for record in references:
        path=_check_file(record['image'])
        with Image.open(path) as image:
            if getattr(image,'n_frames',1)!=1:raise ReferencePassthroughError('one_image_per_reference_slot_required')
            image.verify()
    return references


def _appendix(refs):
    groups={}
    for number,record in enumerate(refs,1):
        groups.setdefault((record['kind'],record['entity_id']),[]).append((number,record))
    lines=['参考内容：']
    for (kind,_),members in groups.items():
        name=json.dumps(members[0][1]['display_name'],ensure_ascii=False)
        views='；'.join('<Picture '+str(number)+'>：'+record['view'] for number,record in members)
        if kind=='character':lines.append(views+'。同一人物'+name+'的外观与服装参考。')
        elif kind=='place':lines.append(views+'。同一场景'+name+'的环境参考。')
        else:lines.append(views+'。前段已审核画面的承接参考。')
    return '\n\n'+'\n'.join(lines)


def compile_prompt(bundle,source_prompt,*,auxiliary_tail=None):
    original=source_text(source_prompt);refs=_references(bundle,auxiliary_tail)
    for number in re.findall(r'<Picture\s+(\d+)>',original):
        if not 1<=int(number)<=len(refs):raise ReferencePassthroughError('original_prompt_has_unbound_picture_tag')
    if re.search(r'<(?:Video|Audio)\s+\d+>',original):raise ReferencePassthroughError('this_v20_adapter_binds_images_only')
    compiled=original+_appendix(refs)
    assert compiled.encode('utf-8').startswith(original.encode('utf-8'))
    return dict(compiled_prompt=compiled,source_prompt_sha256=_sha(original.encode('utf-8')),
        source_prompt_byte_length=len(original.encode('utf-8')),references=refs)


def build_graph(base,bundle,source_prompt,input_mapping,scope,width,height,frames,seed,
                reference_mode='reference_only',*,auxiliary_tail=None,ref_image_size='match'):
    """Build, but never stage/submit, a new graph using real Ref2VA inputs.

    input_mapping keys are exact bundle reference_ids (+ auxiliary_tail when
    supplied); values are caller-staged relative Comfy image names.  Every
    picture has its own LoadImage, even if two identities share identical pixels.
    """
    if reference_mode!='reference_only':raise ReferencePassthroughError('explicit_reference_only_mode_required')
    if ref_image_size not in ('match','max'):raise ReferencePassthroughError('unsupported_reference_image_size')
    if any(type(n) is not int or not 32<=n<=2048 or n%32 for n in (width,height)):
        raise ReferencePassthroughError('ref2va_dimensions_multiple32_required')
    if type(frames) is not int or not 124<=frames<=362 or (frames-5)%17:
        raise ReferencePassthroughError('trained_native_17k_plus5_clock_required')
    if type(seed) is not int or not 0<=seed<2**64:raise ReferencePassthroughError('explicit_seed_required')
    _relative(scope)
    prompt=compile_prompt(bundle,source_prompt,auxiliary_tail=auxiliary_tail);refs=prompt['references']
    if not isinstance(input_mapping,dict) or set(input_mapping)!={r['reference_id'] for r in refs}:
        raise ReferencePassthroughError('exact_reference_input_mapping_required')
    if any(base.get(k,{}).get('class_type')!=kind for k,kind in {
        'condition':'MiniMaxH3ImageToVideo','127':'UNETLoader','129':'RandomNoise','130':'CreateVideo',
        'pick_first':'ImageFromBatch','pick_last':'ImageFromBatch'}.items()):
        raise ReferencePassthroughError('explicit_existing_api_base_required')
    graph=deepcopy(base);old_condition=graph['condition']['inputs']
    if not all(k in old_condition for k in ('clip','vae')):raise ReferencePassthroughError('clip_and_video_vae_binding_required')
    condition=dict(clip=deepcopy(old_condition['clip']),vae=deepcopy(old_condition['vae']),
        prompt=prompt['compiled_prompt'],width=width,height=height,length=frames,ref_image_size=ref_image_size)
    graph.pop('ref_scene',None)
    graph['127']['inputs']['unet_name']=REF2VA_MODEL
    graph['129']['inputs']['noise_seed']=seed
    mapping=[]
    for index,record in enumerate(refs):
        node='v20_reference_'+str(index);name=_relative(input_mapping[record['reference_id']])
        if node in graph:raise ReferencePassthroughError('base_reference_node_collision')
        graph[node]=dict(class_type='LoadImage',inputs=dict(image=name))
        slot='ref_images.ref_image_'+str(index);condition[slot]=[node,0]
        with Image.open(record['image']['path']) as image:w,h=image.size
        scale=min(1.0,math.sqrt(width*height/(w*h))) if ref_image_size=='match' else min(1.0,2048/min(w,h))
        mapping.append(dict(picture=index+1,tag='<Picture '+str(index+1)+'>',slot=slot,node=node,
            reference_id=record['reference_id'],kind=record['kind'],entity_id=record['entity_id'],
            view=record['view'],image=deepcopy(record['image']),input_name=name,
            original_dimensions=[w,h],node_reference_dimensions=[max(32,round(w*scale/32)*32),max(32,round(h*scale/32)*32)]))
    graph['condition']=dict(class_type=NODE,inputs=condition)
    graph['pick_first']['inputs']['batch_index']=0;graph['pick_last']['inputs']['batch_index']=frames-1
    graph['130']['inputs']['fps']=24
    for role in ('video','audio','first','last'):
        if 'save_'+role not in graph:raise ReferencePassthroughError('full_native_audio_video_outputs_required')
        graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    result=dict(contract=CONTRACT,graph=graph,compiled_prompt=prompt['compiled_prompt'],
        source_prompt_sha256=prompt['source_prompt_sha256'],source_prompt_byte_length=prompt['source_prompt_byte_length'],
        reference_map=mapping,bundle_sha256=bundle['bundle_sha256'],reference_mode=reference_mode,
        reference_bundle=deepcopy(bundle),auxiliary_tail=deepcopy(auxiliary_tail),
        model=REF2VA_MODEL,native_frames=frames,width=width,height=height,seed=seed,scope=scope,ref_image_size=ref_image_size,
        clip_binding=deepcopy(condition['clip']),vae_binding=deepcopy(condition['vae']),
        fps=24,model_called=False,media_generated=False)
    validate_graph(result)
    return result


def validate_graph(result):
    """Independent v20 graph contract; never relax the old v3 validator."""
    graph=result['graph'];node=graph['condition'];inputs=node['inputs'];mapping=result['reference_map']
    refs=_references(result['reference_bundle'],result.get('auxiliary_tail'))
    if result.get('bundle_sha256')!=result['reference_bundle']['bundle_sha256'] or len(refs)!=len(mapping):
        raise ReferencePassthroughError('source_reference_bundle_changed')
    if (result.get('contract')!=CONTRACT or node.get('class_type')!=NODE
            or graph['127']['inputs']['unet_name']!=REF2VA_MODEL
            or any(k in inputs for k in ('first_frame','last_frame','ref_images'))):
        raise ReferencePassthroughError('real_reference_only_node_and_weights_required')
    if set(inputs)!=set(('clip','vae','prompt','width','height','length','ref_image_size'))|{'ref_images.ref_image_'+str(i) for i in range(len(mapping))}:
        raise ReferencePassthroughError('reference_only_input_contract_changed')
    expected={'ref_images.ref_image_'+str(i) for i in range(len(mapping))}
    if not 1<=len(mapping)<=MAX_IMAGES or {k for k in inputs if k.startswith('ref_images')}!=expected:
        raise ReferencePassthroughError('exact_reference_slot_coverage_required')
    if len({r['node'] for r in mapping})!=len(mapping):raise ReferencePassthroughError('independent_load_image_each_slot_required')
    for i,row in enumerate(mapping):
        if (row['picture']!=i+1 or row['slot']!='ref_images.ref_image_'+str(i)
                or inputs[row['slot']]!=[row['node'],0]
                or any(row[k]!=refs[i][k] for k in ('reference_id','kind','entity_id','view','image'))
                or graph[row['node']]!=dict(class_type='LoadImage',inputs=dict(image=row['input_name']))):
            raise ReferencePassthroughError('picture_mapping_changed')
    prompt=inputs['prompt'];prefix=prompt.encode('utf-8')[:result['source_prompt_byte_length']]
    if (prompt!=result['compiled_prompt'] or _sha(prefix)!=result['source_prompt_sha256']
            or prompt!=prefix.decode('utf-8')+_appendix(refs)):
        raise ReferencePassthroughError('original_prompt_prefix_changed')
    if (inputs['length']!=result['native_frames'] or graph['130']['inputs']['fps']!=24
            or type(result['native_frames']) is not int or not 124<=result['native_frames']<=362 or (result['native_frames']-5)%17
            or any(type(result[k]) is not int or not 32<=result[k]<=2048 or result[k]%32 or inputs[k]!=result[k] for k in ('width','height'))
            or inputs['ref_image_size']!=result['ref_image_size'] or result['ref_image_size'] not in ('match','max')
            or inputs['clip']!=result['clip_binding'] or inputs['vae']!=result['vae_binding']
            or graph['129']['inputs']['noise_seed']!=result['seed']
            or graph['pick_first']['inputs']['batch_index']!=0 or graph['pick_last']['inputs']['batch_index']!=result['native_frames']-1):
        raise ReferencePassthroughError('native_clock_changed')
    _relative(result['scope'])
    if any(graph['save_'+role]['inputs']['filename_prefix']!=result['scope']+'/'+role for role in ('video','audio','first','last')):
        raise ReferencePassthroughError('native_output_scope_changed')
    for node in graph.values():
        for value in node.get('inputs',{}).values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int and value[0] not in graph:
                raise ReferencePassthroughError('dangling_reference_in_api_base')
    return result
