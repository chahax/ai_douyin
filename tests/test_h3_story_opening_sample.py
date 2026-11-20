"""Thin runner checks; actual generation belongs to root, no HTTP/model calls."""
from pathlib import Path

import pytest

from scripts import run_h3_story_opening_sample as sample


@pytest.fixture
def run(tmp_path,monkeypatch):
    root=tmp_path/'opening_sample'
    root.mkdir()
    monkeypatch.setattr(sample,'RUN',root)
    return root


def test_real_source_prepare_is_file_only_and_preserves_first_shot_scope(run,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('network or media dispatch during prepare')
    monkeypatch.setattr(sample.stills.jobs,'_http',forbidden)
    monkeypatch.setattr(sample.native,'_http',forbidden)
    before=sample.bind(sample.SOURCE/'SOURCE_CASE.json')
    result=sample.prepare(run)
    assert result['model_posts']==0 and result['status']=='source_state_review_required'
    rows=sample.core._entries(sample.bind(run/'SOURCE_CASE.json'))
    assert len(rows)==1 and rows[0]['shot_id']=='S02'
    assert len(rows[0]['canonical_characters'])==3
    assert rows[0]['first_frame_policy']==sample.opening.POLICY
    p=sample.read(run/'stills/opening_S02/PLAN.json')
    row=next(r for r in p['items'] if r['id']=='S02_start')
    assert row['visible_cast']==['su_mo'] and len(row['references'])==2
    assert 'head-and-shoulders close-up' in row['prompt']
    assert not (run/'SOURCE_STATE_REVIEW.json').exists()
    assert not list(run.rglob('CLAIM.json')) and not list(run.rglob('REQUEST.json'))
    assert sample.bind(sample.SOURCE/'SOURCE_CASE.json')==before
    assert sample.prepare(run)==result


def test_missing_actual_root_observation_does_not_reserve_or_dispatch(run):
    assert sample.prepare_images(run)==dict(status='source_state_review_required',model_posts=0)
    assert not list(run.rglob('CLAIM.json'))


def image_plan(run):
    folder=run/'stills/opening_S02/batches/reanchor_S02'
    folder.mkdir(parents=True)
    sample.freeze(folder/'PLAN.json',{})
    return folder


def test_image_unknown_continues_existing_collector_without_launch_or_repost(run,monkeypatch):
    image_plan(run)
    monkeypatch.setattr(sample.stills,'status',lambda *a,**k:dict(status='outcome_unknown'))
    def denied(*a,**k):raise AssertionError('unknown job must not request fresh launch')
    monkeypatch.setattr(sample,'require_approval',denied)
    monkeypatch.setattr(sample.stills,'execute',lambda *a,**k:dict(status='outcome_unknown'))
    assert sample.execute(run,'image')['status']=='outcome_unknown'


def test_prepared_image_requires_actual_launch_approval(run,monkeypatch):
    image_plan(run)
    monkeypatch.setattr(sample.stills,'status',lambda *a,**k:dict(status='prepared'))
    monkeypatch.setattr(sample.stills,'execute',lambda *a,**k:pytest.fail('dispatch before approval'))
    with pytest.raises(FileNotFoundError):sample.execute(run,'image')


@pytest.mark.parametrize('state',['outcome_unknown','blocked_native_failure','blocked_upstream_changed','paused'])
def test_video_terminal_or_blocked_state_never_submits_again(run,monkeypatch,state):
    video=run/'visual_h3_v3/opening_S02';video.mkdir(parents=True)
    monkeypatch.setattr(sample.native,'poll_collect',lambda *a,**k:dict(status=state))
    monkeypatch.setattr(sample.native,'submit_next',lambda *a,**k:pytest.fail('must preserve known state'))
    assert sample.execute(run,'video')['status']==state


def test_launch_request_requires_same_plan_graph_and_code(run,monkeypatch):
    plan=image_plan(run)
    sample.freeze(run/'USER_AUTHORIZATION.json',dict(user_statement='new sample'))
    sample.freeze(run/'SOURCE_CASE.json',dict(source='fixture'))
    sample.freeze(plan/'workflow_api.json',dict(graph='fixture'))
    request=sample.launch_request(run,'image')
    sample.freeze(run/'ROOT_LAUNCH_IMAGE.json',dict(request=request,approved_by='controlled CPU fixture',evidence=['Protocol only.']))
    sample.require_approval(run,'image')
    (plan/'workflow_api.json').write_text('{"changed":true}',encoding='utf-8')
    with pytest.raises(ValueError,match='actual_plan_and_code_bound'):sample.require_approval(run,'image')


def test_scope_and_stage_are_explicit(run,tmp_path):
    with pytest.raises(ValueError,match='explicit_new'):sample.scope(tmp_path/'other')
    with pytest.raises(ValueError,match='explicit_image_or_video'):sample.execute(run,'cloud')


def selection_fixture(run):
    from PIL import Image
    from test_visual_h3_continuity_input_v33 import make_entry
    row=make_entry(run);row['shot_id']='S02'
    sample.freeze(run/'SOURCE_CASE.json',dict(schema=sample.core.SCHEMA,shots=[row]))
    parent=run/'parent.png';child=run/'crop.png'
    Image.new('RGB',(96,128),'gray').save(parent);Image.new('RGB',(96,128),'white').save(child)
    folder=run/'stills/opening_S02/batches/reanchor_S02';folder.mkdir(parents=True)
    candidate=dict(id='S02_start',image=sample.bind(parent),prompt_id='controlled_fixture')
    sample.freeze(folder/'CANDIDATES.json',dict(items=[candidate]))
    original=dict(kind='spatial_still_v24',run=str(run/'stills/opening_S02'),batch_id='reanchor_S02',
                  item_id='S02_start',candidates=None,source_binding_review=dict(path='fixture',sha256='0'*64))
    sample.freeze(run/'IMAGE_RECEIPT_TEMPLATE.json',original)
    actual=dict(original,candidates=sample.bind(folder/'CANDIDATES.json'))
    selection=dict(parent_image=sample.bind(parent),parent_generation_receipt=actual,
                   crop_result=dict(path='fixture_crop_result',sha256='0'*64),image=sample.bind(child))
    return selection,parent,child


def test_derived_selection_requires_its_own_target_review_and_preserves_parent(run):
    selection,parent,child=selection_fixture(run)
    sample.freeze(run/'DERIVED_OPENING_SELECTION.json',selection)
    result=sample.prepare_video(run)
    assert result['status']=='actual_anchor_review_required'
    assert result['candidate']['image']==sample.bind(child)
    assert result['candidate']['derived_from']==sample.bind(parent)
    assert result['candidate']['native_output'] is False
    assert Path(result['required_review_file']).name=='DERIVED_ANCHOR_REVIEW.json'
    assert not (run/'VIDEO_SOURCE_CASE.json').exists()


def test_derived_selection_cannot_swap_a_different_native_parent(run):
    selection,_,child=selection_fixture(run)
    selection['parent_image']=sample.bind(child)
    sample.freeze(run/'DERIVED_OPENING_SELECTION.json',selection)
    with pytest.raises(ValueError,match='preserve_actual_native_parent'):sample.prepare_video(run)
