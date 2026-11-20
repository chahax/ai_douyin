"""Small CPU checks; no downloaded neural weights or production frames used."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('subtitle_cpu_repair',ROOT/'scripts/repair_h3_s02_subtitles_cpu_v1.py')
repair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def test_character_row_mask_and_paste_only_inside_mask():
    image=np.full((1312,736,3),42,np.uint8)
    cv2.putText(image,'SUBTITLE TEST 123',(140,988),cv2.FONT_HERSHEY_SIMPLEX,1.2,(0,0,0),7,cv2.LINE_AA)
    cv2.putText(image,'SUBTITLE TEST 123',(140,988),cv2.FONT_HERSHEY_SIMPLEX,1.2,(255,255,255),3,cv2.LINE_AA)
    after,mask,stats=repair.process(image,repair.DEFAULT,lambda rgb,mask:np.full_like(rgb,80))
    assert 0<np.count_nonzero(mask)<736*256*.2
    assert stats['selected_components']>=5
    assert stats['mask_outside_changed_pixels_before_encode']==0
    assert stats['HSV_white_pixels_after_inside_mask']<stats['HSV_white_pixels_before_inside_mask']
    entire=np.zeros((1312,736),bool);entire[832:1088]=mask>0
    assert np.array_equal(image[~entire],after[~entire])
    interpolated,_,telea_stats=repair.process(image,repair.DEFAULT,lambda rgb,mask:repair.telea_context(rgb,mask,3))
    assert telea_stats['mask_outside_changed_pixels_before_encode']==0
    assert np.array_equal(image[~entire],interpolated[~entire])


@pytest.mark.parametrize('large_white',[False,True])
def test_blank_or_large_garment_is_not_a_character_row(large_white):
    image=np.full((1312,736,3),42,np.uint8)
    if large_white:image[940:1016,100:650]=255
    def forbidden(*args):raise AssertionError('no model should be called')
    after,mask,stats=repair.process(image,repair.DEFAULT,forbidden)
    assert np.count_nonzero(mask)==0
    assert stats['model_called'] is False
    assert np.array_equal(image,after)


def test_original_AAC_packet_hash_survives_video_reencode(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('local CPU FFmpeg required')
    source,target=tmp_path/'synthetic.mp4',tmp_path/'synthetic_reencoded.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=gray:s=64x96:r=24:d=2',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=32000:duration=2','-c:v','libx264',
                    '-preset','ultrafast','-threads','1','-c:a','aac','-ac','2',str(source)],check=True,capture_output=True,timeout=30)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source),'-map','0:v:0','-map','0:a:0',
                    '-c:v','libx264','-preset','ultrafast','-threads','1','-c:a','copy',str(target)],
                   check=True,capture_output=True,timeout=30)
    assert repair.audio_packets(source)==repair.audio_packets(target)


def test_CPU_JIT_image_mask_interface_with_tiny_synthetic_fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES','')
    import torch
    class SyntheticMaskFixture(torch.nn.Module):
        def forward(self,image,mask):return image*(1-mask)+.5*mask
    traced=torch.jit.trace(SyntheticMaskFixture(),(torch.zeros(1,3,16,24),torch.zeros(1,1,16,24)))
    path=tmp_path/'SYNTHETIC_NOT_LAMA.pt';traced.save(str(path))
    model=repair.CpuLama(path,1)
    image=np.zeros((16,24,3),np.uint8);mask=np.zeros((16,24),np.uint8);mask[4:8,5:9]=255
    result=model(image,mask)
    assert result.shape==image.shape and result.dtype==np.uint8
    assert np.array_equal(result[mask==0],image[mask==0])
    assert np.all(result[mask>0]==128)
    # Explicit Telea setup must not require, load or invent a missing weight.
    monkeypatch.setattr(repair,'PROJECT',tmp_path)
    source=tmp_path/repair.SOURCE_REL;source.parent.mkdir(parents=True)
    source.write_bytes(b'not_a_native_video_fixture')
    monkeypatch.setattr(repair,'SOURCE_SHA',repair.bind(source)['sha256'])
    (source.parent.parent/'RESULT.json').write_text(json.dumps(dict(
        prompt_id='96fce6ce-531d-488c-8b30-3182c9944ffd',technical_status='technical_saved',
        files=dict(video=repair.bind(source)))),encoding='utf-8')
    _,_,case,config=repair.setup(tmp_path/repair.ROOT_REL,tmp_path/'MISSING.pt',repair.DEFAULT,method='telea')
    assert config['weights'] is None and config['method']=='telea' and config['telea_radius']==3
    assert config['spatial_interpolation_can_smear_background'] is True
