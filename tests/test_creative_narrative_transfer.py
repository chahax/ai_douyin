from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.creative_narrative_focus import bind_narrative_focus, prompt_for_stage
from src.content_factory.creative_narrative_transfer import enrich_review_context, build_transfer
from src.content_factory.creative_seedance_segments import build_seedance_segment_plan
from src.content_factory.creative_media_capability import audit_creative_executor
from src.content_factory.creative_brief import load_brief
from tests.test_creative_seedance_segments import _story, _config

def fixture():
    script,shots=_story()
    script['beats'][0].update(before='她合上本子。',during='她停住。',after='她看向同事。',
        dialogue=[{'speaker':'甲','text':'上周也是我留下，你先走了。'}],
        event='习惯替同事加班的她开始犹豫。')
    return script,shots

def test_final_prompt_review_is_actual_compiler_output_without_mutating_sources():
    script,shots=fixture()
    context={'script':script,'shots':shots};original=deepcopy(context)
    enriched=enrich_review_context(bind_narrative_focus(),'writer_check__00',context)
    plan=build_seedance_segment_plan(script,shots,audit_creative_executor(shots,config=_config()),config=_config())
    assert context==original
    assert enriched['final_video_prompts'][1]['text']==plan['segments'][1]['payload_template']['content'][0]['text']
    assert 'final_video_prompts' not in enrich_review_context(None,'writer_check__00',context)
    assert 'final_video_prompts' not in enrich_review_context(bind_narrative_focus(),'script_review__00',context)
    enriched['final_video_prompts'][1]['text']='changed'
    with pytest.raises(ValueError,match='NARRATIVE_FINAL_PROMPTS_CHANGED'):
        enrich_review_context(bind_narrative_focus(),'writer_check__00',enriched)

def test_transfer_preserves_actual_event_order_and_rejects_changed_requests():
    script,shots=fixture();binding=bind_narrative_focus()
    plan=build_seedance_segment_plan(script,shots,audit_creative_executor(shots,config=_config()),config=_config())
    report=build_transfer(binding,{'theme':'边界'},script,shots,plan)
    rows=report['beats'][0]['playback']
    assert [r['text'] for r in rows]==['她合上本子。','上周也是我留下，你先走了。','她停住。','她看向同事。']
    assert all('event' not in r for r in rows)
    assert report['semantic_approval'] is False and report['automatic_submit'] is False
    plan['segments'][0]['payload_template']['content'][0]['text']+='new action'
    with pytest.raises(ValueError,match='NARRATIVE_FINAL_PROMPTS_CHANGED'):
        build_transfer(binding,{'theme':'边界'},script,shots,plan)

def test_versions_keep_legacy_dispatch_and_freeze_roles_for_new_tasks():
    binding=bind_narrative_focus()
    assert prompt_for_stage(binding,'director_state_plan__00')
    assert not prompt_for_stage(binding,'static_visual_manifest')
    legacy={k:v for k,v in binding.items() if k not in ('stage_roles','review_final_prompts')}
    legacy['version']='narrative_expression_v1'
    assert not prompt_for_stage(legacy,'director_state_plan__00')
    saved=deepcopy(binding)
    binding['stage_roles'].clear()
    assert prompt_for_stage(saved,'writer_check__00') and not prompt_for_stage(binding,'writer_check__00')

def test_live_action_example_is_valid_replaceable_brief():
    root=Path(__file__).resolve().parents[1]
    brief=load_brief(root/'config/creative_brief.live_action.example.json')
    assert brief['duration_seconds']==[45,60] and '真人' in brief['visual_style']
    assert brief['constraints']
