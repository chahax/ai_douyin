import json
from contextlib import nullcontext
import pytest
from scripts import run_restricted_transcription as m
from src.content_factory.novel_adaptation import restricted_transcription as r,audiovisual_transcription as a

def test_background_exact_quotes_no_identity_inference():
    source={'chapters':[{'index':1,'text':'他说：我是你爸爸。\n\n旁人不相信。'},{'index':2,'text':'今天周六。\n\n他们走了。'}]}
    p=a.packet(source,[1],[2]);b=r.background(p)
    assert b['excerpts']==[{'id':'CH1-P001','text':'他说：我是你爸爸。','role':'context_only'},{'id':'CH2-P001','text':'今天周六。','role':'target'}]
    assert '人物陈述仍是人物陈述' in r.render_background(b)

def test_audio_types_and_unknown_label_are_enforced():
    p=a.packet({'chapters':[{'index':1,'text':'姐姐真好看。'}]},[],[1])
    good='场次：1\n对白[待核]：姐姐真好看。\n旁白：他不想哥哥打架。\n原段：CH1-P001'
    assert r.validate(good,p)['format_passed']
    assert not r.validate(good.replace('[待核]','[待核（一名哥哥）]'),p)['format_passed']
    assert not r.validate(good+'\n心声：他不想哥哥打架。',p)['format_passed']
    assert not r.validate(good.replace('CH1-P001','CH9-P001'),p)['format_passed']
    assert not r.validate(good+'\n世界背景：主角占据孩子身体。',p)['format_passed']
    assert not r.validate(good,p)['semantic_acceptance']

def test_anchored_dialogue_quotes_order_and_evidence():
    p=a.packet({'chapters':[{'index':1,'text':'小明问：“走吗？”\n\n小红点头。\n\n“走吧。”'}]},[],[1])
    head='场次：1\n时间：下午\n地点：屋内\n人物：小明、小红\n'
    body='对白[小明|CH1-P001|CH1-P001]：“走吗？”\n画面[CH1-P002]：小红点头。\n对白[待核|CH1-P003|-]：“走吧。”\n原段：CH1-P001—CH1-P003'
    good=r.anchored_diagnostics(head+body,p)
    assert good['format_passed'] and not good['semantic_acceptance']
    assert good['attribution_evidence'][0]['original_context'][0]['text']=='小明问：“走吗？”'
    for bad,code in [
        (body.replace('走吗？','回家吧。'),'dialogue_not_source_substring'),
        (body.replace('小明|CH1-P001|CH1-P001','小红|CH1-P001|CH1-P001'),'speaker_evidence_not_local_or_missing'),
        (body+'\n画面[CH1-P001]：回到开头。','source_order_reversal'),
        (body.replace('待核|CH1-P003|-','待核（哥哥）|CH1-P003|-'),'unknown_identity_must_remain_empty')]:
        assert code in [i['code'] for i in r.anchored_diagnostics(head+bad,p)['issues']]
    assert not r.anchored_diagnostics(head.replace('地点：屋内\n','')+body,p)['format_passed']

def test_prompt_ids_and_indirect_speech_punctuation(monkeypatch):
    p=a.packet({'chapters':[{'index':20,'text':'甲问乙能否送货。'}]},[],[20])
    assert 'CH20-P001' in r.prompt(2,p)
    assert 'CH2-P' not in r.prompt(2,p)
    good='场次：1\n时间：下午\n地点：店内\n人物：甲、乙\n对白[甲|CH20-P001|CH20-P001]：能否送货？\n原段：CH20-P001'
    assert r.anchored_diagnostics(good,p)['format_passed']
    monkeypatch.setattr(r,'PROMPT_V2',r.PROMPT_V2+'画面[CH2-P001]：错误示例')
    with pytest.raises(ValueError,match='prompt_example_id_outside_source'):r.prompt(2,p)

def test_ellipsis_guidance_preserves_source_and_does_not_classify_silence():
    text='他问：“鱼丸吃吗？”\n\n……\n\n最后点完了菜。\n\n他停住了，……一句话也说不出。\n\n“……”'
    p=a.packet({'chapters':[{'index':3,'text':text}]},[],[3]);before=json.dumps(p,ensure_ascii=False)
    result=r.coverage_guidance(p)
    assert [x['id'] for x in result['ellipsis_contexts']]==['CH3-P002']
    assert result['ellipsis_contexts'][0]['context'][2]['text']=='最后点完了菜。'
    assert json.dumps(p,ensure_ascii=False)==before
    assert '\n\n'.join(x['text'] for x in p['chapters'][0]['paragraphs'])==text
    # Explicit hesitation and quoted silence remain full source statements, not discarded layout.
    assert p['chapters'][0]['paragraphs'][3]['text']=='他停住了，……一句话也说不出。'

def test_focus_scope_and_both_requests_keep_complete_source(tmp_path,monkeypatch):
    run=tmp_path/'focused';prior=m.Path('data/corpus_production_trials/20261030_restricted_round2')
    m.prepare_focus(run,prior);calls=[]
    assert m.read(run/'INPUT.json')==m.read(prior/'INPUT.json')
    assert m.read(run/'PLAN.json')['max_calls']==310
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1
            return {'text':'场次：1\n时间：上午\n地点：店里\n人物：甲\n画面[CH21-P034]：点完菜。\n原段：CH21-P030—CH21-P034'}
    monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert len(calls)==2
    assert calls[0][1]['chapters']==m.read(prior/'INPUT.json')['chapters']
    assert calls[0][1]['coverage_guidance']==calls[1][1]['coverage_guidance']
    assert calls[1][1]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
    assert m.read(run/'STATE.json')['status']=='awaiting_primary_full_review'

@pytest.mark.parametrize('unknown',[False,True])
def test_pipeline_no_analysis_and_round2_causal_change(tmp_path,monkeypatch,unknown):
    run=tmp_path/'r';m.prepare(run,m.Path('data/corpus_production_trials/20261030_av_transcription'),1);calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1
            if unknown:
                self.state['pending']=self.state['calls_started'];raise RuntimeError('unknown')
            return {'text':'场次：1\n旁白：原生候选。\n原段：CH20-P001'}
    monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert len(calls)==(1 if unknown else 2)
    if not unknown:
        assert calls[1][1]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
        with pytest.raises(ValueError):m.prepare(tmp_path/'r2',run,2)
        diag=tmp_path/'diag.json';diag.write_text(json.dumps({'cause':'真实原因','change':'流程修改'}),encoding='utf-8')
        m.prepare(tmp_path/'r2',run,2,diag)
        assert m.read(tmp_path/'r2'/'INPUT.json')==m.read(run/'INPUT.json')
        assert m.read(tmp_path/'r2'/'PLAN.json')['max_calls']==308
    with pytest.raises(ValueError):m.execute(run)
