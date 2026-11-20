from copy import deepcopy
import json
from pathlib import Path
import pytest

from src.content_factory.creative_story_emotion import (
    CRITERIA, VERSION, build_emotion_revision_input, digest,
    story_media_blockers, validate_emotion_review)
from src.content_factory.creative_video_projection import (
    ARRANGEMENT, compile_generation_plan, file_sha, source_bindings)


@pytest.fixture
def source(tmp_path):
    script = {"title": "拒绝", "beats": [
        {"id": "B01", "steps": [{"kind": "action", "text": "乙递笔。"},
                               {"kind": "dialogue", "speaker": "甲", "text": "今晚我先走。"}]},
        {"id": "B02", "steps": [{"kind": "action", "text": "乙收回笔，抬眼。"}]}]}
    brief = {"audience_goal": "从紧张到松一口气", "pressure": "默认她接活",
             "choice": "拒绝", "consequence": "乙接回工作", "release": "她离开",
             "creative_limits": ["不增加反派或报复"]}
    assets = {"characters": [{"name": "甲", "age_group": "成年", "hair": "黑色短发",
                              "clothing": "灰蓝开衫", "body_shape": "中等偏瘦"}]}
    view = {"style": {"visual_medium": "写实", "palette": "暖调", "light_source": "窗边夕光"},
            "shots": []}
    compiled = {"complete": True, "source_raw_linear_script": script,
                "source_map": [], "scheduled_execution": {"beats": []}}
    refs = []
    for i, (beat, step) in enumerate([(0, 0), (0, 1), (1, 0)], 1):
        sid = f"SH0{i}"
        s = script["beats"][beat]["steps"][step]
        dialogue = s["kind"] == "dialogue"
        view["shots"].append({"id": sid, "duration_seconds": 4,
            "composition": "双人近景", "camera": "固定观察",
            "dialogue_lock": [{"speaker": s["speaker"], "text": s["text"]}] if dialogue else [],
            "purpose": "不要把这条内部目的传给服务", "cut_reason": "下一段打开大门"})
        compiled["source_map"].append({"source_step_ref": f"raw_linear_script.beats.{beat}.steps.{step}",
                                      "source_step": s, "shot_id": sid})
        compiled["scheduled_execution"]["beats"].append({"beat_id": sid, "events": [
            {"start": 0, "end": 4, "dialogue_index": 0 if dialogue else -1,
             "performance": "甲目光坚定，乙停顿。" if dialogue else s["text"]}]})
    image = tmp_path / "background.png"
    image.write_bytes(b"mock source bytes, not inspected")
    refs = [{"name": "办公室", "path": str(image), "sha256": file_sha(image),
             "role": "reference_image", "category": "environment_only"}]
    review = {"story_preserved": True, "issues": []}
    arrangement = {"schema": ARRANGEMENT,
        "bindings": source_bindings(script, assets, view, compiled, brief, review),
        "segments": [
            {"id": "G1", "shot_ids": ["SH01"], "duration_seconds": 4,
             "opening_mode": "background_reference", "references": refs},
            {"id": "G2", "shot_ids": ["SH02", "SH03"], "duration_seconds": 8,
             "opening_mode": "approved_raw_tail", "references": []}],
        "interactions": [{"shot_ids": ["SH02", "SH03"], "reason": "拒绝后读听者反应"}]}
    return script, assets, view, compiled, brief, review, arrangement


def rebind(args):
    args[-1]["bindings"] = source_bindings(*args[:-1])
    return args


def test_two_story_beats_three_shots_two_requests_and_no_future_leak(source):
    p = compile_generation_plan(*source)
    assert (p["source_beat_count"], p["observation_shot_count"], p["generation_segment_count"]) == (2, 3, 2)
    assert p["story_blockers"] == ["story_content_confirmation_missing"]
    assert p["creative_quality_passed"] is False and p["remote_request_sent"] is False
    for g in p["segments"]:
        assert g["submission_ready"] is False
        assert g["time_status"] == "planned_not_actual_performance"
        assert "下一段打开大门" not in g["prompt"]
        assert "SH02" not in g["prompt"]
    g = p["segments"][1]
    assert "中文普通话" in g["prompt"] and "今晚我先走。" in g["prompt"]
    assert "0—4秒" in g["prompt"] and "4—8秒" in g["prompt"]
    assert g["payload_template"]["content"][1]["role"] == "first_frame"
    assert g["predecessor_segment_id"] == "G1"


@pytest.mark.parametrize("kind", ["missing", "duplicate", "order", "split_interaction"])
def test_coverage_and_interaction_fail_closed(source, kind):
    a = source[-1]
    if kind == "missing":
        a["segments"][1]["shot_ids"].pop()
    elif kind == "duplicate":
        a["segments"][1]["shot_ids"].append("SH02")
    elif kind == "order":
        a["segments"][1]["shot_ids"].reverse()
    else:
        a["segments"][1]["shot_ids"] = ["SH02"]
        a["segments"][1]["duration_seconds"] = 4
        a["segments"].append({"id": "G3", "shot_ids": ["SH03"], "duration_seconds": 4,
                              "opening_mode": "approved_raw_tail", "references": []})
    with pytest.raises(ValueError, match="cover|interaction"):
        compile_generation_plan(*source)


@pytest.mark.parametrize("duration", [7, 16, True, 8.5])
def test_generation_limits_cannot_compress_or_overflow(source, duration):
    source[-1]["segments"][1]["duration_seconds"] = duration
    with pytest.raises(ValueError, match="duration"):
        compile_generation_plan(*source)


def test_frame_and_background_cannot_mix(source):
    source[-1]["segments"][1]["references"] = source[-1]["segments"][0]["references"]
    with pytest.raises(ValueError, match="mix"):
        compile_generation_plan(*source)


def test_scene_change_preserves_original_video_identity_route(source):
    source[-1]["segments"][1]["opening_mode"] = "scene_change_reference"
    source[-1]["segments"][1]["references"] = source[-1]["segments"][0]["references"]
    p = compile_generation_plan(*source)
    content = p["segments"][1]["payload_template"]["content"]
    assert [r["role"] for r in content[1:]] == ["reference_image", "reference_video"]
    assert "preceding_trusted_original_video_missing" in p["segments"][1]["blockers_before_submit"]


def test_state_type_and_source_binding_fail_closed(source):
    source[0]["title"] = "未经完整返修手工换稿"
    with pytest.raises(ValueError, match="binding"):
        compile_generation_plan(*source)


def test_internal_metadata_is_rejected_instead_of_removed_as_story(source):
    source[3]["scheduled_execution"]["beats"][2]["events"][0]["performance"] = "holder=C01"
    with pytest.raises(ValueError, match="metadata"):
        compile_generation_plan(*rebind(source))


def test_gaps_and_reversed_reactions_fail(source):
    source[3]["scheduled_execution"]["beats"][2]["events"][0]["start"] = 2
    with pytest.raises(ValueError, match="continuous"):
        compile_generation_plan(*rebind(source))


def test_background_file_mutation_fails(source):
    Path(source[-1]["segments"][0]["references"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="background"):
        compile_generation_plan(*source)


def test_full_review_cannot_clear_user_revision_feedback(source):
    s, _, _, _, b, review, _ = source
    confirmation = {"decision": "approved", "user_statement": "测试用户批准当前稿",
                    "script_sha256": digest(s), "brief_sha256": digest(b),
                    "full_review_sha256": digest(review)}
    p = compile_generation_plan(*source, confirmation=confirmation, revision_feedback_unresolved=True)
    assert p["story_blockers"] == ["human_revision_feedback_unresolved"]
    confirmation["script_sha256"] = "older"
    assert "story_content_confirmation_mismatched" in story_media_blockers(s, b, review, confirmation)


def test_complete_revision_context_contains_actual_reference_and_original_feedback(source):
    s, _, _, _, b, _, _ = source
    pack = {"R01": "参考全文：观察反应，保留人物选择的余地。"}
    feedback = {"decision": "revision_requested", "original": "冲突偏弱"}
    r = build_emotion_revision_input(s, b, pack, feedback)
    actual = json.loads(r["messages"][1]["content"])
    assert actual["previous_script"] == s and actual["reference_pack"] == pack
    assert actual["feedback"] == feedback and r["automatic_retry"] is False
    assert r["submitted"] is False


def test_emotion_review_evidence_and_quality_boundary(source):
    s, _, _, _, b, _, _ = source
    review = {"schema": VERSION, "script_sha256": digest(s), "brief_sha256": digest(b),
              "creative_quality_passed": False, "criteria": [
                  {"criterion": c, "finding": "satisfied", "reason": "fixture evidence",
                   "evidence_refs": [{"path": "script.beats.0.steps.0.text", "quote": "乙递笔。"}]}
                  for c in CRITERIA]}
    assert validate_emotion_review(review, s, b) == "needs_content_confirmation"
    review["criteria"][0]["finding"] = "needs_revision"
    assert validate_emotion_review(review, s, b) == "needs_complete_revision"
    review["criteria"][0]["evidence_refs"][0]["quote"] = "正文里没有这句"
    with pytest.raises(ValueError, match="exact"):
        validate_emotion_review(review, s, b)



def test_production_complete_script_validator_rejects_extra_speaker(source):
    from scripts.run_creative_emotion_revision_v1 import validate_script
    previous = deepcopy(source[0])
    previous["selected_candidate_id"] = "story"
    script = {"title": "测试", "premise": "测试完整输出", "selected_candidate_id": "story",
              "beats": [{"id": "B01", "event": "当面拒绝", "trigger": "被默认要求",
                         "steps": [{"kind": "dialogue", "speaker": "甲", "text": "今晚我先走。"}]}]}
    assert validate_script(script, previous)["complete_model_authored_revision"] is True
    script["beats"][0]["steps"][0]["speaker"] = "新增加的第三人"
    with pytest.raises(ValueError, match="speaker"):
        validate_script(script, previous)


def test_production_review_cannot_hide_emotion_issue_or_fake_quote(source):
    from scripts.run_creative_emotion_revision_v1 import validate_full_review
    s, _, _, _, b, _, _ = source
    evidence = [{"path": "script.beats.0.steps.0.text", "quote": "乙递笔。"}]
    review = {"full_text_review": {"story_preserved": True, "issues": [],
                                   "suggestions": [], "calibration_focus": []},
              "emotion_review": {"schema": VERSION, "script_sha256": digest(s), "brief_sha256": digest(b),
                                  "creative_quality_passed": False, "criteria": [
                  {"criterion": c, "finding": "satisfied", "reason": "fixture",
                   "evidence_refs": deepcopy(evidence)} for c in CRITERIA]}}
    assert validate_full_review(review, s, b)["full_review_complete"] is True
    review["emotion_review"]["criteria"][0]["finding"] = "needs_revision"
    with pytest.raises(ValueError, match="omitted"):
        validate_full_review(review, s, b)



def test_v2_preserved_theme_with_issues_and_stable_ids_is_not_a_pass(source):
    from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
    s, _, _, _, b, _, _ = source
    evidence = [{"path": "script.beats.B01.steps.0.text", "quote": "乙递笔。"}]
    review = {"full_text_review": {"story_preserved": True, "issues": [
        {"id": "I1", "location": "B01", "severity": "major", "rule": "压力不足",
         "evidence_refs": deepcopy(evidence), "impact": "fixture impact", "proposal": "整稿修复"}],
        "suggestions": [], "calibration_focus": []},
        "emotion_review": {"schema": VERSION, "script_sha256": digest(s), "brief_sha256": digest(b),
            "creative_quality_passed": False, "criteria": [
                {"criterion": c, "finding": "needs_revision", "reason": "fixture",
                 "evidence_refs": deepcopy(evidence)} for c in CRITERIA]}}
    before = deepcopy(review)
    result = validate_complete_review_v2(review, s, b)
    assert result["needs_revision"] is True
    assert result["raw_review_modified"] is False and review == before
    assert result["reference_resolution"][0]["canonical_path"] == "script.beats.0.steps.0.text"
    review["full_text_review"]["issues"][0]["evidence_refs"][0]["path"] = "script.beats.B99.steps.0.text"
    with pytest.raises(ValueError, match="unknown"):
        validate_complete_review_v2(review, s, b)



def test_complete_input_v2_requires_and_preserves_all_original_brief_fields(source):
    from src.content_factory.creative_story_emotion_input_v2 import (
        build_complete_revision_input, build_complete_review_context)
    s, _, _, _, b, _, _ = source
    original = {"theme": "守住自己的时间", "relationships": "长期兜底的同事关系",
        "audience_emotion": "先紧张后释放", "visual_style": "写实", "turn": "拒绝默认",
        "ending": "赴约", "constraints": ["拒绝前显示多次帮忙的证据"],
        "avoid": ["不靠摸包代替付出历史"], "duration_policy": "flexible"}
    pack, feedback = {"R01": "全文"}, {"decision": "revision_requested"}
    value = build_complete_revision_input(s, b, pack, feedback, creative_brief=original)
    context = json.loads(value["messages"][1]["content"])
    assert context["creative_brief"] == original and context["reference_pack"] == pack
    assert value["bindings"]["creative_brief_sha256"] == digest(original)
    reviewer = build_complete_review_context(s, b, pack, feedback, creative_brief=original)
    assert reviewer["creative_brief"] == original and reviewer["script"] == s
    incomplete = deepcopy(original)
    incomplete.pop("avoid")
    with pytest.raises(ValueError, match="avoid"):
        build_complete_revision_input(s, b, pack, feedback, creative_brief=incomplete)



def test_fresh_story_input_preserves_brief_refs_and_audits_prior_without_old_choreography(source):
    from src.content_factory.creative_story_emotion_input_v3 import build_fresh_story_input
    s, _, _, _, b, _, _ = source
    prior = deepcopy(s)
    prior['selected_candidate_id'] = 'C01'
    original = {'theme': '边界', 'relationships': '同事', 'audience_emotion': '紧张到释放',
        'visual_style': '写实', 'turn': '拒绝默认', 'ending': '赴约',
        'constraints': ['拒绝前交代反复加班'], 'avoid': ['不强行争吵']}
    references = [{'id': 'R01', 'text': '完整分析全文，保持原文'}]
    feedback = {'user_confirmation': '短暂劝留一级阻力', 'original_feedback': '冲突弱'}
    characters = [{'name': '甲', 'clothing': '灰开衫'}, {'name': '乙', 'clothing': '衬衫'}]
    saved = deepcopy((prior, original, references, feedback, characters))
    request = build_fresh_story_input(prior, b, references, feedback,
        creative_brief=original, characters=characters)
    actual = json.loads(request['messages'][1]['content'])
    assert actual['creative_brief'] == original and actual['reference_pack'] == references
    assert actual['feedback'] == feedback and actual['characters'] == characters
    assert 'previous_script' not in actual
    assert actual['replacement_scope']['prior_complete_script_sha256'] == digest(prior)
    assert actual['replacement_scope']['old_failure_budget_reset'] is False
    assert request['bindings']['previous_script_sha256'] == digest(prior)
    assert (prior, original, references, feedback, characters) == saved
    with pytest.raises(ValueError, match='unambiguous'):
        build_fresh_story_input(prior, b, references, feedback,
            creative_brief=original, characters=[characters[0], characters[0]])


def test_request_schema_and_local_speaker_acceptance_agree(source):
    from src.content_factory.creative_story_schema_v2 import complete_story_schema, validate_complete_story
    from jsonschema import Draft202012Validator, ValidationError
    previous = deepcopy(source[0])
    previous['selected_candidate_id'] = 'C01'
    script = {'title': '完整稿', 'premise': '剧情', 'selected_candidate_id': 'C01',
        'beats': [{'id': 'B01', 'event': '拒绝', 'trigger': '被要求',
            'steps': [{'kind': 'action', 'speaker': '', 'text': '甲抬眼看乙。'},
                      {'kind': 'dialogue', 'speaker': '甲', 'text': '今晚我先走。'}]}]}
    schema = complete_story_schema(previous)
    assert validate_complete_story(script, previous)['speaker_constraints_present_in_request_schema']
    for index, speaker in [(0, '甲'), (0, '环境'), (1, '第三人'), (1, '')]:
        wrong = deepcopy(script)
        wrong['beats'][0]['steps'][index]['speaker'] = speaker
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(wrong)
        with pytest.raises(ValidationError):
            validate_complete_story(wrong, previous)
