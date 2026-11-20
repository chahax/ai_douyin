from pathlib import Path
import subprocess

import numpy as np
import pytest
from PIL import Image

from scripts.run_script_video import read, review_packet, sha, speed_preview, write
from test_script_video_review_packet import source_video


def test_speed_preview_preserves_pitch_frames_source_and_review_gate(tmp_path, source_video):
    script = tmp_path/'locked_script.json'
    write(script, {'shots': [{'shot_id': 'S01'}]})
    manifest = {'shots': ['S01'], 'script_sha256': sha(script),
                'review_result': 'pending', 'current_segment_review': 'pending'}
    write(tmp_path/'production.json', manifest)
    receipt = {'status': 'downloaded', 'local_video': str(source_video),
               'video_sha256': sha(source_video), 'last_frame': 'original_platform_tail.png'}
    write(tmp_path/'S01.json', receipt)
    original_receipt = (tmp_path/'S01.json').read_bytes()
    result = speed_preview(tmp_path, 'S01', 1.08, '用户要求稍快一点')
    output = Path(result['preview'])
    audit = read(output.with_suffix('.json'))
    assert abs(result['duration']-2/1.08) < .05
    assert audit['video_frame_count'] == 20
    assert audit['source_sha256'] == sha(source_video)
    assert (tmp_path/'S01.json').read_bytes() == original_receipt
    assert read(tmp_path/'production.json')['current_segment_review'] == 'pending'
    assert result['status'] == 'awaiting_human_review' and result['video_generation_submitted'] is False
    assert audit['technical_status'] == 'succeeded'
    assert audit['content_status'] == 'awaiting_human_review'
    assert 'review_packet' not in result and 'review_packet' not in audit
    assert not (tmp_path/'review_packets').exists()
    packet_result = review_packet(tmp_path, video_path=output)
    packet = read(Path(packet_result['review_packet']))
    assert packet['last_frame_index'] == 19
    assert abs(packet['frames'][-1]['time_seconds']-1.9/1.08) < .001
    packet_dir = Path(packet_result['review_packet']).parent
    with Image.open(packet_dir/packet['frames'][0]['file']) as picture:
        assert picture.getpixel((160,240))[0] > 200
    with Image.open(packet_dir/packet['frames'][-1]['file']) as picture:
        assert picture.getpixel((160,240))[2] > 200
    samples = np.frombuffer(subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
        str(output), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']), dtype='<f4')
    middle = samples[3200:-3200]
    peak = np.fft.rfftfreq(len(middle), 1/16000)[np.argmax(np.abs(np.fft.rfft(middle)))]
    assert abs(peak-440) < 3  # Plain playback resampling would raise this to 475 Hz.
    template = packet_dir/'review.template.json'
    assert all(v is None for v in read(template)['checks'].values())
    template.write_text('{"decision":"pending","notes":"manual observation"}')
    digest = sha(output)
    assert speed_preview(tmp_path, 'S01', 1.08, '再次查看')['preview'] == str(output)
    assert sha(output) == digest and read(template)['notes'] == 'manual observation'
    output.write_bytes(output.read_bytes()+b'changed')
    with pytest.raises(ValueError, match='Existing preview changed'):
        speed_preview(tmp_path, 'S01', 1.08, '再次查看')


@pytest.mark.parametrize('speed', [1, 0, -1, 1.3, float('nan'), float('inf')])
def test_speed_preview_rejects_invalid_speed_before_rendering(tmp_path, speed):
    with pytest.raises(ValueError, match='Preview speed'):
        speed_preview(tmp_path, 'S01', speed, '稍快一点')


def test_speed_preview_requires_pacing_request(tmp_path):
    with pytest.raises(ValueError, match='user pacing request'):
        speed_preview(tmp_path, 'S01', 1.08, '')


def test_assembly_uses_approved_speed_video_and_its_cut_time(tmp_path, source_video):
    from scripts.run_script_video import merge, assembly_speed_preview
    from src.content_factory.script_video_review import build_review_packet
    script = tmp_path/'locked_script.json'
    write(script, {'shots':[{'shot_id':'S01'},{'shot_id':'S02'}]})
    manifest = {'shots':['S01','S02'],'script_sha256':sha(script)}
    write(tmp_path/'production.json',manifest)
    packet = build_review_packet(tmp_path,source_video,sha(source_video),sha(script))
    for sid in manifest['shots']:
        write(tmp_path/f'{sid}.json', {'shot':sid,'status':'downloaded','local_video':str(source_video),
            'video_sha256':sha(source_video),'actual_duration_seconds':2.,'review_packet':str(packet),
            'campaign_attempt_id':sid})
    preview = speed_preview(tmp_path,'S01',1.08,'faster')
    review_packet(tmp_path, video_path=Path(preview['preview']))
    audit_path = Path(preview['preview']).with_suffix('.json')
    manifest = read(tmp_path/'production.json')
    manifest['campaign_path'] = str(tmp_path/'campaign.json')
    write(tmp_path/'production.json',manifest)
    write(tmp_path/'campaign.json',{'attempts':[
            {'id':'S01','shot':'S01','status':'passed','video_sha256':sha(source_video),
         'delivery_preview':str(audit_path),'delivery_audit_sha256':sha(audit_path),
         'delivery_video_sha256':sha(Path(preview['preview']))},
            {'id':'S02','shot':'S02','status':'passed','video_sha256':sha(source_video)}]})
    result = merge(tmp_path)
    assert abs(float(result['duration'])-(2+preview['duration'])) < .1
    manifest = read(tmp_path/'production.json')
    assert manifest['assembly_inputs'][0]['video'] == preview['preview']
    assert manifest['assembly_inputs'][1]['video'] == str(source_video)
    assert 'merged_review_packet' not in manifest
    packet_result = review_packet(tmp_path)
    packet = read(Path(packet_result['review_packet']))
    assert packet['boundaries'][0]['time'] == preview['duration']
    assert manifest['review_result'] == 'awaiting_human_review'
    before = (tmp_path/'campaign.json').read_bytes()
    faster = assembly_speed_preview(tmp_path,1.05,'用户要求整体再快一点')
    audit = read(Path(faster['video']).with_suffix('.json'))
    assert abs(faster['duration']-(2+preview['duration'])/1.05) < .1
    assert len(faster['cuts']) == 1 and 1.7 < faster['cuts'][0]['time'] < 1.9
    assert audit['video_frames_preserved'] == 40
    assert audit['inputs'][0]['total_speed'] == 1.08*1.05
    assert audit['review_status'] == 'awaiting_human_review'
    assert 'review_packet' not in faster and 'review_packet' not in audit
    assert (tmp_path/'campaign.json').read_bytes() == before
    tail_review = tmp_path/'tail_review.json'
    write(tail_review, {'source_sha256':sha(source_video),'speech_end_seconds':1.2,
        'visual_tail_checked':True,'speech_end_method':'local_audio_energy_and_asr'})
    plan_path = tmp_path/'rhythm.json'
    plan = {'schema':'script_video_rhythm_plan/v1','output_label':'rhythm_test',
        'description':'Remove checked tail and match the second clip tempo',
        'baseline_report':str(Path(faster['video']).with_suffix('.json')),
        'baseline_report_sha256':sha(Path(faster['video']).with_suffix('.json')),
        'edits':{'S02':{'video_sha256':sha(source_video),'additional_speed':.95,
            'keep_end_seconds':1.25,'tail_review':str(tail_review),
            'tail_review_sha256':sha(tail_review),'reason':'User flagged idle tail and inconsistent tempo'}}}
    write(plan_path,plan)
    with pytest.raises(ValueError, match='150 ms margin'):
        assembly_speed_preview(tmp_path,1.05,'Fix reported timing',plan_path)
    assert not (tmp_path/'whole_video.rhythm_test.mp4').exists()
    plan['edits']['S02']['keep_end_seconds'] = 1.5
    write(plan_path,plan)
    revised = assembly_speed_preview(tmp_path,1.05,'Fix reported timing',plan_path)
    audit = read(Path(revised['video']).with_suffix('.json'))
    assert audit['video_frames_preserved'] == 35
    assert audit['intentionally_removed_tail_frames'] == 5
    assert audit['inputs'][0]['additional_speed'] == 1.05
    assert audit['inputs'][1]['additional_speed'] == .95
    assert abs(revised['duration']-(preview['duration']/1.05+1.5/.95)) < .1
    assert revised['cuts'] == faster['cuts']
    assert audit['review_status'] == 'awaiting_human_review' and audit['content_trimmed'] is True
    assert (tmp_path/'campaign.json').read_bytes() == before
