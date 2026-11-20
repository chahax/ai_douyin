"""True local HTTP/native-original/CPU-film tests; never production Comfy."""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,shutil
import pytest
from src.content_factory import visual_h3_baseline_two_rounds_v38 as f

REAL_BASELINE=f.BASELINE
REAL_ORIGIN=f.ORIGIN

def module(name):
    path=Path(__file__).with_name(name+'.py');spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return f.bind(path)

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    common=module('test_visual_h3_multiview_continuity_minute_v37')
    with common.server(tmp_path) as (service,url):
        baseline=tmp_path/'baseline';shutil.copytree(REAL_BASELINE,baseline);audit=f.read(baseline/'INPUT_AUDIT.json')
        group=next(r for r in audit['runs'] if r['run']==f.BASELINE_NAME)
        for item in group['segments']:
            h=baseline/item['shot'];item['request']=f.bind(h/'REQUEST.baseline.original.json');item['prompt_snapshot']=f.bind(h/'PROMPT.baseline.actual.txt')
            first=f.bind(h/'first_input.baseline.png');item['baseline_first_input']=dict(original=first,snapshot=first)
        write(baseline/'INPUT_AUDIT.json',audit);root=tmp_path/'session';root.mkdir();origin=tmp_path/'origin_plan.json';source=f.read(REAL_ORIGIN)
        pause=tmp_path/'old_pause.json';pause.write_text('original old pause',encoding='utf-8')
        source['config'].update(service_url=url,input_root=str(service.inputs),output_root=str(service.outputs),gpu_lock_root=str(tmp_path/'gpu'),protected_pause_path=str(pause))
        write(origin,source)
        monkeypatch.setattr(f,'ROOT',root);monkeypatch.setattr(f,'BASELINE',baseline);monkeypatch.setattr(f,'ORIGIN',origin);monkeypatch.setattr(f,'LOCAL_SERVICE',url);monkeypatch.setattr(f,'SHARED_GPU',tmp_path/'gpu')
        write(root/'ROOT_USER_SCOPE.json',dict(schema='h3_baseline_two_round_user_scope/v38',user_statement='Explicit CPU protocol scope, not a production authorization',baseline=f.BASELINE_NAME,
            semantic_review_authorized=True,engineering_limits_not_user_quoted_numbers=dict(rounds=2,video_submissions=8,image_submissions=0,cloud_media=0),unknown_replay=False,publication=False))
        f.prepare(root/'R1');yield root,service

@pytest.fixture(scope='module')
def media(tmp_path_factory):return module('test_visual_h3_multiview_continuity_minute_v37').full_media.__wrapped__(tmp_path_factory)

def launch(run):
    q=f.PROJECT/'data/qa/h3_baseline_two_rounds_v38_20261109/CPU_TEST_FIXTURE.json';write(q,dict(fixture_only=True))
    write(run/'LAUNCH_APPROVAL.json',dict(schema='h3_baseline_round_technical_launch/v38',plan=f.bind(run/'PLAN.json'),authorization=f.bind(f.ROOT/'USER_AUTHORIZATION.json'),
        execution_sources=f._sources(),cpu_acceptance=f.bind(q),approved_for_technical_execution=True))

def finish_round(prepared,name,media):
    root,service=prepared;run=root/name;launch(run)
    for index,sid in enumerate(f.IDS):
        before=len(service.posts);f.tick(run,allow_submit=True);state=f.status(run)['shots'][index]
        assert len(service.posts)==before+1 and state['status']=='submitted'
        f.tick(run,allow_submit=True);assert len(service.posts)==before+1
        service.finish_video(state['prompt_id'],sid,media);f.collect_known(run)
    return f.tick(run,allow_submit=True)

def reviewed_r2_spec(root):
    run=root/'R1';final=f.read(run/'FINAL_RESULT.json')
    review=write(run/'ROOT_OVERALL_VIDEO_REVIEW.json',dict(schema='h3_baseline_overall_review/v38',review_completed_by='root_agent',overall_video_review_completed=True,
        allow_prepare_r2=True,final_result=f.bind(run/'FINAL_RESULT.json'),reviewed_video=final['file'],findings=['Explicit protocol fixture overall review, not a real model visual assessment.']))
    r2=root/'R2';rows=[]
    for row in f.read(run/'PLAN.json')['segments']:
        prompt=r2/'choices'/(row['id']+'.txt');prompt.parent.mkdir(parents=True,exist_ok=True);prompt.write_bytes(f.check(row['prompt']).read_bytes()+b'\n')
        rows.append(dict(id=row['id'],prompt=f.bind(prompt),first=row['baseline_first']))
    return write(r2/'ROUND_SPEC.json',dict(schema='h3_baseline_round_spec/v38',round='R2',r1_overall_review=review,segments=rows))

def test_R1_exact_seed_first_graph_and_reversible_two_insertions(prepared):
    root,service=prepared;run=root/'R1';p=f.read(run/'PLAN.json');base=f._baseline()
    assert not service.posts and sum(len(f.quotes(f.check(r['prompt']).read_bytes().decode('utf-8'))) for r in p['segments'])==10
    for row,b in zip(p['segments'],base):
        actual=f.check(row['prompt']).read_bytes();audit=f.read(f.check(row['byte_diff']));graph=f.read(run/'shots'/row['id']/'workflow_api.json')
        assert len(audit['insertions'])==2 and f.undo_patch(actual,audit)==b['actual_text'].encode('utf-8')
        assert graph['129']['inputs']['noise_seed']==b['baseline_seed']==row['seed'] and row['first_frame']['sha256']==b['baseline_first']['sha256']
        restored=deepcopy(graph);restored['condition']['inputs']['prompt']=b['template']['condition']['inputs']['prompt'];restored['ref_scene']['inputs']['image']=b['template']['ref_scene']['inputs']['image']
        for role in f.ROLES:restored['save_'+role]['inputs']['filename_prefix']=b['template']['save_'+role]['inputs']['filename_prefix']
        assert restored==b['template']
        anchor='声音轨按原句依次演出：'.encode('utf-8');assert actual.split(anchor)[1]==b['actual_text'].encode('utf-8').split(anchor)[1]
        assert actual.count(f.TEXT.encode('utf-8'))==1 and actual.count(f.GAZE[row['id']].encode('utf-8'))==1
        assert b['snapshot_newline_transport']['snapshot_CRLF']>0 and b['snapshot_newline_transport']['actual_request_CR']==0
    assert not (root/'R2/PLAN.json').exists()

def test_actual_HTTP_R1_then_overall_review_and_R2_eight_videos_no_images(prepared,media):
    root,service=prepared;one=finish_round(prepared,'R1',media)
    assert one['clock']['native_frames']==1448 and one['clock']['audio_samples']==2896000 and len(service.posts)==4
    with pytest.raises(OSError):f.prepare(root/'R2')
    assert not (root/'R2/PLAN.json').exists()
    reviewed_r2_spec(root);f.prepare(root/'R2');two=finish_round(prepared,'R2',media)
    assert two['clock']['native_frames']==1448 and len(service.posts)==8 and set(one['native_ids']).isdisjoint(two['native_ids'])
    clients=[r['client_id'] for r in service.posts];assert len(set(clients))==8
    old_clients={f.read(f.BASELINE/sid/'REQUEST.baseline.original.json').get('client_id') for sid in f.IDS};assert not old_clients.intersection(clients)
    assert all('condition' in request['prompt'] and request['prompt']['condition']['class_type']=='MiniMaxH3ImageToVideo' for request in service.posts)
    assert not list(root.rglob('SCENE*')) and not list(root.rglob('ROOT_*IMAGE*'))
    assert f.assemble(root/'R1')==one and f.assemble(root/'R2')==two

@pytest.mark.parametrize('pause',[False,True])
def test_known_ID_collects_after_current_authority_prompt_changed_without_new_POST(prepared,media,pause):
    root,service=prepared;run=root/'R1';launch(run);f.tick(run,allow_submit=True);pid=f.status(run)['shots'][0]['prompt_id'];folder=run/'shots/S01'
    original=[f.bind(folder/n) for n in ('workflow_api.json','GRAPH_BINDING.json','REQUEST.json','CLAIM.json','RESPONSE.json')]
    (root/'USER_AUTHORIZATION.json').write_text('invalid current authorization',encoding='utf-8');Path(f.read(run/'PLAN.json')['segments'][0]['prompt']['path']).write_text('changed current prompt',encoding='utf-8')
    if pause:write(run/'PAUSE.json',dict(reason='fixture'))
    service.finish_video(pid,'S01',media);v=f.tick(run,allow_submit=True)
    assert v['technical_saved']==1 and v['dispatch']==('paused' if pause else 'blocked_current_inputs') and len(service.posts)==1
    assert [f.bind(b['path']) for b in original]==original and f.read(folder/'RESULT.json')['prompt_id']==pid

def test_uncertain_POST_preserves_original_claim_and_never_uses_R2_as_retry(prepared):
    root,service=prepared;run=root/'R1';launch(run);service.drop=True;f.tick(run,allow_submit=True)
    assert f.status(run)['shots'][0]['status']=='outcome_unknown' and len(service.posts)==1
    assert f.tick(run,allow_submit=True)['dispatch']=='unknown_or_failed_native_preserved' and len(service.posts)==1
    with pytest.raises((ValueError,OSError)):f.prepare(root/'R2')
    with pytest.raises(ValueError):f.prepare(root/'R1_retry')
    assert len(service.posts)==1 and not (root/'R2/PLAN.json').exists()

def test_conflicting_staged_first_bytes_stop_before_claim_or_POST(prepared):
    root,service=prepared;run=root/'R1';launch(run);p=f.read(run/'PLAN.json');row=p['segments'][0];target=Path(p['config']['input_root'])/row['input_name'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'conflicting first')
    with pytest.raises(ValueError):f.tick(run,allow_submit=True)
    assert len(service.posts)==0 and target.read_bytes()==b'conflicting first' and not (run/'shots/S01/CLAIM.json').exists()

@pytest.mark.parametrize('field',['model','seed','first','source_prompt'])
def test_any_undeclared_change_blocks_new_native_call(prepared,field):
    root,service=prepared;run=root/'R1';launch(run)
    if field in ('model','seed'):
        p=run/'shots/S01/workflow_api.json';v=f.read(p)
        if field=='model':v['127']['inputs']['unet_name']='foreign_model.safetensors'
        else:v['129']['inputs']['noise_seed']+=1
        write(p,v)
    elif field=='first':Path(f.read(run/'PLAN.json')['segments'][0]['first']['path']).write_bytes(b'changed source first')
    else:Path(f.read(run/'PLAN.json')['segments'][0]['prompt']['path']).write_text('changed prompt',encoding='utf-8')
    assert f.tick(run,allow_submit=True)['dispatch']=='blocked_current_inputs' and not service.posts

def test_wrong_native_history_never_saves_or_dispatches_successor(prepared,media):
    root,service=prepared;run=root/'R1';launch(run);f.tick(run,allow_submit=True);pid=f.status(run)['shots'][0]['prompt_id'];service.finish_video(pid,'S01',media);service.histories[pid]['prompt'][2]={}
    with pytest.raises(ValueError):f.collect_known(run)
    assert len(service.posts)==1 and not (run/'shots/S01/RESULT.json').exists()

def test_single_runner_and_shared_GPU_locks(prepared):
    root,service=prepared;run=root/'R1';launch(run)
    with f.jobs.run_lock(run,'RUNNER.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.execute(run,poll_seconds=1,max_seconds=1)
    f.SHARED_GPU.mkdir(exist_ok=True)
    with f.jobs.run_lock(f.SHARED_GPU,'GPU.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.tick(run,allow_submit=True)
    assert not service.posts

def test_R2_cannot_prepare_from_unfinished_or_wrongly_bound_review(prepared):
    root,service=prepared;r1=root/'R1'
    write(r1/'ROOT_OVERALL_VIDEO_REVIEW.json',dict(schema='h3_baseline_overall_review/v38',overall_video_review_completed=True,allow_prepare_r2=True))
    with pytest.raises((ValueError,OSError)):f.prepare(root/'R2')
    assert not (root/'R2/PLAN.json').exists() and not service.posts
