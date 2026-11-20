from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import contracts as c


SOURCE={'chapters':[{'index':1,'text':'苏墨躺在床上。\n老六和二哥在屋内。\n原主过去欺负他们。'}]}
ENTITIES={'entities':[
 {'id':'su','kind':'character','display_name':'原主苏墨 / 穿书后苏墨','source_ids':['CH1-P001','CH1-P003']},
 {'id':'six','kind':'character','display_name':'老六','source_ids':['CH1-P002']},
 {'id':'two','kind':'character','display_name':'二哥','source_ids':['CH1-P002']},
 {'id':'room','kind':'place','display_name':'苏墨卧室（工作名称）','source_ids':['CH1-P002']}]}


def test_display_label_is_not_literal_source_claim():
    assert c.validate_entities(ENTITIES,SOURCE)==ENTITIES


def test_indexed_chapters_preserve_complete_original_text_and_whitespace():
    import re
    source={'chapters':[{'index':1,'text':'甲\r\n\r\n乙\n  \n丙'}]}
    annotated=c.indexed_chapters(source)[0]['text_with_paragraph_ids']
    restored=re.sub(r'^\[CH1-P\d+\] ', '', annotated, flags=re.M)
    assert restored==source['chapters'][0]['text']
    assert '[CH1-P003]' in annotated


def test_bad_source_refs_report_all_addresses_without_rewriting_names():
    bad=deepcopy(ENTITIES)
    bad['entities'][0]['source_ids']=['CH999-P001']
    bad['entities'][1]['source_ids']=['CH999-P002']
    with pytest.raises(c.ContractError) as exc:c.validate_entities(bad,SOURCE)
    assert len(exc.value.issues)==2
    assert {e.owner for e in exc.value.issues}=={'identity'}
    assert exc.value.issues[0].path=='/entities/0/source_ids/0'


def test_same_form_of_address_can_refer_to_different_entities_in_context():
    source={'chapters':[{'index':1,'text':'弟弟喊哥哥。\n另一家孩子也喊哥哥。'}]}
    rows={'entities':[{'id':str(i),'kind':'character','display_name':str(i),
        'source_ids':[f'CH1-P00{i}']} for i in (1,2)]}
    c.validate_entities(rows,source)


def test_evidence_is_original_program_bound_not_model_quote():
    fact={'facts':[{'id':'f','entity_ids':['su'],'statement':'躺床',
        'temporal_scope':'current','certainty':'explicit','source_ids':['CH1-P001']}]}
    c.validate_facts(fact,SOURCE,ENTITIES,'character')
    bound=c.bind_evidence(fact,SOURCE)
    assert bound['evidence']['CH1-P001']['text']=='苏墨躺在床上。'
    assert bound['semantic_status']=='unreviewed'


def test_unknown_unrelated_fact_does_not_block_scene_but_dependency_does():
    bank={'facts':[{'id':'f','entity_ids':['su'],'statement':'躺床','temporal_scope':'current',
        'certainty':'explicit','source_ids':['CH1-P001']},
        {'id':'q','entity_ids':['su'],'statement':'住房产权未明','temporal_scope':'unspecified',
        'certainty':'unknown','source_ids':['CH1-P001']}]}
    packet=c.build_scene_packet(ENTITIES,{'character':bank},{'choices':[]},['su'],['f'],SOURCE,{})
    assert [f['id'] for f in packet['facts']]==['f']
    with pytest.raises(c.ContractError):
        c.build_scene_packet(ENTITIES,{'character':bank},{'choices':[]},['su'],['q'],SOURCE,{})


def test_record_patch_preserves_every_unselected_record_and_original():
    replacement=deepcopy(ENTITIES['entities'][0]);replacement['display_name']='苏墨'
    patch={'id':'su','before_sha256':c.digest(ENTITIES['entities'][0]),'replacement':replacement}
    out=c.apply_record_patches(ENTITIES,[patch],{'su'},c.digest(ENTITIES),lambda v:c.validate_entities(v,SOURCE))
    assert out['entities'][1:]==ENTITIES['entities'][1:]
    assert ENTITIES['entities'][0]['display_name']!='苏墨'
    assert out['entities'][0]['display_name']=='苏墨'
    with pytest.raises(ValueError,match='outside_authorized'):
        c.apply_record_patches(ENTITIES,[patch],{'six'},c.digest(ENTITIES),lambda _:None)
    with pytest.raises(ValueError,match='stale_patch'):
        c.apply_record_patches(ENTITIES,[patch],{'su'},'wrong',lambda _:None)


def test_new_room_can_be_added_without_rewriting_or_overwriting_old_entities():
    addition={'id':'room2','kind':'place','display_name':'另一间屋子','source_ids':['CH1-P002']}
    out=c.append_records(ENTITIES,[addition],{'room2'},c.digest(ENTITIES),lambda x:c.validate_entities(x,SOURCE))
    assert out['entities'][:-1]==ENTITIES['entities']
    with pytest.raises(ValueError):
        c.append_records(ENTITIES,[ENTITIES['entities'][0]],{'su'},c.digest(ENTITIES),lambda _:None)


def scene(**changes):
    return {'place_id':'room','initial_locations':{},'transitions':[],
            'end_cast':['su','six','two'],**changes}


def test_no_disappearance_without_exit():
    prev={'su':'room','six':'room','two':'room'}
    with pytest.raises(c.ContractError) as exc:
        c.validate_screen_presence(scene(end_cast=['su']),prev,{'su','six','two'},{'room','hall'})
    assert exc.value.issues[0].owner=='continuity'
    assert exc.value.issues[0].code=='cast_location_mismatch'


@pytest.mark.parametrize('value',[
    {'place_id':'imaginary','initial_locations':{},'transitions':[],'end_cast':[]},
    {'place_id':'room','initial_locations':{},'transitions':[],'end_cast':['su','su']},
])
def test_invalid_scene_place_and_duplicate_actor_cannot_pass(value):
    with pytest.raises(c.ContractError):
        c.validate_screen_presence(value,{'su':'room'},{'su'},{'room'})


def test_explicit_exits_allow_room_to_become_empty_of_children():
    prev={'su':'room','six':'room','two':'room'}
    transitions=[{'person':who,'from':'room','to':'hall','action':'跑出房间'} for who in ('six','two')]
    end=c.validate_screen_presence(scene(transitions=transitions,end_cast=['su']),prev,prev,{'room','hall'})
    assert end=={'su':'room','six':'hall','two':'hall'}
    assert prev['six']=='room'


def test_cannot_reset_known_person_location_or_introduce_unknown_person():
    with pytest.raises(c.ContractError) as exc:
        c.validate_screen_presence(scene(initial_locations={'six':'hall'}),
            {'su':'room','six':'room','two':'room'},{'su','six','two'},{'room','hall'})
    assert any(e.code=='silent_location_reset' for e in exc.value.issues)
    with pytest.raises(c.ContractError):
        c.validate_screen_presence(scene(initial_locations={'stranger':'room'}),{}, {'su'}, {'room'})
