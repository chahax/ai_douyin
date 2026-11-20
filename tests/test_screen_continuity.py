import json
from contextlib import nullcontext
from pathlib import Path
from src.content_factory.novel_adaptation import screen_continuity as sc
from scripts import run_restricted_transcription as m

def test_real_missing_dialogue_regression_and_valid_speech():
    text=Path('data/corpus_production_trials/20261030_source_locations_focus/transcription.txt').read_text('utf-8')
    result=sc.dialogue_integrity(text)
    assert result['dialogue_lines']==38 and len(result['missing_body_lines'])==38
    assert not result['body_format_passed']
    assert sc.dialogue_integrity('对白[待核|CH1-P001|-]：走吧。')['body_format_passed']
    assert not sc.dialogue_integrity('对白[待核|CH1-P001|-]：  ')['body_format_passed']
    assert not sc.dialogue_integrity('旁白[CH1-P001]：他说走吧。')['semantic_acceptance']

def test_probe_score_does_not_invent_missing_or_ignore_duplicate_answers():
    cases=m.read(Path('tests/fixtures/screen_continuity_cases.json'))
    full='\n'.join(c['id']+'|'+c['expected']+'|依据' for c in cases)
    score=sc.score_probe(full,cases)
    assert score['correct']==12 and not score['format_errors']
    assert sc.score_probe(full.split('\n',1)[1],cases)['missing']==['T01']
    assert sc.score_probe(full+'\nT01|contradiction|重复',cases)['format_errors']
    assert sc.score_probe(full.replace('T02|contradiction','T02|consistent'),cases)['mismatches'][0]['id']=='T02'

def test_generic_policy_has_no_story_specific_location_template():
    p=m.read(Path('data/corpus_production_trials/20261030_source_locations_focus/INPUT.json'))
    prompt=sc.author_prompt(p)
    for name in ('苏墨','童装店','便利店','融创'):assert name not in prompt
    assert '〈证据原段号〉|〈原文连续地点词〉' not in prompt
    assert '对白[姓名|' in prompt and '：原文出声台词' in prompt
    assert '分头行动' in sc.POLICY and '不强制补一个出门镜头' in sc.POLICY

def test_probe_and_full_agent_inputs_are_isolated(tmp_path,monkeypatch):
    prior=Path('data/corpus_production_trials/20261030_source_locations_focus');run=tmp_path/'r'
    m.prepare_focus(run,prior,'screen_continuity');calls=[]
    assert m.read(run/'PLAN.json')['max_calls']==315
    class Fake:
        def __init__(self,run,plan,state,client):self.run,self.state=run,state
        def save(self):(self.run/'STATE.json').write_text(json.dumps(self.state),encoding='utf-8')
        def call(self,name,role,prompt,payload,schema):
            calls.append((name,prompt,payload));self.state['calls_started']+=1
            return {'text':'场次：1\n时间：下午\n地点：不强调具体位置\n人物：苏墨\n对白[苏墨|CH21-P081|CH21-P079]：回家吧。\n原段：CH21-P081'}
    monkeypatch.setattr(m,'TextLedger',Fake);monkeypatch.setattr(m,'NativeClient',lambda *a:None);monkeypatch.setattr(m,'run_lock',lambda *a:nullcontext())
    m.execute(run)
    assert [x[0] for x in calls]==['continuity_probe','transcription','comparison']
    assert all('expected' not in c for c in calls[0][2]['cases'])
    assert 'cases' not in calls[1][2] and 'cases' not in calls[2][2]
    assert calls[1][2]['chapters']==m.read(prior/'INPUT.json')['chapters']
    assert calls[2][2]['complete_candidate']==(run/'screenplay.md').read_text('utf-8')
    assert calls[2][2]['dialogue_integrity']['body_format_passed']
    assert not (run/'LOCATION_VALIDATION.json').exists()
    assert m.read(run/'STATE.json')['status']=='awaiting_primary_full_review'
