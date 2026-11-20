"""New contact wrapper on real source data, mocked native HTTP, no model."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import h3_asset_flow_execution_v1 as original
from src.content_factory import h3_contact_execution_v1 as wrapper

ROOT=Path(__file__).resolve().parents[1]
INPUTS=ROOT/'data/video_generation/h3_contact_repair_s04_20261114_v1/inputs'
PROFILE=ROOT/'data/video_generation/h3_oral_revision_next_minute_20261113_v1/VOICE_PROFILES_V2.json'


@pytest.fixture
def env(tmp_path,monkeypatch):
    spec=flow.read(INPUTS/'INPUT_SPEC.json')
    cp=flow.freeze(tmp_path/'CONTACT.json',flow._bound(spec['contact_plan']))
    spec['contact_plan']=cp;sp=flow.freeze(tmp_path/'SPEC.json',spec);draft=tmp_path/'offline'
    assert flow.prepare(sp['path'],draft)['status']=='offline_draft_valid'
    cfg=dict(service_url='http://127.0.0.1:8190',input_root=str(tmp_path/'input'),output_root=str(tmp_path/'output'),
        gpu_lock_root=str(tmp_path/'gpu'),protected_pause_path=str(tmp_path/'PAUSE.json'),
        runs_root=str(tmp_path/'visual_h3_v3'),timeout=20,video_enabled=True)
    for key in ('input_root','output_root'):Path(cfg[key]).mkdir()
    Path(cfg['protected_pause_path']).write_text('{"old":true}',encoding='utf-8')
    run=Path(cfg['runs_root'])/'contact_S04';api=wrapper.for_run(run)
    monkeypatch.setattr(api,'_service_anchor',lambda m:cfg)
    state=dict(posts=0,gets=[],response=dict(prompt_id='contact_mock_UUID'))
    def http(config,route,value=None):
        if value is not None:
            assert route=='/prompt';state['posts']+=1
            if isinstance(state['response'],Exception):raise state['response']
            return deepcopy(state['response'])
        state['gets'].append(route)
        if route=='/system_stats':return dict(system=dict(argv=['main.py','--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']]))
        if route=='/queue':return dict(queue_running=[],queue_pending=[])
        if route.startswith('/history/'):return {}
        raise AssertionError('mock route '+route)
    monkeypatch.setattr(api.native,'_http',http)
    auth=flow.freeze(tmp_path/'AUTH.json',dict(real_calls=0,scope='mock_only'))
    return dict(api=api,run=run,cfg=cfg,draft=draft,cp=cp,state=state,auth=auth,tmp=tmp_path)


def prepare(e):return e['api'].prepare(e['run'],e['draft'],e['cfg'],prompt_profiles=flow.bind(PROFILE),authorization=e['auth'])


def approve(e):
    a=e['api'];flow.freeze(e['run']/'LAUNCH_APPROVAL.json',dict(schema=a.LAUNCH,request=a.launch_request(e['run']),
        approved_by='root',evidence=['CPU mock only; no native generation.']))


def test_private_module_isolated_and_actual_contact_reaches_positive(env):
    e=env;old=(original._derive,original._codes,original._load,original.prepare)
    assert prepare(e)['status']=='prepared'
    a=e['api'];_,plan,row,folder=a._load(e['run']);m=flow._bound(plan['live_manifest']);g=flow.read(folder/'workflow_api.json')
    assert (original._derive,original._codes,original._load,original.prepare)==old
    assert m['contact_continuity']['plan_binding']==e['cp']
    assert '米色破旧T恤男童' in m['compiled_prompt'] and '右后方唯一蓝色短袖男童' in m['compiled_prompt']
    assert '叶嫣儿持棉签，轻扶叶西决同一身体的前臂' in g['condition']['inputs']['prompt']
    assert set(m['actor_state']['camera_beats'][1]['actors'])=={'ye_yaner','ye_dong','ye_xijue'}
    assert len(m['references'])==9 and e['state']['posts']==0
    code={Path(v['path']).name for v in plan['code']}
    assert {'h3_contact_execution_v1.py','h3_contact_prompt_v1.py','h3_active_contact_v1.py'}<=code
    assert m['production_ready'] is False and m['voice_identity_locked'] is False


@pytest.mark.parametrize('action',['prepare','submit','collect_known','status','launch_request'])
def test_wrong_run_rejected_before_any_directory_lock_or_service_action(env,action):
    e=env;wrong=e['tmp']/'foreign_run';before=(e['state']['posts'],list(e['state']['gets']))
    with pytest.raises(ValueError,match='bound_to_one_run'):
        getattr(e['api'],action)(wrong)
    assert not wrong.exists() and (e['state']['posts'],e['state']['gets'])==before


def test_submit_recomputes_contact_and_rejects_changed_plan_without_claim(env):
    e=env;prepare(e);approve(e)
    Path(e['cp']['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):e['api'].submit(e['run'])
    assert e['state']['posts']==0 and not (e['run']/'shots/S04/CLAIM.json').exists()


def test_unknown_post_is_not_replayed_and_original_collector_ignores_changed_contact(env):
    e=env;prepare(e);approve(e);e['state']['response']=TimeoutError('controlled timeout')
    assert e['api'].submit(e['run'])['status']=='outcome_unknown'
    assert e['api'].submit(e['run'])['status']=='outcome_unknown' and e['state']['posts']==1
    Path(e['cp']['path']).write_text('{}',encoding='utf-8')
    assert e['api'].collect_known(e['run'])['status']=='outcome_unknown' and e['state']['posts']==1


def test_known_uuid_collection_stays_get_only_after_upstream_change(env):
    e=env;prepare(e);approve(e)
    assert e['api'].submit(e['run'])['prompt_id']=='contact_mock_UUID'
    Path(e['cp']['path']).write_text('{}',encoding='utf-8')
    assert e['api'].collect_known(e['run'],'contact_mock_UUID')['status']=='outcome_unknown'
    assert '/history/contact_mock_UUID' in e['state']['gets'] and e['state']['posts']==1
