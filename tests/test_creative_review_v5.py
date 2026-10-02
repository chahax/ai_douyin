from copy import deepcopy
import pytest
from src.content_factory.creative_review_v4 import build_review_prompt as prompt_v4, validate_review_v4
from src.content_factory.creative_review_v5 import build_review_prompt, validate_review_v5, required_asset_sources, VERSION
from src.content_factory.creative_review_gate import SUPPORTED_VERSIONS, review_prompt, review_rules
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_review_v4 import recorded, fully_cited_review, leaf


def sample():
    fixture = recorded()
    context = fixture['context']
    review = fully_cited_review(context, fixture['review'])
    review['coverage'][0]['checks']['assets']['evidence_refs'].extend(
        {'path': p, 'quote': str(leaf(context, p))} for p in required_asset_sources(context))
    return context, review


def test_assets_must_compare_actual_style_source_not_shot_self_claim():
    context, review = sample()
    validate_review_v5(review, context)
    assets = review['coverage'][0]['checks']['assets']
    assets['evidence_refs'] = [r for r in assets['evidence_refs'] if r['path'] != 'shots.style.character_lock']
    with pytest.raises(CreativeContractError, match='实际style源.*character_lock'):
        validate_review_v5(review, context)


def test_same_shot_issue_evidence_counts_without_duplicate_coverage_quote():
    context, review = sample()
    camera = {'path': 'shots.shots.0.camera', 'quote': context['shots']['shots'][0]['camera']}
    review['story_preserved'] = False
    review['issues'] = [{'id': 'I01', 'owner':'director', 'location':'SH04', 'severity':'major',
        'rule':'一个镜号不能硬切', 'evidence':camera['quote'], 'contradiction':'同镜安排切换机位',
        'impact':'镜内切换', 'proposal':'拆镜', 'evidence_refs':[camera]}]
    checks = review['coverage'][0]['checks']
    for check in checks.values():
        check['evidence_refs'] = [r for r in check['evidence_refs'] if r['path'] != camera['path']]
    checks['continuity']['status'] = 'fail'
    checks['continuity']['issue_ids'] = ['I01']
    validate_review_v5(review, context)
    with pytest.raises(CreativeContractError, match='camera'):
        validate_review_v4(review, context)


def test_style_not_available_does_not_require_invented_source():
    context, review = sample()
    context['shots'].pop('style')
    for check in review['coverage'][0]['checks'].values():
        check['evidence_refs'] = [r for r in check['evidence_refs'] if not r['path'].startswith('shots.style.')]
    validate_review_v5(review, context)


def test_v5_semantics_does_not_change_old_prompt():
    context, _ = sample()
    old = prompt_v4(context)
    current = build_review_prompt(context)
    assert '固定机位只锁定摄影机' in current
    assert 'dialogue[0]' in current
    assert '无须无依据额外插入静止等待' in current
    assert 'shots.style.character_lock' in current
    assert prompt_v4(context) == old
    assert VERSION in SUPPORTED_VERSIONS
    assert review_rules(VERSION) == ''
    assert 'coverage' in review_prompt(VERSION)


def test_script_mode_has_no_asset_source_requirement():
    from tests.test_creative_review_v3 import sample as script_sample
    context, review = script_sample()
    validate_review_v5(review, context)
