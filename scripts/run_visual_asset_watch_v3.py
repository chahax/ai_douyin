"""Explicit local text-to-assets watcher. Disabled policies never dispatch work."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.content_factory import visual_asset_pipeline_v3 as flow
from src.content_factory.visual_asset_handoff_v3 import enqueue_accepted,POLICY_VERSION,_local_url
from src.content_factory.visual_shot_binding_v3 import fingerprint
from src.content_factory import visual_image_jobs_v3 as images

ROOT=Path(__file__).resolve().parents[1]


def validate_policy(root,policy):
    root=Path(root).resolve();base=root/'data/visual_asset_pipeline'
    if policy.get('schema')!=POLICY_VERSION or type(policy.get('enabled')) is not bool:raise ValueError('invalid_media_policy')
    if policy['enabled'] is False:return policy
    if 'h3_delivery' in policy:
        from src.content_factory.visual_h3_reference_delivery_v20 import policy_options
        policy_options(policy['h3_delivery'])
        if policy['pipeline_config'].get('h3_delivery')!=policy['h3_delivery']['mode']:
            raise ValueError('asset_and_video_delivery_mode_mismatch')
        if (policy['h3_delivery']['mode']=='reference_assets/v20'
                and policy.get('planning',{}).get('source_prompt_contract')!='source_window/v20'):
            raise ValueError('direct_references_require_original_source_video_prompt')
    elif policy['pipeline_config'].get('h3_delivery','first_frame/v3')!='first_frame/v3':
        raise ValueError('reference_asset_delivery_requires_bound_policy')
    if (policy.get('media') is not True or policy.get('publication') is not False or not policy.get('actor')
        or not policy.get('user_statement','').strip() or policy.get('origin') not in ('explicit_user_request','explicit_user_approval')):raise ValueError('explicit_media_policy_required')
    text=Path(policy['text_run']).resolve()
    if not text.is_relative_to(root/'data') or text==root/'data' or not (text/'PLAN.json').is_file():raise ValueError('text_run_outside_project_data')
    if flow.file_sha(text/'PLAN.json')!=policy['text_plan_sha256']:raise ValueError('text_plan_changed')
    source=flow.read(text/'SOURCE.json')
    if str(source.get('manifest',{}).get('book_id'))!=str(policy['book_id']):raise ValueError('policy_book_mismatch')
    config=policy['pipeline_config'];service=root/'data/video_generation/h3_six_children_s01_720p_20261102'
    paths=[(config['library'],root/'data/serial_story_assets'),(config['gpu_lock_root'],base/'gpu'),
        (config['protected_pause_path'],root/'data/video_generation/h3_six_children_full_script_recovery_20261104/PAUSE.json'),
        (config['image_service']['protected_pause_path'],root/'data/video_generation/h3_six_children_full_script_recovery_20261104/PAUSE.json'),
        (config['image_service']['input_root'],service/'input'),(config['image_service']['output_root'],service/'output')]
    if any(Path(actual).resolve()!=expected for actual,expected in paths):raise ValueError('media_service_scope_changed')
    if config['image_service'].get('allowed_prefix')!='visual_assets_v3':raise ValueError('new_asset_output_prefix_required')
    _local_url(config['image_service']['service_url']);_local_url(policy.get('planning',{}).get('service_url','http://127.0.0.1:11434'))
    review=config['visual_review']
    if (review.get('provider')!='transformers_local' or review.get('quantization','nf4')!='nf4'
        or Path(review['model_path']).resolve()!=root/'.local_models/video_analysis/Qwen3-VL-4B-Instruct'):raise ValueError('local_review_scope_changed')
    return policy


def scoped_run(root,value):
    base=Path(root).resolve()/'data/visual_asset_pipeline/runs';path=Path(value).resolve()
    if path.parent!=base:raise ValueError('only_new_asset_runs_allowed')
    return path


def scan_once(root,policy,*,execute=False,planner=None,reviewer=None):
    root=Path(root).resolve();validate_policy(root,policy)
    if not policy['enabled']:return dict(status='disabled',created=[],reused=[],blocked=[],executed=[],h3_prepared=[])
    base=root/'data/visual_asset_pipeline'
    receipt=enqueue_accepted(base,Path(policy['text_run']),policy,planner=planner)
    receipt['executed']=[];receipt['h3_prepared']=[]
    if not execute or receipt['status']=='paused' or (base/'PAUSE.json').exists():return receipt
    folders=sorted(set(receipt['created']+receipt['reused']))
    for value in folders:
        run=scoped_run(root,value)
        if (base/'PAUSE.json').exists():receipt['status']='paused';break
        reference_run=None
        if flow.reference_delivery(flow.status(run)['plan']['config']):
            from src.content_factory import visual_h3_reference_delivery_v20 as direct
            reference_run=root/'data/video_generation'/direct.PREFIX/run.name
            if (reference_run/'PLAN.json').exists():
                original=direct.poll_collect(reference_run)
                if (original.get('dispatch')=='blocked_upstream_changed' or original['paused']
                        or any(s['status'] in ('outcome_unknown','failed','interrupted','rejected') for s in original['shots'])):
                    receipt['h3_prepared'].append(dict(asset_run=str(run),run=str(reference_run),
                        status='original_reference_result_retained',progress=original))
                    continue
        if reviewer is None:
            from src.content_factory.visual_asset_review_v3 import VisualReviewClient
            reviewer=VisualReviewClient(flow.status(run)['plan']['config']['visual_review'])
        try:state=flow.tick(run,reviewer=reviewer)
        except images.JobBusyError:
            receipt['blocked'].append(dict(run=str(run),reason='gpu_busy'));continue
        receipt['executed'].append(dict(run=str(run),status=state.get('status')))
        if flow.reference_delivery(flow.status(run)['plan']['config']):
            if state.get('status')=='reference_assets_ready' and not (base/'PAUSE.json').exists() and not (run/'PAUSE.json').exists():
                from src.content_factory import visual_h3_reference_delivery_v20 as direct
                h3_root=root/'data/video_generation'/direct.PREFIX;h3_run=h3_root/run.name
                options=direct.policy_options(policy['h3_delivery'])
                result=(direct.status(h3_run) if (h3_run/'PLAN.json').exists() else
                    direct.prepare(run,h3_run,config=dict(options,runs_root=str(h3_root),
                        base_workflow=str(root/'data/video_generation/h3_six_children_s01_720p_20261102/workflow_api.json'))))
                if options['video_enabled']:
                    result=direct.poll_collect(h3_run)
                    if result.get('dispatch')!='blocked_upstream_changed':result=direct.submit_next(h3_run)
                receipt['h3_prepared'].append(dict(asset_run=str(run),run=str(h3_run),
                    status='reference_delivery',video_enabled=options['video_enabled'],progress=result))
            continue
        if state.get('status')=='h3_inputs_ready' and not (base/'PAUSE.json').exists() and not (run/'PAUSE.json').exists():
            from src.content_factory.visual_h3_handoff_v3 import prepare_from_ready
            h3_root=root/'data/video_generation/visual_h3_v3';h3_run=h3_root/run.name
            result=prepare_from_ready(run,h3_run,config=dict(video_enabled=False,runs_root=str(h3_root),
                base_workflow=str(root/'data/video_generation/h3_six_children_s01_720p_20261102/workflow_api.json')))
            receipt['h3_prepared'].append(dict(asset_run=str(run),run=str(h3_run),status=result['status'],video_enabled=False))
    return receipt


def _self():
    import psutil
    p=psutil.Process(os.getpid());return dict(pid=p.pid,create_time=p.create_time(),cmdline=p.cmdline())


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--policy',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--once',action='store_true');mode.add_argument('--watch',action='store_true')
    parser.add_argument('--execute',action='store_true');parser.add_argument('--interval',type=float,default=10)
    parser.add_argument('--launch-id');parser.add_argument('--project-root',type=Path,default=ROOT)
    args=parser.parse_args(argv);root=args.project_root.resolve();base=root/'data/visual_asset_pipeline';path=args.policy.resolve()
    if path.parent!=base/'policies':raise ValueError('policy_outside_asset_root')
    if not 1<=args.interval<=3600:raise ValueError('invalid_watch_interval')
    policy=flow.read(path);validate_policy(root,policy);policy_sha=fingerprint(policy)
    if not policy['enabled']:
        print(json.dumps(dict(status='disabled')));return 0
    folder=base/'watchers'/policy_sha[:32];folder.mkdir(parents=True,exist_ok=True)
    identity=dict(**_self(),launch_id=args.launch_id,policy_sha256=policy_sha)
    with images.run_lock(folder,'EXECUTION.lock'):
        flow.write(folder/'WORKER.json',identity)
        exit_status='ended';error=None
        try:
            while True:
                if fingerprint(flow.read(path))!=policy_sha:raise ValueError('watch_policy_changed')
                receipt=scan_once(root,policy,execute=args.execute)
                flow.write(folder/'LATEST.json',dict(at=time.time(),policy_sha256=policy_sha,**receipt))
                if not args.watch:print(json.dumps(receipt,ensure_ascii=True));break
                if receipt['status']=='paused':exit_status='paused';break
                time.sleep(args.interval)
        except Exception as exc:
            exit_status='failed';error=dict(type=type(exc).__name__,message=str(exc));raise
        finally:flow.write(folder/'WORKER_EXIT.json',dict(**identity,exit_known=True,status=exit_status,error=error,at=time.time()))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps(dict(status='error',type=type(error).__name__,message=str(error)),ensure_ascii=True));raise SystemExit(2)
