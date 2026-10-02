from pathlib import Path

import pytest

from src.content_factory import video_campaign as campaign
from src.content_factory.script_video_review import REVIEW_CHECKS, file_sha


def setup_campaign(tmp_path):
    path = tmp_path/'campaign.json'
    campaign.write(path, {'schema':'sequential_video_campaign/v1', 'max_failed_outputs':10,
        'authorization':'test authorization', 'provider':'ark_api', 'model':'test-model',
        'attempts':[], 'failed_outputs':0, 'status':'prepared'})
    return path


def candidate(path, number, shot='S01'):
    folder = path.parent/f'run_{number}'
    folder.mkdir()
    manifest = {'shots':['S01','S02'], 'api_model':'test-model', 'provider':'ark_api',
                'script_sha256':f'script-{number}'}
    campaign.write(folder/'production.json', manifest)
    campaign.attach(folder, path)
    record = {'shot':shot, 'script_sha256':manifest['script_sha256'], 'prompt_sha256':f'prompt-{number}'}
    return folder, campaign.read(folder/'production.json'), record


def generated_review(folder, record, passed):
    video = folder/f"{record['shot']}.mp4"
    video.write_bytes(f"test media fixture {folder.name}".encode())
    evidence = folder/'observed.txt'
    evidence.write_text('test evidence')
    packet = folder/'packet.json'
    campaign.write(packet, {'source_sha256':file_sha(video),
                           'evidence':[{'file':evidence.name, 'sha256':file_sha(evidence)}]})
    record.update(status='downloaded', local_video=str(video), video_sha256=file_sha(video),
                  review_packet=str(packet), actual_duration_seconds=6., last_frame_sha256='original-tail')
    campaign.write(folder/f"{record['shot']}.json", record)
    checks = {key:True for key in REVIEW_CHECKS}
    checks['speaker_voice'] = passed
    result = {'source_sha256':record['video_sha256'], 'script_sha256':record['script_sha256'],
              'decision':'passed' if passed else 'failed', 'checks':checks,
              'observations':[{'check':key, 'time_seconds':1., 'notes':'fixture inspection',
                               'evidence':[evidence.name]} for key in REVIEW_CHECKS]}
    review = folder/'review.json'
    campaign.write(review, result)
    return review


def test_serial_gate_requires_full_review_and_adjacent_tail(tmp_path):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    next_folder, next_manifest, next_record = candidate(path, 2, 'S02')
    with pytest.raises(ValueError, match='outstanding'):
        campaign.reserve(next_folder, next_manifest, next_record)
    review = generated_review(folder, record, True)
    broken = campaign.read(review)
    broken['checks']['lip_sync'] = None
    campaign.write(review, broken)
    with pytest.raises(ValueError, match='explicit verdicts'):
        campaign.review(folder, 'S01', review)
    broken['checks']['lip_sync'] = True
    campaign.write(review, broken)
    campaign.review(folder, 'S01', review)
    with pytest.raises(ValueError, match='preceding'):
        campaign.reserve(next_folder, next_manifest, next_record)
    next_record['first_frame_sha256'] = 'original-tail'
    campaign.reserve(next_folder, next_manifest, next_record)
    assert len(campaign.read(path)['attempts']) == 2
    with pytest.raises(ValueError, match='not passed'):
        campaign.require_approved_segments(folder, manifest)


def test_ten_failed_outputs_stop_all_later_submissions_without_double_count(tmp_path):
    path = setup_campaign(tmp_path)
    for number in range(1, 11):
        folder, manifest, record = candidate(path, number)
        campaign.reserve(folder, manifest, record)
        review = generated_review(folder, record, False)
        assert campaign.review(folder, 'S01', review)['failed_outputs'] == number
        assert campaign.review(folder, 'S01', review)['failed_outputs'] == number
    data = campaign.read(path)
    assert data['status'] == 'paused_for_human_review'
    assert len(campaign.read(path.with_name('HUMAN_REVIEW_REQUIRED.json'))['failures']) == 10
    folder, manifest, record = candidate(path, 11)
    with pytest.raises(ValueError, match='Ten failed'):
        campaign.reserve(folder, manifest, record)
    assert len(campaign.read(path)['attempts']) == 10


def test_failure_requires_upstream_revision_and_tampered_evidence_is_rejected(tmp_path):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    review = generated_review(folder, record, False)
    (folder/'observed.txt').write_text('tampered')
    with pytest.raises(ValueError, match='modified'):
        campaign.review(folder, 'S01', review)
    (folder/'observed.txt').write_text('test evidence')
    campaign.review(folder, 'S01', review)
    other, other_manifest, other_record = candidate(path, 2)
    other_record['script_sha256'] = record['script_sha256']
    with pytest.raises(ValueError, match='upstream script'):
        campaign.reserve(other, other_manifest, other_record)
    other_record['script_sha256'] = 'only-timestamp-changed'
    other_record['prompt_sha256'] = record['prompt_sha256']
    with pytest.raises(ValueError, match='upstream script'):
        campaign.reserve(other, other_manifest, other_record)


def test_rejected_request_does_not_count_as_failed_generated_output(tmp_path):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    record.update(status='request_rejected', provider_error_code='ModelNotOpen')
    campaign.reconcile_rejection(manifest, record)
    assert campaign.read(path)['failed_outputs'] == 0
    other, other_manifest, other_record = candidate(path, 2)
    campaign.reserve(other, other_manifest, other_record)


def test_unresolved_research_prerequisite_prevents_reservation(tmp_path):
    path = setup_campaign(tmp_path)
    data = campaign.read(path)
    data['holds'] = ['fresh_collection_verification']
    campaign.write(path, data)
    folder, manifest, record = candidate(path, 1)
    with pytest.raises(ValueError, match='prerequisites'):
        campaign.reserve(folder, manifest, record)
    assert campaign.read(path)['attempts'] == []


def test_partial_review_remains_pending_and_cannot_release_next_segment(tmp_path):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    review_path = generated_review(folder, record, True)
    full_review = campaign.read(review_path)
    partial = campaign.read(review_path)
    partial['checks']['speaker_voice'] = None
    partial['checks']['lip_sync'] = None
    partial['decision'] = 'pending'
    partial['observations'] = [o for o in partial['observations'] if partial['checks'][o['check']] is not None]
    campaign.write(review_path, partial)
    assert campaign.review(folder, 'S01', review_path) == {'decision':'pending', 'failed_outputs':0}
    assert campaign.read(path)['attempts'][0]['uninspected_checks'] == ['speaker_voice', 'lip_sync']
    next_folder, next_manifest, next_record = candidate(path, 2, 'S02')
    next_record['first_frame_sha256'] = 'original-tail'
    with pytest.raises(ValueError, match='outstanding'):
        campaign.reserve(next_folder, next_manifest, next_record)
    campaign.write(review_path, full_review)
    assert campaign.review(folder, 'S01', review_path)['decision'] == 'passed'
    assert len(list((folder/'quality_review_history/S01').glob('*.json'))) == 2
    campaign.reserve(next_folder, next_manifest, next_record)


def test_observed_visual_failure_can_return_to_revision_without_unperformed_audio_claims(tmp_path):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    review_path = generated_review(folder, record, True)
    result = campaign.read(review_path)
    result['checks'] = {key:False if key == 'spatial_layout' else None for key in REVIEW_CHECKS}
    result['observations'] = [o for o in result['observations'] if o['check'] == 'spatial_layout']
    result['decision'] = 'failed'
    campaign.write(review_path, result)
    assert campaign.review(folder, 'S01', review_path)['failed_outputs'] == 1
    attempt = campaign.read(path)['attempts'][0]
    assert attempt['failed_checks'] == ['spatial_layout']
    assert 'speaker_voice' in attempt['uninspected_checks']
    revised, revised_manifest, revised_record = candidate(path, 2)
    campaign.reserve(revised, revised_manifest, revised_record)


def test_approved_speed_delivery_keeps_raw_provenance_and_releases_only_original_tail(tmp_path):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    review_path = generated_review(folder, record, True)
    original_receipt = (folder/'S01.json').read_bytes()
    preview = folder/'S01.speed_1p08.mp4'
    preview.write_bytes(b'different delivery fixture')
    packet = folder/'delivery.packet.json'
    campaign.write(packet, {'source_sha256':file_sha(preview),
        'evidence':[{'file':'observed.txt','sha256':file_sha(folder/'observed.txt')}]})
    audit_path = folder/'S01.speed_1p08.json'
    campaign.write(audit_path, {'schema':'script_video_speed_preview/v1',
        'source_sha256':record['video_sha256'],'script_sha256':manifest['script_sha256'],
        'content_trimmed':False,'video':str(preview),'video_sha256':file_sha(preview),
        'review_packet':str(packet),'actual_duration_seconds':5.555,'speed':1.08})
    manifest['speed_previews'] = {'S01':{'1.08':str(audit_path)}}
    campaign.write(folder/'production.json',manifest)
    result = campaign.read(review_path)
    result.update(source_sha256=file_sha(preview),source_original_sha256=record['video_sha256'],
                  delivery_preview=str(audit_path))
    campaign.write(review_path,result)
    campaign.review(folder,'S01',review_path)
    approved = campaign.read(path)['attempts'][0]
    assert approved['video_sha256'] == record['video_sha256']
    assert approved['delivery_video_sha256'] == file_sha(preview)
    assert approved['original_speed_audio_approved'] is False
    assert (folder/'S01.json').read_bytes() == original_receipt
    selected = campaign.delivery_asset(folder,manifest,'S01')
    assert selected['video'] == str(preview) and selected['actual_duration_seconds'] == 5.555
    next_folder, next_manifest, next_record = candidate(path,2,'S02')
    next_record['first_frame_sha256'] = 'derivative-tail'
    with pytest.raises(ValueError,match='preceding'):
        campaign.reserve(next_folder,next_manifest,next_record)
    next_record['first_frame_sha256'] = 'original-tail'
    preview.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='preview or its original source changed'):
        campaign.reserve(next_folder,next_manifest,next_record)
    preview.write_bytes(b'different delivery fixture')
    campaign.reserve(next_folder,next_manifest,next_record)
    assert len(campaign.read(path)['attempts']) == 2

@pytest.mark.parametrize('creative,decision,count', [(False,'failed',1),(True,'pending',0),(None,'pending',0)])
def test_creative_review_does_not_fabricate_audio_approval(tmp_path, creative, decision, count):
    path = setup_campaign(tmp_path)
    folder, manifest, record = candidate(path, 1)
    campaign.reserve(folder, manifest, record)
    review_path = generated_review(folder, record, True)
    result = campaign.read(review_path)
    result['checks']['speaker_voice'] = None
    result['checks']['lip_sync'] = None
    result['observations'] = [o for o in result['observations'] if result['checks'][o['check']] is not None]
    result['creative_checks'] = {'visual_storytelling':creative}
    if creative is not None:
        result['observations'].append({'check':'visual_storytelling','time_seconds':2.,'notes':'Actual artistic finding','evidence':['observed.txt']})
    result['decision'] = decision
    campaign.write(review_path,result)
    assert campaign.review(folder,'S01',review_path) == {'decision':decision,'failed_outputs':count}
    assert campaign.review(folder,'S01',review_path)['failed_outputs'] == count
    attempt = campaign.read(path)['attempts'][0]
    assert 'speaker_voice' in attempt['uninspected_checks']
    assert 'lip_sync' in attempt['uninspected_checks']
    assert ('visual_storytelling' in attempt['failed_checks']) == (creative is False)
    next_folder, next_manifest, next_record = candidate(path,2,'S02')
    with pytest.raises(ValueError):
        campaign.reserve(next_folder,next_manifest,next_record)
