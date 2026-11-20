"""Deterministic geometry/input-contract tests, not photoreal visual acceptance."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest
from jsonschema import ValidationError

from src.content_factory import visual_environment_v4 as e
from src.content_factory import visual_asset_pipeline_v3 as f
from src.content_factory import visual_asset_registry_v3 as registry
from test_visual_asset_pipeline_v3 import FakeReviewer,service,setup,register_candidate,accept_direct,write


def layout():
    return dict(schema=e.VERSION,space_type='interior',room=dict(width=4,depth=5,height=2.8),
        openings=[dict(id='door',kind='door',wall='south',offset=3.1,width=.8,bottom=0,height=2.1),
            dict(id='window',kind='window',wall='north',offset=1.6,width=1.2,bottom=1,height=1.1)],
        objects=[dict(id='bed',kind='bed',description='One old narrow wooden bed.',center=[.9,2.6],size=[1.3,2,.5],yaw=0,color='wood'),
            dict(id='table',kind='table',description='A worn small wooden table.',center=[3,3.6],size=[.8,.7,.75],yaw=0,color='brown')],
        cameras=dict(front=dict(eye=[3.2,.4,1.6],target=[1.8,3.1,1.1],fov=80),
            reverse=dict(eye=[.45,4.5,1.6],target=[2.8,1.2,1.1],fov=80),
            side=dict(eye=[3.7,2.3,1.6],target=[.3,2.5,1.1],fov=80)),
        design_note='Furniture proportions and exact coordinates are production choices; no new story event.')


def place():
    return dict(id='room',design_version='geometry_v4',required_views=['front','reverse'],
        layout_design='A small worn bedroom, one narrow bed along the west wall, north window and southern door.',
        front_prompt='An empty worn bedroom, peeling plaster, one narrow bed and small wooden table.',spatial_layout=layout())


def test_schema_and_coordinate_contract_have_real_normal_positive():
    assert e.validate_layout(layout())==layout()
    assert e.layout_schema()['properties']['schema']['const']==e.VERSION


@pytest.mark.parametrize('change,message',[
    (lambda p:p['objects'][0].update(center=[.1,.1]),'outside_room'),
    (lambda p:p['objects'][1].update(center=[.9,2.6]),'overlap'),
    (lambda p:p['openings'][0].update(bottom=.1),'reach_floor'),
    (lambda p:p['openings'][1].update(width=3),'outside_wall'),
    (lambda p:p['cameras']['reverse'].update(eye=[3.2,.5,1.6],target=[1.8,3.1,1.1]),'opposing'),
    (lambda p:p['cameras']['side'].update(eye=[3.2,.5,1.6],target=[1.8,3.1,1.1]),'distinct'),
    (lambda p:p['cameras']['front'].update(eye=[.9,2.6,.2]),'inside_object'),
    (lambda p:p['cameras']['front'].update(target=[3.2,.4,1.6]),'degenerate'),
    (lambda p:p['cameras']['front'].update(eye=[5,.4,1.6]),'outside_room'),
    (lambda p:p['objects'][1].update(id='bed'),'duplicate'),
    (lambda p:p['objects'][0].update(yaw=90),'outside_room'),
])
def test_invalid_world_layout_is_rejected_instead_of_silently_reinterpreted(change,message):
    data=layout();change(data)
    with pytest.raises(ValueError,match=message):e.validate_layout(data)


def test_openings_overlap_in_same_wall_but_not_in_separate_wall():
    data=layout();data['openings'].append(dict(id='new',kind='window',wall='north',offset=1.8,width=.5,bottom=1,height=1))
    with pytest.raises(ValueError,match='openings_overlap'):e.validate_layout(data)
    data['openings'][-1]['wall']='west';assert e.validate_layout(data)


def test_bad_types_and_unknown_geometry_are_not_accepted():
    data=layout();data['room']['width']=True
    with pytest.raises((ValidationError,ValueError)):e.validate_layout(data)
    data=layout();data['objects'][0]['size'][2]=float('nan')
    with pytest.raises(ValueError):e.validate_layout(data)
    data=layout();data['room']['secret_path']='x'
    with pytest.raises(ValidationError):e.validate_layout(data)


def test_guide_pixels_reproducible_and_opposite_cameras_are_not_same_image(tmp_path):
    one=e.render_guides(layout(),tmp_path/'one',width=320,height=240)
    before={k:v['sha256'] for k,v in one['views'].items()}
    assert e.render_guides(layout(),tmp_path/'one',width=320,height=240)==one
    two=e.render_guides(layout(),tmp_path/'two',width=320,height=240)
    assert before=={k:v['sha256'] for k,v in two['views'].items()}
    assert len(set(before.values()))==4
    # A real rendering, not a blank rectangle with a success sidecar.
    for row in one['views'].values():
        with Image.open(row['path']) as image:assert len(image.getcolors(320*240))>=5


def test_large_floor_polygon_cannot_cover_nearer_solid_furniture():
    import numpy as np
    image=np.array(e._perspective(layout(),'front',(320,240)))
    # The foreground bed is prominent in this fixed camera. The former average-
    # depth painter rendered the floor over most of it; a depth-buffer must not.
    wood=np.all(image==[169,133,87],axis=-1)
    assert wood.mean()>.10


def test_layout_changes_pixels_and_frozen_input_or_guide_edit_stops(tmp_path):
    data=layout();one=e.render_guides(data,tmp_path/'one',width=320,height=240)
    data['objects'][1]['center']=[2.8,4.1]
    two=e.render_guides(data,tmp_path/'two',width=320,height=240)
    assert one['views']['front']['sha256']!=two['views']['front']['sha256']
    with pytest.raises(ValueError,match='frozen'):e.render_guides(data,tmp_path/'one',width=320,height=240)
    Path(one['views']['front']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='guide_file_changed'):e.render_guides(layout(),tmp_path/'one',width=320,height=240)


def test_review_context_is_semantic_and_camera_changes_screen_relationships():
    p=place();front=e.review_context(p,'front');reverse=e.review_context(p,'reverse')
    assert front['camera_description']!=reverse['camera_description']
    assert front['visible_anchors']!=reverse['visible_anchors']
    raw=json.dumps(front)
    assert 'eye' not in front and 'target' not in front and 'sha256' not in raw and 'pixel' not in raw
    for anchor in front['visible_anchors']:assert set(anchor)=={'id','kind','description','screen_region','distance_band'}
    assert 'no people' in e.place_prompt(p,'front').lower()
    assert 'Spatial art design' not in e.design_description(p) # Numeric JSON stays out of MODEL descriptions.


def setup_environment(tmp_path,service,*,shots=False,views=('front','reverse')):
    run,packet,config=setup(tmp_path,service,shots=shots)
    # New frozen task; old fixture is never relabeled as v4 accepted text.
    packet['places']=[place()];packet['places'][0]['required_views']=list(views)
    if not shots:packet['characters']=[]
    config['first_frame_width']=64;config['first_frame_height']=80
    run=tmp_path/'environment_run';f.prepare(run,packet,config)
    return run,packet,config


class EnvironmentReviewer(FakeReviewer):
    def review_many(self,requests,**kwargs):
        results=super().review_many(requests,**kwargs)
        for request,result in zip(requests,results):
            if request.get('layout_guide'):result['layout_guide_sha256']=f.file_sha(request['layout_guide'])
        return results
    def review_composition(self,path,**kwargs):
        result=super().review_composition(path,**kwargs)
        if kwargs['place'].get('layout_guide'):result['layout_guide_sha256']=f.file_sha(kwargs['place']['layout_guide'])
        return result


@pytest.mark.parametrize('wrong_reference',[None,'0'*64])
def test_nonfront_environment_review_must_return_exact_same_room_front_sha(tmp_path,service,wrong_reference):
    run,packet,config=setup_environment(tmp_path,service,views=('front','reverse'))
    service.auto_complete=True
    class WrongSource(EnvironmentReviewer):
        def review_many(self,requests,**kwargs):
            results=super().review_many(requests,**kwargs)
            for request,result in zip(requests,results):
                if request['expectation']['kind']=='place' and request['expectation']['view']!='front':
                    result['reference_sha256']=wrong_reference
            return results
    with pytest.raises(ValueError,match='environment_review_front_source_mismatch'):
        f.run_until_idle(run,reviewer=WrongSource(),poll_seconds=0,max_ticks=15)
    reverse=registry.get(config['library'],book_id='book1',kind='place',view='reverse')
    assert reverse and reverse[-1]['status']=='candidate'


def test_legacy_environment_layout_description_is_actually_sent_to_review(tmp_path,service):
    run,packet,config=setup(tmp_path,service,shots=True)
    packet['places'][0].pop('appearance_design');packet['places'][0]['layout_design']='North window and west wooden table.'
    run=tmp_path/'legacy_place';f.prepare(run,packet,config)
    register_candidate(tmp_path,config,entity='room',kind='place')
    reviewer=EnvironmentReviewer();f.tick(run,reviewer=reviewer)
    place_request=next(q for batch in reviewer.calls for q in batch if q['expectation']['kind']=='place')
    assert place_request['expectation']['appearance_description']=='North window and west wooden table.'


def test_v4_requires_nonempty_design_before_any_image_job(tmp_path,service):
    run,packet,config=setup_environment(tmp_path,service)
    packet['places'][0]['layout_design']=''
    with pytest.raises(ValueError,match='description_required'):f.prepare(tmp_path/'bad',packet,config)
    assert service.posts==[]


def test_real_generation_graph_receives_camera_guide_then_canonical_without_cycle(tmp_path,service):
    run,packet,config=setup_environment(tmp_path,service);service.auto_complete=True;reviewer=EnvironmentReviewer()
    result=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=20)
    assert result['status']=='assets_ready' and len(service.posts)==2
    first,reverse=[p['prompt'] for p in service.posts]
    assert sum(n['class_type']=='LoadImage' for n in first.values())==1
    assert sum(n['class_type']=='LoadImage' for n in reverse.values())==2
    guides=[j['environment_guide'] for j in result['jobs'].values()]
    assert {g['view'] for g in guides}=={'front','reverse'} and len({g['sha256'] for g in guides})==2
    requests=[q for batch in reviewer.calls for q in batch]
    assert all(q['expectation']['appearance_description'] and q['layout_guide'] for q in requests)
    assert all(q['expectation']['environment_context']['camera_description'] for q in requests)


def test_changed_layout_with_same_design_version_revokes_older_front_and_reverse(tmp_path,service):
    run,packet,config=setup_environment(tmp_path,service);service.auto_complete=True
    assert f.run_until_idle(run,reviewer=EnvironmentReviewer(),poll_seconds=0,max_ticks=20)['status']=='assets_ready'
    packet['places'][0]['spatial_layout']['objects'][1]['center']=[2.8,4.1]
    changed=tmp_path/'changed';f.prepare(changed,packet,config)
    plan=f.status(changed)['plan'];report=f._requirements_status(plan)
    assert not report['ready'] and len(report['pending'])==2
    front=f._lookup(plan,dict(entity_id='room',kind='place',view='front',design_version='geometry_v4'))
    assert front['dependency_stale'] is True
    assert f.tick(changed)['status']=='image_prepared'


def test_v4_first_frame_consumes_guide_and_review_sees_actual_guide(tmp_path,service):
    run,packet,config=setup_environment(tmp_path,service,shots=True,views=('front',));service.auto_complete=True
    actor=register_candidate(tmp_path,config);accept_direct(config,actor)
    reviewer=EnvironmentReviewer();result=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=20)
    assert result['status']=='h3_inputs_ready'
    frame=next(iter(result['first_frames'].values()));assert frame['environment_guide']['view']=='front'
    final_graph=service.posts[-1]['prompt']
    assert sum(n['class_type']=='LoadImage' for n in final_graph.values())==3 # guide + one visible actor + room
    assert reviewer.compositions[-1]['place']['layout_guide']==frame['environment_guide']['path']
    assert reviewer.compositions[-1]['expectation']['environment_context']['space_type']=='interior'
    Path(frame['environment_guide']['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError,match='guide_file_changed'):f.tick(run,reviewer=reviewer)
    assert not (run/'H3_INPUT_READY.json').exists()


def test_wrong_layout_guide_review_hash_never_approves(tmp_path,service):
    run,packet,config=setup_environment(tmp_path,service,views=('front',));service.auto_complete=True
    class Wrong(EnvironmentReviewer):
        def review_many(self,*args,**kwargs):
            rows=super().review_many(*args,**kwargs)
            for row in rows:row['layout_guide_sha256']='0'*64
            return rows
    with pytest.raises(ValueError,match='review_guide_mismatch'):f.run_until_idle(run,reviewer=Wrong(),poll_seconds=0,max_ticks=20)
    assert not f._requirements_status(f.status(run)['plan'])['ready']


def test_explicit_structured_handoff_really_requires_layout_and_uses_it(tmp_path):
    from test_visual_asset_handoff_v3 import server,material
    from src.content_factory import visual_asset_handoff_v3 as handoff
    accepted,bible,source=material(tmp_path)
    with server() as fake:
        planner=handoff.LocalPlanningClient(dict(service_url=fake.url,environment_contract='layout_camera_v4'))
        with pytest.raises(handoff.PlanningBlocked,match='output_invalid'):
            planner.plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'missing_geometry')
        original=fake.output
        def output(payload):
            result=original(payload)
            if 'scene' not in payload and payload['entity']['id']=='room':
                result['spatial_layout']=layout()
                for item in result['spatial_layout']['objects']:item['base_z']=0
            return result
        fake.output=output
        packet=planner.plan_episode(accepted,bible,'book1',source,evidence_dir=tmp_path/'with_geometry')
        expected=layout()
        for item in expected['objects']:item['base_z']=0
        assert packet['places'][0]['spatial_layout']==expected
        assert packet['places'][0]['design_version'].startswith('environment_')
        assert 'geometry reference' in packet['places'][0]['view_prompts']['reverse']


def test_new_planning_schema_requires_explicit_base_z_but_legacy_read_preserves_bytes():
    legacy=layout();assert e.validate_layout(legacy)==legacy
    e.schema_validate(legacy,e.layout_schema())
    with pytest.raises(ValidationError,match='base_z'):e.schema_validate(legacy,e.layout_schema(require_base_z=True))
    explicit=deepcopy(legacy)
    for item in explicit['objects']:item['base_z']=0
    e.schema_validate(explicit,e.layout_schema(require_base_z=True))
    assert e.validate_layout(explicit)==explicit and all('base_z' not in o for o in legacy['objects'])


@pytest.mark.parametrize('height',[-.1,2.7,float('nan'),float('inf'),True])
def test_invalid_base_z_or_top_above_ceiling_is_rejected(height):
    data=layout();data['objects'][0]['base_z']=height
    with pytest.raises((ValueError,ValidationError)):e.validate_layout(data)


def test_shared_floor_footprint_is_allowed_only_with_separate_vertical_intervals():
    data=layout();raised=deepcopy(data['objects'][0]);raised.update(id='ceiling_fixture',kind='other',base_z=2.5,
        size=[1.3,2,.2],description='A ceiling-mounted fixture.')
    data['objects'].append(raised);assert e.validate_layout(data)
    raised['base_z']=.5;assert e.validate_layout(data) # Touching the bed top is not a solid intersection.
    raised['base_z']=.3
    with pytest.raises(ValueError,match='objects_overlap'):e.validate_layout(data)


def test_camera_may_be_under_an_elevated_object_but_not_inside_its_volume():
    data=layout();eye=data['cameras']['front']['eye']
    data['objects'].append(dict(id='overhead',kind='other',description='A ceiling light above the camera.',
        center=eye[:2],size=[.4,.4,.2],base_z=2.5,yaw=0,color='cream'))
    assert e.validate_layout(data)
    data['cameras']['front']['eye'][2]=2.6
    with pytest.raises(ValueError,match='camera_inside_object'):e.validate_layout(data)
    data['cameras']['front']['eye'][2]=2.4;assert e.validate_layout(data)


def test_elevated_fixture_is_rendered_above_ground_with_visible_underside():
    import numpy as np
    data=layout();item=dict(id='fixture',kind='other',description='A red fixture.',center=[2.2,2.4],size=[.5,.5,.2],
        base_z=0,yaw=0,color='red');data['objects'].append(item)
    assert e.validate_layout(data)
    ground=np.array(e._perspective(data,'front',(320,320)));item['base_z']=2.3
    assert e.validate_layout(data)
    high=np.array(e._perspective(data,'front',(320,320)))
    color=np.array([182,143,136]);ground_pixels=np.where(np.all(ground==color,axis=-1));high_pixels=np.where(np.all(high==color,axis=-1))
    assert len(ground_pixels[0])>100 and len(high_pixels[0])>100
    assert high_pixels[0].mean()<ground_pixels[0].mean()-30


def test_renderer_revision_and_height_change_create_new_guides_without_overwriting_old(tmp_path,service,monkeypatch):
    run,packet,config=setup_environment(tmp_path,service,views=('front',));entity=packet['places'][0]
    current=e.RENDERER
    monkeypatch.setattr(e,'RENDERER','cpu_zbuffer/v3')
    old=f._environment_guide(run,entity,'front',width=96,height=128);old_bytes=Path(old['path']).read_bytes()
    monkeypatch.setattr(e,'RENDERER',current)
    new=f._environment_guide(run,entity,'front',width=96,height=128)
    assert new['path']!=old['path'] and new['renderer']==current=='cpu_zbuffer/v4'
    elevated=deepcopy(entity);elevated['spatial_layout']['objects'][1]['base_z']=1.5
    raised=f._environment_guide(run,elevated,'front',width=96,height=128)
    assert raised['path']!=new['path'] and raised['layout_sha256']!=new['layout_sha256']
    assert Path(old['path']).read_bytes()==old_bytes


def static_place():
    entity=place();entity.update(background_contract=e.STATIC_CONTRACT,
        static_materials=dict(wall_surface='aged_plaster',wall_color='cream',floor_surface='worn_wood',
            condition='worn',lighting='dim_ceiling_light'),
        layout_design='GLOBAL_LAYOUT_AUDIT_ONLY: the entire room has a bed, table, door and window.',
        front_prompt='GLOBAL_FRONT_AUDIT_ONLY: paint every item in the entire room.')
    return entity


def test_static_generation_prompts_crop_to_camera_without_full_room_prose_or_list():
    entity=static_place();front=e.place_prompt(entity,'front');reverse=e.place_prompt(entity,'reverse')
    assert 'GLOBAL_' not in front+reverse and 'Fixed furnishings' not in front+reverse
    assert 'door on the south wall' not in front and 'door on the south wall' in reverse
    assert 'window on the north wall' in front and 'window on the north wall' not in reverse
    assert 'dim warm overhead illumination' in front and 'dim_ceiling_light' not in front
    assert front!=reverse
    # Generation is cropped, while semantic review retains the whole room's design.
    assert 'GLOBAL_LAYOUT_AUDIT_ONLY' in e.review_context(entity,'front')['layout_design']


def test_static_prompt_uses_depth_visibility_not_only_projected_object_centres():
    entity=static_place();data=entity['spatial_layout']
    data['objects']=[dict(id='blocker',kind='cabinet',description='Untrusted description ignored by static compiler.',
        center=[2,2],size=[2,.6,2.2],yaw=0,color='brown'),
        dict(id='hidden',kind='stool',description='A stool fully behind the cabinet.',center=[2,3.2],size=[.5,.5,.5],yaw=0,color='wood')]
    data['cameras']['front']=dict(eye=[2,.5,1.5],target=[2,4.5,1.5],fov=60)
    assert e.validate_layout(data)
    prompt=e.place_prompt(entity,'front')
    assert 'cabinet' in prompt and 'stool' not in prompt and 'Untrusted' not in prompt


@pytest.mark.parametrize('mutation',[
    lambda p:p.pop('static_materials'),lambda p:p['static_materials'].update(lighting='visible bottle and meal bowls'),
    lambda p:p['static_materials'].update(extra='free text'),lambda p:p.update(background_contract='unknown-contract'),
])
def test_static_render_context_rejects_missing_or_untyped_material_conditions(mutation):
    entity=static_place();mutation(entity)
    with pytest.raises(ValueError,match='contract'):e.place_prompt(entity,'front')


def test_static_materials_participate_in_environment_dependency_identity():
    entity=static_place();old=f._environment_design_sha(entity)
    entity['static_materials']['wall_color']='blue'
    assert f._environment_design_sha(entity)!=old
    legacy=place()
    assert f._environment_design_sha(legacy)==f.fingerprint({k:legacy.get(k) for k in ('spatial_layout','layout_design','front_prompt')})


def test_static_first_frame_uses_visible_context_but_review_keeps_complete_design(tmp_path,service):
    _,packet,config=setup_environment(tmp_path,service,shots=True,views=('front',))
    packet['places']=[static_place()];packet['places'][0]['required_views']=['front']
    run=tmp_path/'static_room_run';f.prepare(run,packet,config)
    actor=register_candidate(tmp_path,config);accept_direct(config,actor);service.auto_complete=True
    reviewer=EnvironmentReviewer();state=f.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=20)
    assert state['status']=='h3_inputs_ready'
    graph=service.posts[-1]['prompt']
    prompt=' '.join(node['inputs']['text'] for node in graph.values() if node['class_type']=='CLIPTextEncode')
    assert 'GLOBAL_' not in prompt and 'surface_materials' in prompt
    assert 'GLOBAL_LAYOUT_AUDIT_ONLY' in reviewer.compositions[-1]['expectation']['environment_context']['layout_design']


@pytest.mark.parametrize('kind,count',[('table',5),('stool',5),('chair',6),('shelf',8)])
def test_kind_aware_parts_stay_in_rotated_source_bounds_and_keep_one_identity(kind,count):
    import numpy as np
    item=dict(id='unchanged_identity',kind=kind,center=[2,3],size=[1.2,.8,1.4],base_z=.2,yaw=37,color='wood')
    original=deepcopy(item);parts=e._object_parts(item)
    assert item==original and len(parts)==count and {part['id'] for part in parts}=={item['id']}
    angle=__import__('math').radians(-item['yaw']);c,s=__import__('math').cos(angle),__import__('math').sin(angle)
    coords=[]
    for part in parts:
        for x,y in e._corners(part):
            dx,dy=x-item['center'][0],y-item['center'][1]
            coords.append([dx*c-dy*s,dx*s+dy*c])
        assert e._base(part)>=item['base_z']-1e-7 and e._base(part)+part['size'][2]<=item['base_z']+item['size'][2]+1e-7
    coords=np.array(coords)
    assert np.allclose(coords.min(axis=0),[-.6,-.4]) and np.allclose(coords.max(axis=0),[.6,.4])
    assert min(e._base(p) for p in parts)==item['base_z']
    assert max(e._base(p)+p['size'][2] for p in parts)==pytest.approx(item['base_z']+item['size'][2])


def test_table_guide_has_leg_openings_and_all_subfaces_share_parent_visible_id():
    import numpy as np
    data=layout();data['objects']=[dict(id='table_identity',kind='table',description='A table.',center=[2,2.8],
        size=[1.8,1,1],base_z=0,yaw=0,color='wood')]
    data['cameras']['front']=dict(eye=[2,.5,.55],target=[2,3,.55],fov=70)
    image,visible=e._perspective(data,'front',(320,240),return_visibility=True)
    box=deepcopy(data);box['objects'][0]['kind']='cabinet'
    solid=np.array(e._perspective(box,'front',(320,240)));actual=np.array(image)
    wood=np.array([169,133,87]);solid_count=np.all(solid==wood,axis=-1).sum();actual_count=np.all(actual==wood,axis=-1).sum()
    assert actual_count<solid_count*.65 and actual_count>solid_count*.1
    assert set(visible)=={'table_identity','window'}


def test_static_renderer_changes_qualification_but_legacy_design_hash_is_stable(monkeypatch):
    entity=static_place();new=f._environment_design_sha(entity);legacy=place();old_legacy=f._environment_design_sha(legacy)
    monkeypatch.setattr(e,'RENDERER','cpu_zbuffer/v3')
    assert f._environment_design_sha(entity)!=new
    assert f._environment_design_sha(legacy)==old_legacy
