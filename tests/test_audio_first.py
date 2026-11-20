import json
from pathlib import Path
from contextlib import nullcontext
import pytest
from scripts import run_audio_first_trial as runner
from src.content_factory.novel_adaptation import audio_first as a,audiovisual_transcription as av

def sample():
    p=av.packet({'chapters':[{'index':1,'text':'真好吃啊！\n\n“走吧。”\n\n小林说道：“好。”'}]},[],[1])
    raw={'items':[{'source_id':'CH1-P001','kind':'narration','speaker':'','text':'真好吃啊！','evidence_ids':['CH1-P001']},
        {'source_id':'CH1-P002','kind':'dialogue','speaker':'','text':'走吧。','evidence_ids':[]},
        {'source_id':'CH1-P003','kind':'dialogue','speaker':'小林','text':'好。','evidence_ids':['CH1-P003']}]}
    return p,raw

def test_audio_types_and_speakers_stay_separate():
    p,raw=sample();bank=a.build_bank(raw,p)
    assert bank['items'][0]['kind']=='narration' and bank['items'][1]['speaker']==''
    assert not bank['semantic_acceptance']
    raw['items'][0]['speaker']='小林'
    with pytest.raises(ValueError,match='non_dialogue'):a.build_bank(raw,p)

def test_audio_source_integrity_and_unknown_are_not_repaired_by_guess():
    p,raw=sample();raw['items'][1]['speaker']='哥哥'
    bank=a.build_bank(raw,p)
    assert bank['evidence_questions'][0]['speaker']=='哥哥' and not bank['semantic_acceptance']
    raw['items'][1]['speaker']='';raw['items'][1]['text']='我们走吧。'
    with pytest.raises(ValueError,match='original_span'):a.build_bank(raw,p)

def layout():return '场次：1\n时间：白天\n地点：不强调位置\n人物：小林\n画面[CH1-P001]：小林抬头。\n声音[A001]\n声音[A002]\n声音[A003]\n原段：CH1-P001—CH1-P003'

def test_picture_can_only_reference_audio_and_render_is_exact():
    p,raw=sample();bank=a.build_bank(raw,p);v=a.render_layout(layout(),bank,p)
    assert v['format_passed'] and '旁白[A001|旁白|CH1-P001]：真好吃啊！' in v['rendered']
    assert '对白[A002|待核|CH1-P002]：走吧。' in v['rendered']
    for bad in [layout().replace('声音[A001]','对白[小林]：真好吃啊！'),layout().replace('声音[A002]',''),layout().replace('声音[A003]','声音[A002]'),layout().replace('声音[A001]','声音[A999]')]:
        invalid=a.render_layout(bad,bank,p)
        assert not invalid['format_passed'] and invalid['rendered'] is None

def test_full_dispatch_and_failed_source_does_not_reach_picture(tmp_path,monkeypatch):
    prior=Path('data/corpus_production_trials/20261030_screen_continuity');run=tmp_path/'run';runner.prepare(run,prior)
    p,raw=sample();(run/'INPUT.json').write_text(json.dumps(p),encoding='utf-8');calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1
            return raw if name=='audio' else {'text':layout() if name=='picture' else '审查未决，不放行。'}
    monkeypatch.setattr(runner,'DirectLedger',Fake);monkeypatch.setattr(runner,'TextLedger',Fake)
    monkeypatch.setattr(runner,'NativeClient',lambda *a:None);monkeypatch.setattr(runner,'run_lock',lambda *a:nullcontext())
    runner.execute(run)
    assert [x[0] for x in calls]==['audio','picture','comparison']
    assert calls[1][1]['audio_bank']==calls[2][1]['audio_bank']
    assert calls[2][1]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
    assert not runner.read(run/'REVIEW_BINDING.json')['semantic_acceptance']
    other=tmp_path/'failure';runner.prepare(other,prior);(other/'INPUT.json').write_text(json.dumps(p),encoding='utf-8')
    calls.clear();raw['items'][0]['text']='凭空追加'
    runner.execute(other)
    assert [x[0] for x in calls]==['audio']
    assert runner.read(other/'STATE.json')['status']=='needs_attention'
    with pytest.raises(ValueError,match='not_fresh'):runner.execute(other)

def test_known_audio_continuation_keeps_raw_and_original_ceiling(tmp_path):
    prior=Path('data/corpus_production_trials/20261030_audio_first')
    run=tmp_path/'continued';runner.continue_audio(run,prior)
    assert runner.read(run/'audio_DIRECT_DECODED.json')==runner.read(prior/'audio_DIRECT_DECODED.json')
    assert runner.read(run/'PLAN.json')['max_calls']==318
    assert runner.read(run/'PLAN.json')['baseline_calls']==315
    assert runner.read(run/'STATE.json')['calls_started']==316
    assert runner.read(prior/'STATE.json')['status']=='needs_attention'

def test_failed_picture_audit_does_not_regenerate_or_fake_render(tmp_path,monkeypatch):
    prior=Path('data/corpus_production_trials/20261030_audio_first_continued');run=tmp_path/'audit'
    runner.prepare_failed_picture(run,prior);calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,payload));self.state['calls_started']+=1;return {'text':'失败原稿审查'}
    monkeypatch.setattr(runner,'DirectLedger',Fake);monkeypatch.setattr(runner,'TextLedger',Fake)
    monkeypatch.setattr(runner,'NativeClient',lambda *a:None);monkeypatch.setattr(runner,'run_lock',lambda *a:nullcontext())
    runner.execute(run)
    assert [c[0] for c in calls]==['comparison']
    assert calls[0][1]['layout']==(prior/'layout.txt').read_text('utf-8')
    assert not (run/'screenplay.md').exists()
    assert runner.read(run/'STATE.json')['calls_started']==318
    assert not runner.read(run/'REVIEW_BINDING.json')['rendered_candidate']

def test_source_ranges_accept_merged_events_without_changing_source_or_releasing_semantics():
    p,raw=sample()
    for value in ('CH1-P001-P003','CH1-P001—CH1-P003','CH1-P001-CH1-P003'):
        assert a.expand_target_range(value,p)==['CH1-P001','CH1-P002','CH1-P003']
    for value in ('CH1-P003-P001','CH1-P001-P999999999','CH1-P001-CH2-P003','CH9-P001','CH1-P001,P003'):
        assert a.expand_target_range(value,p) is None
    context=av.packet({'chapters':[{'index':1,'text':'前情。'},{'index':2,'text':'当前。'}]},[1],[2])
    assert a.expand_target_range('CH1-P001',context) is None
    v=a.render_layout(layout().replace('画面[CH1-P001]','画面[CH1-P001-P003]'),a.build_bank(raw,p),p)
    assert v['format_passed'] and not v['semantic_acceptance']
    assert v['visual_source_evidence'][0]['originals'][0]['text']=='真好吃啊！'

def test_old_range_failure_replays_but_does_not_become_content_accepted():
    p=Path('data/corpus_production_trials/20261030_audio_first_continued')
    v=a.render_layout((p/'layout.txt').read_text('utf-8'),runner.read(p/'AUDIO_BANK.json'),runner.read(p/'INPUT.json'))
    assert v['format_passed'] and not v['semantic_acceptance']
    assert '七个孩子' in v['rendered'] and '商场附近便利店' in v['rendered']
    assert not runner.read(p/'LAYOUT_VALIDATION.json')['format_passed']

def test_fact_trial_reuses_audio_and_only_calls_picture_review(tmp_path,monkeypatch):
    run=tmp_path/'facts';prior=Path('data/corpus_production_trials/20261030_audio_first_audit')
    runner.prepare_fact_trial(run,prior,Path('data/corpus_production_trials/20261030_audio_first'))
    plan=runner.read(run/'PLAN.json');assert plan['max_calls']==320 and not plan['review_failed_picture_only']
    calls=[]
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,prompt,payload));self.state['calls_started']+=1
            if name=='picture':
                audios='\n'.join('声音['+i['audio_id']+']' for i in payload['audio_bank']['items'])
                return {'text':'场次：1\n时间：白天\n地点：不强调位置\n人物：苏墨\n画面[CH20-P001-P002]：点头。\n'+audios+'\n原段：CH20-P001—CH21-P088'}
            return {'text':'程序通过不证明语义。'}
    monkeypatch.setattr(runner,'DirectLedger',Fake);monkeypatch.setattr(runner,'TextLedger',Fake)
    monkeypatch.setattr(runner,'NativeClient',lambda *a:None);monkeypatch.setattr(runner,'run_lock',lambda *a:nullcontext())
    runner.execute(run)
    assert [x[0] for x in calls]==['picture','comparison']
    assert a.FACT_PRESERVATION in calls[0][1] and a.FACT_PRESERVATION in calls[1][1]
    assert calls[0][2]['audio_bank']['raw_sha256']==runner.read(prior/'AUDIO_BANK.json')['raw_sha256']
    assert calls[1][2]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
    assert not runner.read(run/'REVIEW_BINDING.json')['semantic_acceptance']

def test_review_compaction_keeps_all_source_and_same_complete_candidate(tmp_path):
    prior=Path('data/corpus_production_trials/20261030_source_preservation')
    packet=runner.read(prior/'INPUT.json');bank=runner.read(prior/'AUDIO_BANK.json')
    layout=(prior/'layout.txt').read_text('utf-8');v=runner.read(prior/'LAYOUT_VALIDATION.json');candidate=(prior/'screenplay.md').read_text('utf-8')
    payload=runner.comparison_payload(packet,bank,layout,v,candidate)
    assert payload['source']==packet and payload['audio_bank']==bank and payload['layout']==layout
    assert payload['complete_candidate']==candidate
    assert 'rendered' not in payload['format_diagnostics']
    assert all('originals' not in e for e in payload['format_diagnostics']['visual_source_evidence'])
    assert all(all(s in {p['id'] for ch in packet['chapters'] for p in ch['paragraphs']} for s in e['source_ids']) for e in payload['format_diagnostics']['visual_source_evidence'])
    out=tmp_path/'review';runner.prepare_failed_picture(out,prior)
    assert runner.read(out/'PLAN.json')['max_calls']==320
    assert runner.read(out/'PLAN.json')['review_existing_picture_only']
    assert (out/'screenplay.md').read_text('utf-8')==candidate
    assert runner.read(out/'STATE.json')['calls_started']==319
