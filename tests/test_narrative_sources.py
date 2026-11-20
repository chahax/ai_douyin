"""Frozen cohort gate tests: no models, generation, repository writes or media downloads."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.trend_intelligence import narrative_sources as gate


@pytest.fixture
def cohort(monkeypatch):
    sources, analyses, observations = [], [], []
    for index in range(20):
        source = {'source_id': f'douyin:{index}', 'analysis_id': f'analysis:{index}',
            'collected_at': '2026-09-12T10:00:00+08:00', 'published_at': '',
            'metric_kind': 'likes_user_confirmed', 'metric_value': 50_000,
            'media_access_mode': 'local_media_authorized',
            'expression_analysis': {'evidence': [{'id': 'V1', 'text': f'Observed frame {index}'}]},
            'media_evidence': {'source_video_sha256': f'{index:064x}',
                               'visual': {'artifact_sha256': f'{index + 30:064x}'}},
            'independent_review': {'decision': 'passed_with_limits',
                'review_sha256': f'{index + 60:064x}', 'artifact_sha256': f'{index + 30:064x}',
                'source_video_sha256': f'{index:064x}'}}
        sources.append(source)
        analyses.append(SimpleNamespace(analysis_id=source['analysis_id'], item_id=source['source_id'],
            video_id=str(index), account_uuid='account', media_access_mode=source['media_access_mode'],
            expression_analysis=copy.deepcopy(source['expression_analysis'])))
        observations.append(SimpleNamespace(item_id=source['source_id'], video_id=str(index),
            collected_at=source['collected_at'], published_at='', metric_kind=source['metric_kind'],
            metric_value=source['metric_value'], run_id='batch', keyword=f'tag{index % 2}', root_keywords=[]))
    repo = SimpleNamespace(list_content_analyses=Mock(return_value=analyses),
                           list_observations=Mock(return_value=observations))
    media = Mock(return_value={'ready': True, 'artifacts_checked': True, 'ready_count': 20})
    live = copy.deepcopy(sources)
    read_live = Mock(return_value=live)
    monkeypatch.setattr(gate, 'batch_media_readiness', media)
    monkeypatch.setattr(gate, '_full_source_evidence', read_live)
    return SimpleNamespace(sources=sources, analyses=analyses, observations=observations,
                           repository=repo, media=media, live=live, read_live=read_live)


def workflow(cohort):
    return [{'role': 'system', 'content': 'Frozen project prompt'},
            {'role': 'user', 'content': json.dumps({'source_evidence': cohort.sources})}]


def verify(cohort):
    return gate.verify_workflow_sources(workflow(cohort), repository=cohort.repository)


def test_live_gate_revalidates_exact_versions_and_all_media(cohort):
    original = copy.deepcopy(cohort.sources)
    report = verify(cohort)
    assert report['sample_gate']['total_likes'] == 1_000_000
    assert report['collection_run_id'] == 'batch'
    assert report['source_count'] == len(report['source_bindings']) == 20
    assert report['media_generation'] is False
    assert report['automatic_editorial_approval'] is False
    assert cohort.sources == original
    assert cohort.media.call_args.kwargs == {'required_count': 20,
        'expected_item_ids': [source['source_id'] for source in original], 'verify_artifacts': True}
    json.dumps(report)  # No domain objects leak into the saved gate proof.


def test_newer_analysis_cannot_replace_frozen_analysis(cohort):
    cohort.analyses[0].analysis_id = 'newer-analysis'
    with pytest.raises(ValueError, match='exact frozen analysis'):
        verify(cohort)
    cohort.media.assert_not_called()


@pytest.mark.parametrize('field,value', [('metric_value', 51_000), ('collected_at', 'later')])
def test_changed_observation_cannot_satisfy_old_source(cohort, field, value):
    setattr(cohort.observations[0], field, value)
    with pytest.raises(ValueError, match='original metric/time'):
        verify(cohort)


def test_two_batches_cannot_be_combined(cohort):
    cohort.observations[0].run_id = 'another-batch'
    with pytest.raises(ValueError, match='common collection batch'):
        verify(cohort)


def test_single_tag_blocks_authoring(cohort):
    for observation in cohort.observations:
        observation.keyword = 'one-tag'
    with pytest.raises(ValueError, match='主要标签'):
        verify(cohort)
    cohort.media.assert_not_called()


def test_likes_and_views_are_never_added_together(cohort):
    for index in range(10):
        cohort.sources[index]['metric_kind'] = cohort.observations[index].metric_kind = 'views'
    with pytest.raises(ValueError, match='1,000,000'):
        verify(cohort)


@pytest.mark.parametrize('change', ['review_hash', 'review_rejected', 'video_hash', 'expression'])
def test_stale_live_artifacts_or_review_block_authoring(cohort, change):
    if change == 'review_hash':
        cohort.live[0]['independent_review']['review_sha256'] = 'f' * 64
    elif change == 'review_rejected':
        cohort.live[0]['independent_review']['decision'] = 'failed'
    elif change == 'video_hash':
        cohort.live[0]['media_evidence']['source_video_sha256'] = 'f' * 64
    else:
        cohort.live[0]['expression_analysis']['evidence'][0]['text'] = 'Changed analysis'
    with pytest.raises(ValueError, match='review|differs'):
        verify(cohort)


def test_actual_media_gate_failure_cannot_be_overridden_by_review_snapshot(cohort):
    cohort.media.return_value = {'ready': False, 'missing': [{'item_id': 'douyin:0', 'reasons': ['changed frame']}]}
    with pytest.raises(ValueError, match='media gate failed'):
        verify(cohort)
    cohort.read_live.assert_not_called()


def test_blocked_frozen_source_cannot_be_released_by_live_summary(cohort):
    cohort.sources[0]['independent_review']['blocked_for_script_generation'] = True
    with pytest.raises(ValueError, match='independent review'):
        verify(cohort)


def test_projection_must_be_restored_before_verification(cohort):
    cohort.sources[0]['evidence_projection'] = {'full_source_sha256': 'f' * 64}
    with pytest.raises(ValueError, match='restore full'):
        verify(cohort)


def test_different_ids_cannot_duplicate_one_video(cohort):
    cohort.analyses[0].video_id = cohort.observations[0].video_id = '1'
    with pytest.raises(ValueError, match='视频 19/20'):
        verify(cohort)
