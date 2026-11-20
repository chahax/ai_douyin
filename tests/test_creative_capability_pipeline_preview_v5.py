"""Root integration review against original receipts; no network or generation."""
import json
import socket

import pytest

from scripts import preview_creative_capability_pipeline_v5 as preview
from scripts import audit_creative_provider_environment_v1 as audit


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('capability-first preview must stay offline')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


def test_current_real_4_of_4_stays_zero_dispatch_and_keeps_exact_native_source(tmp_path):
    original = preview.PROJECT / preview.TRIAL / 'probe_v4'
    paths = [original / name for name in ('CALL_LEDGER.json', 'LOOP_STATE.json',
        'call_517_whole_direction_v3_3.json', 'PRODUCTION_RESULT.json')]
    before = {str(path): audit.sha(path) for path in paths}
    result = preview.build_preview(tmp_path / 'integration')
    assert result['actual_gate_reason'] == 'INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED'
    assert result['current_capacity']['attempts_including_claims'] == 4
    assert result['current_capacity']['remaining'] == 0
    assert result['actual_provider_invocations'] == result['new_generation_calls'] == result['new_media_calls'] == 0
    assert not result['budget_reset'] and not result['new_candidate_grant']
    assert not result['complete_text_handoff_ready'] and not result['production_dispatch_entry_integrated']
    assert not result['human_creative_quality_passed'] and not result['actual_media_quality_passed']
    assert result['source_review_proof']['writer_ordinal'] == 512
    assert result['source_review_proof']['review_ordinal'] == 513
    request = json.loads((tmp_path / 'integration/DIRECTOR_REQUEST.preview.json').read_text(encoding='utf-8'))
    source = json.loads(request['messages'][1]['content'])
    frozen = audit.read(preview.original.ROOT / 'INPUT.json')
    assert source['reference_fulltext'] == frozen['reference_fulltext']
    assert source['full_current_script'] == audit.read(preview.original.ROOT / 'ADOPTED_SOURCE.json')['script']
    assert source['known_complete_failure_diagnostics'][0]['original_result_identity']['result_id'] == '517'
    assert source['known_complete_failure_diagnostics'][0]['adopted'] is False
    assert source['brief'] == frozen['brief']
    assert source['production_context_binding']['production_context_sha256'] == result['source_review_proof']['production_context_sha256']
    assert source['production_context_binding']['prior_semantic_review_claim'] is False
    assert result['asset_status']['director_visual_request_enriched'] is False
    assert {row['voice_status'] for row in result['asset_status']['actor_bindings']} == {'unbound'}
    assert all(row['frozen_sources_unchanged'] for row in result['frozen_sources_after'])
    assert {str(path): audit.sha(path) for path in paths} == before
    with pytest.raises(FileExistsError):
        preview.build_preview(tmp_path / 'integration')


def test_changed_capacity_is_not_treated_as_a_new_grant(tmp_path, monkeypatch):
    # Alter the pure capacity result instead of mutating an actual old file.
    monkeypatch.setattr(preview.loop, 'candidate_capacity', lambda state: {
        'attempts_including_claims': 4, 'remaining': 1})
    with pytest.raises(ValueError, match='exact inherited gate changed'):
        preview.build_preview(tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()
