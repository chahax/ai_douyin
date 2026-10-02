from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory.creative_rule_registry import resolve_fields,resolve_constraints,validate_ownership,validate_transition,select_rules
from src.content_factory.creative_evaluation import *


def test_conflict_and_unsupported_never_rewrite_story():
    rows=[{'key':'duration','value':10,'priority':'P1','source':'brief1'},{'key':'duration','value':20,'priority':'P1','source':'brief2'}]
    assert resolve_constraints(rows)['code']=='REQUIREMENT_CONFLICT'
    assert resolve_constraints(rows,expression_supported=False)['code']=='EXPRESSION_UNSUPPORTED'
    assert resolve_constraints([rows[0],{**rows[1],'priority':'P2'}])['constraints'][0]['value']==10


def test_duplicate_authority_and_retirement_are_explicit():
    row={'field_path':'plan.a','owner':'writer','authority':'source','status':'active'}
    with pytest.raises(ValueError,match='MULTIPLE'):validate_ownership([row,row],{'plan':{'a':1}})
    old={'rule_id':'x','status':'active','version':'1','replacement_rule_ids':[]}
    with pytest.raises(ValueError,match='INVALID_RULE'):validate_transition(old,{**old,'status':'retired','version':'2'})
    with pytest.raises(ValueError,match='REPLACEMENT'):validate_transition(old,{**old,'status':'deprecated','version':'2'})
    assert resolve_fields({'a':[{'x':1},{'x':2}]},'a[*].x')==[1,2]


def test_candidate_labels_and_repeated_variants_do_not_create_gold_samples():
    cases=[{'case_id':'A','label_status':'candidate','source_family':'same','independence_group':'same','split':'development','category':'action','case_kind':'error'}]
    assert validate_dataset(cases)['approved_independent_count']==0
    assert not score_review_runs(cases,[])['holdout_repeated_validation_passed']
    gold={**cases[0],'label_status':'approved','adjudication':{'approved_by':'human','approved_at':'2026-09-28'},'split':'holdout','expected_issues':[{'issue_id':'R','severity':'major'}]}
    outcome={'case_id':'A','variant':'new','repeat':1,'status':'unknown','unknown_disposition':'blocked','found_issue_ids':['R'],'references_valid':True,'required_evidence_present':True}
    stats=score_review_runs([gold],[outcome])['per_repeat'][0]['metrics']
    assert stats['major_recall']['numerator']==0 and stats['decidable_unknown']['numerator']==1
    with pytest.raises(ValueError,match='DUPLICATE'):score_review_runs([gold],[outcome,outcome])


def test_correct_unknown_is_visible_and_not_hidden_as_pass():
    case={'case_id':'A','label_status':'approved','adjudication':{'approved_by':'human','approved_at':'now'},'source_family':'a','independence_group':'a','split':'holdout','category':'action','case_kind':'correct','expected_issues':[]}
    row={'case_id':'A','variant':'new','repeat':1,'status':'unknown','unknown_disposition':'review_required'}
    stats=score_review_runs([case],[row])['per_repeat'][0]['metrics']
    assert stats['correct_unknown_blocked']['rate']==1 and stats['correct_false_positive']['rate']==0


def test_cost_null_not_zero_cache_scenario_and_reasoning_not_double_counted():
    call=normalize_call({'response_metadata':{'provider':'x','response_id':'1','prompt_tokens':100,'completion_tokens':20,'total_tokens':120,'reasoning_tokens':10}},'source')
    prices={'version':'fixture-not-live','currency':'CNY','cached_input_per_million':1,'uncached_input_per_million':2,'output_per_million':3}
    assert estimate_call(call,prices)['estimated_amount'] is None
    estimated=estimate_call(call,prices,cache_scenario='all_uncached_comparison')
    assert estimated['estimated_amount']==pytest.approx(0.00026)
    result=summarize_cost([call,deepcopy(call)],[],0)
    assert result['call_count']==1 and result['model_cost'] is None and result['cost_per_qualified_handoff'] is None
    assert summarize_cost([call,{**call,'provider':'y'}],[],0)['call_count']==2


def test_actual_failed_attempt_cost_included_and_cross_currency_not_summed():
    calls=[{'response_id':'a','provider':'x','currency':'CNY','billed_amount':2},{'response_id':'b','provider':'x','currency':'CNY','billed_amount':3}]
    human=[{'active_minutes':30,'wait_minutes':10,'hourly_rate':20,'currency':'CNY'}]
    report=summarize_cost(calls,human,1)
    assert report['cost_per_qualified_handoff']==15
    assert summarize_cost([calls[0],{**calls[1],'currency':'USD'}],human,1)['model_cost'] is None


def test_missing_cost_latency_human_blocks_optimization_claim():
    result=optimization_admission([{'baseline':{'input_tokens':100},'candidate':{'input_tokens':50}}],True)
    assert not result['optimization_verified'] and 'MISSING:model_cost' in result['failures']


def test_repair_and_production_gates_cannot_pass_empty_runs():
    assert not score_repair_runs([])['qualified']
    result=score_production_runs([],[])
    assert not result['normal_passed'] and not result['boundary_passed']


def test_frozen_pack_has_real_fields_and_candidate_labels(tmp_path):
    from scripts.manage_creative_governance import build,verify
    output=tmp_path/'pack';report=build(output)
    assert report['registry']['repository_wide_complete'] is False
    verified=verify(output)
    assert verified['artifact_hashes_valid'] and not verified['dataset']['qualified']
    assert verified['dataset']['approved_case_count']==0
    cost=json.loads((output/'baseline_metrics.json').read_text(encoding='utf-8'))['cost']
    assert cost['call_count']==4 and cost['cost_per_qualified_handoff'] is None
    with pytest.raises(RuntimeError,match='Frozen output'):build(output)
    (output/'rules.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='FROZEN_ARTIFACT'):verify(output)


def test_registry_binding_rejects_artifact_change_without_silent_reload(tmp_path,monkeypatch):
    import src.content_factory.creative_rule_registry as reg
    from scripts.manage_creative_governance import build
    output=tmp_path/'pack';build(output)
    # The focused binding test isolates artifact mutation; live source drift has its own test.
    monkeypatch.setattr(reg,'validate_runtime_sources',lambda *_:{'status':'test-isolated'})
    monkeypatch.setattr(reg,'validate_registry',lambda *_:{'repository_wide_complete':False})
    binding=reg.bind_registry(tmp_path,output)
    activation=reg.validate_registry_binding(binding,tmp_path,'plan_validation',[])['activation']
    assert 'STATE.PRECONDITION.001' in activation['active_rule_ids']
    (output/'rules.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='BINDING_CHANGED'):reg.validate_registry_binding(binding,tmp_path)


def test_offline_evaluator_reports_unmet_admission_without_any_api(tmp_path):
    from scripts.manage_creative_governance import build
    from scripts.evaluate_creative_offline import evaluate
    output=tmp_path/'pack';build(output)
    runs=tmp_path/'runs.jsonl';runs.write_text('',encoding='utf-8')
    report=evaluate(output/'dataset_manifest.json',runs,tmp_path/'eval.json')
    assert report['automatic_paid_execution'] is False
    assert report['result']['holdout_repeated_validation_passed'] is False

def test_registry_live_source_change_requires_new_binding(tmp_path):
    import shutil
    import src.content_factory.creative_rule_registry as reg
    from scripts.manage_creative_governance import build, ROOT
    output=tmp_path/'pack';build(output)
    registry=json.loads((output/'rules.json').read_text(encoding='utf-8'))
    for relative in {s['path'] for r in registry['rules'] for s in r['source_refs']}:
        target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    runtime=json.loads((output/'runtime_sources.json').read_text(encoding='utf-8'))
    for row in runtime['sources']:
        target=tmp_path/row['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/row['path'],target)
    binding=reg.bind_registry(tmp_path,output)
    changed=tmp_path/registry['rules'][0]['source_refs'][0]['path']
    changed.write_bytes(changed.read_bytes()+b'\n# changed after task binding\n')
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):
        reg.validate_registry_binding(binding,tmp_path,'review',[])


def test_runtime_source_drift_is_not_hidden_as_rule_coverage(tmp_path):
    from src.content_factory.creative_rule_registry import validate_runtime_sources,file_hash
    source=tmp_path/'runtime.py';source.write_text('version=1',encoding='utf-8')
    (tmp_path/'runtime_sources.json').write_text(json.dumps({'schema_version':'creative_runtime_sources/v1','sources':[{'path':'runtime.py','sha256':file_hash(source)}]}),encoding='utf-8')
    assert validate_runtime_sources(tmp_path,tmp_path)['rule_inventory_coverage_claim'] is False
    source.write_text('version=2',encoding='utf-8')
    with pytest.raises(ValueError,match='RUNTIME_SOURCE_CHANGED'):validate_runtime_sources(tmp_path,tmp_path)
