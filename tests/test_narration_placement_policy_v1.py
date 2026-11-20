from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest
from src.content_factory import narration_placement_policy_v1 as p

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('narration_cli',ROOT/'scripts/run_narration_placement_policy.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def candidate(case):
    rows=[]
    for q in case['quotes']:
        if q['kind']!='narration':continue
        cls,slot,actor,groups,relation='retain_scene_open','OPEN:'+q['scene_id'],None,[],'outside_group'
        if q['id']=='N_ROOM':cls,slot='retain_action_gap','GAP:A_BOTTLE'
        if q['id'] in ('N_S03','N_S04'):
            cls,slot='convert_character_oral','ORAL:'+q['id']
            actor='ye_xijue' if q['id']=='N_S03' else 'ye_dong'
            groups=['G_CARE' if q['id']=='N_S03' else 'G_WARN'];relation='natural_response' if q['id']=='N_S03' else 'same_topic_turn'
        rows.append(dict(source_quote_id=q['id'],classification=cls,slot_id=slot,dialogue_group_ids=groups,
            source_fact_ids=q['fact_ids'],certainty='sufficient',reason='Controlled structural test, not real model acceptance.',
            pov=dict(speaker_id=actor,knowledge_evidence_quote_ids=[q['id']] if actor else []),oral_relation=relation,
            oral_suggestion=dict(speaker_id=actor,text='我疼得起不来，有人给了我一块面包。' if q['id']=='N_S03' else '咱们连饭都吃不饱，哪有力气打。',source_fact_ids=q['fact_ids']) if actor else None))
    return dict(schema=p.DECISIONS,case_sha256=p.digest(case),decisions=rows)


def receipt(case,value):
    review=dict(schema=p.REVIEW,candidate_sha256=p.digest(value),checks=[dict(source_quote_id=r['source_quote_id'],
        verdict='pass',evidence_quote_ids=[r['source_quote_id']],reason='Controlled schema test only.') for r in value['decisions']])
    return dict(schema=p.RECEIPT,status='accepted',case_sha256=p.digest(case),candidate=value,semantic_review=review)


def test_semantic_question_answer_group_survives_interposed_narration_and_action():
    case=cli.demo_case();slots={s['id'] for s in p.allowed_slots(case)}
    assert 'GAP:A_CARE' not in slots and 'GAP:A_BOTTLE' in slots
    assert case['dialogue_groups'][0]['quote_ids']==['Q_PAIN','Q_NOT_PAIN']
    assert p.validate_decisions(case,candidate(case))==[]


def test_real_compile_preserves_dialogue_and_keeps_narration_without_audio_overlap():
    case=cli.demo_case();value=candidate(case);compiled=p.compile_before_video(case,receipt(case,value))
    audio=compiled['audio_items'];original={q['id']:q for q in case['quotes'] if q['kind']=='dialogue'}
    for item in audio:
        if item['source_quote_id'] in original:
            q=original[item['source_quote_id']];assert item['text']==q['text'] and item['speaker_id']==q['speaker_id']
    assert {a['source_quote_id'] for a in audio if a['mode']=='voiceover'}=={'N_OPEN','N_ROOM'}
    for scene in case['scenes']:
        rows=[a for a in audio if a['scene_id']==scene['id']]
        assert all(a['end']<=b['start'] for a,b in zip(rows,rows[1:]))
    assert '旁白画外叙述' in compiled['compiled_prompt'] and compiled['dispatched_media'] is False


def test_narration_cannot_use_action_inside_a_protected_exchange():
    case=cli.demo_case();value=candidate(case);row=value['decisions'][2]
    row.update(classification='retain_action_gap',slot_id='GAP:A_CARE',oral_suggestion=None,pov={'speaker_id':None,'knowledge_evidence_quote_ids':[]})
    assert any('illegal_or_protected' in i for i in p.validate_decisions(case,value))


def test_actor_present_but_without_knowledge_cannot_orally_claim_narrator_fact():
    case=cli.demo_case();value=candidate(case);row=value['decisions'][2]
    row['pov']['speaker_id']='ye_nan';row['oral_suggestion']['speaker_id']='ye_nan'
    assert any('does_not_know' in i for i in p.validate_decisions(case,value))


def test_later_information_cannot_be_spoken_earlier():
    case=cli.demo_case();next(f for f in case['facts'] if f['id']=='F_INJURY')['known_by']={'ye_xijue':['Q_GIRL']}
    value=candidate(case);value['decisions'][2]['pov']['knowledge_evidence_quote_ids']=['Q_GIRL']
    assert any('learns_fact_later' in i for i in p.validate_decisions(case,value))


def test_convert_does_not_excuse_an_unrelated_interruption():
    case=cli.demo_case();value=candidate(case);value['decisions'][2]['oral_relation']='outside_group'
    assert any('not_a_natural_current_turn' in i for i in p.validate_decisions(case,value))


def test_uncertain_or_semantically_rejected_candidate_cannot_compile():
    case=cli.demo_case();value=candidate(case);value['decisions'][0]['certainty']='uncertain'
    with pytest.raises(ValueError,match='compile_gate'):p.compile_before_video(case,receipt(case,value))
    value=candidate(case);r=receipt(case,value);r['semantic_review']['checks'][0]['verdict']='needs_semantic_repair'
    with pytest.raises(ValueError,match='compile_gate'):p.compile_before_video(case,r)


def test_future_event_cannot_be_pulled_into_scene_opening():
    case=cli.demo_case();case['facts'][0]['scene_open_allowed']=False;value=candidate(case)
    assert any('future_or_unavailable' in i for i in p.validate_decisions(case,value))


def test_single_turn_scene_needs_no_fabricated_dialogue_group_or_action():
    case=dict(schema=p.CASE,characters={'a':'甲'},scenes=[dict(id='s',context='清晨房间',items=['n','q'])],
        quotes=[dict(id='n',kind='narration',scene_id='s',text='天亮了。',fact_ids=[]),dict(id='q',kind='dialogue',scene_id='s',speaker_id='a',text='早。')],
        actions=[],facts=[],dialogue_groups=[])
    assert [s['id'] for s in p.allowed_slots(case)]==['OPEN:s','ORAL:n']


def test_malformed_model_return_becomes_repair_issue_not_ready_or_crash():
    case=cli.demo_case()
    assert p.validate_decisions(case,None) and p.validate_review(case,candidate(case),[])
    value=candidate(case);value['decisions'][2]['pov']=None
    assert p.validate_decisions(case,value)


def test_tampered_original_quote_or_bound_candidate_is_rejected():
    case=cli.demo_case();case['quotes'][0]['text']+='新增'
    with pytest.raises(ValueError,match='original_quote'):p.validate_case(case)
    case=cli.demo_case();value=candidate(case);r=receipt(case,value);r['semantic_review']['candidate_sha256']='wrong'
    with pytest.raises(ValueError,match='compile_gate'):p.compile_before_video(case,r)


def test_existing_started_native_call_is_not_reissued(tmp_path,monkeypatch):
    case=cli.demo_case();cli.prepare(tmp_path,case)
    p.freeze(tmp_path/'calls/C001/START.json',{'pending':True})
    monkeypatch.setattr(cli,'native_call',lambda *a,**k:pytest.fail('unknown call cannot replay'))
    with pytest.raises(ValueError,match='preserved'):cli.judge(tmp_path)
