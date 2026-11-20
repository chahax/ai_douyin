"""Spatial design invariants and real CPU CLI/image artifacts; no model calls."""
from copy import deepcopy
import ast
import json
import math
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from src.content_factory import visual_spatial_scene_v24 as s


@pytest.fixture
def plan(tmp_path):
    root=tmp_path/'source';(root/'sources').mkdir(parents=True)
    for sid in ('S01','S02','S03','S04'):
        (root/'sources'/(sid+'.prompt.txt')).write_text('Source '+sid+' “exact original line '+sid+'”',encoding='utf-8')
    return s.novel_plan(root)


def test_valid_design_carries_states_and_single_prop(plan):
    result=s.validate(plan)
    assert result['furniture_counts']=={'bed':1,'table':1,'door':1,'window':2}
    assert result['semantic_production_approved'] is False
    assert all(a['end_state']==b['start_state'] for a,b in zip(plan['shots'],plan['shots'][1:]))
    assert plan['shots'][2]['prop_transfers'][0]['to']=='su_mo'
    assert plan['shots'][3]['end_state']['actors']['ye_xijue']['visible'] is False


def test_world_heading_points_at_named_scene_partner(plan):
    state=plan['shots'][2]['end_state'];a=state['actors']['su_mo'];b=state['actors']['ye_xijue']
    forward=[math.cos(math.radians(a['facing_deg'])),math.sin(math.radians(a['facing_deg']))]
    delta=[b['position'][i]-a['position'][i] for i in (0,1)];norm=math.hypot(*delta)
    assert sum(forward[i]*delta[i]/norm for i in (0,1))==pytest.approx(1)
    assert plan['shots'][3]['end_state']['actors']['ye_nan']['facing_deg']==0


def test_final_scene_camera_can_see_exit_door(plan):
    door=next(o for o in plan['objects'] if o['kind']=='door')
    camera=plan['cameras'][plan['shots'][3]['camera_id']]
    assert s.project(door['position'],camera)['in_frame']
    assert all(r['projection']['in_frame'] for r in s.projection_report(plan)['items'] if r['shot_id']=='S04')
    assert not any(r['actor_proxy_occluders'] for r in s.projection_report(plan)['items'] if r['shot_id']=='S04')


def test_head_in_frame_is_not_sufficient_when_another_actor_occludes(plan):
    plan['cameras']['door_reverse']={'position':[1.4,4.,1.7],'target':[3.4,2.,1.0],'vertical_fov_deg':70,'near':.05}
    rows=s.projection_report(plan)['items']
    bad=next(r for r in rows if r['shot_id']=='S04' and r['stage']=='start' and r['actor_id']=='ye_xijue')
    assert bad['projection']['in_frame'] and 'su_mo' in bad['actor_proxy_occluders']


@pytest.mark.parametrize('kind',['bed','table','door','window'])
def test_duplicate_physical_object_rejected(plan,kind):
    copy=deepcopy(next(o for o in plan['objects'] if o['kind']==kind));copy['id']+='extra';plan['objects'].append(copy)
    with pytest.raises(s.SpatialError,match='furniture_contract'):s.validate(plan)


def test_duplicate_id_rejected(plan):
    plan['objects'][1]['id']=plan['objects'][0]['id']
    with pytest.raises(s.SpatialError,match='duplicate_object'):s.validate(plan)


def test_furniture_collision_rejected(plan):
    plan['objects'][1]['position'][:2]=plan['objects'][0]['position'][:2]
    with pytest.raises(s.SpatialError,match='furniture_collision'):s.validate(plan)


def test_outside_furniture_rejected(plan):
    plan['objects'][0]['position'][0]=.1
    with pytest.raises(s.SpatialError,match='furniture_outside'):s.validate(plan)


def test_cast_alias_or_invented_child_rejected(plan):
    plan['actors'][2]['id']='invented_child'
    with pytest.raises(s.SpatialError,match='named_cast'):s.validate(plan)


def test_state_extra_character_rejected(plan):
    plan['shots'][0]['start_state']['actors']['extra']=deepcopy(plan['shots'][0]['start_state']['actors']['ye_nan'])
    with pytest.raises(s.SpatialError,match='identity_coverage'):s.validate(plan)


def test_standing_inside_bed_rejected(plan):
    plan['shots'][0]['start_state']['actors']['ye_nan']['position']=[1.25,2.4,0]
    with pytest.raises(s.SpatialError,match='intersects_furniture'):s.validate(plan)


def test_boundary_pose_change_without_carry_rejected(plan):
    plan['shots'][1]['start_state']['actors']['su_mo']['eyes']='open'
    with pytest.raises(s.SpatialError,match='boundary_state'):s.validate(plan)


def test_prop_transfer_required(plan):
    plan['shots'][2].pop('prop_transfers')
    with pytest.raises(s.SpatialError,match='transfer_not_explicit'):s.validate(plan)


def test_prop_cannot_be_two_holders(plan):
    plan['shots'][0]['start_state']['props']['bread_bag']['holder']=['su_mo','ye_xijue']
    with pytest.raises(s.SpatialError,match='one_named_actor'):s.validate(plan)


def test_exit_path_points_cannot_intersect_table(plan):
    plan['shots'][3]['waypoints']['ye_nan'][1]=plan['objects'][1]['position'].copy()
    with pytest.raises(s.SpatialError,match='path_intersects'):s.validate(plan)


def test_path_segment_checks_middle_not_just_vertices(plan):
    path=plan['shots'][3]['waypoints']['ye_nan'];path[1]=[3.3,3.5,0];path[2]=[4.6,3.5,0]
    with pytest.raises(s.SpatialError,match='segment_intersects'):s.validate(plan)


def test_exit_through_wall_instead_of_door_rejected(plan):
    path=plan['shots'][3]['waypoints']['ye_nan'];path[-2]=[4.8,2.7,0];path[-1]=[5.55,2.7,0]
    plan['shots'][3]['end_state']['actors']['ye_nan']['position']=path[-1]
    with pytest.raises(s.SpatialError,match='door_opening'):s.validate(plan)


def test_source_sha_change_rejected(plan):
    Path(plan['shots'][0]['source_prompt']['path']).write_text('changed',encoding='utf-8')
    with pytest.raises(s.SpatialError,match='source_prompt'):s.validate(plan)


def test_dialogue_rewrite_rejected(plan):
    plan['shots'][0]['dialogue_verbatim']=['invented dialogue']
    with pytest.raises(s.SpatialError,match='source_prompt'):s.validate(plan)


@pytest.mark.parametrize('vector',[[0,float('nan'),1],[1,2],['1',2,3],[1,float('inf'),3]])
def test_invalid_vectors_rejected(vector):
    with pytest.raises(s.SpatialError,match='finite_xyz'):s.vec(vector)


def test_camera_projection_front_center_and_behind():
    c={'position':[0,0,1],'target':[0,3,1],'vertical_fov_deg':60}
    assert s.project([0,3,1],c)['uv']==[.5,.5]
    assert s.project([0,-3,1],c)['in_frame'] is False
    assert s.project([10,3,1],c)['in_frame'] is False


def test_camera_degenerate_rejected(plan):
    plan['cameras']['room_front']['target']=plan['cameras']['room_front']['position'].copy()
    with pytest.raises(s.SpatialError,match='degenerate'):s.validate(plan)


def test_furniture_occlusion_uses_ray_segment_not_infinite_line():
    box={'position':[0,2,1],'size':[1,1,1]}
    assert s._ray_hits_box_before_target([0,0,1],[0,3,1],box)
    assert not s._ray_hits_box_before_target([0,0,1],[0,1,1],box)
    assert not s._ray_hits_box_before_target([2,0,1],[2,3,1],box)


def test_projection_report_tracks_exact_named_head_and_exited_cast(plan):
    report=s.projection_report(plan)
    assert len([r for r in report['items'] if r['shot_id']=='S04' and r['stage']=='end'])==1
    lying=next(r for r in report['items'] if r['shot_id']=='S01' and r['stage']=='start' and r['actor_id']=='su_mo')
    assert lying['head_point']==[1.25,3.18,.85]
    assert report['production_approved'] is False


def test_frozen_plan_cannot_overwrite(tmp_path):
    s.freeze(tmp_path/'PLAN.json',{'a':1});s.freeze(tmp_path/'PLAN.json',{'a':1})
    with pytest.raises(s.SpatialError,match='frozen_spatial'):s.freeze(tmp_path/'PLAN.json',{'a':2})


def test_real_cpu_cli_and_diagrams(tmp_path,plan):
    out=tmp_path/'result';source=Path(plan['shots'][0]['source_prompt']['path']).parents[1]
    command=[sys.executable,'-B',str(s.PROJECT/'scripts/run_spatial_scene_v24.py'),'prepare','--run',str(out),'--source',str(source)]
    result=subprocess.run(command,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['model_posts']==0
    manifest=json.loads((out/'DIAGRAMS.json').read_text(encoding='utf-8'))
    assert len(manifest['items'])==9
    for row in manifest['items']:
        with Image.open(row['image']['path']) as im:
            assert im.size==(1100,1000)
            assert len(im.convert('RGB').getcolors(im.width*im.height))>10
        assert s.sha(row['image']['path'])==row['image']['sha256']
    again=subprocess.run(command,capture_output=True,text=True,check=True)
    assert json.loads(again.stdout)==json.loads(result.stdout)
    original=s.sha(out/'SPATIAL_PLAN.json')
    (source/'sources/S01.prompt.txt').write_text('newsource',encoding='utf-8')
    failed=subprocess.run(command,capture_output=True,text=True)
    assert failed.returncode!=0 and s.sha(out/'SPATIAL_PLAN.json')==original


def test_blender_script_is_cpu_and_fixed_named_geometry(tmp_path):
    text=s.blender_script(tmp_path/'plan.json',tmp_path/'out')
    compile(text,'generated_blender_script','exec')
    assert "scene.cycles.device='CPU'" in text
    assert 'CUDA' not in text and 'bpy.ops.wm.save_as_mainfile' in text
    assert "cube('bread_bag_SINGLE'" in text
    assert '__PLAN__' not in text


def test_skin_contract_keeps_identity_colors_only_in_clothing():
    c=s.material_contract();shirts=[]
    for who in s.CAST:
        a=c['actors'][who]
        assert all(a[p]=='human_skin_proxy_v25' for p in ('head','nose_direction','arm'))
        assert a['torso']==who+'_IDENTITY_PLACEHOLDER'
        assert a['shirt_base_color']!=c['skin']['base_color']
        shirts.append(tuple(a['shirt_base_color']))
    assert len(set(shirts))==3
    assert c['geometry_changes'] is False and c['camera_changes'] is False and c['state_changes'] is False


def test_skin_successor_preserves_all_mesh_coordinates_and_camera_code(tmp_path):
    old=s.blender_script(tmp_path/'plan.json',tmp_path/'out')
    new=s.blender_script(tmp_path/'plan.json',tmp_path/'out',s.SKIN_MATERIALS)
    compile(new,'skin_proxy_v25','exec')
    def geometry(text):
        return [ast.dump(ast.Tuple(elts=node.args[:-1],ctx=ast.Load()),include_attributes=False) for node in ast.walk(ast.parse(text)) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ('ball','limb','cube')]
    assert geometry(old)==geometry(new)
    def camera(text):
        return ast.dump(next(n for n in ast.walk(ast.parse(text)) if isinstance(n,ast.FunctionDef) and n.name=='camera'),include_attributes=False)
    assert camera(old)==camera(new)
    assert s.blender_script(tmp_path/'plan.json',tmp_path/'out')==old


def _actual_skin_metadata_fixture():
    contract=s.material_contract();rows=[]
    for who in s.CAST:
        for part in ('head','arm','torso'):
            material=contract['actors'][who][part]
            rgb=contract['skin']['base_color'] if part!='torso' else contract['actors'][who]['shirt_base_color']
            rows.append({'object':who+'_'+part,'material':material,'base_color':rgb})
    return {'material_contract':contract,'renders':[{'actor_material_bindings':rows}]}


def test_skin_runtime_metadata_requires_all_named_heads_arms_and_shirts():
    v=_actual_skin_metadata_fixture();assert s.validate_skin_metadata(v)['skin_materials_verified'] is True
    v['renders'][0]['actor_material_bindings'].pop(0)
    with pytest.raises(s.SpatialError,match='missing_named_actor'):s.validate_skin_metadata(v)


def test_skin_runtime_rejects_teal_head_even_with_claimed_good_contract():
    v=_actual_skin_metadata_fixture();head=next(x for x in v['renders'][0]['actor_material_bindings'] if x['object']=='ye_nan_head')
    head['material']='ye_nan_IDENTITY_PLACEHOLDER';head['base_color']=[.04,.5,.5]
    with pytest.raises(s.SpatialError,match='wrong_material'):s.validate_skin_metadata(v)


def test_skin_runtime_rejects_green_skin_rgb_under_correct_material_name():
    v=_actual_skin_metadata_fixture();v['renders'][0]['actor_material_bindings'][0]['base_color']=[.04,.5,.5]
    with pytest.raises(s.SpatialError,match='color_changed'):s.validate_skin_metadata(v)


@pytest.mark.parametrize('rgb',[None,[],[.62,.43],[.62,.43,float('nan')]])
def test_skin_runtime_cannot_treat_missing_rgb_as_verified(rgb):
    v=_actual_skin_metadata_fixture();v['renders'][0]['actor_material_bindings'][0]['base_color']=rgb
    with pytest.raises(s.SpatialError,match='rgb_required'):s.validate_skin_metadata(v)
