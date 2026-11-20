"""Style transport/scope contracts only; generated fixture pixels are not visual QA."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import types

from PIL import Image
import pytest

from src.content_factory import visual_residence_review_v5 as s
from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_pipeline_v3 as p


@pytest.fixture
def style_request(tmp_path):
    master=tmp_path/'master.png';target=tmp_path/'different_room.png'
    Image.new('RGB',(256,320),'brown').save(master);Image.new('RGB',(256,320),(242,235,210)).save(target)
    patches=[]
    for slot,material,color in [('wall','aged_plaster','beige'),('wood','wood','brown')]:
        path=tmp_path/(slot+'.png');Image.new('RGB',(80,64),color).save(path)
        patches.append(dict(slot=slot,material_key=material,path=str(path),sha256=v.file_sha(path)))
    return dict(mode='reference',target=str(master),source_context=dict(path=str(master),sha256=v.file_sha(master)),patches=patches,
        semantic=dict(shared_style=dict(era='contemporary_low_cost_older_home',wall_color='cream',condition='worn'),
            room_overrides={},material_slots=[{k:x[k] for k in ('slot','material_key')} for x in patches]),
        binding=dict(group_definition_sha256='a'*64,master_sha256=v.file_sha(master),private_audit_path=str(tmp_path/'not_for_model')))


def answer(style_request,**changes):
    result=dict(checks={k:True for k in s.CHECKS},
        patch_checks=[dict(slot=x['slot'],material_match=True,texture_only=True,identifiable=True,
            evidence='Fixture protocol texture evidence, not a real image-quality finding.') for x in style_request['patches']],
        evidence=['Fixture confirms scope transport only.'])
    result.update(changes);return result


def client(monkeypatch,response,on_infer=None):
    instance=v.VisualReviewClient(dict(provider='ollama',endpoint='http://127.0.0.1:1',model='fixture-vision'))
    calls=[]
    monkeypatch.setattr(instance,'discover',lambda:dict(available=True,model='fixture-vision',capabilities=['vision']))
    def infer(payload):
        calls.append(deepcopy(payload))
        if on_infer:on_infer(payload)
        if isinstance(response,Exception):raise response
        return dict(text=json.dumps(response),model='fixture-vision',usage=dict(fixture=True))
    monkeypatch.setattr(instance,'_infer_http',infer)
    return instance,calls


def test_reference_sends_master_global_context_and_actual_patches_but_never_approves_layout(style_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,answer(style_request));result=c.review_style_materials(style_request,tmp_path/'reference_review')
    assert result['decision']=='accepted' and result['style_reference_ready']
    assert result['layout_approved'] is False and result['novel_fidelity_approved'] is False and result['production_approved'] is False
    assert [x['role'] for x in calls[0]['images']]==['master_style_context','material_patch_wall','material_patch_wood']
    assert calls[0]['images'][0]['binding']['sha256']==style_request['source_context']['sha256']
    assert [v.file_sha(x['binding']['path']) for x in calls[0]['images'][1:]]==[x['sha256'] for x in style_request['patches']]
    assert style_request['binding']['private_audit_path'] not in calls[0]['prompt'] and 'a'*64 not in calls[0]['prompt']
    assert result['style_binding_sha256']==v.digest(style_request['binding']) and result['target_sha256']==v.file_sha(style_request['target'])
    assert result['source_context_sha256']==style_request['source_context']['sha256']
    assert result['patch_bindings']==[{k:x[k] for k in ('slot','material_key','sha256')} for x in style_request['patches']]
    assert c.review_style_materials(style_request,tmp_path/'reference_review')==result and len(calls)==1


def test_different_room_geometry_and_functional_override_do_not_enter_style_contract(style_request,monkeypatch,tmp_path):
    style_request['mode']='target';style_request['target']=str(tmp_path/'different_room.png')
    style_request['semantic']['room_overrides']=dict(floor_surface='ceramic_tile')
    c,calls=client(monkeypatch,answer(style_request));result=c.review_style_materials(style_request,tmp_path/'target_review')
    assert result['decision']=='accepted' and not result['style_reference_ready']
    assert [x['role'] for x in calls[0]['images']]==['target','master_style_context','material_patch_wall','material_patch_wood']
    assert set(calls[0]['schema']['properties'])=={'checks','patch_checks','evidence'}
    assert 'layout' not in calls[0]['schema']['properties']['checks']['properties']
    assert 'different furniture' in calls[0]['prompt'] and 'exposure' in calls[0]['prompt']


@pytest.mark.parametrize('change,decision',[
    (dict(palette=False),'repair_required'),(dict(era_finish=False),'repair_required'),
    (dict(wear=False),'repair_required'),(dict(rendering_style=None),'needs_review'),
])
def test_style_mismatch_or_uncertainty_requires_actual_positive_checks(style_request,monkeypatch,change,decision):
    raw=answer(style_request);raw['checks'].update(change)
    c,_=client(monkeypatch,raw);result=c.review_style_materials(style_request)
    assert result['decision']==decision and not result['style_reference_ready']


@pytest.mark.parametrize('field,value,decision',[
    ('material_match',False,'repair_required'),('texture_only',False,'repair_required'),
    ('material_match',None,'needs_review'),('texture_only',None,'needs_review'),
    ('identifiable',False,'repair_required'),('identifiable',None,'needs_review'),
])
def test_patch_content_is_visually_checked_not_inferred_from_slot_metadata(style_request,monkeypatch,field,value,decision):
    raw=answer(style_request);raw['patch_checks'][0][field]=value
    raw['patch_checks'][0]['evidence']='The visible patch contains a complete piece of furniture or an unclear surface.'
    c,_=client(monkeypatch,raw);result=c.review_style_materials(style_request)
    assert result['decision']==decision and result['patch_checks'][0][field] is value


@pytest.mark.parametrize('defect',['missing','duplicate','bool_check','empty_evidence'])
def test_malformed_or_missing_patch_evidence_cannot_pass(style_request,monkeypatch,defect):
    raw=answer(style_request)
    if defect=='missing':raw['patch_checks'].pop()
    elif defect=='duplicate':raw['patch_checks'][1]['slot']=raw['patch_checks'][0]['slot']
    elif defect=='bool_check':raw['checks']['palette']=1
    else:raw['evidence']=[]
    c,_=client(monkeypatch,raw);result=c.review_style_materials(style_request)
    assert result['decision']=='unavailable' and result['completion_known'] and result['retryable']


@pytest.mark.parametrize('field',['shared_style','room_overrides'])
def test_program_metadata_never_crosses_semantic_boundary(style_request,field):
    style_request['semantic'][field]['source_sha256']='f'*64
    with pytest.raises(ValueError,match='invalid_residence_style_property'):s._prepared(style_request)


def test_patch_sha_or_material_scope_mutation_is_rejected_before_inference(style_request,monkeypatch):
    c,calls=client(monkeypatch,answer(style_request))
    style_request['patches'][0]['sha256']='f'*64
    with pytest.raises(ValueError,match='patch_changed'):c.review_style_materials(style_request)
    assert calls==[]


def test_master_context_sha_is_bound_and_cannot_be_replaced_by_unrelated_room(style_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,answer(style_request))
    style_request['source_context']=dict(path=str(tmp_path/'different_room.png'),sha256=v.file_sha(tmp_path/'different_room.png'))
    with pytest.raises(ValueError,match='master_context_changed'):c.review_style_materials(style_request)
    assert calls==[]


def test_patch_scope_stays_separate_from_global_master_context(style_request,monkeypatch):
    raw=answer(style_request);raw['patch_checks'][0]['identifiable']=None
    raw['patch_checks'][0]['evidence']='Global room context is clear, but this texture crop remains too dark to identify.'
    c,calls=client(monkeypatch,raw);result=c.review_style_materials(style_request)
    assert result['decision']=='needs_review' and not result['style_reference_ready']
    assert all(v is True for v in result['checks'].values())
    assert 'not proving a hidden substrate' in calls[0]['prompt']


def test_source_changed_during_style_review_is_not_an_acceptance(style_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,answer(style_request),lambda _:
        Image.new('RGB',(256,320),'black').save(style_request['target']))
    result=c.review_style_materials(style_request,tmp_path/'changed')
    assert result['decision']=='unavailable' and result['completion_known'] and len(calls)==1


def test_unknown_style_native_is_preserved_and_never_reposted(style_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,v.ReviewOutcomeUnknown('fixture unknown transport'))
    result=c.review_style_materials(style_request,tmp_path/'unknown')
    assert result['outcome_unknown'] and not result['retryable'] and not result['completion_known']
    assert c.review_style_materials(style_request,tmp_path/'unknown')==result and len(calls)==1
    assert (tmp_path/'unknown/item_0000/STYLE_ERROR.json').exists()


def test_saved_style_result_or_group_binding_change_cannot_reuse_review(style_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,answer(style_request));c.review_style_materials(style_request,tmp_path/'saved')
    style_request['binding']['group_definition_sha256']='b'*64
    with pytest.raises(ValueError,match='saved residence style'):c.review_style_materials(style_request,tmp_path/'saved')
    assert len(calls)==1


def test_native_local_worker_receives_style_mode_without_loading_models_in_test(style_request,monkeypatch,tmp_path):
    c=v.VisualReviewClient(dict(provider='transformers_local',model_path=str(tmp_path/'fake_model')))
    monkeypatch.setattr(c,'discover',lambda:dict(available=True,model='fixture-no-gpu'))
    def run(command,**kwargs):
        folder=Path(command[command.index('--request')+1]).parent
        saved=v._read(folder/'REQUEST.json');assert saved['review_mode']==s.VERSION
        prepared=saved['prepared'][0]
        result=s._review_one(prepared,lambda _:dict(text=json.dumps(answer(style_request))),saved['model_binding'],folder/'item_0000')
        v._write(folder/'RESULTS.json',dict(request_binding_sha256=saved['request_binding_sha256'],results_sha256=v.digest([result]),results=[result]))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(s.subprocess,'run',run)
    result=c.review_style_materials(style_request,tmp_path/'worker_route')
    assert result['decision']=='accepted' and (tmp_path/'worker_route/WORKER_EXIT.json').exists()


@pytest.mark.parametrize('layout_decision,style_decision,expected',[
    ('accepted','accepted','accepted'),('needs_review','accepted','needs_review'),
    ('repair_required','accepted','repair_required'),('accepted','needs_review','needs_review'),
    ('accepted','repair_required','repair_required'),('accepted','unavailable','unavailable'),
])
def test_separate_style_pass_cannot_upgrade_layout_or_person_count(layout_decision,style_decision,expected):
    layout=dict(decision=layout_decision,checks=dict(layout=None if layout_decision=='needs_review' else True,
        view=False if layout_decision=='repair_required' else True,consistency=True,artifact_free=True),
        completion_known=True,outcome_unknown=False,retryable=False,inference_dispatched=True,visual_evidence=['Layout evidence.'])
    style=dict(result=dict(decision=style_decision,checks={k:True for k in s.CHECKS},completion_known=True,
        retryable=False,inference_dispatched=True,visual_evidence=['Style evidence.']))
    combined=p._combine_residence_style(layout,style)
    assert combined['decision']==expected and combined['checks']==layout['checks']
    assert combined['layout_review']==layout and combined['style_review']==style


def test_style_unknown_stays_unknown_even_when_layout_is_positive():
    combined=p._combine_residence_style(dict(decision='accepted',checks=dict(layout=True),completion_known=True,
        visual_evidence=['Layout positive.']),dict(result=dict(decision='unavailable',completion_known=False,
        outcome_unknown=True,retryable=False,inference_dispatched=True,visual_evidence=[])))
    assert combined['decision']=='unavailable' and combined['outcome_unknown'] and not combined['retryable']


def test_master_bootstrap_only_exempts_initial_source_not_first_frame(style_request,monkeypatch,tmp_path):
    plan=dict(packet=dict(style_groups=[dict(id='home',master_place_id='master')]))
    master=dict(id='master',style_group_id='home');sibling=dict(id='kitchen',style_group_id='home')
    monkeypatch.setattr(p,'_style_reference_for_entity',lambda *_:None)
    assert p._residence_style_review(tmp_path,plan,master,style_request['target'],None,tmp_path/'bootstrap',allow_master_bootstrap=True) is None
    for entity,allow in [(master,False),(sibling,True),(sibling,False)]:
        with pytest.raises(ValueError,match='reference_not_ready'):
            p._residence_style_review(tmp_path,plan,entity,style_request['target'],None,tmp_path/'frame',allow_master_bootstrap=allow)


def test_style_target_receipt_is_separate_and_rechecked_against_current_binding(style_request,monkeypatch,tmp_path):
    from src.content_factory import visual_residence_style_v5 as materials
    plan=dict(packet=dict(style_groups=[dict(id='home',master_place_id='master')]))
    entity=dict(id='kitchen',style_group_id='home');style_request['mode']='target'
    monkeypatch.setattr(p,'_style_reference_for_entity',lambda *_:dict(fixture=True))
    monkeypatch.setattr(materials,'target_request',lambda *a:deepcopy(style_request))
    validations=[]
    def verify(q,result,require_accepted=True):
        validations.append(require_accepted)
        assert result['style_binding_sha256']==v.digest(q['binding'])
        return True
    monkeypatch.setattr(materials,'verify_result',verify)
    c,_=client(monkeypatch,answer(style_request))
    record=p._residence_style_review(tmp_path,plan,entity,style_request['target'],c,tmp_path/'target_style')
    assert record['request_sha256']==p.fingerprint(record['request']) and validations==[False]
    combined=dict(decision='accepted',style_review=record)
    p._verify_residence_style_receipt(tmp_path,plan,entity,style_request['target'],combined)
    assert validations==[False,True]
    style_request['binding']['group_definition_sha256']='c'*64
    with pytest.raises(ValueError,match='dependency_changed'):
        p._verify_residence_style_receipt(tmp_path,plan,entity,style_request['target'],combined)


def test_legacy_room_has_no_extra_style_request_or_requirement(tmp_path):
    assert p._residence_style_review(tmp_path,dict(packet={}),dict(id='old_room'),tmp_path/'unused',None,None) is None
    assert p._verify_residence_style_receipt(tmp_path,dict(packet={}),dict(id='old_room'),tmp_path/'unused',{}) is None


@pytest.mark.parametrize('layout_check,decision',[(False,'repair_required'),(None,'needs_review')])
def test_positive_style_cannot_upgrade_internally_inconsistent_layout_receipt(layout_check,decision):
    layout=dict(decision='accepted',checks=dict(layout=layout_check,view=True),completion_known=True,visual_evidence=['Fixture.'])
    style=dict(result=dict(decision='accepted',completion_known=True,visual_evidence=['Style fixture.']))
    result=p._combine_residence_style(layout,style)
    assert result['decision']==decision and result['checks']['layout'] is layout_check


@pytest.mark.parametrize('stored_sha',[None,'b'*64])
def test_old_shot_prompt_requires_restage_before_any_first_frame(stored_sha,monkeypatch,tmp_path):
    from src.content_factory import visual_residence_style_v5 as materials
    monkeypatch.setattr(materials,'group_for',lambda *a:dict(definition_sha256='a'*64))
    packet=dict(places=[dict(id='room',style_group_id='home')]);shot=dict(id='shot1',place_id='room',home_style_sha256=stored_sha,
        visual_prompt='Old brown wall and old wooden floor, intentionally obsolete fixture.')
    with pytest.raises(ValueError,match='needs_restage'):
        p._prepare_first_frame(tmp_path,dict(packet=packet,config={}),{},shot)
    assert not (tmp_path/'image_jobs').exists()


@pytest.mark.parametrize('invalidations',[
    ['shot1'],[dict(shot_id='shot1',reason='old_stage_uses_previous_materials')],
    dict(shot1=dict(reason='old_stage_uses_previous_materials')),
])
def test_merely_stamping_new_style_sha_cannot_clear_old_stage_invalidation(invalidations,monkeypatch):
    from src.content_factory import visual_residence_style_v5 as materials
    monkeypatch.setattr(materials,'group_for',lambda *a:dict(definition_sha256='a'*64))
    packet=dict(places=[dict(id='room',style_group_id='home')],shot_invalidations=invalidations)
    with pytest.raises(ValueError,match='needs_restage'):
        p._require_current_shot_style(packet,dict(id='shot1',place_id='room',home_style_sha256='a'*64))


def test_current_restage_and_legacy_ungrouped_shots_remain_compatible(monkeypatch):
    from src.content_factory import visual_residence_style_v5 as materials
    monkeypatch.setattr(materials,'group_for',lambda *a:dict(definition_sha256='a'*64))
    assert p._require_current_shot_style(dict(places=[dict(id='room',style_group_id='home')],shot_invalidations=[]),
        dict(id='shot1',place_id='room',home_style_sha256='a'*64)) is None
    assert p._require_current_shot_style(dict(places=[dict(id='old_room')]),dict(id='old',place_id='old_room')) is None
