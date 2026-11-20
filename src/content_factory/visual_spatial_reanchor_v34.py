"""Canonical-room, current-source-state stage for the explicit v33 reanchor.

This is a new staging design, not reuse of the prior B room as A evidence.
Coordinates are staging choices, not measured room geometry. No model calls.
"""
from copy import deepcopy
import json, math, re
from pathlib import Path
from . import visual_spatial_scene_v24 as scene
from . import visual_opening_frame as opening

POLICY='canonical_room_body/v34'
PROJECT=Path(__file__).resolve().parents[2]
SPEC=PROJECT/'data/qa/h3_prompt_identity_v33_20261108/REAL_CASE_r4/SPEC.json'
RUN=PROJECT/'data/video_generation/h3_continuity_full_minute_20261109_v1/spatial_r2'
SIDE=PROJECT/'data/serial_story_assets/fbca884355f49003b6f9c155c477c48e_v2.png'
FIRST_FRAME_POLICY=opening.POLICY


def head_centers(state,actor_specs):
    points=[]
    for spec in actor_specs:
        a=state['actors'][spec['id']]
        if not a['visible']:continue
        x,y,z=a['position'];h=spec['design_height'];pose=a['pose']
        points.append([x,y+.58,z+.27] if pose=='lying' else [x,y,z+h*(.63 if pose=='sitting' else .56 if pose=='kneeling' else 1.)-.13])
    return points


def heads_fit(camera,state,actor_specs,margin=.08,radius=.18):
    for h in head_centers(state,actor_specs):
        for dx in (-radius,radius):
            for dy in (-radius,radius):
                for dz in (-radius,radius):
                    out=scene.project([h[0]+dx,h[1]+dy,h[2]+dz],camera)
                    if out['uv'] is None or any(not margin<=v<=1-margin for v in out['uv']):return False
    return True


def fit_camera(camera,state,actor_specs):
    original=deepcopy(camera)
    if heads_fit(camera,state,actor_specs):return deepcopy(camera),{'changed':False,'margin':.08,'head_radius_m':.18}
    points=head_centers(state,actor_specs);selected=deepcopy(camera);selected['target']=[sum(p[i] for p in points)/len(points) for i in range(3)]
    for fov in range(35,101):
        selected['vertical_fov_deg']=fov
        if heads_fit(selected,state,actor_specs):return selected,{'changed':True,'margin':.08,'head_radius_m':.18,'original_camera':original,'rule':'Center view axis on visible head centroid; smallest integer vertical FOV fitting all conservative head boxes with margin.'}
    raise scene.SpatialError('no_camera_fov_fits_required_heads')


def _opening_points(state, actor_specs, beat):
    """Designed framing bounds, never a claim of actual photographic coverage."""
    points=[]
    for spec in actor_specs:
        who=spec['id']
        if who not in beat['actors']:continue
        actor=state['actors'][who]
        if not actor['visible']:raise scene.SpatialError('opening_subject_not_present_in_world_state')
        head=head_centers({'actors':{who:actor}},[spec])[0]
        for dx in (-.15,.15):
            for dy in (-.16,.16):
                for dz in (-.18,.18):points.append([head[0]+dx,head[1]+dy,head[2]+dz])
        if actor['pose']=='lying':
            for dx in (-.25,.25):points.append([head[0]+dx,head[1]-.42,head[2]-.1])
        else:
            angle=math.radians(actor['facing_deg']);tangent=[-math.sin(angle),math.cos(angle),0]
            bottom=head[2]-(spec['design_height']*.6 if beat['framing']=='medium' else .38)
            if beat['framing']=='wide':bottom=actor['position'][2]+.04
            for side in (-1,1):
                points.append([head[0]+side*.24*tangent[0],head[1]+side*.24*tangent[1],bottom])
        if 'hands' in beat['actors'][who]['visible_parts'] and state['props']['bread_bag']['holder']==who:
            prop=state['props']['bread_bag']['position']
            for dx in (-.13,.13):
                for dz in (-.14,.14):points.append([prop[0]+dx,prop[1],prop[2]+dz])
    return points


def _fit_opening_points(camera, points):
    selected=deepcopy(camera)
    for fov in range(15,101):
        selected['vertical_fov_deg']=fov
        projected=[scene.project(point,selected) for point in points]
        if all(row['uv'] is not None and all(.07<=v<=.93 for v in row['uv']) for row in projected):
            return selected,dict(rule='Smallest integer FOV fitting designed bounds of first-beat subjects only.',
                                 point_count=len(points),margin=.07,points=points,world_actor_changes=False,
                                 all_clip_identity_coverage_required=False)
    raise scene.SpatialError('opening_framing_bounds_do_not_fit')


def _opening_camera(row, state, actor_specs, base_camera, room_size):
    beat=row['camera_beats'][0];framing=beat['framing'];actors=beat['actors']
    if beat['start']!=0 or beat['cut'] is not False or not actors or not set(actors)<=set(state['actors']):
        raise scene.SpatialError('explicit_first_camera_beat_subjects_required')
    if framing not in ('face_close','medium','wide'):
        raise scene.SpatialError('opening_detail_requires_explicit_geometry_planner')
    if framing=='face_close' and len(actors)!=1:
        raise scene.SpatialError('opening_closeup_requires_one_explicit_subject')
    points=_opening_points(state,actor_specs,beat)
    target=[(min(point[i] for point in points)+max(point[i] for point in points))/2 for i in range(3)]
    camera=deepcopy(base_camera);camera['target']=target
    if framing=='face_close':
        who=next(iter(actors));actor=state['actors'][who]
        spec=next(s for s in actor_specs if s['id']==who)
        # Orient the camera to the source body's existing facial plane. The
        # actor is never rotated towards the camera as an identity shortcut.
        angle=math.radians(actor['facing_deg'])
        direction=[.3,-.55,1.] if actor['pose']=='lying' else [math.cos(angle),math.sin(angle),.12]
        length=math.sqrt(sum(v*v for v in direction));direction=[v/length for v in direction]
        candidates=[]
        for scale in (.85,.7,.55,.4):
            position=[target[i]+direction[i]*spec['design_height']*scale for i in range(3)]
            if all(.05<=position[i]<=room_size[i]-.05 for i in range(3)):candidates.append(position)
        if not candidates:raise scene.SpatialError('opening_closeup_camera_outside_designed_room')
        camera['position']=candidates[0]
    else:
        # Keep the source staging side, but use the selected subjects' eye
        # level instead of the old ceiling-height all-cast inspection view.
        heads=head_centers(opening.render_state({'opening_frame':{'policy':FIRST_FRAME_POLICY,'in_frame_actor_ids':list(actors)}},state),actor_specs)
        height=min(room_size[2]-.1,sum(h[2] for h in heads)/len(heads)+.12)
        delta=[camera['position'][i]-target[i] for i in (0,1)];length=math.hypot(*delta)
        if length<1e-7:raise scene.SpatialError('opening_group_camera_side_degenerate')
        best=None
        for step in range(10,37):
            position=[target[i]+delta[i]/length*step/10 for i in (0,1)]+[height]
            if not all(.05<=position[i]<=room_size[i]-.05 for i in range(3)):continue
            candidate=dict(camera,position=position)
            try:candidate,fit=_fit_opening_points(candidate,points)
            except scene.SpatialError:continue
            best=(candidate,fit)
            if candidate['vertical_fov_deg']<=60:break
        if best is None:raise scene.SpatialError('opening_group_camera_bounds_unavailable')
        camera=best[0]
    camera,proof=_fit_opening_points(camera,points)
    proof.update(first_frame_policy=FIRST_FRAME_POLICY,framing=framing,in_frame_actor_ids=sorted(actors),body_heading_preserved=True)
    return camera,proof


def plan_from_spec(spec_path=SPEC,*,first_frame_policy=None):
    if first_frame_policy not in (None,FIRST_FRAME_POLICY):raise scene.SpatialError('unsupported_first_frame_policy')
    spec_path=Path(spec_path).resolve();spec=json.loads(spec_path.read_text(encoding='utf-8'))
    if spec.get('schema')!='h3_continuity_input/v33' or [s['shot_id'] for s in spec['shots']]!=['S01','S02','S03','S04']:
        raise scene.SpatialError('explicit_four_v33_source_shots_required')
    p=scene.novel_plan();p['blocking_revision']='canonical_source_reanchor_head_bounds_r2_v34';p['continuity_source_spec']=scene.bind(spec_path)
    p['visual_design']={'stage_policy':POLICY,'primary_canonical_room':deepcopy(spec['shots'][0]['canonical_room']),
                        'secondary_canonical_room':scene.bind(SIDE),'primary_room_authority':'front, square ceiling shade',
                        'known_reference_difference':'Secondary side has round shade and different bedding; primary front governs this new staging design. Neither image proves the doorway location.',
                        'room_materials':'worn gray-brown plaster, aged cracked concrete floor, dark brown wood bed and small table, plain gray-brown bedding',
                        'ceiling_lamp':{'shape':'square','observed_in_primary':True,'count':1},'new_decorations':[],
                        'metric_basis':'designed approximate dimensions and unseen door location, not recovered photograph metrics',
                        'required_body_design':'connected head-neck-shoulders-torso-arms-legs; neutral skin head and hands; visible facial plane'}
    for i,row in enumerate(spec['shots']):
        source=row['source'];path=Path(source['path'])
        if scene.sha(path)!=source['sha256']:raise scene.SpatialError('v33_source_file_changed')
        p['shots'][i]['source_prompt']=deepcopy(source);p['shots'][i]['dialogue_verbatim']=re.findall('“([^”]+)”',path.read_text(encoding='utf-8'))
        spans={s['id']:s for s in row['source_spans']};ids=row['source_state_span_ids']
        if not ids or any(sid not in spans or spans[sid]['kind']!='context' for sid in ids):raise scene.SpatialError('source_current_state_spans_required')
        p['shots'][i]['source_current_state']={'continuity_spec':scene.bind(spec_path),'source':deepcopy(source),
            'span_ids':ids,'spans':[deepcopy(spans[x]) for x in ids],
            'interpretation':'Current beginning only; later standing/receiving is not pulled back into this start.'}
        p['shots'][i]['staging_changes']=[]
    # First two starts remain asleep. Third begins awake but still on the bed;
    # standing and accepting the bread occur later in S03, never in its anchor.
    initial=deepcopy(p['shots'][0]['start_state']);awake=deepcopy(initial);awake['actors']['su_mo']['eyes']='open'
    received=deepcopy(p['shots'][2]['end_state']);departed=deepcopy(p['shots'][3]['end_state'])
    received['props']['bread_bag']['position']=[2.05,2.6,1.32];departed['props']['bread_bag']['position']=[2.05,2.6,1.32]
    starts=[initial,deepcopy(initial),awake,received];ends=[deepcopy(initial),deepcopy(awake),deepcopy(received),departed]
    cameras={
        'anchor_S01':{'position':[2.9,1.6,2.72],'target':[1.95,2.65,.95],'vertical_fov_deg':75,'near':.05},
        'anchor_S02':{'position':[2.9,1.6,2.72],'target':[1.95,2.65,.95],'vertical_fov_deg':75,'near':.05},
        'anchor_S03':{'position':[2.9,1.6,2.72],'target':[1.95,2.65,.95],'vertical_fov_deg':75,'near':.05},
        'anchor_S04':{'position':[4.0,.65,1.85],'target':[2.5,2.6,1.1],'vertical_fov_deg':62,'near':.05},
    }
    p['cameras'].update(cameras)
    # Initial image supplies readable three-quarter faces; subsequent source
    # gaze/turning actions remain in the actual v33 video screenplay.
    def face_toward(state,who,position):
        a=state['actors'][who]['position'];state['actors'][who]['facing_deg']=math.degrees(math.atan2(position[1]-a[1],position[0]-a[0]))%360
    for i,s in enumerate(p['shots']):
        s['camera_id']='anchor_'+s['id'];s['start_state']=starts[i];s['end_state']=ends[i]
        if first_frame_policy is None:
            for who in scene.CAST:
                s['start_state']['actors'][who]['head_camera_aim_max_deg']=25 if who=='su_mo' and s['start_state']['actors'][who]['pose']=='lying' else 35
                if s['start_state']['actors'][who]['pose']!='lying':face_toward(s['start_state'],who,cameras[s['camera_id']]['position'])
            s['staging_changes']=['The anchor is a medium-wide identity-coverage view; source-specified closeups and gaze changes occur when the v33 shot begins. No global camera lock.',
                                  'Readability r1: camera stays below ceiling; limited head aim makes the facial plane observable while preserving the connected body. Adult-held bread is at left chest, away from the younger child head. These are staging choices, not new plot facts.']
        else:
            beat=spec['shots'][i]['camera_beats'][0]
            s['opening_frame']=dict(policy=FIRST_FRAME_POLICY,camera_beat=deepcopy(beat),camera_beat_sha256=scene.fingerprint(beat),
                                    in_frame_actor_ids=sorted(beat['actors']),framing=beat['framing'])
            s['staging_changes']=['The opening image depicts the first scripted camera beat; later cuts and movement remain in the video.',
                                  'World positions, body headings and held-object ownership are unchanged by framing. Off-frame actors remain in the scene.']
        if i==3:
            s['intermediate_states'][0]['state']=deepcopy(s['start_state']);s['intermediate_states'][0]['state']['actors']['ye_xijue']['pose']='kneeling'
    # Preserve exact boundary carry despite different photographic views.
    for previous,current in zip(p['shots'],p['shots'][1:]):previous['end_state']=deepcopy(current['start_state'])
    for s in p['shots']:
        if first_frame_policy is None:camera,proof=fit_camera(p['cameras'][s['camera_id']],s['start_state'],p['actors'])
        else:
            row=next(row for row in spec['shots'] if row['shot_id']==s['id'])
            camera,proof=_opening_camera(row,s['start_state'],p['actors'],p['cameras'][s['camera_id']],p['room']['size'])
        p['cameras'][s['camera_id']]=camera;s['framing_fit']=proof
    if first_frame_policy is not None:p['first_frame_policy']=first_frame_policy
    p['source_current_state_contract']='S01/S02 father asleep lying, child holds bag; S03 father awake lying, child offers bag; S04 father standing holds bag, two children beside him.'
    p['limitations']=['Designed layout is canonical-inspired, not calibrated complete-room reconstruction. Door position is a staging choice.',
                      'Blockout people are not approved actor identities. Klein must replace proxies; actual output needs root face/body, room and current-state review.',
                      'Primary square lamp unifies the observed front/side lamp discrepancy without claiming both references match perfectly.']
    scene.validate(p);return p


def prepare(run=RUN,spec_path=SPEC,*,first_frame_policy=None):
    run=Path(run).resolve();p=plan_from_spec(spec_path,first_frame_policy=first_frame_policy);result=scene.prepare_plan(run,p)
    scene.freeze(run/'SOURCE_CURRENT_STATE_DESIGN.json',{'schema':'source_current_state_spatial_design/v34','plan':scene.bind(run/'SPATIAL_PLAN.json'),
        'source_spec':scene.bind(spec_path),'canonical_room_front':p['visual_design']['primary_canonical_room'],'canonical_room_side':p['visual_design']['secondary_canonical_room'],
        'shots':[{'id':s['id'],'source_current_state':s['source_current_state'],'state_sha256':scene.fingerprint(s['start_state']),'camera_id':s['camera_id']} for s in p['shots']],
        'source_binding_review_written':False,'production_approved':False})
    return result


ENVIRONMENT=r'''
# Canonical front is the visual authority; geometry is explicit staging only.
wall.diffuse_color=(.19,.175,.145,1);wall.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=wall.diffuse_color
cloth.diffuse_color=(.23,.215,.19,1);cloth.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=cloth.diffuse_color
floor.use_nodes=True;nodes=floor.node_tree.nodes;links=floor.node_tree.links
noise=nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=5;noise.inputs['Detail'].default_value=4
ramp=nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.2;ramp.color_ramp.elements[0].color=(.09,.085,.07,1);ramp.color_ramp.elements[1].position=.8;ramp.color_ramp.elements[1].color=(.31,.30,.275,1)
links.new(noise.outputs['Fac'],ramp.inputs['Fac']);links.new(ramp.outputs['Color'],nodes.get('Principled BSDF').inputs['Base Color'])
bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.28;bump.inputs['Distance'].default_value=.035;links.new(noise.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs['Normal'],nodes.get('Principled BSDF').inputs['Normal'])
for material in (wall,floor,wood,cloth):material.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value=.94
'''

LIGHT=r'''
cube('ceiling',(W/2,D/2,H+.045),(W,D,.09),wall)
lamp_shell=mat('canonical_square_lamp_shell',(.23,.20,.14));lamp_glow=mat('canonical_square_lamp_diffuser',(.78,.69,.49))
lamp_bsdf=lamp_glow.node_tree.nodes.get('Principled BSDF');lamp_bsdf.inputs['Emission Color'].default_value=(1,.78,.48,1);lamp_bsdf.inputs['Emission Strength'].default_value=1
cube('canonical_ceiling_lamp',(W/2,D/2,H-.10),(.48,.48,.20),lamp_shell);cube('canonical_ceiling_lamp_diffuser',(W/2,D/2,H-.21),(.43,.43,.025),lamp_glow)
bpy.ops.object.light_add(type='AREA',location=(W/2,D/2,H-.25));bpy.context.object.name='canonical_lamp_light';bpy.context.object.data.energy=30;bpy.context.object.data.color=(1,.82,.61);bpy.context.object.data.size=.43
'''

BODY=r'''def draw_state(state,camera_position=None):
 clear_dynamic()
 hair=bpy.data.materials.get('human_black_hair_v34') or mat('human_black_hair_v34',(.018,.016,.014))
 dark=bpy.data.materials.get('proxy_face_detail_v34') or mat('proxy_face_detail_v34',(.025,.02,.018))
 for spec in plan['actors']:
  who=spec['id'];a=state['actors'][who]
  if not a['visible']:continue
  x,y,z=a['position'];h=spec['design_height'];m=materials[who];pose=a['pose'];first=len(dynamic)
  def B(part,p,scale,material):
   obj=ball(who+'_'+part,p,scale,material);dynamic.append(obj)
   for poly in obj.data.polygons:poly.use_smooth=True
   return obj
  def L(part,p,q,r,material):dynamic.append(limb(who+'_'+part,p,q,r,material))
  if pose=='lying':
   B('torso',(x,y,z+.22),(.225,.40,.15),m);B('neck',(x,y+.40,z+.23),(.07,.10,.075),skin_material)
   B('head',(x,y+.58,z+.27),(.13,.16,.17),skin_material);B('nose_direction',(x,y+.55,z+.43),(.035,.04,.045),skin_material)
   B('hair',(x,y+.69,z+.34),(.13,.09,.09),hair)
   for dx in (-.11,.11):L('thigh',(x+dx,y-.29,z+.16),(x+dx,y-.59,z+.13),.085,m);L('shin',(x+dx,y-.59,z+.13),(x+dx,y-.91,z+.11),.073,m);B('shoe',(x+dx,y-.96,z+.10),(.09,.16,.07),m)
   for sign in (-1,1):
    shoulder=(x+sign*.22,y+.22,z+.22);elbow=(x+sign*.31,y-.04,z+.17);wrist=(x+sign*.29,y-.31,z+.16)
    L('sleeve',shoulder,elbow,.065,m);L('arm',elbow,wrist,.047,skin_material);B('hand',wrist,(.06,.075,.035),skin_material)
   for dx in (-.045,.045):
    if a['eyes']=='closed':L('closed_eye',(x+dx-.018,y+.55,z+.443),(x+dx+.018,y+.55,z+.443),.004,dark)
    else:B('open_eye',(x+dx,y+.55,z+.443),(.013,.017,.006),dark)
  else:
   top=z+h*(.63 if pose=='sitting' else .56 if pose=='kneeling' else 1.);hc=top-.13
   B('torso',(x,y,top-.48),(.20,.15,.28),m);B('neck',(x,y,top-.29),(.065,.06,.075),skin_material);B('head',(x,y,hc),(.125,.13,.16),skin_material)
   B('nose_direction',(x,y-.13,hc+.01),(.035,.055,.035),skin_material);B('hair',(x,y+.015,hc+.11),(.127,.132,.085),hair)
   for dx in (-.043,.043):
    if a['eyes']=='closed':L('closed_eye',(x+dx-.017,y-.126,hc+.04),(x+dx+.017,y-.126,hc+.04),.004,dark)
    else:B('open_eye',(x+dx,y-.126,hc+.04),(.012,.008,.014),dark)
   hip=(x,y,top-.73)
   if pose=='sitting':
    for dx in (-.1,.1):L('thigh',(x+dx,y,hip[2]),(x+dx,y-.23,.65),.075,m);L('shin',(x+dx,y-.23,.65),(x+dx,y-.23,.08),.065,m)
   elif pose=='kneeling':
    for dx in (-.1,.1):L('thigh',(x+dx,y,hip[2]),(x+dx,y-.07,.18),.075,m);L('shin',(x+dx,y-.07,.18),(x+dx,y+.23,.08),.065,m)
   else:
    for dx in (-.1,.1):L('leg',(x+dx,y,hip[2]),(x+dx,y,.06),.07,m);B('shoe',(x+dx,y-.06,.055),(.09,.15,.055),m)
   rotation=Quaternion(Vector((0,0,1)),math.radians(a['facing_deg']+90));pivot=Vector((x,y,z))
   for obj in dynamic[first:]:obj.location=pivot+rotation@(obj.location-pivot);obj.rotation_euler=(rotation@obj.rotation_euler.to_quaternion()).to_euler()
   holder=state['props']['bread_bag']['holder']==who
   for sign in (-1,1):
    shoulder=pivot+rotation@(Vector((x+sign*.22,y,top-.34))-pivot)
    if holder:
     target=Vector(state['props']['bread_bag']['position'])+Vector((sign*.085,-.02,-.045));elbow=(shoulder+target)/2+Vector((sign*.04,-.07,-.07))
    else:
     elbow=pivot+rotation@(Vector((x+sign*.24,y-.04,top-.56))-pivot);target=pivot+rotation@(Vector((x+sign*.24,y-.10,top-.79))-pivot)
    L('sleeve',shoulder,elbow,.06,m);L('arm',elbow,target,.043,skin_material);B('hand',target,(.055,.04,.065),skin_material)
  if camera_position is not None and a.get('head_camera_aim_max_deg',0)>0:
   center=Vector((x,y+.58,z+.27)) if pose=='lying' else Vector((x,y,hc))
   normal=Vector((0,0,1)) if pose=='lying' else rotation@Vector((0,-1,0))
   target=(Vector(camera_position)-center).normalized();turn=normal.rotation_difference(target)
   angle=turn.angle;limit=math.radians(a['head_camera_aim_max_deg']);q=Quaternion((1,0,0,0)).slerp(turn,min(1,limit/max(angle,1e-9)))
   for obj in dynamic[first:]:
    suffix=obj.name[len(who)+1:].split('.')[0]
    if suffix not in ('head','nose_direction','hair','closed_eye','open_eye'):continue
    obj.location=center+q@(obj.location-center);obj.rotation_euler=(q@obj.rotation_euler.to_quaternion()).to_euler()
 p=state['props']['bread_bag']['position'];dynamic.append(cube('bread_bag_SINGLE',p,(.19,.11,.20),bread))
'''


OPENING_RENDER=r'''def opening_render_state(name,state):
 if state is None:return state
 shot=next((row for row in plan['shots'] if name==row['id']+'_start'),None)
 if shot is None or 'opening_frame' not in shot:return state
 selection=shot['opening_frame'];chosen=selection['in_frame_actor_ids']
 if selection.get('policy')!='first_camera_beat/v1' or len(chosen)!=len(set(chosen)) or not set(chosen)<=set(state['actors']):raise ValueError('invalid_opening_render_selection')
 derived=json.loads(json.dumps(state))
 for who,actor in derived['actors'].items():actor['visible']=actor['visible'] and who in chosen
 holder=derived['props']['bread_bag']['holder']
 derived['_opening_bread_visible']=holder in chosen and 'hands' in selection['camera_beat']['actors'][holder]['visible_parts']
 return derived

'''


def build_script(text,*,first_frame_policy=None):
    if first_frame_policy not in (None,FIRST_FRAME_POLICY):raise scene.SpatialError('unsupported_first_frame_policy')
    if 'skin_contract=json.loads(' not in text:raise scene.SpatialError('v34_requires_neutral_skin_material_policy')
    marker="W,D,H=plan['room']['size']"
    if text.count(marker)!=1:raise scene.SpatialError('v34_environment_injection_changed')
    text=text.replace(marker,ENVIRONMENT+'\n'+marker)
    marker="for name,pos,power,sz in [('window_light'"
    if text.count(marker)!=1:raise scene.SpatialError('v34_light_injection_changed')
    text=text.replace(marker,LIGHT+'\n'+marker)
    pillow=";cube('pillow',(p[0],p[1]+.67,.73),(1.05,.38,.13),cloth)"
    if text.count(pillow)!=1:raise scene.SpatialError('v34_old_pillow_target_changed')
    text=text.replace(pillow,'')
    start=text.index('def draw_state(state):');end=text.index('\ndef camera(spec):',start)
    text=text[:start]+BODY+text[end:]
    call='if state:draw_state(state)'
    if text.count(call)!=1:raise scene.SpatialError('v34_camera_aware_body_call_changed')
    text=text.replace(call,"if state:draw_state(state,plan['cameras'][camid]['position'])")
    marker="'material_contract':skin_contract,"
    if text.count(marker)!=1:raise scene.SpatialError('v34_material_metadata_marker_changed')
    text=text.replace(marker,"'stage_policy':"+repr(POLICY)+",'visual_design':plan['visual_design'],'material_contract':skin_contract,")
    if first_frame_policy is None:return text
    old=" p=state['props']['bread_bag']['position'];dynamic.append(cube('bread_bag_SINGLE',p,(.19,.11,.20),bread))"
    new=" if state.get('_opening_bread_visible',True):\n "+old
    if text.count(old)!=1:raise scene.SpatialError('opening_render_bread_target_changed')
    text=text.replace(old,new)
    old='def render(name,camid,state=None):\n clear_dynamic()'
    new=OPENING_RENDER+'def render(name,camid,state=None):\n world_state=state\n state=opening_render_state(name,state)\n clear_dynamic()'
    if text.count(old)!=1:raise scene.SpatialError('opening_render_state_target_changed')
    text=text.replace(old,new)
    old="'visible_actor_ids':[who for who,a in state['actors'].items() if a['visible']] if state else [],"
    new=("'world_in_scene_actor_ids':[who for who,a in world_state['actors'].items() if a['visible']] if world_state else [],"
         "'rendered_prop_ids':['bread_bag'] if any(o.name=='bread_bag_SINGLE' for o in dynamic) else [],"+old)
    if text.count(old)!=1:raise scene.SpatialError('opening_actual_metadata_target_changed')
    return text.replace(old,new)


def render(run=RUN,blender=None,timeout=1800):
    if blender is None:raise scene.SpatialError('explicit_blender_path_required')
    plan=json.loads((Path(run)/'SPATIAL_PLAN.json').read_text(encoding='utf-8'))
    policy=plan.get('first_frame_policy')
    if policy not in (None,FIRST_FRAME_POLICY):raise scene.SpatialError('unsupported_first_frame_policy')
    return scene.render(run,blender,timeout=timeout,render_tag='blender_canonical_v34',material_policy=scene.SKIN_MATERIALS,stage_policy=POLICY if policy is None else policy)
