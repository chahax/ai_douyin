"""CPU and original-ID HTTP protocol fixtures; no live model or visual review."""
from contextlib import contextmanager
import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading

from PIL import Image
import pytest

from src.content_factory import visual_image_jobs_v3 as jobs
from src.content_factory import visual_multiview_continuity_stills_v37 as scene


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@contextmanager
def server(root):
    inputs, outputs = root/'input', root/'output'; inputs.mkdir(); outputs.mkdir()
    state = dict(posts=0, graphs={}, completed=set(), unknown=False)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, value, code=200):
            body = json.dumps(value).encode(); self.send_response(code)
            self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            if self.path=='/system_stats':
                self.respond(dict(system=dict(argv=['main.py', '--input-directory', str(inputs), '--output-directory', str(outputs)])))
            elif self.path=='/queue':
                self.respond(dict(queue_running=[[0,p,g] for p,g in state['graphs'].items() if p not in state['completed']], queue_pending=[]))
            elif self.path.startswith('/history/'):
                pid = self.path.rsplit('/',1)[1]
                if pid not in state['completed']:
                    self.respond({}); return
                graph = state['graphs'][pid]; images = {}
                shape = next(n['inputs'] for n in graph.values() if n['class_type']=='EmptyFlux2LatentImage')
                for nid,node in graph.items():
                    if node['class_type']=='SaveImage':
                        prefix=Path(node['inputs']['filename_prefix']);target=outputs/prefix.parent/(prefix.name+'_00001_.png')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        if not target.exists():
                            Image.new('RGB',(shape['width'],shape['height']),'navy').save(target)
                        images[nid]=dict(images=[dict(filename=target.name,subfolder=prefix.parent.as_posix(),type='output')])
                self.respond({pid:dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'),outputs=images)})
            else:
                self.respond({},404)
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));state['posts']+=1
            if state['unknown']:
                self.respond(dict(error='result_unknown'),500);return
            pid='fixture-original-image-'+str(state['posts']);state['graphs'][pid]=request['prompt']
            self.respond(dict(prompt_id=pid))
    httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    state.update(url=f'http://127.0.0.1:{httpd.server_port}',input_root=inputs,output_root=outputs)
    try:
        yield state
    finally:
        httpd.shutdown();httpd.server_close();thread.join(timeout=5)


def prepared(root, fake):
    video_run=root/'fresh_video_run';video_run.mkdir()
    mother=root/'mother.png';Image.new('RGB',(64,96),'gray').save(mother)
    mother_result=root/'MOTHER_FIXTURE_RESULT.json'
    write(mother_result,dict(technical_status='saved',prompt_id='fixture-saved-mother',
                             images=[dict(path=str(mother),sha256=jobs.file_sha(mother))]))
    assets=root/'assets';assets.mkdir();entries=[]
    for i,entity in enumerate(scene.CAST):
        for k,view in enumerate(('front','left_oblique','right_oblique')):
            file=assets/(entity+'_'+view+'_v1.png');Image.new('RGB',(64,96),(i*60,k*70,50)).save(file)
            entry=dict(book_id='fixture-book',entity_id=entity,kind='character',view=view,design_version='v1',
                       version=1,identity_group='fixture_identity_'+entity,asset_id=entity+'_'+view,
                       file=file.name,sha256=jobs.file_sha(file),production_approved=False)
            write(file.with_suffix('.json'),entry);entries.append(entry)
    index=assets/'INDEX.json';write(index,dict(assets=entries))
    pause=root/'OLD_PAUSE.json';write(pause,dict(keep=True))
    config=video_run/'IMAGE_CONFIG.json'
    write(config,dict(service_url=fake['url'],input_root=str(fake['input_root']),output_root=str(fake['output_root']),
                      protected_pause_path=str(pause),verify_service_paths=True))
    auth=video_run/'USER_AUTHORIZATION.json'
    write(auth,dict(semantic_generation_gates=False,review_policy='user_reviews_completed_film',engineering_limits=dict(image_submissions=8)))
    case=root/'source_case.json';write(case,dict(explicit_fixture=True))
    spec=scene.make_spec(mother,index,config,auth,case,video_run,mother_native_result=mother_result,width=64,height=96)
    specpath=video_run/'SCENE_IMAGE_SPEC.json';write(specpath,spec)
    run=video_run/'scene';scene.prepare(specpath,run)
    return run,specpath,video_run,pause


def save_scene(fake, run, sid):
    submitted=scene.submit_next(run)
    row=next(r for r in submitted['shots'] if r['id']==sid)
    assert row['prompt_id'];fake['completed'].add(row['prompt_id'])
    scene.collect_known(run)
    return scene.result(run,sid)


def prior_fixture(run, video_run, sid):
    """Explicit protocol fixture with real PNGs and labelled non-media AV bytes."""
    previous=scene.result(run,sid);folder=video_run/'shots'/sid;artifacts=folder/'artifacts';artifacts.mkdir(parents=True)
    originals={}
    for name in ('video','audio','first','last'):
        path=artifacts/(name+('.png' if name in ('first','last') else '.fixture'))
        if name in ('first','last'):
            Image.new('RGB',(64,96),'olive' if name=='last' else 'navy').save(path)
        else:
            path.write_bytes(('EXPLICIT CPU PROTOCOL FIXTURE, NOT MODEL '+name).encode())
        originals[name]=scene.bind(path)
    pid='fixture-native-video-'+sid;graph={'fixture':dict(class_type='ProtocolFixture',inputs={})}
    write(folder/'workflow_api.json',graph)
    write(folder/'STATE.json',dict(id=sid,status='technical_saved',prompt_id=pid))
    write(folder/'HISTORY.json',{pid:dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'))})
    value=dict(schema='visual_h3_handoff/v3',shot_id=sid,prompt_id=pid,technical_status='technical_saved',
               graph_sha256=jobs.digest(graph),first_frame_sha256=previous['image']['sha256'],files=originals,
               timing=dict(native_frames=362),native_metadata=dict(streams=[dict(codec_type='video',width=64,height=96)]))
    write(folder/'RESULT.json',value)
    return scene.bind(folder/'RESULT.json')


def test_cpu_prepare_waits_for_real_prior_and_s01_has_seven_pixel_references(tmp_path):
    with server(tmp_path) as fake:
        run,specpath,video_run,pause=prepared(tmp_path,fake)
        assert [r['status'] for r in scene.status(run)['shots']]==['unprepared']*4
        before=pause.read_bytes();scene.prepare_shot(run,'S01')
        assert [r['status'] for r in scene.status(run)['shots']]==['prepared','unprepared','unprepared','unprepared']
        shot=jobs._read(run/'prepared/S01/SHOT_PLAN.json')
        assert shot['positive_reference_evidence']['reference_count']==7
        assert [r['role'] for r in shot['inputs']]==['room_mother','su_mo_front','ye_nan_front','ye_xijue_front','su_mo_angle','ye_nan_angle','ye_xijue_angle']
        assert all(r['identity']['view']!='front' for r in shot['identity_references'][3:])
        assert fake['posts']==0 and pause.read_bytes()==before
        with pytest.raises(jobs.JobIntegrityError,match='actual_same_run'):
            scene.prepare_shot(run,'S02')


def test_saved_current_tail_and_current_s01_are_actual_first_two_positive_inputs(tmp_path):
    with server(tmp_path) as fake:
        run,_,video_run,_=prepared(tmp_path,fake)
        scene.prepare_shot(run,'S01');first=save_scene(fake,run,'S01');prior=prior_fixture(run,video_run,'S01')
        scene.prepare_shot(run,'S02',prior)
        shot=jobs._read(run/'prepared/S02/SHOT_PLAN.json')
        assert shot['positive_reference_evidence']['reference_count']==8
        assert shot['positive_reference_evidence']['actual_tail_in_positive_chain'] is True
        tail=jobs._read(prior['path'])['files']['last']
        assert shot['inputs'][0]['original_source']==tail
        assert shot['inputs'][1]['original_source']=={k:first['image'][k] for k in ('path','sha256')}
        assert shot['inputs'][1]['role']=='current_run_S01_scene'
        assert shot['room_context']['native_id']==first['native_id']
        assert jobs.file_sha(shot['inputs'][0]['path'])==tail['sha256']
        assert scene.prepare_shot(run,'S02',prior)['shots'][1]['status']=='prepared'
        assert fake['posts']==1


@pytest.mark.parametrize('fault',['old_run','unknown','missing_original','last_sha','last_geometry','history','wrong_first','wrong_video_geometry'])
def test_prior_protocol_scope_originals_and_actual_tail_are_required(tmp_path,fault):
    with server(tmp_path) as fake:
        run,_,video_run,_=prepared(tmp_path,fake);scene.prepare_shot(run,'S01');save_scene(fake,run,'S01')
        prior=prior_fixture(run,video_run,'S01');folder=Path(prior['path']).parent
        value=jobs._read(prior['path'])
        if fault=='old_run':
            other=tmp_path/'old_video_run/shots/S01/RESULT.json';write(other,value);prior=scene.bind(other)
        elif fault=='unknown':
            state=jobs._read(folder/'STATE.json');state['status']='outcome_unknown';write(folder/'STATE.json',state)
        elif fault=='missing_original':
            Path(value['files']['audio']['path']).unlink()
        elif fault=='last_sha':
            Path(value['files']['last']['path']).write_bytes(b'changed native tail')
        elif fault=='last_geometry':
            path=Path(value['files']['last']['path']);Image.new('RGB',(80,96),'gray').save(path)
            value['files']['last']=scene.bind(path);write(folder/'RESULT.json',value);prior=scene.bind(folder/'RESULT.json')
        elif fault=='history':
            history=jobs._read(folder/'HISTORY.json');history[value['prompt_id']]['status']['completed']=False;write(folder/'HISTORY.json',history)
        elif fault=='wrong_first':
            value['first_frame_sha256']='0'*64;write(folder/'RESULT.json',value);prior=scene.bind(folder/'RESULT.json')
        elif fault=='wrong_video_geometry':
            value['native_metadata']['streams'][0]['width']=80;write(folder/'RESULT.json',value);prior=scene.bind(folder/'RESULT.json')
        with pytest.raises((jobs.JobIntegrityError,FileNotFoundError)):
            scene.prepare_shot(run,'S02',prior)
        assert fake['posts']==1 and not (run/'jobs/S02/CLAIM.json').exists()


@pytest.mark.parametrize('fault',['identity_group','design_version','version','front_as_angle'])
def test_multiview_identity_pairing_not_merely_matching_names(tmp_path,fault):
    with server(tmp_path) as fake:
        run,specpath,_,_=prepared(tmp_path,fake);spec=jobs._read(specpath)
        if fault=='front_as_angle':
            spec['shots'][0]['angle_views']['su_mo']='front'
        else:
            spec['assets']['su_mo__right_oblique']['identity'][fault]='wrong'
        other=specpath.with_name('bad_spec.json');write(other,spec)
        with pytest.raises((jobs.JobIntegrityError,ValueError)):
            scene.prepare(other,run.parent/'bad_scene')
        assert fake['posts']==0


@pytest.mark.parametrize('fault',['disconnected_tail','negative_only','swapped_angles','mother_first','missing_angle'])
def test_reference_graph_rejects_provenance_only_tail_or_angle_slots(tmp_path,fault):
    with server(tmp_path) as fake:
        run,_,video_run,_=prepared(tmp_path,fake);scene.prepare_shot(run,'S01');save_scene(fake,run,'S01')
        prior=prior_fixture(run,video_run,'S01');scene.prepare_shot(run,'S02',prior)
        shot=jobs._read(run/'prepared/S02/SHOT_PLAN.json');graph=jobs._read(shot['graph']['path'])
        if fault=='disconnected_tail':graph['S02__positive_ref_1']['inputs']['conditioning']=['S02__positive',0]
        elif fault=='negative_only':graph['S02__guider']['inputs']['positive']=['S02__positive',0]
        elif fault=='swapped_angles':
            a=graph['S02__image_5']['inputs'];b=graph['S02__image_6']['inputs'];a['image'],b['image']=b['image'],a['image']
        elif fault=='mother_first':
            a=graph['S02__image_0']['inputs'];b=graph['S02__image_1']['inputs'];a['image'],b['image']=b['image'],a['image']
        else:graph['S02__positive_ref_7']['inputs']['conditioning']=['S02__positive_ref_5',0]
        with pytest.raises(jobs.JobIntegrityError,match='positive_multiview_tail'):
            scene.reference_graph_evidence(graph,'S02',shot['inputs'])
        assert fake['posts']==1


def test_known_collection_survives_external_source_and_prior_change_but_new_dispatch_stops(tmp_path):
    with server(tmp_path) as fake:
        run,specpath,video_run,pause=prepared(tmp_path,fake);scene.prepare_shot(run,'S01');save_scene(fake,run,'S01')
        prior=prior_fixture(run,video_run,'S01');scene.prepare_shot(run,'S02',prior);posted=scene.submit_next(run)
        pid=posted['shots'][1]['prompt_id'];assert pid
        Path(jobs._read(prior['path'])['files']['last']['path']).write_bytes(b'changed external tail after POST')
        spec=jobs._read(specpath);Path(spec['authorization']['path']).write_text('changed')
        specpath.write_text('changed')
        fake['completed'].add(pid);saved=scene.collect_known(run)
        assert saved['shots'][1]['status']=='saved' and scene.result(run,'S02')['native_id']==pid
        assert fake['posts']==2 and jobs._read(pause)==dict(keep=True)
        assert scene.submit_next(run)['dispatch']=='waiting_preparation_original_or_terminal_job'


def test_outcome_unknown_is_never_replayed_or_used_to_prepare_later_shot(tmp_path):
    with server(tmp_path) as fake:
        run,_,_,_=prepared(tmp_path,fake);scene.prepare_shot(run,'S01');fake['unknown']=True
        assert scene.submit_next(run)['shots'][0]['status']=='outcome_unknown'
        scene.submit_next(run);scene.collect_known(run)
        assert fake['posts']==1 and scene.budget(run)['outcome_unknown']==1
        with pytest.raises(jobs.JobIntegrityError):scene.prepare_shot(run,'S02')


def test_new_dispatch_refuses_mutated_original_tail_while_snapshot_unchanged(tmp_path):
    with server(tmp_path) as fake:
        run,_,video_run,_=prepared(tmp_path,fake);scene.prepare_shot(run,'S01');save_scene(fake,run,'S01')
        prior=prior_fixture(run,video_run,'S01');scene.prepare_shot(run,'S02',prior)
        Path(jobs._read(prior['path'])['files']['last']['path']).write_bytes(b'changed before new POST')
        with pytest.raises(jobs.JobIntegrityError):scene.submit_next(run)
        assert fake['posts']==1


def test_real_subprocess_http_four_sequential_anchor_tail_protocol(tmp_path):
    """Real subprocess/HTTP/native-PNG IO; prior video documents are explicit fixtures."""
    with server(tmp_path) as fake:
        run,specpath,video_run,pause=prepared(tmp_path,fake);before=pause.read_bytes()
        script=Path(__file__).resolve().parents[1]/'scripts/run_multiview_continuity_stills_v37.py'
        def cli(action,*extra):
            proc=subprocess.run([sys.executable,str(script),action,'--run',str(run),*extra],
                                capture_output=True,text=True,encoding='utf-8',timeout=30)
            assert proc.returncode==0,proc.stderr
            return json.loads(proc.stdout)
        prior=None
        for index,sid in enumerate(scene.SHOTS,1):
            args=['--shot',sid]
            if prior:args+=['--prior-video-result',prior['path']]
            cli('prepare-shot',*args)
            value=cli('submit-next');pid=value['shots'][index-1]['prompt_id']
            assert pid and fake['posts']==index
            cli('submit-next');assert fake['posts']==index
            fake['completed'].add(pid);assert cli('collect-known')['shots'][index-1]['status']=='saved'
            receipt=scene.result(run,sid)
            assert receipt['positive_reference_evidence']['reference_count']==(7 if index==1 else 8)
            assert receipt['production_approved'] is False and receipt['user_review_pending'] is True
            if index<4:prior=prior_fixture(run,video_run,sid)
        assert cli('status')['complete'] is True and scene.complete(run)
        assert cli('budget')['claimed']==4 and fake['posts']==4
        assert pause.read_bytes()==before
