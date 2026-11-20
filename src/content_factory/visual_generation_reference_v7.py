"""Explicit geometry/material generation policy; complete rooms are audit-only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .visual_shot_binding_v3 import fingerprint

POLICY='geometry_materials_only/v1'
ORIGIN_KEY='generation_reference_origin'
SCHEMA='generation_reference_origin/v1'
BINDING='geometry_material_generation/v1'
REVISION='source_bound_place_revision/v1'
CAPACITY_KEY='generation_reference_capacity_amendment'
CAPACITY_SCHEMA='generation_reference_review_capacity/v17'


def _evidence(source,records):
    if not isinstance(records,list) or not records:raise ValueError('place_revision_source_evidence_required')
    raw=Path(source['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('place_revision_source_changed')
    text=raw.decode('utf-8').replace('\r\n','\n').replace('\r','\n')
    for record in records:
        if (not isinstance(record,dict) or set(record)!={'id','start','end','text','sha256'} or not isinstance(record['id'],str)
            or type(record['start']) is not int or type(record['end']) is not int
            or not 0<=record['start']<record['end']<=len(text) or text[record['start']:record['end']]!=record['text']
            or hashlib.sha256(record['text'].encode()).hexdigest()!=record['sha256']):
            raise ValueError('place_revision_source_quote_or_range_changed')
    if not any('桌' in record['text'] or 'table' in record['text'].casefold() for record in records):
        raise ValueError('place_revision_evidence_does_not_confirm_table')


def _new_table_place(original,layout,records):
    place=deepcopy(original);place['spatial_layout']=deepcopy(layout)
    place['design_version']='source_revision_'+fingerprint(dict(origin_design_version=original['design_version'],
        layout=layout,source_evidence=records))[:20]
    for key in ('layout_design','front_prompt'):
        place[key]=original[key]+' One source-confirmed old wooden table is part of the fixed room furnishings.'
    return place


def add_source_table(packet,place_id,table,source_evidence,visual_choices):
    """Create an explicit artifact, never alter a frozen source or stage packet."""
    from . import visual_environment_v4 as environment
    original=next(p for p in packet['places'] if p['id']==place_id)
    if not isinstance(visual_choices,str) or not visual_choices.strip():raise ValueError('place_revision_visual_choices_required')
    _evidence(packet['source'],source_evidence)
    if table.get('kind')!='table' or any(o['kind']=='table' for o in original['spatial_layout']['objects']):
        raise ValueError('place_revision_only_missing_zero_to_one_table')
    layout=deepcopy(original['spatial_layout']);layout['objects'].append(deepcopy(table));environment.validate_layout(layout)
    return dict(schema=REVISION,place_id=place_id,origin_design_version=original['design_version'],
        origin_layout_sha256=fingerprint(original['spatial_layout']),source_evidence=deepcopy(source_evidence),
        new_place=_new_table_place(original,layout,source_evidence),visual_choices=visual_choices)


def validate_place_revision(original,revision,source):
    from . import visual_environment_v4 as environment
    if (revision.get('schema')!=REVISION or revision.get('place_id')!=original['id']
        or revision.get('origin_design_version')!=original['design_version']
        or revision.get('origin_layout_sha256')!=fingerprint(original['spatial_layout'])
        or not isinstance(revision.get('visual_choices'),str) or not revision['visual_choices'].strip()):
        raise ValueError('place_revision_origin_or_scope_changed')
    records=revision['source_evidence'];_evidence(source,records);new=revision['new_place'];layout=new['spatial_layout'];old=original['spatial_layout']
    if (any(layout.get(k)!=v for k,v in old.items() if k!='objects') or len(layout['objects'])!=len(old['objects'])+1
        or layout['objects'][:-1]!=old['objects'] or layout['objects'][-1]['kind']!='table'
        or any(o['kind']=='table' for o in old['objects'])):raise ValueError('place_revision_must_only_add_one_table')
    environment.validate_layout(layout);expected=_new_table_place(original,layout,records)
    expected['required_views']=new['required_views']
    if new!=expected:raise ValueError('place_revision_unbound_entity_changes')
    return new


def enabled(config):
    value=config.get('generation_reference_policy')
    if value is None:
        if ORIGIN_KEY in config or CAPACITY_KEY in config:raise ValueError('generation_reference_origin_requires_explicit_policy')
        return False
    if value!=POLICY:raise ValueError('unsupported_generation_reference_policy')
    if not isinstance(config.get(ORIGIN_KEY),dict):raise ValueError('generation_reference_origin_required')
    if config.get('environment_continuation'):raise ValueError('generation_policy_requires_its_own_origin_scope')
    return True


def _validate_packet(packet,origin_packet):
    if (packet.get('book_id')!=origin_packet['book_id'] or packet.get('source')!=origin_packet['source']
        or packet.get('style_groups')!=origin_packet['style_groups']):raise ValueError('generation_reference_book_source_or_group_changed')
    expected={p['id']:p for p in origin_packet['places']};actual={p['id']:p for p in packet.get('places',[])}
    if set(actual)!=set(expected):raise ValueError('generation_reference_original_place_set_changed')
    staged=bool(packet.get('characters') or packet.get('shots') or packet.get('asset_revision'))
    if staged:
        if packet.get('stage_contract')!='continuous_source_home_staging/v6':raise ValueError('generation_policy_requires_source_bound_staging')
        from . import visual_continuous_stage_v6 as staging
        staging.validate_packet(packet)
    revisions={}
    if packet.get('asset_revision'):
        for item in packet['asset_revision']['revisions']:
            raw=Path(item['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('generation_place_revision_file_changed')
            revision=json.loads(raw)
            if revision['place_id'] in revisions:raise ValueError('duplicate_generation_place_revision')
            revisions[revision['place_id']]=revision
    if not set(revisions)<=set(expected):raise ValueError('generation_place_revision_unknown_place')
    validated={pid:validate_place_revision(expected[pid],revision,packet['source']) for pid,revision in revisions.items()}
    for pid,entity in actual.items():
        if ({k:v for k,v in entity.items() if k!='required_views'}!=
            {k:v for k,v in expected[pid].items() if k!='required_views'}):
            revised=validated.get(pid)
            if not revised or {k:v for k,v in entity.items() if k!='required_views'}!={k:v for k,v in revised.items() if k!='required_views'}:
                raise ValueError('generation_reference_place_design_changed')
        elif pid in revisions:raise ValueError('generation_place_revision_not_applied')


def _bound_document(binding,label):
    if (not isinstance(binding,dict) or set(binding)!={'path','sha256'} or not isinstance(binding['path'],str)
        or not isinstance(binding['sha256'],str) or not Path(binding['path']).is_absolute()):
        raise ValueError('generation_capacity_'+label+'_binding_invalid')
    path=Path(binding['path']).resolve();raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=binding['sha256']:raise ValueError('generation_capacity_'+label+'_changed')
    return json.loads(raw)


def _validate_capacity(run,origin_plan,config):
    """Only the explicitly authorized six new runs may raise this one limit."""
    binding=config[CAPACITY_KEY];proof=_bound_document(binding,'proof')
    if (not isinstance(proof,dict) or set(proof)!={'schema','origin_run','origin_plan_sha256','old_config','new_config',
        'target_runs','change','authorization','reason'} or proof.get('schema')!=CAPACITY_SCHEMA):
        raise ValueError('generation_capacity_proof_schema_invalid')
    origin=config[ORIGIN_KEY]['origin'];origin_path=Path(origin['origin_run']).resolve();run=Path(run).resolve()
    if proof['origin_run']!=str(origin_path) or proof['origin_plan_sha256']!=origin['origin_plan_sha256']:
        raise ValueError('generation_capacity_origin_changed')
    from . import visual_environment_continuation_v6 as continuation
    targets=proof['target_runs']
    if not isinstance(targets,list) or len(targets)!=6 or any(not isinstance(t,str) or not Path(t).is_absolute() for t in targets):
        raise ValueError('generation_capacity_requires_six_explicit_targets')
    normalized=[str(continuation._target(origin_path,t)) for t in targets]
    if normalized!=targets or len(set(normalized))!=6 or str(run) not in normalized:
        raise ValueError('generation_capacity_target_not_authorized')
    old=_bound_document(proof['old_config'],'old_config');new=_bound_document(proof['new_config'],'new_config')
    if not isinstance(old,dict) or not isinstance(new,dict) or not isinstance(old.get('visual_review'),dict) or not isinstance(new.get('visual_review'),dict):
        raise ValueError('generation_capacity_config_schema_invalid')
    change=dict(field='visual_review.max_tokens',old=1800,new=4096)
    if fingerprint(proof['change'])!=fingerprint(change) or type(old['visual_review'].get('max_tokens')) is not int or old['visual_review']['max_tokens']!=1800:
        raise ValueError('generation_capacity_only_1800_to_4096')
    expected=deepcopy(old);expected['visual_review']['max_tokens']=4096
    if fingerprint(new)!=fingerprint(expected):raise ValueError('generation_capacity_other_config_changed')
    if fingerprint(old['visual_review'])!=fingerprint(origin_plan['config'].get('visual_review')) or fingerprint(config.get('visual_review'))!=fingerprint(new['visual_review']):
        raise ValueError('generation_capacity_review_model_or_runtime_changed')
    baseline=deepcopy(origin_plan['config'])
    if 'style_reference_root' not in old:baseline.pop('style_reference_root',None)
    if fingerprint(old)!=fingerprint(baseline):
        raise ValueError('generation_capacity_old_config_not_origin')
    # Keep the pre-existing per-run output prefix, geometry proof and static-plan
    # decorations. The executor's established repair cap is at most two; none of
    # these decorations authorizes another review attempt or runtime change.
    normalized=deepcopy(config)
    for key in ('generation_reference_policy',ORIGIN_KEY,CAPACITY_KEY,'first_frame_contract','first_frame_plan'):
        normalized.pop(key,None)
    if 'style_reference_root' in new:normalized['style_reference_root']=deepcopy(new['style_reference_root'])
    else:normalized.pop('style_reference_root',None)
    normalized['image_service']['allowed_prefix']=new['image_service'].get('allowed_prefix')
    repairs=normalized.get('max_repair_rounds',1)
    if type(repairs) is not int or repairs not in (1,2):raise ValueError('generation_capacity_repair_budget_changed')
    normalized['max_repair_rounds']=new.get('max_repair_rounds',1)
    if fingerprint(normalized)!=fingerprint(new):raise ValueError('generation_capacity_other_runtime_changed')
    auth=proof['authorization']
    if not isinstance(auth,dict) or set(auth)!={'evidence','text'}:raise ValueError('generation_capacity_authorization_required')
    evidence=_bound_document(auth['evidence'],'authorization')
    if (evidence.get('schema')!='known_visual_review_capacity_amendment/v17' or not isinstance(auth['text'],str) or not auth['text'].strip()
        or evidence.get('authorization')!=auth['text'] or not isinstance(proof['reason'],str) or not proof['reason'].strip()
        or evidence.get('cause')!=proof['reason'] or evidence.get('old_config')!=proof['old_config'] or evidence.get('new_config')!=proof['new_config']
        or fingerprint(evidence.get('changed_fields'))!=fingerprint({'visual_review.max_tokens':dict(old=1800,new=4096)})
        or type(evidence.get('max_review_attempts')) is not int or evidence['max_review_attempts']!=2 or evidence.get('source_modified') is not False
        or evidence.get('old_run_plan_modified') is not False or evidence.get('unknown_replay') is not False):
        raise ValueError('generation_capacity_authorization_or_reason_changed')
    frozen=run/'PLAN.json'
    if frozen.exists():
        old_plan=json.loads(frozen.read_text(encoding='utf-8'))
        if fingerprint(old_plan.get('config'))!=fingerprint(config):raise ValueError('generation_capacity_frozen_run_config_changed')
    return proof


def bind(origin_run,new_run,packet,base_config=None,*,capacity_amendment=None):
    """Read-only config construction. Never changes the group, designs, or assets."""
    from . import visual_environment_continuation_v6 as continuation
    run=continuation._target(origin_run,new_run);origin,plan=continuation._origin_snapshot(origin_run)
    _validate_packet(packet,plan['packet'])
    config=deepcopy(base_config if base_config is not None else plan['config'])
    if config.get('environment_continuation'):raise ValueError('generation_policy_requires_its_own_origin_scope')
    if CAPACITY_KEY in config:raise ValueError('generation_capacity_requires_explicit_bind_argument')
    if capacity_amendment is not None:
        if (run/'PLAN.json').exists():raise ValueError('generation_capacity_first_bind_requires_unprepared_run')
        config[CAPACITY_KEY]=deepcopy(capacity_amendment)
    config.update(generation_reference_policy=POLICY,style_reference_root=origin['origin_reference_root'])
    config[ORIGIN_KEY]=dict(schema=SCHEMA,target_run=str(run),origin=origin,
        asset_revision_sha256=fingerprint(packet.get('asset_revision')))
    validate(run,packet,config)
    return config


def validate(run,packet,config):
    if not enabled(config):return
    from . import visual_environment_continuation_v6 as continuation
    proof=config[ORIGIN_KEY]
    if (proof.get('schema')!=SCHEMA or not isinstance(proof.get('origin'),dict)
        or not isinstance(proof['origin'].get('origin_run'),str)):
        raise ValueError('generation_reference_origin_schema_invalid')
    source=proof.get('origin',{});current,plan=continuation._origin_snapshot(source['origin_run'])
    if (str(continuation._target(source['origin_run'],run))!=proof.get('target_run') or current!=source
        or config.get('style_reference_root')!=source['origin_reference_root']
        or proof.get('asset_revision_sha256')!=fingerprint(packet.get('asset_revision'))):raise ValueError('generation_reference_origin_changed')
    _validate_packet(packet,plan['packet'])
    if CAPACITY_KEY in config:_validate_capacity(run,plan,config)
    for key in ('library','gpu_lock_root','protected_pause_path','visual_review','style_reference_contract','style_reference_parent_manifest'):
        if key=='visual_review' and CAPACITY_KEY in config:continue
        if config.get(key)!=plan['config'].get(key):raise ValueError('generation_reference_runtime_or_review_changed:'+key)
    for key in ('service_url','input_root','output_root'):
        if config['image_service'][key]!=plan['config']['image_service'][key]:raise ValueError('generation_reference_image_service_changed')


def baseline_front(plan,row):
    if not enabled(plan['config']) or row.get('kind')!='place' or row.get('view')!='front':return False
    from . import visual_asset_pipeline_v3 as pipeline
    entity=next(p for p in plan['packet']['places'] if p['id']==row['entity_id'])
    if row['design_version']!=entity['design_version']:return False
    for original in plan['config'][ORIGIN_KEY]['origin']['fronts']:
        if (pipeline._asset_identity(row)==original['identity'] and fingerprint(row.get('review'))==original['review_sha256']
            and fingerprint(row.get('provenance'))==original['provenance_sha256']):return True
    return False


def header(plan,stage):
    if not enabled(plan['config']):return None
    return dict(schema=BINDING,policy=POLICY,stage=stage,
        origin_sha256=fingerprint(plan['config'][ORIGIN_KEY]['origin']),full_room_images_in_generation=False)


def current_binding(plan,binding,stage):
    expected=header(plan,stage)
    return bool(expected and isinstance(binding,dict) and all(binding.get(k)==v for k,v in expected.items()))


def layout_free_patches(bundle,entity):
    from . import visual_residence_style_v5 as style
    if bundle.get('reference_contract')!=style.APPEARANCE_CONTRACT:
        raise ValueError('geometry_materials_policy_requires_layout_free_appearance_reference')
    result=style.read(Path(bundle['manifest_path']).parent/'REFERENCE_REVIEW.json')
    style.verify_result(style.reference_request(bundle),result)
    if any(patch.get('layout_free') is not True for patch in result['patch_checks']):
        raise ValueError('geometry_materials_reference_is_not_layout_free')
    return style.target_request(bundle,entity,bundle['master']['path'])['patches']


def place_prompt(entity,view):
    from . import visual_environment_v4 as environment
    return ('A photorealistic empty contemporary Chinese room. The first reference alone specifies this camera and spatial '
        'arrangement. Render its visible furnishings and openings as real physical objects with natural materials. '
        'The remaining references are close-up color and finish samples, without a room layout. Apply them only to '
        'compatible surfaces in this geometry. Preserve the first image framing, occlusion and visible furniture placement. '
        'No people, labels, diagram lines or captions.\n'+json.dumps(environment.render_context(entity,view),ensure_ascii=False))


def bind_job(plan,stage,inputs,roles,folder):
    from . import visual_image_jobs_v3 as images
    value=header(plan,stage)
    if value is None:return None
    if len(inputs)!=len(roles) or not roles or roles[0]!='geometry':raise ValueError('generation_input_roles_invalid')
    if any(role!='geometry' and not role.startswith(('material:','character:')) for role in roles):
        raise ValueError('complete_room_generation_reference_refused')
    value.update(inputs=[dict(role=role,**{k:item[k] for k in ('input_name','path','sha256')}) for role,item in zip(roles,inputs)],
        job_dir=str(Path(folder).resolve()),job_plan_sha256=images.file_sha(Path(folder)/'PLAN.json'))
    return value


def verify_job(plan,binding,stage,inputs,roles,*,receipt=None,require_receipt=False):
    """Re-read the frozen native input/graph, not just a claimed policy string."""
    from . import visual_image_jobs_v3 as images
    if not isinstance(binding,dict):raise ValueError('generation_policy_binding_missing')
    expected=header(plan,stage)
    if expected is None:return
    if any(binding.get(k)!=v for k,v in expected.items()):raise ValueError('generation_policy_binding_changed')
    expected_inputs=[dict(role=role,**{k:item[k] for k in ('input_name','path','sha256')}) for role,item in zip(roles,inputs)]
    if len(inputs)!=len(roles) or binding.get('inputs')!=expected_inputs:raise ValueError('generation_policy_inputs_changed')
    folder=Path(binding['job_dir']);job_plan=images._read(folder/'PLAN.json');graph=images._read(folder/'workflow_api.json')
    if images.file_sha(folder/'PLAN.json')!=binding.get('job_plan_sha256') or images.digest(graph)!=job_plan['graph_sha256']:
        raise ValueError('generation_policy_native_job_changed')
    native={item['input_name']:{k:item[k] for k in ('input_name','path','sha256')} for item in job_plan['inputs']}
    if native!={item['input_name']:item for item in inputs}:raise ValueError('generation_policy_native_inputs_changed')
    image_names=[node['inputs']['image'] for node in graph.values() if node['class_type']=='LoadImage']
    if set(image_names)!=set(native) or len(image_names)!=len(native):raise ValueError('generation_policy_native_reference_graph_changed')
    for item in inputs:
        if images.file_sha(item['path'])!=item['sha256']:raise ValueError('generation_policy_input_file_changed')
    if require_receipt:
        if not isinstance(receipt,dict) or not receipt.get('prompt_id'):raise ValueError('generation_policy_native_receipt_missing')
        result=images._read(folder/'RESULT.json');state=images._read(folder/'STATE.json')
        if result!=receipt or state.get('status')!='saved' or state.get('prompt_id')!=receipt['prompt_id']:
            raise ValueError('generation_policy_saved_receipt_changed')
        history=images._read(folder/'HISTORY.json').get(receipt['prompt_id'],{})
        if (history.get('prompt',[None,None,None])[2]!=graph or history.get('status',{}).get('completed') is not True
            or history.get('status',{}).get('status_str')!='success'):
            raise ValueError('generation_policy_native_completion_not_proven')
        for output in receipt.get('images',[]):
            if not Path(output['path']).resolve().is_relative_to(folder.resolve()/'artifacts') or images.file_sha(output['path'])!=output['sha256']:
                raise ValueError('generation_policy_native_output_changed')
        if not receipt.get('images'):raise ValueError('generation_policy_native_output_missing')
    if receipt and (receipt.get('job_id')!=job_plan['job_id'] or receipt.get('graph_sha256')!=job_plan['graph_sha256']
        or receipt.get('inputs_sha256')!=images.digest(job_plan['inputs'])):raise ValueError('generation_policy_receipt_changed')
