import json
from pathlib import Path

import httpx
import pytest

from src.content_factory.seedance_client import SeedanceClient,SeedanceConfig,SeedanceReference,SeedanceAPIError,ARK_BASE_URL
from src.content_factory.seedance_models import load_catalog

MINI='doubao-seedance-2-0-mini-260615'
FAST='doubao-seedance-2-0-fast-260128'
STANDARD='doubao-seedance-2-0-260128'
V25='doubao-seedance-2-5-260628'


def client(model):
    return SeedanceClient(SeedanceConfig(api_key='test-secret',base_url=ARK_BASE_URL,model=model,provider='ark_api'))


@pytest.mark.parametrize('model,duration,resolution,fmt',[(MINI,15,'480p','mp4'),(FAST,-1,'720p','mp4'),(STANDARD,15,'4k','mp4'),(V25,30,'1080p','mov')])
def test_all_documented_models_build_distinct_requests(model,duration,resolution,fmt):
    with client(model) as c:
        p=c.build_task_payload('已审核的提示词',duration=duration,resolution=resolution,output_format=fmt)
    assert p['model']==model and p['duration']==duration and p['resolution']==resolution
    assert p.get('output_format')==('mov' if model==V25 else None)


@pytest.mark.parametrize('model,duration,resolution,fmt',[(MINI,16,'480p',None),(FAST,6,'1080p',None),(V25,31,'480p',None),(V25,6,'4k',None),(MINI,6,'480p','mov')])
def test_invalid_model_parameters_fail_before_network(model,duration,resolution,fmt):
    with client(model) as c,pytest.raises(ValueError):
        c.build_task_payload('prompt',duration=duration,resolution=resolution,output_format=fmt)


def test_v25_edit_extend_and_frame_constraints():
    video=SeedanceReference('video','https://example.com/video.mp4','reference_video')
    first=SeedanceReference('image','https://example.com/first.png','first_frame')
    last=SeedanceReference('image','https://example.com/last.png','last_frame')
    with client(V25) as c:
        with pytest.raises(ValueError,match='ratio=adaptive'):
            c.build_task_payload('编辑视频1',duration=-1,task_type='edit',references=[video])
        with pytest.raises(ValueError,match='duration=-1'):
            c.build_task_payload('编辑视频1',duration=6,ratio='adaptive',task_type='edit',references=[video])
        p=c.build_task_payload('编辑视频1',duration=-1,ratio='adaptive',task_type='edit',references=[video],output_format='mov')
        assert p['omni_reference_task_type']=='edit' and p['output_format']=='mov'
        p=c.build_task_payload('向后延长视频1',duration=10,ratio='adaptive',task_type='extend',references=[video])
        assert p['omni_reference_task_type']=='extend'
        with pytest.raises(ValueError,match='ratio=adaptive'):
            c.build_task_payload('动作推进',duration=6,references=[first,last])
        p=c.build_task_payload('动作推进',duration=6,ratio='adaptive',task_type='first_last_frame',references=[first,last])
        assert [r.get('role') for r in p['content'][1:]]==['first_frame','last_frame']
        with pytest.raises(ValueError,match='without mixed'):
            c.build_task_payload('prompt',duration=6,ratio='adaptive',references=[first,video])


def test_reference_limits_and_audio_only_differ_by_family():
    audio=SeedanceReference('audio','https://example.com/a.mp3','reference_audio')
    images=[SeedanceReference('image',f'https://example.com/{i}.png','reference_image') for i in range(30)]
    with client(MINI) as c:
        with pytest.raises(ValueError,match='combined'):
            c.build_task_payload('参考音色',duration=6,references=[audio])
        with pytest.raises(ValueError,match='count exceeds'):
            c.build_task_payload('参考外貌',duration=6,references=images[:10])
    with client(V25) as c:
        c.build_task_payload('参考音色',duration=6,references=[audio])
        c.build_task_payload('参考外貌',duration=6,references=images)
        with pytest.raises(ValueError,match='count exceeds'):
            c.build_task_payload('参考外貌',duration=6,references=images+[images[0]])


def test_explicit_cli_model_changes_only_this_preview(tmp_path):
    from scripts.seedance_generate import main
    pack={'schema':'analysis_video_prompt_pack/v1','segments':[{'id':'S01','source':{'shot_number':'S01'},'generation':{'duration_seconds':6},'prompts':{'video_prompt_zh':'参考视频1的动作，创建新镜头'}}]}
    path=tmp_path/'pack.json';path.write_text(json.dumps(pack),encoding='utf-8')
    main([str(path),'--segment','S01','--provider','ark_api','--model',V25,'--duration','20','--output-format','mov','--output-dir',str(tmp_path)])
    report=json.loads((tmp_path/'S01.seedance.json').read_text(encoding='utf-8'))
    assert report['mode']=='dry-run' and report['request']['model']==V25
    assert load_catalog()['preferred']['model']==MINI


def test_http_rejections_preserve_structured_code_and_redact_key():
    transport=httpx.MockTransport(lambda req:httpx.Response(404,json={'error':{'code':'ModelNotOpen','message':'test-secret must not leak'}}))
    with httpx.Client(transport=transport) as http:
        c=SeedanceClient(SeedanceConfig(api_key='test-secret',base_url=ARK_BASE_URL,model=MINI,provider='ark_api'),http_client=http)
        with pytest.raises(SeedanceAPIError) as caught:c.create_task(c.build_task_payload('prompt',duration=6))
    assert caught.value.status_code==404 and caught.value.error_code=='ModelNotOpen'
    assert 'test-secret' not in str(caught.value)
