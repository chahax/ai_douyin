from copy import deepcopy
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation import contracts as c

SOURCE={'chapters':[{'index':1,'text':'甲给乙面包，乙走出房间。'}]}
ENT=[{'id':p,'kind':'character','display_name':p,'source_ids':['CH1-P001']} for p in ['a','b']]
FACT={'id':'f','entity_ids':['a','b'],'statement':'甲给乙面包。','source_ids':['CH1-P001'],'temporal_scope':'current','certainty':'explicit','category':'event'}
PACKET={'entities':ENT,'facts':[FACT],'evidence':{'CH1-P001':{}},'source_sha256':c.digest(SOURCE),'semantic_status':'selected_dependencies_reviewed'}
DESIGN={'title':'面包','world_fact_ids':['f'],'visual_design':[],
 'places':[{'id':p,'description':p,'basis':'adaptation_design'} for p in ['room','other']],
 'initial_locations':{'a':'room','b':'other'},'props':[{'id':'bread','kind':'面包','owner':'a','description':'一块面包'}],
 'scenes':[{'id':id,'place':place,'duration_seconds':20,'objective':'交接后的场景','fact_ids':['f']} for id,place in [('s1','room'),('s2','other')]]}

def beat(id,start):
    return {'id':id,'start':start,'end':start+10,'camera':'中景','action':'自然动作','emotion':'平静',
        'audio':[],'prop_uses':[],'fact_ids':['f'],'source_ids':['CH1-P001'],'adaptation_detail':'构图设计'}

class Fake:
    def __init__(self):self.calls=[]
    def call(self,name,role,prompt,payload,schema):
        self.calls.append((name,deepcopy(payload)))
        if name=='DESIGN':
            value=deepcopy(DESIGN);value.pop('initial_locations')
            for prop in value['props']:prop.pop('owner')
            return value
        if name=='OPENING_STATE':return {'locations':{'a':'room','b':'other'},'owners':{'bread':'a'}}
        if name=='FINAL_REVIEW':return {'verdict':'pass','issues':[]}
        b1,b2=beat('b1',0),beat('b2',10)
        if name=='SCENE_s1':
            b1['moves']=[{'person':'b','origin':'other','destination':'room','action':'走进来'}]
            b1['transfers']=[{'prop':'bread','origin':'a','destination':'b','action':'交给'}]
            b1['audio']=[{'kind':'dialogue','speaker':'a','text':'给你。','start':1,'end':3}]
            b2['moves']=[{'person':'b','origin':'room','destination':'other','action':'走出去'}]
            return {'id':'s1','beats':[b1,b2]}
        b1['requires_information']=[{'person':'b','event_id':'s1:b1:a0'}]
        b1['audio']=[{'kind':'inner','speaker':'b','text':'谢谢。','start':1,'end':3}]
        return {'id':'s2','beats':[b1,b2]}

def test_full_workflow_compiles_facts_and_carries_state_and_information(tmp_path):
    fake=Fake()
    result,review=run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2})
    assert result['design']['world_framework']==FACT['statement']
    assert result['end_state']['props']['bread']=='b'
    assert result['end_state']['locations']=={'a':'room','b':'other'}
    assert [n for n,_ in fake.calls]==['DESIGN','OPENING_STATE','SCENE_s1','SCENE_s2','FINAL_REVIEW']
    encoded=fake.calls[3][1]['previous_state']
    assert encoded['information_event_catalog'][encoded['information']['b'][0]]['text']=='给你。'
    assert 'information' not in fake.calls[-1][1]['candidate']['end_state']
    assert (tmp_path/'PRODUCTION_VIEWS_UNAPPROVED.json').exists()
    assert review['verdict']=='pass' # simulated protocol result, not content acceptance


def test_content_led_pacing_removes_required_scene_target_and_records_gate(tmp_path):
    fake=Fake()
    result,_=run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2,'pacing_policy':{'max_scene_seconds':30}})
    scene_payload=next(payload for name,payload in fake.calls if name=='SCENE_s1')
    assert 'duration_seconds' not in scene_payload['current_scene']
    assert scene_payload['pacing_policy']['max_scene_seconds']==30
    assert result['design']['scenes'][0]['duration_seconds']==20
    assert (tmp_path/'s1_PACING.json').exists()

def test_fresh_workflow_enforces_reviewed_source_event_even_when_state_is_consistent(tmp_path):
    contract={'events':[{'id':'handoff','kind':'transfer','scene_id':'s1','source_ids':['CH1-P001'],
        'prop':'bread','origin':'a','destination':'b'}]}
    review={'verdict':'accepted','source_sha256':c.digest(SOURCE),'contract_sha256':c.digest(contract)}
    class MissingTransfer(Fake):
        def call(self,name,role,prompt,payload,schema):
            if name=='PATCH_s1_0':
                self.calls.append((name,deepcopy(payload)))
                assert payload['allowed_fields']=={'b1':['transfers'],'b2':['transfers']}
                return {'patches':[{'id':'b1','changes':{'transfers':[
                    {'prop':'bread','origin':'a','destination':'b','action':'交给'}]}}]}
            result=super().call(name,role,prompt,payload,schema)
            if name=='SCENE_s1':result['beats'][0]['transfers']=[]
            return result
    fake=MissingTransfer()
    result,_=run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2,'require_source_events':True},
        source_contract=contract,contract_review=review)
    assert result['end_state']['props']['bread']=='b'
    assert result['source_event_gate']=='reviewed_contract_enforced'
    assert any(name=='PATCH_s1_0' for name,_ in fake.calls)


def test_required_source_event_gate_stops_before_any_scene_call(tmp_path):
    import pytest
    fake=Fake()
    with pytest.raises(ValueError,match='reviewed_source_events_required'):
        run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2,'require_source_events':True})
    assert [name for name,_ in fake.calls]==['DESIGN','OPENING_STATE']

def test_reviewed_design_checkpoint_skips_layout_regeneration_and_binds_source(tmp_path):
    from src.content_factory.novel_adaptation.scenes import compile_design
    import pytest
    checkpoint=compile_design(DESIGN,PACKET)
    checkpoint['target_chapters']=[1]
    contract={'events':[{'id':'handoff','kind':'transfer','scene_id':'s1','source_ids':['CH1-P001'],
        'prop':'bread','origin':'a','destination':'b'}]}
    review={'verdict':'accepted','source_sha256':c.digest(SOURCE),'contract_sha256':c.digest(contract)}
    fake=Fake()
    result,_=run_workflow(tmp_path,fake,SOURCE,PACKET,{'scene_count':2,'require_source_events':True},
        design_checkpoint=checkpoint,source_contract=contract,contract_review=review)
    assert [name for name,_ in fake.calls]==['SCENE_s1','SCENE_s2','FINAL_REVIEW']
    assert result['source_event_gate']=='reviewed_contract_enforced'
    changed=deepcopy(checkpoint);changed['world_framework']='擅自增加父亲亡故'
    with pytest.raises(ValueError,match='source_facts_changed'):
        run_workflow(tmp_path/'invalid',Fake(),SOURCE,PACKET,{'scene_count':2},design_checkpoint=changed)

def test_next_episode_entry_uses_reviewed_handoff_without_resetting_props(tmp_path):
    from src.content_factory.novel_adaptation.scenes import compile_design
    from src.content_factory.novel_adaptation.handoff import export_handoff
    old={'design':deepcopy(DESIGN),'end_state':{'locations':{'a':'room','b':'other'},'props':{'bread':'b'},
        'information':{'b':[{'id':'s1:b1:a0','speaker':'a','kind':'dialogue','text':'给你。'}]}}}
    review={'verdict':'accepted_text_pilot','candidate_sha256':c.digest(old),'source_sha256':c.digest(SOURCE)}
    h=export_handoff(old,{'entities':ENT},SOURCE,review,book_id='book',episode_id='E01',timeline_id='CURRENT')
    checkpoint=compile_design(DESIGN,PACKET);checkpoint['props'][0]['owner']='b';checkpoint['target_chapters']=[1]
    class Continued(Fake):
        def call(self,name,role,prompt,payload,schema):
            result=super().call(name,role,prompt,payload,schema)
            if name=='SCENE_s1':
                assert payload['previous_state']['props']['bread']=='b'
                result['beats'][0]['transfers']=[]
                result['beats'][0]['audio'][0]['text']='你回来了。'
                result['beats'][0]['requires_information']=[{'person':'b','event_id':'E01:s1:b1:a0'}]
            return result
    result,_=run_workflow(tmp_path,Continued(),SOURCE,PACKET,{'scene_count':2,'book_id':'book','episode_id':'E02',
        'timeline_id':'CURRENT','handoff_sha256':c.digest(h)},design_checkpoint=checkpoint,continuation=h)
    assert result['previous_episode_handoff_sha256']==c.digest(h)
    assert result['end_state']['props']['bread']=='b'
    assert result['end_state']['information']['b'][0]['id']=='E01:s1:b1:a0'
