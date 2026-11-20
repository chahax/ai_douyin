"""Furniture-count contract canaries; injected responses are not visual QA."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest
from jsonschema import validate

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as registry
from test_visual_asset_review_v3 import images,provider,place_observation
from test_visual_asset_pipeline_v3 import FakeReviewer
from test_visual_environment_v4 import place
from test_visual_h3_handoff_v3 import service as h3_service,native_media,setup as h3_setup
from src.content_factory import visual_h3_handoff_v3 as h3


def inventory(beds=1):
    return dict.fromkeys(v.FURNITURE_KINDS,0)|dict(bed=beds)


def objects(count=0):
    result={k:dict(count=0,regions=[],evidence='Fixture: no visible instance.') for k in v.FURNITURE_KINDS}
    result['bed']=dict(count=count,regions=([[0,500,220,990],[600,200,960,800]][:count] if count is not None else []),
        evidence='Fixture: left cropped bed and right complete bed.' if count==2 else 'Fixture evidence; no count may be parsed from prose.')
    return result


def blind(count=0):
    return dict(observations=dict(people_count=0,age_band='unknown',orientation='unknown',framing='environment',pose_view='unknown'),
        rois=dict.fromkeys(v.ROI_NAMES),evidence=['Protocol target-only room observation.'],object_observations=objects(count))


def review(images,tmp_path,*,count,allowed=1,primary=True):
    raw=place_observation(0);raw['checks']['layout']=primary
    guide=tmp_path/'guide.png';Image.new('RGB',(256,384),'white').save(guide)
    with provider([raw],blind=blind(count)) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([
            dict(target=images[1],reference=images[0],layout_guide=guide,
                expectation=dict(kind='place',view='reverse',expected_people=0,layout_object_inventory=inventory(allowed)))],
            evidence_dir=tmp_path/'review')[0]
    return result,requests


def test_physical_inventory_counts_parent_objects_not_mesh_parts_or_bedding():
    result=v.inventory_from_layout(dict(objects=[dict(kind=k) for k in ['bed','bedding','building','wardrobe','desk','ceiling_light','stool']]))
    assert result==inventory()|dict(cabinet=1,table=1,light=1,stool=1)
    with pytest.raises(ValueError,match='unsupported_layout_inventory_kind'):
        v.inventory_from_layout(dict(objects=[dict(kind='mystery')]))


def test_new_blind_schema_has_no_allowed_counts_and_permits_excess():
    one=dict(kind='place',layout_object_inventory=inventory(1));nine=dict(kind='place',layout_object_inventory=inventory(9))
    assert v.blind_schema(one)==v.blind_schema(nine)
    validate(blind(2),v.blind_schema(one))
    assert 'layout_object_inventory' not in v._model_expectation(one)
    assert set(v.blind_schema(one)['properties']['object_observations']['properties'])==set(v.FURNITURE_KINDS)
    assert 'object_observations' not in v.blind_schema(dict(kind='place'))['properties']


def test_actual_target_only_two_bed_response_overrides_general_true(images,tmp_path):
    result,requests=review(images,tmp_path,count=2)
    assert result['decision']=='repair_required' and result['checks']['layout'] is False
    assert result['object_inventory_check']['exceeds']==['bed']
    assert result['object_observations']['bed']['regions'][0][0]==0 # Partial frame-edge instance counts.
    assert len(requests)==2 and len(requests[0]['messages'][0]['images'])==1
    prompt=requests[0]['messages'][0]['content']
    assert 'FURNITURE_OBSERVATION' in prompt and 'EXPECTATION_JSON' not in prompt
    assert 'allowed_total' not in prompt and 'layout_object_inventory' not in prompt
    assert len(requests[1]['messages'][0]['images'])==3 # Source and current guide still compared.
    assert result['completion_known'] is True and result['outcome_unknown'] is False


def test_unknown_does_not_parse_prose_or_boxes_into_a_known_count(images,tmp_path):
    result,_=review(images,tmp_path,count=None)
    assert result['decision']=='needs_review' and result['checks']['layout'] is None
    assert result['object_observations']['bed']['count'] is None
    assert result['object_inventory_check']['unknown']==['bed']


@pytest.mark.parametrize('count',[0,1])
def test_occlusion_has_no_visible_lower_bound(images,tmp_path,count):
    result,_=review(images,tmp_path,count=count,allowed=9)
    assert result['decision']=='accepted' and result['checks']['layout'] is True
    assert result['object_inventory_check']['visible_lower_bound_enforced'] is False


@pytest.mark.parametrize('primary',[False,None])
def test_valid_count_never_upgrades_other_layout_failure(images,tmp_path,primary):
    result,_=review(images,tmp_path,count=1,primary=primary)
    assert result['checks']['layout'] is primary
    assert result['decision']==('repair_required' if primary is False else 'needs_review')


@pytest.mark.parametrize('change',[
    lambda b:b['bed'].update(count=True),lambda b:b['bed'].update(count=-1),
    lambda b:b['bed'].update(count=2),lambda b:b['bed'].update(regions=[[0,0,0,900]]),
    lambda b:b['bed'].update(count=2,regions=[[0,0,500,500]]*2),
    lambda b:b['bed'].update(evidence=''),lambda b:b.pop('chair'),
])
def test_malformed_count_regions_and_coverage_fail_closed(change):
    value=objects(1);change(value)
    with pytest.raises(v.ReviewProtocolError):v.validate_object_observations(value,inventory())


def test_unknown_is_not_synthesized_from_region_count():
    value=objects(1);value['bed']['count']=None
    assert v.validate_object_observations(value,inventory())['bed']['count'] is None


def test_unplanned_supported_furniture_has_zero_upper_bound():
    result=dict(decision='accepted',checks=dict(layout=True),layout_object_inventory=inventory(),object_observations=objects(0))
    result['object_observations']['sofa']=dict(count=1,regions=[[1,2,300,400]],evidence='Fixture: visible extra sofa.')
    v.enforce_layout_inventory(result,inventory())
    assert result['checks']['layout'] is False and result['object_inventory_check']['exceeds']==['sofa']


def test_unavailable_or_unknown_receipt_stays_unknown_and_does_not_invent_counts(images):
    prepared=v._prepared(dict(target=images[1],expectation=dict(kind='place',layout_object_inventory=inventory())))
    result=v._unavailable(prepared,v.ReviewOutcomeUnknown('Fixture unknown native call'))
    assert p._consume_layout_inventory(result,inventory())==result
    assert result['outcome_unknown'] is True and 'object_observations' not in result
    with pytest.raises(v.ReviewProtocolError):p._consume_layout_inventory(dict(decision='accepted'),inventory())


def test_composition_inventory_only_goes_to_room_and_cannot_be_hidden_by_actors(images,monkeypatch):
    client=v.VisualReviewClient(dict(provider='ollama',endpoint='http://127.0.0.1:9',model='fixture'))
    captured=[]
    def fake(requests,**kwargs):
        captured.extend(deepcopy(requests));results=[]
        for request in requests:
            exp=request['expectation'];kind=exp['kind']
            result=dict(decision='accepted',checks=dict.fromkeys(v.check_names(exp),True),issues=[],evidence=['Fixture only'],
                completion_known=True,outcome_unknown=False,inference_dispatched=True)
            if kind=='place':
                result.update(layout_object_inventory=inventory(),object_observations=objects(2))
                v.enforce_layout_inventory(result,inventory())
            results.append(result)
        return results
    monkeypatch.setattr(client,'review_many',fake)
    result=client.review_composition(images[1],[dict(id='actor',path=str(images[0]))],dict(id='room',path=str(images[0])),
        expectation=dict(layout_object_inventory=inventory()))
    assert 'layout_object_inventory' not in captured[0]['expectation']
    assert captured[-1]['expectation']['layout_object_inventory']==inventory()
    assert result['checks']['layout'] is False and result['decision']=='repair_required'
    assert result['checks']['identity'] is True


@pytest.mark.parametrize('malformed',[False,True])
def test_pipeline_consumes_inventory_before_style_and_registry(images,tmp_path,monkeypatch,malformed):
    entity=place();entity['required_views']=['front']
    root=tmp_path/'library';row=registry.register(root,images[1],book_id='book',entity_id='room',kind='place',view='front',design_version=entity['design_version'])
    plan=dict(packet=dict(places=[entity],characters=[],shots=[],book_id='book'),config=dict(library=str(root),generation_reference_policy='geometry_materials_only/v1'))
    state={};guide=dict(path=str(images[0]),sha256=v.file_sha(images[0]))
    monkeypatch.setattr(p,'_lookup',lambda *args,**kwargs:row)
    monkeypatch.setattr(p,'_image_path',lambda *args:images[1])
    monkeypatch.setattr(p,'_environment_guide',lambda *args,**kwargs:guide)
    class Reviewer(FakeReviewer):
        def review_many(self,requests,**kwargs):
            results=super().review_many(requests,**kwargs)
            for request,result in zip(requests,results):
                result['layout_guide_sha256']=guide['sha256']
                if malformed:result.pop('object_observations')
                else:result['object_observations']=objects(2)
            return results
    reviewer=Reviewer()
    if malformed:
        with pytest.raises(v.ReviewProtocolError):p.review_candidates(tmp_path/'run',plan,state,reviewer)
    else:
        p.review_candidates(tmp_path/'run',plan,state,reviewer)
        result=next(iter(state['reviews'].values()))
        assert result['decision']=='repair_required' and result['checks']['layout'] is False
        saved=registry.get(root,book_id='book')[0]
        assert saved['status']=='candidate' and saved['review']['decision']=='repair_required'
    assert reviewer.calls[0][0]['expectation']['layout_object_inventory']['bed']==1


def test_legacy_policy_does_not_retrofit_counts_and_reviewed_front_is_not_recalled(images,tmp_path,monkeypatch):
    entity=place();entity['required_views']=['front']
    assert p._review_layout_inventory(dict(config={}),entity) is None
    plan=dict(packet=dict(places=[entity],characters=[],shots=[],book_id='book'),config=dict(generation_reference_policy='geometry_materials_only/v1'))
    monkeypatch.setattr(p,'_lookup',lambda *args,**kwargs:dict(status='reviewed'))
    reviewer=FakeReviewer();assert p.review_candidates(tmp_path,plan,{},reviewer)==0 and reviewer.calls==[]


@pytest.mark.parametrize('baseline,missing,count,accepted',[
    (True,True,0,True),(False,True,0,False),(False,False,0,True),(False,False,2,False),(False,False,None,False)])
def test_registry_lookup_rechecks_new_scope_but_exact_legacy_front_remains_usable(monkeypatch,baseline,missing,count,accepted):
    entity=place();plan=dict(config=dict(generation_reference_policy='geometry_materials_only/v1'),packet=dict(places=[entity]))
    raw=dict(asset_id='asset',version=1,kind='place',view='front',status='reviewed')
    receipt=dict(decision='accepted',checks=dict.fromkeys(v.PLACE_CHECKS,True),
        layout_object_inventory=v.inventory_from_layout(entity['spatial_layout']),object_observations=objects(count))
    if missing:receipt.pop('object_observations');receipt.pop('layout_object_inventory')
    monkeypatch.setattr(p,'_raw_lookup',lambda *args:deepcopy(raw))
    monkeypatch.setattr(p,'_dependencies',lambda *args:([],True))
    monkeypatch.setattr(p,'_entity',lambda *args:entity)
    monkeypatch.setattr(p,'_latest_review',lambda *args:deepcopy(receipt))
    monkeypatch.setattr(p.generation_refs,'baseline_front',lambda *args:baseline)
    if missing and not baseline:
        with pytest.raises(ValueError):p._lookup(plan,{})
    else:
        result=p._lookup(plan,{})
        assert (result['status']=='reviewed') is accepted
    assert raw['status']=='reviewed' # No registry rewrite or old receipt upgrade.


@pytest.mark.parametrize('change',[
    lambda r:r.pop('object_observations'),
    lambda r:r['subreviews'].clear(),
    lambda r:r['object_observations']['bed'].update(count=None),
    lambda r:r['object_observations']['bed'].update(count=2,regions=objects(2)['bed']['regions']),
    lambda r:r['subreviews'][0]['object_observations']['bed'].update(count=1,regions=objects(1)['bed']['regions']),
])
def test_first_frame_persistent_gate_blocks_missing_unknown_excess_or_disagreement(change):
    entity=place();plan=dict(config=dict(generation_reference_policy='geometry_materials_only/v1'))
    value=dict(decision='accepted',checks=dict.fromkeys(v.PLACE_CHECKS,True),
        layout_object_inventory=v.inventory_from_layout(entity['spatial_layout']),object_observations=objects(0))
    value['subreviews']=[deepcopy(value)];change(value)
    before=deepcopy(value)
    with pytest.raises(ValueError):p._verify_first_frame_inventory(plan,entity,value)
    assert value==before # Qualification never changes an old receipt.


def test_first_frame_persistent_gate_accepts_actual_bound_room_observations():
    entity=place();plan=dict(config=dict(generation_reference_policy='geometry_materials_only/v1'))
    value=dict(decision='accepted',checks=dict.fromkeys(v.PLACE_CHECKS,True),
        layout_object_inventory=v.inventory_from_layout(entity['spatial_layout']),object_observations=objects(0))
    value['subreviews']=[deepcopy(value)];before=deepcopy(value)
    assert p._verify_first_frame_inventory(plan,entity,value) is None and value==before


def test_h3_ready_consumer_cannot_skip_furniture_qualification(tmp_path,h3_service,monkeypatch):
    asset,run,config=h3_setup(tmp_path,h3_service,environment_v4=True)
    checked=[]
    def reject(plan,entity,review):
        checked.append((entity['id'],review['target_sha256']))
        raise ValueError('fixture_unknown_furniture')
    monkeypatch.setattr(p,'_verify_first_frame_inventory',reject)
    with pytest.raises(h3.HandoffIntegrityError,match='h3_ready_furniture_inventory_invalid'):
        h3.prepare_from_ready(asset,run,config)
    assert checked and not run.exists() and h3_service.posts==[]
