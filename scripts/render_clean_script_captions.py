"""Add transparent captions to a caption-free original; never alter its raw tail."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_script_video import locked, probe, read, sha, write
from scripts.render_script_video_captions import ass_time, caption_chunks, visible
from src.content_factory.script_video_review import build_review_packet


def caption_cues(dialogue, result, duration):
    """Require the measured words to equal the script before placing that text."""
    recognized, raw_recognized, stamps = '', '', []
    for row in result:
        chars = visible(row['text'])
        times = row.get('timestamp', [])
        if len(chars) != len(times):
            raise ValueError('ASR words and timestamps differ')
        recognized += chars
        raw_recognized += row['text']
        stamps.extend(times)
    if not stamps or recognized != visible(dialogue):
        raise ValueError('Inspect the actual dialogue mismatch; captions must not hide it')
    # Generic punctuation normalization must not turn 4.2 into 42, or -42 into 42.
    numeric = r'[-+−]?\d+(?:[.,]\d+)*[%％]?'
    if re.findall(numeric, dialogue) != re.findall(numeric, raw_recognized):
        raise ValueError('Inspect the numeric dialogue mismatch before adding captions')
    previous = 0.
    for pair in stamps:
        if (len(pair) != 2 or any(type(t) not in (int, float) for t in pair)
                or not previous <= pair[0] < pair[1] <= duration * 1000 + 1):
            raise ValueError('ASR timestamps are outside this clip or unordered')
        previous = pair[1]
    cues, cursor = [], 0
    for chunk in caption_chunks(dialogue, limit=16):
        count = len(visible(chunk))
        begin = max(0, stamps[cursor][0] / 1000 - .06)
        finish = min(duration, stamps[cursor + count - 1][1] / 1000 + .06)
        cursor += count
        if cursor < len(stamps):
            finish = min(finish, max(begin + .01, stamps[cursor][0] / 1000 - .06))
        if finish <= begin:
            raise ValueError('Caption timing is empty')
        cues.append({'text': chunk, 'start': begin, 'end': finish})
    return cues


def audio_hash(path):
    return subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
        '-map', '0:a:0', '-c', 'copy', '-f', 'streamhash', '-hash', 'sha256', '-']).decode().strip()


def frame_times(path):
    value = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(path)]))
    return [float(frame['best_effort_timestamp_time']) for frame in value['frames']]


def caption_shots(folder, manifest, script):
    """Read the frozen dialogue of an explicit reviewed screenplay trial."""
    if manifest.get('trial_schema') in {
            'reviewed_screenplay_first_shot/v1', 'reviewed_screenplay_segment/v1'}:
        from scripts.run_screenplay_trial import verify_inputs
        plan_path = folder / 'trial_plan.json'
        if sha(plan_path) != manifest['trial_plan_sha256']:
            raise ValueError('Reviewed screenplay plan changed before captioning')
        story, _, _ = verify_inputs(read(plan_path))
        if story != script or manifest['script_sha256'] != read(plan_path)['bindings']['story']['sha256']:
            raise ValueError('Caption dialogue differs from the reviewed screenplay')
        return story['version']['shots']
    return script['shots']


def retain_native_cues(cues, review, duration):
    """Omit overlay only for specifically inspected existing full caption cues."""
    spans=review.get('native_caption_spans', [])
    if review.get('native_caption_free') is True:
        if spans: raise ValueError('Caption-free review cannot contain native captions')
        return cues, []
    if not spans: raise ValueError('Actual review must identify each native caption')
    omitted=[]
    for span in spans:
        if (not isinstance(span.get('text'),str) or not span.get('notes')
                or not 0 <= span.get('start',-1) < span.get('end',-1) <= duration):
            raise ValueError('Invalid inspected native caption span')
        matches=[cue for cue in cues if cue['text'].rstrip('，。！？；、!?;')==span['text'].rstrip('，。！？；、!?;') and
                 cue['start'] < span['end'] and span['start'] < cue['end']]
        if len(matches)!=1 or matches[0] in omitted:
            raise ValueError('Native caption must match one full measured dialogue cue')
        if any(cue is not matches[0] and cue['start']<span['end'] and span['start']<cue['end'] for cue in cues):
            raise ValueError('Native caption overlaps another measured cue')
        omitted.append(matches[0])
    return [cue for cue in cues if cue not in omitted], omitted


def render(folder, shot_id, transcript_path, review_path):
    folder = Path(folder).resolve()
    manifest, script = locked(folder)
    record = read(folder / f'{shot_id}.json')
    source = Path(record['local_video']).resolve()
    if (record['status'] != 'downloaded' or not source.is_relative_to(folder)
            or sha(source) != record['video_sha256']):
        raise ValueError('Use the unchanged original video from this run')
    # Review only authorizes an overlay, never media approval or another generation.
    review_path, transcript_path = Path(review_path).resolve(), Path(transcript_path).resolve()
    if not all(p.is_relative_to(folder) and p.is_file() for p in (review_path, transcript_path)):
        raise ValueError('Keep actual caption review and transcript inside this run')
    review = read(review_path)
    if (review.get('source_sha256') != record['video_sha256']
            or (review.get('native_caption_free') is not True and not review.get('native_caption_spans'))
            or review.get('caption_area_clear') is not True
            or not review.get('notes') or not review.get('evidence')):
        raise ValueError('Actual review must confirm no existing lettering and a clear lower caption area')
    for relative in review['evidence']:
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('Caption review evidence is missing')
    packet_path = Path(record['review_packet']).resolve()
    if not packet_path.is_relative_to(folder) or not packet_path.is_file():
        raise ValueError('The original review packet must be inside this run')
    packet = read(packet_path)
    transcript = read(transcript_path)
    audio = (packet_path.parent / packet['audio']).resolve()
    if not audio.is_relative_to(packet_path.parent) or not audio.is_file():
        raise ValueError('Packet audio must remain inside this original review packet')
    evidence = next(item for item in packet['evidence'] if item['file'] == packet['audio'])
    if (packet['source_sha256'] != record['video_sha256']
            or Path(packet['source_video']).resolve() != source
            or packet['script_sha256'] != manifest['script_sha256']
            or Path(transcript['audio']).resolve() != audio.resolve()
            or sha(audio) != evidence['sha256']):
        raise ValueError('ASR must refer to this exact original audio packet')
    shot = next(s for s in caption_shots(folder, manifest, script) if s['shot_id'] == shot_id)
    media = probe(source)
    stream = next(s for s in media['streams'] if s['codec_type'] == 'video')
    w, h = stream['width'], stream['height']
    duration = float(media['format']['duration'])
    cues = caption_cues(shot['dialogue'], transcript['result'], duration)
    cues, retained_native = retain_native_cues(cues, review, duration)
    output = folder / f'{shot_id}.clean_captions.mp4'
    ass_path, report_path = output.with_suffix('.ass'), output.with_suffix('.json')
    if any(p.exists() for p in (output, ass_path, report_path)):
        raise FileExistsError('Preserve the existing caption attempt; inspect it instead of overwriting')
    font = max(16, round(w * 24 / 496))
    lines = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {w}', f'PlayResY: {h}',
        'WrapStyle: 2', '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        f'Style: Dialogue,Microsoft YaHei,{font},&H00FFFFFF,&H00FFFFFF,&H00303030,&HFF000000,0,0,0,0,100,100,0,0,1,1.2,0.3,5,20,20,0,1',
        '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    for cue in cues:
        # Project dialogue is plain text; reject ASS control sequences.
        if any(c in cue['text'] for c in '{}\\\r\n'):
            raise ValueError('Caption text contains formatting control characters')
        lines.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},Dialogue,,0,0,0,,"
                     + '{\\pos(' + str(w // 2) + ',' + str(round(h * .85)) + ')}' + cue['text'])
    ass_path.write_text('\n'.join(lines), encoding='utf-8-sig')
    report = {'schema': 'clean_script_captions/v1', 'status': 'rendering',
        'started_at': datetime.now(timezone.utc).isoformat(), 'source': str(source),
        'source_sha256': record['video_sha256'], 'script_sha256': manifest['script_sha256'],
        'transcript_sha256': sha(transcript_path), 'caption_review_sha256': sha(review_path),
        'ass_sha256': sha(ass_path), 'cues': cues, 'retained_native_cues':retained_native,
        'native_caption_spans':review.get('native_caption_spans', []), 'video': str(output),
        'subtitle_style': 'white_text_thin_outline_no_box', 'media_review': 'pending',
        'video_generation_submitted': False, 'external_audio_uploaded': False,
        'raw_tail_replaced': False, 'changes': 'transparent text overlay only; original audio copied'}
    write(report_path, report)
    try:
        subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-n', '-i', source.name,
            '-vf', f'ass={ass_path.name}', '-map', '0:v:0', '-map', '0:a:0',
            '-fps_mode', 'passthrough', '-enc_time_base:v', '1:24000',
            '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-c:a', 'copy',
            '-movflags', '+faststart', output.name], cwd=folder, check=True, capture_output=True)
        if audio_hash(source) != audio_hash(output) or frame_times(source) != frame_times(output):
            raise ValueError('Caption rendering changed the audio or video timestamps')
        report.update(status='candidate_pending_review', video_sha256=sha(output),
            audio_preserved=True, frame_timestamps_preserved=True,
            review_packet=str(build_review_packet(folder, output, sha(output), manifest['script_sha256'])))
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write(report_path, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('run-dir', 'shot', 'transcript', 'caption-review'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    result = render(args.run_dir, args.shot, args.transcript, args.caption_review)
    print(json.dumps({key: result[key] for key in ('status', 'video', 'media_review')}, ensure_ascii=False))
