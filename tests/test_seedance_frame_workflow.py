import json

import httpx
import pytest
from PIL import Image

from test_conversation_direction import setup
from scripts.run_script_video import prepare, read, write, submit, save_last_frame
from src.content_factory.seedance_frames import bind_frame, image_info
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, ARK_BASE_URL, ARK_MINI_MODEL


def frame_run(tmp_path):
    _, script, _, plan = setup(tmp_path)
    folder = tmp_path / 'run'
    prepare(folder, script, 'test scope', plan, provider='ark_api')
    image = folder / 'opening.png'
    Image.new('RGB', (320, 480), 'white').save(image)
    return folder, image, read(folder / 'production.json'), read(folder / 'direction_plan.json')


def review(plan, shot, image):
    return {'shot_id': shot, 'camera_id': next(s['camera_id'] for s in plan['shots'] if s['shot_id'] == shot),
            'checks': {'composition': True, 'identity': True, 'opening_state': True},
            'notes': 'fixture only', 'evidence': [image.name]}


def config():
    return SeedanceConfig(api_key='test-private-key', base_url=ARK_BASE_URL, model=ARK_MINI_MODEL, provider='ark_api')


def test_reviewed_first_frame_reaches_real_submit_payload_and_preview_never_submits(tmp_path, monkeypatch):
    folder, image, manifest, plan = frame_run(tmp_path)
    bind_frame(folder, 'S02', image, review(plan, 'S02', image), manifest, plan)
    monkeypatch.setattr('scripts.run_script_video.save_ark_report', lambda *a: None)
    calls = []
    class Client(SeedanceClient):
        def create_task(self, payload):
            calls.append(payload)
            assert read(folder / 'S02.json')['status'] == 'submit_outcome_unknown'
            return {'id': 'cgt-frame'}
    with Client(config()) as client:
        submit(folder, 'S02', client, [], image, preview=True)
        assert not calls and not (folder / 'S02.json').exists()
        assert read(folder / 'S02.workflow.preview.json')['video_generation_submitted'] is False
        submit(folder, 'S02', client, [], image)
        assert calls[0]['content'][1]['role'] == 'first_frame'
        assert calls[0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
        assert calls[0]['ratio'] == 'adaptive' and calls[0]['return_last_frame'] is True
        original = (folder / 'S02.json').read_bytes()
        submit(folder, 'S02', client, [], image, preview=True)
        assert len(calls) == 1 and (folder / 'S02.json').read_bytes() == original
        with pytest.raises(ValueError, match='duplicate'):
            submit(folder, 'S02', client, [], image)


def test_missing_or_changed_frame_review_blocks_spending(tmp_path):
    folder, image, manifest, plan = frame_run(tmp_path)
    with SeedanceClient(config()) as client:
        with pytest.raises(ValueError, match='Bind and review'):
            submit(folder, 'S02', client, [], image, preview=True)
        bind_frame(folder, 'S02', image, review(plan, 'S02', image), manifest, plan)
        Image.new('RGB', (320, 480), 'black').save(image)
        with pytest.raises(ValueError, match='changed'):
            submit(folder, 'S02', client, [], image, preview=True)
        with pytest.raises(ValueError, match='cannot mix'):
            submit(folder, 'S02', client, [image], image, preview=True)
    assert not (folder / 'S02.json').exists()


def test_raw_tail_cannot_silently_cross_to_another_camera(tmp_path):
    folder, image, manifest, plan = frame_run(tmp_path)
    assert plan['shots'][0]['camera_id'] != plan['shots'][1]['camera_id']
    write(folder / 'S01.json', {'shot': 'S01', 'last_frame': str(image), 'last_frame_sha256': image_info(image)['sha256']})
    with pytest.raises(ValueError, match='Camera changes'):
        bind_frame(folder, 'S02', image, review(plan, 'S02', image), manifest, plan)


def test_returned_tail_is_saved_without_ark_key_on_media_host(tmp_path):
    folder, image, manifest, plan = frame_run(tmp_path)
    video = folder / 'S01.mp4'
    video.write_bytes(b'fixture video')
    from scripts.run_script_video import sha
    task = {'status': 'succeeded', 'content': {'last_frame_url': 'https://media.example/tail.png'}}
    write(folder / 'S01.json', {'provider': 'ark_api', 'status': 'downloaded', 'shot': 'S01',
                              'local_video': str(video), 'video_sha256': sha(video), 'latest_response': task})
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == 'GET' and 'authorization' not in request.headers
        return httpx.Response(200, content=image.read_bytes())
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with SeedanceClient(config(), http_client=http) as client:
            save_last_frame(folder, 'S01', client)
            save_last_frame(folder, 'S01', client)
    assert len(calls) == 1
    assert (folder / 'S01.last_frame.png').read_bytes() == image.read_bytes()
    assert read(folder / 'S01.json')['last_frame_sha256'] == image_info(image)['sha256']
