from copy import deepcopy
import json
import threading
from pathlib import Path
import pytest

from test_narration_placement_policy_v2 import cli,candidate
from src.content_factory import narration_prevideo_agent_v1 as agent
from src.content_factory import narration_placement_policy_v2 as p

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'


def spec(tmp_path,budget=4,adopt=False):
    case=cli.case_v2();p.freeze(tmp_path/'CASE.json',case)
    value=dict(case=p.bind(tmp_path/'CASE.json'),call_budget=budget,
        authorization=dict(max_text_calls=budget,publication=False,source_scope='Controlled injected transport or verified adopted receipt; never new real API call.'),
        sources=[dict(id='S03',source_case=p.bind(OLD/'segments/S03/SOURCE_CASE.json'),quote_ids=['N_S03'],action_span_map={'s010':'A_LEAVE'})])
    if adopt:value['adopted_receipt']=p.bind(ROOT/'data/corpus_production_trials/20261113_narration_placement_v1/RECEIPT_V2.json')
    return value,case


def envelope(value):
    return dict(model=agent.MODEL,usage=dict(prompt_tokens=11,completion_tokens=7,total_tokens=18),
        choices=[dict(index=0,finish_reason='stop',message=dict(content=json.dumps(value,ensure_ascii=False)))])


def transport_for(case,*,reject_first_review=False,alias=False):
    state=dict(calls=[],reviewed=0)
    def call(folder,request):
        phase=request['phase'];state['calls'].append(phase)
        payload=json.loads(request['args']['messages'][1]['content'])
        if phase!='review':
            value=candidate(case)
            if alias:
                value['decisions'][0]['classification']='keep_as_narration'
                value['decisions'][2]['classification']='move_as_narration'
                value['decisions'][3]['classification']='convert_to_oral';value['decisions'][3]['oral_suggestion']=value['decisions'][3]['oral_suggestion']['text']
        else:
            state['reviewed']+=1;c=payload['candidate']
            value=dict(schema=p.base.REVIEW,candidate_sha256=p.digest(c),checks=[dict(source_quote_id=r['source_quote_id'],
                verdict='needs_semantic_repair' if reject_first_review and state['reviewed']==1 else 'pass',
                evidence_quote_ids=[r['source_quote_id']],reason='Injected protocol verification, not model semantic evaluation.') for r in c['decisions']])
        return envelope(value)
    return call,state


def test_fresh_case_without_old_calls_runs_judge_review_and_real_source_consumer(tmp_path):
    value,case=spec(tmp_path);run=tmp_path/'fresh';agent.prepare(run,value);call,state=transport_for(case)
    result=agent.execute(run,transport=call)
    assert state['calls']==['judge','review'] and result['local_calls_started']==2
    assert result['sources'][0]['result']['status']=='fresh_source_case_ready_for_actual_asset_tail_gate'
    entry=p.read(result['sources'][0]['result']['source_case']['path'])['shots'][0]
    assert entry['audio'][0]['mode']=='voiceover' and entry['audio'][0]['start']==1.2
    assert not (run/'calls/C003').exists()


def test_completed_receipt_reentry_has_zero_transport_calls(tmp_path):
    value,case=spec(tmp_path);run=tmp_path/'fresh';agent.prepare(run,value);call,state=transport_for(case)
    first=agent.execute(run,transport=call)
    second=agent.execute(run,transport=lambda *a:pytest.fail('completed receipt must not call model'))
    assert first==second and state['calls']==['judge','review']


def test_unknown_claim_is_retained_and_never_issued_again(tmp_path):
    value,case=spec(tmp_path);run=tmp_path/'unknown';agent.prepare(run,value);calls=[]
    def unknown(*args):calls.append(1);raise TimeoutError('injected timeout')
    assert agent.execute(run,transport=unknown)['status']=='outcome_unknown'
    assert agent.execute(run,transport=unknown)['status']=='outcome_unknown'
    assert calls==[1] and (run/'calls/C001/START.json').exists() and not (run/'calls/C002').exists()


def test_budget_does_not_turn_unreviewed_candidate_into_ready(tmp_path):
    value,case=spec(tmp_path,budget=1);run=tmp_path/'budget';agent.prepare(run,value);call,state=transport_for(case)
    result=agent.execute(run,transport=call)
    assert result['status']=='needs_semantic_repair' and state['calls']==['judge']
    assert not (run/'RECEIPT.json').exists() and not (run/'sources').exists()


def test_bounded_independent_repair_rechecks_full_candidate(tmp_path):
    value,case=spec(tmp_path,budget=4);run=tmp_path/'repair';agent.prepare(run,value);call,state=transport_for(case,reject_first_review=True)
    result=agent.execute(run,transport=call)
    assert result['status']=='source_consumption_complete' and state['calls']==['judge','review','repair','review']
    assert len(list((run/'calls').glob('*/RESPONSE.json')))==4


def test_finite_native_normalization_precedes_independent_review(tmp_path):
    value,case=spec(tmp_path);run=tmp_path/'normalize';agent.prepare(run,value);call,state=transport_for(case,alias=True)
    result=agent.execute(run,transport=call)
    proof=p.read(run/'calls/C001/NORMALIZATION.json')
    assert result['status']=='source_consumption_complete' and proof['changes']
    assert proof['native_schema_compliance_claimed'] is False and proof['narrative_or_dialogue_text_changed'] is False


def test_adopted_real_receipt_is_verified_and_consumed_with_no_seventh_call(tmp_path):
    value,case=spec(tmp_path,budget=0,adopt=True);run=tmp_path/'adopt';agent.prepare(run,value)
    result=agent.execute(run,transport=lambda *a:pytest.fail('adopted receipt cannot trigger API'))
    assert result['local_calls_started']==0 and result['text_execution']=='adopted_verified_real_receipt_no_new_call'
    assert result['sources'][0]['result']['status']=='fresh_source_case_ready_for_actual_asset_tail_gate'


def test_source_case_over_budget_is_a_notice_not_truncated_ready(tmp_path):
    value,case=spec(tmp_path);run=tmp_path/'split'
    value['sources']=[dict(id='S04',source_case=p.bind(OLD/'segments/S04/SOURCE_CASE.json'),quote_ids=['Q_NAN','Q_GIRL','N_S04'],action_span_map={'s010':'Q_NAN','s012':'Q_GIRL','s014':'A_STOP'})]
    value['adopted_receipt']=p.bind(ROOT/'data/corpus_production_trials/20261113_narration_placement_v1/RECEIPT_V2.json')
    agent.prepare(run,value);result=agent.execute(run,transport=lambda *a:pytest.fail('no API'))
    assert result['sources'][0]['result']['status']=='needs_segment_split'
    assert not (run/'sources/S04/SOURCE_CASE.json').exists()


def test_adopted_candidate_cannot_be_changed_behind_native_review(tmp_path):
    value,case=spec(tmp_path,budget=0,adopt=True)
    receipt=p.read(value['adopted_receipt']['path']);receipt['candidate']['decisions'][-1]['oral_suggestion']['text']='咱们没力气打。'
    receipt['semantic_review']['candidate_sha256']=p.digest(receipt['candidate'])
    p.freeze(tmp_path/'FORGED_RECEIPT.json',receipt);value['adopted_receipt']=p.bind(tmp_path/'FORGED_RECEIPT.json')
    with pytest.raises(ValueError,match='differs_from_native'):
        agent.prepare(tmp_path/'forged',value)


def test_concurrent_execute_cannot_start_a_duplicate_review_or_exceed_budget(tmp_path):
    value,case=spec(tmp_path,budget=2);run=tmp_path/'concurrent';agent.prepare(run,value);call,state=transport_for(case)
    # Seed the known judge so the contested operation is the review dispatch.
    agent._call(run,case,'judge',None,None,call)
    started=threading.Event();release=threading.Event();outcomes=[]
    def slow_review(folder,request):
        started.set();assert release.wait(5);return call(folder,request)
    worker=threading.Thread(target=lambda:outcomes.append(agent.execute(run,transport=slow_review)))
    worker.start();assert started.wait(5)
    second=agent.execute(run,transport=lambda *a:pytest.fail('concurrent owner must not dispatch'))
    release.set();worker.join(5)
    assert not worker.is_alive() and second['status']=='busy_existing_narration_owner'
    assert outcomes[0]['status']=='source_consumption_complete' and state['calls']==['judge','review']
    assert not (run/'calls/C003').exists()


def test_last_moment_dispatch_rechecks_actual_start_budget_and_unknown(tmp_path):
    value,case=spec(tmp_path,budget=1);run=tmp_path/'guard';agent.prepare(run,value);call,state=transport_for(case)
    agent._call(run,case,'judge',None,None,call)
    with pytest.raises(ValueError,match='actual_started_calls'):
        agent._call(run,case,'review',candidate(case),None,call)
    assert state['calls']==['judge'] and not (run/'calls/C002').exists()


def test_plan_budget_cannot_be_enlarged_independently_of_frozen_spec(tmp_path):
    value,case=spec(tmp_path,budget=1);run=tmp_path/'tamper';agent.prepare(run,value)
    plan=p.read(run/'PLAN.json');plan['call_budget']=8;plan['authority']['max_text_calls']=8
    (run/'PLAN.json').write_text(json.dumps(plan),encoding='utf-8')
    with pytest.raises(ValueError,match='match_frozen_spec'):
        agent.execute(run,transport=lambda *a:pytest.fail('tampered scope must not call'))
