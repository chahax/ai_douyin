"""Join original video packets on their video timeline; normalize audio endpoints."""
from pathlib import Path
import json
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_six_children_minute_20261102 as runner

def assemble(run):
    plan=runner.validate(run);state=runner.read(run/'STATE.json')
    paths=[];durations=[];summary=[]
    for shot in plan['shots']:
        row=state['segments'].get(shot['id'],{})
        if row.get('status')!='complete':raise ValueError('segments_incomplete')
        path=run/'segments'/shot['id']/'video.mp4'
        if runner.sha(path)!=row['video']['sha256']:raise ValueError('video_changed')
        meta=runner.metadata(path)
        video=next(s for s in meta['streams'] if s['codec_type']=='video')
        audio=next(s for s in meta['streams'] if s['codec_type']=='audio')
        if video['r_frame_rate']!='24/1' or video['width']!=720 or video['height']!=1280:raise ValueError('incompatible_video')
        duration=float(video['duration']);paths.append(path);durations.append(duration)
        summary.append(dict(segment=shot['id'],video_seconds=duration,audio_seconds=float(audio['duration']),frame_count=int(video['nb_frames'])))
    output=run/'deliverables/six_children_opening_60s_review.mp4'
    if output.exists():raise ValueError('assembly_already_exists')
    listing=run/'concat_video_timeline.txt'
    listing.write_text(''.join("file '"+p.resolve().as_posix()+"'\nduration "+f'{d:.6f}'+"\n" for p,d in zip(paths,durations)),encoding='utf-8')
    command=['ffmpeg','-nostdin','-v','warning','-f','concat','-safe','0','-i',str(listing)]
    for path in paths:command+=['-i',str(path)]
    filters=[f'[{i+1}:a:0]aresample=48000,apad,atrim=duration={d:.6f},asetpts=PTS-STARTPTS[a{i}]' for i,d in enumerate(durations)]
    filters+=[''.join(f'[a{i}]' for i in range(len(paths)))+f'concat=n={len(paths)}:v=0:a=1[audio]']
    command+=['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[audio]','-c:v','copy','-c:a','aac','-b:a','160k','-movflags','+faststart',str(output)]
    runner.durable(run/'ASSEMBLY_COMMAND.json',command,immutable=True)
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    (run/'assembly.stderr.log').write_text(result.stderr,encoding='utf-8');result.check_returncode()
    metadata=runner.metadata(output)
    video=next(s for s in metadata['streams'] if s['codec_type']=='video')
    if int(video['nb_frames'])!=sum(s['frame_count'] for s in summary):raise ValueError('frame_count_mismatch')
    if abs(float(video['duration'])-sum(durations))>1/24:raise ValueError('video_timeline_mismatch')
    runner.durable(run/'DELIVERY.json',dict(video=runner.binding(output),metadata=metadata,segments=summary,
        content_status='awaiting_human_review',video_content_reviewed=False,original_video_packets_preserved=True,
        audio_processing='Each audio stream padded/trimmed to its own video endpoint; concatenated and encoded as continuous AAC 48kHz. No speech recognition or listening.',
        assembly_script=runner.binding(__file__)),immutable=True)
    state.update(status='delivered_awaiting_human_review',delivery=str(output.resolve()))
    runner.durable(run/'STATE.json',state);runner.event(run,'ASSEMBLED native video packets on continuous video timeline; audio endpoints aligned; awaiting_human_review')
    print(json.dumps(dict(path=str(output.resolve()),duration=metadata['format']['duration'],frames=video['nb_frames']),ensure_ascii=False))

if __name__=='__main__':assemble(Path(sys.argv[1]))
