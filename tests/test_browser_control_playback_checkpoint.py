"""Playback resumes the real loop after a foreground job at an item boundary."""
from types import SimpleNamespace

import pytest

from src.platform_adapter import douyin_playback as playback


def test_foreground_time_does_not_exhaust_background_budget(monkeypatch):
    from src.operations_accounts import browser_control_runtime as control
    clock = [100.0]
    events = []
    snapshots = []
    monkeypatch.setattr(playback.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(playback, 'enrich_candidate_engagement_signals', lambda rows: rows)

    def safe_point(cursor):
        snapshots.append(cursor)
        if cursor['next_candidate_index'] == 1:
            events.append('publish')
            clock[0] += 120.0
            return 120.0
        return 0.0

    monkeypatch.setattr(control, 'background_safe_point', safe_point)
    controller = playback.DouyinRelevantPlaybackController(SimpleNamespace())

    def play(candidate, *, planned_seconds):
        events.append(candidate['video_id'])
        clock[0] += 3
        return playback.PlaybackItemResult(video_id=candidate['video_id'], title='',
            author='', url='', relevance_score=90, playback_verified=True, actual_watch_seconds=3)

    monkeypatch.setattr(controller, '_play_candidate', play)
    result = controller.run([{'video_id': 'one'}, {'video_id': 'two'}],
        playback.PlaybackOptions(max_videos=2, total_minutes=1), domain_strategy_id='legal_services')
    assert events == ['one', 'publish', 'two']
    assert [item.video_id for item in result.items] == ['one', 'two']
    assert snapshots[1]['completed']['verified_videos'] == 1
    assert snapshots[1]['completed']['actual_watch_seconds'] == 3
    assert result.verified_videos == 2 and result.actual_watch_seconds == 6


def test_unsafe_foreground_outcome_does_not_resume_next_item(monkeypatch):
    from src.operations_accounts import browser_control_runtime as control
    monkeypatch.setattr(playback, 'enrich_candidate_engagement_signals', lambda rows: rows)
    controller = playback.DouyinRelevantPlaybackController(SimpleNamespace())
    seen = []

    def safe_point(cursor):
        if cursor['next_candidate_index'] == 1:
            raise RuntimeError('foreground_result_unknown')
        return 0.0

    monkeypatch.setattr(control, 'background_safe_point', safe_point)
    def play(candidate, **kwargs):
        seen.append(candidate['video_id'])
        return playback.PlaybackItemResult(video_id=candidate['video_id'], title='', author='',
            url='', relevance_score=90, playback_verified=True)
    monkeypatch.setattr(controller, '_play_candidate', play)
    with pytest.raises(RuntimeError, match='foreground_result_unknown'):
        controller.run([{'video_id': 'one'}, {'video_id': 'two'}],
            playback.PlaybackOptions(max_videos=2), domain_strategy_id='legal_services')
    assert seen == ['one']
