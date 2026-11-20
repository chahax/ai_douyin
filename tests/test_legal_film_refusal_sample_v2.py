"""Only v2 complete-repair projection and preserved service isolation."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_film_refusal_performance_v2_20261010 as text
from scripts import run_legal_film_refusal_sample_v2_20261010 as media
from src.content_factory import media_review_policy


def load_helper(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old_text = load_helper('_refusal_v1_projection_helpers', 'test_legal_film_refusal_sample_v1.py')
old_media = load_helper('_refusal_v2_media_helpers', 'test_legal_film_material_sample_v1.py')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('v2 refusal checks must remain offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def frozen():
    x = text.control.read(text.ROOT / 'INPUT.json')
    ledger = text.control.read(text.PREVIOUS / 'CALL_LEDGER.json')
    rejected = text.control.read(text.PREVIOUS / ledger['calls'][0]['receipt'])
    return SimpleNamespace(x=x, rejected=rejected, anchor=text.control.read(text.ROOT / 'ANCHOR.json'))


def test_exact_396_complete_rejection_and_spend_are_preserved(frozen):
    inherited = frozen.anchor['inherited']
    assert inherited['calls_started'] == 396 and inherited['reported_tokens'] == 6459283
    assert inherited['unknown_token_reservations'] == 93117 and inherited['pending_ordinals'] == [70, 160]
    assert frozen.anchor['revision_of_ordinal'] == 396
    assert frozen.anchor['automatic_retry'] is False and frozen.anchor['budget_reset'] is False
    assert frozen.rejected['status'] == 'contract_rejected'
    assert frozen.rejected['failure']['code'] == 'source dialogue copied into performance prose'
    assert frozen.x['rejected_current_performance'] == frozen.rejected['output']
    assert frozen.x['specific_revision_findings'][0]['code'] == 'DIALOGUE_REPEATED_IN_ACTING_PROSE'
    assert frozen.x['selected_asset_feedback']['human_approval_recorded'] is True
    assert frozen.x['scope']['requires_previous_human_approval'] is True


def test_actual_v2_writer_complete_repair_and_full_review_keep_source_boundaries(monkeypatch, frozen):
    prepared = SimpleNamespace(root=text.ROOT, x=frozen.x, written={
        str(text.ROOT / 'INPUT.json'): frozen.x,
        str(text.ROOT / 'ANCHOR.json'): frozen.anchor,
        str(text.ROOT / 'WRITER_SCHEMA.json'): text.contract.schema(frozen.x['background_full_script'], frozen.x['contract_spec'])})
    monkeypatch.setattr(old_text, 'text', text)
    monkeypatch.setattr(text, 'summary', lambda: {})
    monkeypatch.setattr(text.control, 'write', lambda *args: None)
    requests = old_text.requests.__wrapped__(monkeypatch, prepared)
    text.dispatch('performance')
    label, request, validator = requests.calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == text.WRITER_LABEL and request['model'] == 'MiniMax-M3'
    assert payload['rejected_current_performance'] == frozen.rejected['output']
    assert payload['specific_revision_findings'] == frozen.x['specific_revision_findings']
    assert payload['reference_fulltext'] == frozen.x['reference_fulltext']
    assert list(payload['current_interaction']['source_catalog']) == ['B2.S01', 'B2.S02']
    assert 'background_full_script' not in payload and 'previous_current_coverage' not in payload
    for ref, source in text.contract.catalog(frozen.x['background_full_script']).items():
        if source['kind'] == 'dialogue' and ref not in text.REFS:
            assert source['text'] not in request['messages'][1]['content']
    with pytest.raises(ValueError, match='source dialogue copied'):
        validator(frozen.rejected['output'])
    assert validator(requests.actor)['quality_passed'] is False
    text.dispatch('review')
    label, review, _ = requests.calls[1]
    body = json.loads(review['messages'][1]['content'])
    assert len(requests.calls) == 2
    assert label == text.REVIEW_LABEL and review['model'] == 'deepseek-flash'
    assert body['background_full_script'] == frozen.x['background_full_script']
    assert body['reference_fulltext'] == frozen.x['reference_fulltext']
    assert body['full_model_current_performance'] == requests.actor
    assert body['full_model_current_performance'] != frozen.rejected['output']
    assert body['actual_first_prompt'] == requests.prompt


def test_v2_approved_tail_unknown_once_and_saved_candidate_still_pending(monkeypatch, tmp_path):
    assert media.validate_approved_tail is media_review_policy.validate_approved_tail
    approval = media.validate_approved_tail(media.PREVIOUS_MEDIA / 'receipt.human_review.json')
    assert approval['sha256'] == '8350e02f341876272865cec4e34d87b46ef2f93a3656e6afe8bd2ba10ea7c611'
    for name, check in [('unknown', old_media.test_unknown_dispatch_never_resubmits_or_resets_reservation),
                        ('saved', old_media.test_original_id_only_queries_and_success_still_pending_human)]:
        folder = tmp_path / name
        folder.mkdir()
        with monkeypatch.context() as isolated:
            isolated.setattr(old_media, 'm', media)
            fake = old_media.fake_service.__wrapped__(isolated, folder)
            old_media.test_request_actual_native_first_frame_role_and_wrong_role_blocked(fake)
            check(fake)
