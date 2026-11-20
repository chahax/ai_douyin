import bpy,math,json,hashlib
from pathlib import Path
from mathutils import Vector
ROOT=Path('D:/IT/ai_douyin/tools/scene_lab_20261006')
OUT=ROOT/'geometry'; OUT.mkdir(exist_ok=True)
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
scene.render.engine='CYCLES'; scene.cycles.samples=24
scene.render.resolution_x=1024;scene.render.resolution_y=576;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.view_settings.view_transform='AgX'
scene.world.color=(0.3,0.3,0.3)
def mat(name,color):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(*color,1)
 m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.72
 return m
wall=mat('warm_plaster',(.75,.71,.64));wood=mat('pale_wood',(.60,.46,.31));floor=mat('matte_gray_pvc',(.40,.41,.41));metal=mat('gray_metal',(.25,.27,.28));black=mat('chair_black',(.055,.065,.065));door_mat=mat('gray_wood_door',(.47,.43,.37));glass=mat('window_gray',(.60,.70,.73));white=mat('warm_white',(.92,.88,.78))
objects=[]
def box(name,loc,size,material,parent=None):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=size
 bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(material)
 if parent:o.parent=parent
 bevel=o.modifiers.new('small_edges','BEVEL');bevel.width=.012;bevel.segments=2;o.modifiers.new('weighted_normals','WEIGHTED_NORMAL')
 objects.append(o);return o
# Single continuous office+corridor shell; ceiling omitted for plan inspection.
box('E07_continuous_floor',(3,3.5,-.08),(6,7,.16),floor)
box('E08_south',(3,-.07,1.4),(6,.14,2.8),wall)
box('E08_east',(6.07,3.5,1.4),(.14,7,2.8),wall)
box('E08_corridor_north',(3,7.07,1.4),(6,.14,2.8),wall)
box('E08_west_below_window',(-.07,2.5,.45),(.14,5,.9),wall)
box('E08_west_above_window',(-.07,2.5,2.67),(.14,5,.26),wall)
box('E08_west_south_pier',(-.07,.25,1.7),(.14,.5,1.65),wall)
box('E08_west_north_pier',(-.07,4.65,1.7),(.14,.7,1.65),wall)
box('E08_corridor_west',(-.07,6,1.4),(.14,2,2.8),wall)
# Door opening x .9..1.85, y5.
box('E08_far_wall_left',(.45,5,1.4),(.9,.14,2.8),wall)
box('E08_far_wall_right',(3.925,5,1.4),(4.15,.14,2.8),wall)
box('E08_door_header',(1.375,5,2.47),(.95,.14,.66),wall)
box('E04_frame_left',(.9,5,1.08),(.065,.22,2.16),door_mat)
box('E04_frame_right',(1.85,5,1.08),(.065,.22,2.16),door_mat)
box('E04_frame_top',(1.375,5,2.16),(1.02,.22,.065),door_mat)
bpy.ops.object.empty_add(location=(.94,5,0));hinge=bpy.context.object;hinge.name='E04_door_hinge';hinge.rotation_euler.z=math.radians(85)
leaf=box('E04_door_leaf',(.425,0,1.035),(.85,.055,2.07),door_mat,hinge)
box('E04_lower_horizontal_handle',(.68,-.07,.87),(.23,.035,.035),metal,hinge)
# One wide window, same frame and blind in every shot; glazing not blocking sunset light.
for y in [.5,2.4,4.3]:box('E05_window_vertical',(0,y,1.70),(.06,.045,1.67),metal)
for z in [.91,2.52]:box('E05_window_horizontal',(0,2.4,z),(.06,3.85,.045),metal)
box('E05_half_lowered_blind',(0,2.4,2.19),(.035,3.77,.64),glass)
for y in [1.6,3.2]:box('E05_blind_edge',(0,y,2.2),(.05,.02,.60),white)
# Two parallel desks, fixed positions.
for ident,x in [('E01',1.55),('E02',3.25)]:
 box(ident+'_desk',(x,2,.76),(1.4,.72,.045),wood)
 for dx in [-.6,.6]:
  for dy in [-.26,.26]:box(ident+'_leg',(x+dx,2+dy,.38),(.035,.035,.735),metal)
# Two matching five-foot office chairs; no character identity guessed.
for ident,x in [('E09',1.55),('E10',3.25)]:
 box(ident+'_seat',(x,1.14,.47),(.48,.45,.06),black)
 box(ident+'_back',(x,.94,.78),(.46,.065,.53),black)
 box(ident+'_stem',(x,1.14,.24),(.06,.06,.42),metal)
 for i in range(5):
  a=i*math.tau/5;o=box(ident+'_foot_'+str(i),(x+.13*math.cos(a),1.14+.13*math.sin(a),.06),(.29,.038,.035),metal);o.rotation_euler.z=a
# Drawer behind Lin's desk, no third workstation.
box('E03_drawer_cabinet',(3.25,4.67,.43),(.78,.45,.86),wood)
for z in [.18,.45,.71]:
 box('E03_drawer_front_'+str(z),(3.25,4.425,z),(.72,.025,.24),wood)
 box('E03_handle_'+str(z),(3.25,4.4,z),(.17,.025,.025),black)
# Prop positions are only layout cues, not a new performance state.
box('P05_layout_paper',(3.23,2,.79),(.29,.21,.002),white)
for j,c in enumerate([(.9,.8,.3),(.9,.55,.6),(.4,.65,.85)]):box('P03_layout_note_'+str(j),(1.2+j*.09,2.22,.786),(.075,.075,.001),mat('note_'+str(j),c))
bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=.22,depth=.045,location=(3,2.5,2.75));lamp=bpy.context.object;lamp.name='E06_round_ceiling_light';lamp.data.materials.append(white);objects.append(lamp)
bpy.ops.object.light_add(type='AREA',location=(3,2.5,2.6));bpy.context.object.data.energy=160;bpy.context.object.data.size=4
bpy.ops.object.light_add(type='AREA',location=(-2,1.5,2.4));light=bpy.context.object;light.name='evening_window_key';light.data.energy=700;light.data.color=(1,.71,.46);light.data.shape='RECTANGLE';light.data.size=3.4;light.data.size_y=2
light.rotation_euler=(Vector((2,2,1.1))-light.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.light_add(type='AREA',location=(2.7,6.2,2.6));bpy.context.object.data.energy=120;bpy.context.object.data.size=2

def camera(name,loc,target,lens=23,ortho=None):
 bpy.ops.object.camera_add(location=loc);o=bpy.context.object;o.name=name;o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler();o.data.lens=lens;o.data.clip_end=100
 if ortho:o.data.type='ORTHO';o.data.ortho_scale=ortho
 return o
cams=[camera('plan',(3,3.5,12),(3,3.5,0),ortho=12.5),camera('office_to_door',(3.55,.35,1.55),(1.48,4.65,1.18),22),camera('corridor_to_office',(1.37,6.55,1.55),(2.05,1.7,1.1),22),camera('office_reverse',(1.25,4.65,1.55),(2.5,1.8,1.1),24)]
# Z depth, same metric range in all cameras: near white/far black, 0..9 m.
scene.use_nodes=True;tree=scene.node_tree;tree.nodes.clear();rl=tree.nodes.new('CompositorNodeRLayers');scene.view_layers[0].use_pass_z=True
comp=tree.nodes.new('CompositorNodeComposite');tree.links.new(rl.outputs['Image'],comp.inputs[0])
mapn=tree.nodes.new('CompositorNodeMapRange');mapn.inputs['From Min'].default_value=0;mapn.inputs['From Max'].default_value=9;mapn.inputs['To Min'].default_value=1;mapn.inputs['To Max'].default_value=0;mapn.use_clamp=True;tree.links.new(rl.outputs['Depth'],mapn.inputs['Value'])
out=tree.nodes.new('CompositorNodeOutputFile');out.base_path=str(OUT);out.format.file_format='PNG';out.format.color_mode='RGB';out.format.color_depth='16';tree.links.new(mapn.outputs[0],out.inputs[0])
geometry=[{'name':o.name,'world_matrix':[[round(v,6) for v in row] for row in o.matrix_world],'dimensions':[round(v,6) for v in o.dimensions]} for o in objects]
geomhash=hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest()
manifest={'schema':'scene_geometry_candidate_v1','source':'S7 STATIC_ASSET_DEFINITIONS','not_human_approved':True,'dimensions_are_authored_assumptions':True,'office_m':[6,5,2.8],'corridor_m':[6,2,2.8],'units':'meters','door_open_degrees_for_spatial_probe':85,'ceiling_omitted_for_cutaway':True,'depth_range_m':[0,9],'geometry_sha256':geomhash,'objects':geometry,'cameras':[],'video_content_review':'human_only'}
for c in cams:
 scene.camera=c;scene.render.filepath=str(OUT/(c.name+'.png'));out.file_slots[0].path=c.name+'_depth_'
 bpy.ops.render.render(write_still=True)
 depth=OUT/(c.name+'_depth_0001.png')
 manifest['cameras'].append({'id':c.name,'image':str(OUT/(c.name+'.png')),'depth':str(depth),'geometry_sha256':geomhash,'camera_matrix':[[round(v,6) for v in row] for row in c.matrix_world],'lens_mm':c.data.lens,'orthographic':c.data.type=='ORTHO'})
scene.camera=cams[1];bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'office_corridor_candidate.blend'))
(OUT/'SCENE_MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
print('SCENE_LAB_COMPLETE',geomhash)
