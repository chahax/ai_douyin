from copy import deepcopy
import pytest
from src.content_factory.creative_review_v6 import (build_review_prompt, validate_review_v6,
    build_review_repair, validate_repair_preserves_conclusions, comparison_requirements, VERSION)
from src.content_factory.creative_review_gate import SUPPORTED_VERSIONS
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_review_v5 import sample
from tests.test_creative_review_v4 import leaf


def prepared():
    context, review = sample()
    checks = review['coverage'][0]['checks']
    checks['timing']['evidence_refs'].append({'path':'script.beats.0.before','quote':context['script']['beats'][0]['before']})
    # Provide actual source references, not synthetic pass results.
    for name, prefixes in comparison_requirements(context)['SH04'].items():
        for prefix in prefixes:
            if prefix in ('creative_brief.', 'brief.'):
                key = prefix[:-1]
                field = next(k for k,v in context[key].items() if isinstance(v,str) and v)
                checks[name]['evidence_refs'].append({'path':prefix+field,'quote':context[key][field]})
    return context, review


def test_v6_requires_source_comparison_not_every_compiled_leaf():
    context, review = prepared()
    for check in review['coverage'][0]['checks'].values():
        check['evidence_refs'] = [r for r in check['evidence_refs'] if r['path'] not in ('shots.shots.0.camera','shots.shots.0.cut_reason','shots.shots.0.prompt')]
    for check in review['coverage'][0]['checks'].values():
        check['evidence_refs'].append({'path':'shots.shots.0.start_state','quote':context['shots']['shots'][0]['start_state']})
    validate_review_v6(review, context)
    review['coverage'][0]['checks']['timing']['evidence_refs'] = [r for r in review['coverage'][0]['checks']['timing']['evidence_refs'] if not r['path'].startswith('script.beats.')]
    with pytest.raises(CreativeContractError, match=r'coverage.0.checks.timing.evidence_refs'):
        validate_review_v6(review, context)


def test_state_plan_must_be_compared_when_present():
    context, review = prepared()
    context['state_plan'] = {'initial_state':'站立'}
    with pytest.raises(CreativeContractError, match='state_plan'):
        validate_review_v6(review, context)
    review['coverage'][0]['checks']['continuity']['evidence_refs'].append({'path':'state_plan.initial_state','quote':'站立'})
    validate_review_v6(review, context)


def test_repair_has_full_source_and_cannot_change_conclusion():
    context, review = prepared()
    instruction, payload = build_review_repair('coverage.0.checks.timing.evidence_refs missing', context, review)
    assert payload['review_context'] == context
    assert payload['invalid_review'] == review
    assert 'coverage' in payload['target_contract']
    assert payload['validation_error'].startswith('coverage.0')
    corrected = deepcopy(review)
    corrected['coverage'][0]['checks']['assets']['evidence_refs'] = []
    validate_repair_preserves_conclusions(review, corrected)
    corrected['coverage'][0]['checks']['assets']['reason'] = 'changed meaning'
    with pytest.raises(CreativeContractError, match='不得改变'):
        validate_repair_preserves_conclusions(review, corrected)


def test_real_round_three_repair_missing_context_is_addressed():
    import json
    path = __import__('pathlib').Path('data/production_trials/say_no_three_production_cycles_20260927/round_03/writer_check__segment_scope_v2_beat_01_00__contract_repair.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    old = json.loads(record['request'][1]['content'])
    assert 'review_context' not in old
    context, review = prepared()
    _, new = build_review_repair(old['error'], context, review)
    assert new['review_context']['shots']['shots']
    assert new['review_context']['script']['beats']
    assert new['target_contract']


def test_v6_is_opt_in_and_semantics_are_explicit():
    assert VERSION in SUPPORTED_VERSIONS
    text = build_review_prompt({})
    assert '末态' in text and '5单位/秒' in text and '不是正确答案' in text
