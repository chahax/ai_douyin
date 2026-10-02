import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from script_pair_fixture import pair_payload
from test_script_pair import parse
from src.content_factory.conversation_direction import (stage_for, camera_for, validate_plan,
    compile_prompt, require_reviewed_reference, file_hash, CHECKS, generate_plan)
from scripts.run_script_video import prepare, submit, write, locked, review_reference
from test_script_video_run import Client


def setup(tmp_path):
    script=asdict(parse(pair_payload())[0])
    script['characters']=list(script['characters'])
    script['characters'].append({**script['characters'][0],'name':'咨询员'})
    for i,shot in enumerate(script['shots']):
        shot['participants']=['当事人','咨询员'] if i==0 else ['当事人']
        shot['model_prompt_zh']='旧的并排座位和缓慢等待提示不得沿用'
    path=tmp_path/'script.json'
    write(path,script)
    path.with_suffix('.md').write_text('storyboard')
    path.with_suffix('.audit.json').write_text('{}')
    stage=stage_for(script,'当事人','咨询员')
    plan={'schema':'conversation_direction/v1','script_sha256':file_hash(path),'stage':stage,'shots':[
        {'shot_id':s['shot_id'],'camera_id':camera_for(s,stage),'dialogue_start_seconds':0.2,
         'start_frame':'食指按住自己桌边材料','end_frame':'手放回原位',
         'performance':'专注、动作利落','transition':'动作收势后切镜',
         'action_beats':[{'start':0,'end':s['end_seconds']-s['start_seconds'],'action':'迅速核对材料，视线跟随证据移动'}]}
        for s in script['shots']]}
    plan_path=tmp_path/'plan.json';write(plan_path,plan)
    return script,path,plan,plan_path


@pytest.mark.parametrize('defect',['seat','camera','late_speech','idle','speech_in_action'])
def test_direction_rejects_spatial_and_pacing_defects(tmp_path,defect):
    script,path,plan,_=setup(tmp_path)
    if defect=='seat':plan['stage']['seats']['咨询员']=[1,1]
    if defect=='camera':plan['stage']['cameras']['master']['position']=[3,0]
    if defect=='late_speech':plan['shots'][0]['dialogue_start_seconds']=2.5
    if defect=='idle':plan['shots'][0]['action_beats'][0]['start']=1
    if defect=='speech_in_action':plan['shots'][0]['action_beats'][0]['action']='第三秒才开口'
    with pytest.raises(ValueError):validate_plan(plan,script,file_hash(path))


def test_compiler_keeps_original_dialogue_but_replaces_inconsistent_camera_prompt(tmp_path):
    script,path,plan,_=setup(tmp_path)
    validate_plan(plan,script,file_hash(path))
    prompt=compile_prompt(script,script['shots'][0],plan)
    assert script['shots'][0]['dialogue'] in prompt
    assert '旧的并排座位和缓慢等待提示不得沿用' not in prompt
    assert '桌面横隔在两人之间' in prompt and '第0.2秒' in prompt
    ordered=compile_prompt(script,script['shots'][0],plan,timing_mode='ordered')
    assert '动作1：' in ordered and '第0.2秒' not in ordered
    assert script['shots'][0]['dialogue'] in ordered
    framed=compile_prompt(script,script['shots'][0],plan,timing_mode='ordered',use_input_first_frame=True)
    assert f"首帧：{plan['shots'][0]['start_frame']}。" not in framed
    assert '从该姿态立即执行动作1' in framed
    assert script['shots'][0]['dialogue'] in framed
    shot = dict(script['shots'][0], continuity='旧稿首态：合同平放，手指仍压在签名上')
    framed = compile_prompt(script,shot,plan,timing_mode='ordered',use_input_first_frame=True)
    assert '旧稿首态' not in framed
    assert '以输入首帧的实际手位、道具开合和位置为起点' in framed
    assert plan['shots'][0]['end_frame'] in framed
    assert plan['shots'][0]['action_beats'][0]['action'] in framed
    assert shot['continuity'] in compile_prompt(script,shot,plan)


def test_exact_point_four_second_gap_is_not_rejected_by_float_rounding(tmp_path):
    script,path,plan,_=setup(tmp_path)
    duration=script['shots'][0]['end_seconds']-script['shots'][0]['start_seconds']
    plan['shots'][0]['action_beats'][0]['end']=duration-0.4
    validate_plan(plan,script,file_hash(path))
    plan['shots'][0]['action_beats'][0]['end']=duration-0.401
    with pytest.raises(ValueError,match='trailing hold'):
        validate_plan(plan,script,file_hash(path))


def test_two_person_prepare_requires_plan_and_locks_it(tmp_path):
    _,path,_,plan_path=setup(tmp_path)
    folder=tmp_path/'run'
    with pytest.raises(ValueError,match='固定座位'):prepare(folder,path,'test')
    prepare(folder,path,'test',plan_path)
    (folder/'direction_plan.json').write_text('{}')
    with pytest.raises(ValueError,match='direction plan changed'):locked(folder)


def test_bad_reference_never_reaches_paid_client(tmp_path):
    _,path,_,plan_path=setup(tmp_path)
    folder=(tmp_path/'run').resolve();prepare(folder,path,'test',plan_path)
    video=folder/'S01.mp4';video.write_bytes(b'synthetic-video')
    client=Client()
    with pytest.raises(ValueError,match='参考视频未经'):submit(folder,'S02',client,[video])
    assert client.calls==0 and not (folder/'S02.json').exists()
    write(folder/'S01.json',{'status':'downloaded','local_video':str(video),'video_sha256':file_hash(video)})
    evidence=folder/'S01_frames.jpg';evidence.write_bytes(b'frame')
    review_path=folder/'review_input.json'
    write(review_path,{'checks':{c:False for c in CHECKS},'notes':'座位错误且动作迟缓','evidence':['S01_frames.jpg']})
    review_reference(folder,'S01',review_path)
    with pytest.raises(ValueError,match='禁止继续使用'):submit(folder,'S02',client,[video])
    assert client.calls==0
    write(review_path,{'checks':{c:True for c in CHECKS},'notes':'synthetic fixture verified','evidence':['S01_frames.jpg']})
    review_reference(folder,'S01',review_path)
    submit(folder,'S02',client,[video])
    assert client.calls==1


def test_model_revision_retains_provenance_and_cannot_overwrite_previous_run(tmp_path):
    _,path,plan,plan_path=setup(tmp_path)
    class DirectionClient:
        model_name='test-model'
        calls=0

        def chat_completion_tracked(self,messages,**kwargs):
            self.calls+=1
            self.messages=messages
            assert kwargs['use_cache'] is False
            return json.dumps({'shots':plan['shots']},ensure_ascii=False)

    client=DirectionClient()
    output=tmp_path/'revision'
    result=generate_plan(path,output,'当事人','咨询员',client,plan_path,'加快抬眼，不改变原台词')
    assert result['generation']['draft_sha256']==file_hash(plan_path)
    assert result['script_sha256']==file_hash(path)
    assert '旧的并排座位和缓慢等待提示不得沿用' not in client.messages[1]['content']
    assert '加快抬眼' in client.messages[-1]['content']
    assert (output/'S01.prompt.txt').exists()
    with pytest.raises(ValueError,match='new output directory'):
        generate_plan(path,output,'当事人','咨询员',client)
    assert client.calls==1
