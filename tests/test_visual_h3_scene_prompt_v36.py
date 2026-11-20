"""Source/text contract tests only; no content review, inference or media POST."""
from copy import deepcopy
from pathlib import Path
import json
import urllib.request
import pytest
from src.content_factory import visual_h3_scene_prompt_v36 as p


@pytest.fixture
def entries():return json.loads(p.SOURCE.read_text(encoding='utf8'))['shots']


def test_real_four_sources_keep_all_ten_ordered_quotes_and_each_action_verbatim(entries):
    total=0
    for entry in entries:
        result=p.compile_segment(entry);source=p.check(entry['source']).read_text(encoding='utf8')
        audit=result['audit'];a,b=audit['source_body_range'].values();x,y=audit['prompt_body_range'].values()
        assert result['prompt_text'][x:y]==source[a:b]
        assert [q.group() for q in p.QUOTE.finditer(result['prompt_text'])]==[r['text'] for r in result['audio']]
        for m in result['source_map']:
            q=m['prompt_range'];s=m['source_range']
            assert result['prompt_text'][q['start']:q['end']]==source[s['start']:s['end']]
        assert audit['ordered_quotes_exact'] and audit['all_source_actions_copied']
        assert result['user_review_pending'] and not result['production_approved']
        assert not result['native_text_absence_guaranteed'] and result['model_calls']==result['media_POSTs']==0
        total+=len(result['audio'])
    assert total==10 and [len(p.compile_segment(e)['audio']) for e in entries]==[3,2,2,3]


def test_actual_prompt_has_requested_gaze_and_text_instruction_without_fixed_camera_or_face_enums(entries):
    for entry in entries:
        text=p.compile_segment(entry)['prompt_text']
        assert text.count(p.TEXT_POLICY)==1 and p.PERFORMANCE in text
        assert '对话对象或面包' in text and '自然侧面和三分之二侧面' in text
        assert all(word not in text for word in ('visible_parts','face=true','required_faces','camera_override','固定机位','tripod','look at camera'))
        assert '台词仅作为声音播放' in text
    # The source explicitly requests these cuts. They are not replaced by a
    # uniform locked-camera wrapper or by the static opening-frame prompt.
    assert '平顺切到' in p.compile_segment(entries[0])['prompt_text']
    assert '立刻跪下' in p.compile_segment(entries[3])['prompt_text']
    assert '两人一起沿床尾空出的通道向房门跑出去' in p.compile_segment(entries[3])['prompt_text']


@pytest.mark.parametrize('error',['quote_hash','quote_order','speaker','audio_time','duration','partition'])
def test_invalid_original_source_audio_or_clock_is_rejected_without_a_model(entries,error):
    entry=deepcopy(entries[0])
    if error=='quote_hash':entry['audio'][0]['quote_sha256']='0'*64
    elif error=='quote_order':entry['audio'].reverse()
    elif error=='speaker':entry['audio'][0]['speaker']='invented_character'
    elif error=='audio_time':entry['audio'][0]['end']=16
    elif error=='duration':entry['duration']=14
    else:entry['source_spans'].pop(5)
    with pytest.raises(p.PromptError):p.compile_segment(entry)


def test_source_file_change_rejected_by_raw_bytes_not_reclassified(entries,tmp_path):
    entry=deepcopy(entries[0]);file=tmp_path/'source.txt';file.write_bytes(Path(entry['source']['path']).read_bytes())
    entry['source']=p.binding(file);file.write_bytes(file.read_bytes()+b' altered')
    with pytest.raises(p.PromptError,match='bytes_changed'):p.compile_segment(entry)


def test_image_face_reviews_are_not_required_or_faked_in_prompt_stage(entries):
    entry=deepcopy(entries[0]);original=p.compile_segment(entry)['prompt_text']
    entry['coverage_review']={'path':'missing.json','sha256':'not a true review'}
    entry['actual_first_image']={'path':'missing.png','sha256':'no image accepted'}
    for beat in entry['camera_beats']:
        for actor in beat['actors'].values():actor['visible_parts']=['back']
    result=p.compile_segment(entry)
    assert result['prompt_text']==original and result['user_review_pending']
    assert 'semantic_passed' not in result and 'review_passed' not in result


def test_prepare_freezes_four_outputs_and_validates_idempotently_without_http(entries,tmp_path,monkeypatch):
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('prompt compilation may not contact a service'))
    out=tmp_path/'prompts';plan=p.prepare(p.SOURCE,out)
    assert p.prepare(p.SOURCE,out)==plan
    checked=p.validate(plan)
    assert checked['audio_quote_count']==10 and checked['native_fields']=={}
    assert [s['id'] for s in checked['segments']]==list(p.IDS)
    for row in checked['segments']:
        assert row['prompt']==p.binding(out/(row['id']+'.prompt.txt'))
        assert row['prompt_utf8_sha256']==p.sha(Path(row['prompt']['path']).read_text(encoding='utf8'))
    file=out/'S03.prompt.txt';file.write_text('tampered text',encoding='utf8')
    with pytest.raises(p.PromptError):p.validate(plan)
    with pytest.raises(p.PromptError,match='frozen_v36'):p.prepare(p.SOURCE,out)


@pytest.mark.parametrize('field,value',[('production_approved',True),('native_text_absence_guaranteed',True),('native_fields',{'negative_prompt':'fake unsupported input'})])
def test_plan_never_claims_semantic_or_native_subtitle_success(tmp_path,field,value):
    plan=p.prepare(p.SOURCE,tmp_path/'prompts');data=p.read(plan);data[field]=value
    file=tmp_path/'changed.json';file.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    with pytest.raises(p.PromptError):p.validate(p.binding(file))


def test_prepare_requires_the_actual_four_segment_ten_quote_source(entries,tmp_path):
    source=tmp_path/'three.json';source.write_text(json.dumps(dict(shots=entries[:3]),ensure_ascii=False),encoding='utf8')
    with pytest.raises(p.PromptError,match='four_ordered'):p.prepare(source,tmp_path/'prompts')
