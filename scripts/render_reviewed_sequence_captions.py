"""Transparent subtitles for this approved sequence, retaining native audio."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_script_video import locked, read, sha, write, probe
from scripts.render_script_video_captions import speech_map, caption_chunks, visible, ass_time
from scripts.render_clean_script_captions import audio_hash
from src.content_factory import video_campaign
from src.content_factory.script_video_review import build_review_packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--alignment-review', required=True)
    args = parser.parse_args()
    folder = Path(args.run_dir).resolve()
    manifest, script = locked(folder)
    video_campaign.require_approved_segments(folder, manifest)
    source = Path(manifest['merged_video'])
    if sha(source) != manifest['final_sha256']:
        raise ValueError('Merged source changed')
    reviewed = read(Path(args.alignment_review))
    output = folder/'short_45s_complete.mp4'
    if output.exists():
        raise ValueError('Keep existing output; do not overwrite')
    ass = folder/'complete_captions.ass'
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 496
PlayResY: 864
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,Microsoft YaHei,26,&H00FFFFFF,&H00FFFFFF,&H00151515,&HFF000000,0,0,0,0,100,100,0,0,1,1.2,0,2,24,24,90,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines, cues, cuts, offset = [], [], [], 0.0
    for shot in script['shots']:
        sid = shot['shot_id']
        receipt = read(folder/f'{sid}.json')
        transcript_path = folder/f'{sid}.local_asr.json'
        transcript = read(transcript_path)
        approval = reviewed['shots'][sid]
        if (approval['video_sha256'] != receipt['video_sha256']
                or approval['transcript_sha256'] != sha(transcript_path)
                or approval.get('caption_text') != shot['dialogue']
                or not approval.get('notes')):
            raise ValueError('Explicit measured caption alignment review required')
        _, stamps = speech_map(shot['dialogue'], transcript['result'])
        duration = receipt['actual_duration_seconds']
        cursor = 0
        if offset:
            cuts.append(dict(time=offset, to=sid, **{'from':script['shots'][len(cuts)]['shot_id']}))
        for chunk in caption_chunks(shot['dialogue'], limit=16):
            count = len(visible(chunk))
            start = max(0, stamps[cursor][0]/1000-.06)
            end = min(duration, stamps[cursor+count-1][1]/1000+.08)
            cursor += count
            if cursor < len(stamps):
                end = min(end, stamps[cursor][0]/1000-.02)
            if not 0 <= start < end <= duration:
                raise ValueError('Invalid caption interval')
            start += offset; end += offset
            cues.append(dict(shot=sid,start=start,end=end,text=chunk))
            lines.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Dialogue,,0,0,0,,{chunk}')
        # The project merger resamples each video to 30 fps, and concat uses the
        # longest stream. Probe the exact input lengths used in that merger.
        media = probe(Path(receipt['local_video']))
        video_stream = next(s for s in media['streams'] if s['codec_type']=='video')
        audio_stream = next(s for s in media['streams'] if s['codec_type']=='audio')
        import math
        offset += max(math.ceil(float(video_stream['duration'])*30-1e-6)/30, float(audio_stream['duration']))
    ass.write_text(header+'\n'.join(lines)+'\n', encoding='utf-8-sig')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-n','-i',str(source),
        '-vf',f'ass={ass.name}','-c:v','libx264','-crf','18','-preset','fast',
        '-c:a','copy','-movflags','+faststart',str(output)],cwd=folder,check=True)
    if audio_hash(source) != audio_hash(output):
        raise ValueError('Caption render changed the audio stream')
    packet = build_review_packet(folder, output, sha(output),manifest['script_sha256'],cuts)
    write(folder/'complete_caption_render.json', dict(source=str(source),source_sha256=sha(source),
        video=str(output),video_sha256=sha(output),audio_stream_unchanged=True,
        caption_style='transparent white text thin outline, no background box',
        alignment_review=str(Path(args.alignment_review).resolve()),cues=cues,cuts=cuts,
        review_packet=str(packet),review_status='pending'))
    print(json.dumps({'video':str(output),'review_packet':str(packet)},ensure_ascii=False))


if __name__ == '__main__':
    main()
