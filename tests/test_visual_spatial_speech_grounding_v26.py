from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import pytest
from src.content_factory import visual_spatial_speech_grounding_v26 as f


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');return f.binding(path)


@pytest.fixture
def case(tmp_path):
    image=tmp_path/'reference.dat';image.write_bytes(b'CPU-only source binding fixture, not production image')
    actors={name:dict(display_name=display,visual_description=desc,picture_index=i,image=f.binding(image)) for i,name,display,desc in
            [(1,'su_mo','苏墨','穿深色夹克的成年父亲'),(2,'ye_nan','叶南','穿灰色翻领短袖的哥哥'),(3,'ye_xijue','叶西决','穿米色短袖的弟弟')]}
    source='0—5秒，叶西决看着苏墨，轻声说：“原句一。”\r\n5—9秒，叶南看着弟弟，内心独白：“原句二。”\r\n9—15秒，哥哥把手放在弟弟肩侧。'
    records=[dict(quote_index=i,quote_sha256=f.sha(m.group().encode('utf-8')),speaker_id=actor,mode=mode) for i,(m,(actor,mode)) in enumerate(zip(f.spans(source),[('ye_xijue','dialogue'),('ye_nan','inner')]))]
    return source,records,actors,tmp_path


def compile(case):
    source,records,actors,_=case
    return f.compile_prompt(source,f.sha(source.encode('utf-8')),records,actors)


def test_insert_only_bidirectional_replay_and_crlf_preserved(case):
    source,records,actors,_=case;out,audit=compile(case)
    assert f.restore(out,audit)==source and f.verify(source,out,audit)
    assert '\r\n' in out and audit['original_text_modified'] is False
    assert [m.group() for m in f.spans(out)]==[m.group() for m in f.spans(source)]
    assert audit['model_calls']==0 and audit['production_approved'] is False
    assert len(audit['insertions'])==2


def test_explicit_speaker_beats_last_named_person(case):
    source,records,actors,_=case;out,audit=compile(case)
    assert '由叶西决本人开口说出本句台词：\n“原句一。”' in out
    assert '苏墨本人开口' not in out


def test_inner_explicit_named_person_closed_mouth_and_voiceover(case):
    out,audit=compile(case)
    assert '叶南本人嘴唇闭合' in out and '以叶南的画外音呈现：\n“原句二。”' in out
    assert '由叶南本人开口' not in out


def test_plain_actor_action_style_has_no_engineering_label_or_closeup_lock(case):
    out,audit=compile(case)
    assert audit['instruction_style']==f.STYLE
    for op in audit['insertions']:
        text=op['inserted_text']
        assert '镜头明确呈现' in text and '的面部及本段原有动作' in text
        assert '【' not in text and '】' not in text and '本句声画执行' not in text
        assert '面部近景' not in text and '固定机位' not in text and '不生成' not in text
    assert '原段中的动作和表情照常演出' in out


def test_existing_r1_production_artifacts_remain_exact_and_verifiable():
    audit=f.read(f.ROOT/'B_speech/AUDIT.json')
    assert 'instruction_style' not in audit
    for row in audit['segments']:
        source=f.check(row['source_prompt']).read_bytes().decode('utf-8')
        output=f.check(row['output_prompt']).read_bytes().decode('utf-8')
        assert f.verify(source,output,row) and f.restore(output,row)==source


def test_actual_four_source_r2_retains_original_action_and_only_one_each_quote(tmp_path):
    output=tmp_path/'r2';spec=f.make_trusted_spec(f.ROOT/'INPUTS.json',output);audit=f.prepare(spec,output)
    assert audit['instruction_style']==f.STYLE and audit['total_original_quotes']==10
    for row in audit['segments']:
        source=f.check(row['source_prompt']).read_bytes().decode('utf-8');text=f.check(row['output_prompt']).read_bytes().decode('utf-8')
        assert f.restore(text,row)==source
        assert '【本句声画执行】' not in text
        assert [m.group() for m in f.spans(text)]==[m.group() for m in f.spans(source)]
        for op in row['insertions']:assert '面部及本段原有动作' in op['inserted_text'] and '面部近景' not in op['inserted_text']
    s04=(output/'S04.prompt.txt').read_text(encoding='utf-8')
    assert '立刻跪下' in s04 and '两人一起沿床尾空出的通道向房门跑出去' in s04


@pytest.mark.parametrize('value',['foreign_actor','',None])
def test_foreign_missing_actor_reject(case,value):
    case[1][0]['speaker_id']=value
    with pytest.raises(ValueError,match='foreign_or_missing'):compile(case)


@pytest.mark.parametrize('value',['',None,'narration','dialog','INNER'])
def test_mode_not_guessed_or_defaulted(case,value):
    case[1][0]['mode']=value
    with pytest.raises(ValueError,match='explicit_dialogue_or_inner'):compile(case)


def test_absent_mode_field_rejects(case):
    del case[1][0]['mode']
    with pytest.raises(ValueError,match='explicit_structured'):compile(case)


def test_quote_sha_mismatch_rejects(case):
    case[1][0]['quote_sha256']='0'*64
    with pytest.raises(ValueError,match='audio_quote_sha'):compile(case)


def test_duplicate_quote_index_rejects(case):
    case[1][1]['quote_index']=0
    with pytest.raises(ValueError,match='unique_in_range'):compile(case)


def test_missing_source_occurrence_rejects(case):
    case[1].pop()
    with pytest.raises(ValueError,match='coverage'):compile(case)


def test_extra_source_occurrence_rejects(case):
    case[1].append(dict(case[1][0]))
    with pytest.raises(ValueError,match='coverage'):compile(case)


def test_changed_original_source_sha_rejects(case):
    with pytest.raises(ValueError,match='source_text_sha'):
        f.compile_prompt(case[0],'0'*64,case[1],case[2])


def test_identical_repeated_quotes_are_independent_occurrences(case):
    source='叶西决说：“同一句。”叶南说：“同一句。”';records=deepcopy(case[1])
    for r,m in zip(records,f.spans(source)):r['quote_sha256']=f.sha(m.group().encode('utf-8'))
    out,audit=f.compile_prompt(source,f.sha(source.encode('utf-8')),records,case[2])
    assert [m.group() for m in f.spans(out)]==['“同一句。”','“同一句。”']
    assert f.restore(out,audit)==source


def test_shuffled_structured_records_sort_by_original_occurrence(case):
    expected,_=compile(case);case[1].reverse();actual,_=compile(case)
    assert actual==expected


@pytest.mark.parametrize('text',['他说：“未结束','他说：「未结束','他说：“外层“嵌套”结束”'])
def test_ambiguous_quoting_rejected_instead_of_guessed(case,text):
    with pytest.raises(ValueError,match='unbalanced_or_nested'):f.spans(text)


def test_reference_sha_change_rejects(case):
    Path(case[2]['su_mo']['image']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='file_changed'):compile(case)


def test_instruction_cannot_contain_extra_quoted_examples(case):
    case[2]['ye_nan']['visual_description']='示例“角色一”'
    with pytest.raises(ValueError,match='quote_free'):compile(case)


def test_picture_slots_not_collapsed_even_if_source_pixels_same(case):
    out,_=compile(case)
    assert '<Picture 3>' in out and '<Picture 2>' in out
    case[2]['ye_nan']['picture_index']=3
    with pytest.raises(ValueError,match='one_picture_identity'):compile(case)


def test_audit_mapping_tamper_detected(case):
    source=case[0];out,audit=compile(case);audit['records'][0]['speaker_id']='su_mo'
    with pytest.raises(ValueError,match='audited_speaker_mode'):f.verify(source,out,audit)


def test_output_tamper_detected(case):
    out,audit=compile(case)
    with pytest.raises(ValueError,match='compiled_text_sha'):f.restore(out+'changed',audit)


def test_prepare_all_rows_validated_before_outputs(case):
    source,records,actors,root=case;p=root/'original.txt';p.write_bytes(source.encode('utf-8'))
    bad=deepcopy(records);bad[0]['mode']='guess'
    spec=root/'spec.json';put(spec,dict(schema='spatial_speech_grounding_spec/v26',speaker_map_authority='explicit test fixture',actors=actors,
        segments=[dict(id='A',source_prompt=f.binding(p),records=records),dict(id='B',source_prompt=f.binding(p),records=bad)]))
    out=root/'output'
    with pytest.raises(ValueError):f.prepare(spec,out)
    assert not out.exists()


def test_prepare_freezes_and_never_overwrites_original(case):
    source,records,actors,root=case;p=root/'original.txt';p.write_bytes(source.encode('utf-8'));b=f.binding(p)
    spec=root/'spec.json';put(spec,dict(schema='spatial_speech_grounding_spec/v26',speaker_map_authority='explicit test fixture',actors=actors,segments=[dict(id='A',source_prompt=b,records=records)]))
    out=root/'output';one=f.prepare(spec,out);two=f.prepare(spec,out)
    assert one==two and f.binding(p)==b
    (out/'A.prompt.txt').write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='frozen_output_differs'):f.prepare(spec,out)


def test_actual_four_chapter_source_production_cpu_prepare(tmp_path):
    """Actual production inputs, no model/API calls and no old file mutations."""
    inputs=f.ROOT/'INPUTS.json';before=f.binding(inputs);out=tmp_path/'production_inputs_cpu';spec=f.make_trusted_spec(inputs,out);result=f.prepare(spec,out)
    assert result['total_original_quotes']==10 and result['model_calls']==0
    assert [s['segment_id'] for s in result['segments']]==list(f.TRUSTED_MAP)
    for row in result['segments']:
        source=f.check(row['source_prompt']).read_bytes().decode('utf-8');compiled=f.check(row['output_prompt']).read_bytes().decode('utf-8')
        assert f.verify(source,compiled,row) and f.restore(compiled,row)==source
        assert [(r['speaker_id'],r['mode']) for r in row['records']]==list(f.TRUSTED_MAP[row['segment_id']])
    s02=(out/'S02.prompt.txt').read_text(encoding='utf-8')
    assert '由叶西决本人开口说出本句台词：\n“爸爸，这是好心人给我的面包。”' in s02
    s03=(out/'S03.prompt.txt').read_text(encoding='utf-8')
    assert '以叶西决的画外音呈现：\n“他一定在想怎么打我。”' in s03
    assert f.binding(inputs)==before


def test_trusted_book_map_cannot_silently_follow_new_source_revision(tmp_path):
    data=f.read(f.ROOT/'INPUTS.json');data['segments'][0]['adapted_prompt']['sha256']='0'*64
    p=tmp_path/'inputs.json';put(p,data)
    with pytest.raises(ValueError,match='exact_known_source_revision'):f.make_trusted_spec(p,tmp_path/'out')


def test_real_cli_production_cpu_blackbox(tmp_path):
    out=tmp_path/'cli';script=f.PROJECT/'scripts/run_spatial_speech_grounding_v26.py'
    p=subprocess.run([sys.executable,str(script),'--trusted-inputs',str(f.ROOT/'INPUTS.json'),'--out',str(out)],capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert p.returncode==0,p.stderr
    receipt=json.loads(p.stdout);assert receipt['segments']==4 and receipt['original_quotes']==10 and receipt['model_calls']==0
    assert (out/'AUDIT.json').is_file() and (out/'READING.md').is_file()
