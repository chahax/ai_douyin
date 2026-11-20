import hashlib
import json

from src.trend_intelligence.emotion_evidence import source_emotion, delivery_projection
from scripts.prepare_source_emotion_analysis import windows


def test_sampling_does_not_call_long_video_fully_observed():
    assert windows(15) == [(0, 15)]
    assert windows(1800) == [(0, 8), (896, 904), (1792, 1800)]


def test_projection_does_not_promote_model_legal_quote_to_source_fact():
    result = delivery_projection('他用坚定语气说：“下班出了事就得按工伤算。”。法律一定保护他。说话节奏急切。')
    assert '下班' not in result and '工伤' not in result and '法律' not in result
    assert '节奏急切' in result


def test_missing_and_stale_original_are_not_emotion_evidence(tmp_path):
    index = tmp_path / 'index.json'
    assert source_emotion('x', 'a', index_path=index)['status'] == 'not_analyzed'
    index.write_text(json.dumps({'sources': {'x': {'source_video_sha256': 'b'}}}))
    assert source_emotion('x', 'a', index_path=index)['status'] == 'not_analyzed'


def test_underlying_observation_tampering_is_not_silently_used(tmp_path):
    observation, sample = tmp_path/'observation.json', tmp_path/'sample.mp4'
    observation.write_bytes(b'original'); sample.write_bytes(b'sample')
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = tmp_path/'emotion.json'
    artifact.write_text(json.dumps({'schema':'source_emotion_analysis/v1', 'source_id':'x',
        'source_video_sha256':'a', 'status':'model_observed_unverified',
        'coverage':'sampled_begin_middle_end', 'windows':[{
            'observation_path':str(observation), 'sample_path':str(sample),
            'observation_sha256':sha(observation), 'sample_sha256':sha(sample)}], 'source_duration_seconds':90,
        'observation':'sampled opinion', 'limitations':['not independently verified'],
        'transcript_path':str(observation), 'transcript_sha256':sha(observation), 'asr_density':{},
        'observation_path':str(observation), 'sample_path':str(sample),
        'observation_sha256':sha(observation), 'sample_sha256':sha(sample)}))
    index = tmp_path/'index.json'
    index.write_text(json.dumps({'sources':{'x':{'source_video_sha256':'a',
        'artifact_path':str(artifact),'artifact_sha256':sha(artifact)}}}))
    result = source_emotion('x', 'a', index_path=index)
    assert result['status'] == 'model_observed_unverified'
    assert result['coverage'] == 'sampled_begin_middle_end'
    observation.write_bytes(b'replaced')
    assert source_emotion('x', 'a', index_path=index)['status'] == 'unavailable'
