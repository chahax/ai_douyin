"""Independent pure-CPU verification of the actual 2266 receipt and mutations.

Only immutable existing files are read. Mutated scenarios use fresh local
copies with their refs coherently rebound, so the negative cases exercise
meaning rather than merely an old checksum. No actual typed artifact is saved.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from src.platform_adapter import fanqie_form_feedback_v1 as f

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'data/production_trials/fanqie_alias_flow_20261116_v1'
DEV = ROOT/'data/flow_development/fanqie_postclick_empty_binding_20261117_v1'
COMMAND = '0da0d53eac2a4b53bb9be45818a56b57'
FOLDER = ROOT/'data/fanqie_account_control/commands'/COMMAND


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bound(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return bound(path)


def actual_args():
    return dict(form_prepared_ref=bound(FOLDER/'FORM_PREPARED.json'),
        submit_claim_ref=bound(FOLDER/'SUBMIT_CLAIM.json'),
        code_manifest_ref=bound(RUN/'CODE_MANIFEST_SEARCH_SCOPE_FIX.json'),
        managed_source_ref=bound(DEV/'fanqie_managed_promotion_v1.py.before'),
        feedback_source_ref=bound(DEV/'fanqie_form_feedback_v1.py.before'),
        execution_approval_ref=bound(RUN/'ROOT_SEARCH_SCOPE_FIX_APPROVAL.json'),
        execution_plan_ref=bound(RUN/'flow_search_scope_fix_v2/PLAN.json'),
        execution_state_ref=bound(RUN/'flow_search_scope_fix_v2/STATE.json'))


@pytest.fixture(autouse=True)
def no_external_and_preserve_originals(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Post-click derivation must be pure local CPU')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    refs = [bound(FOLDER/'SUBMIT_RESPONSE.json'), *actual_args().values(),
        bound(RUN/'flow/STATE.json'),
        bound(ROOT/'data/fanqie_account_control/promotion_application_claims/2c4a85f9f20a17b15bbfac76500079781a48b666018a82f9d31eec0ef6aea0f2/CLAIM.json'),
        bound(ROOT/'data/fanqie_account_control/promotion_application_claims/8f82149fad28354b20ca946f84d24b995941a843dcf172a8929e84d6139d1c0a/CLAIM.json')]
    yield
    assert all(bound(r['path']) == r for r in refs)


def expected():
    claim = read(FOLDER/'SUBMIT_CLAIM.json')
    return {k: claim['intent'][k] for k in ('book_id', 'book_name', 'alias')}


def derive(response_ref, args):
    return f.derive_alias_validation(response_ref, expected(), **args)


def clone(tmp_path, mutate_raw=None, mutate_claim=None, mutate_prepared=None,
          mutate_state=None, mutate_approval=None, mutate_plan=None):
    folder = tmp_path/COMMAND
    raw = read(FOLDER/'SUBMIT_RESPONSE.json')
    prepared = read(FOLDER/'FORM_PREPARED.json')
    claim = read(FOLDER/'SUBMIT_CLAIM.json')
    state = read(RUN/'flow_search_scope_fix_v2/STATE.json')
    plan = read(RUN/'flow_search_scope_fix_v2/PLAN.json')
    approval = read(RUN/'ROOT_SEARCH_SCOPE_FIX_APPROVAL.json')
    if mutate_raw:
        mutate_raw(raw)
    if mutate_claim:
        mutate_claim(claim)
    if mutate_prepared:
        mutate_prepared(prepared)
    response = put(folder/'SUBMIT_RESPONSE.json', raw)
    prep = put(folder/'FORM_PREPARED.json', prepared)
    claim_ref = put(folder/'SUBMIT_CLAIM.json', claim)
    state['last_application']['result'].update(feedback_ref=response,
        form_prepared=prep, submit_response=response)
    if mutate_state:
        mutate_state(state)
    if mutate_plan:
        mutate_plan(plan)
    if mutate_approval:
        mutate_approval(approval)
    args = actual_args()
    args.update(form_prepared_ref=prep, submit_claim_ref=claim_ref,
        execution_state_ref=put(tmp_path/'STATE.json', state),
        execution_plan_ref=put(tmp_path/'PLAN.json', plan),
        execution_approval_ref=put(tmp_path/'APPROVAL.json', approval))
    return response, args


def mutate_post(raw, change, *, sync_messages=False):
    h = raw['form_feedback']
    old = deepcopy(h['post_click'][0])
    sample = deepcopy(old)
    change(sample)
    h['post_click'][0] = sample
    h['latest'] = deepcopy(sample)
    h['observations'] = [deepcopy(sample) if s == old else s for s in h['observations']]
    ui = raw['submission_feedback']['observations'][0]
    ui['observed_at'] = sample['observed_at']
    if sync_messages:
        ui['messages'] = deepcopy(sample['messages'])
        ui['changed_messages'] = deepcopy(sample['messages'])


def test_actual_2266_derives_only_in_memory_without_inventing_legacy_observations():
    raw = read(FOLDER/'SUBMIT_RESPONSE.json')
    doc = derive(bound(FOLDER/'SUBMIT_RESPONSE.json'), actual_args())
    value = f.validate_alias_validation(doc, expected())
    assert doc['schema'] == 'fanqie_alias_validation_derivation/v1'
    assert doc['original_result'] == raw['result'] == 'post_submit_feedback_observed'
    assert doc['form_feedback'] == raw['form_feedback']
    assert doc['readback'] == raw['readback']
    assert doc['submission_feedback'] == raw['submission_feedback']
    assert value['schema'] == 'fanqie_alias_validation/v2'
    assert value['same_alias'] is False and value['current_alias'] == ''
    assert value['submitted_alias'] == expected()['alias'] and value['submitted_alias_bound'] is True
    assert value['alias_binding']['evidence_mode'] == 'legacy_source_bound_derivation'
    assert value['alias_binding']['alternative_alias_scope'] == 'not_observed_in_captured_samples'
    assert value['alias_binding']['react_internal_state_verified'] is False
    assert value['server_response_evidence'] is False and value['platform_business_outcome_verified'] is False
    assert all(k not in value['observation'] for k in ('modal_count', 'alias_input_count', 'alias_input_attached'))
    assert 'click_count' not in doc['form_feedback'] and 'post_click_field_writes' not in doc['form_feedback']
    assert bound(FOLDER/'SUBMIT_RESPONSE.json')['sha256'] == '2266f7ebd5af433f8709564be2372def12dff2890d2bc2decf676d351bb0ba41'
    # The global once claim is the same original intent, not a new submission.
    global_claim = ROOT/'data/fanqie_account_control/promotion_application_claims/2c4a85f9f20a17b15bbfac76500079781a48b666018a82f9d31eec0ef6aea0f2/CLAIM.json'
    assert read(global_claim) == read(FOLDER/'SUBMIT_CLAIM.json')
    assert bound(global_claim)['sha256'] == '3f7a909c9a9e7ab39c29a366f4187c3a4e1eff317d2a143d7b0b769dc0878c8b'


def test_coherently_rebound_immutable_copy_is_a_valid_semantic_baseline(tmp_path):
    response, args = clone(tmp_path)
    assert f.confirmed_alias_validation(derive(response, args), expected())


@pytest.mark.parametrize('variant', [
    'explicit_second_click', 'legacy_post_field_write', 'legacy_count_two',
    'stale_ui_baseline', 'contradictory_disabled_button', 'earlier_other_alias',
    'success_hint', 'baseline_success_hint', 'mixed_hint', 'other_current_alias',
    'wrong_book', 'reversed_time', 'late_time', 'preclick_other_alias',
])
def test_rebound_causal_contradictions_never_derive_naming_failure(tmp_path, variant):
    def mutate(raw):
        h = raw['form_feedback']; ui = raw['submission_feedback']
        if variant == 'explicit_second_click':
            h['click_count'] = 2
        elif variant == 'legacy_post_field_write':
            h['post_click_field_writes'] = 1
        elif variant == 'legacy_count_two':
            mutate_post(raw, lambda s: s.update(alias_input_count=2))
        elif variant == 'stale_ui_baseline':
            ui['baseline']['messages'] = deepcopy(h['post_click'][0]['messages'])
        elif variant == 'contradictory_disabled_button':
            mutate_post(raw, lambda s: s['submit_buttons'][0].update(disabled=False, aria_disabled=False, enabled=False))
        elif variant == 'earlier_other_alias':
            s = h['observations'][0]
            assert s['stage'] == 'pre_click'
            s.update(current_alias='另一条未授权词', same_alias=False)
        elif variant in ('success_hint', 'baseline_success_hint'):
            title = dict(source='known_result_title', visible=True, attached=True, text='申请成功')
            target = ui['baseline'] if variant == 'baseline_success_hint' else ui['observations'][0]
            target['titles'] = [title]
        elif variant == 'mixed_hint':
            mutate_post(raw, lambda s: s['messages'].append(dict(source='known_error_list', visible=True, attached=True, text='网络异常，请稍后重试')), sync_messages=True)
        elif variant == 'other_current_alias':
            mutate_post(raw, lambda s: s.update(current_alias='另一条未授权词', same_alias=False))
        elif variant == 'wrong_book':
            mutate_post(raw, lambda s: s.update(book_id='8302660145530539062', observed_book_ids=['8302660145530539062']))
        elif variant in ('reversed_time', 'late_time'):
            stamp = h['pre_click']['observed_at'] + (-.1 if variant == 'reversed_time' else 8)
            mutate_post(raw, lambda s: s.update(observed_at=stamp))
        elif variant == 'preclick_other_alias':
            h['pre_click'].update(current_alias='另一条未授权词', same_alias=False)
    response, args = clone(tmp_path, mutate_raw=mutate)
    with pytest.raises(ValueError):
        derive(response, args)


@pytest.mark.parametrize('variant', ['wrong_command', 'wrong_claim_alias', 'wrong_request', 'wrong_source', 'wrong_approval', 'wrong_batch', 'raw_hash_changed'])
def test_cross_command_source_and_claim_binding_fail_closed(tmp_path, variant):
    claim_change = None
    state_change = None
    approval_change = None
    if variant == 'wrong_command':
        claim_change = lambda c: c.update(command_id='different-command')
    elif variant == 'wrong_claim_alias':
        claim_change = lambda c: c['intent'].update(alias='另一条未授权词')
    elif variant == 'wrong_request':
        other = put(tmp_path/'OTHER_REQUEST.json', dict(schema='fanqie_promotion_apply_request/v1', alias='另一条词'))
        claim_change = lambda c: c.update(request=other)
    elif variant == 'wrong_approval':
        approval_change = lambda a: a.pop('source_manifest')
    elif variant == 'wrong_batch':
        state_change = lambda s: s['last_application'].update(command_id='different-command')
    response, args = clone(tmp_path, mutate_claim=claim_change, mutate_state=state_change, mutate_approval=approval_change)
    if variant == 'wrong_source':
        args['managed_source_ref'] = args['feedback_source_ref']
    elif variant == 'raw_hash_changed':
        Path(response['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError):
        derive(response, args)


def test_a_derived_document_cannot_forge_current_alias_or_evidence_mode():
    doc = derive(bound(FOLDER/'SUBMIT_RESPONSE.json'), actual_args())
    for key, value in [('same_alias', True), ('current_alias', expected()['alias']),
                       ('submitted_alias', '另一条未授权词'), ('server_response_evidence', True)]:
        bad = deepcopy(doc); bad['alias_validation'][key] = value
        with pytest.raises(ValueError):
            f.validate_alias_validation(bad, expected())
