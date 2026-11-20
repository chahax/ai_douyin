import json
from contextlib import nullcontext
from pathlib import Path
import pytest
from scripts import run_isolated_nodes_trial as m
from src.content_factory.novel_adaptation import isolated_nodes as n,audio_first as a,audiovisual_transcription as av,contracts as c

def sample():
    packet=av.packet({'chapters':[{'index':1,'text':'小林说：“出发吧。”\n\n听说要去公园，孩子笑了。'}]},[],[1])
    raw={'items':[{'source_id':'CH1-P001','kind':'dialogue','speaker':'小林','text':'出发吧。','evidence_ids':['CH1-P001']}]}
    return packet,raw


def test_full_max_trial_clears_inherited_picture_only_and_keeps_prior(tmp_path):
    prior=Path('data/corpus_production_trials/20261030_location_context_review')
    before=m.read(prior/'STATE.json');run=tmp_path/'max'
    m.prepare(run,prior,'max',32768,'用最新的模型和强度跑一遍试试')
    plan=m.read(run/'PLAN.json')
    assert not plan.get('isolated_picture_only') and not plan.get('isolated_review_only')
    assert plan['inference']['writer_effort']=='max' and plan['inference']['writer_max_tokens']==32768
    assert plan['max_calls']==before['calls_started']+3
    assert m.read(run/'STATE.json')['completed_stages']==[]
    assert m.read(run/'STATE.json')['retained_unknowns']==before['retained_unknowns']
    assert not (run/'AUDIO_BANK.json').exists()
    assert m.read(prior/'STATE.json')==before

def test_stage_contracts_reject_other_stage_outputs():
    packet,raw=sample()
    assert c.schema_issues({'text':'越权生成画面'},a.schema(packet),'audio')
    with pytest.raises(c.ContractError):n.validate_picture(raw,packet)
    assert c.schema_issues({'items':[]},c.obj(text=c.TEXT),'review')
    n.validate_picture({'text':'候选','gaps':[{'source_id':'CH1-P002','missing_content':'去公园的告知'}]},packet)
    with pytest.raises(c.ContractError):n.validate_picture({'text':'候选','gaps':[{'source_id':'CH9-P001','missing_content':'猜测'}]},packet)

def test_only_needed_handoff_data_no_previous_prompts_or_reviews():
    packet,raw=sample();bank=a.build_bank(raw,packet)
    bank['note']='上一节点不应传入的说明';bank['evidence_questions']=[{'text':'不应传给画面'}]
    payload=n.picture_payload(packet,bank)
    assert set(payload)=={'source','audio_items'}
    assert set(payload['audio_items'][0])=={'audio_id','source_id','kind','speaker','text','evidence_ids'}
    assert '不应传' not in json.dumps(payload,ensure_ascii=False)
    review=n.review_payload(packet,bank,'完整候选',[],{'issues':[],'rendered':'重复稿','visual_source_evidence':['重复原文']})
    assert review['candidate']=='完整候选' and 'text' not in review['audio_index'][0]
    assert '重复' not in json.dumps(review,ensure_ascii=False)
    assert n.AUDIO not in n.PICTURE and n.PICTURE not in n.REVIEW

def test_three_fresh_nodes_only_and_gap_reaches_reviewer(tmp_path,monkeypatch):
    run=tmp_path/'run';m.prepare(run,Path('data/corpus_production_trials/20261030_source_preservation_review'))
    packet,raw=sample();(run/'INPUT.json').write_text(json.dumps(packet),encoding='utf-8');calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,prompt,payload,schema));self.state['calls_started']+=1
            if name=='audio':return raw
            if name=='picture':return {'text':'场次：1\n时间：白天\n地点：不强调\n人物：小林\n画面[CH1-P001-P002]：小林说话。\n声音[A001]\n原段：CH1-P001-P002','gaps':[{'source_id':'CH1-P002','missing_content':'告知目的地'}]}
            return {'text':'声音缺告知，保持未验收。'}
    monkeypatch.setattr(m,'DirectLedger',Fake);monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert [x[0] for x in calls]==['audio','picture','comparison']
    assert [x[1] for x in calls]==[n.AUDIO,n.PICTURE,n.REVIEW]
    assert set(calls[0][2])=={'source'}
    assert set(calls[1][2])=={'source','audio_items'}
    assert calls[2][2]['gaps']==m.read(run/'GAPS.json')
    assert calls[2][2]['candidate']==(run/'screenplay.md').read_text('utf-8')
    assert m.read(run/'STATE.json')['calls_started']==323
    assert not m.read(run/'REVIEW_BINDING.json')['semantic_acceptance']
    with pytest.raises(ValueError,match='not_fresh'):m.execute(run)

def test_raw_review_uses_own_prompt_and_keeps_original_boundary(tmp_path,monkeypatch):
    prior=Path('data/corpus_production_trials/20261030_isolated_nodes');run=tmp_path/'audit';m.prepare_review(run,prior);calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,prompt,payload));self.state['calls_started']+=1;return {'text':'原稿审查'}
    monkeypatch.setattr(m,'DirectLedger',Fake);monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert len(calls)==1 and calls[0][0]=='comparison' and calls[0][1]==n.REVIEW
    assert calls[0][2]['candidate']['raw_picture']==(prior/'layout.txt').read_text('utf-8')
    assert calls[0][2]['gaps']==m.read(prior/'GAPS.json')
    assert m.read(run/'STATE.json')['calls_started']==m.read(run/'PLAN.json')['max_calls']==323
    assert not (run/'screenplay.md').exists()
