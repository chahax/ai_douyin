import copy
import json
import pytest
from scripts.run_reference_director import approved, digest
from scripts.run_reference_performance_beat import context_binding, verify_context, validate_beat


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def reviewed(folder, value):
    folder.mkdir()
    save(folder/'raw.txt', value)
    save(folder/'candidate.json', value)
    save(folder/'validation.json', {'status': 'structure_valid_semantics_pending'})
    save(folder/'review.json', {'decision': 'passed', 'candidate_sha256': digest(folder/'candidate.json'),
                              'unresolved': [], 'findings': [{'evidence': 'fixture', 'finding': 'fixture'}]})


def test_assembly_does_not_allow_authored_content_to_change(tmp_path):
    values = []
    sources = []
    for index in range(1, 5):
        folder = tmp_path/f'B{index:02}'
        value = {'id': folder.name, 'actions': [], 'lines': [],
                 'end_positions': {'A': '门内', 'B': '门外'}, 'risks': []}
        reviewed(folder, value)
        values.append(value)
        sources.append({'folder': str(folder), 'candidate_sha256': digest(folder/'candidate.json'),
                        'review_sha256': digest(folder/'review.json')})
    final = tmp_path/'performance'
    expected = {'beats': [{k: v for k, v in row.items() if k != 'risks'} for row in values], 'risks': []}
    reviewed(final, expected)
    (final/'raw.txt').unlink()
    save(final/'assembly.json', {'recipe': 'approved_performance_beats/v1', 'sources': sources})
    assert approved(final) == expected
    changed = copy.deepcopy(expected)
    changed['beats'][0]['end_positions']['B'] = '已进门'
    save(final/'candidate.json', changed)
    review = json.loads((final/'review.json').read_text())
    review['candidate_sha256'] = digest(final/'candidate.json')
    save(final/'review.json', review)
    with pytest.raises(ValueError, match='preserve'):
        approved(final)


def test_updated_previous_beat_invalidates_downstream_context(tmp_path):
    for stage in ('story', 'emotion', 'visual', 'B01'):
        reviewed(tmp_path/stage, {'fixture': stage})
    second = tmp_path/'B02'
    second.mkdir()
    payload = {'source_bindings': context_binding(tmp_path, tmp_path/'B01')}
    save(second/'request.json', [{'role': 'system', 'content': ''},
                                {'role': 'user', 'content': json.dumps(payload)}])
    verify_context(tmp_path, second, tmp_path/'B01')
    save(tmp_path/'B01'/'candidate.json', {'fixture': 'different end state'})
    with pytest.raises(ValueError, match='different upstream'):
        verify_context(tmp_path, second, tmp_path/'B01')


def test_extra_beat_is_rejected_before_action_validation():
    with pytest.raises(ValueError, match='exact locked beat'):
        validate_beat({'id': 'B05'}, 'B01', {'emotion': {'beats': [{'id': 'B01'}]}})
