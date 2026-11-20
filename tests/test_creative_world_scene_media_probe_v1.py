"""Only synthetic verifier outputs. No service calls, media, pixels or claims."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from scripts import creative_world_scene_media_probe_v1 as m
from tests.test_creative_world_scene_context_v1 import case as world_case


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError('media preparation tests must never call a service')
    monkeypatch.setattr(socket.socket, 'connect', deny); monkeypatch.setattr(socket, 'create_connection', deny)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, ensure_ascii=False), 'utf8')
    return str(path)


@pytest.fixture
def case(tmp_path):
    goal, script = world_case.__wrapped__(); project = Path(m.PROJECT)
    root = tmp_path / 'text'; root.mkdir()
    setup = {'goal_sha256': m.world.digest(goal), 'OFFLINE': True}
    natives = {'goal': goal, 'raw_script': script, 'compiled_script': m.world.compile_script(script, goal)['script'], 'setup': setup}
    paths = {k: write(root/(k+'.json'), v) for k,v in natives.items()}
    handoff = Path(write(root/'TEXT_HANDOFF.json', {'OFFLINE': True}))
    text = {'valid': True, 'accepted': True, 'status': 'text_ready_for_director', 'handoff_path': str(handoff),
        'handoff_sha256': m.sha(handoff), 'paths': paths, 'identity': {
            'native_goal_sha256': m.world.digest(goal), 'native_script_sha256': m.world.digest(script),
            'compiled_script_sha256': m.world.digest(natives['compiled_script']), 'native_setup_sha256': m.world.digest(setup)}}
    prodroot = tmp_path/'production'; cert = Path(write(prodroot/'HANDOFF.json', {'OFFLINE': True}))
    proof = Path(write(prodroot/'NATIVE_PERFORMANCE.json', {'OFFLINE': 'synthetic native fixture, not real approval'}))
    catalog = m.read(m.CATALOG); refs = []
    actors = goal['whole_plan']['characters']
    for i, (asset_id, version) in enumerate(m.FIXED_ASSETS, 1):
        row = {'picture': i, 'asset_id': asset_id, 'version': version}
        if i == 1: row.update(role='environment', scene_ids=[goal['whole_plan']['scenes'][0]['id']])
        else:
            actor = next(a for a in actors if a['id'] == ('c_employee' if i==2 else 'c_manager'))
            asset = next(a for a in catalog['assets'] if a['asset_id'] == asset_id)
            original = Path(asset['evidence_paths'][0]).parent/'IMAGEGEN_REQUEST.json'
            quote = '方澄，成年中国职场女性' if i==2 else '林屿，成年中国职场男性'
            row.update(role='character', character_id=actor['id'], name=actor['name'],
                gender_presentation=actor['profile']['gender_presentation'], asset_presentation='female' if i==2 else 'male',
                gender_mapping_reviewed=True, asset_gender_evidence={'path': str(original), 'file_sha256': m.sha(original), 'quote': quote})
        refs.append(row)
    prompt = 'OFFLINE synthetic already-reviewed prompt; no actual generation.'
    production = {'schema': m.PRODUCTION_VERSION, 'valid': True, 'accepted': True, 'status': 'first_segment_ready_for_media',
        'text_handoff_sha256': text['handoff_sha256'], **text['identity'], 'production_handoff_path': str(cert),
        'production_handoff_sha256': m.sha(cert), 'proof_files': [{'path':str(proof),'file_sha256':m.sha(proof)}],
        'segment_ordinal':1,'beat_id':script['beats'][0]['id'],'source_refs':list(m.sources.catalog(script))[:2],
        'duration_seconds':8,'actual_video_prompt':prompt,'video_prompt_sha256':m.text_sha(prompt),'reference_map':refs,
        'story_id':'legal_scoped_call634_same_story'}
    service = tmp_path/'service'
    snap = {'read_only':True,'queue':{'queue_running':[],'queue_pending':[]},
        'h3_model_names':['minimax_h3_ref2va_pruned_int8_convrot.safetensors'],
        'system_stats':{'argv':['--offline','--preview-method','none','--input-directory',str(service/'input'),'--output-directory',str(service/'output')]}}
    config = m.Config(str(root),str(prodroot),str(tmp_path/'prepared'),20261015, service_root=str(service))
    return config,text,production,snap


def prepare(case):
    cfg,text,prod,snapshot = case
    return m.prepare(cfg,text_verifier=lambda root:deepcopy(text),production_verifier=lambda root,**kw:deepcopy(prod),
        service_snapshot=snapshot,offline_test=True)


def test_prepare_exact_native_prompt_three_actual_assets_and_no_submit_or_old_tail(case):
    cfg,text,prod,_ = case; result = prepare(case); output=Path(cfg.output_root)
    assert result['synthetic'] and not result['eligible_for_root_single_submit_review']
    assert result['media_claim_created'] is False and result['media_submissions'] == 0
    assert (output/'PROMPT.txt').read_text('utf8') == prod['actual_video_prompt']
    graph=m.read(output/'workflow_api.json'); condition=graph['condition']['inputs']
    assert (condition['width'],condition['height'],condition['length'])==(1280,704,192)
    refs=m.read(output/'REFERENCE_MAP.json')
    assert [r['picture'] for r in refs] == [1,2,3] and refs[1]['name']==prod['reference_map'][1]['name']
    assert all(m.sha(r['source_path'])==m.sha(r['input_path']) for r in refs)
    assert not result['old_rejected_tail_used'] and not any(n['class_type']=='MiniMaxH3AddGuide' for n in graph.values())
    assert not (output/'RUN_CLAIM.json').exists() and not result['native1280_generation_verified']


@pytest.mark.parametrize('fault',['text_unknown','other_script','prompt_changed','reordered_references','actor_mismatch','gender_evidence','bad_duration','active_gpu'])
def test_missing_qualification_wrong_native_and_reference_order_block_before_writes(case,fault):
    cfg,text,prod,snap=case
    if fault=='text_unknown': text['status']='halt_review_uncertain'
    elif fault=='other_script': prod['native_script_sha256']='0'*64
    elif fault=='prompt_changed': prod['actual_video_prompt']+='changed'
    elif fault=='reordered_references': prod['reference_map'][1],prod['reference_map'][2]=prod['reference_map'][2],prod['reference_map'][1]
    elif fault=='actor_mismatch': prod['reference_map'][1]['name']='old-name-guessed-from-node'
    elif fault=='gender_evidence': prod['reference_map'][1]['asset_gender_evidence']['quote']='not original request'
    elif fault=='bad_duration': prod['duration_seconds']=6
    else: snap['queue']['queue_running']=[{'prompt_id':'preserve-other-task'}]
    with pytest.raises(m.PreparationBlocked):prepare(case)
    assert not Path(cfg.output_root).exists() and not Path(cfg.service_root,'input').exists()


def test_live_never_accepts_injected_mock_verifier(case):
    cfg,text,prod,snap=case
    with pytest.raises(m.PreparationBlocked):m.prepare(cfg,text_verifier=lambda root:text,production_verifier=lambda root,**kw:prod,service_snapshot=snap)
    assert not Path(cfg.output_root).exists()


def test_existing_preparation_and_bound_proof_changes_cannot_be_reused(case):
    cfg,text,prod,_=case; prepare(case)
    with pytest.raises(m.PreparationBlocked):prepare(case)
    assert not Path(cfg.output_root,'RUN_CLAIM.json').exists()
    path=Path(prod['proof_files'][0]['path']);path.write_text('changed','utf8')
    with pytest.raises(m.PreparationBlocked):m.verified_sources(cfg,text_verifier=lambda root:text,production_verifier=lambda root,**kw:prod,offline_test=True)


def test_unavailable_fixed_module_cli_is_blocked_without_claim(case,monkeypatch,capsys):
    cfg,_,_,_=case
    def unavailable(name):raise ModuleNotFoundError('actual production verifier not ready')
    monkeypatch.setattr(m.importlib,'import_module',unavailable)
    assert m.main(['prepare','--text-root',cfg.text_root,'--production-root',cfg.production_root,'--output-root',cfg.output_root,'--seed','1'])==2
    assert json.loads(capsys.readouterr().out)['status']=='blocked_before_media_preparation'
    assert not Path(cfg.output_root).exists()
