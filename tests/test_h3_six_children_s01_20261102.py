import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/run_h3_six_children_s01_20261102.py'
spec = importlib.util.spec_from_file_location('h3_same_pixel', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def run(tmp_path, monkeypatch):
    seed = tmp_path / 'seed'
    (seed / 'segments/S01').mkdir(parents=True)
    (seed / 'assets').mkdir()
    (seed / 'segments/S01/PROMPT.txt').write_bytes('原文不改。\r\n对白与动作。'.encode())
    (seed / 'assets/opening.original.jpeg').write_bytes(b'original-jpeg')
    graph = m.read(m.SOURCE)
    models = tmp_path / 'models'
    for folder, name in [('diffusion_models', graph['127']['inputs']['unet_name']),
                         ('text_encoders', graph['128']['inputs']['clip_name'])] + [
                             ('vae', graph[n]['inputs']['vae_name']) for n in ('119', '120')]:
        p = models / folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'model')
    monkeypatch.setattr(m, 'SEEDANCE', seed)
    monkeypatch.setattr(m, 'MODEL_ROOT', models)
    root = tmp_path / 'run'
    m.prepare(root)
    plan = m.read(root / 'PLAN.json')
    m.durable(root / 'NATIVE_VALIDATION.json', dict(valid=True, node_errors={}, node_execution_performed=False,
                                                 graph_sha256=plan['graph']['sha256']))
    m.durable(root / 'PRIMARY_DISPATCH_REVIEW.json', dict(approved_for_single_submission=True,
              plan_sha256=m.sha(root / 'PLAN.json'), native_validation_sha256=m.sha(root / 'NATIVE_VALIDATION.json')))
    return root


class FakeClient:
    def __init__(self, run, error=None):
        self.run, self.error, self.posts, self.gets = run, error, [], []
        self.queue = dict(queue_running=[], queue_pending=[])
        self.argv = ['main.py', '--input-directory', str(run / 'input'), '--output-directory', str(run / 'output'),
                     '--offline', '--disable-all-custom-nodes']

    def get(self, path):
        self.gets.append(path)
        if path == '/system_stats':
            return dict(system=dict(argv=self.argv))
        if path == '/queue':
            return self.queue
        if path == '/history/original-id':
            return {'original-id': dict(prompt=[0, 'original-id', m.read(self.run / 'workflow_api.json')],
                                        status=dict(status_str='success', completed=True), outputs={})}
        raise AssertionError(path)

    def post(self, request):
        self.posts.append(request)
        if self.error:
            raise self.error
        return dict(prompt_id='original-id', node_errors={})


def fake_collect(run, entry, state):
    state['status'] = 'saved'
    m.durable(run / 'STATE.json', state)
    return state


def test_exact_inputs_and_graph_changes(run):
    plan = m.validate(run)
    assert (run / 'PROMPT.txt').read_bytes() == Path(plan['source_prompt']['path']).read_bytes()
    assert (run / 'input/opening.original.jpeg').read_bytes() == b'original-jpeg'
    old, new = m.read(m.SOURCE), m.read(run / 'workflow_api.json')
    assert set(old) == set(new)
    changed = {key for key in new if new[key] != old[key]}
    assert changed == {'condition', 'ref_scene', '129', 'save_video', 'save_audio', 'save_first', 'save_last'}
    assert new['condition']['inputs']['width'] == 736
    assert new['condition']['inputs']['height'] == 1312
    assert new['condition']['inputs']['length'] == 362
    assert new['pick_last']['inputs']['batch_index'] == 361
    assert new['130']['inputs']['fps'] == 24


def test_single_submission_and_saved_noop(run):
    c = FakeClient(run)
    result = m.execute(run, c, collect_fn=fake_collect)
    assert result['status'] == 'saved'
    assert len(c.posts) == 1
    assert m.read(run / 'SUBMISSION_CLAIM.json')['request']['sha256'] == m.sha(run / 'REQUEST.actual.json')
    m.execute(run, c, collect_fn=fake_collect)
    assert len(c.posts) == 1


def test_unknown_submission_never_replays(run):
    c = FakeClient(run, TimeoutError('response lost'))
    with pytest.raises(TimeoutError):
        m.execute(run, c, collect_fn=fake_collect)
    assert m.read(run / 'STATE.json')['status'] == 'submit_outcome_unknown'
    with pytest.raises(ValueError, match='unknown_submission_not_replayed'):
        m.execute(run, c, collect_fn=fake_collect)
    assert len(c.posts) == 1


def test_original_id_response_recovery_without_post(run):
    m.durable(run / 'SUBMISSION_RESPONSE.json', dict(prompt_id='original-id', node_errors={}))
    c = FakeClient(run)
    m.execute(run, c, collect_fn=fake_collect)
    assert c.posts == []
    assert c.gets == ['/history/original-id']


@pytest.mark.parametrize('field', ['prompt', 'opening', 'graph'])
def test_changed_frozen_input_blocks_before_submit(run, field):
    Path(m.read(run / 'PLAN.json')[field]['path']).write_bytes(b'changed')
    c = FakeClient(run)
    with pytest.raises(ValueError, match='frozen_input_changed'):
        m.execute(run, c, collect_fn=fake_collect)
    assert not c.posts
    assert not (run / 'SUBMISSION_CLAIM.json').exists()


@pytest.mark.parametrize('cause', ['busy', 'wrong_input', 'review_missing', 'validation_not_pure'])
def test_preflight_blocks_without_claim(run, cause):
    c = FakeClient(run)
    if cause == 'busy':
        c.queue['queue_running'] = [['other']]
    elif cause == 'wrong_input':
        c.argv[2] = str(run.parent)
    elif cause == 'review_missing':
        (run / 'PRIMARY_DISPATCH_REVIEW.json').unlink()
    else:
        val = m.read(run / 'NATIVE_VALIDATION.json')
        val['node_execution_performed'] = True
        m.durable(run / 'NATIVE_VALIDATION.json', val)
    with pytest.raises((ValueError, FileNotFoundError)):
        m.execute(run, c, collect_fn=fake_collect)
    assert not c.posts
    assert not (run / 'SUBMISSION_CLAIM.json').exists()


def test_collect_rejects_output_escape(run):
    entry = {'outputs': {'save_video': {'images': [{'type': 'output', 'subfolder': '../..', 'filename': 'escape.mp4'}]}}}
    with pytest.raises(ValueError, match='output_escape'):
        m.collect(run, entry, {'prompt_id': 'original-id'})
