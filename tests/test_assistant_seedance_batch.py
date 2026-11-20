"""Focused batch recovery, stop and source-admission guards; no model calls."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.content_factory import assistant_seedance_batch as batch
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceClient


class FakeClient:
    config = SimpleNamespace(provider='ark_api', model=ARK_MINI_MODEL, base_url=ARK_BASE_URL)
    build_task_payload = SeedanceClient.build_task_payload

    def __init__(self, mode='succeeded'):
        self.mode, self.posts, self.gets = mode, 0, []
        self.original = batch.file_row(batch.S01_OUT / 'S02/receipt.json', 'S02')

    def create_task(self, request):
        self.posts += 1
        if self.mode == 'unknown':
            raise TimeoutError('offline unknown create outcome')
        return {'id': 'offline_batch_S03'}

    def get_task(self, task_id):
        self.gets.append(task_id)
        status = 'succeeded' if task_id == batch.INITIAL_TASK else self.mode
        return dict(id=task_id, model=ARK_MINI_MODEL, status=status,
                    content=dict(last_frame_url='https://offline.invalid/native', video_url='https://offline.invalid/video'))

    def download_last_frame(self, task, path):
        path = Path(path)
        path.write_bytes(Path(self.original['last_frame']).read_bytes())
        return path

    def download_video(self, task, path):
        path = Path(path)
        path.write_bytes(Path(self.original['video_path']).read_bytes())
        return path


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    plan = copy.deepcopy(batch.read(batch.OUT / 'BATCH_PLAN.json'))
    out = tmp_path / 'batch'
    out.mkdir()
    authorization = out / 'BATCH_AUTHORIZATION.json'
    authorization.write_bytes(Path(plan['authorization']['path']).read_bytes())
    plan['authorization'].update(path=str(authorization), sha256=batch.sha(authorization))
    for segment in plan['segments']:
        directory = out / 'segments' / segment['segment_id']
        directory.mkdir(parents=True)
        for key in ('source', 'prompt'):
            path = directory / Path(segment[key]['path']).name
            path.write_bytes(Path(segment[key]['path']).read_bytes())
            segment[key].update(path=str(path), sha256=batch.sha(path))
    ledger = tmp_path / 'legacy.json'
    ledger.write_bytes(batch.STORY_LEDGER.read_bytes())
    monkeypatch.setattr(batch, 'STORY_LEDGER', ledger)
    plan['history']['legacy_ledger'].update(path=str(ledger), sha256=batch.sha(ledger))
    batch.durable(out / 'BATCH_PLAN.json', plan)
    client = FakeClient()
    batch.execute('prepare', client, out)
    assert client.posts == 0 and client.gets == []
    return out, plan


def test_unknown_claim_has_no_id_and_never_reposts(prepared):
    out, _ = prepared
    client = FakeClient('unknown')
    with pytest.raises(ValueError, match='submit_outcome_unknown'):
        batch.execute('start', client, out, poll_seconds=0)
    with pytest.raises(ValueError, match='no known original task ID'):
        batch.execute('start', client, out, poll_seconds=0)
    assert client.posts == 1
    assert not (out / 'segments/S04/SUBMISSION_CLAIM.json').exists()


def test_pending_original_id_recovery_success_skip_and_stop(prepared):
    out, plan = prepared
    client = FakeClient()
    predecessor = client.original
    record = batch.submit_one(out, plan, plan['segments'][0], predecessor, client)
    directory = out / 'segments/S03'
    # Simulate losing the batch index after the original create response was durable.
    (out / 'job_ids.json').unlink()
    recovered = batch.recover_record(out, directory)
    assert recovered['task_id'] == record['task_id'] == 'offline_batch_S03'
    assert batch.read(out / 'job_ids.json')['jobs']['S03']['task_id'] == record['task_id']
    batch.query_until_saved(out, directory, recovered, client, wait_timeout=1, poll_seconds=0)
    before = list(client.gets)
    batch.durable(out / 'STOP_REQUESTED.json', {'user_statement': 'stop'})
    with pytest.raises(ValueError, match='user stop requested'):
        batch.execute('start', client, out, poll_seconds=0)
    assert client.posts == 1 and client.gets == before
    assert not (out / 'segments/S04/SUBMISSION_CLAIM.json').exists()
    assert batch.read(directory / 'receipt.json')['content_status'] == 'awaiting_human_review'


def test_native_tail_change_and_scope_change_are_rejected(prepared, tmp_path):
    out, plan = prepared
    client = FakeClient()
    altered = tmp_path / 'altered_tail.original'
    altered.write_bytes(Path(client.original['last_frame']).read_bytes()[:-2])
    with pytest.raises(ValueError, match='input bytes do not match'):
        batch.request_for(client, plan['segments'][0], client.original, altered)
    auth = batch.read(out / 'BATCH_AUTHORIZATION.json')
    auth['max_new_video_submissions'] = 11
    batch.durable(out / 'BATCH_AUTHORIZATION.json', auth)
    plan['authorization']['sha256'] = batch.sha(out / 'BATCH_AUTHORIZATION.json')
    batch.durable(out / 'BATCH_PLAN.json', plan)
    with pytest.raises(ValueError, match='authorization scope differs'):
        batch.validate_plan(out)
    assert client.posts == 0


def test_service_failure_stops_batch_without_new_candidate(prepared):
    out, _ = prepared
    client = FakeClient('failed')
    with pytest.raises(ValueError, match='service task failed'):
        batch.execute('start', client, out, poll_seconds=0)
    assert client.posts == 1
    assert batch.read(out / 'job_ids.json')['jobs']['S03']['task_id'] == 'offline_batch_S03'
    assert not (out / 'segments/S04/SUBMISSION_CLAIM.json').exists()
    assert sum(int(e['failure']) for e in batch.read(out / 'MEDIA_EVENTS.json')['events']) == 1


def test_missing_or_null_historical_failure_evidence_is_not_zero(prepared, tmp_path, monkeypatch):
    out, plan = prepared
    original_root = batch.S01_OUT
    isolated = tmp_path / 'prior_history'
    (isolated / 'S02').mkdir(parents=True)
    for binding, destination in zip(plan['history']['prior_media_events'], (isolated / 'MEDIA_EVENTS.json', isolated / 'S02/MEDIA_EVENTS.json')):
        destination.write_bytes(Path(binding['path']).read_bytes())
        binding.update(path=str(destination), sha256=batch.sha(destination))
    monkeypatch.setattr(batch, 'S01_OUT', isolated)
    first = batch.read(isolated / 'MEDIA_EVENTS.json')
    assert 'trial_technical_failures' not in first
    assert batch.history_count(plan, out, dispatch=True) == 1
    first['combined_known_failures'] = None
    batch.durable(isolated / 'MEDIA_EVENTS.json', first)
    plan['history']['prior_media_events'][0]['sha256'] = batch.sha(isolated / 'MEDIA_EVENTS.json')
    with pytest.raises(ValueError, match='unknown cannot count as zero'):
        batch.history_count(plan, out, dispatch=True)


def test_durable_replace_transient_lock_and_bounded_failure_keeps_tmp(tmp_path, monkeypatch):
    target = tmp_path / 'receipt.json'
    original_replace = Path.replace
    attempts, waits = [], []
    monkeypatch.setattr(batch.time, 'sleep', waits.append)

    def transient_lock(source, destination):
        attempts.append(destination)
        if len(attempts) <= 2:
            raise PermissionError('simulated local sharing conflict')
        return original_replace(source, destination)

    monkeypatch.setattr(Path, 'replace', transient_lock)
    batch.durable(target, {'value': 1})
    assert batch.read(target) == {'value': 1}
    assert len(attempts) == 3 and waits == [0.05, 0.05]
    assert not target.with_name('receipt.json.tmp').exists()

    attempts.clear()
    waits.clear()

    def persistent_lock(source, destination):
        attempts.append(destination)
        raise PermissionError('persistent simulated local sharing conflict')

    monkeypatch.setattr(Path, 'replace', persistent_lock)
    with pytest.raises(PermissionError, match='persistent simulated'):
        batch.durable(target, {'value': 2})
    assert len(attempts) == 20 and len(waits) == 19 and sum(waits) <= 1
    assert batch.read(target) == {'value': 1}
    assert batch.read(target.with_name('receipt.json.tmp')) == {'value': 2}
