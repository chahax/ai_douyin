import copy
import importlib.util
from pathlib import Path
import subprocess
import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/run_h3_six_children_batch_20261102.py'
spec = importlib.util.spec_from_file_location('h3_batch', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
h = m.h


def history(prompt_id, graph):
    return {prompt_id: dict(prompt=[0, prompt_id, graph], status=dict(status_str='success', completed=True), outputs={})}


def fake_receipt(run, prompt_id):
    files = {}
    for role in ('video', 'audio', 'first', 'last'):
        p = run / ('native_' + role + '.bin')
        p.write_bytes((run.name + role).encode())
        files[role] = h.binding(p)
    receipt = dict(prompt_id=prompt_id, technical_status='succeeded', content_status='awaiting_human_review',
                   files=files, delivery=files['video'])
    h.durable(run / 'receipt.json', receipt)
    return receipt


@pytest.fixture
def batch(tmp_path, monkeypatch):
    base = h.read(m.SERVICE / 'workflow_api.json')
    model_rows = h.read(m.SERVICE / 'PLAN.json')['models']
    service = tmp_path / 'service'
    (service / 'input').mkdir(parents=True)
    (service / 'output').mkdir()
    h.durable(service / 'workflow_api.json', base)
    h.durable(service / 'PLAN.json', dict(models=model_rows))
    h.durable(service / 'HISTORY.json', history('first-id', base))
    fake_receipt(service, 'first-id')
    seed = tmp_path / 'seed'
    for segment in m.IDS:
        p = seed / 'segments' / segment / 'PROMPT.txt'
        p.parent.mkdir(parents=True)
        p.write_bytes((segment + ' 原对白\r\n原动作').encode())
    monkeypatch.setattr(m, 'SERVICE', service)
    monkeypatch.setattr(m, 'SEEDANCE', seed)
    root = tmp_path / 'batch'
    m.prepare(root)
    h.durable(root / 'PRIMARY_DISPATCH_REVIEW.json', dict(approved_for_remaining_three_and_assembly=True,
                                                       plan_sha256=h.sha(root / 'PLAN.json')))
    return root


class Client:
    def __init__(self, batch):
        self.batch = batch
        self.histories = {'first-id': h.read(m.SERVICE / 'HISTORY.json')}
        self.posts = []
        self.gets = []
        self.error_at = None
        self.busy = False
        self.corrupt = False

    def get(self, path):
        self.gets.append(path)
        if path.startswith('/history/'):
            return self.histories.get(path.rsplit('/', 1)[-1], {})
        if path == '/system_stats':
            return {'system': {'argv': ['main.py', '--input-directory', str(m.SERVICE / 'input'),
                    '--output-directory', str(m.SERVICE / 'output'), '--offline', '--disable-all-custom-nodes']}}
        if path == '/queue':
            return dict(queue_running=[['busy']] if self.busy else [], queue_pending=[])
        raise AssertionError(path)

    def post(self, request):
        self.posts.append(request)
        if self.error_at == len(self.posts):
            raise TimeoutError('unknown submission')
        prompt_id = 'id-' + str(len(self.posts))
        graph = copy.deepcopy(request['prompt'])
        if self.corrupt:
            graph['condition']['inputs']['width'] = 32
        self.histories[prompt_id] = history(prompt_id, graph)
        return dict(prompt_id=prompt_id, node_errors={})


def collect(run, entry, state):
    receipt = fake_receipt(run, state['prompt_id'])
    state['status'] = 'saved'
    h.durable(run / 'STATE.json', state)
    return receipt


def assemble(batch, receipts):
    assert len(receipts) == 4
    receipt = dict(delivery=receipts[-1]['delivery'], segments=receipts)
    h.durable(batch / 'receipt.json', receipt)
    h.durable(batch / 'STATE.json', dict(status='saved'))
    return receipt


def run_batch(batch, client):
    return m.execute(batch, client, validate_fn=lambda run: None, collect_fn=collect, assemble_fn=assemble)


def test_three_serial_submissions_native_tail_chain_and_saved_noop(batch):
    client = Client(batch)
    original = h.sha(m.SERVICE / 'receipt.json')
    run_batch(batch, client)
    assert len(client.posts) == 3
    assert h.sha(m.SERVICE / 'receipt.json') == original
    previous = m.SERVICE
    for index, segment in enumerate(m.IDS):
        run = batch / segment
        frozen = h.read(run / 'FROZEN_INPUT.json')
        assert frozen['predecessor_receipt'] == h.binding(previous / 'receipt.json')
        tail = h.read(previous / 'receipt.json')['files']['last']
        assert frozen['staged_input']['sha256'] == tail['sha256']
        graph = client.posts[index]['prompt']
        assert graph['condition']['inputs']['prompt'] == (run / 'PROMPT.txt').read_text(encoding='utf-8')
        assert graph['save_video']['inputs']['filename_prefix'] == m.PREFIX + '/' + segment + '/video'
        assert h.read(run / 'STATE.json')['submissions'] == 1
        previous = run
    run_batch(batch, client)
    assert len(client.posts) == 3


def test_unknown_second_submission_stops_third_and_resume_never_reposts(batch):
    client = Client(batch)
    client.error_at = 2
    with pytest.raises(TimeoutError):
        run_batch(batch, client)
    assert len(client.posts) == 2
    assert h.read(batch / 'S04/STATE.json')['status'] == 'prepared'
    with pytest.raises(ValueError, match='unknown_submission_not_replayed'):
        run_batch(batch, client)
    assert len(client.posts) == 2


def test_known_id_recovers_after_collection_interrupt_without_repost(batch):
    client = Client(batch)
    with pytest.raises(RuntimeError):
        m.execute(batch, client, validate_fn=lambda run: None,
                  collect_fn=lambda *args: (_ for _ in ()).throw(RuntimeError('local interruption')), assemble_fn=assemble)
    assert len(client.posts) == 1
    run_batch(batch, client)
    assert len(client.posts) == 3


@pytest.mark.parametrize('problem', ['busy', 'missing_predecessor_live_history', 'changed_prompt', 'changed_predecessor_tail', 'review_changed'])
def test_preflight_problems_prevent_any_submission(batch, problem):
    client = Client(batch)
    if problem == 'busy':
        client.busy = True
    elif problem == 'missing_predecessor_live_history':
        client.histories.clear()
    elif problem == 'changed_prompt':
        (batch / 'S03/PROMPT.txt').write_text('changed')
    elif problem == 'changed_predecessor_tail':
        Path(h.read(m.SERVICE / 'receipt.json')['files']['last']['path']).write_bytes(b'changed')
    else:
        h.durable(batch / 'PRIMARY_DISPATCH_REVIEW.json', dict(approved_for_remaining_three_and_assembly=False))
    with pytest.raises(ValueError):
        run_batch(batch, client)
    assert not client.posts


def test_history_mismatch_never_continues(batch):
    client = Client(batch)
    client.corrupt = True
    with pytest.raises(ValueError, match='history_identity_mismatch'):
        run_batch(batch, client)
    assert len(client.posts) == 1
    assert h.read(batch / 'S03/STATE.json')['status'] == 'prepared'


def test_native_validation_failure_prevents_claim(batch):
    client = Client(batch)
    def fail(run):
        raise ValueError('native validation rejected')
    with pytest.raises(ValueError, match='native validation rejected'):
        m.execute(batch, client, validate_fn=fail, collect_fn=collect, assemble_fn=assemble)
    assert not client.posts
    assert not (batch / 'S02/SUBMISSION_CLAIM.json').exists()


def test_full_batch_exclusive_lock(batch):
    client = Client(batch)
    with h.process_lock(batch / '.batch.lock'):
        with pytest.raises(OSError):
            run_batch(batch, client)
    assert not client.posts


def test_collect_rejects_other_segment_output(batch):
    entry = {'outputs': {'save_video': {'images': [{'type': 'output', 'subfolder': 'S01', 'filename': 'video.mp4'}]}}}
    with pytest.raises(ValueError, match='output_escape_or_wrong_segment'):
        m.collect(batch / 'S02', entry, {'prompt_id': 'id'})


def test_partial_encode_is_preserved_and_not_overwritten(batch):
    target = batch / 'partial.mp4'
    target.write_bytes(b'partial')
    with pytest.raises(ValueError, match='incomplete_local_encode_preserved'):
        m.run_ffmpeg_once(batch, 'CROP', ['ffmpeg'], target)
    assert target.read_bytes() == b'partial'


def test_real_ffmpeg_silent_color_assembly(tmp_path):
    """Synthetic pixels/silence only: no inspection of user/generated content."""
    source = tmp_path / 'synthetic.mp4'
    command = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=720x1280:r=24',
               '-f', 'lavfi', '-i', 'anullsrc=r=32000:cl=stereo', '-t', f'{m.DURATION:.12f}',
               '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-movflags', '+faststart', str(source)]
    subprocess.run(command, capture_output=True, check=True)
    batch = tmp_path / 'assembled'
    batch.mkdir()
    receipts = [dict(prompt_id='synthetic-' + str(i), delivery=h.binding(source)) for i in range(4)]
    result = m.assemble(batch, receipts)
    assert result['technical_status'] == 'succeeded'
    assert result['video_stream_copy'] is True
    assert h.read(batch / 'PACKET_TIMELINE.json')['count'] == 1448
    assert h.read(batch / 'STATE.json')['status'] == 'saved'
