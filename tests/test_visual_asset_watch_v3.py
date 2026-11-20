"""Local watcher protocol tests against temporary HTTP fixtures, no real GPU."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import shutil

from PIL import Image

import pytest

from scripts import run_visual_asset_watch_v3 as watch
from src.web import visual_assets_panel_v3 as panel
from src.content_factory import visual_asset_handoff_v3 as handoff
from test_visual_asset_handoff_v3 import server,text_run


def ready_protocol_fixture(root,config):
    """Controlled image/acceptance data for contracts, never semantic production QA."""
    from src.content_factory import visual_h3_handoff_v3 as h3
    from src.content_factory.visual_shot_binding_v3 import compile_bindings
    run=panel.home(root)/'runs'/'ready_protocol';source=root/'data/fixture/ready_source.md';source.write_text('A fictional actor looks toward the door.')
    packet=dict(schema='visual_asset_packet/v3',book_id='book1',source=dict(path=str(source),sha256=panel.flow.file_sha(source)),
        characters=[dict(id='actor',design_version='v1',required_views=['front'])],places=[dict(id='room',design_version='v1',required_views=['front'])],
        shots=[dict(id='shot1',scene_id='s1',place_id='room',place_view='front',visible_cast=['actor'],character_views={'actor':'front'},visual_prompt='The actor looks toward the door.',start=0,end=5,audio=[dict(speaker='actor',mode='onscreen',text='你好。')])])
    panel.flow.prepare(run,packet,config)
    for entity,kind in [('actor','character'),('room','place')]:
        path=root/(entity+'.png');Image.new('RGB',(64,80),'gray').save(path)
        row=panel.library.register(config['library'],path,book_id='book1',entity_id=entity,kind=kind,view='front',design_version='v1')
        panel.library.review(config['library'],book_id='book1',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],decision='accepted',reviewer='protocol_fixture_only',checks={k:True for k in panel.library.REVIEW_CHECKS[kind]},evidence=dict(image_sha256=row['sha256'],observations=['Controlled fixture, not visual production approval.']))
    plan=panel.flow.status(run)['plan'];bindings=compile_bindings(packet,lambda req:panel.flow._lookup(plan,req));shot=bindings['shots'][0]
    frame=run/'frames/shot1.png';frame.parent.mkdir();shutil.copyfile(root/'actor.png',frame);sha=panel.flow.file_sha(frame)
    subreviews=[dict(decision='accepted',target_sha256=sha,reference_sha256=a['sha256'],checks={k:True for k in (h3.CHARACTER_CHECKS if a['kind']=='character' else h3.PLACE_CHECKS)},completion_known=True,outcome_unknown=False,visual_evidence=['Protocol fixture comparison only.']) for a in shot['references']]
    review=dict(decision='accepted',target_sha256=sha,reference_bindings=[dict(id=a['entity_id'],kind=a['kind'],sha256=a['sha256']) for a in shot['references']],
        checks={k:True for k in tuple(dict.fromkeys(h3.CHARACTER_CHECKS+h3.PLACE_CHECKS))},subreviews=subreviews,completion_known=True,outcome_unknown=False,visual_evidence=['Protocol fixture composition only.'])
    frames={'shot1':dict(path=str(frame),sha256=sha,binding_sha256=shot['binding_sha256'],review=review)}
    panel.flow.write(run/'SHOT_BINDINGS.json',bindings)
    panel.flow.write(run/'H3_INPUT_READY.json',dict(schema='h3_visual_input/v3',source=packet['source'],shots=bindings['shots'],first_frames=frames,old_batch_resume=False,publication=False))
    state=panel.read(run/'STATE.json');state.update(status='h3_inputs_ready',first_frames=frames);panel.flow.write(run/'STATE.json',state)
    workflow=root/'data/video_generation/h3_six_children_s01_720p_20261102/workflow_api.json';workflow.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(h3.DEFAULT_BASE,workflow)
    return run


def fixture_policy(root,fake):
    folder=root/'data'/'fixture';folder.mkdir(parents=True)
    run,accepted,bible,index=text_run(folder)
    config=panel.default_config(root);config['image_service']['service_url']=fake.url
    for key in ('input_root','output_root'):Path(config['image_service'][key]).mkdir(parents=True)
    panel.flow.write(Path(config['protected_pause_path']),dict(id='protected-old'))
    policy=handoff.make_policy(run,'book1',config,actor='qa-admin',user_statement='QA explicit media handoff.',planning=dict(service_url=fake.url))
    path=panel.home(root)/'policies'/'qa.json';panel.flow.write(path,policy)
    return run,policy,path


def test_disabled_default_never_dispatches_or_creates_root(tmp_path,monkeypatch):
    monkeypatch.setattr(watch,'enqueue_accepted',lambda *a,**k:pytest.fail('disabled dispatch'))
    value=watch.scan_once(tmp_path,dict(schema=handoff.POLICY_VERSION,enabled=False),execute=True)
    assert value['status']=='disabled' and not (tmp_path/'data').exists()


def test_real_http_scan_is_idempotent_and_does_not_execute_media_by_default(tmp_path,monkeypatch):
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake);old=(run/'PLAN.json').read_bytes()
        monkeypatch.setattr(watch.flow,'tick',lambda *a,**kw:pytest.fail('scan must not execute media'))
        first=watch.scan_once(tmp_path,policy);second=watch.scan_once(tmp_path,policy)
        assert len(first['created'])==1 and second['reused']==first['created'] and len(fake.chats)==3
        assert first['executed']==[] and (run/'PLAN.json').read_bytes()==old
        assert panel.read(Path(policy['pipeline_config']['protected_pause_path']))==dict(id='protected-old')


def test_execute_ticks_only_new_root_and_pauses_take_priority(tmp_path,monkeypatch):
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake);calls=[]
        monkeypatch.setattr(watch.flow,'tick',lambda run,**kw:calls.append(Path(run)) or dict(status='assets_ready'))
        result=watch.scan_once(tmp_path,policy,execute=True,reviewer=object())
        assert len(calls)==1 and calls[0].parent==panel.home(tmp_path)/'runs' and result['executed'][0]['status']=='assets_ready'
        panel.flow.write(panel.home(tmp_path)/'PAUSE.json',dict(actor='qa'))
        again=watch.scan_once(tmp_path,policy,execute=True,reviewer=object())
        assert again['status']=='paused' and len(calls)==1


@pytest.mark.parametrize('change',['legacy_run','legacy_gpu','remote_ollama','remote_images','cloud_review','changed_plan'])
def test_policy_cannot_expand_old_authorization_or_service_scope(tmp_path,change):
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake)
        if change=='legacy_run':policy['text_run']=str(tmp_path/'outside')
        if change=='legacy_gpu':policy['pipeline_config']['gpu_lock_root']=str(tmp_path/'other_gpu')
        if change=='remote_ollama':policy['planning']['service_url']='http://example.com'
        if change=='remote_images':policy['pipeline_config']['image_service']['service_url']='https://localhost:8190'
        if change=='cloud_review':policy['pipeline_config']['visual_review']['provider']='openai_compatible'
        if change=='changed_plan':panel.flow.write(run/'PLAN.json',dict(media=True))
        with pytest.raises(ValueError):watch.scan_once(tmp_path,policy)
        assert fake.chats==[]


def test_untrusted_enqueue_run_path_cannot_tick_old_h3(tmp_path,monkeypatch):
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake)
        monkeypatch.setattr(watch,'enqueue_accepted',lambda *a,**kw:dict(status='scanned',created=[str(tmp_path/'data/video_generation/h3_old')],reused=[],blocked=[]))
        monkeypatch.setattr(watch.flow,'tick',lambda *a,**kw:pytest.fail('old run must never tick'))
        with pytest.raises(ValueError,match='only_new_asset_runs'):watch.scan_once(tmp_path,policy,execute=True,reviewer=object())


def test_cli_independent_process_once_then_reuse_http_blackbox(tmp_path):
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake)
        cmd=[sys.executable,'-B','scripts/run_visual_asset_watch_v3.py','--policy',str(path),'--project-root',str(tmp_path),'--once','--launch-id','qa-launch']
        first=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        assert first.returncode==0,first.stdout+first.stderr
        created=json.loads(first.stdout)['created'];assert len(created)==1
        second=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        assert second.returncode==0,second.stdout+second.stderr
        assert json.loads(second.stdout)['reused']==created and len(fake.chats)==3
        folder=panel.home(tmp_path)/'watchers'/watch.fingerprint(policy)[:32]
        identity=panel.read(folder/'WORKER.json');ended=panel.read(folder/'WORKER_EXIT.json')
        assert identity['launch_id']=='qa-launch' and ended['exit_known'] is True and ended['pid']==identity['pid']


def test_cli_pause_and_disabled_make_no_model_request(tmp_path):
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake);panel.flow.write(panel.home(tmp_path)/'PAUSE.json',dict(actor='qa'))
        cmd=[sys.executable,'-B','scripts/run_visual_asset_watch_v3.py','--policy',str(path),'--project-root',str(tmp_path),'--watch','--interval','1']
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        assert result.returncode==0 and fake.chats==[]
        policy['enabled']=False;panel.flow.write(path,policy)
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        assert result.returncode==0 and json.loads(result.stdout)['status']=='disabled'


def test_cli_policy_outside_new_control_root_is_rejected(tmp_path):
    path=tmp_path/'outside.json';panel.flow.write(path,dict(schema=handoff.POLICY_VERSION,enabled=False))
    result=subprocess.run([sys.executable,'-B','scripts/run_visual_asset_watch_v3.py','--policy',str(path),'--project-root',str(tmp_path),'--once'],capture_output=True,text=True,timeout=15)
    assert result.returncode==2 and 'policy_outside_asset_root' in result.stdout


def test_watch_ready_freezes_new_h3_plan_disabled_and_snapshot_reads_it(tmp_path,monkeypatch):
    from src.content_factory import visual_h3_handoff_v3 as h3
    with server() as fake:
        text,policy,path=fixture_policy(tmp_path,fake);asset=ready_protocol_fixture(tmp_path,policy['pipeline_config'])
        protected=Path(policy['pipeline_config']['protected_pause_path']);old=protected.read_bytes()
        monkeypatch.setattr(watch,'enqueue_accepted',lambda *a,**k:dict(status='scanned',created=[],reused=[str(asset)],blocked=[]))
        monkeypatch.setattr(watch.flow,'tick',lambda run,**kw:panel.read(Path(run)/'STATE.json'))
        monkeypatch.setattr(h3,'_http',lambda *a,**k:pytest.fail('preparation must never dispatch H3'))
        receipt=watch.scan_once(tmp_path,policy,execute=True,reviewer=object())
        destination=tmp_path/'data/video_generation/visual_h3_v3'/asset.name
        assert receipt['h3_prepared']==[dict(asset_run=str(asset),run=str(destination),status='prepared',video_enabled=False)]
        plan=panel.read(destination/'PLAN.json');assert plan['config']['video_enabled'] is False and plan['old_batch_resume'] is False
        assert plan['asset_run']==str(asset) and protected.read_bytes()==old and fake.chats==[]
        assert not list(destination.rglob('CLAIM.json'))
        before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
        view=panel.snapshot(tmp_path);row=next(r for r in view['runs'] if r['path']==str(asset))
        assert row['h3_handoff']['status']=='prepared' and row['h3_handoff']['video_enabled'] is False
        assert {str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before
        again=watch.scan_once(tmp_path,policy,execute=True,reviewer=object())
        assert again['h3_prepared']==receipt['h3_prepared']


def test_nonexecute_scan_never_prepares_h3_even_if_existing_ready(tmp_path,monkeypatch):
    from src.content_factory import visual_h3_handoff_v3 as h3
    with server() as fake:
        run,policy,path=fixture_policy(tmp_path,fake)
        monkeypatch.setattr(h3,'prepare_from_ready',lambda *a,**k:pytest.fail('scan-only H3 prepare forbidden'))
        assert watch.scan_once(tmp_path,policy)['h3_prepared']==[]
