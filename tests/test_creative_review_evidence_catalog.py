from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory.creative_review_evidence_catalog import diagnostics,leaf_catalog,reference_error,VERSION,FIELD
from src.content_factory.creative_review_v6 import build_review_prompt,build_review_repair,validate_review_v6,validate_repair_preserves_conclusions
from src.content_factory.creative_workflow_contract import parse_json_object,CreativeContractError

ROOT=Path('data/production_trials/say_no_v3_two_production_cycles_20260928/round_01')


def receipt():
    if not ROOT.exists():pytest.skip('local paid receipt unavailable')
    raw=json.loads((ROOT/'writer_check__state_plan_00.json').read_text(encoding='utf-8'))
    return raw,json.loads(raw['request']['messages'][1]['content']),parse_json_object(raw['response_text'])


def test_real_paid_prompt_and_repair_remain_replayable_without_new_binding():
    raw,context,review=receipt()
    assert build_review_prompt(context)==raw['request']['messages'][0]['content']
    repair=json.loads((ROOT/'writer_check__state_plan_00__contract_repair.json').read_text(encoding='utf-8'))
    instruction,payload=build_review_repair(repair['error'],context,review)
    messages=repair['request']
    assert instruction==messages[0]['content']
    assert payload==json.loads(messages[1]['content'])


def test_real_review_all_bad_refs_and_missing_sources_reported_together():
    _,context,review=receipt();original=deepcopy(review);context[FIELD]=VERSION
    report=diagnostics(review,context)
    assert len(report['invalid_references'])>=15
    assert report['missing_comparisons']
    assert all(row['reason']=='string_leaf_cannot_be_traversed' for row in report['invalid_references'])
    assert any(row['actual_leaf_path']=='shots.shots.0.end_state' for row in report['invalid_references'])
    with pytest.raises(CreativeContractError) as error:validate_review_v6(review,context)
    assert 'invalid_references' in str(error.value) and 'missing_comparisons' in str(error.value)
    _,repair=build_review_repair(str(error.value),context,review)
    assert repair['evidence_diagnostics']==report
    assert review==original


def test_directory_does_not_repeat_prose_or_parse_json_strings():
    _,context,_=receipt();catalog=leaf_catalog(context)
    assert 'end_state' in catalog['shots.shots.0']['str']
    assert not any(path.startswith('shots.shots.0.end_state.') for path in catalog)
    assert not any('.operations.' in path for path in catalog)
    assert len(json.dumps(catalog,ensure_ascii=False))<len(json.dumps(context,ensure_ascii=False))/4


def test_paths_do_not_waive_quote_validation_or_change_conclusions():
    context={'shot':{'state':'{"posture":"standing"}'}}
    assert reference_error({'path':'shot.state.posture','quote':'standing'},context)['reason']=='string_leaf_cannot_be_traversed'
    assert reference_error({'path':'shot.state','quote':'standing'},context) is None
    assert reference_error({'path':'shot.state','quote':'sitting'},context)['reason']=='quote_not_verbatim_substring'
    _,_,review=receipt();changed=deepcopy(review);changed['coverage'][0]['checks']['timing']['reason']='new judgment'
    with pytest.raises(CreativeContractError,match='不得改变'):validate_repair_preserves_conclusions(review,changed)
