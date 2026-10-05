"""Local frame/audio evidence for inspection; extraction never means approval."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REVIEW_CHECKS = ('identity', 'spatial_layout', 'props_and_hands', 'action_pace',
                 'dialogue_pace', 'speaker_voice', 'lip_sync', 'cut_continuity')


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args):
    return subprocess.check_output(args, stderr=subprocess.PIPE)


def build_review_packet(folder, video, expected_sha, script_sha, cuts=()):
    folder, video = Path(folder).resolve(), Path(video).resolve()
    cuts = list(cuts)
    if not video.is_relative_to(folder) or file_sha(video) != expected_sha:
        raise ValueError('Review source must be an unchanged video inside this run')
    context = json.dumps({'source': expected_sha, 'script': script_sha, 'cuts': list(cuts)}, sort_keys=True)
    key = hashlib.sha256(context.encode()).hexdigest()[:20]
    output = folder / 'review_packets' / video.stem / key
    packet_path = output / 'packet.json'
    if packet_path.exists():
        packet = json.loads(packet_path.read_text(encoding='utf-8'))
        for item in packet['evidence']:
            path = (output / item['file']).resolve()
            if not path.is_relative_to(output) or file_sha(path) != item['sha256']:
                raise ValueError('Review evidence changed; inspect before rebuilding')
        return packet_path
    output.mkdir(parents=True, exist_ok=True)
    data = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                           '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(video)]))
    pts = [float(f['best_effort_timestamp_time']) for f in data['frames']]
    if not pts or pts != sorted(pts):
        raise ValueError('Missing or unordered decoded frame timestamps')
    times = [p - pts[0] for p in pts]

    def nearest(t):
        right = bisect.bisect_left(times, t)
        return min({max(0, right-1), min(len(times)-1, right)}, key=lambda i: abs(times[i]-t))

    selected = {0, len(times)-1}
    selected.update(nearest(i*.5) for i in range(math.floor(times[-1]*2)+1))
    boundaries = []
    for n, cut in enumerate(cuts, 1):
        t = float(cut['time'])
        if not 0 < t < times[-1]:
            raise ValueError('Cut time is outside the source video')
        indices = sorted({nearest(t+d) for d in (-.5, -.25, -.04, 0, .25, .5)})
        selected.update(indices)
        boundaries.append(dict(cut, id=f'cut_{n:02}', frame_indices=indices))
    indices = sorted(selected)
    expression = '+'.join(f'eq(n,{i})' for i in indices)
    run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', str(video),
         '-vf', f"select='{expression}',scale=320:-2", '-fps_mode', 'vfr',
         str(output/'frame_%04d.png')])
    frames = []
    for number, index in enumerate(indices, 1):
        image_path = output / f'frame_{number:04}.png'
        if not image_path.is_file():
            raise ValueError('Frame extraction did not produce every requested sample')
        frames.append({'frame_index': index, 'time_seconds': times[index],
                       'decoded_pts': pts[index], 'file': image_path.name})
    frame_map = {f['frame_index']: f for f in frames}
    font_path = Path('C:/Windows/Fonts/arial.ttf')
    font = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()

    def sheet(items, name, columns):
        with Image.open(output/items[0]['file']) as picture:
            width, height = picture.size
        cell_h = height+30
        canvas = Image.new('RGB', (width*columns, cell_h*math.ceil(len(items)/columns)), '#14202d')
        draw = ImageDraw.Draw(canvas)
        for i, item in enumerate(items):
            x, y = i % columns*width, i // columns*cell_h
            with Image.open(output/item['file']) as picture:
                canvas.paste(picture, (x, y+30))
            draw.text((x+8, y+5), f"{video.stem} | {item['time_seconds']:.3f}s | f{item['frame_index']}", font=font, fill='white')
        canvas.save(output/name)
        return name

    sheets = [sheet(frames[i:i+12], f'timeline_{i//12+1:02}.jpg', 4) for i in range(0, len(frames), 12)]
    for boundary in boundaries:
        boundary['sheet'] = sheet([frame_map[i] for i in boundary['frame_indices']], boundary['id']+'.jpg', 3)
        start = max(0, boundary['time']-1)
        excerpt = boundary['id']+'.mp4'
        run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-ss', str(start), '-i', str(video),
             '-t', str(min(2, times[-1]-start)), '-c:v', 'libx264', '-preset', 'fast',
             '-crf', '20', '-c:a', 'aac', '-movflags', '+faststart', str(output/excerpt)])
        boundary.update(audiovisual_excerpt=excerpt, excerpt_start_seconds=start)
    run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', str(video),
         '-vn', '-ac', '1', '-ar', '16000', str(output/'audio.wav')])
    first_last = sheet([frames[0], frames[-1]], 'first_last.jpg', 2)
    evidence = [{'file': p.name, 'sha256': file_sha(p)} for p in sorted(output.iterdir()) if p.is_file()]
    packet = {'schema': 'script_video_review_packet/v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'source_video': str(video), 'source_sha256': expected_sha, 'script_sha256': script_sha,
              'sampling_interval_seconds': .5, 'first_frame_index': 0, 'last_frame_index': len(times)-1,
              'frames': frames, 'timeline_sheets': sheets, 'first_last_sheet': first_last,
              'boundaries': boundaries, 'audio': 'audio.wav', 'evidence': evidence,
              'review_status': 'pending', 'automated_visual_or_voice_verdict': False}
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    template = {'source_sha256': expected_sha, 'script_sha256': script_sha, 'decision': 'pending',
                'checks': {name: None for name in REVIEW_CHECKS}, 'observations': [],
                'instruction': (
                    '实际查看时间标注抽帧及每个切点，听看原生视频核对发声角色、声线、口型与语速。'
                    '人物换位、碰错或拿错道具、关键动作缺失或反向、尾态不连续、错人发声与声画错配属于失败。'
                    '不改变人物/道具归属、关键动作和末态的短暂自然对视、同一道具上的抬指或重新接触、轻微姿态变化，'
                    '记录为可接受表演差异，不因剧本未逐字列出便自动判失败；480p无法确认的细节保持null，不把推测写成false。'
                    '逐项记录秒数和证据；抽帧完成或ASR通过不等于审核通过。')}
    (output/'review.template.json').write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding='utf-8')
    return packet_path
