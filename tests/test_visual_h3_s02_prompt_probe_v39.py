"""Single-ID real local HTTP protocol tests; no production service/model."""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,shutil
import pytest
from src.content_factory import visual_h3_s02_prompt_probe_v39 as f

REAL_SOURCE=f.SOURCE;REAL_RUN=f.RUN
def module():
    p=Path(__file__).with_name('test_visual_h3_multiview_continuity_minute_v37.py');s=importlib.util.spec_from_file_location('v39_HTTP_fixture',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8');return f.bind(p)

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    with module().server(tmp_path) as (server,url):
        source=tmp_path/'source_R2';folder=source/'shots/S02';folder.mkdir(parents=True);original=REAL_SOURCE/'shots/S02'
        for name in ('REQUEST.json','workflow_api.json','GRAPH_BINDING.json','STATE.json','HISTORY.json','RESULT.json','first_input.png'):shutil.copyfile(original/name,folder/name)
        p=f.read(REAL_SOURCE/'PLAN.json');pause=tmp_path/'old_pause.json';pause.write_text('immutable old pause',encoding='utf-8');gpu=tmp_path/'gpu'
        p['config'].update(service_url=url,input_root=str(server.inputs),output_root=str(server.outputs),gpu_lock_root=str(gpu),protected_pause_path=str(pause));p['protected_pause']=f.bind(pause)
        row=next(r for r in p['segments'] if r['id']=='S02');row['first_frame']=f.bind(folder/'first_input.png');write(folder/'GRAPH_BINDING.json',row);write(source/'PLAN.json',p)
        state=f.read(folder/'STATE.json');state['plan_sha256']=f.digest(p);write(folder/'STATE.json',state)
        run=tmp_path/'probe';run.mkdir();shutil.copyfile(REAL_RUN/'PROMPT.txt',run/'PROMPT.txt');scope=f.read(REAL_RUN/'ROOT_USER_SCOPE.json');scope['source']=str(folder);scope['user_statement']='Explicit single-ID HTTP protocol fixture, not production authorization';write(run/'ROOT_USER_SCOPE.json',scope)
        monkeypatch.setattr(f,'RUN',run);monkeypatch.setattr(f,'SOURCE',source);monkeypatch.setattr(f,'LOCAL_SERVICE',url);monkeypatch.setattr(f,'SHARED_GPU',gpu)
        f.prepare(run);yield run,server

@pytest.fixture(scope='module')
def media(tmp_path_factory):return module().full_media.__wrapped__(tmp_path_factory)

def launch(run):
    q=f.PROJECT/'data/qa/h3_s02_prompt_probe_v39_20261110/CPU_FIXTURE.json';write(q,dict(fixture_only=True))
    p=f.read(run/'PLAN.json');write(run/'LAUNCH_APPROVAL.json',dict(schema='h3_s02_probe_technical_launch/v39',plan=f.bind(run/'PLAN.json'),authorization=p['authorization'],
        execution_sources=f._sources(),cpu_acceptance=f.bind(q),approved_for_technical_execution=True))

def test_exact_R2_recipe_first_seed_quotes_then_single_HTTP_save(prepared,media):
    run,server=prepared;p=f.read(run/'PLAN.json');g=f.read(run/'shots/S02/workflow_api.json');old=f.read(f.SOURCE/'shots/S02/REQUEST.json')['prompt'];restored=deepcopy(g)
    restored['condition']['inputs']['prompt']=old['condition']['inputs']['prompt'];restored['ref_scene']['inputs']['image']=old['ref_scene']['inputs']['image']
    for role in ('video','audio','first','last'):restored['save_'+role]['inputs']['filename_prefix']=old['save_'+role]['inputs']['filename_prefix']
    assert restored==old and g['129']['inputs']['noise_seed']==45905597282583733 and p['shot']['first_frame']['sha256']==f.FIRST_SHA
    assert f.base.quotes(g['condition']['inputs']['prompt'])==f.base.quotes(old['condition']['inputs']['prompt']) and not server.posts
    launch(run);f.tick(run,allow_submit=True);pid=f.status(run)['shot']['prompt_id'];assert len(server.posts)==1
    f.tick(run,allow_submit=True);assert len(server.posts)==1
    server.finish_video(pid,'S02',media);result=f.tick(run,allow_submit=True)
    assert result['native_id']==pid and result['postprocessing']==[] and set(result['files'])=={'video','audio','first','last'}
    assert result['timing']['native_frames']==362 and result['file']['sha256']==result['files']['video']['sha256'] and len(server.posts)==1
    assert f.finalize(run)==result

def test_known_ID_collects_after_current_prompt_authority_and_pause_change(prepared,media):
    run,server=prepared;launch(run);f.tick(run,allow_submit=True);pid=f.status(run)['shot']['prompt_id'];folder=run/'shots/S02';before=[f.bind(folder/n) for n in ('REQUEST.json','CLAIM.json','RESPONSE.json','workflow_api.json')]
    (run/'PROMPT.txt').write_text('changed current prompt',encoding='utf-8');(run/'USER_AUTHORIZATION.json').write_text('invalid current auth',encoding='utf-8');write(run/'PAUSE.json',dict(reason='fixture'))
    server.finish_video(pid,'S02',media);v=f.tick(run,allow_submit=True)
    assert v['native_id']==pid and len(server.posts)==1 and [f.bind(b['path']) for b in before]==before

def test_uncertain_POST_never_replays_or_creates_alternate_scope(prepared):
    run,server=prepared;launch(run);server.drop=True;f.tick(run,allow_submit=True)
    assert f.status(run)['shot']['status']=='outcome_unknown' and len(server.posts)==1
    assert f.tick(run,allow_submit=True)['dispatch']=='unknown_or_failed_native_preserved' and len(server.posts)==1
    assert f.prepare(run)['shot']['status']=='outcome_unknown'
    with pytest.raises(ValueError):f.prepare(run.parent/'alternate')
    assert len(server.posts)==1

def test_conflicting_first_staging_stops_before_claim(prepared):
    run,server=prepared;launch(run);p=f.read(run/'PLAN.json');target=Path(p['config']['input_root'])/p['shot']['input_name'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'conflicting pixels')
    with pytest.raises(ValueError):f.tick(run,allow_submit=True)
    assert not server.posts and not (run/'shots/S02/CLAIM.json').exists() and target.read_bytes()==b'conflicting pixels'

def test_shared_GPU_and_single_runner_locks(prepared):
    run,server=prepared;launch(run)
    with f.jobs.run_lock(run,'RUNNER.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.execute(run,poll_seconds=1,max_seconds=1)
    f.SHARED_GPU.mkdir(exist_ok=True)
    with f.jobs.run_lock(f.SHARED_GPU,'GPU.lock'):
        with pytest.raises(f.jobs.JobBusyError):f.tick(run,allow_submit=True)
    assert not server.posts

def test_wrong_graph_or_history_cannot_save_or_submit_another_ID(prepared,media):
    run,server=prepared;launch(run);f.tick(run,allow_submit=True);pid=f.status(run)['shot']['prompt_id'];server.finish_video(pid,'S02',media);server.histories[pid]['prompt'][2]={}
    with pytest.raises(ValueError):f.collect_known(run)
    assert len(server.posts)==1 and not (run/'shots/S02/RESULT.json').exists()
