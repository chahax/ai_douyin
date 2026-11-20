"""One evidenced recovery before local model loading/inference.

The original unknown outcome is never cleared or reclassified. A separate target
review may consume the last existing attempt, using the already completed layout.
Proof distinguishes a pre-Python worker from a worker stuck in resource preflight.
"""
from copy import deepcopy
import ast
from pathlib import Path
import re
import time

import psutil

from . import visual_asset_pipeline_v3 as pipeline
from . import visual_asset_registry_v3 as registry
from . import visual_asset_review_v3 as visual
from . import visual_residence_appearance_v6 as appearance
from . import visual_residence_style_v5 as style

VERSION='local_unstarted_target_review_recovery/v6'


def _read(path):return pipeline.read(path)
def _sha(path):return pipeline.file_sha(path)


def _worker_preflight_order(source):
    path=Path(source.get('path','')).resolve()
    if path!=visual.PROJECT/'scripts/visual_review_worker_v3.py' or _sha(path)!=source.get('sha256'):
        raise ValueError('preflight_worker_source_binding_required')
    tree=ast.parse(path.read_text(encoding='utf-8'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
    loading=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='_write' and len(n.args)>1 and
        isinstance(n.args[1],ast.Call) and any(k.arg=='stage' and isinstance(k.value,ast.Constant) and k.value.value=='loading' for k in n.args[1].keywords)]
    probes=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='probe_resources']
    imports=[n for n in ast.walk(tree) if (isinstance(n,ast.Import) and any(x.name.split('.')[0] in ('torch','transformers','bitsandbytes') for x in n.names)) or
        (isinstance(n,ast.ImportFrom) and (n.module or '').split('.')[0] in ('torch','transformers','bitsandbytes'))]
    loads=[n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr in ('from_pretrained','generate')]
    if len(loading)!=1 or len(probes)!=1 or not imports or not loads or not loading[0].lineno<probes[0].lineno<min(n.lineno for n in imports+loads):
        raise ValueError('worker_preflight_model_order_unconfirmed')


def _resource_preflight_evidence(folder,binding,diagnosis,native_request):
    if Path(diagnosis.get('folder','')).resolve()!=folder.resolve() or diagnosis.get('read_errors')!=[] or diagnosis.get('inference_claims')!=[]:
        raise ValueError('complete_bound_preflight_observation_required')
    required=('REQUEST.json','CLAIM.json','WORKER_LAUNCH.json','WORKER_RUNTIME.json','WORKER_STATE.json','worker.log')
    if any(diagnosis.get('bound_files',{}).get(name)!=_sha(folder/name) for name in required):
        raise ValueError('preflight_runtime_state_snapshot_changed')
    runtime=_read(folder/'WORKER_RUNTIME.json');state=_read(folder/'WORKER_STATE.json');claim=_read(folder/'CLAIM.json')
    if (state!=diagnosis.get('state') or state.get('stage')!='loading' or runtime.get('pid')!=state.get('pid') or
            runtime.get('request_binding_sha256')!=binding or not runtime.get('actual_executable') or not runtime.get('prefix') or
            any(runtime.get('model_packages_imported',{}).get(k) is not False for k in ('torch','transformers','bitsandbytes'))):
        raise ValueError('worker_not_proven_in_resource_preflight')
    _worker_preflight_order(diagnosis.get('worker_source',{}))
    deadline=claim.get('at',0)+native_request['config'].get('timeout',900)
    if (not claim.get('at') or not deadline-30<=diagnosis.get('additional_observation_at',0)<=deadline or
            diagnosis.get('after_timeout_at',0)<deadline):raise ValueError('preflight_observation_not_bound_to_timeout_window')
    forbidden=('torch','c10','cuda','cudnn','cublas','nvrtc','bitsandbytes','fbgemm','caffe2','triton')
    family_samples=[];initial=diagnosis.get('processes',[])
    identities={p.get('pid'):p for p in initial if isinstance(p,dict)}
    later=[]
    for item in diagnosis.get('additional_processes',[]):
        original=identities.get(item.get('pid'))
        if (not original or type(original.get('created_at')) not in (int,float) or
                item.get('created_at')!=original['created_at']):raise ValueError('preflight_later_process_identity_unconfirmed')
        current=dict(item)
        for key in ('ppid','name'):
            if key not in original or (key in current and current[key]!=original[key]):
                raise ValueError('preflight_later_process_identity_conflict')
            current.setdefault(key,original[key])
        later.append(current)
    for observations in (initial,later):
        parents=[p for p in observations if p.get('pid')==runtime['pid']]
        children=[p for p in observations if p.get('ppid')==runtime['pid'] and p.get('name','').lower()=='nvidia-smi.exe']
        if len(parents)!=1 or len(children)!=1:raise ValueError('original_resource_probe_family_not_observed')
        parent=parents[0];child=children[0];modules=parent.get('module_basenames')
        if (parent.get('ppid')!=runtime.get('ppid') or not isinstance(modules,list) or not modules or any(any(part in name.lower() for part in forbidden) for name in modules) or
                child.get('status')!='stopped' or child.get('cpu_user')!=0 or child.get('cpu_system')!=0 or
                set(n.lower() for n in child.get('module_basenames',[]))!={'ntdll.dll','nvidia-smi.exe'}):
            raise ValueError('model_loading_or_resource_probe_progress_observed')
        family_samples.append(tuple(item.get(k) for item in (parent,child) for k in ('pid','ppid','created_at')))
    if family_samples[0]!=family_samples[1]:raise ValueError('preflight_process_identity_changed_between_observations')
    required_pids={p['pid'] for p in diagnosis['processes']}|{runtime['ppid']}
    if not required_pids<={p.get('pid') for p in diagnosis.get('exit_processes',[])}:
        raise ValueError('whole_resource_probe_family_exit_not_proven')


def _no_original_inference(folder,binding,diagnosis=None,native_request=None):
    folder=Path(folder)
    entered=any((folder/name).exists() for name in ('WORKER_RUNTIME.json','WORKER_STATE.json'))
    if (any((folder/name).exists() for name in ('WORKER_FAILURE.json','RESULTS.json')) or
            any(folder.glob('item_*')) or any(p!=folder/'CLAIM.json' for p in folder.rglob('*_CLAIM.json'))):
        raise ValueError('original_worker_may_have_entered_inference')
    if entered:
        if diagnosis is None or native_request is None or not diagnosis.get('bound_files'):raise ValueError('original_worker_may_have_entered_inference')
        _resource_preflight_evidence(folder,binding,diagnosis,native_request)
    if not (folder/'worker.log').is_file() or (folder/'worker.log').stat().st_size!=0:
        raise ValueError('original_worker_log_not_empty')
    claim=_read(folder/'CLAIM.json');exit_receipt=_read(folder/'WORKER_EXIT.json');error=_read(folder/'WORKER_ERROR.json')
    if (claim.get('request_binding_sha256')!=binding or exit_receipt.get('request_binding_sha256')!=binding or
            exit_receipt.get('exited') is not True or exit_receipt.get('terminated_on_timeout') is not True or
            error.get('type')!='TimeoutExpired'):
        raise ValueError('original_local_timeout_receipts_required')
    return exit_receipt,error


def _exited_processes(diagnosis,request_path,request_sha,exit_receipt,error):
    files=diagnosis.get('files',[]);files=[files] if isinstance(files,dict) else files
    matches=[item for item in files if Path(item.get('request_path','')).resolve()==Path(request_path).resolve()]
    if len(matches)!=1:raise ValueError('diagnosis_does_not_bind_original_request')
    evidence=matches[0]
    preflight=bool(diagnosis.get('bound_files'))
    if (evidence.get('sha256')!=request_sha or evidence.get('worker_state_exists') is not preflight or
            evidence.get('worker_log_bytes')!=0 or evidence.get('worker_exit')!=exit_receipt or evidence.get('worker_error')!=error):
        raise ValueError('diagnosis_timeout_evidence_changed')
    processes=diagnosis.get('exit_processes',[]) if preflight else diagnosis.get('processes',[])
    outer=diagnosis.get('outer_launcher_after_timeout')
    if outer is not None:processes=[*processes,outer]
    if not processes or any(type(p.get('pid')) is not int or p['pid']<1 or p.get('error')!='NoSuchProcess' for p in processes):
        raise ValueError('original_family_exit_evidence_required')
    pids={p['pid'] for p in processes};samples=diagnosis.get('earlier_readonly_samples',[])
    stopped=[p for p in samples if p.get('status')=='stopped' and p.get('user_cpu_seconds')==0 and
        p.get('system_cpu_seconds')==0 and isinstance(p.get('modules'),list) and len(p['modules'])==2 and
        Path(p['modules'][0]).name.lower()=='python.exe' and Path(p['modules'][1]).name.lower()=='ntdll.dll']
    if not preflight and (not stopped or any(p.get('pid') not in pids for p in stopped)):
        raise ValueError('original_uninitialized_python_child_evidence_required')
    if preflight:
        runtime=_read(Path(request_path).parent/'WORKER_RUNTIME.json')
        samples=[*samples,*[dict(pid=p['pid'],create_time=p.get('created_at'),
            exe=runtime['actual_executable'] if p['pid']==runtime['pid'] else p.get('exe',p.get('name')))
            for p in diagnosis.get('processes',[])]]
    identities={p['pid']:p for p in [*samples,*diagnosis.get('original_process_identities',[])]
        if isinstance(p,dict) and type(p.get('pid')) is int and isinstance(p.get('create_time'),(int,float)) and p.get('exe')}
    for pid in pids:
        try:
            process=psutil.Process(pid)
            previous=identities.get(pid)
            if previous:
                created=process.create_time();executable=process.exe()
                if executable and abs(created-previous['create_time'])>1e-6:continue
        except psutil.NoSuchProcess:continue
        except Exception as problem:raise ValueError('cannot_confirm_original_family_exit') from problem
        raise ValueError('original_family_process_still_exists')
    return sorted(pids)


def _known_layout(folder,layout,target_sha):
    folder=Path(folder);request=_read(folder/'REQUEST.json');saved=_read(folder/'RESULTS.json')
    exit_receipt=_read(folder/'WORKER_EXIT.json');worker=_read(folder/'WORKER_STATE.json')
    values=saved.get('results',[])
    if (saved.get('request_binding_sha256')!=request.get('request_binding_sha256') or
            request.get('request_binding_sha256')!=visual.digest(dict(config=request['config'],requests=request['prepared'])) or
            saved.get('results_sha256')!=visual.digest(values) or exit_receipt.get('exited') is not True or
            exit_receipt.get('code')!=0 or exit_receipt.get('request_binding_sha256')!=saved.get('request_binding_sha256') or
            worker.get('stage')!='completed'):
        raise ValueError('completed_layout_worker_results_required')
    matches=[i for i,r in enumerate(values) if r==layout and r.get('target_sha256')==target_sha]
    if len(matches)!=1:raise ValueError('layout_result_does_not_match_original_completed_receipt')
    index=matches[0];prepared=request['prepared'][index]
    if (prepared['target']['sha256']!=target_sha or layout.get('binding_sha256')!=visual.digest(prepared) or
            layout.get('decision')!='accepted' or layout.get('completion_known') is not True or
            layout.get('outcome_unknown') is not False or set(layout.get('checks',{}))!=set(visual.PLACE_CHECKS) or
            any(v is not True for v in layout['checks'].values())):
        raise ValueError('original_layout_not_source_bound_and_accepted')
    item=folder/f'item_{index:04}'
    if _read(item/'RESULT.json')!=layout or any(not (item/name).is_file() for name in ('BLIND_NATIVE.json','MODEL_NATIVE.json')):
        raise ValueError('original_completed_layout_native_evidence_required')
    visual._unchanged(prepared)


def _known_target_style(folder,result,request,config):
    folder=Path(folder);prepared=appearance._prepared(request);binding=visual.digest(dict(config=config,prepared=prepared))
    native=_read(folder/'REQUEST.json');saved=_read(folder/'RESULTS.json');exited=_read(folder/'WORKER_EXIT.json')
    runtime=_read(folder/'WORKER_RUNTIME.json')
    if (native.get('review_mode')!=appearance.VERSION or native.get('prepared')!=[prepared] or native.get('config')!=config or
            native.get('request_binding_sha256')!=binding or saved.get('request_binding_sha256')!=binding or
            saved.get('results')!=[result] or saved.get('results_sha256')!=visual.digest([result]) or
            exited.get('exited') is not True or exited.get('code')!=0 or exited.get('request_binding_sha256')!=binding or
            _read(folder/'WORKER_STATE.json').get('stage')!='completed' or
            runtime.get('request_binding_sha256')!=binding or type(runtime.get('pid')) is not int or runtime['pid']<1 or
            not runtime.get('actual_executable') or not runtime.get('prefix') or
            _read(folder/'item_0000/RESULT.json')!=result or not (folder/'item_0000/APPEARANCE_NATIVE.json').is_file() or
            result.get('binding_sha256')!=visual.digest(prepared)):
        raise ValueError('completed_new_local_target_style_evidence_required')
    appearance._unchanged(prepared)


def _validate(plan,*,after_claim=False):
    run=Path(plan['run']);snapshot=pipeline.status(run);state=snapshot['state'];asset_plan=snapshot['plan']
    if (not snapshot['paused'] or _sha(run/'PLAN.json')!=plan['asset_plan_sha256'] or
            _sha(run/'PAUSE.json')!=plan['pause_sha256']):raise ValueError('recovery_requires_same_paused_asset_run')
    key=plan['asset_key'];old=state.get('reviews',{}).get(key)
    if visual.digest(old)!=plan['original_review_sha256']:raise ValueError('original_unknown_review_changed')
    expected_attempt=2 if after_claim else 1
    if state.get('review_attempts',{}).get(key)!=expected_attempt or asset_plan['config'].get('max_review_attempts',2)<2:
        raise ValueError('local_recovery_review_budget_not_available')
    if (old.get('decision')!='unavailable' or old.get('outcome_unknown') is not True or old.get('completion_known') is not False or
            old.get('style_review',{}).get('result',{}).get('error_type')!='TimeoutExpired'):
        raise ValueError('original_target_style_timeout_unknown_required')
    request=plan['target_style_request'];record=old['style_review'];layout=old.get('layout_review')
    if (record.get('request')!=request or record.get('request_sha256')!=visual.digest(request) or request.get('mode')!='target' or
            request.get('binding',{}).get('reference_contract')!=appearance.CONTRACT or
            request.get('binding',{}).get('target_sha256')!=old.get('target_sha256') or
            _sha(request['target'])!=old['target_sha256']):raise ValueError('original_target_style_binding_changed')
    style.verify_result(request,record['result'],require_accepted=False)
    folder=Path(plan['original_style_dir']);native_request=_read(folder/'REQUEST.json')
    if native_request.get('config',{}).get('provider','transformers_local')!='transformers_local' or native_request.get('review_mode')!=appearance.VERSION:
        raise ValueError('only_local_appearance_target_recovery_supported')
    prepared=appearance._prepared(request)
    binding=visual.digest(dict(config=native_request['config'],prepared=prepared))
    if (native_request.get('prepared')!=[prepared] or native_request.get('request_binding_sha256')!=binding or
            record['result'].get('binding_sha256')!=visual.digest(prepared)):
        raise ValueError('original_style_native_request_binding_changed')
    for frozen in plan['evidence_files']:
        if _sha(frozen['path'])!=frozen['sha256']:raise ValueError('frozen_local_recovery_evidence_changed')
    diagnosis=_read(plan['diagnosis_path'])
    exited,error=_no_original_inference(folder,binding,diagnosis,native_request)
    _exited_processes(diagnosis,folder/'REQUEST.json',_sha(folder/'REQUEST.json'),exited,error)
    _known_layout(plan['original_layout_dir'],layout,old['target_sha256'])
    row=pipeline._raw_lookup(asset_plan,plan['requirement'])
    if not row or registry.review_target(row)!=plan['asset_target']:raise ValueError('local_recovery_asset_version_changed')
    return snapshot,row,native_request


def prepare_recovery(run,asset_key,original_style_dir,original_layout_dir,diagnosis_path,*,recovery_id,actor,statement):
    if not actor or not statement or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',recovery_id):
        raise ValueError('explicit_local_recovery_authorization_required')
    run=Path(run).resolve();snapshot=pipeline.status(run);old=snapshot['state'].get('reviews',{}).get(asset_key)
    if not isinstance(old,dict):raise ValueError('original_review_not_found')
    request=old.get('style_review',{}).get('request',{});rows=registry.get(snapshot['plan']['config']['library'],book_id=snapshot['plan']['packet']['book_id'])
    rows=[r for r in rows if f"{r['asset_id']}:v{r['version']}:{r['sha256']}"==asset_key]
    if len(rows)!=1:raise ValueError('recovery_asset_not_found')
    row=rows[0];style_dir=Path(original_style_dir).resolve();layout_dir=Path(original_layout_dir).resolve()
    if not style_dir.is_relative_to(run/'style_reviews') or not layout_dir.is_relative_to(run/'reviews'):
        raise ValueError('original_recovery_evidence_outside_asset_run')
    evidence=[style_dir/n for n in ('REQUEST.json','CLAIM.json','WORKER_EXIT.json','WORKER_ERROR.json','worker.log')]
    evidence += [layout_dir/n for n in ('REQUEST.json','RESULTS.json','WORKER_EXIT.json','WORKER_STATE.json')]
    evidence.append(Path(diagnosis_path).resolve())
    diagnosis=_read(diagnosis_path)
    for name in ('WORKER_LAUNCH.json','WORKER_RUNTIME.json','WORKER_STATE.json'):
        if (style_dir/name).is_file():evidence.append(style_dir/name)
    if diagnosis.get('worker_source'):evidence.append(Path(diagnosis['worker_source']['path']).resolve())
    plan=dict(schema=VERSION,run=str(run),asset_key=asset_key,asset_plan_sha256=_sha(run/'PLAN.json'),pause_sha256=_sha(run/'PAUSE.json'),
        asset_target=registry.review_target(row),requirement={k:row[k] for k in ('entity_id','kind','view','design_version')},
        original_style_dir=str(style_dir),original_layout_dir=str(layout_dir),diagnosis_path=str(Path(diagnosis_path).resolve()),
        original_review_sha256=visual.digest(old),target_style_request=deepcopy(request),
        evidence_files=[dict(path=str(p),sha256=_sha(p)) for p in evidence],actor=actor,statement=statement,
        original_outcome_known=False,new_target_review_limit=1,total_review_limit=2,
        recovery_phase='resource_preflight_unstarted' if diagnosis.get('bound_files') else 'python_unstarted')
    _validate(plan)
    folder=run/'local_unstarted_recoveries'/recovery_id
    with pipeline.images.run_lock(run):
        pipeline.freeze(folder/'PLAN.json',plan)
    return folder


def execute_recovery(folder,reviewer):
    folder=Path(folder).resolve();plan=_read(folder/'PLAN.json');run=Path(plan['run'])
    if plan.get('schema')!=VERSION or folder.parent!=run/'local_unstarted_recoveries':raise ValueError('invalid_local_recovery_scope')
    with pipeline.images.run_lock(run):
        if (folder/'APPLIED.json').exists():return _read(folder/'APPLIED.json')
        if (folder/'CLAIM.json').exists():raise ValueError('local_recovery_already_claimed_no_automatic_replay')
        snapshot,row,original=_validate(plan)
        if reviewer.provider!='transformers_local' or reviewer.config!=original['config'] or reviewer.discover()!=original['model_binding']:
            raise ValueError('local_recovery_model_or_config_changed')
        with pipeline.gpu_access(snapshot['plan']):
            # Claim and reserve the final existing attempt only after both leases.
            with (folder/'CLAIM.json').open('x',encoding='utf-8') as stream:
                import json
                json.dump(dict(plan_sha256=_sha(folder/'PLAN.json'),at=time.time(),original_outcome_known=False),stream)
            state=snapshot['state'];state['review_attempts'][plan['asset_key']]=2;pipeline.write(run/'STATE.json',state)
            result=reviewer.review_residence_appearance(deepcopy(plan['target_style_request']),evidence_dir=folder/'new_target_review')
        pipeline.freeze(folder/'NEW_TARGET_RESULT.json',result)
        style.verify_result(plan['target_style_request'],result,require_accepted=False)
        current,latest,_=_validate(plan,after_claim=True)
        receipt=dict(schema=VERSION,asset_key=plan['asset_key'],new_target_result_sha256=visual.digest(result),
            original_review_sha256=plan['original_review_sha256'],original_outcome_known=False,review_attempts=2,
            source_reference_redispatched=False,layout_redispatched=False,new_style_decision=result['decision'])
        state=current['state']
        if result.get('completion_known') is True and result.get('outcome_unknown') is False and result['decision']!='unavailable':
            _known_target_style(folder/'new_target_review',result,plan['target_style_request'],original['config'])
            old=state['reviews'][plan['asset_key']]
            record=dict(request=deepcopy(plan['target_style_request']),request_sha256=visual.digest(plan['target_style_request']),result=deepcopy(result))
            combined=pipeline._combine_residence_style(old['layout_review'],record)
            combined['local_unstarted_recovery']=dict(plan_sha256=_sha(folder/'PLAN.json'),original_review_sha256=plan['original_review_sha256'],original_outcome_known=False)
            evidence=dict(image_sha256=latest['sha256'],observations=combined['visual_evidence'],review=visual.digest(combined),
                source_review=deepcopy(combined),model=combined.get('model_binding'),rois=deepcopy(combined.get('rois',{})),reference_roi_evidence=None)
            registry.review(current['plan']['config']['library'],book_id=latest['book_id'],asset_id=latest['asset_id'],version=latest['version'],
                file_sha256=latest['sha256'],decision=combined['decision'] if combined['decision'] in ('accepted','repair_required') else 'unavailable',
                reviewer='local_visual_model',checks={k:v for k,v in combined['checks'].items() if type(v) is bool},evidence=evidence)
            state.setdefault('review_history',{}).setdefault(plan['asset_key'],[]).append(deepcopy(old))
            state['reviews'][plan['asset_key']]=combined;receipt['combined_decision']=combined['decision']
        else:receipt['combined_decision']='not_combined_original_unknown_preserved'
        state.setdefault('local_unstarted_recoveries',{})[plan['asset_key']]=receipt
        state['status']='paused';pipeline.write(run/'STATE.json',state)
        pipeline.freeze(folder/'APPLIED.json',receipt)
        return receipt
