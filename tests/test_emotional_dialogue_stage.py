import copy

import pytest

from scripts.run_emotional_dialogue_stage import validate_dialogue


def fixture():
    return {'shots': [{'shot_id': f'S{i+1:02d}', 'dialogue': '甲' * count,
        'emotion':'测试情绪', 'pace':'偏快', 'tone':'坚定', 'stress_words':['甲'],
        'pause':'无刻意停顿', 'ending_emotion':'仍坚定'}
        for i,count in enumerate([20,35,35,35,20,20])]}


def test_validation_preserves_authored_text_without_approval():
    data=fixture(); before=copy.deepcopy(data)
    assert validate_dialogue(data)==before
    assert data==before and 'approved' not in data


def test_repair_feedback_lists_all_budget_and_stress_errors_together():
    data=fixture()
    data['shots'][0]['dialogue']='甲'*26
    data['shots'][5]['stress_words']=['不存在']
    with pytest.raises(ValueError) as error:
        validate_dialogue(data)
    assert 'S01' in str(error.value) and 'S06' in str(error.value)


def test_short_total_and_open_ending_are_both_reported():
    data=fixture()
    for row in data['shots']:
        row['dialogue']='甲'
    data['shots'][-1]['dialogue']='甲？'
    with pytest.raises(ValueError) as error:
        validate_dialogue(data)
    assert 'total dialogue' in str(error.value) and 'closed statement' in str(error.value)
