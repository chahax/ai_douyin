"""Synthetic evidence fixtures only; never used by production providers."""
import json
from dataclasses import replace
from pathlib import Path

from src.trend_intelligence.media_evidence import file_sha256


def complete_media_analysis(analysis, folder, *, mode='prop_demonstration'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in ['source.mp4', 'audio.wav', 'visual.json', 'transcript.json', 'frames.json']:
        path = folder/name
        path.write_text(json.dumps({'test_fixture_only': True, 'item_id': analysis.item_id,
                                    'kind': name}), encoding='utf-8')
        files[name] = {'path':str(path.resolve()), 'sha':file_sha256(path)}
    frames = []
    for i,second in enumerate([0.,1.,3.,5.9]):
        frame = folder/f'frame_{i}.jpg'
        frame.write_bytes(f'test_frame_{analysis.item_id}_{i}'.encode())
        frames.append({'id':f'visual-{i+1}','path':str(frame.resolve()),
                       'sha256':file_sha256(frame),'time_seconds':second})
    manifest=folder/'frames.json'
    manifest.write_text(json.dumps({'schema':'local_video_frame_manifest/v2',
        'source_video_sha256':files['source.mp4']['sha'],'duration_seconds':6.,'frames':frames}),encoding='utf-8')
    files['frames.json']['sha']=file_sha256(manifest)
    visual_text = analysis.visual_summary or '办公室里当事人与律师对照并展示合同，律师递出一页标记材料，表情冷静'
    asr_text = '这张通知和合同写的期限不一样，请核对原件。'
    evidence = [{'id':frame['id'],'channel':'visual','start_seconds':frame['time_seconds'],
                 'end_seconds':frame['time_seconds'],'text':visual_text} for frame in frames]
    evidence.append({'id':'A0001','channel':'asr','start_seconds':1.,'end_seconds':3.,'text':asr_text})
    claim = lambda text, ids: {'text':text, 'evidence_ids':ids}
    expression = {'schema':'video_expression_analysis/v1',
        'core_message':claim('通知与合同期限不一致，应对照原件核对。',['visual-1','A0001']),
        'expression_modes':[{'mode':mode,'evidence_ids':['visual-1','A0001']}],
        'visual_expression':[claim('展示实物，指向两份材料的差异。',['visual-1'])],
        'audio_expression':[claim('现场对白指出两份材料不同。',['A0001'])],
        'conflict':{'status':'not_observed'},'evidence':evidence,'uncertainties':[]}
    payloads = {'visual.json': {'schema':'local_qwen_frame_analysis/v2',
        'answer':{'expression_analysis':expression},
        'batches':[{'observations':[{'frame_id':frame['id'],'event':visual_text} for frame in frames]}]},
        'transcript.json': {'result':[{'sentence_info':[{'start':1000,'end':3000,'text':asr_text}]}]}}
    for name,payload in payloads.items():
        Path(files[name]['path']).write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        files[name]['sha']=file_sha256(files[name]['path'])
    media = {'schema':'local_media_evidence/v1',
        'source_video_path':files['source.mp4']['path'],'source_video_sha256':files['source.mp4']['sha'],
        'duration_seconds':6.,
        'visual':{'status':'completed','artifact_path':files['visual.json']['path'],
            'artifact_sha256':files['visual.json']['sha'],'frame_manifest_path':files['frames.json']['path'],
            'frame_manifest_sha256':files['frames.json']['sha'],'sample_times_seconds':[0.,1.,3.,5.9],
            'total_sampled_frame_count':4,'analyzed_frame_count':4,'coverage_start_seconds':0.,'coverage_end_seconds':5.9},
        'audio':{'status':'transcribed','artifact_path':files['transcript.json']['path'],
            'artifact_sha256':files['transcript.json']['sha'],'audio_path':files['audio.wav']['path'],
            'audio_sha256':files['audio.wav']['sha'],'coverage_start_seconds':0.,'coverage_end_seconds':6.,
            'prosody_status':'not_analyzed','speaker_identity_status':'not_analyzed','lip_sync_status':'not_analyzed'}}
    return replace(analysis,status='completed',media_access_mode='local_media_authorized',
        provider_id='synthetic_test_provider',provider_version='test-v2',duration_seconds=6.,
        expression_analysis=expression,media_evidence=media)
