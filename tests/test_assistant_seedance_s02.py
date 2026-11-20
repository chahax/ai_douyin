"""Only the new S02 native-tail, continuation and duplicate/unknown gates."""
import base64
import copy
import hashlib
from types import SimpleNamespace

import pytest

from src.content_factory import assistant_seedance_s02 as s02
from src.content_factory.seedance_client import ARK_BASE_URL, ARK_MINI_MODEL, SeedanceClient


class FakeClient:
    config = SimpleNamespace(provider='ark_api', model=ARK_MINI_MODEL, base_url=ARK_BASE_URL)
    build_task_payload = SeedanceClient.build_task_payload

    def __init__(self):
        self.posts = 0

    def create_task(self, request):
        self.posts += 1
        raise TimeoutError('offline unknown submission result')


@pytest.fixture
def input_plan(tmp_path, monkeypatch):
    plan = copy.deepcopy(s02.read(s02.OUT / 'PLAN.json'))
    out = tmp_path / 'S02'
    out.mkdir()
    for name in ('SOURCE_S02.md', 'PROMPT.txt', 'USER_CONTINUATION.json', 'SOURCE_SERVICE_GET.json',
                 'S01.service_native_tail.original.jpg', 'NATIVE_TAIL_BINDING.json'):
        (out / name).write_bytes((s02.OUT / name).read_bytes())
    tail = s02.read(out / 'NATIVE_TAIL_BINDING.json')
    tail.update(native_tail_path=str(out / 'S01.service_native_tail.original.jpg'),
                service_get_path=str(out / 'SOURCE_SERVICE_GET.json'), user_continuation_path=str(out / 'USER_CONTINUATION.json'))
    s02.persist(out / 'NATIVE_TAIL_BINDING.json', tail)
    for key in ('prompt', 'user_continuation', 'service_source', 'first_frame', 'native_tail_binding'):
        path = out / s02.Path(plan[key]['path']).name
        plan[key].update(path=str(path), sha256=s02.sha(path))
    plan['sources']['segment']['path'] = str(out / 'SOURCE_S02.md')
    ledger = tmp_path / 'legacy.json'
    ledger.write_bytes(s02.STORY_LEDGER.read_bytes())
    monkeypatch.setattr(s02, 'STORY_LEDGER', ledger)
    plan['story_counter'].update(path=str(ledger), sha256=s02.sha(ledger))
    s02.persist(out / 'PLAN.json', plan)
    return out, plan


def test_one_exact_first_frame_and_unknown_cannot_resubmit(input_plan):
    out, _ = input_plan
    client = FakeClient()
    before = s02.sha(s02.S01_OUT / 'receipt.json')
    s02.execute('prepare', client, out)
    request = s02.read(out / 'REQUEST.actual.json')
    refs = request['content'][1:]
    assert len(refs) == 1 and refs[0]['role'] == 'first_frame'
    raw = base64.b64decode(refs[0]['image_url']['url'].split(',', 1)[1])
    assert hashlib.sha256(raw).hexdigest() == s02.PRIOR_TAIL_SHA
    assert client.posts == 0
    result = s02.execute('submit', client, out)
    assert result['status'] == 'submit_outcome_unknown'
    with pytest.raises(ValueError, match='already claimed'):
        s02.execute('submit', client, out)
    with pytest.raises(FileNotFoundError):
        s02.execute('query', client, out)
    assert client.posts == 1
    assert s02.sha(s02.S01_OUT / 'receipt.json') == before


def test_changed_native_tail_is_blocked_before_claim(input_plan):
    out, _ = input_plan
    frame = out / 'S01.service_native_tail.original.jpg'
    frame.write_bytes(frame.read_bytes()[:-2])
    with pytest.raises(ValueError, match='bound source/artifact changed'):
        s02.execute('prepare', FakeClient(), out)
    assert not (out / 'SUBMISSION_CLAIM.json').exists()


def test_continuation_without_user_acceptance_is_blocked(input_plan):
    out, plan = input_plan
    path = out / 'USER_CONTINUATION.json'
    user = s02.read(path)
    user['accepted_prior_segment_for_continuation'] = False
    s02.persist(path, user)
    plan['user_continuation']['sha256'] = s02.sha(path)
    s02.persist(out / 'PLAN.json', plan)
    with pytest.raises(ValueError, match='user continuation does not bind'):
        s02.execute('prepare', FakeClient(), out)
    assert not (out / 'SUBMISSION_CLAIM.json').exists()
