"""Real local HTTP/staging/CPU-AV black boxes; no production Comfy service."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import http.server,importlib.util,json,shutil,threading
from PIL import Image
import pytest
from src.content_factory import visual_h3_scene_performance_minute_v36 as f

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return f.bind(path)

class SceneFixture:
    """Test-only producer runs real native image jobs behind the HTTP fixture."""
    __file__=__file__
    def prepare(self,spec_path,run,authorization=None):
        spec=f.read(spec_path);run=Path(run);run.mkdir(parents=True,exist_ok=True)
        authorization=authorization or f.bind(run.parent/'USER_AUTHORIZATION.json')
        f.freeze(run/'PLAN.json',dict(config=spec['config'],authorization=authorization,items=spec['items']))
        for item in spec['items']:
            sid=item['id'];scope='scene_fixture/'+sid;name=scope+'/ref.png';cfg=deepcopy(spec['config']);cfg['allowed_prefix']='scene_fixture'
            graph=f.jobs.build_graph([dict(id=sid,prompt='Photographic scene fixture',seed=12,references=[dict(input_name=name)])],scope,width=736,height=1312,steps=4)
            f.jobs.prepare_job(run/sid,graph,cfg,[dict(input_name=name,**item['image'])],job_id=sid)
    def status(self,run):
        return dict(shots=[dict(f.jobs.status(Path(run)/sid),id=sid,job_dir=str(Path(run)/sid)) for sid in f.IDS])
    def complete(self,run):return all(s['status']=='saved' for s in self.status(run)['shots'])
    def collect_known(self,run):
        for sid in f.IDS:
            job=Path(run)/sid;s=f.jobs.status(job)
            if s.get('prompt_id') and s['status'] not in ('saved','failed','interrupted','rejected','cancelled'):
                s=f.jobs.poll(job)
                if s['status']=='native_complete':f.jobs.collect(job)
    def submit_next(self,run):
        for row in self.status(run)['shots']:
            if row['status']=='saved':continue
            if row['status']=='prepared':f.jobs.submit(Path(run)/row['id'])
            return self.status(run)
    def result(self,run,sid):
        job=Path(run)/sid;value=f.read(job/'RESULT.json');image=value['images'][0]
        return dict(technical_status='saved',native_id=value['prompt_id'],native_result=f.bind(job/'RESULT.json'),image={k:image[k] for k in ('path','sha256')})

class Server:
    def __init__(self,root):
        self.root=root;self.inputs=root/'input';self.outputs=root/'output';self.inputs.mkdir();self.outputs.mkdir()
        self.posts=[];self.histories={};self.graphs={};self.drop=False;self.foreign_busy=False
    def queue(self):
        rows=[[i,pid,g] for i,(pid,g) in enumerate(self.graphs.items()) if pid not in self.histories]
        if self.foreign_busy:rows.append([999,'unrelated_native',{}])
        return dict(queue_running=rows,queue_pending=[])
    def finish_image(self,pid,color='blue'):
        graph=self.graphs[pid];outputs={}
        for nid,node in graph.items():
            if node['class_type']=='SaveImage':
                rel=Path(node['inputs']['filename_prefix']+'_00001_.png');p=self.outputs/rel;p.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(736,1312),color).save(p)
                outputs[nid]=dict(images=[dict(filename=p.name,subfolder=rel.parent.as_posix(),type='output')])
        self.histories[pid]=dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success',messages=[['execution_success',{}]]),outputs=outputs)
    def finish_video(self,pid,sid,media):
        graph=self.graphs[pid];outputs={}
        for role,key,ext,source in [('video','images','mp4',sid+'.mp4'),('audio','audio','flac','audio.flac'),('first','images','png',sid+'.png'),('last','images','png',sid+'.png')]:
            rel=Path(graph['save_'+role]['inputs']['filename_prefix']+'_00001_.'+ext);p=self.outputs/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(media/source,p)
            outputs['save_'+role]={key:[dict(filename=p.name,subfolder=rel.parent.as_posix(),type='output')]}
        self.histories[pid]=dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success',messages=[['execution_success',{}]]),outputs=outputs)

@contextmanager
def server(root):
    fixture=Server(root)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value):
            data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/system_stats':return self.reply(dict(system=dict(argv=['main.py','--input-directory',str(fixture.inputs),'--output-directory',str(fixture.outputs)])))
            if self.path=='/queue':return self.reply(fixture.queue())
            if self.path.startswith('/history/'):
                pid=self.path.rsplit('/',1)[1];return self.reply({pid:fixture.histories[pid]} if pid in fixture.histories else {})
            self.reply({})
        def do_POST(self):
            assert self.path=='/prompt';body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));fixture.posts.append(body);pid='http_native_'+str(len(fixture.posts));fixture.graphs[pid]=body['prompt']
            if fixture.drop:self.close_connection=True;return
            self.reply(dict(prompt_id=pid,node_errors={}))
    host=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
    try:yield fixture,'http://127.0.0.1:'+str(host.server_port)
    finally:host.shutdown();host.server_close();thread.join(timeout=5)

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    with server(tmp_path) as (service,url):
        monkeypatch.setattr(f,'RUN',tmp_path/'minute');monkeypatch.setattr(f,'FRAMES',124);monkeypatch.setattr(f,'SECONDS',5);monkeypatch.setattr(f,'QUOTE_COUNT',4)
        monkeypatch.setattr(f,'LOCAL_SERVICE',url);monkeypatch.setattr(f,'SHARED_GPU',tmp_path/'gpu');monkeypatch.setattr(f,'PROMPT_MODULE',Path(__file__))
        scene=SceneFixture();monkeypatch.setattr(f,'_scene',lambda:scene);run=f.RUN;run.mkdir();pause=tmp_path/'old_pause.json';pause.write_text('original-pause')
        cfg=dict(service_url=url,input_root=str(service.inputs),output_root=str(service.outputs),timeout=3,protected_pause_path=str(pause),gpu_lock_root=str(f.SHARED_GPU),video_enabled=True)
        base=tmp_path/'base.json';shutil.copyfile(f.native.DEFAULT_BASE,base);cfg['base_workflow']=str(base)
        image_cfg={k:cfg[k] for k in ('service_url','input_root','output_root','timeout','protected_pause_path')};items=[];rows=[]
        for index,sid in enumerate(f.IDS):
            image=tmp_path/(sid+'.png');Image.new('RGB',(736,1312),['gray','blue','green','red'][index]).save(image);items.append(dict(id=sid,image=f.bind(image)))
            source=tmp_path/(sid+'.source.txt');source.write_text('0—5秒，父亲轻声说：“第'+str(index+1)+'句”。',encoding='utf-8')
            prompt=tmp_path/(sid+'.prompt.txt');prompt.write_bytes(source.read_bytes());rows.append(dict(id=sid,source=f.bind(source),prompt=f.bind(prompt),audio=[]))
        prompt_plan=write(tmp_path/'prompt_plan.json',dict(schema='h3_scene_performance_prompts/v36',segments=rows))
        scene_spec=write(tmp_path/'scene_spec.json',dict(config=image_cfg,items=items))
        write(run/'MINUTE_SPEC.json',dict(schema='h3_scene_performance_minute_spec/v36',prompt_plan=prompt_plan,scene_spec=scene_spec,h3_config=cfg))
        write(run/'USER_AUTHORIZATION.json',dict(schema='h3_scene_performance_minute_authorization/v36',user_statement='Controlled test delegates content review to user',engineering_scope_not_user_quoted_numeric_limit=True,
            engineering_limits=dict(image_submissions=8,video_submissions=4,cloud_media=0),text_model_calls=0,publication=False,unknown_native_replay=False,
            semantic_video_retakes=False,review_policy='user_reviews_completed_film',semantic_generation_gates=False))
        f.prepare(run)
        yield run,service,scene

def launch(run):
    acceptance=f.PROJECT/'data/qa/h3_scene_performance_v36_20261109/CPU_TEST_FIXTURE.json';write(acceptance,dict(fixture_only=True))
    write(run/'LAUNCH_APPROVAL.json',dict(schema='h3_scene_performance_technical_launch/v36',plan=f.bind(run/'PLAN.json'),authorization=f.bind(run/'USER_AUTHORIZATION.json'),
        execution_sources=f._sources(),cpu_acceptance=f.bind(acceptance),approved_for_technical_execution=True,review_policy='user_reviews_completed_film'))

def images(prepared):
    run,service,scene=prepared;launch(run)
    for sid in f.IDS:
        f.tick(run,stage='images',allow_submit=True);pid=f.jobs.status(run/'scene'/sid)['prompt_id'];service.finish_image(pid);f.collect_known(run)
    return run,service,scene

@pytest.fixture(scope='module')
def media(tmp_path_factory):
    path=Path(__file__).with_name('test_visual_h3_continuity_minute_v34.py');spec=importlib.util.spec_from_file_location('v36_media_fixture',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m.media.__wrapped__(tmp_path_factory)

def test_prepare_has_no_semantic_review_files_or_posts_and_cannot_run_unauthorized(prepared):
    run,service,_=prepared;assert not service.posts and not list(run.rglob('ROOT_*REVIEW*'))
    assert f.status(run)['content_status']=='user_review_pending'
    assert f.tick(run,stage='images',allow_submit=False)['technical_saved']==0
    assert f.tick(run,stage='images',allow_submit=True)['dispatch']=='blocked_current_inputs' and not service.posts

def test_http_eight_posts_real_staging_native_receipts_four_cpu_videos_and_clock(prepared,media):
    run,service,scene=images(prepared)
    assert len(service.posts)==4 and f.tick(run,stage='images',allow_submit=True)['dispatch']=='images_complete_cold_family_transition_by_owner'
    assert len(service.posts)==4 and scene.complete(run/'scene')
    for index,sid in enumerate(f.IDS):
        f.tick(run,stage='videos',allow_submit=True);state=f.status(run)['shots'][index];pid=state['prompt_id'];folder=run/'shots'/sid
        assert len(service.posts)==5+index and state['status']=='submitted'
        row=f.read(folder/'GRAPH_BINDING.json');graph=f.read(folder/'workflow_api.json')
        assert graph['condition']['inputs']['prompt']==f.check(f.read(run/'PLAN.json')['segments'][index]['prompt']).read_bytes().decode()
        assert 'last_frame' not in graph['condition']['inputs'] and 'ref_images' not in graph['condition']['inputs']
        assert f.bind(Path(f.read(run/'PLAN.json')['config']['input_root'])/row['input_name'])['sha256']==row['first_frame']['sha256']
        if index:assert row['previous_tail']['native_id']==f.read(run/'shots'/f.IDS[index-1]/'RESULT.json')['prompt_id']
        service.finish_video(pid,sid,media);f.collect_known(run)
    final=f.tick(run,stage='videos',allow_submit=True)
    assert final['clock']['native_frames']==496 and final['clock']['audio_samples']==496*2000
    assert final['content_status']=='user_review_pending' and final['subtitle_postproduction_enabled'] is False and final['burned_text_absence_verified'] is False
    assert len(service.posts)==8 and len(set(final['native_ids']))==4 and not list(run.rglob('ROOT_*REVIEW*'))
    assert f.assemble(run)==final

def test_known_video_collects_after_authority_or_prompt_changed_and_pause(prepared,media):
    run,service,_=images(prepared);f.tick(run,stage='videos',allow_submit=True);pid=f.status(run)['shots'][0]['prompt_id'];folder=run/'shots/S01'
    original=[f.bind(folder/n) for n in ('workflow_api.json','REQUEST.json','CLAIM.json','RESPONSE.json')]
    Path(f.read(run/'PLAN.json')['segments'][0]['prompt']['path']).write_text('Changed after POST',encoding='utf-8');write(run/'PAUSE.json',dict(reason='fixture'))
    (run/'USER_AUTHORIZATION.json').write_text('invalid current authorization',encoding='utf-8');service.finish_video(pid,'S01',media)
    value=f.tick(run,stage='videos',allow_submit=True)
    assert value['technical_saved']==1 and value['dispatch']=='paused' and len(service.posts)==5
    assert [f.bind(x['path']) for x in original]==original and f.read(folder/'RESULT.json')['prompt_id']==pid

def test_unknown_http_accepted_response_loss_never_reposts(prepared):
    run,service,_=images(prepared);service.drop=True;f.tick(run,stage='videos',allow_submit=True)
    assert f.status(run)['shots'][0]['status']=='outcome_unknown' and len(service.posts)==5
    assert f.tick(run,stage='videos',allow_submit=True)['dispatch']=='unknown_or_failed_native_preserved' and len(service.posts)==5

def test_wrong_history_graph_rejected_without_new_post(prepared,media):
    run,service,_=images(prepared);f.tick(run,stage='videos',allow_submit=True);pid=f.status(run)['shots'][0]['prompt_id'];service.finish_video(pid,'S01',media)
    service.histories[pid]['prompt'][2]={}
    with pytest.raises(ValueError):f.collect_known(run)
    assert len(service.posts)==5 and not (run/'shots/S01/RESULT.json').exists()

def test_video_stage_does_not_implicitly_warm_switch_or_make_images(prepared):
    run,service,_=prepared;launch(run)
    assert f.tick(run,stage='videos',allow_submit=True)['dispatch']=='four_saved_scene_images_required' and not service.posts

def test_single_execute_lock_stops_duplicate_dispatch(prepared):
    run,service,_=prepared;launch(run)
    with f.jobs.run_lock(run,'RUNNER.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.execute(run,stage='images',max_seconds=1,poll_seconds=1)
    assert not service.posts

@pytest.mark.parametrize('replacement',['无对白','“替换原句”','“第1句”“第1句”'])
def test_quote_contract_rejects_missing_changed_or_duplicated_quote_even_with_rebound_files(prepared,replacement):
    run,_,_=prepared;spec=f.read(run/'MINUTE_SPEC.json');plan_path=Path(spec['prompt_plan']['path']);plan=f.read(plan_path)
    path=Path(plan['segments'][0]['prompt']['path']);path.write_text(replacement,encoding='utf-8');plan['segments'][0]['prompt']=f.bind(path)
    write(plan_path,plan)
    with pytest.raises(ValueError,match='quotes_changed'):f._prompts(f.bind(plan_path))

def test_image_http_response_unknown_is_not_replayed(prepared):
    run,service,_=prepared;launch(run);service.drop=True;f.tick(run,stage='images',allow_submit=True)
    assert len(service.posts)==1
    assert f.tick(run,stage='images',allow_submit=True)['dispatch']=='unknown_or_failed_native_preserved' and len(service.posts)==1

def test_shared_global_gpu_lock_protects_image_dispatch(prepared):
    run,service,_=prepared;launch(run);f.SHARED_GPU.mkdir(parents=True,exist_ok=True)
    with f.jobs.run_lock(f.SHARED_GPU,'GPU.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.tick(run,stage='images',allow_submit=True)
    assert not service.posts

def test_conflicting_staged_first_pixels_rejected_before_video_claim(prepared):
    run,service,_=images(prepared);p=f.read(run/'PLAN.json');target=Path(p['config']['input_root'])/run.name/'S01/first_input.png'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'conflicting bytes')
    with pytest.raises(ValueError):f.tick(run,stage='videos',allow_submit=True)
    assert len(service.posts)==4 and target.read_bytes()==b'conflicting bytes' and not (run/'shots/S01/CLAIM.json').exists()

def test_actual_scene_producer_receipts_enter_native_i2v_without_semantic_review(prepared,tmp_path,monkeypatch,media):
    from src.content_factory import visual_scene_performance_stills_v36 as scene
    prior,service,_=prepared;run=tmp_path/'actual_scene_minute';run.mkdir();monkeypatch.setattr(f,'RUN',run);monkeypatch.setattr(f,'_scene',lambda:scene)
    old=f.read(prior/'MINUTE_SPEC.json');cfg=old['h3_config'];authority=f.read(prior/'USER_AUTHORIZATION.json');write(run/'USER_AUTHORIZATION.json',authority)
    refs=f.read(f.check(old['scene_spec']))['items'];mother=refs[0]['image'];mother_result=write(tmp_path/'mother_fixture.json',dict(technical_status='saved',prompt_id='cpu_mother',images=[mother]))
    image_cfg=write(tmp_path/'real_image_config.json',{k:cfg[k] for k in ('service_url','input_root','output_root','timeout','protected_pause_path')})
    source_case=write(tmp_path/'real_scene_source_fixture.json',dict(controlled_fixture=True))
    sp=scene.make_spec(mother['path'],{cid:refs[i+1]['image']['path'] for i,cid in enumerate(scene.CAST)},image_cfg['path'],run/'USER_AUTHORIZATION.json',source_case['path'],mother_native_result=mother_result['path'])
    scene_spec=write(run/'SCENE_IMAGE_SPEC.json',sp);write(run/'MINUTE_SPEC.json',dict(old,scene_spec=scene_spec));f.prepare(run);launch(run)
    for index,sid in enumerate(f.IDS):
        f.tick(run,stage='images',allow_submit=True);pid=f.status(run)['images']['shots'][index]['prompt_id'];service.finish_image(pid);f.collect_known(run)
    assert scene.complete(run/'scene') and len(service.posts)==4
    f.tick(run,stage='videos',allow_submit=True);pid=f.status(run)['shots'][0]['prompt_id'];row=f.read(run/'shots/S01/GRAPH_BINDING.json')
    receipt=scene.result(run/'scene','S01')
    assert row['scene_result']['native_result']==receipt['native_result'] and row['first_frame']['sha256']==receipt['image']['sha256']
    assert all(len(s['reference_graph_evidence']['references'])==4 for s in f.read(run/'scene/PLAN.json')['shots'])
    service.finish_video(pid,'S01',media);f.collect_known(run)
    assert f.status(run)['technical_saved']==1 and len(service.posts)==5 and not list(run.rglob('ROOT_*REVIEW*'))

@pytest.mark.parametrize('target',['prompt','authorization','base','source'])
def test_changed_current_inputs_stop_before_real_http_post(prepared,target):
    run,service,_=prepared;launch(run);p=f.read(run/'PLAN.json')
    path=p['segments'][0][target]['path'] if target in ('prompt','source') else run/'USER_AUTHORIZATION.json' if target=='authorization' else p['base_workflow']['path']
    Path(path).write_text('Changed bound input',encoding='utf-8')
    assert f.tick(run,stage='images',allow_submit=True)['dispatch']=='blocked_current_inputs' and not service.posts
