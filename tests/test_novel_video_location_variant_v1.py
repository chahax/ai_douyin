from copy import deepcopy
from pathlib import Path

import pytest

from src.content_factory import novel_video_location_variant_v1 as trial


class Client:
    def __init__(self, config, *, task_id='variant-task', fail=False, status='running'):
        self.config, self.task_id, self.fail, self.status = config, task_id, fail, status
        self.posts, self.gets = [], []

    def create_task(self, payload):
        self.posts.append(deepcopy(payload))
        if self.fail:
            raise TimeoutError('unknown transport result')
        return {'id': self.task_id}

    def get_task(self, task_id):
        self.gets.append(task_id)
        return {'id': task_id, 'status': self.status,
                'content': {'video_url': 'https://example.test/video', 'last_frame_url': 'https://example.test/tail'}}

    def download_video(self, task, path):
        Path(path).write_bytes(b'fake-video')

    def download_last_frame(self, task, path):
        Path(path).write_bytes(b'fake-native-tail')


@pytest.fixture
def variant(tmp_path, monkeypatch):
    parent = trial.parent_trial
    source = tmp_path / 'source'
    source.mkdir()
    original = Path('data/novel_agent_production/20261018_original_trial_v7/run')
    for name in ('BINDING.json', 'PRODUCTION_HANDOFF.json', 'SCREENPLAY.md', 'OUTPUT_MANIFEST.json'):
        (source / name).write_bytes((original / name).read_bytes())
    registry = tmp_path / 'registry'
    monkeypatch.setattr(parent, 'REGISTRY', registry)
    monkeypatch.setattr(trial, 'REGISTRY', registry)
    monkeypatch.setattr(trial.runtime, 'inspect', lambda run: {'status': 'text_ready_for_production', 'blockers': []})
    config = trial.seedance.SeedanceConfig('fake', base_url=trial.seedance.ARK_BASE_URL,
                                         model=trial.seedance.ARK_MINI_MODEL, provider='ark_api')
    monkeypatch.setattr(parent, '_config', lambda **kw: config)
    monkeypatch.setattr(trial, '_config', lambda **kw: config)
    parent_run = tmp_path / 'parent'
    monkeypatch.setattr(trial, 'PARENT_RUN', parent_run)
    parent.prepare(parent_run, source_run=source)
    client = Client(config, task_id=trial.PARENT_TASK_ID, status='failed')
    parent.submit(parent_run, client=client)
    parent.query(parent_run, client=client)
    return tmp_path / 'variant', source, config, parent_run


def test_exact_location_only_request_and_preserved_parent(variant):
    run, source, config, parent = variant
    before = {p.name: p.read_bytes() for p in parent.iterdir() if p.is_file()}
    result = trial.prepare(run, source_run=source)
    old = trial.core._read(parent / 'REQUEST.json')
    new = trial.core._read(run / 'REQUEST.json')
    expected = deepcopy(old)
    expected['content'][0]['text'] = expected['content'][0]['text'].replace(trial.OLD_LOCATION, trial.NEW_LOCATION, 1)
    assert new == expected
    assert new['content'][0]['text'].count(trial.NEW_LOCATION) == 1
    assert trial.OLD_LOCATION not in new['content'][0]['text']
    assert 'evidence_refs' in new['content'][0]['text']
    recipe = trial.core._read(run / 'RECIPE.json')
    assert recipe['parent_recipe'] == trial.core._read(parent / 'RECIPE.json')
    assert trial.OLD_LOCATION in recipe['world_framework']
    assert trial.NEW_LOCATION in recipe['display_world_framework']
    assert result['failure_counter']['failures_used'] == 1
    assert result['status'] == 'prepared_not_submitted'
    assert before == {p.name: p.read_bytes() for p in parent.iterdir() if p.is_file()}


def test_variant_cross_directory_cannot_redispatch_or_replace_parent_claim(variant):
    run, source, config, parent = variant
    original_claim = trial.core._read(parent / 'PLAN.json')['canonical_claim']
    parent_bytes = Path(original_claim).read_bytes()
    trial.prepare(run, source_run=source)
    other = run.with_name('another')
    trial.prepare(other, source_run=source)
    client = Client(config)
    trial.submit(run, client=client)
    with pytest.raises(ValueError, match='claim'):
        trial.submit(other, client=client)
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    assert len(client.posts) == 1
    assert Path(original_claim).read_bytes() == parent_bytes
    assert trial.core._read(run / 'PLAN.json')['canonical_claim'] != original_claim


@pytest.mark.parametrize('field,value', [('status', 'running'), ('task_id', 'different'), ('submissions_started', 0)])
def test_parent_not_fixed_known_terminal_stops(variant, field, value):
    run, source, config, parent = variant
    state = trial.core._read(parent / 'state.json')
    state[field] = value
    trial._save(parent / 'state.json', state)
    with pytest.raises(ValueError, match='failed'):
        trial.prepare(run, source_run=source)


def test_unknown_submit_stays_claimed_and_does_not_guess_id(variant):
    run, source, config, parent = variant
    trial.prepare(run, source_run=source)
    client = Client(config, fail=True)
    with pytest.raises(TimeoutError):
        trial.submit(run, client=client)
    assert trial.inspect(run)['status'] == 'submit_outcome_unknown'
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    with pytest.raises(FileNotFoundError):
        trial.query(run, client=client)
    assert len(client.posts) == 1 and client.gets == []
    assert trial.inspect(run)['failure_counter']['failures_used'] == 1


@pytest.mark.parametrize('mutation', ['text', 'parameter'])
def test_forged_binding_still_cannot_change_other_text_or_parameters(variant, mutation):
    run, source, config, parent = variant
    trial.prepare(run, source_run=source)
    request = trial.core._read(run / 'REQUEST.json')
    if mutation == 'text':
        request['content'][0]['text'] += 'other change'
    else:
        request['duration'] = 10
    trial._save(run / 'REQUEST.json', request)
    plan = trial.core._read(run / 'PLAN.json')
    plan['request'] = trial.core._binding(run / 'REQUEST.json')
    trial._save(run / 'PLAN.json', plan)
    client = Client(config)
    with pytest.raises(ValueError, match='\u8bf7\u6c42'):
        trial.submit(run, client=client)
    assert client.posts == []


def test_failures_inherit_same_story_and_are_not_double_counted(variant):
    run, source, config, parent = variant
    trial.prepare(run, source_run=source)
    client = Client(config, status='failed')
    trial.submit(run, client=client)
    trial.query(run, client=client)
    result = trial.query(run, client=client)
    assert result['failure_counter']['failures_used'] == 2
    assert result['failure_counter']['failed_task_ids'] == [trial.PARENT_TASK_ID, 'variant-task']
    with pytest.raises(ValueError):
        trial.submit(run, client=client)
    assert len(client.posts) == 1


def test_query_recovers_only_saved_original_id_after_checkpoint_failure(variant, monkeypatch):
    run, source, config, parent = variant
    trial.prepare(run, source_run=source)
    client = Client(config)
    save, crashed = trial._save, []
    def fail_once(path, value):
        if value.get('status') == 'submitted' and not crashed:
            crashed.append(True)
            raise OSError('checkpoint interrupted')
        save(path, value)
    monkeypatch.setattr(trial, '_save', fail_once)
    with pytest.raises(OSError):
        trial.submit(run, client=client)
    assert trial.core._read(run / 'state.json')['task_id'] is None
    assert trial.query(run, client=client)['task_id'] == 'variant-task'
    assert len(client.posts) == 1 and client.gets == ['variant-task']


def test_success_only_saved_as_pending_human_and_no_continuation(variant, monkeypatch):
    run, source, config, parent = variant
    trial.prepare(run, source_run=source)
    client = Client(config, status='succeeded')
    trial.submit(run, client=client)
    monkeypatch.setattr(trial, '_metadata', lambda path: {'container_complete': True})
    monkeypatch.setattr(trial, 'last_frame_integrity', lambda path: {'complete': True})
    result = trial.query(run, client=client)
    receipt = trial.core._read(run / 'receipt.json')
    assert result['content_status'] == 'awaiting_human_review' and not result['human_approved']
    assert not receipt['content_inspection_performed'] and not receipt['posthoc_frame_extraction']
    assert not receipt['audio_or_asr_review_performed'] and not receipt['continuation_authorized']
    assert receipt['native_tail_source'] == 'provider_returned_original_last_frame_url'
    trial.media_review_policy.validate_source_bindings(receipt)
    trial.query(run, client=client)
    assert len(client.posts) == 1 and client.gets == ['variant-task']


def test_real_parent_compiles_to_main_agent_expected_request_without_calls():
    plan, request, files = trial._parent()
    handoff = trial._source(plan['source_run'])
    recipe, prompt = trial.compile_prompt(handoff)
    expected = trial.core._read('data/video_generation/novel_ferry_location_variant_20261018/EXPECTED_REQUEST.json')
    assert trial._payload(prompt, trial._config()) == trial._expected_request(request) == expected
    assert recipe['location_variant']['replacement_count'] == 1
    assert files
