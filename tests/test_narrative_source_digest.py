import copy

import pytest

from scripts.run_narrative_workflow import author_payload, source_digest


def test_digest_preserves_semantics_original_rows_and_limits_without_media_inventory():
    source = {'source_id': 'douyin:x', 'metric_kind': 'likes', 'metric_value': 12,
        'media_evidence': {'private_path': 'local-only'},
        'expression_analysis': {'core_message': {'text': 'observed action', 'evidence_ids': ['V1', 'V2', 'V3']},
            'uncertainties': ['audio not checked'], 'evidence': [
                {'id': 'V1', 'channel': 'visual', 'text': 'before'},
                {'id': 'V2', 'channel': 'visual', 'text': 'middle'},
                {'id': 'V3', 'channel': 'visual', 'text': 'after'},
                {'id': 'A1', 'channel': 'asr', 'text': 'words'}]},
        'independent_review': {'decision': 'passed_with_limits', 'limits': ['motion unverified']},
        'emotion_analysis': {'status': 'model_observed_unverified', 'limitations': ['unknown voice'], 'windows': ['large']}}
    original = copy.deepcopy(source)
    result = source_digest(source)
    assert source == original
    assert result['expression_analysis']['core_message'] == source['expression_analysis']['core_message']
    assert [r['id'] for r in result['expression_analysis']['evidence']] == ['V1', 'V3', 'A1']
    assert all(r in source['expression_analysis']['evidence'] for r in result['expression_analysis']['evidence'])
    assert result['evidence_projection']['total_evidence_rows'] == 4
    assert 'media_evidence' not in result
    assert 'windows' not in result['emotion_analysis']
    assert result['independent_review']['limits'] == ['motion unverified']
    assert result['emotion_analysis']['limitations'] == ['unknown voice']


def test_projection_keeps_all_twenty_sources_and_legacy_payload_replay():
    context = {'source_evidence': [{'source_id': str(i), 'expression_analysis': {'evidence': []}} for i in range(20)],
               'reference': {'source_id': 'local:x', 'source': {'path': 'private'}, 'insights': []}, 'brief': 'actual brief'}
    legacy = author_payload(context, 'outline', None)
    current = author_payload(context, 'outline', None, projection_version='source_digest_v2')
    assert legacy['source_evidence'] == context['source_evidence']
    assert [s['source_id'] for s in current['source_evidence']] == [str(i) for i in range(20)]
    assert current['brief'] == 'actual brief'
    assert 'source' not in current['reference']
    with pytest.raises(ValueError, match='projection'):
        author_payload(context, 'outline', None, projection_version='invented')


def test_v3_keeps_cohort_and_selects_demonstrations_and_conflict_examples():
    sources = []
    for i in range(20):
        mode = 'conflict_drama' if i < 3 else 'prop_demonstration' if i < 6 else 'direct_explanation'
        sources.append({'source_id': str(i), 'metric_value': 20-i,
            'expression_analysis': {'core_message': {'text': 'verified core', 'evidence_ids': ['V1', 'V2', 'V3']},
                'expression_modes': [{'mode': mode}], 'visual_expression': [{'text': 'full detail'}],
                'uncertainties': ['not acoustically verified'],
                'evidence': [{'id': 'V'+str(n), 'channel': 'visual', 'text': str(n)} for n in range(1,4)]}})
    context = {'source_evidence': sources, 'reference': {'source_id': 'local:x', 'insights': []}}
    projected = author_payload(context, 'outline', None, projection_version='source_digest_v3')
    assert len(projected['source_evidence']) == 20
    assert projected['detailed_source_ids'] == ['0', '1', '3', '4']
    assert 'visual_expression' in projected['source_evidence'][0]['expression_analysis']
    overview = projected['source_evidence'][-1]['expression_analysis']
    assert overview['core_message'] == sources[-1]['expression_analysis']['core_message']
    assert overview['uncertainties'] == ['not acoustically verified']
    assert [r['id'] for r in overview['evidence']] == ['V1', 'V3']


def test_v4_claim_ids_cannot_point_to_omitted_evidence_and_does_not_mutate_context():
    source = {'source_id': 'source', 'expression_analysis': {
        'core_message': {'text': 'unchanged semantic text', 'evidence_ids': ['V1', 'V2', 'V3']},
        'evidence': [{'id': 'V'+str(i), 'channel': 'visual', 'text': str(i)} for i in range(1,4)]}}
    context = {'source_evidence': [source], 'reference': {'source_id': 'local:x', 'insights': []}}
    original = copy.deepcopy(context)
    payload = author_payload(context, 'outline', None, projection_version='source_digest_v4')
    expression = payload['source_evidence'][0]['expression_analysis']
    assert context == original
    assert expression['core_message']['text'] == 'unchanged semantic text'
    assert expression['core_message']['evidence_ids'] == ['V1', 'V3']
    assert set(expression['core_message']['evidence_ids']) <= {e['id'] for e in expression['evidence']}


def test_v5_is_explicit_background_and_exposes_no_direct_cohort_citations():
    source = {'source_id': 'source', 'metric_kind': 'likes', 'metric_value': 100,
        'expression_analysis': {'core_message': {'text': 'core with its original qualifications', 'evidence_ids': ['V1']},
            'expression_modes': [{'mode': 'direct_explanation', 'evidence_ids': ['V1']}],
            'evidence': [{'id': 'V1', 'text': 'full original'}]},
        'independent_review': {'decision': 'passed_with_limits', 'acoustic_status': 'not_reviewed'}}
    context = {'source_evidence': [source], 'reference': {'source_id': 'local:x', 'insights': [{'id': 'B03'}]}}
    original = copy.deepcopy(context)
    payload = author_payload(context, 'outline', None, projection_version='source_overview_v5')
    projected = payload['source_evidence'][0]
    assert context == original
    assert projected['expression_analysis']['core_message']['text'] == source['expression_analysis']['core_message']['text']
    assert projected['expression_analysis']['evidence'] == []
    assert projected['evidence_projection']['direct_citation_allowed'] is False
    assert projected['review_scope']['acoustic_status'] == 'not_reviewed'
    assert payload['reference']['insights'] == [{'id': 'B03'}]
