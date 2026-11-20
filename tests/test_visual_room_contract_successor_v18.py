"""One explicit new contract after the known loop; no additional model/GPU call."""
from copy import deepcopy
import json

import pytest

from src.content_factory import visual_room_contract_successor_v18 as f
from src.content_factory import visual_known_capacity_extension_v17 as old
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_review_v3 as v
from test_visual_known_capacity_extension_v17 import case,install_execution,write,upgrade_for_handoff


@pytest.fixture
def parent(case,monkeypatch):
    calls,styles=install_execution(case,monkeypatch,length_failure=True)
    old.prepare_extension(case['run'],authorization=case['authorization']);result=old.execute_extension(case['run'])
    assert result['room']['decision']=='unavailable' and len(calls)==1 and not styles
    case['authorization18']=dict(scope=f.VERSION,authorized_by='root_task',reason='One evidenced new compact contract; no increased cap.')
    return case


def test_prepare_keeps_both_original_and_v17_evidence_and_declares_total_four(parent):
    run=parent['run'];prior=(old._sidecar(run)/'RESULT.json').read_bytes();state=(run/'STATE.json').read_bytes()
    value=f.prepare_successor(run,authorization=parent['authorization18'])
    assert value['original_attempts']==3 and value['original_legacy_attempts']==2 and value['total_composition_attempts']==4
    assert value['review_config']['max_tokens']==4096 and value['room_prepared']['prompt_version']=='room_compare/v18'
    assert (old._sidecar(run)/'RESULT.json').read_bytes()==prior and (run/'STATE.json').read_bytes()==state


def test_exactly_one_new_compact_model_then_style_and_persistent_apply(parent,monkeypatch):
    calls,styles=install_execution(parent,monkeypatch);run=parent['run'];f.prepare_successor(run,authorization=parent['authorization18'])
    before=(old._sidecar(run)/'RESULT.json').read_bytes();result=f.execute_successor(run)
    assert len(calls)==len(styles)==1 and set(calls[0]['schema']['properties'])=={'checks','evidence'}
    assert result['room']['decision']=='accepted' and result['room']['observations']['people_count']==2
    receipt=f.apply_successor(run);frame=p.read(run/'STATE.json')['first_frames'][old.SHOT]
    assert frame['review_attempts']==4 and frame['original_review_attempts']==2 and frame['v17_attempts']==frame['v18_attempts']==1
    assert len(frame['review_history'])==3 and receipt['total_composition_attempts']==4
    old.verify_applied(frame['review']);f.verify_applied(frame['review'])
    assert (old._sidecar(run)/'RESULT.json').read_bytes()==before
    assert not (run/'H3_INPUT_READY.json').exists()


@pytest.mark.parametrize('field,value',[
    ('completion_marker_present',True),('finish_reason','stop'),('text','Not a repetition loop'),
])
def test_unrelated_or_changed_v17_failure_cannot_receive_a_successor(parent,field,value):
    file=old._sidecar(parent['run'])/'room_review/item_0000/MODEL_INCOMPLETE_NATIVE.json';raw=p.read(file);raw['native'][field]=value;write(file,raw)
    with pytest.raises(ValueError):f.prepare_successor(parent['run'],authorization=parent['authorization18'])


@pytest.mark.parametrize('unknown,room_false,style_accepted',[(True,False,True),(False,True,True),(False,False,False)])
def test_failure_stops_without_apply_or_repeat(parent,monkeypatch,unknown,room_false,style_accepted):
    calls,styles=install_execution(parent,monkeypatch,unknown=unknown,room_false=room_false,style_accepted=style_accepted)
    run=parent['run'];f.prepare_successor(run,authorization=parent['authorization18']);before=(run/'STATE.json').read_bytes()
    result=f.execute_successor(run);assert f.execute_successor(run)==result and len(calls)==1
    with pytest.raises(ValueError,match='not_fully_accepted'):f.apply_successor(run)
    assert (run/'STATE.json').read_bytes()==before


def test_persistent_room_native_tampering_is_rejected(parent,monkeypatch):
    install_execution(parent,monkeypatch);run=parent['run'];f.prepare_successor(run,authorization=parent['authorization18'])
    f.execute_successor(run);f.apply_successor(run);review=p.read(run/'STATE.json')['first_frames'][old.SHOT]['review']
    path=f._sidecar(run)/'room_review/item_0000/MODEL_NATIVE.json';path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='evidence_changed'):old.verify_applied(review)


def test_existing_successor_claim_is_not_replayed(parent,monkeypatch):
    calls,_=install_execution(parent,monkeypatch);run=parent['run'];f.prepare_successor(run,authorization=parent['authorization18'])
    write(f._sidecar(run)/'EXECUTION_CLAIM.json',dict(unknown=True))
    with pytest.raises(v.ReviewOutcomeUnknown):f.execute_successor(run)
    assert not calls


def test_v17_different_target_cannot_be_laundered_as_a_known_parent(parent):
    side=old._sidecar(parent['run']);result=p.read(side/'RESULT.json');result['room']['target_sha256']='0'*64;write(side/'RESULT.json',result)
    saved=p.read(side/'room_review/RESULTS.json');saved['results']=[result['room']];saved['results_sha256']=v.digest(saved['results']);write(side/'room_review/RESULTS.json',saved)
    with pytest.raises(ValueError,match='parent_source_binding_changed'):
        f.prepare_successor(parent['run'],authorization=parent['authorization18'])


def test_unresolved_prior_style_activity_blocks_a_new_style_budget(parent):
    write(old._sidecar(parent['run'])/'target_style_review/CLAIM.json',dict(unknown=True))
    with pytest.raises(ValueError,match='conflicting_or_style_activity'):
        f.prepare_successor(parent['run'],authorization=parent['authorization18'])


def test_compact_apply_then_normal_tick_and_h3_remain_qualified(case,monkeypatch):
    from src.content_factory import visual_h3_handoff_v3 as h3
    run=case['run'];_,bindings=upgrade_for_handoff(case)
    inventory_gate=p._verify_first_frame_inventory;inventory_source=p._review_layout_inventory
    generation_gate=p._verify_first_frame_generation;style_gate=p._verify_residence_style_receipt
    install_execution(case,monkeypatch,length_failure=True);old.prepare_extension(run,authorization=case['authorization']);old.execute_extension(run)
    install_execution(case,monkeypatch)
    f.prepare_successor(run,authorization=dict(scope=f.VERSION,authorized_by='root_task',reason='One explicit test successor.'))
    f.execute_successor(run);f.apply_successor(run);applied=p.file_sha(run/'STATE.json')
    monkeypatch.setattr(p,'_verify_first_frame_inventory',inventory_gate);monkeypatch.setattr(p,'_review_layout_inventory',inventory_source)
    monkeypatch.setattr(p,'_verify_first_frame_generation',generation_gate);monkeypatch.setattr(p,'_verify_residence_style_receipt',style_gate)
    monkeypatch.setattr(h3,'_ready_environment_guide',lambda asset,entity,shot,frame:frame['environment_guide'])
    assert p.tick(run,reviewer=None)['status']=='h3_inputs_ready' and p.file_sha(run/'STATE.json')!=applied
    snapshot,ready,current=h3.validate_ready(run)
    assert current==bindings and snapshot['state']['status']=='h3_inputs_ready'
    review=ready['first_frames'][old.SHOT]['review'];old.verify_applied(review)
    assert ready['first_frames'][old.SHOT]['review_attempts']==4
