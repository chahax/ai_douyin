"""Isolated V2 bridge for verified saved scene assets and project-relative tails.

No original RESULT/receipt is rewritten or copied to masquerade as a new job.
All transport, source and Root launch gates remain the frozen V1 implementation.
"""
from copy import deepcopy
from pathlib import Path
import types

from . import h3_universal_direction_execution_v1 as v1
from . import h3_asset_flow_v2 as flow
from . import visual_h3_library_continuation_v1 as library

VERSION='h3_universal_direction_execution/v2'
REUSE_APPROVAL='h3_scene_guide_reuse_approval/v1'
PROJECT=Path(__file__).resolve().parents[2]


def _require(ok,message):
    if not ok:raise ValueError(message)


def _inside(path,root):
    value=Path(path).resolve();_require(value.is_relative_to(Path(root).resolve()),'saved_scene_path_outside_approved_scope')
    return value


def normalize_last_image(receipt):
    raw=receipt['last_image'];path=Path(raw['path'])
    absolute=(PROJECT/path).resolve() if not path.is_absolute() else path.resolve()
    _inside(absolute,PROJECT)
    normalized=flow.bind(absolute)
    _require(normalized['sha256']==raw['sha256'],'project_relative_native_tail_SHA_changed')
    result=deepcopy(receipt);result['last_image']=normalized
    if raw!=normalized:
        result['last_image_path_normalization']=dict(original_last_image=deepcopy(raw),absolute_last_image=normalized,
            path_base=str(PROJECT),original_native_records_modified=False)
    return result


def _scene_equivalent(expected,actual):
    copy=deepcopy(actual);before=expected.get('initial__guider',{});after=copy.get('initial__guider',{})
    value=before.get('inputs',{}).get('cfg');native=after.get('inputs',{}).get('cfg')
    if (before.get('class_type')==after.get('class_type')=='CFGGuider'
            and type(value) is int and value==1 and type(native) is float and native==1):
        after['inputs']['cfg']=value
    return flow.digest(copy)==flow.digest(expected)


def _all_bindings(value):
    if isinstance(value,dict):
        if set(value)=={'path','sha256'}:yield value
        else:
            for item in value.values():yield from _all_bindings(item)
    elif isinstance(value,list):
        for item in value:yield from _all_bindings(item)


def verify_saved_scene_reuse(series,path,expected_job_id,approval_binding):
    series=Path(series).resolve();path=Path(path).resolve()
    _require(approval_binding is not None,'explicit_Root_scene_reuse_approval_required')
    approval_path=flow.core.check(approval_binding);_inside(approval_path,series)
    approval=flow.read(approval_path)
    _require(approval.get('schema')==REUSE_APPROVAL and str(approval.get('approved_by','')).strip().lower()=='root'
        and Path(approval.get('target_run','')).resolve()==series and approval.get('shot_id')=='S02'
        and approval.get('user_authorization')==flow.bind(series/'USER_AUTHORIZATION.json')
        and approval.get('preserve_original_records') is True and type(approval.get('new_image_calls')) is int
        and approval['new_image_calls']==0 and isinstance(approval.get('evidence'),list) and approval['evidence']
        and all(isinstance(s,str) and s.strip() for s in approval['evidence']), 'complete_Root_saved_scene_reuse_approval_required')
    source_run=Path(approval['source_run']).resolve();_inside(source_run,PROJECT)
    _require(source_run!=series and flow.core.check(approval['scene_receipt'])==path
        and approval['scene_receipt']==flow.bind(path)
        and approval['source_series_plan']==flow.bind(source_run/'PLAN.json'),'exact_original_scene_receipt_and_series_required')
    _inside(path,source_run)
    receipt=flow.read(path)
    _require(receipt.get('schema')==library.SCENE_GUIDE and receipt.get('completion_known') is True
        and receipt.get('outcome_unknown') is False and set(receipt.get('generation_records',{}))=={'plan','request','history','result'},
        'completed_original_scene_records_required')
    records=receipt['generation_records'];record_paths={k:flow.core.check(v) for k,v in records.items()}
    job_folder=record_paths['plan'].parent;_inside(job_folder,source_run)
    _require(all(record_paths[k]==job_folder/(k.upper()+'.json') for k in records),'one_original_scene_job_record_directory_required')
    plan=flow.read(record_paths['plan']);request=flow.read(record_paths['request']);history=flow.read(record_paths['history']);result=flow.read(record_paths['result'])
    pid=receipt.get('native_prompt_id');job_id=plan.get('job_id')
    _require(job_id==expected_job_id==approval.get('native_job_id') and pid==approval.get('native_prompt_id')
        and plan.get('version')=='visual_image_jobs/v3' and result.get('version')==plan['version']
        and result.get('job_id')==job_id and result.get('prompt_id')==pid and result.get('technical_status')=='saved'
        and result.get('production_approved') is False and set(history)=={pid},'unique_original_scene_job_and_prompt_required')
    event=history[pid];hp=event.get('prompt',[])
    _require(len(hp)>2 and hp[1]==pid and _scene_equivalent(request['prompt'],hp[2])
        and event.get('status',{}).get('completed') is True and event['status'].get('status_str')=='success'
        and plan.get('graph_sha256')==flow.digest(request['prompt'])==result.get('graph_sha256')
        and result.get('inputs_sha256')==flow.digest(plan.get('inputs',[])),'original_scene_plan_graph_and_success_history_required')
    cfg=plan['config'];output_root=Path(cfg['output_root']).resolve();prefix=Path(cfg['allowed_prefix'])
    _inside(output_root,PROJECT)
    _require(prefix.parts and not prefix.is_absolute() and '..' not in prefix.parts,'safe_original_scene_job_prefix_required')
    scope=(output_root/prefix/job_id).resolve();_inside(scope,output_root)
    source_series=flow.read(source_run/'PLAN.json');series_cfg=flow._bound(source_series['config'])
    _require(Path(series_cfg['output_root']).resolve()==output_root,'source_series_and_scene_output_root_must_match')
    image=flow.core.check(receipt['image']);_inside(image,job_folder/'artifacts')
    _require(receipt['image']==approval.get('image'),'approved_scene_pixels_must_match')
    source=flow.core.check(receipt['source_image']);_inside(source,scope)
    output=receipt.get('native_output',{});node=output.get('node_id');index=output.get('index')
    emitted=event.get('outputs',{}).get(node,{}).get('images',[])
    _require(type(index) is int and 0<=index<len(emitted) and emitted[index].get('type')=='output'
        and Path(output.get('source_path','')).resolve()==source,'original_scene_output_locator_required')
    emitted_path=(output_root/emitted[index].get('subfolder','')/emitted[index]['filename']).resolve()
    save=request['prompt'].get(node,{});save_prefix=Path(save.get('inputs',{}).get('filename_prefix',''))
    _require(save.get('class_type')=='SaveImage' and not save_prefix.is_absolute() and '..' not in save_prefix.parts
        and emitted_path==source and (output_root/save_prefix).resolve().is_relative_to(scope)
        and receipt['source_image']['sha256']==receipt['image']['sha256'],'original_SaveImage_scope_and_pixel_SHA_required')
    matches=[x for x in result.get('images',[]) if x.get('path')==str(image) and x.get('sha256')==receipt['image']['sha256']
        and Path(x.get('source_path','')).resolve()==source and x.get('save_node')==node]
    _require(len(matches)==1,'original_RESULT_must_bind_selected_saved_scene_image')
    with library.base.Image.open(image) as opened:
        _require(opened.size==(736,1312),'native_scene_geometry_required');opened.verify()
    source_refs=flow.read(flow.core.check(receipt['source_refs']))
    for binding in _all_bindings(source_refs):flow.core.check(binding)
    declared={flow.digest(r['image']) for r in source_refs.get('references',[])}
    planned=set()
    for item in plan.get('inputs',[]):
        original={k:item[k] for k in ('path','sha256')};flow.core.check(original);planned.add(flow.digest(original))
        staged=(Path(cfg['input_root'])/item['input_name']).resolve();_inside(staged,cfg['input_root'])
        _require(staged==Path(item['staged_path']).resolve() and flow.bind(staged)['sha256']==item['sha256'],
            'original_scene_LoadImage_staging_changed')
        loads=[v for v in request['prompt'].values() if v.get('class_type')=='LoadImage' and v.get('inputs',{}).get('image')==item['input_name']]
        _require(len(loads)==1,'each_original_scene_input_must_have_one_LoadImage')
    _require(planned==declared,'original_scene_source_reference_pixels_changed')
    return dict(deepcopy(receipt),saved_scene_reuse=dict(schema='approved_saved_scene_reuse/v1',approval_binding=deepcopy(approval_binding),
        source_receipt=approval['scene_receipt'],source_series_plan=approval['source_series_plan'],
        origin='reused_original_asset_not_generated_in_target_run',original_records_preserved=True,
        cfg_conversion='only_CFGGuider_initial__guider_int1_to_float1_allowed',new_image_calls=0,model_quality_passed=False))


def _cell(function,name):
    cells=dict(zip(function.__code__.co_freevars,function.__closure__ or ()))
    _require(name in cells,'private_V1_factory_closure_contract_changed');return cells[name].cell_contents


def _private_globals(function,values):
    namespace=dict(function.__globals__);namespace.update(values)
    clone=types.FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
    clone.__kwdefaults__=deepcopy(function.__kwdefaults__)
    return clone


def library_for_run(series,policy_binding,reuse_approval_binding=None):
    bound=Path(series).resolve();api=v1.library_for_run(bound,policy_binding)
    original_input=api.input_value;raw_input=_cell(original_input,'original_input');raw_review=_cell(raw_input,'review_request')
    namespace=_cell(raw_review,'ns');_require(namespace is not library.base.__dict__,'private_library_namespace_required')
    original_verify=namespace['verify_native']
    def verify_native(binding):return normalize_last_image(original_verify(binding))
    namespace['verify_native']=verify_native
    def scene_guide(value,path,expected_job_id=None):
        v1._same(bound,value)
        if Path(path).resolve().is_relative_to(bound):return library.generated_scene_guide(value,path,expected_job_id)
        return verify_saved_scene_reuse(bound,path,expected_job_id,reuse_approval_binding)
    review=_private_globals(raw_review,{'generated_scene_guide':scene_guide})
    raw=v1._replace_closure(raw_input,{'review_request':review})
    wrapped_input=v1._replace_closure(original_input,{'original_input':raw})
    original_prepare=api.prepare_video;compiled=_cell(original_prepare,'compiled_prepare')
    prepared=v1._replace_closure(compiled,{'input_value':wrapped_input})
    prepare_wrapper=v1._replace_closure(original_prepare,{'compiled_prepare':prepared})
    def prepare(value,sid,*,code_files=()):
        v1._same(bound,value)
        extra=(__file__,)+( (str(flow.core.check(reuse_approval_binding)),) if reuse_approval_binding is not None else () )
        return prepare_wrapper(value,sid,code_files=tuple(code_files)+extra)
    def review_request(value,sid):
        v1._same(bound,value);return review(value,sid)
    namespace.update(input_value=wrapped_input,prepare_video=prepare)
    api.input_value,api.prepare_video,api.review_request=wrapped_input,prepare,review_request
    return api


def asset_for_run(run,policy_binding):
    return v1.asset_for_run(run,policy_binding)
