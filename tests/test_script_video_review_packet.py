import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.content_factory.script_video_review import build_review_packet, file_sha
from scripts.run_script_video import query, read, write
from test_script_video_run import setup_run


@pytest.fixture
def source_video(tmp_path):
    path = tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-v','error','-y',
                    '-f','lavfi','-i','color=c=red:s=320x480:r=10:d=1',
                    '-f','lavfi','-i','color=c=blue:s=320x480:r=10:d=1',
                    '-f','lavfi','-i','sine=frequency=440:duration=2',
                    '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
                    '-map','[v]','-map','2:a','-c:v','libx264','-c:a','aac',str(path)],check=True)
    return path


def test_real_frames_bracket_cut_and_never_auto_approve(tmp_path, source_video):
    cuts=[{'time':1.,'from':'S01','to':'S02'}]
    packet_path=build_review_packet(tmp_path,source_video,file_sha(source_video),'script',cuts)
    packet=read(packet_path)
    assert packet['first_frame_index']==0 and packet['last_frame_index']==19
    assert packet['frames'][0]['time_seconds']==0 and packet['frames'][-1]['time_seconds']==1.9
    assert packet['review_status']=='pending' and packet['automated_visual_or_voice_verdict'] is False
    by_index={f['frame_index']:f for f in packet['frames']}
    ids=packet['boundaries'][0]['frame_indices']
    assert any(by_index[i]['time_seconds']<1 for i in ids)
    assert any(by_index[i]['time_seconds']>=1 for i in ids)
    with Image.open(packet_path.parent/packet['frames'][0]['file']) as image:
        assert image.getpixel((160,240))[0]>200
    with Image.open(packet_path.parent/packet['frames'][-1]['file']) as image:
        assert image.getpixel((160,240))[2]>200
    assert (packet_path.parent/packet['boundaries'][0]['audiovisual_excerpt']).stat().st_size>0
    template=packet_path.parent/'review.template.json'
    assert all(v is None for v in read(template)['checks'].values())
    template.write_text('{"decision":"failed","notes":"review must survive"}')
    assert build_review_packet(tmp_path,source_video,file_sha(source_video),'script',cuts)==packet_path
    assert read(template)['decision']=='failed'
    (packet_path.parent/packet['frames'][0]['file']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='evidence changed'):
        build_review_packet(tmp_path,source_video,file_sha(source_video),'script',cuts)


def test_downloaded_query_does_not_extract_evidence_or_clear_rejection(tmp_path,source_video):
    folder=setup_run(tmp_path)
    video=folder/'S01.mp4';shutil.copyfile(source_video,video)
    write(folder/'S01.json',{'shot':'S01','status':'downloaded','local_video':str(video),'video_sha256':file_sha(video)})
    manifest=read(folder/'production.json');manifest['review_result']='failed';write(folder/'production.json',manifest)
    class NoNetwork:
        def get_task(self,*args):raise AssertionError('Local review must not call the provider')
    query(folder,'S01',NoNetwork())
    record=read(folder/'S01.json')
    assert 'review_packet' not in record
    assert not (folder/'review_packets').exists()
    assert read(folder/'production.json')['review_result']=='failed'
    with pytest.raises(ValueError,match='unchanged'):
        build_review_packet(folder,source_video,file_sha(source_video),'script')
