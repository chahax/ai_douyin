"""CPU-only fixtures. Synthetic native files are never presented as real media."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]
SOURCE_RUN=ROOT/'data/video_generation/h3_universal_direction_minute_20261114_v1'
spec=importlib.util.spec_from_file_location('same_scene_writer',ROOT/'scripts/materialize_h3_same_scene_inputs.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
f=w.flow


def put(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return f.bind(path)


def synthetic_native(run,sid):
    nr=run/'visual_h3_v3'/(run.name+'_'+sid);folder=nr/'shots'/sid;folder.mkdir(parents=True)
    output=run/'synthetic_outputs'/sid;output.mkdir(parents=True)
    graph={'condition':{'inputs':{'prompt':'synthetic CPU fixture, never generated video'}},'124':{'inputs':{'denoise':1}},'130':{'inputs':{'fps':24}}}
    row=dict(id=sid,scope=sid,graph_sha256=f.digest(graph),timing={'native_frames':362})
    plan=dict(schema='synthetic_native_fixture/v1',shots=[row],config={'output_root':str(output.parent)},synthetic_fixture=True)
    put(nr/'PLAN.json',plan);put(folder/'workflow_api.json',graph)
    files={};outputs={}
    for role in ('video','audio','first','last'):
        path=output/(role+('.png' if role in ('first','last') else '.test_fixture'))
        if role in ('first','last'):Image.new('RGB',(8,8),'red' if role=='first' else 'blue').save(path)
        else:path.write_bytes(b'synthetic non-media CPU fixture')
        saved=folder/'artifacts'/path.name;saved.parent.mkdir(exist_ok=True);saved.write_bytes(path.read_bytes())
        files[role]=dict(**f.bind(saved),source_path=str(path))
        outputs['save_'+role]={('audio' if role=='audio' else 'images'):[dict(filename=path.name,subfolder=sid,type='output')]}
    pid='synthetic_fresh_'+sid
    result=dict(shot_id=sid,prompt_id=pid,technical_status='technical_saved',publication=False,production_approved=False,
        graph_sha256=f.digest(graph),files=files,synthetic_fixture=True)
    result_binding=put(folder/'RESULT.json',result)
    put(folder/'STATE.json',dict(id=sid,prompt_id=pid,status='technical_saved',plan_sha256=f.digest(plan),synthetic_fixture=True))
    put(folder/'REQUEST.json',dict(prompt=graph));put(folder/'RESPONSE.json',dict(prompt_id=pid))
    casted=deepcopy(graph);casted['124']['inputs']['denoise']=1.0;casted['130']['inputs']['fps']=24.0
    put(folder/'HISTORY.json',{pid:dict(prompt=[1,pid,casted],status=dict(completed=True,status_str='success'),outputs=outputs)})
    return result_binding,{k:files['last'][k] for k in ('path','sha256')}


@pytest.fixture
def setup(tmp_path):
    run=tmp_path/'synthetic_run';run.mkdir()
    original=f.read(SOURCE_RUN/'ORIGINALS.json');design=f.read(SOURCE_RUN/'inputs/SOURCE_CATALOG.json')
    rows=[]
    for sid in original['source_cases']:
        folder=run/'segments'/sid;folder.mkdir(parents=True)
        series_case=put(folder/'SOURCE_CASE.json',f.read(SOURCE_RUN/'segments'/sid/'SOURCE_CASE.json'))
        runtime=put(folder/'runtime_source/SOURCE_CASE.json',f._bound(original['source_cases'][sid])) if sid in ('S03','S04') else series_case
        original['source_cases'][sid]=runtime;design['segments'][sid]['runtime_source_origin_copy']=runtime
        design['segments'][sid]['series_plan_source']=series_case
        rows.append(dict(shot_id=sid,source_case=series_case,native_run=str(run/'visual_h3_v3'/(run.name+'_'+sid))))
        if sid in ('S03','S04'):
            state=f.read(SOURCE_RUN/'segments'/sid/'STATE_PLAN_TEMPLATE.json');state['source_origin']=runtime
            state_binding=put(folder/'STATE_PLAN_TEMPLATE.json',state)
            inp=f.read(SOURCE_RUN/'segments'/sid/'INPUT_SPEC_TEMPLATE.json')
            inp.update(source_case=runtime,state_plan_template=state_binding,expected_predecessor_run=str(run))
            put(folder/'INPUT_SPEC_TEMPLATE.json',inp)
    design['series_plan']=put(run/'PLAN.json',dict(schema='synthetic_series_plan/v1',sources=rows))
    design['run']=str(run);put(run/'inputs/SOURCE_CATALOG.json',design);put(run/'ORIGINALS.json',original)

    def make(sid='S03'):
        prev='S02' if sid=='S03' else 'S03';result,image=synthetic_native(run,prev)
        old=ROOT/'data/video_generation/h3_contact_repair_s04_20261114_v1/inputs'
        states=deepcopy(f.read(old/'STATE_PLAN.json')['initial']);cast=list(states)
        review=dict(schema='synthetic_actual_guide_review/v1',guide_image=image,predecessor_result=result,
            completion_known=True,outcome_unknown=False,reviewed_by='CPU_SYNTHETIC_FIXTURE_NOT_A_REAL_VISUAL_REVIEW',
            evidence=['Synthetic unit fixture; no actual video/model/media generated.'],usable_for_continuation=True,
            observed_actor_count=len(cast),unexpected_actor_ids=[],guide_visible_actor_ids=cast,
            screen_identity_map={c:'synthetic '+c for c in cast},world_actor_state={c:'synthetic '+c for c in cast})
        if sid=='S04':
            cp=f.read(old/'CONTACT_PLAN.json');review['observed_contacts']=[w.contact._observation(c) for c in cp['initial_contacts']]
        envelope=dict(schema=w.INITIAL_STATES,predecessor_result=result,guide_image=image,states=states,
            observations={c:dict(posture='occluded' if states[c]['posture']=='unknown' else 'visible',
                evidence='Synthetic actual-observation contract; not inferred from portraits.') for c in cast})
        review_binding=put(run/'observations'/sid/'REVIEW.json',review);state_binding=put(run/'observations'/sid/'STATES.json',envelope)
        return dict(run=run,shot_id=sid,predecessor_binding=result,review_binding=review_binding,
            initial_states_binding=state_binding,output_dir=run/'segments'/sid/'materialized_test')
    return run,make


def test_missing_future_result_never_prepares_or_writes_a_future_package(setup,monkeypatch):
    run,_=setup;path=run/'visual_h3_v3'/(run.name+'_S02')/'shots/S02/RESULT.json'
    monkeypatch.setattr(f,'prepare',lambda *a,**k:pytest.fail('future input must not prepare'))
    out=run/'segments/S03/not_yet'
    result=w.materialize(run,'S03',dict(path=str(path),sha256='0'*64),{}, {},out)
    assert result['status']=='awaiting_actual_saved_predecessor' and not out.exists()


def test_real_templates_materialize_complete_source_action_flow_cpu_with_unknowns_preserved(setup,monkeypatch):
    _,make=setup;args=make()
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('writer cannot execute media or models'))
    monkeypatch.setattr(socket,'socket',lambda *a,**k:pytest.fail('writer cannot access network'))
    before=f.bind(args['run']/'ORIGINALS.json');result=w.materialize(**args)
    assert result['status']=='same_scene_input_materialized' and result['validation']['status']=='offline_draft_verified'
    state=f._bound(result['state_plan']);template=f.read(args['run']/'segments/S03/STATE_PLAN_TEMPLATE.json')
    assert state['initial']['ye_dong']['posture']=='unknown'
    assert state['source_actions']==template['source_actions'] and result['contact_plan'] is None
    assert state['initial']['ye_yaner']['held_items']==['cotton_swab']
    assert all(r['asserted_states']['ye_dong']['posture']=='unknown' for r in state['beats'])
    assert state['beats'][0]['asserted_states']['ye_xijue']['gaze']=='身旁的哥哥姐姐'
    assert f.bind(args['run']/'ORIGINALS.json')==before and result['physical_staging_performed'] is False
    assert w.materialize(**args)['receipt']==result['receipt']


def test_wrong_run_or_nonimmediate_result_is_rejected_before_prepare(setup,monkeypatch):
    run,make=setup;args=make();other,image=synthetic_native(run,'S01');args['predecessor_binding']=other
    monkeypatch.setattr(f,'prepare',lambda *a,**k:pytest.fail('wrong predecessor must not prepare'))
    with pytest.raises(w.MaterializationError,match='immediate_predecessor'):w.materialize(**args)
    assert not args['output_dir'].exists()


def test_review_cannot_bind_first_frame_as_actual_tail(setup):
    _,make=setup;args=make();result=f._bound(args['predecessor_binding']);review=f._bound(args['review_binding'])
    review['guide_image']={k:result['files']['first'][k] for k in ('path','sha256')}
    args['review_binding']=put(args['review_binding']['path'],review)
    with pytest.raises(w.MaterializationError,match='same_actual_tail_review'):w.materialize(**args)


def test_tampered_review_binding_is_not_treated_as_success(setup):
    _,make=setup;args=make();review=f._bound(args['review_binding']);review['evidence']=['tampered']
    put(args['review_binding']['path'],review)
    with pytest.raises(w.MaterializationError,match='bound_input_changed'):w.materialize(**args)


def test_occluded_posture_cannot_be_upgraded_from_a_standing_portrait(setup):
    _,make=setup;args=make();envelope=f._bound(args['initial_states_binding'])
    envelope['states']['ye_dong']['posture']='standing'
    args['initial_states_binding']=put(args['initial_states_binding']['path'],envelope)
    with pytest.raises(w.MaterializationError,match='posture_must_remain_unknown'):w.materialize(**args)


def test_known_posture_with_explicit_current_visible_evidence_is_allowed(setup):
    _,make=setup;args=make();envelope=f._bound(args['initial_states_binding'])
    envelope['states']['ye_dong']['posture']='standing';envelope['observations']['ye_dong']=dict(posture='visible',evidence='Synthetic current whole lower body visible.')
    args['initial_states_binding']=put(args['initial_states_binding']['path'],envelope)
    state=f._bound(w.materialize(**args)['state_plan'])
    assert state['initial']['ye_dong']['posture']=='standing'


def test_unseen_body_posture_does_not_erase_source_confirmed_held_tool(setup):
    _,make=setup;args=make();envelope=f._bound(args['initial_states_binding'])
    envelope['states']['ye_yaner']['posture']='unknown'
    envelope['observations']['ye_yaner']=dict(posture='occluded',evidence='Synthetic lower body hidden; tool carried from confirmed source/previous observation, not presumed absent.')
    args['initial_states_binding']=put(args['initial_states_binding']['path'],envelope)
    state=f._bound(w.materialize(**args)['state_plan'])
    assert state['initial']['ye_yaner']['posture']=='unknown' and state['initial']['ye_yaner']['held_items']==['cotton_swab']


def test_s04_contact_uses_only_new_basis_and_preserves_existing_correct_source(setup):
    _,make=setup;args=make('S04');before=f.bind(args['run']/'ORIGINALS.json');result=w.materialize(**args)
    state=f._bound(result['state_plan']);cp=f._bound(result['contact_plan']);spec=f._bound(result['input_spec'])
    old=f._bound(f.read(args['run']/'segments/S04/INPUT_SPEC_TEMPLATE.json')['historical_contact_plan_comparison_only'])
    assert cp['initial_basis']==state['initial_basis'] and cp['initial_basis']!=old['initial_basis']
    assert cp['initial_contacts']==old['initial_contacts'] and spec['source_case']==f.read(args['run']/'ORIGINALS.json')['source_cases']['S04']
    assert f.bind(args['run']/'ORIGINALS.json')==before
    resolution=f.read(args['output_dir']/'CONTACT_RESOLVED.json')
    assert resolution['status']=='ready' and resolution['changes']==[]


def test_needed_contact_camera_closure_returns_revision_notice_without_overwriting_catalog(setup,monkeypatch):
    run,make=setup;args=make('S04');source=f.read(run/'ORIGINALS.json')['source_cases']['S04'];case=f._bound(source)
    del case['shots'][0]['camera_beats'][1]['actors']['ye_xijue'];new=put(source['path'],case)
    catalog=f.read(run/'ORIGINALS.json');catalog['source_cases']['S04']=new;put(run/'ORIGINALS.json',catalog)
    design=f.read(run/'inputs/SOURCE_CATALOG.json');design['segments']['S04']['runtime_source_origin_copy']=new;put(run/'inputs/SOURCE_CATALOG.json',design)
    inp=f.read(run/'segments/S04/INPUT_SPEC_TEMPLATE.json');st=f._bound(inp['state_plan_template']);st['source_origin']=new
    inp.update(source_case=new,state_plan_template=put(inp['state_plan_template']['path'],st));put(run/'segments/S04/INPUT_SPEC_TEMPLATE.json',inp)
    before=f.bind(run/'ORIGINALS.json')
    monkeypatch.setattr(f,'prepare',lambda *a,**k:pytest.fail('unadopted camera revision cannot prepare'))
    result=w.materialize(**args)
    assert result['status']=='needs_explicit_source_catalog_revision' and result['changes']
    assert f.bind(run/'ORIGINALS.json')==before and not args['output_dir'].exists()


def test_damaged_original_or_unknown_state_never_materializes(setup):
    _,make=setup;args=make();result=f._bound(args['predecessor_binding']);Path(result['files']['video']['path']).write_bytes(b'damaged fixture')
    with pytest.raises(w.MaterializationError,match='bound_input_changed'):w.materialize(**args)


def test_result_left_by_unknown_state_is_not_replayed_as_known(setup):
    _,make=setup;args=make();folder=Path(args['predecessor_binding']['path']).parent;state=f.read(folder/'STATE.json');state['status']='outcome_unknown';put(folder/'STATE.json',state)
    with pytest.raises(w.MaterializationError,match='known_fresh_saved_predecessor'):w.materialize(**args)
