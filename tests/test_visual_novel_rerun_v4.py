"""Source/window, separated-node and original-ID contracts; no real model/GPU."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.content_factory import visual_novel_rerun_v4 as flow


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def fixture(tmp_path,*,attempts=2,vo=False,native_seconds=8):
    folder=tmp_path/'inputs';folder.mkdir(parents=True)
    source=folder/'SCRIPT.md'
    data=dict(scenes=[],segments=[],source_scope='three fixture scene windows, not a real novel')
    text='Existing fixed screenplay. Alice and Bob.\n'
    for n,(heading,body) in enumerate([
        ('Bedroom','Alice lies in the old bedroom. Alice says hello.'),
        ('Kitchen evening','Alice and Bob stand in the kitchen. Alice says hello.'),
        ('Kitchen morning','The same kitchen in morning. Alice and Bob eat. Alice says hello.')],1):
        sid=f'S{n}';text+=heading+'\n';start=len(text);text+=body+'\n';end=len(text)-1
        unit=dict(id=f'{sid}_P1_U1',parent=f'{sid}_P1',start=start,end=end,text=body,
            sha256=hashlib.sha256(body.encode()).hexdigest(),audio_items=[])
        a=text.index('hello',start)
        unit['audio_items']=[dict(speaker='Alice',channel='画外对白' if vo else '对白',text='hello',start=a,end=a+5)]
        scene=dict(id=sid,chapter=1,heading=heading,metadata=[],blocks=[dict(id=f'{sid}_P1',start=start,end=end,text=body)])
        data['scenes'].append(scene);data['segments'].append(dict(id=f'F{n:04d}',scene=sid,chapter=1,
            units=[unit],native_seconds=native_seconds,native_frames=192))
    source.write_text(text,encoding='utf-8');binding=dict(path=str(source.resolve()),sha256=flow.files.file_sha(source))
    data['source']=binding;coverage=folder/'COVERAGE.json';write(coverage,data)
    cast=folder/'cast';cast.mkdir()
    characters=[]
    for cid,name in [('a','Alice'),('b','Bob')]:
        s=text.index(name)
        characters.append(dict(id=cid,name=name,identity_group=cid,visual_design_age=10,front_prompt='One fictional child, gray cotton shirt.',
            source_facts=dict(script=str(source.resolve()),quote=name,start=s,end=s+len(name))))
    write(cast/'CAST_PLAN.json',dict(source=binding,characters=characters))
    write(cast/'VIEW_DESCRIPTIONS.json',dict(defaults={},right_profile_from_pose='same pose'))
    write(cast/'FINAL_MAP.json',dict(cast_plan_sha256=flow.files.file_sha(cast/'CAST_PLAN.json'),
        items=[dict(character_id=c['id'],view='front',prompt=c['front_prompt']) for c in characters]))
    run=tmp_path/'visual_novel_reruns_v4'/'new_visual'
    flow.prepare(run,source,coverage,cast,'fixture_book',user_statement='Authorized QA visual planning only.',
        config=dict(max_stage_attempts=attempts))
    return run,data,source


def layout():
    return dict(schema='room_layout_camera/v4',space_type='interior',room=dict(width=8,depth=6,height=3),
        openings=[dict(id='door',kind='door',wall='south',offset=5,width=1,bottom=0,height=2)],
        objects=[dict(id='bed',kind='bed',description='One worn bed',center=[1.5,3],size=[2,3,1],yaw=0,color='wood',base_z=0)],
        cameras=dict(front=dict(eye=[6,1,1.6],target=[3,3,1],fov=65),
            reverse=dict(eye=[4,5,1.6],target=[6,1,1],fov=65),side=dict(eye=[1,5,1.6],target=[6,5,1],fov=65)),
        design_note='Art-department coordinates, not fictional factual measurements.')


class Fake:
    def __init__(self):self.calls=[];self.mode='normal';self.hidden=False;self.extra=False;self.split=False
    def binding(self):return dict(provider='fixture_protocol_only',model='not_a_real_model')
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages))
        data=json.loads(messages[1]['content'])['materials']
        if self.mode=='unknown':raise TimeoutError('QA transport ended without response')
        if self.mode=='malformed':return dict(text='not json',native=dict(fixture=True),completion_known=True)
        if 'place' in data:
            result=dict(layout_design='A modest worn room, fixed door and furniture.',front_prompt='Empty worn room, steady wide view.',
                source_ids=[data['scenes'][0]['heading']['id']],spatial_layout=layout(),
                room_appearance={k:values[0] for k,values in flow.STATIC_APPEARANCE.items()})
            for item in result['spatial_layout']['objects']:item['permanent_role']=flow.STATIC_ROLES[item['kind']]
            if self.mode=='overlap':result['spatial_layout']['objects'].append(dict(result['spatial_layout']['objects'][0],id='duplicated_bed'))
            if self.mode=='missing_z':result['spatial_layout']['objects'][0].pop('base_z')
            if self.mode=='above_ceiling':result['spatial_layout']['objects'][0]['base_z']=3
            if self.mode=='free_prop_injection':
                result['layout_design']='A room with an iodine bottle and dinner bowls ready.'
                result['front_prompt']='Draw medicine, food and a shopping bag.'
                result['spatial_layout']['objects'][0]['id']='medicine_bottle'
                result['spatial_layout']['objects'][0]['description']='A bed with food plates, iodine bottle and bowls.'
        elif 'window' in data:
            cast=[] if self.hidden else ['a']
            if self.extra:cast=['b']
            w=data['window']
            result=dict(shot=dict(id=w['id'],place_id=data['scene_mapping']['place_ids'][0],visible_cast=cast,
                place_view='front',visual_prompt='Alice looks toward the camera in this same room.',source_ids=[w['source_units'][0]['id']],
                requires_finer_split=self.split))
        else:
            result=dict(places=[dict(id='bedroom',name='Old bedroom',space_type='interior',scene_ids=['S1'],description='One old bedroom.',
                source_ids=[data['scenes'][0]['heading']['id']]),
                dict(id='kitchen',name='Kitchen',space_type='interior',scene_ids=['S2','S3'],description='Same kitchen morning and evening.',
                    source_ids=[data['scenes'][1]['heading']['id']])],
                scenes=[dict(id=s['id'],place_ids=['bedroom' if s['id']=='S1' else 'kitchen'],
                    scene_present_cast=['a'] if s['id']=='S1' else ['a','b'],source_ids=[s['heading']['id']]) for s in data['scenes']],
                context_only_places=[])
            if self.mode=='bad_source_id':result['places'][0]['source_ids']=['nonexistent_record']
            if self.mode=='missing_scene':result['scenes'].pop()
        return dict(text=json.dumps(result),native=dict(fixture=True),metadata=dict(finish_reason='stop'),completion_known=True)


def test_full_separated_plan_reuses_kitchen_preserves_audio_and_never_claims_text_acceptance(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();result=flow.plan(run,client=fake)
    assert result['state']['status']=='visual_packet_ready'
    packet=flow.sample_packet(run);assert packet['text_contract']==flow.VERSION
    assert 'accepted_sha256' not in packet and packet['production_approved'] is False
    assert len(packet['places'])==2 and [s['id'] for s in packet['shots']]==['F0001','F0002']
    assert packet['shots'][0]['audio'][0]['text']=='hello' and packet['shots'][0]['audio'][0]['speaker']=='a'
    assert packet['shots'][0]['audio'][0]['mode']=='onscreen'
    for s in packet['shots']:assert source.read_text(encoding='utf-8')[s['audio'][0]['source_start']:s['audio'][0]['source_end']]=='hello'
    assert all(c['required_views']==['front'] for c in packet['characters'])
    assert all(p['design_version'].startswith('environment_') and 'spatial_layout' in p for p in packet['places'])
    # one physical-location pass, two geometry passes, three staging passes.
    assert len(fake.calls)==6
    first=json.loads(fake.calls[0][1]['content'])['materials'];assert 'windows' not in first
    for call in fake.calls[1:3]:assert 'place' in json.loads(call[1]['content'])['materials']
    for call in fake.calls[3:]:assert 'audio' not in json.loads(call[1]['content'])['materials'].get('scene_mapping',{})
    before=len(fake.calls);flow.plan(run,client=fake);assert len(fake.calls)==before


def test_source_offset_change_prevents_any_model(tmp_path):
    run,data,source=fixture(tmp_path);source.write_text(source.read_text(encoding='utf-8')+'changed',encoding='utf-8')
    fake=Fake()
    with pytest.raises(flow.RerunBlocked,match='source_changed'):flow.plan(run,client=fake)
    assert fake.calls==[]


def test_coverage_unit_not_equal_source_rejected_during_prepare(tmp_path):
    run,data,source=fixture(tmp_path);p=flow.status(run)['plan'];data['segments'][0]['units'][0]['text']='Changed'
    write(p['coverage']['path'],data)
    with pytest.raises(flow.RerunBlocked,match='unit_source_offset_changed'):
        flow.prepare(run.parent/'another',source,p['coverage']['path'],p['cast_root'],'fixture_book',user_statement='QA')


def test_unknown_original_call_not_replayed_by_another_client(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();fake.mode='unknown'
    with pytest.raises(flow.RerunBlocked,match='unknown_planning_call'):flow.plan(run,client=fake)
    assert len(fake.calls)==1
    second=Fake()
    with pytest.raises(flow.RerunBlocked,match='unknown_planning_call'):flow.plan(run,client=second)
    assert second.calls==[] and list((run/'calls/locations').glob('attempt_00/CLAIM.json'))


@pytest.mark.parametrize('finish',['length','stop'])
def test_native_client_known_terminal_contract_failure_can_repair_once(tmp_path,finish):
    from src.content_factory.creative_workflow_roles import RoleResponseError
    run,data,source=fixture(tmp_path)
    class NativeRejectedOnce(Fake):
        def call(self,messages,schema):
            if not self.calls:
                self.calls.append(deepcopy(messages))
                raise RoleResponseError('native contract rejected',dict(finish_reason=finish),response_text='partial',
                    response_payload=dict(id='native_completed_id',choices=[dict(finish_reason=finish,message=dict(content='partial'))]))
            return super().call(messages,schema)
    fake=NativeRejectedOnce();flow.plan(run,client=fake,phase='locations')
    assert len(fake.calls)==2 and flow.status(run)['state']['status']=='locations_ready'
    original=flow.files.read(run/'calls/locations/attempt_00/NATIVE.json')
    assert original['completion_known'] is True and original['native']['id']=='native_completed_id'
    assert (run/'calls/locations/attempt_00/VALIDATION_ERROR.json').exists()


def test_native_client_payload_without_terminal_proof_remains_unknown(tmp_path):
    from src.content_factory.creative_workflow_roles import RoleResponseError
    run,data,source=fixture(tmp_path)
    class Interrupted(Fake):
        def call(self,messages,schema):
            self.calls.append(deepcopy(messages))
            raise RoleResponseError('unfinished response',dict(finish_reason=''),response_text='partial',
                response_payload=dict(id='maybe_id',choices=[dict(finish_reason=None,message=dict(content='partial'))]))
    fake=Interrupted()
    with pytest.raises(flow.RerunBlocked,match='unknown_planning_call'):flow.plan(run,client=fake)
    second=Fake()
    with pytest.raises(flow.RerunBlocked,match='unknown_planning_call'):flow.plan(run,client=second)
    assert len(fake.calls)==1 and not second.calls and not (run/'calls/locations/attempt_00/NATIVE.json').exists()


@pytest.mark.parametrize('mode',['bad_source_id','missing_scene','malformed'])
def test_known_invalid_outputs_have_bounded_attempts_and_preserve_native(tmp_path,mode):
    run,data,source=fixture(tmp_path);fake=Fake();fake.mode=mode
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):flow.plan(run,client=fake)
    assert len(fake.calls)==2 and len(list((run/'calls/locations').glob('*/NATIVE.json')))==2
    with pytest.raises(flow.RerunBlocked):flow.plan(run,client=fake)
    assert len(fake.calls)==2


def test_geometry_overlap_blocks_before_staging_and_keeps_source(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();flow.plan(run,client=fake,phase='locations');fake.mode='overlap'
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):flow.plan(run,client=fake,phase='designs')
    assert not (run/'STAGING.json').exists() and not (run/'PLACES.json').exists()
    assert source.read_text(encoding='utf-8').startswith('Existing fixed screenplay.')


def test_hidden_onscreen_actor_fails_and_voiceover_never_forces_visibility(tmp_path):
    run,data,source=fixture(tmp_path,attempts=1);fake=Fake();fake.hidden=True
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):flow.plan(run,client=fake)
    other,data,source=fixture(tmp_path/'voice',attempts=1,vo=True);fake=Fake();fake.hidden=True
    flow.plan(other,client=fake);packet=flow._load_artifact(other,'PACKET_ALL.json')
    assert all(s['visible_cast']==[] and s['audio'][0]['mode']=='voiceover' for s in packet['shots'])


def test_person_not_in_scene_cannot_become_visible(tmp_path):
    run,data,source=fixture(tmp_path,attempts=1);fake=Fake();fake.extra=True
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):flow.plan(run,client=fake)


def test_requires_split_stays_in_plan_but_cannot_be_sample_dispatched(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();fake.hidden=True;fake.split=True
    flow.plan(run,client=fake)
    assert flow.status(run)['state']['blocked_shots']==['F0001','F0002','F0003']
    with pytest.raises(flow.RerunBlocked,match='requires_split'):flow.sample_packet(run,shot_ids=['F0001'])


def test_artifact_tampering_cannot_silently_replace_physical_place(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();flow.plan(run,client=fake,phase='locations')
    locations=flow.files.read(run/'LOCATIONS.json');locations['places'][0]['name']='Invented room';write(run/'LOCATIONS.json',locations)
    with pytest.raises(flow.RerunBlocked,match='visual_artifact_binding_changed'):flow.plan(run,client=fake)
    assert len(fake.calls)==1


def test_source_character_manifest_changes_block_planning(tmp_path):
    run,data,source=fixture(tmp_path);p=flow.status(run)['plan'];final=Path(p['cast_root'])/'FINAL_MAP.json'
    final.write_text('{}',encoding='utf-8');fake=Fake()
    with pytest.raises(flow.RerunBlocked,match='cast_input_changed'):flow.plan(run,client=fake)
    assert not fake.calls


def test_native_padding_not_requested_as_overlong_speech_clip(tmp_path):
    run,data,source=fixture(tmp_path,native_seconds=362/24);flow.plan(run,client=Fake())
    s=flow.sample_packet(run)['shots'][0]
    assert s['end']-s['start']==15 and s['legacy_native_seconds']==362/24 and s['audio'][0]['text']=='hello'


def test_legacy_target_scope_and_empty_authorization_rejected(tmp_path):
    run,data,source=fixture(tmp_path);p=flow.status(run)['plan']
    with pytest.raises(flow.RerunBlocked,match='namespace'):flow.prepare(tmp_path/'old_H3',source,p['coverage']['path'],p['cast_root'],'book',user_statement='QA')
    with pytest.raises(flow.RerunBlocked,match='authorization'):flow.prepare(run.parent/'other',source,p['coverage']['path'],p['cast_root'],'book',user_statement='')


def test_status_cli_is_readonly_and_does_not_create_clients(tmp_path):
    run,data,source=fixture(tmp_path)
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=subprocess.run([sys.executable,str(flow.PROJECT/'scripts/run_visual_novel_rerun_v4.py'),'status','--run',str(run)],
        cwd=flow.PROJECT,capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0 and json.loads(result.stdout)['state']['status']=='prepared'
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_source_ids_hydrate_exact_markdown_and_audio_is_not_location_input():
    heading='### Scene one bedroom'
    metadata='**地点**：旧卧室**在场人物**：苏墨；孩子不在场\n**入场状态**：苏墨独自躺着。'
    voice='**【旁白】** 他回忆现代写字楼，之后过马路被车撞。'
    action='——外景插入：街边小摊，他把面包放进袋子，拎回家。'
    text=heading+'\n'+metadata+'\n'+voice+'\n'+action
    def block(bid,body,sounds=None):
        start=text.index(body)
        return dict(id=bid,text=body,start=start,end=start+len(body),sound_spans=sounds or [])
    scene=dict(id='S1',chapter=1,heading=heading,metadata=[dict(text=metadata,start=text.index(metadata),end=text.index(metadata)+len(metadata))],
        blocks=[block('S1_P1',voice,[dict(start=9,end=len(voice),text=voice[9:],channel='旁白')]),block('S1_P2',action)])
    scenes,index=flow._scene_materials(dict(scenes=[scene],segments=[]),text);s=scenes[0]
    model=flow._planner_scene(s);encoded=json.dumps(model,ensure_ascii=False)
    assert '写字楼' not in encoded and '过马路' not in encoded and '街边小摊' in encoded
    assert model['context_only']['audio_only_block_ids']==['S1_P1']
    cast=next(m for m in s['initial_metadata'] if m['kind']=='metadata_cast')
    row=dict(source_ids=[cast['id']]);flow._bind_evidence(row,index,{cast['id']},'scene')
    assert row['evidence']==['**在场人物**：苏墨；孩子不在场\n']
    for record in index.values():
        assert text[record['start']:record['end']]==record['text']
        assert hashlib.sha256(record['text'].encode()).hexdigest()==record['sha256']
    with pytest.raises(flow.RerunBlocked,match='source_id_outside_scope:physical_place:S1_P1'):
        flow._bind_evidence(dict(source_ids=['S1_P1']),index,set(s['physical_source_ids']),'physical_place')
    # Initial cast/location mention cannot be used as physical asset evidence.
    with pytest.raises(flow.RerunBlocked,match='source_id_outside_scope'):
        flow._bind_evidence(dict(source_ids=[cast['id']]),index,set(s['physical_source_ids']),'place')


def test_source_ids_cannot_cross_scene_or_window_and_error_names_record(tmp_path):
    run,data,source=fixture(tmp_path,attempts=1)
    class WrongScene(Fake):
        def call(self,messages,schema):
            raw=super().call(messages,schema);candidate=json.loads(raw['text'])
            if 'places' in candidate:candidate['places'][0]['source_ids']=['S2_H001']
            raw['text']=json.dumps(candidate);return raw
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):flow.plan(run,client=WrongScene())
    error=flow.files.read(run/'calls/locations/attempt_00/VALIDATION_ERROR.json')['error']['reason']
    assert error=='source_id_outside_scope:places[bedroom]:S2_H001'
    other,_,_=fixture(tmp_path/'other',attempts=1)
    class WrongWindow(Fake):
        def call(self,messages,schema):
            raw=super().call(messages,schema);candidate=json.loads(raw['text'])
            if 'shot' in candidate:candidate['shot']['source_ids']=['S2_P1_U1']
            raw['text']=json.dumps(candidate);return raw
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):flow.plan(other,client=WrongWindow())
    error=flow.files.read(other/'calls/stage_F0001/attempt_00/VALIDATION_ERROR.json')['error']['reason']
    assert error=='source_id_outside_scope:shots[F0001]:S2_P1_U1'


def test_legacy_revision_is_read_only_and_cannot_consume_new_attempts(tmp_path):
    run,data,source=fixture(tmp_path);p=flow.files.read(run/'PLAN.json');p['schema']='legacy_source_bound_visual/v4';write(run/'PLAN.json',p)
    assert flow.status(run)['plan']['schema']=='legacy_source_bound_visual/v4'
    before={str(f):f.read_bytes() for f in run.rglob('*') if f.is_file()};fake=Fake()
    with pytest.raises(flow.RerunBlocked,match='new_revision_requires_new_visual_run'):flow.plan(run,client=fake)
    assert not fake.calls and before=={str(f):f.read_bytes() for f in run.rglob('*') if f.is_file()}


def test_selected_places_are_frozen_and_unselected_scenes_stop_before_design_calls(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();flow.plan(run,client=fake,phase='designs',place_ids=['bedroom'])
    assert len(fake.calls)==2
    assert [p['id'] for p in flow._load_artifact(run,'PLACES.json')]==['bedroom']
    assert flow._load_artifact(run,'DESIGN_SELECTION.json')==dict(place_ids=['bedroom'])
    flow.plan(run,client=fake,phase='staging',scene_ids=['S1']);assert len(fake.calls)==3
    packet=flow.sample_packet(run);assert [p['id'] for p in packet['places']]==['bedroom']
    before=len(fake.calls)
    with pytest.raises(flow.RerunBlocked,match='scene_requires_unselected_design_places:S2:kitchen'):
        flow.plan(run,client=fake,phase='staging',scene_ids=['S2'])
    with pytest.raises(flow.RerunBlocked,match='frozen_design_selection_changed'):
        flow.plan(run,client=fake,phase='designs',place_ids=['bedroom','kitchen'])
    assert len(fake.calls)==before


@pytest.mark.parametrize('mode',['missing_z','above_ceiling'])
def test_new_design_requires_explicit_object_height_and_3d_bounds(tmp_path,mode):
    run,data,source=fixture(tmp_path,attempts=1);fake=Fake();flow.plan(run,client=fake,phase='locations');fake.mode=mode
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):
        flow.plan(run,client=fake,phase='designs',place_ids=['bedroom'])
    assert not (run/'PLACES.json').exists()
    request=flow.files.read(run/'calls/design_bedroom/attempt_00/REQUEST.json')
    assert 'base_z' in request['response_schema']['properties']['spatial_layout']['properties']['objects']['items']['required']


def _new_import_target(run,source):
    p=flow.status(run)['plan'];target=run.parent/'new_revision'
    flow.prepare(target,source,p['coverage']['path'],p['cast_root'],p['book_id'],user_statement='Authorized new visual QA revision.',config=p['config'])
    return target


def test_import_locations_revalidates_source_ids_and_binds_origin_without_model_calls(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();flow.plan(run,client=fake,phase='locations')
    target=_new_import_target(run,source);before={str(f):f.read_bytes() for f in run.rglob('*') if f.is_file()}
    flow.import_locations(target,run)
    assert before=={str(f):f.read_bytes() for f in run.rglob('*') if f.is_file()}
    assert not (target/'calls').exists()
    proof=flow._load_artifact(target,'LOCATIONS_IMPORT.json')
    assert proof['new_model_call'] is False and proof['origin_locations']['sha256']==flow.files.file_sha(run/'LOCATIONS.json')
    assert flow._load_artifact(target,'LOCATIONS.json')==flow._load_artifact(run,'LOCATIONS.json')
    other=Fake();flow.plan(target,client=other,phase='designs',place_ids=['bedroom'])
    assert len(other.calls)==1 and not (target/'calls/locations').exists()


def test_import_locations_rejects_incompatible_config_and_validly_bound_wrong_scene_evidence(tmp_path):
    run,data,source=fixture(tmp_path);flow.plan(run,client=Fake(),phase='locations');target=_new_import_target(run,source)
    p=flow.files.read(target/'PLAN.json');p['config']['max_tokens']=12000;write(target/'PLAN.json',p)
    with pytest.raises(flow.RerunBlocked,match='locations_import_incompatible:config'):flow.import_locations(target,run)
    assert not (target/'LOCATIONS.json').exists()
    p['config']['max_tokens']=16000;write(target/'PLAN.json',p)
    # This QA origin fixture has valid byte bindings but invalid source scope.
    candidate=flow._load_artifact(run,'LOCATIONS.json');candidate['places'][0]['source_ids']=['S2_H001']
    write(run/'LOCATIONS.json',candidate)
    binding=flow.files.read(run/'LOCATIONS.json.binding');binding['content_sha256']=flow.fingerprint(candidate);write(run/'LOCATIONS.json.binding',binding)
    with pytest.raises(flow.RerunBlocked,match='source_id_outside_scope:places'):flow.import_locations(target,run)
    assert not (target/'LOCATIONS.json').exists()


def test_static_compiler_discards_movable_props_hidden_in_free_model_fields(tmp_path):
    run,data,source=fixture(tmp_path);fake=Fake();fake.mode='free_prop_injection'
    flow.plan(run,client=fake,phase='designs',place_ids=['bedroom'])
    place=flow._load_artifact(run,'PLACES.json')[0]
    render_inputs=json.dumps({k:place[k] for k in ('front_prompt','layout_design','spatial_layout','view_prompts')})
    for value in ('iodine','medicine','food','bowls','shopping bag'):assert value not in render_inputs
    native=flow.files.read(run/'calls/design_bedroom/attempt_00/NATIVE.json')
    assert 'iodine bottle' in native['text'] and 'medicine_bottle' in native['text']
    assert place['static_compilation']['free_model_prose_used_for_generation'] is False
    assert place['background_contract']=='static_room_per_shot_props/v1'
    assert place['static_materials']=={k:values[0] for k,values in flow.STATIC_APPEARANCE.items()}
    assert place['spatial_layout']['objects'][0]['id']=='bed_01'
    request=flow.files.read(run/'calls/design_bedroom/attempt_00/REQUEST.json')
    materials=json.loads(request['messages'][1]['content'])['materials']
    assert 'description' not in materials['place']
    assert all('physical_actions' not in s and 'initial_metadata' not in s for s in materials['scenes'])
    item=request['response_schema']['properties']['spatial_layout']['properties']['objects']['items']
    assert 'other' not in item['properties']['kind']['enum']
    assert set(item['properties']['kind']['enum'])==set(flow.STATIC_ROLES)


def _split_fixture_first_scene(run,data,source):
    """Two actual source windows in one QA scene, with different allowed IDs."""
    first=data['segments'][0];unit=first['units'][0];old_end=unit['end'];old_sounds=deepcopy(unit['audio_items'])
    split=source.read_text(encoding='utf-8').index('Alice says',unit['start']);second=deepcopy(first)
    unit['end']=split;unit['text']=source.read_text(encoding='utf-8')[unit['start']:split]
    unit['sha256']=hashlib.sha256(unit['text'].encode()).hexdigest();unit['audio_items']=[]
    second['id']='F0004';other=second['units'][0];other['id']='S1_P1_U2';other['start']=split;other['end']=old_end
    other['text']=source.read_text(encoding='utf-8')[split:old_end];other['sha256']=hashlib.sha256(other['text'].encode()).hexdigest();other['audio_items']=old_sounds
    data['segments'].insert(1,second)
    p=flow.files.read(run/'PLAN.json');write(p['coverage']['path'],data);p['coverage']['sha256']=flow.files.file_sha(p['coverage']['path']);write(run/'PLAN.json',p)


def test_one_window_requests_and_explicit_shot_selection_never_send_future_windows(tmp_path):
    run,data,source=fixture(tmp_path);_split_fixture_first_scene(run,data,source);fake=Fake()
    flow.plan(run,client=fake,place_ids=['bedroom'],scene_ids=['S1'],shot_ids=['F0004'])
    assert len(fake.calls)==3 and not (run/'calls/stage_F0001').exists()
    assert flow._load_artifact(run,'SHOT_SELECTION.json')==dict(shot_ids=['F0004'])
    staged=flow._load_artifact(run,'STAGING.json');assert [s['id'] for s in staged]==['F0004']
    assert staged[0]['source_ids']==['S1_P1_U2'] and staged[0]['audio'][0]['text']=='hello'
    assert staged[0]['start']==8 and flow.status(run)['state']['completed_scenes']==[]
    request=flow.files.read(run/'calls/stage_F0004/attempt_00/REQUEST.json');materials=json.loads(request['messages'][1]['content'])['materials']
    assert 'windows' not in materials and materials['window']['id']=='F0004'
    assert materials['context_only']['previous_units'][0]['id']=='S1_P1_U1'
    assert 'physical_actions' not in materials['context_only']['scene']
    assert all('source_facts' not in p and 'design_source_ids' not in p for p in materials['places'])
    assert request['response_schema']['properties']['shot']['properties']['id']==dict(const='F0004')
    packet=flow.sample_packet(run);assert packet['visual_scope']==dict(scene_ids=['S1'],shot_ids=['F0004'])


def test_previous_window_id_is_context_only_and_cannot_be_used_as_current_evidence(tmp_path):
    run,data,source=fixture(tmp_path,attempts=1);_split_fixture_first_scene(run,data,source)
    class PreviousAsCurrent(Fake):
        def call(self,messages,schema):
            raw=super().call(messages,schema);candidate=json.loads(raw['text'])
            if 'shot' in candidate:candidate['shot']['source_ids']=['S1_P1_U1']
            raw['text']=json.dumps(candidate);return raw
    with pytest.raises(flow.RerunBlocked,match='known_planning_validation_failed'):
        flow.plan(run,client=PreviousAsCurrent(),place_ids=['bedroom'],scene_ids=['S1'],shot_ids=['F0004'])
    error=flow.files.read(run/'calls/stage_F0004/attempt_00/VALIDATION_ERROR.json')['error']['reason']
    assert error=='source_id_outside_scope:shots[F0004]:S1_P1_U1'
