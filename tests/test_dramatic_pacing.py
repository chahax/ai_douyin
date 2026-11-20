import copy

import pytest

from src.trend_intelligence.dramatic_pacing import (
    audit_pacing, require_new_draft_pacing, require_delivery_fields,
)


def story(durations):
    return {'version': {'shots': [
        {'shot_id': f'S{i:02d}', 'beat': beat, 'duration_seconds': seconds}
        for i, (beat, seconds) in enumerate(zip(
            ('setup', 'conflict', 'escalation', 'turn', 'resolution', 'closure'), durations), 1)
    ]}}


def test_current_flat_timeline_is_rejected_without_rewriting_history():
    current = story([7, 8, 7, 8, 8, 7])
    before = copy.deepcopy(current)
    audit = audit_pacing(current, 'short')
    assert audit['pressure_seconds'] == 23
    assert audit['ending_seconds'] == 15
    assert len(audit['issues']) == 3
    with pytest.raises(ValueError, match='dramatic pacing'):
        require_new_draft_pacing(current, 'short')
    assert current == before


@pytest.mark.parametrize('kind,durations', [('short', [5, 10, 10, 10, 5, 5]),
                                         ('long', [20, 45, 45, 40, 15, 15])])
def test_budget_does_not_claim_semantic_approval(kind, durations):
    result = require_new_draft_pacing(story(durations), kind)
    assert result['semantic_review_required'] is True
    assert not result['issues']
    assert 'approved' not in result


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1, True])
def test_invalid_durations_rejected(bad):
    with pytest.raises(ValueError, match='duration'):
        audit_pacing(story([bad, 10, 10, 10, 5, 5]), 'short')


def test_delivery_requires_all_fields_and_content():
    text = '触发：对方催签；情绪：受压转坚定；语速：偏快；语气：硬拒绝；重音：不能；停顿：句后0.4秒；余波：紧绷未松'
    def production(value):
        return {'shots': [{'shot_id': 'S04', 'emotion_and_performance': value}]}
    require_delivery_fields(production(text))
    for bad in ('自然平稳', text.replace('偏快', ''), text + '语气：自然'):
        with pytest.raises(ValueError):
            require_delivery_fields(production(bad))
