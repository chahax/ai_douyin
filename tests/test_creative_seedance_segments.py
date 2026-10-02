from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory.creative_media_capability import audit_creative_executor
from src.content_factory.creative_seedance_segments import (
    ADAPTER_ID, build_seedance_segment_plan, validate_seedance_segment_plan,
)
from src.content_factory.seedance_client import SeedanceConfig
from scripts.compile_creative_seedance_segments import compile_run


def _config():
    return SeedanceConfig(
        api_key="dry-run", provider="ark_api",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seedance-2-0-mini-260615",
    )


def _story():
    script = {
        "beats": [
            {"id": "B01"},
            {"id": "B02"},
            {"id": "B03"},
        ],
    }
    style = {
        "visual_medium": "写实电影质感",
        "palette": "低饱和冷暖对比",
        "spatial_layout": "两人隔桌相对",
        "character_lock": "甲短发深色外套，乙长发浅色外套",
        "light_source": "窗外侧光与室内暖灯",
    }

    def shot(index, continuity):
        return {
            "id": f"SH0{index}", "beat_id": f"B0{index}", "duration_seconds": 8,
            "purpose": "读清反应", "composition": "双人中近景", "camera": "固定机位",
            "visible_performance": "甲停顿，乙抬眼", "event_lock": "两人确认决定",
            "dialogue_lock": ([{"speaker": "甲", "text": "我知道了。"}] if index == 2 else []),
            "start_state": "两人隔桌站立", "end_state": "两人视线相遇",
            "cut_reason": "情绪视角变化", "dialogue_mode": "画内",
            "continuity_mode": continuity, "prompt": "两人确认决定",
            "production_choices": ["固定服装与桌面道具"],
        }

    shots = {
        "style": style,
        "shots": [
            shot(1, "planned_cut_requires_adapter"),
            shot(2, "raw_tail_continuation"),
            shot(3, "planned_cut_requires_adapter"),
        ],
        "media_assumptions": [],
    }
    return script, shots


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_segment_adapter_maps_cut_and_raw_tail_without_remote_submit():
    script, shots = _story()
    config = _config()
    capability = audit_creative_executor(shots, config=config)
    plan = build_seedance_segment_plan(script, shots, capability, config=config)
    assert plan["adapter_id"] == ADAPTER_ID
    assert plan["mapping_status"] == "mapped_submission_locked"
    assert plan["remote_request_sent"] is False
    assert plan["automatic_submit"] is False
    assert [row["opening_frame_source"] for row in plan["segments"]] == [
        "reviewed_opening_frame",
        "preceding_approved_raw_tail",
        "reviewed_new_camera_opening_frame",
    ]
    assert plan["segments"][1]["predecessor_segment_id"] == "SEG001"
    assert "preceding_segment_visual_review_missing" in plan["segments"][1]["blockers_before_submit"]
    assert "offline_cut_assembly_unverified" in plan["segments"][2]["blockers_before_submit"]
    assert all(row["submission_ready"] is False for row in plan["segments"])
    payload = plan["segments"][1]["payload_template"]
    assert payload["model"] == config.model
    assert payload["return_last_frame"] is True
    assert payload["content"][-1]["role"] == "first_frame"
    assert "片段内部不切镜" in payload["content"][0]["text"]
    assert "我知道了" in payload["content"][0]["text"]


def test_segment_adapter_blocks_oversize_shot_instead_of_guessing_semantic_split():
    script, shots = _story()
    shots["shots"][1]["duration_seconds"] = 18
    config = _config()
    capability = audit_creative_executor(shots, config=config)
    plan = build_seedance_segment_plan(script, shots, capability, config=config)
    blocked = plan["segments"][1]
    assert plan["mapping_status"] == "partial_mapping_blocked"
    assert plan["blocked_shots"] == ["SH02"]
    assert blocked["payload_template"] is None
    assert blocked["payload_template_sha256"] is None
    assert "duration_revision_or_semantic_segment_split_required" in blocked["blockers_before_submit"]


def test_segment_plan_is_version_bound_and_tampering_fails_closed():
    script, shots = _story()
    config = _config()
    capability = audit_creative_executor(shots, config=config)
    plan = build_seedance_segment_plan(script, shots, capability, config=config)
    validate_seedance_segment_plan(plan, script, shots, capability, config=config)
    changed = deepcopy(plan)
    changed["segments"][0]["payload_template"]["content"][0]["text"] += "新增情节"
    with pytest.raises(ValueError, match="分段计划"):
        validate_seedance_segment_plan(changed, script, shots, capability, config=config)


def test_segment_adapter_rejects_capability_from_another_model():
    script, shots = _story()
    capability = audit_creative_executor(shots, config=_config())
    changed = deepcopy(capability)
    changed["model"] = "doubao-seedance-2-0-fast-260128"
    with pytest.raises(ValueError, match="配置不一致"):
        build_seedance_segment_plan(script, shots, changed, config=_config())


def test_offline_compiler_binds_handoff_and_keeps_review_failure(tmp_path, monkeypatch):
    script, shots = _story()
    capability = audit_creative_executor(shots, config=_config())
    handoff = {
        "script_sha256": _hash(script), "shots_sha256": _hash(shots),
        "capability_audit_sha256": _hash(capability), "automatic_submit": False,
    }
    state = {
        "status": "needs_revision", "assistant_review_required": True,
        "assistant_review_outcome": "major_issues",
    }
    for name, value in (
        ("SCREENPLAY.json", script), ("STORYBOARD.json", shots),
        ("MEDIA_CAPABILITY_AUDIT.json", capability), ("MEDIA_HANDOFF.json", handoff),
        ("state.json", state),
    ):
        (tmp_path / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        SeedanceConfig, "from_env", classmethod(lambda cls, *args, **kwargs: _config()),
    )
    plan, receipt = compile_run(tmp_path)
    assert receipt["text_gate_status"] == "assistant_review_major_issues"
    assert receipt["remote_request_sent"] is False
    assert plan["automatic_submit"] is False
    script["beats"].append({"id": "B04"})
    (tmp_path / "SCREENPLAY.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="script_sha256"):
        compile_run(tmp_path)


def test_offscreen_dialogue_and_legacy_plan_validation():
    script, shots = _story()
    shots["shots"][1]["dialogue_mode"] = "画外"
    config = _config()
    capability = audit_creative_executor(shots, config=config)
    current = build_seedance_segment_plan(script, shots, capability, config=config)
    text = current["segments"][1]["payload_template"]["content"][0]["text"]
    assert "以下画外对白" in text and "不跟随声音对口型" in text
    legacy = build_seedance_segment_plan(script, shots, capability, config=config, _legacy=True)
    assert legacy["adapter_id"].endswith("/v1")
    validate_seedance_segment_plan(legacy, script, shots, capability, config=config)
    assert current["adapter_id"] == ADAPTER_ID


def test_contradictory_dialogue_mode_blocks_mapping():
    script, shots = _story()
    shots["shots"][1]["dialogue_mode"] = "无对白"
    capability = audit_creative_executor(shots, config=_config())
    result = build_seedance_segment_plan(script, shots, capability, config=_config())
    assert result["blocked_shots"] == ["SH02"]
    assert result["segments"][1]["payload_template"] is None


@pytest.mark.parametrize('source_mode,request_mode',[
    ('画内对白','画内'),('画外对白','画外'),('混合对白','画内/画外')])
def test_v3_compiler_accepts_state_plan_modes_and_preserves_v2(source_mode,request_mode):
    from src.content_factory.creative_seedance_segments import PREVIOUS_ADAPTER_ID
    script,shots=_story()
    shots['shots'][1]['dialogue_mode']=source_mode
    config=_config();capability=audit_creative_executor(shots,config=config)
    current=build_seedance_segment_plan(script,shots,capability,config=config)
    assert not current['blocked_shots']
    prompt=current['segments'][1]['payload_template']['content'][0]['text']
    assert '以下'+request_mode+'对白' in prompt
    original=deepcopy(shots)
    previous=build_seedance_segment_plan(script,shots,capability,config=config,_v2=True)
    assert previous['adapter_id']==PREVIOUS_ADAPTER_ID
    assert previous['blocked_shots']==['SH02']
    validate_seedance_segment_plan(previous,script,shots,capability,config=config)
    assert shots==original
