"""Explicit CPU LaMa or Telea postprocessing, preserving original H3 media.

Canary writes eight independent before/after/mask samples. Full is a separate
explicit command after a canary exists. This does not claim temporal coherence
or that every subtitle has been found by a white-component heuristic.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import cv2
import numpy as np
from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from qa_h3_baseline_two_rounds_v38 import bind, digest, freeze, read, require, extract_batch, inspect_clock

PROJECT = SCRIPTS.parent
ROOT_REL = Path('data/video_generation/h3_s02_subtitle_repair_20261110_v1')
SOURCE_REL = Path('data/video_generation/h3_s02_prompt_probe_20261110_v1/shots/S02/artifacts/video_00001_.mp4')
SOURCE_SHA = '5ca5045427d23b3a492dde647d11d67fabe5669a29543fe1429c668494a55079'
CANARY_FRAMES = (0, 60, 120, 180, 240, 276, 288, 361)
DEFAULT = dict(context_y=[832, 1088], search_y=[940, 1016], saturation_max=95,
               value_min=210, component_min_area=7, component_max_area=1200,
               component_width=[3, 58], component_height=[10, 52], top_tolerance=4,
               row_min_components=5, row_min_span=120, tall_component_min=24,
               mask_dilate=4, max_context_mask_fraction=0.20)


def white_pixels(rgb, cfg):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    return (hsv[:, :, 1] <= cfg['saturation_max']) & (hsv[:, :, 2] >= cfg['value_min'])


def detect_mask(rgb, cfg):
    """Mask character-like white components in the top coherent subtitle row."""
    require(rgb.shape == (1312, 736, 3) and rgb.dtype == np.uint8, 'native_RGB_frame_required')
    y0, y1 = cfg['context_y']
    a, b = cfg['search_y']
    raw = white_pixels(rgb[a:b], cfg)
    closed = cv2.morphologyEx(raw.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    candidates = []
    for label, row in enumerate(stats[1:], 1):
        x, y, width, height, area = map(int, row)
        if (cfg['component_min_area'] <= area <= cfg['component_max_area'] and
                cfg['component_width'][0] <= width <= cfg['component_width'][1] and
                cfg['component_height'][0] <= height <= cfg['component_height'][1]):
            candidates.append(dict(label=label, x=x, y=y, w=width, h=height, area=area))
    groups = []
    for row in sorted(candidates, key=lambda r: r['y']):
        if not groups or abs(row['y'] - np.median([r['y'] for r in groups[-1]])) > cfg['top_tolerance']:
            groups.append([row])
        else:
            groups[-1].append(row)
    accepted = []
    for group in groups:
        span = max(r['x'] + r['w'] for r in group) - min(r['x'] for r in group)
        tall = [r for r in group if r['h'] >= cfg['tall_component_min']]
        if len(group) >= cfg['row_min_components'] and span >= cfg['row_min_span'] and len(tall) >= 3:
            accepted.append((group, tall))
    mask = np.zeros((y1 - y0, 736), np.uint8)
    selected, row_box = [], None
    if accepted:
        group, tall = accepted[0]  # Highest coherent row; not a large white garment.
        top = int(np.median([r['y'] for r in group]))
        bottom = top + int(np.median([r['h'] for r in tall]))
        left, right = min(r['x'] for r in group), max(r['x'] + r['w'] for r in group)
        selected = [r for r in candidates if left - 4 <= r['x'] + r['w'] / 2 <= right + 4 and
                    max(0, min(bottom + 2, r['y'] + r['h']) - max(top - 2, r['y'])) >= .6 * r['h']]
        strokes = raw & np.isin(labels, [r['label'] for r in selected])
        mask[a - y0:b - y0] = strokes.astype(np.uint8) * 255
        radius = cfg['mask_dilate']
        if radius:
            mask = cv2.dilate(mask, np.ones((radius * 2 + 1, radius * 2 + 1), np.uint8))
        row_box = [left, a + top, right, a + bottom]
    pixels = int(np.count_nonzero(mask))
    require(pixels <= mask.size * cfg['max_context_mask_fraction'], 'mask_area_guard_exceeded')
    return mask, dict(component_candidates=len(candidates), selected_components=len(selected),
                      selected_row_box=row_box, mask_pixels=pixels, mask_fraction_context=pixels / mask.size,
                      detected_white_stroke_pixels=int(np.count_nonzero(raw)),
                      detector_is_not_OCR=True, subtitle_absence_verified=False)


def masked_restore(rgb, mask, prediction, cfg):
    y0, y1 = cfg['context_y']
    require(mask.shape == (y1 - y0, 736) and prediction.shape == (y1 - y0, 736, 3), 'context_prediction_geometry_changed')
    after = rgb.copy()
    selected = mask > 0
    after[y0:y1][selected] = prediction[selected]
    full_mask = np.zeros(rgb.shape[:2], bool)
    full_mask[y0:y1] = selected
    changed = np.any(after != rgb, axis=2)
    outside = int(np.count_nonzero(changed & ~full_mask))
    require(outside == 0, 'outside_mask_preencode_difference_must_be_zero')
    before_white = white_pixels(rgb[y0:y1], cfg)
    after_white = white_pixels(after[y0:y1], cfg)
    return after, dict(mask_outside_changed_pixels_before_encode=outside,
                       changed_pixels_inside_mask=int(np.count_nonzero(changed & full_mask)),
                       HSV_white_pixels_before_inside_mask=int(np.count_nonzero(before_white & selected)),
                       HSV_white_pixels_after_inside_mask=int(np.count_nonzero(after_white & selected)),
                       metric_is_not_text_recognition=True)


class CpuLama:
    def __init__(self, weights, threads):
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
        import torch
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        self.torch = torch
        self.model = torch.jit.load(str(weights), map_location='cpu').eval()
        require(all(p.device.type == 'cpu' for p in self.model.parameters()), 'CPU_parameters_required')

    def __call__(self, rgb, mask):
        torch = self.torch
        image = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float()[None] / 255
        tensor_mask = torch.from_numpy((mask > 0).astype(np.float32))[None, None]
        with torch.inference_mode():
            output = self.model(image, tensor_mask)
        if isinstance(output, dict):
            output = output['inpainted']
        require(isinstance(output, torch.Tensor) and tuple(output.shape) == tuple(image.shape), 'JIT_context_output_shape_changed')
        require(output.device.type == 'cpu' and bool(torch.isfinite(output).all()), 'finite_CPU_output_required')
        return output[0].clamp(0, 1).permute(1, 2, 0).mul(255).round().to(torch.uint8).numpy()


def telea_context(rgb, mask, radius=3):
    """Explicit spatial interpolation on a bounded local crop, no model."""
    require(radius in (3, 5), 'explicit_Telea_radius_3_or_5_required')
    prediction = rgb.copy()
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return prediction
    margin = max(16, radius * 4)
    x0, x1 = max(0, int(xs.min())-margin), min(rgb.shape[1], int(xs.max())+margin+1)
    y0, y1 = max(0, int(ys.min())-margin), min(rgb.shape[0], int(ys.max())+margin+1)
    crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    local_mask = np.ascontiguousarray(mask[y0:y1, x0:x1])
    # Channel order is immaterial to this per-channel spatial interpolation.
    prediction[y0:y1, x0:x1] = cv2.inpaint(crop, local_mask, radius, cv2.INPAINT_TELEA)
    return prediction


def process(rgb, cfg, infer):
    mask, detection = detect_mask(rgb, cfg)
    y0, y1 = cfg['context_y']
    prediction = infer(rgb[y0:y1], mask) if detection['mask_pixels'] else rgb[y0:y1].copy()
    after, diff = masked_restore(rgb, mask, prediction, cfg)
    return after, mask, dict(**detection, **diff, model_called=bool(detection['mask_pixels']))


def config_file(path):
    cfg = dict(DEFAULT) if path is None else read(path)
    require(set(cfg) == set(DEFAULT), 'explicit_supported_detector_config_required')
    require(cfg['context_y'] == [832, 1088] and 832 <= cfg['search_y'][0] < cfg['search_y'][1] <= 1088,
            'fixed_full_width_context_and_inner_search_required')
    require(0 <= cfg['saturation_max'] <= 255 and 0 <= cfg['value_min'] <= 255 and
            0 <= cfg['mask_dilate'] <= 8 and 0 < cfg['max_context_mask_fraction'] <= .25,
            'bounded_mask_parameters_required')
    return cfg


def setup(run, weights, cfg, expected_sha=None, *, method='lama', radius=3):
    run, weights = Path(run).resolve(), Path(weights).resolve()
    require(run == PROJECT / ROOT_REL, 'only_new_postprocessing_root_allowed')
    source = PROJECT / SOURCE_REL
    require(bind(source)['sha256'] == SOURCE_SHA, 'explicit_v39_source_SHA_changed')
    native_result = source.parent.parent / 'RESULT.json'
    native = read(native_result)
    require(native.get('prompt_id') == '96fce6ce-531d-488c-8b30-3182c9944ffd' and
            native.get('technical_status') == 'technical_saved' and
            native['files']['video']['sha256'] == SOURCE_SHA and
            Path(native['files']['video']['path']).resolve() == source, 'explicit_original_v39_result_required')
    require(method in ('lama', 'telea'), 'explicit_local_method_required')
    weight_binding = None
    if method == 'lama':
        require(weights.is_relative_to(PROJECT / 'data/models/lama_subtitle') and weights.stat().st_size == 205669692,
                'complete_pre_downloaded_LaMa_JIT_required')
        weight_binding = bind(weights)
        if expected_sha:
            require(weight_binding['sha256'] == expected_sha, 'approved_weight_SHA_changed')
    else:
        require(radius in (3, 5), 'explicit_Telea_radius_3_or_5_required')
    frozen = dict(run=str(run), script=bind(Path(__file__)), source=bind(source), source_native_result=bind(native_result),
                  source_native_id=native['prompt_id'], weights=weight_binding,
                  weights_bytes=weights.stat().st_size if method=='lama' else None,
                  detector=cfg, width=736, height=1312,
                  frames=362, fps=24, context_RGB=[0, 832, 736, 1088], method=method,
                  method_detail='CPU_torch_jit_LaMa_mask_only_paste' if method=='lama' else 'CPU_OpenCV_Telea_local_crop_mask_only_paste',
                  telea_radius=radius if method=='telea' else None,
                  spatial_interpolation_can_smear_background=method=='telea',
                  postprocessing=True, new_native_generation=False,
                  temporal_model=False, temporal_consistency_guaranteed=False,
                  outside_mask_unchanged_applies='decoded_RGB_before_lossy_reencoding')
    case = run / 'cases' / digest(frozen)[:16]
    freeze(case / 'CONFIG.json', frozen)
    return source, weights, case, frozen


def panel(before, after, mask, cfg, label):
    y0, y1 = cfg['context_y']
    images = [before[y0:y1], after[y0:y1], np.repeat(mask[:, :, None], 3, axis=2)]
    canvas = Image.new('RGB', (736 * 3, 284), 'white')
    draw = ImageDraw.Draw(canvas)
    for column, (image, title) in enumerate(zip(images, ('BEFORE', 'AFTER', 'MASK'))):
        canvas.paste(Image.fromarray(image), (column * 736, 28))
        draw.text((column * 736 + 6, 7), label + ' ' + title, fill='black')
    return canvas


def canary(source, case, cfg, infer):
    report = case / 'CANARY.json'
    if report.exists():
        old = read(report)
        for item in old['artifacts']:
            require(bind(item['path']) == item, 'existing_canary_artifact_changed')
        return old
    frames = extract_batch(source, CANARY_FRAMES, case / 'source_frames')
    rows, artifacts, panels = [], [], []
    for index in CANARY_FRAMES:
        with Image.open(frames[index]['path']) as im:
            before = np.asarray(im.convert('RGB'))
        after, mask, stats = process(before, cfg, infer)
        folder = case / 'canary' / f'n{index:04d}'
        folder.mkdir(parents=True, exist_ok=True)
        for name, pixels in [('before', before), ('after', after), ('mask_context', mask)]:
            path = folder / (name + '.png')
            require(not path.exists(), 'unreceipted_canary_output_preserved')
            Image.fromarray(pixels).save(path)
            artifacts.append(bind(path))
        rows.append(dict(frame=index, seconds=index / 24, stats=stats, before=bind(folder/'before.png'),
                         after=bind(folder/'after.png'), mask=bind(folder/'mask_context.png')))
        panels.append(panel(before, after, mask, cfg, f'ACTUAL frame {index} {index/24:.3f}s'))
    boards = []
    for index in range(0, len(panels), 2):
        canvas = Image.new('RGB', (2208, 568), 'white')
        for offset, image in enumerate(panels[index:index+2]):
            canvas.paste(image, (0, offset * 284))
        path = case / f'CANARY_BEFORE_AFTER_MASK_{index//2+1:02d}.jpg'
        canvas.save(path, quality=96)
        boards.append(bind(path))
    artifacts += boards
    require(bind(source)['sha256'] == SOURCE_SHA, 'native_source_changed_during_canary')
    value = dict(schema='subtitle_CPU_local_canary/v1', config=bind(case/'CONFIG.json'),
                 method=read(case/'CONFIG.json')['method'],
                 source=bind(source), postprocessing=True, temporal_consistency_guaranteed=False,
                 rows=rows, boards=boards, artifacts=artifacts,
                 all_mask_outside_diff_before_encode_zero=all(r['stats']['mask_outside_changed_pixels_before_encode']==0 for r in rows),
                 full_video_processed=False, content_approved=False)
    freeze(report, value)
    return value


def audio_packets(path):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_packets', '-show_data_hash', 'sha256',
           '-show_entries', 'packet=pts,dts,duration,size,data_hash,side_data_list', '-of', 'json', str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    require(result.returncode == 0, 'audio_packet_probe_failed')
    packets = json.loads(result.stdout)['packets']
    require(packets and all('data_hash' in row for row in packets), 'compressed_audio_packet_hashes_required')
    return dict(packet_count=len(packets), packets=packets, packet_manifest_sha256=digest(packets))


def full(source, case, cfg, infer):
    require((case/'CANARY.json').is_file(), 'run_canary_then_explicit_full_command_required')
    output, receipt = case/'S02_SUBTITLE_REPAIRED_CPU_POSTPROCESSED.mp4', case/'FULL_RESULT.json'
    if receipt.exists():
        result = read(receipt)
        require(bind(output)==result['file'], 'existing_processed_movie_changed')
        return result
    partial = case/'FULL.partial.mp4'
    require(not output.exists() and not partial.exists(), 'unreceipted_processing_output_preserved')
    before_audio = audio_packets(source)
    freeze(case/'SOURCE_AUDIO_PACKETS.json', before_audio)
    decoder_cmd = ['ffmpeg','-nostdin','-v','error','-hwaccel','none','-threads','2','-i',str(source),
                   '-map','0:v:0','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    encoder_cmd = ['ffmpeg','-nostdin','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','736x1312','-r','24','-i','pipe:0',
                   '-i',str(source),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','18',
                   '-threads','2','-pix_fmt','yuv420p','-c:a','copy','-frames:v','362','-fps_mode','cfr','-movflags','+faststart',str(partial)]
    freeze(case/'FULL_COMMANDS.json', dict(decoder=decoder_cmd, encoder=encoder_cmd, explicit_full_stage=True))
    stats = []
    with (case/'decoder.stderr.log').open('wb') as dl, (case/'encoder.stderr.log').open('wb') as el:
        decoder = subprocess.Popen(decoder_cmd, stdout=subprocess.PIPE, stderr=dl)
        encoder = subprocess.Popen(encoder_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=el)
        try:
            for index in range(362):
                data = decoder.stdout.read(736*1312*3)
                require(len(data)==736*1312*3, 'source_decoded_frame_count_changed')
                before = np.frombuffer(data, np.uint8).reshape(1312,736,3)
                after, _, row = process(before,cfg,infer)
                encoder.stdin.write(after.tobytes())
                stats.append(dict(frame=index,**row))
            require(not decoder.stdout.read(1), 'source_has_extra_video_frames')
            encoder.stdin.close()
            require(decoder.wait(timeout=180)==0 and encoder.wait(timeout=180)==0, 'CPU_decode_or_encode_failed')
        finally:
            for process_obj in (decoder,encoder):
                if process_obj.poll() is None:
                    process_obj.terminate()
                    process_obj.wait(timeout=30)
    geometry, probe = inspect_clock(partial,362)
    freeze(case/'OUTPUT_PROBE.json', probe)
    after_audio = audio_packets(partial)
    freeze(case/'OUTPUT_AUDIO_PACKETS.json', after_audio)
    require(before_audio==after_audio, 'original_AAC_packets_or_timestamps_changed')
    require(bind(source)['sha256']==SOURCE_SHA, 'native_source_changed_during_processing')
    partial.rename(output)
    value = dict(schema='subtitle_CPU_local_processed_video/v1',file=bind(output),source=bind(source),config=bind(case/'CONFIG.json'),
                 method=read(case/'CONFIG.json')['method'],
                 clock=geometry,frame_stats=stats,postprocessing=True,new_native_generation=False,
                 original_AAC_stream_copy=True,audio_packet_manifest_sha256=before_audio['packet_manifest_sha256'],
                 audio_packet_identity_verified=True,all_mask_outside_diff_before_encode_zero=True,
                 lossy_reencode_can_change_pixels_outside_mask=True,temporal_consistency_guaranteed=False,
                 subtitle_absence_verified=False,content_approved=False)
    freeze(receipt,value)
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('canary','full'),required=True)
    parser.add_argument('--method',choices=('lama','telea'),default='lama')
    parser.add_argument('--radius',type=int,choices=(3,5),default=3)
    parser.add_argument('--run',type=Path,default=PROJECT/ROOT_REL)
    parser.add_argument('--weights',type=Path,default=PROJECT/'data/models/lama_subtitle/big-lama.pt')
    parser.add_argument('--weights-sha256')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--threads',type=int,default=2)
    args=parser.parse_args(argv)
    require(1<=args.threads<=16,'bounded_CPU_threads_required')
    cfg=config_file(args.config)
    source,weights,case,frozen=setup(args.run,args.weights,cfg,args.weights_sha256,method=args.method,radius=args.radius)
    inspect_clock(source,362)
    inference=None
    def infer(rgb,mask):
        nonlocal inference
        if args.method=='telea':
            return telea_context(rgb,mask,args.radius)
        if inference is None:
            inference=CpuLama(weights,args.threads)
        return inference(rgb,mask)
    try:
        result=canary(source,case,cfg,infer) if args.stage=='canary' else full(source,case,cfg,infer)
    except Exception as error:
        freeze(case/('ERROR_'+str(time.time_ns())+'.json'),dict(stage=args.stage,type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),native_source_unchanged=True))
        raise
    print(json.dumps(dict(status='CPU_postprocessing_'+args.stage+'_complete',case=str(case),
                          method=args.method,
                          receipt=bind(case/('CANARY.json' if args.stage=='canary' else 'FULL_RESULT.json')),
                          boards=result.get('boards'),file=result.get('file'),postprocessing=True,
                          temporal_consistency_guaranteed=False),ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
