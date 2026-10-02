"""Merge downloaded clips without synthesizing sound; make a visual review sheet."""
import json
import subprocess
from jimeng_continuity_test import RUN


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def main():
    inputs = [RUN / f'S0{i}.mp4' for i in range(1, 4)]
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    for path in inputs:
        args += ['-i', str(path)]
    args += ['-filter_complex', '[0:v:0][0:a:0][1:v:0][1:a:0][2:v:0][2:a:0]concat=n=3:v=1:a=1[v][a]',
             '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
             '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(RUN / 'continuity_15s.mp4')]
    run(*args)
    for i, path in enumerate(inputs, 1):
        run('ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path),
            '-vf', 'fps=2,scale=270:-1,tile=5x2', '-frames:v', '1', str(RUN / f'S0{i}_frames.jpg'))
    run('ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(RUN / 'S01_frames.jpg'), '-i', str(RUN / 'S02_frames.jpg'), '-i', str(RUN / 'S03_frames.jpg'),
        '-filter_complex', '[0:v][1:v][2:v]vstack=inputs=3', '-frames:v', '1', str(RUN / 'continuity_contact_sheet.jpg'))
    probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(RUN / 'continuity_15s.mp4')])
    (RUN / 'merged_probe.json').write_bytes(probe)
    print(json.dumps({'merged': str(RUN / 'continuity_15s.mp4'), 'contact_sheet': str(RUN / 'continuity_contact_sheet.jpg')}))


if __name__ == '__main__':
    main()
