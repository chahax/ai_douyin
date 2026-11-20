"""Focused offline boundaries for the next approved-tail refusal exchange."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_film_refusal_performance_v1_20261010 as text
from scripts import run_legal_film_refusal_sample_v1_20261010 as media

_spec = importlib.util.spec_from_file_location('_refusal_sample_old_helpers', Path(__file__).with_name('test_legal_film_material_sample_v1.py'))
old = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('refusal sample tests are strictly offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    root = tmp_path / 'round01'
    written = {}
    monkeypatch.setattr(text, 'ROOT', root)
    monkeypatch.setattr(text.control, 'write', lambda path, value, *args: written.update({str(path): deepcopy(value)}))
    monkeypatch.setattr(text.previous_text, 'runtime', lambda: SimpleNamespace(check=lambda ledger: None))
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(prepare=lambda: None))
    monkeypatch.setattr(text, 'summary', lambda: {})
    text.prepare()
    return SimpleNamespace(root=root, written=written, x=written[str(root / 'INPUT.json')],
                           anchor=written[str(root / 'ANCHOR.json')])


@pytest.fixture
def requests(monkeypatch, prepared):
    calls = []
    actor = {'continuous_performance': '小林面对周姐，把当前拒签说清。周姐听完他的话，以当前格式答复试图让他接下手续；小林接收她的解释，纸笔没有移动。',
             'zhou_intent': '让小林将当前材料当作通常手续接受', 'xiaolin_intent': '让周姐面对公司决定与本人意愿的冲突',
             'camera': '同侧观察小林把疑问转为明确拒签，周姐是明确对手，格式答复完整且被接收后结束。',
             'delivery': '自然普通话对话，双方目的面向对方，不朗读演法也不按字摆声。', 'post_pause_seconds': .4}
    compiled = text.contract.compile_contract(actor, prepared.x['background_full_script'], prepared.x['contract_spec'])
    candidate = text.contract.pack_first(compiled)
    prompt = text.contract.render_prompt(candidate, prepared.x['background_full_script'], prepared.x['contract_spec'])
    def dispatch(label, request, validator):
        calls.append((label, deepcopy(request), validator))
        return {'ordinal': 999, 'status': 'contract_rejected'}
    read = text.control.read
    monkeypatch.setattr(text.control, 'read', lambda path: deepcopy(prepared.written[str(path)]) if str(path) in prepared.written else read(path))
    monkeypatch.setattr(text, 'prepare', lambda: None)
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(text, 'compiled', lambda: deepcopy(compiled))
    monkeypatch.setattr(text, 'candidate', lambda: deepcopy(candidate))
    monkeypatch.setattr(text, 'prompt', lambda: prompt)
    monkeypatch.setattr(text, 'accepted', lambda label: {'output': deepcopy(actor)})
    return SimpleNamespace(calls=calls, actor=actor, compiled=compiled, candidate=candidate, prompt=prompt)


def test_prepare_preserves_395_known_and_unknown_usage_and_formal_approval(prepared):
    inherited = prepared.anchor['inherited']
    assert inherited['calls_started'] == 395 and inherited['reported_tokens'] == 6456309
    assert inherited['unknown_token_reservations'] == 93117 and inherited['pending_ordinals'] == [70, 160]
    assert prepared.anchor['budget_reset'] is False and prepared.anchor['automatic_retry'] is False
    assert prepared.anchor['mutable_predecessor_receipt_not_hashed'] is True
    assert prepared.x['selected_asset_feedback']['human_approval_recorded'] is True
    assert prepared.x['scope']['max_new_submissions'] == 1
    assert prepared.x['scope']['later_segments_authorized'] is False
    assert prepared.x['scope']['user_statement'] == '第二段通过，使用原尾帧继续'
    assert prepared.x['contract_spec']['source_refs'] == ['B2.S01', 'B2.S02']
    assert prepared.written[str(prepared.root / 'PREDECESSOR_APPROVED_SNAPSHOT.json')]['content_status'] == 'approved'
    assert str(text.PREVIOUS_MEDIA / 'receipt.json') not in prepared.anchor['parent_files']


def test_writer_current_only_r01_and_no_old_acting_or_future_lines(prepared, requests):
    text.dispatch('performance')
    assert len(requests.calls) == 1
    label, request, validator = requests.calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == text.WRITER_LABEL and request['model'] == 'MiniMax-M3'
    assert payload['reference_fulltext'] == prepared.x['reference_fulltext']
    assert list(payload['current_interaction']['source_catalog']) == ['B2.S01', 'B2.S02']
    assert 'background_full_script' not in payload and 'previous_current_coverage' not in payload
    assert 'rejected_current_performance' not in payload and 'full_model_current_performance' not in payload
    assert payload['current_initial_state']['paper'] == payload['current_initial_state']['pen'] == 'xiaolin_near_edge'
    for ref, source in text.contract.catalog(prepared.x['background_full_script']).items():
        if source['kind'] == 'dialogue' and ref not in text.REFS:
            assert source['text'] not in request['messages'][1]['content']
    assert request['input_provenance']['old_global_acting_prose_in_actual_messages'] is False
    assert validator(requests.actor)['quality_passed'] is False


def test_review_retains_full_380_r01_exact_new_model_and_actual_prompt(prepared, requests):
    text.dispatch('review')
    label, request, _ = requests.calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == text.REVIEW_LABEL and request['model'] == 'deepseek-flash'
    assert payload['background_full_script'] == prepared.x['background_full_script']
    assert payload['reference_fulltext'] == prepared.x['reference_fulltext']
    assert payload['full_model_current_performance'] == requests.actor
    assert payload['compiled_current_interaction'] == requests.compiled
    assert payload['actual_first_prompt'] == requests.prompt
    assert request['input_provenance']['full_script_in_actual_messages'] is True
    for ref, source in text.contract.catalog(prepared.x['background_full_script']).items():
        if source['kind'] == 'dialogue':
            assert requests.prompt.count(source['text']) == int(ref in text.REFS)


def test_native_first_frame_role_unknown_no_implicit_resubmit(monkeypatch, tmp_path):
    monkeypatch.setattr(old, 'm', media)
    fake = old.fake_service.__wrapped__(monkeypatch, tmp_path)
    old.test_request_actual_native_first_frame_role_and_wrong_role_blocked(fake)
    old.test_unknown_dispatch_never_resubmits_or_resets_reservation(fake)


def test_original_id_query_request_binding_saved_still_awaiting(monkeypatch, tmp_path):
    monkeypatch.setattr(old, 'm', media)
    fake = old.fake_service.__wrapped__(monkeypatch, tmp_path)
    old.test_original_id_only_queries_and_success_still_pending_human(fake)

@pytest.fixture
def planning(monkeypatch, prepared, requests):
    folder = media.ROOT / 'DELIVERABLE_refusal'
    x = prepared.x
    gate = {'unresolved_mandatory_findings': [], 'text_sample_qualified': True}
    review = {'validation': {'needs_revision': False}, 'output': {'full_source_read': True}}
    expected = {'FULL_SCRIPT.json': x['background_full_script'], 'CONTRACT_SPEC.json': x['contract_spec'],
        'FULL_MODEL_CURRENT_PERFORMANCE.json': requests.actor, 'CURRENT_INTERACTION_COMPILED.json': requests.compiled,
        'FIRST_SAMPLE.json': requests.candidate, 'FULL_SOURCE_REVIEW.json': review['output'],
        'INDEPENDENT_PERFORMANCE_GATE.json': gate, 'ASSET_FEEDBACK.json': x['selected_asset_feedback'], 'USER_SCOPE.json': x['scope']}
    files = {str(folder / name): value for name, value in expected.items()}
    files.update({str(media.ROOT / 'INPUT.json'): x, str(media.ROOT / 'CALL_LEDGER.json'): {},
        str(media.ROOT / 'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json'): gate,
        str(folder / 'HANDOFF.json'): {'source_sha256': x['scope']['script_sha256'],
            'compiled_sha256': media.digest(requests.compiled), 'human_script_adoption_recorded': False},
        str(media.ROOT / 'PREDECESSOR_APPROVED_SNAPSHOT.json'): prepared.written[str(prepared.root / 'PREDECESSOR_APPROVED_SNAPSHOT.json')]})
    read = media.read
    monkeypatch.setattr(media, 'read', lambda path: deepcopy(files[str(path)]) if str(path) in files else read(path))
    sha = media.sha
    monkeypatch.setattr(media, 'sha', lambda path: 'offline-source-sha' if str(path) in files else sha(path))
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(ledger=media.ROOT / 'CALL_LEDGER.json', check=lambda value: None))
    monkeypatch.setattr(text, 'accepted', lambda label: review if label == text.REVIEW_LABEL else {'output': requests.actor})
    return files


def test_formal_approved_tail_and_snapshot_bound_without_mutable_receipt(planning):
    plan = media.media_plan(object())
    assert plan['image_role'] == 'first_frame'
    assert plan['first_frame']['sha256'] == '8350e02f341876272865cec4e34d87b46ef2f93a3656e6afe8bd2ba10ea7c611'
    assert plan['source_refs'] == ['B2.S01', 'B2.S02']
    paths = {Path(row['path']).resolve() for row in plan['sources'].values()}
    assert (media.PREVIOUS_MEDIA / 'receipt.json').resolve() not in paths
    assert (media.ROOT / 'PREDECESSOR_APPROVED_SNAPSHOT.json').resolve() in paths
    assert (media.PREVIOUS_MEDIA / 'receipt.human_review.json').resolve() in paths
    assert plan['authorization']['max_new_submissions'] == 1
    assert plan['later_segments_authorized'] is False and plan['budget_reset'] is False


def test_pending_snapshot_does_not_stand_in_for_approval(planning):
    planning[str(media.ROOT / 'PREDECESSOR_APPROVED_SNAPSHOT.json')]['content_status'] = 'awaiting_human_review'
    with pytest.raises(ValueError, match='approved predecessor identity or source differs'):
        media.media_plan(object())


def test_default_human_approval_gate_refuses_missing_approval(planning, monkeypatch):
    def denied(*args, **kwargs):
        raise ValueError('continuation requires an explicit approved user review')
    monkeypatch.setattr(media, 'validate_approved_tail', denied)
    with pytest.raises(ValueError, match='explicit approved user review'):
        media.media_plan(object())
