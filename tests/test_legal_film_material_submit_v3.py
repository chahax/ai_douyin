"""One exact instruction override, immutable lineage, and fake dispatch only."""
from copy import deepcopy
import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import run_legal_film_material_submit_v3_20261010 as m

_spec = importlib.util.spec_from_file_location('_material_submit_v3_helpers', Path(__file__).with_name('test_legal_film_material_sample_v1.py'))
old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('single-request tests are strictly offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def frozen():
    folder = m.ROOT / 'DELIVERABLE_material'
    x = m.read(m.ROOT / 'INPUT.json')
    return SimpleNamespace(auth=m.read(m.OUT / 'SINGLE_REQUEST_AUTHORIZATION.json'),
        preview=m.read(m.OUT / 'REQUEST.preapproval.preview.json'), scope=x['scope'],
        handoff=m.read(folder / 'HANDOFF.json'), prior=m.read(m.PREVIOUS_MEDIA / 'receipt.json'),
        snapshot=m.read(m.OUT / 'PREDECESSOR_TECHNICAL_SNAPSHOT.json'), asset=x['selected_asset_feedback'])


def validate(f):
    return m.validate_single_request_authorization(f.auth, f.preview, f.scope, f.handoff,
                                                  f.prior, f.snapshot, f.asset)


def pure_client():
    client = m.SeedanceClient.__new__(m.SeedanceClient)
    client.config = SimpleNamespace(model=m.MODEL, provider='ark_api')
    return client


def test_exact_human_instruction_request_and_pending_snapshot(frozen):
    before = deepcopy(frozen.__dict__)
    tail = validate(frozen)
    assert frozen.__dict__ == before
    assert frozen.auth['user_statement'] == '提交视频请求'
    assert frozen.auth['performance_ordinal'] == 394 and frozen.auth['review_ordinal'] == 395
    assert frozen.auth['request_sha256'] == m.REQUEST_SHA == m.digest(frozen.preview['request'])
    assert frozen.auth['compiled_sha256'] == m.COMPILED_SHA
    assert frozen.scope['requires_previous_human_approval'] is True
    assert frozen.handoff['requires_previous_candidate_explicit_human_approval'] is True
    assert frozen.snapshot['content_status'] == 'awaiting_human_review'
    assert frozen.snapshot['human_decision'] is None
    assert tail['human_approval_recorded'] is False
    assert tail['use_basis'] == 'explicit_single_request_user_instruction'
    assert frozen.auth['max_new_submissions'] == 1
    assert all(frozen.auth[k] is False for k in ['batch_authorized', 'later_segments_authorized', 'automatic_retry', 'budget_reset'])


@pytest.mark.parametrize('field,value', [('user_statement', '生成所有剩余视频'),
    ('max_new_submissions', 2), ('max_new_submissions', True), ('batch_authorized', True),
    ('later_segments_authorized', True), ('automatic_retry', True), ('budget_reset', True),
    ('performance_ordinal', 392), ('review_ordinal', 393), ('compiled_sha256', 'different'),
    ('source_sha256', 'different'), ('first_frame_sha256', 'different'),
    ('previous_content_approval_recorded', True)])
def test_expansion_or_different_source_cannot_use_exact_authorization(frozen, field, value):
    frozen.auth[field] = value
    with pytest.raises(ValueError, match='exact single request authorization'):
        validate(frozen)


def test_default_requirements_and_historical_preview_cannot_be_rewritten(frozen):
    frozen.scope['requires_previous_human_approval'] = False
    with pytest.raises(ValueError, match='historical approval requirement'):
        validate(frozen)
    frozen.scope['requires_previous_human_approval'] = True
    frozen.preview['dispatch_allowed'] = True
    with pytest.raises(ValueError, match='historical unsubmitted preview changed'):
        validate(frozen)


def test_later_real_approval_keeps_snapshot_and_rejection_blocks(frozen):
    frozen.prior['content_status'] = 'approved'
    frozen.prior['human_decision'] = 'approved'
    tail = validate(frozen)
    assert tail['human_approval_recorded'] is False
    assert frozen.snapshot['content_status'] == 'awaiting_human_review'
    frozen.prior['content_status'] = 'rejected'
    with pytest.raises(ValueError, match='rejected predecessor'):
        validate(frozen)


def test_actual_plan_exact_request_and_no_mutable_prior_receipt_in_sources(frozen):
    client = pure_client()
    plan = m.media_plan(client)
    assert m.request_for(client, plan) == frozen.preview['request']
    assert plan['image_role'] == 'first_frame'
    assert plan['previous_content_approval_recorded'] is False
    assert plan['base_authorization']['requires_previous_human_approval'] is True
    paths = {Path(row['path']).resolve() for row in plan['sources'].values()}
    assert (m.PREVIOUS_MEDIA / 'receipt.json').resolve() not in paths
    assert (m.OUT / 'PREDECESSOR_TECHNICAL_SNAPSHOT.json').resolve() in paths
    assert Path(frozen.asset['path']).resolve() in paths
    assert plan['first_frame']['sha256'] == m.FIRST_FRAME_SHA
    assert plan['duration_seconds'] == 13 and plan['source_refs'] == m.text_operator.REFS


def test_single_dispatch_unknown_has_no_retries_or_reservation_reset(monkeypatch, tmp_path):
    monkeypatch.setattr(old, 'm', m)
    fake = old.fake_service.__wrapped__(monkeypatch, tmp_path)
    old.test_unknown_dispatch_never_resubmits_or_resets_reservation(fake)


def test_original_id_query_saved_request_and_human_review_state(monkeypatch, tmp_path):
    monkeypatch.setattr(old, 'm', m)
    fake = old.fake_service.__wrapped__(monkeypatch, tmp_path)
    old.test_original_id_only_queries_and_success_still_pending_human(fake)
