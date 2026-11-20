"""Small v2 regression for complete-current repair and unchanged tail approval."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_film_material_performance_v2_20261010 as text
from scripts import run_legal_film_material_sample_v2_20261010 as media

_spec = importlib.util.spec_from_file_location('_material_sample_v1_test_helpers', Path(__file__).with_name('test_legal_film_material_sample_v1.py'))
old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('v2 tests are strictly offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    root = tmp_path / 'round02'
    written = {}
    monkeypatch.setattr(text, 'ROOT', root)
    monkeypatch.setattr(text.control, 'write', lambda path, value, *args: written.update({str(path): deepcopy(value)}))
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(prepare=lambda: None))
    monkeypatch.setattr(text, 'summary', lambda: {})
    text.prepare()
    return SimpleNamespace(root=root, written=written, x=written[str(root / 'INPUT.json')],
                           anchor=written[str(root / 'ANCHOR.json')])


@pytest.fixture
def requests(monkeypatch, prepared):
    calls = []
    actor = {'continuous_performance': '周姐边说明边一次将纸笔送到小林近桌沿，收回手。小林等纸到位看清原因栏后抬眼问周姐，没碰笔。',
             'zhou_intent': '让小林按材料办手续', 'xiaolin_intent': '要求解释为何写成本人意愿',
             'camera': '同侧观察小林看清事实后的质问，周姐是明确受问对象，完整反问后结束。',
             'delivery': '正常普通话对话，反问由看清事实后的求解释行动产生，不照念。', 'post_pause_seconds': .4}
    compiled = text.contract.compile_contract(actor, prepared.x['background_full_script'])
    candidate = text.contract.pack_first(compiled)
    def dispatch(label, request, validator):
        calls.append((label, deepcopy(request), validator))
        return {'ordinal': 999, 'status': 'contract_rejected'}
    read = text.control.read
    monkeypatch.setattr(text.control, 'read', lambda path: deepcopy(prepared.written[str(path)]) if str(path) in prepared.written else read(path))
    monkeypatch.setattr(text, 'prepare', lambda: None)
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(text, 'compiled', lambda: deepcopy(compiled))
    monkeypatch.setattr(text, 'candidate', lambda: deepcopy(candidate))
    monkeypatch.setattr(text, 'accepted', lambda label: {'output': deepcopy(actor)})
    return SimpleNamespace(calls=calls, actor=actor, compiled=compiled, candidate=candidate)


def test_v2_prepare_carries_393_spend_unknowns_and_exact_independent_finding(prepared):
    inherited = prepared.anchor['inherited']
    assert inherited['calls_started'] == 393 and inherited['reported_tokens'] == 6442173
    assert inherited['unknown_token_reservations'] == 93117 and inherited['pending_ordinals'] == [70, 160]
    assert prepared.anchor['automatic_retry'] is False and prepared.anchor['budget_reset'] is False
    predecessor = text.control.read(text.PREVIOUS / 'CALL_LEDGER.json')
    model = text.control.read(text.PREVIOUS / predecessor['calls'][0]['receipt'])
    gate = text.control.read(text.PREVIOUS / 'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')
    assert prepared.x['rejected_current_performance'] == model['output']
    assert prepared.x['specific_revision_findings'] == gate['unresolved_mandatory_findings']
    assert prepared.x['specific_revision_findings'][0]['code'] == 'WORD_BY_WORD_VOLUME_RAMP'
    assert prepared.x['scope']['requires_previous_human_approval'] is True


def test_v2_writer_receives_complete_392_and_gate_but_no_future_script(prepared, requests):
    text.dispatch('performance')
    label, request, validator = requests.calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == text.WRITER_LABEL and request['model'] == 'MiniMax-M3'
    assert payload['rejected_current_performance'] == prepared.x['rejected_current_performance']
    assert payload['specific_revision_findings'] == prepared.x['specific_revision_findings']
    assert payload['reference_fulltext'] == prepared.x['reference_fulltext']
    assert list(payload['current_interaction']['source_catalog']) == ['B1.S04', 'B1.S05', 'B1.S06', 'B1.S07']
    assert 'background_full_script' not in payload and 'previous_current_coverage' not in payload
    for ref, source in text.contract.catalog(prepared.x['background_full_script']).items():
        if source['kind'] == 'dialogue' and ref not in text.REFS:
            assert source['text'] not in request['messages'][1]['content']
    assert request['input_provenance']['prior_rejected_current_performance_in_actual_messages'] is True
    assert request['input_provenance']['old_global_acting_prose_in_actual_messages'] is False
    assert validator(requests.actor)['quality_passed'] is False


def test_v2_review_keeps_full_380_r01_new_performance_and_actual_prompt(prepared, requests):
    text.dispatch('review')
    label, request, _ = requests.calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == text.REVIEW_LABEL and request['model'] == 'deepseek-flash'
    assert payload['background_full_script'] == prepared.x['background_full_script']
    assert payload['reference_fulltext'] == prepared.x['reference_fulltext']
    assert payload['full_model_current_performance'] == requests.actor
    assert payload['compiled_current_interaction'] == requests.compiled
    assert payload['actual_first_prompt'] == text.contract.render_prompt(requests.candidate, prepared.x['background_full_script'])
    assert request['input_provenance']['full_script_in_actual_messages'] is True


def test_v2_native_first_frame_role_and_user_review_request_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(old, 'm', media)
    fake = old.fake_service.__wrapped__(monkeypatch, tmp_path)
    old.test_request_actual_native_first_frame_role_and_wrong_role_blocked(fake)
    old.test_original_id_only_queries_and_success_still_pending_human(fake)


def test_v2_approval_gate_still_refuses_unapproved_predecessor(monkeypatch):
    monkeypatch.setattr(old, 'm', media)
    planning = old.planning.__wrapped__(monkeypatch)
    old.test_media_plan_binds_approved_native_tail_and_exact_predecessor(planning)
    old.test_unapproved_previous_tail_blocks_plan(planning, monkeypatch)
