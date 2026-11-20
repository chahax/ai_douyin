"""CPU crops and real temporary HTTP reference graphs, not visual approval."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import pytest

from src.content_factory import visual_residence_style_v5 as s
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_environment_v4 as e
from test_visual_environment_v4 import static_place,EnvironmentReviewer
from test_visual_asset_pipeline_v3 import service,setup,accept_direct,write


def result(request):
    return dict(schema='residence_style_visual_review/v5',mode=request['mode'],decision='accepted',
        target_sha256=s.sha(request['target']),style_binding_sha256=p.fingerprint(request['binding']),
        source_context_sha256=request['source_context']['sha256'],
        patch_bindings=[{k:q[k] for k in ('slot','material_key','sha256')} for q in request['patches']],
        checks={k:True for k in s.CHECKS},patch_checks=[dict(slot=q['slot'],material_match=True,texture_only=True,identifiable=True,
            evidence='Protocol fixture only, not semantic acceptance.') for q in request['patches']],
        completion_known=True,outcome_unknown=False,retryable=False,style_reference_ready=request['mode']=='reference',
        layout_approved=False,novel_fidelity_approved=False,visual_evidence=['CPU protocol fixture only.'])


def packet_setup(tmp_path,service):
    _,packet,config=setup(tmp_path,service);packet['characters']=[];packet['places']=[]
    for pid in ('master','room2','kitchen'):
        entity=static_place();entity.update(id=pid,design_version='v5_'+pid,required_views=['front'],style_group_id='home',style_version='style_v1')
        if pid=='kitchen':entity['static_materials']['floor_surface']='concrete'
        packet['places'].append(entity)
    shared=dict(packet['places'][0]['static_materials'],wood_color='wood',era='contemporary_low_cost_older_home',base_lighting_family='simple_warm_ceiling_bulb')
    group=dict(id='home',style_version='style_v1',master_place_id='master',members=['master','room2','kitchen'],source=packet['source'],
        source_ids=['SP_001'],shared_style=shared,required_material_slots=['wall','floor','wood'],
        room_materials={x['id']:deepcopy(x['static_materials']) for x in packet['places']})
    group['definition_sha256']=p.fingerprint(group)
    for entity in packet['places']:entity['home_style_sha256']=group['definition_sha256']
    packet['style_groups']=[group];run=tmp_path/'style_run';p.prepare(run,packet,config)
    return run,packet,p.read(run/'PLAN.json')['config']


def fixture(tmp_path,service):
    run,packet,config=packet_setup(tmp_path,service);entity=packet['places'][0];group=packet['style_groups'][0]
    guide=p._environment_guide(run,entity,'front');source=tmp_path/'master_source.png';shutil.copyfile(guide['path'],source)
    row=library.register(config['library'],source,book_id='book1',entity_id='master',kind='place',view='front',design_version=entity['design_version'],
        provenance=dict(environment_guide=guide,source=packet['source'],dependencies=[],dependency_fingerprint=p.fingerprint([])))
    accept_direct(config,row)
    row=p._raw_lookup(p.read(run/'PLAN.json'),dict(entity_id='master',kind='place',view='front',design_version=entity['design_version']))
    path=p._image_path(p.read(run/'PLAN.json'),row)
    bundle=s.prepare_reference(run,group,entity,row,path,guide,library_path=config['library'])
    return run,packet,config,row,path,bundle


def test_master_layout_then_material_review_unlocks_group_without_cycle(tmp_path,service):
    run,packet,config,row,path,bundle=fixture(tmp_path,service);plan=p.read(run/'PLAN.json')
    req=dict(entity_id='master',kind='place',view='front',design_version='v5_master')
    assert p._lookup(plan,req)['status']=='candidate'
    assert p._lookup(plan,req,_layout_only=True)['status']=='reviewed'
    assert not (Path(bundle['manifest_path']).parent/'READY.json').exists()
    assert s.accept_reference(bundle,result(s.reference_request(bundle)))
    assert p._lookup(plan,req)['status']=='reviewed'
    assert p._lookup(plan,req)['residence_style_binding']['master_identity']==s.identity(row)
    assert p._style_reference_for_entity(run,plan,packet['places'][1])['manifest_sha256']==bundle['manifest_sha256']


def test_actual_frozen_crops_recompute_and_incompatible_floor_is_not_transferred(tmp_path,service):
    run,packet,config,row,path,bundle=fixture(tmp_path,service)
    request=s.target_request(bundle,packet['places'][2],path)
    assert [q['slot'] for q in request['patches']]==['wall','wood']
    assert request['semantic']['room_overrides']['floor_surface']=='concrete'
    for patch in bundle['patches']:
        raw,_=s._crop_bytes(path,patch['pixel_roi'])
        assert raw==Path(patch['path']).read_bytes() and len(raw)>0
        assert MIN(patch['pixel_roi'])>=64
    assert s.verify_result(request,result(request))


def MIN(roi):return min(roi['width'],roi['height'])


@pytest.mark.parametrize('mutation',[
    lambda r:r['checks'].update(wear=1),lambda r:r['patch_checks'][0].update(texture_only='true'),
    lambda r:r.update(completion_known=False,outcome_unknown=True),lambda r:r.update(style_binding_sha256='0'*64),
    lambda r:r['patch_bindings'][0].update(sha256='0'*64),lambda r:r['patch_checks'].pop(),
])
def test_self_claimed_or_unbound_style_acceptance_is_rejected(tmp_path,service,mutation):
    *_,bundle=fixture(tmp_path,service);request=s.reference_request(bundle);receipt=result(request);mutation(receipt)
    with pytest.raises(ValueError):s.verify_result(request,receipt)
    assert not (Path(bundle['manifest_path']).parent/'READY.json').exists()


def test_unknown_material_review_can_be_retained_without_ready_or_replay(tmp_path,service):
    *_,bundle=fixture(tmp_path,service);request=s.reference_request(bundle);receipt=result(request)
    receipt.update(decision='unavailable',checks={k:None for k in s.CHECKS},patch_checks=[],completion_known=False,
        outcome_unknown=True,style_reference_ready=False,visual_evidence=[])
    assert s.verify_result(request,receipt,require_accepted=False)
    assert not s.accept_reference(bundle,receipt)
    with pytest.raises(ValueError):s.verify_result(request,receipt)


@pytest.mark.parametrize('part',['crop','master_file','source_file','manifest'])
def test_modified_actual_sources_or_materials_cannot_reuse_ready(tmp_path,service,part):
    run,packet,config,row,path,bundle=fixture(tmp_path,service);s.accept_reference(bundle,result(s.reference_request(bundle)))
    if part=='crop':Path(bundle['patches'][0]['path']).write_bytes(b'changed')
    elif part=='master_file':Path(path).write_bytes(b'changed')
    elif part=='source_file':Path(packet['source']['path']).write_text('changed')
    else:
        manifest=s.read(bundle['manifest_path']);manifest['patches'][0]['pixel_roi']['x']+=1;write(Path(bundle['manifest_path']),manifest)
    with pytest.raises((ValueError,OSError)):s.load_reference(bundle['manifest_path'],packet['style_groups'][0],row,path)


def test_new_master_version_or_group_definition_invalidates_derived_materials(tmp_path,service):
    run,packet,config,row,path,bundle=fixture(tmp_path,service);s.accept_reference(bundle,result(s.reference_request(bundle)))
    changed=tmp_path/'new_master.png';Image.new('RGB',(768,1024),'blue').save(changed)
    new=library.register(config['library'],changed,book_id='book1',entity_id='master',kind='place',view='front',design_version='v5_master')
    with pytest.raises(s.StyleStale):s.load_reference(bundle['manifest_path'],packet['style_groups'][0],row,path)
    assert new['version']>row['version']
    group=deepcopy(packet['style_groups'][0]);group['style_version']='changed'
    with pytest.raises(s.StyleStale):s.group_for(dict(packet,style_groups=[group]),packet['places'][0])


def test_cross_group_reference_or_dropped_compatible_patch_is_rejected(tmp_path,service):
    run,packet,config,row,path,bundle=fixture(tmp_path,service)
    entity=deepcopy(packet['places'][1]);entity['style_group_id']='other'
    with pytest.raises(s.StyleStale):s.target_request(bundle,entity,path)
    request=s.target_request(bundle,packet['places'][1],path);request['patches'].pop();request['binding']['patches'].pop();request['semantic']['material_slots'].pop()
    with pytest.raises(ValueError,match='scope_changed'):s.verify_result(request,result(request))


def test_surface_masks_do_not_change_guide_pixels_and_never_include_openings_as_wall():
    entity=static_place();normal=e._perspective(entity['spatial_layout'],'front',(320,320))
    image,masks=e._perspective(entity['spatial_layout'],'front',(320,320),return_surfaces=True)
    assert np.array_equal(np.array(normal),np.array(image))
    assert not np.any(masks['wall']&masks['floor']) and not np.any(masks['wall']&masks['wood'])
    window=np.all(np.array(image)==[119,153,169],axis=-1)
    assert window.any() and not masks['wall'][window].any()
    with pytest.raises(ValueError,match='too_small'):s._rectangle(np.zeros((128,128),dtype=bool))


def test_reference_rejects_wrong_guide_camera_and_renderer_upgrade(tmp_path,service,monkeypatch):
    run,packet,config,row,path,bundle=fixture(tmp_path,service);entity=packet['places'][0]
    guide=deepcopy(row['provenance']['environment_guide']);guide['camera']['fov']=35
    with pytest.raises(ValueError,match='alignment_invalid'):
        s.prepare_reference(run,packet['style_groups'][0],entity,row,path,guide,library_path=config['library'])
    request=s.reference_request(bundle);receipt=result(request)
    monkeypatch.setattr(e,'RENDERER','future-renderer')
    with pytest.raises(s.StyleStale):s.verify_result(request,receipt)


def test_roi_selection_prefers_usable_patch_over_larger_but_too_narrow_stripe():
    mask=np.zeros((500,200),dtype=bool);mask[:,:30]=True;mask[100:200,70:170]=True
    roi=s._rectangle(mask)
    assert MIN(roi)>=64 and roi['x']>=70


def test_actual_exposure_prefers_bright_smaller_surface_and_does_not_edit_pixels():
    mask=np.zeros((512,512),dtype=bool);mask[:,:180]=True;mask[120:300,260:440]=True
    rgb=np.zeros((512,512,3),dtype=np.uint8)+5
    yy,xx=np.indices((180,180));grain=((xx+yy)%8)*3
    rgb[120:300,260:440]=np.stack([125+grain,85+grain,45+grain],axis=-1)
    source=Image.fromarray(rgb);before=source.tobytes();roi,quality=s._exposed_rectangle(mask,source)
    assert roi['x']>=260 and roi['y']>=120 and quality['usable_fraction']>.9
    assert quality['luminance_mean']>.15 and source.tobytes()==before
    assert s._rectangle(mask)['x']<180 # A geometry-area-only selector chooses the dark side.


def test_unidentifiable_actual_dark_surface_cannot_be_promoted_by_roi_scoring():
    with pytest.raises(ValueError,match='exposure_insufficient'):
        s._exposed_rectangle(np.ones((256,256),dtype=bool),Image.new('RGB',(256,256),(2,2,2)))


@pytest.mark.parametrize('change',[
    lambda q,r:q['source_context'].update(sha256='0'*64),
    lambda q,r:r.update(source_context_sha256='0'*64),
    lambda q,r:r['patch_checks'][0].update(identifiable=None),
])
def test_master_context_and_actual_patch_identifiability_are_independently_required(tmp_path,service,change):
    *_,bundle=fixture(tmp_path,service);request=s.reference_request(bundle);receipt=result(request);change(request,receipt)
    with pytest.raises(ValueError):s.verify_result(request,receipt)


class StyleReviewer(EnvironmentReviewer):
    def __init__(self):super().__init__();self.style_calls=[]
    def review_style_materials(self,request,**kwargs):self.style_calls.append(deepcopy(request));return result(request)


def test_real_http_three_fronts_use_geometry_and_crops_never_whole_master_in_sibling(tmp_path,service):
    run,packet,config=packet_setup(tmp_path,service);service.auto_complete=True;reviewer=StyleReviewer()
    original=service.complete
    def complete():
        original()
        for output in service.histories['native_'+str(len(service.posts))]['outputs'].values():
            for item in output['images']:Image.new('RGB',(768,1024),'gray').save(service.output/item['subfolder']/item['filename'])
    service.complete=complete
    state=p.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=40)
    assert state['status']=='assets_ready' and len(service.posts)==3
    assert state['style_references']['home']['status']=='style_reference_ready'
    native_refs=[sum(n['class_type']=='LoadImage' for n in post['prompt'].values()) for post in service.posts]
    assert native_refs==[1,4,3] # master guide; matching room 3 crops; kitchen excludes incompatible floor.
    assert [q['mode'] for q in reviewer.style_calls]==['reference','target','target']
    sibling_jobs=[task for task in state['jobs'].values() if task['requirement']['entity_id']!='master']
    for task in sibling_jobs:
        native=p.read(Path(task['folder'])/'PLAN.json')
        assert all(Path(item['path']).name!='master_source.png' for item in native['inputs'])
        assert task['residence_style']['master_identity']['entity_id']=='master'
