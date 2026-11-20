"""H3 handoff transport/state black boxes; fixtures do not certify visual quality."""
from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from PIL import Image
import pytest

from src.content_factory import visual_h3_handoff_v3 as h
from src.content_factory import visual_asset_pipeline_v3 as pipeline
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_image_jobs_v3 as jobs
from src.content_factory import visual_environment_v4 as environment
from src.content_factory.visual_shot_binding_v3 import compile_bindings,fingerprint


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.fixture(scope='module')
def native_media(tmp_path_factory):
    """Real CPU encoded AV container for output-validation black boxes, not H3 output."""
    root=tmp_path_factory.mktemp('h3_native_media')
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=gray:s=96x128:r=24',
        '-f','lavfi','-i','anullsrc=r=48000:cl=mono','-frames:v','124','-t',str(124/24),
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(root/'video.mp4')],check=True,timeout=30)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=mono',
        '-t',str(124/24),'-c:a','flac',str(root/'audio.flac')],check=True,timeout=30)
    Image.new('RGB',(96,128),'gray').save(root/'frame.png')
    return root


class Service:
    def __init__(self,root,media):
        self.input=root/'native_input';self.input.mkdir()
        self.output=root/'native_output';self.output.mkdir();self.media=media
        self.posts=[];self.current=None;self.histories={};self.drop=False;self.reject=None
        self.queue_override=None;self.wrong_paths=False;self.response_override=None;owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,obj,code=200):
                data=json.dumps(obj).encode();self.send_response(code);self.send_header('Content-Length',str(len(data)))
                self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path=='/queue':
                    self.reply(owner.queue_override if owner.queue_override is not None else
                        dict(queue_running=[] if not owner.current else [[0,owner.current,owner.posts[-1]['prompt']]],queue_pending=[]))
                elif self.path=='/system_stats':
                    self.reply(dict(system=dict(argv=['main.py','--input-directory',str(owner.input)+'_wrong' if owner.wrong_paths else str(owner.input),
                        '--output-directory',str(owner.output)])))
                elif self.path.startswith('/history/'):
                    pid=self.path.rsplit('/',1)[1];self.reply({pid:owner.histories[pid]} if pid in owner.histories else {})
                else:self.send_error(404)
            def do_POST(self):
                if self.path!='/prompt':self.send_error(404);return
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));owner.posts.append(payload)
                if owner.reject:self.reply(dict(error='fixture_rejected'),owner.reject);return
                owner.current='native_'+str(len(owner.posts))
                if owner.drop:self.connection.shutdown(2);self.connection.close();return
                self.reply(owner.response_override if owner.response_override is not None else dict(prompt_id=owner.current,node_errors={}))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(5)
    def complete(self):
        pid=self.current;assert pid;graph=self.posts[-1]['prompt'];outputs={}
        for role,kind,extension,original in [('video','images','mp4','video.mp4'),('audio','audio','flac','audio.flac'),
            ('first','images','png','frame.png'),('last','images','png','frame.png')]:
            prefix=Path(graph['save_'+role]['inputs']['filename_prefix']);folder=self.output/prefix.parent;folder.mkdir(parents=True,exist_ok=True)
            dest=folder/(prefix.name+'_00001_.'+extension);shutil.copyfile(self.media/original,dest)
            outputs['save_'+role]={kind:[dict(filename=dest.name,subfolder=prefix.parent.as_posix(),type='output')]}
        self.histories[pid]=dict(prompt=[0,pid,deepcopy(graph)],status=dict(completed=True,status_str='success',messages=[['execution_success',{}]]),outputs=outputs)
        self.current=None


@pytest.fixture
def service(tmp_path,native_media):
    s=Service(tmp_path,native_media)
    try:yield s
    finally:s.close()


def review(path,kind,reference_sha=None):
    return dict(decision='accepted',target_sha256=h.file_sha(path),reference_sha256=reference_sha,
        checks={k:True for k in (h.CHARACTER_CHECKS if kind=='character' else h.PLACE_CHECKS)},
        completion_known=True,outcome_unknown=False,retryable=False,
        visual_evidence=['Controlled protocol fixture, not semantic image evaluation.'])


def _room_layout():
    return dict(schema=environment.VERSION,space_type='interior',room=dict(width=4,depth=5,height=2.8),
        openings=[dict(id='door',kind='door',wall='south',offset=3.1,width=.8,bottom=0,height=2.1)],
        objects=[dict(id='bed',kind='bed',description='A plain wooden bed.',center=[.9,2.6],size=[1.3,2,.5],yaw=0,color='wood')],
        cameras=dict(front=dict(eye=[3.2,.4,1.6],target=[1.8,3.1,1.1],fov=80),
            reverse=dict(eye=[.45,4.5,1.6],target=[2.8,1.2,1.1],fov=80),
            side=dict(eye=[3.7,2.3,1.6],target=[.3,2.5,1.1],fov=80)),
        design_note='A production geometry fixture, not a claim about novel measurements.')


def setup(tmp_path,service,enabled=False,shots=2,environment_v4=False):
    run=tmp_path/'asset_run';run.mkdir()
    script=tmp_path/'script.md';script.write_text('The man looks at the door. A complete spoken sentence.',encoding='utf-8')
    pause=tmp_path/'legacy_PAUSE.json';write(pause,dict(keep='original protected pause'))
    packet=dict(schema='visual_asset_packet/v3',book_id='book1',source=dict(path=str(script),sha256=h.file_sha(script)),
        characters=[dict(id='man',design_version='v1',required_views=['front'],age_band='adult')],
        places=[dict(id='room',design_version='v1',required_views=['front'])],shots=[])
    if environment_v4:
        packet['places'][0].update(spatial_layout=_room_layout(),layout_design='A modest room with a bed.',
            front_prompt='A photorealistic modest room, fixed bed and door.')
    for i in range(shots):
        packet['shots'].append(dict(id='shot'+str(i+1),scene_id='scene1',place_id='room',visible_cast=['man'],
            character_views={'man':'front'},visual_prompt='The man looks at the door.',start=i*5,end=(i+1)*5,
            captions='POSTPRODUCTION_CAPTION_SECRET',audio=[dict(speaker='man',mode='onscreen',text='整句台词，逐字保留。'),
                dict(speaker='man',mode='inner_voice',text='心里想着下一步。'),dict(speaker='narrator',mode='voiceover',text='旁白的完整句子。')]))
    cfg=dict(library=str(tmp_path/'library'),gpu_lock_root=str(tmp_path/'gpu'),protected_pause_path=str(pause),
        image_service=dict(service_url=service.url,input_root=str(service.input),output_root=str(service.output)))
    pipeline.prepare(run,packet,cfg)
    for entity,kind in [('man','character'),('room','place')]:
        image=tmp_path/(entity+'.png')
        real=h.PROJECT/'data/image_model_trials/20261106_novel_cast_turnaround/selected/su_mo/front.png'
        if kind=='character' and real.is_file():shutil.copyfile(real,image)
        else:Image.new('RGB',(96,128),'gray').save(image)
        provenance={}
        if environment_v4 and kind=='place':
            provenance=dict(environment_guide=pipeline._environment_guide(run,packet['places'][0],'front',width=128,height=128),
                dependencies=[],dependency_fingerprint=fingerprint([]))
        row=library.register(cfg['library'],image,book_id='book1',entity_id=entity,kind=kind,view='front',design_version='v1',
            provenance=provenance)
        library.review(cfg['library'],book_id='book1',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
            decision='accepted',reviewer='protocol_fixture',checks={k:True for k in library.REVIEW_CHECKS[kind]},
            evidence=dict(image_sha256=row['sha256'],observations=['Fixture only, not semantic QA.']))
    plan=pipeline.read(run/'PLAN.json');bindings=compile_bindings(packet,lambda req:pipeline._lookup(plan,req));frames={}
    for shot in bindings['shots']:
        target=run/'frames'/(shot['id']+'.png');target.parent.mkdir(exist_ok=True)
        # Existing image bytes are consumed through the actual ready/registry contract.
        if environment_v4:Image.new('RGB',(96,128),'gray').save(target)
        else:shutil.copyfile(tmp_path/'man.png',target)
        references=[dict(id=a['entity_id'],kind=a['kind'],sha256=a['sha256']) for a in shot['references']]
        subs=[review(target,a['kind'],a['sha256']) for a in shot['references']]
        composition=dict(decision='accepted',target_sha256=h.file_sha(target),reference_bindings=references,
            checks={k:True for k in tuple(dict.fromkeys(h.CHARACTER_CHECKS+h.PLACE_CHECKS))},subreviews=subs,
            completion_known=True,outcome_unknown=False,retryable=False,
            visual_evidence=['Controlled fixture only, not semantic composition QA.'])
        frames[shot['id']]=dict(path=str(target),sha256=h.file_sha(target),binding_sha256=shot['binding_sha256'],review=composition)
        if environment_v4:
            guide=pipeline._environment_guide(run,packet['places'][0],'front',width=96,height=128)
            frames[shot['id']]['environment_guide']=guide
            composition['layout_guide_sha256']=guide['sha256'];subs[-1]['layout_guide_sha256']=guide['sha256']
    write(run/'SHOT_BINDINGS.json',bindings)
    ready=dict(schema='h3_visual_input/v3',source=packet['source'],shots=bindings['shots'],first_frames=frames,old_batch_resume=False,publication=False)
    write(run/'H3_INPUT_READY.json',ready)
    state=pipeline.read(run/'STATE.json');state.update(status='h3_inputs_ready',first_frames=frames);write(run/'STATE.json',state)
    target=tmp_path/'visual_h3_v3'/'new_batch'
    config=dict(runs_root=str(target.parent),video_enabled=enabled,width=96,height=128,timeout=3)
    return run,target,config


def test_prepare_consumes_current_real_stored_frame_and_only_this_shot_prompt(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service);before=h.file_sha(tmp_path/'legacy_PAUSE.json')
    result=h.prepare_from_ready(asset,run,cfg)
    assert result['status']=='prepared' and not result['video_enabled'] and not service.posts
    plan=h.read(run/'PLAN.json');row=plan['shots'][0];graph=h.read(run/'shots/shot1/workflow_api.json')
    assert graph['condition']['class_type']=='MiniMaxH3ImageToVideo' and set(graph)==set(h.CLASSES)
    assert graph['ref_scene']['inputs']==dict(image=row['input_name'])
    assert h.file_sha(service.input/row['input_name'])==row['first_frame']['sha256']
    prompt=graph['condition']['inputs']['prompt']
    assert '整句台词，逐字保留。' in prompt and 'inner_voice' in prompt and '画外音' in prompt
    assert 'POSTPRODUCTION_CAPTION_SECRET' not in json.dumps(graph) and 'opening.original' not in json.dumps(graph)
    assert '苏墨' not in prompt and '叶南' not in prompt and '叶西决' not in prompt
    assert row['timing']['requested_seconds']==5 and row['timing']['native_frames']==124
    assert plan['publication'] is False and plan['old_batch_resume'] is False and before==h.file_sha(tmp_path/'legacy_PAUSE.json')
    assert h.prepare_from_ready(asset,run,cfg)==result
    assert h.submit_next(run)['dispatch']=='video_policy_disabled' and not service.posts


def test_serial_original_ids_restart_and_pause_collects_inflight_only(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg)
    assert h.submit_next(run)['status']=='running' and len(service.posts)==1
    assert h.submit_next(run)['shots'][0]['prompt_id']=='native_1' and len(service.posts)==1
    h.poll_collect(run);h.set_paused(run,True);service.complete()
    paused=h.poll_collect(run);assert paused['paused'] and paused['shots'][0]['status']=='technical_saved'
    assert h.submit_next(run)['dispatch']=='paused_before_submit' and len(service.posts)==1
    receipt=h.read(run/'shots/shot1/RESULT.json')
    assert receipt['technical_status']=='technical_saved' and receipt['content_status']=='media_review_required'
    assert receipt['publication'] is False and receipt['automatic_audio_cut'] is False
    h.set_paused(run,False);h.submit_next(run);assert len(service.posts)==2
    service.complete();result=h.poll_collect(run)
    assert result['status']=='media_review_required' and result['production_approved'] is False
    h.submit_next(run);h.poll_collect(run);assert len(service.posts)==2


@pytest.mark.parametrize('value',[True,False,1,'true'])
def test_video_dispatch_policy_is_strict_boolean(tmp_path,service,value):
    asset,run,cfg=setup(tmp_path,service);cfg['video_enabled']=value
    if type(value) is bool:
        h.prepare_from_ready(asset,run,cfg);h.submit_next(run);assert len(service.posts)==int(value)
    else:
        with pytest.raises(ValueError,match='boolean'):h.prepare_from_ready(asset,run,cfg)


@pytest.mark.parametrize('entity,kind',[('man','character'),('room','place')])
def test_new_asset_version_blocks_ready_and_frozen_h3_dispatch(tmp_path,service,entity,kind):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg)
    image=tmp_path/'new_man.png';Image.new('RGB',(64,80),'red').save(image)
    library.register(tmp_path/'library',image,book_id='book1',entity_id=entity,kind=kind,view='front',design_version='v1')
    with pytest.raises(ValueError,match='not_reviewed'):h.submit_next(run)
    assert not service.posts


@pytest.mark.parametrize('mutation',[
    lambda r:r['first_frames']['shot1']['review']['reference_bindings'][0].update(sha256='0'*64),
    lambda r:r['first_frames']['shot1']['review']['checks'].update(identity=False),
    lambda r:r['first_frames']['shot1']['review'].update(visual_evidence=[]),
    lambda r:r['first_frames']['shot1']['review']['subreviews'][1].update(reference_sha256='0'*64),
    lambda r:r['shots'][0].update(place_id='wrong_room'),
])
def test_stale_or_unbound_ready_cannot_be_prepared(tmp_path,service,mutation):
    asset,run,cfg=setup(tmp_path,service);ready=h.read(asset/'H3_INPUT_READY.json');mutation(ready)
    write(asset/'H3_INPUT_READY.json',ready)
    # Also alter the live state to show validation does not rely on equality alone.
    state=h.read(asset/'STATE.json');state['first_frames']=ready['first_frames'];write(asset/'STATE.json',state)
    with pytest.raises(ValueError):h.prepare_from_ready(asset,run,cfg)
    assert not run.exists() and not service.posts


def test_missing_ready_and_first_frame_mutation_are_errors_not_healthy(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service);h.prepare_from_ready(asset,run,cfg)
    original=h.read(asset/'H3_INPUT_READY.json');Path(original['first_frames']['shot1']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):h.status(run)
    (asset/'H3_INPUT_READY.json').unlink()
    with pytest.raises(FileNotFoundError):h.status(run)
    assert not service.posts


@pytest.mark.parametrize('seconds,frames',[(2,124),(5,124),(15,362)])
def test_native_grid_records_padding_without_truncating_full_sentence(seconds,frames):
    shot=dict(start=0,end=seconds,visible_cast=['actor'],visual_prompt='He talks.',audio=[dict(speaker='actor',mode='onscreen',text='A complete sentence remains intact.')])
    timing=h._timing(shot);assert timing['native_frames']==frames and timing['automatic_audio_cut'] is False
    assert 'A complete sentence remains intact.' in h.prompt_for(shot,timing)


@pytest.mark.parametrize('shot',[{},dict(start=1,end=1),dict(start=0,end=16),dict(start=0,end=float('nan'))])
def test_missing_or_overlong_timing_requires_upstream_boundary(shot):
    with pytest.raises(ValueError):h._timing(shot)


def test_http_rejected_is_known_but_never_automatically_reposted(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);service.reject=400
    assert h.submit_next(run)['shots'][0]['status']=='rejected'
    h.submit_next(run);h.poll_collect(run);assert len(service.posts)==1


def test_post_disconnect_remains_unknown_and_keeps_single_claim(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);service.drop=True
    assert h.submit_next(run)['status']=='outcome_unknown'
    claim=(run/'shots/shot1/CLAIM.json').read_bytes()
    h.submit_next(run);h.poll_collect(run)
    assert len(service.posts)==1 and (run/'shots/shot1/CLAIM.json').read_bytes()==claim


def test_response_receipt_recovers_original_id_after_state_write_loss(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);h.submit_next(run)
    path=run/'shots/shot1/STATE.json';state=h.read(path);state.update(prompt_id=None,status='prepared');write(path,state)
    assert h.submit_next(run)['shots'][0]['prompt_id']=='native_1' and len(service.posts)==1


def test_claim_without_response_is_preserved_and_never_dispatched_again(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg)
    write(run/'shots/shot1/CLAIM.json',dict(original_unknown=True))
    result=h.submit_next(run)
    assert result['status']=='outcome_unknown' and not service.posts
    h.poll_collect(run);h.submit_next(run);assert not service.posts


def test_native_claim_source_binding_and_staged_frame_cannot_change(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);h.submit_next(run)
    claim=run/'shots/shot1/CLAIM.json';value=h.read(claim);value['first_frame_sha256']='0'*64;write(claim,value)
    with pytest.raises(ValueError,match='binding'):h.status(run)
    assert len(service.posts)==1


@pytest.mark.parametrize('queue',[{},dict(queue_running=None,queue_pending=[]),dict(queue_running=[[0,'wrong']],queue_pending=[])])
def test_invalid_queue_not_treated_as_idle(tmp_path,service,queue):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);service.queue_override=queue
    with pytest.raises(ValueError,match='queue'):h.submit_next(run)
    assert not service.posts and not (run/'shots/shot1/CLAIM.json').exists()


def test_service_paths_must_be_observed_before_submission(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);service.wrong_paths=True
    with pytest.raises(ValueError,match='service_paths'):h.submit_next(run)
    assert not service.posts


def test_unknown_original_id_does_not_create_a_replacement(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);h.submit_next(run);service.current=None
    assert h.poll_collect(run)['status']=='outcome_unknown'
    h.submit_next(run);assert len(service.posts)==1


def test_history_graph_and_output_scope_are_bound_to_original_native_id(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);h.submit_next(run);service.complete()
    entry=service.histories['native_1'];original=deepcopy(entry)
    entry['prompt'][2]['condition']['inputs']['prompt']='changed'
    with pytest.raises(ValueError,match='identity'):h.poll_collect(run)
    service.histories['native_1']=original
    service.histories['native_1']['outputs']['save_video']['images'][0]['subfolder']='other_run'
    with pytest.raises(ValueError,match='scope'):h.poll_collect(run)
    assert len(service.posts)==1


def test_changed_upstream_while_inflight_still_collects_but_blocks_next(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg);h.submit_next(run);service.complete()
    source=Path(h.read(asset/'PLAN.json')['packet']['source']['path']);source.write_text('changed')
    result=h.poll_collect(run)
    assert result['status']=='blocked_upstream_changed' and result['shots'][0]['status']=='technical_saved'
    with pytest.raises(ValueError):h.submit_next(run)
    assert len(service.posts)==1


def test_gpu_mutex_and_old_pause_are_shared_without_mutating_legacy(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg)
    gpu=tmp_path/'gpu';gpu.mkdir(exist_ok=True)
    with jobs.run_lock(gpu,'GPU.lock'):
        with pytest.raises(jobs.JobBusyError):h.submit_next(run)
    before=h.file_sha(tmp_path/'legacy_PAUSE.json');h.set_paused(run,True);h.set_paused(run,False)
    assert h.file_sha(tmp_path/'legacy_PAUSE.json')==before and not service.posts
    (tmp_path/'legacy_PAUSE.json').unlink()
    with pytest.raises(FileNotFoundError):h.submit_next(run)


def test_legacy_target_and_nonlocal_graph_are_rejected(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service)
    with pytest.raises(ValueError,match='scope'):h.prepare_from_ready(asset,tmp_path/'old_h3_batch',cfg)
    base=h.read(h.DEFAULT_BASE);base['remote']=dict(class_type='CloudAPI',inputs={})
    path=tmp_path/'bad_workflow.json';write(path,base);cfg['base_workflow']=str(path)
    with pytest.raises(ValueError,match='base_workflow'):h.prepare_from_ready(asset,run,cfg)
    assert not service.posts


def test_final_registry_version_check_and_post_share_mutation_fence(tmp_path,service,monkeypatch):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg)
    original_lock=library._lock;original_http=h._http;active=[]
    @contextmanager
    def observed_lock(*args,**kwargs):
        with original_lock(*args,**kwargs):
            active.append(True)
            try:yield
            finally:active.pop()
    def observed_http(config,route,value=None):
        if route=='/prompt':assert active==[True]
        return original_http(config,route,value)
    monkeypatch.setattr(library,'_lock',observed_lock);monkeypatch.setattr(h,'_http',observed_http)
    h.submit_next(run);assert len(service.posts)==1


def test_mismatched_frame_aspect_blocks_before_any_h3_plan_or_staging(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service)
    cfg.update(width=736,height=1312)
    with pytest.raises(ValueError,match='aspect_mismatch'):h.prepare_from_ready(asset,run,cfg)
    assert not run.exists() and not service.posts


def test_same_aspect_different_pixels_and_one_percent_rounding_are_allowed(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service);cfg.update(width=752,height=1008)
    assert h.prepare_from_ready(asset,run,cfg)['status']=='prepared'
    assert not service.posts


def test_64x80_frame_matching_64x80_native_canvas_is_allowed(tmp_path):
    path=tmp_path/'first.png';Image.new('RGB',(64,80),'gray').save(path)
    shot=dict(binding_sha256='0'*64,visible_cast=[],visual_prompt='An empty room.',audio=[],start=0,end=5)
    graph=h.build_graph(h.read(h.DEFAULT_BASE),shot,dict(path=str(path),sha256=h.file_sha(path)),h._timing(shot),
        'visual_h3_v3/example/shot/first.png','visual_h3_v3/example/shot',64,80)
    assert graph['condition']['inputs']['width']==64 and graph['condition']['inputs']['height']==80


@pytest.mark.parametrize('key',['service_url','input_root','output_root','gpu_lock_root','protected_pause_path'])
def test_h3_cannot_bypass_shared_native_queue_mutex_or_legacy_pause_binding(tmp_path,service,key):
    asset,run,cfg=setup(tmp_path,service)
    cfg[key]='http://127.0.0.1:19999' if key=='service_url' else str(tmp_path/('other_'+key))
    with pytest.raises(ValueError,match='share_asset_service'):h.prepare_from_ready(asset,run,cfg)
    assert not run.exists() and not service.posts


def test_automatic_dimensions_use_actual_reviewed_first_frame_and_freeze_output_size(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service);cfg.pop('width');cfg.pop('height')
    h.prepare_from_ready(asset,run,cfg);plan=h.read(run/'PLAN.json')
    with Image.open(plan['shots'][0]['first_frame']['path']) as image:expected=image.size
    assert (plan['config']['width'],plan['config']['height'])==expected
    for row in plan['shots']:
        cond=h.read(run/'shots'/row['id']/'workflow_api.json')['condition']['inputs']
        assert (cond['width'],cond['height'])==expected
    assert h.prepare_from_ready(asset,run,cfg)['status']=='prepared' and not service.posts


def test_automatic_dimensions_reject_different_first_frame_pixel_sizes(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service);cfg.pop('width');cfg.pop('height')
    ready=h.read(asset/'H3_INPUT_READY.json');frame=ready['first_frames']['shot2']
    Image.new('RGB',(192,256),'gray').save(frame['path']);frame['sha256']=h.file_sha(frame['path'])
    frame['review']['target_sha256']=frame['sha256']
    for sub in frame['review']['subreviews']:sub['target_sha256']=frame['sha256']
    write(asset/'H3_INPUT_READY.json',ready)
    state=h.read(asset/'STATE.json');state['first_frames']=ready['first_frames'];write(asset/'STATE.json',state)
    with pytest.raises(ValueError,match='equal_first_frame_sizes'):h.prepare_from_ready(asset,run,cfg)
    assert not run.exists() and not service.posts


def test_explicit_native_dimensions_must_be_a_pair(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service);cfg.pop('height')
    with pytest.raises(ValueError,match='width_height_pair'):h.prepare_from_ready(asset,run,cfg)


@pytest.mark.parametrize('response',[{},[],dict(prompt_id='../unsafe')])
def test_malformed_http_success_body_stays_unknown_without_reposting(tmp_path,service,response):
    asset,run,cfg=setup(tmp_path,service,True);h.prepare_from_ready(asset,run,cfg)
    service.response_override=response
    assert h.submit_next(run)['status']=='outcome_unknown'
    assert h.read(run/'shots/shot1/RESPONSE.json')==response
    h.submit_next(run);h.poll_collect(run);assert len(service.posts)==1


def _save_ready_frames(asset,ready):
    write(asset/'H3_INPUT_READY.json',ready)
    state=h.read(asset/'STATE.json');state['first_frames']=ready['first_frames'];write(asset/'STATE.json',state)


def test_v4_guide_is_independently_verified_readonly_without_rendering(tmp_path,service,monkeypatch):
    asset,run,cfg=setup(tmp_path,service,environment_v4=True)
    before={str(p.relative_to(asset)):h.file_sha(p) for p in asset.rglob('*') if p.is_file()}
    def forbidden(*args,**kwargs):pytest.fail('Ready verification must not create missing geometry inputs.')
    monkeypatch.setattr(pipeline,'_environment_guide',forbidden)
    monkeypatch.setattr(environment,'render_guides',forbidden)
    _,ready,_=h.validate_ready(asset)
    assert ready['first_frames']['shot1']['environment_guide']['renderer']==environment.RENDERER
    assert before=={str(p.relative_to(asset)):h.file_sha(p) for p in asset.rglob('*') if p.is_file()}
    assert h.prepare_from_ready(asset,run,cfg)['status']=='prepared' and not service.posts


@pytest.mark.parametrize('mutation',[
    lambda f:f.pop('environment_guide'),
    lambda f:f['environment_guide'].update(sha256='0'*64),
    lambda f:f['environment_guide'].update(renderer='cpu_zbuffer/old'),
    lambda f:f['environment_guide'].update(layout_sha256='0'*64),
    lambda f:f['environment_guide'].update(design_sha256='0'*64),
    lambda f:f['environment_guide'].update(view='reverse'),
    lambda f:f['environment_guide']['camera'].update(fov=65),
    lambda f:f['review'].update(layout_guide_sha256='0'*64),
    lambda f:f['review']['subreviews'][-1].update(layout_guide_sha256='0'*64),
])
def test_v4_frame_guide_and_each_review_binding_are_required(tmp_path,service,mutation):
    asset,run,cfg=setup(tmp_path,service,environment_v4=True)
    ready=h.read(asset/'H3_INPUT_READY.json');mutation(ready['first_frames']['shot1']);_save_ready_frames(asset,ready)
    with pytest.raises(h.HandoffIntegrityError,match='environment_guide'):h.prepare_from_ready(asset,run,cfg)
    assert not run.exists() and not service.posts


@pytest.mark.parametrize('case',['missing_png','changed_png','missing_manifest','changed_manifest','outside_png','outside_manifest'])
def test_v4_frame_guide_files_and_bound_directory_cannot_be_replaced_or_recreated(tmp_path,service,case):
    asset,run,cfg=setup(tmp_path,service,environment_v4=True)
    ready=h.read(asset/'H3_INPUT_READY.json');guide=ready['first_frames']['shot1']['environment_guide']
    path=Path(guide['path']);manifest=Path(guide['manifest_path'])
    if case=='missing_png':path.unlink()
    elif case=='changed_png':Image.new('RGB',(96,128),'red').save(path)
    elif case=='missing_manifest':manifest.unlink()
    elif case=='changed_manifest':
        data=h.read(manifest);data['binding']['layout']['cameras']['front']['fov']=65;write(manifest,data)
    elif case=='outside_png':
        external=tmp_path/'outside.png';shutil.copyfile(path,external);guide['path']=str(external)
    else:
        external=tmp_path/'GUIDES.json';shutil.copyfile(manifest,external);guide['manifest_path']=str(external)
    _save_ready_frames(asset,ready)
    before={str(p.relative_to(asset)):h.file_sha(p) for p in asset.rglob('*') if p.is_file()}
    with pytest.raises(h.HandoffIntegrityError,match='environment_guide'):h.validate_ready(asset)
    assert before=={str(p.relative_to(asset)):h.file_sha(p) for p in asset.rglob('*') if p.is_file()}
    if case=='missing_png':assert not path.exists()
    if case=='missing_manifest':assert not manifest.exists()
    assert not run.exists() and not service.posts


@pytest.mark.parametrize('field',['layout','camera','layout_design','front_prompt'])
def test_v4_guide_must_match_current_place_even_with_same_design_version(tmp_path,service,field):
    asset,run,cfg=setup(tmp_path,service,environment_v4=True)
    snapshot,ready,bindings=h.validate_ready(asset)
    entity=deepcopy(snapshot['plan']['packet']['places'][0])
    if field=='layout':entity['spatial_layout']['objects'][0]['center'][1]+=.1
    elif field=='camera':entity['spatial_layout']['cameras']['front']['fov']=65
    else:entity[field]+=' Changed design.'
    assert entity['design_version']=='v1'
    with pytest.raises(h.HandoffIntegrityError,match='environment_guide'):
        h._ready_environment_guide(asset,entity,bindings['shots'][0],ready['first_frames']['shot1'])
    assert not service.posts


def test_v4_cli_prepare_and_status_then_changed_guide_blocks_status_without_post(tmp_path,service):
    asset,run,cfg=setup(tmp_path,service,environment_v4=True)
    config=tmp_path/'h3_config.json';write(config,cfg)
    entry=h.PROJECT/'scripts/run_visual_h3_v3.py'
    def cli(action,*extra):
        result=subprocess.run([sys.executable,'-B',str(entry),action,'--run',str(run),*map(str,extra)],
            cwd=h.PROJECT,capture_output=True,text=True,timeout=40)
        return result,json.loads(result.stdout)
    result,value=cli('prepare','--asset-run',asset,'--config',config)
    assert result.returncode==0 and value['status']=='prepared',result.stderr+result.stdout
    result,value=cli('status');assert result.returncode==0 and value['status']=='prepared'
    guide=h.read(asset/'H3_INPUT_READY.json')['first_frames']['shot1']['environment_guide']
    Image.new('RGB',(96,128),'red').save(guide['path'])
    result,value=cli('status')
    assert result.returncode==2 and value['status']=='error' and 'environment_guide' in value['message']
    assert not service.posts and not (run/'shots/shot1/CLAIM.json').exists()
