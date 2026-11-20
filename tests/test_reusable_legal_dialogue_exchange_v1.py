"""Four focused offline checks of the reusable current-dialogue entry point."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_dialogue_exchange as m
from scripts import run_legal_dialogue_exchange_media as strict
from src.content_factory import media_review_policy

SETUP = m.PROJECT / 'data/production_revisions/legal_film_format_pressure_20261010/round_01/SETUP.json'
_spec = importlib.util.spec_from_file_location('_reusable_exchange_fake_media', Path(__file__).with_name('test_legal_film_material_sample_v1.py'))
old_media = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(old_media)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('reusable dialogue checks must remain offline')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def prepared(monkeypatch):
    op = strict.MediaExchange(SETUP.parent)
    op.root = m.PROJECT / 'data/qa/reusable_dialogue_exchange_20261010/virtual_round'
    original_read = m.control.read
    prior = deepcopy(original_read(op.previous / 'receipt.json'))
    prior['content_status'] = 'awaiting_human_review'
    files = {str(op.previous / 'receipt.json'): prior, str(op.root / 'SETUP.json'): deepcopy(op.settings)}
    def read(path):
        return deepcopy(files[str(path)]) if str(path) in files else original_read(path)
    monkeypatch.setattr(m.control, 'read', read)
    monkeypatch.setattr(m.control, 'write', lambda path, value, *args: files.update({str(path): deepcopy(value)}))
    monkeypatch.setattr(op, 'runtime', lambda: SimpleNamespace(prepare=lambda: None))
    monkeypatch.setattr(op, 'summary', lambda: {})
    op.prepare()
    return SimpleNamespace(op=op, files=files, prior=prior,
        x=files[str(op.root / 'INPUT.json')], anchor=files[str(op.root / 'ANCHOR.json')])


@pytest.fixture
def performance(prepared, monkeypatch):
    op = prepared.op
    actor = {'continuous_performance': '小林接着周姐刚才的解释，把格式与本人意愿分开，要求她正面回应。周姐听完后改用办理困难施压，小林听见后意识到她还在推动他签字，纸笔保持原位。',
        'zhou_intent': '借办理困难让小林接受公司的办理办法', 'xiaolin_intent': '让周姐面对他没有提出辞职的事实',
        'camera': '同侧观察两人的交锋，保留周姐改变说服办法及小林收到压力的反应。',
        'delivery': '自然普通话交谈，用对对方的态度变化表达压力，不按字加重。', 'post_pause_seconds': .5}
    compiled = m.contract.compile_contract(actor, prepared.x['background_full_script'], prepared.x['contract_spec'])
    first = m.contract.pack_first(compiled)
    prompt = m.contract.render_prompt(first, prepared.x['background_full_script'], prepared.x['contract_spec'])
    monkeypatch.setattr(op, 'compiled', lambda: deepcopy(compiled))
    monkeypatch.setattr(op, 'candidate', lambda: deepcopy(first))
    monkeypatch.setattr(op, 'prompt', lambda: prompt)
    monkeypatch.setattr(op, 'accepted', lambda label: {'output': deepcopy(actor)})
    return SimpleNamespace(actor=actor, compiled=compiled, first=first, prompt=prompt)


def test_prepare_preserves401_spend_and_allows_pending_for_text_only(prepared):
    a = prepared.anchor
    assert a['inherited']['calls_started'] == 401 and a['inherited']['reported_tokens'] == 6501453
    assert a['inherited']['unknown_token_reservations'] == 93117 and a['inherited']['pending_ordinals'] == [70, 160]
    assert a['budget_reset'] is False and a['automatic_retry'] is False
    assert a['predecessor_mutable_receipt_not_hashed'] is True
    assert str(prepared.op.previous / 'receipt.json') not in a['parent_files']
    assert prepared.files[str(prepared.op.root / 'PREDECESSOR_CANDIDATE_SNAPSHOT.json')]['content_status'] == 'awaiting_human_review'
    assert prepared.x['selected_asset_feedback']['human_approval_required_at_media_dispatch'] is True
    assert prepared.x['current_interaction']['source_refs'] == ['B2.S03', 'B2.S04']
    assert prepared.x['scope']['max_new_submissions'] == 1 and prepared.x['scope']['later_segments_authorized'] is False


def test_actual_writer_current_only_and_review_full_source_raw_compiled_prompt(prepared, performance, monkeypatch):
    op = prepared.op
    calls = []
    def dispatch(label, req, validator):
        calls.append((label, deepcopy(req), validator))
        return {'ordinal': 999, 'status': 'contract_rejected'}
    monkeypatch.setattr(op, 'prepare', lambda: None)
    monkeypatch.setattr(op, 'runtime', lambda: SimpleNamespace(dispatch=dispatch))
    op.dispatch('performance')
    label, req, validator = calls[0]
    body = json.loads(req['messages'][1]['content'])
    assert label == 'current_performance' and req['model'] == 'MiniMax-M3'
    assert list(body['current_interaction']['source_catalog']) == ['B2.S03', 'B2.S04']
    assert body['reference_fulltext'] == prepared.x['reference_fulltext']
    assert body['film_method_current_brief'] == prepared.x['film_method_current_brief']
    assert 'background_full_script' not in body and 'previous_current_coverage' not in body
    for ref, item in m.contract.catalog(prepared.x['background_full_script']).items():
        if item['kind'] == 'dialogue' and ref not in op.refs:
            assert item['text'] not in req['messages'][1]['content']
    assert validator(performance.actor)['quality_passed'] is False
    op.dispatch('review')
    label, req, _ = calls[1]
    body = json.loads(req['messages'][1]['content'])
    assert label == 'full_source_review' and req['model'] == 'deepseek-flash'
    assert body['background_full_script'] == prepared.x['background_full_script']
    assert body['reference_fulltext'] == prepared.x['reference_fulltext']
    assert body['full_model_current_performance'] == performance.actor
    assert body['compiled_current_interaction'] == performance.compiled
    assert body['actual_first_sample'] == performance.first and body['actual_first_prompt'] == performance.prompt
    assert len(calls) == 2


@pytest.fixture
def planning(prepared, performance, monkeypatch):
    op = prepared.op
    x = prepared.x
    folder = op.root / 'DELIVERABLE'
    gate = {'text_sample_qualified': True, 'unresolved_mandatory_findings': [],
        'source_sha256': m.contract.digest(x['background_full_script']), 'compiled_sha256': m.contract.digest(performance.compiled)}
    review = {'output': {'full_source_read': True}, 'validation': {'needs_revision': False}}
    expected = {'FULL_SCRIPT.json': x['background_full_script'], 'FULL_MODEL_CURRENT_PERFORMANCE.json': performance.actor,
        'CONTRACT_SPEC.json': x['contract_spec'], 'CURRENT_INTERACTION_COMPILED.json': performance.compiled,
        'FIRST_SAMPLE.json': performance.first, 'FULL_SOURCE_REVIEW.json': review['output'],
        'INDEPENDENT_PERFORMANCE_GATE.json': gate, 'ASSET_FEEDBACK.json': x['selected_asset_feedback'], 'USER_SCOPE.json': x['scope']}
    prepared.files.update({str(folder / name): deepcopy(value) for name, value in expected.items()})
    prepared.files.update({str(op.root / 'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json'): deepcopy(gate),
        str(op.root / 'CALL_LEDGER.json'): {}, str(folder / 'HANDOFF.json'): {'compiled_sha256':m.contract.digest(performance.compiled),
        'source_sha256':m.contract.digest(x['background_full_script']), 'source_refs':op.refs},
        str(op.previous / 'receipt.human_review.json'): {'user_statement':'第三段通过，继续下一段'}})
    prepared.files[str(op.previous / 'receipt.json')]['content_status'] = 'approved'
    monkeypatch.setattr(op, 'runtime', lambda: SimpleNamespace(ledger=op.root/'CALL_LEDGER.json', check=lambda value:None))
    monkeypatch.setattr(op, 'accepted', lambda label:deepcopy(review) if label=='full_source_review' else {'output':deepcopy(performance.actor)})
    original_sha = m.sha
    monkeypatch.setattr(m, 'sha', lambda path:'offline-current-source-sha' if str(path) in prepared.files else original_sha(path))
    approvals=[]
    def approved(path, *, expected_tail_path):
        assert path == op.previous/'receipt.human_review.json'
        assert str(expected_tail_path)==x['selected_asset_feedback']['path']
        approvals.append(path)
        return {'path':x['selected_asset_feedback']['path'], 'sha256':x['selected_asset_feedback']['sha256']}
    monkeypatch.setattr(m, 'validate_approved_tail', approved)
    return SimpleNamespace(op=op, files=prepared.files, gate=gate, approvals=approvals)


def test_media_formal_approval_exact_identity_and_independent_gate(planning, monkeypatch):
    op = planning.op
    plan = op.media_plan(object())
    assert len(planning.approvals)==1 and plan['image_role']=='first_frame'
    assert plan['independent_current_gate_verified'] is True
    assert str(Path(strict.__file__).resolve().relative_to(m.PROJECT)) in plan['sources']
    paths={Path(row['path']).resolve() for row in plan['sources'].values()}
    assert (op.previous/'receipt.json').resolve() not in paths
    assert (op.root/'PREDECESSOR_CANDIDATE_SNAPSHOT.json').resolve() in paths
    assert plan['budget_reset'] is False and plan['later_segments_authorized'] is False
    prior=planning.files[str(op.previous/'receipt.json')]
    prior['content_status']='awaiting_human_review'
    with pytest.raises(ValueError,match='predecessor not approved'):op.media_plan(object())
    prior['content_status']='approved'
    with monkeypatch.context() as isolated:
        isolated.setattr(m,'validate_approved_tail',lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('missing formal approval')))
        with pytest.raises(ValueError,match='missing formal approval'):op.media_plan(object())
    for field in ['task_id','video_sha256','last_frame_sha256','last_frame_source','logical_task_id']:
        old=prior[field];prior[field]='altered-predecessor'
        with pytest.raises(ValueError,match='predecessor source changed'):op.media_plan(object())
        prior[field]=old
    old=prior['plan_snapshot']['script_content_sha256'];prior['plan_snapshot']['script_content_sha256']='altered-script'
    with pytest.raises(ValueError,match='predecessor source changed'):op.media_plan(object())
    prior['plan_snapshot']['script_content_sha256']=old
    for field,value in [('text_sample_qualified',False),('unresolved_mandatory_findings',['unresolved']),
                        ('source_sha256','wrong-source'),('compiled_sha256','wrong-compiled')]:
        gate=deepcopy(planning.gate);gate[field]=value
        planning.files[str(op.root/'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json')]=gate
        planning.files[str(op.root/'DELIVERABLE/INDEPENDENT_PERFORMANCE_GATE.json')]=deepcopy(gate)
        with pytest.raises(ValueError,match='independent.*gate|text.*unresolved'):op.media_plan(object())


def test_media_executes_old_v5_once_unknown_original_id_and_awaiting(prepared, monkeypatch, tmp_path):
    assert m.media_base.validate_approved_tail is media_review_policy.validate_approved_tail
    op=prepared.op
    for name,check in [('unknown',old_media.test_unknown_dispatch_never_resubmits_or_resets_reservation),
                      ('saved',old_media.test_original_id_only_queries_and_success_still_pending_human)]:
        directory=tmp_path/name;directory.mkdir()
        with monkeypatch.context() as isolated:
            isolated.setattr(old_media,'m',m.media_base)
            fake=old_media.fake_service.__wrapped__(isolated,directory)
            isolated.setattr(op,'out',fake.out)
            isolated.setattr(op,'media_plan',lambda client:deepcopy(fake.plan))
            old_media.test_request_actual_native_first_frame_role_and_wrong_role_blocked(fake)
            # Exercise Exchange.media itself; it must delegate to the unchanged v5 submission/query function.
            real_media=m.media_base.media
            isolated.setattr(m.media_base,'media',lambda operation:real_media(operation))
            original_old_media=m.media_base
            proxy=SimpleNamespace(media=op.media,read=m.media_base.read,digest=m.media_base.digest,MODEL=m.MODEL)
            isolated.setattr(old_media,'m',proxy)
            check(fake)
