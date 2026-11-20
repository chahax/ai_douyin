import importlib.util
from pathlib import Path
import pytest
from src.content_factory import narration_placement_policy_v2 as p

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('narration_v2_cli',ROOT/'scripts/run_narration_placement_v2.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def candidate(case):
    slots={'N_OPEN':('retain_scene_open','OPEN:SC_MEMORY'),'N_ROOM':('retain_action_gap','GAP:A_BOTTLE'),
        'N_S03':('retain_action_gap','GAP:A_LEAVE'),'N_S04':('convert_character_oral','GAP:A_STOP')}
    rows=[]
    for q in case['quotes']:
        if q['kind']!='narration':continue
        cls,slot=slots[q['id']];oral=cls=='convert_character_oral'
        rows.append(dict(source_quote_id=q['id'],classification=cls,slot_id=slot,source_fact_ids=q['fact_ids'],
            dialogue_group_ids=['G_WARN'] if q['id']=='N_S04' else ['G_CARE'] if q['id']=='N_S03' else [],
            reason='CPU contract test only',certainty='sufficient',oral_relation='outside_group',
            pov=dict(speaker_id='ye_dong' if oral else None,knowledge_evidence_quote_ids=['N_S04'] if oral else []),
            oral_suggestion=dict(speaker_id='ye_dong',text='咱们饭都吃不饱，哪有力气打。',source_fact_ids=q['fact_ids']) if oral else None))
    return dict(schema=p.base.DECISIONS,case_sha256=p.digest(case),decisions=rows)


def receipt(case,c):
    return dict(schema=p.base.RECEIPT,placement_contract=p.VERSION,status='accepted',case_sha256=p.digest(case),candidate=c,
        semantic_review=dict(schema=p.base.REVIEW,candidate_sha256=p.digest(c),checks=[dict(source_quote_id=r['source_quote_id'],verdict='pass',
            reason='CPU fixture only',evidence_quote_ids=[r['source_quote_id'],'A_BOTTLE'] if r['source_quote_id']=='N_ROOM' else [r['source_quote_id']]) for r in c['decisions']]))


def test_both_narration_and_oral_use_only_complete_exchange_external_slots():
    case=cli.case_v2();c=candidate(case)
    assert p.validate_decisions(case,c)==[]
    assert not any(s['kind']=='oral_source_position' for s in p.allowed_slots(case))
    c['decisions'][3]['slot_id']='ORAL:N_S04'
    assert p.validate_decisions(case,c)


def test_mixed_physical_motive_evaluation_cannot_all_become_child_speech():
    case=cli.case_v2();c=candidate(case);r=c['decisions'][2]
    r.update(classification='convert_character_oral',pov=dict(speaker_id='ye_xijue',knowledge_evidence_quote_ids=['N_S03']),
        oral_suggestion=dict(speaker_id='ye_xijue',text='我拿回了面包。',source_fact_ids=r['source_fact_ids']))
    issues=p.validate_decisions(case,c)
    assert any('mixed_narrator_only' in i for i in issues)


def test_compile_keeps_question_answer_and_warning_audio_contiguous_and_nonoverlapping():
    case=cli.case_v2();c=candidate(case);compiled=p.compile_before_video(case,receipt(case,c))
    ids=[a['id'] for a in compiled['audio_items']]
    assert ids[ids.index('Q_PAIN')+1]=='Q_NOT_PAIN' and ids[ids.index('Q_NAN')+1]=='Q_GIRL'
    assert ids.index('N_S04')>ids.index('Q_GIRL')
    assert next(a for a in compiled['audio_items'] if a['id']=='N_S03')['mode']=='voiceover'
    assert next(a for a in compiled['audio_items'] if a['id']=='N_S04')['mode']=='onscreen'
    assert '上贡' not in next(a for a in compiled['audio_items'] if a['id']=='N_S04')['text']
    for scene in case['scenes']:
        audio=[a for a in compiled['audio_items'] if a['scene_id']==scene['id']]
        assert all(a['end']<=b['start'] for a,b in zip(audio,audio[1:]))


def test_known_action_evidence_is_valid_but_unknown_action_is_not():
    case=cli.case_v2();c=candidate(case);r=receipt(case,c)
    assert p.validate_review(case,c,r['semantic_review'])==[]
    r['semantic_review']['checks'][1]['evidence_quote_ids'].append('A_INVENTED')
    assert p.validate_review(case,c,r['semantic_review'])


def test_narrator_mind_claim_cannot_gain_fake_self_experience():
    case=cli.case_v2();f=next(f for f in case['facts'] if f['id']=='F_STRANGER_MOTIVE');f['known_by']={'ye_xijue':['N_S03']}
    with pytest.raises(ValueError,match='not_personal_experience'):p.validate_case(case)


def test_long_oral_and_early_knowledge_are_blocked():
    case=cli.case_v2();c=candidate(case);c['decisions'][3]['oral_suggestion']['text']='很长'*30
    assert p.validate_decisions(case,c)
    c=candidate(case);q=next(q for q in case['quotes'] if q['id']=='N_S04');q['allowed_slot_ids']=['OPEN:SC_CARE'];c['case_sha256']=p.digest(case);c['decisions'][3]['slot_id']='OPEN:SC_CARE'
    assert any('knowledge_not_established' in i for i in p.validate_decisions(case,c))


def test_native_alias_normalization_is_finite_and_preserves_every_spoken_word():
    case=cli.case_v2();c=candidate(case)
    c['decisions'][0]['classification']='keep_as_narration';c['decisions'][2]['classification']='move_as_narration'
    c['decisions'][3]['classification']='convert_to_oral';text=c['decisions'][3]['oral_suggestion']['text'];c['decisions'][3]['oral_suggestion']=text
    normalized,proof=p.normalize_native_shape(case,c)
    assert normalized['decisions'][3]['oral_suggestion']['text']==text
    assert proof['narrative_or_dialogue_text_changed'] is False and proof['native_schema_compliance_claimed'] is False
    c['decisions'][0]['classification']='guess_a_new_kind'
    with pytest.raises(ValueError,match='unknown_native'):p.normalize_native_shape(case,c)


def test_actual_prompt_enum_and_object_shape_are_generated_from_same_schema():
    case=cli.case_v2();messages=p.messages(case);text='\n'.join(m['content'] for m in messages)
    for value in p.DECISION_SCHEMA['properties']['decisions']['items']['properties']['classification']['enum']:assert value in text
    assert '不可为字符串' in text and 'decision_schema' in text
