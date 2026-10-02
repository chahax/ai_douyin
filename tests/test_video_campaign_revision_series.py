"""Offline campaign revisions preserve failure history and never reuse old passes."""
import copy

import pytest

from src.content_factory import video_campaign as campaign
from src.content_factory.script_video_review import file_sha
from test_video_campaign import setup_campaign, candidate, generated_review


@pytest.fixture
def old_campaign(tmp_path):
    path = setup_campaign(tmp_path)
    for number in range(1, 4):
        folder, manifest, record = candidate(path, number)
        campaign.reserve(folder, manifest, record)
        campaign.review(folder, 'S01', generated_review(folder, record, False))
    folder, manifest, record = candidate(path, 4)
    campaign.reserve(folder, manifest, record)
    campaign.review(folder, 'S01', generated_review(folder, record, True))
    folder, manifest, record = candidate(path, 5, 'S02')
    record['first_frame_sha256'] = 'original-tail'
    campaign.reserve(folder, manifest, record)
    review = generated_review(folder, record, True)
    value = campaign.read(review)
    value['decision'] = 'pending'
    for field in ('speaker_voice', 'lip_sync'):
        value['checks'][field] = None
    value['observations'] = [o for o in value['observations'] if value['checks'][o['check']] is not None]
    campaign.write(review, value)
    campaign.review(folder, 'S02', review)
    # Represent the exact pre-series storage layout; no real campaign is edited.
    data = campaign.read(path)
    for attempt in data['attempts']:
        attempt.pop('series_id', None)
        run = tmp_path / f"run_{int(attempt['id'].split('_')[1])}"
        production = campaign.read(run / 'production.json')
        production.pop('campaign_series_id', None)
        campaign.write(run / 'production.json', production)
        receipt = campaign.read(run / f"{attempt['shot']}.json")
        receipt.pop('campaign_series_id', None)
        campaign.write(run / f"{attempt['shot']}.json", receipt)
    campaign.write(path, data)
    return path, folder, record['campaign_attempt_id']


def begin(case):
    path, _, pending_id = case
    return campaign.start_revision(path, authorization='用户明确开始新版完整视频',
        reason='使用新审核通过剧本从首镜重新制作', supersede_attempt_ids=(pending_id,))


def test_start_preserves_legacy_attempts_failures_and_pending_review_truth(old_campaign):
    path, folder, pending_id = old_campaign
    original = campaign.read(path)
    files = {p: p.read_bytes() for p in path.parent.rglob('*') if p.is_file() and p != path}
    result = begin(old_campaign)
    data = campaign.read(path)
    assert result['next_shot'] == 'S01' and result['failed_outputs'] == data['failed_outputs'] == 3
    assert result['previous_series_id'] == 'legacy' and result['series_id'] == data['current_series_id']
    assert len(data['attempts']) == len(original['attempts'])
    assert data['attempts'][:-1] == original['attempts'][:-1]
    pending = data['attempts'][-1]
    assert pending['id'] == pending_id and pending['status'] == 'superseded'
    assert pending['superseded_from_status'] == 'awaiting_review'
    assert pending['uninspected_checks'] == ['speaker_voice', 'lip_sync']
    assert pending['supersession']['authorization'] == '用户明确开始新版完整视频'
    assert pending['supersession']['proof']['video_sha256'] == original['attempts'][-1]['video_sha256']
    assert pending['supersession']['proof']['recorded_status'] == 'downloaded'
    assert all(p.read_bytes() == raw for p, raw in files.items())
    assert campaign.read(folder / 'S02.quality_review.json')['decision'] == 'pending'


@pytest.mark.parametrize('defect', ['submitted', 'unknown', 'downloading', 'download_failed',
    'video_changed', 'record_hash_changed', 'attempt_unreconciled', 'provider_still_running'])
def test_unresolved_or_unverified_output_cannot_be_superseded(old_campaign, defect):
    path, folder, _ = old_campaign
    receipt = campaign.read(folder / 'S02.json')
    if defect == 'video_changed':
        (folder / 'S02.mp4').write_bytes(b'tampered output')
    elif defect == 'record_hash_changed': receipt['video_sha256'] = '0' * 64
    elif defect == 'attempt_unreconciled':
        data = campaign.read(path)
        data['attempts'][-1]['status'] = 'awaiting_generation_or_review'
        campaign.write(path, data)
    elif defect == 'provider_still_running': receipt['latest_response'] = {'status': 'running'}
    else: receipt['status'] = defect
    campaign.write(folder / 'S02.json', receipt)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        begin(old_campaign)
    assert path.read_bytes() == before and not path.with_suffix('.lock').exists()


@pytest.mark.parametrize('ids', [(), ('unknown',), ('attempt_005', 'attempt_005'), ('attempt_004',)])
def test_superseding_requires_exact_explicit_pending_attempt_ids(old_campaign, ids):
    path, _, _ = old_campaign
    before = path.read_bytes()
    with pytest.raises(ValueError):
        campaign.start_revision(path, authorization='明确重新制作', reason='新的完整制作', supersede_attempt_ids=ids)
    assert path.read_bytes() == before


def test_new_series_starts_at_first_shot_and_old_runs_cannot_join_it(old_campaign):
    path, old_folder, _ = old_campaign
    result = begin(old_campaign)
    with pytest.raises(ValueError, match='older.*series'):
        campaign.attach(old_folder, path)
    folder, manifest, record = candidate(path, 6, 'S02')
    assert manifest['campaign_series_id'] == result['series_id']
    with pytest.raises(ValueError, match='S01'):
        campaign.reserve(folder, manifest, record)
    with pytest.raises(ValueError, match='not passed'):
        campaign.require_approved_segments(folder, manifest)
    record['shot'] = 'S01'
    campaign.reserve(folder, manifest, record)
    attempt = campaign.read(path)['attempts'][-1]
    assert attempt['series_id'] == result['series_id'] and attempt['shot'] == 'S01'
    assert attempt['id'] == 'attempt_006'


def test_only_current_series_preceding_original_tail_releases_next_shot(old_campaign):
    path, _, _ = old_campaign
    revision = begin(old_campaign)
    folder, manifest, record = candidate(path, 6)
    campaign.reserve(folder, manifest, record)
    review = generated_review(folder, record, True)
    tail = folder / 'S01.last_frame.png'
    tail.write_bytes(b'actual new series original tail')
    record.update(last_frame=str(tail), last_frame_sha256=file_sha(tail))
    campaign.write(folder / 'S01.json', record)
    campaign.review(folder, 'S01', review)
    next_folder, next_manifest, next_record = candidate(path, 7, 'S02')
    assert next_manifest['campaign_series_id'] == revision['series_id']
    next_record['first_frame_sha256'] = 'original-tail'
    with pytest.raises(ValueError, match='preceding'):
        campaign.reserve(next_folder, next_manifest, next_record)
    next_record['first_frame_sha256'] = file_sha(tail)
    campaign.reserve(next_folder, next_manifest, next_record)
    assert campaign.read(path)['failed_outputs'] == 3
    assert campaign.read(path)['attempts'][-1]['series_id'] == revision['series_id']


def test_run_retry_stays_in_series_and_global_tenth_failure_still_locks(old_campaign):
    path, _, _ = old_campaign
    revision = begin(old_campaign)
    for number in range(6, 13):
        folder, manifest, record = candidate(path, number)
        assert manifest['campaign_series_id'] == revision['series_id']
        campaign.reserve(folder, manifest, record)
        result = campaign.review(folder, 'S01', generated_review(folder, record, False))
        assert result['failed_outputs'] == number - 2
    data = campaign.read(path)
    assert data['failed_outputs'] == 10 and data['status'] == 'paused_for_human_review'
    assert len(campaign.read(path.with_name('HUMAN_REVIEW_REQUIRED.json'))['failures']) == 10
    with pytest.raises(ValueError, match='Ten failed'):
        campaign.start_revision(path, authorization='开始下一版', reason='仍不能跳过失败锁')
    folder, manifest, record = candidate(path, 13)
    with pytest.raises(ValueError, match='Ten failed'):
        campaign.reserve(folder, manifest, record)


def test_next_explicit_series_retains_failures_and_cannot_reuse_previous_approval(old_campaign):
    path, _, _ = old_campaign
    first = begin(old_campaign)
    folder, manifest, record = candidate(path, 6)
    campaign.reserve(folder, manifest, record)
    campaign.review(folder, 'S01', generated_review(folder, record, False))
    second = campaign.start_revision(path, authorization='用户要求新的完整版本', reason='重新制作全部镜头')
    assert second['series_id'] != first['series_id'] and second['failed_outputs'] == 4
    new_folder, new_manifest, new_record = candidate(path, 7)
    campaign.reserve(new_folder, new_manifest, new_record)
    assert campaign.read(path)['attempts'][-1]['series_id'] == second['series_id']


def test_superseded_pending_review_cannot_later_be_marked_passed_in_active_series(old_campaign):
    path, folder, _ = old_campaign
    begin(old_campaign)
    before = path.read_bytes()
    record = campaign.read(folder / 'S02.json')
    full_review = generated_review(folder, record, True)
    with pytest.raises(ValueError, match='older.*series|superseded'):
        campaign.review(folder, 'S02', full_review)
    assert path.read_bytes() == before


def test_empty_authorization_and_recorded_failure_total_cannot_reset_ledger(old_campaign):
    path, _, pending_id = old_campaign
    before = path.read_bytes()
    with pytest.raises(ValueError, match='authorization'):
        campaign.start_revision(path, authorization='', reason='新版本', supersede_attempt_ids=(pending_id,))
    assert path.read_bytes() == before
    data = campaign.read(path)
    data['failed_outputs'] = 10
    campaign.write(path, data)
    with pytest.raises(ValueError, match='Ten failed'):
        begin(old_campaign)
    assert campaign.read(path)['failed_outputs'] == 10
