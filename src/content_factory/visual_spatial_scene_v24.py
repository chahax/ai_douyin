"""Explicit spatial blocking, deterministic diagrams and CPU Blender exports.

This is a staging design, not a claim to recover metric facts from a novel or
an image. It never calls a model or authorizes a production asset. Old source
files are read-only; changed plans require a new output namespace.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = PROJECT / 'data/video_generation/spatial_minute_experiments_20261107_v1/spatial_r3'
SOURCE = PROJECT / 'data/video_generation/h3_reference_full_minute_20261107_v1'
SCHEMA = 'explicit_spatial_scene/v24'
CAST = ('su_mo', 'ye_nan', 'ye_xijue')
COLORS = {'su_mo': '#4075c5', 'ye_nan': '#149c9c', 'ye_xijue': '#eb9c35'}


class SpatialError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bind(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def freeze(path, value):
    path = Path(path)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise SpatialError('frozen_spatial_artifact_changed_use_new_run')
    else:
        with path.open('xb') as stream:
            stream.write(encoded)


def vec(value):
    if not isinstance(value, list) or len(value) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise SpatialError('finite_xyz_vector_required')
    return value


def sub(a, b): return [x-y for x, y in zip(a, b)]
def dot(a, b): return sum(x*y for x, y in zip(a, b))
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def unit(a):
    norm = math.sqrt(dot(a, a))
    if norm < 1e-7: raise SpatialError('camera_degenerate_direction')
    return [x/norm for x in a]


def project(point, camera, width=736, height=1312):
    """Normalized image coordinates and view depth; no fake visibility verdict."""
    forward = unit(sub(vec(camera['target']), vec(camera['position'])))
    right = unit(cross(forward, [0, 0, 1])); up = cross(right, forward)
    rel = sub(vec(point), camera['position']); depth = dot(rel, forward)
    if depth <= 0: return {'in_frame': False, 'depth': depth, 'uv': None}
    scale = math.tan(math.radians(camera['vertical_fov_deg'])/2)
    u = .5 + dot(rel, right)/(2*depth*scale*width/height)
    v = .5 - dot(rel, up)/(2*depth*scale)
    return {'uv': [u, v], 'depth': depth, 'in_frame': 0 <= u <= 1 and 0 <= v <= 1}


def _actor(position, pose='standing', eyes='open', facing=180, visible=True):
    return {'position': list(position), 'pose': pose, 'eyes': eyes, 'facing_deg': facing, 'visible': visible}


def novel_plan(source=SOURCE):
    source = Path(source).resolve()
    camera = lambda pos, target, fov=54: {'position': pos, 'target': target, 'vertical_fov_deg': fov, 'near': .05}
    initial = {
        'actors': {'su_mo': _actor([1.25, 2.6, .58], 'lying', 'closed'),
                   'ye_nan': _actor([2.8, 2.95, 0], facing=220),
                   'ye_xijue': _actor([2.5, 2.4, 0], facing=200)},
        'props': {'bread_bag': {'holder': 'ye_xijue', 'position': [2.38, 2.3, .88]}},
    }
    seated = deepcopy(initial); seated['actors']['su_mo'] = _actor([1.85, 2.6, .58], 'sitting', facing=90)
    received = deepcopy(seated); received['actors']['su_mo'] = _actor([2.25, 2.75, 0], facing=100)
    received['actors']['ye_nan']['position'] = [2.85, 2.65, 0]
    received['props']['bread_bag'] = {'holder': 'su_mo', 'position': [2.35, 2.52, 1.05]}
    departed = deepcopy(received)
    departed['actors']['ye_nan'] = _actor([5.55, 1.65, 0], facing=90, visible=False)
    departed['actors']['ye_xijue'] = _actor([5.55, 1.15, 0], facing=90, visible=False)
    # Headings are measured in this world coordinate system, not arbitrary
    # image-left/right guesses. Keep the initial prototype frozen elsewhere.
    def face(state,who,target):
        a=state['actors'][who]['position'];b=state['actors'][target]['position']
        state['actors'][who]['facing_deg']=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))%360
    for state in (initial,seated,received):
        face(state,'ye_nan','ye_xijue');face(state,'ye_xijue','su_mo')
        if state['actors']['su_mo']['pose']!='lying':face(state,'su_mo','ye_xijue')
    face(departed,'su_mo','ye_xijue')
    for who in ('ye_nan','ye_xijue'):departed['actors'][who]['facing_deg']=0
    states = [initial, initial, seated, received, departed]
    shots = []
    for index, sid in enumerate(('S01', 'S02', 'S03', 'S04')):
        path = source/'sources'/(sid+'.prompt.txt'); text = path.read_text(encoding='utf-8')
        quotes = re.findall('“([^”]+)”', text)
        shots.append({'id': sid, 'source_prompt': bind(path), 'dialogue_verbatim': quotes,
                      'start_state': deepcopy(states[index]), 'end_state': deepcopy(states[index+1]),
                      'camera_id': ['bedside_master', 'bedside_master', 'children_medium', 'door_reverse'][index],
                      'native_frames': 362, 'fps': 24, 'staging_changes': []})
    shots[1]['staging_changes'] = ['DESIGN interpolation: awake father props up to sit on bed edge by the end; source specifies bed-edge in following segment but not exact sitting instant. No dialogue changed.']
    shots[2]['prop_transfers'] = [{'prop_id': 'bread_bag', 'from': 'ye_xijue', 'to': 'su_mo', 'segment_seconds': [13, 15]}]
    shots[3]['waypoints'] = {'ye_nan': [[2.85, 2.65, 0], [3.6, 1.8, 0], [4.8, 1.5, 0], [5.55, 1.65, 0]],
                               'ye_xijue': [[2.5, 2.4, 0], [3.6, 1.25, 0], [4.8, 1.15, 0], [5.55, 1.15, 0]]}
    kneel = deepcopy(received); kneel['actors']['ye_xijue']['pose'] = 'kneeling'
    shots[3]['intermediate_states'] = [{'segment_seconds': 7, 'state': kneel, 'reason': 'Source child kneels while responding.'}]
    return {
        'schema': SCHEMA, 'blocking_revision': 'heading_door_cast_visibility_r3', 'units': 'meters', 'coordinate_system': 'right-handed X east, Y north, Z up; image v down',
        'metric_basis': 'staging_design_not_novel_metric_fact_or_measured_reconstruction',
        'room': {'id': 'su_mo_room', 'size': [5.2, 4.4, 2.8]},
        'objects': [
            {'id': 'bed_01', 'kind': 'bed', 'position': [1.25, 2.4, .28], 'size': [1.4, 2.1, .56]},
            {'id': 'table_01', 'kind': 'table', 'position': [3.95, 3.55, .4], 'size': [.7, .65, .8]},
            {'id': 'door_01', 'kind': 'door', 'wall': 'east', 'position': [5.2, 1.4, 1.05], 'size': [.08, 1.2, 2.1]},
            {'id': 'window_01', 'kind': 'window', 'wall': 'north', 'position': [1.2, 4.4, 1.65], 'size': [1.2, .08, 1.1]},
            {'id': 'window_02', 'kind': 'window', 'wall': 'west', 'position': [0, 3.15, 1.65], 'size': [.08, 1.1, 1.1]},
        ],
        'actors': [
            {'id': 'su_mo', 'label': 'Su Mo / adult father', 'design_height': 1.74, 'diagram_color': COLORS['su_mo'], 'identity_image': 'character:su_mo:front'},
            {'id': 'ye_nan', 'label': 'Ye Nan / older brother', 'design_height': 1.4, 'diagram_color': COLORS['ye_nan'], 'identity_image': 'character:ye_nan:front'},
            {'id': 'ye_xijue', 'label': 'Ye Xijue / younger brother', 'design_height': 1.18, 'diagram_color': COLORS['ye_xijue'], 'identity_image': 'character:ye_xijue:front'},
        ],
        'props': [{'id': 'bread_bag', 'kind': 'bagged_bread', 'unique': True}],
        'cameras': {
            'room_front': camera([4.65, .4, 1.7], [1.7, 2.5, 1.0], 65),
            'room_side': camera([.35, .4, 1.7], [2.7, 2.65, 1.0], 65),
            'room_reverse': camera([4.7, 4.0, 1.7], [2.15, 2.6, 1.05], 65),
            'bedside_master': camera([4.35, .55, 1.65], [2.0, 2.65, 1.05], 58),
            'children_medium': camera([3.9, .85, 1.5], [2.35, 2.65, 1.05], 54),
            'door_reverse': camera([.35, 2.0, 1.7], [3.0, 2.1, 1.0], 75),
        },
        'shots': shots, 'production_approved': False, 'publication': False,
        'limitations': ['Blockout actors are colored identity placeholders, not generated cast assets.',
                        'One persistent geometry prevents furniture duplication in the renderer; video model compliance remains untested.',
                        'Camera positions can change by shot; no global tripod or fixed-framing instruction is added.'],
    }


def _inside_xy(p, obj, margin=0):
    return all(abs(p[i]-obj['position'][i]) < obj['size'][i]/2+margin for i in (0, 1))


def segment_intersects_box(a, b, obj, margin=.12):
    """Slab intersection in the floor plane, including obstacles between waypoints."""
    lo,hi=0.,1.
    for i in (0,1):
        lower=obj['position'][i]-obj['size'][i]/2-margin;upper=obj['position'][i]+obj['size'][i]/2+margin;delta=b[i]-a[i]
        if abs(delta)<1e-12:
            if a[i]<lower or a[i]>upper:return False
        else:
            left,right=sorted(((lower-a[i])/delta,(upper-a[i])/delta));lo=max(lo,left);hi=min(hi,right)
            if lo>hi:return False
    return True


def _ray_hits_box_before_target(origin, target, obj):
    lo,hi=0.,1.
    for i in range(3):
        lower=obj['position'][i]-obj['size'][i]/2;upper=obj['position'][i]+obj['size'][i]/2;delta=target[i]-origin[i]
        if abs(delta)<1e-12:
            if origin[i]<lower or origin[i]>upper:return False
        else:
            left,right=sorted(((lower-origin[i])/delta,(upper-origin[i])/delta));lo=max(lo,left);hi=min(hi,right)
            if lo>hi:return False
    return 1e-5 < lo < .99999 and hi>0


def projection_report(plan):
    """Frustum and furniture-head-ray checks, not full pixel/actor occlusion QA."""
    rows=[]
    for shot in plan['shots']:
        camera=plan['cameras'][shot['camera_id']]
        for stage,state in [('start',shot['start_state']),('end',shot['end_state'])]:
            for spec in plan['actors']:
                who=spec['id'];a=state['actors'][who]
                if not a['visible']:continue
                x,y,z=a['position'];h=spec['design_height'];pose=a['pose']
                point=([x,y+.58,z+.27] if pose=='lying' else [x,y,z+h*(.63 if pose=='sitting' else .56 if pose=='kneeling' else 1.)-.13])
                blocked=[o['id'] for o in plan['objects'] if o['kind'] in ('bed','table') and _ray_hits_box_before_target(camera['position'],point,o)]
                cast_blocked=[]
                for other_spec in plan['actors']:
                    other=other_spec['id'];b=state['actors'][other]
                    if other==who or not b['visible']:continue
                    bx,by,bz=b['position'];bh=other_spec['design_height'];bp=b['pose']
                    if bp=='lying':box={'position':[bx,by,bz+.23],'size':[.48,1.5,.4]}
                    else:
                        top=bh*(.63 if bp=='sitting' else .56 if bp=='kneeling' else 1.)
                        box={'position':[bx,by,bz+top/2],'size':[.46,.38,top]}
                    if _ray_hits_box_before_target(camera['position'],point,box):cast_blocked.append(other)
                rows.append({'shot_id':shot['id'],'stage':stage,'actor_id':who,'head_point':point,'projection':project(point,camera),'furniture_occluders':blocked,'actor_proxy_occluders':cast_blocked})
    return {'schema':'spatial_camera_projection/v24','items':rows,'scope':'Designed head-center rays with conservative furniture/actor-box occlusion proxies; not full-silhouette, wall or semantic image visibility certification.','production_approved':False}


def validate(plan, *, verify_sources=True):
    if plan.get('schema') != SCHEMA or plan.get('production_approved') is not False or plan.get('publication') is not False:
        raise SpatialError('explicit_unapproved_spatial_design_required')
    size = vec(plan['room']['size'])
    if min(size) <= 0: raise SpatialError('positive_room_dimensions_required')
    objects = plan['objects']; ids = [x['id'] for x in objects]
    if len(set(ids)) != len(ids): raise SpatialError('duplicate_object_id')
    counts = {kind: sum(o['kind'] == kind for o in objects) for kind in ('bed', 'table', 'door', 'window')}
    if counts != {'bed': 1, 'table': 1, 'door': 1, 'window': 2}: raise SpatialError('novel_room_furniture_contract_changed')
    solids = [o for o in objects if o['kind'] in ('bed', 'table')]
    for o in objects:
        vec(o['position']); vec(o['size'])
        if min(o['size']) <= 0: raise SpatialError('positive_object_dimensions_required')
    for o in solids:
        if any(o['position'][i]-o['size'][i]/2 < 0 or o['position'][i]+o['size'][i]/2 > size[i] for i in (0, 1)):
            raise SpatialError('furniture_outside_room')
    a,b=solids
    if all(abs(a['position'][i]-b['position'][i]) < (a['size'][i]+b['size'][i])/2 for i in (0, 1)):
        raise SpatialError('furniture_collision')
    if [a['id'] for a in plan['actors']] != list(CAST) or [p['id'] for p in plan['props']] != ['bread_bag']:
        raise SpatialError('named_cast_or_unique_prop_changed')
    for camera in plan['cameras'].values():
        vec(camera['position']); vec(camera['target'])
        if not 15 <= camera['vertical_fov_deg'] <= 100: raise SpatialError('camera_fov_out_of_range')
        project(camera['target'], camera)
    if [s['id'] for s in plan['shots']] != ['S01','S02','S03','S04']: raise SpatialError('four_source_segments_required')
    previous=None; observations=[]
    for shot in plan['shots']:
        if shot['native_frames'] != 362 or shot['fps'] != 24 or shot['camera_id'] not in plan['cameras']:
            raise SpatialError('shot_native_clock_or_camera_changed')
        if verify_sources:
            binding=shot['source_prompt'];path=Path(binding['path'])
            if sha(path) != binding['sha256'] or re.findall('“([^”]+)”', path.read_text(encoding='utf-8')) != shot['dialogue_verbatim']:
                raise SpatialError('source_prompt_or_dialogue_changed')
        if previous is not None and shot['start_state'] != previous: raise SpatialError('boundary_state_not_carried_forward')
        for stage,state in [('start',shot['start_state']),('end',shot['end_state'])]+[('intermediate',v['state']) for v in shot.get('intermediate_states',[])]:
            if set(state['actors']) != set(CAST) or set(state['props']) != {'bread_bag'}: raise SpatialError('state_identity_coverage_changed')
            holder=state['props']['bread_bag']['holder']
            if holder not in CAST: raise SpatialError('prop_holder_must_be_one_named_actor')
            for who,actor in state['actors'].items():
                p=vec(actor['position'])
                if actor['pose'] not in ('lying','sitting','standing','kneeling'): raise SpatialError('unsupported_actor_pose')
                if actor['visible']:
                    if not 0 <= p[0] <= size[0] or not 0 <= p[1] <= size[1]: raise SpatialError('visible_actor_outside_room')
                    for o in solids:
                        if _inside_xy(p,o,.12) and not (o['kind']=='bed' and actor['pose'] in ('lying','sitting')):
                            raise SpatialError('standing_actor_intersects_furniture')
                if actor['visible']:
                    height=next(a['design_height'] for a in plan['actors'] if a['id']==who)
                    eye=p.copy();eye[2]+=height*(.25 if actor['pose']=='lying' else .55 if actor['pose']=='sitting' else .48 if actor['pose']=='kneeling' else .9)
                    observations.append({'shot':shot['id'],'stage':stage,'actor':who,'projection':project(eye,plan['cameras'][shot['camera_id']])})
        start=shot['start_state']['props']['bread_bag']['holder'];end=shot['end_state']['props']['bread_bag']['holder']
        transfers=shot.get('prop_transfers',[])
        if start!=end:
            if len(transfers)!=1 or transfers[0]['from']!=start or transfers[0]['to']!=end or transfers[0]['prop_id']!='bread_bag':
                raise SpatialError('prop_transfer_not_explicit')
        elif transfers: raise SpatialError('spurious_prop_transfer')
        for who,path in shot.get('waypoints',{}).items():
            if who not in CAST or path[0] != shot['start_state']['actors'][who]['position'] or path[-1] != shot['end_state']['actors'][who]['position']:
                raise SpatialError('exit_path_not_bound_to_state')
            for p in path:
                vec(p)
                if any(_inside_xy(p,o,.12) for o in solids): raise SpatialError('exit_path_intersects_furniture')
            for a,b in zip(path,path[1:]):
                if any(segment_intersects_box(a,b,o) for o in solids):raise SpatialError('exit_path_segment_intersects_furniture')
                if (a[0]<=size[0]<b[0]) or (b[0]<=size[0]<a[0]):
                    t=(size[0]-a[0])/(b[0]-a[0]);cross_y=a[1]+t*(b[1]-a[1]);door=next(o for o in objects if o['kind']=='door')
                    if abs(cross_y-door['position'][1])>door['size'][1]/2-.12:raise SpatialError('exit_path_misses_door_opening')
                if min(a[0],b[0])<0 or min(a[1],b[1])<0 or max(a[1],b[1])>size[1]:raise SpatialError('exit_path_crosses_other_wall')
        previous=shot['end_state']
    return {'valid':True,'furniture_counts':counts,'projected_actors':observations,'semantic_production_approved':False}


def _floor(plan,state,camera_id,out,label):
    w,h=1100,1000;im=Image.new('RGB',(w,h),'#f5f4f0');d=ImageDraw.Draw(im)
    scale=155;ox,oy=120,850
    xy=lambda p:(ox+p[0]*scale,oy-p[1]*scale)
    d.text((24,20),'SPATIAL BLOCKOUT / DESIGN COORDINATES / NOT CAST OR PHOTO',fill='black')
    d.text((24,42),label+' | '+camera_id,fill='black')
    room=plan['room']['size'];d.rectangle([xy([0,room[1]]),xy([room[0],0])],outline='black',width=5)
    for o in plan['objects']:
        p,s=o['position'],o['size'];a=xy([p[0]-s[0]/2,p[1]+s[1]/2]);b=xy([p[0]+s[0]/2,p[1]-s[1]/2])
        color={'bed':'#b89c82','table':'#9f8162','window':'#74bad8','door':'#d6b878'}[o['kind']]
        d.rectangle([a,b],fill=color,outline='black',width=2);d.text((a[0]+3,a[1]+4),o['id'],fill='black')
    c=plan['cameras'][camera_id];cp=xy(c['position']);tp=xy(c['target']);d.line([cp,tp],fill='#9348bd',width=3)
    yaw=math.atan2(c['target'][1]-c['position'][1],c['target'][0]-c['position'][0]);hfov=2*math.atan(math.tan(math.radians(c['vertical_fov_deg'])/2)*736/1312)
    for a in (yaw-hfov/2,yaw+hfov/2):d.line([cp,xy([c['position'][0]+3*math.cos(a),c['position'][1]+3*math.sin(a)])],fill='#b991d4',width=2)
    d.ellipse([cp[0]-7,cp[1]-7,cp[0]+7,cp[1]+7],fill='#9348bd');d.text((cp[0]+9,cp[1]),'CAM',fill='#6c2c98')
    for who,a in state['actors'].items():
        p=xy(a['position']);color=COLORS[who];rad=13
        d.ellipse([p[0]-rad,p[1]-rad,p[0]+rad,p[1]+rad],fill=color,outline='black',width=2)
        d.text((p[0]+17,p[1]-8),who+' / '+a['pose']+(' / exited' if not a['visible'] else ''),fill=color)
    prop=state['props']['bread_bag'];p=xy(prop['position']);d.rectangle([p[0]-6,p[1]-6,p[0]+6,p[1]+6],fill='#f5dc65',outline='black');d.text((25,920),'bread_bag holder = '+prop['holder'],fill='black')
    d.text((25,944),'Color identifies a named placeholder, not clothing color. Purple = camera and horizontal field of view.',fill='black')
    im.save(out)


def prepare(run=DEFAULT_RUN,source=SOURCE):
    return prepare_plan(run,novel_plan(source))


def prepare_plan(run,plan):
    """Prepare an explicit source-bound staging design; never alter old plans."""
    run=Path(run).resolve();validation=validate(plan)
    freeze(run/'SPATIAL_PLAN.json',plan);freeze(run/'VALIDATION.json',validation)
    rows=[]
    for shot in plan['shots']:
        for stage,state in [('start',shot['start_state']),('end',shot['end_state'])]+[('at_'+str(v['segment_seconds']),v['state']) for v in shot.get('intermediate_states',[])]:
            file=run/'diagrams'/(shot['id']+'_'+stage+'.png');file.parent.mkdir(parents=True,exist_ok=True)
            if not file.exists():_floor(plan,state,shot['camera_id'],file,shot['id']+' '+stage)
            rows.append({'shot_id':shot['id'],'stage':stage,'image':bind(file),'camera_id':shot['camera_id'],'state_sha256':fingerprint(state)})
    freeze(run/'DIAGRAMS.json',{'schema':'spatial_diagrams/v24','plan':bind(run/'SPATIAL_PLAN.json'),'items':rows,'production_approved':False})
    # Original stage handoff is explicit and frozen; no human names inferred from pixels.
    handoff={'schema':'spatial_reference_handoff/v24','plan':bind(run/'SPATIAL_PLAN.json'),'rooms':{'su_mo_room':{'furniture_ids':[o['id'] for o in plan['objects']],'geometry_sha256':fingerprint({'room':plan['room'],'objects':plan['objects']})}},
             'cast_mapping':[{k:a[k] for k in ('id','label','identity_image','diagram_color')} for a in plan['actors']],
             'segments':[{'id':s['id'],'source_prompt':s['source_prompt'],'camera':plan['cameras'][s['camera_id']],'start_state':s['start_state'],'end_state':s['end_state'],'prop_transfers':s.get('prop_transfers',[]),'production_approved':False} for s in plan['shots']],
             'production_approved':False,'publication':False}
    freeze(run/'HANDOFF.json',handoff)
    freeze(run/'CAMERA_PROJECTION.json',projection_report(plan))
    return {'status':'spatial_prepared','plan':bind(run/'SPATIAL_PLAN.json'),'diagrams':bind(run/'DIAGRAMS.json'),'handoff':bind(run/'HANDOFF.json'),'model_posts':0,'production_approved':False}


LEGACY_MATERIALS = 'identity_placeholders/v24'
SKIN_MATERIALS = 'identity_color_clothes_only/v25'


def material_contract(policy=SKIN_MATERIALS):
    if policy!=SKIN_MATERIALS:raise SpatialError('explicit_skin_material_policy_required')
    return {'schema':'spatial_skin_material_contract/v25','policy':policy,
            'skin':{'material_name':'human_skin_proxy_v25','base_color':[.62,.43,.31],'roughness':.7},
            'actors':{who:{'head':'human_skin_proxy_v25','nose_direction':'human_skin_proxy_v25','arm':'human_skin_proxy_v25',
                           'torso':who+'_IDENTITY_PLACEHOLDER','shirt_base_color':list(color),
                           'leg':who+'_IDENTITY_PLACEHOLDER','thigh':who+'_IDENTITY_PLACEHOLDER','shin':who+'_IDENTITY_PLACEHOLDER'}
                      for who,color in {'su_mo':(.10,.28,.62),'ye_nan':(.04,.5,.5),'ye_xijue':(.85,.39,.06)}.items()},
            'geometry_changes':False,'camera_changes':False,'state_changes':False,
            'scope':'Neutral skin proxy for existing head/nose/arm meshes. No added hands/fingers/face rig or production identity approval.'}


def _skin_script(text):
    """Explicit material-only successor; retain the legacy template byte-for-byte."""
    contract=json.dumps(material_contract(),ensure_ascii=True)
    old="materials={k:mat(k+'_IDENTITY_PLACEHOLDER',v) for k,v in colors.items()}"
    new=old+"\nskin_contract=json.loads("+repr(contract)+")\nskin_material=mat('human_skin_proxy_v25',tuple(skin_contract['skin']['base_color']),.7)"
    if text.count(old)!=1:raise SpatialError('skin_material_injection_target_changed')
    text=text.replace(old,new)
    # The meshes and all coordinates remain unchanged; only these material arguments differ.
    substitutions=[
        ("(.13,.16,.17),m))","(.13,.16,.17),skin_material))"),
        ("(.125,.13,.16),m))","(.125,.13,.16),skin_material))"),
        ("(.035,.055,.035),m))","(.035,.055,.035),skin_material))"),
        ("(x+dx,y-.12,top-.77),.045,m))","(x+dx,y-.12,top-.77),.045,skin_material))"),
    ]
    for old,new in substitutions:
        if text.count(old)!=1:raise SpatialError('skin_part_material_target_changed')
        text=text.replace(old,new)
    marker=" render_metadata.append({'name':name,"
    added=" material_bindings=[]\n for obj in dynamic:\n  if obj.type!='MESH' or not obj.data.materials:continue\n  material=obj.data.materials[0];base=material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value\n  material_bindings.append({'object':obj.name,'material':material.name,'base_color':list(base)[:3]})\n"
    if text.count(marker)!=1:raise SpatialError('skin_actual_metadata_target_changed')
    text=text.replace(marker,added+" render_metadata.append({'actor_material_bindings':material_bindings,'name':name,")
    marker="'schema':'actual_blender_spatial_render/v24',"
    if text.count(marker)!=1:raise SpatialError('skin_metadata_schema_target_changed')
    return text.replace(marker,"'material_contract':skin_contract,'schema':'actual_blender_spatial_render/v24',")


def validate_skin_metadata(metadata):
    contract=material_contract()
    if metadata.get('material_contract')!=contract:raise SpatialError('actual_skin_material_contract_changed')
    observed=set()
    for row in metadata['renders']:
        for obj in row.get('actor_material_bindings',[]):
            for who,spec in contract['actors'].items():
                if not obj['object'].startswith(who+'_'):continue
                suffix=obj['object'][len(who)+1:].split('.')[0]
                if suffix not in ('head','nose_direction','arm','torso','leg','thigh','shin'):continue
                observed.add((who,suffix))
                if obj['material']!=spec[suffix]:raise SpatialError('actual_actor_part_has_wrong_material')
                expected=contract['skin']['base_color'] if suffix in ('head','nose_direction','arm') else spec['shirt_base_color']
                rgb=obj.get('base_color')
                if not isinstance(rgb,list) or len(rgb)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in rgb):raise SpatialError('actual_material_rgb_required')
                if any(abs(a-b)>1e-6 for a,b in zip(rgb,expected)):raise SpatialError('actual_skin_or_clothing_color_changed')
    if any(any((who,part) not in observed for part in ('head','torso','arm')) for who in CAST):raise SpatialError('actual_skin_render_missing_named_actor')
    return {'skin_materials_verified':True,'observed_actor_parts':[list(x) for x in sorted(observed)]}


def blender_script(plan_path, output_dir, material_policy=LEGACY_MATERIALS,stage_policy='legacy/v24'):
    """Generate a self-contained script; Blender Cycles CPU, never CUDA/Eevee."""
    text=_BLENDER_TEMPLATE.replace('__PLAN__',repr(str(Path(plan_path).resolve()))).replace('__OUTPUT__',repr(str(Path(output_dir).resolve())))
    if material_policy==SKIN_MATERIALS:text=_skin_script(text)
    elif material_policy!=LEGACY_MATERIALS:raise SpatialError('unknown_material_policy')
    if stage_policy=='canonical_room_body/v34':
        from . import visual_spatial_reanchor_v34
        return visual_spatial_reanchor_v34.build_script(text)
    if stage_policy=='first_camera_beat/v1':
        from . import visual_spatial_reanchor_v34
        return visual_spatial_reanchor_v34.build_script(text,first_frame_policy=stage_policy)
    if stage_policy!='legacy/v24':raise SpatialError('unknown_spatial_stage_policy')
    return text


def render(run,blender,*,timeout=900,render_tag='blender_fov_r1',material_policy=LEGACY_MATERIALS,stage_policy='legacy/v24'):
    run=Path(run).resolve();plan=json.loads((run/'SPATIAL_PLAN.json').read_text(encoding='utf-8'));validate(plan)
    if not re.fullmatch(r'blender[A-Za-z0-9_-]*',render_tag):raise SpatialError('safe_blender_render_tag_required')
    out=run/render_tag;out.mkdir(exist_ok=True);script=out/'render_spatial.py';data=blender_script(run/'SPATIAL_PLAN.json',out,material_policy,stage_policy)
    if script.exists() and script.read_text(encoding='utf-8')!=data:raise SpatialError('frozen_blender_script_changed')
    script.write_text(data,encoding='utf-8')
    request={'schema':'spatial_blender_cpu_request/v24','blender':bind(blender),'plan':bind(run/'SPATIAL_PLAN.json'),'script':bind(script),'device':'CPU','engine':'CYCLES','publication':False}
    if material_policy==SKIN_MATERIALS:request['material_contract']=material_contract()
    if stage_policy!='legacy/v24':request['stage_policy']=stage_policy
    freeze(out/'REQUEST.json',request)
    if (out/'RESULT.json').exists():
        receipt=json.loads((out/'RESULT.json').read_text(encoding='utf-8'))
        checked=receipt['files']+[receipt[k] for k in ('contact','scene','metadata')]
        if receipt['request_sha256']!=sha(out/'REQUEST.json') or any(sha(x['path'])!=x['sha256'] for x in checked):raise SpatialError('render_receipt_changed')
        if material_policy==SKIN_MATERIALS:
            check=validate_skin_metadata(json.loads((out/'RENDER_METADATA.json').read_text(encoding='utf-8')))
            if receipt.get('material_policy')!=SKIN_MATERIALS or receipt.get('skin_material_check')!=check:raise SpatialError('skin_receipt_check_changed')
        return receipt
    with (out/'stdout.log').open('w',encoding='utf-8') as stdout,(out/'stderr.log').open('w',encoding='utf-8') as stderr:
        p=subprocess.run([str(blender),'--background','--factory-startup','--threads','2','--python',str(script)],stdout=stdout,stderr=stderr,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:raise SpatialError('blender_cpu_render_failed_see_logs')
    expected=['room_front','room_side','room_reverse']+[s['id']+'_'+stage for s in plan['shots'] for stage in ('start','end')]+['S04_at_7']
    files=[]
    for name in expected:
        path=out/(name+'.png')
        with Image.open(path) as im:
            if im.size!=(736,1312):raise SpatialError('actual_blender_dimensions_wrong')
        files.append(bind(path))
    metadata=json.loads((out/'RENDER_METADATA.json').read_text(encoding='utf-8'))
    if (metadata.get('engine')!='CYCLES' or metadata.get('device')!='CPU' or metadata.get('plan_sha256')!=sha(run/'SPATIAL_PLAN.json')
            or metadata.get('structural_ids')!=['bed_01','table_01_top','door_01_open','window_01','window_02']
            or [x['name'] for x in metadata.get('renders',[])]!=expected):raise SpatialError('actual_blender_metadata_contract_changed')
    if any(abs(v['actual_vertical_fov_deg']-plan['cameras'][v['camera_id']]['vertical_fov_deg'])>1e-4 for v in metadata['renders']):raise SpatialError('actual_blender_camera_fov_mismatch')
    skin_check=validate_skin_metadata(metadata) if material_policy==SKIN_MATERIALS else None
    cards=[]
    for f in files:
        with Image.open(f['path']) as im:
            c=Image.new('RGB',(184,350),'white');c.paste(im.convert('RGB').resize((184,328)),(0,22));ImageDraw.Draw(c).text((4,5),Path(f['path']).stem,fill='black');cards.append(c)
    board=Image.new('RGB',(736,math.ceil(len(cards)/4)*350),'white')
    for i,c in enumerate(cards):board.paste(c,((i%4)*184,(i//4)*350))
    board.save(out/'CONTACT.jpg',quality=94)
    receipt={'schema':'spatial_blender_cpu_result/v24','request_sha256':sha(out/'REQUEST.json'),'files':files,'contact':bind(out/'CONTACT.jpg'),'scene':bind(out/'room_layout.blend'),'metadata':bind(out/'RENDER_METADATA.json'),'device':'CPU','model_posts':0,'content_status':'blockout_not_photoreal_or_production_approved','production_approved':False}
    if skin_check is not None:receipt.update(material_policy=material_policy,skin_material_check=skin_check)
    freeze(out/'RESULT.json',receipt);return receipt


_BLENDER_TEMPLATE=r'''import bpy, json, math, hashlib
from pathlib import Path
from mathutils import Vector, Quaternion
from bpy_extras.object_utils import world_to_camera_view
plan=json.loads(Path(__PLAN__).read_text(encoding='utf-8'));out=Path(__OUTPUT__)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=12
scene.render.resolution_x=736;scene.render.resolution_y=1312;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.film_transparent=False
scene.world.color=(.25,.25,.25)
def mat(name,color,rough=.8):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 b=m.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(*color,1);b.inputs['Roughness'].default_value=rough
 return m
wall=mat('warm_gray_plaster',(.30,.28,.23));floor=mat('old_gray_concrete',(.26,.25,.22));wood=mat('dark_old_wood',(.16,.085,.04));cloth=mat('gray_plain_bedding',(.22,.24,.24));glass=mat('pale_window',(.65,.73,.74));door=mat('door_wood',(.20,.13,.08));bread=mat('bagged_bread',(.68,.43,.13))
def cube(name,pos,size,material):
 bpy.ops.mesh.primitive_cube_add(size=1,location=pos);o=bpy.context.object;o.name=name;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(material);return o
def ball(name,pos,scale,material):
 bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,location=pos);o=bpy.context.object;o.name=name;o.scale=scale;o.data.materials.append(material);return o
def limb(name,a,b,r,material):
 d=Vector(b)-Vector(a);mid=(Vector(a)+Vector(b))/2;bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=r,depth=d.length,location=mid)
 o=bpy.context.object;o.name=name;o.rotation_euler=d.to_track_quat('Z','Y').to_euler();o.data.materials.append(material);return o
W,D,H=plan['room']['size']
cube('floor',(W/2,D/2,-.06),(W,D,.12),floor)
# Cut actual window and door holes; all views share the identical room geometry.
cube('south_wall',(W/2,-.06,H/2),(W,.12,H),wall)
cube('north_below',(W/2,D+.06,.55),(W,.12,1.1),wall);cube('north_above',(W/2,D+.06,2.5),(W,.12,.6),wall)
cube('north_left',(.3,D+.06,1.65),(.6,.12,1.1),wall);cube('north_right',(3.5,D+.06,1.65),(3.4,.12,1.1),wall)
cube('window_01',(1.2,D+.09,1.65),(1.2,.03,1.1),glass)
cube('west_below',(-.06,D/2,.55),(.12,D,1.1),wall);cube('west_above',(-.06,D/2,2.5),(.12,D,.6),wall)
cube('west_low',(-.06,1.3,1.65),(.12,2.6,1.1),wall);cube('west_high',(-.06,4.05,1.65),(.12,.7,1.1),wall)
cube('window_02',(-.09,3.15,1.65),(.03,1.1,1.1),glass)
cube('east_front',(W+.06,.4,H/2),(.12,.8,H),wall);cube('east_rear',(W+.06,3.2,H/2),(.12,2.4,H),wall);cube('east_lintel',(W+.06,1.4,2.45),(.12,1.2,.7),wall)
cube('door_01_open',(W+.55,2.,1.05),(1.1,.07,2.1),door)
for o in plan['objects']:
 p=o['position'];s=o['size']
 if o['kind']=='bed':
  cube(o['id'],p,s,wood);cube('mattress',(p[0],p[1],.59),(s[0]-.08,s[1]-.05,.14),cloth);cube('pillow',(p[0],p[1]+.67,.73),(1.05,.38,.13),cloth)
 if o['kind']=='table':
  cube(o['id']+'_top',(p[0],p[1],.77),(s[0],s[1],.06),wood)
  for x in (-.27,.27):
   for y in (-.24,.24):cube(o['id']+'_leg',(p[0]+x,p[1]+y,.37),(.06,.06,.74),wood)
for name,pos,power,sz in [('window_light',(1.2,3.9,2.2),180,2),('fill',(3,.7,2.5),75,3)]:
 bpy.ops.object.light_add(type='AREA',location=pos);l=bpy.context.object;l.name=name;l.data.energy=power;l.data.shape='DISK';l.data.size=sz;l.rotation_euler=(Vector((2,2,.5))-l.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add();cam=bpy.context.object;scene.camera=cam
dynamic=[]
render_metadata=[]
def clear_dynamic():
 for o in list(dynamic):
  if o.name in bpy.data.objects:bpy.data.objects.remove(o,do_unlink=True)
 dynamic.clear()
colors={'su_mo':(.10,.28,.62),'ye_nan':(.04,.5,.5),'ye_xijue':(.85,.39,.06)}
materials={k:mat(k+'_IDENTITY_PLACEHOLDER',v) for k,v in colors.items()}
def draw_state(state):
 clear_dynamic()
 for spec in plan['actors']:
  who=spec['id'];a=state['actors'][who]
  if not a['visible']:continue
  x,y,z=a['position'];h=spec['design_height'];m=materials[who];pose=a['pose'];first=len(dynamic)
  if pose=='lying':
   dynamic.append(ball(who+'_torso',(x,y,z+.22),(.22,.42,.15),m));dynamic.append(ball(who+'_head',(x,y+.58,z+.27),(.13,.16,.17),m))
   for dx in (-.11,.11):dynamic.append(limb(who+'_leg',(x+dx,y-.28,z+.15),(x+dx,y-.79,z+.13),.075,m))
  else:
   top=z+h*(.63 if pose=='sitting' else .56 if pose=='kneeling' else 1.)
   dynamic.append(ball(who+'_head',(x,y,top-.13),(.125,.13,.16),m));dynamic.append(ball(who+'_nose_direction',(x,y-.13,top-.12),(.035,.055,.035),m));dynamic.append(ball(who+'_torso',(x,y,top-.46),(.19,.14,.27),m))
   hip=(x,y,top-.73)
   if pose=='sitting':
    for dx in (-.1,.1):dynamic.append(limb(who+'_thigh',(x+dx,y,hip[2]),(x+dx,y-.23,.65),.07,m));dynamic.append(limb(who+'_shin',(x+dx,y-.23,.65),(x+dx,y-.23,.1),.065,m))
   elif pose=='kneeling':
    for dx in (-.1,.1):dynamic.append(limb(who+'_leg',(x+dx,y,hip[2]),(x+dx,y+.23,.1),.07,m))
   else:
    for dx in (-.1,.1):dynamic.append(limb(who+'_leg',(x+dx,y,hip[2]),(x+dx,y,.08),.07,m))
   for dx in (-.24,.24):dynamic.append(limb(who+'_arm',(x+dx,y,top-.32),(x+dx,y-.12,top-.77),.045,m))
   rotation=Quaternion(Vector((0,0,1)),math.radians(a['facing_deg']+90));pivot=Vector((x,y,z))
   for obj in dynamic[first:]:
    obj.location=pivot+rotation@(obj.location-pivot);obj.rotation_euler=(rotation@obj.rotation_euler.to_quaternion()).to_euler()
 p=state['props']['bread_bag']['position'];dynamic.append(cube('bread_bag_SINGLE',p,(.19,.11,.20),bread))
def camera(spec):
 cam.location=spec['position'];cam.rotation_euler=(Vector(spec['target'])-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='PERSP';cam.data.sensor_fit='VERTICAL';cam.data.lens=cam.data.sensor_height/(2*math.tan(math.radians(spec['vertical_fov_deg'])/2))
def render(name,camid,state=None):
 clear_dynamic()
 if state:draw_state(state)
 camera(plan['cameras'][camid]);scene.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
 projection=cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(),x=736,y=1312)
 render_metadata.append({'name':name,'camera_id':camid,'actual_vertical_fov_deg':math.degrees(2*math.atan(1/projection[1][1])),'camera_world_matrix':[list(row) for row in cam.matrix_world],'camera_projection_matrix':[list(row) for row in projection],'visible_actor_ids':[who for who,a in state['actors'].items() if a['visible']] if state else [],'bread_holder':state['props']['bread_bag']['holder'] if state else None,'render_size':[scene.render.resolution_x,scene.render.resolution_y]})
for k in ('room_front','room_side','room_reverse'):render(k,k)
for s in plan['shots']:
 for stage in ('start','end'):render(s['id']+'_'+stage,s['camera_id'],s[stage+'_state'])
 for v in s.get('intermediate_states',[]):render(s['id']+'_at_'+str(v['segment_seconds']),s['camera_id'],v['state'])
clear_dynamic();camera(plan['cameras']['room_front']);bpy.ops.wm.save_as_mainfile(filepath=str(out/'room_layout.blend'))
metadata={'schema':'actual_blender_spatial_render/v24','blender_version':bpy.app.version_string,'engine':scene.render.engine,'device':scene.cycles.device,'threads':2,'plan_sha256':hashlib.sha256(Path(__PLAN__).read_bytes()).hexdigest(),'structural_ids':[name for name in ['bed_01','table_01_top','door_01_open','window_01','window_02'] if name in bpy.data.objects],'renders':render_metadata}
(out/'RENDER_METADATA.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
print('SPATIAL_CPU_COMPLETE')
'''
