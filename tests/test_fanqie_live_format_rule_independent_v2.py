"""Actual current-schema missing-rule receipt: pure local reconstruction."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from src.platform_adapter import fanqie_form_feedback_v1 as f
from test_fanqie_postclick_derivation_independent_v2 import mutate_post

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'data/production_trials/fanqie_alias_flow_20261116_v1'
DEV = ROOT/'data/flow_development/fanqie_alias_format_rule_20261117_v1'
CMD = '2a4e1474059d47d1a9ffd10be78fb4d2'
FOLDER = ROOT/'data/fanqie_account_control/commands'/CMD


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def ref(p):
    p = Path(p).resolve()
    return dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def put(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return ref(p)


def args():
    return dict(form_prepared_ref=ref(FOLDER/'FORM_PREPARED.json'), submit_claim_ref=ref(FOLDER/'SUBMIT_CLAIM.json'),
        code_manifest_ref=ref(RUN/'CODE_MANIFEST_POSTCLICK_BINDING_V3.json'),
        managed_source_ref=ref(DEV/'fanqie_managed_promotion_v1.py.before'),
        feedback_source_ref=ref(DEV/'fanqie_form_feedback_v1.py.before'),
        execution_approval_ref=ref(RUN/'ROOT_POSTCLICK_BINDING_V3_APPROVAL.json'),
        execution_plan_ref=ref(RUN/'flow_postclick_binding_v3/PLAN.json'),
        execution_state_ref=ref(RUN/'flow_postclick_binding_v3/STATE.json'))


def expected():
    return {k: read(FOLDER/'SUBMIT_CLAIM.json')['intent'][k] for k in ('book_id', 'book_name', 'alias')}


@pytest.fixture(autouse=True)
def no_external_or_original_write(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Only local CPU evidence reads are permitted')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    pins = [ref(FOLDER/'SUBMIT_RESPONSE.json'), *args().values(), ref(RUN/'DERIVED_FIRST_ALIAS_NAMING_VALIDATION_V2.json')]
    yield
    assert all(ref(p['path']) == p for p in pins)


def test_actual_9788_live_evidence_rebuild_keeps_observed_counts_and_original_result():
    raw = read(FOLDER/'SUBMIT_RESPONSE.json')
    doc = f.rebuild_live_validation(ref(FOLDER/'SUBMIT_RESPONSE.json'), expected(), **args())
    value = f.validate_alias_validation(doc, expected())
    assert doc['schema'] == 'fanqie_alias_validation_derivation/v2'
    assert doc['original_result'] == raw['result'] == 'post_submit_feedback_observed'
    assert doc['form_feedback'] == raw['form_feedback'] and doc['readback'] == raw['readback']
    assert value['observation'] == raw['form_feedback']['latest']
    assert value['observation']['alias_input_count'] == 1
    assert value['observation']['alias_input_attached'] is True
    assert value['same_alias'] is False and value['current_alias'] == ''
    assert value['submitted_alias'] == expected()['alias']
    assert value['alias_binding']['evidence_mode'] == 'source_bound_live_rule_derivation'
    assert value['known_message'] == '仅支持汉字及阿拉伯数字，字数限制为4-8字'
    assert value['rule_id'] == 'alias_format_invalid'
    assert value['server_response_evidence'] is False and value['platform_business_outcome_verified'] is False
    assert ref(FOLDER/'SUBMIT_RESPONSE.json')['sha256'] == '9788e2202f5f236566ed360c0c96f159b960a1703a7391ea6be3f13941672476'


def test_previous_formal_legacy_derivation_still_validates_without_rewriting():
    doc = read(RUN/'DERIVED_FIRST_ALIAS_NAMING_VALIDATION_V2.json')
    expected_old = {k: doc['alias_validation'][k] for k in ('book_id', 'book_name', 'alias')}
    value = f.validate_alias_validation(doc, expected_old)
    assert value['alias_binding']['evidence_mode'] == 'legacy_source_bound_derivation'
    assert value['same_alias'] is False and 'alias_input_count' not in value['observation']


@pytest.mark.parametrize('variant', ['missing_count', 'second_click', 'old_source', 'mixed_hint'])
def test_live_rebuild_never_uses_legacy_inference_or_ambiguous_feedback(tmp_path, variant):
    raw = read(FOLDER/'SUBMIT_RESPONSE.json')
    if variant == 'missing_count':
        mutate_post(raw, lambda s: s.pop('alias_input_count'))
    elif variant == 'second_click':
        raw['form_feedback']['click_count'] = 2
    elif variant == 'mixed_hint':
        mutate_post(raw, lambda s: s['messages'].append(dict(source='known_error_list', visible=True, attached=True,
            text='平台异常，请稍后重试')), sync_messages=True)
    folder = tmp_path/CMD
    response = put(folder/'SUBMIT_RESPONSE.json', raw)
    prep = put(folder/'FORM_PREPARED.json', read(FOLDER/'FORM_PREPARED.json'))
    claim = put(folder/'SUBMIT_CLAIM.json', read(FOLDER/'SUBMIT_CLAIM.json'))
    state = read(RUN/'flow_postclick_binding_v3/STATE.json')
    state['last_application']['result'].update(feedback_ref=response, form_prepared=prep, submit_response=response)
    inputs = args()
    inputs.update(form_prepared_ref=prep, submit_claim_ref=claim, execution_state_ref=put(tmp_path/'STATE.json', state))
    if variant == 'old_source':
        old = ROOT/'data/flow_development/fanqie_postclick_empty_binding_20261117_v1/fanqie_form_feedback_v1.py.before'
        inputs['feedback_source_ref'] = ref(old)
    with pytest.raises(ValueError):
        f.rebuild_live_validation(response, expected(), **inputs)
