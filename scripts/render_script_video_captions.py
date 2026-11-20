"""Render locked-script captions over generated lettering; keep original media and audio."""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_script_video import locked, probe, read, sha, write, review_packet
from src.content_factory.script_video_review import build_review_packet
from src.content_factory.video_campaign import preview_asset


def visible(text):
    return ''.join(c for c in text if c.isalnum())


def caption_chunks(text, limit=30):
    pieces = re.findall(r'[^，。！？、；]+[，。！？、；]?', text)
    chunks, current = [], ''
    for piece in pieces:
        while len(piece) > limit:
            if current:
                chunks.append(current)
                current = ''
            chunks.append(piece[:limit])
            piece = piece[limit:]
        if current and len(current + piece) > limit:
            chunks.append(current)
            current = ''
        current += piece
    if current:
        chunks.append(current)
    if ''.join(chunks) != text:
        raise ValueError('Caption segmentation changed the locked dialogue')
    return chunks


def speech_map(text, result):
    recognized, times = '', []
    for row in result:
        chars = visible(row['text'])
        stamps = row.get('timestamp', [])
        if len(chars) != len(stamps):
            raise ValueError('ASR character timing mismatch; inspect before captioning')
        recognized += chars
        times.extend(stamps)
    if not times:
        raise ValueError('No measured speech timestamps')
    source = visible(text)
    indices = [None] * len(source)
    for tag, a, b, c, d in difflib.SequenceMatcher(None, source, recognized, autojunk=False).get_opcodes():
        for i in range(a, b):
            indices[i] = min(len(times) - 1, c + int((i-a) * max(d-c, 1) / max(b-a, 1)))
    return source, [times[i] for i in indices]


def ass_time(seconds):
    n = round(seconds * 100)
    return f'{n//360000}:{n//6000%60:02}:{n//100%60:02}.{n%100:02}'


def render_shot_preview(folder, shot_id, preview_path, authorization, clean_plate=None):
    """Caption one registered speed preview; approval and its raw source stay unchanged."""
    folder, preview_path = folder.resolve(), preview_path.resolve()
    if not authorization or not authorization.strip():
        raise ValueError('Record the user caption request in --authorization')
    if clean_plate is None:
        raise ValueError('Provide --clean-plate from an inspected caption-free frame; do not add a solid subtitle bar')
    clean_plate = Path(clean_plate).resolve()
    if not clean_plate.is_relative_to(folder) or not clean_plate.is_file():
        raise ValueError('The inspected background frame must be inside this run')
    manifest, script = locked(folder)
    if shot_id not in manifest['shots']:
        raise ValueError('Shot is not part of the locked run')
    record = read(folder/f'{shot_id}.json')
    parent = preview_asset(folder, manifest, record, preview_path)
    source = Path(parent['video'])
    if read(preview_path).get('caption_render'):
        raise ValueError('Use the uncaptioned speed preview as input')
    transcript_path = folder/f'{shot_id}.transcript.json'
    transcript = read(transcript_path)
    raw_packet = read(Path(record['review_packet']))
    if (Path(transcript['audio']).resolve() != (Path(record['review_packet']).parent/raw_packet['audio']).resolve()
            or raw_packet['source_sha256'] != record['video_sha256']):
        raise ValueError('Caption timestamps must belong to this original clip')
    shot = next(s for s in script['shots'] if s['shot_id'] == shot_id)
    _, stamps = speech_map(shot['dialogue'], transcript['result'])
    output = source.with_name(source.stem+'.overlay.mp4')
    audit_path = output.with_suffix('.json')
    if output.exists() or audit_path.exists():
        raise ValueError('Caption preview already exists; inspect it instead of overwriting')
    media = probe(source)
    stream = next(s for s in media['streams'] if s['codec_type'] == 'video')
    w, h = stream['width'], stream['height']
    # This fixed-camera composition was inspected: lettering is below hands/book.
    top, height = round(h*.805), round(h*.125)
    font_size = round(w*32/496)
    patch_x, patch_y = round(w*28/496), round(h*690/864)
    patch_w, patch_h = round(w*440/496), round(h*116/864)
    feather = max(2, round(w*12/496))
    from PIL import Image
    with Image.open(clean_plate) as plate:
        if plate.size != (w,h):
            raise ValueError('Background frame must match the video dimensions')
    ass = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {w}', f'PlayResY: {h}',
        'WrapStyle: 2', '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        f'Style: Dialogue,SimSun,{font_size},&H00FFFFFF,&H00FFFFFF,&H00303030,&H70303030,0,0,0,0,100,100,0,0,1,1.2,0.4,5,20,20,0,1',
        '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    cues, cursor = [], 0
    speed, duration = parent['speed'], parent['actual_duration_seconds']
    for chunk in caption_chunks(shot['dialogue'], limit=16):
        count = len(visible(chunk))
        begin = max(0, stamps[cursor][0]/1000/speed-.08)
        finish = min(duration, stamps[cursor+count-1][1]/1000/speed+.08)
        cursor += count
        if cursor < len(stamps):
            finish = min(finish, max(begin+.01, stamps[cursor][0]/1000/speed-.08))
        if finish <= begin:
            raise ValueError('Invalid caption cue; inspect measured speech timings')
        ass.append(f'Dialogue: 0,{ass_time(begin)},{ass_time(finish)},Dialogue,,0,0,0,,{{\\pos({w//2},{top+height//2})}}{chunk}')
        cues.append({'text':chunk, 'start':begin, 'end':finish})
    ass_file = output.with_suffix('.ass')
    ass_file.write_text('\n'.join(ass), encoding='utf-8-sig')
    alpha = f'255*min(1,min(min(X/{feather},(W-1-X)/{feather}),min(Y/{feather},(H-1-Y)/{feather})))'
    filters = (f"[1:v]crop={patch_w}:{patch_h}:{patch_x}:{patch_y},format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'[background];"
        f'[0:v][background]overlay={patch_x}:{patch_y}:format=auto,ass={ass_file.name}[v]')
    subprocess.run(['ffmpeg','-hide_banner','-v','error','-n','-i',source.name,
        '-i',str(clean_plate),'-filter_complex',filters,'-map','[v]','-map','0:a:0',
        '-fps_mode','vfr','-enc_time_base:v','1:24000',
        '-c:v','libx264','-crf','18','-preset','fast','-c:a','copy',
        '-movflags','+faststart',output.name], cwd=folder, check=True, capture_output=True)
    def audio_hash(video):
        return subprocess.check_output(['ffmpeg','-v','error','-i',str(video),
            '-map','0:a:0','-c','copy','-f','streamhash','-hash','sha256','-']).decode().strip()
    final = probe(output)
    audio_digest = audio_hash(source)
    if (audio_digest != audio_hash(output)
            or next(s['nb_frames'] for s in final['streams'] if s['codec_type']=='video') != stream['nb_frames']
            or abs(float(final['format']['duration'])-duration) > .05):
        raise ValueError('Captioning changed audio, frame count or duration; inspect before proceeding')
    report = dict(read(preview_path), video=str(output), video_sha256=sha(output),
        actual_duration_seconds=float(final['format']['duration']), created_at=datetime.now(timezone.utc).isoformat(),
        authorization=authorization, review_status='pending', preview_only=True,
        parent_preview=str(preview_path), parent_preview_sha256=sha(preview_path),
        caption_render={'source_video':str(source),'source_video_sha256':sha(source),
            'source_transcript':str(transcript_path),'transcript_sha256':sha(transcript_path),
            'caption_source':'locked_script.dialogue','timing':'original ASR timestamps divided by playback speed',
            'cues':cues,'ass':str(ass_file),'style':'white_text_thin_outline_no_box',
            'background_restore':{'method':'feathered_patch_from_inspected_caption_free_frame',
                'image':str(clean_plate),'image_sha256':sha(clean_plate),
                'x':patch_x,'y':patch_y,'width':patch_w,'height':patch_h,'feather_pixels':feather,
                'scope':'字幕下方桌面背景；不修改人物、手或道具；背景取样区域不保留该区域的原生反射运动'},
            'audio':'stream_copy','audio_stream_sha256':audio_digest,
            'dialogue_completeness':'pending_user_listening; correct captions do not establish spoken completeness'})
    report.pop('actual_review',None)
    report['review_packet'] = str(build_review_packet(folder,output,report['video_sha256'],manifest['script_sha256']))
    write(output.with_suffix('.probe.json'),final)
    write(audit_path,report)
    manifest.setdefault('speed_previews',{}).setdefault(shot_id,{})[f'{speed}_overlay'] = str(audit_path)
    manifest['latest_speed_preview'] = str(output)
    manifest['subtitle_style'] = 'white_text_thin_outline_no_box'
    write(folder/'production.json',manifest)
    return {'video':str(output),'duration':report['actual_duration_seconds'],'speed':speed,
            'review_packet':report['review_packet'],'status':'pending','video_generation_submitted':False}


def render(folder):
    folder = folder.resolve()
    manifest, script = locked(folder)
    if manifest.get('subtitle_style') == 'white_text_thin_outline_no_box':
        raise ValueError('This run uses approved per-shot overlay subtitles; merge those deliveries instead of applying the legacy solid-bar renderer')
    original = folder / 'short_45s_candidate.mp4'
    if not original.is_file():
        raise ValueError('Merge verified shots first')
    expected = manifest.get('original_merged_sha256', manifest.get('final_sha256'))
    if sha(original) != expected:
        raise ValueError('Original merged video changed')
    media = probe(original)
    stream = next(s for s in media['streams'] if s['codec_type'] == 'video')
    w, h = stream['width'], stream['height']
    # Reviewed native lettering occupies the lower table area, below hands and props.
    top = int(h * .75)
    ass = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {w}', f'PlayResY: {h}',
           'WrapStyle: 2', '[V4+ Styles]',
           'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
           'Style: Dialogue,Microsoft YaHei,30,&H00F5F5F2,&H00F5F5F2,&H0019222D,&H0019222D,0,0,0,0,100,100,0,0,1,0,0,5,28,28,0,1',
           'Style: Role,Microsoft YaHei,18,&H008CBADE,&H008CBADE,&H0019222D,&H0019222D,0,0,0,0,100,100,0,0,1,0,0,7,28,28,0,1',
           '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    offset, cues, source_audit = 0., [], []
    for shot in script['shots']:
        sid = shot['shot_id']
        record = read(folder / f'{sid}.json')
        if sha(Path(record['local_video'])) != record['video_sha256']:
            raise ValueError('Source clip changed')
        duration = record['actual_duration_seconds']
        _, stamps = speech_map(shot['dialogue'], read(folder/f'{sid}.transcript.json')['result'])
        start, end = ass_time(offset), ass_time(offset + duration)
        ass.append(f'Dialogue: 0,{start},{end},Role,,0,0,0,,{{\\pos(28,{top+25})}}{shot["dialogue_speaker"]}')
        cursor = 0
        for chunk in caption_chunks(shot['dialogue']):
            count = len(visible(chunk))
            begin = max(0, stamps[cursor][0]/1000 - .10)
            finish = min(duration, stamps[cursor+count-1][1]/1000 + .10)
            cursor += count
            if cursor < len(stamps):
                finish = min(finish, max(begin+.01, stamps[cursor][0]/1000-.10))
            if finish <= begin:
                raise ValueError('Invalid caption cue timing')
            lines = chunk if len(chunk) <= 15 else chunk[:15] + r'\N' + chunk[15:]
            ass.append(f'Dialogue: 1,{ass_time(offset+begin)},{ass_time(offset+finish)},Dialogue,,0,0,0,,{{\\pos({w//2},{top+112})}}{lines}')
            cues.append({'shot': sid, 'start': offset+begin, 'end': offset+finish, 'text': chunk})
        source_audit.append({'shot': sid, 'sha256': record['video_sha256'], 'duration': duration})
        offset += duration
    ass_file = folder/'locked_captions.ass'
    ass_file.write_text('\n'.join(ass), encoding='utf-8-sig')
    output = folder/'short_45s_review.mp4'
    filter_text = f'drawbox=x=0:y={top}:w=iw:h=ih-{top}:color=0x14202D:t=fill,ass=locked_captions.ass'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',original.name,
                    '-vf',filter_text,'-c:v','libx264','-crf','18','-preset','fast',
                    '-c:a','copy','-movflags','+faststart',output.name],cwd=folder,check=True,capture_output=True)
    final = probe(output)
    if abs(float(final['format']['duration'])-float(media['format']['duration'])) > .05:
        raise ValueError('Caption rendering changed duration')
    audit = {'schema':'script_video_caption_render/v1','completed_at':datetime.now(timezone.utc).isoformat(),
             'script_sha256':manifest['script_sha256'],'original_video':str(original),'original_sha256':sha(original),
             'output':str(output),'output_sha256':sha(output),'audio':'stream_copy',
             'caption_source':'locked_script.dialogue','timing':'local_asr_character_alignment',
             'mask':{'y':top,'height':h-top,'reason':'Cover incorrect generated lettering in reviewed table area'},
             'sources':source_audit,'cues':cues,'duration':float(final['format']['duration'])}
    write(folder/'caption_render.json', audit)
    write(folder/'review_video.probe.json', final)
    manifest.update(merged_video_original=str(original),original_merged_sha256=sha(original),
                    merged_video=str(output),final_sha256=sha(output),caption_report=str(folder/'caption_render.json'),
                    caption_completed_at=audit['completed_at'],review_result='pending',
                    subtitle_note='字幕逐字取自锁定剧本，按本地语音时间对齐；覆盖模型原生错字，保留原始无剪辑合并版。')
    write(folder/'production.json',manifest)
    review_packet(folder)
    return {'video':str(output),'duration':audit['duration'],'cues':len(cues),'audio':'copied'}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--shot')
    parser.add_argument('--preview-audit',type=Path)
    parser.add_argument('--authorization')
    parser.add_argument('--clean-plate',type=Path,help='已检查、无字幕、与视频尺寸一致的本批背景帧')
    args = parser.parse_args()
    if args.shot or args.preview_audit:
        if not args.shot or not args.preview_audit:
            parser.error('--shot and --preview-audit must be provided together')
        result = render_shot_preview(args.run_dir,args.shot,args.preview_audit,args.authorization,args.clean_plate)
    else:
        result = render(args.run_dir)
    print(json.dumps(result,ensure_ascii=False))
