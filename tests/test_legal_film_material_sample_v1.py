"""Offline native-tail approval and dispatch boundaries for one material segment."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from scripts import run_legal_film_material_sample_v1_20261010 as m
from src.content_factory.media_review_policy import validate_source_bindings


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('offline tests cannot use a network')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def planning(monkeypatch):
    t = m.text_operator
    script = json.loads((t.SOURCE / 'FULL_SCRIPT.json').read_text(encoding='utf-8-sig'))
    actor = {'continuous_performance': '周姐边说明边在当前句末段一次将纸笔送到小林近桌沿并收回手。小林等纸到位看清原因栏后抬问周姐，未碰笔。',
             'zhou_intent': '让小林接下材料', 'xiaolin_intent': '要求说明为什么写成自己的意愿',
             'camera': '同侧观察小林收到材料与理解变化，当前反问完整后才结束。',
             'delivery': '正常普通话交谈，不朗读表演指令。', 'post_pause_seconds': .4}
    compiled = t.contract.compile_contract(actor, script)
    first = t.contract.pack_first(compiled)
    asset = {'path': str(m.PREVIOUS_MEDIA / 'FILM380_OPEN01.provider_last.png'), 'sha256': 'old-tail-sha'}
    scope = {'script_sha256': t.contract.SOURCE_SHA, 'previous_task_id': 'approved-original-id',
             'previous_video_sha256': 'old-video-sha', 'max_new_submissions': 1, 'later_segments_authorized': False}
    review = {'validation': {'needs_revision': False}, 'output': {'full_source_read': True}}
    gate = {'unresolved_mandatory_findings': [], 'text_sample_qualified': True}
    x = {'background_full_script': script, 'scope': scope, 'selected_asset_feedback': asset}
    prior = {'task_id': 'approved-original-id', 'video_sha256': 'old-video-sha',
             'logical_task_id': m.LOGICAL, 'last_frame_source': 'generation_service_original',
             'plan_snapshot': {'script_content_sha256': t.contract.SOURCE_SHA}, 'last_frame_sha256': 'old-tail-sha'}
    folder = m.ROOT / 'DELIVERABLE_material'
    expected = {'FULL_SCRIPT.json': script, 'FULL_MODEL_CURRENT_PERFORMANCE.json': actor,
                'CURRENT_INTERACTION_COMPILED.json': compiled, 'FIRST_SAMPLE.json': first,
                'FULL_SOURCE_REVIEW.json': review['output'], 'INDEPENDENT_PERFORMANCE_GATE.json': gate,
                'ASSET_FEEDBACK.json': asset, 'USER_SCOPE.json': scope}
    files = {str(folder / name): value for name, value in expected.items()}
    files.update({str(m.ROOT / 'INPUT.json'): x, str(m.ROOT / 'CALL_LEDGER.json'): {},
                  str(m.ROOT / 'INDEPENDENT_CURRENT_PERFORMANCE_GATE.json'): gate,
                  str(folder / 'HANDOFF.json'): {'source_sha256': t.contract.SOURCE_SHA,
                      'human_script_adoption_recorded': False, 'combined_B1_text_coverage_complete': True},
                  str(m.PREVIOUS_MEDIA / 'receipt.json'): prior,
                  str(m.PREVIOUS_MEDIA / 'receipt.human_review.json'): {'user_statement': '这一段通过，继续'}})
    monkeypatch.setattr(m, 'read', lambda path: deepcopy(files[str(path)]))
    monkeypatch.setattr(m, 'sha', lambda path: 'old-tail-sha' if str(path) == asset['path'] else 'source-sha')
    monkeypatch.setattr(t, 'runtime', lambda: SimpleNamespace(check=lambda ledger: None, ledger=m.ROOT / 'CALL_LEDGER.json'))
    monkeypatch.setattr(t, 'accepted', lambda label: review if label == t.REVIEW_LABEL else {'output': actor})
    monkeypatch.setattr(t, 'compiled', lambda: deepcopy(compiled))
    monkeypatch.setattr(t, 'candidate', lambda: deepcopy(first))
    approvals = []
    def approved(path, *, expected_tail_path):
        assert path == m.PREVIOUS_MEDIA / 'receipt.human_review.json'
        assert str(expected_tail_path) == asset['path']
        approvals.append((path, expected_tail_path))
        return deepcopy(asset)
    monkeypatch.setattr(m, 'validate_approved_tail', approved)
    return SimpleNamespace(files=files, prior=prior, asset=asset, approvals=approvals)


def test_media_plan_binds_approved_native_tail_and_exact_predecessor(planning):
    plan = m.media_plan(object())
    assert len(planning.approvals) == 1
    assert plan['image_role'] == 'first_frame'
    assert plan['first_frame'] == planning.asset
    assert plan['script_content_sha256'] == m.text_operator.contract.SOURCE_SHA
    assert plan['predecessor_task_id'] == 'approved-original-id'
    assert plan['opening_frame_source'] == 'preceding_human_approved_service_original_tail'
    assert plan['source_refs'] == ['B1.S04', 'B1.S05', 'B1.S06', 'B1.S07']
    assert plan['budget_reset'] is False and plan['later_segments_authorized'] is False
    assert plan['text_qualified_not_current_video_approved'] is True


def test_unapproved_previous_tail_blocks_plan(planning, monkeypatch):
    def blocked(*args, **kwargs):
        raise ValueError('continuation requires an explicit approved user review')
    monkeypatch.setattr(m, 'validate_approved_tail', blocked)
    with pytest.raises(ValueError, match='explicit approved user review'):
        m.media_plan(object())


@pytest.mark.parametrize('field,value', [('task_id', 'another-id'), ('video_sha256', 'another-video'),
    ('logical_task_id', 'another-story'), ('last_frame_source', 'locally_extracted'),
    ('last_frame_sha256', 'another-tail'), ('script_content_sha256', 'another-script')])
def test_approved_predecessor_identity_or_source_change_blocks(planning, field, value):
    previous = planning.files[str(m.PREVIOUS_MEDIA / 'receipt.json')]
    if field == 'script_content_sha256':
        previous['plan_snapshot'][field] = value
    else:
        previous[field] = value
    with pytest.raises(ValueError, match='predecessor identity or source differs'):
        m.media_plan(object())


@pytest.fixture
def fake_service(monkeypatch, tmp_path):
    out = tmp_path / 'material'
    out.mkdir()
    frame = tmp_path / 'approved-provider-tail.png'
    frame.write_bytes(b'offline-tail-reference')
    plan = {'shot_id': 'B1_MATERIAL_EXCHANGE', 'sources': {}, 'duration_seconds': 12,
            'prompt': 'offline current material prompt', 'model': m.MODEL, 'provider': 'ark_api',
            'source_refs': ['B1.S04', 'B1.S05', 'B1.S06', 'B1.S07'], 'image_role': 'first_frame',
            'first_frame': {'path': str(frame), 'sha256': m.sha(frame)}}
    class Client:
        config = SimpleNamespace(model=m.MODEL, provider='ark_api')
        submissions = 0
        create_error = None
        final = {'status': 'running'}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def build_task_payload(self, prompt, **kwargs):
            assert kwargs['task_type'] == 'first_frame'
            assert len(kwargs['references']) == 1 and kwargs['references'][0].role == 'first_frame'
            assert kwargs['references'][0].source.startswith('data:image/png;base64,')
            return {'model': m.MODEL, 'duration': kwargs['duration'], 'content': [
                {'type': 'text', 'text': prompt}, {'type': 'image_url', 'role': kwargs['references'][0].role,
                 'image_url': {'url': kwargs['references'][0].source}}]}
        def create_task(self, request):
            self.submissions += 1
            if self.create_error:
                raise self.create_error
            return {'id': 'offline-original-material-id'}
        def get_task(self, task_id):
            self.queried_ids.append(task_id)
            return deepcopy(self.final)
        def download_video(self, task, path):
            Path(path).write_bytes(b'offline-video')
            return Path(path)
        def download_last_frame(self, task, path):
            Path(path).write_bytes(b'offline-returned-tail')
            return Path(path)
    client = Client()
    client.queried_ids = []
    request = m.request_for(client, plan)
    (out / 'PLAN.json').write_text(json.dumps(plan), encoding='utf-8')
    (out / 'REQUEST.preview.json').write_text(json.dumps(request), encoding='utf-8')
    reservations = []
    monkeypatch.setattr(m, 'OUT', out)
    monkeypatch.setattr(m, 'SeedanceClient', lambda config: client)
    monkeypatch.setattr(m, 'SeedanceConfig', SimpleNamespace(from_env=lambda *args, **kwargs: object()))
    monkeypatch.setattr(m, 'media_plan', lambda unused: deepcopy(plan))
    monkeypatch.setattr(m, 'verify_files', lambda bindings: None)
    monkeypatch.setattr(m, 'reserve_media_attempt', lambda *args: reservations.append(args))
    probe = {'streams': [{'codec_type': 'video', 'width': 496, 'height': 864}, {'codec_type': 'audio'}],
             'format': {'duration': '12.096'}}
    def metadata_only(command, **kwargs):
        assert command[:7] == ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json']
        return json.dumps(probe)
    monkeypatch.setattr(m.subprocess, 'check_output', metadata_only)
    return SimpleNamespace(out=out, plan=plan, request=request, client=client, reservations=reservations)


def test_request_actual_native_first_frame_role_and_wrong_role_blocked(fake_service):
    assert fake_service.request['content'][1]['role'] == 'first_frame'
    altered = deepcopy(fake_service.plan)
    altered['image_role'] = 'reference_image'
    with pytest.raises(ValueError, match='approved native first frame'):
        m.request_for(fake_service.client, altered)


def test_unknown_dispatch_never_resubmits_or_resets_reservation(fake_service):
    f = fake_service
    f.client.create_error = RuntimeError('offline outcome unknown')
    with pytest.raises(RuntimeError, match='outcome unknown'):
        m.media('media_submit')
    receipt = m.read(f.out / 'receipt.json')
    assert receipt['technical_status'] == 'unknown' and receipt['status'] == 'submit_outcome_unknown'
    assert receipt['request'] == f.request and receipt['request_sha256'] == m.digest(f.request)
    with pytest.raises(ValueError, match='never repeat submit'):
        m.media('media_submit')
    with pytest.raises(ValueError, match='no task ID'):
        m.media('media_query')
    assert f.client.submissions == len(f.reservations) == 1


def test_original_id_only_queries_and_success_still_pending_human(fake_service):
    f = fake_service
    m.media('media_submit')
    f.client.final = {'status': 'succeeded', 'content': {'last_frame_url': 'offline-original-tail'}}
    m.media('media_query')
    receipt = m.read(f.out / 'receipt.json')
    assert f.client.queried_ids == ['offline-original-material-id', 'offline-original-material-id']
    assert f.client.submissions == len(f.reservations) == 1
    assert receipt['technical_status'] == 'succeeded' and receipt['content_status'] == 'awaiting_human_review'
    assert receipt['human_decision'] is None and receipt['next_segment_dispatch_allowed'] is False
    assert receipt['assistant_content_inspected'] is False and receipt['tail_status'] == 'saved_unapproved'
    assert receipt['request'] == f.request and receipt['request_sha256'] == m.digest(f.request)
    validate_source_bindings(receipt)
    with pytest.raises(ValueError, match='never repeat submit'):
        m.media('media_submit')
    assert not (f.out / '.execution.lock').exists()
