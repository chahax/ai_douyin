"""Deterministic CPU-only crops from the user's accepted native S02.

No image synthesis, upload, HTTP, resizing, rotation or asset-library rewrite.
The output is an append-preserved candidate bundle awaiting root observation.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'accepted_S02_identity_environment_20261111_v1'
OUT = ROOT / 'data/serial_story_assets' / VERSION
ACCEPTED = ROOT / 'data/video_generation/h3_story_opening_s02_20261110_v1'
NATIVE_ID = 'ad632988-544f-4074-91c5-76ccfff0f88e'
VIDEO_SHA = '333c204265493be12503173e836094b6bfb06b85a316a32ac242b0d2ecdb12a5'
NATIVE_RESULT = ACCEPTED / 'visual_h3_v3/opening_S02/shots/S02/RESULT.json'
QA = ACCEPTED / 'qc_opening' / NATIVE_ID / 'with_asr'
FRAME_SHA = {
    0: '824e2c66bb9766c31efcc8117b834a5caa19cf5ed2d47279b6564b39e71aa513',
    168: '9aae86516ed3eaa8172b98ca6988bb71171f52f6d0add4b079d78fdb7466153f',
    360: '97410d0650376d9e3fb37fb9828dd3044ba38809744ae1bbb5cc30b1997473d0',
}
ROWS = (
    ('P1', 'su_mo', 'adult_su_mo_accepted_S02', 'character', 168, (0, 192, 736, 1120),
     'father_identity_and_visible_upper_wardrobe',
     ['One reclining source pose only; not a new upright or alternate-angle photograph.',
      'Expression and partial open eyes are inherited from the accepted performance.']),
    ('P2', 'ye_nan', 'child_ye_nan_accepted_S02', 'character', 360, (64, 64, 320, 608),
     'older_boy_identity_and_visible_upper_wardrobe',
     ['Downward gaze; cropped face and upper clothing, not a complete body turnaround.',
      'Existing shirt markings and background poster pixels are retained.']),
    ('P3', 'ye_xijue', 'child_ye_xijue_accepted_S02', 'character', 360, (440, 192, 288, 448),
     'younger_boy_identity_and_visible_upper_wardrobe',
     ['One source angle and expression only; native source resolution is retained.',
      'This portrait is not a bread-bag or hand-position reference.']),
    ('P4', 'su_mo_room', 'room_accepted_S02', 'environment_detail', 0, (0, 0, 736, 384),
     'furniture_and_wall_material_detail',
     ['Background detail of the accepted frame; not a complete front-view room image.',
      'Cannot establish unseen layout or metric room geometry.']),
    ('P5', 'su_mo_room', 'room_accepted_S02', 'environment_detail', 360, (416, 0, 320, 192),
     'window_and_wall_material_detail',
     ['Small background detail of the accepted frame; not a complete side-view room image.',
      'No new viewing angle, outpainting or high-resolution detail was synthesized.']),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=sha(path.read_bytes()))


def preserve(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('existing_candidate_preserved_use_new_version:' + str(path))
    else:
        path.write_bytes(data)


def freeze(path, value):
    preserve(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def png_bytes(image):
    buf = io.BytesIO()
    image.save(buf, format='PNG', optimize=False, compress_level=6)
    return buf.getvalue()


def source_frames():
    result = read(NATIVE_RESULT)
    video = {k: result['files']['video'][k] for k in ('path', 'sha256')}
    if result['prompt_id'] != NATIVE_ID or video['sha256'] != VIDEO_SHA or bind(video['path']) != video:
        raise ValueError('exact_accepted_native_video_required')
    report = read(QA / 'QA.json')
    binding = read(QA / 'BINDING.json')
    if report['native_id'] != NATIVE_ID or report['video'] != video or binding['video'] != video:
        raise ValueError('original_QA_source_video_changed')
    artifacts = {item['path']: item['sha256'] for item in report['artifacts']}
    frames = {}
    for index, expected in FRAME_SHA.items():
        path = QA / 'frames' / f'actual_{index:04d}.png'
        if bind(path)['sha256'] != expected or artifacts.get(str(path.resolve())) != expected:
            raise ValueError('existing_QA_frame_changed')
        with Image.open(path) as image:
            rgb = image.convert('RGB')
            if rgb.size != (736, 1312):
                raise ValueError('exact_source_frame_dimensions_required')
            frames[index] = rgb
    return video, frames


def verify_decoded_frames(video, frames):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('local_ffmpeg_required_for_CPU_pixel_verification')
    indices = sorted(frames)
    select = 'select=' + '+'.join(f'eq(n\\,{index})' for index in indices)
    command = [ffmpeg, '-nostdin', '-v', 'error', '-hwaccel', 'none', '-threads', '1',
               '-i', video['path'], '-vf', select, '-vsync', '0', '-pix_fmt', 'rgb24',
               '-f', 'rawvideo', 'pipe:1']
    process = subprocess.run(command, capture_output=True, timeout=90)
    if process.returncode:
        raise ValueError('CPU_frame_verification_failed:' + process.stderr.decode('utf-8', errors='replace')[-2000:])
    stride = 736 * 1312 * 3
    if len(process.stdout) != stride * len(indices):
        raise ValueError('CPU_decoded_frame_count_changed')
    rows = []
    for order, index in enumerate(indices):
        pixels = process.stdout[order * stride:(order + 1) * stride]
        if pixels != frames[index].tobytes():
            raise ValueError('existing_QA_frame_not_exact_source_decode')
        rows.append(dict(frame_index=index, seconds=index / 24,
                         frame=bind(QA / 'frames' / f'actual_{index:04d}.png'),
                         rgb24_pixels_sha256=sha(pixels), exact_source_decode_pixels=True))
    return dict(schema='accepted_video_CPU_frame_verification/v1', source_video=video,
                native_id=NATIVE_ID, command=command, CPU_only=True, frames=rows,
                no_gpu_inference=True, no_HTTP=True)


def extract(out=OUT):
    out = Path(out).resolve()
    if out != OUT.resolve():
        raise ValueError('explicit_new_asset_version_directory_required')
    video, frames = source_frames()
    verification = verify_decoded_frames(video, frames)
    freeze(out / 'SOURCE_FRAME_VERIFICATION.json', verification)
    rows = []
    for number, (label, entity, group, kind, index, box, purpose, limits) in enumerate(ROWS, 1):
        x, y, width, height = box
        source = frames[index]
        if min(x, y) < 0 or min(width, height) <= 0 or x + width > source.width or y + height > source.height:
            raise ValueError('exact_crop_inside_original_source_required')
        crop = source.crop((x, y, x + width, y + height))
        path = out / (label + '_' + entity + ('_portrait.png' if kind == 'character' else '_' + purpose + '.png'))
        preserve(path, png_bytes(crop))
        with Image.open(path) as actual:
            if actual.convert('RGB').tobytes() != crop.tobytes() or actual.size != (width, height):
                raise ValueError('exact_source_crop_pixels_required')
        rows.append(dict(slot=number - 1, tag=f'<Picture {number}>', label=label,
            reference_id=VERSION + ':' + label, entity_id=entity, actor_id=entity if kind == 'character' else None,
            identity_group=group, asset_version=VERSION, kind=kind, purpose=purpose,
            source=dict(native_id=NATIVE_ID, video=video, frame_index=index, fps=24,
                frame=bind(QA / 'frames' / f'actual_{index:04d}.png'), qa_report=bind(QA / 'QA.json')),
            roi=dict(x=x, y=y, width=width, height=height),
            derivation=dict(operation='PIL_RGB_integer_crop_only', resize=None, rotation_degrees=0,
                source_orientation_preserved=True, upscale=False, exact_pixels_sha256_kind='RGB24_row_major_bytes',
                exact_pixels_sha256=sha(crop.tobytes()), generative_model_calls=0),
            image=dict(**bind(path), width=width, height=height), limitations=limits,
            intended_person_count=1 if kind == 'character' else 0,
            semantic_review_status='root_actual_observation_required', production_approved=False))
    manifest = dict(schema='accepted_video_fixed_reference_assets/v1', asset_version=VERSION,
        source_native_id=NATIVE_ID, source_video=video, source_native_result=bind(NATIVE_RESULT),
        source_QA_binding=bind(QA / 'BINDING.json'), source_frame_verification=bind(out / 'SOURCE_FRAME_VERIFICATION.json'),
        extraction_script=bind(__file__), pillow_version=PILLOW_VERSION,
        fixed_reference_count=5, fixed_order=['P1', 'P2', 'P3', 'P4', 'P5'],
        clip_actor_ids=['su_mo', 'ye_nan', 'ye_xijue'], references=rows,
        fixed_reference_set_sha256=sha(json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')),
        no_new_generations=True, no_HTTP=True, no_upscale=True, environment_complete_views_claimed=False,
        dynamic_previous_tail_replaces_fixed_assets=False, semantic_review_status='root_actual_observation_required',
        production_approved=False, publication=False)
    freeze(out / 'ASSET_MANIFEST.json', manifest)
    # This labeled, resized contact is review-only; it is not a model reference.
    board = Image.new('RGB', (1280, 500), 'white')
    draw = ImageDraw.Draw(board)
    for index, row in enumerate(rows):
        with Image.open(row['image']['path']) as image:
            image = image.convert('RGB')
            image.thumbnail((236, 444), Image.Resampling.LANCZOS)
            board.paste(image, (index * 256 + (256 - image.width) // 2, 36))
        draw.text((index * 256 + 8, 8), row['label'] + ' ' + row['entity_id'], fill='black')
        draw.text((index * 256 + 8, 478), f"{row['image']['width']}x{row['image']['height']} native crop", fill='black')
    preserve(out / 'REVIEW_ONLY_CONTACT.png', png_bytes(board))
    return dict(status='five_CPU_candidates_require_root_review', manifest=bind(out / 'ASSET_MANIFEST.json'),
                review_contact=bind(out / 'REVIEW_ONLY_CONTACT.png'), assets=[row['image'] for row in rows],
                new_model_calls=0, HTTP_calls=0, original_media_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(extract(args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
