"""Pipeline protocol tests with temporary loopback Comfy; no GPU/VLM quality claim."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import threading

from PIL import Image
import pytest

from src.content_factory import visual_asset_pipeline_v3 as f
from src.content_factory import visual_asset_registry_v3 as assets


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeComfy:
    """Real HTTP transport, known prompt IDs, native graph receipts and output files."""
    def __init__(self,root):
        self.input=root/'native_input';self.output=root/'native_output'
        self.input.mkdir();self.output.mkdir()
        self.posts=[];self.current=None;self.histories={};self.auto_complete=False;self.drop_post_response=False;self.queue_response=None
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,value):
                raw=json.dumps(value).encode();self.send_response(200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                if self.path=='/queue':
                    if owner.queue_response is not None:self.reply(owner.queue_response);return
                    row=[] if owner.current is None else [[0,owner.current,owner.posts[-1]['prompt']]]
                    self.reply(dict(queue_running=row,queue_pending=[]))
                elif self.path=='/system_stats':
                    self.reply({'system':{'argv':['main.py','--input-directory',str(owner.input),'--output-directory',str(owner.output)]}})
                elif self.path.startswith('/history/'):
                    pid=self.path.rsplit('/',1)[1];self.reply({pid:owner.histories[pid]} if pid in owner.histories else {})
                else:self.send_error(404)
            def do_POST(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
                if self.path!='/prompt':self.send_error(404);return
                owner.posts.append(json.loads(raw));pid='native_'+str(len(owner.posts));owner.current=pid
                if owner.auto_complete:owner.complete()
                if owner.drop_post_response:
                    self.connection.shutdown(2);self.connection.close();return
                self.reply(dict(prompt_id=pid,node_errors={}))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def complete(self):
        pid=self.current;assert pid
        graph=self.posts[-1]['prompt'];outputs={}
        for nid,node in graph.items():
            if node['class_type']!='SaveImage':continue
            prefix=Path(node['inputs']['filename_prefix']);folder=self.output/prefix.parent;folder.mkdir(parents=True,exist_ok=True)
            image=folder/(prefix.name+'_00001_.png');Image.new('RGB',(64,80),(len(self.posts)*30%255,70,110)).save(image)
            outputs[nid]={'images':[dict(filename=image.name,subfolder=prefix.parent.as_posix(),type='output')]}
        self.histories[pid]=dict(prompt=[0,'test_client',graph],status=dict(completed=True,status_str='success',messages=[['execution_success',{}]]),outputs=outputs)
        self.current=None
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)


@pytest.fixture
def service(tmp_path):
    s=FakeComfy(tmp_path)
    try:yield s
    finally:s.close()


def setup(tmp_path,service,*,views=('front',),shots=False):
    source=tmp_path/'SCRIPT.md';source.write_text('The actor waits in the room.',encoding='utf-8')
    pause=tmp_path/'legacy_PAUSE.json';write(pause,dict(original='keep paused'))
    packet=dict(schema='visual_asset_packet/v3',book_id='book1',source=dict(path=str(source),sha256=sha(source)),
        characters=[dict(id='actor',design_version='v1',required_views=list(views),age_band='child',
            front_prompt='A fictional child in gray clothing, neutral front view.',
            view_prompts=dict(left_oblique='Same child, left three-quarter view.'),appearance_design='gray shirt')],
        places=[],shots=[])
    if shots:
        packet['places']=[dict(id='room',design_version='v1',required_views=['front'],appearance_design='one old wooden table')]
        packet['shots']=[dict(id='shot1',scene_id='scene1',place_id='room',visible_cast=['actor'],
            character_views={'actor':'front'},visual_prompt='The child waits by the table.',audio=[])]
    config=dict(library=str(tmp_path/'library'),gpu_lock_root=str(tmp_path/'gpu_lock'),protected_pause_path=str(pause),
        image_service=dict(service_url=service.url,input_root=str(service.input),output_root=str(service.output),
                           allowed_prefix='qa_visual_assets',protected_pause_path=str(pause),timeout=3),
        visual_review=dict(provider='ollama',endpoint=service.url,model='qa_protocol_fake',timeout=1),max_repair_rounds=2)
    run=tmp_path/'run';f.prepare(run,packet,config)
    return run,packet,config


def register_candidate(tmp_path,config,*,entity='actor',kind='character',color='gray'):
    image=tmp_path/(entity+'_'+color+'.png');Image.new('RGB',(64,80),color).save(image)
    return assets.register(config['library'],image,book_id='book1',entity_id=entity,kind=kind,view='front',design_version='v1')


class FakeReviewer:
    """Injected deterministic protocol reviewer, explicitly not a semantic evaluator."""
    def __init__(self,decision='accepted',*,retryable=False,completion_known=True):
        self.decision=decision;self.retryable=retryable;self.completion_known=completion_known
        self.calls=[];self.compositions=[];self.directories=[]
    def result(self,path,kind='character'):
        return dict(target_sha256=sha(path),decision=self.decision,
            retryable=self.retryable,completion_known=self.completion_known,
            outcome_unknown=not self.completion_known,inference_dispatched=not self.retryable,
            checks={k:True for k in assets.REVIEW_CHECKS[kind]} if self.decision=='accepted' else {},
            visual_evidence=['Protocol fixture only; no quality assertion.'],
            model_binding=dict(provider='test_injection',model='not_a_visual_model'),
            reference_roi_evidence=None,
            rois={k:dict(x=0,y=0,width=16,height=16) for k in ('face','clothing','hands')})
    def review_many(self,requests,*,evidence_dir):
        self.calls.append(deepcopy(requests));self.directories.append(str(evidence_dir))
        # Mirror the real review client's immutable evidence-directory contract.
        binding=f.fingerprint(requests);path=Path(evidence_dir)/'FIXTURE_BINDING.json'
        if path.exists() and json.loads(path.read_text())['sha256']!=binding:
            raise ValueError('review job inputs changed')
        write(path,dict(sha256=binding))
        results=[]
        for q in requests:
            result=self.result(q['target'],q['expectation']['kind']);exp=q['expectation']
            if exp.get('layout_object_inventory') is not None:
                result.update(layout_object_inventory=deepcopy(exp['layout_object_inventory']),
                    object_observations={k:dict(count=0,regions=[],evidence='Protocol fixture has zero visible instances; not semantic image QA.') for k in exp['layout_object_inventory']})
            if q.get('reference'):result['reference_sha256']=sha(q['reference'])
            if exp.get('reference_roi'):
                box=exp['reference_roi'];source=exp['reference_roi_source']
                with Image.open(q['reference']) as original:
                    size=list(original.size);crop=original.convert('RGB').crop((box['x'],box['y'],box['x']+box['width'],box['y']+box['height']))
                    stream=io.BytesIO();crop.save(stream,format='PNG')
                result.update(reference_sha256=sha(q['reference']),reference_roi_evidence=dict(source_sha256=sha(q['reference']),
                    source_dimensions=size,pixel_roi=deepcopy(box),roi_name=exp['view'],roi_source=deepcopy(source),
                    roi_source_sha256=f.fingerprint(source),crop_sha256=hashlib.sha256(stream.getvalue()).hexdigest(),coordinate_system='source_pixels'))
            results.append(result)
        return results
    def review_composition(self,path,**kwargs):
        self.compositions.append(deepcopy(kwargs));result=self.result(path)
        inventory=kwargs.get('expectation',{}).get('layout_object_inventory')
        if inventory is not None:
            result['checks'].update({k:True for k in assets.REVIEW_CHECKS['place']})
            result.update(layout_object_inventory=deepcopy(inventory),object_observations={k:dict(count=0,regions=[],evidence='Protocol fixture only, not semantic image QA.') for k in inventory})
            room=deepcopy(result);room['checks']={k:True for k in assets.REVIEW_CHECKS['place']}
            room['reference_sha256']=sha(kwargs['place']['path'])
            result['subreviews']=[dict(self.result(path),reference_sha256=sha(c['path'])) for c in kwargs.get('characters',[])]+[room]
        return result


def accept_direct(config,row):
    return assets.review(config['library'],book_id='book1',asset_id=row['asset_id'],version=row['version'],
        file_sha256=row['sha256'],decision='accepted',reviewer='protocol_fixture',
        checks={k:True for k in assets.REVIEW_CHECKS[row['kind']]},
        evidence=dict(image_sha256=row['sha256'],observations=['Protocol fixture, not a visual model.']))


def test_prepare_is_frozen_and_status_has_no_dispatch_side_effect(tmp_path,service):
    run,packet,config=setup(tmp_path,service)
    before=(run/'STATE.json').read_bytes()
    assert f.status(run)['state']['status']=='prepared'
    assert not service.posts and (run/'STATE.json').read_bytes()==before
    assert f.prepare(run,packet,config)['state']['status']=='prepared'
    changed=deepcopy(packet);changed['characters'][0]['front_prompt']='Changed input'
    with pytest.raises(ValueError,match='frozen_input_changed'):f.prepare(run,changed,config)


def test_source_change_is_not_reported_as_healthy(tmp_path,service):
    run,packet,config=setup(tmp_path,service);Path(packet['source']['path']).write_text('changed')
    with pytest.raises(ValueError,match='script_changed'):f.status(run)
    assert not service.posts


def test_pause_before_first_tick_neither_generates_nor_calls_reviewer(tmp_path,service):
    run,packet,config=setup(tmp_path,service);reviewer=FakeReviewer()
    f.set_paused(run,True,actor='owner',role='admin')
    assert f.tick(run,reviewer=reviewer)['status']=='paused'
    assert not service.posts and not reviewer.calls
    with pytest.raises(PermissionError):f.set_paused(run,False,actor='viewer',role='viewer')


def test_generation_restart_tracks_original_id_once_and_collects_before_review(tmp_path,service):
    run,packet,config=setup(tmp_path,service)
    assert f.tick(run)['status']=='image_prepared'
    assert f.tick(run)['status']=='image_submitted';assert len(service.posts)==1
    state=f.tick(run);assert state['status']=='image_running' and len(service.posts)==1
    task=next(iter(state['jobs'].values()));pid=json.loads((Path(task['folder'])/'STATE.json').read_text())['prompt_id']
    assert pid=='native_1'
    service.complete();reviewer=FakeReviewer()
    assert f.tick(run,reviewer=reviewer)['status']=='assets_ready'
    assert len(service.posts)==1 and len(reviewer.calls)==1
    row=assets.get(config['library'],book_id='book1')[0]
    assert row['status']=='reviewed' and not row['production_approved']


def test_pause_inflight_collects_original_but_never_starts_review_or_new_job(tmp_path,service):
    run,packet,config=setup(tmp_path,service);f.tick(run);f.tick(run)
    f.set_paused(run,True,actor='owner',role='admin');service.complete();reviewer=FakeReviewer()
    result=f.tick(run,reviewer=reviewer)
    assert result['status']=='paused' and not reviewer.calls and len(service.posts)==1
    assert all(x['status']=='collected' for x in result['jobs'].values())
    assert assets.get(config['library'],book_id='book1')[0]['status']=='candidate'


def test_pause_arriving_during_review_prevents_next_generation(tmp_path,service):
    run,packet,config=setup(tmp_path,service,views=('front','left_oblique'))
    register_candidate(tmp_path,config)
    class PauseAfterReview(FakeReviewer):
        def review_many(self,*args,**kwargs):
            result=super().review_many(*args,**kwargs)
            f.set_paused(run,True,actor='owner',role='admin')
            return result
    state=f.tick(run,reviewer=PauseAfterReview())
    assert state['status']=='paused' and not state['jobs'] and not service.posts
    assert assets.get(config['library'],book_id='book1')[0]['status']=='reviewed'


def test_original_native_id_missing_after_service_restart_is_never_replaced(tmp_path,service):
    run,packet,config=setup(tmp_path,service);f.tick(run);f.tick(run)
    service.current=None  # Native service restarted and lost its in-memory history.
    first=f.tick(run)
    assert first['status']=='image_outcome_unknown' and len(service.posts)==1
    assert f.tick(run)['status']=='image_outcome_unknown' and len(service.posts)==1
    task=next(iter(first['jobs'].values()))
    saved=json.loads((Path(task['folder'])/'STATE.json').read_text())
    assert saved['prompt_id']=='native_1'


def test_ambiguous_post_result_is_not_replayed_after_restart(tmp_path,service):
    run,packet,config=setup(tmp_path,service);f.tick(run);service.drop_post_response=True
    f.tick(run)
    assert len(service.posts)==1
    assert f.tick(run)['status']=='outcome_unknown'
    assert f.tick(run)['status']=='outcome_unknown' and len(service.posts)==1


def test_missing_visual_provider_cannot_promote_existing_candidate(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    state=f.tick(run,reviewer=None)
    assert state['status']=='blocked_review_or_design'
    assert not state['requirements']['ready'] and not service.posts
    assert assets.get(config['library'],book_id='book1')[0]['status']=='candidate'


def test_known_provider_unavailable_can_recover_without_regenerating_image(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    first=FakeReviewer('unavailable',retryable=True)
    assert f.tick(run,reviewer=first)['status']=='blocked_review_or_design'
    recovered=FakeReviewer('accepted')
    assert f.tick(run,reviewer=recovered)['status']=='assets_ready'
    assert recovered.calls and not service.posts
    assert len(f.status(run)['state']['review_history'])==1
    assert first.directories!=recovered.directories


def test_unknown_review_result_is_preserved_without_replay(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    first=FakeReviewer('unavailable',completion_known=False)
    assert f.tick(run,reviewer=first)['status']=='blocked_review_or_design'
    recovered=FakeReviewer('accepted')
    assert f.tick(run,reviewer=recovered)['status']=='blocked_review_or_design'
    assert not recovered.calls and not service.posts
    assert assets.get(config['library'],book_id='book1')[0]['status']=='candidate'


def test_unknown_review_does_not_replay_by_creating_a_new_pipeline_run(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    assert f.tick(run,reviewer=FakeReviewer('unavailable',completion_known=False))['status']=='blocked_review_or_design'
    other=tmp_path/'other_run';f.prepare(other,packet,config);reviewer=FakeReviewer()
    assert f.tick(other,reviewer=reviewer)['status']=='blocked_review_or_design'
    assert not reviewer.calls and not service.posts


def test_review_expectation_matches_real_schema_and_keeps_appearance_contract(tmp_path,service):
    from src.content_factory.visual_asset_review_v3 import observation_schema
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    reviewer=FakeReviewer();f.tick(run,reviewer=reviewer)
    expectation=reviewer.calls[0][0]['expectation']
    schema=observation_schema(expectation)  # Must accept the real client's ROI list contract.
    assert expectation['locate_rois']==['face','clothing','hands']
    assert expectation['appearance_description']=='gray shirt'
    assert schema['properties']['rois']['properties']['face']['type']=='array'


def test_gpu_busy_updates_durable_waiting_state_and_heartbeat_without_dispatch(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    service.queue_response=dict(queue_running=[[0,'foreign_native',{}]],queue_pending=[])
    reviewer=FakeReviewer()
    first=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=1)
    assert first['status']=='waiting_gpu' and first['heartbeat_at']>0
    second=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=1)
    assert second['status']=='waiting_gpu' and second['heartbeat_at']>first['heartbeat_at']
    assert not reviewer.calls and not service.posts
    service.queue_response=None
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=1)['status']=='assets_ready'


def test_parallel_executor_contention_preserves_owner_state_and_can_continue(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    ready=threading.Event();release=threading.Event()
    def original_owner():
        with f.images.run_lock(run):ready.set();release.wait(10)
    owner=threading.Thread(target=original_owner);owner.start();assert ready.wait(5)
    before=(run/'STATE.json').read_bytes();reviewer=FakeReviewer()
    try:
        result=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=1)
        assert result['status']=='prepared' and (run/'STATE.json').read_bytes()==before
        assert not reviewer.calls and not service.posts
    finally:release.set();owner.join(5)
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=1)['status']=='assets_ready'


def test_known_unavailable_retries_are_bounded_and_never_regenerate_asset(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    reviewer=FakeReviewer('unavailable',retryable=True)
    for _ in range(5):assert f.tick(run,reviewer=reviewer)['status']=='blocked_review_or_design'
    assert len(reviewer.calls)==2 and len(set(reviewer.directories))==2
    assert not service.posts
    state=f.status(run)['state'];assert list(state['review_attempts'].values())==[2]


def test_multi_wave_generation_uses_distinct_bound_review_evidence(tmp_path,service):
    run,packet,config=setup(tmp_path,service,views=('front','left_oblique'))
    service.auto_complete=True;reviewer=FakeReviewer()
    state=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=12)
    assert state['status']=='assets_ready' and len(service.posts)==2
    assert len(reviewer.calls)==2 and len(set(reviewer.directories))==2


def test_existing_front_then_face_candidates_complete_two_review_layers_without_regeneration(tmp_path,service):
    run,packet,config=setup(tmp_path,service,views=('front','face'))
    front=register_candidate(tmp_path,config)
    image=tmp_path/'face.png';Image.new('RGB',(64,80),'blue').save(image)
    dependencies=[f._asset_identity(front)]
    assets.register(config['library'],image,book_id='book1',entity_id='actor',kind='character',view='face',
        provenance=dict(dependencies=dependencies,dependency_fingerprint=f.fingerprint(dependencies)))
    reviewer=FakeReviewer()
    first=f.tick(run,reviewer=reviewer)
    assert first['status']=='review_pending' and not service.posts
    assert [q['expectation']['view'] for q in reviewer.calls[0]]==['front']
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=4)['status']=='assets_ready'
    assert [[q['expectation']['view'] for q in wave] for wave in reviewer.calls]==[['front'],['face']]
    assert not service.posts


def legacy_detail_review(tmp_path,service,*,view='face',old_changes=None,attempts=1,roi_available=True):
    run,packet,config=setup(tmp_path,service)
    front=register_candidate(tmp_path,config)
    if roi_available:assert f.tick(run,reviewer=FakeReviewer())['status']=='assets_ready'
    else:accept_direct(config,front)
    front=assets.get(config['library'],book_id='book1',view='front')[0]
    packet['characters'][0]['required_views']=['front',view]
    run=tmp_path/'legacy_detail';f.prepare(run,packet,config)
    image=tmp_path/'detail.png';Image.new('RGB',(64,80),'blue').save(image)
    deps=[f._asset_identity(front)]
    detail=assets.register(config['library'],image,book_id='book1',entity_id='actor',kind='character',view=view,
        provenance=dict(dependencies=deps,dependency_fingerprint=f.fingerprint(deps)))
    old=FakeReviewer('needs_review').result(image)
    old.update(checks=dict(identity=None,view=True,clothing=None,anatomy=None),reference_sha256=front['sha256'])
    old.update(old_changes or {})
    assets.review(config['library'],book_id='book1',asset_id=detail['asset_id'],version=detail['version'],file_sha256=detail['sha256'],
        decision='unavailable',reviewer='known_legacy_fixture',checks=dict(view=True),
        evidence=dict(image_sha256=detail['sha256'],observations=['Legacy protocol fixture, not semantic acceptance.'],
                      review=f.fingerprint(old),source_review=old))
    key=f"{detail['asset_id']}:v{detail['version']}:{detail['sha256']}"
    state=f.status(run)['state'];state.update(reviews={key:old},review_attempts={key:attempts});f.write(run/'STATE.json',state)
    return run,config,detail,old,key,front


@pytest.mark.parametrize('view',['face','clothing','hands'])
def test_known_legacy_uncertainty_gets_one_sha_bound_reference_roi_review(view,tmp_path,service):
    run,config,detail,old,key,front=legacy_detail_review(tmp_path,service,view=view)
    reviewer=FakeReviewer()
    state=f.tick(run,reviewer=reviewer)
    assert state['status']=='assets_ready' and len(reviewer.calls)==1 and not service.posts
    exp=reviewer.calls[0][0]['expectation']
    assert exp['reference_roi']==dict(x=0,y=0,width=16,height=16)
    assert exp['reference_roi_source']==dict(asset_id=front['asset_id'],version=front['version'],image_sha256=front['sha256'],
        review_sha256=f.fingerprint(front['review']['evidence']['source_review']))
    assert state['review_history'][key]==[old] and old['checks']['identity'] is None
    assert state['review_attempts'][key]==2 and key in state['roi_enhancements']
    current=assets.get(config['library'],book_id='book1',view=view)[0]
    receipt=current['review']['evidence']['source_review']['reference_roi_evidence']
    assert receipt==current['review']['evidence']['reference_roi_evidence']
    assert receipt['roi_name']==view and receipt['source_sha256']==front['sha256']
    assert f.tick(run,reviewer=reviewer)['status']=='assets_ready' and len(reviewer.calls)==1


@pytest.mark.parametrize('changes,attempts,roi_available',[
    (dict(completion_known=False,outcome_unknown=True),1,True),
    (dict(completion_known=None,outcome_unknown=False),1,True),
    (dict(reference_roi_evidence=dict(already_had_roi=True)),1,True),
    ({},2,True),({},1,False),
])
def test_roi_enhancement_requires_known_result_new_approved_roi_and_available_budget(changes,attempts,roi_available,tmp_path,service):
    run,config,detail,old,key,front=legacy_detail_review(tmp_path,service,old_changes=changes,attempts=attempts,roi_available=roi_available)
    reviewer=FakeReviewer();state=f.tick(run,reviewer=reviewer)
    assert state['status']=='blocked_review_or_design' and not reviewer.calls and not service.posts
    assert assets.get(config['library'],book_id='book1',view='face')[0]['status']=='candidate'
    assert state['reviews'][key]==old


def test_enhanced_roi_review_that_remains_uncertain_is_not_automatically_repeated(tmp_path,service):
    run,config,detail,old,key,front=legacy_detail_review(tmp_path,service)
    reviewer=FakeReviewer('needs_review')
    assert f.tick(run,reviewer=reviewer)['status']=='blocked_review_or_design'
    next_reviewer=FakeReviewer()
    state=f.tick(run,reviewer=next_reviewer)
    assert state['status']=='blocked_review_or_design' and not next_reviewer.calls and len(reviewer.calls)==1
    assert state['reviews'][key]['reference_roi_evidence'] and state['review_history'][key]==[old]
    assert assets.get(config['library'],book_id='book1',view='face')[0]['status']=='candidate'


def legacy_room_count_review(tmp_path,service,*,enabled=False,changes=None,attempts=1,already_refreshed=False):
    _,packet,config=setup(tmp_path,service)
    packet['characters']=[]
    packet['places']=[dict(id='room',design_version='v1',required_views=['front'],layout_design='One old table in this room.')]
    config[f.BLIND_COUNT_REFRESH_POLICY]=enabled;config['max_review_attempts']=4
    run=tmp_path/'new_count_contract';f.prepare(run,packet,config)
    row=register_candidate(tmp_path,config,entity='room',kind='place')
    old=FakeReviewer('needs_review').result(tmp_path/'room_gray.png',kind='place')
    old.update(checks=dict(layout=True,view=True,consistency=None,artifact_free=True),
        observations=dict(people_count=None,age_band='unknown',orientation='unknown',framing='environment'),
        issues=[],prompt_version='view-scope-actual-layout-guide-v8')
    old.update(changes or {})
    assets.review(config['library'],book_id='book1',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
        decision='unavailable',reviewer='known_legacy_fixture',checks=dict(layout=True,view=True,artifact_free=True),
        evidence=dict(image_sha256=row['sha256'],observations=['Known count-null fixture; not semantic vision.'],
            review=f.fingerprint(old),source_review=old))
    key=f"{row['asset_id']}:v{row['version']}:{row['sha256']}"
    if attempts!=1 or already_refreshed:
        state=f.status(run)['state'];state['review_attempts']={key:attempts}
        if already_refreshed:state['blind_count_refreshes']={key:dict(previous_review_sha256=f.fingerprint(old))}
        f.write(run/'STATE.json',state)
    return run,config,row,old,key


def test_explicit_count_contract_refresh_reuses_image_and_keeps_previous_known_result(tmp_path,service):
    run,config,row,old,key=legacy_room_count_review(tmp_path,service,enabled=True)
    reviewer=FakeReviewer();state=f.tick(run,reviewer=reviewer)
    assert state['status']=='assets_ready' and len(reviewer.calls)==1 and not service.posts
    assert state['review_history'][key]==[old] and state['review_attempts'][key]==2
    refresh=state['blind_count_refreshes'][key]
    assert refresh['previous_review_sha256']==f.fingerprint(old) and refresh['target_sha256']==row['sha256']
    assert refresh['policy']==f.BLIND_COUNT_REFRESH_POLICY
    assert f.tick(run,reviewer=reviewer)['status']=='assets_ready' and len(reviewer.calls)==1


@pytest.mark.parametrize('changes,attempts,already_refreshed',[
    (dict(completion_known=False,outcome_unknown=True),1,False),
    (dict(completion_known=None),1,False),
    (dict(observations={}),1,False),
    (dict(observations=dict(people_count=0)),1,False),
    (dict(checks=dict(layout=None,view=True,consistency=None,artifact_free=True)),1,False),
    (dict(checks=dict(layout=False,view=True,consistency=None,artifact_free=True)),1,False),
    (dict(issues=[dict(kind='layout',severity='uncertain')]),1,False),
    (dict(issues=[dict(kind='artifact',severity='blocking')]),1,False),
    (dict(blind_count_recheck=dict(people_count=None)),1,False),
    ({},2,False),({},1,True),
])
def test_count_refresh_never_uses_unknown_other_defects_or_exhausted_budget(changes,attempts,already_refreshed,tmp_path,service):
    run,config,row,old,key=legacy_room_count_review(tmp_path,service,enabled=True,
        changes=changes,attempts=attempts,already_refreshed=already_refreshed)
    reviewer=FakeReviewer();state=f.tick(run,reviewer=reviewer)
    assert state['status']=='blocked_review_or_design' and not reviewer.calls and not service.posts
    assert assets.get(config['library'],book_id='book1',kind='place')[0]['status']=='candidate'


def test_legacy_count_refresh_is_disabled_by_default_and_does_not_loop_when_still_uncertain(tmp_path,service):
    run,config,row,old,key=legacy_room_count_review(tmp_path,service)
    reviewer=FakeReviewer();assert f.tick(run,reviewer=reviewer)['status']=='blocked_review_or_design'
    assert not reviewer.calls and not service.posts
    plan=f.read(run/'PLAN.json');plan['config'][f.BLIND_COUNT_REFRESH_POLICY]=True
    state=f.read(run/'STATE.json');still_unknown=FakeReviewer('needs_review')
    f.review_candidates(run,plan,state,still_unknown)
    assert len(still_unknown.calls)==1 and state['review_attempts'][key]==2
    assert f.review_candidates(run,plan,state,reviewer)==0 and not reviewer.calls


def test_count_refresh_rejects_an_old_result_for_a_different_target(tmp_path,service):
    run,config,row,old,key=legacy_room_count_review(tmp_path,service,enabled=True,
        changes=dict(target_sha256='f'*64))
    snapshot=f.status(run)
    assert not f._can_refresh_blind_count(snapshot['plan'],snapshot['state'],key,row,old,1)
    # The invalid old receipt is not an existing review for this target. An
    # ordinary first review is still allowed, rather than inheriting that result.
    assert f._latest_review(snapshot['state'],assets.get(config['library'],book_id='book1')[0])=={}


@pytest.mark.parametrize('value',[1,'true',None])
def test_count_refresh_policy_requires_explicit_boolean(tmp_path,service,value):
    _,packet,config=setup(tmp_path,service);config[f.BLIND_COUNT_REFRESH_POLICY]=value
    with pytest.raises(ValueError,match='blind_count_refresh_requires_boolean'):
        f.prepare(tmp_path/'invalid_count_policy',packet,config)


@pytest.mark.parametrize('defect',['missing','source_sha','crop_sha','roi_source'])
def test_wrong_reference_roi_receipt_cannot_approve_detail(defect,tmp_path,service):
    run,config,detail,old,key,front=legacy_detail_review(tmp_path,service)
    class BadReceipt(FakeReviewer):
        def review_many(self,*args,**kwargs):
            result=super().review_many(*args,**kwargs)
            if defect=='missing':result[0].pop('reference_roi_evidence')
            elif defect=='source_sha':result[0]['reference_sha256']='f'*64
            elif defect=='crop_sha':result[0]['reference_roi_evidence']['crop_sha256']='e'*64
            else:result[0]['reference_roi_evidence']['roi_source']['version']=99
            return result
    with pytest.raises(ValueError,match='reference_roi_review_mismatch'):f.tick(run,reviewer=BadReceipt())
    assert assets.get(config['library'],book_id='book1',view='face')[0]['status']=='candidate'
    assert f.status(run)['state']['reviews'][key]==old and not service.posts


def test_new_run_reuses_sha_bound_roi_from_existing_reviewed_front(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    assert f.tick(run,reviewer=FakeReviewer())['status']=='assets_ready'
    packet['characters'][0]['required_views']=['front','face']
    packet['characters'][0]['view_prompts']['face']='Face detail of the same child, head and shoulders.'
    new_run=tmp_path/'detail_run';f.prepare(new_run,packet,config)
    state=f.tick(new_run,reviewer=FakeReviewer())
    assert state['status']=='image_prepared'
    task=next(iter(state['jobs'].values()))
    assert task['requirement']['view']=='face'
    f.tick(new_run)
    crops=[n for n in service.posts[0]['prompt'].values() if n['class_type']=='ImageCrop']
    assert len(crops)==1 and crops[0]['inputs']['width']==16


def test_changed_or_wrong_review_target_never_marks_asset_reviewed(tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    class WrongImage(FakeReviewer):
        def result(self,*args,**kwargs):return dict(super().result(*args,**kwargs),target_sha256='f'*64)
    with pytest.raises(ValueError,match='wrong_image'):f.tick(run,reviewer=WrongImage())
    assert assets.get(config['library'],book_id='book1')[0]['status']=='candidate'


def test_legacy_video_pause_must_remain_before_any_image_submission(tmp_path,service):
    run,packet,config=setup(tmp_path,service);f.tick(run)
    Path(config['protected_pause_path']).unlink()
    with pytest.raises(ValueError,match='legacy_batch_not_paused'):f.tick(run)
    assert not service.posts


@pytest.mark.parametrize('response',[{},[],{'queue_running':[]},
    {'queue_running':None,'queue_pending':[]},{'queue_running':[],'queue_pending':{}}])
def test_malformed_native_queue_is_not_treated_as_empty(response,tmp_path,service):
    run,packet,config=setup(tmp_path,service);register_candidate(tmp_path,config)
    reviewer=FakeReviewer();service.queue_response=response
    with pytest.raises(ValueError,match='queue_schema_invalid'):f.tick(run,reviewer=reviewer)
    assert not reviewer.calls and not service.posts
    assert assets.get(config['library'],book_id='book1')[0]['status']=='candidate'


@pytest.mark.parametrize('same_pixels',[False,True])
def test_changed_front_invalidates_generated_direction_until_rebuilt(tmp_path,service,same_pixels):
    run,packet,config=setup(tmp_path,service,views=('front','left_oblique'))
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=12)['status']=='assets_ready'
    original=assets.get(config['library'],book_id='book1',view='left_oblique')[0]
    assert original['status']=='reviewed' and len(original['provenance']['dependencies'])==1
    if same_pixels:
        front=assets.get(config['library'],book_id='book1',view='front')[0]
        changed=assets.register(config['library'],front['path'],book_id='book1',entity_id='actor',kind='character',view='front',
                                input_sha256=f.fingerprint(dict(design_input='new version, same pixels')))
        assert changed['sha256']==front['sha256'] and changed['version']==2
    else:changed=register_candidate(tmp_path,config,color='red')
    accept_direct(config,changed)
    state=f.tick(run,reviewer=reviewer)
    assert state['status']=='image_prepared' and not state['requirements']['ready']
    task=list(state['jobs'].values())[-1]
    assert task['requirement']['view']=='left_oblique'
    assert task['dependencies'][0]['version']==2
    # Old accepted evidence and its original image remain intact, but cannot qualify this run.
    assert assets.get(config['library'],book_id='book1',view='left_oblique')[0]['status']=='reviewed'
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=8)['status']=='assets_ready'
    assert len(service.posts)==3
    assert max(assets.get(config['library'],book_id='book1',view='left_oblique'),key=lambda a:a['version'])['version']==2


def test_changed_pose_reference_invalidates_right_profile_with_same_front(tmp_path,service):
    run,packet,config=setup(tmp_path,service)
    packet['characters'][0].update(required_views=['front','right_oblique','right_profile'],
        view_prompts=dict(right_oblique='Same person looking screen-right at three quarters.',
                          right_profile='Same person in screen-right profile.'))
    run=tmp_path/'profile_run';f.prepare(run,packet,config)
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=16)['status']=='assets_ready'
    old=assets.get(config['library'],book_id='book1',view='right_oblique')[0]
    image=tmp_path/'new_pose.png';Image.new('RGB',(64,80),'yellow').save(image)
    newer=assets.register(config['library'],image,book_id='book1',entity_id='actor',kind='character',view='right_oblique',provenance=old['provenance'])
    accept_direct(config,newer)
    state=f.tick(run,reviewer=reviewer)
    assert state['status']=='image_prepared'
    task=list(state['jobs'].values())[-1]
    assert task['requirement']['view']=='right_profile'
    assert {d['view']:d['version'] for d in task['dependencies']}=={'front':1,'right_oblique':2}


def test_imported_manifest_canonical_dependency_is_sha_bound_and_read_only(tmp_path,service):
    run,packet,config=setup(tmp_path,service,views=('front','left_oblique'))
    front=register_candidate(tmp_path,config);accept_direct(config,front)
    image=tmp_path/'direction.png';Image.new('RGB',(64,80),'blue').save(image)
    manifest=tmp_path/'FINAL_MAP.json'
    write(manifest,dict(items=[dict(character_id='actor',view='left_oblique',sha256=sha(image),
                                  ultimate_canonical_sha256=front['sha256'],reference_sha256=front['sha256'])]))
    provenance=dict(manifest_path=str(manifest),manifest_sha256=sha(manifest),native_verified=False)
    direction=assets.register(config['library'],image,book_id='book1',entity_id='actor',kind='character',view='left_oblique',provenance=provenance)
    accept_direct(config,direction);before=manifest.read_bytes()
    assert f.tick(run)['status']=='assets_ready'
    assert manifest.read_bytes()==before
    accept_direct(config,register_candidate(tmp_path,config,color='red'))
    state=f.tick(run)
    assert state['status']=='image_prepared' and not state['requirements']['ready']
    assert manifest.read_bytes()==before and not service.posts


def test_twin_parent_revision_invalidates_child_front_without_merging_roles(tmp_path,service):
    run,packet,config=setup(tmp_path,service)
    older=packet['characters'][0];older.update(id='older',identity_group='twins')
    younger=deepcopy(older);younger.update(id='younger',canonical_from_role='older')
    packet['characters'].append(younger);run=tmp_path/'twins';f.prepare(run,packet,config)
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=12)['status']=='assets_ready'
    image=tmp_path/'new_older.png';Image.new('RGB',(64,80),'orange').save(image)
    changed=assets.register(config['library'],image,book_id='book1',entity_id='older',kind='character',view='front',identity_group='twins')
    accept_direct(config,changed)
    state=f.tick(run,reviewer=reviewer)
    assert state['status']=='image_prepared' and not state['requirements']['ready']
    task=list(state['jobs'].values())[-1]
    assert task['requirement']['entity_id']=='younger' and task['dependencies'][0]['version']==2


def test_first_frame_is_reviewed_before_h3_export_and_never_submits_video(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config));accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    reviewer=FakeReviewer();service.auto_complete=True
    assert f.tick(run,reviewer=reviewer)['status']=='first_frame_prepared'
    assert f.tick(run,reviewer=reviewer)['status']=='image_submitted'
    assert f.tick(run,reviewer=reviewer)['status']=='h3_inputs_ready'
    ready=json.loads((run/'H3_INPUT_READY.json').read_text())
    assert ready['publication'] is False and ready['old_batch_resume'] is False
    assert len(service.posts)==1 and len(reviewer.compositions)==1
    assert [x['id'] for x in reviewer.compositions[0]['characters']]==['actor']
    assert all('MiniMax' not in n['class_type'] for n in service.posts[0]['prompt'].values())


@pytest.mark.parametrize('dimensions',[(736,1312),(512,896)])
def test_first_frame_dimensions_are_independent_of_asset_portrait_dimensions(dimensions,tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    if dimensions!=(736,1312):config.update(first_frame_width=dimensions[0],first_frame_height=dimensions[1])
    run=tmp_path/'dimensions_run';f.prepare(run,packet,config)
    # The same config keeps the casting/turnaround graph at 768x1024.
    assert f.tick(run)['status']=='image_prepared'
    f.tick(run)
    portrait=[n['inputs'] for n in service.posts[-1]['prompt'].values() if n['class_type']=='EmptyFlux2LatentImage'][0]
    assert (portrait['width'],portrait['height'])==(768,1024)
    service.complete();reviewer=FakeReviewer()
    accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    assert f.tick(run,reviewer=reviewer)['status']=='first_frame_prepared'
    f.tick(run)
    frame=[n['inputs'] for n in service.posts[-1]['prompt'].values() if n['class_type']=='EmptyFlux2LatentImage'][0]
    assert (frame['width'],frame['height'])==dimensions


def test_identical_twin_image_bytes_keep_two_role_input_slots(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    first=packet['characters'][0];first.update(id='twin_a',identity_group='twins')
    second=deepcopy(first);second['id']='twin_b';packet['characters'].append(second)
    packet['shots'][0].update(visible_cast=['twin_a','twin_b'],character_views={'twin_a':'front','twin_b':'front'})
    run=tmp_path/'same_image_twins';f.prepare(run,packet,config)
    image=tmp_path/'twins.png';Image.new('RGB',(64,80),'gray').save(image)
    for role in ('twin_a','twin_b'):
        accept_direct(config,assets.register(config['library'],image,book_id='book1',entity_id=role,
            kind='character',view='front',identity_group='twins'))
    accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=8)['status']=='h3_inputs_ready'
    names=[n['inputs']['image'] for n in service.posts[0]['prompt'].values() if n['class_type']=='LoadImage']
    assert len(names)==len(set(names))==3
    assert sha(service.input/names[0])==sha(service.input/names[1])
    assert [r['id'] for r in reviewer.compositions[0]['characters']]==['twin_a','twin_b']


@pytest.mark.parametrize('ages,expected',[
    (['adult'],'adult'),(['child'],'child'),(['adult','adult'],'adult'),
    (['child','child'],'child'),(['adult','child'],'mixed'),
    (['adult','unknown'],'unknown'),([None,'child'],'unknown'),([], 'unknown'),
])
def test_composition_age_band_uses_visible_people_only(ages,expected,tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    template=packet['characters'][0];packet['characters']=[];visible=[]
    for n,age in enumerate(ages):
        role=deepcopy(template);role.update(id='visible_'+str(n),age_band=age)
        packet['characters'].append(role);visible.append(role['id'])
    offscreen=deepcopy(template);offscreen.update(id='offscreen_voice',age_band='child' if expected=='adult' else 'adult')
    packet['characters'].append(offscreen)
    packet['shots'][0].update(visible_cast=visible,character_views={cid:'front' for cid in visible},
        audio=[dict(mode='voiceover',speaker=offscreen['id'],text='A voice outside this camera view.')])
    run=tmp_path/'age_run';f.prepare(run,packet,config)
    for character in packet['characters']:
        accept_direct(config,register_candidate(tmp_path,config,entity=character['id']))
    accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=8)['status']=='h3_inputs_ready'
    request=reviewer.compositions[0]
    assert request['expectation']['age_band']==expected
    assert request['expectation']['expected_people']==len(visible)
    assert [c['id'] for c in request['characters']]==visible


def test_later_protocol_failure_revokes_previously_ready_export_and_records_failure(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config));accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=8)['status']=='h3_inputs_ready'
    service.queue_response={}
    with pytest.raises(ValueError,match='queue_schema_invalid'):f.tick(run,reviewer=reviewer)
    state=f.status(run)['state']
    assert state['status']=='failed' and 'queue_schema_invalid' in state['error']['message']
    assert not (run/'H3_INPUT_READY.json').exists()
    archived=[Path(p) for e in state['invalidations'] for p in e['archived_files']]
    assert any(p.name=='H3_INPUT_READY.json' and p.is_file() for p in archived)


def test_first_frame_without_visual_acceptance_never_exports_h3_input(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config));accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;reviewer=FakeReviewer('unavailable')
    f.tick(run);f.tick(run)
    assert f.tick(run,reviewer=reviewer)['status']=='blocked_first_frame_review'
    assert not (run/'H3_INPUT_READY.json').exists()


def test_first_frame_known_unavailable_recovers_same_image_without_regeneration(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config));accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;first=FakeReviewer('unavailable',retryable=True)
    f.tick(run);f.tick(run)
    assert f.tick(run,reviewer=first)['status']=='blocked_first_frame_review'
    before=f.status(run)['state']['first_frames']['shot1']['sha256']
    recovered=FakeReviewer()
    state=f.tick(run,reviewer=recovered)
    assert state['status']=='h3_inputs_ready' and len(service.posts)==1
    assert state['first_frames']['shot1']['sha256']==before
    assert len(state['first_frames']['shot1']['review_history'])==1
    assert first.compositions[0]['evidence_dir']!=recovered.compositions[0]['evidence_dir']


def test_first_frame_repair_is_bounded_and_preserves_all_generated_attempts(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config));accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;reviewer=FakeReviewer('repair_required')
    state=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=20)
    assert state['status']=='blocked_first_frame_review'
    assert len(service.posts)==3 and len(reviewer.compositions)==3
    assert len(state['first_frame_history']['shot1'])==2
    history=state['first_frame_history']['shot1']+[state['first_frames']['shot1']]
    assert len({row['sha256'] for row in history})==3
    assert all(Path(row['path']).is_file() for row in history)
    assert not (run/'H3_INPUT_READY.json').exists()


def test_asset_version_change_does_not_keep_old_first_frame_ready(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config));accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    service.auto_complete=True;reviewer=FakeReviewer()
    f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=8)
    assert f.status(run)['state']['status']=='h3_inputs_ready'
    old=deepcopy(f.status(run)['state']['first_frames']['shot1'])
    accept_direct(config,register_candidate(tmp_path,config,color='red'))
    try:result=f.tick(run,reviewer=reviewer)
    except ValueError:
        assert f.status(run)['state']['status']!='h3_inputs_ready'
    else:
        assert result['status']!='h3_inputs_ready'
        assert result.get('first_frames',{}).get('shot1')!=old or result.get('invalidations')
    assert not (run/'H3_INPUT_READY.json').exists(), 'A stale ready export remains available to consumers'


def test_generated_twin_uses_reviewed_sibling_and_keeps_shared_identity_group(tmp_path,service):
    run,packet,config=setup(tmp_path,service)
    older=packet['characters'][0];older.update(id='older',identity_group='twins')
    younger=deepcopy(older);younger.update(id='younger',canonical_from_role='older')
    packet['characters'].append(younger)
    run=tmp_path/'twin_run';f.prepare(run,packet,config)
    image=tmp_path/'older.png';Image.new('RGB',(64,80),'gray').save(image)
    source=assets.register(config['library'],image,book_id='book1',entity_id='older',kind='character',view='front',identity_group='twins')
    accept_direct(config,source)
    assert f.tick(run)['status']=='image_prepared'
    task=next(iter(f.status(run)['state']['jobs'].values()))
    assert task['requirement']['entity_id']=='younger'
    f.tick(run);graph=service.posts[0]['prompt']
    loaded=[n['inputs']['image'] for n in graph.values() if n['class_type']=='LoadImage']
    assert loaded==['asset_'+source['sha256'][:20]+'.png']
    service.complete();state=f.tick(run,reviewer=FakeReviewer())
    assert state['status']=='assets_ready'
    rows=assets.get(config['library'],book_id='book1',kind='character',view='front')
    assert {r['entity_id'] for r in rows}=={'older','younger'}
    assert {r['identity_group'] for r in rows}=={'twins'}


def test_asset_update_invalidates_dependent_shot_only_and_preserves_unrelated_frame(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    other=deepcopy(packet['characters'][0]);other['id']='other';packet['characters'].append(other)
    shot2=deepcopy(packet['shots'][0]);shot2.update(id='shot2',visible_cast=['other'],
        character_views={'other':'front'},visual_prompt='The other child stands beside the table.')
    packet['shots'].append(shot2)
    run=tmp_path/'two_shots';f.prepare(run,packet,config)
    for args in ({},{'entity':'other','color':'blue'},{'entity':'room','kind':'place','color':'white'}):
        accept_direct(config,register_candidate(tmp_path,config,**args))
    service.auto_complete=True;reviewer=FakeReviewer()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=16)['status']=='h3_inputs_ready'
    old_frames=deepcopy(f.status(run)['state']['first_frames'])
    assert len(service.posts)==2
    accept_direct(config,register_candidate(tmp_path,config,color='red'))
    state=f.tick(run,reviewer=reviewer)
    assert state['status']=='first_frame_prepared'
    assert state['first_frames']['shot2']==old_frames['shot2']
    assert 'shot1' not in state['first_frames']
    assert not (run/'H3_INPUT_READY.json').exists()
    assert f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=8)['status']=='h3_inputs_ready'
    assert len(service.posts)==3, 'Only the changed actor shot may be regenerated'
    assert f.status(run)['state']['first_frames']['shot2']==old_frames['shot2']


def test_real81_import_in_two_cli_processes_is_idempotent_and_unreviewed(tmp_path,service):
    """Real media provenance, only temporary registry; no VLM or image calls."""
    root=Path(__file__).resolve().parents[1]
    cast=root/'data/image_model_trials/20261106_novel_cast_turnaround'
    packet=f.packet_from_cast(cast,'qa_actual_book')
    runs_root=tmp_path/'visual_asset_runs_v3';run=runs_root/'real_run';_,_,config=setup(tmp_path,service)
    packet_path=tmp_path/'packet.json';config_path=tmp_path/'config.json';write(packet_path,packet);write(config_path,config)
    entry=root/'scripts/run_visual_asset_pipeline_v3.py'
    def cli(action,*extra):
        return subprocess.run([sys.executable,'-B',str(entry),action,'--run',str(run),'--runs-root',str(runs_root),*extra],capture_output=True,text=True,cwd=root,timeout=120)
    p=cli('prepare','--packet',str(packet_path),'--config',str(config_path));assert p.returncode==0,p.stderr+p.stdout
    # Use public tick API without a reviewer; avoids any real model discovery.
    command=[sys.executable,'-B','-c','import json,sys;from src.content_factory.visual_asset_pipeline_v3 import tick;print(json.dumps(tick(sys.argv[1])))',str(run)]
    for n in range(2):
        p=subprocess.run(command,capture_output=True,text=True,cwd=root,timeout=120);assert p.returncode==0,p.stderr+p.stdout
        state=json.loads(p.stdout);assert state['status']=='blocked_review_or_design' and state['imported']==81
        assert len(assets.get(config['library'],book_id='qa_actual_book'))==81
        if n==0:before=(Path(config['library'])/'INDEX.json').read_bytes()
        else:assert before==(Path(config['library'])/'INDEX.json').read_bytes()
    assert not service.posts
    assert all(x['status']=='candidate' for x in assets.get(config['library'],book_id='qa_actual_book'))


def test_actual_cli_restart_uses_original_native_id_and_pause_never_resubmits(tmp_path,service):
    run,packet,config=setup(tmp_path,service)
    runs_root=tmp_path/'visual_asset_runs_v3';run=runs_root/'run';f.prepare(run,packet,config)
    root=Path(__file__).resolve().parents[1];entry=root/'scripts/run_visual_asset_pipeline_v3.py'
    def cli(action):
        result=subprocess.run([sys.executable,'-B',str(entry),action,'--run',str(run),'--runs-root',str(runs_root)],cwd=root,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        return json.loads(result.stdout)
    assert cli('tick')['status']=='image_prepared'
    assert cli('tick')['status']=='image_submitted' and len(service.posts)==1
    assert cli('tick')['status']=='image_running' and len(service.posts)==1
    cli('pause');service.complete()
    assert cli('tick')['status']=='paused' and len(service.posts)==1
    assert cli('status')['state']['status']=='paused'
