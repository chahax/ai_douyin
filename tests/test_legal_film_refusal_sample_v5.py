"""Focused offline checks of unchanged-399 same-source v5 review and media isolation."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_film_refusal_review_v5_20261010 as text
from scripts import run_legal_film_refusal_sample_v5_20261010 as media
from src.content_factory import media_review_policy

_spec = importlib.util.spec_from_file_location('_refusal_v5_fake_media', Path(__file__).with_name('test_legal_film_material_sample_v1.py'))
old_media = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old_media)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('v5 review checks must remain offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def frozen():
    ledger = text.control.read(text.PREVIOUS / 'CALL_LEDGER.json')
    writer, review = [text.control.read(text.PREVIOUS / row['receipt']) for row in ledger['calls']]
    return SimpleNamespace(x=text.control.read(text.ROOT / 'INPUT.json'),
        anchor=text.control.read(text.ROOT / 'ANCHOR.json'), writer=writer, review=review,
        compiled=text.control.read(text.PREVIOUS / 'CURRENT_INTERACTION_COMPILED.json'),
        first=text.control.read(text.PREVIOUS / 'FIRST_SAMPLE.json'),
        prompt=(text.PREVIOUS / 'ACTUAL_FIRST_PROMPT.txt').read_text(encoding='utf-8-sig').rstrip('\n'))


def test_v5_only_new_review_preserves_399_400_source_and_inherited_spend(frozen):
    a = frozen.anchor
    assert a['inherited']['calls_started'] == 400
    assert a['inherited']['reported_tokens'] == 6488409
    assert a['inherited']['unknown_token_reservations'] == 93117
    assert a['inherited']['pending_ordinals'] == [70, 160]
    assert a['automatic_retry'] is False and a['budget_reset'] is False
    assert a['unchanged_performance_ordinal'] == 399 and a['preserved_disputed_review_ordinal'] == 400
    assert frozen.writer['ordinal'] == 399 and frozen.writer['status'] == 'contract_valid'
    assert frozen.writer['validation']['quality_passed'] is False
    assert frozen.review['ordinal'] == 400 and frozen.review['validation']['needs_revision'] is True
    assert frozen.x['disputed_full_review'] == frozen.review['output']
    dispute = frozen.x['independent_evidence_dispute']
    assert dispute['model_performance_rewritten'] is False
    assert dispute['new_same_source_full_review_required'] is True
    assert dispute['media_dispatch_authorized_by_this_record'] is False
    assert 'rejected_current_performance' not in frozen.x
    assert 'specific_revision_findings' not in frozen.x
    assert 'specific_revision_targets' not in frozen.x
    assert text.control.read(text.PREVIOUS / 'FULL_MODEL_CURRENT_PERFORMANCE.json') == frozen.writer['output']
    assert text.contract.compile_contract(frozen.writer['output'], frozen.x['background_full_script'], frozen.x['contract_spec']) == frozen.compiled
    assert text.contract.render_prompt(frozen.first, frozen.x['background_full_script'], frozen.x['contract_spec']) == frozen.prompt


def test_v5_actual_messages_full_unchanged_399_original_400_and_independent_evidence(monkeypatch, frozen):
    calls = []
    writes = []
    def dispatch(label, request, validator):
        calls.append((label, deepcopy(request), validator))
        return {'ordinal': 999, 'status': 'contract_valid', 'validation': validator(deepcopy(frozen.review['output']))}
    monkeypatch.setattr(text, 'prepare', lambda: None)
    monkeypatch.setattr(text, 'summary', lambda: {})
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(text, 'accepted', lambda label: deepcopy(frozen.writer))
    monkeypatch.setattr(text, 'compiled', lambda: deepcopy(frozen.compiled))
    monkeypatch.setattr(text, 'candidate', lambda: deepcopy(frozen.first))
    monkeypatch.setattr(text, 'prompt', lambda: frozen.prompt)
    monkeypatch.setattr(text.control, 'write', lambda path, value, *args: writes.append((path, deepcopy(value))))
    text.dispatch('review')
    assert len(calls) == 1
    label, request, validator = calls[0]
    assert label == text.REVIEW_LABEL and request['model'] == 'deepseek-flash'
    body = json.loads(request['messages'][1]['content'])
    assert body['background_full_script'] == frozen.x['background_full_script']
    assert body['reference_fulltext'] == frozen.x['reference_fulltext']
    assert body['full_model_current_performance'] == frozen.writer['output']
    assert body['disputed_full_review'] == frozen.review['output']
    assert body['independent_evidence_dispute'] == frozen.x['independent_evidence_dispute']
    assert body['compiled_current_interaction'] == frozen.compiled
    assert body['actual_first_sample'] == frozen.first and body['actual_first_prompt'] == frozen.prompt
    provenance = request['input_provenance']
    assert provenance['unchanged_performance_ordinal'] == 399
    assert provenance['unchanged_performance_sha256'] == text.control.digest(frozen.writer['output'])
    assert provenance['complete_disputed_review_in_actual_messages'] is True
    assert provenance['independent_evidence_dispute_in_actual_messages'] is True
    assert validator(deepcopy(frozen.review['output']))['needs_revision'] is True
    clean = deepcopy(frozen.review['output'])
    clean.update(issues=[], current_interaction_valid=True, exact_dialogue_and_scope_preserved=True)
    result = validator(clean)
    assert result['needs_revision'] is False and result['actual_media_quality_passed'] is False
    clean['current_interaction_valid'] = False
    assert validator(clean)['needs_revision'] is True
    with pytest.raises(ValueError, match='review-only unchanged performance'):
        text.dispatch('performance')
    assert len(calls) == 1
    assert len(writes) == 1 and writes[0][0] == text.ROOT / 'request_previews/review.json'
    assert writes[0][1] == request


def test_v5_default_second_tail_and_unchanged_media_once_unknown_query_and_pending(monkeypatch, tmp_path):
    assert media.validate_approved_tail is media_review_policy.validate_approved_tail
    approved = media.validate_approved_tail(media.PREVIOUS_MEDIA / 'receipt.human_review.json')
    assert approved['sha256'] == '8350e02f341876272865cec4e34d87b46ef2f93a3656e6afe8bd2ba10ea7c611'
    previous_path = Path(media.__file__).with_name('run_legal_film_refusal_sample_v4_20261010.py')
    def functions(path):
        return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(path.read_text(encoding='utf-8-sig')).body if isinstance(node, ast.FunctionDef)}
    old, current = functions(previous_path), functions(Path(media.__file__))
    for name in ['request_for', 'media_plan', 'media']:
        assert current[name] == old[name]
    x = text.control.read(text.ROOT / 'INPUT.json')
    assert x['scope']['requires_previous_human_approval'] is True
    assert x['scope']['max_new_submissions'] == 1 and x['scope']['budget_reset'] is False
    assert x['scope']['later_segments_authorized'] is False and x['scope']['automatic_retry'] is False
    for name, check in [('unknown', old_media.test_unknown_dispatch_never_resubmits_or_resets_reservation),
                        ('saved', old_media.test_original_id_only_queries_and_success_still_pending_human)]:
        folder = tmp_path / name
        folder.mkdir()
        with monkeypatch.context() as isolated:
            isolated.setattr(old_media, 'm', media)
            fake = old_media.fake_service.__wrapped__(isolated, folder)
            old_media.test_request_actual_native_first_frame_role_and_wrong_role_blocked(fake)
            check(fake)
