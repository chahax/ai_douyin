import json
from pathlib import Path
import pytest
from src.content_factory.creative_plan_patch import repair_paths_for_error, timing_budget, build_patch_schema, apply_plan_patch
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_action_plan_v2 import sample
from scripts import resume_failed_plan_production as recovery


def test_timing_error_scopes_only_named_beat_and_exposes_shared_budget():
    plan,script,manifest=sample()
    error='action_plan无法排入且不能压缩动作/hold: '+json.dumps({'beat_id':script['beats'][1]['id']})
    scope=repair_paths_for_error(plan,error)
    assert scope==['beats.1.groups']
    schema=build_patch_schema(plan,scope)
    paths=[path for branch in schema['properties']['patches']['items']['oneOf'] for path in branch['properties']['path']['enum']]
    assert paths==scope
    rows=timing_budget({'script':script},plan)
    assert len(rows)==len(script['beats'])
    for row in rows:
        assert row['maximum_action_and_hold_seconds']+row['minimum_dialogue_seconds']==pytest.approx(row['shot_seconds'])


def test_boxed_number_still_rejected_instead_of_silently_cast_to_pass():
    from src.content_factory.creative_plan_patch import plan_digest
    plan,_,_=sample()
    patch={'source_sha256':plan_digest(plan),'patches':[{'path':'beats.0.groups.0.duration_seconds','value':['4']}]}
    with pytest.raises(CreativeContractError,match='PLAN_PATCH_VALUE_SCHEMA'):
        apply_plan_patch(plan,patch)


def fixture(tmp_path,monkeypatch):
    state={'status':'needs_attention','last_error':'PLAN_PATCH_VALUE_SCHEMA',
        'calls_started':14,'reported_tokens':195507,'revision_rounds':1,'contract_repairs_used':5,
        'max_calls':20,'max_total_tokens':500000,'max_revisions':5,'max_contract_repairs':8,
        'rule_registry_binding':{'registry_dir':'old'},'stages':[{'name':'static_visual_manifest'},{'name':'writer_script'}]}
    write=lambda name,value:(tmp_path/name).write_text(json.dumps(value),encoding='utf-8')
    write('state.json',state);write('static_visual_manifest.json',{'output':{'schema':'static_visual_manifest_v2'}})
    write('director_state_plan__00.json',{'status':'response_received'})
    write('director_state_plan__00__contract_repair_b79373e4fad5__action_patch_merge.json',{'output':{'schema':'whole_film_action_plan_v2'}})
    write('writer_script__rule_activation.json',{'old':'binding'})
    monkeypatch.setattr(recovery,'bind_new_task',lambda:{'registry_dir':'new'})
    return state,write


def test_recovery_preserves_history_and_counters_and_repeated_prepare_is_idempotent(tmp_path,monkeypatch):
    before,_=fixture(tmp_path,monkeypatch)
    receipt=recovery.prepare(tmp_path)
    state=json.loads((tmp_path/'state.json').read_text(encoding='utf-8'))
    assert state['calls_started']==14 and state['reported_tokens']==195507
    assert state['contract_repairs_used']==5 and state['revision_rounds']==2
    assert state['max_calls']==20 and state['max_revisions']==5
    assert (tmp_path/'history/failed_plan_v15_20261001/director_state_plan__00.json').exists()
    assert not (tmp_path/'director_state_plan__00.json').exists()
    assert json.loads((tmp_path/'history/failed_plan_v15_20261001/state_before.json').read_text(encoding='utf-8'))==before
    assert recovery.prepare(tmp_path)==receipt


def test_recovery_cannot_replace_reviewed_plan(tmp_path,monkeypatch):
    _,write=fixture(tmp_path,monkeypatch);write('STATE_PLAN.json',{'approved':True})
    with pytest.raises(RuntimeError,match='已审核'):
        recovery.prepare(tmp_path)
    assert (tmp_path/'director_state_plan__00.json').exists()
