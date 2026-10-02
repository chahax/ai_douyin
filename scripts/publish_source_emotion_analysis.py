"""Index completed local observations without certifying semantic approval."""
import argparse
import hashlib
import json
import sys
import re
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.trend_intelligence.emotion_evidence import delivery_projection


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def coverage_limitations(source):
    """Coverage is a media sampling claim, never an emotion-review result."""
    duration = float(source['source_duration_seconds'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid source duration')
    spans = source['windows']
    if not spans:
        raise ValueError('no continuous windows observed')
    previous_end = 0.0
    for span in spans:
        start, end = float(span['source_start']), float(span['source_end'])
        if (not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end > duration + 1e-6
                or start < previous_end - 1e-6):
            raise ValueError('Invalid or overlapping source windows')
        if source['coverage'] == 'full' and abs(start - previous_end) > 1e-6:
            raise ValueError('Full coverage has an unobserved gap')
        previous_end = end
    if source['coverage'] == 'full':
        if abs(previous_end - duration) > 1e-6:
            raise ValueError('Full coverage misses the source ending')
        coverage = ('全片原声音轨按连续窗口覆盖；画面仅在联合音画任务中抽帧观察，不能称为逐帧完整审核。'
                    '覆盖完整不代表语气、人物归属或转折已确认，也不能据此确定全片情绪峰值、占比或观众反应。')
    elif source['coverage'] == 'sampled_begin_middle_end':
        coverage = ('旧版仅取开头、中部和末尾各8秒，未覆盖部分未知；'
                    '不能确定全片峰值与情绪占比。')
    else:
        raise ValueError('Unknown source coverage')
    return ['本地模型对连续片段的音画观察，未经独立逐项确认；可能误认情绪与说话者。',
        coverage,
        '分析窗口边界及旧版样本拼接点不等于原片剪辑点；原片时间映射为提取区间，重编码存在帧取整与音频填充误差。',
        '演员的声音和表演不是观众情绪测量；动机、观众反应与表达机制必须分别标注推断或待复核。',
        '人物对抗/单人讲解类型须以独立审核的来源表达分析为准，不由语气激烈推断。',
        '点赞是同批展示指标；不能由相关性断言情绪导致高点赞。']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--index', type=Path, default=ROOT/'data/source_emotion/index.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    index = json.loads(args.index.read_text(encoding='utf-8')) if args.index.exists() else {
        'schema':'source_emotion_index/v1', 'sources':{}}
    for source in manifest['sources']:
        limitations = coverage_limitations(source)
        window_results = []
        for window, observation_path in zip(source['windows'], source['window_observation_paths'], strict=True):
            path = Path(observation_path)
            result = json.loads(path.read_text(encoding='utf-8'))
            sample = Path(result['video'])
            if window.get('clip_path') and (
                    sample.resolve() != Path(window['clip_path']).resolve()
                    or sha(sample) != window['clip_sha256']):
                raise ValueError('Observation does not match its prepared source window')
            if (result['source_sha256'] != sha(sample)
                    or not (result['use_audio_in_video'] or result['audio_only'])
                    or not result['response'].strip()):
                raise ValueError('Missing or mismatched joint AV observation')
            window_results.append(dict(window, observation=delivery_projection(result['response']),
                observation_scope='audio_only' if result['audio_only'] else 'audio_and_sampled_video',
                observation_path=str(path.resolve()), observation_sha256=sha(path),
                sample_path=str(sample.resolve()), sample_sha256=sha(sample)))
        if not window_results:
            raise ValueError('no continuous windows observed')
        transcript_path = Path(source['transcript_path'])
        transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
        if transcript.get('provenance', {}).get('source_video_sha256') != source['source_video_sha256']:
            raise ValueError('transcript source mismatch')
        count = sum(len(re.sub(r'[^\w]', '', row.get('text',''))) for row in transcript['result'])
        report = {key:source[key] for key in ('source_id','title','metric_kind','metric_value',
            'source_video_sha256','source_duration_seconds','coverage')}
        report.update(schema='source_emotion_analysis/v1', status='model_observed_unverified',
            windows=window_results,
            unresolved_windows=[i for i, window in enumerate(window_results)
                                if window['observation'] == '没有可单独引用的表达观察，待复核。'],
            observation='\n'.join(f"原片 {w['source_start']:.2f}—{w['source_end']:.2f} 秒：{w['observation']}" for w in window_results),
            transcript_path=str(transcript_path.resolve()), transcript_sha256=sha(transcript_path),
            asr_density={'recognized_characters':count, 'characters_per_video_second':count/source['source_duration_seconds'],
                'scope':'全片ASR字数/全片时长，非精确发音速度；含转写误差与片内停顿，不据此判断情绪'},
            analyzed_at_bjt=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            limitations=limitations)
        for key in ('sampling_mode', 'window_seconds', 'audio_coverage_seconds',
                    'preview_has_artificial_joins', 'artificial_preview_joins', 'mapping_limitation'):
            if key in source:
                report[key] = source[key]
        artifact = path.parent/'emotion_analysis.json'
        if artifact.exists():
            raise ValueError('Analysis artifact already exists; preserve it and use a new preparation')
        artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        index['sources'][source['source_id']] = {'source_video_sha256':source['source_video_sha256'],
            'artifact_path':str(artifact.resolve()), 'artifact_sha256':sha(artifact)}
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Indexed {len(manifest["sources"])} unverified model observations')


if __name__ == '__main__':
    main()
