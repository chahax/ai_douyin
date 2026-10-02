from copy import deepcopy
import pytest
from src.content_factory.creative_brief import normalize_brief, brief_focus, focus_duration_is_flexible
from src.content_factory.creative_original_prompt import validate_brief_script
from src.content_factory.creative_workflow_contract import (
    CreativeContractError, creative_focus_duration_range, validate_candidate_duration,
    validate_creative_focus_duration, compile_beat_screenplay,
)
from src.content_factory.creative_workflow import _validate_script_for_candidate
from src.content_factory.creative_narrative_focus import bind_narrative_focus, prompt_for_stage
from tests.test_creative_model_profile import setup


def brief(policy="flexible"):
    return normalize_brief({"schema":"creative_brief/v1","theme":"关系变化",
                            "duration_seconds":[45,60],"duration_policy":policy})


def test_flexible_reference_is_not_a_hidden_range_or_candidate_duration_lock():
    focus=brief_focus(brief())
    value={"beats":[{"duration_seconds":40},{"duration_seconds":40}]}
    validate_candidate_duration(value,{"duration_seconds":55},focus)
    validate_creative_focus_duration(value,focus)
    validate_brief_script({"beats":[{"duration_seconds":40,"dialogue":[]},
                                    {"duration_seconds":40,"dialogue":[]}]},brief())
    assert creative_focus_duration_range(focus) is None
    assert focus_duration_is_flexible("单场景要求\n"+focus)
    assert not focus_duration_is_flexible("主题里写参考时长（可浮动）不改变模式")


def test_shorter_complete_story_is_also_allowed_by_flexible_policy():
    focus=brief_focus(brief())
    value={"beats":[{"duration_seconds":10},{"duration_seconds":10}]}
    validate_candidate_duration(value,{"duration_seconds":55},focus)
    validate_creative_focus_duration(value,focus)


def test_legacy_and_explicit_strict_range_still_enforce_existing_rules():
    legacy=normalize_brief({"schema":"creative_brief/v1","theme":"关系变化",
                            "duration_seconds":[45,60]})
    assert "duration_policy" not in legacy
    value={"beats":[{"duration_seconds":40},{"duration_seconds":40}]}
    for b in [legacy,brief("strict_range")]:
        focus=brief_focus(b)
        assert creative_focus_duration_range(focus)==(45.,60.)
        with pytest.raises(CreativeContractError):validate_creative_focus_duration(value,focus)
        with pytest.raises(CreativeContractError):validate_candidate_duration(value,{"duration_seconds":55},focus)
    with pytest.raises(ValueError):brief("ignore_everything")


def test_real_script_validator_receives_flexible_policy_not_only_prompt(tmp_path):
    a,_=setup(tmp_path);script=deepcopy(a[2]);candidate=a[0]['candidates'][0]
    for b in script['beats']:b['duration_seconds']=40
    script['duration_seconds']=80
    script['screenplay_markdown']=compile_beat_screenplay(script)
    _validate_script_for_candidate(script,candidate,'','original',brief_focus(brief()))
    with pytest.raises(CreativeContractError):
        _validate_script_for_candidate(script,candidate,'','original',brief_focus(brief("strict_range")))


def test_flexible_total_does_not_relax_explicit_local_performance_requirements():
    value={"beats":[{"duration_seconds":12,"dialogue":[]}]}
    b=brief();b['constraints']=['结尾最多10秒']
    with pytest.raises(CreativeContractError,match='结尾'):validate_brief_script(value,b)


def test_new_content_priority_is_frozen_into_every_author_and_reviewer_stage():
    binding=bind_narrative_focus()
    assert binding['version']=='narrative_expression_v3'
    assert binding['review_priorities']==['emotion_expression','event_expression','visual_expression']
    for stage in ['writer_script','writer_revise__01','director_state_plan__00',
                  'writer_check__00','script_review__00']:
        prompt=prompt_for_stage(binding,stage)
        assert '情感表达、事件表达、画面表达' in prompt
        assert '不强迫角色口头解释感情' in prompt
    old={'version':'narrative_expression_v2','common':'old common',
         'review':'old review','stage_roles':{'writer_check':'review'}}
    assert prompt_for_stage(old,'writer_check__00')=='\nold common\nold review'


def test_flexible_story_is_not_mechanically_rescaled_to_candidate_estimate():
    from src.content_factory.creative_workflow import _project_whole_film_writer_duration_scale
    assert _project_whole_film_writer_duration_scale(
        {'material_ref':{'creative_focus':brief_focus(brief())}},'编剧局部返修总时长') is None
