from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import story_text as s
from src.content_factory.novel_adaptation.contracts import digest

SOURCE={'chapters':[{'index':1,'text':'甲把信交给乙。乙读信后离开。'},{'index':2,'text':'第二天甲找乙。'}]}
PACKET={'source_sha256':digest(SOURCE),'entities':[{'id':p,'kind':'character'} for p in ('a','b')]}
OUTLINE={'title':'信','premise':'一封信改变决定','beats':[{'id':'e1','source_ids':['CH1-P001'],
 'time_layer':'current','participants':['a','b'],'location':'客厅','situation':'甲持信','turn':'乙读信','outcome':'乙离开'}],'omissions':[]}
DRAFT={'title':'信','scenes':[{'id':'s1','beat_ids':['e1'],'location':'客厅','cast':['a','b'],
 'action':'甲递信，乙接过读完，起身走出房间。','lines':[{'kind':'dialogue','speaker':'a','text':'给你。'}],
 'ending':'甲留在客厅，乙带信离开。','adaptation_notes':[]}]}

class Fake:
    def __init__(self):self.calls=[]
    def call(self,name,role,prompt,payload,schema):
        self.calls.append((name,payload,schema))
        return deepcopy(OUTLINE if name=='STORY_EVENTS' else DRAFT)

def test_two_distinct_stages_keep_full_source_and_defer_shots():
    ledger=Fake();saved={}
    r=s.generate(ledger,SOURCE,PACKET,[1],lambda k,v:saved.update({k:v}))
    assert [x[0] for x in ledger.calls]==['STORY_EVENTS','STORY_DIALOGUE']
    assert len(ledger.calls[0][1]['complete_chapters'])==2
    assert ledger.calls[1][1]['outline']==OUTLINE
    assert r['semantic_acceptance'] is False and r['fixed_duration_seconds'] is None
    assert 'STORY_DIALOGUE_NATIVE' in saved

@pytest.mark.parametrize('case',['future_source','duplicate_beat','camera_field'])
def test_planning_contract_rejects_cross_scope_or_mixed_responsibilities(case):
    v=deepcopy(OUTLINE)
    if case=='future_source':v['beats'][0]['source_ids']=['CH2-P001']
    if case=='duplicate_beat':v['beats'].append(deepcopy(v['beats'][0]))
    if case=='camera_field':v['beats'][0]['camera']='特写'
    with pytest.raises(ValueError):s.validate_outline(v,SOURCE,PACKET,[1])

@pytest.mark.parametrize('case',['absent','narrator','seconds','missing_beat'])
def test_draft_checks_identity_and_coverage_without_timing_inventory(case):
    v=deepcopy(DRAFT);outline=deepcopy(OUTLINE)
    if case=='absent':v['scenes'][0]['cast']=['b']
    if case=='narrator':v['scenes'][0]['lines'][0]['speaker']='NARRATOR'
    if case=='seconds':v['scenes'][0]['seconds']=240
    if case=='missing_beat':outline['beats'].append({**outline['beats'][0],'id':'e2'})
    with pytest.raises(ValueError):s.validate_draft(v,PACKET,outline)

def test_bad_outline_stops_before_drafting_and_preserves_native_failure():
    ledger=Fake();saved={}
    def broken(*args):ledger.calls.append(args);return {**OUTLINE,'camera':'bad'}
    ledger.call=broken
    with pytest.raises(ValueError):s.generate(ledger,SOURCE,PACKET,[1],lambda k,v:saved.update({k:v}))
    assert len(ledger.calls)==1 and 'STORY_EVENTS_NATIVE' in saved


def test_combined_route_preserves_reviewed_facts_and_separates_later_chapters():
    packet=deepcopy(PACKET);packet['semantic_status']='selected_dependencies_reviewed'
    packet['facts']=[{'id':'f1','source_ids':['CH1-P001'],'statement':'乙读信后离开。','certainty':'explicit','temporal_scope':'current'},
                     {'id':'f2','source_ids':['CH2-P001'],'statement':'次日甲找乙。','certainty':'explicit','temporal_scope':'current'}]
    original=deepcopy(packet);ledger=Fake();saved={}
    s.generate(ledger,SOURCE,packet,[1],lambda k,v:saved.update({k:v}),use_reviewed_materials=True)
    material=ledger.calls[0][1]['reviewed_materials']
    assert material['target_facts'][0]['fact']==packet['facts'][0]
    assert material['context_only_facts'][0]['fact']==packet['facts'][1]
    assert ledger.calls[1][1]['reviewed_materials']==material and packet==original


def test_unreviewed_packet_cannot_be_promoted_by_combined_route():
    with pytest.raises(ValueError,match='reviewed_materials_missing'):
        s.reviewed_materials(SOURCE,PACKET,[1])


def test_guard_withholds_later_explanations_and_requires_scene_timeline():
    packet=deepcopy(PACKET);packet['semantic_status']='selected_dependencies_reviewed'
    packet['facts']=[{'id':'later','source_ids':['CH2-P001'],'statement':'不能提前推定的后章解释'}]
    ledger=Fake();base=ledger.call
    def call(*args):
        result=base(*args)
        if args[0]=='STORY_DIALOGUE':result['scenes'][0]['timeline']='current'
        return result
    ledger.call=call;saved={};before=deepcopy(SOURCE)
    s.generate(ledger,SOURCE,packet,[1],lambda k,v:saved.update({k:deepcopy(v)}),use_reviewed_materials=True,scope_guard=True)
    for _,payload,_ in ledger.calls:
        assert [x['index'] for x in payload['complete_chapters']]==[1]
        assert payload['reviewed_materials']['context_only_facts']==[]
    assert saved['AUTHORING_SCOPE']['withheld_fact_ids']==['later'] and SOURCE==before
    with pytest.raises(ValueError):s.validate_draft(DRAFT,PACKET,OUTLINE,explicit_timeline=True)


def test_direct_story_bypasses_outline_and_binds_original_source_without_accepting_content():
    calls=[];saved={}
    class Writer:
        def call(self,name,role,prompt,payload,schema):
            calls.append(name)
            assert set(schema['properties'])=={'title','screenplay','source_ids'}
            assert '甲把信交给乙。乙读信后离开。' in payload['complete_chapters'][0]['text_with_paragraph_ids']
            assert 'scene.timeline' not in prompt
            return {'title':'信','screenplay':'客厅，甲递信给乙。乙读完带信离开。','source_ids':['CH1-P001']}
    r=s.generate(Writer(),SOURCE,PACKET,[1],lambda k,v:saved.update({k:v}),direct_story=True,scope_guard=True)
    assert calls==['STORY_DIRECT'] and 'STORY_EVENTS_NATIVE' not in saved
    assert saved['STORY_SOURCE_EVIDENCE']['CH1-P001']['text']==SOURCE['chapters'][0]['text']
    assert not r['semantic_acceptance'] and not r['outline_required']
