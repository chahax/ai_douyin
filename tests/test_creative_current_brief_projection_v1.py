from copy import deepcopy
import json

import pytest

from src.content_factory.creative_current_brief_projection_v1 import (
    CurrentBriefProjectionError, current_identity, digest,
    project_current_brief, verify_writer_request,
)


@pytest.fixture
def brief():
    return {
        "brief_id": "current-resignation-20261010",
        "source_identity": {"source_id": "current-adopted-script-362", "sha256": "a" * 64},
        "characters": [
            {"character_id": "xiaolin", "name": "小林", "role": "员工"},
            {"character_id": "zhou", "name": "周姐", "role": "人事主管"},
        ],
        "scenes": [{"scene_id": "meeting", "description": "小会议室"}],
        "facts": [
            {"fact_id": "F1", "text": "公司决定让小林离开。", "participant_ids": ["xiaolin", "zhou"]},
            {"fact_id": "F2", "text": "申请写着个人原因，尚未签字。", "participant_ids": ["xiaolin"]},
        ],
        "initial_state": {
            "scene_id": "meeting",
            "character_states": [
                {"character_id": "xiaolin", "state": "坐在桌外侧，工牌戴着"},
                {"character_id": "zhou", "state": "坐在桌里侧"},
            ],
            "prop_states": [
                {"prop_id": "paper", "state": "纸面朝上，在周姐面前", "holder_character_id": "zhou"},
                {"prop_id": "pen", "state": "在纸边", "holder_character_id": "zhou"},
            ],
        },
        "event_chain": [
            {"event_id": "E1", "summary": "通知公司决定，将纸笔推到小林近桌沿",
             "participant_ids": ["zhou", "xiaolin"], "fact_ids": ["F1"], "scene_id": "meeting"},
            {"event_id": "E2", "summary": "小林看清个人原因后质问，周姐坚持公司口径",
             "participant_ids": ["xiaolin", "zhou"], "fact_ids": ["F1", "F2"], "scene_id": "meeting"},
            {"event_id": "E3", "summary": "小林拒签，周姐收回纸笔并独自离开",
             "participant_ids": ["xiaolin", "zhou"], "fact_ids": ["F2"], "scene_id": "meeting"},
        ],
        "ending": {"after_event_id": "E3", "summary": "小林留下，争议未结束",
                   "participant_ids": ["xiaolin"], "scene_id": "meeting"},
        "constraints": {"allowed_character_ids": ["xiaolin", "zhou"],
                        "allowed_scene_ids": ["meeting"], "max_duration_seconds": 180,
                        "dialogue_language": "普通话", "subtitles": False},
    }


@pytest.fixture
def old():
    return {
        "schema": "trend_story_direction/v1", "packet_sha256": "b" * 64,
        "selected_candidate_id": "OLD_CANDIDATE",
        "creative_brief": {"coffee": "旧咖啡提案", "phone": "旧手机提案"},
        "emotional_brief": "旧社保提案", "characters": [{"name": "旧律师"}],
        "goals": ["旧三场景目标"],
        "tag_choices": [{"tag_id": "tag:old-1", "story_relevance": "旧正文相关提案"}],
    }


def test_current_context_excludes_complete_old_proposal_and_only_projects_selected_tag_id(brief, old):
    projection = project_current_brief(brief, old, selected_tag_ids=["tag:old-1"])
    assert projection["writer_context"] == {"current_brief": brief, "tag_ids": ["tag:old-1"]}
    serialized = json.dumps(projection["writer_context"], ensure_ascii=False)
    for forbidden in ["旧咖啡提案", "旧手机提案", "旧社保提案", "旧律师", "旧三场景目标",
                      "旧正文相关提案", "OLD_CANDIDATE", "story_relevance", "creative_brief"]:
        assert forbidden not in serialized
    assert projection["archive"] == {
        "direction_sha256": digest(old),
        "source_identity": {"schema": old["schema"], "packet_sha256": old["packet_sha256"]},
    }
    proof = verify_writer_request(deepcopy(projection["writer_context"]), projection)
    assert proof["exact_projection_match"] is True
    assert proof["creative_quality_passed"] is False


def test_no_old_tags_selected_by_default(brief, old):
    assert project_current_brief(brief, old)["writer_context"]["tag_ids"] == []


def test_input_objects_are_unchanged_and_output_owns_deep_copies(brief, old):
    original_brief, original_old = deepcopy(brief), deepcopy(old)
    projection = project_current_brief(brief, old, selected_tag_ids=["tag:old-1"])
    projection["writer_context"]["current_brief"]["facts"][0]["text"] = "输出副本变化"
    projection["identity"]["current_brief"]["source_identity"]["source_id"] = "输出身份变化"
    projection["archive"]["source_identity"]["schema"] = "输出档案变化"
    assert brief == original_brief
    assert old == original_old


@pytest.mark.parametrize("change", ["fact", "source_hash"])
def test_changed_current_fact_or_source_changes_identity_and_rejects_old_expected_identity(brief, old, change):
    expected = current_identity(brief)
    changed = deepcopy(brief)
    if change == "fact":
        changed["facts"][0]["text"] = "当前事实改变"
    else:
        changed["source_identity"]["sha256"] = "c" * 64
    assert current_identity(changed) != expected
    with pytest.raises(CurrentBriefProjectionError, match="CURRENT_IDENTITY_MISMATCH"):
        project_current_brief(changed, old, expected_current_identity=expected)


def test_changed_old_proposal_changes_archive_hash_without_overwriting_current_identity(brief, old):
    first = project_current_brief(brief, old)
    changed = deepcopy(old)
    changed["creative_brief"]["coffee"] = "另一个旧提案"
    changed["selected_candidate_id"] = "DIFFERENT_OLD_ID"
    second = project_current_brief(brief, changed)
    assert first["writer_context"] == second["writer_context"]
    assert first["identity"]["current_brief"] == second["identity"]["current_brief"]
    assert first["identity"]["writer_context_sha256"] == second["identity"]["writer_context_sha256"]
    assert first["archive"]["direction_sha256"] != second["archive"]["direction_sha256"]


@pytest.mark.parametrize("extra_field", ["source_direction", "creative_brief", "characters", "goals"])
def test_actual_writer_request_rejects_extra_archived_fields(brief, old, extra_field):
    projection = project_current_brief(brief, old)
    actual = deepcopy(projection["writer_context"])
    actual[extra_field] = old
    with pytest.raises(CurrentBriefProjectionError, match="WRITER_REQUEST_PROJECTION_MISMATCH"):
        verify_writer_request(actual, projection)


def test_actual_request_rejects_changed_or_missing_current_content(brief, old):
    projection = project_current_brief(brief, old)
    actual = deepcopy(projection["writer_context"])
    actual["current_brief"]["facts"][0]["text"] = "另一个事实"
    with pytest.raises(CurrentBriefProjectionError, match="WRITER_REQUEST_PROJECTION_MISMATCH"):
        verify_writer_request(actual, projection)
    actual = deepcopy(projection["writer_context"])
    actual.pop("tag_ids")
    with pytest.raises(CurrentBriefProjectionError, match="WRITER_REQUEST_PROJECTION_MISMATCH"):
        verify_writer_request(actual, projection)


@pytest.mark.parametrize("field", ["facts", "event_chain", "ending"])
def test_unselected_third_person_id_is_structurally_rejected(brief, old, field):
    invalid = deepcopy(brief)
    if field == "ending":
        invalid[field]["participant_ids"].append("third")
    else:
        invalid[field][0]["participant_ids"].append("third")
    with pytest.raises(CurrentBriefProjectionError, match="REFERENCE_UNKNOWN"):
        project_current_brief(invalid, old)


def test_added_character_cannot_expand_explicit_allowed_scope(brief, old):
    invalid = deepcopy(brief)
    invalid["characters"].append({"character_id": "third", "name": "另一人", "role": "同事"})
    with pytest.raises(CurrentBriefProjectionError, match="CHARACTER_SCOPE_MISMATCH"):
        project_current_brief(invalid, old)


def test_prose_is_preserved_without_plot_keyword_blacklist_or_semantic_rewrite(brief, old):
    changed = deepcopy(brief)
    changed["facts"][0]["text"] = "公司说这不是第三人的决定。"
    projection = project_current_brief(changed, old)
    assert projection["writer_context"]["current_brief"]["facts"][0]["text"] == changed["facts"][0]["text"]


@pytest.mark.parametrize("change,code", [
    ("bad_hash", "SOURCE_IDENTITY_INVALID"),
    ("missing_fact", "FIELD_INVALID"),
    ("duplicate_fact", "REFERENCE_DUPLICATE"),
    ("unknown_fact", "REFERENCE_UNKNOWN"),
    ("old_extra_field", "FIELDS_INVALID"),
])
def test_invalid_facts_and_source_are_not_silently_projected(brief, old, change, code):
    invalid = deepcopy(brief)
    if change == "bad_hash":
        invalid["source_identity"]["sha256"] = "not-a-hash"
    elif change == "missing_fact":
        invalid["facts"] = []
    elif change == "duplicate_fact":
        invalid["facts"].append(deepcopy(invalid["facts"][0]))
    elif change == "unknown_fact":
        invalid["event_chain"][0]["fact_ids"] = ["OLD_FACT"]
    else:
        invalid["creative_brief"] = old["creative_brief"]
    with pytest.raises(CurrentBriefProjectionError, match=code):
        project_current_brief(invalid, old)


def test_unknown_selected_tag_rejected_instead_of_adding_story_relevance(brief, old):
    with pytest.raises(CurrentBriefProjectionError, match="REFERENCE_UNKNOWN"):
        project_current_brief(brief, old, selected_tag_ids=["tag:not-found"])


def test_tampered_projection_current_identity_is_rejected(brief, old):
    projection = project_current_brief(brief, old)
    projection["identity"]["current_brief"]["brief_sha256"] = "d" * 64
    with pytest.raises(CurrentBriefProjectionError, match="CURRENT_IDENTITY_MISMATCH"):
        verify_writer_request(projection["writer_context"], projection)


def test_actual_json_identity_is_strict_even_when_python_values_compare_equal(brief, old):
    brief["constraints"]["max_duration_seconds"] = 1
    projection = project_current_brief(brief, old)
    actual = deepcopy(projection["writer_context"])
    actual["current_brief"]["constraints"]["max_duration_seconds"] = True
    assert actual == projection["writer_context"]
    with pytest.raises(CurrentBriefProjectionError, match="WRITER_REQUEST_PROJECTION_MISMATCH"):
        verify_writer_request(actual, projection)


def test_tampered_archive_identity_is_rejected(brief, old):
    projection = project_current_brief(brief, old)
    projection["archive"]["direction_sha256"] = "f" * 64
    with pytest.raises(CurrentBriefProjectionError, match="ARCHIVE_IDENTITY_INVALID"):
        verify_writer_request(projection["writer_context"], projection)
