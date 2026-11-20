"""Source-bound production geometry and deterministic CPU camera guides.

The JSON describes an art-department choice, not novel facts or a reconstructed
real building. Guide conditioning improves spatial input; it does not certify a
diffusion result. Nothing here calls models, installs packages or changes jobs.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from PIL import Image,ImageDraw
import numpy as np
from jsonschema import validate as schema_validate

VERSION='room_layout_camera/v4'
RENDERER='cpu_zbuffer/v4'
VIEWS=('front','reverse','side','layout')
COLORS={'wood':'#a98557','brown':'#80654c','gray':'#8f9598','blue':'#8aa4ba',
        'green':'#94a384','cream':'#d7d0b9','red':'#b68f88'}
KINDS=('bed','table','cabinet','stove','counter','stool','chair','shelf','building','light','bedding','sofa','other')
STATIC_CONTRACT='static_room_per_shot_props/v1'
STATIC_MATERIALS=dict(wall_surface=('aged_plaster','plain_painted','tile','exposed_brick','concrete'),
    wall_color=('cream','gray','brown','blue','green'),floor_surface=('worn_wood','concrete','ceramic_tile','earth','stone','asphalt'),
    condition=('worn','ordinary','well_kept'),lighting=('dim_ceiling_light','natural_daylight','warm_ceiling_light','overcast_daylight'))


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def obj(properties):return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def layout_schema(*,require_base_z=False):
    """Read old floor-level objects, but require explicit height for new planning."""
    number=dict(type='number',minimum=0,maximum=100)
    positive=dict(type='number',exclusiveMinimum=0,maximum=100)
    text=dict(type='string',minLength=1,maxLength=600)
    ident=dict(type='string',pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,48}$')
    def vec(n):return dict(type='array',items=number,minItems=n,maxItems=n)
    camera=obj(dict(eye=vec(3),target=vec(3),fov=dict(type='number',minimum=35,maximum=110)))
    item=obj(dict(id=ident,kind=dict(enum=list(KINDS)),description=text,center=vec(2),size=vec(3),
        yaw=dict(type='number',minimum=-360,maximum=360),color=dict(enum=list(COLORS)),base_z=number))
    if not require_base_z:item['required'].remove('base_z')
    return obj(dict(schema=dict(const=VERSION),space_type=dict(enum=['interior','exterior']),
        room=obj(dict(width=positive,depth=positive,height=positive)),
        openings=dict(type='array',maxItems=12,items=obj(dict(id=ident,kind=dict(enum=['door','window']),
            wall=dict(enum=['north','south','east','west']),offset=number,width=positive,bottom=number,height=positive))),
        objects=dict(type='array',minItems=1,maxItems=24,items=item),
        cameras=obj({view:deepcopy(camera) for view in ('front','reverse','side')}),design_note=text))


def _point(v):return all(type(n) in (int,float) and math.isfinite(n) for n in v)
def _base(item):return item.get('base_z',0)
def _corners(item):
    angle=math.radians(item['yaw']);c,s=math.cos(angle),math.sin(angle);x,y=item['center'];w,d,_=item['size']
    return [(x+a*c-b*s,y+a*s+b*c) for a,b in ((-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2))]


def _object_parts(item):
    """Recognizable furniture inside the unchanged conservative collision box."""
    kind=item['kind'];w,d,h=item['size'];parts=[];angle=math.radians(item['yaw']);c,s=math.cos(angle),math.sin(angle)
    def box(x,y,z,pw,pd,ph):
        parts.append(dict(item,center=[item['center'][0]+x*c-y*s,item['center'][1]+x*s+y*c],
            size=[pw,pd,ph],base_z=_base(item)+z))
    def legs(top):
        thick=min(w,d)*.12
        for x in (-(w-thick)/2,(w-thick)/2):
            for y in (-(d-thick)/2,(d-thick)/2):box(x,y,0,thick,thick,top)
    if kind in ('table','stool'):
        thickness=h*(.12 if kind=='table' else .16)
        box(0,0,h-thickness,w,d,thickness);legs(h-thickness)
    elif kind=='chair':
        seat=h*.43;thickness=h*.08
        box(0,0,seat,w,d,thickness);legs(seat)
        box(0,(d-d*.12)/2,seat+thickness,w,d*.12,h-seat-thickness)
    elif kind=='shelf':
        thickness=min(h*.045,d*.12);post=min(w,d)*.09
        for z in (0,(h-thickness)/3,2*(h-thickness)/3,h-thickness):box(0,0,z,w,d,thickness)
        for x in (-(w-post)/2,(w-post)/2):
            for y in (-(d-post)/2,(d-post)/2):box(x,y,0,post,post,h)
    else:parts.append(item)
    return parts


def _overlap(a,b):
    # Separating-axis check: touching edges are allowed, intersecting footprints not.
    for polygon in (a,b):
        for p,q in zip(polygon,polygon[1:]+polygon[:1]):
            axis=(p[1]-q[1],q[0]-p[0]);av=[x*axis[0]+y*axis[1] for x,y in a];bv=[x*axis[0]+y*axis[1] for x,y in b]
            if max(av)<=min(bv)+1e-7 or max(bv)<=min(av)+1e-7:return False
    return True


def validate_layout(layout):
    schema_validate(layout,layout_schema())
    room=layout['room'];w,d,h=(room[k] for k in ('width','depth','height'))
    if not _point((w,d,h)) or min(w,d,h)<1:raise ValueError('environment_dimensions_too_small_or_nonfinite')
    identifiers=[o['id'] for o in layout['objects']+layout['openings']]
    if len(identifiers)!=len(set(identifiers)):raise ValueError('duplicate_environment_object_id')
    cuboids=[]
    for item in layout['objects']:
        base=_base(item);top=base+item['size'][2]
        if (not _point(item['center']+item['size']+[item['yaw'],base]) or min(item['size'])<=0
            or base<0 or top>h+1e-7):
            raise ValueError('invalid_environment_object_dimensions')
        rectangle=_corners(item)
        if any(x < -1e-7 or x>w+1e-7 or y < -1e-7 or y>d+1e-7 for x,y in rectangle):raise ValueError('environment_object_outside_room')
        if any(max(base,low)<min(top,high)-1e-7 and _overlap(rectangle,other) for other,low,high in cuboids):
            raise ValueError('environment_objects_overlap')
        cuboids.append((rectangle,base,top))
    for opening in layout['openings']:
        if not _point([opening[k] for k in ('offset','width','bottom','height')]):raise ValueError('invalid_environment_opening')
        span=w if opening['wall'] in ('north','south') else d
        if opening['offset']+opening['width']>span+1e-7 or opening['bottom']+opening['height']>h+1e-7:
            raise ValueError('environment_opening_outside_wall')
        if opening['kind']=='door' and abs(opening['bottom'])>1e-7:raise ValueError('door_must_reach_floor')
        for other in layout['openings']:
            if other['id']>=opening['id'] or other['wall']!=opening['wall']:continue
            if (max(other['offset'],opening['offset']) < min(other['offset']+other['width'],opening['offset']+opening['width'])-1e-7
                and max(other['bottom'],opening['bottom']) < min(other['bottom']+other['height'],opening['bottom']+opening['height'])-1e-7):
                raise ValueError('environment_openings_overlap')
    directions={}
    for view,camera in layout['cameras'].items():
        eye,target=camera['eye'],camera['target']
        if not _point(eye+target+[camera['fov']]):raise ValueError('invalid_environment_camera')
        if any(not (0<=x<=limit) for vec in (eye,target) for x,limit in zip(vec,(w,d,h))):raise ValueError('environment_camera_outside_room')
        v=(target[0]-eye[0],target[1]-eye[1]);length=math.hypot(*v)
        if length<.3 or not .1<=eye[2]<=h:raise ValueError('environment_camera_direction_degenerate')
        directions[view]=(v[0]/length,v[1]/length)
        if any(_overlap(_corners(o),[(eye[0]-.01,eye[1]-.01),(eye[0]+.01,eye[1]-.01),
                (eye[0]+.01,eye[1]+.01),(eye[0]-.01,eye[1]+.01)])
                and _base(o)-1e-7<=eye[2]<=_base(o)+o['size'][2]+1e-7 for o in layout['objects']):
            raise ValueError('environment_camera_inside_object')
    dot=lambda a,b:sum(x*y for x,y in zip(directions[a],directions[b]))
    if dot('front','reverse')>-.5:raise ValueError('reverse_camera_not_opposing_front')
    if abs(dot('front','side'))>.85:raise ValueError('side_camera_not_distinct')
    return deepcopy(layout)


def design_description(entity,*,require=False):
    text=entity.get('layout_design') or entity.get('appearance_design') or ''
    if not isinstance(text,str) or require and not text.strip():raise ValueError('environment_design_description_required')
    if entity.get('spatial_layout'):
        layout=validate_layout(entity['spatial_layout'])
        text+='\nArt-department completion, not novel factual measurements: '+layout['design_note']
    return text


def review_context(entity,view):
    """Semantic camera anchors; numeric geometry stays out of visual JSON prompts."""
    layout=validate_layout(entity['spatial_layout']);description=design_description(entity,require=True)
    if view=='layout':
        return dict(layout_design=description,space_type=layout['space_type'],camera_description='Top-down floor plan, north at the top.',
            visible_anchors=[dict(id=o['id'],kind=o['kind'],description=o['description'],screen_region='center',distance_band='middle') for o in layout['objects']],
            comparison_rule='Compare fixed physical object and opening relationships. This is an art design, not a new novel fact.')
    camera=layout['cameras'][view];eye,target=camera['eye'],camera['target'];dx,dy=target[0]-eye[0],target[1]-eye[1]
    horizontal=math.hypot(dx,dy);right=(dy/horizontal,-dx/horizontal)
    direction=('north' if dy>0 else 'south') if abs(dy)>=abs(dx) else ('east' if dx>0 else 'west')
    anchors=[];room=layout['room'];w,d=room['width'],room['depth']
    items=[dict(id=o['id'],kind=o['kind'],description=o['description']+(' [Elevated above the floor.]' if _base(o)>0 else ''),
        point=(*o['center'],_base(o)+o['size'][2]/2)) for o in layout['objects']]
    for o in layout['openings']:
        items.append(dict(id=o['id'],kind=o['kind'],description=o['kind']+' on the '+o['wall']+' wall',
            point=_wall_point(o['wall'],o['offset']+o['width']/2,o['bottom']+o['height']/2,room)))
    for item in items:
        vx,vy=item['point'][0]-eye[0],item['point'][1]-eye[1]
        forward=(vx*dx+vy*dy)/horizontal;side=vx*right[0]+vy*right[1]
        if forward<=.08:continue
        ratio=side/(forward*math.tan(math.radians(camera['fov']/2)))
        if abs(ratio)>1.1:continue
        anchors.append(dict(id=item['id'],kind=item['kind'],description=item['description'],
            screen_region='left' if ratio<-.3 else 'right' if ratio>.3 else 'center',
            distance_band='near' if forward<max(w,d)*.33 else 'far' if forward>max(w,d)*.7 else 'middle'))
    return dict(layout_design=description,space_type=layout['space_type'],
        camera_description='Eye-level camera looking toward the '+direction+' side, '+view+' view of the same physical location.',
        visible_anchors=anchors,
        comparison_rule='Judge the actual target from the stated camera. A different camera may reverse screen sides; do not require copying the source image viewpoint. Foreground occlusion may leave an anchor uncertain. Compare wall openings and fixed furnishings, not generated captions.')


def _wall_point(wall,along,z,room):
    return (along,room['depth'],z) if wall=='north' else (along,0,z) if wall=='south' else (room['width'],along,z) if wall=='east' else (0,along,z)


def _floorplan(layout,size):
    width,height=size;canvas=Image.new('RGB',size,'#ede9df');draw=ImageDraw.Draw(canvas);room=layout['room']
    scale=min((width-48)/room['width'],(height-48)/room['depth']);ox=(width-room['width']*scale)/2;oy=(height-room['depth']*scale)/2
    def pt(p):return (ox+p[0]*scale,oy+(room['depth']-p[1])*scale)
    bounds=[pt((0,room['depth'])),pt((room['width'],0))];draw.rectangle(bounds,fill='#d8d2c5',outline='#484b4d',width=8)
    for item in sorted(layout['objects'],key=lambda o:_base(o)+o['size'][2]):
        draw.polygon([pt(p) for p in _corners(item)],fill=COLORS[item['color']],outline='#414546',width=3)
    for opening in layout['openings']:
        a=_wall_point(opening['wall'],opening['offset'],0,room);b=_wall_point(opening['wall'],opening['offset']+opening['width'],0,room)
        draw.line([pt(a),pt(b)],fill='#6998b0' if opening['kind']=='window' else '#b79d74',width=11)
    return canvas


def _perspective(layout,view,size,*,return_visibility=False,return_surfaces=False):
    width,height=size;room=layout['room'];camera=layout['cameras'][view];eye=camera['eye'];target=camera['target']
    sub=lambda a,b:tuple(x-y for x,y in zip(a,b))
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    cross=lambda a,b:(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    unit=lambda a:tuple(x/math.sqrt(dot(a,a)) for x in a)
    forward=unit(sub(target,eye));right=unit(cross(forward,(0,0,1)));up=cross(right,forward)
    f=(width/2)/math.tan(math.radians(camera['fov']/2));faces=[]
    def face(vertices,color,anchor_id=None,surface=None):
        points=[]
        for p in vertices:
            v=sub(p,eye);points.append((dot(v,right),dot(v,up),dot(v,forward)))
        # Clip against near plane to avoid overflow from a wall behind the camera.
        clipped=[]
        for a,b in zip(points,points[1:]+points[:1]):
            if a[2]>=.08:clipped.append(a)
            if (a[2]>=.08)!=(b[2]>=.08):
                t=(.08-a[2])/(b[2]-a[2]);clipped.append(tuple(x+(y-x)*t for x,y in zip(a,b)))
        if len(clipped)<3:return
        projected=[(max(-100000,min(100000,width/2+f*x/z)),max(-100000,min(100000,height/2-f*y/z))) for x,y,z in clipped]
        faces.append((clipped,projected,color,anchor_id,surface))
    w,d,h=(room[k] for k in ('width','depth','height'))
    face([(0,0,0),(w,0,0),(w,d,0),(0,d,0)],'#bcb4a3',surface='floor')
    if layout['space_type']=='interior':
        for wall,color in [('north','#cdc9bd'),('south','#d7d2c5'),('east','#c4c0b6'),('west','#d2cdbf')]:
            span=w if wall in ('north','south') else d
            face([_wall_point(wall,0,0,room),_wall_point(wall,span,0,room),_wall_point(wall,span,h,room),_wall_point(wall,0,h,room)],color,surface='wall')
    for item in layout['objects']:
        surface='wood' if item['color'] in ('wood','brown') and item['kind'] in ('bed','table','cabinet','counter','stool','chair','shelf') else None
        for part in _object_parts(item):
            base=[(*p,_base(part)) for p in _corners(part)];top=[(*p,_base(part)+part['size'][2]) for p in _corners(part)]
            face(base,COLORS[item['color']],item['id'],surface)
            face(top,COLORS[item['color']],item['id'],surface)
            for i in range(4):face([base[i],base[(i+1)%4],top[(i+1)%4],top[i]],COLORS[item['color']],item['id'],surface)
    # Opening faces lie just toward the room interior, so no coincident wall hides them.
    for opening in layout['openings']:
        a=opening['offset'];b=a+opening['width'];z=opening['bottom'];t=z+opening['height']
        vertices=[_wall_point(opening['wall'],q,r,room) for q,r in ((a,z),(b,z),(b,t),(a,t))]
        inward={'north':(0,-.01,0),'south':(0,.01,0),'east':(-.01,0,0),'west':(.01,0,0)}[opening['wall']]
        face([tuple(x+y for x,y in zip(p,inward)) for p in vertices],'#7799a9' if opening['kind']=='window' else '#9d8566',opening['id'])
    background=Image.new('RGB',size,'#dfd9c9' if layout['space_type']=='interior' else '#d5e1e6')
    pixels=np.array(background);depth=np.full((height,width),np.inf,dtype=np.float32)
    ids={item['id']:n+1 for n,item in enumerate(layout['objects']+layout['openings'])}
    visible=np.zeros((height,width),dtype=np.uint16) if return_visibility else None
    surface_ids={'wall':1,'floor':2,'wood':3}
    surfaces=np.zeros((height,width),dtype=np.uint8) if return_surfaces else None
    for camera_points,polygon,color,anchor_id,surface in faces:
        rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
        for k in range(1,len(polygon)-1):
            tri=[polygon[i] for i in (0,k,k+1)];z=[camera_points[i][2] for i in (0,k,k+1)]
            (x0,y0),(x1,y1),(x2,y2)=tri
            denominator=(y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
            if abs(denominator)<1e-9:continue
            left=max(0,int(math.floor(min(p[0] for p in tri))));right=min(width-1,int(math.ceil(max(p[0] for p in tri))))
            top=max(0,int(math.floor(min(p[1] for p in tri))));bottom=min(height-1,int(math.ceil(max(p[1] for p in tri))))
            if left>right or top>bottom:continue
            xx,yy=np.meshgrid(np.arange(left,right+1,dtype=np.float32)+.5,np.arange(top,bottom+1,dtype=np.float32)+.5)
            a=((y1-y2)*(xx-x2)+(x2-x1)*(yy-y2))/denominator
            b=((y2-y0)*(xx-x2)+(x0-x2)*(yy-y2))/denominator;c=1-a-b
            inside=(a>=-1e-6)&(b>=-1e-6)&(c>=-1e-6)
            inverse=a/z[0]+b/z[1]+c/z[2]
            values=np.divide(1,inverse,out=np.full_like(inverse,np.inf),where=inverse>0)
            target=depth[top:bottom+1,left:right+1];mask=inside&(values<target)
            target[mask]=values[mask];pixels[top:bottom+1,left:right+1][mask]=rgb
            if visible is not None:visible[top:bottom+1,left:right+1][mask]=ids.get(anchor_id,0)
            if surfaces is not None:surfaces[top:bottom+1,left:right+1][mask]=surface_ids.get(surface,0)
    # Draw only the visible polygon boundaries, never hidden edges through furniture.
    for camera_points,polygon,_,_,_ in faces:
        for i in range(len(polygon)):
            j=(i+1)%len(polygon);a,b=polygon[i],polygon[j];za,zb=camera_points[i][2],camera_points[j][2]
            steps=min(10000,max(1,int(math.hypot(a[0]-b[0],a[1]-b[1]))))
            for t in np.linspace(0,1,steps+1):
                x=int(round(a[0]+t*(b[0]-a[0])));y=int(round(a[1]+t*(b[1]-a[1])))
                if not (0<=x<width and 0<=y<height):continue
                z=1/((1-t)/za+t/zb)
                if z<=depth[y,x]+.025:pixels[y,x]=(91,92,87)
    image=Image.fromarray(pixels)
    if return_surfaces:
        return image,{key:surfaces==number for key,number in surface_ids.items()}
    if not return_visibility:return image
    result={}
    for ident,number in ids.items():
        yy,xx=np.where(visible==number)
        if len(xx)>=max(4,width*height*.0001):
            result[ident]=dict(screen_region='left' if xx.mean()<width*.35 else 'right' if xx.mean()>width*.65 else 'center')
    return image,result


def render_context(entity,view,*,width=768,height=1024):
    """Positive generation conditions: safe surfaces and only actually visible IDs."""
    if entity.get('background_contract')!=STATIC_CONTRACT:raise ValueError('static_background_contract_required')
    material=entity.get('static_materials')
    if (not isinstance(material,dict) or set(material)!=set(STATIC_MATERIALS)
        or any(material[key] not in values for key,values in STATIC_MATERIALS.items())):
        raise ValueError('static_materials_contract_invalid')
    layout=validate_layout(entity['spatial_layout'])
    if view not in VIEWS:raise ValueError('unsupported_environment_view')
    visible=({item['id']:dict(screen_region='center') for item in layout['objects']+layout['openings']}
             if view=='layout' else _perspective(layout,view,(width,height),return_visibility=True)[1])
    anchors=[]
    for item in layout['objects']+layout['openings']:
        if item['id'] not in visible:continue
        description=(item['color']+' '+item['kind'].replace('_',' ')+(' above floor level' if _base(item)>0 else '')
            if 'color' in item else item['kind']+' on the '+item['wall']+' wall')
        anchors.append(dict(kind=item['kind'],description=description,**visible[item['id']]))
    light=dict(dim_ceiling_light='dim warm overhead illumination',natural_daylight='soft natural daylight',
        warm_ceiling_light='warm overhead illumination',overcast_daylight='soft overcast daylight')[material['lighting']]
    surfaces={key:value.replace('_',' ') for key,value in material.items() if key!='lighting'}
    return dict(surface_materials=surfaces,illumination=light,visible_furnishings_and_openings=anchors,
        camera='Top-down view of the room geometry.' if view=='layout' else 'The exact camera, framing and visible surfaces in the geometry reference.',
        spatial_rule='Depict the visible geometry with natural materials and furnishings. Preserve object count, placement and partial framing shown in this camera.')


def render_guides(layout,folder,*,width=768,height=1024):
    layout=validate_layout(layout);folder=Path(folder)
    if type(width) is not int or type(height) is not int or min(width,height)<64 or max(width,height)>2048 or width%16 or height%16:
        raise ValueError('environment_guide_dimensions_invalid')
    folder.mkdir(parents=True,exist_ok=True);binding=dict(schema=VERSION,renderer=RENDERER,layout_sha256=digest(layout),layout=layout,width=width,height=height)
    manifest=folder/'GUIDES.json'
    if manifest.exists():
        old=json.loads(manifest.read_text(encoding='utf-8'))
        if old['binding']!=binding:raise ValueError('frozen_environment_guide_input_changed')
        for row in old['views'].values():
            path=Path(row['path'])
            if path.parent.resolve()!=folder.resolve() or file_sha(path)!=row['sha256']:raise ValueError('environment_guide_file_changed')
        return old
    rows={}
    for view in VIEWS:
        canvas=_floorplan(layout,(width,height)) if view=='layout' else _perspective(layout,view,(width,height))
        path=folder/(view+'.png')
        if path.exists():raise ValueError('orphan_environment_guide_not_overwritten')
        canvas.save(path)
        rows[view]=dict(path=str(path.resolve()),sha256=file_sha(path),view=view,layout_sha256=binding['layout_sha256'],
            camera=None if view=='layout' else deepcopy(layout['cameras'][view]),technical_guide=True,production_approved=False)
    result=dict(schema='environment_guides/v4',binding=binding,views=rows)
    manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def place_prompt(entity,view):
    if view not in VIEWS:raise ValueError('unsupported_environment_view')
    if entity.get('background_contract'):
        context=render_context(entity,view)
        return ('A photorealistic, unoccupied contemporary Chinese physical location. The first reference is the geometry '
            'blockout of this exact camera. Render natural room surfaces and the visible furnishings within this framing. '
            'Additional reference images supply established appearance and materials from another camera. '
            'Keep foreground cropping and occlusion as shown. No people, labels, diagrams, letters or captions.\n'
            +json.dumps(context,ensure_ascii=False))
    layout=validate_layout(entity['spatial_layout']);description=design_description(entity,require=True)
    base=entity.get('front_prompt','').strip()
    if not base:raise ValueError('environment_front_prompt_required')
    camera=('top-down floor-plan viewpoint' if view=='layout' else
        'the exact camera position and perspective of the geometry reference image')
    furniture='; '.join(x['kind']+': '+x['description'] for x in layout['objects'])
    return (f'An empty, photorealistic physical location, {camera}. The first reference is a geometric blockout of this exact location, '
        'not a collage or a second room. Recreate its spatial arrangement as natural materials and furnishings. '
        'Preserve the shown camera, wall openings and furniture locations. Additional reference, if present, supplies '
        'the established room appearance and materials from another camera. No people, labels, diagrams, letters or captions in the photograph. '
        +base+'\nProduction layout: '+description+'\nFixed furniture: '+furniture+'\nCamera and visible placement: '
        +json.dumps(review_context(entity,view),ensure_ascii=False))
