import pytest
from src.content_factory.novel_adaptation.action_windows import action_windows


def scene(phase='after_audio', index=0):
    return {'id': 'S1', 'beats': [{'id': 'B1', 'start': 10, 'end': 22,
        'audio': [{'start': 11, 'end': 13}, {'start': 20, 'end': 22}],
        'transforms': [{'phase': phase, 'after_audio_index': index}],
        'action_order': [{'field': 'transforms', 'index': 0}]}]}


def test_after_audio_uses_remaining_beat_not_speech_duration():
    assert action_windows(scene())[0]['maximum_available_seconds'] == 9


def test_zero_window_is_reported_not_claimed_physically_impossible():
    row = action_windows(scene(index=1))[0]
    assert row['maximum_available_seconds'] == 0
    assert row['interpretation'] == 'shared_upper_bound_not_reserved_duration'


def test_concurrent_actions_do_not_each_get_exclusive_time():
    value = scene()
    value['beats'][0]['action_order'] *= 2
    assert [r['maximum_available_seconds'] for r in action_windows(value)] == [9, 9]


@pytest.mark.parametrize('phase,seconds', [('start',12), ('end',0)])
def test_boundary_phase(phase, seconds):
    assert action_windows(scene(phase))[0]['maximum_available_seconds'] == seconds


@pytest.mark.parametrize('index', [-1,2,True,None])
def test_missing_anchor_is_error(index):
    with pytest.raises(ValueError, match='action_audio_anchor_missing'):
        action_windows(scene(index=index))
