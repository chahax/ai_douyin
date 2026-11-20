from copy import deepcopy
from pathlib import Path
import json
import re
import subprocess
import sys
import pytest
from src.content_factory import visual_spatial_native_prompt_v29 as f
from scripts import prepare_spatial_native_prompt_v29_r2 as revision


@pytest.fixture
def case(tmp_path):
    spec=f.make_spec(f.ROOT/'INPUTS.json',f.ROOT/'B_speech_r2/INPUT_SPEC.json',f.ROOT/'B_CANDIDATE_SPEC.json',tmp_path/'spec')
    value=f.speech.read(spec)
    return spec,value,tmp_path


def compile_row(value,index=0):
    s=value['segments'][index]
    source=f.speech.check(s['source_prompt']).read_bytes().decode('utf-8')
    return f.compile_segment(source,s['source_prompt'],s['records'],s['events'],value['references'],s['summary_en'],s.get('camera_tradeoff'))


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return path


def test_actual_four_sources_cpu_prepare_all_ten_original_quotes_once(case):
    spec,value,tmp=case;before=[f.speech.binding(x['source_prompt']['path']) for x in value['segments']]
    result=f.prepare(spec,tmp/'result')
    assert len(result['segments'])==4 and result['total_original_quotes']==10
    assert result['model_calls']==0 and result['production_approved'] is False
    for row in result['segments']:
        source=f.speech.check(row['source_prompt']).read_bytes().decode('utf-8')
        text=f.speech.check(row['output_prompt']).read_bytes().decode('utf-8')
        originals=[m.group() for m in f.speech.spans(source)]
        assert [m.group() for m in f.speech.spans(text)]==originals
        assert f.validate_native_prompt(text,originals)
        assert row['source_actions_english_translation_requires_root_semantic_review'] is True
        assert row['picture_slot_count']==5 and row['latent_guides_are_not_reference_slots']
        assert row['source_prompt'] in before
    assert before==[f.speech.binding(x['source_prompt']['path']) for x in value['segments']]
    assert 'spec.prompt_format = official_ref2va_v29' in (tmp/'result/READING.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('index,expected',[(0,{'ye_xijue':1,'ye_nan':2}),(1,{'su_mo':1,'ye_xijue':2}),(2,{'su_mo':1,'ye_xijue':2}),(3,{'su_mo':1,'ye_xijue':2})])
def test_local_speaker_event_order_independent_from_global_subject(case,index,expected):
    text,audit=compile_row(case[1],index)
    assert audit['local_speaker_map']==expected
    for row in audit['original_quotes']:
        assert row['local_vocal_id']=='S'+str(expected[row['speaker_id']])
        assert row['global_subject']==f.SUBJECTS[row['speaker_id']]
    if index==0:
        assert '<Subject 3> (S1)' in text and '<Subject 2> (S2)' in text
    retention=text.split('retention_analysis:\n')[1].split('\ndetailed_description:')[0]
    assert not re.search(r'\(S\d+\)',retention)


def test_inner_modes_closed_lips_immediately_after_each_original_quote(case):
    count=0
    for i in range(4):
        text,audit=compile_row(case[1],i)
        for row in audit['original_quotes']:
            if row['mode']=='inner':
                source=f.speech.check(audit['source_prompt']).read_bytes().decode('utf-8')
                quote=f.speech.spans(source)[row['quote_index']].group()
                assert 'says in an off-screen voiceover: <d>[Mandarin Chinese] '+quote+'</d> while <Subject '+str(row['global_subject'])+">'s lips remain completely closed." in text
                count+=1
    assert count==4


def test_first_shot_untimed_later_original_timestamps(case):
    for i in range(4):
        text,audit=compile_row(case[1],i)
        body=text.split('detailed_description:\n')[1].split('\noverall_soundscape:')[0]
        assert '[Shot 1] At ' not in body
        for j,event in enumerate(audit['English_visual_events'][1:],2):
            assert '[Shot '+str(j)+'] At '+f._timestamp(event['start_ms'])+', ' in body


def test_source_actions_audited_verbatim_and_required_movements_remain(case):
    s01,a01=compile_row(case[1],0);s02,a02=compile_row(case[1],1);s03,a03=compile_row(case[1],2);s04,a04=compile_row(case[1],3)
    assert 'Finish on his closed-eyed face' in s01
    assert 'opens his eyes' in s02 and 'has not reached out to take it' in s02
    assert 'rises and approaches' in s03 and 'takes the bread' in s03
    assert 'full-body view of the three people standing' in s03 and a03['diagnostic_camera_tradeoff']
    assert 'drops to his knees' in s04 and 'takes <Subject 2> by the hand' in s04
    assert 'run out together' in s04 and 'close view of his helpless, frustrated face' in s04
    assert 'diagnostic terminal guide' not in s03
    for audit in (a01,a02,a03,a04):
        source=f.speech.check(audit['source_prompt']).read_bytes().decode('utf-8')
        for event in audit['English_visual_events']:
            for fragment in event['source_fragments']:
                assert f._fragment(source,fragment['char_start'],fragment['char_end'])==fragment


@pytest.mark.parametrize('field,value',[('speaker_id','foreign_actor'),('mode','narration'),('mode',None),('quote_sha256','0'*64),('quote_index',2)])
def test_bad_explicit_occurrence_record_rejects(case,field,value):
    case[1]['segments'][0]['records'][0][field]=value
    with pytest.raises(ValueError):compile_row(case[1])


def test_missing_explicit_mode_rejects(case):
    del case[1]['segments'][0]['records'][0]['mode']
    with pytest.raises(ValueError):compile_row(case[1])


@pytest.mark.parametrize('key,value',[('char_start',0),('char_end',4),('utf8_byte_start',0),('sha256','0'*64),('text','invented event')])
def test_source_action_fragment_offset_text_or_sha_tampering_rejects(case,key,value):
    event=case[1]['segments'][0]['events'][1];event['source_fragments'][0][key]=value
    with pytest.raises(ValueError,match='source_event_offset'):compile_row(case[1])


def test_original_event_clock_not_only_contiguous_new_clock(case):
    events=case[1]['segments'][0]['events'];events[0]['end_ms']=4000;events[1]['start_ms']=4000
    with pytest.raises(ValueError,match='source_event_clock'):compile_row(case[1])


def test_quote_cannot_move_to_other_action_event(case):
    event=case[1]['segments'][0]['events'][1];event['quote_indices']=[0];event['visual_en']=event['visual_en'].replace('{speech:1}','{speech:0}')
    with pytest.raises(ValueError,match='duplicate_or_foreign'):compile_row(case[1])


def test_missing_quote_event_rejects(case):
    event=case[1]['segments'][0]['events'][1];event['quote_indices']=[];event['visual_en']=event['visual_en'].replace('{speech:1}','')
    with pytest.raises(ValueError,match='all_original_speech'):compile_row(case[1])


def test_source_text_sha_changed_rejects(case):
    value=case[1];row=value['segments'][0];source=f.speech.check(row['source_prompt']).read_bytes().decode('utf-8')
    with pytest.raises(ValueError,match='source_text_sha'):f.compile_segment(source+'changed',row['source_prompt'],row['records'],row['events'],value['references'],row['summary_en'])


@pytest.mark.parametrize('injection',['<Picture 6>','<Audio 1>','<Video 1>','<Subject 5>','“invented words”','[Shot 7]'])
def test_pure_validator_rejects_foreign_assets_chinese_or_shot(case,injection):
    text,_=compile_row(case[1])
    with pytest.raises(ValueError):f.validate_native_prompt(text+'\n'+injection)


def test_pure_validator_rejects_moved_words_unclosed_block_and_lips(case):
    text,_=compile_row(case[1],1)
    originals=[m.group() for m in f.speech.spans(text)]
    with pytest.raises(ValueError,match='original_quote'):f.validate_native_prompt(text,list(reversed(originals)))
    with pytest.raises(ValueError,match='complete_Mandarin'):f.validate_native_prompt(text+'<d>')
    with pytest.raises(ValueError,match='closed_lips'):f.validate_native_prompt(text.replace('remain completely closed','move with speech'))


def test_prepare_cross_checks_trusted_structured_map_not_only_file_binding(case):
    path,value,tmp=case;value['segments'][0]['records'][0]['speaker_id']='su_mo'
    changed=write(tmp/'changed.json',value)
    with pytest.raises(ValueError,match='trusted_speaker_mode'):f.prepare(changed,tmp/'changed_output')
    assert not (tmp/'changed_output').exists()


def test_prepare_cross_checks_reference_spec_mapping(case):
    path,value,tmp=case;value['references'][3]['image']=deepcopy(value['references'][4]['image'])
    with pytest.raises(ValueError,match='actual_reference_spec_mapping'):f.prepare(write(tmp/'changed.json',value),tmp/'changed_output')


def test_cpu_cli_actual_four_source_files_and_frozen_no_overwrite(case):
    _,_,tmp=case;out=tmp/'blackbox'
    proc=subprocess.run([sys.executable,'-X','utf8','scripts/run_spatial_native_prompt_v29.py','--out',str(out)],cwd=f.speech.PROJECT,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert proc.returncode==0,proc.stdout+proc.stderr
    result=json.loads(proc.stdout);assert result['segments']==4 and result['original_quotes']==10 and result['model_calls']==0
    audit=f.speech.read(out/'AUDIT.json');assert audit['total_original_quotes']==10
    original=(out/'S01.prompt.txt').read_bytes();(out/'S01.prompt.txt').write_bytes(original+b'changed')
    spec=out/'INPUT_SPEC.json'
    with pytest.raises(ValueError,match='frozen_output_differs'):f.prepare(spec,out)
    assert (out/'S01.prompt.txt').read_bytes()==original+b'changed'


def test_explicit_task_type_is_opt_in_and_default_preserves_all_r1_prompt_bytes(case):
    for i,row in enumerate(case[1]['segments']):
        text,_=compile_row(case[1],i)
        assert text.encode('utf-8')==(f.ROOT/'B_native_v29'/(row['id']+'.prompt.txt')).read_bytes()


def test_r2_actual_cpu_prepare_changes_only_declared_english_inputs_and_task_type(case):
    parent,value,tmp=case;out=tmp/'r2';path=revision.make_revision(parent,out);changed=f.speech.read(path)
    result=f.prepare(path,out)
    assert result['total_original_quotes']==10
    for old,new,audit in zip(value['segments'],changed['segments'],result['segments']):
        assert old['records']==new['records'] and old['source_prompt']==new['source_prompt']
        assert [e['source_fragments'] for e in old['events']]==[e['source_fragments'] for e in new['events']]
        assert new['task_type']=='reference generation + keyframe completion'
        assert new['events'][0]['visual_en'].startswith(revision.CONTINUATION)
        text=f.speech.check(audit['output_prompt']).read_bytes().decode('utf-8')
        assert '[reference generation + keyframe completion]' in text
        assert '<Picture 6>' not in text and f.validate_native_prompt(text)
        if new['id']=='S01':
            assert 'asleep' not in text and 'sleeping' not in text
            assert 'lies with his eyes closed' in text and 'keeps his eyes closed on the bed' in text
        if new['id']=='S03':assert 'provided closing guide' in text
    assert changed['parent_spec']==f.speech.binding(parent)
    assert len(changed['revision_input_audit']['exact_english_replacements'])==4


def test_r2_anchor_does_not_guess_when_parent_revision_changed(case):
    parent,value,tmp=case;value['segments'][0]['summary_en']='A different parent summary.'
    with pytest.raises(ValueError,match='exact_correction_anchor'):revision.make_revision(write(tmp/'changed_parent.json',value),tmp/'r2')


def test_future_story_can_explicitly_establish_sleep_no_global_ban(case):
    value=case[1];text,_=compile_row(value)
    assert 'lies asleep' in text
