"""Offline declaration fixtures, not human golds or provider/media quality tests."""
from copy import deepcopy
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from content_factory import creative_shared_production_contract_v1 as c


def production_fixture():
    script = {"title": "离线测试", "premise": "两人在会议室谈话", "selected_candidate_id": "offline_fixture",
        "beats": [{"id": "B1", "steps": [
            {"kind": "action", "speaker": "", "text": "两人隔桌坐着，纸在桌面。"},
            {"kind": "dialogue", "speaker": "zhou", "text": "请看这张纸。"},
            {"kind": "dialogue", "speaker": "xiaolin", "text": "我先看一下。"}]}]}
    context = {"characters": [{"id": "zhou", "name": "周姐"}, {"id": "xiaolin", "name": "小林"}],
        "scenes": [{"id": "meeting_room", "description": "小会议室，两人隔桌坐着"}],
        "initial_state": {"scene_id": "meeting_room", "prop_states": [{"id": "paper", "expected_state": "桌面上的纸"}]}}
    declaration = "离线创作声明：女性；中年；短黑发；灰色上衣；男性；年轻；黑色短发；蓝色衬衫；玻璃隔断与会议桌；白色A4纸；公司；隔桌坐着；谈话前；面朝上。"
    approval = "离线模拟用户素材批准：asset_main内zhou_subject对应周姐zhou，xiaolin_subject对应小林xiaolin，room_subject对应meeting_room；素材和对应关系获批准。"
    provider_doc = "offline-provider fixture-model 支持 reference_image、first_frame、text_to_video_bootstrap，允许按人物主体映射引用素材。"
    bank = [{"source_id": sid, "kind": kind, "text": text, "sha256": c.text_sha256(text)} for sid, kind, text in [
        ("casting", "user_declaration", declaration), ("approval", "user_asset_approval", approval), ("policy", "provider_documentation", provider_doc)]]
    def refs(sid):
        return [{"source_id": sid, "quote": next(x["text"] for x in bank if x["source_id"] == sid)}]
    policy = {"status": "verified", "provider_id": "offline-provider", "model": "fixture-model", "identity_reference_mode": "reference_image",
        "allowed_reference_modes": ["reference_image", "first_frame", "text_to_video_bootstrap"],
        "allows_actor_asset_mapping": True, "sources": refs("policy"), "reason": ""}
    manifest = c.build_pending_manifest(script, context, policy, bank)
    values = {"zhou": ("女性", "中年", "短黑发", "灰色上衣"), "xiaolin": ("男性", "年轻", "黑色短发", "蓝色衬衫")}
    for actor in manifest["actors"]:
        actor["profile"] = {field: c.known(value, refs("casting")) for field, value in zip(c.PROFILE_FIELDS, values[actor["id"]])}
        actor["asset_binding"] = c.known({"asset_id": "asset_main", "subject_key": actor["id"] + "_subject"}, refs("approval"))
    manifest["scenes"][0]["appearance"] = c.known("玻璃隔断与会议桌", refs("casting"))
    manifest["scenes"][0]["asset_binding"] = c.known({"asset_id": "asset_main", "subject_key": "room_subject"}, refs("approval"))
    manifest["props"][0]["appearance"] = c.known("白色A4纸", refs("casting"))
    manifest["props"][0]["owner"] = c.known("公司", refs("casting"))
    manifest["asset_catalog"] = [{"asset_id": "asset_main", "kind": "image", "path": "D:/offline/example.png", "sha256": "a" * 64,
        "approval": {"status": "approved", "sources": refs("approval")}, "subjects": [
            {"subject_key": sid, "entity_type": kind, "entity_id": eid, "mapping_status": "confirmed", "sources": refs("approval")}
            for sid, kind, eid in [("zhou_subject", "actor", "zhou"), ("xiaolin_subject", "actor", "xiaolin"), ("room_subject", "scene", "meeting_room")]]}]
    state = {"global_manifest_sha256": c.digest(manifest), "scene_id": "meeting_room", "previous_scene_id": None, "completed_source_refs": [],
        "actors": [{"id": aid, "pose": c.known("隔桌坐着", refs("casting")), "emotion": c.known("谈话前", refs("casting"))} for aid in values],
        "props": [{"id": "paper", "holder": c.known(None, refs("casting")),
            "support": c.known({"entity_type": "scene", "entity_id": "meeting_room"}, refs("casting")), "orientation": c.known("面朝上", refs("casting"))}]}
    return script, manifest, state


def _compile():
    script, manifest, state = production_fixture()
    return script, manifest, state, c.compile_segment_context(manifest, script, state, ["B1.S01"])


def _attach(compiled):
    return [{"asset_id": x["asset_id"], "sha256": x["sha256"], "reference_mode": compiled["media_binding"]["role"]} for x in compiled["media_binding"]["assets"]]


def test_actual_487_source_builds_pending_without_name_or_pixel_inference():
    root = Path(__file__).resolve().parents[1]
    inp = json.loads((root / "data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v8/INPUT.json").read_text(encoding="utf-8"))
    policy = {"status": "unknown", "provider_id": "ark", "model": "seedance-unverified", "identity_reference_mode": "unverified", "allows_actor_asset_mapping": None, "sources": [], "reason": "离线尚未核实"}
    manifest = c.build_pending_manifest(inp["full_current_script"], inp["scene_and_character_context"], policy)
    assert all(a["profile"]["gender_presentation"]["value"] is None for a in manifest["actors"])
    assert all(a["asset_binding"]["status"] == "unknown" for a in manifest["actors"])
    assert c.production_gate(manifest, inp["full_current_script"])["status"] == "shared_pending"
    assert c.validate_casting_bootstrap(manifest, inp["full_current_script"])["status"] == "casting_bootstrap_pending"


def test_complete_fixed_profile_projects_once_with_same_manifest_and_unbound_voice():
    script, manifest, state, compiled = _compile()
    native = deepcopy(manifest)
    prompt = c.render_shared_context(compiled, manifest, script, state, ["B1.S01"])
    for value in ("女性", "中年", "短黑发", "灰色上衣", "男性", "年轻", "黑色短发", "蓝色衬衫"):
        assert value in prompt
    result = c.validate_provider_request_coverage(compiled, "当前演法\n" + prompt, _attach(compiled), "offline-provider", "fixture-model")
    assert result["global_manifest_sha256"] == c.digest(manifest)
    assert result["voice_identity_guaranteed"] is False
    assert manifest == native


@pytest.mark.parametrize("field", c.PROFILE_FIELDS)
def test_missing_any_identity_attribute_blocks_production(field):
    script, manifest, state = production_fixture()
    manifest["actors"][0]["profile"][field] = c.unknown("待确认")
    state["global_manifest_sha256"] = c.digest(manifest)
    with pytest.raises(ValueError, match="pending"):
        c.compile_segment_context(manifest, script, state, ["B1.S01"])


def test_wrong_subject_mapping_is_not_accepted_from_same_name():
    script, manifest, _ = production_fixture()
    manifest["actors"][0]["asset_binding"]["value"]["subject_key"] = "xiaolin_subject"
    with pytest.raises(ValueError, match="does not match"):
        c.production_gate(manifest, script)


def test_unapproved_mapping_blocks_formal_but_explicit_casting_can_bootstrap():
    script, manifest, state = production_fixture()
    for entity in [*manifest["actors"], *manifest["scenes"]]:
        entity["asset_binding"] = c.unknown("创作选角已有，视觉对应待批准")
    manifest["asset_catalog"] = []
    state["global_manifest_sha256"] = c.digest(manifest)
    assert c.production_gate(manifest, script)["status"] == "shared_pending"
    assert c.validate_casting_bootstrap(manifest, script)["status"] == "casting_bootstrap_ready"
    compiled = c.compile_segment_context(manifest, script, state, ["B1.S01"], bootstrap=True)
    assert compiled["media_binding"]["role"] == "text_to_video_bootstrap"
    assert compiled["media_binding"]["assets"] == []
    assert compiled["human_approved"] is False
    assert "尚未批准" in compiled["prompt_fragment"]
    assert c.validate_provider_request_coverage(compiled, compiled["prompt_fragment"], [], "offline-provider", "fixture-model")["media_status"] == "awaiting_human_review"
    state["completed_source_refs"] = ["B1.S01"]
    with pytest.raises(ValueError, match="first segment"):
        c.compile_segment_context(manifest, script, state, ["B1.S02"], bootstrap=True)


def test_formal_continuation_actual_tail_does_not_change_global_baseline_hash():
    script, manifest, state, first = _compile()
    state["completed_source_refs"] = ["B1.S01"]
    state["previous_scene_id"] = "meeting_room"
    tail = {"path": "D:/offline/original_tail.png", "sha256": "b" * 64, "role": "first_frame", "source": "generation_service_original",
        "source_task_id": "offline-task", "source_segment_id": "M001", "source_video_sha256": "c" * 64,
        "human_review_path": "D:/offline/human_review.json", "human_review_sha256": "d" * 64, "human_review_decision": "approved",
        "global_manifest_sha256": c.digest(manifest), "actor_ids": [x["id"] for x in manifest["actors"]]}
    binding = {"role": "first_frame", "assets": [{"asset_id": "actual_tail_M001", "sha256": tail["sha256"], "path": tail["path"], "kind": "image"}], "tail_evidence": tail}
    second = c.compile_segment_context(manifest, script, state, ["B1.S02"], media_binding=binding)
    assert first["global_manifest_sha256"] == second["global_manifest_sha256"]
    assert first["media_binding_sha256"] != second["media_binding_sha256"]
    assert second["approved_asset_bindings"][0]["asset_sha256"] == "a" * 64
    assert second["media_binding"]["assets"][0]["sha256"] == "b" * 64
    assert c.validate_provider_request_coverage(second, second["prompt_fragment"], _attach(second), "offline-provider", "fixture-model")["status"] == "shared_request_coverage_valid"
    with pytest.raises(ValueError, match="actual attachments"):
        c.validate_provider_request_coverage(second, second["prompt_fragment"], _attach(first), "offline-provider", "fixture-model")
    binding["tail_evidence"]["human_review_decision"] = "rejected"
    with pytest.raises(Exception):
        c.compile_segment_context(manifest, script, state, ["B1.S02"], media_binding=binding)


def test_owner_holder_support_are_distinct_and_unknown_holder_stops():
    script, manifest, state = production_fixture()
    # Ownership remains 公司; the current holder is explicitly nobody.
    compiled = c.compile_segment_context(manifest, script, state, ["B1.S01"])
    assert compiled["projection"]["props"][0]["owner"]["value"] == "公司"
    assert compiled["projection"]["dynamic_state"]["props"][0]["holder"]["value"] is None
    state["props"][0]["holder"] = c.unknown("没有实际持有人证据")
    with pytest.raises(ValueError, match="dynamic production facts are pending"):
        c.compile_segment_context(manifest, script, state, ["B1.S01"])


def test_false_provenance_changed_hash_and_profile_rewrite_blocked():
    script, manifest, state, compiled = _compile()
    wrong = deepcopy(manifest)
    wrong["actors"][0]["profile"]["appearance"]["value"] = "凭名字猜的长发"
    with pytest.raises(ValueError, match="inferred rewrite"):
        c.production_gate(wrong, script)
    wrong = deepcopy(manifest)
    wrong["provenance_catalog"][0]["sha256"] = "e" * 64
    with pytest.raises(ValueError, match="hash changed"):
        c.production_gate(wrong, script)
    wrong_compiled = deepcopy(compiled)
    wrong_compiled["projection"]["actors"][0]["profile"]["appearance"]["value"] = "错误人物"
    with pytest.raises(ValueError, match="projection or coverage changed"):
        c.render_shared_context(wrong_compiled, manifest, script, state, ["B1.S01"])
    with pytest.raises(ValueError, match="cannot be generated"):
        c.assert_creative_does_not_override({"performance": {"profile": {"wardrobe": "另一件衣服"}}})


def test_scene_change_requires_current_source_action_permission():
    script, manifest, state = production_fixture()
    room2 = deepcopy(manifest["scenes"][0]); room2["id"] = "corridor"
    manifest["scenes"].append(room2)
    extra = deepcopy(manifest["asset_catalog"][0]["subjects"][-1])
    extra.update(subject_key="corridor_subject", entity_id="corridor")
    manifest["asset_catalog"][0]["subjects"].append(extra)
    room2["asset_binding"]["value"]["subject_key"] = "corridor_subject"
    state["global_manifest_sha256"] = c.digest(manifest)
    state.update(previous_scene_id="meeting_room", scene_id="corridor")
    with pytest.raises(ValueError, match="source-event permission"):
        c.compile_segment_context(manifest, script, state, ["B1.S01"])
    permission = {"source_ref": "B1.S02", "from_scene_id": "meeting_room", "to_scene_id": "corridor", "sources": manifest["scenes"][0]["setting"]["sources"]}
    manifest["scene_transition_permissions"] = [permission]
    with pytest.raises(ValueError, match="actual source action"):
        c.validate_shared_manifest(manifest, script)


def test_actual_request_cannot_drop_profiles_asset_or_change_model():
    _, _, _, compiled = _compile()
    with pytest.raises(ValueError, match="complete shared projection"):
        c.validate_provider_request_coverage(compiled, "只有当前演法", _attach(compiled), "offline-provider", "fixture-model")
    with pytest.raises(ValueError, match="actual attachments"):
        c.validate_provider_request_coverage(compiled, compiled["prompt_fragment"], [], "offline-provider", "fixture-model")
    with pytest.raises(ValueError, match="frozen policy"):
        c.validate_provider_request_coverage(compiled, compiled["prompt_fragment"], _attach(compiled), "other-provider", "fixture-model")


def test_undefined_emotion_remains_unknown_without_blocking_physical_state():
    script, manifest, state = production_fixture()
    state["actors"][0]["emotion"] = c.unknown("来源未定义情绪，留给当前创作，不冒充已确认观感")
    compiled = c.compile_segment_context(manifest, script, state, ["B1.S01"])
    assert compiled["nonblocking_dynamic_unknown"] == ["actors.zhou.emotion"]
    assert compiled["projection"]["dynamic_state"]["actors"][0]["emotion"]["value"] is None
    assert "当前情绪：未知，不推断" in compiled["prompt_fragment"]
    state["props"][0]["orientation"] = c.unknown("来源未定义该角度，保留未知")
    compiled = c.compile_segment_context(manifest, script, state, ["B1.S01"])
    assert "props.paper.orientation" in compiled["nonblocking_dynamic_unknown"]
    assert compiled["projection"]["dynamic_state"]["props"][0]["orientation"]["value"] is None
    state["actors"][0]["pose"] = c.unknown("没有物理姿态来源")
    with pytest.raises(ValueError, match="pending"):
        c.compile_segment_context(manifest, script, state, ["B1.S01"])
