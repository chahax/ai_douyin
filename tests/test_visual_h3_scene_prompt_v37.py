"""Program/source contract only; no new image viewing or semantic qualification."""
from copy import deepcopy
from pathlib import Path
import json
import urllib.request
import pytest
from src.content_factory import visual_h3_scene_prompt_v37 as p


@pytest.fixture
def entries():return json.loads(p.SOURCE.read_text(encoding='utf8'))['shots']


def test_original_ten_quotes_actions_camera_and_current_state_remain_exact(entries):
    total=0
    for e in entries:
        row=p.compile_segment(e);text=row['prompt_text'];source=p.check(e['source']).read_text(encoding='utf8')
        audit=row['audit'];a,b=audit['source_body_range'].values();x,y=audit['prompt_body_range'].values()
        assert text[x:y]==source[a:b]
        assert [q.group() for q in p.source_text.QUOTE.finditer(text)]==[a['text'] for a in row['audio']]
        for m in row['source_map']:
            q=m['prompt_range'];s=m['source_range'];assert text[q['start']:q['end']]==source[s['start']:s['end']]
        assert set(row['mapped_actor_ids'])==set(e['character_names']) and len(row['mapped_actor_ids'])==3
        assert row['user_review_pending'] and row['semantic_review_performed'] is False
        assert row['model_calls']==row['media_POSTs']==0 and not row['production_approved']
        total+=len(row['audio'])
    assert total==10


def test_multiview_maps_one_actor_not_standing_pose_or_permanent_three_person_group(entries):
    for e in entries:
        row=p.compile_segment(e);text=row['prompt_text']
        assert '本场角色仅为苏墨、叶南、叶西决' in text
        assert '人物按本段动作入画或离场' in text
        assert '正面、侧面与细节参考只是该演员的身份和衣着依据' in text
        assert '实际站位、朝向和动作由本段剧情决定' in text
        assert '自然侧面和三分之二侧面' in text and p.PERFORMANCE in text
        assert text.count(p.TEXT_POLICY)==1 and '所有台词仅作为声音播放' in text
        assert all(v not in text for v in ('visible_parts','required_faces','固定机位','tripod','look at camera'))
    assert '立刻跪下' in p.compile_segment(entries[3])['prompt_text']
    assert '向房门跑出去' in p.compile_segment(entries[3])['prompt_text']


def test_later_segments_continue_input_instead_of_reintroducing_portrait_group(entries):
    for i,e in enumerate(entries):
        r=p.compile_segment(e);requirement=r['continuity_input_requirement']
        if i==0:
            assert requirement['requires_current_run_previous_video_last'] is False
            assert all(s['text'] in r['prompt_text'] for s in r['identity_sources'])
        else:
            assert p.CONTINUATION in r['prompt_text']
            assert requirement['predecessor_segment']==p.IDS[i-1]
            assert requirement['requires_current_run_previous_video_last'] is True
            assert requirement['last_pixels_must_enter_image_edit'] is True
            assert requirement['last_provenance_only_is_insufficient'] is True
            assert all(s['text'] not in r['prompt_text'] for s in r['identity_sources'])
            assert r['audit']['identity_material_usage']=='continue_current_input_identity'
        assert 'actual_image_accepted' not in r and 'semantic_passed' not in r


def test_compilation_does_not_require_or_fake_old_image_face_reviews(entries):
    e=deepcopy(entries[1]);expected=p.compile_segment(e)['prompt_text']
    e['actual_first_image']={'path':'not-opened.png','sha256':'unknown'}
    e['coverage_review']={'path':'not-reviewed.json','sha256':'false'}
    assert p.compile_segment(e)['prompt_text']==expected


@pytest.mark.parametrize('error',['quote','speaker','partition','extra_actor'])
def test_source_audio_actor_or_partition_error_is_hard_failure(entries,error):
    e=deepcopy(entries[0])
    if error=='quote':e['audio'][0]['quote_sha256']='changed'
    elif error=='speaker':e['audio'][0]['speaker']='invented'
    elif error=='partition':e['source_spans'].pop(4)
    else:e['character_names']['new_person']='陌生人'
    with pytest.raises(p.PromptError):p.compile_segment(e)


def test_prepare_validate_idempotence_and_no_service_calls(entries,tmp_path,monkeypatch):
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('v37 CPU compilation must not contact service'))
    plan=p.prepare(p.SOURCE,tmp_path/'prompts');assert p.prepare(p.SOURCE,tmp_path/'prompts')==plan
    value=p.validate(plan);assert value['audio_quote_count']==10 and value['native_fields']=={}
    assert not value['semantic_review_performed'] and value['user_review_pending']
    assert value['source_validator']==p.binding(p.source_text.__file__)
    Path(value['segments'][2]['prompt']['path']).write_text('tampered continuation',encoding='utf8')
    with pytest.raises(p.PromptError):p.validate(plan)


def test_continuity_contract_cannot_be_downgraded_to_provenance_only(tmp_path):
    plan=p.prepare(p.SOURCE,tmp_path/'prompts');value=p.read(plan)
    value['segments'][1]['continuity_input_requirement']['last_pixels_must_enter_image_edit']=False
    file=tmp_path/'changed.json';file.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    with pytest.raises(p.PromptError,match='continuity_or_source_audit'):p.validate(p.binding(file))


@pytest.mark.parametrize('field',['production_approved','native_text_absence_guaranteed','semantic_review_performed'])
def test_source_checks_never_become_semantic_or_subtitle_pass(tmp_path,field):
    plan=p.prepare(p.SOURCE,tmp_path/'prompts');value=p.read(plan);value[field]=True
    file=tmp_path/'changed.json';file.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    with pytest.raises(p.PromptError):p.validate(p.binding(file))


def test_v36_frozen_code_and_real_four_prompts_are_unchanged(tmp_path):
    old=p.source_text.OUT/'PROMPT_PLAN.json'
    previous=p.source_text.read(p.binding(old));files=[Path(p.source_text.__file__),old]+[Path(r['prompt']['path']) for r in previous['segments']]
    before=[p.binding(f) for f in files]
    p.prepare(p.SOURCE,tmp_path/'prompts')
    assert [p.binding(f) for f in files]==before
