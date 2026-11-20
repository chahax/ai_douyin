import time

import pytest

from scripts.run_script_video import original_ark_reference, read, write, sha
from src.content_factory.conversation_direction import require_reviewed_reference


def original(tmp_path):
    video = tmp_path / 'S01.mp4'
    video.write_bytes(b'original-video')
    frame = tmp_path / 'S01.last_frame.png'
    frame.write_bytes(b'original-frame')
    response = {'id': 'task-original', 'status': 'succeeded', 'model': 'mini',
                'created_at': int(time.time()) - 3600,
                'content': {'video_url': 'https://example.com/original.mp4',
                            'last_frame_url': 'https://example.com/original.png'}}
    write(video.with_suffix('.json'), {
        'provider': 'ark_api', 'status': 'downloaded', 'local_video': str(video),
        'video_sha256': sha(video), 'submit_id': 'task-original',
        'last_frame': str(frame), 'last_frame_sha256': sha(frame),
        'latest_response': response})

    class Client:
        calls = 0
        def get_task(self, task_id):
            assert task_id == 'task-original'
            self.calls += 1
            return response

    return video, frame, response, Client()


def test_original_reference_checks_account_and_keeps_provider_url(tmp_path):
    video, frame, response, client = original(tmp_path)
    ref, audit = original_ark_reference(tmp_path, video, client, {'api_model': 'mini'}, preview=True)
    assert client.calls == 0 and ref.role == 'reference_video'
    ref, audit = original_ark_reference(tmp_path, video, client, {'api_model': 'mini'}, field='last_frame_url')
    assert client.calls == 1 and ref.role == 'first_frame'
    assert audit['verification'] == 'current_account_task_get'
    assert audit['content_field'] == 'last_frame_url'
    frame.write_bytes(b'edited-frame')
    with pytest.raises(ValueError, match='modified'):
        original_ark_reference(tmp_path, video, client, {'api_model': 'mini'}, field='last_frame_url')


@pytest.mark.parametrize('defect', ['expired', 'model', 'bytes', 'provider'])
def test_unverified_or_expired_reference_is_rejected(tmp_path, defect):
    video, frame, response, client = original(tmp_path)
    if defect == 'expired': response['created_at'] -= 31 * 86400
    if defect == 'model': response['model'] = 'different-model'
    if defect == 'bytes': video.write_bytes(b'edited-video')
    if defect == 'provider':
        record = read(video.with_suffix('.json'))
        record['provider'] = 'different-provider'
        write(video.with_suffix('.json'), record)
    with pytest.raises(ValueError):
        original_ark_reference(tmp_path, video, client, {'api_model': 'mini'})


def test_user_acceptance_requires_matching_asset_and_direction(tmp_path):
    video, _, _, _ = original(tmp_path)
    (tmp_path / 'reference_reviews').mkdir()
    acceptance = {'status': 'accepted', 'video_sha256': sha(video),
                  'user_statement': '这个视频感觉是可以的', 'recorded_at': '2026-09-08T00:00:00Z'}
    write(tmp_path / 'USER_ACCEPTANCE.json', acceptance)
    write(tmp_path / 'reference_reviews' / f'{sha(video)}.json', {
        'decision': 'accepted_by_user', 'acceptance_file': 'USER_ACCEPTANCE.json',
        'asset_sha256': sha(video), 'direction_sha256': 'plan-a'})
    require_reviewed_reference(tmp_path, video, 'plan-a')
    with pytest.raises(ValueError, match='does not match'):
        require_reviewed_reference(tmp_path, video, 'plan-b')
    acceptance['video_sha256'] = 'different-video'
    write(tmp_path / 'USER_ACCEPTANCE.json', acceptance)
    with pytest.raises(ValueError, match='does not match'):
        require_reviewed_reference(tmp_path, video, 'plan-a')
