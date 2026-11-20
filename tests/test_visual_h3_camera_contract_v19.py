"""CPU-only director inheritance; no model, GPU, or production artifact writes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from src.content_factory import visual_h3_native_prompt_v15 as flow
from test_visual_h3_native_prompt_v15 import planner_fixture, source_fixture, entry, Client


class AdapterClient:
    def __init__(self,text):self.text=text;self.calls=[]
    def binding(self):return dict(provider='fixture',model='CPU-no-model',retries=0)
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages))
        constants={key:value['const'] for key,value in schema['properties'].items() if 'const' in value}
        return dict(text=json.dumps(dict(constants,motion_description=self.text)),completion_known=True,
            metadata=dict(finish_reason='stop'),native=dict(fixture=True))


def new_run(tmp_path,monkeypatch,shot_updates):
    old,scope=planner_fixture(tmp_path,monkeypatch,shot_updates=shot_updates)
    p=flow.status(old)['plan'];run=tmp_path/'visual_h3_native_prompts_v19'/'source_directed'
    # No camera_contract argument: the public prepare default must be v19.
    flow.prepare(run,p['full_parent']['path'],p['packet']['path'],Path(p['asset_plan']['path']).parent,
        user_statement='CPU source-directed fixture only.',official_guide_path=p['official_guide']['path'])
    return old,run,scope


@pytest.mark.parametrize('source,text',[
    ('The camera pushes in to a close-up of the adult face.',
     'One adult man rests on the bed and opens his eyes. The camera slowly pushes in to a close-up of his attentive face.'),
    ('Begin in medium view, then cut to the same adult hands.',
     'One adult man rests on the bed and gently moves his fingers. The shot cuts to a close view of the same adult hands.'),
    ('镜头缓慢推进，再切换为同一人物的表情特写。',
     'One adult man opens his eyes while resting. The camera pushes in slowly, then cuts to a close-up of the same face.')])
def test_planned_push_and_cut_are_inherited_not_globally_locked(tmp_path,monkeypatch,source,text):
    old,run,scope=new_run(tmp_path,monkeypatch,dict(visual_prompt=source))
    before=(old/'PLAN.json').read_bytes();client=AdapterClient(text);binding=flow.plan(run,client=client)
    value=flow.verify_plan(binding['path']);p=flow.status(run)['plan'];e=value['shots'][0]
    assert p['schema']==flow.VERSION_V19 and value['schema']==flow.SCHEMA_V19
    assert p['native_prompt_contract']==value['native_prompt_contract']==flow.CONTRACT_V19
    assert e['camera_contract']==flow.CAMERA_CONTRACT_V19
    assert e['camera_motion']=='inherit_source_shot_design'
    assert e['camera_design']['source_fields']['visual_prompt']==source
    system=client.calls[0][0]['content']
    assert 'not a director' in system and 'bound source_camera_design is the camera authority' in system
    assert 'locked-off tripod' not in system and 'never write' not in system
    compiled=flow.compile_for(scope['shots'][0],dict(native_frames=277,native_seconds=277/24),
        flow.load_for(scope,binding,scope['shots'][0]),'first')
    assert text in compiled and 'locked-off tripod' not in compiled and 'framing' not in compiled
    assert (old/'PLAN.json').read_bytes()==before and len(client.calls)==1


def test_camera_operation_not_designed_upstream_is_rejected():
    parent=source_fixture_mock();shot=parent['shots'][0]
    design=flow.source_camera_design(shot)
    candidate=dict(visible_cast=shot['visible_cast'],camera_contract=flow.CAMERA_CONTRACT_V19,
        camera_motion='inherit_source_shot_design',motion_description='The adult rests as the camera arcs around him, revealing his attentive face.')
    with pytest.raises(flow.NativePromptBlocked,match='not_in_upstream_design'):
        flow._check_motion(candidate,shot,{c['id']:c for c in parent['characters']},design)


def source_fixture_mock():
    return dict(characters=[dict(id='a',age_band='adult')],shots=[dict(id='F',visible_cast=['a'],
        audio=[],visual_prompt='The camera pushes in slowly toward the same adult face.')])


def test_explicit_fixed_source_stays_fixed_and_model_cannot_choose_free_camera(tmp_path,monkeypatch):
    _,run,scope=new_run(tmp_path,monkeypatch,dict(camera_motion='locked_off_tripod',visual_prompt='The fixed view shows the adult on the bed.'))
    design=flow.status(run)['plan']['camera_design'];assert design['mode']=='explicit_fixed'
    candidate=dict(visible_cast=['a'],camera_contract=flow.CAMERA_CONTRACT_V19,camera_motion='inherit_source_shot_design',
        motion_description='One adult man rests on his back. The camera pushes in toward his face as he opens both eyes.')
    with pytest.raises(flow.NativePromptBlocked,match='camera_transition'):
        flow._check_motion(candidate,scope['shots'][0],{'a':dict(age_band='adult')},design)
    candidate['camera_motion']='free_camera'
    with pytest.raises(ValidationError):flow._check_motion(candidate,scope['shots'][0],{'a':dict(age_band='adult')},design)
    client=AdapterClient('One adult man rests on his back, then opens both eyes and keeps an attentive gaze in the fixed source composition.')
    b=flow.plan(run,client=client);e=flow.load_for(scope,b,scope['shots'][0])
    compiled=flow.compile_for(scope['shots'][0],dict(native_frames=277,native_seconds=277/24),e,'first')
    assert 'explicitly fixed source camera remains fixed' in compiled


def test_explicit_design_is_bound_and_compiled_without_llm_camera_choice(tmp_path,monkeypatch):
    old,scope=planner_fixture(tmp_path,monkeypatch);p=flow.status(old)['plan']
    design_path=tmp_path/'UPSTREAM_CAMERA.json'
    doc=dict(schema='source_camera_design/v19',shot_sha256=flow.stage.fingerprint(scope['shots'][0]),
        instruction='The camera pulls back gradually to show the same adult and bed.',camera_motion='pull_back')
    flow.stage.files.write(design_path,doc);run=tmp_path/'visual_h3_native_prompts_v19'/'explicit_design'
    flow.prepare(run,p['full_parent']['path'],p['packet']['path'],Path(p['asset_plan']['path']).parent,
        user_statement='CPU explicit upstream camera design.',official_guide_path=p['official_guide']['path'],camera_design=flow._binding(design_path))
    client=AdapterClient('The adult remains on the bed and opens his eyes as the camera pulls back gradually in accordance with the source direction.')
    binding=flow.plan(run,client=client);value=flow.verify_plan(binding['path'])
    assert value['shots'][0]['camera_motion']=='pull_back'
    compiled=flow.compile_for(scope['shots'][0],dict(native_frames=277,native_seconds=277/24),flow.load_for(scope,binding,scope['shots'][0]),'first')
    assert doc['instruction'] in compiled and 'locked-off tripod' not in compiled
    flow.stage.files.write(design_path,dict(doc,instruction='Different direction.'))
    with pytest.raises(flow.NativePromptBlocked,match='artifact_changed'):flow.status(run)


def test_v19_keeps_source_audio_identity_and_unknown_no_replay(tmp_path,monkeypatch):
    _,run,scope=new_run(tmp_path,monkeypatch,dict(visual_prompt='The camera pushes in toward the same adult.'))
    class Unknown(AdapterClient):
        def call(self,messages,schema):self.calls.append(messages);raise TimeoutError('Missing terminal response')
    bad=Unknown('');fresh=AdapterClient('The adult rests with an attentive gaze as the camera pushes in slowly toward his face.')
    with pytest.raises(flow.NativePromptBlocked,match='unknown_native_motion'):flow.plan(run,client=bad)
    with pytest.raises(flow.NativePromptBlocked,match='unknown_native_motion'):flow.plan(run,client=fresh)
    assert len(bad.calls)==1 and not fresh.calls


def test_frozen_legacy_fixture_keeps_original_schema_and_camera_gate(tmp_path,monkeypatch):
    run,scope=planner_fixture(tmp_path,monkeypatch);client=Client();b=flow.plan(run,client=client)
    assert flow.verify_plan(b['path'])['schema']==flow.SCHEMA
    assert 'camera_contract' not in flow.status(run)['plan']
    e=flow.load_for(scope,b,scope['shots'][0]);assert 'camera_contract' not in e
    compiled=flow.compile_for(scope['shots'][0],dict(native_frames=277,native_seconds=277/24),e,'first')
    assert 'single locked-off tripod' in compiled and 'room throughout' in compiled


@pytest.mark.parametrize('legacy',[False,True])
def test_actual_handoff_prepare_and_load_consume_versioned_camera_without_gpu(tmp_path,monkeypatch,legacy):
    from src.content_factory import visual_h3_handoff_v3 as h
    old,scope=planner_fixture(tmp_path,monkeypatch,shot_updates=dict(visual_prompt='The camera pushes in then cuts to the same adult hands.'),real_image=True)
    p=flow.status(old)['plan'];asset=Path(p['asset_plan']['path']).parent
    asset_plan=flow.stage.files.read(asset/'PLAN.json');pause=tmp_path/'old_PAUSE.json';flow.stage.files.write(pause,dict(keep='unchanged'))
    asset_plan['config'].update(image_service=dict(service_url='http://127.0.0.1:65531',input_root=str(tmp_path/'input'),output_root=str(tmp_path/'output')),
        gpu_lock_root=str(tmp_path/'gpu'),protected_pause_path=str(pause))
    (tmp_path/'input').mkdir();(tmp_path/'output').mkdir()
    flow.stage.files.write(asset/'PLAN.json',asset_plan)
    source=scope['shots'][0];bound=dict(source,binding_sha256='CPU_source_bound_shot')
    monkeypatch.setattr(h,'validate_ready',lambda path:(dict(plan=flow.stage.files.read(asset/'PLAN.json')),flow.stage.files.read(asset/'H3_INPUT_READY.json'),dict(shots=[bound])))
    native_run=tmp_path/('visual_h3_native_prompts_v15' if legacy else 'visual_h3_native_prompts_v19')/'consumable'
    flow.prepare(native_run,p['full_parent']['path'],p['packet']['path'],asset,user_statement='CPU end-to-end interface only.',
        official_guide_path=p['official_guide']['path'],camera_contract=flow.LEGACY_CAMERA_CONTRACT if legacy else flow.CAMERA_CONTRACT_V19)
    text='One adult man rests on the bed with an attentive expression and natural breathing.'
    client=Client() if legacy else AdapterClient(text+' The camera pushes in slowly and then cuts to his hands as designed.')
    native_binding=flow.plan(native_run,client=client);wire=flow.CONTRACT if legacy else flow.CONTRACT_V19
    staged=[];monkeypatch.setattr(h.jobs,'stage_input',lambda *args:staged.append(args))
    # A production POST or any HTTP call fails this CPU test immediately.
    monkeypatch.setattr(h,'_http',lambda *args,**kwargs:pytest.fail('No media service call authorized in CPU test'))
    h3_run=tmp_path/h.PREFIX/'test_source_camera'
    result=h.prepare_from_ready(asset,h3_run,dict(native_prompt_contract=wire,native_prompt_plan=native_binding,
        runs_root=str(h3_run.parent),video_enabled=False,width=736,height=1312))
    _,loaded=h._load(h3_run);graph=flow.stage.files.read(h3_run/'shots/F0001/workflow_api.json');prompt=graph['condition']['inputs']['prompt']
    assert len(staged)==1 and graph['condition']['inputs']['length']==277 and 'last_frame' not in graph['condition']['inputs']
    assert loaded['config']['native_prompt_contract']==wire and loaded['config']['video_enabled'] is False
    assert ('locked-off tripod' in prompt)==legacy
    assert ('camera pushes in' in prompt)==(not legacy)
    for item in source['audio']:assert prompt.count('<d>[Chinese] '+item['text']+'</d>')==1
    wrong=dict(loaded['config'],native_prompt_contract=flow.CONTRACT_V19 if legacy else flow.CONTRACT)
    with pytest.raises(h.HandoffIntegrityError,match='wire_contract_mismatch'):
        h._native_prompt(scope,wrong,bound,h._timing(bound))
