"""Known length capacity amendment; fixture inference only, no GPU/model calls."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import psutil
import pytest

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_split_observation_v14 as split
from src.content_factory import visual_known_capacity_extension_v17 as c
from src.content_factory import visual_review_output_v17 as output


def write(path,value):p.write(path,value)
def native(text,*,completed=True):
    return dict(text=json.dumps(text),model='fixture-no-model',usage=dict(prompt_tokens=100,completion_tokens=30),
        completion_marker_present=completed,finish_reason='stop' if completed else 'max_tokens')


def test_incomplete_raw_is_saved_before_known_rejection_and_never_replayed(tmp_path):
    calls=[];payload=dict(prompt='fixture',images=[],schema={})
    def infer(_):
        calls.append(1)
        return output.native_response(text='{"checks":',token_ids=[1,2,3],prompt_tokens=10,eos_token_ids=[9],
            output_limit=3,model='fixture',seconds=.1,image_count=1,quantization='nf4')
    with pytest.raises(v.ReviewProtocolError,match='exhausted'):v._native_call(infer,payload,tmp_path,'MODEL')
    raw=p.read(tmp_path/'MODEL_INCOMPLETE_NATIVE.json')
    assert raw['request_sha256']==v.digest(payload)
    assert raw['native']['text']=='{"checks":' and raw['native']['usage']['completion_tokens']==3
    assert raw['native']['finish_reason']=='max_tokens' and raw['native']['completion_marker_present'] is False
    assert not (tmp_path/'MODEL_NATIVE.json').exists()
    before=(tmp_path/'MODEL_INCOMPLETE_NATIVE.json').read_bytes()
    with pytest.raises(v.ReviewProtocolError,match='exhausted'):v._native_call(infer,payload,tmp_path,'MODEL')
    assert calls==[1] and (tmp_path/'MODEL_INCOMPLETE_NATIVE.json').read_bytes()==before


@pytest.mark.parametrize('ids,finish',[([1,9],'stop'),([1],'missing_completion_marker'),([],'missing_completion_marker')])
def test_finish_diagnostic_does_not_invent_a_length_limit(ids,finish):
    args=dict(text='{}',token_ids=ids,prompt_tokens=10,eos_token_ids=[9],output_limit=10,
        model='fixture',seconds=.1,image_count=1,quantization='nf4')
    if finish=='stop':assert output.native_response(**args)['finish_reason']==finish
    else:
        with pytest.raises(v.ReviewProtocolError) as problem:output.native_response(**args)
        assert problem.value.native_response['finish_reason']==finish


@pytest.fixture
def case(tmp_path,monkeypatch):
    run=tmp_path/'run';run.mkdir();source=tmp_path/'source.md';source.write_text('Source-bound fixture only.')
    files=[]
    for name,color in [('target','gray'),('adult','blue'),('child','yellow'),('room','silver'),('guide','white')]:
        f=(run if name=='target' else tmp_path)/(name+'.png');Image.new('RGB',(64,80),color).save(f);files.append(f)
    target,adult,child,room,guide=files;sha=p.file_sha(target);binding='a'*64
    monkeypatch.setattr(c,'TARGET',sha)
    config=dict(provider='transformers_local',model_path=str(v.DEFAULT_MODEL),quantization='nf4',max_tokens=1800,timeout=900)
    inventory={k:0 for k in v.FURNITURE_KINDS};inventory.update(bed=1,table=1)
    expectation=dict(kind='place',expected_people=2,locate_rois=[],layout_object_inventory=inventory,furniture_observation_scope=split.SCOPE)
    prepared=[v._prepared(dict(target=target,reference=ref,expectation=dict(kind='character',locate_rois=[]))) for ref in (adult,child)]
    prepared.append(v._prepared(dict(target=target,reference=room,layout_guide=guide,expectation=expectation)))
    model=dict(available=True,model='fixture-no-model',provider='test_fixture')
    values=[dict(schema=v.VERSION,target_sha256=sha,reference_sha256=p.file_sha(ref),binding_sha256=v.digest(item),
        decision='accepted',completion_known=True,outcome_unknown=False,retryable=False,inference_dispatched=True,
        checks={k:True for k in v.CHARACTER_CHECKS},issues=[],evidence=['Protocol fixture.'],visual_evidence=['Protocol fixture.'])
        for item,ref in zip(prepared[:2],(adult,child))]
    values.append(v._unavailable(prepared[2],v.ReviewProtocolError(c.ERROR),model))
    room_model=dict(checks={k:True for k in v.PLACE_CHECKS},observations=dict(people_count=2,age_band='unknown',orientation='unknown',framing='environment'),
        issues=[],rois=dict.fromkeys(v.ROI_NAMES),reference_rois=dict.fromkeys(v.ROI_NAMES),evidence=['Fixture guide/source comparisons; not visual QA.'])
    objects={k:dict(count=0,regions=[],evidence='Not visible in the fixture.') for k in inventory}
    objects.update(bed=dict(count=1,regions=[[0,400,600,900]],evidence='One fixture bed.'),table=dict(count=1,regions=[[700,400,1000,900]],evidence='One fixture table.'))
    batchbinding=v.digest(dict(config=config,requests=prepared));request=dict(config=config,prepared=prepared,request_binding_sha256=batchbinding,model_binding=model)
    base=run/'first_frame_reviews'/binding/sha
    for attempt in (0,1):
        folder=base/str(attempt);write(folder/'REQUEST.json',request);write(folder/'CLAIM.json',dict(request_binding_sha256=batchbinding))
        write(folder/'RESULTS.json',dict(request_binding_sha256=batchbinding,results=values,results_sha256=v.digest(values)))
        write(folder/'WORKER_EXIT.json',dict(exited=True,code=0,at=100,request_binding_sha256=batchbinding))
        write(folder/'WORKER_RUNTIME.json',dict(pid=9999991,ppid=9999992,request_binding_sha256=batchbinding))
        write(folder/'WORKER_STATE.json',dict(stage='completed'))
        item=folder/'item_0002';tp=prepared[2]['target']
        for stem,payload,raw in [
            ('PEOPLE',split._payload(tp,split.PEOPLE_PROMPT,split.people_schema(),'target_people'),native(dict(people_count=2,evidence=['Two fixture people.']))),
            ('FURNITURE',split._payload(tp,split.FURNITURE_PROMPT,split.furniture_schema(inventory),'target_furniture'),native(dict(object_observations=objects)))]:
            write(item/(stem+'_REQUEST.json'),payload);write(item/(stem+'_CLAIM.json'),dict(request_sha256=v.digest(payload)));write(item/(stem+'_NATIVE.json'),raw)
        furniture=p.read(item/'FURNITURE_NATIVE.json');normalized,operations=split.normalize(v._parse_content(furniture['text']),inventory)
        write(item/'FURNITURE_NORMALIZATION.json',dict(schema=split.VERSION,raw_native_sha256=v.digest(furniture),normalized_sha256=v.digest(normalized),operations=operations))
        payload=dict(prompt='Frozen room MODEL fixture',images=[dict(role='target',binding=tp),dict(role='reference',binding=prepared[2]['reference']),dict(role='layout_guide',binding=prepared[2]['layout_guide'])],schema=v.observation_schema(expectation))
        write(item/'MODEL_REQUEST.json',payload);write(item/'MODEL_CLAIM.json',dict(request_sha256=v.digest(payload)))
        write(item/'MODEL_ERROR.json',dict(type='ReviewProtocolError',message=c.ERROR,completion_known=True))
    review=dict(schema=v.VERSION,target_sha256=sha,decision='unavailable',completion_known=True,outcome_unknown=False,
        checks={**{k:True for k in v.CHARACTER_CHECKS},**{k:None for k in v.PLACE_CHECKS}},subreviews=values,
        layout_guide_sha256=p.file_sha(guide),layout_object_inventory=inventory,furniture_observation_scope=split.SCOPE)
    entity=dict(id='room',design_version='v1')
    shot=dict(id=c.SHOT,binding_sha256=binding,references=[dict(entity_id='room',kind='place',view='front',design_version='v1')])
    plan=dict(config=dict(visual_review=config,max_review_attempts=2),packet=dict(source=dict(path=str(source),sha256=p.file_sha(source)),places=[entity]))
    frame=dict(path=str(target),sha256=sha,binding_sha256=binding,review_attempts=2,review=review,review_history=[deepcopy(review)],environment_guide=dict(sha256=p.file_sha(guide)))
    write(run/'PLAN.json',plan);write(run/'SHOT_BINDINGS.json',dict(shots=[shot]));write(run/'STATE.json',dict(status='blocked_first_frame_review',jobs={'image':dict(status='collected')},first_frames={c.SHOT:frame}))
    def no_process(pid):raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(c.psutil,'Process',no_process)
    monkeypatch.setattr(p,'_style_reference_for_entity',lambda *args:dict(fixture=True))
    from src.content_factory import visual_residence_style_v5 as residence
    target_style=dict(target=str(target),binding=dict(target_sha256=sha))
    monkeypatch.setattr(residence,'target_request',lambda *args:deepcopy(target_style))
    return dict(run=run,base=base,frame=frame,model=model,room_model=room_model,inventory=inventory,style_request=target_style,
        authorization=dict(scope=c.VERSION,authorized_by='root_task',reason='Explicit one-time fixture capacity amendment.'))


def install_execution(case,monkeypatch,*,room_false=False,unknown=False,style_accepted=True,length_failure=False):
    from contextlib import nullcontext
    calls=[];styles=[]
    monkeypatch.setattr(p,'gpu_access',lambda *args,**kwargs:nullcontext())
    def fake_dispatch(client,request,evidence_dir,backend):
        prepared=backend._prepared(request);folder=Path(evidence_dir);item=folder/'item_0000';item.mkdir(parents=True)
        binding=v.digest(dict(config=client.config,prepared=prepared))
        write(folder/'REQUEST.json',dict(config=client.config,prepared=[prepared],request_binding_sha256=binding,review_mode=backend.VERSION,model_binding=case['model']))
        write(folder/'CLAIM.json',dict(request_binding_sha256=binding))
        def infer(payload):
            calls.append(deepcopy(payload))
            if unknown:raise v.ReviewOutcomeUnknown('Fixture outcome unknown.')
            if length_failure:
                from src.content_factory.visual_room_contract_successor_v18 import LOOP
                return output.native_response(text=(LOOP+' ')*4,token_ids=[1]*4096,prompt_tokens=100,eos_token_ids=[9],
                    output_limit=4096,model='fixture',seconds=.1,image_count=3,quantization='nf4')
            answer=deepcopy(case['room_model'])
            if set(payload['schema']['properties'])=={'checks','evidence'}:
                answer=dict(checks=deepcopy(answer['checks']),evidence={k:'Bounded visible fixture evidence for '+k for k in answer['checks']})
            if room_false:answer['checks']['layout']=False
            return native(answer)
        try:result=backend._review_one(prepared,infer,case['model'],item)
        except (v.ReviewUnavailable,ValueError) as error:result=backend._unavailable(prepared,error,case['model'])
        write(folder/'RESULTS.json',dict(request_binding_sha256=binding,results=[result],results_sha256=v.digest([result])))
        write(folder/'WORKER_EXIT.json',dict(exited=True,code=0,at=100,request_binding_sha256=binding))
        write(folder/'WORKER_RUNTIME.json',dict(pid=9999993,ppid=9999994,request_binding_sha256=binding))
        write(folder/'WORKER_STATE.json',dict(stage='completed'))
        return result
    monkeypatch.setattr(c.dispatcher,'review',fake_dispatch)
    def style(*args,**kwargs):
        styles.append(1);folder=Path(args[5]);result=dict(decision='accepted' if style_accepted else 'needs_review',
            completion_known=True,outcome_unknown=False,target_sha256=case['frame']['sha256'],checks=dict(palette=style_accepted),visual_evidence=['Fixture style.'])
        write(folder/'RESULTS.json',dict(results=[result],results_sha256=v.digest([result])))
        write(folder/'item_0000/STYLE_NATIVE.json',native(dict(fixture='style')))
        return dict(request=case['style_request'],request_sha256=v.digest(case['style_request']),result=result)
    monkeypatch.setattr(p,'_residence_style_review',style)
    monkeypatch.setattr(p,'_verify_residence_style_receipt',lambda *args:None)
    monkeypatch.setattr(p,'_verify_first_frame_inventory',lambda *args:None)
    monkeypatch.setattr(p,'_verify_first_frame_generation',lambda *args:None)
    monkeypatch.setattr(p,'_review_layout_inventory',lambda *args:case['inventory'])
    return calls,styles


def test_prepare_keeps_original_two_attempts_and_changes_only_sidecar_capacity(case):
    run=case['run'];state=(run/'STATE.json').read_bytes();plan=(run/'PLAN.json').read_bytes()
    value=c.prepare_extension(run,authorization=case['authorization'])
    assert value['original_attempts']==2 and value['total_composition_attempts']==3 and value['review_config']['max_tokens']==4096
    assert value['additional_room_reviews']==value['additional_target_style_reviews']==1
    assert (run/'STATE.json').read_bytes()==state and (run/'PLAN.json').read_bytes()==plan
    assert not (c._sidecar(run)/'EXECUTION_CLAIM.json').exists()


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(outcome_unknown=True,completion_known=False),lambda d:d.update(error='Different error'),
    lambda d:d.update(decision='repair_required'),lambda d:d.update(target_sha256='0'*64),
])
def test_unknown_or_other_failures_do_not_receive_a_capacity_extension(case,mutation):
    f=case['base']/'1/RESULTS.json';value=p.read(f);mutation(value['results'][2]);value['results_sha256']=v.digest(value['results']);write(f,value)
    with pytest.raises(ValueError):c.prepare_extension(case['run'],authorization=case['authorization'])


def test_missing_blind_proof_does_not_get_recreated(case):
    f=case['base']/'1/item_0002/FURNITURE_NORMALIZATION.json';f.unlink()
    with pytest.raises(ValueError,match='missing_completed_blind'):c.prepare_extension(case['run'],authorization=case['authorization'])
    assert not f.exists()


def test_one_room_model_one_target_style_and_append_apply_preserves_original_limit(case,monkeypatch):
    run=case['run'];old_plan=(run/'PLAN.json').read_bytes();old_native=(case['base']/'1/item_0002/PEOPLE_NATIVE.json').read_bytes()
    calls,styles=install_execution(case,monkeypatch);c.prepare_extension(run,authorization=case['authorization'])
    result=c.execute_extension(run)
    assert len(calls)==len(styles)==1 and calls[0]['images'][0]['role']=='target'
    assert result['room']['decision']=='accepted' and (case['base']/'1/item_0002/PEOPLE_NATIVE.json').read_bytes()==old_native
    receipt=c.apply_extension(run);state=p.read(run/'STATE.json');frame=state['first_frames'][c.SHOT]
    assert receipt['total_composition_attempts']==frame['review_attempts']==3 and frame['original_review_attempts']==2
    assert frame['review']['decision']=='accepted' and len(frame['review_history'])==2
    assert frame['review']['layout_review']['subreviews'][:2]==p.read(case['base']/'1/RESULTS.json')['results'][:2]
    assert (run/'PLAN.json').read_bytes()==old_plan and p.read(run/'PLAN.json')['config']['max_review_attempts']==2
    assert not (run/'H3_INPUT_READY.json').exists() and receipt['production_approved'] is False
    assert c.apply_extension(run)==receipt and len(calls)==1


@pytest.mark.parametrize('unknown,room_false,style_accepted',[(True,False,True),(False,True,True),(False,False,False)])
def test_nonacceptance_never_applies_or_retries(case,monkeypatch,unknown,room_false,style_accepted):
    calls,styles=install_execution(case,monkeypatch,unknown=unknown,room_false=room_false,style_accepted=style_accepted)
    run=case['run'];before=(run/'STATE.json').read_bytes();c.prepare_extension(run,authorization=case['authorization'])
    first=c.execute_extension(run);assert c.execute_extension(run)==first and len(calls)==1
    with pytest.raises(ValueError,match='not_fully_accepted'):c.apply_extension(run)
    assert (run/'STATE.json').read_bytes()==before
    if unknown or room_false:assert not styles


def test_current_state_or_source_change_blocks_before_dispatch(case,monkeypatch):
    calls,_=install_execution(case,monkeypatch);c.prepare_extension(case['run'],authorization=case['authorization'])
    state=p.read(case['run']/'STATE.json');state['operator_note']='Changed';write(case['run']/'STATE.json',state)
    with pytest.raises(ValueError,match='CAS_changed'):c.execute_extension(case['run'])
    assert not calls


def test_successor_claim_without_result_is_not_replayed(case,monkeypatch):
    calls,_=install_execution(case,monkeypatch);c.prepare_extension(case['run'],authorization=case['authorization'])
    write(c._sidecar(case['run'])/'EXECUTION_CLAIM.json',dict(original='unknown retained'))
    with pytest.raises(v.ReviewOutcomeUnknown):c.execute_extension(case['run'])
    assert not calls


def test_unresolved_extra_native_claim_blocks_capacity_scope(case):
    folder=case['base']/'0/item_0002';write(folder/'EXTRA_REQUEST.json',dict(fixture=True))
    write(folder/'EXTRA_CLAIM.json',dict(at=1,request_sha256=v.digest(dict(fixture=True))))
    with pytest.raises(ValueError,match='prior_native_outcome_unknown'):
        c.prepare_extension(case['run'],authorization=case['authorization'])


def test_live_original_worker_is_never_assumed_exited(case,monkeypatch):
    class Alive:
        def create_time(self):return 1
    monkeypatch.setattr(c.psutil,'Process',lambda pid:Alive())
    with pytest.raises(ValueError,match='still_exists'):c.prepare_extension(case['run'],authorization=case['authorization'])


def test_extension_cannot_change_scope_or_be_used_without_explicit_authorization(case):
    auth=deepcopy(case['authorization']);auth['scope']='reset_review_budget'
    with pytest.raises(ValueError,match='authorization_required'):c.prepare_extension(case['run'],authorization=auth)


def test_primary_alltrue_does_not_override_excess_furniture(case,monkeypatch):
    for i in (0,1):
        item=case['base']/str(i)/'item_0002';raw=p.read(item/'FURNITURE_NATIVE.json');content=json.loads(raw['text'])
        content['object_observations']['bed'].update(count=2,regions=[[0,400,300,900],[310,400,600,900]])
        raw['text']=json.dumps(content);write(item/'FURNITURE_NATIVE.json',raw)
        normalized,operations=split.normalize(content,case['inventory'])
        write(item/'FURNITURE_NORMALIZATION.json',dict(schema=split.VERSION,raw_native_sha256=v.digest(raw),normalized_sha256=v.digest(normalized),operations=operations))
    calls,styles=install_execution(case,monkeypatch);c.prepare_extension(case['run'],authorization=case['authorization'])
    result=c.execute_extension(case['run'])
    assert result['room']['decision']=='repair_required' and result['room']['checks']['layout'] is False
    assert len(calls)==1 and not styles


def test_apply_requires_actual_new_native_completion_marker(case,monkeypatch):
    install_execution(case,monkeypatch);c.prepare_extension(case['run'],authorization=case['authorization']);c.execute_extension(case['run'])
    f=c._sidecar(case['run'])/'room_review/item_0000/MODEL_NATIVE.json';raw=p.read(f);raw['completion_marker_present']=False;write(f,raw)
    with pytest.raises(ValueError,match='completion_marker'):c.apply_extension(case['run'])


def test_original_source_is_not_rebound_to_a_changed_text(case):
    source=Path(p.read(case['run']/'PLAN.json')['packet']['source']['path']);source.write_text('Changed source.')
    with pytest.raises(ValueError,match='original_source_changed'):
        c.prepare_extension(case['run'],authorization=case['authorization'])


def test_original_native_claim_binding_is_required(case):
    f=case['base']/'0/item_0002/MODEL_CLAIM.json';value=p.read(f);value['request_sha256']='0'*64;write(f,value)
    with pytest.raises(ValueError,match='native_claim_changed'):
        c.prepare_extension(case['run'],authorization=case['authorization'])


def test_pause_before_execution_does_not_consume_successor(case,monkeypatch):
    calls,_=install_execution(case,monkeypatch);c.prepare_extension(case['run'],authorization=case['authorization'])
    write(case['run']/'PAUSE.json',dict(paused=True))
    with pytest.raises(ValueError,match='run_paused'):c.execute_extension(case['run'])
    assert not calls and not (c._sidecar(case['run'])/'EXECUTION_CLAIM.json').exists()


def test_legacy_review_needs_no_capacity_sidecar():
    assert c.verify_applied(dict(decision='accepted')) is None


@pytest.mark.parametrize('file',['room_review/item_0000/MODEL_NATIVE.json','target_style_review/item_0000/STYLE_NATIVE.json','RESULT.json','PLAN.json'])
def test_persistent_consumption_rejects_changed_sidecar_native_or_proof(case,monkeypatch,file):
    install_execution(case,monkeypatch);c.prepare_extension(case['run'],authorization=case['authorization'])
    c.execute_extension(case['run']);c.apply_extension(case['run'])
    review=p.read(case['run']/'STATE.json')['first_frames'][c.SHOT]['review']
    c.verify_applied(review)
    f=c._sidecar(case['run'])/file;f.write_bytes(f.read_bytes()+b' ')
    with pytest.raises(ValueError,match='evidence_changed'):c.verify_applied(review)


@pytest.mark.parametrize('kind',['capacity_extension','original_room_binding_sha256'])
def test_missing_top_level_proof_cannot_downgrade_a_v17_room_to_legacy(kind):
    room={'capacity_extension':dict(schema=c.VERSION)} if kind=='capacity_extension' else dict(original_room_binding_sha256='a'*64)
    with pytest.raises(ValueError,match='persistent_proof_required'):c.verify_applied(dict(subreviews=[room]))


def test_pipeline_and_h3_inventory_entry_cannot_skip_capacity_marker_validation():
    review=dict(subreviews=[dict(original_room_binding_sha256='a'*64)])
    with pytest.raises(ValueError,match='persistent_proof_required'):
        p._verify_first_frame_inventory(dict(config={}),{},review)


def upgrade_for_handoff(case):
    from src.content_factory import visual_asset_registry_v3 as registry
    from src.content_factory import visual_h3_handoff_v3 as h3
    from src.content_factory.visual_shot_binding_v3 import compile_bindings
    run=case['run'];plan=p.read(run/'PLAN.json');request=p.read(case['base']/'1/REQUEST.json')
    cfg=dict(plan['config'],library=str(run/'library'),gpu_lock_root=str(run/'gpu_lock'))
    packet=dict(schema='visual_asset_packet/v3',book_id='fixture_book',source=plan['packet']['source'],
        characters=[dict(id=x,design_version='v1',required_views=['front']) for x in ('adult','child')],
        places=[dict(id='room',design_version='v1',required_views=['front'])],
        shots=[dict(id=c.SHOT,scene_id='scene',place_id='room',visible_cast=['adult','child'],
            character_views=dict(adult='front',child='front'),visual_prompt='Source-bound fixture.',audio=[],start=0,end=5)])
    for entity,kind,item in zip(('adult','child','room'),('character','character','place'),request['prepared']):
        row=registry.register(cfg['library'],item['reference']['path'],book_id='fixture_book',entity_id=entity,
            kind=kind,view='front',design_version='v1')
        registry.review(cfg['library'],book_id='fixture_book',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],
            decision='accepted',reviewer='test_fixture',checks={k:True for k in registry.REVIEW_CHECKS[kind]},
            evidence=dict(image_sha256=row['sha256'],observations=['Protocol fixture only.']))
    plan.update(schema='visual_asset_pipeline/v3',packet=packet,packet_sha256=p.fingerprint(packet),config=cfg,
        publication=False,old_h3_resume=False)
    bindings=compile_bindings(packet,lambda req:p._lookup(plan,req));shot=bindings['shots'][0]
    oldbase=case['base'];newbase=oldbase.parent.parent/shot['binding_sha256']/case['frame']['sha256']
    newbase.parent.mkdir(parents=True);oldbase.rename(newbase);case['base']=newbase
    state=p.read(run/'STATE.json');frame=state['first_frames'][c.SHOT];frame['binding_sha256']=shot['binding_sha256']
    frame['review']['reference_bindings']=[dict(id=a['entity_id'],kind=a['kind'],sha256=a['sha256']) for a in shot['references']]
    write(run/'PLAN.json',plan);write(run/'SHOT_BINDINGS.json',bindings);write(run/'STATE.json',state)
    return plan,bindings


def test_apply_then_normal_tick_and_h3_validation_survive_normal_state_changes(case,monkeypatch):
    """Actual registry/compile/tick/H3 consumer; inference/style are fixture data.

    This legacy geometry fixture has a supplied guide rather than a real v4
    spatial layout, so only its guide adapter is stubbed. The v17 persistent
    consumer, source binding, registry, tick and validate_ready remain real.
    """
    run=case['run'];plan,bindings=upgrade_for_handoff(case)
    from src.content_factory import visual_h3_handoff_v3 as h3
    inventory_gate=p._verify_first_frame_inventory;inventory_source=p._review_layout_inventory
    generation_gate=p._verify_first_frame_generation;style_gate=p._verify_residence_style_receipt
    install_execution(case,monkeypatch)
    c.prepare_extension(run,authorization=case['authorization']);c.execute_extension(run);c.apply_extension(run)
    applied_sha=p.file_sha(run/'STATE.json')
    # Restore the actual production consumer functions after the synthetic inference.
    monkeypatch.setattr(p,'_verify_first_frame_inventory',inventory_gate)
    monkeypatch.setattr(p,'_review_layout_inventory',inventory_source)
    monkeypatch.setattr(p,'_verify_first_frame_generation',generation_gate)
    monkeypatch.setattr(p,'_verify_residence_style_receipt',style_gate)
    monkeypatch.setattr(h3,'_ready_environment_guide',lambda asset,entity,shot,frame:frame['environment_guide'])
    assert p.tick(run,reviewer=None)['status']=='h3_inputs_ready'
    assert p.file_sha(run/'STATE.json')!=applied_sha
    snapshot,ready,current=h3.validate_ready(run)
    assert snapshot['state']['status']=='h3_inputs_ready' and current==bindings
    assert ready['first_frames'][c.SHOT]['review']['decision']=='accepted'
    c.verify_applied(ready['first_frames'][c.SHOT]['review'])
