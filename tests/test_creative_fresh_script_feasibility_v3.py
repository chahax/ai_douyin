"""Timing necessities only: neither mock prose nor estimates prove quality."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import creative_fresh_script_feasibility_v3 as feasibility
from tests import test_creative_fresh_legal_text_pipeline_v1 as fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket,"connect",lambda *a,**k:pytest.fail("offline only"))
    monkeypatch.setattr(socket,"create_connection",lambda *a,**k:pytest.fail("offline only"))


@pytest.fixture
def inputs():
    case=fixture.inputs()
    brief=fixture.fresh.compile_brief(fixture.theme_for(case['packet']),case['packet'],case['legal_context'],
        case['production_preferences'],case['source_binding_sha256'])
    return brief,{**case['production_preferences'],'whole_film_max_seconds':180}


def with_total(total):
    chunks=[]
    while total:
        current=min(48,total);chunks.append(current);total-=current
    return {'title':'离线长度边界','premise':'纯路由夹具，不是实际剧情质量金标。','beats':[
        {'id':'B1','trigger':'离线夹具','event':'按顺序说话','steps':[
            {'kind':'dialogue','speaker':'worker' if i%2==0 else 'hr','text':'汉'*count}
            for i,count in enumerate(chunks)]}]}


@pytest.mark.parametrize('text,blocked',[('汉'*48,False),('汉'*49,True),('a1'*24,False),('a1'*25,True),
    ('汉，'*48+'……?!',False),('汉，'*49,True)])
def test_single_window_reuses_exact_v2_spoken_count(inputs,text,blocked):
    brief,prefs=inputs;raw=fixture.raw_script();raw['beats'][0]['steps'][0]['text']=text
    report=feasibility.diagnose_script(raw,brief,prefs)
    assert report['dialogue_rows'][0]['spoken_character_count']==feasibility.source.spoken_characters({'text':text})
    assert bool(report['dialogue_window_diagnostics']['violations']) is blocked
    assert report['dialogue_rows'][0]['field_path']=='script.beats.0.steps.0.text'
    assert report['dialogue_rows'][0]['text']==text and report['dialogue_rows'][0]['speaker_id']=='worker'
    if blocked:
        with pytest.raises(feasibility.ScriptFeasibilityError):feasibility.validate_script(raw,brief,prefs)
    else:
        assert feasibility.validate_script(raw,brief,prefs)['production_feasible'] is None


@pytest.mark.parametrize('total,blocked',[(594,False),(595,True)])
def test_whole_speech_only_boundary_not_changed_by_split_units(inputs,total,blocked):
    brief,prefs=inputs;raw=with_total(total)
    report=feasibility.diagnose_script(raw,brief,prefs);whole=report['whole_speech_floor']
    assert not report['dialogue_window_diagnostics']['violations']
    assert whole['spoken_character_count']==total and whole['estimated_speech_only_seconds']==total/3.3
    assert whole['exceeds_whole_speech_floor'] is blocked
    assert whole['production_feasible'] is None and whole['reaction_and_action_duration_known'] is False
    assert report['creative_quality_passed'] is False and report['human_quality_approved'] is False
    if blocked:
        with pytest.raises(feasibility.ScriptFeasibilityError) as caught:feasibility.validate_script(raw,brief,prefs)
        assert [r['code'] for r in caught.value.detail['issues']]==['WHOLE_FILM_SPEECH_MINIMUM_EXCEEDED']
    else:
        assert whole['remaining_before_reaction_and_action_seconds']==0
        assert report['status']=='necessary_conditions_satisfied_only'


def test_local_and_whole_defects_are_reported_together(inputs):
    brief,prefs=inputs;raw=with_total(700);raw['beats'][0]['steps'][0]['text']+='额外'
    with pytest.raises(feasibility.ScriptFeasibilityError) as caught:feasibility.validate_script(raw,brief,prefs)
    detail=caught.value.detail
    assert {row['code'] for row in detail['issues']}=={'SCRIPT_DIALOGUE_WINDOW_EXCEEDED','WHOLE_FILM_SPEECH_MINIMUM_EXCEEDED'}
    assert detail['dialogue_window_diagnostics']['violations'][0]['text']==raw['beats'][0]['steps'][0]['text']
    assert detail['whole_speech_floor']['spoken_character_count']==702


def test_policy_provenance_is_the_original_normal_timing_predicate(inputs):
    _,prefs=inputs;policy=feasibility.build_policy(prefs)
    assert policy['speaking_rate']==feasibility.source.NORMAL_SPOKEN_CHARACTERS_PER_SECOND==3.3
    assert policy['max_segment_seconds']==feasibility.source.MAX_SEGMENT_SECONDS==15
    assert policy['receiver_reserve_seconds']==feasibility.windows.RECEIVER_RESERVE_SECONDS==.3
    assert policy['timing_contract_source'].startswith('creative_fresh_legal_text_pipeline_v1.validate_script:')
    assert policy['timing_diagnostic_source']=='creative_known_draft_continuation_v2.dialogue_window_diagnostics'
    assert policy['whole_limit_source']=='explicit production_preferences.whole_film_max_seconds'
    assert policy['whole_floor_includes_reaction_or_action_time'] is False


def test_actions_and_punctuation_do_not_reduce_sequential_dialogue_sum(inputs):
    brief,prefs=inputs;raw=with_total(595)
    before=feasibility.diagnose_script(raw,brief,prefs)
    steps=raw['beats'][0]['steps'];steps.insert(1,{'kind':'action','speaker':'','text':'在相邻谈话时自然抬眼。'*100})
    steps[-1]['text']+='，。！？……'
    after=feasibility.diagnose_script(raw,brief,prefs)
    assert before['whole_speech_floor']['estimated_speech_only_seconds']==after['whole_speech_floor']['estimated_speech_only_seconds']
    assert after['policy']['action_overlap_subtracts_from_speech_floor'] is False
    assert after['whole_speech_floor']['exceeds_whole_speech_floor'] is True


@pytest.mark.parametrize('limit',[None,True,False,0,-1,float('nan'),float('inf'),-float('inf'),'180',{},10**1000])
def test_unknown_nonfinite_or_nonpositive_whole_limit_is_closed(inputs,limit):
    brief,prefs=inputs;prefs['whole_film_max_seconds']=limit
    with pytest.raises(feasibility.ScriptFeasibilityConfigError):feasibility.diagnose_script(fixture.raw_script(),brief,prefs)


def test_missing_explicit_whole_limit_does_not_use_different_preference_alias(inputs):
    brief,prefs=inputs;prefs.pop('whole_film_max_seconds');prefs['max_duration_seconds']=180
    with pytest.raises(feasibility.ScriptFeasibilityConfigError):feasibility.diagnose_script(fixture.raw_script(),brief,prefs)


@pytest.mark.parametrize('key,value',[('normal_spoken_characters_per_second',6.6),('native_segment_max_seconds',30),
    ('receiver_reserve_seconds',0),('normal_spoken_characters_per_second',True),('no_speed_fitting',False),
    ('no_speed_fitting',1),('native_segment_max_seconds',None)])
def test_provided_conflicting_timing_preferences_cannot_silently_relax_policy(inputs,key,value):
    _,prefs=inputs;prefs[key]=value
    with pytest.raises(feasibility.ScriptFeasibilityConfigError):feasibility.build_policy(prefs)


@pytest.mark.parametrize('fault',['unknown_kind','blank_text','unknown_speaker','missing_steps','missing_cast'])
def test_structural_or_closed_source_failure_cannot_be_timing_qualified(inputs,fault):
    brief,prefs=inputs;raw=fixture.raw_script()
    if fault=='unknown_kind':raw['beats'][0]['steps'][0]['kind']='subtitle'
    elif fault=='blank_text':raw['beats'][0]['steps'][0]['text']=''
    elif fault=='unknown_speaker':raw['beats'][0]['steps'][0]['speaker']='third_person'
    elif fault=='missing_steps':raw['beats'][0].pop('steps')
    else:raw['beats'].pop(1)
    with pytest.raises(ValueError):feasibility.diagnose_script(raw,brief,prefs)


def test_actual_528_reports_one_window_and_644_whole_speech_without_source_change():
    root=Path('data/production_trials/fresh_legal_full_flow_20261012/round_01')
    path=root/'call_528_fresh_draft_03_known_local_revision.json';before=path.read_bytes()
    receipt=json.loads(before.decode('utf-8-sig'));payload=json.loads(receipt['request']['messages'][1]['content'])
    raw=receipt.get('document_output',receipt.get('output'));source_before=deepcopy(raw)
    report=feasibility.diagnose_script(raw,payload['brief'],payload['production_preferences'])
    assert report['whole_speech_floor']['dialogue_count']==22
    assert report['whole_speech_floor']['spoken_character_count']==644
    assert report['whole_speech_floor']['estimated_speech_only_seconds']==644/3.3
    assert report['whole_speech_floor']['whole_film_max_seconds']==180
    rows=report['dialogue_window_diagnostics']['violations'];assert len(rows)==1
    assert rows[0]['source_ref']=='B6.S03' and rows[0]['spoken_character_count']==49
    assert {v['code'] for v in report['issues']}=={'SCRIPT_DIALOGUE_WINDOW_EXCEEDED','WHOLE_FILM_SPEECH_MINIMUM_EXCEEDED'}
    assert raw==source_before and path.read_bytes()==before


def test_preferences_identity_and_change_are_explicit_not_input_mutation(inputs):
    brief,prefs=inputs;raw=with_total(595);before=deepcopy((raw,brief,prefs))
    first=feasibility.diagnose_script(raw,brief,prefs,expected_preferences_sha256=feasibility.digest(prefs))
    changed={**prefs,'whole_film_max_seconds':181}
    second=feasibility.diagnose_script(raw,brief,changed)
    assert first['production_preferences_sha256']!=second['production_preferences_sha256']
    assert first['policy_sha256']!=second['policy_sha256'] and not second['whole_speech_floor']['exceeds_whole_speech_floor']
    with pytest.raises(feasibility.ScriptFeasibilityConfigError):feasibility.diagnose_script(raw,brief,changed,
        expected_preferences_sha256=feasibility.digest(prefs))
    assert (raw,brief,prefs)==before


def test_validator_closure_keeps_original_context_after_caller_mutates_it(inputs):
    brief,prefs=inputs;validator=feasibility.make_validator(brief,prefs)
    prefs['whole_film_max_seconds']=999;brief['constraints']['allowed_character_ids']=['different']
    with pytest.raises(feasibility.ScriptFeasibilityError):validator(with_total(595))


def test_returned_diagnostic_can_be_changed_without_mutating_input_source(inputs):
    brief,prefs=inputs;raw=fixture.raw_script();before=deepcopy((raw,brief,prefs))
    report=feasibility.diagnose_script(raw,brief,prefs)
    report['dialogue_rows'][0]['text']='changed';report['policy']['whole_film_max_seconds']=999
    assert (raw,brief,prefs)==before


def test_pure_validation_has_no_file_or_ledger_operation(inputs,monkeypatch):
    import builtins
    brief,prefs=inputs
    monkeypatch.setattr(builtins,'open',lambda *a,**k:pytest.fail('pure function must not open files'))
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('pure function must not open files'))
    report=feasibility.validate_script(fixture.raw_script(),brief,prefs)
    assert report['dispatch_performed'] is False and report['media_authorized'] is False and report['source_prose_changed'] is False
