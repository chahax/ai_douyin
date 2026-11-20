from copy import deepcopy
import json,pytest
from src.content_factory.novel_adaptation.context_projection import encode_state,decode_state
from src.content_factory.novel_adaptation.workflow import compact_design


def test_shared_history_roundtrip_is_lossless_and_original_unchanged():
    event={'id':'e1','text':'Full dialogue retained. '*100,'speaker':'a'}
    design={'recipes':[{'id':'cook','inputs':['food']}]}
    state={'locations':{'a':'room'},'information':{p:[deepcopy(event)] for p in ['a','b','c','d']},
           'recipes':{'cook':deepcopy(design['recipes'][0])},'recipes_completed':[]}
    old=deepcopy(state);encoded=encode_state(state,design)
    assert state==old and decode_state(encoded,design)==state
    assert len(json.dumps(encoded))<len(json.dumps(state))/2


def test_conflicting_information_ids_are_not_silently_merged():
    with pytest.raises(ValueError,match='information_id_conflict'):
        encode_state({'information':{'a':[{'id':'e','text':'one'}],'b':[{'id':'e','text':'two'}]}},{})


def test_column_groups_roundtrip_heterogeneous_rows_and_null_without_omissions():
    state={'information':{'a':[{'id':'x','text':'全文','speaker':None},{'id':'y','text':'另一句','time':3}],
                          'b':[{'id':'x','text':'全文','speaker':None}]}}
    old=deepcopy(state);encoded=encode_state(state,{},compact_events=True)
    assert state==old and decode_state(encoded,{})==state
    assert 'information_event_catalog' not in encoded and len(encoded['information_event_groups'])==2
    bad=deepcopy(encoded);bad['information_event_groups'][0]['rows'][0].append('extra')
    with pytest.raises(ValueError,match='row_length'):decode_state(bad,{})


def test_single_scene_context_keeps_adjacent_plan_and_complete_registry():
    design={'world_framework':'duplicate source prose','world_fact_ids':['f'],
        'props':[{'id':'door','stationary':True}],'recipes':[{'id':'cook'}],
        'scenes':[{'id':str(i),'objective':'full'+str(i),'place':'room','fact_ids':['f']} for i in range(6)]}
    old=deepcopy(design);view=compact_design(design,'2')
    assert design==old and view['props']==design['props'] and view['recipes']==design['recipes']
    for i in (1,2,3):assert view['scenes'][i]['objective']==design['scenes'][i]['objective']
    for i in (0,4,5):assert view['scenes'][i]=={k:v for k,v in design['scenes'][i].items() if k!='objective'}
