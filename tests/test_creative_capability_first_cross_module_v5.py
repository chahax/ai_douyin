"""Use the actual A/B/C modules together with explicit synthetic evidence."""
from copy import deepcopy
import json
import socket

import pytest

from src.content_factory import creative_reference_compiler_v4 as references
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from tests.test_creative_reference_compiler_v4 import create_asset, NOW, ACCOUNT, MODEL
from tests.test_creative_complete_production_coordinator_v4 import run


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('cross-module integration is synthetic and offline')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


def make_enricher(root, *, omit_last=False):
    contracts = []
    def enrich(request):
        manifest = json.loads(request['messages'][1]['content'])['shared_manifest']
        required = [{'entity_type': kind, 'entity_id': row['id']}
            for kind, rows in (('actor', manifest['actors']), ('scene', manifest['scenes'])) for row in rows]
        assets, mappings, gets = [], [], {}
        evidence_root = root / ('synthetic_originals_' + str(len(contracts)))
        evidence_root.mkdir()
        for index, entity in enumerate(required):
            if omit_last and index == len(required) - 1:
                continue
            aid = 'synthetic_bound_' + str(index)
            native = entity['entity_type'] == 'actor'
            asset, mapping, get = create_asset(evidence_root, aid, 'image',
                'first_frame' if native else 'reference_image', entity['entity_type'],
                entity['entity_id'], native=native)
            # A service's original tail is used here as an ordinary reference,
            # never falsely claimed to be the formal continuation first frame.
            asset['role'] = 'reference_image'
            assets.append(asset)
            mappings.append(mapping)
            if native:
                gets[aid] = get
        contract = {'schema': references.BINDING_SCHEMA, 'provider_id': 'ark_api',
            'model': MODEL, 'mode': 'multimodal_reference',
            'input_account_binding_sha256': ACCOUNT, 'assets': assets,
            'entity_bindings': mappings, 'required_entities': required, 'voices': []}
        contracts.append(deepcopy(contract))
        visual = references.build_director_visual_messages(request['messages'], contract,
            [asset['asset_id'] for asset in reversed(assets)], now=NOW,
            expected_account_binding_sha256=ACCOUNT, provider_get_evidence=gets)
        actual = deepcopy(request)
        actual['messages'] = visual['messages']
        return {'request': actual, 'coverage': visual['coverage']}
    return enrich, contracts


def test_actual_reference_compiler_enriches_actual_coordinator_requests_and_review(tmp_path):
    enrich, contracts = make_enricher(tmp_path)
    result, service = run(tmp_path, enricher=enrich)
    assert result['complete_text_handoff_ready']
    assert [row['request']['stage'] for row in service.calls] == [
        'whole_direction', 'local_performance', 'local_performance', 'whole_production_review']
    director_request = service.calls[0]['request']
    image_ids = [row['asset_id'] for row in result['director_visual_request_proof']['ordered_images']]
    assert image_ids == [row['asset_id'] for row in reversed(contracts[0]['assets'])]
    assert 'R01完整教学参考全文' in director_request['messages'][1]['content']
    assert all(row['type'] == 'image_url' for row in director_request['messages'][-1]['content'][1:])
    for receipt in service.calls:
        assert receipt['request_sha256'] == pipeline.digest(receipt['request'])
    review = json.loads(service.calls[-1]['request']['messages'][1]['content'])
    assert review['director_visual_request_proof'] == result['director_visual_request_proof']
    assert review['director_actual_request_sha256'] == pipeline.digest(director_request)
    assert 'data:image' not in service.calls[-1]['request']['messages'][1]['content']
    assert not result['media_dispatch_allowed'] and not result['human_creative_quality_passed']
    assert not result['actual_media_quality_passed']


def test_missing_actual_required_scene_stops_before_director_claim(tmp_path):
    enrich, _ = make_enricher(tmp_path, omit_last=True)
    result, service = run(tmp_path, enricher=enrich)
    assert result['reason'] == 'DIRECTOR_REFERENCE_BINDING_INVALID'
    assert service.calls == [] and not result['loop_state']['director_events']


def test_exact_selected_originals_are_reused_only_for_unchanged_local_inputs(tmp_path):
    # Distinct evidence paths/receipt hashes mean new identities, even though
    # synthetic pixel bytes are equal. Changed approved source identities must
    # invalidate local requests, then trigger a fresh full review.
    enrich, _ = make_enricher(tmp_path)
    result, service = run(tmp_path, mode='review_fail', enricher=enrich)
    assert result['complete_text_handoff_ready'] and service.directors == service.reviews == 2
    locals_ = [row for row in service.calls if row['request']['stage'] == 'local_performance']
    assert len(locals_) == 4
    visual_bindings = [json.loads(row['request']['messages'][1]['content'])['director_visual_binding']
        for row in (locals_[0], locals_[2])]
    assert visual_bindings[0]['selected_material_sha256'] != visual_bindings[1]['selected_material_sha256']
