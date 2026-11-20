"""Offline boundaries for film-method v3 opening; no real service dispatch."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import pytest
from jsonschema import ValidationError
from scripts import run_legal_film_performance_v3_20261010 as text
from scripts import run_legal_film_sample_v3_20261010 as media


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('offline tests cannot access a network')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


@pytest.fixture
def current():
    x = json.loads((text.ROOT / 'INPUT.json').read_text(encoding='utf-8-sig'))
    actor = {
        'continuous_performance': '周姐展开文件夹时向小林说明决定，等待他接下通知。小林听清后转向周姐，以当前反问要求解释，她接收这一问。',
        'zhou_intent': '让小林接下公司通知', 'xiaolin_intent': '要求周姐解释为何让自己离开',
        'camera': '同侧中近景观察小林接收通知与反问，周姐始终是明确受问者，反问完整结束后才切出。',
        'delivery': '正常普通话交谈，周姐向对方说明，小林当面反问，不朗读。',
        'post_pause_seconds': .4,
    }
    compiled = text.contract.compile_contract(actor, x['background_full_script'])
    return SimpleNamespace(x=x, actor=actor, compiled=compiled, first=text.contract.pack_first(compiled))


@pytest.fixture
def capture_text(monkeypatch, current):
    calls, writes = [], {}
    def dispatch(label, request, validator):
        calls.append((label, deepcopy(request), validator))
        return {'ordinal': 999, 'status': 'contract_rejected'}
    monkeypatch.setattr(text, 'prepare', lambda: None)
    monkeypatch.setattr(text, 'runtime', lambda: SimpleNamespace(dispatch=dispatch))
    monkeypatch.setattr(text, 'summary', lambda: {'unknown_token_reservations': 93117})
    monkeypatch.setattr(text, 'compiled', lambda: deepcopy(current.compiled))
    monkeypatch.setattr(text, 'candidate', lambda: deepcopy(current.first))
    monkeypatch.setattr(text, 'accepted', lambda label: {'output': deepcopy(current.actor)})
    monkeypatch.setattr(text.control, 'write', lambda path, value, *args: writes.update({str(path): deepcopy(value)}))
    return calls, writes


def test_writer_current_only_actual_reference_and_current_film_method(current, capture_text):
    calls, writes = capture_text
    text.dispatch('performance')
    assert len(calls) == 1
    label, request, validator = calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == 'natural_opening_exchange_r1'
    assert request['model'] == 'MiniMax-M3'
    assert request['parameters']['thinking'] == 'disabled'
    assert payload['reference_fulltext'] == current.x['reference_fulltext']
    assert payload['film_method_current_brief'] == current.x['film_method_current_brief']
    assert list(payload['current_interaction']['source_catalog']) == ['B1.S01', 'B1.S02', 'B1.S03']
    assert payload['current_initial_state']['paper_pen'] == '未签，留周姐侧'
    assert 'background_full_script' not in payload and 'current_brief' not in payload
    assert 'previous_sample_identity' not in payload and 'full_model_current_performance' not in payload
    assert 'previous_complete_B1_performance' not in payload
    assert payload['rejected_current_performance'] == current.x['rejected_current_performance']
    assert '旧演法' not in json.dumps(payload['rejected_current_performance'], ensure_ascii=False)
    for ref, source in text.contract.catalog(current.x['background_full_script']).items():
        if source['kind'] == 'dialogue' and ref not in text.REFS:
            assert source['text'] not in request['messages'][1]['content']
    assert request['input_provenance']['current_actor_request_excludes_future_story'] is True
    assert validator(current.actor)['quality_passed'] is False
    assert str(text.ROOT / 'request_previews/performance.json') in writes


def test_full_source_review_sees_exact_source_and_current_output(current, capture_text):
    calls, writes = capture_text
    text.dispatch('review')
    label, request, _ = calls[0]
    payload = json.loads(request['messages'][1]['content'])
    assert label == 'natural_opening_full_source_review_r1'
    assert request['model'] == 'deepseek-flash'
    assert payload['background_full_script'] == current.x['background_full_script']
    assert payload['reference_fulltext'] == current.x['reference_fulltext']
    assert payload['full_model_current_performance'] == current.actor
    assert payload['compiled_current_interaction'] == current.compiled
    assert payload['actual_first_prompt'] == text.contract.render_prompt(current.first, current.x['background_full_script'])
    assert request['input_provenance']['full_script_in_actual_messages'] is True
    assert str(text.ROOT / 'request_previews/review.json') in writes


def test_six_fields_compile_preserves_dialogue_and_normal_timing(current):
    script = current.x['background_full_script']
    before = deepcopy((script, current.actor))
    compiled = text.contract.compile_contract(current.actor, script)
    assert (script, current.actor) == before
    assert compiled['all_native_values_preserved'] is True and compiled['fit_scaled'] is False
    assert compiled['timing_assumption']['normal_spoken_characters_per_second'] == 3.3
    assert compiled['timing_assumption']['measured_audio'] is False
    assert compiled['schedule'][0]['start'] == compiled['schedule'][1]['start'] == 0
    assert compiled['schedule'][2]['start'] >= compiled['schedule'][1]['end']
    prompt = text.contract.render_prompt(current.first, script)
    for ref, source in text.contract.catalog(script).items():
        if source['kind'] == 'dialogue':
            assert prompt.count(source['text']) == int(ref in text.REFS)
    blocked = text.contract.pack_first(compiled, max_seconds=4)
    assert blocked['dispatch_ready'] is False and blocked['fit_scaled'] is False
    assert blocked['duration_seconds'] is None


def test_writer_rejects_object_field_and_copied_or_future_dialogue(current, capture_text):
    calls, _ = capture_text
    text.dispatch('performance')
    validator = calls[0][2]
    wrong = deepcopy(current.actor)
    wrong['camera'] = {'item': '错误类型'}
    with pytest.raises(ValidationError):
        validator(wrong)
    for ref in ['B1.S02', 'B1.S04']:
        wrong = deepcopy(current.actor)
        wrong['continuous_performance'] = text.contract.catalog(current.x['background_full_script'])[ref]['text']
        with pytest.raises(ValueError, match='dialogue copied'):
            validator(wrong)


def test_actual_anchor_preserves_unknowns_spend_and_single_sample_scope(current):
    anchor = json.loads((text.ROOT / 'ANCHOR.json').read_text(encoding='utf-8-sig'))
    assert anchor['inherited']['calls_started'] == 389
    assert anchor['inherited']['reported_tokens'] == 6416388
    assert anchor['inherited']['unknown_token_reservations'] == 93117
    assert anchor['inherited']['pending_ordinals'] == [70, 160]
    assert anchor['budget_reset'] is False and anchor['automatic_retry'] is False
    assert all(Path(p).is_relative_to(text.PROJECT) for p in anchor['parent_files'])
    assert any(p.endswith('DIRECTOR_SKILL_SOURCE_SNAPSHOT.md') for p in anchor['parent_files'])
    assert current.x['scope']['max_new_submissions'] == 1
    assert current.x['scope']['later_segments_authorized'] is False
    assert current.x['scope']['unapproved_prior_tail_used'] is False


@pytest.fixture
def fake_media(monkeypatch, tmp_path):
    out = tmp_path / 'media'
    out.mkdir()
    reference = tmp_path / 'approved-reference.png'
    reference.write_bytes(b'offline-approved-reference')
    plan = {'shot_id': 'B1_NATURAL_EXCHANGE', 'sources': {}, 'duration_seconds': 8,
            'source_refs': ['B1.S01', 'B1.S02', 'B1.S03'],
            'reference_image': {'path': str(reference), 'sha256': media.sha(reference)}}
    request = {'model': media.MODEL, 'duration': 8, 'content': [{'type': 'text', 'text': 'offline prompt'}]}
    (out / 'PLAN.json').write_text(json.dumps(plan), encoding='utf-8')
    (out / 'REQUEST.preview.json').write_text(json.dumps(request), encoding='utf-8')
    class Client:
        config = SimpleNamespace(model=media.MODEL)
        submissions = 0
        queried_ids = None
        create_error = None
        final = {'status': 'running'}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def create_task(self, value):
            assert value == request
            self.submissions += 1
            if self.create_error:
                raise self.create_error
            return {'id': 'offline-original-id'}
        def get_task(self, task_id):
            self.queried_ids.append(task_id)
            return deepcopy(self.final)
        def download_video(self, task, path):
            Path(path).write_bytes(b'offline-video-bytes')
            return Path(path)
        def download_last_frame(self, task, path):
            Path(path).write_bytes(b'offline-service-tail')
            return Path(path)
    client = Client()
    client.queried_ids = []
    reservations = []
    monkeypatch.setattr(media, 'OUT', out)
    monkeypatch.setattr(media, 'SeedanceClient', lambda config: client)
    monkeypatch.setattr(media, 'SeedanceConfig', SimpleNamespace(from_env=lambda *args, **kwargs: object()))
    monkeypatch.setattr(media, 'media_plan', lambda c: deepcopy(plan))
    monkeypatch.setattr(media, 'request_for', lambda c, p: deepcopy(request))
    monkeypatch.setattr(media, 'verify_files', lambda bindings: None)
    monkeypatch.setattr(media, 'reserve_media_attempt', lambda *args: reservations.append(args))
    probe = {'streams': [{'codec_type': 'video', 'width': 496, 'height': 864}, {'codec_type': 'audio'}],
             'format': {'duration': '8.096'}}
    def metadata_only(command, **kwargs):
        assert command[:7] == ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json']
        return json.dumps(probe)
    monkeypatch.setattr(media.subprocess, 'check_output', metadata_only)
    return SimpleNamespace(out=out, plan=plan, request=request, client=client, reservations=reservations)


def test_unknown_submission_is_reserved_once_and_never_dispatched_twice(fake_media):
    f = fake_media
    f.client.create_error = RuntimeError('offline unknown transport result')
    with pytest.raises(RuntimeError, match='unknown transport'):
        media.media('media_submit')
    receipt = media.read(f.out / 'receipt.json')
    assert receipt['technical_status'] == 'unknown' and receipt['status'] == 'submit_outcome_unknown'
    assert f.client.submissions == len(f.reservations) == 1
    with pytest.raises(ValueError, match='never repeat submit'):
        media.media('media_submit')
    with pytest.raises(ValueError, match='no task ID'):
        media.media('media_query')
    assert f.client.submissions == len(f.reservations) == 1
    assert not (f.out / '.execution.lock').exists()


def test_queries_reconcile_only_the_original_id(fake_media):
    f = fake_media
    media.media('media_submit')
    media.media('media_query')
    assert f.client.queried_ids == ['offline-original-id', 'offline-original-id']
    assert f.client.submissions == len(f.reservations) == 1
    with pytest.raises(ValueError, match='never repeat submit'):
        media.media('media_submit')
    assert f.client.submissions == 1


def test_saved_sample_and_original_tail_remain_unapproved(fake_media):
    f = fake_media
    f.client.final = {'status': 'succeeded', 'content': {'last_frame_url': 'offline-tail'}}
    result = media.media('media_submit')
    receipt = media.read(f.out / 'receipt.json')
    assert result['technical_status'] == 'succeeded'
    assert receipt['content_status'] == 'awaiting_human_review'
    assert receipt['human_decision'] is None and receipt['next_segment_dispatch_allowed'] is False
    assert receipt['assistant_content_inspected'] is False
    assert receipt['last_frame_source'] == 'generation_service_original'
    assert receipt['tail_status'] == 'saved_unapproved' and receipt['video_bytes'] > 0
    assert receipt['video_sha256'] == media.sha(receipt['video_path'])
    assert receipt['last_frame_sha256'] == media.sha(receipt['last_frame'])
    assert f.client.submissions == len(f.reservations) == 1


def test_saved_receipt_can_be_bound_to_future_explicit_user_review(fake_media):
    from src.content_factory.media_review_policy import validate_source_bindings
    fake_media.client.final = {'status': 'succeeded', 'content': {}}
    media.media('media_submit')
    receipt = media.read(fake_media.out / 'receipt.json')
    assert receipt['request'] == fake_media.request
    assert receipt['request_sha256'] == media.digest(fake_media.request)
    validate_source_bindings(receipt)
