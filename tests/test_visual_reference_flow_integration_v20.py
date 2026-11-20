"""New-route integration, using local protocol fixtures only (no GPU)."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_visual_h3_reference_bundle_v20 import setup as bundle_setup
from test_visual_asset_handoff_v3 import material, server, client
from src.content_factory import visual_asset_pipeline_v3 as assets
from src.content_factory import visual_asset_handoff_v3 as handoff
from src.content_factory import visual_h3_reference_delivery_v20 as direct
from scripts import run_visual_asset_watch_v3 as watch


def ready_assets(s, *, three=False):
    packet=deepcopy(s['packet'])
    for person in packet['characters']:
        person['required_views']=({'adult':['front','left_profile'],'child':['front']}.get(person['id'],[]))
    packet['places'][0]['required_views']=['front','side']
    packet['shots'][0].update(start=0,end=5)
    if three:
        packet['characters'].append(dict(id='third',name='第三人',design_version='v1',required_views=['front']))
        packet['shots'][0]['visible_cast'].append('third')
        packet['shots'][0]['character_views']['third']='front'
        packet['scenes'][0]['cast'].append('third')
        s['add']('third','character','front',color='green')
    run=s['tmp']/'new_asset_run'
    assets.prepare(run,packet,dict(library=str(s['lib']),h3_delivery=assets.REFERENCE_DELIVERY))
    return run


@pytest.mark.parametrize('three',[False,True])
def test_reference_asset_tick_skips_composition_and_two_person_limit(bundle_setup,monkeypatch,three):
    run=ready_assets(bundle_setup,three=three)
    monkeypatch.setattr(assets,'compile_bindings',lambda *a,**k:pytest.fail('old composition invoked'))
    monkeypatch.setattr(assets,'_prepare_first_frame',lambda *a,**k:pytest.fail('unexpected first image'))
    result=assets.tick(run)
    assert result['status']=='reference_assets_ready'
    assert set(result['reference_assets'])=={'shot1'}
    assert not (run/'H3_INPUT_READY.json').exists()
    assert not (run/'SHOT_BINDINGS.json').exists()
    assert assets.run_until_idle(run)['status']=='reference_assets_ready'


def test_original_source_not_planner_camera_or_action_rewrite(tmp_path):
    accepted,bible,source=material(tmp_path)
    scene=accepted['bound']['script']['scenes'][0]
    scene.pop('camera')
    source_path=Path(source['path'])
    handoff._write(source_path,accepted)
    source['sha256']=handoff._sha(source_path)
    accepted['binding']['candidate_sha256']=handoff._legacy(accepted['bound'])
    handoff._write(source_path,accepted);source['sha256']=handoff._sha(source_path)
    with server() as fake:
        output=fake.output
        def altered(payload):
            value=output(payload)
            if 'shots' in value:
                for row in value['shots']:row['visual_prompt']='LOCKED OFF TRIPOD invented motion'
            return value
        fake.output=altered
        packet=client(fake,source_prompt_contract='source_window/v20').plan_episode(
            accepted,bible,'book1',source,evidence_dir=tmp_path/'planning')
    shot=packet['shots'][0]
    prompt=shot['complete_video_prompt']
    assert 'Alice opens the wooden door.' in prompt
    assert 'Hello.' in prompt and 'A remembered voice.' in prompt
    assert 'LOCKED OFF' not in prompt and 'TRIPOD' not in prompt
    assert shot['source_prompt_contract']=='source_window/v20'


def test_new_policy_selects_reference_delivery_and_source_passthrough(tmp_path):
    handoff._write(tmp_path/'text'/'PLAN.json',{'text':'unchanged'})
    config={'library':str(tmp_path/'lib')}
    policy=handoff.make_policy(tmp_path/'text','book',config,actor='admin',user_statement='生成参考图后制作视频')
    assert policy['pipeline_config']['h3_delivery']==assets.REFERENCE_DELIVERY
    assert policy['planning']['source_prompt_contract']=='source_window/v20'
    assert policy['h3_delivery']==dict(mode=assets.REFERENCE_DELIVERY,video_enabled=False)
    assert config=={'library':str(tmp_path/'lib')}
    assert not any((tmp_path/'text').glob('**/REQUEST.json'))


def test_explicit_legacy_policy_remains_separate(tmp_path):
    handoff._write(tmp_path/'text'/'PLAN.json',{})
    p=handoff.make_policy(tmp_path/'text','book',{},actor='admin',user_statement='旧入口',
        h3_delivery=dict(mode='first_frame/v3',video_enabled=False))
    assert p['pipeline_config']['h3_delivery']=='first_frame/v3'
    assert 'source_prompt_contract' not in p['planning']
    with pytest.raises(ValueError,match='asset_and_video'):
        handoff.make_policy(tmp_path/'text','book',dict(h3_delivery='first_frame/v3'),
            actor='admin',user_statement='must not silently migrate')


def fake_watch(monkeypatch,tmp_path,*,existing=False):
    run=tmp_path/'data/visual_asset_pipeline/runs/case'
    run.mkdir(parents=True)
    policy=dict(enabled=True,text_run=str(tmp_path/'text'),
                h3_delivery=dict(mode=assets.REFERENCE_DELIVERY,video_enabled=False))
    monkeypatch.setattr(watch,'validate_policy',lambda *a:None)
    monkeypatch.setattr(watch,'enqueue_accepted',lambda *a,**k:dict(status='scanned',created=[str(run)],reused=[],blocked=[]))
    monkeypatch.setattr(assets,'status',lambda *a:dict(plan=dict(config=dict(h3_delivery=assets.REFERENCE_DELIVERY))))
    monkeypatch.setattr(assets,'tick',lambda *a,**k:dict(status='reference_assets_ready'))
    calls=[]
    monkeypatch.setattr(direct,'prepare',lambda *a,**k:(calls.append(('prepare',a,k)) or dict(shots=[])))
    monkeypatch.setattr(direct,'submit_next',lambda *a:pytest.fail('disabled route submitted'))
    h3=tmp_path/'data/video_generation'/direct.PREFIX/run.name
    if existing:
        h3.mkdir(parents=True);(h3/'PLAN.json').write_text('{}')
    return policy,run,h3,calls


def test_watch_uses_reference_route_without_legacy_handoff(monkeypatch,tmp_path):
    policy,run,h3,calls=fake_watch(monkeypatch,tmp_path)
    result=watch.scan_once(tmp_path,policy,execute=True,reviewer=object())
    assert calls[0][1]==(run,h3)
    assert calls[0][2]['config']['video_enabled'] is False
    assert result['h3_prepared'][0]['status']=='reference_delivery'


def test_watch_collects_original_reference_id_before_new_work(monkeypatch,tmp_path):
    policy,run,h3,calls=fake_watch(monkeypatch,tmp_path,existing=True)
    monkeypatch.setattr(assets,'tick',lambda *a,**k:pytest.fail('unknown original must not trigger new work'))
    monkeypatch.setattr(direct,'poll_collect',lambda *a:dict(paused=False,shots=[dict(status='outcome_unknown')]))
    result=watch.scan_once(tmp_path,policy,execute=True,reviewer=object())
    assert calls==[]
    assert result['h3_prepared'][0]['status']=='original_reference_result_retained'


@pytest.mark.parametrize('reason',['paused','blocked_upstream_changed'])
def test_executor_retains_known_job_until_saved_after_stop(monkeypatch,tmp_path,reason):
    values=[dict(paused=reason=='paused',dispatch=reason if reason!='paused' else None,
                 shots=[dict(status='running',prompt_id='known-original')],technical_saved=0,total=1,video_enabled=True),
            dict(paused=reason=='paused',dispatch=reason if reason!='paused' else None,
                 shots=[dict(status='technical_saved',prompt_id='known-original')],technical_saved=1,total=1,video_enabled=True)]
    monkeypatch.setattr(direct,'poll_collect',lambda *a:values.pop(0))
    monkeypatch.setattr(direct,'submit_next',lambda *a:pytest.fail('stop must not submit successor'))
    monkeypatch.setattr(direct.time,'sleep',lambda *a:None)
    run=tmp_path/'paused_reference_job';run.mkdir()
    result=direct.execute(run,poll_seconds=1,max_seconds=10)
    assert result['technical_saved']==1 and values==[]
