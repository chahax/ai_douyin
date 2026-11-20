from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.scenes import advance,initial_state,reviewed_packet,plan_schema,production_scene

SOURCE={'chapters':[{'index':1,'text':'甲把面包交给乙。'}]}
ENT={'entities':[{'id':p,'kind':'character','display_name':p,'source_ids':['CH1-P001']} for p in ['a','b']]}
PLAN={'places':[{'id':'room'},{'id':'other'}],'initial_locations':[{'person':p,'place':'room'} for p in ['a','b']],
 'props':[{'id':'bread1','owner':'a'}],'scenes':[{'id':'s1','place':'room','duration_seconds':4}]}
SCENE={'id':'s1','beats':[{'id':'b1','start':0,'end':4,'present':['a','b'],'camera':'中景','action':'递给面包','emotion':'迟疑',
 'audio':[{'kind':'dialogue','speaker':'a','text':'给你。','start':0,'end':2}], 'moves':[],
 'transfers':[{'prop':'bread1','origin':'a','destination':'b','action':'交给'}],
 'fact_ids':['f'],'source_ids':['CH1-P001'],'adaptation_detail':'镜头设计'}]}

def test_transfer_state_is_carried_and_original_not_mutated():
    prev=initial_state(PLAN,ENT);after=advance(SCENE,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,prev)
    assert after['props']['bread1']=='b' and prev['props']['bread1']=='a'
    with pytest.raises(c.ContractError,match='prop_transfer_origin'):
        advance(SCENE,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,after)

@pytest.mark.parametrize('error',['vanish','absent_speaker','zero_audio','remote_prop','gap'])
def test_actual_continuity_failures_are_rejected(error):
    s=deepcopy(SCENE);state=initial_state(PLAN,ENT);b=s['beats'][0]
    if error=='vanish':b['present']=['a']
    if error=='absent_speaker':b['audio'][0]['speaker']='NARRATOR'
    if error=='zero_audio':b['audio'][0]['end']=0
    if error=='remote_prop':state['locations']['b']='other';b['present']=['a']
    if error=='gap':b['start']=1
    with pytest.raises(c.ContractError):advance(s,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)

def test_review_is_bound_to_actual_record_and_only_selected_dependencies():
    fact={'id':'f','entity_ids':['a'],'statement':'递面包','temporal_scope':'current','certainty':'explicit','source_ids':['CH1-P001']}
    bank={'event':{'facts':[fact]}};reviews={r['id']:{'verdict':'accepted','record_sha256':c.digest(r),'source_sha256':c.digest(SOURCE)} for r in ENT['entities']+[fact]}
    args=(ENT,bank,{'choices':[]},['a'],['f'],SOURCE,{})
    assert reviewed_packet(*args,reviews)['semantic_status']=='selected_dependencies_reviewed'
    fact['statement']='已经吃掉面包'
    with pytest.raises(c.ContractError,match='unreviewed_or_changed'):
        reviewed_packet(*args,reviews)


def test_two_scenes_carry_actors_and_prop_without_reinitializing():
    plan=deepcopy(PLAN)
    plan['scenes'].append({'id':'s2','place':'other','duration_seconds':4})
    first=deepcopy(SCENE)
    first['beats'].append({'id':'exit','start':4,'end':6,'present':['a'],'camera':'门口',
        'action':'乙带着面包离开','emotion':'犹豫','audio':[],
        'moves':[{'person':'b','origin':'room','destination':'other','action':'走入另一间屋子'}],
        'transfers':[],'fact_ids':[],'source_ids':['CH1-P001'],'adaptation_detail':'连接动作'})
    plan['scenes'][0]['duration_seconds']=6
    end=advance(first,plan['scenes'][0],plan,ENT,['f'],SOURCE,initial_state(plan,ENT))
    second=deepcopy(SCENE);second['id']='s2';b=second['beats'][0]
    b.update(present=['b'],audio=[],transfers=[],action='乙拿着面包')
    final=advance(second,plan['scenes'][1],plan,ENT,['f'],SOURCE,end)
    assert final['locations']=={'a':'room','b':'other'}
    assert final['props']['bread1']=='b'
    b['present']=['a','b']
    with pytest.raises(c.ContractError,match='presence_mismatch'):
        advance(second,plan['scenes'][1],plan,ENT,['f'],SOURCE,end)


def test_beat_patch_keeps_other_beats_verbatim():
    scene=deepcopy(SCENE);scene['beats'].append({**deepcopy(scene['beats'][0]),'id':'untouched'})
    changed={**scene['beats'][0],'emotion':'担忧'}
    out=c.apply_record_patches(scene,[{'id':'b1','before_sha256':c.digest(scene['beats'][0]),'replacement':changed}],
        {'b1'},c.digest(scene),lambda _:None)
    assert out['beats'][1]==scene['beats'][1] and out['beats'][0]['emotion']=='担忧'


def test_single_opening_position_per_character_and_no_missing_character():
    plan=deepcopy(PLAN);plan['initial_locations']={'a':'room','b':'other'}
    assert initial_state(plan,ENT)['locations']==plan['initial_locations']
    plan['initial_locations'].pop('b')
    with pytest.raises(ValueError,match='coverage'):initial_state(plan,ENT)
    schema=plan_schema(['a','b','bread'],['f'],['a','b'])['properties']['initial_locations']
    assert not c.schema_issues({'a':'room','b':'other'},schema,'test')
    assert c.schema_issues({'a':'room','b':'other','bread':'room'},schema,'test')


def test_source_change_invalidates_review_even_if_record_unchanged():
    reviews={r['id']:{'verdict':'accepted','record_sha256':c.digest(r),'source_sha256':c.digest(SOURCE)} for r in ENT['entities']}
    changed={'chapters':[{'index':1,'text':'甲没有把面包交给乙。'}]}
    with pytest.raises(c.ContractError,match='unreviewed_or_changed'):
        reviewed_packet(ENT,{}, {'choices':[]},['a'],[],changed,{},reviews)


def test_production_view_derives_state_and_keeps_repair_notes_out_of_performance():
    scene=deepcopy(SCENE);scene['beats'][0].pop('present')
    scene['beats'][0]['adaptation_detail']='旧审核说甲还拿着面包（已过时）'
    before=deepcopy(scene)
    view=production_scene(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))
    beat=view['beats'][0]
    assert beat['present_after_moves']==['a','b']
    assert beat['prop_owners_after_transfers']=={'bread1':'b'}
    assert 'adaptation_detail' not in beat and '旧审核' not in str(view)
    assert scene==before and view['semantic_status']=='unapproved'


def test_empty_transition_defaults_preserve_explicit_moves():
    from src.content_factory.novel_adaptation.scenes import normalize_scene
    original={'beats':[{'id':'x','moves':[{'person':'a'}]}]}
    out=normalize_scene(original)
    assert out['beats'][0]['transfers']==[]
    assert out['beats'][0]['moves']==original['beats'][0]['moves']
    assert 'transfers' not in original['beats'][0]


def test_visual_stage_cannot_rewrite_reviewed_world_claims():
    from src.content_factory.novel_adaptation.scenes import compile_design
    packet={'semantic_status':'selected_dependencies_reviewed','facts':[{'id':'f','statement':'如果米提前吃空才会受罚。'}]}
    raw={'world_fact_ids':['f'],'visual_design':[{'basis':'adaptation_design','description':'暖色灯光'}]}
    result=compile_design(raw,packet)
    assert result['world_framework']=='如果米提前吃空才会受罚。'
    assert result['source_constraints']==packet['facts']
    assert 'world_framework' not in raw
    with pytest.raises(ValueError,match='scope'):compile_design({**raw,'world_fact_ids':['missing']},packet)


def test_opening_state_rejects_location_prose_and_future_owner_ids():
    from src.content_factory.novel_adaptation.scenes import opening_schema,bind_opening
    schema=opening_schema(PLAN,ENT)
    bad={'locations':{'a':'room 床边','b':'other 屋内'},'owners':{'bread1':'unknown-person'}}
    errors=c.schema_issues(bad,schema,'opening')
    assert len(errors)==3
    good={'locations':{'a':'room','b':'other'},'owners':{'bread1':'a'}}
    assert bind_opening(PLAN,good,ENT)['props'][0]['owner']=='a'


def test_context_chapter_does_not_authorize_playing_next_episode():
    source={'chapters':SOURCE['chapters']+[{'index':2,'text':'乙把面包吃掉。'}]}
    plan={**PLAN,'target_chapters':[1]};scene=deepcopy(SCENE)
    scene['beats'][0]['source_ids']=['CH2-P001']
    with pytest.raises(c.ContractError,match='schema'):
        advance(scene,plan['scenes'][0],plan,ENT,['f'],source,initial_state(plan,ENT))

def test_end_phase_speaker_finishes_before_exit_and_information_is_preserved():
    scene=deepcopy(SCENE);beat=scene['beats'][0];beat.pop('present')
    beat['moves']=[{'person':'a','origin':'room','destination':'other','action':'说完离开','phase':'end'}]
    end=advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))
    assert end['locations']['a']=='other'
    assert end['information']['b'][0]['text']=='给你。'
    assert production_scene(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))['beats'][0]['present_after_moves']==['b']
    beat['moves'][0]['phase']='start'
    with pytest.raises(c.ContractError,match='absent_speaker'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))


def test_model_cannot_author_redundant_presence_but_legacy_evidence_is_retained():
    from src.content_factory.novel_adaptation.scenes import model_scene_schema,derive_presence_input
    schema=model_scene_schema(PLAN,ENT,['f'],SOURCE)
    assert c.schema_issues(SCENE,schema,'scene')
    derived=derive_presence_input(SCENE)
    derived['beats'][0]['prop_uses']=[]
    assert not c.schema_issues(derived,schema,'scene')
    assert SCENE['beats'][0]['present']==['a','b']

def test_absent_information_user_and_unheard_history_are_distinct_causes():
    scene=deepcopy(SCENE);b=scene['beats'][0];b.pop('present')
    b['audio']=[];b['transfers']=[]
    b['requires_information']=[{'person':'b','event_id':'prior:line:a0'}]
    prev=initial_state(PLAN,ENT);prev['locations']['b']='other'
    prev['information']={'b':[{'id':'prior:line:a0'}]}
    with pytest.raises(c.ContractError) as error:
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,prev)
    codes={issue.code for issue in error.value.issues}
    assert 'information_user_absent' in codes and 'unheard_information_dependency' not in codes
    prev['locations']['b']='room';prev['information']={}
    with pytest.raises(c.ContractError) as error:
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,prev)
    codes={issue.code for issue in error.value.issues}
    assert 'unheard_information_dependency' in codes and 'information_user_absent' not in codes

def test_entry_after_first_line_cannot_hear_it_but_can_speak_next():
    scene=deepcopy(SCENE);b=scene['beats'][0];b.pop('present');b['transfers']=[]
    b['audio']=[{'kind':'dialogue','speaker':'a','text':'先说。','start':0,'end':1},
                {'kind':'dialogue','speaker':'b','text':'来了。','start':2,'end':3}]
    b['moves']=[{'person':'b','origin':'other','destination':'room','action':'进门','phase':'after_audio','after_audio_index':0}]
    state=initial_state(PLAN,ENT);state['locations']['b']='other'
    end=advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)
    assert [x['id'] for x in end['information']['b']]==['s1:b1:a1']
    view=production_scene(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)
    assert view['beats'][0]['audio_presence']==[{'audio_index':0,'present':['a']},{'audio_index':1,'present':['a','b']}]
    b['moves'][0]['after_audio_index']=1
    with pytest.raises(c.ContractError,match='absent_speaker'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)
    b['moves'][0]['after_audio_index']=99
    with pytest.raises(c.ContractError,match='transition_audio_anchor_missing'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)


def test_audio_boundary_requires_valid_phase_and_index_pair():
    from src.content_factory.novel_adaptation.scenes import scene_schema
    scene=deepcopy(SCENE)
    scene['beats'][0]['moves']=[{'person':'a','origin':'room','destination':'other','action':'离开','phase':'after_audio'}]
    assert c.schema_issues(scene,scene_schema(PLAN,ENT,['f'],SOURCE),'scene')
    scene['beats'][0]['moves'][0].update(phase='start',after_audio_index=0)
    assert c.schema_issues(scene,scene_schema(PLAN,ENT,['f'],SOURCE),'scene')

def test_model_information_refs_are_person_specific_prior_audio_not_fact_ids():
    from src.content_factory.novel_adaptation.scenes import model_scene_schema,derive_presence_input
    scene=derive_presence_input(SCENE)
    scene['beats'][0]['prop_uses']=[]
    scene['beats'][0]['requires_information']=[{'person':'a','event_id':'f'}]
    schema=model_scene_schema(PLAN,ENT,['f'],SOURCE,initial_state(PLAN,ENT))
    assert c.schema_issues(scene,schema,'scene')
    prior=initial_state(PLAN,ENT)
    prior['information']={'a':[{'id':'past:b:a0'}],'b':[]}
    schema=model_scene_schema(PLAN,ENT,['f'],SOURCE,prior)
    scene['beats'][0]['requires_information']=[{'person':'a','event_id':'past:b:a0'}]
    assert not c.schema_issues(scene,schema,'scene')
    scene['beats'][0]['requires_information'][0]['person']='b'
    assert c.schema_issues(scene,schema,'scene')

def test_visible_bread_cannot_reappear_in_previous_holders_hands():
    scene=deepcopy(SCENE);scene['beats'][0].pop('present')
    state=initial_state(PLAN,ENT);state['props']['bread1']='b'
    scene['beats'][0]['transfers']=[]
    scene['beats'][0]['prop_uses']=[{'prop':'bread1','holder':'a'}]
    with pytest.raises(c.ContractError,match='visible_prop_owner_mismatch'):
        advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)
    scene['beats'][0]['prop_uses'][0]['holder']='b'
    assert advance(scene,PLAN['scenes'][0],PLAN,ENT,['f'],SOURCE,state)['props']['bread1']=='b'

def test_generation_evidence_is_selected_facts_not_entire_context_chapter():
    from src.content_factory.novel_adaptation.scenes import model_scene_schema,derive_presence_input
    source={'chapters':[{'index':1,'text':'甲把面包交给乙。\n如果米提前吃空才会挨打。'}]}
    scene=derive_presence_input(SCENE);scene['beats'][0]['prop_uses']=[]
    schema=model_scene_schema(PLAN,ENT,['f'],source,initial_state(PLAN,ENT),['CH1-P001'])
    assert not c.schema_issues(scene,schema,'scene')
    scene['beats'][0]['source_ids']=['CH1-P002']
    assert c.schema_issues(scene,schema,'scene')
