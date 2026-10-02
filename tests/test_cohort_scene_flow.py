"""Synthetic regression cases derived from rejected trial failure categories."""
import copy
import math
import pytest
from src.trend_intelligence.cohort_scene_flow import apply_plan_replacements
from src.trend_intelligence.cohort_scene_flow import spoken_characters


def test_punctuation_is_not_spoken_as_extra_syllables():
    assert spoken_characters('墙上钉眼要补，押金得扣。两千就这么扣？')==16
    c=contract();row=replay(c)['beats'][0]
    n=round((row['duration']-row['beat']['pause'])*5.1)
    plain={'lines':[{'speaker':'A','text':'甲'*n}]}
    punctuated={'lines':[{'speaker':'A','text':'，'.join('甲'*n)+'！'}]}
    assert validate_lines(plain,c,row)['rate']==validate_lines(punctuated,c,row)['rate']


def test_dialogue_projection_hides_later_revelations_and_uses_current_hands():
    from scripts.run_cohort_scene_flow import dialogue_projection
    c=contract();c['facts']['F']['initial_knowers']=['A','B'];trace=replay(c)
    first=dialogue_projection(scene_request(c,trace['beats'][0]),c,trace['beats'][0])
    assert 'goal' not in first and 'transactions' not in first and first['facts']=={}
    later=dialogue_projection(scene_request(c,trace['beats'][2]),c,trace['beats'][2])
    assert 'F' in later['facts'] and 'G' not in later['facts']
    assert later['props']['PA']['location']=='A:right'
    assert c['props']['PA']['location']=='A:pocket'
    assert later['continuity_contract']['planned_prop_destinations']['K']=='A:left'


def test_silent_payment_time_goes_to_final_delivery_without_padding():
    c=contract();c['beats'][5]['speakers']=[]
    trace=replay(c);payment=trace['beats'][5];ending=trace['beats'][6]
    assert payment['duration']==pytest.approx(payment['minimum_action_seconds']+.2)
    assert payment['duration']+ending['duration']==pytest.approx(9)
    assert validate_lines({'lines':[]},c,payment)['rate'] is None


def test_dialogue_cannot_invent_a_new_money_amount():
    from src.trend_intelligence.cohort_scene_flow import monetary_mentions
    assert monetary_mentions('千真万确，说一百遍。')==[]
    c=contract();row=replay(c)['beats'][0]
    with pytest.raises(FlowError,match='amount absent'):
        validate_lines({'lines':[{'speaker':'A','text':'再扣八百元。'}]},c,row,strict_timing=False)


def test_whole_schedule_redistributes_speech_without_changing_actions():
    from src.trend_intelligence.cohort_scene_flow import fit_dialogue_timing
    c=contract();trace=replay(c);scenes=[]
    for row in trace['beats']:
        n=round((row['duration']-row['minimum_action_seconds']-row['beat']['pause'])*5.1)
        scenes.append({'lines':[{'speaker':'A','text':'甲'*n}]})
    scenes[0]['lines'][0]['text']+='甲甲甲'
    scenes[1]['lines'][0]['text']=scenes[1]['lines'][0]['text'][:-3]
    fitted=fit_dialogue_timing(c,trace,scenes)
    assert fitted['beats'][-1]['end']==pytest.approx(45)
    assert fitted['terminal']==trace['terminal']
    for a,b,s in zip(trace['beats'],fitted['beats'],scenes):
        assert a['before']==b['before'] and a['after']==b['after'] and a['beat']['ops']==b['beat']['ops']
        assert a['minimum_action_seconds']==b['minimum_action_seconds']
        validate_lines(s,c,b)
    scenes[0]['lines'][0]['text']='甲'*500
    with pytest.raises(FlowError,match='Speech needs'):fit_dialogue_timing(c,trace,scenes)


def test_direction_cannot_rewrite_actions_or_bind_stale_dialogue():
    from src.trend_intelligence.cohort_scene_flow import apply_direction_revision,check_direction_quotes
    trace=replay(contract());scenes=[{'lines':[{'speaker':'A','text':'真实对白'}]}]*len(trace['beats'])
    revision={'dialogue_sha256':signature(scenes),'overrides':{'B1':{'trigger':'「未出现的对白」'}}}
    changed=apply_direction_revision(trace,revision,scenes)
    assert check_direction_quotes(changed,scenes)[0]['quote']=='未出现的对白'
    revision['overrides']={'B1':{'ops':[]}}
    with pytest.raises(FlowError,match='cannot change'):apply_direction_revision(trace,revision,scenes)
    revision['overrides']={'B1':{'emotion':'synthetic'}};revision['dialogue_sha256']='stale'
    with pytest.raises(FlowError,match='different dialogue'):apply_direction_revision(trace,revision,scenes)
from src.trend_intelligence.cohort_scene_flow import FlowError,strict_json,replay,scene_request,signature,validate_lines,render

def contract():
    def beat(i,role,ops):return {'id':f'B{i}','role':role,'weight':1,'intent':f'synthetic event {i}',
        'trigger':'synthetic obstruction','emotion':'synthetic delivery','cps':5.1,'pause':.2,
        'speakers':['A','B'],'framing':'synthetic fixed scene','ops':ops}
    return {'schema':'cohort_event_contract/v2','kind':'short','title':'synthetic','goal':'synthetic receipt and handover','space':'synthetic fixed layout',
        'characters':{'A':{'name':'甲','position':'left'},'B':{'name':'乙','position':'right'}},
        'locations':['A:left','A:right','A:pocket','B:left','B:right','B:bag','table'],
        'props':{'PA':{'name':'甲设备','owner':'A','location':'A:pocket'},'PB':{'name':'乙设备','owner':'B','location':'B:left'},'K':{'name':'物件','owner':'A','location':'B:right'}},
        'facts':{'F':{'text':'synthetic evidence','kind':'evidence','prop':'PB','initial_knowers':['B']},
                 'G':{'text':'synthetic consent','kind':'agreement','prop':None,'initial_knowers':[]}},
        'transactions':{'X':{'payer':'A','payee':'B','amount':'一百元','payer_prop':'PA','payee_prop':'PB','agreement':'G','requires':['F']}},
        'terminal':{'props':{'K':'A:left'},'transactions':{'X':'received'},'confirmed':{'F':['A','B']}},
        'references':[{'source_id':'synthetic-source','evidence_ids':['E1'],'use':'synthetic expression reference'}],
        'beats':[beat(1,'conflict',[]),beat(2,'escalation',[['move','PA','A:pocket','A:right']]),
            beat(3,'turn',[['show','F','B','A']]),beat(4,'turn',[['ack','F','A'],['agree','G','A']]),
            beat(5,'escalation',[]),beat(6,'resolution',[['submit','X','A']]),
            beat(7,'closure',[['receive','X','B'],['move','K','B:right','A:left']])]}


def test_field_repair_preserves_frozen_content_and_original():
    original=contract();before=copy.deepcopy(original)
    fixed=apply_plan_replacements(original,{'replacements':[{'path':'/beats/3/emotion','value':'changed'}]},['/beats/3/emotion'])
    assert original==before
    expected=copy.deepcopy(before);expected['beats'][3]['emotion']='changed'
    assert fixed==expected


def test_field_repair_reports_off_by_one_and_rejects_extra_changes():
    with pytest.raises(FlowError,match='missing=.*beats/3/emotion.*extra=.*beats/4/emotion'):
        apply_plan_replacements(contract(),{'replacements':[{'path':'/beats/4/emotion','value':'wrong'}]},['/beats/3/emotion'])


def test_initial_knowledge_does_not_replace_showing_evidence():
    c=contract();c['facts']['F']['initial_knowers']=['A','B']
    c['beats'][2]['ops']=[];c['beats'][3]['ops']=[['agree','G','A']]
    with pytest.raises(FlowError,match='never shown'):replay(c)


def test_structural_trace_cannot_pass_as_actual_review(tmp_path):
    from scripts.run_cohort_scene_flow import require_actual_review,save,identity,now
    candidate=tmp_path/'contract.json';save(candidate,contract())
    review=tmp_path/'review.json';save(review,replay(contract()))
    with pytest.raises(ValueError,match='Actual review'):require_actual_review(review,candidate,('physical_actions',))
    save(review,{'candidate':identity(candidate),'decision':'passed','unresolved':[],
                 'reviewed_at_bjt':now(),'checks':{'physical_actions':{'passed':True}}})
    with pytest.raises(ValueError,match='Unchecked'):require_actual_review(review,candidate,('physical_actions',))


def test_actual_review_cannot_survive_candidate_edit(tmp_path):
    from scripts.run_cohort_scene_flow import require_actual_review,save,identity,now
    candidate=tmp_path/'contract.json';save(candidate,contract())
    review=tmp_path/'review.json';save(review,{'candidate':identity(candidate),'decision':'passed','unresolved':[],
        'reviewed_at_bjt':now(),'checks':{'physical_actions':{'passed':True,'finding':'synthetic review','evidence':['synthetic operation']}}})
    require_actual_review(review,candidate,('physical_actions',))
    c=contract();c['goal']='changed';save(candidate,c)
    with pytest.raises(ValueError,match='Actual review'):require_actual_review(review,candidate,('physical_actions',))

def test_realized_goal_is_derived_and_timing_is_exact():
    trace=replay(contract(),{'synthetic-source':{'E1':{}}})
    assert trace['terminal']['transactions']['X']=='received'
    assert trace['terminal']['props']['K']=='A:left'
    assert trace['duration']==pytest.approx(45)
    assert sum(b['duration'] for b in trace['beats'] if b['beat']['role'] in ('resolution','closure'))==pytest.approx(9)
    assert trace['semantic_review_required'] and 'pending_actual_review' in trace['status']

@pytest.mark.parametrize('operation,expected',[
    (['submit','X','B'],'reversed_payment'),
    (['receive','X','B'],'receipt_without_payment'),
    (['move','PA','A:pocket','A:left'],'prop_transition'),
    (['move','K','B:right','B:left'],'occupied_hand'),
    (['ack','F','A'],'ack_without_evidence'),
])
def test_old_failure_categories_are_rejected(operation,expected):
    c=contract()
    if expected=='prop_transition':c['beats'][4]['ops']=[operation]
    elif expected=='occupied_hand':c['beats'][0]['ops']=[operation]
    elif expected=='ack_without_evidence':c['beats'][0]['ops']=[operation]
    else:c['beats'][0]['ops']=[operation]
    with pytest.raises(FlowError) as e:replay(c)
    assert e.value.code==expected

def test_payer_metadata_alone_cannot_hide_reversed_actual_operation():
    c=contract();c['beats'][5]['ops']=[['submit','X','B']]
    assert c['transactions']['X']['payer']=='A'
    with pytest.raises(FlowError,match='must be performed'):replay(c)

def test_seen_evidence_is_not_confirmation_or_payment_consent():
    c=contract();c['beats'][3]['ops']=[]
    with pytest.raises(FlowError) as e:replay(c)
    assert e.value.code=='payment_before_agreement'

def test_ending_claim_cannot_replace_receiver_or_handover_action():
    c=contract();c['beats'][6]['ops']=[['move','K','B:right','A:left']]
    with pytest.raises(FlowError) as e:replay(c)
    assert e.value.code=='unrealized_result'
    c=contract();c['beats'][6]['ops']=[['receive','X','B']]
    with pytest.raises(FlowError) as e:replay(c)
    assert e.value.code=='terminal_prop'

def test_duplicate_and_malformed_model_json_never_silently_drop_dialogue():
    with pytest.raises(FlowError) as e:strict_json('{"speaker":"A","text":"one","speaker":"B"}')
    assert e.value.code=='duplicate_key'
    with pytest.raises(FlowError):strict_json('{"ops":[],"ending":}')

def test_unknown_source_evidence_returns_to_research():
    with pytest.raises(FlowError) as e:replay(contract(),{'synthetic-source':{'E2':{}}})
    assert e.value.stage=='research'

def test_only_changed_beat_or_state_suffix_changes_scene_request():
    c=contract();old=replay(c)
    c['beats'][4]['emotion']='changed delivery only';new=replay(c)
    keys1=[signature(scene_request(contract(),r)) for r in old['beats']]
    keys2=[signature(scene_request(c,r)) for r in new['beats']]
    assert [i for i,(a,b) in enumerate(zip(keys1,keys2)) if a!=b]==[4]
    c=contract();c['beats'][1]['ops']=[['move','PA','A:pocket','A:left']];c['terminal']['props']={'K':'A:right'}
    c['beats'][6]['ops'][1]=['move','K','B:right','A:right'];changed=replay(c)
    keys3=[signature(scene_request(c,r)) for r in changed['beats']]
    assert keys1[0]==keys3[0] and all(a!=b for a,b in zip(keys1[1:],keys3[1:]))

def test_dialogue_pacing_checks_local_budget_after_real_actions():
    c=contract();trace=replay(c);row=trace['beats'][5]
    available=row['duration']-row['minimum_action_seconds']-row['beat']['pause']
    n=round(available*5.1);valid={'lines':[{'speaker':'A','text':'甲'*n}]}
    assert validate_lines(valid,c,row)['characters']==n
    with pytest.raises(FlowError) as e:validate_lines({'lines':[{'speaker':'A','text':'甲'*40}]},c,row)
    assert e.value.code=='scene_pacing' and e.value.beat_id==row['beat']['id']

def test_dialogue_and_end_time_do_not_change_event_states():
    c=contract();trace=replay(c);before=copy.deepcopy(trace);scenes=[]
    for row in trace['beats']:
        seconds=row['duration']-row['minimum_action_seconds']-row['beat']['pause']
        scenes.append({'lines':[{'speaker':'A','text':'甲'*round(seconds*5.1)}]})
    body=render(c,trace,scenes)
    assert trace==before and '45.00秒' in body and '声明语速' in body
