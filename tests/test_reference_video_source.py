import json
import pytest
from scripts import run_director_video as executor
from scripts import reference_video_source as source


def write(path,value):
    path.write_text(json.dumps(value),encoding='utf-8')


def test_reference_s01_cannot_submit_without_actual_opening(tmp_path):
    write(tmp_path/'production.json',{'test_shot':'S01','trial_schema':'reviewed_reference_director_segment/v1'})
    with pytest.raises(ValueError,match='actually reviewed original opening'):
        executor.submit(tmp_path)
    assert not (tmp_path/'S01.json').exists()


def test_explicit_reviewed_text_only_opening_needs_no_image():
    executor.verify_opening_mode({'test_shot':'S01','trial_schema':'reviewed_reference_director_segment/v1',
                                 'opening_mode':'text_only','reference_binding':{}},
                                {'reference_requirement':'text_only'})


def test_manifest_alone_cannot_switch_reviewed_opening_mode():
    with pytest.raises(ValueError,match='differs from reviewed source'):
        executor.verify_opening_mode({'test_shot':'S01','trial_schema':'reviewed_reference_director_segment/v1',
                                     'opening_mode':'text_only','reference_binding':{}},
                                    {'reference_requirement':'reviewed_opening_image'})


def test_text_only_mode_cannot_smuggle_an_image_reference():
    with pytest.raises(ValueError,match='cannot contain an image'):
        executor.verify_opening_mode({'test_shot':'S01','trial_schema':'reviewed_reference_director_segment/v1',
                                     'opening_mode':'text_only','reference_binding':{},'opening_image':{'path':'old'}},
                                    {'reference_requirement':'text_only'})


def test_existing_receipt_never_retried(tmp_path):
    write(tmp_path/'production.json',{'test_shot':'S01','trial_schema':'reviewed_reference_director_segment/v1'})
    write(tmp_path/'S01.json',{'status':'submission_unknown'})
    with pytest.raises(ValueError,match='Existing receipt'):
        executor.submit(tmp_path)


def test_reference_bundle_dispatches_its_own_verifier(tmp_path,monkeypatch):
    write(tmp_path/'bundle.json',{'schema':'reference_director_video_bundle/v1'})
    sentinel=({'schema':'verified'},{'schema':source.SCHEMA})
    monkeypatch.setattr(source,'verify_bundle',lambda folder:sentinel)
    assert executor.verify_bundle(tmp_path)==sentinel


def test_reference_bundle_detects_source_rewrite(tmp_path,monkeypatch):
    original={'schema':source.SCHEMA,'source_review':{'path':'review','sha256':'a'},'shots':[]}
    write(tmp_path/'script.json',original)
    write(tmp_path/'bundle.json',{'schema':'reference_director_video_bundle/v1','source':'source','prompts':'prompts',
          'script':source.identity(tmp_path/'script.json'),'review':original['source_review']})
    monkeypatch.setattr(source,'build_script',lambda *args:{**original,'shots':[{'changed':True}]})
    with pytest.raises(ValueError,match='projection changed'):
        source.verify_bundle(tmp_path)
