from copy import deepcopy
import json
import pytest
from src.content_factory.creative_review_evidence_ids import build_evidence_catalog,expand_review_ids,save_expansion,VERSION,FIELD
from src.content_factory.creative_review_v6 import validate_review_v6,build_review_prompt,build_review_repair,validate_repair_preserves_conclusions
from src.content_factory.creative_review_gate import validate_review
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_review_v6 import prepared


def fixture():
    context,review=prepared();context[FIELD]=VERSION
    for check in review['coverage'][0]['checks'].values():
        check['evidence_refs'].append({'path':'shots.shots.0.start_state','quote':context['shots']['shots'][0]['start_state']})
    review['coverage'][0]['checks']['requirements']['evidence_refs'].append({'path':'creative_brief.theme','quote':context['creative_brief']['theme']})
    catalog=build_evidence_catalog(context);paths={v['path']:k for k,v in catalog['entries'].items()}
    raw=deepcopy(review)
    def convert(obj):
        if isinstance(obj,dict):
            for key,value in obj.items():
                if key=='evidence_refs':obj[key]=[{'ref_id':paths[r['path']]} for r in value if r['path'] in paths]
                else:convert(value)
        elif isinstance(obj,list):
            for value in obj:convert(value)
    convert(raw)
    return context,raw


def test_expansion_preserves_conclusions_and_requires_existing_source_checks():
    context,raw=fixture();original=deepcopy(raw)
    effective,receipt=expand_review_ids(raw,context);validate_review_v6(effective,context)
    validate_repair_preserves_conclusions(raw,effective)
    assert raw==original and receipt['automatic_approval'] is False
    raw['coverage'][0]['checks']['timing']['evidence_refs']=[]
    effective,_=expand_review_ids(raw,context)
    with pytest.raises(CreativeContractError,match='缺少对照'):validate_review_v6(effective,context)


def test_context_changes_and_mixed_refs_are_rejected():
    context,raw=fixture();context['script']['beats'][0]['before']+='改变'
    with pytest.raises(CreativeContractError,match='stale'):expand_review_ids(raw,context)
    context,raw=fixture();raw['coverage'][0]['checks']['timing']['evidence_refs'].append({'path':'script.beats.0.before','quote':'anything'})
    with pytest.raises(CreativeContractError,match='不可混用'):expand_review_ids(raw,context)


def test_expansion_receipt_is_immutable_and_prompt_uses_navigation_not_duplication(tmp_path):
    context,raw=fixture();effective=save_expansion(tmp_path,'writer_check__00',raw,context)
    assert save_expansion(tmp_path,'writer_check__00',raw,context)==effective
    corrupted=json.loads((tmp_path/'writer_check__00__evidence_ids_expansion.json').read_text(encoding='utf-8'));corrupted['automatic_approval']=True
    (tmp_path/'writer_check__00__evidence_ids_expansion.json').write_text(json.dumps(corrupted),encoding='utf-8')
    with pytest.raises(RuntimeError,match='展开回执'):save_expansion(tmp_path,'writer_check__00',raw,context)
    prompt=build_review_prompt(context)
    assert '前64字符导航片段' in prompt and 'evidence_refs每项仅为' in prompt
    instruction,payload=build_review_repair('missing',context,raw)
    assert payload['review_context']==context
    assert 'ref_id' in instruction and '逐字保留' in instruction


def test_actual_stage_stores_raw_ids_and_returns_effective_then_gates_assistant(tmp_path):
    from src.content_factory.creative_workflow import CreativeWorkflow,CREATE_REVIEW_PROFILE,EVENT_WRITER_VERSION
    from tests.test_creative_workflow import FakeClients
    context,raw=fixture();context.pop(FIELD)
    clients=FakeClients([raw]);workflow=CreativeWorkflow(tmp_path,clients=clients,model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=EVENT_WRITER_VERSION,review_policy_version='evidence_review_v6')
    workflow.state={'calls_started':0,'stages':[],'revision_rounds':0,'contract_repairs_used':0,FIELD:VERSION}
    result=workflow._stage('writer_check__ids_test','writer',context,lambda value:validate_review(value,context))
    record=json.loads((tmp_path/'writer_check__ids_test.json').read_text(encoding='utf-8'))
    assert record['output']==raw and 'ref_id' in str(record['output'])
    assert 'path' in result['coverage'][0]['checks']['timing']['evidence_refs'][0]
    assert workflow._stage('writer_check__ids_test','writer',context,lambda value:validate_review(value,context))==result
    assert len(clients.calls)==1
    assert workflow._verified_review('writer_check__ids_test',result,context) is None
    assert workflow.state['status']=='script_review_pending'


def test_real_production_repair_only_reformats_and_cannot_be_accepted():
    from pathlib import Path
    from src.content_factory.creative_workflow_contract import parse_json_object
    from src.content_factory.creative_review_v6 import evidence_gaps
    root=Path('data/production_trials/say_no_action_one_production_cycle_20260928/round_01')
    if not root.exists():pytest.skip('real production receipt unavailable')
    first=json.loads((root/'writer_check__state_plan_00.json').read_text(encoding='utf-8'))
    repaired=json.loads((root/'writer_check__state_plan_00__contract_repair.json').read_text(encoding='utf-8'))
    context=json.loads(first['request']['messages'][1]['content'])
    raw=json.loads(first['response_text']);fixed=json.loads(repaired['response_text'])
    assert raw==fixed
    assert parse_json_object(first['response_text'])==raw
    assert parse_json_object(repaired['response_text'])==fixed
    assert len(first['response_text'])!=len(repaired['response_text'])
    effective,_=expand_review_ids(raw,context)
    gaps=evidence_gaps(effective,context)
    assert len(gaps)==17
    catalog=build_evidence_catalog(context)['entries']
    assert all(any(entry['path'].startswith(prefix) for entry in catalog.values())
               for gap in gaps for prefix in gap['missing_source_prefixes'])
    with pytest.raises(CreativeContractError,match='缺少对照证据'):validate_review_v6(effective,context)


def test_real_id_repair_replays_and_optin_hints_only_offer_existing_candidates():
    from pathlib import Path
    from src.content_factory.creative_review_evidence_ids import HINT_FIELD,HINT_VERSION,repair_candidates
    root=Path('data/production_trials/say_no_action_one_production_cycle_20260928/round_01')
    if not root.exists():pytest.skip('real production receipt unavailable')
    first=json.loads((root/'writer_check__state_plan_00.json').read_text(encoding='utf-8'))
    repaired=json.loads((root/'writer_check__state_plan_00__contract_repair.json').read_text(encoding='utf-8'))
    context=json.loads(first['request']['messages'][1]['content']);raw=json.loads(first['response_text'])
    instruction,payload=build_review_repair(repaired['error'],context,raw)
    assert instruction==repaired['request'][0]['content']
    assert payload==json.loads(repaired['request'][1]['content'])
    old_catalog=build_evidence_catalog(context)
    context[HINT_FIELD]=HINT_VERSION
    assert build_evidence_catalog(context)==old_catalog
    before=deepcopy(raw)
    instruction,payload=build_review_repair(repaired['error'],context,raw)
    hints=payload['candidate_evidence'];assert hints['automatic_selection'] is False
    assert len(hints['missing_comparisons'])==17
    for gap in hints['missing_comparisons']:
        assert 1<=len(gap['candidates'])<=3
        for candidate in gap['candidates']:
            assert old_catalog['entries'][candidate['ref_id']]['path']==candidate['path']
            assert candidate['path'].startswith(gap['missing_source_prefix'])
    assert raw==before
    raw['coverage'][0]['checks']['timing']['evidence_refs'].append({'ref_id':'UNKNOWN'})
    unknown=repair_candidates(raw,context)['unknown_or_invalid_references']
    assert len(unknown)==1 and unknown[0]['reference']['ref_id']=='UNKNOWN'
