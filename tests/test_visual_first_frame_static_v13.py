"""Still-vs-motion isolation, actual ROI pixels and shot guide integrity; CPU only."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

from PIL import Image
import pytest

from src.content_factory import visual_first_frame_static_v13 as s
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_h3_handoff_v3 as h
from src.content_factory import visual_generation_reference_v7 as g
from src.content_factory import visual_image_jobs_v3 as jobs
from src.content_factory import visual_continuous_stage_v6 as staging
from src.content_factory.visual_shot_binding_v3 import compile_bindings
from test_visual_environment_v4 import static_place
from test_visual_environment_continuation_v6 import setup_origin,tree
from test_visual_asset_pipeline_v3 import service,FakeReviewer


def plan_file(tmp_path,packet):
    shot=packet['shots'][0]
    value=dict(schema=s.SCHEMA,source=packet['source'],packet_sha256=p.fingerprint(packet),shots=[dict(
        shot_id=shot['id'],shot_sha256=p.fingerprint(shot),visible_cast=shot['visible_cast'],
        static_start_prompt='A single adult man lies on the bed, eyes closed, head resting on the mattress.',
        camera_override=dict(eye=[3.2,.4,1.6],target=[.9,2.6,.5],fov=50))])
    path=tmp_path/'STILL_PLAN.json';p.write(path,value)
    return dict(first_frame_contract=s.CONTRACT,first_frame_plan=dict(path=str(path),sha256=p.file_sha(path))),value


def fixture(tmp_path):
    path=tmp_path/'SCRIPT.md';path.write_text('Source remains unchanged.',encoding='utf-8')
    entity=static_place();shot=dict(id='F1',place_id=entity['id'],place_view='side',visible_cast=['actor'],
        character_views={'actor':'front'},scene_present_cast=['actor','child_offscreen'],
        visual_prompt='ORIGINAL_DYNAMIC_PROMPT: the child_offscreen speaks and the man later opens his eyes.',
        audio=[dict(speaker='child_offscreen',mode='offscreen_dialogue',text='Original audio remains.')],start=0,end=5)
    packet=dict(schema='visual_asset_packet/v3',book_id='book1',source=dict(path=str(path),sha256=p.file_sha(path)),
        characters=[dict(id='actor',design_version='v1')],places=[entity],shots=[shot])
    config,_=plan_file(tmp_path,packet);config['generation_reference_policy']=g.POLICY
    plan=dict(packet=packet,packet_sha256=p.fingerprint(packet),config=config)
    return plan,dict(shot,binding_sha256='a'*64),entity


def test_default_is_unchanged_and_static_plan_requires_explicit_isolated_contract():
    assert not s.enabled({})
    for config in [dict(first_frame_plan={}),dict(first_frame_contract='guess'),
                   dict(first_frame_contract=s.CONTRACT,first_frame_plan={})]:
        with pytest.raises(ValueError):s.enabled(config)


@pytest.mark.parametrize('mutation',[
    lambda value:value.update(source=dict(path='wrong',sha256='0'*64)),
    lambda value:value.update(packet_sha256='0'*64),
    lambda value:value['shots'][0].update(shot_sha256='0'*64),
    lambda value:value['shots'][0].update(visible_cast=['actor','child_offscreen']),
    lambda value:value['shots'][0].update(static_start_prompt='中文动态提示'),
    lambda value:value['shots'][0].update(static_start_prompt='The actor hears child offscreen nearby.'),
    lambda value:value['shots'][0].update(unused_dynamic_prompt='Wrong content in another field.'),
    lambda value:value['shots'].append(deepcopy(value['shots'][0])),
    lambda value:value['shots'][0]['camera_override'].update(eye=[20,0,1]),
])
def test_plan_cannot_change_source_shot_cast_or_leak_offscreen_identity(tmp_path,mutation):
    plan,_,_=fixture(tmp_path);path=Path(plan['config']['first_frame_plan']['path']);value=p.read(path);mutation(value);p.write(path,value)
    plan['config']['first_frame_plan']['sha256']=p.file_sha(path)
    with pytest.raises(ValueError):s.validate_plan(plan['packet'],plan['config'])


def test_physical_plan_hash_is_checked_even_if_its_content_would_be_valid(tmp_path):
    plan,_,_=fixture(tmp_path);path=Path(plan['config']['first_frame_plan']['path']);path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='plan_file_changed'):s.validate_plan(plan['packet'],plan['config'])


@pytest.mark.parametrize('camera',[
    dict(eye=[.9,2.6,.2],target=[2,3,1],fov=50),
    dict(eye=[1,1,1],target=[1,1,1],fov=50),
    dict(eye=[1,1,1],target=[2,2,1],fov=10),
    dict(eye=[True,1,1],target=[2,2,1],fov=50),
])
def test_camera_must_be_physical_without_rewriting_canonical_views(tmp_path,camera):
    _,_,entity=fixture(tmp_path)
    with pytest.raises(ValueError):s.validate_camera(entity['spatial_layout'],camera)


def test_shot_guide_overrides_only_camera_and_h3_reads_same_frozen_pixels(tmp_path):
    plan,shot,entity=fixture(tmp_path);before=deepcopy(entity);run=tmp_path/'asset';p.write(run/'PLAN.json',plan)
    value=s.guide(run,plan,shot,entity,width=160,height=256,create=True)
    assert value['camera']!=entity['spatial_layout']['cameras']['side'] and entity==before
    path=run/'frame.png';shutil.copyfile(value['path'],path);frame=dict(path=str(path),environment_guide=value)
    old=tree(run)
    assert h._ready_environment_guide(run,entity,shot,frame)==value and tree(run)==old
    _,semantic=s.contexts(entity,shot,s.entry(plan,shot),width=160,height=256)
    assert 'shot-specific' in semantic['camera_description']
    frame['environment_guide']['camera']['fov']=60
    with pytest.raises(h.HandoffIntegrityError):h._ready_environment_guide(run,entity,shot,frame)


def test_missing_or_changed_guide_never_gets_rebuilt_during_readonly_validation(tmp_path):
    plan,shot,entity=fixture(tmp_path);run=tmp_path/'asset';p.write(run/'PLAN.json',plan)
    with pytest.raises(FileNotFoundError):s.guide(run,plan,shot,entity,width=160,height=256,create=False)
    assert not (run/'environment_guides').exists()
    value=s.guide(run,plan,shot,entity,width=160,height=256,create=True)
    Path(value['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='pixels_changed'):s.guide(run,plan,shot,entity,width=160,height=256,create=False)
    assert Path(value['path']).read_bytes()==b'changed'


def test_head_shoulders_roi_is_single_contiguous_real_source_region():
    face=dict(x=307,y=30,width=139,height=165)
    assert s.identity_roi(face,[768,1024])==dict(x=203,y=0,width=347,height=401)
    with pytest.raises(ValueError):s.identity_roi(dict(x=0,y=0,width=300,height=800),[768,1024])
    with pytest.raises(ValueError):s.identity_roi(dict(x=-1,y=0,width=50,height=50),[768,1024])


def reviewed_actor(config,path):
    row=library.register(config['library'],path,book_id='book1',entity_id='actor',kind='character',view='front',design_version='v1')
    result=FakeReviewer().result(path);result['rois']['face']=dict(x=307,y=30,width=139,height=165)
    library.review(config['library'],book_id='book1',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
        decision='accepted',reviewer='protocol_fixture',checks=result['checks'],evidence=dict(image_sha256=row['sha256'],
            observations=['Protocol fixture only.'],review=p.fingerprint(result),source_review=result))
    return row


def test_native_firstframe_uses_static_start_single_identity_crop_and_original_h3_motion(tmp_path,service,monkeypatch):
    origin,run=setup_origin(tmp_path,service);old=p.read(origin/'PLAN.json');packet=deepcopy(old['packet'])
    packet['characters']=[dict(id='actor',design_version='v1',required_views=['front'],front_prompt='A fictional adult.',age_band='adult')]
    packet['stage_contract']='continuous_source_home_staging/v6';place=packet['places'][0]
    packet['shots']=[dict(id='F1',place_id=place['id'],place_view='front',visible_cast=['actor'],character_views={'actor':'front'},
        scene_present_cast=['actor','child_offscreen'],home_style_sha256=place['home_style_sha256'],
        visual_prompt='ORIGINAL_DYNAMIC_PROMPT: child_offscreen speaks and the man later opens his eyes.',
        audio=[dict(speaker='child_offscreen',mode='offscreen_dialogue',text='Original audio remains.')],start=0,end=5)]
    original=deepcopy(packet);monkeypatch.setattr(staging,'validate_packet',lambda value:True) # Protocol fixture only.
    config=g.bind(origin,run,packet);static_config,_=plan_file(tmp_path,packet);config.update(static_config,first_frame_width=160,first_frame_height=256)
    p.prepare(run,packet,config);plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json')
    source=tmp_path/'actor.png';image=Image.new('RGB',(768,1024),'white')
    for y in range(1024):
        for x in range(768):image.putpixel((x,y),(x%255,y%255,(x+y)%255))
    image.save(source);reviewed_actor(config,source)
    shot=compile_bindings(packet,lambda req:p._lookup(plan,req))['shots'][0]
    jid=p._prepare_first_frame(run,plan,state,shot);task=state['jobs'][jid];graph=p.read(Path(task['folder'])/'workflow_api.json')
    text=graph['first_frame__positive']['inputs']['text'];native=p.read(Path(task['folder'])/'PLAN.json')
    assert 'ORIGINAL_DYNAMIC_PROMPT' not in text and 'child_offscreen' not in text and 'Original audio' not in text
    assert 'A single adult man lies' in text and len(native['inputs'])==5
    identities=[q for q in native['inputs'] if q['input_name'].startswith('identity_')];assert len(identities)==1
    assert all(q['sha256']!=p.file_sha(source) for q in native['inputs'])
    with Image.open(source) as original_pixels,Image.open(identities[0]['path']) as cropped:
        assert cropped.size==(347,401) and cropped.tobytes()==original_pixels.crop((203,0,550,401)).tobytes()
    original_complete=service.complete
    def complete():
        original_complete()
        for output in service.histories['native_'+str(len(service.posts))]['outputs'].values():
            for item in output['images']:Image.new('RGB',(160,256),'gray').save(service.output/item['subfolder']/item['filename'])
    service.complete=complete
    jobs.submit(task['folder']);jobs.poll(task['folder']);receipt=jobs.collect(task['folder']);p._collect_generated(run,plan,state,jid,receipt)
    frame=state['first_frames']['F1'];p._verify_first_frame_generation(plan,shot,frame)
    h._ready_environment_guide(run,place,shot,frame)
    assert 'ORIGINAL_DYNAMIC_PROMPT' in h.prompt_for(shot,h._timing(shot)) and 'Original audio remains.' in h.prompt_for(shot,h._timing(shot))
    assert packet==original and p.read(run/'PLAN.json')['packet']==original
    crop=Path(identities[0]['path']);crop.write_bytes(b'changed')
    with pytest.raises(ValueError,match='crop_changed'):p._verify_first_frame_generation(plan,shot,frame)
