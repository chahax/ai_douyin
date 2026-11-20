"""Explicit CPU subtitle postprocessing for an independently bound H3 video.

Canary and full are separate actions. Original media and unknown/partial outputs
are preserved. Detection is a white-glyph heuristic, not OCR or a quality pass.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import repair_h3_s02_subtitles_cpu_v1 as pixel
from qa_h3_baseline_two_rounds_v38 import bind, freeze, read, require, extract_batch, inspect_clock
from qa_h3_reference_full_minute_cpu import probe

WEIGHT_SHA = '344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9'
WEIGHT_BYTES = 205669692
WIDTH, HEIGHT, FPS = 736, 1312, 24


def setup(source, expected_sha, run, weights, detector_config):
    source, run, weights = [Path(p).resolve() for p in (source, run, weights)]
    require(source != run and not source.is_relative_to(run), 'isolated_output_cannot_contain_source')
    require(re.fullmatch('[0-9a-f]{64}', expected_sha) and bind(source)['sha256'] == expected_sha,
            'explicit_source_SHA_mismatch')
    require(weights.stat().st_size == WEIGHT_BYTES and bind(weights)['sha256'] == WEIGHT_SHA,
            'approved_complete_LaMa_weight_SHA_required')
    cfg = pixel.config_file(detector_config)
    metadata = probe(source)
    video = [s for s in metadata['streams'] if s['codec_type'] == 'video']
    audio = [s for s in metadata['streams'] if s['codec_type'] == 'audio']
    require(len(video) == len(audio) == 1 and audio[0]['codec_name'] == 'aac', 'single_video_and_AAC_required')
    v = video[0]
    require((v['width'], v['height'], v['r_frame_rate']) == (WIDTH, HEIGHT, '24/1'), 'supported_736x1312_24fps_required')
    count = int(v['nb_read_frames'])
    require(count >= 8, 'at_least_eight_decoded_frames_required')
    inspect_clock(source, count)
    config = dict(schema='native_subtitle_CPU_config/v1', source=bind(source), weights=bind(weights),
        weights_bytes=WEIGHT_BYTES, detector=cfg, width=WIDTH, height=HEIGHT, fps=FPS, frames=count,
        method='lama', code=bind(__file__), pixel_helpers=bind(pixel.__file__),
        postprocessing=True, temporal_consistency_guaranteed=False, new_native_generation=False)
    freeze(run / 'CONFIG.json', config)
    freeze(run / 'SOURCE_PROBE.json', metadata)
    return run, config


def validate_canary(run, config):
    path = run / 'CANARY.json'
    require(path.is_file(), 'explicit_canary_required_before_full')
    value = read(path)
    require(value['config'] == bind(run / 'CONFIG.json') and value['source'] == config['source'],
            'canary_source_config_or_code_changed')
    for item in value['artifacts']:
        require(bind(item['path']) == item, 'canary_artifact_changed')
    require(len(value['rows']) == 8 and value['all_mask_outside_diff_before_encode_zero'] is True,
            'complete_eight_frame_canary_required')
    return value


def canary(run, config, infer):
    if (run / 'CANARY.json').exists():
        return validate_canary(run, config)
    indices = sorted({round((config['frames'] - 1) * i / 7) for i in range(8)})
    frames = extract_batch(config['source']['path'], indices, run / 'source_frames')
    rows, artifacts, boards = [], [], []
    for index in indices:
        folder = run / 'canary' / f'n{index:04d}'
        folder.mkdir(parents=True, exist_ok=True)
        with Image.open(frames[index]['path']) as im:
            before = np.asarray(im.convert('RGB'))
        after, mask, stats = pixel.process(before, config['detector'], infer)
        for name, pixels in [('before', before), ('after', after), ('mask', mask)]:
            target = folder / (name + '.png')
            require(not target.exists(), 'unreceipted_canary_output_preserved')
            Image.fromarray(pixels).save(target)
            artifacts.append(bind(target))
        board = folder / 'BEFORE_AFTER_MASK.jpg'
        require(not board.exists(), 'unreceipted_canary_board_preserved')
        pixel.panel(before, after, mask, config['detector'], f'{index/24:.3f}s').save(board, quality=96)
        boards.append(bind(board)); artifacts.append(bind(board))
        rows.append(dict(frame=index, stats=stats))
    require(bind(config['source']['path']) == config['source'], 'source_changed_during_canary')
    value = dict(schema='native_subtitle_CPU_canary/v1', config=bind(run/'CONFIG.json'), source=config['source'],
        rows=rows, boards=boards, artifacts=artifacts, content_approved=False,
        all_mask_outside_diff_before_encode_zero=True, full_video_processed=False)
    freeze(run / 'CANARY.json', value)
    return value


def commands(source, partial, count):
    decoder = ['ffmpeg','-nostdin','-v','error','-hwaccel','none','-threads','2','-i',str(source),
               '-map','0:v:0','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    encoder = ['ffmpeg','-nostdin','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24',
        '-s','736x1312','-r','24','-i','pipe:0','-i',str(source),'-map','0:v:0','-map','1:a:0',
        '-c:v','libx264','-preset','medium','-crf','18','-threads','2','-pix_fmt','yuv420p',
        '-c:a','copy','-frames:v',str(count),'-fps_mode','cfr','-movflags','+faststart',str(partial)]
    return decoder, encoder


def full(run, config, infer):
    validate_canary(run, config)
    output, partial = run/'SUBTITLE_REPAIRED_CPU_POSTPROCESSED.mp4', run/'FULL.partial.mp4'
    receipt = run/'FULL_RESULT.json'
    if receipt.exists():
        value = read(receipt)
        require(value['config'] == bind(run/'CONFIG.json') and bind(output) == value['file'], 'saved_processed_result_changed')
        return value
    require(not output.exists() and not partial.exists(), 'unreceipted_full_output_preserved')
    source, count = config['source']['path'], config['frames']
    before_audio = pixel.audio_packets(source)
    freeze(run/'SOURCE_AUDIO_PACKETS.json', before_audio)
    decoder_cmd, encoder_cmd = commands(source, partial, count)
    freeze(run/'FULL_COMMANDS.json', dict(decoder=decoder_cmd, encoder=encoder_cmd))
    stats = []
    with (run/'decoder.stderr.log').open('xb') as dl, (run/'encoder.stderr.log').open('xb') as el:
        decoder = encoder = None
        try:
            decoder = subprocess.Popen(decoder_cmd, stdout=subprocess.PIPE, stderr=dl)
            encoder = subprocess.Popen(encoder_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=el)
            for index in range(count):
                raw = decoder.stdout.read(WIDTH*HEIGHT*3)
                require(len(raw) == WIDTH*HEIGHT*3, 'decoded_frame_count_changed')
                after, _, row = pixel.process(np.frombuffer(raw,np.uint8).reshape(HEIGHT,WIDTH,3), config['detector'], infer)
                encoder.stdin.write(after.tobytes()); stats.append(dict(frame=index, **row))
            require(not decoder.stdout.read(1), 'extra_decoded_frames')
            encoder.stdin.close()
            require(decoder.wait(timeout=180) == encoder.wait(timeout=180) == 0, 'CPU_decode_encode_failed')
        finally:
            for process in (decoder, encoder):
                if process is not None and process.poll() is None:
                    process.terminate(); process.wait(timeout=30)
    geometry, metadata = inspect_clock(partial, count)
    after_audio = pixel.audio_packets(partial)
    freeze(run/'OUTPUT_PROBE.json', metadata); freeze(run/'OUTPUT_AUDIO_PACKETS.json', after_audio)
    require(before_audio == after_audio, 'original_AAC_packet_hash_or_PTS_changed')
    require(bind(source) == config['source'], 'source_changed_during_full')
    partial.rename(output)
    value = dict(schema='native_subtitle_CPU_processed/v1', file=bind(output), source=config['source'],
        config=bind(run/'CONFIG.json'), canary=bind(run/'CANARY.json'), method='lama', clock=geometry,
        source_frames=count, processed_frames=len(stats), masked_frames=sum(s['mask_pixels'] > 0 for s in stats),
        frame_stats=stats, original_AAC_stream_copy=True, audio_packet_identity_verified=True,
        audio_packet_manifest_sha256=before_audio['packet_manifest_sha256'],
        all_mask_outside_diff_before_encode_zero=True, lossy_reencode_can_change_pixels_outside_mask=True,
        spatial_upscaling=False, temporal_consistency_guaranteed=False, subtitle_absence_verified=False,
        content_approved=False, new_native_generation=False)
    freeze(receipt, value)
    return value


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['canary','full'])
    p.add_argument('--source', type=Path, required=True); p.add_argument('--expected-sha', required=True)
    p.add_argument('--run', type=Path, required=True); p.add_argument('--method', choices=['lama'], default='lama')
    p.add_argument('--weights', type=Path, required=True); p.add_argument('--detector-config', type=Path, required=True)
    args = p.parse_args(argv)
    run, config = setup(args.source, args.expected_sha, args.run, args.weights, args.detector_config)
    if args.action == 'canary' and (run/'CANARY.json').exists():
        print(json.dumps(validate_canary(run, config), ensure_ascii=False)); return 0
    if args.action == 'full':
        validate_canary(run, config)  # Fail before loading weights if the canary is absent/stale.
        if (run/'FULL_RESULT.json').exists():
            print(json.dumps(full(run, config, None), ensure_ascii=False)); return 0
    infer = pixel.CpuLama(args.weights, 2)
    value = canary(run, config, infer) if args.action == 'canary' else full(run, config, infer)
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
