"""Focused offline guards for the single source-bound service trial."""
import copy
import json
from types import SimpleNamespace

import pytest

from src.content_factory import assistant_seedance_trial as trial
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceClient


class FakeClient:
    config = SimpleNamespace(provider='ark_api', model=ARK_MINI_MODEL, base_url=ARK_BASE_URL)
    build_task_payload = SeedanceClient.build_task_payload

    def __init__(self, unknown=False):
        self.posts = 0
        self.gets = 0
        self.unknown = unknown
        self.query_id = 'offline_task_1'

    def create_task(self, payload):
        self.posts += 1
        if self.unknown:
            raise TimeoutError('offline unknown result; never resubmit')
        return {'id': 'offline_task_1'}

    def get_task(self, task_id):
        self.gets += 1
        return {'id': self.query_id, 'status': 'running'}


@pytest.fixture
def prepared_input(tmp_path, monkeypatch):
    plan = copy.deepcopy(trial.read(trial.OUT / 'PLAN.json'))
    ledger = tmp_path / 'historical_ledger.json'
    ledger.write_bytes(trial.STORY_LEDGER.read_bytes())
    monkeypatch.setattr(trial, 'STORY_LEDGER', ledger)
    plan['story_counter']['path'] = str(ledger)
    plan['story_counter']['sha256'] = trial.sha(ledger)
    out = tmp_path / 'trial'
    out.mkdir()
    trial.persist(out / 'PLAN.json', plan)
    return out, plan, ledger


def test_source_admission_and_non_seedream_rejection(prepared_input, tmp_path):
    out, plan, _ = prepared_input
    trial.validate(out / 'PLAN.json')
    original = trial.read(plan['references'][1]['provenance']['path'])
    original['model'] = 'openai-image-tool'
    altered = tmp_path / 'wrong_provider_receipt.json'
    trial.persist(altered, original)
    plan['references'][1]['provenance'] = {'path': str(altered), 'sha256': trial.sha(altered)}
    trial.persist(out / 'PLAN.json', plan)
    with pytest.raises(ValueError, match='fresh original Seedream'):
        trial.validate(out / 'PLAN.json')


def test_prepare_is_local_and_duplicate_submit_is_blocked(prepared_input):
    out, _, ledger = prepared_input
    before = trial.sha(ledger)
    client = FakeClient()
    trial.execute('prepare', client, out)
    assert client.posts == 0
    assert not (out / 'SUBMISSION_CLAIM.json').exists()
    preview = (out / 'REQUEST.preview.json').read_text(encoding='utf-8')
    assert 'base64,' not in preview
    assert 'url_sha256' in preview
    trial.execute('submit', client, out)
    with pytest.raises(ValueError, match='already claimed'):
        trial.execute('submit', client, out)
    assert client.posts == 1
    assert trial.sha(ledger) == before
    assert trial.read(out / 'MEDIA_EVENTS.json')['combined_known_failures'] == 1


def test_unknown_result_cannot_resubmit_or_query_new_id(prepared_input):
    out, _, _ = prepared_input
    client = FakeClient(unknown=True)
    trial.execute('prepare', client, out)
    result = trial.execute('submit', client, out)
    assert result['status'] == 'submit_outcome_unknown'
    with pytest.raises(ValueError, match='already claimed'):
        trial.execute('submit', client, out)
    with pytest.raises(FileNotFoundError):
        trial.execute('query', client, out)
    assert client.posts == 1 and client.gets == 0
    assert trial.read(out / 'receipt.json')['error_message'].startswith('offline unknown')


def test_query_rejects_mismatched_provider_task_id(prepared_input):
    out, _, _ = prepared_input
    client = FakeClient()
    trial.execute('prepare', client, out)
    trial.execute('submit', client, out)
    client.query_id = 'another_task'
    with pytest.raises(ValueError, match='another task identity'):
        trial.execute('query', client, out)
    assert client.posts == 1 and client.gets == 1


def test_native_jpeg_tail_encoded_integrity_and_truncation(tmp_path):
    # Provider's original encoded bytes: inspect headers/markers only, never pixels.
    original = trial.OUT / 'S01.provider_last.png'
    metadata = trial.last_frame_integrity(original)
    assert metadata['format'] == 'jpeg'
    assert metadata['eoi_present'] is True
    assert metadata['pixel_decoding'] is False
    truncated = tmp_path / 'truncated_native_tail.jpeg'
    truncated.write_bytes(original.read_bytes()[:-2])
    with pytest.raises(ValueError, match='truncated JPEG'):
        trial.last_frame_integrity(truncated)
