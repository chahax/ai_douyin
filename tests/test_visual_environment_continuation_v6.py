"""Explicit cross-run reference reuse, with no GPU or production origin writes."""
from copy import deepcopy
import hashlib
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_environment_continuation_v6 as c
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_residence_style_v5 as style
from test_visual_residence_appearance_storage_v6 import setup_v6,AppearanceReviewer
from test_visual_asset_pipeline_v3 import service


class BoundReviewer(AppearanceReviewer):
    def review_many(self,requests,**kwargs):
        results=super().review_many(requests,**kwargs)
        for request,result in zip(requests,results):
            if request.get('reference'):result['reference_sha256']=p.file_sha(request['reference'])
        return results


def setup_origin(tmp_path,service):
    run,_,_,_,_,_,_=setup_v6(tmp_path,service);service.auto_complete=True
    original=service.complete
    def complete():
        original()
        for output in service.histories['native_'+str(len(service.posts))]['outputs'].values():
            for image in output['images']:Image.new('RGB',(768,1024),'gray').save(service.output/image['subfolder']/image['filename'])
    service.complete=complete
    state=p.run_until_idle(run,reviewer=BoundReviewer(),poll_seconds=0,max_ticks=30)
    assert state['status']=='assets_ready'
    return run,run.with_name('continued_views')


def tree(root):return {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(root).rglob('*') if path.is_file()}


def test_derivation_is_readonly_and_keeps_source_style_models_with_explicit_output_prefix(tmp_path,service):
    origin,target=setup_origin(tmp_path,service);before=tree(origin);old=p.status(origin)['plan']
    value=c.derive(origin,target,allowed_prefix='residence_multiview_v7')
    assert not target.exists() and tree(origin)==before
    packet,config=value['packet'],value['config']
    assert packet['book_id']==old['packet']['book_id'] and packet['source']==old['packet']['source']
    assert packet['style_groups']==old['packet']['style_groups'] and not packet['shots'] and not packet['characters']
    assert 'import_manifest' not in packet
    assert all(entity['required_views']==['front','reverse','side'] for entity in packet['places'])
    assert config['style_reference_root']==old['config']['style_reference_root']
    assert config['visual_review']==old['config']['visual_review']
    assert config['image_service']['allowed_prefix']=='residence_multiview_v7'
    assert config['max_repair_rounds']==1 and config['max_review_attempts']==2


def test_six_new_views_reuse_original_ready_and_never_rebuild_or_reapprove_reference(tmp_path,service,monkeypatch):
    origin,target=setup_origin(tmp_path,service);before=tree(origin);initial_posts=len(service.posts)
    result=c.prepare(origin,target,allowed_prefix='residence_multiview_v7');assert result['status']=='prepared'
    class TargetOnly(BoundReviewer):
        def review_residence_appearance(self,request,**kwargs):
            assert request['mode']=='target','Continuation must not repeat source appearance approval.'
            return super().review_residence_appearance(request,**kwargs)
    def forbidden(*args,**kwargs):pytest.fail('Continuation may only read original reference bundle.')
    monkeypatch.setattr(style,'prepare_reference',forbidden);monkeypatch.setattr(style,'accept_reference',forbidden)
    reviewer=TargetOnly();state=p.run_until_idle(target,reviewer=reviewer,poll_seconds=0,max_ticks=100)
    assert state['status']=='assets_ready' and len(service.posts)-initial_posts==6
    assert not (target/'style_references').exists() and tree(origin)==before
    assert state['style_references']['home']['inherited_reference'] is True
    assert state['style_references']['home']['source_reference_review_calls']==0
    assert len(reviewer.style_calls)==6 and all(q['mode']=='target' for q in reviewer.style_calls)
    assert p.status(target)['state']['status']=='assets_ready' # New registry rows do not invalidate old-front-only proof.
    assert not (target/'H3_INPUT_READY.json').exists()


@pytest.mark.parametrize('change',[
    lambda value:value['config'].update(max_repair_rounds=2),
    lambda value:value['config'].update(max_review_attempts=3),
    lambda value:value['config'].update(style_reference_root='another-root'),
    lambda value:value['packet']['places'][0].update(design_version='changed'),
    lambda value:value['packet']['shots'].append(dict(id='forbidden-firstframe')),
])
def test_changed_scope_config_or_design_cannot_use_origin_permission(tmp_path,service,change):
    origin,target=setup_origin(tmp_path,service);value=c.derive(origin,target);change(value)
    with pytest.raises(ValueError):p.prepare(target,value['packet'],value['config'])
    assert not target.exists()


@pytest.mark.parametrize('kind',['guide','guide_manifest','ready','reference_review','parent_manifest','crop','source','front_rejected'])
def test_source_or_reference_expiration_stops_new_run_without_dispatch(tmp_path,service,kind):
    origin,target=setup_origin(tmp_path,service);c.prepare(origin,target);before=len(service.posts)
    plan=p.status(origin)['plan'];entity=plan['packet']['places'][0];bundle=p._style_reference_for_entity(origin,plan,entity)
    front=p._raw_lookup(plan,dict(entity_id=entity['id'],kind='place',view='front',design_version=entity['design_version']))
    if kind=='guide':path=front['provenance']['environment_guide']['path']
    elif kind=='guide_manifest':path=front['provenance']['environment_guide']['manifest_path']
    elif kind=='ready':path=Path(bundle['manifest_path']).parent/'READY.json'
    elif kind=='reference_review':path=Path(bundle['manifest_path']).parent/'REFERENCE_REVIEW.json'
    elif kind=='parent_manifest':path=bundle['inherited_reference']['path']
    elif kind=='crop':path=bundle['patches'][0]['path']
    elif kind=='source':path=plan['packet']['source']['path']
    else:
        library.review(plan['config']['library'],book_id=plan['packet']['book_id'],asset_id=front['asset_id'],version=front['version'],
            file_sha256=front['sha256'],decision='rejected',reviewer='fixture_source_revoked',checks={},
            evidence=dict(image_sha256=front['sha256'],observations=['Known source revoked for protocol test.']))
        path=None
    if path:Path(path).write_bytes(b'changed')
    with pytest.raises((ValueError,OSError,KeyError)):p.status(target)
    assert len(service.posts)==before


def test_origin_mutable_status_is_not_used_as_an_immutable_global_manifest(tmp_path,service):
    origin,target=setup_origin(tmp_path,service);c.prepare(origin,target)
    state=p.read(origin/'STATE.json');state.update(status='paused',ui_note='Only mutable status changed.')
    p.write(origin/'STATE.json',state)
    assert p.status(target)['state']['status']=='prepared'


def test_invalid_views_or_origin_target_are_refused(tmp_path,service):
    origin,target=setup_origin(tmp_path,service)
    for views in [('front',),('side','side'),('back',)]:
        with pytest.raises(ValueError):c.derive(origin,target,views=views)
    with pytest.raises(ValueError):c.derive(origin,origin)
    with pytest.raises(ValueError):c.derive(origin,origin/'nested')
    with pytest.raises(ValueError):c.derive(origin,target,allowed_prefix='../escape')
