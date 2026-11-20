"""Target-only taxonomy protocol; fixtures do not claim real visual acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import base64
import io

from PIL import Image
import pytest

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_furniture_taxonomy_v12 as t
from test_visual_asset_review_v3 import provider,images,place_observation
from test_visual_furniture_inventory_v11 import objects,inventory


def double_label():
    result=objects(1);box=[0,660,460,1000]
    result['table']=dict(count=1,regions=[box],evidence='Fixture freestanding table.')
    result['counter']=dict(count=1,regions=[box],evidence='Fixture overlapping counter annotation.')
    return result


def response(same=True,count=1,category='table'):
    return dict(same_physical_instance=same,visible_instance_count=count,unique_category=category,
        evidence='The crop shows one freestanding surface with its own visible legs, not a fixed built-in worktop.')


def run(images,tmp_path,*,taxonomy=None,primary=True,source=None):
    observed=deepcopy(source or double_label())
    blind=dict(observations=dict(people_count=0,age_band='unknown',orientation='unknown',framing='environment',pose_view='unknown'),
        rois=dict.fromkeys(v.ROI_NAMES),evidence=['Fixture room.'],object_observations=observed)
    main=place_observation(0);main['checks']['layout']=primary
    guide=tmp_path/'guide.png';Image.new('RGB',(256,384),'white').save(guide)
    has_roi=t.candidate(observed) is not None
    answers=[taxonomy or response(),main] if has_roi else [main]
    with provider(answers,blind=blind) as (url,received):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        q=dict(target=images[1],reference=images[0],layout_guide=guide,
            expectation=dict(kind='place',view='reverse',expected_people=0,locate_rois=[],layout_object_inventory=inventory()|dict(table=1)))
        result=client.review_many([q],evidence_dir=tmp_path/'review')[0]
    return result,received,q


def test_actual_roi_is_only_target_and_changes_one_dual_label_not_planned_count(images,tmp_path):
    result,requests,_=run(images,tmp_path)
    assert result['decision']=='accepted' and result['checks']['layout'] is True
    assert result['object_observations']['counter']['count']==0 and result['object_observations']['table']['count']==1
    assert result['object_observations_original']['counter']['count']==1
    assert len(requests)==3 and len(requests[1]['messages'][0]['images'])==1
    crop=Image.open(io.BytesIO(base64.b64decode(requests[1]['messages'][0]['images'][0])))
    assert crop.width<256 and crop.height<384
    text=requests[1]['messages'][0]['content']
    assert 'allowed_total' not in text and 'layout_object_inventory' not in text and 'EXPECTATION_JSON' not in text
    v.enforce_layout_inventory(deepcopy(result),inventory()|dict(table=1))


def test_observed_counter_category_does_not_get_changed_to_match_plan(images,tmp_path):
    result,_,_=run(images,tmp_path,taxonomy=response(category='counter'))
    assert result['object_observations']['table']['count']==0 and result['object_observations']['counter']['count']==1
    assert result['decision']=='repair_required' and result['checks']['layout'] is False


@pytest.mark.parametrize('answer',[response(same=None,count=None,category='unknown'),response(category='unknown')])
def test_uncertain_roi_keeps_counts_null_and_blocks(images,tmp_path,answer):
    result,_,_=run(images,tmp_path,taxonomy=answer)
    assert result['checks']['layout'] is None and result['decision']=='needs_review'
    assert all(result['object_observations'][k]['count'] is None for k in ('table','counter'))


def test_distinct_instances_are_not_merged_by_overlap(images,tmp_path):
    result,_,_=run(images,tmp_path,taxonomy=response(same=False,count=2,category='unknown'))
    assert result['object_observations']==result['object_observations_original']
    assert result['checks']['layout'] is False and result['decision']=='repair_required'


@pytest.mark.parametrize('primary',[False,None])
def test_taxonomy_never_upgrades_actual_guide_primary_layout(images,tmp_path,primary):
    result,_,_=run(images,tmp_path,primary=primary)
    assert result['checks']['layout'] is primary
    assert result['decision']==('repair_required' if primary is False else 'needs_review')


def test_two_beds_remain_two_and_never_trigger_taxonomy_roi(images,tmp_path):
    result,requests,_=run(images,tmp_path,source=objects(2))
    assert len(requests)==2 and 'object_taxonomy_recheck' not in result
    assert result['object_observations']['bed']['count']==2 and result['checks']['layout'] is False


def test_different_table_and_counter_boxes_do_not_trigger_merge():
    value=double_label();value['counter']['regions']=[[600,200,950,650]]
    assert t.candidate(value) is None


def test_correcting_one_cross_label_does_not_remove_another_table():
    value=double_label();value['table']['count']=2;value['table']['regions'].append([600,100,900,400])
    corrected=t.apply(value,t.candidate(value),response())
    assert corrected['table']['count']==2 and corrected['counter']['count']==0


@pytest.mark.parametrize('field',['crop','native','blind_native','request','primary_native'])
def test_persisted_evidence_changes_fail_closed(images,tmp_path,field):
    result,_,_=run(images,tmp_path)
    Path(result['object_taxonomy_recheck']['artifacts'][field]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):v.enforce_layout_inventory(result,inventory()|dict(table=1))


@pytest.mark.parametrize('change',[
    lambda r:r['object_taxonomy_recheck']['answer'].update(unique_category='counter'),
    lambda r:r['object_observations']['table'].update(count=0,regions=[]),
    lambda r:r['object_observations_original']['counter'].update(count=0,regions=[]),
    lambda r:r['object_taxonomy_recheck']['selection']['annotations'][0].update(region=[0,0,500,500]),
    lambda r:r.pop('object_taxonomy_recheck'),
])
def test_json_self_claims_cannot_change_the_correction(images,tmp_path,change):
    result,_,_=run(images,tmp_path);change(result)
    with pytest.raises(ValueError):v.enforce_layout_inventory(result,inventory()|dict(table=1))


def test_even_rehashed_primary_false_cannot_be_elevated(images,tmp_path):
    result,_,_=run(images,tmp_path)
    item=result['object_taxonomy_recheck']['artifacts']['primary_native'];path=Path(item['path'])
    raw=json.loads(path.read_text());body=json.loads(raw['text']);body['checks']['layout']=False;raw['text']=json.dumps(body)
    path.write_text(json.dumps(raw),encoding='utf-8');item['sha256']=v.file_sha(path)
    with pytest.raises(ValueError,match='cannot upgrade'):v.enforce_layout_inventory(result,inventory()|dict(table=1))


def test_cached_receipt_rechecks_roi_files(images,tmp_path):
    result,_,q=run(images,tmp_path)
    Path(result['object_taxonomy_recheck']['artifacts']['crop']['path']).write_bytes(b'changed')
    # Discovery/inference must not be reached when a cached proof was modified.
    with provider([]) as (url,_):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        # Original config endpoint is part of binding, so use direct artifact guard here.
        with pytest.raises(ValueError):v.verify_furniture_taxonomy(result)


@pytest.mark.parametrize('answer',[response(same=True,count=2),response(same=False,count=1,category='unknown'),
    response(same=None,category='table'),response(count=True),response(category='cabinet')])
def test_inconsistent_or_unscoped_answers_are_rejected(answer):
    with pytest.raises(ValueError):t.answer(answer)


def test_composite_and_h3_inventory_consumer_revalidate_same_actual_roi(images,tmp_path):
    from src.content_factory import visual_asset_pipeline_v3 as pipeline
    from test_visual_environment_v4 import place
    observed=double_label()
    blind=dict(observations=dict(people_count=0,age_band='unknown',orientation='unknown',framing='environment',pose_view='unknown'),
        rois=dict.fromkeys(v.ROI_NAMES),evidence=['Fixture.'],object_observations=observed)
    entity=place();expected=v.inventory_from_layout(entity['spatial_layout'])
    with provider([response(),place_observation(0)],blind=blind) as (url,_):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review_composition(images[1],[],dict(id='room',path=str(images[0]),layout_guide=str(images[0])),
            expectation=dict(layout_object_inventory=expected),evidence_dir=tmp_path/'composition')
    plan=dict(config=dict(generation_reference_policy='geometry_materials_only/v1'))
    assert result['decision']=='accepted'
    pipeline._verify_first_frame_inventory(plan,entity,result)
    Path(result['object_taxonomy_recheck']['artifacts']['crop']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):pipeline._verify_first_frame_inventory(plan,entity,result)
