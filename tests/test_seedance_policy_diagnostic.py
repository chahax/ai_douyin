import json
from pathlib import Path

import pytest

from scripts.run_seedance_policy_diagnostic import initialize, submit_next, query_current, add_identity_refinement, VARIANTS, POLICY_CODE


def setup_case(tmp_path):
    from PIL import Image
    frame = tmp_path / 'tail.png'; Image.new('RGB', (360, 640), 'gray').save(frame)
    prompt = '原提示\n所有重新入画人物沿用原稿外貌与服装：\n父亲：具体外貌\n女儿：具体外貌\n只补充身份'
    receipt = tmp_path / 'failed.json'
    receipt.write_text(json.dumps({'status':'failed','submit_id':'old-task','request':{'duration':6,'generate_audio':True,
        'content':[{'type':'text','text':prompt}]},'latest_response':{'status':'failed','error':{'code':POLICY_CODE}}}), encoding='utf-8')
    return receipt, frame


def test_initialize_builds_single_variable_order(tmp_path, monkeypatch):
    receipt, frame = setup_case(tmp_path); output = tmp_path / 'diag'
    initialize(output, receipt, frame, '用户授权逐项诊断')
    plan = json.loads((output/'plan.json').read_text(encoding='utf-8'))
    assert [v['id'] for v in plan['variants']] == list(VARIANTS)
    assert plan['variants'][0]['use_first_frame'] is True
    assert plan['variants'][1]['use_first_frame'] is False
    assert '具体外貌' not in plan['variants'][0]['prompt']
    assert '具体外貌' in plan['variants'][1]['prompt']


def test_sequence_stops_on_success_and_does_not_resubmit(tmp_path, monkeypatch):
    receipt, frame = setup_case(tmp_path); output = tmp_path / 'diag'
    initialize(output, receipt, frame, '用户授权逐项诊断')
    class Client:
        calls = 0
        def __init__(self, config): self.config=config
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def build_task_payload(self,prompt,**kw):
            refs=kw.pop('references')
            return {'model':self.config.model,'content':[{'type':'text','text':prompt}]+[r.to_content() for r in refs],**kw}
        def create_task(self,payload): Client.calls += 1; return {'id':'task-a'}
        def get_task(self,task): return {'id':task,'status':'succeeded','content':{'video_url':'https://x/video','last_frame_url':'https://x/tail'}}
        def download_video(self,response,path): Path(path).write_bytes(b'video'); return Path(path)
        def download_last_frame(self,response,path): Path(path).write_bytes(b'tail'); return Path(path)
    monkeypatch.setattr('scripts.run_seedance_policy_diagnostic.SeedanceClient',Client)
    submit_next(output); query_current(output)
    assert submit_next(output)['status']=='stopped_after_success'
    assert Client.calls==1


def test_non_target_failure_stops_instead_of_advancing(tmp_path, monkeypatch):
    receipt, frame = setup_case(tmp_path); output = tmp_path / 'diag'
    initialize(output, receipt, frame, '用户授权逐项诊断')
    class Client:
        def __init__(self, config): self.config=config
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def build_task_payload(self,prompt,**kw):
            refs=kw.pop('references')
            return {'content':[{'type':'text','text':prompt}]+[r.to_content() for r in refs],**kw}
        def create_task(self,payload): return {'id':'task-a'}
        def get_task(self,task): return {'id':task,'status':'failed','error':{'code':'SetLimitExceeded'}}
    monkeypatch.setattr('scripts.run_seedance_policy_diagnostic.SeedanceClient',Client)
    submit_next(output); query_current(output)
    plan=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    assert plan['status']=='stopped_for_inspection'
    with pytest.raises(ValueError,match='differs'): submit_next(output)


def test_identity_failed_success_can_add_one_narrow_refinement(tmp_path):
    receipt, frame = setup_case(tmp_path); output = tmp_path / 'diag'
    initialize(output, receipt, frame, '用户授权逐项诊断')
    plan=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    plan['status']='stopped_after_success'; plan['attempts']=[{
        'variant':VARIANTS[0], 'status':'succeeded', 'video_sha256':'a'*64}]
    (output/'plan.json').write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
    review=output/'review.json'; review.write_text(json.dumps({
        'schema':'policy_diagnostic_visual_review/v1','variant':VARIANTS[0],
        'source_sha256':'a'*64,'decision':'failed','checks':{'identity':False}}),encoding='utf-8')
    result=add_identity_refinement(output,review)
    assert result['next_variant']=='A2_wardrobe_identity'
    actual=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    assert actual['variants'][1]['use_first_frame'] is True
    assert '浅灰夹克' in actual['variants'][1]['prompt'] and '具体外貌' not in actual['variants'][1]['prompt']
