"""Derived framing authenticates pixels and native parent; no vision inference."""
from copy import deepcopy
from pathlib import Path

from PIL import Image, __version__ as PILLOW_VERSION
import pytest

from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_opening_frame as opening
from test_visual_h3_continuity_input_v33 import make_entry, write


def fixture(tmp_path,monkeypatch):
    row=make_entry(tmp_path)
    row['first_frame_policy']=opening.POLICY
    row['camera_beats'][0]['framing']='face_close'
    initial=core.evaluate(row)
    parent=tmp_path/'native_parent.png'
    im=Image.new('RGB',(160,240))
    im.putdata([(x%256,y%256,(x+y)%256) for y in range(240) for x in range(160)])
    im.save(parent)
    output=tmp_path/'derived.png';box=dict(x=32,y=48,width=96,height=144)
    im.crop((32,48,128,192)).resize((160,240),Image.Resampling.LANCZOS).save(output)
    contract=opening.contract(row)
    model_file=tmp_path/'controlled_detector.onnx';model_file.write_bytes(b'Protocol fixture; never loaded.')
    model=dict(path=str(model_file),sha256='8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4')
    original_check=core.check
    def fixture_check(value):
        if value==model:return model_file  # Only bypass a detector file in this no-inference unit fixture.
        return original_check(value)
    monkeypatch.setattr(core,'check',fixture_check)
    detection=dict(schema='story_opening_face_detection/v1',status='unique_face_consensus',source=core.binding(parent),
        opening_contract_sha256=core.digest(contract),box=box,
        opening_contract=deepcopy(contract),code=core.binding(__file__),source_size=[160,240],
        detector='opencv_yunet',method='opencv_yunet_rotation_consensus/v1',model=model,
        score_threshold=.85,confidence=.90,landmark_geometry_valid=True,
        landmarks=[[60,80],[90,80],[75,100],[63,120],[87,120]],
        candidates=[dict(angle=-10,score=.90),dict(angle=0,score=.92),dict(angle=10,score=.91)],
        bbox_source='algorithm_auto_multirotation_consensus',
        consensus=dict(supporting_angles=[-10,0,10],candidate_indices=[0,1,2],minimum_distinct_angles=2))
    detected=write(tmp_path/'DETECTION.json',detection)
    result=dict(schema='story_opening_crop/v1',parent_image=core.binding(parent),image=core.binding(output),box=box,target_size=[160,240],
        resampler='PIL.Image.Resampling.LANCZOS',pillow_version=PILLOW_VERSION,
        detection=detected,opening_contract_sha256=core.digest(contract))
    result_binding=write(tmp_path/'CROP_RESULT.json',result)
    receipt=dict(kind='derived_opening_crop/v1',parent_image=core.binding(parent),
        parent_generation_receipt=dict(kind='spatial_still_v24',fixture_only=True),crop_result=result_binding)
    review=core.read(row['coverage_review'])
    review.update(target_image=core.binding(output),source_current_state_matches=True,
        work_order_sha256=initial['work_order_sha256'],opening_frame=dict(contract_sha256=core.digest(contract),
        visible_actor_ids=['su_mo'],framing='face_close',
        checks=dict(source_start_state_matches=True,source_attention_matches=True)))
    row['reanchor']=dict(image=core.binding(output),generation_receipt=receipt,
        work_order_sha256=initial['work_order_sha256'],coverage_review=write(tmp_path/'DERIVED_REVIEW.json',review))
    observed=[]
    def native_parent(entry,reanchor,work_order,requirements):
        observed.append(deepcopy(reanchor))
        assert reanchor['image']==core.binding(parent)
        assert reanchor['generation_receipt']['kind']=='spatial_still_v24'
        return dict(kind='spatial_still_v24',fixture_native_parent_verified=True)
    monkeypatch.setattr(core,'_spatial_receipt',native_parent)
    return row,result,detection,observed


def rewrite(row,result=None,detection=None):
    receipt=row['reanchor']['generation_receipt']
    current=result or core.read(receipt['crop_result'])
    if detection is not None:current['detection']=write(current['detection']['path'],detection)
    receipt['crop_result']=write(receipt['crop_result']['path'],current)


def test_crop_retains_parent_native_proof_and_has_own_visual_review(tmp_path,monkeypatch):
    row,_,_,observed=fixture(tmp_path,monkeypatch)
    result=core.evaluate(row)
    assert result['status']=='ready'
    proof=result['generation_receipt']
    assert proof['kind']=='derived_opening_crop/v1' and proof['exact_pixels_verified'] is True
    assert proof['native_output'] is False and proof['parent_visual_approval_inherited'] is False
    assert observed and proof['parent_generation_proof']['fixture_native_parent_verified'] is True
    review=core.read(row['reanchor']['coverage_review'])
    review['target_image']=row['reanchor']['generation_receipt']['parent_image']
    row['reanchor']['coverage_review']=write(row['reanchor']['coverage_review']['path'],review)
    with pytest.raises(ValueError,match='actual_image_canonical'):core.evaluate(row)


@pytest.mark.parametrize('change',[
    lambda r:r.update(pillow_version='wrong'),
    lambda r:r.update(resampler='NEAREST'),
    lambda r:r.update(opening_contract_sha256='0'*64),
    lambda r:r.update(target_size=[160,241]),
    lambda r:r['box'].update(x=-1),
    lambda r:r['box'].update(width=160),
    lambda r:r['box'].update(x=32.0),
])
def test_changed_crop_algorithm_contract_or_bounds_cannot_pass(tmp_path,monkeypatch,change):
    row,result,_,_=fixture(tmp_path,monkeypatch)
    change(result);rewrite(row,result=result)
    with pytest.raises(ValueError):core.evaluate(row)


@pytest.mark.parametrize('change',[
    lambda r:r.update(status='ambiguous'),
    lambda r:r.update(bbox_source='manual_box'),
    lambda r:r.update(opening_contract_sha256='0'*64),
    lambda r:r['box'].update(x=33),
    lambda r:r['consensus'].update(supporting_angles=[0,10]),
    lambda r:r['consensus'].update(supporting_angles=[0,0,0]),
    lambda r:r.update(method='haar_only'),
    lambda r:r.update(detector='haar'),
    lambda r:r.update(confidence=.7),
    lambda r:r.update(score_threshold=.7),
    lambda r:r.update(landmark_geometry_valid=False),
    lambda r:r.update(landmarks=[[0,0]]*5),
    lambda r:r['model'].update(sha256='0'*64),
    lambda r:r['consensus'].update(candidate_indices=[0,3]),
])
def test_unknown_manual_or_unbound_detection_is_refused(tmp_path,monkeypatch,change):
    row,result,det,_=fixture(tmp_path,monkeypatch)
    det=deepcopy(det);change(det);rewrite(row,result=result,detection=det)
    with pytest.raises(ValueError):core.evaluate(row)


def test_changed_output_pixels_fail_even_when_every_file_hash_is_rebound(tmp_path,monkeypatch):
    row,result,_,_=fixture(tmp_path,monkeypatch)
    path=Path(row['reanchor']['image']['path'])
    with Image.open(path) as image:
        copy=image.convert('RGB');copy.putpixel((0,0),(255,0,255));copy.save(path)
    row['reanchor']['image']=core.binding(path);result['image']=core.binding(path)
    rewrite(row,result=result)
    with pytest.raises(ValueError,match='exact_parent_crop_resize_pixels'):core.evaluate(row)


def test_changed_box_cannot_be_hidden_by_updating_the_detector_report(tmp_path,monkeypatch):
    row,result,det,_=fixture(tmp_path,monkeypatch)
    result['box']['x']=33;det['box']['x']=33
    rewrite(row,result=result,detection=det)
    with pytest.raises(ValueError,match='exact_parent_crop_resize_pixels'):core.evaluate(row)


def test_parent_unknown_or_bad_receipt_is_not_promoted_by_cpu_crop(tmp_path,monkeypatch):
    row,_,_,_=fixture(tmp_path,monkeypatch)
    def unknown(*args):raise core.ContinuityError('actual_still_request_history_result_not_complete')
    monkeypatch.setattr(core,'_spatial_receipt',unknown)
    with pytest.raises(ValueError,match='history_result_not_complete'):core.evaluate(row)


def test_two_strong_yunet_angles_with_valid_landmarks_are_accepted(tmp_path,monkeypatch):
    row,result,det,_=fixture(tmp_path,monkeypatch)
    det['consensus'].update(supporting_angles=[-10,0],candidate_indices=[0,1])
    rewrite(row,result=result,detection=det)
    assert core.evaluate(row)['status']=='ready'
