"""Dynamic V2 bridge tests: local originals and isolated mocked transports only."""
from copy import deepcopy
from pathlib import Path
import socket

import pytest

from test_h3_universal_direction_execution_v1 import library_env, binding, approve
from test_visual_h3_library_minute_v2 import run
from test_visual_h3_library_continuation_v1 import spec,review
from src.content_factory import h3_universal_direction_execution_v2 as execution
from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import visual_h3_library_continuation_v1 as library

ROOT=Path(__file__).resolve().parents[1]
ACTUAL=ROOT/'data/video_generation/h3_universal_direction_minute_20261114_v1'
APPROVAL=ACTUAL/'SCENE_GUIDE_REUSE_APPROVAL.json'


@pytest.fixture
def saved_scene(tmp_path):
    target=tmp_path/'approved_reuse_target';target.mkdir()
    authority=flow.freeze(target/'USER_AUTHORIZATION.json',dict(synthetic_CPU_test=True,new_image_model_calls=0))
    data=deepcopy(flow.read(APPROVAL));data.update(target_run=str(target),user_authorization=authority)
    auth=flow.freeze(target/'SCENE_GUIDE_REUSE_APPROVAL.json',data)
    return target,data,auth


def validator(case,*,expected=None,approval=None,path=None):
    target,data,auth=case
    return execution.verify_saved_scene_reuse(target,path or data['scene_receipt']['path'],expected or data['native_job_id'],approval or auth)


def test_real_dynamic_s02_review_request_succeeds_with_absolute_new_s01_tail_and_original_a02(monkeypatch):
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('Actual bridge test forbids all network'))
    original_base=library.base.verify_native;original_scene=library.generated_scene_guide
    native=ACTUAL/'visual_h3_v3'/(ACTUAL.name+'_S01')/'shots/S01/RESULT.json'
    before=flow.bind(native);raw=flow.read(native)
    assert not Path(raw['files']['last']['path']).is_absolute()
    api=execution.library_for_run(ACTUAL,flow.bind(ACTUAL/'UNIVERSAL_POLICY.json'),flow.bind(APPROVAL))
    result=api.review_request(ACTUAL,'S02');request=flow._bound(result['request'])
    assert result['status']=='actual_guide_state_review_required'
    assert Path(request['predecessor_receipt']['last_image']['path']).is_absolute()
    assert request['predecessor_receipt']['last_image']['sha256']==raw['files']['last']['sha256']
    assert request['guide_image']==flow.read(APPROVAL)['image']
    assert request['generation_receipt']['native_prompt_id']=='ed50eff4-eacf-4063-8eac-4c79b1dc016c'
    assert request['generation_receipt']['saved_scene_reuse']['origin']=='reused_original_asset_not_generated_in_target_run'
    assert flow.bind(native)==before and request['predecessor_receipt']['result']==raw
    assert library.base.verify_native is original_base and library.generated_scene_guide is original_scene


def test_original_saved_scene_full_records_cfg_cast_and_source_pixels_are_verified(saved_scene,monkeypatch):
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('no network'))
    _,data,_=saved_scene;before={k:flow.bind(v['path']) for k,v in flow.read(data['scene_receipt']['path'])['generation_records'].items()}
    result=validator(saved_scene)
    assert result['image']==data['image'] and result['saved_scene_reuse']['original_records_preserved'] is True
    assert result['saved_scene_reuse']['new_image_calls']==0
    assert before=={k:flow.bind(v['path']) for k,v in result['generation_records'].items()}


def test_only_named_CFGGuider_1_to_1_float_is_equivalent():
    request={'initial__guider':dict(class_type='CFGGuider',inputs=dict(cfg=1)), 'noise':dict(inputs=dict(noise_seed=17))}
    native=deepcopy(request);native['initial__guider']['inputs']['cfg']=1.0
    assert execution._scene_equivalent(request,native)
    native['noise']['inputs']['noise_seed']=17.0
    assert not execution._scene_equivalent(request,native)
    native=deepcopy(request);native['initial__guider']['inputs']['cfg']=True
    assert not execution._scene_equivalent(request,native)


def test_wrong_scene_job_or_native_id_is_not_accepted(saved_scene):
    with pytest.raises(ValueError,match='unique_original_scene_job'):validator(saved_scene,expected='other_job')
    target,data,_=saved_scene;data['native_prompt_id']='some_other_job'
    wrong=flow.freeze(target/'WRONG_NATIVE.json',data)
    with pytest.raises(ValueError,match='unique_original_scene_job'):validator(saved_scene,approval=wrong)


def test_root_reuse_authority_must_match_target_user_and_saved_pixels(saved_scene):
    target,data,_=saved_scene
    wrong=deepcopy(data);wrong['approved_by']='not_root';bad=flow.freeze(target/'NOT_ROOT.json',wrong)
    with pytest.raises(ValueError,match='Root_saved_scene_reuse_approval'):validator(saved_scene,approval=bad)
    wrong=deepcopy(data);wrong['image']['sha256']='0'*64;bad=flow.freeze(target/'WRONG_IMAGE.json',wrong)
    with pytest.raises(ValueError,match='approved_scene_pixels'):validator(saved_scene,approval=bad)
    wrong=deepcopy(data);wrong['user_authorization']['sha256']='0'*64;bad=flow.freeze(target/'WRONG_AUTHORITY.json',wrong)
    with pytest.raises(ValueError,match='Root_saved_scene_reuse_approval'):validator(saved_scene,approval=bad)


def test_scene_receipt_SHA_and_copied_new_run_result_are_not_forged_as_original(saved_scene):
    target,data,_=saved_scene;wrong=deepcopy(data);wrong['scene_receipt']['sha256']='0'*64
    bad=flow.freeze(target/'WRONG_RECEIPT_SHA.json',wrong)
    with pytest.raises(ValueError,match='bound_input_changed'):validator(saved_scene,approval=bad)
    original=flow.read(data['scene_receipt']['path']);copied=flow.freeze(target/'COPIED_OLD_SCENE.json',original)
    wrong=deepcopy(data);wrong['scene_receipt']=copied;bad=flow.freeze(target/'COPIED_APPROVAL.json',wrong)
    with pytest.raises(ValueError,match='outside_approved_scope'):validator(saved_scene,approval=bad,path=copied['path'])


def test_project_relative_last_image_normalization_preserves_the_original_receipt(tmp_path):
    file=tmp_path/'tail.png';file.write_bytes(b'explicit test bytes, not a model image')
    relative=file.resolve().relative_to(execution.PROJECT).as_posix()
    original=dict(last_image=dict(path=relative,sha256=flow.bind(file)['sha256']),result={'files':{'last':{'path':relative}}})
    before=deepcopy(original);normalized=execution.normalize_last_image(original)
    assert original==before and normalized['result']==before['result'] and normalized['last_image']==flow.bind(file)
    wrong=deepcopy(original);wrong['last_image']['sha256']='0'*64
    with pytest.raises(ValueError,match='tail_SHA_changed'):execution.normalize_last_image(wrong)


def test_relative_tail_cannot_escape_the_project(tmp_path):
    original=dict(last_image=dict(path='../not-in-project.png',sha256='0'*64))
    with pytest.raises(ValueError,match='outside_approved_scope'):execution.normalize_last_image(original)


def test_v2_private_prepare_keeps_policy_and_Root_submit_gate(library_env):
    target,state=library_env;library.prepare(target,spec(target));review(target)
    api=execution.library_for_run(target,binding(target))
    assert api.prepare_video(target,'S01')['status']=='prepared'
    approve(target,api,approved_by='someone')
    with pytest.raises(ValueError,match='Root_launch_approval_required'):api.submit(target,'S01')
    assert state['posts']==0
    _,plan,_=api._load(target,'S01')
    assert 'h3_universal_direction_execution_v2.py' in {Path(v['path']).name for v in plan['code']}


def test_v2_unknown_claim_still_cannot_rePOST(library_env):
    target,state=library_env;library.prepare(target,spec(target));review(target)
    api=execution.library_for_run(target,binding(target));api.prepare_video(target,'S01');approve(target,api)
    state['response']=TimeoutError('Explicit mocked unknown response')
    assert api.submit(target,'S01')['status']=='outcome_unknown'
    assert api.submit(target,'S01')['status']=='outcome_unknown' and state['posts']==1
