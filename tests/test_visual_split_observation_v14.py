"""Independent target-only requests and auditable one-box formatting, no GPU."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_split_observation_v14 as s
from src.content_factory import visual_asset_pipeline_v3 as p
from test_visual_asset_review_v3 import images,provider,place_observation,observation
from test_visual_furniture_inventory_v11 import objects,inventory
from test_visual_furniture_taxonomy_v12 import double_label,response,run as legacy_taxonomy
from test_visual_environment_v4 import place


def people(count=1):return dict(people_count=count,evidence=['Fixture visible human count, no pose/face/ROI task.'])


def q(images,guide,allowed=None):
    return dict(target=images[1],reference=images[0],layout_guide=guide,
        expectation=dict(kind='place',view='side',locate_rois=[],expected_people=1,
            layout_object_inventory=allowed or inventory(),furniture_observation_scope=s.SCOPE))


def run(images,tmp_path,*,furniture=None,human=None,primary=True,taxonomy=None,allowed=None):
    guide=tmp_path/'guide.png';Image.new('RGB',(256,384),'white').save(guide)
    main=place_observation(1);main['checks']['layout']=primary
    native=dict(object_observations=deepcopy(furniture if furniture is not None else objects(1)))
    with provider(([taxonomy,main] if taxonomy is not None else [main]),people_observation=human or people(),furniture_observation=native) as (url,received):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review_many([q(images,guide,allowed)],evidence_dir=tmp_path/'split')[0]
        requests=deepcopy(received)
    return result,requests


def test_scoped_requests_are_separate_short_tasks_and_model_keeps_actual_guide(images,tmp_path):
    result,requests=run(images,tmp_path)
    assert result['decision']=='accepted' and result['prompt_version']==s.PROMPT_VERSION
    assert len(requests)==3
    human,furniture,model=requests
    assert set(human['format']['properties'])=={'people_count','evidence'}
    assert set(furniture['format']['properties'])=={'object_observations'}
    assert len(human['messages'][0]['images'])==len(furniture['messages'][0]['images'])==1
    assert len(model['messages'][0]['images'])==3
    assert 'furniture_observation_scope' not in model['messages'][0]['content']
    assert not (tmp_path/'split/item_0000/BLIND_NATIVE.json').exists()
    assert (tmp_path/'split/item_0000/PEOPLE_NATIVE.json').exists()
    assert (tmp_path/'split/item_0000/FURNITURE_NATIVE.json').exists()
    assert all(result['observations'][k]=='unknown' for k in ['age_band','orientation','framing','pose_view'])


def test_only_single_valid_flat_box_is_wrapped_with_original_native_preserved(images,tmp_path):
    value=objects(1);value['bed']['regions']=[0,330,1000,1000]
    result,_=run(images,tmp_path,furniture=value)
    assert result['decision']=='accepted' and result['object_observations']['bed']['regions']==[[0,330,1000,1000]]
    folder=tmp_path/'split/item_0000'
    raw=json.loads(p.read(folder/'FURNITURE_NATIVE.json')['text'])
    assert raw['object_observations']['bed']['regions']==[0,330,1000,1000]
    audit=p.read(folder/'FURNITURE_NORMALIZATION.json')
    assert audit['operations']==[dict(operation='wrap_single_valid_ltrb',kind='bed',before=[0,330,1000,1000],after=[[0,330,1000,1000]])]


@pytest.mark.parametrize('box,count',[([-1,0,1000,1000],1),([0,0,1001,1000],1),([500,500,100,100],1),
    ([0,0,1000,1000],2),([0,0,1000,1000],None),([0,0,1000,1000],True)])
def test_flat_box_normalization_never_fixes_coordinates_or_count(box,count):
    value=objects(1);value['bed'].update(count=count,regions=box)
    with pytest.raises(ValueError):s.normalize(dict(object_observations=value),inventory())


@pytest.mark.parametrize('field',['table','chair','light'])
def test_entire_null_kind_is_not_converted_to_absent_or_zero(images,tmp_path,field):
    value=objects(1);value[field]=None
    result,requests=run(images,tmp_path,furniture=value)
    assert result['decision']=='unavailable' and result['completion_known'] is True and result['retryable'] is True
    assert len(requests)==2 and 'object_observations' not in result


def test_structured_unknown_is_not_zero_or_accepted(images,tmp_path):
    value=objects(1);value['table']['count']=None;value['table']['evidence']='Fixture uncertain visible object.'
    result,_=run(images,tmp_path,furniture=value)
    assert result['object_observations']['table']['count'] is None and result['decision']=='needs_review'
    assert result['checks']['layout'] is None


def test_unknown_people_count_is_preserved_without_repeating_people_only_task(images,tmp_path):
    result,requests=run(images,tmp_path,human=people(None))
    assert len(requests)==3 and result['observations']['people_count'] is None
    assert result['checks']['consistency'] is None and result['decision']=='needs_review'


def test_extra_people_or_two_beds_still_fail_hard_gates(images,tmp_path):
    result,_=run(images,tmp_path,furniture=objects(2),human=people(2))
    assert result['decision']=='repair_required' and result['checks']['layout'] is False
    assert result['checks']['consistency'] is False and result['object_observations']['bed']['count']==2


@pytest.mark.parametrize('primary',[False,None])
def test_new_observation_nodes_do_not_upgrade_primary_layout(images,tmp_path,primary):
    result,_=run(images,tmp_path,primary=primary)
    assert result['checks']['layout'] is primary


def test_split_taxonomy_proof_still_uses_independent_roi_not_planned_table_count(images,tmp_path):
    result,requests=run(images,tmp_path,furniture=double_label(),taxonomy=response(),allowed=inventory()|dict(table=1))
    assert result['decision']=='accepted' and len(requests)==4
    assert result['object_taxonomy_recheck']['schema']=='target_furniture_taxonomy/v2'
    assert result['object_observations']['table']['count']==1 and result['object_observations']['counter']['count']==0
    v.verify_furniture_taxonomy(result)


@pytest.mark.parametrize('field',['people_request','people_native','furniture_request','furniture_native','normalization'])
def test_consumers_recheck_every_independent_native_artifact(images,tmp_path,field):
    result,_=run(images,tmp_path)
    Path(result['split_observation']['artifacts'][field]['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):p._consume_layout_inventory(result,inventory())


def test_even_rehashed_people_native_cannot_change_the_observed_count(images,tmp_path):
    result,_=run(images,tmp_path);entry=result['split_observation']['artifacts']['people_native'];path=Path(entry['path'])
    raw=p.read(path);body=json.loads(raw['text']);body['people_count']=0;raw['text']=json.dumps(body);p.write(path,raw);entry['sha256']=v.file_sha(path)
    with pytest.raises(ValueError,match='people count changed'):v.verify_furniture_taxonomy(result)


def test_furniture_schema_is_independent_of_permitted_quantity():
    assert s.furniture_schema(inventory(1))==s.furniture_schema(inventory(99))
    assert 'rois' not in s.furniture_schema(inventory())['properties']


def test_legacy_builder_and_unscoped_taxonomy_receipts_remain_v12(images,tmp_path):
    legacy=dict(target=images[1],reference=images[0],expectation=dict(kind='place',expected_people=0,layout_object_inventory=inventory()))
    assert v._prepared(legacy)['prompt_version']=='target-furniture-taxonomy-roi-v12'
    assert 'observations' in v.blind_schema(legacy['expectation'])['properties']
    assert 'object_observations' in v.blind_schema(legacy['expectation'])['properties']
    result,requests,_=legacy_taxonomy(images,tmp_path)
    assert result['decision']=='accepted' and result['object_taxonomy_recheck']['schema']=='target_furniture_taxonomy/v1'
    v.verify_furniture_taxonomy(result)


@pytest.mark.parametrize('exp',[dict(kind='character',furniture_observation_scope=s.SCOPE),
    dict(kind='place',furniture_observation_scope=s.SCOPE),dict(kind='place',layout_object_inventory=inventory(),furniture_observation_scope='guess/v0')])
def test_explicit_scope_rejects_actors_missing_inventory_or_unknown_contract(images,exp):
    with pytest.raises(ValueError):v._prepared(dict(target=images[1],expectation=exp))


def test_composite_only_place_gets_split_scope_and_actor_acceptance_never_grants_room(images,tmp_path):
    main=place_observation(1);main['checks']['layout']=False
    with provider([observation(),main],people_observation=people(),furniture_observation=dict(object_observations=objects(1))) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_composition(images[1],
            [dict(id='child',path=str(images[0]))],dict(id='room',path=str(images[0]),layout_guide=str(images[0])),
            expectation=dict(age_band='child',layout_object_inventory=inventory(),furniture_observation_scope=s.SCOPE),evidence_dir=tmp_path/'composition')
    assert result['subreviews'][0]['decision']=='accepted'
    assert 'split_observation' not in result['subreviews'][0]
    assert result['subreviews'][1]['decision']=='repair_required' and result['decision']=='repair_required'
    assert result['checks']['layout'] is False and len(requests)==5


def test_h3_inventory_consumer_revalidates_top_and_room_split_proof(images,tmp_path,monkeypatch):
    entity=place();expected=v.inventory_from_layout(entity['spatial_layout'])
    with provider([place_observation(1)],people_observation=people(),furniture_observation=dict(object_observations=objects(1))) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_composition(images[1],[],
            dict(id='room',path=str(images[0]),layout_guide=str(images[0])),expectation=dict(layout_object_inventory=expected,furniture_observation_scope=s.SCOPE),
            evidence_dir=tmp_path/'h3')
    # Empty actor list means expected_people=0; fixture people=1 must remain a failure.
    assert result['checks']['consistency'] is False
    result['checks']['consistency']=True # Explicit attempted promotion cannot pass the native people evidence checks/room decision.
    monkeypatch.setattr(p.static_frames,'enabled',lambda config:True)
    with pytest.raises(ValueError):p._verify_first_frame_inventory(dict(config=dict(generation_reference_policy='geometry_materials_only/v1')),entity,result)


def test_valid_static_frame_and_room_share_one_rechecked_split_receipt(images,tmp_path,monkeypatch):
    entity=place();expected=v.inventory_from_layout(entity['spatial_layout'])
    with provider([place_observation(0)],people_observation=people(0),furniture_observation=dict(object_observations=objects(1))) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_composition(images[1],[],
            dict(id='room',path=str(images[0]),layout_guide=str(images[0])),expectation=dict(layout_object_inventory=expected,furniture_observation_scope=s.SCOPE),
            evidence_dir=tmp_path/'valid_h3')
    plan=dict(config=dict(generation_reference_policy='geometry_materials_only/v1'))
    monkeypatch.setattr(p.static_frames,'enabled',lambda config:True)
    assert result['decision']=='accepted'
    p._verify_first_frame_inventory(plan,entity,result)
    entry=result['split_observation']['artifacts']['normalization'];other=tmp_path/'same_data_other_receipt.json'
    other.write_bytes(Path(entry['path']).read_bytes());entry['path']=str(other.resolve())
    with pytest.raises(ValueError,match='proofs_disagree'):p._verify_first_frame_inventory(plan,entity,result)


def test_known_legacy_shape_failure_can_get_new_scope_without_touching_raw_or_image(images,tmp_path):
    guide=tmp_path/'guide.png';Image.new('RGB',(256,384),'white').save(guide)
    malformed=dict(observations=dict(people_count=1,age_band='adult',orientation='screen_right',framing='full_body',pose_view='back'),
        rois=dict.fromkeys(v.ROI_NAMES),evidence=['Fixture legacy combined response.'],object_observations=dict.fromkeys(v.FURNITURE_KINDS))
    malformed['object_observations']['bed']=dict(count=1,regions=[0,330,1000,1000],evidence='Fixture visible bed.')
    legacy=q(images,guide);legacy['expectation'].pop('furniture_observation_scope')
    with provider([],blind=malformed) as (url,_):
        old=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([legacy],evidence_dir=tmp_path/'0')[0]
    original=v.file_sha(tmp_path/'0/item_0000/BLIND_NATIVE.json');image_sha=v.file_sha(images[1])
    assert old['decision']=='unavailable' and old['completion_known'] is True and old['retryable'] is True
    with provider([place_observation(1)],people_observation=people(),furniture_observation=dict(object_observations=objects(1))) as (url,_):
        new=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([q(images,guide)],evidence_dir=tmp_path/'1')[0]
    assert new['decision']=='accepted' and new['target_sha256']==old['target_sha256']==image_sha
    assert v.file_sha(tmp_path/'0/item_0000/BLIND_NATIVE.json')==original and v.file_sha(images[1])==image_sha
