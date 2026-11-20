"""Consume reviewed v3 first frames in a new, serial, local H3 namespace.

Preparation is not media dispatch. No legacy H3 plan/pause is changed; no result
is published or declared visually approved. An unknown POST is never repeated.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image
from jsonschema.exceptions import ValidationError

from . import visual_asset_pipeline_v3 as pipeline
from . import visual_image_jobs_v3 as jobs
from . import visual_environment_v4 as environment
from . import visual_h3_endpoints_v15 as endpoints
from .visual_shot_binding_v3 import AUDIO_MODES, compile_bindings, fingerprint

PROJECT=Path(__file__).resolve().parents[2]
DEFAULT_BASE=PROJECT/'data/video_generation/h3_six_children_s01_720p_20261102/workflow_api.json'
DEFAULT_RUNS=PROJECT/'data/video_generation/visual_h3_v3'
SCHEMA='visual_h3_handoff/v3'
PREFIX='visual_h3_v3'
CLASSES={'119':'VAELoader','120':'VAELoader','121':'VAEDecodeAudio',
    '122':'VAEDecodeTiled','123':'KSamplerSelect','124':'BasicScheduler',
    '125':'SamplerCustomAdvanced','126':'BasicGuider','127':'UNETLoader',
    '128':'CLIPLoader','129':'RandomNoise','130':'CreateVideo',
    'ref_scene':'LoadImage','condition':'MiniMaxH3ImageToVideo',
    'pick_first':'ImageFromBatch','pick_last':'ImageFromBatch',
    'save_first':'SaveImage','save_last':'SaveImage','save_video':'SaveVideo','save_audio':'SaveAudio'}
CHARACTER_CHECKS=('identity','view','clothing','anatomy')
PLACE_CHECKS=('layout','view','consistency','artifact_free')


class HandoffIntegrityError(ValueError):pass


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def file_sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True);jobs._write(Path(path),value)
def freeze(path,value):jobs._freeze(Path(path),value)
def slug(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise ValueError('unsafe_h3_identifier')
    return value
def relative(value):return jobs._relative(value)
def bound(root,value):return jobs._bound(root,value)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise HandoffIntegrityError('h3_http_redirect_refused')


def _http(config,route,value=None):
    client=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    request=urllib.request.Request(config['service_url']+route,
        data=None if value is None else json.dumps(value).encode(),headers={'Content-Type':'application/json'})
    with client.open(request,timeout=config['timeout']) as response:
        raw=response.read(16*1024*1024+1)
    if len(raw)>16*1024*1024:raise HandoffIntegrityError('h3_response_too_large')
    return json.loads(raw)


def _config(asset_plan,config):
    config=deepcopy(config or {});base=asset_plan['config'];service=base['image_service']
    allowed={'service_url','input_root','output_root','gpu_lock_root','protected_pause_path',
             'base_workflow','runs_root','video_enabled','width','height','timeout',
             'keyframe_policy','source_endpoint_certificate','native_prompt_contract','native_prompt_plan','continuity_input_plan'}
    if set(config)-allowed:raise ValueError('unsupported_h3_config')
    endpoints.configured(config)
    if 'continuity_input_plan' in config:
        continuity=config['continuity_input_plan']
        if (not isinstance(continuity,dict) or set(continuity)!={'path','sha256'}
            or 'native_prompt_plan' in config or 'native_prompt_contract' in config or endpoints.configured(config)):
            raise ValueError('exclusive_first_only_continuity_input_plan_required')
    if 'native_prompt_plan' in config or 'native_prompt_contract' in config:
        binding=config.get('native_prompt_plan')
        if (config.get('native_prompt_contract') not in ('official_multimodal/v15','official_multimodal/v19') or not isinstance(binding,dict)
            or set(binding)!={'path','sha256'}):raise ValueError('explicit_native_h3_prompt_plan_required')
    elif endpoints.configured(config):raise ValueError('source_static_endpoints_require_native_prompt_plan')
    for key in ('service_url','input_root','output_root'):config.setdefault(key,service[key])
    config.setdefault('gpu_lock_root',base['gpu_lock_root'])
    config.setdefault('protected_pause_path',base.get('protected_pause_path'))
    config.setdefault('base_workflow',str(DEFAULT_BASE));config.setdefault('runs_root',str(DEFAULT_RUNS))
    config.setdefault('video_enabled',False);config.setdefault('timeout',30)
    if type(config['video_enabled']) is not bool:raise ValueError('explicit_boolean_video_policy_required')
    if not config['protected_pause_path']:raise ValueError('legacy_pause_binding_required')
    parsed=urllib.parse.urlsplit(config['service_url'])
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or not parsed.port
        or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise ValueError('loopback_h3_service_required')
    config['service_url']=config['service_url'].rstrip('/')
    if type(config['timeout']) not in (float,int) or not math.isfinite(config['timeout']) or not 0<config['timeout']<=300:
        raise ValueError('invalid_h3_timeout')
    for key in ('input_root','output_root','gpu_lock_root','base_workflow','runs_root'):
        config[key]=str(Path(config[key]).resolve())
    if config['protected_pause_path']:config['protected_pause_path']=str(Path(config['protected_pause_path']).resolve())
    # The shared lock is released after POST; native queue ownership then keeps
    # image/VLM jobs out. A different service/queue or lock would break that gate.
    if (config['service_url']!=service['service_url'].rstrip('/')
        or any(config[k]!=str(Path(service[k]).resolve()) for k in ('input_root','output_root'))
        or config['gpu_lock_root']!=str(Path(base['gpu_lock_root']).resolve())
        or not base.get('protected_pause_path')
        or config['protected_pause_path']!=str(Path(base['protected_pause_path']).resolve())):
        raise ValueError('h3_must_share_asset_service_mutex_and_legacy_pause_scope')
    if Path(config['runs_root']).name!=PREFIX:raise ValueError('new_visual_h3_namespace_required')
    if any(not Path(config[k]).is_dir() for k in ('input_root','output_root')):raise ValueError('h3_service_directories_missing')
    for key in ('width','height'):
        if key in config and (type(config[key]) is not int or not 64<=config[key]<=2048 or config[key]%16):
            raise ValueError('h3_dimensions_must_be_multiples_of_16')
    return config


def _target(run,config):
    run=Path(run).resolve();root=Path(config['runs_root'])
    if run==root or not run.is_relative_to(root) or run.parent!=root:raise ValueError('new_h3_run_scope_required')
    slug(run.name)
    if any('recovery' in p.lower() for p in run.parts):raise ValueError('legacy_recovery_target_refused')
    return run


def _strict_checks(review,names):
    return (isinstance(review,dict) and review.get('decision')=='accepted'
        and set(review.get('checks',{}))==set(names) and all(review['checks'][k] is True for k in names)
        and review.get('completion_known') is True and review.get('outcome_unknown') is False
        and isinstance(review.get('visual_evidence'),list) and bool(review['visual_evidence'])
        and all(isinstance(e,str) and e.strip() for e in review['visual_evidence']))


def _ready_environment_guide(asset_run,entity,shot,frame):
    """Verify an existing v4 geometry input without rendering or repairing files."""
    guide=frame.get('environment_guide')
    layout=entity.get('spatial_layout')
    if not layout:
        if guide is not None:raise HandoffIntegrityError('h3_ready_environment_guide_without_layout')
        return None
    try:
        asset_plan=read(Path(asset_run)/'PLAN.json')
        if pipeline.static_frames.enabled(asset_plan['config']):
            with Image.open(frame['path']) as image:width,height=image.size
            expected=pipeline.static_frames.guide(asset_run,asset_plan,shot,entity,width=width,height=height,create=False)
            if guide!=expected:raise ValueError('static_shot_guide_changed')
            return guide
        layout=environment.validate_layout(layout)
        if not isinstance(guide,dict):raise ValueError('missing_binding')
        view=shot.get('place_view','front')
        if view not in environment.VIEWS:raise ValueError('unknown_view')
        with Image.open(frame['path']) as image:width,height=image.size
        if any(type(n) is not int or not 64<=n<=2048 or n%16 for n in (width,height)):
            raise ValueError('invalid_guide_dimensions')
        key=fingerprint(dict(layout=layout,renderer=environment.RENDERER,width=width,height=height))[:24]
        root=(Path(asset_run)/'environment_guides').resolve();folder=root/key
        path=Path(guide['path']).resolve();manifest_path=Path(guide['manifest_path']).resolve()
        if (not root.is_relative_to(Path(asset_run).resolve()) or not path.is_relative_to(root) or path!=folder/(view+'.png')
            or manifest_path!=folder/'GUIDES.json'):
            raise ValueError('outside_bound_directory_or_view')
        manifest=read(manifest_path)
        expected_binding=dict(schema=environment.VERSION,renderer=environment.RENDERER,
            layout_sha256=fingerprint(layout),layout=layout,width=width,height=height)
        if (manifest.get('schema')!='environment_guides/v4' or manifest.get('binding')!=expected_binding
            or set(manifest.get('views',{}))!=set(environment.VIEWS)):
            raise ValueError('manifest_layout_camera_or_renderer_changed')
        actual_sha=file_sha(path)
        camera=None if view=='layout' else deepcopy(layout['cameras'][view])
        expected_view=dict(path=str(path),sha256=actual_sha,view=view,layout_sha256=fingerprint(layout),
            camera=camera,technical_guide=True,production_approved=False)
        if manifest['views'][view]!=expected_view:raise ValueError('manifest_view_or_file_changed')
        expected_guide=dict(expected_view,design_sha256=pipeline._environment_design_sha(entity),
            renderer=environment.RENDERER,manifest_path=str(manifest_path))
        if guide!=expected_guide:raise ValueError('frame_layout_camera_design_or_file_changed')
        with Image.open(path) as image:
            if image.format!='PNG' or image.size!=(width,height):raise ValueError('guide_image_format_or_size_changed')
            image.verify()
        return guide
    except (OSError,KeyError,TypeError,ValueError,ValidationError) as error:
        raise HandoffIntegrityError('h3_ready_environment_guide_invalid:'+str(error)) from error


def validate_ready(asset_run):
    """Recompile using current registry versions/dependencies; stale ready is invalid."""
    asset_run=Path(asset_run).resolve();snapshot=pipeline.status(asset_run)
    plan=snapshot['plan'];packet=plan['packet'];ready=read(asset_run/'H3_INPUT_READY.json')
    if (ready.get('schema')!='h3_visual_input/v3' or ready.get('old_batch_resume') is not False
        or ready.get('publication') is not False or ready.get('source')!=packet['source']):
        raise HandoffIntegrityError('h3_ready_source_or_scope_changed')
    if packet.get('style_groups'):
        try:
            for shot in packet.get('shots',[]):pipeline._require_current_shot_style(packet,shot)
        except ValueError as error:raise HandoffIntegrityError('h3_ready_shot_style_requires_restage:'+str(error)) from error
    bindings=compile_bindings(packet,lambda req:pipeline._lookup(plan,req))
    if ready.get('shots')!=bindings['shots'] or read(asset_run/'SHOT_BINDINGS.json')!=bindings:
        raise HandoffIntegrityError('h3_ready_asset_versions_or_staging_changed')
    if not bindings['shots']:raise HandoffIntegrityError('h3_ready_has_no_shots')
    frames=ready.get('first_frames');wanted={s['id'] for s in bindings['shots']}
    if not isinstance(frames,dict) or set(frames)!=wanted:raise HandoffIntegrityError('h3_ready_first_frame_coverage_changed')
    if snapshot['state'].get('status')!='h3_inputs_ready':raise HandoffIntegrityError('asset_pipeline_not_currently_ready')
    places={entity['id']:entity for entity in packet['places']}
    for shot in bindings['shots']:
        frame=frames[shot['id']];path=Path(frame['path']).resolve()
        if (not path.is_relative_to(asset_run) or frame.get('binding_sha256')!=shot['binding_sha256']
            or file_sha(path)!=frame.get('sha256') or snapshot['state'].get('first_frames',{}).get(shot['id'])!=frame):
            raise HandoffIntegrityError('h3_ready_first_frame_changed')
        with Image.open(path) as image:image.verify()
        names=tuple(dict.fromkeys(CHARACTER_CHECKS+PLACE_CHECKS)) if shot['visible_cast'] else PLACE_CHECKS
        review=frame.get('review',{})
        place_entity=places[shot['place_id']]
        if place_entity.get('style_group_id'):
            pipeline._verify_residence_style_receipt(asset_run,plan,place_entity,path,review)
        guide=_ready_environment_guide(asset_run,places[shot['place_id']],shot,frame)
        try:pipeline._verify_first_frame_generation(plan,shot,frame)
        except ValueError as error:raise HandoffIntegrityError('h3_ready_generation_reference_invalid:'+str(error)) from error
        try:pipeline._verify_first_frame_inventory(plan,place_entity,review)
        except ValueError as error:raise HandoffIntegrityError('h3_ready_furniture_inventory_invalid:'+str(error)) from error
        if guide and review.get('layout_guide_sha256')!=guide['sha256']:
            raise HandoffIntegrityError('h3_ready_composition_environment_guide_changed')
        references=[dict(id=a['entity_id'],kind=a['kind'],sha256=a['sha256']) for a in shot['references']]
        if (not _strict_checks(review,names) or review.get('target_sha256')!=frame['sha256']
            or review.get('reference_bindings')!=references):
            raise HandoffIntegrityError('h3_ready_composition_not_source_bound_and_accepted')
        subreviews=review.get('subreviews')
        if not isinstance(subreviews,list) or len(subreviews)!=len(references):
            raise HandoffIntegrityError('h3_ready_composition_subreviews_missing')
        for reference,subreview in zip(references,subreviews):
            checks=CHARACTER_CHECKS if reference['kind']=='character' else PLACE_CHECKS
            if (not _strict_checks(subreview,checks) or subreview.get('target_sha256')!=frame['sha256']
                or subreview.get('reference_sha256')!=reference['sha256']):
                raise HandoffIntegrityError('h3_ready_composition_reference_changed')
            if guide and reference['kind']=='place' and subreview.get('layout_guide_sha256')!=guide['sha256']:
                raise HandoffIntegrityError('h3_ready_place_subreview_environment_guide_changed')
    return snapshot,ready,bindings


def _timing(shot):
    start=shot.get('start');end=shot.get('end')
    if (type(start) not in (int,float) or type(end) not in (int,float)
        or not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end):
        raise ValueError('shot_start_end_required_for_complete_audio_and_action')
    requested=end-start
    if requested>15:raise ValueError('shot_exceeds_h3_range_split_upstream_at_complete_audio_action_boundary')
    frames=max(124,5+17*math.ceil((requested*24-5)/17))
    if frames>362:raise ValueError('shot_exceeds_h3_native_frame_limit')
    return dict(start=start,end=end,requested_seconds=requested,native_frames=frames,native_seconds=frames/24,
                padding_seconds=frames/24-requested,automatic_audio_cut=False)


def prompt_for(shot,timing):
    from .visual_source_voice_v13 import source_direction
    if not isinstance(shot.get('visual_prompt'),str) or not shot['visual_prompt'].strip():raise ValueError('shot_visual_required')
    audio=[]
    for item in shot.get('audio',[]):
        if (item.get('mode') not in AUDIO_MODES or not isinstance(item.get('text'),str)
            or not item['text'].strip() or not isinstance(item.get('speaker'),str) or not item['speaker']):
            raise ValueError('explicit_complete_audio_item_required')
        if item['mode']=='onscreen' and item['speaker'] not in shot['visible_cast']:raise ValueError('onscreen_speaker_not_visible')
        spoken=dict(speaker=item['speaker'],mode=item['mode'],text=item['text'])
        for key in ('source_speaker','source_channel'):
            if key in item:
                if not isinstance(item[key],str) or not item[key].strip():raise ValueError('invalid_source_audio_attribution')
                spoken[key]=item[key]
        direction=source_direction(shot,item)
        if direction is not None:spoken['source_direction']=direction
        audio.append(spoken)
    payload=dict(visual=shot['visual_prompt'],visible_cast=deepcopy(shot['visible_cast']),audio=audio,
                 requested_seconds=timing['requested_seconds'],native_seconds=timing['native_seconds'])
    # Only current-shot visible action and verbatim audio are sent. Captions,
    # prior whole-cast costumes, old opening and tails never enter this prompt.
    offscreen=('offscreen_dialogue为指定角色在画外说话，保持该角色的年龄、声线和对话语气；'
        '画面按本镜入镜角色与动作推进。' if any(a['mode']=='offscreen_dialogue' for a in audio) else '')
    return ('写实中国剧情影像，连续平顺镜头。以输入的已审核首图建立人物外貌、服装与空间。'
        '按本镜画面推进动作与神情，visible_cast给出本镜入镜人物，声音依 audio 顺序逐字使用自然普通话。'
        'onscreen 为对应入镜人物对白与口型；inner_voice 为指定人物心声画外音；'
        'voiceover 为旁白画外音。完整台词与动作落点结束后自然收束。'+offscreen+'\n'
        +json.dumps(payload,ensure_ascii=False,indent=2))


def _validate_graph(graph,scope,input_name,*,keyframe_policy=None):
    if set(graph)!=set(CLASSES) or any(graph[k].get('class_type')!=v for k,v in CLASSES.items()):
        raise HandoffIntegrityError('unsupported_or_changed_h3_graph_classes')
    if graph['ref_scene']['inputs']!={'image':input_name}:raise HandoffIntegrityError('h3_first_frame_input_changed')
    condition=graph['condition']['inputs']
    if any(type(condition.get(k)) is not int or not 64<=condition[k]<=2048 or condition[k]%16 for k in ('width','height')):
        raise HandoffIntegrityError('invalid_h3_native_dimensions')
    if (condition.get('first_frame')!=['ref_scene',0] or 'ref_images' in condition
        or (condition.get('last_frame')!=['ref_scene',0] if keyframe_policy==endpoints.POLICY else 'last_frame' in condition)):
        raise HandoffIntegrityError('h3_requires_this_shot_first_frame_only')
    if keyframe_policy not in (None,endpoints.POLICY):raise HandoffIntegrityError('h3_unknown_keyframe_policy')
    if keyframe_policy==endpoints.POLICY and any(condition[k]%32 for k in ('width','height')):
        raise HandoffIntegrityError('h3_native_endpoint_dimensions_must_be_multiples_of_32')
    if graph['127']['inputs']['unet_name']!='minimax_h3_fl2va_pruned_int8_convrot.safetensors':
        raise HandoffIntegrityError('wrong_h3_image_to_video_model')
    for key,name in [('119','vae_name'),('120','vae_name'),('128','clip_name')]:relative(graph[key]['inputs'][name])
    for role in ('video','audio','first','last'):
        if graph['save_'+role]['inputs']['filename_prefix']!=scope+'/'+role:raise HandoffIntegrityError('h3_output_prefix_changed')
    if graph['130']['inputs'].get('fps')!=24:raise HandoffIntegrityError('h3_requires_24fps')


def build_graph(base,shot,frame,timing,input_name,scope,width=None,height=None,*,keyframe_policy=None,native_prompt=None):
    graph=deepcopy(base)
    if set(graph)!=set(CLASSES) or any(graph[k].get('class_type')!=v for k,v in CLASSES.items()):
        raise HandoffIntegrityError('unsupported_h3_base_workflow')
    graph['ref_scene']['inputs']={'image':input_name}
    condition=graph['condition']['inputs'];condition.pop('last_frame',None)
    condition.update(prompt=prompt_for(shot,timing),length=timing['native_frames'],first_frame=['ref_scene',0])
    if native_prompt is not None:
        if not isinstance(native_prompt,str) or not native_prompt.strip():raise ValueError('native_h3_prompt_text_required')
        condition['prompt']=native_prompt
    if keyframe_policy==endpoints.POLICY:condition['last_frame']=['ref_scene',0]
    if width is not None:condition['width']=width
    if height is not None:condition['height']=height
    with Image.open(frame['path']) as image:
        actual_aspect=image.width/image.height
    if abs(actual_aspect/(condition['width']/condition['height'])-1)>0.01:
        raise HandoffIntegrityError('reviewed_first_frame_aspect_mismatch_regenerate_upstream_or_match_h3_dimensions')
    graph['129']['inputs']['noise_seed']=int(fingerprint(dict(shot=shot['binding_sha256'],frame=frame['sha256']))[:14],16)
    graph['pick_first']['inputs']['batch_index']=0;graph['pick_last']['inputs']['batch_index']=timing['native_frames']-1
    for role in ('video','audio','first','last'):graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    _validate_graph(graph,scope,input_name,keyframe_policy=keyframe_policy)
    return graph


def _native_prompt(packet,config,shot,timing):
    if 'native_prompt_plan' not in config:return None
    from . import visual_h3_native_prompt_v15 as native
    entry=native.load_for(packet,config['native_prompt_plan'],shot)
    expected=(native.CONTRACT_V19 if entry.get('camera_contract')==native.CAMERA_CONTRACT_V19 else native.CONTRACT)
    if config.get('native_prompt_contract')!=expected:
        raise HandoffIntegrityError('native_prompt_wire_contract_mismatch')
    return native.compile_for(shot,timing,entry,anchor_mode='first_last' if endpoints.configured(config) else 'first')


def _continuity_input(packet,config,shot,frame,timing):
    if 'continuity_input_plan' not in config:return None
    from . import visual_h3_continuity_input_v33 as continuity
    return continuity.load_for(packet,config['continuity_input_plan'],shot,frame,timing)


def _continuity_proof(result):
    return {k:deepcopy(result[k]) for k in ('schema','plan','entry_sha256','first_image','coverage_review',
        'generation_receipt','compiled_prompt_utf8_sha256')}


def prepare_from_ready(asset_run,h3_run,config=None):
    snapshot,ready,bindings=validate_ready(asset_run)
    return _prepare_from_inputs(asset_run,h3_run,config,snapshot,ready,bindings)


def prepare_from_continuity(plan_binding,h3_run,config):
    """Explicit reviewed v33 input adapter, including three-person first images."""
    from . import visual_h3_continuity_input_v33 as continuity
    config=deepcopy(config)
    if config.get('continuity_input_plan',plan_binding)!=plan_binding:raise HandoffIntegrityError('continuity_plan_config_mismatch')
    config['continuity_input_plan']=plan_binding
    snapshot,ready,bindings=continuity.handoff_snapshot(plan_binding,config)
    return _prepare_from_inputs(Path(plan_binding['path']).parent,h3_run,config,snapshot,ready,bindings,continuity_source=plan_binding)


def _prepare_from_inputs(asset_run,h3_run,config,snapshot,ready,bindings,*,continuity_source=None):
    cfg=_config(snapshot['plan'],config)
    if ('width' in cfg)!=('height' in cfg):raise ValueError('explicit_h3_width_height_pair_required')
    if 'width' not in cfg:
        sizes=[]
        for shot in bindings['shots']:
            with Image.open(ready['first_frames'][shot['id']]['path']) as image:sizes.append(image.size)
        if len(set(sizes))!=1:raise HandoffIntegrityError('auto_h3_dimensions_require_equal_first_frame_sizes')
        width,height=sizes[0]
        if any(type(n) is not int or not 64<=n<=2048 or n%16 for n in (width,height)):
            raise HandoffIntegrityError('reviewed_first_frame_size_invalid_for_h3_no_automatic_crop')
        cfg.update(width=width,height=height)
    run=_target(h3_run,cfg);base_path=Path(cfg['base_workflow']);base=read(base_path)
    if 'continuity_input_plan' in cfg and (run/'PLAN.json').exists() and read(run/'PLAN.json')['config']!=cfg:
        raise HandoffIntegrityError('frozen_h3_plan_changed_use_new_run')
    protected=None
    if cfg['protected_pause_path']:
        protected=dict(path=cfg['protected_pause_path'],sha256=file_sha(cfg['protected_pause_path']))
    plan=dict(schema=SCHEMA,asset_run=str(Path(asset_run).resolve()),config=cfg,
        source=ready['source'],ready_sha256=continuity_source['sha256'] if continuity_source else file_sha(Path(asset_run)/'H3_INPUT_READY.json'),
        asset_plan_sha256=continuity_source['sha256'] if continuity_source else file_sha(Path(asset_run)/'PLAN.json'),bindings_sha256=fingerprint(bindings),
        base_workflow_sha256=file_sha(base_path),protected_pause=protected,shots=[],
        publication=False,old_batch_resume=False,media_generated=False)
    if continuity_source:plan.update(upstream_contract='h3_continuity_input/v33',continuity_source_plan=continuity_source)
    graphs={};stage=[]
    for shot in bindings['shots']:
        sid=slug(shot['id']);frame=ready['first_frames'][sid];timing=_timing(shot)
        scope=PREFIX+'/'+run.name+'/'+sid;input_name=scope+'/first_frame'+Path(frame['path']).suffix.lower()
        endpoint=(endpoints.validate_certificate(asset_run,snapshot,ready,bindings,cfg['source_endpoint_certificate'],shot)
                  if endpoints.configured(cfg) else None)
        native_prompt=_native_prompt(snapshot['plan']['packet'],cfg,shot,timing)
        continuity=_continuity_input(snapshot['plan']['packet'],cfg,shot,frame,timing)
        if continuity is not None:
            if continuity['status']!='ready':
                report=run/'continuity_workorders'/(sid+'_'+continuity['entry_sha256']+'.json')
                report.parent.mkdir(parents=True,exist_ok=True);freeze(report,continuity)
                raise HandoffIntegrityError('continuity_input_'+continuity['status']+':'+str(report))
            native_prompt=continuity['compiled_prompt']
        graph=build_graph(base,shot,frame,timing,input_name,scope,cfg.get('width'),cfg.get('height'),
            keyframe_policy=cfg.get('keyframe_policy'),native_prompt=native_prompt)
        graphs[sid]=graph
        plan['shots'].append(dict(id=sid,binding_sha256=shot['binding_sha256'],first_frame=deepcopy(frame),
            graph_sha256=fingerprint(graph),scope=scope,input_name=input_name,timing=timing,
            subtitles=dict(stage='postproduction',audio=deepcopy(shot.get('audio',[])),**({'enabled':False} if continuity is not None else {})),
            **({'keyframe_conditioning':endpoint} if endpoint else {}),
            **({'native_prompt':dict(contract=cfg['native_prompt_contract'],plan=cfg['native_prompt_plan'],
                anchor_mode='first_last' if endpoint else 'first',prompt_sha256=fingerprint(native_prompt))} if native_prompt and continuity is None else {}),
            **({'continuity_input':_continuity_proof(continuity)} if continuity is not None else {})))
        stage.append((frame,input_name))
    run.mkdir(parents=True,exist_ok=True)
    with jobs.run_lock(run):
        if (run/'PLAN.json').exists() and read(run/'PLAN.json')!=plan:raise HandoffIntegrityError('frozen_h3_plan_changed_use_new_run')
        for frame,name in stage:
            jobs.stage_input({k:cfg[k] for k in ('service_url','input_root','output_root','timeout')},frame['path'],name,frame['sha256'])
        for sid,graph in graphs.items():
            folder=run/'shots'/sid;folder.mkdir(parents=True,exist_ok=True);freeze(folder/'workflow_api.json',graph)
            if not (folder/'STATE.json').exists():write(folder/'STATE.json',dict(id=sid,status='prepared',prompt_id=None,plan_sha256=fingerprint(plan)))
        freeze(run/'PLAN.json',plan)
        if not (run/'STATE.json').exists():write(run/'STATE.json',dict(status='prepared',plan_sha256=fingerprint(plan),publication=False))
    return status(run)


def _load(run,current=True):
    run=Path(run).resolve();plan=read(run/'PLAN.json')
    if plan.get('schema')!=SCHEMA or plan.get('publication') is not False or plan.get('old_batch_resume') is not False:
        raise HandoffIntegrityError('not_new_h3_handoff_plan')
    cfg=_config(dict(config=dict(image_service=plan['config'],**{k:plan['config'][k] for k in ('gpu_lock_root','protected_pause_path')})),plan['config'])
    if _target(run,cfg)!=run or read(run/'STATE.json').get('plan_sha256')!=fingerprint(plan):raise HandoffIntegrityError('h3_plan_or_scope_changed')
    for row in plan['shots']:
        slug(row['id']);folder=run/'shots'/row['id'];graph=read(folder/'workflow_api.json')
        if fingerprint(graph)!=row['graph_sha256']:raise HandoffIntegrityError('frozen_h3_graph_changed')
        _validate_graph(graph,row['scope'],row['input_name'],keyframe_policy=cfg.get('keyframe_policy'))
        if endpoints.configured(cfg):
            proof=row.get('keyframe_conditioning',{})
            if (proof.get('policy')!=endpoints.POLICY or proof.get('certificate')!=cfg['source_endpoint_certificate']
                or proof.get('binding_sha256')!=row['binding_sha256'] or proof.get('source_same_frame_conditioning') is not True
                or proof.get('first_frame_sha256')!=row['first_frame']['sha256'] or proof.get('last_frame_sha256')!=row['first_frame']['sha256']):
                raise HandoffIntegrityError('h3_frozen_endpoint_conditioning_changed')
        elif row.get('keyframe_conditioning') is not None:raise HandoffIntegrityError('h3_endpoint_proof_without_policy')
        if 'native_prompt_plan' in cfg:
            expected=dict(contract=cfg['native_prompt_contract'],plan=cfg['native_prompt_plan'],
                anchor_mode='first_last' if endpoints.configured(cfg) else 'first',prompt_sha256=fingerprint(graph['condition']['inputs']['prompt']))
            if row.get('native_prompt')!=expected:raise HandoffIntegrityError('h3_frozen_native_prompt_binding_changed')
        if 'continuity_input_plan' in cfg:
            from . import visual_h3_continuity_input_v33 as continuity
            proof=row.get('continuity_input',{})
            first={k:row['first_frame'][k] for k in ('path','sha256')}
            if (proof.get('schema')!=continuity.SCHEMA or proof.get('plan')!=cfg['continuity_input_plan']
                or proof.get('first_image')!=first or not isinstance(proof.get('entry_sha256'),str)
                or proof.get('compiled_prompt_utf8_sha256')!=continuity.sha(graph['condition']['inputs']['prompt'])
                or row.get('native_prompt') is not None or row.get('subtitles',{}).get('enabled') is not False):
                raise HandoffIntegrityError('h3_frozen_continuity_input_changed')
    if current:
        asset=Path(plan['asset_run'])
        if plan.get('upstream_contract')=='h3_continuity_input/v33':
            from . import visual_h3_continuity_input_v33 as continuity
            if plan.get('continuity_source_plan')!=cfg.get('continuity_input_plan'):raise HandoffIntegrityError('continuity_source_plan_changed')
            continuity.check(plan['continuity_source_plan']);snapshot,ready,bindings=continuity.handoff_snapshot(plan['continuity_source_plan'],cfg)
            upstream_plan_sha=upstream_ready_sha=plan['continuity_source_plan']['sha256']
        else:
            snapshot,ready,bindings=validate_ready(asset)
            upstream_plan_sha=file_sha(asset/'PLAN.json');upstream_ready_sha=file_sha(asset/'H3_INPUT_READY.json')
        if (upstream_plan_sha!=plan['asset_plan_sha256'] or upstream_ready_sha!=plan['ready_sha256']
            or fingerprint(bindings)!=plan['bindings_sha256'] or ready['source']!=plan['source']
            or file_sha(cfg['base_workflow'])!=plan['base_workflow_sha256']):
            raise HandoffIntegrityError('h3_frozen_upstream_changed')
        current_shots={shot['id']:shot for shot in bindings['shots']}
        for row in plan['shots']:
            shot=current_shots[row['id']]
            if endpoints.configured(cfg):
                current_endpoint=endpoints.validate_certificate(asset,snapshot,ready,bindings,cfg['source_endpoint_certificate'],shot)
                if current_endpoint!=row['keyframe_conditioning']:raise HandoffIntegrityError('h3_current_endpoint_certificate_changed')
            expected_prompt=_native_prompt(snapshot['plan']['packet'],cfg,shot,row['timing'])
            continuity=_continuity_input(snapshot['plan']['packet'],cfg,shot,ready['first_frames'][row['id']],row['timing'])
            if continuity is not None:
                if continuity['status']!='ready' or _continuity_proof(continuity)!=row['continuity_input']:
                    raise HandoffIntegrityError('h3_current_continuity_input_not_ready_or_changed')
                expected_prompt=continuity['compiled_prompt']
            if expected_prompt is not None and read(run/'shots'/row['id']/'workflow_api.json')['condition']['inputs']['prompt']!=expected_prompt:
                raise HandoffIntegrityError('h3_current_native_prompt_changed')
    return run,plan


def _shot_state(folder,plan,row):
    state=read(folder/'STATE.json')
    if state.get('id')!=row['id'] or state.get('plan_sha256')!=fingerprint(plan):raise HandoffIntegrityError('h3_shot_state_changed')
    response=read(folder/'RESPONSE.json') if (folder/'RESPONSE.json').exists() else {}
    # A malformed HTTP-200 body may still follow an accepted native request.
    # Retain it verbatim and keep the claim unknown; never infer rejection.
    if not isinstance(response,dict):response={}
    pid=response.get('prompt_id')
    if not isinstance(pid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',pid):pid=None
    if pid:
        slug(pid)
        if state.get('prompt_id') not in (None,pid):raise HandoffIntegrityError('h3_native_identity_changed')
        if not (folder/'CLAIM.json').exists() or not (folder/'REQUEST.json').exists():raise HandoffIntegrityError('h3_native_claim_missing')
        claim=read(folder/'CLAIM.json');request=read(folder/'REQUEST.json')
        if (claim.get('graph_sha256')!=row['graph_sha256'] or claim.get('first_frame_sha256')!=row['first_frame']['sha256']
            or fingerprint(request.get('prompt'))!=row['graph_sha256']):
            raise HandoffIntegrityError('h3_native_submission_binding_changed')
        state['prompt_id']=pid
        if state['status']=='prepared':state['status']='submitted'
    elif state.get('prompt_id'):raise HandoffIntegrityError('h3_native_response_missing')
    if (folder/'CLAIM.json').exists() and not pid and state['status']!='rejected':state['status']='outcome_unknown'
    if state['status']=='technical_saved':_verify_result(folder,plan,row,state)
    return state


def status(h3_run):
    run,plan=_load(h3_run);shots=[]
    for row in plan['shots']:shots.append(_shot_state(run/'shots'/row['id'],plan,row))
    states=[s['status'] for s in shots]
    current=('media_review_required' if all(s=='technical_saved' for s in states) else
        'outcome_unknown' if 'outcome_unknown' in states else 'blocked_native_failure' if any(s in ('failed','interrupted','rejected') for s in states) else
        'paused' if (run/'PAUSE.json').exists() else 'running' if any(s in ('submitted','running','queued') for s in states) else 'prepared')
    return dict(schema=SCHEMA,status=current,shots=shots,paused=(run/'PAUSE.json').exists(),
        video_enabled=plan['config']['video_enabled'],publication=False,production_approved=False,
        media_generated=any(s=='technical_saved' for s in states),input_ready_sha256=plan['ready_sha256'])


def set_paused(h3_run,paused=True,*,actor='operator'):
    if type(paused) is not bool or not isinstance(actor,str) or not actor.strip():raise ValueError('explicit_pause_actor_required')
    run,plan=_load(h3_run,current=False)
    with jobs.run_lock(run):
        record=dict(plan_sha256=fingerprint(plan),action='pause' if paused else 'resume',actor=actor,at=time.time())
        write(run/'CONTROL'/(uuid.uuid4().hex+'.json'),record)
        if paused:write(run/'PAUSE.json',record)
        elif (run/'PAUSE.json').exists():
            if read(run/'PAUSE.json').get('plan_sha256')!=fingerprint(plan):raise HandoffIntegrityError('foreign_h3_pause_marker')
            (run/'PAUSE.json').unlink()
    return dict(paused=paused,publication=False)


def _queue(cfg):
    q=_http(cfg,'/queue')
    if not isinstance(q,dict) or any(type(q.get(k)) is not list for k in ('queue_running','queue_pending')):
        raise HandoffIntegrityError('invalid_h3_queue_response')
    if any(not isinstance(r,list) or len(r)<3 or not isinstance(r[1],str) or not isinstance(r[2],dict) for r in q['queue_running']+q['queue_pending']):
        raise HandoffIntegrityError('invalid_h3_queue_row')
    return q


def _service_paths(cfg):
    stats=_http(cfg,'/system_stats')
    try:
        argv=stats['system']['argv'];observed={key:Path(argv[argv.index(flag)+1]).resolve()
            for key,flag in [('input_root','--input-directory'),('output_root','--output-directory')]}
    except (ValueError,KeyError,IndexError,TypeError):raise HandoffIntegrityError('h3_service_paths_unconfirmed') from None
    if any(observed[k]!=Path(cfg[k]) for k in observed):raise HandoffIntegrityError('wrong_h3_service_paths')


def native_graph_equivalence(expected,observed):
    """Recognize only two observed Comfy FLOAT-input casts; keep both raw graphs."""
    if not isinstance(expected,dict) or not isinstance(observed,dict):return None
    normal=deepcopy(observed);operations=[]
    for node,field,value in [('124','denoise',1),('130','fps',24)]:
        original=expected.get(node,{}).get('inputs',{}).get(field)
        actual=normal.get(node,{}).get('inputs',{}).get(field)
        if type(original) is int and original==value and type(actual) is float and actual==value:
            normal[node]['inputs'][field]=original
            operations.append(dict(path=node+'/inputs/'+field,source_value=original,native_value=actual,
                                   source_type='int',native_type='float'))
    if fingerprint(normal)!=fingerprint(expected):return None
    return dict(schema='h3_native_float_input_cast/v1',source_graph_sha256=fingerprint(expected),
                native_graph_sha256=fingerprint(observed),normalizations=operations)


def _verify_native_graph(folder,row,observed,prompt_id):
    expected=read(folder/'workflow_api.json')
    if fingerprint(expected)!=row['graph_sha256']:raise HandoffIntegrityError('frozen_h3_graph_changed')
    proof=native_graph_equivalence(expected,observed)
    if proof is None:return False
    if proof['normalizations']:
        proof=dict(proof,prompt_id=prompt_id)
        receipts=folder/'native_graph_receipts';receipts.mkdir(parents=True,exist_ok=True)
        freeze(receipts/(proof['native_graph_sha256']+'.json'),proof)
    return True


@contextmanager
def _gpu(plan):
    cfg=plan['config'];root=Path(cfg['gpu_lock_root']);root.mkdir(parents=True,exist_ok=True)
    with jobs.run_lock(root,'GPU.lock'),jobs.run_lock(Path(cfg['input_root']),'VISUAL_GPU.lock'):
        protected=plan['protected_pause']
        if protected and file_sha(protected['path'])!=protected['sha256']:raise HandoffIntegrityError('legacy_pause_changed')
        yield


@contextmanager
def _upstream_dispatch_fence(plan):
    if plan.get('upstream_contract')=='h3_continuity_input/v33':
        # v33 has its own immutable input plan, not a fabricated v3 registry.
        root=Path(plan['continuity_source_plan']['path']).parent
        with jobs.run_lock(root,'CONTINUITY_INPUT_DISPATCH.lock'):yield
    else:
        asset_plan=read(Path(plan['asset_run'])/'PLAN.json')
        with pipeline.library._lock(Path(asset_plan['config']['library'])):yield


def submit_next(h3_run):
    run,plan=_load(h3_run);cfg=plan['config']
    with jobs.run_lock(run):
        current=status(run)
        if not cfg['video_enabled']:return dict(current,dispatch='video_policy_disabled')
        if current['paused']:return dict(current,dispatch='paused_before_submit')
        row=next((r for r,s in zip(plan['shots'],current['shots']) if s['status']!='technical_saved'),None)
        if row is None:return current
        folder=run/'shots'/row['id'];state=_shot_state(folder,plan,row)
        if state['status']!='prepared':return current
        # Keep the final current-version compilation and POST in one registry
        # mutation fence, using the same GPU -> library lock order as the pipeline.
        with _gpu(plan),_upstream_dispatch_fence(plan):
            _load(run)
            if (run/'PAUSE.json').exists():return dict(current,dispatch='paused_before_submit')
            _service_paths(cfg);q=_queue(cfg)
            if q['queue_running'] or q['queue_pending']:return dict(current,dispatch='waiting_gpu_queue')
            staged=bound(cfg['input_root'],row['input_name'])
            if file_sha(staged)!=row['first_frame']['sha256']:raise HandoffIntegrityError('staged_first_frame_changed')
            request=dict(prompt=read(folder/'workflow_api.json'),client_id=uuid.uuid4().hex)
            freeze(folder/'REQUEST.json',request);freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],first_frame_sha256=row['first_frame']['sha256']))
            try:response=_http(cfg,'/prompt',request)
            except urllib.error.HTTPError as error:
                freeze(folder/'SUBMISSION_ERROR.json',dict(type='HTTPError',code=error.code,response=error.read(16000).decode('utf-8',errors='replace')))
                state.update(status='rejected' if error.code in (400,422) else 'outcome_unknown',reason='native_http_'+str(error.code))
            except Exception as error:
                freeze(folder/'SUBMISSION_ERROR.json',dict(type=type(error).__name__,message=str(error)))
                state.update(status='outcome_unknown',reason='post_result_not_observed')
            else:
                freeze(folder/'RESPONSE.json',response)
                if not isinstance(response,dict) or not isinstance(response.get('prompt_id'),str) or not response['prompt_id']:
                    state.update(status='outcome_unknown',reason='native_response_missing_id')
                else:
                    if re.fullmatch(r'[A-Za-z0-9_-]{1,100}',response['prompt_id']):
                        state.update(status='submitted',prompt_id=response['prompt_id'],submitted_at=time.time())
                    else:state.update(status='outcome_unknown',reason='native_response_unsafe_id')
            write(folder/'STATE.json',state)
    return status(run)


def _metadata(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],
        capture_output=True,text=True,timeout=60,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return json.loads(result.stdout)


def _verify_result(folder,plan,row,state):
    result=read(folder/'RESULT.json')
    if (result.get('prompt_id')!=state.get('prompt_id') or result.get('graph_sha256')!=row['graph_sha256']
        or result.get('first_frame_sha256')!=row['first_frame']['sha256']
        or result.get('publication') is not False or result.get('production_approved') is not False
        or result.get('technical_status')!='technical_saved' or result.get('content_status')!='media_review_required'):
        raise HandoffIntegrityError('h3_saved_result_binding_changed')
    for key in ('keyframe_conditioning','native_prompt','continuity_input'):
        if row.get(key) is not None and result.get(key)!=row[key]:raise HandoffIntegrityError('h3_saved_conditioning_metadata_changed')
    if set(result.get('files',{}))!={'video','audio','first','last'}:raise HandoffIntegrityError('h3_saved_output_coverage_changed')
    for item in result['files'].values():
        path=Path(item['path']).resolve()
        if not path.is_relative_to(folder/'artifacts') or file_sha(path)!=item['sha256']:
            raise HandoffIntegrityError('h3_saved_output_changed')
    return result


def _collect(folder,plan,row,state,entry):
    cfg=plan['config'];files={};scope=(Path(cfg['output_root'])/row['scope']).resolve()
    for role,key,suffix in [('video','images','.mp4'),('audio','audio','.flac'),('first','images','.png'),('last','images','.png')]:
        records=entry.get('outputs',{}).get('save_'+role,{}).get(key)
        if not isinstance(records,list) or len(records)!=1 or records[0].get('type')!='output':
            raise HandoffIntegrityError('h3_expected_native_output_missing')
        record=records[0];filename=record.get('filename')
        if not isinstance(filename,str) or '/' in filename or '\\' in filename or not filename.startswith(role+'_') or Path(filename).suffix.lower()!=suffix:
            raise HandoffIntegrityError('h3_native_filename_changed')
        subfolder=record.get('subfolder','').replace('\\','/')
        source=bound(cfg['output_root'],subfolder+'/'+filename if subfolder else filename)
        if source.parent!=scope or not source.is_file() or source.stat().st_size==0:raise HandoffIntegrityError('h3_native_output_scope_changed')
        if role in ('first','last'):
            with Image.open(source) as image:image.verify()
        dest=folder/'artifacts'/filename;dest.parent.mkdir(exist_ok=True);original_sha=file_sha(source)
        if dest.exists():
            if file_sha(dest)!=original_sha:raise HandoffIntegrityError('h3_partial_local_copy_changed')
        else:jobs._copy_new(source,dest)
        if file_sha(dest)!=original_sha:raise HandoffIntegrityError('h3_output_changed_during_copy')
        files[role]=dict(path=str(dest),source_path=str(source),sha256=original_sha)
    graph=read(folder/'workflow_api.json');condition=graph['condition']['inputs']
    metadata=_metadata(files['video']['path']);streams=metadata['streams']
    video=next((s for s in streams if s['codec_type']=='video'),None);audio=next((s for s in streams if s['codec_type']=='audio'),None)
    if (not video or not audio or video['width']!=condition['width'] or video['height']!=condition['height']
        or int(video.get('nb_frames',-1))!=row['timing']['native_frames'] or video.get('r_frame_rate')!='24/1'):
        raise HandoffIntegrityError('h3_native_av_metadata_mismatch')
    standalone_audio=_metadata(files['audio']['path'])
    if not any(s.get('codec_type')=='audio' for s in standalone_audio['streams']):raise HandoffIntegrityError('h3_saved_audio_stream_missing')
    for role in ('first','last'):
        with Image.open(files[role]['path']) as image:
            if image.size!=(condition['width'],condition['height']):raise HandoffIntegrityError('h3_native_frame_dimensions_changed')
    result=dict(schema=SCHEMA,shot_id=row['id'],prompt_id=state['prompt_id'],graph_sha256=row['graph_sha256'],
        first_frame_sha256=row['first_frame']['sha256'],files=files,timing=row['timing'],native_metadata=metadata,
        technical_status='technical_saved',content_status='media_review_required',automatic_audio_cut=False,
        production_approved=False,publication=False,old_batch_resume=False,
        **({key:deepcopy(row[key]) for key in ('keyframe_conditioning','native_prompt','continuity_input') if row.get(key) is not None}))
    freeze(folder/'RESULT.json',result);state['status']='technical_saved';write(folder/'STATE.json',state)
    return result


def poll_collect(h3_run):
    # Frozen original IDs are still collected while paused or upstream has changed.
    run,plan=_load(h3_run,current=False);cfg=plan['config']
    with jobs.run_lock(run):
        source_error=None
        try:_load(run)
        except (OSError,ValueError,KeyError) as error:source_error=dict(type=type(error).__name__,message=str(error))
        for row in plan['shots']:
            folder=run/'shots'/row['id'];state=_shot_state(folder,plan,row)
            if not state.get('prompt_id') or state['status'] in ('technical_saved','failed','interrupted','rejected'):continue
            pid=state['prompt_id'];history=_http(cfg,'/history/'+slug(pid))
            if not isinstance(history,dict):raise HandoffIntegrityError('invalid_h3_history_response')
            entry=history.get(pid)
            if entry:
                prompt=entry.get('prompt');native=entry.get('status')
                if (not isinstance(prompt,list) or len(prompt)<3 or prompt[1]!=pid or not _verify_native_graph(folder,row,prompt[2],pid)
                    or not isinstance(native,dict) or type(native.get('completed')) is not bool or native.get('status_str') not in ('success','error')):
                    raise HandoffIntegrityError('h3_native_history_identity_or_schema_changed')
                write(folder/'HISTORY.latest.json',history)
                if native['status_str']=='error':
                    events=[x[0] for x in native.get('messages',[]) if isinstance(x,list) and x]
                    state.update(status='interrupted' if 'execution_interrupted' in events else 'failed',native_terminal=native)
                elif native['completed']:
                    freeze(folder/'HISTORY.json',history);_collect(folder,plan,row,state,entry)
                else:state['status']='running'
            else:
                queue=_queue(cfg);matches=[q for q in queue['queue_running']+queue['queue_pending'] if q[1]==pid]
                if any(not _verify_native_graph(folder,row,q[2],pid) for q in matches):raise HandoffIntegrityError('h3_native_queue_graph_changed')
                state.update(status='running' if matches else 'outcome_unknown',reason=None if matches else 'original_id_absent_history_and_queue')
            write(folder/'STATE.json',state)
        if source_error:
            write(run/'INPUT_INVALID.json',dict(at=time.time(),error=source_error))
            return dict(status='blocked_upstream_changed',input_error=source_error,shots=[_shot_state(run/'shots'/r['id'],plan,r) for r in plan['shots']],publication=False,production_approved=False)
    return status(run)
