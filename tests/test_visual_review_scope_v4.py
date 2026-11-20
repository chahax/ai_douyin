"""Applicability/lineage/transport boundaries, not model quality assertions."""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import pytest
from PIL import Image

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_registry_v3 as a
from src.content_factory.visual_review_scope_v4 import character_scope
from test_visual_asset_review_v3 import images,provider,observation,roi_expectation


def scoped_expectation(source,view='face'):
    value=roi_expectation(source);value['view']=view
    return value


@pytest.mark.parametrize('view,excluded',[
    ('face',['clothing']),('clothing',['identity']),('hands',['identity','clothing'])])
def test_invisible_checks_remain_null_and_explicitly_not_applicable(images,tmp_path,view,excluded):
    raw=observation();raw['observations'].update(framing=view,age_band='unknown' if view!='face' else 'child')
    raw['checks'].update({k:None for k in excluded})
    if view!='face':raw['observations']['people_count']=0
    with provider([raw]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],scoped_expectation(images[0],view),tmp_path/'job')
    assert result['decision']=='accepted' and result['view_scope']['not_applicable']==excluded
    assert all(result['checks'][k] is None for k in excluded)
    assert result['view_scope']['identity_basis']==('visual_comparison' if view=='face' else 'canonical_roi_lineage')
    assert 'SERVER_CHECK_SCOPE' in requests[1]['messages'][0]['content']


@pytest.mark.parametrize('identity',[None,False])
def test_face_identity_is_still_required(images,tmp_path,identity):
    raw=observation();raw['observations']['framing']='face';raw['checks'].update(identity=identity,clothing=None)
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],scoped_expectation(images[0]),tmp_path/'job')
    assert result['decision']==('needs_review' if identity is None else 'repair_required')
    assert result['checks']['identity'] is identity


def test_unbound_crop_cannot_skip_identity_or_clothing(images,tmp_path):
    exp=scoped_expectation(images[0]);exp.pop('reference_roi_source')
    raw=observation();raw['observations']['framing']='face';raw['checks']['clothing']=None
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],exp,tmp_path/'job')
    assert result['decision']=='needs_review' and result['view_scope']['not_applicable']==[]


def test_composition_keeps_full_character_checks_even_when_view_face(images,tmp_path):
    exp=scoped_expectation(images[0]);exp['composition_subject']={'id':'actor','description':'Fictional subject.'}
    raw=observation();raw['observations']['framing']='face';raw['checks']['clothing']=None
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(images[1],images[0],exp,tmp_path/'job')
    assert result['decision']=='needs_review' and result['view_scope']['required']==list(v.CHARACTER_CHECKS)


def test_scoped_details_still_reject_full_body_substitution(images,tmp_path):
    raw=observation();raw['checks']['clothing']=None
    with provider([raw]) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],images[0],scoped_expectation(images[0]),tmp_path/'job')
    assert result['decision']=='repair_required' and result['checks']['view'] is False


def place_observation():
    return observation(checks={k:True for k in v.PLACE_CHECKS},
        observations=dict(people_count=0,age_band='unknown',orientation='unknown',framing='environment'))


def environment_context():
    return dict(layout_design='One worn wooden bed beside a window; door on the opposite wall.',space_type='bedroom',
        camera_description='From the doorway looking toward the bed.',
        visible_anchors=[dict(id='bed',kind='bed',description='One wooden bed.',screen_region='left',distance_band='middle')],
        comparison_rule='Compare this camera view against the actual fixed-room guide.')


def test_empty_environment_front_does_not_require_human_pose(images,tmp_path):
    with provider([place_observation()]) as (url,requests):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review(
            images[1],expectation=dict(kind='place',view='front',expected_people=0,locate_rois=[]),evidence_dir=tmp_path/'job')
    assert result['decision']=='accepted' and result['observations']['pose_view']=='unknown'
    assert result['checks']['view'] is True and result['direction_auxiliary'] is None


def test_actual_layout_guide_is_sent_as_third_image_with_semantic_context(images,tmp_path):
    guide=tmp_path/'guide.png';Image.new('RGB',(160,128),'tan').save(guide)
    with provider([place_observation()]) as (url,requests):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review_many([dict(target=images[1],reference=images[0],layout_guide=guide,
            expectation=dict(kind='place',view='front',expected_people=0,environment_context=environment_context()))],evidence_dir=tmp_path/'job')[0]
    assert result['decision']=='accepted' and result['layout_guide_sha256']==v.file_sha(guide)
    assert len(requests[0]['messages'][0]['images'])==1 and len(requests[1]['messages'][0]['images'])==3
    prompt=requests[1]['messages'][0]['content']
    assert 'ACTUAL_LAYOUT_GUIDE' in prompt and 'screen_region' in prompt and 'camera_description' in prompt
    assert str(guide) not in prompt and v.file_sha(guide) not in prompt


def test_changing_actual_guide_cannot_keep_old_acceptance(images,tmp_path):
    guide=tmp_path/'guide.png';Image.new('RGB',(160,128),'tan').save(guide)
    def mutate(body):
        if len(body['messages'][0].get('images',[]))==3:Image.new('RGB',(160,128),'red').save(guide)
    with provider([place_observation()],on_post=mutate) as (url,_):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([
            dict(target=images[1],reference=images[0],layout_guide=guide,expectation=dict(kind='place',view='reverse',expected_people=0))],evidence_dir=tmp_path/'job')[0]
    assert result['decision']=='unavailable' and 'changed' in result['error']


def test_environment_audit_coordinates_cannot_be_smuggled_into_model_context(images):
    context=environment_context();context['room_coordinates']=[1,2,3]
    with pytest.raises(ValueError,match='semantic_context'):
        v._prepared(dict(target=images[1],expectation=dict(kind='place',environment_context=context)))


def lineage_fixture(tmp_path,view='face'):
    library=tmp_path/'library';source=tmp_path/'canonical.png';detail=tmp_path/'detail.png'
    Image.new('RGB',(64,96),'gray').save(source);Image.new('RGB',(64,96),'silver').save(detail)
    front=a.register(library,source,book_id='b',entity_id='actor',kind='character',view='front',design_version='v1')
    boxes={'face':dict(x=16,y=4,width=32,height=32),'clothing':dict(x=8,y=32,width=48,height=32),'hands':dict(x=4,y=60,width=56,height=20)}
    native=dict(decision='accepted',target_sha256=front['sha256'],checks={k:True for k in v.CHARACTER_CHECKS},rois=boxes,
        completion_known=True,outcome_unknown=False,visual_evidence=['Synthetic contract fixture, not semantic QA.'])
    a.review(library,book_id='b',asset_id=front['asset_id'],version=front['version'],file_sha256=front['sha256'],decision='accepted',
        reviewer='protocol_fixture',checks=native['checks'],evidence=dict(image_sha256=front['sha256'],observations=native['visual_evidence'],source_review=native,review=v.digest(native)))
    dependency={k:front[k] for k in ('asset_id','version','entity_id','kind','view','design_version','sha256')}
    row=a.register(library,detail,book_id='b',entity_id='actor',kind='character',view=view,design_version='v1',provenance=dict(dependencies=[dependency]))
    origin=dict(asset_id=front['asset_id'],version=front['version'],image_sha256=front['sha256'],review_sha256=v.digest(native))
    prepared=v._prepared(dict(target=detail,reference=source,expectation=dict(kind='character',view=view,reference_roi=boxes[view],reference_roi_source=origin)))
    scope=character_scope(view,bound_roi=True)
    checks={k:True if k in scope['required'] else None for k in v.CHARACTER_CHECKS}
    result=dict(decision='accepted',target_sha256=row['sha256'],reference_sha256=front['sha256'],checks=checks,
        view_scope=scope,reference_roi_evidence=prepared['reference_roi_evidence'],completion_known=True,outcome_unknown=False)
    return library,front,row,result


def scoped_registration(library,row,result):
    return a.review(library,book_id='b',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],decision='accepted',
        reviewer='protocol_fixture',checks={k:x for k,x in result['checks'].items() if type(x) is bool},
        evidence=dict(image_sha256=row['sha256'],observations=['Synthetic contract fixture, not semantic QA.'],review=v.digest(result),source_review=result))


@pytest.mark.parametrize('view',['face','clothing','hands'])
def test_registry_independently_accepts_only_current_bound_detail_scope(tmp_path,view):
    library,front,row,result=lineage_fixture(tmp_path,view)
    value=scoped_registration(library,row,result)
    assert value['status']=='reviewed' and value['production_approved'] is False
    assert value['review']['evidence']['source_review']['checks']==result['checks']


@pytest.mark.parametrize('tamper',['crop','scope','origin','version','review','generation'])
def test_registry_rejects_untrusted_detail_lineage(tmp_path,tamper):
    library,front,row,result=lineage_fixture(tmp_path)
    if tamper=='crop':result['reference_roi_evidence']['crop_sha256']='a'*64
    elif tamper=='scope':result['view_scope']['required']=['view']
    elif tamper=='origin':result['reference_roi_evidence']['roi_source']={}
    elif tamper=='version':result['reference_roi_evidence']['roi_source']['version']=99
    elif tamper=='review':result['reference_roi_evidence']['roi_source']['review_sha256']='a'*64
    elif tamper=='generation':
        # A different registered detail with no generation reference cannot claim lineage.
        row=a.register(library,tmp_path/'detail.png',book_id='b',entity_id='actor',kind='character',view='face',design_version='v1',input_sha256='f'*64)
    with pytest.raises(ValueError):scoped_registration(library,row,result)
    assert a.get(library,book_id='b',asset_id=row['asset_id'],version=row['version'])[0]['status']=='candidate'


def test_new_canonical_version_withdraws_old_scoped_detail_without_changing_history(tmp_path):
    library,front,row,result=lineage_fixture(tmp_path,'hands');scoped_registration(library,row,result)
    before=(library/'reviews'/a.get(library,book_id='b',asset_id=row['asset_id'])[0]['review']['review_id']).with_suffix('.json').read_bytes()
    image=tmp_path/'new_canonical.png';Image.new('RGB',(64,96),'red').save(image)
    a.register(library,image,book_id='b',entity_id='actor',kind='character',view='front',design_version='v1')
    value=a.get(library,book_id='b',asset_id=row['asset_id'])[0]
    assert value['status']=='candidate' and value['dependency_error']=='detail_canonical_version_changed'
    record=library/'reviews'/(value['review']['review_id']+'.json')
    assert record.read_bytes()==before


def test_revoked_canonical_withdraws_old_scoped_detail(tmp_path):
    library,front,row,result=lineage_fixture(tmp_path);scoped_registration(library,row,result)
    a.review(library,book_id='b',asset_id=front['asset_id'],version=front['version'],file_sha256=front['sha256'],decision='unavailable',
        reviewer='protocol_fixture',checks={},evidence=dict(reason='Original source now uncertain.'))
    value=a.get(library,book_id='b',asset_id=row['asset_id'])[0]
    assert value['status']=='candidate' and value['dependency_error']=='detail_canonical_not_currently_reviewed'


def test_place_review_with_non_character_scope_none_is_compatible(tmp_path):
    source=tmp_path/'room.png';Image.new('RGB',(64,96),'gray').save(source)
    library=tmp_path/'library';row=a.register(library,source,book_id='b',entity_id='room',kind='place',view='front')
    native=dict(view_scope=None,decision='accepted',target_sha256=row['sha256'],checks={k:True for k in v.PLACE_CHECKS})
    value=a.review(library,book_id='b',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],decision='accepted',
        reviewer='fixture_protocol',checks=native['checks'],evidence=dict(image_sha256=row['sha256'],observations=['Fixture room.'],source_review=native,review=v.digest(native)))
    assert value['status']=='reviewed'
