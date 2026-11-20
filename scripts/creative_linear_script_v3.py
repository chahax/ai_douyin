"""Complete narrative-order scripts; preliminary budgets never prove actual timing.

New model outputs omit all duration fields. Legacy durations are program-only
placeholders, with a separate proof for the later actual local schedule.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

from scripts import creative_linear_script_v2 as frozen_v2
from src.content_factory.creative_workflow_contract import CreativeContractError, _speech_units

VERSION = "complete_linear_script_v3"
TIMING_STATUS = "preliminary_budget_not_actual"
# These are the existing legacy script validator's per-beat ceiling and whole
# script density allowance, respectively. Neither measures actual delivery.
SPEECH_FLOOR_RATE = 4.5
PROVISIONAL_SPEECH_BUDGET_RATE = 3.5
# A fixed, arbitrary compatibility allowance: NOT measured action/response time.
PROVISIONAL_NON_DIALOGUE_ALLOWANCE_SECONDS = 6.0
EMPTY_ACTION = frozen_v2.EMPTY_ACTION
FIELD_DICTIONARY = deepcopy(frozen_v2.FIELD_DICTIONARY)
FIELD_DICTIONARY.pop("duration_seconds")
RULES = """提交完整新剧本，使用指定工具；不写分析、补丁或局部替换。
剧本只负责故事因果、情绪与表演先后。steps数组是唯一播放顺序：刺激、开口、听后反应及回应按实际先后逐项填写。每拍最多两句对白只是现有对白接口限制，不把一个动作拆成一拍。
每拍只填id/event/trigger/steps；不填duration_seconds、总时长或实际对白秒数。程序初步预算只是兼容投影，任意动作预算未计时；局部表演模型另行安排实际时长、动作重叠与反应窗口，确定性编译再验证。
不要在action再次描述已经播放的同一次说话，不生成before/during/after。明确人物和道具的位置变更及取用前提；按情绪与因果组织叙事拍，可含多个镜头，镜头划分由导演安排，保留必需观察对象切换，不添加无作用动作。
brief的45—60秒为柔性范围，不为凑固定时长删改因果或增添操作。旧稿秒数不是本稿锁定时间。
输入中完整参考只供学习表达机制；保留全部真实输入，结合问题重新创作完整新稿，不把失效旧稿转换格式后当新交付。
"""


def _fail(code: str, message: str) -> None:
    error = CreativeContractError(code + ": " + message)
    error.detail = {"code": code, "blocks_handoff": True, "automatic_retry": False,
                    "semantic_approval": False}
    raise error


def _schema(candidate_id: str, names: list[str] | None) -> dict[str, Any]:
    schema = frozen_v2._schema(candidate_id, names or [])
    beat = schema["properties"]["beats"]["items"]
    del beat["properties"]["duration_seconds"]
    beat["required"].remove("duration_seconds")
    if names is None:
        beat["properties"]["steps"]["items"]["properties"]["speaker"] = {"type": "string"}
    return schema


def build_linear_script_schema(context: dict[str, Any]) -> dict[str, Any]:
    schema = frozen_v2.build_linear_script_schema(context)
    beat = schema["properties"]["beats"]["items"]
    del beat["properties"]["duration_seconds"]
    beat["required"].remove("duration_seconds")
    return schema


def build_linear_script_messages(
    context: dict[str, Any], previous_script: dict[str, Any], issues: Any,
) -> list[dict[str, str]]:
    payload = {"protocol": VERSION, "context": deepcopy(context),
               "previous_script": deepcopy(previous_script), "issues": deepcopy(issues),
               "field_dictionary": deepcopy(FIELD_DICTIONARY),
               "revision_mode": "complete_new_script",
               "timing_responsibility": "script owns narrative order; local performance owns actual schedule; program estimates are not actual windows"}
    return [{"role": "system", "content": RULES},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _validate_source(raw: dict[str, Any], candidate: str, names: list[str] | None) -> None:
    if not isinstance(raw, dict):
        _fail("LINEAR_SCHEMA_INVALID", "必须提交完整对象")
    if raw.get("selected_candidate_id") != candidate:
        _fail("LINEAR_IDENTITY_CHANGED", "完整新稿不能更换已选故事身份")
    errors = list(Draft202012Validator(_schema(candidate, names)).iter_errors(raw))
    if errors:
        _fail("LINEAR_SCHEMA_INVALID", errors[0].message)
    if not raw["title"].strip() or not raw["premise"].strip():
        _fail("LINEAR_SCHEMA_INVALID", "标题和梗概不能为空白")
    seen = set()
    for beat in raw["beats"]:
        if not beat["id"].strip() or beat["id"] in seen:
            _fail("LINEAR_BEAT_ID_INVALID", "每拍ID必须非空且唯一")
        seen.add(beat["id"])
        if not beat["event"].strip() or not beat["trigger"].strip():
            _fail("LINEAR_SCHEMA_INVALID", "事件和刺激不能为空白")
        if sum(s["kind"] == "dialogue" for s in beat["steps"]) > 2:
            _fail("LINEAR_TOO_MANY_DIALOGUES", "每拍最多两句对白")
        for step in beat["steps"]:
            if not step["text"].strip():
                _fail("LINEAR_STEP_TEXT_INVALID", "步骤正文不能为空白")
            if step["kind"] == "action" and step["speaker"] != "":
                _fail("LINEAR_ACTION_SPEAKER_INVALID", "action的speaker必须为空字符串")
            if step["kind"] == "dialogue" and (
                not step["speaker"].strip() or names is not None and step["speaker"] not in names
            ):
                _fail("LINEAR_SPEAKER_INVALID", "对白须有已绑定的真实人物名")


def preliminary_timing_estimates(raw: dict[str, Any]) -> dict[str, Any]:
    """Compute separate deterministic placeholders without editing model source.

    Speech floor assumes the legacy 4.5-unit ceiling; a 3.5-unit budget plus a
    fixed six-second allowance permits legacy display only. No action, pause,
    reaction or actual speech window has been timed or validated.
    """
    if not isinstance(raw, dict):
        _fail("LINEAR_SCHEMA_INVALID", "必须提交完整对象")
    _validate_source(raw, raw.get("selected_candidate_id"), None)
    raw_sha = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    rows = {}
    for beat in raw["beats"]:
        units = sum(_speech_units(s["text"]) for s in beat["steps"] if s["kind"] == "dialogue")
        floor = units / SPEECH_FLOOR_RATE
        speech_budget = units / PROVISIONAL_SPEECH_BUDGET_RATE
        budget = math.ceil(speech_budget + PROVISIONAL_NON_DIALOGUE_ALLOWANCE_SECONDS)
        rows[beat["id"]] = {
            "budget_seconds": budget, "speech_units": units,
            "speech_floor_seconds": floor, "provisional_speech_budget_seconds": speech_budget,
            "provisional_non_dialogue_allowance_seconds": PROVISIONAL_NON_DIALOGUE_ALLOWANCE_SECONDS,
            "action_step_count": sum(s["kind"] == "action" for s in beat["steps"]),
            "action_duration_seconds": None, "pause_duration_seconds": None,
            "actual_dialogue_window_seconds": None, "actual_reaction_window_seconds": None,
            "timing_status": TIMING_STATUS, "actual_windows_verified": False,
            "allowance_basis": "fixed arbitrary compatibility placeholder; actions/pauses/reactions unmeasured",
        }
    return {"schema": VERSION, "raw_sha256": raw_sha, "timing_status": TIMING_STATUS,
            "by_beat_id": rows, "estimated_total_budget_seconds": sum(r["budget_seconds"] for r in rows.values()),
            "speech_floor_units_per_second": SPEECH_FLOOR_RATE,
            "provisional_speech_budget_units_per_second": PROVISIONAL_SPEECH_BUDGET_RATE,
            "actual_windows_verified": False, "action_timing_verified": False,
            "semantic_approval": False, "production_ready": False,
            "required_next_stage": "local_model_actual_schedule_then_deterministic_compile_and_full_joint_review"}


# Explicit alternative name for callers discussing the budget proof.
preliminary_budget_estimates = preliminary_timing_estimates
render_linear_screenplay = frozen_v2.render_linear_screenplay


def accept_linear_script(
    previous: dict[str, Any], raw: dict[str, Any], *,
    character_names: list[str] | None = None,
) -> dict[str, Any]:
    """Return the legacy narrative projection, never a validated timing result.

    The caller must preserve raw and separately bind preliminary_timing_estimates
    by raw SHA. It must not use these durations as actual local schedule windows.
    """
    names = sorted(set(character_names)) if character_names is not None else frozen_v2._names(previous)
    _validate_source(raw, previous["selected_candidate_id"], names)
    proof = preliminary_timing_estimates(raw)
    if (proof["estimated_total_budget_seconds"] > 600
            or any(row["budget_seconds"] > 600 for row in proof["by_beat_id"].values())):
        _fail("LINEAR_PRELIMINARY_COMPATIBILITY_LIMIT",
              "程序暂定预算超过旧投影0—600秒范围；不能自动压缩或当作原稿质量失败")
    projection = deepcopy(raw)
    for beat in projection["beats"]:
        beat["duration_seconds"] = proof["by_beat_id"][beat["id"]]["budget_seconds"]
    return frozen_v2.accept_linear_script(previous, projection, character_names=names)
