from copy import deepcopy
import json
import pytest
from tests.test_creative_action_plan_v1 import sample as old_sample
from src.content_factory.creative_action_plan_v2 import VERSION, schedule_action_plan, compile_action_plan
from src.content_factory.creative_state_plan_v6 import build_state_plan_schema, build_state_plan_prompt, validate_state_plan, compile_state_plan
from src.content_factory.creative_workflow_contract import CreativeContractError


def sample():
    p,s,m=old_sample()
    p['schema']=VERSION
    p['spatial_contract']={'seats':[{'seat_id':'E02','access_positions':['桌旁'],'required_facing':'桌面'}]}
    for c in m['characters']: p['initial_state'][c['id']]['facing']='桌面'
    for row,beat in zip(p['beats'],s['beats']):
        row['cut_after_event_id']='dialogue_0' if beat['dialogue'] else row['groups'][-1]['id']
        row['completion_condition']='all_required_events_complete'
    return p,s,m


def test_version_dispatch_and_compiled_cut_facing_preserve_sources():
    import jsonschema
    p,s,m=sample(); before=deepcopy((p,s,m))
    ctx={'script':s,'static_visual_manifest':m,'state_plan_version':VERSION}
    jsonschema.validate(p,build_state_plan_schema(ctx))
    assert VERSION in build_state_plan_prompt(ctx)
    validate_state_plan(p,s,m)
    result=compile_state_plan(p,s,m)
    assert result==compile_action_plan(p,s,m)
    assert (p,s,m)==before
    assert result['shots'][0]['end_state']==result['shots'][1]['start_state']
    assert 'facing' in result['shots'][0]['prompt']
    assert '唯一执行切点：10秒' in result['shots'][0]['prompt']


@pytest.mark.parametrize('anchor',['A1','missing'])
def test_cut_cannot_precede_remaining_locked_dialogue(anchor):
    p,s,m=sample();p['beats'][0]['cut_after_event_id']=anchor
    with pytest.raises(CreativeContractError,match='PLAN_CUT_'):
        schedule_action_plan(p,s,m)


def test_last_action_anchor_after_dialogue_is_valid():
    p,s,m=sample(); group=deepcopy(p['beats'][0]['groups'][0])
    group.update(id='later',script_slot='after',operations=[],performance='保持已经成立状态')
    p['beats'][0]['groups'].append(group);p['beats'][0]['cut_after_event_id']='later'
    _,report=schedule_action_plan(p,s,m)
    assert report['beats'][0]['cut_contract']['completion_seconds']>report['beats'][0]['actual_dialogue_seconds'][0]


def test_seat_wrong_side_is_failure_and_does_not_guess_move():
    p,s,m=sample();p['initial_state']['C02']['position']='椅背后'
    before=deepcopy(p)
    with pytest.raises(CreativeContractError,match='PLAN_SEAT_ACCESS_INVALID'):
        schedule_action_plan(p,s,m)
    assert p==before


@pytest.mark.parametrize('missing',['facing','seat','positions','required_facing'])
def test_seat_missing_evidence_is_blocking_unknown(missing):
    p,s,m=sample()
    if missing=='facing': p['initial_state']['C02']['facing']=None
    if missing=='seat': p['spatial_contract']['seats']=[]
    if missing=='positions': p['spatial_contract']['seats'][0]['access_positions']=[]
    if missing=='required_facing': p['spatial_contract']['seats'][0]['required_facing']=None
    with pytest.raises(CreativeContractError,match='PLAN_SEAT_ACCESS_UNKNOWN') as exc:
        schedule_action_plan(p,s,m)
    assert exc.value.detail['status']=='unknown'
    assert exc.value.detail['unknown_disposition']=='review_required'
    assert exc.value.detail['blocks_handoff'] is True


def test_separate_approach_and_face_then_sit_is_valid_and_compiled():
    p,s,m=sample();p['initial_state']['C02'].update(position='椅背后',facing='门')
    row=p['beats'][1];approach=deepcopy(row['groups'][0])
    approach.update(id='approach',performance='走到可坐侧并转身',operations=[
        {'kind':'move','actor':'C02','target':'','value':'桌旁'},
        {'kind':'face','actor':'C02','target':'','value':'桌面'}])
    row['groups'].insert(0,approach)
    compiled=compile_action_plan(p,s,m)
    assert '身体朝向' in compiled['shots'][1]['visible_performance']
    assert json.loads(compiled['shots'][1]['end_state'])['C02(陈禾)']['facing']=='桌面'


def test_same_group_approach_cannot_satisfy_sit_start_precondition():
    p,s,m=sample();p['initial_state']['C02']['position']='椅背后'
    p['beats'][1]['groups'][0]['operations'].insert(0,{'kind':'move','actor':'C02','target':'','value':'桌旁'})
    with pytest.raises(CreativeContractError,match='PLAN_SEAT_ACCESS_INVALID'): schedule_action_plan(p,s,m)


def test_prose_contradiction_not_falsely_claimed_checked_and_sources_preserved():
    p,s,m=sample();p['beats'][0]['dialogue_performance']='抬眼看向同伴，未写入操作'
    p['beats'][0]['camera']='文件夹落桌就切走'
    _,report=schedule_action_plan(p,s,m)
    pair=report['semantic_comparisons'][0]
    assert pair['semantic_status']=='not_checked'
    assert any(x['value']=='文件夹落桌就切走' for x in pair['prose_sources'])
    assert any(x['value']=='抬眼看向同伴，未写入操作' for x in pair['prose_sources'])


def test_explicit_parallel_source_requirement_reports_expression_not_physical_error():
    p,s,m=sample();s['beats'][0]['execution_requirements']=[{'kind':'simultaneous_dialogue_action'}]
    before=deepcopy(s)
    with pytest.raises(CreativeContractError,match='EXPRESSION_UNSUPPORTED'): schedule_action_plan(p,s,m)
    assert s==before


def test_old_protocol_still_replays_without_new_fields():
    from src.content_factory.creative_action_plan_v1 import schedule_action_plan as old_schedule
    p,s,m=old_sample()
    old_schedule(p,s,m)
    validate_state_plan(p,s,m)


def test_hold_cannot_hide_face_action_in_legacy_projection():
    p,s,m=sample();g=p['beats'][0]['groups'][0]
    g.update(kind='hold',hold_subject='C01',operations=[{'kind':'face','actor':'C01','target':'','value':'门'}])
    with pytest.raises(CreativeContractError,match='PLAN_HOLD_HAS_ACTION'): schedule_action_plan(p,s,m)


def test_body_facing_is_not_inferred_from_gaze():
    p,s,m=sample();p['initial_state']['C02'].update(facing='门',gaze='桌面')
    with pytest.raises(CreativeContractError,match='PLAN_SEAT_ACCESS_INVALID'): schedule_action_plan(p,s,m)


def test_later_required_hold_cannot_be_skipped_by_dialogue_cut_anchor():
    p,s,m=sample()
    p['beats'][0]['groups'].append({'id':'response','script_slot':'after','kind':'hold','duration_seconds':2,
        'hold_subject':'C01','performance':'听完后保持反应','operations':[]})
    with pytest.raises(CreativeContractError,match='PLAN_CUT_BEFORE_REQUIRED_EVENT'): schedule_action_plan(p,s,m)


def test_independent_simultaneous_character_actions_remain_supported():
    p,s,m=sample();p['beats'][0]['groups'][0]['operations'].append({'kind':'gaze','actor':'C01','target':'','value':'P01'})
    schedule_action_plan(p,s,m)


def test_compiled_boundary_tampering_is_not_a_valid_handoff_source():
    from src.content_factory.creative_action_plan_v2 import check_adjacent_state_transition
    p,s,m=sample();shots=compile_action_plan(p,s,m)
    row=json.loads(shots['shots'][1]['start_state']);row['C02(陈禾)']['gaze']='门'
    shots['shots'][1]['start_state']=json.dumps(row)
    with pytest.raises(CreativeContractError,match='PLAN_BOUNDARY_STATE_CONFLICT'): check_adjacent_state_transition(shots)


def test_unknown_actor_is_contract_error_not_keyerror():
    p,s,m=sample();p['beats'][0]['groups'][0]['operations'][0]['actor']='C404'
    with pytest.raises(CreativeContractError,match='PLAN_SCHEMA_INVALID'): schedule_action_plan(p,s,m)


def test_nonexistent_seat_is_known_invalid_not_unknown():
    p,s,m=sample();p['beats'][1]['groups'][0]['operations'][0]['target']='E404'
    with pytest.raises(CreativeContractError,match='PLAN_SEAT_ACCESS_INVALID') as exc: schedule_action_plan(p,s,m)
    assert exc.value.detail['status']=='failed'


@pytest.mark.parametrize('identifier',['dialogue_0','A1'])
def test_reserved_and_cross_beat_duplicate_group_ids_are_rejected(identifier):
    p,s,m=sample();p['beats'][1]['groups'][0]['id']=identifier;p['beats'][1]['cut_after_event_id']=identifier
    with pytest.raises(CreativeContractError): schedule_action_plan(p,s,m)


def unavailable(code='EXPRESSION_UNSUPPORTED'):
    return {'status':'unsupported','code':code,'source_paths':['script.beats.0.event'],
            'reason':'该段明确要求同说同动，串行协议不能忠实表达'}


def test_model_response_allows_grounded_refusal_but_internal_plan_schema_does_not():
    import jsonschema
    from src.content_factory.creative_action_plan_v2 import build_action_plan_schema, build_model_response_schema
    p,s,m=sample();ctx={'script':s,'static_visual_manifest':m,'state_plan_version':VERSION}
    response=unavailable()
    jsonschema.validate(response,build_model_response_schema(ctx))
    jsonschema.validate(response,build_state_plan_schema(ctx))
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(response,build_action_plan_schema(ctx))
    jsonschema.validate(p,build_model_response_schema(ctx))


@pytest.mark.parametrize('code',['EXPRESSION_UNSUPPORTED','REQUIREMENT_CONFLICT'])
def test_terminal_refusal_binds_real_sources_without_changing_them(code):
    from src.content_factory.creative_action_plan_v2 import reject_unavailable_response, PlanUnavailableError, _digest
    p,s,m=sample();ctx={'script':s,'creative_brief':{'constraint':'同说同动'}};before=deepcopy(ctx)
    value=unavailable(code);value['source_paths'].append('creative_brief.constraint')
    with pytest.raises(PlanUnavailableError) as exc: reject_unavailable_response(value,ctx)
    detail=exc.value.detail
    assert detail['code']==code and detail['blocks_handoff'] and detail['automatic_retry'] is False
    assert detail['source_sha256']==_digest(ctx)
    assert detail['source_refs'][0]['value']==s['beats'][0]['event']
    assert detail['response_sha256']==_digest(value)
    assert detail['semantic_judgment_verified'] is False
    assert ctx==before


@pytest.mark.parametrize('mutate',[
    lambda r:r.update(source_paths=[]),
    lambda r:r.update(source_paths=['script.beats.99.event']),
    lambda r:r.update(source_paths=['static_visual_manifest.scene']),
    lambda r:r.update(source_paths=['script.beats']),
    lambda r:r.update(source_paths=['script.beats.0.event','script.beats.0.event']),
    lambda r:r.update(reason='  '),
    lambda r:r.update(status='maybe'),
    lambda r:r.update(unrequested='field'),
])
def test_malformed_explicit_refusal_still_stops_instead_of_paid_plan_repair(mutate):
    from src.content_factory.creative_action_plan_v2 import reject_unavailable_response, PlanUnavailableError
    _,s,_=sample();r=unavailable();mutate(r)
    with pytest.raises(PlanUnavailableError) as exc: reject_unavailable_response(r,{'script':s})
    assert exc.value.detail['code']=='PLAN_UNAVAILABLE_RESPONSE_INVALID'
    assert exc.value.detail['reason_code']=='REQUIRED_EVIDENCE_MISSING'
    assert exc.value.detail['automatic_retry'] is False


def test_normal_plan_is_not_a_refusal_and_old_transport_schema_unchanged():
    from src.content_factory.creative_action_plan_v2 import reject_unavailable_response
    p,s,m=sample();assert reject_unavailable_response(p,{'script':s}) is None
    oldp,olds,oldm=old_sample()
    schema=build_state_plan_schema({'script':olds,'static_visual_manifest':oldm,'state_plan_version':oldp['schema']})
    assert 'oneOf' not in schema


def test_same_refusal_for_changed_source_has_different_program_computed_binding():
    from src.content_factory.creative_action_plan_v2 import reject_unavailable_response, PlanUnavailableError
    _,s,_=sample();other=deepcopy(s);other['beats'][0]['event']='完全不同的动作'
    hashes=[]
    for script in (s,other):
        with pytest.raises(PlanUnavailableError) as exc: reject_unavailable_response(unavailable(),{'script':script})
        hashes.append(exc.value.detail['source_sha256'])
    assert hashes[0]!=hashes[1]


@pytest.mark.parametrize('mutate',[
    lambda p:p['beats'][0]['groups'][0].update(kind='hold',hold_subject='C01'),
    lambda p:p['beats'][0]['groups'][0].update(hold_subject='C01'),
    lambda p:p['beats'][0]['groups'][0].update(kind='hold',hold_subject='',operations=[]),
])
def test_hold_action_relations_are_now_in_provider_schema(mutate):
    import jsonschema
    from src.content_factory.creative_action_plan_v2 import build_action_plan_schema
    p,s,m=sample();mutate(p)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(p,build_action_plan_schema({'script':s,'static_visual_manifest':m}))


@pytest.mark.parametrize('operation',[
    {'kind':'place','actor':'C02','target':'E01','value':'P01'},
    {'kind':'take','actor':'C02','target':'E01','value':'右手'},
    {'kind':'sit','actor':'C02','target':'P01','value':'椅上'},
    {'kind':'sit','actor':'C02','target':'E02','value':''},
    {'kind':'move','actor':'C02','target':'E01','value':'桌旁'},
])
def test_operation_target_and_value_contract_is_in_generation_schema(operation):
    import jsonschema
    from src.content_factory.creative_action_plan_v2 import build_action_plan_schema
    p,s,m=sample();p['beats'][0]['groups'][0]['operations']=[operation]
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(p,build_action_plan_schema({'script':s,'static_visual_manifest':m}))
