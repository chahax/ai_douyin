import json
import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.content_factory.creative_workflow import (
    CreativeWorkflow, _apply_candidate_quote_patches,
    _apply_character_quote_patches, _apply_director_revision_patch, _hash,
    _apply_director_feedback_response_patch,
    _apply_missing_analysis_patches, _apply_missing_beat_patches,
    _apply_novel_dialogue_patches, _apply_repair_patches, _apply_writer_revision_patch,
    _apply_writer_action_patches, _apply_writer_timing_patch,
    _audit_review_source_absence_claims,
    _dialogue_compression_options, _dialogue_inventory, _director_repair_evidence,
    _dialogue_split_repair_beat_ids,
    _escape_embedded_json_quotes, _expand_direct_speech_bounds,
    _director_revision_beats,
    _invalid_candidate_quote_paths, _invalid_novel_dialogue_paths,
    _invalid_director_feedback_response_indexes,
    _missing_analysis_fields, _missing_beat_fields,
    _missing_director_feedback_suffix,
    _novel_dialogue_order_repair_beat_ids,
    _issue_beat_ids, _project_legacy_writer_beat_plan, _project_writer_revision,
    _project_missing_check_impacts,
    _project_candidate_meta_quote_as_prose,
    _project_repeated_candidate_evidence_quote_as_prose,
    _project_redundant_source_quote_wrappers,
    _project_explicit_issue_owner,
    _project_director_feedback_candidate_lock,
    _project_director_beat_event_locks,
    _project_director_feedback_response_order,
    _project_feedback_patch_echo_metadata,
    _project_mismatched_raw_tail_to_planned_cut,
    _project_missing_locked_dialogue_split_fields,
    _candidate_with_director_scope,
    _project_blank_dialogue_separators,
    _project_interleaved_dialogue_revision_patch,
    _project_flat_writer_revision_patch,
    _project_noop_director_source_scope,
    _project_redundant_action_dialogue_quotes,
    _project_singleton_dialogue_objects,
    _project_unique_source_dialogue_punctuation,
    _replace_director_feedback_responses,
    _reuse_projection_bound_legacy_beat_repair,
    _parse_format_repair, _project_director_beat_duration_scale, _project_unrequested_analysis_quote_patches,
    _repair_evidence, _revise_selected_source_boundary, _source_scope_audit,
    _story_issues_require_candidate_revision, _story_issues_require_source_boundary,
    _validate_director_feedback_response,
    _validate_director_brief_for_source,
    _validate_director_revision_result,
    _validate_dialogue_split_revision_scope,
    _validate_writer_revision_result,
)
from src.content_factory.creative_workflow_contract import (
    PROMPTS, WRITER_TOOL_SCHEMAS, CreativeContractError,
    _canonical_source_quote, _speech_units, compile_beat_screenplay,
    compile_screenplay_template,
    creative_focus_beat_range, creative_focus_duration_range,
    validate_analysis, validate_candidate_duration,
    validate_creative_focus_action_constraints,
    validate_creative_focus_beat_count, validate_creative_focus_duration,
    validate_candidate_embedded_dialogue_order, validate_director_brief,
    validate_director_shots_or_story_issues,
    validate_script,
    validate_shots,
)
from src.content_factory.creative_workflow_inputs import load_materials
from src.content_factory.creative_workflow_roles import (
    RoleConfig, RoleResult, role_context_capability,
)
from src.content_factory.creative_calibration import (
    calibration_status, record_review, record_revision_review,
    style_class_for_brief, synchronize_review_state,
)
from src.content_factory.creative_media_capability import audit_creative_executor
from src.content_factory.seedance_client import SeedanceConfig
from scripts.run_creative_workflow import claim_logical_task, validate_run_dir_before_claim


SOURCE = "起因句。" + "旁白描写与事件背景。" * 35 + "结局句。"
QUOTED_SOURCE = "甲说：「起因句。」" + "旁白描写与事件背景。" * 35 + "乙回答：「结局句。」"


def test_writer_check_cannot_invent_source_repairs_or_literalize_metaphors():
    prompt = PROMPTS["writer_check"]
    assert "回指性措辞已经向观众提供了前事类别" in prompt
    assert "今日方知姓" in prompt
    assert "当面接受”只要求接受者" in prompt
    assert "你们才说有本事进得来" in prompt
    assert "不得再要求复演瀑布外立约" in prompt
    assert "不得把一个完整词语按单字分给不同人物" in prompt
    assert "不得建议角色自说原文没有的称号" in prompt
    assert "问题 owner 必须按实际修复层级填写" in prompt
    assert "不能仅因切镜或自然停顿判为对白断裂" in prompt
    assert "必须同时阅读 start_state、visible_performance 和 end_state" in prompt
    assert "剧本总时长超出 candidate_lock/creative_focus" in prompt
    assert "proposal 不得新写原文没有的对白、照片、证件" in prompt
    assert "需上游选段/候选修订，不能由当前编剧或导演局部补写" in prompt
    assert "不等于画面必须出现红色/白色脸" in prompt
    assert "即使是 minor 也不能漏掉 impact" in prompt
    assert "10 秒镜头堆入五到七个" in PROMPTS["director_shots"]
    assert "character_lock 必须写确定人数" in PROMPTS["director_shots"]
    assert "换脸、换发色" in PROMPTS["writer_check"]
    assert "不能靠签后撕开一份合同制造甲乙方副本" in PROMPTS["writer_script"]
    assert "窗口只取出并递交所需复印件或材料" in PROMPTS["writer_script"]
    assert "参考片约八成的可用剧本" in PROMPTS["writer_check"]
    assert "相同根因只能列一次" in PROMPTS["writer_check"]
    assert "签署后的甲乙方完整副本不能由撕开一份合同产生" in PROMPTS["writer_check"]
    assert "不能擅自断言人物在前排" in PROMPTS["director_shots"]
    assert "所有“不新增、不得、避免、不可、不猜”" in PROMPTS["writer_check"]
    assert "不得只检查高潮和结尾" in PROMPTS["writer_script"]
    assert "剧本只让安妮沉默坐下" in PROMPTS["director_shots"]
    assert "间接叙述不是可以删除的事件" in PROMPTS["writer_check"]
    assert "桥前 → 欠身上桥头 → 走到桥中" in PROMPTS["writer_script"]
    assert "先完成笑声或起手动作，再说台词" in PROMPTS["writer_revise"]
    assert "两条相邻 dialogue" in PROMPTS["writer_script"]
    assert "同一 speaker" in PROMPTS["writer_revise"]
    assert "所有引文必须严格服从原文出现顺序" in PROMPTS["writer_analysis"]
    assert "必须继续按 selected_source 的出现顺序排列" in PROMPTS["writer_director_feedback"]
    assert "选用的 Q 项必须按编号递增" in PROMPTS["writer_script"]
    assert "间接叙述不等于人物直接引语" in PROMPTS["writer_analysis"]
    assert "不得建议把间接叙述逐字改成人物台词" in PROMPTS["director_brief"]
    assert "全部检查通过时返回空数组" in PROMPTS["director_brief"]
    assert "必须最终锁定一种可执行媒介" in PROMPTS["director_brief"]
    assert "不能让人物视线落向胸前" in PROMPTS["writer_script"]
    assert "仍把选择留给下游" in PROMPTS["writer_check"]
    assert "不得因为 shots.style 没有契约外的 selected_style_id 字段而报问题" in PROMPTS["writer_check"]
    assert "这种凝视会改写人物动机" in PROMPTS["writer_check"]
    assert "仙石、芝兰、车辆、家具" in PROMPTS["writer_analysis"]
    assert "仙石、芝兰、车辆、家具" in PROMPTS["director_brief"]
    assert "仙石、芝兰、车辆、家具" in PROMPTS["writer_script"]
    assert "退回候选层" in PROMPTS["director_shots"]
    assert "不得把“告诉、叮嘱、表示、答应”等间接叙述" in PROMPTS["writer_revise"]
    assert "老师的请求是第二句" in PROMPTS["writer_script"]
    assert "after 已位于本拍全部 dialogue 之后" in PROMPTS["writer_script"]
    assert "已经播放的回答审成尚未发生" in PROMPTS["writer_check"]
    assert "拿来我看！” → after 递出并接住讲义" in PROMPTS["writer_revise"]
    assert "不得把三处证据、两句对白或对白与叙述拼接" in PROMPTS["writer_analysis"]
    assert "依据不足的 fear 明确写“原文未证实”" in PROMPTS["writer_analysis"]
    assert "普通随身或桌内物品" in PROMPTS["writer_analysis"]
    assert "不要强迫编剧在情绪刺激之前单独预演取物" in PROMPTS["director_brief"]
    assert "连续波浪号、连续省略号" in PROMPTS["writer_script"]
    assert "slate 是写字石板" in PROMPTS["writer_script"]
    assert "slate 是写字石板" in PROMPTS["director_shots"]
    assert "不能把英文 slate 审成木板" in PROMPTS["writer_check"]
    assert "不得凭“收束要有重量”把十秒余波夸大成二十秒以上" in PROMPTS["writer_check"]
    assert "不得让同伴或人群新说一句带该姓名的提示" in PROMPTS["writer_script"]
    assert "绝不能建议 Jane、同学或人群新喊一句带该姓名的话" in PROMPTS["writer_check"]
    assert "不得把英文句子的字母数、字符数或去空格长度" in PROMPTS["writer_check"]
    assert "不能在讲义下方凭空添加黑板范图" in PROMPTS["writer_script"]
    assert "不得写成“嘴动但没有出声”" in PROMPTS["writer_script"]
    assert "不能在桌上或讲义下方增加黑板范图" in PROMPTS["director_shots"]
    assert "前镜手指从红线起点移动到中段" in PROMPTS["writer_check"]
    assert "不能把一整段动作路径当作起始状态" in PROMPTS["writer_check"]
    assert "start_state 只描述该镜第一帧已经成立的静态状态" in PROMPTS["director_shots"]
    assert "不能被审成研究室桌上的黑板范图" in PROMPTS["writer_check"]
    assert "不能把“嘴动但没有出声”当成忠实表演" in PROMPTS["writer_check"]
    assert "不能要求删光表情并让文字独占情绪" in PROMPTS["writer_check"]
    assert "用朴素语气逐字说出那句肯定" in PROMPTS["writer_script"]
    assert "脚步保持连续" in PROMPTS["writer_script"]
    assert "保持脚步连续" in PROMPTS["director_shots"]
    assert "对白落音后的反应窗口" in PROMPTS["director_shots"]
    assert "心理停顿与身体停步" in PROMPTS["writer_check"]
    assert "脚步保持连续" in PROMPTS["writer_revise"]
    assert "嘴里发出一声轻笑：对白" in PROMPTS["writer_script"]
    assert "把轻笑写入 during" in PROMPTS["writer_check"]
    assert "不能把五秒静止镜审成一到两秒已满足" in PROMPTS["writer_check"]
    assert "该发声动作移入 before" in PROMPTS["writer_revise"]


def test_reference_benchmark_quality_rules_are_bound_to_every_creative_stage():
    assert "触发条件、可迁移做法及成片中可观察的验收证据" in PROMPTS["reference_summary"]
    assert "至少形成四次清楚可辨的因果推进" in PROMPTS["writer_analysis"]
    assert "至少出现三次有意义变化" in PROMPTS["writer_analysis"]
    assert "建立、上升、转折、峰值、余波" in PROMPTS["director_brief"]
    assert "连续15至20秒" in PROMPTS["writer_script"]
    assert "至少出现三次可感知的视觉状态变化" in PROMPTS["director_shots"]
    assert "因果升级20、情绪递进20、视觉递进20" in PROMPTS["writer_check"]
    assert "总分低于80" in PROMPTS["writer_check"]
    assert "任一项低于该项满分的60%" in PROMPTS["writer_check"]
    assert "决定性动作明确写进 conflict 或 turn" in PROMPTS["writer_analysis"]
    assert "决定性动作前的劝阻、犹豫和许可必须先发生" in PROMPTS["writer_script"]
    assert "表达渠道优化误判为故事未保留" in PROMPTS["writer_check"]
    assert "工作人员接过身份证并开始登记" in PROMPTS["writer_check"]
    assert "上一镜 end_state 与下一镜 start_state完全相同".replace("start_state完全", "start_state 完全") in PROMPTS["writer_check"]


def test_creative_agent_manifest_has_only_writer_and_director_roles():
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "creative_agent_models.json")
        .read_text(encoding="utf-8")
    )
    assert set(manifest["roles"]) == {"writer", "director"}
    assert all(manifest["roles"][role]["api_key_env"] for role in manifest["roles"])
    for role in manifest["roles"]:
        assert manifest["roles"][role]["context_capability"] == {
            key: value for key, value in role_context_capability(role).items()
            if key not in ("provider", "model")
        }


def test_director_revision_replaces_only_affected_beat_shots():
    answers = _answers()
    previous_script = answers[2]
    script = deepcopy(previous_script)
    script["beats"][1]["after"] = "两人相互点头"
    previous_shots = answers[3]
    issues = [{
        "owner": "writer", "location": "B02 / SH02", "evidence": "收束变化",
        "impact": "镜头须同步", "proposal": "更新第二拍", "severity": "major",
    }]
    affected = _director_revision_beats(previous_script, script, previous_shots, issues)
    assert affected == ["B02"]
    replacement = deepcopy(previous_shots["shots"][1])
    replacement["visible_performance"] = "两人相互点头"
    patch = {"replace_beats": [{"beat_id": "B02", "shots": [replacement]}]}
    merged = _apply_director_revision_patch(previous_shots, patch, affected)
    assert merged["shots"][0] == previous_shots["shots"][0]
    assert merged["shots"][1]["visible_performance"] == "两人相互点头"
    assert merged["style"] == previous_shots["style"]
    assert merged["media_assumptions"] == previous_shots["media_assumptions"]


def test_complete_director_feedback_responses_may_be_sorted_locally():
    rows = [
        {"feedback_index": index, "decision": "accepted_in_script", "reason": f"处理 {index}"}
        for index in (0, 1, 2, 4, 5, 3)
    ]
    output = {"candidate_update": {"id": "C01"}, "feedback_responses": rows}

    projected = _project_director_feedback_response_order(output, [{} for _ in range(6)])

    assert projected is not None
    assert [row["feedback_index"] for row in projected["feedback_responses"]] == list(range(6))
    assert output["feedback_responses"] == rows


def test_workflow_merges_compact_director_revision_and_rechecks(tmp_path):
    answers = _answers()
    issue_check = {"story_preserved": True, "issues": [{
        "owner": "director", "location": "SH01 / B01", "evidence": "表情不可读",
        "impact": "观众看不清反应", "proposal": "调整第一拍表演", "severity": "major",
    }], "calibration_focus": []}
    replacement = deepcopy(answers[3]["shots"][0])
    replacement["visible_performance"] = "迟疑表情清楚可见"
    patch = {"replace_beats": [{"beat_id": "B01", "shots": [replacement]}]}
    clients = FakeClients([
        answers[0], answers[1], answers[2], answers[3], issue_check, patch, answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 7
    stored_patch = json.loads((run_dir / "director_revise__01.json").read_text(encoding="utf-8"))
    assert stored_patch["output"] == patch
    storyboard = json.loads((run_dir / "STORYBOARD.json").read_text(encoding="utf-8"))
    assert storyboard["shots"][0]["visible_performance"] == "迟疑表情清楚可见"
    assert storyboard["shots"][1] == answers[3]["shots"][1]


def test_invalid_compact_director_revision_repairs_projected_full_storyboard(tmp_path):
    answers = _answers()
    previous_shots = answers[3]
    invalid_shot = deepcopy(previous_shots["shots"][0])
    invalid_shot["duration_seconds"] = 1
    compact = {"replace_beats": [{"beat_id": "B01", "shots": [invalid_shot]}]}
    valid_shot = deepcopy(previous_shots["shots"][0])
    repair = {"replace_beats": [{"beat_id": "B01", "shots": [valid_shot]}]}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([repair]))
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    payload = {
        "previous_shots": previous_shots,
        "affected_beat_ids": ["B01"],
        "brief": answers[1],
        "script": answers[2],
    }
    corrected = workflow._validate_or_repair(
        "director_revise__01", "director", payload, compact,
        lambda value: _validate_director_revision_result(
            value, previous_shots, ["B01"], answers[1], answers[2],
        ),
    )
    assert corrected["shots"] == previous_shots["shots"]
    projection = next(run_dir.glob("director_revise__01__invalid_projection_*.json"))
    receipt = json.loads(projection.read_text(encoding="utf-8"))
    assert receipt["affected_beat_ids"] == ["B01"]
    assert receipt["output_sha256"] != receipt["source_sha256"]


def test_writer_revision_projects_only_issue_named_beats():
    previous = _answers()[2]
    proposed = deepcopy(previous)
    proposed["beats"][0]["before"] = "模型擅自改了第一拍"
    proposed["beats"][1]["after"] = "第二拍按问题修成相互点头"
    issues = [{
        "owner": "writer", "location": "B02", "evidence": "结尾不清",
        "impact": "关系不明", "proposal": "修第二拍", "severity": "major",
    }]
    affected = _issue_beat_ids(previous, issues)
    assert affected == ["B02"]
    projected = _project_writer_revision(previous, proposed, affected)
    assert projected["beats"][0] == previous["beats"][0]
    assert projected["beats"][1]["after"] == "第二拍按问题修成相互点头"
    assert "模型擅自改了第一拍" not in projected["screenplay_markdown"]
    assert "第二拍按问题修成相互点头" in projected["screenplay_markdown"]


def test_issue_beat_range_expands_every_existing_beat():
    script = deepcopy(_answers()[2])
    for index in range(3, 8):
        row = deepcopy(script["beats"][-1])
        row["id"] = f"B{index:02}"
        script["beats"].append(row)
    issues = [{
        "owner": "writer", "location": "B01-B07 总时长与结尾容量",
        "evidence": "前段均需压缩", "impact": "末段无空间",
        "proposal": "重分全部节拍时长", "severity": "major",
    }]
    assert _issue_beat_ids(script, issues) == [f"B{index:02}" for index in range(1, 8)]


def test_issue_beat_ids_are_found_when_touching_chinese_text():
    script = deepcopy(_answers()[2])
    issues = [{
        "owner": "writer", "location": "B01与B02之间的反应重复",
        "evidence": "B01末尾接着B02开头", "impact": "刺激会像发生两次",
        "proposal": "保留B01一次，直接衔接B02动作", "severity": "major",
    }]

    assert _issue_beat_ids(script, issues) == ["B01", "B02"]

def test_issue_location_does_not_expand_from_unchanged_guardrails():
    script = deepcopy(_answers()[2])
    for index in range(3, 6):
        row = deepcopy(script["beats"][-1])
        row["id"] = f"B{index:02}"
        script["beats"].append(row)
    issues = [{
        "owner": "writer", "location": "B04",
        "evidence": "B04 时长过长", "impact": "节奏拖沓",
        "proposal": "只改 B04；不得改动 B01-B03、B05",
        "severity": "major",
    }]
    assert _issue_beat_ids(script, issues) == ["B04"]


def test_writer_revision_compact_schema_and_merge():
    previous = _answers()[2]
    replacement = deepcopy(previous["beats"][1])
    replacement["after"] = "第二拍按问题修成相互点头"
    patch = {"replace_beats": [{"beat_id": "B02", "beat": replacement}]}
    merged = _apply_writer_revision_patch(previous, patch, ["B02"])
    assert set(WRITER_TOOL_SCHEMAS["writer_revise"]["properties"]) == {"replace_beats"}
    assert merged["beats"][0] == previous["beats"][0]
    assert merged["beats"][1]["after"] == "第二拍按问题修成相互点头"
    assert merged["duration_seconds"] == 20
    assert "第二拍按问题修成相互点头" in merged["screenplay_markdown"]
    assert "不要返回标题、premise、整份 beats、screenplay_markdown" in PROMPTS["writer_revise"]
    assert "对应跳出或穿出动作必须完整移到 before" in PROMPTS["writer_revise"]


def test_legacy_writer_beat_plan_projects_only_current_contract_fields():
    legacy = {
        "title": "旧节拍", "premise": "事件不变", "selected_candidate_id": "C01",
        "duration_seconds": 20, "source_sha256": "ignored",
        "beats": [{
            "beat_id": "B01", "summary": "旧摘要", "characters": ["甲"],
            "on_screen_text": None, "duration_seconds": 20,
        }],
    }
    projected = _project_legacy_writer_beat_plan(legacy)
    assert projected == {
        "title": "旧节拍", "premise": "事件不变", "selected_candidate_id": "C01",
        "duration_seconds": 20,
        "beats": [{"id": "B01", "duration_seconds": 20}],
    }
    assert _project_legacy_writer_beat_plan({**legacy, "beats": [{"id": "B01"}]}) is None


def test_projection_bound_complete_legacy_repair_can_be_reused(tmp_path):
    output = {
        "title": "旧节拍", "premise": "事件不变", "selected_candidate_id": "C01",
        "duration_seconds": 10, "beats": [{"id": "B01", "duration_seconds": 10}],
    }
    payload = {"candidate_lock": {"id": "C01"}}
    required = _missing_beat_fields(output)
    values = {
        "event": "甲走到门前", "trigger": "门铃响起", "before": "甲停下脚步",
        "during": "甲伸手开门", "after": "甲看见来人", "dialogue": [],
    }
    patch = {"patches": [
        {"path": path, "value": values[path[-1]]} for path in required
    ]}
    repaired_text = json.dumps(patch, ensure_ascii=False, separators=(",", ":"))
    raw_text = repaired_text.replace("},{", "}{", 1)
    source_sha = "a" * 64
    projection_path = tmp_path / "writer_script__local_beat_plan_projection_aaaaaaaaaaaa.json"
    projection_path.write_text(json.dumps({
        "schema": "creative_local_beat_plan_projection/v1",
        "source_sha256": source_sha, "output_sha256": _hash(output),
    }), encoding="utf-8")
    repair_path = tmp_path / "writer_script__contract_repair_aaaaaaaaaaaa.json"
    repair_path.write_text(json.dumps({
        "status": "response_received", "source_sha256": source_sha,
        "payload_sha256": _hash(payload), "response_text": raw_text,
        "response_metadata": {"finish_reason": "stop"},
    }), encoding="utf-8")
    format_path = tmp_path / (
        "writer_script__contract_repair_aaaaaaaaaaaa__response__format_repair.json"
    )
    format_path.write_text(json.dumps({
        "status": "response_received", "source_sha256": _hash(raw_text),
        "response_text": repaired_text, "response_metadata": {"finish_reason": "stop"},
    }), encoding="utf-8")

    corrected = _reuse_projection_bound_legacy_beat_repair(
        tmp_path, "writer_script", output, payload, required,
    )
    assert corrected is not None
    assert corrected["beats"][0]["dialogue"] == []
    assert corrected["beats"][0]["after"] == "甲看见来人"
    receipt = json.loads(next(tmp_path.glob(
        "writer_script__local_legacy_repair_reuse_*.json"
    )).read_text(encoding="utf-8"))
    assert receipt["format_repair_record"] == format_path.name
    assert receipt["required_paths"] == required


def test_projection_bound_partial_legacy_repair_is_not_reused(tmp_path):
    output = {
        "title": "旧节拍", "premise": "事件不变", "selected_candidate_id": "C01",
        "duration_seconds": 10, "beats": [{"id": "B01", "duration_seconds": 10}],
    }
    payload = {"candidate_lock": {"id": "C01"}}
    required = _missing_beat_fields(output)
    source_sha = "b" * 64
    (tmp_path / "writer_script__local_beat_plan_projection_bbbbbbbbbbbb.json").write_text(
        json.dumps({
            "schema": "creative_local_beat_plan_projection/v1",
            "source_sha256": source_sha, "output_sha256": _hash(output),
        }), encoding="utf-8",
    )
    partial = {"patches": [{"path": required[0], "value": "只有一项"}]}
    (tmp_path / "writer_script__contract_repair_bbbbbbbbbbbb.json").write_text(
        json.dumps({
            "status": "response_received", "source_sha256": source_sha,
            "payload_sha256": _hash(payload),
            "response_text": json.dumps(partial, ensure_ascii=False),
            "response_metadata": {"finish_reason": "stop"},
        }), encoding="utf-8",
    )
    assert _reuse_projection_bound_legacy_beat_repair(
        tmp_path, "writer_script", output, payload, required,
    ) is None


def test_unique_direct_quote_restores_only_source_punctuation():
    source = "石猴高叫道：「我進去，我進去。」后来又道：「大造化！大造化！」"
    script = {
        "beats": [{"dialogue": [
            {"speaker": "石猴", "text": "我進去！我進去！"},
            {"speaker": "石猴", "text": "大造化！大造化！"},
        ]}],
    }
    path = ["beats", 0, "dialogue", 0, "text"]
    result = _project_unique_source_dialogue_punctuation(script, source, [path])
    assert result is not None
    corrected, changes = result
    assert corrected["beats"][0]["dialogue"][0]["text"] == "我進去，我進去。"
    assert corrected["beats"][0]["dialogue"][1]["text"] == "大造化！大造化！"
    assert changes == [{
        "path": path, "from": "我進去！我進去！", "to": "我進去，我進去。",
    }]


def test_source_dialogue_punctuation_projection_rejects_word_changes_and_ambiguity():
    path = ["beats", 0, "dialogue", 0, "text"]
    changed = {"beats": [{"dialogue": [{"speaker": "石猴", "text": "我要進去！"}]}]}
    assert _project_unique_source_dialogue_punctuation(
        changed, "石猴道：「我進去。」", [path],
    ) is None
    ambiguous = {"beats": [{"dialogue": [{"speaker": "石猴", "text": "我進去！"}]}]}
    assert _project_unique_source_dialogue_punctuation(
        ambiguous, "甲道：「我進去。」乙道：「我進去！」", [path],
    ) is None


def test_english_punctuation_projection_preserves_word_spaces():
    path = ["beats", 0, "dialogue", 0, "text"]
    script = {"beats": [{"dialogue": [{
        "speaker": "Anne", "text": "I have not hope of the Avery."
    }]}]}
    result = _project_unique_source_dialogue_punctuation(
        script, "Anne said, “I have not hope\nof the Avery,” then paused.", [path],
    )
    assert result is not None
    corrected, _ = result
    assert corrected["beats"][0]["dialogue"][0]["text"] == (
        "I have not hope of the Avery,"
    )


def test_punctuation_projection_repairs_safe_subset_and_leaves_mixed_narration():
    source = (
        'Anne said, “I have not hope of the Avery,” then added, '
        '“And I’m not going to look. Please don’t sympathize with me.” '
        'Jane answered, “Oh, Anne I’m so proud!”'
    )
    script = {"beats": [{"dialogue": [
        {"speaker": "Anne", "text": "I have not hope of the Avery."},
        {"speaker": "Anne", "text": "And I'm not going to look. Please don't sympathize with me."},
        {"speaker": "Jane", "text": "Oh, Anne, Jane said proudly, I'm so proud!"},
    ]}]}
    paths = [
        ["beats", 0, "dialogue", 0, "text"],
        ["beats", 0, "dialogue", 1, "text"],
        ["beats", 0, "dialogue", 2, "text"],
    ]
    result = _project_unique_source_dialogue_punctuation(script, source, paths)
    assert result is not None
    corrected, changes = result
    assert corrected["beats"][0]["dialogue"][0]["text"] == (
        "I have not hope of the Avery,"
    )
    assert corrected["beats"][0]["dialogue"][1]["text"] == (
        "And I’m not going to look. Please don’t sympathize with me."
    )
    assert corrected["beats"][0]["dialogue"][2]["text"] == (
        "Oh, Anne, Jane said proudly, I'm so proud!"
    )
    assert [row["path"] for row in changes] == paths[:2]


def test_missing_check_impact_gets_only_conservative_non_release_placeholder():
    check = {"story_preserved": True, "issues": [{
        "owner": "writer", "location": "B05", "evidence": "起点状态不一致",
        "proposal": "补全转身完成状态", "severity": "minor",
    }], "calibration_focus": []}
    result = _project_missing_check_impacts(check)
    assert result is not None
    corrected, indexes = result
    assert indexes == [0]
    assert corrected["issues"][0]["impact"] == (
        "模型未提供影响说明；该问题在补全影响并重新复核前阻止自动放行。"
    )
    assert "impact" not in check["issues"][0]


def test_missing_check_impact_projection_rejects_other_missing_evidence():
    check = {"story_preserved": True, "issues": [{
        "owner": "writer", "location": "B05", "proposal": "补全状态",
        "severity": "major",
    }], "calibration_focus": []}
    assert _project_missing_check_impacts(check) is None


def test_workflow_merges_compact_writer_revision_before_director(tmp_path):
    answers = _answers()
    issue_check = {"story_preserved": False, "issues": [{
        "owner": "writer", "location": "B02", "evidence": "结尾反应不清",
        "impact": "关系未完成", "proposal": "修第二拍结尾", "severity": "major",
    }], "calibration_focus": []}
    replacement = deepcopy(answers[2]["beats"][1])
    replacement["after"] = "两人相互点头并放松"
    patch = {"replace_beats": [{"beat_id": "B02", "beat": replacement}]}
    clients = FakeClients([
        answers[0], answers[1], answers[2], answers[3], issue_check,
        patch, answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    screenplay = json.loads((run_dir / "SCREENPLAY.json").read_text(encoding="utf-8"))
    assert screenplay["beats"][0] == answers[2]["beats"][0]
    assert screenplay["beats"][1]["after"] == "两人相互点头并放松"
    record = json.loads((run_dir / "writer_revise__01.json").read_text(encoding="utf-8"))
    assert record["output"] == patch


def test_invalid_compact_writer_revision_repairs_projected_full_screenplay(tmp_path):
    answers = _answers()
    source = QUOTED_SOURCE
    previous = deepcopy(answers[2])
    previous["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句。"}]
    previous["beats"][1]["dialogue"] = [{"speaker": "乙", "text": "结局句。"}]
    previous["screenplay_markdown"] = compile_beat_screenplay(previous)
    invalid_beat = deepcopy(previous["beats"][0])
    invalid_beat["dialogue"] = [{"speaker": "甲", "text": "起因句。结局句。"}]
    compact = {"replace_beats": [{"beat_id": "B01", "beat": invalid_beat}]}
    dialogue_path = ["beats", 0, "dialogue", 0, "text"]
    repair = {"patches": [{"path": dialogue_path, "value": "起因句。"}]}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([repair]))
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    candidate = answers[0]["candidates"][0]
    payload = {
        "material_ref": {"source_driver": "novel"},
        "selected_source": {"text": source},
        "source_dialogue_inventory": _dialogue_inventory(source),
        "candidate_lock": candidate,
        "previous_script": previous,
        "affected_beat_ids": ["B01"],
    }
    corrected = workflow._validate_or_repair(
        "writer_revise__story_01", "writer", payload, compact,
        lambda value: _validate_writer_revision_result(
            value, previous, ["B01"], candidate, source, "novel",
        ),
    )
    assert corrected["beats"][0]["dialogue"] == [{"speaker": "甲", "text": "起因句。"}]
    assert corrected["beats"][1] == previous["beats"][1]
    projection_files = list(run_dir.glob("writer_revise__story_01__invalid_projection_*.json"))
    assert len(projection_files) == 1
    projection = json.loads(projection_files[0].read_text(encoding="utf-8"))
    assert projection["schema"] == "creative_writer_revision_projection/v1"
    assert projection["affected_beat_ids"] == ["B01"]
    repair_record = json.loads(
        (run_dir / "writer_revise__story_01__contract_repair.json").read_text(encoding="utf-8")
    )
    repair_payload = json.loads(repair_record["request"][1]["content"])
    assert repair_payload["invalid_dialogue"][0]["path"] == dialogue_path
    allowed = repair_payload["allowed_source_spans"][0]["options"]
    assert any(row["text"] == "起因句。" for row in allowed)


def test_mixed_review_issues_do_not_send_director_beats_to_writer(tmp_path):
    answers = _answers()
    mixed_check = {"story_preserved": False, "issues": [
        {
            "owner": "director", "location": "SH01 / B01",
            "evidence": "第一镜表情不可读", "impact": "观众看不清反应",
            "proposal": "导演调整第一拍表演", "severity": "major",
        },
        {
            "owner": "writer", "location": "B02 / SH02",
            "evidence": "第二拍结尾不清", "impact": "关系结果不明",
            "proposal": "编剧修第二拍结尾", "severity": "major",
        },
    ], "calibration_focus": []}
    revised_beat = deepcopy(answers[2]["beats"][1])
    revised_beat["after"] = "两人相互点头并放松"
    writer_patch = {"replace_beats": [{"beat_id": "B02", "beat": revised_beat}]}
    shot_one = deepcopy(answers[3]["shots"][0])
    shot_one["visible_performance"] = "迟疑表情清楚可见"
    shot_two = deepcopy(answers[3]["shots"][1])
    director_patch = {"replace_beats": [
        {"beat_id": "B01", "shots": [shot_one]},
        {"beat_id": "B02", "shots": [shot_two]},
    ]}
    clients = FakeClients([
        answers[0], answers[1], answers[2], answers[3], mixed_check,
        writer_patch, director_patch, answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    record = json.loads((run_dir / "writer_revise__01.json").read_text(encoding="utf-8"))
    payload = json.loads(record["request"]["messages"][1]["content"])
    assert payload["affected_beat_ids"] == ["B02"]
    assert [issue["owner"] for issue in payload["issues"]] == ["writer"]
    assert record["output"] == writer_patch


def test_review_source_absence_claim_is_dismissed_only_when_exact_text_refutes_it():
    script = deepcopy(_answers()[2])
    source_line = "我門中有十二個字，分派起名，到你乃第十輩之小徒矣。"
    script["beats"][1]["dialogue"] = [{"speaker": "祖師", "text": source_line}]
    false_claim = {
        "owner": "writer", "location": "B02 / SH03",
        "evidence": f"B02 对白‘{source_line}’在 selected_source 里并未出现。",
        "impact": "会被误判为选段外文本", "proposal": "需上游选段修订",
        "severity": "blocking",
    }
    subjective_context_claim = {
        "owner": "writer", "location": "B01",
        "evidence": "取得姓氏的前因未出现在本片里。",
        "impact": "观众可能不理解求名原因", "proposal": "需上游选段修订",
        "severity": "major",
    }
    kept, dismissed = _audit_review_source_absence_claims(
        [false_claim, subjective_context_claim], script,
        f"猴王叩头。祖師道：「{source_line}」猴王抬头。",
    )
    assert kept == [subjective_context_claim]
    assert dismissed[0]["issue_index"] == 0
    assert dismissed[0]["contradicted_dialogue"] == [
        {"beat_id": "B02", "text": source_line},
    ]


def _answers():
    analysis = {
        "summary": "两人因误会争执，后来理解彼此。",
        "characters": [{"name": "甲", "want": "解释误会", "source_quote": "起因句。"}],
        "candidates": [{"id": "C01", "title": "误会", "setup": "相遇", "conflict": "误会",
                        "turn": "解释", "peak": "承认", "aftermath": "和解",
                        "start_quote": "起因句。", "end_quote": "结局句。",
                        "duration_seconds": 20, "selection_reason": "事件完整"}],
        "selected_candidate_id": "C01", "selection_reason": "因果清晰", "reference_use": [],
    }
    brief = {
        "style_options": [
            {"id": "S01", "medium": "写实", "palette": "冷暖", "performance_fit": "近景",
             "source_basis": "争执", "tradeoff": "成本高"},
            {"id": "S02", "medium": "二维", "palette": "淡色", "performance_fit": "线条",
             "source_basis": "误会", "tradeoff": "细节少"},
        ],
        "selected_style_id": "S01", "visual_strategy": "近景", "spatial_strategy": "同一空间",
        "performance_strategy": "留反应", "feasibility_notes": [], "writer_feedback": [],
    }
    script = {
        "title": "误会", "premise": "两人消除误会", "selected_candidate_id": "C01",
        "duration_seconds": 20,
        "beats": [
            {"id": "B01", "duration_seconds": 10, "event": "相遇", "trigger": "见面",
             "before": "迟疑", "during": "质问", "after": "停顿", "consequence": "解释", "dialogue": []},
            {"id": "B02", "duration_seconds": 10, "event": "和解", "trigger": "解释",
             "before": "紧张", "during": "理解", "after": "放松", "consequence": "和解", "dialogue": []},
        ],
        "screenplay_markdown": "甲和乙相遇，因误会争执。解释后两人理解彼此。",
    }
    def shot(index, beat):
        return {"id": f"SH0{index}", "beat_id": beat, "duration_seconds": 10,
                "purpose": "看反应", "composition": "双人近景", "camera": "固定",
                "visible_performance": "脸可见", "event_lock": "相遇" if beat == "B01" else "和解",
                "dialogue_lock": [], "start_state": "站着", "end_state": "站着",
                "cut_reason": "节拍转换", "dialogue_mode": "无对白",
                "continuity_mode": "planned_cut_requires_adapter", "prompt": "两人站着",
                "production_choices": []}
    shots = {"style": {"style_option_id": "S01", "visual_medium": "写实", "palette": "冷暖",
                       "spatial_layout": "同一空间", "character_lock": "甲乙", "light_source": "窗"},
             "shots": [shot(1, "B01"), shot(2, "B02")], "media_assumptions": []}
    check = {"story_preserved": True, "issues": [], "calibration_focus": ["人物归属"]}
    return [analysis, brief, script, shots, check]


def test_director_character_lock_rejects_uncertain_headcount():
    answers = _answers()
    shots = deepcopy(answers[3])
    shots["style"]["character_lock"] = "四到六名学生，服装朴素统一"

    with pytest.raises(CreativeContractError, match="锁定确切人数"):
        validate_shots(shots, answers[1], answers[2])


def test_director_shot_rejects_dense_hand_action_sequence():
    answers = _answers()
    shots = deepcopy(answers[3])
    dense = deepcopy(shots["shots"][0])
    dense["duration_seconds"] = 5
    dense["visible_performance"] = (
        "她握住铅笔，取过削笔刀，把笔尖抵进刀口，转动手腕，削出木屑，"
        "搁回铅笔，拨齐卡片，叠成一沓，压平后放回桌角，最后呼出长气"
    )
    tail = deepcopy(shots["shots"][0])
    tail["id"] = "SH01b"
    tail["duration_seconds"] = 5
    shots["shots"] = [dense, tail, shots["shots"][1]]

    with pytest.raises(CreativeContractError, match="连续物理步骤"):
        validate_shots(shots, answers[1], answers[2])


def test_script_rejects_reaction_before_its_first_dialogue_stimulus():
    script = deepcopy(_answers()[2])
    script["beats"][0]["before"] = "学生听到问话后眼神停了一下。"
    script["beats"][0]["dialogue"] = [
        {"speaker": "中年先生", "text": "你能抄下来么？"},
        {"speaker": "青年学生", "text": "可以抄一点。"},
    ]
    script["beats"][0]["during"] = "学生看向讲义。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="before 描写了听到本拍问话"):
        validate_script(script, "C01", "", "reference_video")


def test_script_rejects_later_speaker_answer_completed_in_during():
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [
        {"speaker": "中年先生", "text": "你能抄下来么？"},
        {"speaker": "青年学生", "text": "可以抄一点。"},
    ]
    script["beats"][0]["during"] = "学生答出一点后嘴唇合拢。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="后续说话人已经答出"):
        validate_script(script, "C01", "", "reference_video")


def test_script_rejects_after_that_still_waits_for_played_reply():
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [
        {"speaker": "顾玉荣", "text": "你为什么不接？"},
        {"speaker": "林夏", "text": "我当骚扰电话了。"},
    ]
    script["beats"][0]["after"] = (
        "顾玉荣等待这句回应；林夏嘴唇微张准备开口。"
    )
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="已经结束的后续对白"):
        validate_script(script, "C01", "", "reference_video")


def test_script_rejects_silent_mouth_action_that_replaces_unlocked_speech():
    script = deepcopy(_answers()[2])
    script["beats"][0]["during"] = "Anne嘴唇微微动着说出关于音乐会的紧张与期待。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="表演未锁定的说话内容"):
        validate_script(script, "C01", "", "reference_video")


def test_script_rejects_unshown_position_jump_inside_beat():
    script = deepcopy(_answers()[2])
    script["beats"][0]["before"] = "学生站在桌侧等候。"
    script["beats"][0]["during"] = "学生低头翻看手里的讲义。"
    script["beats"][0]["after"] = "学生站在门边一侧凝视纸页。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="从 桌侧 变到 门边一侧"):
        validate_script(script, "C01", "", "reference_video")


def test_script_rejects_unshown_position_jump_between_adjacent_beats():
    script = deepcopy(_answers()[2])
    script["beats"][0]["after"] = "学生仍站在桌侧，低头看着讲义。"
    script["beats"][1]["before"] = "学生站在门边一侧，继续看着讲义。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="B01→B02.*从 桌侧 跳到 门边一侧"):
        validate_script(script, "C01", "", "reference_video")


def test_script_allows_position_change_across_explicit_time_transition():
    script = deepcopy(_answers()[2])
    script["beats"][0]["after"] = "学生仍站在桌侧，低头看着讲义。"
    script["beats"][1]["event"] = "两三天后，学生再次来到研究室。"
    script["beats"][1]["before"] = "两三天后，学生站在门边一侧，继续看着讲义。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    validate_script(script, "C01", "", "reference_video")


def test_writer_script_missing_body_uses_full_body_repair(tmp_path):
    answers = _answers()
    partial_script = {"title": answers[2]["title"]}
    clients = FakeClients([
        answers[0], answers[1], partial_script, answers[2], answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"

    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))

    assert state["status"] == "media_handoff_pending_capability"
    repair = json.loads(
        (run_dir / "writer_script__contract_repair.json").read_text(encoding="utf-8")
    )
    assert repair["repair_protocol"] == "writer_script_full_body/v1"
    assert "重新提交完整的 writer_script JSON" in repair["request"][0]["content"]
    repair_payload = json.loads(repair["request"][1]["content"])
    assert repair_payload["candidate_lock"]["id"] == "C01"


def test_writer_script_truncated_beat_array_uses_structured_full_body_repair(tmp_path):
    answers = _answers()
    complete_script = deepcopy(answers[2])
    incomplete_script = deepcopy(complete_script)
    incomplete_script["beats"] = incomplete_script["beats"][:2]
    incomplete_script["item"] = {
        **deepcopy(complete_script["beats"][-1]),
        "id": "B06",
    }
    clients = FakeClients([
        answers[0], answers[1], incomplete_script, complete_script, answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"

    state = CreativeWorkflow(
        run_dir,
        clients=clients,
        creative_focus="总时长20秒，二到四个节拍。",
    ).run(_bundle(tmp_path))

    assert state["status"] == "media_handoff_pending_capability"
    repair = json.loads(
        (run_dir / "writer_script__contract_repair.json").read_text(encoding="utf-8")
    )
    assert repair["repair_protocol"] == "writer_script_full_body/v1"
    repair_call = clients.calls[3]
    assert "重新提交完整的 writer_script JSON" in repair_call[1][0]["content"]
    assert clients.call_kwargs[3]["structured_schema"] == WRITER_TOOL_SCHEMAS["writer_script"]


def test_interleaved_dialogue_revision_projection_preserves_all_content():
    patch = {"replace_beats": [{
        "beat_id": "B04", "duration_seconds": 12, "event": "肯定",
        "trigger": "对视", "before": "马修低头", "during": [
            {"action": "马修微笑", "dialogue": None},
            {"action": None, "dialogue": [{"speaker": "Matthew", "text": "First."}]},
            {"action": "安妮抬眼", "dialogue": None},
            {"action": None, "dialogue": [{"speaker": "Matthew", "text": "Second,"}]},
        ],
        "after": "安妮屏息",
        "dialogue": [{"speaker": "Matthew", "text": "First. Second,"}],
    }]}

    projected = _project_interleaved_dialogue_revision_patch(patch, ["B04"])

    assert projected is not None
    beat = projected["replace_beats"][0]["beat"]
    assert beat["before"] == "马修低头；马修微笑"
    assert beat["during"] == "安妮抬眼"
    assert beat["after"] == "安妮屏息"
    assert beat["dialogue"] == [
        {"speaker": "Matthew", "text": "First."},
        {"speaker": "Matthew", "text": "Second,"},
    ]


def test_dialogue_split_projection_drops_only_blank_separator():
    previous = deepcopy(_answers()[2])
    previous["beats"][0]["dialogue"] = [
        {"speaker": "Matthew", "text": "First. Second,"},
    ]
    beat = deepcopy(previous["beats"][0])
    beat["dialogue"] = [
        {"speaker": "Matthew", "text": "First."},
        {"speaker": "Anne", "text": " "},
        {"speaker": "Matthew", "text": " Second,"},
    ]
    patch = {"replace_beats": [{"beat_id": "B01", "beat": beat}]}

    projected = _project_blank_dialogue_separators(patch, previous, ["B01"])

    assert projected is not None
    assert projected["replace_beats"][0]["beat"]["dialogue"] == [
        {"speaker": "Matthew", "text": "First."},
        {"speaker": "Matthew", "text": " Second,"},
    ]


def test_dialogue_split_patch_can_restore_only_omitted_locked_fields():
    previous = deepcopy(_answers()[2])
    parent = previous["beats"][0]
    partial = {
        key: deepcopy(parent[key])
        for key in ("id", "duration_seconds", "event", "trigger", "before")
    }
    partial["during"] = "学生看向老师，随后准备回答。"
    partial["dialogue"] = deepcopy(parent["dialogue"])
    patch = {"replace_beats": [{"beat_id": "B01", "beat": partial}]}

    projected = _project_missing_locked_dialogue_split_fields(
        previous, patch, ["B01"],
    )
    assert projected is not None
    corrected, restored = projected
    assert corrected["replace_beats"][0]["beat"]["after"] == parent["after"]
    assert restored == [{"beat_id": "B01", "field": "after"}]
    _validate_dialogue_split_revision_scope(previous, corrected, ["B01"])

    tampered = deepcopy(patch)
    tampered["replace_beats"][0]["beat"]["after"] = "擅自改写结尾"
    assert _project_missing_locked_dialogue_split_fields(
        previous, tampered, ["B01"],
    ) is None


def test_dialogue_split_revision_cannot_move_final_reaction_into_same_beat():
    previous = deepcopy(_answers()[2])
    previous["beats"][0]["dialogue"] = [
        {"speaker": "Matthew", "text": "First. Second,"},
    ]
    beat = deepcopy(previous["beats"][0])
    beat["dialogue"] = [
        {"speaker": "Matthew", "text": "First."},
        {"speaker": "Matthew", "text": " Second,"},
    ]
    beat["after"] = "Anne提前回以微笑。"
    patch = {"replace_beats": [{"beat_id": "B01", "beat": beat}]}

    with pytest.raises(CreativeContractError, match="锁定字段: after"):
        _validate_dialogue_split_revision_scope(previous, patch, ["B01"])


class FakeClients:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = []
        self.call_kwargs = []
        self.latest_script = None

    def call(self, role, messages, **kwargs):
        self.calls.append((role, messages))
        self.call_kwargs.append(kwargs)
        if "本阶段把已校验的 beat_lock 写成完整" in messages[0]["content"]:
            answer = {"beat_scenes": [
                {"beat_id": beat["id"], "action_segments": [
                    f"{beat['before']}。{beat['during']}。{beat['after']}。"
                    for _ in range(len(beat["dialogue"]) + 1)
                ]}
                for beat in self.latest_script["beats"]
            ]}
        else:
            answer = next(self.answers)
            if isinstance(answer, dict) and "beats" in answer and "screenplay_markdown" in answer:
                self.latest_script = answer
        return RoleResult(json.dumps(answer, ensure_ascii=False),
                          {"role": role, "requested_model": "test", "total_tokens": 1,
                           "finish_reason": "tool_calls" if kwargs.get("structured_schema") is not None else "stop",
                           "output_mode": "tool_call" if kwargs.get("structured_schema") is not None else "content"})


def _bundle(tmp_path):
    path = tmp_path / "novel.txt"
    path.write_text(SOURCE, encoding="utf-8")
    return load_materials(source_driver="novel", title="测试", novel_path=path)


def _quoted_bundle(tmp_path):
    path = tmp_path / "quoted_novel.txt"
    path.write_text(QUOTED_SOURCE, encoding="utf-8")
    return load_materials(source_driver="novel", title="带直接引语的测试", novel_path=path)


def test_full_novel_route_and_blocked_media(tmp_path):
    bundle = _bundle(tmp_path)
    clients = FakeClients(_answers())
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(bundle)
    brief_record = json.loads((run_dir / "director_brief.json").read_text(encoding="utf-8"))
    assert brief_record["request"]["parameters"]["max_tokens"] == 20000
    writer_record = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))
    writer_budget = writer_record["context_budget"]
    assert writer_budget["model"] == "MiniMax-M3"
    assert writer_budget["planning_context_window_tokens"] == 512_000
    assert writer_budget["estimated_total_tokens"] == (
        writer_budget["estimated_input_tokens"]
        + writer_budget["requested_max_output_tokens"]
    )
    context_receipt = json.loads(
        (run_dir / "CONTEXT_STRATEGY.json").read_text(encoding="utf-8")
    )
    assert context_receipt["strategy"]["mode"] == "full"
    assert context_receipt["source_delivery"] == "full_source_text"
    assert context_receipt["not_sent_verbatim_to_initial_analysis"] == []
    assert [role for role, _ in clients.calls] == ["writer", "director", "writer", "director", "writer"]
    assert SOURCE in clients.calls[0][1][1]["content"]
    beat_request = json.loads(clients.calls[2][1][1]["content"])
    assert beat_request["candidate_lock"]["aftermath"] == "和解"
    assert not (run_dir / "writer_screenplay.json").exists()
    assert state["text_pass_sequence"] == 1 and state["video_pass_sequence"] == 0
    assert json.loads((run_dir / "MEDIA_HANDOFF.json").read_text(encoding="utf-8"))["automatic_submit"] is False
    draft = json.loads((run_dir / "EXECUTION_DRAFT.json").read_text(encoding="utf-8"))
    assert draft["generation_segments"] == []
    assert [row["shot_id"] for row in draft["shot_requirements"]] == ["SH01", "SH02"]
    assert draft["automatic_submit"] is False
    capability = json.loads((run_dir / "MEDIA_CAPABILITY_AUDIT.json").read_text(encoding="utf-8"))
    handoff = json.loads((run_dir / "MEDIA_HANDOFF.json").read_text(encoding="utf-8"))
    segment_plan = json.loads((run_dir / "SEEDANCE_SEGMENT_PLAN.json").read_text(encoding="utf-8"))
    assert capability["model"] == handoff["media_model"]
    assert capability["parameter_preflight"]["remote_request_sent"] is False
    assert capability["automatic_submit"] is False
    assert segment_plan["mapping_status"] == "mapped_submission_locked"
    assert segment_plan["automatic_submit"] is False
    assert _hash(segment_plan) == handoff["segment_plan_sha256"]
    packet = json.loads((run_dir / "EDITORIAL_REVIEW_PACKET.json").read_text(encoding="utf-8"))
    assert packet["review_status"] == "assistant_review_pending"
    assert packet["source_scope_audit"]["selected_source_sha256"]
    assert [row["beat_id"] for row in packet["emotion_windows"]] == ["B01", "B02"]
    assert packet["emotion_windows"][0]["shots"][0]["id"] == "SH01"
    check_record = json.loads((run_dir / "writer_check__00.json").read_text(encoding="utf-8"))
    check_payload = json.loads(check_record["request"]["messages"][1]["content"])
    assert check_payload["source_scope_audit"] == packet["source_scope_audit"]
    assert check_payload["candidate_lock"]["aftermath"] == "和解"
    assert (run_dir / "SCREENPLAY.md").exists()
    assert (run_dir / "EDITORIAL_REVIEW_PACKET.md").exists()
    manifest = json.loads(
        (run_dir / "CREATIVE_OUTPUT_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["handoff_sha256"] == _hash(handoff)
    assert manifest["automatic_media_submit"] is False
    assert {row["role"] for row in manifest["stage_handoffs"]} == {"writer", "director"}
    assert manifest["usage_summary"]["calls_started"] == 5
    assert manifest["usage_summary"]["reported_total_tokens"] == 5
    purposes = {row["purpose"] for row in manifest["artifacts"]}
    assert "完整可读剧本" in purposes
    assert "导演分镜、表演与连续性" in purposes
    assert "锁定媒体交接与提交开关" in purposes
    assert "上下文能力依据、估算、分层与未逐字发送范围" in purposes


def test_reference_manifest_records_adaptation_counts(tmp_path):
    novel = tmp_path / "novel.txt"
    novel.write_text(SOURCE, encoding="utf-8")
    text_reference = tmp_path / "direction.md"
    text_reference.write_text("构图分析与节奏证据。", encoding="utf-8")
    json_reference = tmp_path / "observations.json"
    json_reference.write_text(json.dumps([
        {"time": 1, "observation": "先看动作"},
        {"time": 2, "observation": "再看反应"},
    ], ensure_ascii=False), encoding="utf-8")

    bundle = load_materials(
        source_driver="novel", title="参考适配", novel_path=novel,
        reference_paths=[text_reference, json_reference],
    )

    rows = bundle.manifest["reference_adaptation"]
    assert [(row["format"], row["items_read"], row["items_effective"],
             row["items_excluded"]) for row in rows] == [
        ("text", 1, 1, 0), ("json", 2, 2, 0),
    ]
    assert all(row["exclusion_reasons"] == [] and row["characters_read"] > 0 for row in rows)


def test_context_budget_fails_closed_above_verified_role_limit(tmp_path):
    workflow = CreativeWorkflow(tmp_path / "run", clients=FakeClients([]))
    workflow.run_dir.mkdir()
    workflow.state = {
        "calls_started": 0, "max_calls": 20, "max_total_tokens": 2_000_000,
        "revision_rounds": 0, "stages": [],
    }
    messages = [{"role": "user", "content": "字" * 512_000}]
    with pytest.raises(RuntimeError, match="上下文规划上限.*未发送"):
        workflow._reserve_tokens("writer", messages, max_tokens=1)


def test_output_manifest_tamper_blocks_completed_resume(tmp_path):
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    path = run_dir / "CREATIVE_OUTPUT_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["usage_summary"]["calls_started"] = 999
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="输出包总清单版本不符"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_creative_focus_reaches_late_director_and_writer_review(tmp_path):
    focus = "甲亲手递稳麦克风，乙主动接住后才开口"
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers()), creative_focus=focus).run(
        _bundle(tmp_path)
    )
    for stage in ("director_shots", "writer_check__00"):
        record = json.loads((run_dir / f"{stage}.json").read_text(encoding="utf-8"))
        payload = json.loads(record["request"]["messages"][1]["content"])
        assert payload["material_ref"]["creative_focus"] == focus


def test_director_routes_upstream_story_issue_before_shot_design(tmp_path):
    answers = _answers()
    story_issue = {"story_issues": [{
        "owner": "writer", "location": "B02", "evidence": "解释先于可见物证",
        "impact": "观众先听解释才看见证明", "proposal": "把举起物证移到首句前",
        "severity": "major",
    }]}
    revised = deepcopy(answers[2])
    revised["beats"][1]["before"] = "先举起物证再解释"
    revised["screenplay_markdown"] = "甲和乙相遇，因误会争执。甲先举起物证，再解释并和解。"
    clients = FakeClients([answers[0], answers[1], answers[2], story_issue,
                           revised, answers[3], answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["revision_rounds"] == 1
    assert state["calls_started"] == 7
    assert state["revision_committed"] == ["story_issue_round_01"]
    assert json.loads((run_dir / "director_shots.json").read_text(encoding="utf-8"))["output"] == story_issue
    assert (run_dir / "director_shots__story_01.json").exists()
    assert json.loads((run_dir / "SCREENPLAY.json").read_text(encoding="utf-8"))["beats"][1]["before"] == "先举起物证再解释"


def test_director_contract_error_replaces_complete_affected_beat_shots(tmp_path):
    answers = _answers()
    script = deepcopy(answers[2])
    script["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句。"}]
    shots = deepcopy(answers[3])
    replacement = deepcopy(shots["shots"][0])
    replacement["dialogue_lock"] = [{"speaker": "甲", "text": "起因句。"}]
    replacement["dialogue_mode"] = "画内"
    patch = {"replace_beats": [{"beat_id": "B01", "shots": [replacement]}]}
    clients = FakeClients([answers[0], answers[1], script, shots, patch, answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_quoted_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    repair = json.loads(
        (run_dir / "director_shots__contract_repair.json").read_text(encoding="utf-8")
    )
    assert repair["repair_protocol"] == "director_beat_contract_patch/v1"
    request = json.loads(repair["request"][1]["content"])
    assert request["target_beat_ids"] == ["B01"]
    assert request["script_beats"][0]["dialogue"] == [{"speaker": "甲", "text": "起因句。"}]
    assert "shots" not in request and "media_assumptions" not in request


def test_director_story_issue_at_revision_cap_stops_before_media(tmp_path):
    answers = _answers()
    issue = {"story_issues": [{
        "owner": "writer", "location": "B01", "evidence": "前因遗漏",
        "impact": "行动无动机", "proposal": "补前因", "severity": "major",
    }]}
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients([*answers[:3], issue]),
                             max_revisions=0).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert state["calls_started"] == 4
    assert state["revision_rounds"] == 0
    assert not (run_dir / "MEDIA_HANDOFF.json").exists()
    unresolved = json.loads((run_dir / "UNRESOLVED_DRAFT.json").read_text(encoding="utf-8"))
    assert unresolved["shots"] is None
    assert unresolved["automatic_media_submit"] is False


def test_director_story_issue_reserves_budget_for_recheck(tmp_path):
    answers = _answers()
    issue = {"story_issues": [{
        "owner": "writer", "location": "B01", "evidence": "前因遗漏",
        "impact": "行动无动机", "proposal": "补前因", "severity": "major",
    }]}
    run_dir = tmp_path / "run"
    with pytest.raises(RuntimeError, match="预算不足"):
        CreativeWorkflow(run_dir, clients=FakeClients([*answers[:3], issue]),
                         max_calls=6).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 4
    assert state["revision_rounds"] == 0
    assert not (run_dir / "writer_revise__story_01.json").exists()
    assert not (run_dir / "MEDIA_HANDOFF.json").exists()


def test_director_story_issue_shares_revision_cap_with_later_writer_check(tmp_path):
    answers = _answers()
    preflight_issue = {"story_issues": [{
        "owner": "writer", "location": "B01", "evidence": "前因遗漏",
        "impact": "行动无动机", "proposal": "补前因", "severity": "major",
    }]}
    later_issue = {"story_preserved": False, "issues": [{
        "owner": "director", "location": "SH02", "evidence": "切镜漏反应",
        "impact": "情绪断裂", "proposal": "补反应", "severity": "major",
    }], "calibration_focus": []}
    clients = FakeClients([*answers[:3], preflight_issue, answers[2],
                           answers[3], later_issue])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients, max_revisions=1).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert state["revision_rounds"] == 1
    assert state["calls_started"] == 7
    assert not (run_dir / "director_revise__01.json").exists()
    assert not (run_dir / "MEDIA_HANDOFF.json").exists()


def test_director_story_issue_contract_rejects_mixed_or_minor_result():
    brief, script, shots = _answers()[1:4]
    issue = {"owner": "writer", "location": "B01", "evidence": "前因遗漏",
             "impact": "行动无动机", "proposal": "补前因", "severity": "major"}
    validate_director_shots_or_story_issues({"story_issues": [issue]}, brief, script)
    with pytest.raises(CreativeContractError, match="不得混入分镜"):
        validate_director_shots_or_story_issues(
            {"story_issues": [issue], "shots": shots["shots"]}, brief, script,
        )
    with pytest.raises(CreativeContractError, match="主要剧情问题"):
        validate_director_shots_or_story_issues(
            {"story_issues": [{**issue, "severity": "minor"}]}, brief, script,
        )


def test_director_source_boundary_issue_stops_before_local_writer_revision(tmp_path):
    answers = _answers()
    issue = {"owner": "writer", "location": "selected_source 终点",
             "evidence": "关键牵手位于锁定终点之后", "impact": "核心反转没有原文依据",
             "proposal": "扩展 selected_source 选段终点后重新编剧", "severity": "blocking"}
    clients = FakeClients([answers[0], answers[1], answers[2], {"story_issues": [issue]}])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert state["revision_rounds"] == 0
    assert state["calls_started"] == 4
    assert state["upstream_repair_required"] == "selected_source_boundary"
    assert _story_issues_require_source_boundary([issue]) is True
    assert not (run_dir / "writer_revise__story_01.json").exists()
    receipt = json.loads(
        (run_dir / "UPSTREAM_SOURCE_BOUNDARY_REQUIRED.json").read_text(encoding="utf-8")
    )
    assert receipt["automatic_media_submit"] is False


def test_director_candidate_scope_issue_stops_before_local_writer_revision(tmp_path):
    answers = _answers()
    issue = {
        "owner": "writer", "location": "candidate_lock / B01",
        "evidence": "关键告知只有间接叙述，选段没有人物直接引语",
        "impact": "观众听不到刺激，后续反应失去因果",
        "proposal": "需退回候选层，改选有直接对白的事件或修改候选呈现约束",
        "severity": "blocking",
    }
    clients = FakeClients([
        answers[0], answers[1], answers[2], {"story_issues": [issue]},
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert state["revision_rounds"] == 0
    assert state["calls_started"] == 4
    assert state["upstream_repair_required"] == "candidate_revision"
    assert _story_issues_require_candidate_revision([issue]) is True
    assert not (run_dir / "writer_revise__story_01.json").exists()
    receipt = json.loads(
        (run_dir / "UPSTREAM_CANDIDATE_REVISION_REQUIRED.json").read_text(encoding="utf-8")
    )
    assert receipt["automatic_media_submit"] is False


def test_conditional_candidate_fallback_does_not_override_local_beat_fix():
    issue = {
        "owner": "writer",
        "location": "B01",
        "evidence": "节拍漏掉一条已锁定的原文对白",
        "impact": "下一句失去直接刺激",
        "proposal": (
            "在 B01 恢复该原文对白；若不愿恢复，则应退回候选层重选事件。"
        ),
        "severity": "blocking",
    }
    assert _story_issues_require_candidate_revision([issue]) is False


def test_upstream_fallback_does_not_override_concrete_beat_redistribution():
    issue = {
        "owner": "writer",
        "location": "selected_source / B03-B05",
        "evidence": "现稿把连续对白挤入末拍",
        "impact": "刺激与反应窗口被压缩",
        "proposal": (
            "需上游选段/候选修订，不能由当前编剧或导演局部补写；"
            "要么把 B05 拆为两个 beat，要么重新分配 B03-B05 的对白。"
        ),
        "severity": "blocking",
    }

    assert _story_issues_require_source_boundary([issue]) is False
    assert _story_issues_require_candidate_revision([issue]) is False


def test_writer_check_source_boundary_issue_stops_before_local_revision(tmp_path):
    answers = _answers()
    issue = {
        "owner": "writer", "location": "selected_source 起点 / B01",
        "evidence": "剧本新增衣服价签追问，但锁定原文没有这个动作",
        "impact": "核心动机依赖无来源事件",
        "proposal": "需上游选段/候选修订，不能由当前编剧或导演局部补写",
        "severity": "blocking",
    }
    answers[-1] = {
        "story_preserved": False, "issues": [issue], "calibration_focus": [],
    }
    clients = FakeClients(answers)
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert state["revision_rounds"] == 0
    assert state["calls_started"] == 5
    assert state["upstream_repair_required"] == "selected_source_boundary"
    assert not (run_dir / "writer_revise__01.json").exists()
    assert not (run_dir / "director_revise__01.json").exists()
    assert not (run_dir / "MEDIA_HANDOFF.json").exists()
    receipt = json.loads(
        (run_dir / "UPSTREAM_SOURCE_BOUNDARY_REQUIRED.json").read_text(encoding="utf-8")
    )
    assert receipt["writer_check_sha256"]
    assert receipt["automatic_media_submit"] is False


def test_director_can_expand_novel_source_to_immediate_causal_lead_in(tmp_path):
    novel = tmp_path / "novel.txt"
    novel.write_text("诱因句。" + SOURCE, encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="前因选段", novel_path=novel)
    answers = _answers()
    answers[1]["source_scope"] = {
        "lead_in_start_quote": "诱因句。", "reason": "起因句的动作必须有前一句刺激",
    }
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    selection = json.loads((run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8"))
    assert selection["text"].startswith("诱因句。起因句。")
    assert selection["candidate_start_character"] == len("诱因句。")
    assert selection["scope_adjustment"]["source"] == "director_brief"


def test_director_can_extend_novel_source_to_candidate_aftermath(tmp_path):
    novel = tmp_path / "novel.txt"
    novel.write_text(SOURCE + "后续确认动作。", encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="延长终点", novel_path=novel)
    answers = _answers()
    answers[1]["source_scope"] = {
        "extend_end_quote": "后续确认动作。", "reason": "候选收束必须包含确认动作",
    }
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    selection = json.loads((run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8"))
    assert selection["text"].endswith("结局句。后续确认动作。")
    assert selection["candidate_end_character"] == len(SOURCE)
    assert selection["scope_adjustment"]["extend_end_quote"] == "后续确认动作。"
    writer_record = json.loads((run_dir / "writer_script.json").read_text(encoding="utf-8"))
    writer_payload = json.loads(writer_record["request"]["messages"][1]["content"])
    assert writer_payload["selected_source"]["text"] == selection["text"]


def test_director_can_trim_overwide_novel_end_before_writer(tmp_path):
    novel = tmp_path / "novel.txt"
    novel.write_text(SOURCE + "下一场句。", encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="收窄终点", novel_path=novel)
    answers = _answers()
    answers[0]["candidates"][0]["end_quote"] = "下一场句。"
    answers[1]["source_scope"] = {
        "trim_end_quote": "结局句。", "reason": "下一场不进入本片",
    }
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    selection = json.loads((run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8"))
    assert selection["text"] == SOURCE
    assert selection["candidate_end_character"] == len(SOURCE + "下一场句。")
    assert selection["scope_adjustment"]["trim_end_quote"] == "结局句。"
    writer_record = json.loads((run_dir / "writer_script.json").read_text(encoding="utf-8"))
    writer_payload = json.loads(writer_record["request"]["messages"][1]["content"])
    assert writer_payload["selected_source"]["text"] == selection["text"]


def test_director_noop_end_trim_is_locally_cleared_without_repair_call(tmp_path):
    answers = _answers()
    answers[1]["source_scope"] = {
        "trim_end_quote": "结局句。", "reason": "误把原终点再次写成收窄终点",
    }
    projected = _project_noop_director_source_scope(
        answers[1], SOURCE, "novel", answers[0]["candidates"][0],
    )
    assert projected is not None
    assert projected[0]["source_scope"] == {}
    assert projected[1] == ["trim_end_quote"]

    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 5
    assert state["contract_repairs_used"] == 0
    receipts = list(run_dir.glob("director_brief__local_noop_source_scope_*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["schema"] == "creative_local_noop_director_source_scope/v1"
    assert receipt["cleared_fields"] == ["trim_end_quote"]


def test_writer_reconciles_director_preflight_feedback_before_script(tmp_path):
    answers = _answers()
    answers[1]["writer_feedback"] = [{
        "issue": "候选 aftermath 把选段终点后的回家动作写进本片",
        "scope": "candidate.aftermath / selected_source end_quote",
        "proposal": "删去回家，以选段内两人停止争执作为收束",
    }]
    candidate_update = deepcopy(answers[0]["candidates"][0])
    candidate_update["start_quote"] = "导演已通过 selected_source 单独前移的起点"
    candidate_update["aftermath"] = "两人在结局句处停止争执"
    candidate_update["selection_reason"] = "以锁定选段内的停止争执收束"
    negotiation = {
        "candidate_update": candidate_update,
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_candidate_change",
            "reason": "已删除选段终点后的回家动作，并改为选段内收束",
        }],
    }
    clients = FakeClients([
        answers[0], answers[1], negotiation, answers[2], answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))

    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 6
    assert [role for role, _ in clients.calls] == [
        "writer", "director", "writer", "writer", "director", "writer",
    ]
    original = json.loads(
        (run_dir / "writer_analysis.json").read_text(encoding="utf-8")
    )["output"]
    effective = json.loads(
        (run_dir / "EFFECTIVE_ANALYSIS.json").read_text(encoding="utf-8")
    )
    assert original["candidates"][0]["aftermath"] == "和解"
    assert effective["candidates"][0]["aftermath"] == candidate_update["aftermath"]
    assert effective["candidates"][0]["start_quote"] == original["candidates"][0]["start_quote"]
    local_receipts = list(run_dir.glob(
        "writer_director_feedback__local_candidate_lock_*.json"
    ))
    assert len(local_receipts) == 1
    assert json.loads(local_receipts[0].read_text(encoding="utf-8"))[
        "restored_locked_fields"
    ] == ["start_quote"]
    receipt = json.loads(
        (run_dir / "DIRECTOR_FEEDBACK_CANDIDATE_REVISION.json")
        .read_text(encoding="utf-8")
    )
    assert receipt["changed_candidate_fields"] == ["aftermath", "selection_reason"]
    assert receipt["effective_analysis_sha256"] == _hash(effective)
    writer_record = json.loads(
        (run_dir / "writer_script.json").read_text(encoding="utf-8")
    )
    writer_payload = json.loads(writer_record["request"]["messages"][1]["content"])
    assert writer_payload["candidate_lock"]["aftermath"] == candidate_update["aftermath"]
    handoff = json.loads((run_dir / "MEDIA_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["analysis_sha256"] == _hash(effective)
    manifest = json.loads(
        (run_dir / "CREATIVE_OUTPUT_MANIFEST.json").read_text(encoding="utf-8")
    )
    artifact_paths = {row["path"] for row in manifest["artifacts"]}
    assert "DIRECTOR_FEEDBACK_CANDIDATE_REVISION.json" in artifact_paths
    assert "EFFECTIVE_ANALYSIS.json" in artifact_paths


def test_candidate_feedback_cannot_be_deferred_as_director_only():
    candidate = _answers()[0]["candidates"][0]
    feedback = [{
        "issue": "aftermath 位于 selected_source 终点之后",
        "scope": "candidate.aftermath",
        "proposal": "修订候选收束",
    }]
    value = {
        "candidate_update": deepcopy(candidate),
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "director_only",
            "reason": "留给镜头处理",
        }],
    }
    with pytest.raises(CreativeContractError, match="不能推给导演摄影阶段"):
        _validate_director_feedback_response(value, candidate, feedback)


def test_director_feedback_projection_restores_only_locked_candidate_fields():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    update = deepcopy(candidate)
    update["start_quote"] = "导演已在 selected_source 正式前移的起点"
    update["aftermath"] = "在锁定选段内停止争执"
    responses = [{
        "feedback_index": 0,
        "decision": "accepted_candidate_change",
        "reason": "已把收束改回锁定选段范围",
    }]
    projected = _project_director_feedback_candidate_lock({
        "candidate_update": update, "feedback_responses": responses,
    }, candidate)
    assert projected is not None
    corrected, restored, relocated, rejected, stripped, downgraded = projected
    assert restored == ["start_quote"]
    assert relocated is False
    assert rejected == []
    assert stripped == []
    assert downgraded == []
    assert corrected["candidate_update"]["start_quote"] == candidate["start_quote"]
    assert corrected["candidate_update"]["aftermath"] == update["aftermath"]

    nested = deepcopy(update)
    nested["feedback_responses"] = responses
    nested_projected = _project_director_feedback_candidate_lock(
        {"candidate_update": nested}, candidate,
    )
    assert nested_projected is not None
    assert nested_projected[1:] == (["start_quote"], True, [], [], [])
    assert nested_projected[0]["feedback_responses"] == responses
    assert _project_director_feedback_candidate_lock(
        {"candidate_update": {**update, "unrelated": "不明内容"}}, candidate,
    ) is None


def test_director_feedback_projection_rejects_unacknowledged_candidate_changes():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    update = deepcopy(candidate)
    update["setup"] = "模型自行改写的开场"
    update["peak"] = "模型自行改写的高光"
    responses = [{
        "feedback_index": 0,
        "decision": "accepted_in_script",
        "reason": "候选声明已经正确，只在剧本节拍中落实",
    }]
    projected = _project_director_feedback_candidate_lock({
        "candidate_update": update, "feedback_responses": responses,
    }, candidate)

    assert projected is not None
    corrected, restored, relocated, rejected, stripped, downgraded = projected
    assert corrected["candidate_update"] == candidate
    assert restored == []
    assert relocated is False
    assert rejected == ["setup", "peak"]
    assert stripped == []
    assert downgraded == []


def test_director_feedback_projection_strips_known_provider_wrappers():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    update = deepcopy(candidate)
    update["conflict"] = "修正后的冲突"
    nested_response = {
        "feedback_index": 0,
        "decision": "accepted_candidate_change",
        "reason": "已按导演意见修改冲突",
        "field_changes": {"conflict": "修正后的冲突"},
    }
    update["feedback_responses"] = [nested_response]
    output = {
        "candidate_update": update,
        "source_sha256": "abc",
        "source_evidence": [],
        "creative_focus": "仅作回显",
    }

    projected = _project_director_feedback_candidate_lock(output, candidate)

    assert projected is not None
    corrected, restored, relocated, rejected, stripped, downgraded = projected
    assert set(corrected) == {"candidate_update", "feedback_responses"}
    assert corrected["candidate_update"]["conflict"] == "修正后的冲突"
    assert set(corrected["feedback_responses"][0]) == {
        "feedback_index", "decision", "reason",
    }
    assert restored == []
    assert relocated is True
    assert rejected == []
    assert stripped == [
        "creative_focus", "source_evidence", "source_sha256",
        "feedback_responses[0].field_changes",
    ]
    assert downgraded == []


def test_director_feedback_projection_downgrades_noop_change_decision():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    output = {
        "candidate_update": deepcopy(candidate),
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_candidate_change",
            "reason": "候选已经包含所需约束，后续在剧本中落实",
        }],
    }

    projected = _project_director_feedback_candidate_lock(output, candidate)

    assert projected is not None
    corrected, restored, relocated, rejected, stripped, downgraded = projected
    assert corrected["feedback_responses"][0]["decision"] == "accepted_in_script"
    assert restored == []
    assert relocated is False
    assert rejected == []
    assert stripped == []
    assert downgraded == [0]


def test_director_feedback_response_patch_only_appends_exact_missing_suffix():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    feedback = [
        {"issue": f"意见{i}", "scope": "script", "proposal": f"处理{i}"}
        for i in range(5)
    ]
    output = {
        "candidate_update": candidate,
        "feedback_responses": [
            {"feedback_index": i, "decision": "accepted_in_script", "reason": f"已处理{i}"}
            for i in range(4)
        ],
    }
    missing = _missing_director_feedback_suffix(output, feedback)
    assert missing == [4]
    corrected = _apply_director_feedback_response_patch(output, {
        "feedback_responses": [{
            "feedback_index": 4,
            "decision": "accepted_in_script",
            "reason": "在剧本动作与反应窗口中落实",
        }],
    }, missing)
    _validate_director_feedback_response(corrected, candidate, feedback)
    assert corrected["candidate_update"] == candidate
    assert len(output["feedback_responses"]) == 4

    with pytest.raises(CreativeContractError, match="编号、决定或理由无效"):
        _apply_director_feedback_response_patch(output, {
            "feedback_responses": [{
                "feedback_index": 3,
                "decision": "accepted_in_script",
                "reason": "错误编号",
            }],
        }, missing)
    with pytest.raises(CreativeContractError, match="只能包含"):
        _apply_director_feedback_response_patch(output, {
            "feedback_responses": [{
                "feedback_index": 4,
                "decision": "accepted_in_script",
                "reason": "多余字段",
            }],
            "candidate_update": candidate,
        }, missing)


def test_missing_director_feedback_suffix_uses_compact_repair_protocol(tmp_path):
    candidate = deepcopy(_answers()[0]["candidates"][0])
    feedback = [
        {"issue": f"意见{i}", "scope": "script", "proposal": f"处理{i}"}
        for i in range(5)
    ]
    incomplete = {
        "candidate_update": candidate,
        "feedback_responses": [
            {"feedback_index": i, "decision": "accepted_in_script", "reason": f"已处理{i}"}
            for i in range(4)
        ],
    }
    patch = {"feedback_responses": [{
        "feedback_index": 4,
        "decision": "accepted_in_script",
        "reason": "保留可见的动作与反应时长",
    }]}
    clients = FakeClients([patch])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=clients)
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    payload = {
        "candidate_lock": candidate,
        "writer_feedback": feedback,
        "selected_source": {"text": SOURCE},
    }
    corrected = workflow._validate_or_repair(
        "writer_director_feedback", "writer", payload, incomplete,
        lambda value: _validate_director_feedback_response(
            value, candidate, feedback, payload["selected_source"],
        ),
    )
    assert len(corrected["feedback_responses"]) == 5
    repair_path = next(run_dir.glob("writer_director_feedback__contract_repair*.json"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))
    assert repair["repair_protocol"] == "writer_director_feedback_response_patch/v1"
    request = json.loads(repair["request"][1]["content"])
    assert request["missing_feedback"] == [{
        "feedback_index": 4,
        "feedback": feedback[4],
        "candidate_decision_required": False,
    }]
    assert "original" not in request
    assert set(patch) == {"feedback_responses"}


def test_candidate_feedback_cannot_claim_unlocked_next_source_line():
    candidate = _answers()[0]["candidates"][0]
    update = deepcopy(candidate)
    update["aftermath"] = "人物整衣端肃"
    value = {
        "candidate_update": update,
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_candidate_change",
            "reason": "整衣端肃紧接于原文下一行",
        }],
    }
    feedback = [{
        "issue": "原结尾越过 selected_source",
        "scope": "candidate.aftermath",
        "proposal": "改为选段内收束",
    }]
    with pytest.raises(CreativeContractError, match="所谓原文下一行"):
        _validate_director_feedback_response(
            value, candidate, feedback, {"text": SOURCE},
        )


def test_candidate_feedback_may_explicitly_disclaim_unlocked_next_source_line():
    candidate = _answers()[0]["candidates"][0]
    value = {
        "candidate_update": deepcopy(candidate),
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_in_script",
            "reason": (
                '维持锁定起点，不会引用 materials 中未提供的“原文下一行”'
                "或选段之外的事实"
            ),
        }],
    }
    feedback = [{
        "issue": "起点保持不变",
        "scope": "candidate.start_quote",
        "proposal": "维持锁定边界",
    }]

    _validate_director_feedback_response(
        value, candidate, feedback, {"text": SOURCE},
    )


def test_candidate_feedback_may_say_boundary_must_not_extend_to_next_source_line():
    candidate = _answers()[0]["candidates"][0]
    value = {
        "candidate_update": deepcopy(candidate),
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_in_script",
            "reason": (
                "维持锁定起点，本阶段不得以“原文下一行”扩展边界，"
                "因此不加入选段外事实"
            ),
        }],
    }
    feedback = [{
        "issue": "起点保持不变",
        "scope": "candidate.start_quote",
        "proposal": "维持锁定边界",
    }]

    _validate_director_feedback_response(
        value, candidate, feedback, {"text": SOURCE},
    )


def test_repeated_same_field_evidence_quote_is_unquoted_without_changing_words():
    value = deepcopy(_answers()[0])
    candidate = value["candidates"][0]
    candidate["turn"] = (
        '林夏只说“哈？”，洛雪微等他回答。'
        '（原著事实：林夏只回了一个“哈？”；制作设想：保持原地。）'
    )
    problem = "候选故事声明中的逐字原文对白顺序倒置或重复: turn=哈？ → turn=哈？"

    projected, changes = _project_repeated_candidate_evidence_quote_as_prose(
        value, problem,
    )

    assert projected["candidates"][0]["turn"] == (
        '林夏只说“哈？”，洛雪微等他回答。'
        '（原著事实：林夏只回了一个哈？；制作设想：保持原地。）'
    )
    assert changes[0]["unquoted_evidence_occurrences"] == 1
    assert value["candidates"][0]["turn"].count("“哈？”") == 2


def test_redundant_ascii_source_quote_wrapper_is_removed_only_for_unique_inner_text():
    value = deepcopy(_answers()[0])
    value["characters"][0]["source_quote"] = '"几岁了？"'
    value["characters"].append({
        "name": "乙", "want": "等待", "fear": "原文未证实", "source_quote": '"重复"',
    })
    value["candidates"][0]["start_quote"] = '"哈？"'
    source = '她问：“几岁了？”他答：“哈？”重复，后来又重复。'

    projected, changes = _project_redundant_source_quote_wrappers(value, source)

    assert projected["characters"][0]["source_quote"] == "几岁了？"
    assert projected["candidates"][0]["start_quote"] == "哈？"
    assert projected["characters"][1]["source_quote"] == '"重复"'
    assert {row["path"] for row in changes} == {
        "characters[0].source_quote", "candidates[0].start_quote",
    }


def test_candidate_embedded_source_dialogue_must_keep_source_order():
    source = (
        'Mr. Phillips asked, "Anne Shirley, what does this mean?" '
        'Gilbert stood and said, "It was my fault Mr. Phillips. I teased her."'
    )
    candidate = {
        "setup": '老师先问“Anne Shirley, what does this mean?”',
        "conflict": "安妮保持沉默",
        "turn": '吉尔伯特承认“It was my fault Mr. Phillips. I teased her.”',
        "peak": "老师作出处理", "aftermath": "课堂恢复",
    }
    validate_candidate_embedded_dialogue_order(candidate, source)
    inverted = deepcopy(candidate)
    inverted["setup"] = candidate["turn"]
    inverted["turn"] = candidate["setup"]
    with pytest.raises(CreativeContractError, match="对白顺序倒置或重复"):
        validate_candidate_embedded_dialogue_order(inverted, source)


def test_candidate_dialogue_order_ignores_quoted_production_wording():
    source = 'Teacher asked, "First source line." Then he said, "Second source line."'
    candidate = {
        "setup": '画面采用“低饱和固定机位”后说“First source line.”',
        "conflict": "保持停顿", "turn": '他说“Second source line.”',
        "peak": "关系改变", "aftermath": "安静收束",
    }
    validate_candidate_embedded_dialogue_order(candidate, source)


def test_director_feedback_candidate_update_cannot_invert_source_dialogue():
    source = (
        'Mr. Phillips asked, "Anne Shirley, what does this mean?" '
        'Gilbert said, "It was my fault Mr. Phillips. I teased her."'
    )
    candidate = deepcopy(_answers()[0]["candidates"][0])
    update = deepcopy(candidate)
    update["setup"] = '吉尔伯特先说“It was my fault Mr. Phillips. I teased her.”'
    update["turn"] = '老师后问“Anne Shirley, what does this mean?”'
    value = {
        "candidate_update": update,
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_candidate_change",
            "reason": "按导演意见调整候选描述",
        }],
    }
    with pytest.raises(CreativeContractError, match="对白顺序倒置或重复"):
        _validate_director_feedback_response(
            value, candidate,
            [{"issue": "候选顺序", "scope": "candidate", "proposal": "调整"}],
            {"text": source},
        )


def test_quoted_prop_labels_are_not_treated_as_character_dialogue():
    source = (
        'The teacher was writing some verses “To Priscilla” at his desk. '
        'Gilbert took a candy heart with a gold motto on it, “You are sweet,” '
        'and slipped it under Anne’s arm.'
    )
    candidate = deepcopy(_answers()[0]["candidates"][0])
    candidate["turn"] = '糖心上有“You are sweet”字样。'
    candidate["peak"] = '老师先前写过“To Priscilla”诗题。'
    validate_candidate_embedded_dialogue_order(candidate, source)

    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [{
        "speaker": "Gilbert", "text": "You are sweet,",
    }]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="不是所选原文中的人物直接引语"):
        validate_script(script, "C01", source, "novel")


def test_deliberately_slow_dialogue_reserves_action_and_reaction_time():
    script = deepcopy(_answers()[2])
    script["beats"][1].update(
        duration_seconds=12,
        before="说话人语速放稳，郑重开口并短暂停顿",
        during="听者保持注视",
        after="话落后等待反应",
        dialogue=[{"speaker": "甲", "text": "甲" * 50}],
    )
    script["duration_seconds"] = 22
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="放慢、停顿或郑重"):
        validate_script(script, "C01", "", "reference_video")


def test_direct_dialogue_uses_quoted_occurrence_after_same_narration_words():
    source = 'It was Gilbert, near the gate. “Gilbert,” she said, “Thank you.”'
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [{"speaker": "Anne", "text": "Gilbert,"}]
    script["beats"][1]["dialogue"] = [{"speaker": "Anne", "text": "Thank you."}]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")

    narration_only = 'It was Gilbert, near the gate. She stopped walking.'
    with pytest.raises(CreativeContractError, match="不是所选原文中的人物直接引语"):
        validate_script(script, "C01", narration_only, "novel")


def test_drawn_out_dialogue_marks_require_slow_timing_in_beat_and_shot():
    brief = _answers()[1]
    script = deepcopy(_answers()[2])
    chant = "铁如意，指挥倜傥，一座皆惊呢～～；金叵罗，颠倒淋漓噫，千杯未醉嗬～～……。"
    script["beats"][1].update(
        duration_seconds=8,
        dialogue=[{"speaker": "众学生", "text": chant}],
    )
    script["duration_seconds"] = 18
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="放慢、停顿或郑重"):
        validate_script(script, "C01", "", "reference_video")

    shots = deepcopy(_answers()[3])
    shots["shots"][1]["duration_seconds"] = 8
    shots["shots"][1]["dialogue_lock"] = [{"speaker": "众学生", "text": chant}]
    shots["shots"][1]["visible_performance"] = "众学生齐声诵读，先生观察全班"
    with pytest.raises(CreativeContractError, match="放慢、停顿或郑重"):
        validate_shots(shots, brief, script)


def test_shot_transmitted_solemnly_reserves_speaking_time():
    brief = _answers()[1]
    script = deepcopy(_answers()[2])
    speech = "我家師父正才下榻，登壇講道，還未說出原由，就教我出來開門。"
    script["beats"][1]["dialogue"] = [{"speaker": "仙童", "text": speech}]
    script["beats"][1]["duration_seconds"] = 12
    script["duration_seconds"] = 22
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    shots = deepcopy(_answers()[3])
    shots["shots"][1]["duration_seconds"] = 6
    shots["shots"][1]["dialogue_lock"] = [{"speaker": "仙童", "text": speech}]
    shots["shots"][1]["visible_performance"] = (
        "仙童抬颌面向来者，口气收敛为传话般郑重，目光停在对方脸上。"
    )
    continuation = deepcopy(shots["shots"][1])
    continuation["id"] = "SH03"
    continuation["duration_seconds"] = 6
    continuation["dialogue_lock"] = []
    continuation["visible_performance"] = "来者听完后抬眼回应。"
    shots["shots"].append(continuation)
    with pytest.raises(CreativeContractError, match="放慢、停顿或郑重"):
        validate_shots(shots, brief, script)


def test_director_may_split_one_exact_writer_line_across_adjacent_shots():
    brief = _answers()[1]
    script = deepcopy(_answers()[2])
    full_line = "列位呵，人而无信，不知其可。你们才说有本事进得来，就拜他为王。"
    script["beats"][1]["dialogue"] = [{"speaker": "石猿", "text": full_line}]
    script["beats"][1]["duration_seconds"] = 20
    script["duration_seconds"] = 30
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    shots = deepcopy(_answers()[3])
    shots["shots"][1]["duration_seconds"] = 10
    shots["shots"][1]["dialogue_lock"] = [{
        "speaker": "石猿", "text": "列位呵，人而无信，不知其可。",
    }]
    continuation = deepcopy(shots["shots"][1])
    continuation["id"] = "SH03"
    continuation["duration_seconds"] = 10
    continuation["dialogue_lock"] = [{
        "speaker": "石猿", "text": "你们才说有本事进得来，就拜他为王。",
    }]
    shots["shots"].append(continuation)
    validate_shots(shots, brief, script)

    rewritten = deepcopy(shots)
    rewritten["shots"][2]["dialogue_lock"][0]["text"] = "你们曾说有本事进得来，就拜他为王。"
    with pytest.raises(CreativeContractError, match="分镜对白与剧本顺序或内容不符"):
        validate_shots(rewritten, brief, script)


def test_director_reports_all_beat_duration_mismatches_in_one_pass():
    brief = _answers()[1]
    script = _answers()[2]
    shots = deepcopy(_answers()[3])
    shots["shots"][0]["duration_seconds"] = 4
    shots["shots"][1]["duration_seconds"] = 18
    with pytest.raises(CreativeContractError) as failure:
        validate_shots(shots, brief, script)
    message = str(failure.value)
    assert "B01 分镜时长与剧本节拍不符" in message
    assert "B02 分镜时长与剧本节拍不符" in message
    assert "分镜合计 4 秒，剧本 10 秒" in message


def test_duplicate_director_shot_ids_are_locally_resequenced(tmp_path):
    brief = _answers()[1]
    script = _answers()[2]
    duplicate = deepcopy(_answers()[3])
    duplicate["shots"][1]["id"] = duplicate["shots"][0]["id"]
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([]))
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    corrected = workflow._validate_or_repair(
        "director_shots", "director", {"brief": brief, "script": script},
        duplicate, lambda value: validate_shots(value, brief, script),
    )
    assert [row["id"] for row in corrected["shots"]] == ["SH01", "SH02"]
    assert corrected["shots"][1]["visible_performance"] == "脸可见"
    assert workflow.state["calls_started"] == 0
    receipts = list(run_dir.glob("director_shots__local_shot_id_resequence_*.json"))
    assert len(receipts) == 1


def test_long_dialogue_internal_reaction_requires_structural_dialogue_split():
    script = deepcopy(_answers()[2])
    first = "列位先听我把前因说清，今日这一件事关系大家今后的安稳，"
    second = "你们是否愿意一起兑现方才的约定？"
    script["beats"][1].update(
        duration_seconds=24,
        dialogue=[{"speaker": "甲", "text": first + second}],
        during="甲说到前段时，众人陆续抬头",
        after="众人彼此看见，随后点头",
    )
    script["duration_seconds"] = 34
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="语言时间锚点模拟单条长对白内部动作"):
        validate_script(script, "C01", "", "reference_video")

    script["beats"][1].update(
        dialogue=[
            {"speaker": "甲", "text": first},
            {"speaker": "甲", "text": second},
        ],
        during="众人从各处陆续抬头，视线转向甲",
        after="众人彼此看见，随后点头",
    )
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", "", "reference_video")


def test_novel_dialogue_order_patch_rebuilds_only_inverted_beat_range(tmp_path):
    source = (
        "甲先问：“Anne Shirley, what does this mean?” "
        "乙随后答：“It was my fault Mr. Phillips. I teased her.”"
    )
    invalid = deepcopy(_answers()[2])
    invalid["beats"][0]["dialogue"] = [{
        "speaker": "乙", "text": "It was my fault Mr. Phillips. I teased her.",
    }]
    invalid["beats"][1]["dialogue"] = [{
        "speaker": "甲", "text": "Anne Shirley, what does this mean?",
    }]
    invalid["screenplay_markdown"] = compile_beat_screenplay(invalid)
    assert _novel_dialogue_order_repair_beat_ids(invalid, source) == ["B01", "B02"]
    with_later_typo = deepcopy(invalid)
    with_later_typo["beats"][1]["dialogue"].append({
        "speaker": "乙", "text": "A later line with a punctuation typo",
    })
    assert _novel_dialogue_order_repair_beat_ids(
        with_later_typo, source,
    ) == ["B01", "B02"]

    first = deepcopy(invalid["beats"][0])
    second = deepcopy(invalid["beats"][1])
    first["dialogue"] = [{
        "speaker": "甲", "text": "Anne Shirley, what does this mean?",
    }]
    second["dialogue"] = [{
        "speaker": "乙", "text": "It was my fault Mr. Phillips. I teased her.",
    }]
    repair_patch = {"replace_beats": [
        {"beat_id": "B01", "beat": first},
        {"beat_id": "B02", "beat": second},
    ]}
    clients = FakeClients([repair_patch])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=clients)
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    payload = {
        "materials": {"source_driver": "novel"},
        "selected_source": {"text": source},
        "source_dialogue_inventory": [
            {"id": "Q01", "text": "Anne Shirley, what does this mean?"},
            {"id": "Q02", "text": "It was my fault Mr. Phillips. I teased her."},
        ],
    }
    corrected = workflow._validate_or_repair(
        "writer_script", "writer", payload, invalid,
        lambda value: validate_script(value, "C01", source, "novel"),
    )
    assert corrected["beats"][0]["dialogue"] == first["dialogue"]
    assert corrected["beats"][1]["dialogue"] == second["dialogue"]
    repair_path = next(run_dir.glob("writer_script__contract_repair*.json"))
    receipt = json.loads(repair_path.read_text(encoding="utf-8"))
    assert receipt["repair_protocol"] == "writer_dialogue_order_beat_patch/v2"
    request = json.loads(receipt["request"][1]["content"])
    assert request["target_beat_ids"] == ["B01", "B02"]
    assert request["target_duration_seconds"] == 20
    assert [row["text"] for row in request["required_target_dialogue_order"]] == [
        "Anne Shirley, what does this mean?",
        "It was my fault Mr. Phillips. I teased her.",
    ]


def test_dialogue_order_range_includes_all_rows_displaced_by_one_early_jump():
    source = "第一句。第二句。第三句。第四句。"
    plan = deepcopy(_answers()[2])
    plan["beats"] = [deepcopy(plan["beats"][0]) for _ in range(4)]
    for index, beat in enumerate(plan["beats"], start=1):
        beat["id"] = f"B{index:02d}"
    for beat, text_value in zip(
        plan["beats"], ["第一句。", "第四句。", "第二句。", "第三句。"], strict=True,
    ):
        beat["dialogue"] = [{"speaker": "旁白", "text": text_value}]
    assert _novel_dialogue_order_repair_beat_ids(plan, source) == ["B02", "B03", "B04"]


def test_flat_writer_revision_rows_are_wrapped_without_changing_content():
    beat = {
        key: deepcopy(value) for key, value in _answers()[2]["beats"][0].items()
        if key in {
            "id", "duration_seconds", "event", "trigger", "before", "during",
            "after", "dialogue",
        }
    }
    flat = {
        "replace_beats": [{
            "beat_id": beat["id"],
            **{key: value for key, value in beat.items() if key != "id"},
        }],
    }
    projected = _project_flat_writer_revision_patch(flat, ["B01"])
    assert projected == {
        "replace_beats": [{"beat_id": "B01", "beat": beat}],
    }
    assert _project_flat_writer_revision_patch(
        {"replace_beats": [{**flat["replace_beats"][0], "extra": "拒绝"}]}, ["B01"],
    ) is None


def test_dense_physical_steps_cannot_hide_behind_short_dialogue_beat():
    script = deepcopy(_answers()[2])
    script["beats"][1].update(
        duration_seconds=8,
        before="攀住树干，跃下，落地，屈膝，撑地，起身，整衣，上步，站定，拱手，躬身",
        during="保持姿态",
        after="抬眼等待",
        dialogue=[{"speaker": "甲", "text": "甲" * 20}],
    )
    script["duration_seconds"] = 18
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="连续物理步骤"):
        validate_script(script, "C01", "", "reference_video")


def test_dense_physical_steps_are_checked_per_shot():
    brief, script, shots = deepcopy(_answers()[1]), deepcopy(_answers()[2]), deepcopy(_answers()[3])
    shots["shots"][1]["duration_seconds"] = 3
    shots["shots"][1]["visible_performance"] = (
        "攀住树干，跃下，落地，屈膝，撑地，起身，整衣，站定"
    )
    with pytest.raises(CreativeContractError, match="切镜不能代替动作时间"):
        validate_shots(shots, brief, script)


def test_action_cannot_quote_short_or_simplified_dialogue_for_explanation():
    script = deepcopy(_answers()[2])
    script["beats"][1].update(
        during='人物保持站位；来源以"你跟我进来"作结，随后抬眼',
        dialogue=[{"speaker": "甲", "text": "你跟我進來。"}],
    )
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="用引号再次写入已锁定对白片段"):
        validate_script(script, "C01", "", "reference_video")


def test_action_cannot_quote_single_character_dialogue():
    script = deepcopy(_answers()[2])
    script["beats"][1].update(
        during='先前问句落下后，人物简声答"是"，另一人继续观察',
        dialogue=[{"speaker": "甲", "text": "是。"}],
    )
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="用引号再次写入已锁定对白片段"):
        validate_script(script, "C01", "", "reference_video")


def test_quoted_first_person_role_label_is_not_treated_as_repeated_dialogue():
    script = deepcopy(_answers()[2])
    script["beats"][0].update(
        before='短黑发学生装的"我"站在左侧，画内不开口',
        during='"我"维持站姿，听者看向"我"',
        after='"我"仍在原位，听者收住动作',
        dialogue=[{
            "speaker": "我（第一人称画外旁白）",
            "text": "我在学年终结时来告别。",
        }],
    )
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    validate_script(script, "C01", "", "reference_video")


def test_singleton_dialogue_object_is_locally_wrapped_without_model_repair(tmp_path):
    answers = _answers()
    script = deepcopy(answers[2])
    script["beats"][0]["dialogue"] = {"speaker": "甲", "text": "起因句。"}
    projection = _project_singleton_dialogue_objects(script)
    assert projection is not None
    assert projection[0]["beats"][0]["dialogue"] == [
        {"speaker": "甲", "text": "起因句。"},
    ]
    shots = deepcopy(answers[3])
    shots["shots"][0]["dialogue_lock"] = [{"speaker": "甲", "text": "起因句。"}]
    shots["shots"][0]["dialogue_mode"] = "画内"
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(
        run_dir,
        clients=FakeClients([answers[0], answers[1], script, shots, answers[4]]),
        max_contract_repairs=0,
    ).run(_quoted_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 5
    assert state["contract_repairs_used"] == 0
    stored = json.loads((run_dir / "writer_script.json").read_text(encoding="utf-8"))
    assert stored["output"]["beats"][0]["dialogue"] == [
        {"speaker": "甲", "text": "起因句。"},
    ]
    receipts = list(run_dir.glob("writer_script__local_singleton_dialogue_*.json"))
    assert len(receipts) == 1
    assert not list(run_dir.glob("writer_script__contract_repair*.json"))


def test_complete_json_followed_by_exact_duplicate_prefix_is_recovered_locally(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([]))
    workflow.state = {"stages": [], "calls_started": 0}
    value = {"summary": "完整对象", "rows": [{"id": 1, "text": "原文"}]}
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raw = canonical + canonical[:-7]
    assert workflow._decode("writer_analysis", "writer", raw) == value
    receipt = json.loads(
        (run_dir / "writer_analysis__local_duplicate_prefix.json")
        .read_text(encoding="utf-8")
    )
    assert receipt["schema"] == "creative_local_duplicate_json_prefix/v1"
    assert receipt["discarded_duplicate_prefix_characters"] == len(canonical) - 7


def test_writer_director_feedback_adjacent_objects_merge_without_model_repair(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([]))
    workflow.state = {"stages": [], "calls_started": 0}
    first = {"candidate_update": {"id": "C01", "title": "候选"}}
    second = {"feedback_responses": [{
        "feedback_index": 0,
        "decision": "accepted_in_script",
        "reason": "在节拍中落实",
    }]}
    raw = (
        json.dumps(first, ensure_ascii=False, separators=(",", ":"))
        + json.dumps(second, ensure_ascii=False, separators=(",", ":"))
    )
    assert workflow._decode("writer_director_feedback", "writer", raw) == {
        **first, **second,
    }
    receipt = json.loads(
        (run_dir / "writer_director_feedback__local_adjacent_objects_merge.json")
        .read_text(encoding="utf-8")
    )
    assert receipt["schema"] == "creative_local_adjacent_objects_merge/v1"
    assert receipt["first_keys"] == ["candidate_update"]
    assert receipt["second_keys"] == ["feedback_responses"]


def test_backward_quote_in_explicit_meta_explanation_is_unquoted_only():
    value = {
        "candidate_update": {
            "aftermath": "收束于后一句；「前一句」仅作为前段原文引语，不当作后场事实展开。",
        },
        "feedback_responses": [],
    }
    problem = "候选故事声明中的逐字原文对白顺序倒置或重复: peak=后一句 → aftermath=前一句"
    projected = _project_candidate_meta_quote_as_prose(value, problem)
    assert projected is not None
    corrected, change = projected
    assert corrected["candidate_update"]["aftermath"] == (
        "收束于后一句；前一句仅作为前段原文引语，不当作后场事实展开。"
    )
    assert change["quoted_text"] == "前一句"
    assert value["candidate_update"]["aftermath"] == (
        "收束于后一句；「前一句」仅作为前段原文引语，不当作后场事实展开。"
    )


def test_backward_quote_without_explicit_exclusion_is_not_locally_changed():
    value = {
        "candidate_update": {"aftermath": "人物又说：「前一句」"},
        "feedback_responses": [],
    }
    problem = "候选故事声明中的逐字原文对白顺序倒置或重复: peak=后一句 → aftermath=前一句"
    assert _project_candidate_meta_quote_as_prose(value, problem) is None


def test_explicit_issue_repair_layer_corrects_owner_without_rewriting_issue():
    value = {
        "story_preserved": False,
        "issues": [{
            "owner": "director",
            "severity": "major",
            "location": "SH07/SH08/B04",
            "evidence": "当前 B04 总时长不足。",
            "impact": "动作不可读。",
            "proposal": "将 B04.duration_seconds 延长到 15 秒，须由 writer 调整。",
        }],
        "calibration_focus": [],
    }
    projected = _project_explicit_issue_owner(value)
    assert projected is not None
    corrected, changes = projected
    assert corrected["issues"][0]["owner"] == "writer"
    assert corrected["issues"][0]["proposal"] == value["issues"][0]["proposal"]
    assert changes == [{
        "issue_index": 0,
        "from": "director",
        "to": "writer",
        "rule": "issue text explicitly assigned the repair layer",
    }]
    assert value["issues"][0]["owner"] == "director"


def test_chinese_issue_owner_labels_are_normalized_without_changing_issue_text():
    value = {"issues": [
        {"owner": "script/编剧", "location": "B01", "evidence": "缺事件", "impact": "不成立", "proposal": "补事件", "severity": "major"},
        {"owner": "导演", "location": "SH01", "evidence": "机位错", "impact": "跳轴", "proposal": "改机位", "severity": "major"},
    ]}
    projected, changes = _project_explicit_issue_owner(value)
    assert [row["owner"] for row in projected["issues"]] == ["writer", "director"]
    assert [row["evidence"] for row in projected["issues"]] == ["缺事件", "机位错"]
    assert len(changes) == 2


def test_shot_only_proposal_is_projected_to_director_owner():
    value = {
        "story_preserved": True,
        "issues": [{
            "owner": "writer",
            "severity": "major",
            "location": "B01/SH01",
            "evidence": "同一远景挤入两句命令和反应。",
            "impact": "面部反应不可读。",
            "proposal": "把 SH01 拆为 SH01A 与 SH01B，保持 B01 总时长不变。",
        }],
        "calibration_focus": [],
    }
    projected = _project_explicit_issue_owner(value)
    assert projected is not None
    corrected, changes = projected
    assert corrected["issues"][0]["owner"] == "director"
    assert changes[0]["rule"] == "shot-only proposal stays in director layer"


def test_shot_proposal_that_requests_beat_duration_change_stays_writer_owned():
    value = {
        "story_preserved": False,
        "issues": [{
            "owner": "writer",
            "severity": "major",
            "location": "B05/SH06",
            "evidence": "本拍总时长不足。",
            "impact": "动作无法完成。",
            "proposal": "先调整 SH06；若仍不够，向 writer 申请增加 B05.duration_seconds。",
        }],
        "calibration_focus": [],
    }
    assert _project_explicit_issue_owner(value) is None


def test_adjacent_object_merge_is_limited_to_exact_feedback_shape(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([]), max_calls=5)
    workflow.state = {"stages": [], "calls_started": 5, "format_repairs_used": 0}
    raw = '{"candidate_update":{}}{"unexpected":[]}'
    with pytest.raises(CreativeContractError, match="格式"):
        workflow._decode("writer_director_feedback", "writer", raw)


def test_selected_source_anchor_inside_dialogue_expands_to_quote_marks():
    source = "旁白。猴王道：「我雖不是樹上生，卻是石裏長的。」祖師點頭。"
    start = source.index("我雖不是")
    end = source.index("石裏長的") + len("石裏長的")
    expanded_start, expanded_end = _expand_direct_speech_bounds(source, start, end)
    assert source[expanded_start:expanded_end] == "「我雖不是樹上生，卻是石裏長的。」"


def test_director_source_expansion_rejects_quote_after_candidate_start(tmp_path):
    answers = _answers()
    answers[1]["source_scope"] = {
        "lead_in_start_quote": "结局句。", "reason": "错误地向后扩展",
    }
    run_dir = tmp_path / "run"
    with pytest.raises(CreativeContractError, match="不在候选起点前 1200 字内"):
        CreativeWorkflow(
            run_dir, clients=FakeClients(answers), max_contract_repairs=0,
        ).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 2
    assert not (run_dir / "writer_script.json").exists()


def test_director_lead_in_cannot_start_inside_a_sentence():
    source = "Opening clause continues here. " + SOURCE
    candidate = deepcopy(_answers()[0]["candidates"][0])
    brief = deepcopy(_answers()[1])
    brief["source_scope"] = {
        "lead_in_start_quote": "continues here.",
        "trim_start_quote": "",
        "extend_end_quote": "",
        "trim_end_quote": "",
        "reason": "错误地从句中起片",
    }
    with pytest.raises(CreativeContractError, match="起点落在句子或单词中间"):
        _validate_director_brief_for_source(brief, source, "novel", candidate)


def test_director_source_scope_semantic_error_uses_contract_repair(tmp_path):
    bundle = _bundle(tmp_path)
    answers = _answers()
    invalid_brief = deepcopy(answers[1])
    invalid_brief["source_scope"] = {
        "lead_in_start_quote": "不存在且无法唯一定位的前因引文",
        "trim_start_quote": "",
        "reason": "尝试补充直接前因",
    }
    valid_scope = {
        "lead_in_start_quote": "", "trim_start_quote": "", "reason": "",
    }
    valid_brief = {**deepcopy(answers[1]), "source_scope": valid_scope}
    clients = FakeClients([
        answers[0], invalid_brief, {"source_scope": valid_scope},
        answers[2], answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 6
    assert state["contract_repairs_used"] == 1
    repaired = json.loads((run_dir / "director_brief.json").read_text(encoding="utf-8"))
    assert repaired["output"] == valid_brief
    receipt = json.loads(
        (run_dir / "director_brief__contract_repair.json").read_text(encoding="utf-8")
    )
    assert "必须唯一定位" in receipt["error"]
    assert receipt["repair_protocol"] == "director_source_scope_patch/v1"
    repair_payload = json.loads(receipt["request"][1]["content"])
    assert "source_window" in repair_payload
    assert "original" not in repair_payload
    assert "不要返回 style_options" in receipt["request"][0]["content"]


def test_video_director_cannot_claim_novel_scope():
    brief = deepcopy(_answers()[1])
    brief["source_scope"] = {
        "lead_in_start_quote": "某段小说", "trim_start_quote": "", "reason": "前移",
    }
    candidate = deepcopy(_answers()[0]["candidates"][0])
    candidate["start_quote"] = ""
    candidate["end_quote"] = ""
    with pytest.raises(CreativeContractError, match="视频原创导演"):
        _validate_director_brief_for_source(
            brief, "参考片只提供表达方法", "reference_video", candidate,
        )


def test_director_can_trim_overwide_novel_start_before_writer(tmp_path):
    novel = tmp_path / "novel.txt"
    novel.write_text(SOURCE.replace("结局句。", "实际开场句。结局句。"), encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="收窄选段", novel_path=novel)
    answers = _answers()
    answers[1]["source_scope"] = {
        "trim_start_quote": "实际开场句。", "reason": "此前独立场景不进入本片",
    }
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    selection = json.loads((run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8"))
    assert selection["text"] == "实际开场句。结局句。"
    assert selection["candidate_start_character"] == 0
    assert selection["scope_adjustment"]["trim_start_quote"] == "实际开场句。"
    writer_record = json.loads((run_dir / "writer_script.json").read_text(encoding="utf-8"))
    writer_payload = json.loads(writer_record["request"]["messages"][1]["content"])
    assert writer_payload["selected_source"]["text"] == selection["text"]


def test_director_cannot_trim_beyond_candidate_or_expand_and_trim(tmp_path):
    answers = _answers()
    answers[1]["source_scope"] = {
        "lead_in_start_quote": "起因句。", "trim_start_quote": "结局句。",
        "reason": "两个方向冲突",
    }
    with pytest.raises(CreativeContractError, match="不能同时前移和收窄"):
        validate_director_brief(answers[1])
    answers = _answers()
    answers[1]["source_scope"] = {
        "trim_start_quote": "结局句。", "reason": "错误地从结尾开始",
    }
    with pytest.raises(CreativeContractError, match="不在候选原文内部"):
        CreativeWorkflow(
            tmp_path / "end", clients=FakeClients(answers), max_contract_repairs=0,
        ).run(_bundle(tmp_path))
    answers = _answers()
    answers[1]["source_scope"] = {
        "extend_end_quote": "结局句。", "trim_end_quote": "转折句。",
        "reason": "两个方向冲突",
    }
    with pytest.raises(CreativeContractError, match="不能同时延长和收窄"):
        validate_director_brief(answers[1])


def test_director_feedback_omits_checks_that_require_no_action():
    brief = deepcopy(_answers()[1])
    brief["writer_feedback"] = [{
        "issue": "候选未引入关键道具，不存在先出现后起作用的问题",
        "scope": "candidate",
        "proposal": "无需修改。",
    }]

    with pytest.raises(CreativeContractError, match="检查通过结论"):
        validate_director_brief(brief)


def test_selected_director_style_must_choose_one_executable_medium():
    brief = deepcopy(_answers()[1])
    brief["style_options"][0]["medium"] = "低饱和都市写实实拍或高拟真三维"

    with pytest.raises(CreativeContractError, match="锁定一种可执行媒介"):
        validate_director_brief(brief)

    brief["selected_style_id"] = brief["style_options"][1]["id"]
    validate_director_brief(brief)


def test_novel_script_rejects_unsupported_body_gaze_target():
    script = deepcopy(_answers()[2])
    script["beats"][0]["trigger"] = "甲的视线从乙眼睛落到乙胸前衬衫扣"

    with pytest.raises(CreativeContractError, match="原文未支持的身体凝视目标"):
        validate_script(script, "C01", SOURCE, "novel")

    script["beats"][0]["trigger"] = "甲继续向前"
    script["beats"][0]["before"] = "甲目光从路面抬起望向前方，嘴唇微张准备说话"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", SOURCE, "novel")


def test_novel_storyboard_rejects_unsupported_body_gaze_target():
    answers = _answers()
    shots = deepcopy(answers[3])
    shots["shots"][0]["visible_performance"] += "，甲的目光扫向乙领口"

    with pytest.raises(CreativeContractError, match="原文未支持的身体凝视目标"):
        validate_shots(shots, answers[1], answers[2], SOURCE)


def test_execution_draft_tamper_blocks_completed_resume(tmp_path):
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    path = run_dir / "EXECUTION_DRAFT.json"
    draft = json.loads(path.read_text(encoding="utf-8"))
    draft["shot_requirements"][0]["prompt"] = "新剧情"
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="执行预稿"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_seedance_segment_plan_tamper_blocks_completed_resume(tmp_path):
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    path = run_dir / "SEEDANCE_SEGMENT_PLAN.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["segments"][0]["payload_template"]["content"][0]["text"] += "新增情节"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="分段计划已被改动"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_media_capability_audit_blocks_unmapped_cut_and_oversize_shot():
    shots = _answers()[3]
    shots["shots"][1]["duration_seconds"] = 18
    config = SeedanceConfig(
        api_key="dry-run", provider="ark_api",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seedance-2-0-mini-260615",
    )
    audit = audit_creative_executor(shots, config=config)
    assert audit["duration_max"] == 15
    assert audit["shots"][0]["fits_single_model_request"] is True
    assert audit["shots"][1]["fits_single_model_request"] is False
    assert "segment_mapping_or_duration_revision" in audit["shots"][1]["requirements_before_submit"]
    assert "new_camera_opening_frame_and_cut_adapter" in audit["shots"][1]["requirements_before_submit"]
    assert all(row["ready_for_submit"] is False for row in audit["shots"])
    assert audit["schema"] == "creative_media_capability_audit/v2"
    assert audit["segment_adapter"]["local_request_mapping_available"] is True
    assert audit["segment_adapter"]["remote_submission_enabled"] is False
    assert "actual_segment_visual_and_audio_review" in audit["missing_runtime_capabilities"]


def test_all_creative_stages_disable_hidden_thinking(tmp_path):
    class CaptureClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.parameters = []

        def call(self, role, messages, **kwargs):
            self.parameters.append((role, kwargs))
            return super().call(role, messages, **kwargs)

    clients = CaptureClients(_answers())
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert [row[1]["thinking"] for row in clients.parameters] == [
        "disabled", "disabled", "disabled", "disabled", "disabled"
    ]
    record = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))
    assert record["request"]["parameters"]["thinking"] == "disabled"
    director = json.loads((run_dir / "director_brief.json").read_text(encoding="utf-8"))
    assert director["request"]["parameters"]["thinking"] == "disabled"


def test_compiled_screenplay_uses_only_locked_beat_dialogue():
    plan = _answers()[2]
    plan["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句。"}]
    rendered = compile_beat_screenplay(plan)
    assert rendered.count("**甲**：起因句。") == 1
    assert rendered.index("迟疑") < rendered.index("**甲**：起因句。") < rendered.index("质问")
    assert "[[DIALOGUE" not in rendered


def test_compiled_screenplay_preserves_meaningful_english_spaces():
    plan = deepcopy(_answers()[2])
    plan["beats"][0]["dialogue"] = [
        {"speaker": "Anne", "text": "You mean, hateful boy!"},
    ]
    rendered = compile_beat_screenplay(plan)
    assert "**Anne**：You mean, hateful boy!" in rendered
    assert "Youmean,hatefulboy!" not in rendered

    template = compile_screenplay_template(
        {"beat_scenes": [
            {"beat_id": "B01", "action_segments": ["Anne 转身。", "她握住写字石板。"]},
            {"beat_id": "B02", "action_segments": ["教室安静下来。"]},
        ]},
        plan,
    )
    assert "**Anne**：You mean, hateful boy!" in template


def test_slate_source_cannot_be_changed_to_wood_grain():
    source = "Anne brought her slate down and cracked it clear across."
    script = deepcopy(_answers()[2])
    for beat in script["beats"]:
        beat["dialogue"] = []
    script["beats"][1]["during"] = "写字板沿木纹裂成两半"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="slate 改成木板或木纹"):
        validate_script(script, "C01", source, "novel")

    script["beats"][1]["during"] = "写字石板横向裂成两半"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")

    brief = _answers()[1]
    shots = deepcopy(_answers()[3])
    shots["shots"][0]["visible_performance"] = "旧木板沿木纹裂开"
    with pytest.raises(CreativeContractError, match="slate 改成木板或木纹"):
        validate_shots(shots, brief, script, source)


def test_future_blackboard_reference_cannot_create_current_blackboard_diagram():
    source = "先生说：以后你要全照着黑板上那样的画。"
    script = deepcopy(_answers()[2])
    for beat in script["beats"]:
        beat["dialogue"] = []
    script["beats"][0]["before"] = "先生指向讲义下方的黑板范图"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="未来黑板画"):
        validate_script(script, "C01", source, "novel")

    script["beats"][0]["before"] = "先生抬眼看向学生"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")

    brief = _answers()[1]
    shots = deepcopy(_answers()[3])
    shots["shots"][0]["prompt"] = "研究室桌上，讲义下方的黑板范图清晰可见"
    with pytest.raises(CreativeContractError, match="未来黑板画"):
        validate_shots(shots, brief, script, source)


def test_oral_agreement_cannot_be_rendered_as_silent_mouth_motion():
    source = "我虽然觉得有些可惜，却也口头答应着。"
    script = deepcopy(_answers()[2])
    for beat in script["beats"]:
        beat["dialogue"] = []
    script["beats"][0]["after"] = "学生点头，嘴微动一下但没有出声"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="口头答应改成嘴动但没有出声"):
        validate_script(script, "C01", source, "novel")

    script["beats"][0]["after"] = "学生点头；字幕呈现原文叙述"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")

    brief = _answers()[1]
    shots = deepcopy(_answers()[3])
    shots["shots"][0]["visible_performance"] = "学生嘴轻动却不出声"
    with pytest.raises(CreativeContractError, match="口头答应改成嘴动但没有出声"):
        validate_shots(shots, brief, script, source)


def test_long_dialogue_cannot_be_squeezed_into_short_beat():
    plan = _answers()[2]
    plan["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "这一长段话必须给说话和反应留下时间"}]
    plan["beats"][0]["duration_seconds"] = 2
    plan["duration_seconds"] = 12
    plan["screenplay_markdown"] = compile_beat_screenplay(plan)
    with pytest.raises(CreativeContractError, match="对白约.*计时单位无法在"):
        validate_script(plan, "C01", SOURCE, "reference_video")


def test_english_dialogue_timing_counts_words_instead_of_letters():
    assert _speech_units("十分钟后") == 4
    assert _speech_units("I haven't the moral courage.") == 10
    plan = deepcopy(_answers()[2])
    english = (
        "I have not the courage to read the result before everyone, so please "
        "read the announcement and come tell me quickly without trying to soften it."
    )
    plan["beats"][0]["dialogue"] = [{"speaker": "Anne", "text": english}]
    plan["beats"][0]["duration_seconds"] = 15
    plan["beats"][1]["duration_seconds"] = 10
    plan["duration_seconds"] = 25
    plan["screenplay_markdown"] = compile_beat_screenplay(plan)
    validate_script(plan, "C01", SOURCE, "reference_video")


def test_second_dialogue_request_must_precede_transfer_action():
    plan = deepcopy(_answers()[2])
    beat = plan["beats"][1]
    beat["dialogue"] = [
        {"speaker": "学生", "text": "可以抄一点。"},
        {"speaker": "老师", "text": "拿来我看！"},
    ]
    beat["during"] = "学生递出讲义，老师接住并收下"
    beat["after"] = "两人视线落在讲义上"
    plan["screenplay_markdown"] = compile_beat_screenplay(plan)
    with pytest.raises(CreativeContractError, match="第二句请求台词之前提前完成"):
        validate_script(plan, "C01", SOURCE, "reference_video")
    beat["during"] = "学生看着手中的讲义，短暂停顿"
    beat["after"] = "学生递出讲义，老师接住并收下"
    plan["screenplay_markdown"] = compile_beat_screenplay(plan)
    validate_script(plan, "C01", SOURCE, "reference_video")


def test_dialogue_timing_anchor_routes_only_referenced_beat_to_compact_repair():
    plan = deepcopy(_answers()[2])
    assert _dialogue_split_repair_beat_ids(
        plan,
        "B02.during 用语言时间锚点模拟单条长对白内部动作；应拆成相邻 dialogue",
    ) == ["B02"]
    assert _dialogue_split_repair_beat_ids(plan, "B02 对白时长不足") == []


def test_action_cannot_generically_repeat_locked_dialogue_performance():
    plan = deepcopy(_answers()[2])
    plan["beats"][0]["dialogue"] = [{"speaker": "马修", "text": "你会做得很好。"}]
    plan["beats"][0]["during"] = "马修用朴素语气逐字说出那句肯定"
    plan["screenplay_markdown"] = compile_beat_screenplay(plan)
    with pytest.raises(CreativeContractError, match="用泛称再次表演已锁定对白"):
        validate_script(plan, "C01", SOURCE, "reference_video")


def test_novel_dialogue_repair_only_changes_invalid_lines_and_keeps_source_order(tmp_path):
    answers = _answers()
    script = deepcopy(answers[2])
    script["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句。结局句。"}]
    script["beats"][1]["dialogue"] = [{"speaker": "乙", "text": "结局句。！"}]
    required = [["beats", 0, "dialogue", 0, "text"], ["beats", 1, "dialogue", 0, "text"]]
    assert _invalid_novel_dialogue_paths(script, QUOTED_SOURCE) == required
    patch = {"patches": [
        {"path": required[0], "value": "起因句。"},
        {"path": required[1], "value": "结局句。"},
    ]}
    shots = deepcopy(answers[3])
    for shot, line in zip(shots["shots"], ["起因句。", "结局句。"], strict=True):
        shot["dialogue_lock"] = [{"speaker": "甲" if line == "起因句。" else "乙",
                                  "text": line}]
        shot["dialogue_mode"] = "画内"
    clients = FakeClients([answers[0], answers[1], script, patch, shots, answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_quoted_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["contract_repairs_used"] == 1
    repaired = json.loads((run_dir / "writer_script.json").read_text(encoding="utf-8"))["output"]
    assert [line["text"] for beat in repaired["beats"] for line in beat["dialogue"]] == [
        "起因句。", "结局句。",
    ]
    repair = json.loads((run_dir / "writer_script__contract_repair.json")
                        .read_text(encoding="utf-8"))
    payload = json.loads(repair["request"][1]["content"])
    assert [row["path"] for row in payload["invalid_dialogue"]] == required
    assert "original" not in payload


def test_novel_dialogue_patch_rejects_fabricated_text_and_unrequested_paths():
    plan = _answers()[2]
    plan["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "前句。后句。"}]
    plan["beats"][1]["dialogue"] = [{"speaker": "乙", "text": "千歲大王。"}]
    source = "前句。中间题字。后句。群猴称「千歲大王」。"
    required = _invalid_novel_dialogue_paths(plan, source)
    assert required == [["beats", 0, "dialogue", 0, "text"],
                        ["beats", 1, "dialogue", 0, "text"]]
    with pytest.raises(CreativeContractError, match="连续引文"):
        _apply_novel_dialogue_patches(plan, {"patches": [
            {"path": required[0], "value": "伪造台词"},
            {"path": required[1], "value": "千歲大王"},
        ]}, required, source)
    with pytest.raises(CreativeContractError, match="路径"):
        _apply_novel_dialogue_patches(plan, {"patches": [
            {"path": required[1], "value": "千歲大王"},
            {"path": required[0], "value": "前句。"},
        ]}, required, source)


def test_novel_dialogue_patch_also_applies_to_writer_revision(tmp_path):
    source = "他报出洛雪微的名字，店员打电话确认后让他带走衣服。"
    invalid = deepcopy(_answers()[2])
    invalid["beats"][0]["dialogue"] = [{"speaker": "林夏", "text": "洛雪微。"}]
    invalid["screenplay_markdown"] = compile_beat_screenplay(invalid)
    path = ["beats", 0, "dialogue", 0, "text"]
    workflow = CreativeWorkflow(
        tmp_path / "run", clients=FakeClients([{"patches": [{"path": path, "value": ""}]}]),
    )
    workflow.run_dir.mkdir()
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "contract_repairs_used": 0,
        "format_repairs_used": 0, "revision_rounds": 0,
    }
    corrected = workflow._validate_or_repair(
        "writer_revise__01", "writer",
        {"material_ref": {"source_driver": "novel"},
         "selected_source": {"text": source}},
        invalid,
        lambda value: validate_script(value, "C01", source, "novel"),
    )
    assert corrected["beats"][0]["dialogue"] == []
    request = json.loads((workflow.run_dir / "writer_revise__01__contract_repair.json")
                         .read_text(encoding="utf-8"))["request"]
    payload = json.loads(request[1]["content"])
    assert payload["invalid_dialogue"] == [{
        "path": path, "speaker": "林夏", "text": "洛雪微。",
    }]


def test_director_continuity_reports_all_raw_tail_mismatches():
    from src.content_factory.creative_workflow_contract import validate_shots

    _, brief, script, shots, _ = _answers()
    shots["shots"][1]["continuity_mode"] = "raw_tail_continuation"
    shots["shots"][1]["start_state"] = "另一处位置"
    third = deepcopy(shots["shots"][1])
    third["id"] = "SH03"
    third["start_state"] = "又一处位置"
    shots["shots"].append(third)
    with pytest.raises(CreativeContractError, match="SH02,SH03 原始尾帧续段状态不连续"):
        validate_shots(shots, brief, script)


def test_shot_dialogue_cannot_borrow_time_from_silent_shot():
    from src.content_factory.creative_workflow_contract import validate_shots

    _, brief, script, shots, _ = _answers()
    speech = "这段话在一个镜头里说不完还要有演员反应"
    script["beats"][0]["dialogue"] = [{"speaker": "甲", "text": speech}]
    shots["shots"][0]["dialogue_lock"] = [{"speaker": "甲", "text": speech}]
    shots["shots"][0]["duration_seconds"] = 2
    silent = deepcopy(shots["shots"][0])
    silent["id"] = "SH03"
    silent["dialogue_lock"] = []
    silent["duration_seconds"] = 8
    shots["shots"].insert(1, silent)
    with pytest.raises(CreativeContractError, match="SH01 对白约.*无法在 2 秒内"):
        validate_shots(shots, brief, script)


def test_minimax_structured_tool_arguments_are_recorded_and_not_assumed_valid(monkeypatch):
    import openai
    from src.content_factory import creative_workflow_roles as roles

    captured = {}
    tool = SimpleNamespace(function=SimpleNamespace(
        name="submit_creative_json", arguments='{"summary":"only"}',
    ))
    choice = SimpleNamespace(
        finish_reason="tool_calls",
        message=SimpleNamespace(content="", tool_calls=[tool]),
    )
    response = SimpleNamespace(
        choices=[choice], model="MiniMax-M3", id="fake-id",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )

    def create(**kwargs):
        captured.update(kwargs)
        return response

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    monkeypatch.setattr(roles, "role_config", lambda role: RoleConfig(
        "minimax", "MiniMax-M3", "https://example.invalid", "fake-token",
    ))
    result = roles.CreativeRoleClients().call(
        "writer", [{"role": "user", "content": "分析"}],
        thinking="disabled", structured_schema={"type": "object"},
    )
    assert result.text == '{"summary":"only"}'
    assert result.metadata["output_mode"] == "tool_call"
    assert captured["tool_choice"]["function"]["name"] == "submit_creative_json"
    choice.message.tool_calls = []
    with pytest.raises(RuntimeError, match="未返回唯一的结构化工具调用"):
        roles.CreativeRoleClients().call(
            "writer", [{"role": "user", "content": "分析"}],
            thinking="disabled", structured_schema={"type": "object"},
        )
    choice.message.content = '{"summary":"from content"}'
    with pytest.raises(roles.RoleResponseError) as rejected:
        roles.CreativeRoleClients().call(
            "writer", [{"role": "user", "content": "分析"}],
            thinking="disabled", structured_schema={"type": "object"},
        )
    assert rejected.value.response_text == '{"summary":"from content"}'
    assert rejected.value.response_metadata["response_fault_code"] == "REQUIRED_TOOL_MISSING"
    assert rejected.value.response_payload["choices"][0]["message"]["content"] == rejected.value.response_text
    response.model = "unexpected-writer-model"
    with pytest.raises(RuntimeError, match="返回模型与已确认角色配置不符"):
        roles.CreativeRoleClients().call(
            "writer", [{"role": "user", "content": "分析"}],
            thinking="disabled", structured_schema={"type": "object"},
        )


def test_deepseek_director_disables_default_thinking(monkeypatch):
    import openai
    from src.content_factory import creative_workflow_roles as roles

    captured = {}
    choice = SimpleNamespace(
        finish_reason="stop",
        message=SimpleNamespace(content='{"style_options":[]}', tool_calls=[]),
    )
    response = SimpleNamespace(
        choices=[choice], model="deepseek-flash", id="director-id",
        usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4, total_tokens=12),
    )

    def create(**kwargs):
        captured.update(kwargs)
        return response

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create),
    ))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
    monkeypatch.setattr(roles, "role_config", lambda role: RoleConfig(
        "deepseek", "deepseek-flash", "https://example.invalid", "fake-token",
    ))
    result = roles.CreativeRoleClients().call(
        "director", [{"role": "user", "content": "分镜"}], thinking="disabled",
    )
    assert result.metadata["thinking_mode"] == "disabled"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_missing_tool_call_stops_same_task_resume_without_retry(tmp_path):
    class ProtocolClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.failed_once = False

        def call(self, role, messages, **kwargs):
            if not self.failed_once:
                self.failed_once = True
                raise RuntimeError("writer API 未返回唯一的结构化工具调用")
            return super().call(role, messages, **kwargs)

    clients = ProtocolClients(_answers())
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(RuntimeError, match="未返回唯一的结构化工具调用"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    before = (run_dir / "state.json").read_bytes()
    with pytest.raises(CreativeContractError, match="REQUIRED_TOOL_MISSING"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 1
    assert not (run_dir / "writer_analysis__protocol_attempt_01.json").exists()


def test_missing_tool_call_with_prose_stops_without_json_repair(tmp_path):
    class ProtocolContentClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.failed_once = False

        def call(self, role, messages, **kwargs):
            if not self.failed_once:
                self.failed_once = True
                self.calls.append((role, messages))
                self.call_kwargs.append(kwargs)
                return RoleResult(
                    "I'll analyze the locked selection, then build candidates.",
                    {
                        "role": role,
                        "requested_model": "test",
                        "finish_reason": "tool_calls",
                        "output_mode": "content_after_missing_tool_call",
                        "total_tokens": 1,
                    },
                )
            return super().call(role, messages, **kwargs)

    clients = ProtocolContentClients(_answers())
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    for _ in range(2):
        with pytest.raises(CreativeContractError, match="REQUIRED_TOOL_MISSING"):
            CreativeWorkflow(run_dir, clients=clients).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 1 and len(clients.calls) == 1
    assert state["format_repairs_used"] == 0
    assert not (run_dir / "writer_analysis__protocol_attempt_01.json").exists()
    assert not (run_dir / "writer_analysis__format_repair.json").exists()


def test_source_dialogue_inventory_preserves_characters_and_context():
    source = "众猴道：「我等即拜他为王。」石猴应声道：「我進去，\n我進去。」女子问：“饿了？”"
    rows = _dialogue_inventory(source)
    assert [row["text"] for row in rows] == ["我等即拜他为王。", "我進去，我進去。", "饿了？"]
    assert "石猴应声道" in rows[1]["before"]
    assert "女子问" in rows[2]["before"]


def test_nested_source_quote_must_keep_its_closing_delimiter():
    source = "童子道：「說：『外面有個修行的來了，可去接待接待。』想必就是你了？」"
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [{
        "speaker": "童子", "text": "說：『外面有個修行的來了，可去接待接待。",
    }]
    script["beats"][1]["dialogue"] = [{
        "speaker": "童子", "text": "想必就是你了？",
    }]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="漏掉对应结束符"):
        validate_script(script, "C01", source, "novel")

    script["beats"][0]["dialogue"][0]["text"] += "』"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")


def test_source_scope_audit_surfaces_long_omitted_lead_in_without_auto_rejecting():
    lead_in = "甲问：“你真要离开？”乙答：“我再想想。”甲追问：“何时回来？”" + "沉默中等待。" * 110
    source = lead_in + "乙终于说：“现在出发。”"
    script = {"beats": [{"dialogue": [{"speaker": "乙", "text": "现在出发。"}]}]}
    audit = _source_scope_audit(source, script, "novel")
    assert audit["potential_overwide_start"] is True
    assert audit["preceding_quoted_spans"] == 3
    assert audit["first_spoken_source_offset"] >= 500
    assert _source_scope_audit(source, script, "reference_video")["applicable"] is False


def test_script_dialogue_ignores_layout_wrap_but_not_character_changes():
    script = _answers()[2]
    script["beats"][0]["dialogue"] = [{"speaker": "石猴", "text": "我進去，我進去。"}]
    script["screenplay_markdown"] = "**石猴**：我進去，我進去。\n石猴纵身跃入水帘。"
    validate_script(script, "C01", "石猴道：「我進去，\n我進去。」", "novel")
    script["screenplay_markdown"] = "**石猴**：我进去，我进去。\n石猴纵身跃入水帘。"
    with pytest.raises(CreativeContractError, match="对白未按顺序进入可读剧本"):
        validate_script(script, "C01", "石猴道：「我進去，\n我進去。」", "novel")


def test_screenplay_template_compiles_only_locked_dialogue():
    beat_plan = _answers()[2]
    beat_plan["beats"][0]["dialogue"] = [{"speaker": "石猴", "text": "我進去，我進去。"}]
    rendered = compile_screenplay_template(
        {"beat_scenes": [
            {"beat_id": "B01", "action_segments": ["石猴瞑目蹲身。", "他跃入水帘。"]},
            {"beat_id": "B02", "action_segments": ["群猴望向洞口。"]},
        ]},
        beat_plan,
    )
    assert "**石猴**：我進去，我進去。" in rendered
    assert "[[DIALOGUE" not in rendered
    with pytest.raises(CreativeContractError, match="动作段数"):
        compile_screenplay_template(
            {"beat_scenes": [
                {"beat_id": "B01", "action_segments": ["石猴瞑目蹲身。"]},
                {"beat_id": "B02", "action_segments": ["群猴望向洞口。"]},
            ]}, beat_plan
        )
    with pytest.raises(CreativeContractError, match="动作段含直接引语"):
        compile_screenplay_template(
            {"beat_scenes": [
                {"beat_id": "B01", "action_segments": ['石猴说"别怕"。', "他跃入水帘。"]},
                {"beat_id": "B02", "action_segments": ["群猴望向洞口。"]},
            ]}, beat_plan
        )
    with pytest.raises(CreativeContractError, match="节拍数量"):
        compile_screenplay_template(
            {"beat_scenes": [
                {"beat_id": "B01", "action_segments": ["石猴瞑目蹲身。", "他跃入水帘。"]},
                {"beat_id": "B02", "action_segments": ["群猴望向洞口。"]},
                {"beat_id": "CLOSE", "action_segments": ["群猴又说了收束台词。"]},
            ]}, beat_plan
        )


def test_beat_result_is_in_after_without_redundant_consequence():
    from src.content_factory.creative_workflow_contract import validate_beat_plan

    plan = _answers()[2]
    for beat in plan["beats"]:
        beat.pop("consequence")
    validate_beat_plan(plan, "C01", SOURCE, "novel")
    plan["beats"][0]["after"] = ""
    with pytest.raises(CreativeContractError, match="B01.after"):
        validate_beat_plan(plan, "C01", SOURCE, "novel")


def test_missing_beat_patch_fills_only_named_empty_cells():
    original = _answers()[2]
    original["beats"][0].pop("before")
    original["beats"][1]["dialogue"] = [{"speaker": "甲", "amount": "已有错误别名"}]
    paths = _missing_beat_fields(original)
    assert paths == [["beats", 0, "before"], ["beats", 1, "dialogue", 0, "text"]]
    corrected = _apply_missing_beat_patches(original, {"patches": [
        {"path": paths[0], "value": "甲先退半步。"},
        {"path": paths[1], "value": "我想解释。"},
    ]}, paths)
    assert corrected["beats"][0]["before"] == "甲先退半步。"
    assert corrected["beats"][1]["dialogue"][0]["text"] == "我想解释。"
    assert "before" not in original["beats"][0]
    with pytest.raises(CreativeContractError, match="路径"):
        _apply_missing_beat_patches(original, {"patches": [
            {"path": paths[1], "value": "我想解释。"},
            {"path": paths[0], "value": "甲先退半步。"},
        ]}, paths)


def test_missing_dialogue_container_is_repaired_as_locked_list():
    original = deepcopy(_answers()[2])
    original["beats"][0].pop("dialogue")
    paths = _missing_beat_fields(original)
    assert paths == [["beats", 0, "dialogue"]]
    corrected = _apply_missing_beat_patches(
        original,
        {"patches": [{"path": paths[0], "value": []}]},
        paths,
    )
    assert corrected["beats"][0]["dialogue"] == []
    with pytest.raises(CreativeContractError, match="完整台词列表"):
        _apply_missing_beat_patches(
            original,
            {"patches": [{"path": paths[0], "value": "无对白"}]},
            paths,
        )


def test_small_arithmetic_duration_mismatch_is_visible_and_not_clean(tmp_path):
    answers = _answers()
    answers[0]["candidates"][0]["duration_seconds"] = 90
    answers[2]["duration_seconds"] = 90
    answers[2]["beats"][0]["duration_seconds"] = 50
    answers[2]["beats"][1]["duration_seconds"] = 50
    answers[3]["shots"][0]["duration_seconds"] = 50
    answers[3]["shots"][1]["duration_seconds"] = 50
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(_bundle(tmp_path))
    script = json.loads((run_dir / "SCREENPLAY.json").read_text(encoding="utf-8"))
    assert script["duration_seconds"] == 100
    assert script["declared_duration_seconds"] == 90
    assert script["duration_reconciliation"] == "computed_from_beat_durations; first_draft_warning"

    evidence = tmp_path / "review.md"
    evidence.write_text("人物归属、关键动机和情绪高光均已核对原文。"
                        "额外检查各段时长，总时长原填九十秒而逐段相加为一百秒。" * 4,
                        encoding="utf-8")
    review = record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)
    assert review["first_draft_no_major"] is False


def test_independent_video_driver(tmp_path):
    video = tmp_path / "video.mp4"
    analysis = tmp_path / "analysis.md"
    video.write_bytes(b"mock-video")
    analysis.write_text("原视频 video.mp4。镜头中两人先争执，随后沉默，再和解。", encoding="utf-8")
    bundle = load_materials(source_driver="reference_video", title="原创", video_path=video, analysis_path=analysis)
    assert bundle.source_driver == "reference_video"
    assert "镜头中两人" in bundle.source_text
    with pytest.raises(ValueError):
        load_materials(source_driver="reference_video", title="错误", novel_path=tmp_path / "novel.txt")


def test_video_driver_runs_entire_role_route(tmp_path):
    video = tmp_path / "reference.mp4"
    analysis = tmp_path / "reference.md"
    video.write_bytes(b"video bytes")
    analysis.write_text("原视频 reference.mp4。观察到误会、沉默和和解。", encoding="utf-8")
    bundle = load_materials(source_driver="reference_video", title="原创片", video_path=video,
                            analysis_path=analysis)
    answers = _answers()
    answers[0]["candidates"][0]["start_quote"] = ""
    answers[0]["candidates"][0]["end_quote"] = ""
    clients = FakeClients(answers)
    state = CreativeWorkflow(tmp_path / "video_run", clients=clients).run(bundle)
    assert state["source_driver"] == "reference_video"
    assert [role for role, _ in clients.calls] == ["writer", "director", "writer", "director", "writer"]
    assert "原视频 reference.mp4" in clients.calls[0][1][1]["content"]
    assert state["video_pass_sequence"] == 0


def test_video_analysis_must_name_its_source(tmp_path):
    video = tmp_path / "first.mp4"
    analysis = tmp_path / "other.md"
    video.write_bytes(b"video bytes")
    analysis.write_text("只讨论了另一个无关片子。", encoding="utf-8")
    with pytest.raises(ValueError, match="未标明原视频"):
        load_materials(source_driver="reference_video", title="错配", video_path=video,
                       analysis_path=analysis)


def test_video_analysis_scope_records_excluded_suffix(tmp_path):
    video = tmp_path / "source.mp4"
    analysis = tmp_path / "analysis.md"
    video.write_bytes(b"video")
    analysis.write_text("原片 source.mp4。" + "画面因果。" * 30 + "\n## 其他试片\n另一个故事。",
                        encoding="utf-8")
    bundle = load_materials(source_driver="reference_video", title="范围", video_path=video,
                            analysis_path=analysis, analysis_end_heading="## 其他试片")
    assert "另一个故事" not in bundle.source_text
    assert bundle.manifest["scope"]["analysis_scope_end_heading"] == "## 其他试片"

def test_video_analysis_scope_accepts_null_heading(tmp_path):
    video = tmp_path / "source.mp4"
    analysis = tmp_path / "analysis.md"
    video.write_bytes(b"video")
    analysis.write_text("原片 source.mp4。" + "画面因果。" * 30, encoding="utf-8")
    bundle = load_materials(source_driver="reference_video", title="范围", video_path=video,
                            analysis_path=analysis, analysis_end_heading=None)
    assert bundle.manifest["scope"]["analysis_scope_end_heading"] is None


def test_tampered_parent_and_source_stop(tmp_path):
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "run"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    script_record = run_dir / "writer_script.json"
    record = json.loads(script_record.read_text(encoding="utf-8"))
    record["output"]["title"] = "篡改"
    script_record.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (run_dir / "state.json").write_text(
        (run_dir / "state.json").read_text(encoding="utf-8").replace(
            "media_handoff_pending_capability", "needs_attention"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="产物被改动"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)
    Path(bundle.manifest["files"]["story_source"]["path"]).write_text(SOURCE + "变化", encoding="utf-8")
    with pytest.raises(ValueError, match="版本已改变"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_known_wrong_character_attribution():
    source = "女生身材高挑，穿着经典的衬衫短裙学妹装。顾玉荣走到林夏面前。"
    analysis = _answers()[0]
    analysis["characters"] = [{"name": "洛雪微", "want": "解释", "source_quote":
                                "女生身材高挑，穿着经典的衬衫短裙学妹装"}]
    analysis["candidates"][0]["start_quote"] = "女生身材高挑"
    analysis["candidates"][0]["end_quote"] = "顾玉荣走到林夏面前"
    with pytest.raises(CreativeContractError, match="归属错误"):
        validate_analysis(analysis, source, "novel")


def test_video_analysis_lifts_only_unambiguous_misnested_candidate_fields():
    analysis = _answers()[0]
    original_reason = "同一问话后有更清楚的反应"
    for index in range(3):
        candidate = deepcopy(analysis["candidates"][0])
        candidate["id"] = f"C{index + 1:02}"
        candidate["start_quote"] = ""
        candidate["end_quote"] = ""
        if index:
            candidate["end_quote"] = {
                "duration_seconds": candidate.pop("duration_seconds"),
                "selection_reason": original_reason,
            }
            candidate.pop("selection_reason")
        analysis["candidates"][index:index + 1] = [candidate]
    validate_analysis(analysis, "参考片分析仅提供表达方法", "reference_video")
    assert [item["id"] for item in analysis["candidates"]] == ["C01", "C02", "C03"]
    assert [item["selection_reason"] for item in analysis["candidates"][1:]] == [
        original_reason, original_reason,
    ]
    assert len(analysis["format_reconciliations"]) == 3
    assert sum(row["repair"] == "lift_duration_and_reason_from_empty_video_end_quote"
               for row in analysis["format_reconciliations"]) == 2
    assert analysis["characters"][0]["source_quote"] == ""

    malformed = _answers()[0]
    malformed["candidates"][0]["start_quote"] = ""
    malformed["candidates"][0]["end_quote"] = {"duration_seconds": 20, "unknown": "剧情"}
    with pytest.raises(CreativeContractError):
        validate_analysis(malformed, "参考片分析仅提供表达方法", "reference_video")


def test_video_original_invented_source_quotes_are_cleared_and_disclosed():
    analysis = deepcopy(_answers()[0])
    analysis["candidates"][0]["start_quote"] = "原创故事开场台词"
    analysis["candidates"][0]["end_quote"] = "原创故事收束动作"
    validate_analysis(analysis, "参考片只有镜头表达方法", "reference_video")
    candidate = analysis["candidates"][0]
    assert candidate["start_quote"] == candidate["end_quote"] == ""
    assert analysis["characters"][0]["source_quote"] == ""
    assert {row["repair"] for row in analysis["format_reconciliations"]} == {
        "clear_invented_original_video_source_quotes",
        "clear_invented_original_video_character_source_quote",
    }


def test_video_analysis_lifts_only_exact_nested_character_want():
    analysis = deepcopy(_answers()[0])
    analysis["candidates"][0]["start_quote"] = ""
    analysis["candidates"][0]["end_quote"] = ""
    analysis["characters"] = [{
        "name": "父亲",
        "want": {"goal": "让女儿带着热饭离开", "fear": "女儿误以为自己在挽留",
                 "source_quote": "父亲把面装进保温盒"},
    }]
    validate_analysis(analysis, "参考片只提供表达节奏", "reference_video")
    character = analysis["characters"][0]
    assert character == {
        "name": "父亲", "want": "让女儿带着热饭离开",
        "fear": "女儿误以为自己在挽留", "source_quote": "",
    }
    assert [row["repair"] for row in analysis["format_reconciliations"]] == [
        "lift_video_character_goal_fear_and_quote_from_nested_want",
        "clear_invented_original_video_character_source_quote",
    ]

    ambiguous = deepcopy(_answers()[0])
    ambiguous["characters"] = [{
        "name": "父亲", "want": {"goal": "送饭", "fear": "被误解", "source_quote": ""},
        "fear": "另一个担忧",
    }]
    with pytest.raises(CreativeContractError, match="character.want"):
        validate_analysis(ambiguous, "参考片只提供表达节奏", "reference_video")


def test_video_analysis_lifts_only_single_unambiguous_candidate_from_top_level():
    analysis = deepcopy(_answers()[0])
    candidate = analysis["candidates"][0]
    candidate["start_quote"] = candidate["end_quote"] = ""
    moved = {
        key: candidate.pop(key) for key in (
            "setup", "conflict", "turn", "peak", "aftermath",
            "start_quote", "end_quote", "duration_seconds",
        )
    }
    analysis.update(moved)
    candidate.pop("selection_reason")
    original_reason = analysis["selection_reason"]
    validate_analysis(analysis, "参考片只提供表达节奏", "reference_video")
    assert all(analysis["candidates"][0][key] == item for key, item in moved.items())
    assert analysis["candidates"][0]["selection_reason"] == original_reason
    assert all(key not in analysis for key in moved)
    assert analysis["format_reconciliations"][0]["repair"] == (
        "lift_single_video_candidate_fields_from_top_level"
    )

    ambiguous = deepcopy(analysis)
    ambiguous["candidates"].append(deepcopy(ambiguous["candidates"][0]))
    ambiguous["candidates"][0] = {"id": "C01", "title": "甲"}
    ambiguous["candidates"][1] = {"id": "C02", "title": "乙"}
    ambiguous.update(moved)
    with pytest.raises(CreativeContractError):
        validate_analysis(ambiguous, "参考片只提供表达节奏", "reference_video")


def test_local_quote_repair_preserves_text_and_rejects_structural_damage():
    raw = '{"story_preserved":true,"issues":[],"calibration_focus":["保持"藏伞→松手"四拍反应"]}'
    value = _escape_embedded_json_quotes(raw)
    assert value == {"story_preserved": True, "issues": [],
                     "calibration_focus": ["保持\"藏伞→松手\"四拍反应"]}
    assert _escape_embedded_json_quotes('{"a":"甲","b" "乙"}') is None


def test_unselected_bad_quote_is_retained_as_rejected_evidence():
    analysis = _answers()[0]
    analysis["candidates"].append(dict(analysis["candidates"][0], id="C03"))
    bad = dict(analysis["candidates"][0], id="C02", end_quote="根本不存在的结局句。")
    analysis["candidates"].append(bad)
    selected = validate_analysis(analysis, SOURCE, "novel")
    assert selected["id"] == "C01"
    assert [row["id"] for row in analysis["candidates"]] == ["C01", "C03"]
    assert analysis["rejected_candidates"][0]["id"] == "C02"
    assert "必须唯一定位" in analysis["rejected_candidates"][0]["reason"]


def test_selected_bad_quote_still_blocks_analysis():
    analysis = _answers()[0]
    analysis["candidates"][0]["end_quote"] = "根本不存在的结局句。"
    before = json.dumps(analysis, ensure_ascii=False, sort_keys=True)
    with pytest.raises(CreativeContractError, match="必须唯一定位"):
        validate_analysis(analysis, SOURCE, "novel")
    assert json.dumps(analysis, ensure_ascii=False, sort_keys=True) == before


def test_model_issues_cannot_self_approve(tmp_path):
    answers = _answers()
    answers[-1] = {"story_preserved": False, "issues": [{"owner": "director", "location": "SH01",
        "evidence": "改变了人物关系", "impact": "主线失真", "proposal": "修分镜", "severity": "major"}],
        "calibration_focus": []}
    state = CreativeWorkflow(tmp_path / "run", clients=FakeClients(answers), max_revisions=0).run(_bundle(tmp_path))
    assert state["status"] == "needs_revision"
    assert not (tmp_path / "run" / "MEDIA_HANDOFF.json").exists()
    unresolved = json.loads((tmp_path / "run" / "UNRESOLVED_DRAFT.json").read_text(encoding="utf-8"))
    assert unresolved["status"] == "needs_revision"
    assert unresolved["issues"][0]["location"] == "SH01"
    assert unresolved["automatic_media_submit"] is False
    assert "未通过的剧本工作稿" in (tmp_path / "run" / "UNRESOLVED_DRAFT.md").read_text(encoding="utf-8")


def test_writer_revision_envelope_keeps_script_and_audits_discarded_metadata(tmp_path):
    answers = _answers()
    issue_check = {"story_preserved": False, "issues": [{
        "owner": "writer", "location": "B02", "evidence": "最后反应缺少可见决定",
        "impact": "收束不成立", "proposal": "在节拍中补出双方行动", "severity": "major",
    }], "calibration_focus": []}
    revised = deepcopy(answers[2])
    revised["beats"][1]["after"] = "两人主动握手并和解"
    revised["screenplay_markdown"] = "甲和乙相遇，因误会争执。解释后两人主动握手并和解。"
    envelope = {"writer_script": {**revised, "source_evidence": ["只供修复参考"],
                                  "change_log": ["B02 补动作"], "shot_list": []},
                "unresolved": [], "issues_resolved": ["B02"],
                "source_scope": {"kept": ["F01"], "modified": [], "conflicts": []},
                "creative_notes": "保持原结局"}
    clients = FakeClients([answers[0], answers[1], answers[2], answers[3],
                           issue_check, envelope, answers[3], answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    record = json.loads((run_dir / "writer_revise__01.json").read_text(encoding="utf-8"))
    assert record["request"]["tool_schema_sha256"] is not None
    assert record["output"]["beats"][1]["after"] == "两人主动握手并和解"
    assert "source_evidence" not in record["output"]
    receipt = json.loads((run_dir / "writer_revise__01__local_envelope_reconciliation.json")
                         .read_text(encoding="utf-8"))
    assert receipt["envelope_key"] == "writer_script"
    assert receipt["excluded_inner_keys"] == ["change_log", "shot_list", "source_evidence"]
    assert "writer_revise__01" in state["local_format_reconciliations"]


def test_writer_revision_envelope_cannot_hide_unresolved_issues(tmp_path):
    workflow = CreativeWorkflow(tmp_path / "run", clients=FakeClients([]))
    with pytest.raises(CreativeContractError, match="仍有未解决问题"):
        workflow._unwrap_writer_revise_envelope(
            "writer_revise__01", {"writer_script": _answers()[2],
                                  "unresolved": ["最后反应缺失"]},
        )
    with pytest.raises(CreativeContractError, match="改动来源边界"):
        workflow._unwrap_writer_revise_envelope(
            "writer_revise__02", {"writer_script": _answers()[2],
                                  "source_scope": {"modified": ["F01"], "conflicts": []}},
        )


def test_writer_revision_single_extra_closer_is_reconciled_without_model_call(tmp_path):
    answers = _answers()
    issue_check = {"story_preserved": False, "issues": [{
        "owner": "writer", "location": "B02", "evidence": "最后动作不清",
        "impact": "收束不成立", "proposal": "写出可见决定", "severity": "major",
    }], "calibration_focus": []}
    envelope = {"writer_script": answers[2], "unresolved": []}

    class ExtraBraceClients(FakeClients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            if len(self.calls) == 6:
                return RoleResult(result.text + "}", result.metadata)
            return result

    clients = ExtraBraceClients([answers[0], answers[1], answers[2], answers[3],
                                 issue_check, envelope, answers[3], answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 8
    assert state["format_repairs_used"] == 0
    receipt = json.loads((run_dir / "writer_revise__01__local_format_repair.json")
                         .read_text(encoding="utf-8"))
    assert receipt["repair"] == "discard_one_superfluous_final_closing_brace"


def test_malformed_json_is_repaired_without_repeating_source_call(tmp_path):
    bundle = _bundle(tmp_path)
    answers = _answers()
    class FormatClients(FakeClients):
        def call(self, role, messages, **kwargs):
            if not self.calls:
                self.calls.append((role, messages))
                raw = json.dumps(_answers()[0], ensure_ascii=False)
                return RoleResult(raw[:-1] + ",}",
                                  {"role": role, "finish_reason": "tool_calls", "output_mode": "tool_call"})
            return super().call(role, messages, **kwargs)
    clients = FormatClients(answers)
    state = CreativeWorkflow(tmp_path / "run", clients=clients).run(bundle)
    assert state["calls_started"] == 6
    assert state["format_repairs_used"] == 1
    assert state["contract_repairs_used"] == 0
    assert state["revision_rounds"] == 0
    assert len(clients.calls) == 6
    assert (tmp_path / "run" / "writer_analysis__format_repair.json").exists()


def test_v2_format_and_contract_repairs_share_one_cap(tmp_path):
    answers = _answers()
    answers[2]["selected_candidate_id"] = "C02"

    class MalformedAnalysisClients(FakeClients):
        def call(self, role, messages, **kwargs):
            if not self.calls:
                self.calls.append((role, messages))
                raw = json.dumps(_answers()[0], ensure_ascii=False)
                return RoleResult(raw[:-1] + ",}", {"role": role, "finish_reason": "tool_calls", "output_mode": "tool_call"})
            return super().call(role, messages, **kwargs)

    run_dir = tmp_path / "run"
    with pytest.raises(CreativeContractError, match="共享格式与契约修复预算已满"):
        CreativeWorkflow(
            run_dir, clients=MalformedAnalysisClients(answers), max_contract_repairs=1,
        ).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["format_repairs_used"] == 1
    assert state["contract_repairs_used"] == 0
    assert state["revision_rounds"] == 0
    assert state["calls_started"] == 4


def test_format_repair_unknown_transport_stops_even_with_retry_flag(tmp_path):
    class FlakyFormatClients(FakeClients):
        def call(self, role, messages, **kwargs):
            if len(self.calls) == 0:
                self.calls.append((role, messages))
                raw = json.dumps(_answers()[0], ensure_ascii=False)
                return RoleResult(raw[:-1] + ",}", {"role": role, "finish_reason": "tool_calls", "output_mode": "tool_call"})
            if len(self.calls) == 1:
                self.calls.append((role, messages))
                raise RuntimeError("writer API 调用失败: APIConnectionError; status=unknown; request_id=unknown")
            return super().call(role, messages, **kwargs)

    clients = FlakyFormatClients(_answers())
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(RuntimeError, match="APIConnectionError"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    with pytest.raises(CreativeContractError, match="OUTCOME_UNKNOWN"):
        CreativeWorkflow(run_dir, clients=clients, retry_unconfirmed_transport=True).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 2 and len(clients.calls) == 2
    repair = json.loads((run_dir / "writer_analysis__format_repair.json").read_text(encoding="utf-8"))
    assert repair["failure"]["code"] == "OUTCOME_UNKNOWN"
    assert "prior_attempts" not in repair


def test_empty_contract_repair_stops_without_second_dispatch(tmp_path):
    class EmptyRepairClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.empty_once = False

        def call(self, role, messages, **kwargs):
            if len(self.calls) == 3 and not self.empty_once:
                self.empty_once = True
                self.calls.append((role, messages))
                raise RuntimeError("writer API 返回空正文")
            return super().call(role, messages, **kwargs)

    answers = _answers()
    invalid = deepcopy(answers[2])
    invalid["selected_candidate_id"] = "C02"
    clients = EmptyRepairClients([answers[0], answers[1], invalid,
                                  answers[2], answers[3], answers[4]])
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(RuntimeError, match="返回空正文"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    with pytest.raises(CreativeContractError, match="EMPTY_RESPONSE"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["contract_repairs_used"] == 1 and state["calls_started"] == 4
    assert len(clients.calls) == 4
    receipt = json.loads((run_dir / "writer_script__contract_repair.json").read_text(encoding="utf-8"))
    assert receipt["failure"]["code"] == "EMPTY_RESPONSE"
    assert "prior_attempts" not in receipt


def test_empty_main_stage_stops_without_second_dispatch(tmp_path):
    class EmptyStageClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.empty_once = False

        def call(self, role, messages, **kwargs):
            if len(self.calls) == 3 and not self.empty_once:
                self.empty_once = True
                self.calls.append((role, messages))
                raise RuntimeError("director API 返回空正文")
            return super().call(role, messages, **kwargs)

    clients = EmptyStageClients(_answers())
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(RuntimeError, match="返回空正文"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    with pytest.raises(CreativeContractError, match="EMPTY_RESPONSE"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 4 and len(clients.calls) == 4
    assert not (run_dir / "director_shots__empty_attempt_01.json").exists()


def test_format_repair_cannot_rewrite_content():
    original = '{"title":"原文","dialogue":"我進去。",}'
    repaired = '{"title":"原文","dialogue":"我進去。"}'
    assert _parse_format_repair(original, repaired)["dialogue"] == "我進去。"
    preface = "Here is my analysis.\n" + original[:-1]
    assert _parse_format_repair(preface, repaired)["dialogue"] == "我進去。"
    with pytest.raises(CreativeContractError, match="改动了正文"):
        _parse_format_repair(preface, '{"title":"原文","dialogue":"我不進去。"}')
    assert _parse_format_repair("```json\n" + original + "\n```", repaired)["title"] == "原文"
    with pytest.raises(CreativeContractError, match="改动了正文"):
        _parse_format_repair(original, '{"title":"原文","dialogue":"我不進去。"}')


def test_format_repair_can_recover_exact_embedded_original_from_repair_envelope():
    source = ('{"error":"only replace_beats","original":'
              '{"replace_beats":[{"beat_id":"B01","beat":{"id":"B01"}}]'
              ',"source_sha256":"abc","source_evidence":[]}')
    repaired = '{"replace_beats":[{"beat_id":"B01","beat":{"id":"B01"}}]}'
    assert _parse_format_repair(source, repaired) == {
        "replace_beats": [{"beat_id": "B01", "beat": {"id": "B01"}}]
    }
    with pytest.raises(CreativeContractError):
        _parse_format_repair(
            source,
            '{"replace_beats":[{"beat_id":"B01","beat":{"id":"B02"}}]}',
        )


def test_director_duration_scale_preserves_content_and_locks_beat_total():
    output = {"shots": [
        {"id": "SH03", "beat_id": "B02", "duration_seconds": 10, "prompt": "a"},
        {"id": "SH04", "beat_id": "B02", "duration_seconds": 10, "prompt": "b"},
    ]}
    script = {"beats": [{"id": "B02", "duration_seconds": 32}]}
    corrected, changes = _project_director_beat_duration_scale(
        output, script, "SH03 对白约 52 个计时单位无法在 10 秒内自然说完",
    )
    assert [row["duration_seconds"] for row in corrected["shots"]] == [16, 16]
    assert [row["prompt"] for row in corrected["shots"]] == ["a", "b"]
    assert [row["duration_seconds"] for row in output["shots"]] == [10, 10]
    assert len(changes) == 2


def test_format_repair_can_escape_only_quotes_left_unescaped_by_repair_model():
    source = '{"title":"原文","dialogue":"他说：\"我進去。\""}'
    repaired = '{"title":"原文","dialogue":"他说："我進去。""}'
    assert _parse_format_repair(source, repaired) == {
        "title": "原文", "dialogue": '他说："我進去。"',
    }


def test_unknown_no_id_connection_failure_stops_without_repeat(tmp_path):
    class FlakyClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.attempts = 0

        def call(self, role, messages, **kwargs):
            self.attempts += 1
            if self.attempts == 3:
                raise RuntimeError("writer API 调用失败: APIConnectionError; status=unknown; request_id=unknown")
            return super().call(role, messages, **kwargs)

    clients = FlakyClients(_answers())
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(RuntimeError, match="APIConnectionError"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    with pytest.raises(CreativeContractError, match="OUTCOME_UNKNOWN"):
        CreativeWorkflow(run_dir, clients=clients, retry_unconfirmed_transport=True).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 3 and clients.attempts == 3
    assert not (run_dir / "writer_script__transport_attempt_01.json").exists()


def test_unknown_no_id_529_failure_stops_without_repeat(tmp_path):
    class FlakyClients(FakeClients):
        def __init__(self, answers):
            super().__init__(answers)
            self.attempts = 0

        def call(self, role, messages, **kwargs):
            self.attempts += 1
            if self.attempts == 3:
                raise RuntimeError(
                    "writer API 调用失败: InternalServerError; "
                    "status=529; request_id=unknown"
                )
            return super().call(role, messages, **kwargs)

    clients = FlakyClients(_answers())
    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(RuntimeError, match="status=529"):
        CreativeWorkflow(run_dir, clients=clients).run(bundle)
    with pytest.raises(CreativeContractError, match="OUTCOME_UNKNOWN"):
        CreativeWorkflow(run_dir, clients=clients, retry_unconfirmed_transport=True).run(bundle)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 3 and clients.attempts == 3
    assert not (run_dir / "writer_script__transport_attempt_01.json").exists()


def test_sequential_contract_repairs_recheck_and_share_two_round_limit(tmp_path):
    answers = _answers()
    initial = deepcopy(answers[2])
    initial["duration_seconds"] = 30
    initial["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句。"}]
    initial["selected_candidate_id"] = "C02"
    first_repair = deepcopy(initial)
    first_repair["selected_candidate_id"] = "C01"
    second_repair = deepcopy(first_repair)
    second_repair["duration_seconds"] = 20
    second_repair["screenplay_markdown"] = "**甲**：起因句。\n甲和乙因误会争执，随后和解。"
    answers[3]["shots"][0]["dialogue_lock"] = [{"speaker": "甲", "text": "起因句。"}]
    clients = FakeClients([
        answers[0], answers[1], initial, first_repair, second_repair, answers[3], answers[4]
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(
        run_dir, clients=clients, max_revisions=2, budget_policy_version="v1_20260922",
    ).run(_quoted_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["calls_started"] == 7
    assert state["revision_rounds"] == 2
    assert len(list(run_dir.glob("writer_script__contract_repair*.json"))) == 2


def test_contract_repair_cycle_stops_with_explicit_error(tmp_path):
    answers = _answers()
    first = deepcopy(answers[2])
    first["selected_candidate_id"] = "C02"
    second = deepcopy(answers[2])
    second["title"] = ""
    clients = FakeClients([answers[0], answers[1], first, second, first])
    run_dir = tmp_path / "run"
    with pytest.raises(CreativeContractError, match="无效版本之间循环"):
        CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_attention"
    assert state["calls_started"] == 5


def test_v2_contract_repairs_do_not_consume_content_revision_round(tmp_path):
    answers = _answers()
    initial = deepcopy(answers[2])
    initial["selected_candidate_id"] = "C02"
    initial["duration_seconds"] = 30
    first_repair = deepcopy(initial)
    first_repair["selected_candidate_id"] = "C01"
    second_repair = deepcopy(first_repair)
    second_repair["duration_seconds"] = 20
    issue_check = {"story_preserved": False, "issues": [{
        "owner": "director", "location": "SH01", "evidence": "镜头没有给反应时间",
        "impact": "情绪重心不可见", "proposal": "延长反应镜头", "severity": "major",
    }], "calibration_focus": []}
    clients = FakeClients([
        answers[0], answers[1], initial, first_repair, second_repair,
        answers[3], issue_check, answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(
        run_dir, clients=clients, max_contract_repairs=2,
        budget_policy_version="v2_20260922",
    ).run(_bundle(tmp_path))
    assert state["budget_policy_version"] == "v2_20260922"
    assert state["contract_repairs_used"] == 2
    assert state["revision_rounds"] == 1
    assert state["calls_started"] == 9
    assert state["status"] == "media_handoff_pending_capability"


def test_contract_repair_is_reported_but_does_not_replace_content_review(tmp_path):
    answers = _answers()
    invalid = deepcopy(answers[2])
    invalid["selected_candidate_id"] = "C02"
    clients = FakeClients([answers[0], answers[1], invalid, answers[2], answers[3], answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(
        run_dir, clients=clients, max_contract_repairs=2,
        budget_policy_version="v2_20260922",
    ).run(_bundle(tmp_path))
    assert state["contract_repairs_used"] == 1
    assert state["revision_rounds"] == 0
    evidence = tmp_path / "evidence.md"
    evidence.write_text("人物归属、行为动机和情绪高光均已逐拍阅读，未发现阻断问题。" * 5, encoding="utf-8")
    review = record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)
    assert review["first_draft_no_major"] is True
    assert review["operationally_clean"] is False
    assert review["technical_repairs_before_complete_draft"] == {
        "contract_repairs": 1,
        "format_repairs": 0,
        "analysis_format_reconciliations": 0,
        "local_format_reconciliations": [],
    }


def test_v3_allows_three_technical_repairs_without_spending_content_round(tmp_path):
    answers = _answers()
    initial = deepcopy(answers[2])
    initial["title"] = ""
    initial["selected_candidate_id"] = "C02"
    initial["duration_seconds"] = 30
    first = deepcopy(initial)
    first["title"] = "误会"
    second = deepcopy(first)
    second["selected_candidate_id"] = "C01"
    third = deepcopy(second)
    third["duration_seconds"] = 20
    clients = FakeClients([answers[0], answers[1], initial, first, second, third,
                           answers[3], answers[4]])
    state = CreativeWorkflow(tmp_path / "run", clients=clients).run(_bundle(tmp_path))
    assert state["budget_policy_version"] == "v4_20260923"
    assert state["contract_repairs_used"] == 3
    assert state["revision_rounds"] == 0
    assert state["calls_started"] == 8
    assert state["status"] == "media_handoff_pending_capability"


def test_writer_analysis_missing_field_patch_preserves_existing_source_and_story(tmp_path):
    answers = _answers()
    incomplete = deepcopy(answers[0])
    incomplete["candidates"][0].pop("setup")
    patch = {"patches": [{"path": ["candidates", 0, "setup"],
                          "value": "两人先相遇，再因误会争执"}]}
    clients = FakeClients([incomplete, patch, *answers[1:]])
    run_dir = tmp_path / "patched_analysis"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["contract_repairs_used"] == 1
    repaired = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))["output"]
    assert repaired["candidates"][0]["setup"] == "两人先相遇，再因误会争执"
    assert repaired["candidates"][0]["start_quote"] == incomplete["candidates"][0]["start_quote"]
    assert _missing_analysis_fields(repaired) == []
    with pytest.raises(CreativeContractError, match="路径与缺失字段不一致"):
        _apply_missing_analysis_patches(incomplete, {
            "patches": [{"path": ["candidates", 0, "start_quote"], "value": "伪原文"}],
        }, [["candidates", 0, "setup"]])


def test_writer_analysis_candidate_quote_patch_is_compact_and_source_bound(tmp_path):
    answers = _answers()
    invalid = deepcopy(answers[0])
    invalid["candidates"][0]["start_quote"] = "不存在的开场近义句"
    invalid["candidates"][0]["end_quote"] = "不存在的结尾近义句"
    required = _invalid_candidate_quote_paths(invalid, SOURCE)
    assert required == [
        ["candidates", 0, "start_quote"], ["candidates", 0, "end_quote"],
    ]
    start_patch = {"patches": [{"path": required[0], "value": "起因句。"}]}
    end_patch = {"patches": [{"path": required[1], "value": "结局句。"}]}
    clients = FakeClients([invalid, start_patch, end_patch, *answers[1:]])
    run_dir = tmp_path / "quote_patch"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["contract_repairs_used"] == 2
    repaired = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))["output"]
    assert repaired["candidates"][0]["start_quote"] == "起因句。"
    assert repaired["candidates"][0]["end_quote"] == "结局句。"
    assert repaired["candidates"][0]["setup"] == invalid["candidates"][0]["setup"]
    receipt = json.loads(
        (run_dir / "writer_analysis__contract_repair.json").read_text(encoding="utf-8")
    )
    payload = json.loads(receipt["request"][1]["content"])
    assert "original" not in payload
    assert payload["invalid_candidate_quotes"][0]["path"] == required[0]
    assert len(payload["invalid_candidate_quotes"]) == 1
    later_receipts = list(run_dir.glob("writer_analysis__contract_repair_*.json"))
    assert len(later_receipts) == 1
    later_payload = json.loads(
        json.loads(later_receipts[0].read_text(encoding="utf-8"))["request"][1]["content"]
    )
    assert [row["path"] for row in later_payload["invalid_candidate_quotes"]] == [required[1]]
    assert "只修复 invalid_candidate_quotes" in receipt["request"][0]["content"]
    with pytest.raises(CreativeContractError, match="必须唯一定位"):
        _apply_candidate_quote_patches(invalid, {
            "patches": [
                {"path": required[0], "value": "仍然不存在"},
                {"path": required[1], "value": "结局句。"},
            ],
        }, required, SOURCE)


def test_analysis_patch_rejects_unsolicited_quote_change_but_keeps_requested_fix(tmp_path):
    answers = _answers()
    incomplete = deepcopy(answers[0])
    incomplete["characters"][0].pop("want")
    patch = {"patches": [
        {"path": ["characters", 0, "want"], "value": "解释误会"},
        {"path": ["characters", 0, "source_quote"], "value": "不存在的伪引文"},
    ]}
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=FakeClients([incomplete, patch, *answers[1:]]))
    state = state.run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["contract_repairs_used"] == 1
    result = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))["output"]
    assert result["characters"][0]["want"] == "解释误会"
    assert result["characters"][0]["source_quote"] == "起因句。"
    receipt = json.loads((run_dir / "writer_analysis__contract_repair__local_patch_projection.json")
                         .read_text(encoding="utf-8"))
    assert receipt["ignored_paths"] == [["characters", 0, "source_quote"]]
    assert _project_unrequested_analysis_quote_patches({"patches": [
        patch["patches"][0],
        {"path": ["candidates", 0, "start_quote"], "value": "伪引文"},
    ]}, [["characters", 0, "want"]]) is None


def test_writer_analysis_repair_requests_only_contract_object(tmp_path):
    answers = _answers()
    invalid = deepcopy(answers[0])
    invalid["summary"] = invalid.pop("characters")
    clients = FakeClients([invalid, *answers])
    state = CreativeWorkflow(tmp_path / "run", clients=clients).run(_bundle(tmp_path))
    instruction = clients.calls[1][1][0]["content"]
    assert "顶层必须且只能有 summary、characters" in instruction
    assert "candidates 每项必须且只能有 id、title、setup、conflict、turn" in instruction
    assert "候选 id 使用 C01" in instruction
    assert "不要回显输入的 error、original" in instruction
    assert state["contract_repairs_used"] == 1
    assert state["status"] == "media_handoff_pending_capability"


def test_contract_repair_response_gets_format_only_repair(tmp_path):
    valid = _answers()[0]
    invalid = deepcopy(valid)
    invalid["candidates"] = "供应商折叠了字段"
    valid_text = json.dumps(valid, ensure_ascii=False)

    class RawClients:
        def __init__(self):
            self.answers = iter([valid_text[:-1], valid_text])

        def call(self, role, messages, **kwargs):
            return RoleResult(next(self.answers), {"role": role, "total_tokens": 1})

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    workflow = CreativeWorkflow(run_dir, clients=RawClients())
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v3_20260922", "contract_repairs_used": 0,
        "format_repairs_used": 0, "revision_rounds": 0,
    }
    corrected = workflow._validate_or_repair(
        "writer_analysis", "writer",
        {"materials": {"story_source": SOURCE, "creative_focus": "起因句到结局句"}},
        invalid,
        lambda value: validate_analysis(value, SOURCE, "novel"),
    )
    assert corrected == valid
    assert workflow.state["calls_started"] == 2
    assert workflow.state["contract_repairs_used"] == 1
    assert workflow.state["format_repairs_used"] == 1
    assert (run_dir / "writer_analysis__contract_repair__response__format_repair.json").exists()


def test_missing_analysis_character_list_reports_type_error():
    invalid = deepcopy(_answers()[0])
    invalid.pop("characters")
    with pytest.raises(CreativeContractError, match="characters 必须为列表"):
        validate_analysis(invalid, SOURCE, "novel")


def test_invalid_character_quote_repair_carries_indexed_source_evidence():
    source = "甲因大雨仍守在门口，乙在室内迟疑。过了很久，乙开门向甲道歉。"
    quote = "甲因大雨仍守在门口……乙开门向甲道歉。"
    evidence = _repair_evidence(
        {"story_source": source},
        {"characters": [{"name": "甲", "source_quote": quote}], "candidates": []},
        "characters[0].source_quote 在来源中必须唯一定位",
    )
    assert evidence["invalid_character_quotes"] == [{
        "path": ["characters", 0, "source_quote"],
        "name": "甲", "invalid_quote": quote,
    }]
    assert source in evidence["source_evidence"][0]["text"]
    invalid = deepcopy(_answers()[0])
    invalid["characters"][0]["source_quote"] = quote
    with pytest.raises(CreativeContractError, match=r"characters\[0\]\.source_quote"):
        validate_analysis(invalid, SOURCE, "novel")


def test_short_character_quote_may_be_unique_inside_selected_candidate():
    source = "我给你一万！多少？两万！隔开另一场。多少？！"
    analysis = deepcopy(_answers()[0])
    analysis["characters"] = [{
        "name": "乙", "want": "确认报价", "fear": "原文未证实",
        "source_quote": "多少？",
    }]
    analysis["candidates"][0]["start_quote"] = "我给你一万！"
    analysis["candidates"][0]["end_quote"] = "两万！"

    validate_analysis(analysis, source, "novel")
    assert analysis["characters"][0]["source_quote"] == "多少？"


def test_invalid_character_quote_uses_compact_bound_patch(tmp_path):
    answers = _answers()
    invalid = deepcopy(answers[0])
    invalid["characters"][0]["source_quote"] = "起困句。"
    patch = {"patches": [{
        "path": ["characters", 0, "source_quote"], "value": "起因句。",
    }]}
    clients = FakeClients([invalid, patch, *answers[1:]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    repair = json.loads(
        (run_dir / "writer_analysis__contract_repair.json").read_text(encoding="utf-8")
    )
    assert repair["repair_protocol"] == "writer_character_quote_patch/v2"
    assert set(json.loads(repair["request"][1]["content"])) == {
        "error", "draft_sha256", "invalid_character_quotes", "source_evidence",
    }
    with pytest.raises(CreativeContractError, match="逐项对应"):
        _apply_character_quote_patches(invalid, {"patches": []}, [
            ["characters", 0, "source_quote"],
        ], SOURCE)

    traditional_source = "猴王道：「你家既與神仙相鄰，何不從他修行？學得個不老之方，卻不是好？」"
    near = deepcopy(answers[0])
    near["characters"][0]["source_quote"] = (
        "我家既與神仙相鄰，何不從他修行？學得個不老之方，卻不是好？"
    )
    recovered = _apply_character_quote_patches(near, {"patches": [{
        "path": ["characters", 0, "source_quote"],
        "value": "我家既与神仙相邻，何不从他修行？学得个不老之方，却不是好？",
    }]}, [["characters", 0, "source_quote"]], traditional_source)
    assert recovered["characters"][0]["source_quote"].startswith("你家既與神仙相鄰")


def test_structurally_incomplete_analysis_repair_gets_focused_chapter_evidence():
    source = (
        "第6章 前一件事\n无关内容。\n"
        "第7章 转账\n导师发来消息。\n她交代去买衣服后离开。\n手机显示十万元到账。\n"
        "第8章 后一件事\n后续内容。"
    )
    evidence = _repair_evidence(
        {"story_source": source,
         "creative_focus": "只选第7章导师消息到十万元转账"},
        {"summary": "供应商把其余字段折叠或截断了"},
        "candidates 必须为列表",
    )
    assert evidence["creative_focus"] == "只选第7章导师消息到十万元转账"
    assert len(evidence["source_evidence"]) == 1
    excerpt = evidence["source_evidence"][0]["text"]
    assert "导师发来消息" in excerpt and "十万元到账" in excerpt
    assert "第6章" not in excerpt and "第8章" not in excerpt


def test_unmatched_candidate_quote_repair_falls_back_to_focused_chapter():
    source = (
        "第6章 前文\n无关。\n"
        "第7章 转账\n导师发来消息。\n手机显示十万元到账。\n富婆，饿饿，饭饭。\n"
        "第8章 后文\n无关。"
    )
    evidence = _repair_evidence(
        {"materials": {"story_source": source,
                       "creative_focus": "只选第7章导师消息到十万元转账"}},
        {"characters": [], "candidates": [{
            "start_quote": "完全不存在的开场动作和人物描述",
            "end_quote": "人物拿手机走向另一处的虚构结尾",
        }]},
        "candidate.end_quote 在来源中必须唯一定位",
    )
    assert len(evidence["source_evidence"]) == 1
    assert "富婆，饿饿，饭饭" in evidence["source_evidence"][0]["text"]


def test_director_response_singleton_envelope_is_unwrapped_with_receipt(tmp_path):
    workflow = CreativeWorkflow(tmp_path / "run", clients=FakeClients([]))
    workflow.run_dir.mkdir()
    workflow.state = {"local_format_reconciliations": []}
    original = {"director_shots": deepcopy(_answers()[3])}
    corrected = workflow._unwrap_director_envelope("director_revise__01", original)
    assert corrected == original["director_shots"]
    assert workflow.state["local_format_reconciliations"] == ["director_revise__01"]
    assert (workflow.run_dir / "director_revise__01__local_envelope_reconciliation.json").exists()
    assert workflow._unwrap_director_envelope("director_revise__01", original) == corrected
    assert workflow._unwrap_director_envelope("writer_script", original) == original


def test_contract_repair_echoed_original_and_evidence_is_reported_as_noop(tmp_path):
    answers = _answers()
    invalid_script = deepcopy(answers[2])
    invalid_script["selected_candidate_id"] = "C02"
    echoed_request = {
        "error": "所选候选不匹配",
        "original": invalid_script,
        "source_sha256": "example",
        "source_evidence": [],
        "source_evidence_limit": "只可修复证据覆盖的字段",
    }
    clients = FakeClients([answers[0], answers[1], invalid_script, echoed_request])
    run_dir = tmp_path / "run"
    with pytest.raises(CreativeContractError, match="修复只回显原稿与证据"):
        CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_attention"
    assert state["calls_started"] == 4
    assert state["revision_rounds"] == 0
    assert state["contract_repairs_used"] == 1
    assert len(list(run_dir.glob("writer_script__contract_repair*.json"))) == 1


def test_contract_repair_lifts_changed_inner_draft_only_when_evidence_unchanged(tmp_path):
    class WrappedRepairClients(FakeClients):
        def call(self, role, messages, **kwargs):
            if len(self.calls) == 3:
                self.calls.append((role, messages))
                wrapper = json.loads(messages[1]["content"])
                wrapper["original"]["duration_seconds"] = 20
                return RoleResult(
                    json.dumps(wrapper, ensure_ascii=False),
                    {"role": role, "finish_reason": "stop", "total_tokens": 1},
                )
            return super().call(role, messages, **kwargs)

    answers = _answers()
    invalid = deepcopy(answers[2])
    invalid["duration_seconds"] = 30
    clients = WrappedRepairClients([answers[0], answers[1], invalid, answers[3], answers[4]])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(run_dir, clients=clients).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    assert state["contract_repairs_used"] == 1
    repair = json.loads((run_dir / "writer_script__contract_repair.json").read_text(encoding="utf-8"))
    assert repair["reconciliation"] == "lift_modified_original_from_unchanged_evidence_wrapper"


def test_beat_plan_rejects_dialogue_repeated_inside_action_field():
    from src.content_factory.creative_workflow_contract import validate_beat_plan

    beat_plan = _answers()[2]
    beat_plan["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句子。"}]
    beat_plan["beats"][0]["after"] = "甲转身时又喊出起因句子"
    with pytest.raises(CreativeContractError, match="复述已锁定对白"):
        validate_beat_plan(beat_plan, "C01", SOURCE, "novel")


def test_beat_plan_rejects_simplified_paraphrase_of_traditional_dialogue():
    from src.content_factory.creative_workflow_contract import validate_beat_plan

    source = "甲說：「大王若是這般遠慮，真所謂道心開發也。」随后众人抬头。"
    beat_plan = deepcopy(_answers()[2])
    beat_plan["beats"][0]["dialogue"] = [{
        "speaker": "甲", "text": "大王若是這般遠慮，真所謂道心開發也。",
    }]
    beat_plan["beats"][0]["during"] = (
        "甲站定后厉声高叫大王若是这般远虑真所谓道心开发也，众人随即抬头。"
    )
    with pytest.raises(CreativeContractError, match="改写复述已锁定对白"):
        validate_beat_plan(beat_plan, "C01", source, "novel")


def test_workflow_repairs_dialogue_restatement_with_bound_action_patch(tmp_path):
    answers = _answers()
    answers[0]["characters"][0]["source_quote"] = "起因句子。"
    answers[0]["candidates"][0]["start_quote"] = "起因句子。"
    invalid = deepcopy(answers[2])
    invalid["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句子。"}]
    invalid["beats"][0]["during"] = "甲转身时又说出起因句子"
    patch = {"patches": [{
        "path": ["beats", 0, "during"],
        "value": "甲转身看向乙，眉头松开；乙保持注视",
    }]}
    answers[3]["shots"][0]["dialogue_lock"] = [{"speaker": "甲", "text": "起因句子。"}]
    clients = FakeClients([
        answers[0], answers[1], invalid, patch, answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"
    novel = tmp_path / "action_patch_novel.txt"
    novel.write_text(QUOTED_SOURCE.replace("起因句。", "起因句子。"), encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="动作复述修复", novel_path=novel)
    state = CreativeWorkflow(run_dir, clients=clients).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    repair = json.loads(
        (run_dir / "writer_script__contract_repair.json").read_text(encoding="utf-8")
    )
    assert repair["repair_protocol"] == "writer_action_restatement_patch/v1"
    payload = json.loads(repair["request"][1]["content"])
    assert payload["invalid_action_restatements"][0]["path"] == ["beats", 0, "during"]
    assert "title" not in payload and "premise" not in payload
    screenplay = json.loads((run_dir / "SCREENPLAY.json").read_text(encoding="utf-8"))
    assert screenplay["beats"][0]["during"] == "甲转身看向乙，眉头松开；乙保持注视"

    with pytest.raises(CreativeContractError, match="路径与目标清单不一致"):
        _apply_writer_action_patches(invalid, {"patches": [{
            "path": ["beats", 1, "during"], "value": "乙后退半步",
        }]}, [["beats", 0, "during"]])


def test_novel_character_dialogue_must_be_inside_source_direct_speech():
    source = "甲說：「你來了。」隨後甲轉身離開。"
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "你來了。"}]
    script["beats"][1]["dialogue"] = [{"speaker": "甲", "text": "隨後甲轉身離開。"}]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="不是所选原文中的人物直接引语"):
        validate_script(script, "C01", source, "novel")
    assert _invalid_novel_dialogue_paths(script, source) == [
        ["beats", 1, "dialogue", 0, "text"],
    ]
    script["beats"][1]["dialogue"][0]["speaker"] = "旁白"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")


def test_novel_script_cannot_skip_later_direct_speech_and_keep_its_aftermath():
    source = (
        '“你为什么删我？”“只是清理好友。”'
        '“那为什么不接电话？”“我以为是骚扰电话。”“你！”她气得发抖。'
    )
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [
        {"speaker": "甲", "text": "你为什么删我？"},
    ]
    script["beats"][1]["dialogue"] = [
        {"speaker": "乙", "text": "只是清理好友。"},
    ]
    script["beats"][1]["after"] = "甲听完后身体发抖"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="仍有未进入剧本的直接对白"):
        validate_script(script, "C01", source, "novel")


def test_novel_script_may_end_before_unused_later_direct_speech():
    source = (
        '“你为什么删我？”“只是清理好友。”'
        '“那为什么不接电话？”“我以为是骚扰电话。”“你！”她气得发抖。'
    )
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [
        {"speaker": "甲", "text": "你为什么删我？"},
    ]
    script["beats"][1]["dialogue"] = [
        {"speaker": "乙", "text": "只是清理好友。"},
    ]
    script["beats"][1]["after"] = "乙说完后保持原位；甲收回视线，本片在此收束"
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    validate_script(script, "C01", source, "novel")


def test_script_cannot_count_exclamation_marks_as_spoken_characters():
    source = '“你！！！”'
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "你！！！"}]
    script["beats"][0]["during"] = "甲仅发出短促的两个字，气流断成三段"
    script["beats"][1]["dialogue"] = []
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="实际锁定对白去除标点后为 1 个字"):
        validate_script(script, "C01", source, "novel")


def test_script_cannot_miscount_stutter_with_count_before_speech_verb():
    source = '“没……没啊。”'
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "没……没啊。"}]
    script["beats"][0]["during"] = "甲才把那两个字连同卡顿一起挤出来"
    script["beats"][1]["dialogue"] = []
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    with pytest.raises(CreativeContractError, match="实际锁定对白去除标点后为 3 个字"):
        validate_script(script, "C01", source, "novel")


def test_bare_vocative_may_match_character_name_in_action_prose():
    source = '“Gilbert,” she said, “I appreciate it.”'
    script = deepcopy(_answers()[2])
    script["beats"][0]["before"] = "Anne 抬眼看向 Gilbert，右手仍向他伸着"
    script["beats"][0]["during"] = "Gilbert 站在原位听她继续"
    script["beats"][0]["after"] = "Anne 仍看着 Gilbert"
    script["beats"][0]["dialogue"] = [
        {"speaker": "Anne", "text": "Gilbert,"},
        {"speaker": "Anne", "text": "I appreciate it."},
    ]
    script["beats"][1]["dialogue"] = []
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    validate_script(script, "C01", source, "novel")


def test_script_duration_must_remain_near_selected_candidate_duration():
    script = deepcopy(_answers()[2])
    script["beats"][0]["duration_seconds"] = 45
    script["beats"][1]["duration_seconds"] = 45
    script["duration_seconds"] = 90
    candidate = deepcopy(_answers()[0]["candidates"][0])
    with pytest.raises(CreativeContractError, match="偏离候选 20 秒"):
        validate_candidate_duration(script, candidate)


def test_explicit_creative_focus_duration_range_is_a_hard_writer_boundary():
    script = deepcopy(_answers()[2])
    script["beats"][0]["duration_seconds"] = 53
    script["beats"][1]["duration_seconds"] = 52
    script["duration_seconds"] = 105
    focus = "总时长70到100秒，六到八个节拍。"
    assert creative_focus_duration_range(focus) == (70.0, 100.0)
    with pytest.raises(CreativeContractError, match="超出 creative_focus 明确时长范围 70-100 秒"):
        validate_creative_focus_duration(script, focus)


def test_creative_focus_duration_range_accepts_english_and_reversed_bounds():
    assert creative_focus_duration_range("duration: 80-95 seconds") == (80.0, 95.0)
    assert creative_focus_duration_range("总时长100至70秒") == (70.0, 100.0)


def test_explicit_creative_focus_beat_range_is_a_hard_writer_boundary():
    script = deepcopy(_answers()[2])
    focus = "总时长70到100秒，六到八个节拍。"
    assert creative_focus_beat_range(focus) == (6, 8)
    with pytest.raises(CreativeContractError, match="明确节拍范围 6-8 个"):
        validate_creative_focus_beat_count(script, focus)


def test_creative_focus_beat_range_accepts_english_and_reversed_bounds():
    assert creative_focus_beat_range("8 to 10 beats") == (8, 10)
    assert creative_focus_beat_range("十二至八个节拍") == (8, 12)


def test_invalid_complete_director_feedback_row_uses_bound_replacement():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    feedback = [{
        "issue": "candidate C01 的 timing 需要在节拍层落实",
        "scope": "candidate C01 timing",
        "proposal": "在节拍中保留反应时间",
    }]
    output = {
        "candidate_update": candidate,
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "director_only",
            "reason": "交给导演处理",
        }],
    }
    assert _invalid_director_feedback_response_indexes(output, feedback) == [0]
    patch = {"feedback_responses": [{
        "feedback_index": 0,
        "decision": "accepted_in_script",
        "reason": "在编剧节拍中保留刺激和反应时间",
    }]}
    corrected = _replace_director_feedback_responses(output, patch, [0])
    assert corrected["feedback_responses"][0]["decision"] == "accepted_in_script"
    assert output["feedback_responses"][0]["decision"] == "director_only"
    _validate_director_feedback_response(corrected, candidate, feedback)


def test_director_feedback_replacement_rejects_extra_keys():
    output = {
        "candidate_update": deepcopy(_answers()[0]["candidates"][0]),
        "feedback_responses": [{
            "feedback_index": 0, "decision": "director_only", "reason": "x",
        }],
    }
    patch = {"feedback_responses": [{
        "feedback_index": 0, "decision": "accepted_in_script", "reason": "x",
        "rationale_field": "selection_reason",
    }]}
    with pytest.raises(CreativeContractError, match="编号、决定或理由无效"):
        _replace_director_feedback_responses(output, patch, [0])


def test_feedback_patch_may_drop_only_echoed_boolean_request_metadata():
    patch = {"feedback_responses": [{
        "feedback_index": 3,
        "decision": "accepted_in_script",
        "reason": "在节拍中落实连续变形",
        "candidate_decision_required": True,
    }]}

    projected = _project_feedback_patch_echo_metadata(patch)

    assert projected is not None
    corrected, stripped = projected
    assert corrected == {"feedback_responses": [{
        "feedback_index": 3,
        "decision": "accepted_in_script",
        "reason": "在节拍中落实连续变形",
    }]}
    assert stripped == ["feedback_responses[0].candidate_decision_required"]
    assert "candidate_decision_required" in patch["feedback_responses"][0]


def test_feedback_patch_keeps_rejecting_unknown_extra_metadata():
    patch = {"feedback_responses": [{
        "feedback_index": 0,
        "decision": "accepted_in_script",
        "reason": "处理",
        "rationale_field": "candidate.turn",
    }]}

    assert _project_feedback_patch_echo_metadata(patch) is None


def test_feedback_patch_may_drop_empty_rationale_field():
    patch = {"feedback_responses": [{
        "feedback_index": 4,
        "decision": "accepted_in_script",
        "reason": "节拍中保持无对白",
        "rationale_field": "",
    }]}

    projected = _project_feedback_patch_echo_metadata(patch)

    assert projected is not None
    corrected, stripped = projected
    assert corrected["feedback_responses"][0] == {
        "feedback_index": 4,
        "decision": "accepted_in_script",
        "reason": "节拍中保持无对白",
    }
    assert stripped == ["feedback_responses[0].rationale_field"]


def test_mismatched_raw_tail_is_conservatively_downgraded_to_planned_cut():
    output = {
        "style": {},
        "shots": [
            {"id": "SH01", "start_state": "门闭", "end_state": "门开，仙童站定",
             "continuity_mode": "planned_cut_requires_adapter"},
            {"id": "SH02", "start_state": "猴王在树上，仙童站定", "end_state": "猴王落地",
             "continuity_mode": "raw_tail_continuation"},
            {"id": "SH03", "start_state": "猴王落地", "end_state": "猴王躬身",
             "continuity_mode": "raw_tail_continuation"},
        ],
        "media_assumptions": [],
    }

    projected = _project_mismatched_raw_tail_to_planned_cut(output)

    assert projected is not None
    corrected, affected = projected
    assert affected == ["SH02"]
    assert corrected["shots"][1]["continuity_mode"] == "planned_cut_requires_adapter"
    assert corrected["shots"][2]["continuity_mode"] == "raw_tail_continuation"
    assert output["shots"][1]["continuity_mode"] == "raw_tail_continuation"


def test_director_scope_adjustment_becomes_the_next_candidate_lock():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    adjusted = _candidate_with_director_scope(candidate, {
        "scope_adjustment": {
            "source": "director_brief",
            "lead_in_start_quote": "更早的逐字起点",
            "extend_end_quote": "更后的逐字终点",
            "reason": "覆盖承诺动作",
        },
    })

    assert adjusted["start_quote"] == "更早的逐字起点"
    assert adjusted["end_quote"] == "更后的逐字终点"
    assert candidate["start_quote"] != adjusted["start_quote"]


def test_candidate_projection_normalizes_quote_casing_and_drops_director_notes():
    candidate = deepcopy(_answers()[0]["candidates"][0])
    update = deepcopy(candidate)
    update["start_Quote"] = update.pop("start_quote")
    update["end_Quote"] = update.pop("end_quote")
    update["director_notes"] = "仅属导演执行说明"
    output = {
        "candidate_update": update,
        "feedback_responses": [{
            "feedback_index": 0,
            "decision": "accepted_in_script",
            "reason": "保持现有候选并在节拍落实",
        }],
    }

    projected = _project_director_feedback_candidate_lock(output, candidate)

    assert projected is not None
    corrected, restored, relocated, rejected, stripped, downgraded = projected
    assert corrected["candidate_update"] == candidate
    assert restored == []
    assert relocated is False
    assert rejected == []
    assert stripped == [
        "candidate_update.start_Quote",
        "candidate_update.end_Quote",
        "candidate_update.director_notes",
    ]
    assert downgraded == []


def test_writer_timing_repair_is_compact_and_cannot_rewrite_story(tmp_path):
    answers = _answers()
    long_script = deepcopy(answers[2])
    long_script["duration_seconds"] = 90
    for beat in long_script["beats"]:
        beat["duration_seconds"] = 45
    timing_patch = {"replace_beats": [
        {"beat_id": "B01", "duration_seconds": 10, "dialogue": []},
        {"beat_id": "B02", "duration_seconds": 10, "dialogue": []},
    ]}
    clients = FakeClients([
        answers[0], answers[1], long_script, timing_patch, answers[3], answers[4],
    ])
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(
        run_dir, clients=clients, creative_focus="总时长15到25秒",
    ).run(_bundle(tmp_path))
    assert state["status"] == "media_handoff_pending_capability"
    repair = json.loads(
        (run_dir / "writer_script__contract_repair.json").read_text(encoding="utf-8")
    )
    assert repair["repair_protocol"] == "writer_timing_patch/v4"
    request = json.loads(repair["request"][1]["content"])
    assert request["target_beat_ids"] == ["B01", "B02"]
    assert request["required_total_duration_range"] == [15.0, 25.0]
    assert "title" not in request and "premise" not in request
    assert request["beat_speech_unit_caps"] == {"B01": 202, "B02": 202}
    assert request["film_speech_unit_cap"] == 315

    invalid = deepcopy(timing_patch)
    invalid["replace_beats"][0]["event"] = "偷改事件"
    with pytest.raises(CreativeContractError, match="只能提交时长和对白"):
        _apply_writer_timing_patch(long_script, invalid, ["B01", "B02"])


def test_zero_duration_uses_new_timing_protocol_instead_of_stale_dialogue_repair(tmp_path):
    invalid = deepcopy(_answers()[2])
    invalid["beats"][1]["duration_seconds"] = 0
    invalid["duration_seconds"] = 10
    invalid["screenplay_markdown"] = compile_beat_screenplay(invalid)
    payload = {
        "material_ref": {"source_driver": "reference_video"},
        "candidate_lock": {"duration_seconds": 20},
    }
    patch = {"replace_beats": [{
        "beat_id": "B02", "duration_seconds": 10, "dialogue": [],
    }]}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "writer_script__contract_repair.json").write_text(json.dumps({
        "status": "response_received",
        "source_sha256": _hash(invalid),
        "payload_sha256": _hash(payload),
        "repair_protocol": "writer_novel_dialogue_patch/v1",
        "response_text": json.dumps({"patches": []}),
        "response_metadata": {"finish_reason": "stop"},
    }, ensure_ascii=False), encoding="utf-8")
    workflow = CreativeWorkflow(run_dir, clients=FakeClients([patch]))
    workflow.state = {
        "calls_started": 0, "max_calls": 5, "max_total_tokens": 100000,
        "budget_policy_version": "v4_20260923", "max_contract_repairs": 3,
        "contract_repairs_used": 0, "format_repairs_used": 0,
        "revision_rounds": 0, "stages": [],
    }
    corrected = workflow._validate_or_repair(
        "writer_script", "writer", payload, invalid,
        lambda value: validate_script(value, "C01", "", "reference_video"),
    )
    assert corrected["beats"][1]["duration_seconds"] == 10
    assert workflow.state["calls_started"] == 1
    new_repairs = [
        path for path in run_dir.glob("writer_script__contract_repair_*.json")
        if path.name != "writer_script__contract_repair.json"
    ]
    assert len(new_repairs) == 1
    receipt = json.loads(new_repairs[0].read_text(encoding="utf-8"))
    assert receipt["repair_protocol"] == "writer_timing_patch/v4"


def test_timing_repair_source_options_are_exact_contiguous_clauses():
    source_line = "第一句交代原因，第二句保留行动。第三句给出决定；第四句明确方向。"
    plan = deepcopy(_answers()[2])
    plan["beats"][0]["dialogue"] = [{"speaker": "甲", "text": source_line}]
    rows = _dialogue_compression_options(
        plan, ["B01"], f"甲说：「{source_line}」",
    )
    assert len(rows) == 1
    options = rows[0]["options"]
    assert {row["text"] for row in options} >= {
        "第一句交代原因，",
        "第二句保留行动。",
        "第一句交代原因，第二句保留行动。",
        "第三句给出决定；第四句明确方向。",
    }
    assert all(row["text"] in source_line for row in options)
    assert all(row["speech_units"] == _speech_units(row["text"])
               for row in options)


def test_timing_repair_keeps_nested_quote_delimiters_with_clause():
    source_line = "說：『外面有個修行的來了，可去接待接待。』想必就是你了？"
    plan = deepcopy(_answers()[2])
    plan["beats"][0]["dialogue"] = [{"speaker": "仙童", "text": source_line}]
    rows = _dialogue_compression_options(
        plan, ["B01"], f"仙童道：「{source_line}」",
    )
    options = {row["text"] for row in rows[0]["options"]}
    assert "說：『外面有個修行的來了，可去接待接待。』" in options
    assert "說：『外面有個修行的來了，可去接待接待。" not in options


def test_dialogue_timing_reports_all_overfull_beats_and_whole_film_density():
    from src.content_factory.creative_workflow_contract import validate_beat_plan

    beat_plan = _answers()[2]
    beat_plan["duration_seconds"] = 10
    for beat in beat_plan["beats"]:
        beat["duration_seconds"] = 5
        beat["dialogue"] = [{"speaker": "甲", "text": "解释" * 20}]
    with pytest.raises(CreativeContractError) as failure:
        validate_beat_plan(beat_plan, "C01", SOURCE, "reference_video")
    message = str(failure.value)
    assert "B01 对白约" in message
    assert "B02 对白约" in message
    assert "全片对白约" in message


def test_emotional_beat_reserves_reaction_time_below_six_chars_per_second():
    from src.content_factory.creative_workflow_contract import validate_beat_plan

    beat_plan = _answers()[2]
    beat_plan["beats"][0]["duration_seconds"] = 5
    beat_plan["beats"][0]["dialogue"] = [{
        "speaker": "旁白", "text": "一二三四五六七八九十一二三四五六七八九十一二三",
    }]
    beat_plan["beats"][1]["duration_seconds"] = 20
    beat_plan["duration_seconds"] = 25
    with pytest.raises(CreativeContractError, match="B01 对白约.*无法在 5 秒内"):
        validate_beat_plan(beat_plan, "C01", SOURCE, "reference_video")


def test_prompt_version_change_cannot_reuse_incomplete_run(tmp_path, monkeypatch):
    from src.content_factory.creative_workflow_contract import PROMPTS

    run_dir = tmp_path / "run"
    bundle = _bundle(tmp_path)
    with pytest.raises(StopIteration):
        CreativeWorkflow(run_dir, clients=FakeClients(_answers()[:1])).run(bundle)
    record = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))
    assert record["request"]["parameters"]["max_completion_tokens"] == 12000
    assert record["prompt_sha256"]
    monkeypatch.setitem(PROMPTS, "writer_analysis", PROMPTS["writer_analysis"] + "新规则")
    with pytest.raises(RuntimeError, match="提示词版本已改变"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_director_cannot_drop_or_reorder_dialogue(tmp_path):
    answers = _answers()
    answers[2]["beats"][0]["dialogue"] = [{"speaker": "甲", "text": "起因句。"}]
    answers[2]["screenplay_markdown"] += "起因句。"
    answers[3]["shots"][0]["dialogue_lock"] = []
    from src.content_factory.creative_workflow_contract import validate_shots
    with pytest.raises(CreativeContractError, match="分镜对白"):
        validate_shots(answers[3], answers[1], answers[2])


def test_assistant_review_binds_finished_versions_and_does_not_count_video(tmp_path):
    run_dir = tmp_path / "sample"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(_bundle(tmp_path))
    evidence = tmp_path / "review.md"
    evidence.write_text("人物归属：甲的起因句来自原文。动机：误会后主动解释。"
                        "情绪高光：质问前有迟疑，解释时有停顿，和解后有放松。"
                        "分镜按先质问再解释的顺序展示反应，未加入原文外的对白。" * 2,
                        encoding="utf-8")
    review = record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)
    assert review["first_draft_no_major"] is True
    assert len(review["workflow_profile_sha256"]) == 64
    assert review["input_profile"]["source_driver"] == "novel"
    assert review["style_class"] == "cinematic_realism"
    status = calibration_status(tmp_path)
    assert status["consecutive_first_draft_passes"] == 1
    assert status["stop_per_draft_assistant_review"] is False
    assert status["video_flow_passes"] == 0
    with pytest.raises(ValueError, match="不覆盖"):
        record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)


def test_style_class_treats_ink_wash_with_negated_cg_as_2d():
    brief = {
        "selected_style_id": "S01",
        "style_options": [{
            "id": "S01",
            "medium": "古典工笔淡彩动画（绢本设色质感，非写实CG）",
        }],
    }

    assert style_class_for_brief(brief) == "2d_illustrated_animation"


def test_workflow_profile_change_invalidates_old_clean_review(tmp_path, monkeypatch):
    from src.content_factory import creative_calibration

    run_dir = tmp_path / "sample"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(_bundle(tmp_path))
    evidence = tmp_path / "review.md"
    evidence.write_text(
        "人物归属和原文逐字核对完成；动机、情绪高光及镜头时长均无主要问题。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)

    monkeypatch.setattr(
        creative_calibration, "current_workflow_profile_sha256", lambda: "changed-profile",
    )
    status = creative_calibration.calibration_status(tmp_path)
    assert status["consecutive_first_draft_passes"] == 0
    assert status["stop_per_draft_assistant_review"] is False
    assert status["profile_mismatch_reviews"] == 1


def test_profile_change_between_generation_and_review_cannot_count_as_clean(
    tmp_path, monkeypatch,
):
    from src.content_factory import creative_calibration

    run_dir = tmp_path / "sample"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(_bundle(tmp_path))
    monkeypatch.setattr(
        creative_calibration, "current_workflow_profile_sha256", lambda: "new-profile",
    )
    evidence = tmp_path / "review.md"
    evidence.write_text(
        "人物归属、动机、情绪高光和镜头连续性均已逐项核对。" * 5,
        encoding="utf-8",
    )
    review = record_review(
        run_dir, category="campus_novel", outcome="passed", evidence_file=evidence,
    )
    assert review["profile_unchanged_since_generation"] is False
    assert review["first_draft_no_major"] is False


def test_assistant_major_review_reopens_task_without_reusing_text_handoff(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    finished = CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    handoff_hash = finished["handoff_sha256"]
    evidence = tmp_path / "major.md"
    evidence.write_text(
        "人物归属虽正确，但第一拍的关键道具突然出现。"
        "观众尚未看见甲取物，后续却据此改变决定，动机不成立。"
        "请回到编剧节拍建立取物动作，再由导演重做受影响镜头。" * 3,
        encoding="utf-8",
    )
    review = record_review(run_dir, category="campus_novel", outcome="major_issues",
                           evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "needs_revision"
    assert state["assistant_review_outcome"] == "major_issues"
    assert state["handoff_sha256"] == handoff_hash
    assert calibration_status(tmp_path)["reviewed_tasks"] == 1
    assert calibration_status(tmp_path)["consecutive_first_draft_passes"] == 0
    assert CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)["status"] == "needs_revision"
    assert synchronize_review_state(run_dir) == state
    evidence.write_text(evidence.read_text(encoding="utf-8") + "篡改", encoding="utf-8")
    with pytest.raises(ValueError, match="证据或媒体交接版本不符"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)
    assert calibration_status(tmp_path)["reviewed_tasks"] == 0
    assert review["outcome"] == "major_issues"


def test_assistant_feedback_spends_same_round_and_keeps_original_handoff(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "major.md"
    evidence.write_text(
        "人物归属正确，但第一拍缺少决定性道具的首次出现。"
        "请先建立取物动作，再让镜头捕捉人物看到它后的反应。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    initial = json.loads((run_dir / "SCREENPLAY.json").read_text(encoding="utf-8"))
    handoff = json.loads((run_dir / "MEDIA_HANDOFF.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    feedback = {
        "schema": "creative_assistant_feedback/v1",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{
            "owner": "writer", "location": "B01", "evidence": "道具出现前就改变决定",
            "impact": "观众看不懂动机", "proposal": "先建立取物动作", "severity": "major",
        }],
    }
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    revised = deepcopy(initial)
    revised["beats"][0]["before"] = "先建立道具再迟疑"
    revised["screenplay_markdown"] = compile_beat_screenplay(revised)
    clients = FakeClients([revised, _answers()[3], _answers()[4]])
    workflow = CreativeWorkflow(run_dir, clients=clients)
    updated = workflow.revise_from_assistant(bundle, path)
    assert updated["status"] == "needs_revision"
    assert updated["assistant_revision_status"] == "assistant_recheck_pending"
    assert updated["calls_started"] == 8 and updated["revision_rounds"] == 1
    draft = json.loads((run_dir / "ASSISTANT_REVISION_DRAFT.json").read_text(encoding="utf-8"))
    assert draft["script"]["beats"][0]["before"] == "先建立道具再迟疑"
    assert draft["automatic_submit"] is False
    assert json.loads((run_dir / "SCREENPLAY.json").read_text(encoding="utf-8")) == initial
    assert json.loads((run_dir / "MEDIA_HANDOFF.json").read_text(encoding="utf-8")) == handoff
    assert calibration_status(tmp_path)["reviewed_tasks"] == 1
    resumed = CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(bundle, path)
    assert resumed["calls_started"] == 8 and resumed["revision_rounds"] == 1
    followup_evidence = tmp_path / "followup.md"
    followup_evidence.write_text(
        "返修后道具首次出现虽已建立，但另一拍人物仍突然改变决定。"
        "观众尚未看到新刺激，不能把编剧回核的空问题单当作内容通过。" * 4,
        encoding="utf-8",
    )
    second = record_revision_review(run_dir, outcome="major_issues",
                                    evidence_file=followup_evidence)
    assert second["draft_sha256"] == updated["assistant_revision_draft_sha256"]
    reviewed = CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(bundle, path)
    assert reviewed["assistant_revision_status"] == "needs_revision"
    assert reviewed["calls_started"] == 8
    with pytest.raises(ValueError, match="不覆盖"):
        record_revision_review(run_dir, outcome="major_issues", evidence_file=followup_evidence)
    feedback["issues"][0]["proposal"] = "改变别的情节"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="已绑定另一版本"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(bundle, path)


def test_assistant_feedback_merges_compact_writer_and_director_patches(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    answers = _answers()
    CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(bundle)
    evidence = tmp_path / "major.md"
    evidence.write_text(
        "第一拍的决定性道具尚未建立，人物就已经改变决定。"
        "需要编剧只修第一拍，再让导演重做第一拍镜头并保留第二拍。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    feedback = {
        "schema": "creative_assistant_feedback/v1",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{
            "owner": "writer", "location": "B01 / SH01",
            "evidence": "道具出现前就改变决定", "impact": "观众看不懂动机",
            "proposal": "先建立取物动作", "severity": "major",
        }],
    }
    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    revised_beat = deepcopy(answers[2]["beats"][0])
    revised_beat["before"] = "甲先从桌面拿起道具，再迟疑"
    writer_patch = {"replace_beats": [{"beat_id": "B01", "beat": revised_beat}]}
    revised_shot = deepcopy(answers[3]["shots"][0])
    revised_shot["visible_performance"] = "甲拿起道具后停顿，迟疑清楚可见"
    director_patch = {"replace_beats": [{"beat_id": "B01", "shots": [revised_shot]}]}

    updated = CreativeWorkflow(
        run_dir, clients=FakeClients([writer_patch, director_patch, answers[4]]),
    ).revise_from_assistant(bundle, feedback_path)

    assert updated["assistant_revision_status"] == "assistant_recheck_pending"
    draft = json.loads((run_dir / "ASSISTANT_REVISION_DRAFT.json").read_text(encoding="utf-8"))
    assert draft["script"]["beats"][0]["before"] == "甲先从桌面拿起道具，再迟疑"
    assert draft["script"]["beats"][1] == answers[2]["beats"][1]
    assert draft["shots"]["shots"][0]["visible_performance"] == "甲拿起道具后停顿，迟疑清楚可见"
    assert draft["shots"]["shots"][1] == answers[3]["shots"][1]
    receipt = json.loads(
        (run_dir / "writer_revise__assistant_01__affected_projection.json")
        .read_text(encoding="utf-8")
    )
    assert receipt["affected_beat_ids"] == ["B01"]
    assert not (run_dir / "writer_revise__assistant_01__contract_repair.json").exists()
    assert not (run_dir / "director_revise__assistant_01__contract_repair.json").exists()


def test_second_assistant_feedback_uses_reviewed_parent_and_shared_budget(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    first_evidence = tmp_path / "first.md"
    first_evidence.write_text(
        "首稿人物动机有来源，但决定性道具没有首次出现。"
        "观众看不见刺激，后续改变决定不成立，编剧需补建立动作。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=first_evidence)
    initial_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    first_feedback = {
        "schema": "creative_assistant_feedback/v1",
        "handoff_sha256": initial_state["handoff_sha256"],
        "assistant_review_sha256": initial_state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "B01", "evidence": "关键道具未出现",
                    "impact": "决定无刺激", "proposal": "补首次出现", "severity": "major"}],
    }
    feedback_path = tmp_path / "first_feedback.json"
    feedback_path.write_text(json.dumps(first_feedback, ensure_ascii=False), encoding="utf-8")
    revised = deepcopy(_answers()[2])
    revised["beats"][0]["before"] = "甲先取出道具然后迟疑"
    revised["screenplay_markdown"] = compile_beat_screenplay(revised)
    first_check = {
        "story_preserved": False,
        "issues": [{"owner": "writer", "location": "B02", "evidence": "下一拍决定缺刺激",
                    "impact": "转折不成立", "proposal": "补可见触发", "severity": "major"}],
        "calibration_focus": ["第一轮未解决的转折"],
    }
    first_workflow = CreativeWorkflow(
        run_dir, clients=FakeClients([revised, _answers()[3], first_check]),
    )
    first_state = first_workflow.revise_from_assistant(bundle, feedback_path)
    assert first_state["revision_rounds"] == 1
    assert first_state["assistant_revision_status"] == "needs_revision"
    first_draft_path = run_dir / "ASSISTANT_REVISION_DRAFT.json"
    first_draft_bytes = first_draft_path.read_bytes()
    reread_evidence = tmp_path / "reread.md"
    reread_evidence.write_text(
        "第一次返修补了道具出现，但下一拍的关系决定仍没有新的可见刺激。"
        "这个主要问题要回到编剧修，不应只让导演增加一个特写。" * 4,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="没有待助手复看的返修稿"):
        record_revision_review(run_dir, outcome="passed", evidence_file=reread_evidence)
    record_revision_review(run_dir, outcome="major_issues", evidence_file=reread_evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    second_feedback = {
        "schema": "creative_assistant_feedback/v2",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "parent_revision_review_sha256": state["assistant_revision_review_sha256"],
        "issues": [{"owner": "writer", "location": "B02", "evidence": "下一拍决定缺刺激",
                    "impact": "转折不成立", "proposal": "补可见触发", "severity": "major"}],
    }
    second_path = tmp_path / "second_feedback.json"
    second_path.write_text(json.dumps(second_feedback, ensure_ascii=False), encoding="utf-8")
    stale = deepcopy(second_feedback)
    stale["parent_revision_review_sha256"] = "0" * 64
    stale_path = tmp_path / "stale_feedback.json"
    stale_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CreativeContractError, match="第一轮实际复核"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(bundle, stale_path)
    assert not (run_dir / "ASSISTANT_FEEDBACK__02.json").exists()
    second_script = deepcopy(revised)
    second_script["beats"][1]["before"] = "乙看到道具后才主动解释"
    second_script["screenplay_markdown"] = compile_beat_screenplay(second_script)
    second_workflow = CreativeWorkflow(
        run_dir, clients=FakeClients([second_script, _answers()[3], _answers()[4]]),
    )
    second_state = second_workflow.revise_from_assistant(bundle, second_path)
    assert second_state["assistant_revision_status"] == "assistant_recheck_pending"
    assert second_state["revision_rounds"] == 2
    assert second_state["calls_started"] == 11
    assert second_state["assistant_revision_round_index"] == 2
    assert first_draft_path.read_bytes() == first_draft_bytes
    second_draft = json.loads((run_dir / "ASSISTANT_REVISION_DRAFT__02.json").read_text(encoding="utf-8"))
    assert second_draft["script"]["beats"][0]["before"] == "甲先取出道具然后迟疑"
    assert second_draft["script"]["beats"][1]["before"] == "乙看到道具后才主动解释"
    assert second_draft["parent_revision_review_sha256"] == second_feedback["parent_revision_review_sha256"]
    assert CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(
        bundle, second_path,
    )["calls_started"] == 11
    final_evidence = tmp_path / "final.md"
    final_evidence.write_text(
        "第二轮返修中，道具首次出现与下一拍的反应已经按剧本顺序展示。"
        "人物动机、对白来源、两人位置、手上道具和末拍的关系结果均逐项复核，"
        "没有再发现阻断或主要质量问题。" * 4,
        encoding="utf-8",
    )
    record_revision_review(run_dir, outcome="passed", evidence_file=final_evidence)
    promoted = CreativeWorkflow(run_dir, clients=FakeClients([])).promote_reviewed_assistant_revision(bundle)
    assert promoted["status"] == "reviewed_revision_media_handoff_pending_capability"
    assert promoted["revision_rounds"] == 2
    assert first_draft_path.read_bytes() == first_draft_bytes
    assert json.loads((run_dir / "ASSISTANT_REVISED_SCREENPLAY.json").read_text(encoding="utf-8")) == second_script
    assert CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)["status"] == promoted["status"]
    reread_evidence.write_text(reread_evidence.read_text(encoding="utf-8") + "篡改", encoding="utf-8")
    with pytest.raises(ValueError, match="返修稿助手复核与当前任务版本不符"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_assistant_upstream_character_motivation_rechecks_all_descendants(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "first.md"
    evidence.write_text(
        "首稿把一次短暂反应解释为确定的强烈动机，原文引文只支持当场动作。"
        "这一人物目标会影响导演方向、剧本表演与镜头判断，必须先修编剧分析。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    original_analysis = json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))["output"]
    feedback = {
        "schema": "creative_assistant_feedback/v3", "round_index": 1,
        "repair_scope": "analysis_character_motivation", "target_characters": ["甲"],
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "writer_analysis.characters[0].want",
                    "evidence": "引文只支持当场动作", "impact": "导演误读人物动机",
                    "proposal": "只保留有依据的有限目标", "severity": "major"}],
    }
    path = tmp_path / "analysis_feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    invalid = deepcopy(feedback)
    invalid["target_characters"] = ["不存在的人物"]
    invalid_path = tmp_path / "invalid_feedback.json"
    invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CreativeContractError, match="不存在的人物"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(bundle, invalid_path)
    assert not (run_dir / "ASSISTANT_FEEDBACK.json").exists()
    revised_script = deepcopy(_answers()[2])
    revised_script["beats"][0]["before"] = "甲看见证据后才开口"
    revised_script["screenplay_markdown"] = compile_beat_screenplay(revised_script)
    clients = FakeClients([
        {"character_updates": [{"name": "甲", "want": "只解释这次误会",
                                 "fear": "其他担忧原文未证实", "source_quote": "模型错误扩写的引文"}]},
        _answers()[1], revised_script, _answers()[3], _answers()[4],
    ])
    updated = CreativeWorkflow(run_dir, clients=clients).revise_from_assistant(bundle, path)
    assert updated["assistant_revision_status"] == "assistant_recheck_pending"
    assert updated["calls_started"] == 10 and updated["revision_rounds"] == 1
    draft = json.loads((run_dir / "ASSISTANT_REVISION_DRAFT.json").read_text(encoding="utf-8"))
    assert draft["analysis"]["characters"][0]["want"] == "只解释这次误会"
    assert draft["analysis"]["candidates"] == original_analysis["candidates"]
    assert draft["analysis"]["characters"][0]["source_quote"] == "起因句。"
    assert [row["name"] for row in draft["source_quote_echoes_ignored"]] == ["甲"]
    assert json.loads((run_dir / "writer_analysis.json").read_text(encoding="utf-8"))["output"] == original_analysis
    assert [row["name"] for row in updated["stages"][-5:]] == [
        "writer_character_motivation_revise__assistant_01", "director_brief__assistant_01",
        "writer_revise__assistant_01", "director_revise__assistant_01",
        "writer_check__assistant_01",
    ]
    reread = tmp_path / "reread.md"
    reread.write_text(
        "已逐项复看修订分析的引文与人物目标，候选边界和对白没有改写。"
        "导演方向、剧本动作、镜头和编剧回核都建立在新分析上，"
        "人物反应与结局仍符合所选原文，未发现主要问题。" * 4,
        encoding="utf-8",
    )
    record_revision_review(run_dir, outcome="passed", evidence_file=reread)
    promoted = CreativeWorkflow(run_dir, clients=FakeClients([])).promote_reviewed_assistant_revision(bundle)
    assert promoted["status"] == "reviewed_revision_media_handoff_pending_capability"
    revised_analysis_path = run_dir / "ASSISTANT_REVISED_ANALYSIS.json"
    assert json.loads(revised_analysis_path.read_text(encoding="utf-8"))["characters"][0]["want"] == "只解释这次误会"
    assert CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)["status"] == promoted["status"]
    changed = json.loads(revised_analysis_path.read_text(encoding="utf-8"))
    changed["characters"][0]["want"] = "篡改"
    revised_analysis_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="返修交接的 ASSISTANT_REVISED_ANALYSIS.json 版本不符"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_assistant_upstream_candidate_claims_rebuilds_all_descendants(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "first.md"
    evidence.write_text(
        "首稿候选的情绪峰值承诺了选段结束以后才发生的动作，"
        "而当前锁定原文只到两人理解彼此，不能让后代剧本和镜头继续沿用越界结果。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    original_analysis = json.loads(
        (run_dir / "writer_analysis.json").read_text(encoding="utf-8")
    )["output"]
    original_candidate = deepcopy(original_analysis["candidates"][0])
    feedback = {
        "schema": "creative_assistant_feedback/v3", "round_index": 1,
        "repair_scope": "analysis_candidate_claims", "target_candidate_id": "C01",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "writer_analysis.candidates[C01].peak",
                    "evidence": "峰值承诺了选段外动作", "impact": "剧本会越过来源边界",
                    "proposal": "把峰值和收束限制在结局句以内", "severity": "major"}],
    }
    path = tmp_path / "candidate_feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    candidate_update = {
        **original_candidate,
        "peak": "解释被听见，两人停止争执",
        "aftermath": "两人在结局句内确认理解",
        "selection_reason": "锁定选段内已有起因、解释和理解",
    }
    beat_plan = deepcopy(_answers()[2])
    beat_plan.pop("screenplay_markdown")
    clients = FakeClients([
        {"candidate_update": candidate_update}, _answers()[1], beat_plan,
        _answers()[3], _answers()[4],
    ])
    updated = CreativeWorkflow(run_dir, clients=clients).revise_from_assistant(bundle, path)
    assert updated["assistant_revision_status"] == "assistant_recheck_pending"
    assert updated["calls_started"] == 10 and updated["revision_rounds"] == 1
    assert [row["name"] for row in updated["stages"][-5:]] == [
        "writer_candidate_claims_revise__assistant_01", "director_brief__assistant_01",
        "writer_script__assistant_01", "director_revise__assistant_01",
        "writer_check__assistant_01",
    ]
    draft = json.loads((run_dir / "ASSISTANT_REVISION_DRAFT.json").read_text(encoding="utf-8"))
    revised_candidate = draft["analysis"]["candidates"][0]
    assert revised_candidate["peak"] == "解释被听见，两人停止争执"
    for key in ("id", "title", "start_quote", "end_quote", "duration_seconds"):
        assert revised_candidate[key] == original_candidate[key]
    assert json.loads(
        (run_dir / "writer_analysis.json").read_text(encoding="utf-8")
    )["output"] == original_analysis
    assert draft["script"]["screenplay_markdown"] == compile_beat_screenplay(beat_plan)
    reread = tmp_path / "reread.md"
    reread.write_text(
        "已重新对照候选起止引文，峰值与收束均没有再承诺选段以外的动作。"
        "导演方向、节拍稿、镜头及编剧回核都从修订候选重新生成，"
        "人物、对白、选段边界和事件结果未发现主要问题。" * 4,
        encoding="utf-8",
    )
    record_revision_review(run_dir, outcome="passed", evidence_file=reread)
    promoted = CreativeWorkflow(run_dir, clients=FakeClients([])).promote_reviewed_assistant_revision(bundle)
    assert promoted["status"] == "reviewed_revision_media_handoff_pending_capability"
    revised_analysis = json.loads(
        (run_dir / "ASSISTANT_REVISED_ANALYSIS.json").read_text(encoding="utf-8")
    )
    assert revised_analysis["candidates"][0] == revised_candidate


def test_assistant_candidate_claims_cannot_change_selected_source_lock(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "first.md"
    evidence.write_text(
        "候选峰值超出锁定来源，需要回到候选声明修复。"
        "本轮只允许收回越界承诺，不能借机扩大或替换原文选段。" * 6,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    original = json.loads(
        (run_dir / "writer_analysis.json").read_text(encoding="utf-8")
    )["output"]["candidates"][0]
    feedback = {
        "schema": "creative_assistant_feedback/v3", "round_index": 1,
        "repair_scope": "analysis_candidate_claims", "target_candidate_id": "C01",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "writer_analysis.candidates[C01].peak",
                    "evidence": "峰值越界", "impact": "来源不实",
                    "proposal": "收回越界承诺", "severity": "major"}],
    }
    path = tmp_path / "candidate_feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    invalid = {**original, "peak": "修改峰值", "end_quote": "起因句。"}
    with pytest.raises(CreativeContractError, match="改变了身份、选段或时长"):
        CreativeWorkflow(
            run_dir,
            clients=FakeClients([{"candidate_update": invalid}] * 3),
        ).revise_from_assistant(bundle, path)
    assert not (run_dir / "ASSISTANT_REVISION_DRAFT.json").exists()


def test_assistant_selected_source_boundary_rebuilds_bound_descendants(tmp_path):
    novel = tmp_path / "novel.txt"
    novel.write_text("直接诱因。" + SOURCE, encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="补足前因", novel_path=novel)
    run_dir = tmp_path / "sample"
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    original_selection = json.loads(
        (run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8")
    )
    original_bytes = (run_dir / "SELECTED_SOURCE.json").read_bytes()
    evidence = tmp_path / "first.md"
    evidence.write_text(
        "首稿从角色反应开始，紧邻原文里的直接诱因没有进入锁定选段。"
        "缺少这一步会让第一拍的质问和迟疑没有可见前因，必须受控前移边界后重做下游稿。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    feedback = {
        "schema": "creative_assistant_feedback/v3", "round_index": 1,
        "repair_scope": "selected_source_boundary", "target_candidate_id": "C01",
        "parent_selected_source_sha256": _hash(original_selection),
        "new_start_quote": "直接诱因。", "new_end_quote": "结局句。",
        "boundary_reason": "把第一拍成立所需的紧邻直接诱因纳入同一事件",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "selected_source.start_quote",
                    "evidence": "当前起点前紧邻直接诱因", "impact": "第一拍缺少因果",
                    "proposal": "前移到直接诱因并重做全部下游稿", "severity": "major"}],
    }
    path = tmp_path / "boundary_feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    beat_plan = deepcopy(_answers()[2])
    beat_plan.pop("screenplay_markdown")
    updated = CreativeWorkflow(
        run_dir,
        clients=FakeClients([_answers()[1], beat_plan, _answers()[3], _answers()[4]]),
    ).revise_from_assistant(bundle, path)
    assert updated["assistant_revision_status"] == "assistant_recheck_pending"
    assert updated["calls_started"] == 9 and updated["revision_rounds"] == 1
    assert [row["name"] for row in updated["stages"][-4:]] == [
        "director_brief__assistant_01", "writer_script__assistant_01",
        "director_revise__assistant_01", "writer_check__assistant_01",
    ]
    draft = json.loads((run_dir / "ASSISTANT_REVISION_DRAFT.json").read_text(encoding="utf-8"))
    revised_selection = draft["selected_source"]
    assert revised_selection["text"].startswith("直接诱因。起因句。")
    assert revised_selection["parent_selected_source_sha256"] == _hash(original_selection)
    assert draft["selected_source_sha256"] == _hash(revised_selection)
    assert draft["analysis"]["candidates"][0]["start_quote"] == "直接诱因。"
    assert (run_dir / "SELECTED_SOURCE.json").read_bytes() == original_bytes

    reread = tmp_path / "reread.md"
    reread.write_text(
        "已逐字核对新旧选段边界，新选段只向前纳入紧邻的直接诱因，仍是同一候选事件。"
        "导演方向、节拍、分镜和编剧回核都重新生成，人物、结局和原文对白未发现主要问题。" * 4,
        encoding="utf-8",
    )
    record_revision_review(run_dir, outcome="passed", evidence_file=reread)
    promoted = CreativeWorkflow(
        run_dir, clients=FakeClients([]),
    ).promote_reviewed_assistant_revision(bundle)
    assert promoted["status"] == "reviewed_revision_media_handoff_pending_capability"
    exported = json.loads(
        (run_dir / "ASSISTANT_REVISED_SELECTED_SOURCE.json").read_text(encoding="utf-8")
    )
    handoff = json.loads(
        (run_dir / "ASSISTANT_REVISED_MEDIA_HANDOFF.json").read_text(encoding="utf-8")
    )
    assert exported == revised_selection
    assert handoff["selected_source_sha256"] == _hash(exported)
    revised_manifest = json.loads(
        (run_dir / "ASSISTANT_REVISED_CREATIVE_OUTPUT_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    assert revised_manifest["handoff_sha256"] == _hash(handoff)
    assert promoted["revised_output_manifest_sha256"] == _hash(revised_manifest)


def test_selected_source_boundary_rejects_stale_reverse_distant_and_noop():
    source = "远端前文。" + "填充。" * 300 + SOURCE
    start = source.index("起因句。")
    end = source.index("结局句。") + len("结局句。")
    current = {
        "candidate_id": "C01", "start_character": start, "end_character": end,
        "source_sha256": _hash(source), "excerpt_sha256": _hash(source[start:end]),
        "text": source[start:end],
    }
    base = {
        "target_candidate_id": "C01", "parent_selected_source_sha256": _hash(current),
        "new_start_quote": "起因句。", "new_end_quote": "结局句。",
        "boundary_reason": "调整边界",
    }
    with pytest.raises(CreativeContractError, match="没有改变"):
        _revise_selected_source_boundary(source, current, base)
    with pytest.raises(CreativeContractError, match="未绑定当前"):
        _revise_selected_source_boundary(
            source, current, {**base, "parent_selected_source_sha256": "0" * 64},
        )
    with pytest.raises(CreativeContractError, match="起止顺序倒置"):
        _revise_selected_source_boundary(
            source, current,
            {**base, "new_start_quote": "结局句。", "new_end_quote": "起因句。"},
        )
    with pytest.raises(CreativeContractError, match="800 字"):
        _revise_selected_source_boundary(
            source, current, {**base, "new_start_quote": "远端前文。"},
        )


def test_video_driver_rejects_selected_source_boundary_feedback(tmp_path):
    video = tmp_path / "reference.mp4"
    analysis_path = tmp_path / "reference.md"
    video.write_bytes(b"video bytes")
    analysis_path.write_text(
        "原视频 reference.mp4。观察到误会、沉默和和解。", encoding="utf-8",
    )
    bundle = load_materials(
        source_driver="reference_video", title="原创片", video_path=video,
        analysis_path=analysis_path,
    )
    answers = _answers()
    answers[0]["candidates"][0]["start_quote"] = ""
    answers[0]["candidates"][0]["end_quote"] = ""
    run_dir = tmp_path / "video_run"
    CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(bundle)
    evidence = tmp_path / "video_review.md"
    evidence.write_text(
        "视频原创稿的前因表达不足，但该来源只提供表达机制，不存在可逐字引用的小说选段。"
        "问题应回到原创候选或节拍处理，不能伪造起止引文。" * 5,
        encoding="utf-8",
    )
    record_review(run_dir, category="video_original", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    selection = json.loads((run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8"))
    feedback = {
        "schema": "creative_assistant_feedback/v3", "round_index": 1,
        "repair_scope": "selected_source_boundary", "target_candidate_id": "C01",
        "parent_selected_source_sha256": _hash(selection),
        "new_start_quote": "观察到误会", "new_end_quote": "和解",
        "boundary_reason": "错误尝试",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "selected_source.start_quote",
                    "evidence": "原创前因不足", "impact": "动机不清",
                    "proposal": "错误地尝试小说选段修订", "severity": "major"}],
    }
    path = tmp_path / "video_boundary_feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CreativeContractError, match="视频原创驱动"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).revise_from_assistant(bundle, path)
    assert not (run_dir / "ASSISTANT_FEEDBACK.json").exists()


def test_reviewed_assistant_revision_exports_separate_bound_handoff(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "first.md"
    evidence.write_text(
        "人物关系和原著事实清楚，但镜头没有给甲听完解释后的表情。"
        "导演应调整同一情绪节拍的构图与反应窗口，之后再读完整稿。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    feedback = {
        "schema": "creative_assistant_feedback/v1",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{
            "owner": "director", "location": "SH02", "evidence": "没有听者表情",
            "impact": "解释后的情绪不可见", "proposal": "给听者反应镜头",
            "severity": "major",
        }],
    }
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    revised = CreativeWorkflow(run_dir, clients=FakeClients([_answers()[3], _answers()[4]]))
    assert revised.revise_from_assistant(bundle, path)["assistant_revision_status"] == "assistant_recheck_pending"
    second_evidence = tmp_path / "second.md"
    second_evidence.write_text(
        "导演稿已补上甲听完解释后的可见表情和停顿，人物关系、对白与先后顺序未改变。"
        "逐镜核对手、道具、站位和最终关系结果，未再发现主要质量问题。" * 4,
        encoding="utf-8",
    )
    record_revision_review(run_dir, outcome="passed", evidence_file=second_evidence)
    promoted = CreativeWorkflow(run_dir, clients=FakeClients([])).promote_reviewed_assistant_revision(bundle)
    assert promoted["status"] == "reviewed_revision_media_handoff_pending_capability"
    assert promoted["assistant_revision_status"] == "passed_media_handoff_pending_capability"
    handoff = json.loads((run_dir / "ASSISTANT_REVISED_MEDIA_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["automatic_submit"] is False
    assert handoff["text_status"] == "assistant_review_passed_after_revision"
    assert handoff["original_handoff_sha256"] == promoted["handoff_sha256"]
    assert calibration_status(tmp_path)["reviewed_tasks"] == 1
    assert calibration_status(tmp_path)["consecutive_first_draft_passes"] == 0
    assert CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)["status"] == promoted["status"]
    screenplay = run_dir / "ASSISTANT_REVISED_SCREENPLAY.json"
    changed = json.loads(screenplay.read_text(encoding="utf-8"))
    changed["premise"] = "另一种故事"
    screenplay.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="版本不符"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)


def test_assistant_feedback_cannot_reset_shared_revision_cap(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers()), max_revisions=0).run(bundle)
    evidence = tmp_path / "first.md"
    evidence.write_text(
        "已读取人物、剧情和分镜，发现关键道具的首次拿取缺失。"
        "这会使之后的情绪决定没有可见刺激，必须回到编剧层修订。" * 4,
        encoding="utf-8",
    )
    record_review(run_dir, category="campus_novel", outcome="major_issues",
                  evidence_file=evidence)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    feedback = {
        "schema": "creative_assistant_feedback/v1",
        "handoff_sha256": state["handoff_sha256"],
        "assistant_review_sha256": state["assistant_review_sha256"],
        "issues": [{"owner": "writer", "location": "B01", "evidence": "道具未出现",
                    "impact": "动机不可见", "proposal": "先建立取物动作", "severity": "major"}],
    }
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
    stopped = CreativeWorkflow(run_dir, clients=FakeClients([]), max_revisions=0).revise_from_assistant(
        bundle, path,
    )
    assert stopped["assistant_revision_status"] == "budget_exhausted"
    assert stopped["calls_started"] == 5 and stopped["revision_rounds"] == 0
    assert not (run_dir / "ASSISTANT_REVISION_DRAFT.json").exists()


def test_capability_audit_tamper_invalidates_resume_and_calibration(tmp_path):
    run_dir = tmp_path / "sample"
    bundle = _bundle(tmp_path)
    CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
    evidence = tmp_path / "review.md"
    evidence.write_text("人物归属和来源逐项核对；误会、解释与和解的动机清楚。"
                        "重要对白前后保留可见反应，导演画风有材料依据。" * 4,
                        encoding="utf-8")
    record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)
    path = run_dir / "MEDIA_CAPABILITY_AUDIT.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    audit["automatic_submit"] = True
    path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="媒体执行能力审计已被改动"):
        CreativeWorkflow(run_dir, clients=FakeClients([])).run(bundle)
    assert calibration_status(tmp_path)["reviewed_tasks"] == 0


def test_incomplete_attempt_breaks_consecutive_clean_draft_sequence(tmp_path):
    bundle = _bundle(tmp_path)
    evidence = tmp_path / "review.md"
    evidence.write_text("人物与原文引文对应，解释误会的动机成立；"
                        "质问前、中、后均有表演窗口，镜头连续并有明确收束。" * 4,
                        encoding="utf-8")
    for name in ("first", "third"):
        run_dir = tmp_path / name
        CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(bundle)
        record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)
        if name == "first":
            with pytest.raises(StopIteration):
                CreativeWorkflow(tmp_path / "second", clients=FakeClients(_answers()[:2])).run(bundle)
    status = calibration_status(tmp_path)
    assert status["attempted_tasks"] == 3
    assert status["reviewed_tasks"] == 2
    assert status["consecutive_first_draft_passes"] == 1
    assert status["stop_per_draft_assistant_review"] is False


def test_calibration_milestone_survives_routine_unreviewed_task_and_reopens_on_major_issue(
    tmp_path, monkeypatch,
):
    from src.content_factory import creative_calibration
    monkeypatch.setattr(creative_calibration, "_valid_handoff", lambda _run, _state: {})
    profile = creative_calibration.current_workflow_profile_sha256()

    def add_attempt(index, category=None, outcome="passed"):
        run_dir = tmp_path / f"run_{index}"
        run_dir.mkdir()
        handoff_sha = f"handoff_{index}"
        (run_dir / "state.json").write_text(json.dumps({
            "schema": "creative_workflow_state/v1",
            "created_at": f"2026-09-22T00:00:{index:02}+00:00",
            "status": "media_handoff_pending_capability",
            "handoff_sha256": handoff_sha,
        }), encoding="utf-8")
        if category:
            evidence = tmp_path / f"evidence_{index}.md"
            evidence.write_text(f"第 {index} 份实际审阅证据", encoding="utf-8")
            (run_dir / "CALIBRATION_REVIEW.json").write_text(json.dumps({
                "handoff_sha256": handoff_sha,
                "evidence_path": str(evidence),
                "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                "first_draft_no_major": outcome == "passed",
                "category": category, "outcome": outcome,
                "material_sha256": f"material_{index}",
                "workflow_profile_sha256": profile,
                "input_profile_sha256": f"input_profile_{index}",
                "style_class": f"style_{index}",
            }), encoding="utf-8")

    for index, category in enumerate(("campus_novel", "other_genre_novel", "video_original"), 1):
        add_attempt(index, category)
    assert calibration_status(tmp_path)["stop_per_draft_assistant_review"] is True
    add_attempt(4)
    status = calibration_status(tmp_path)
    assert status["stop_per_draft_assistant_review"] is True
    assert status["consecutive_first_draft_passes"] == 0
    assert len(status["calibration_milestone"]["run_dirs"]) == 3
    add_attempt(5, "video_original", "major_issues")
    status = calibration_status(tmp_path)
    assert status["stop_per_draft_assistant_review"] is False
    assert status["targeted_review_reopened"] is True


def test_completed_task_snapshots_calibrated_review_policy(tmp_path, monkeypatch):
    from src.content_factory import creative_workflow
    monkeypatch.setattr(creative_workflow, "calibration_status", lambda _root: {
        "stop_per_draft_assistant_review": True,
        "calibration_milestone": {"at": "2026-09-22T00:00:03+00:00", "run_dirs": ["a", "b", "c"]},
    })
    run_dir = tmp_path / "calibrated_task"
    state = CreativeWorkflow(run_dir, clients=FakeClients(_answers())).run(_bundle(tmp_path))
    packet = json.loads((run_dir / "EDITORIAL_REVIEW_PACKET.json").read_text(encoding="utf-8"))
    handoff = json.loads((run_dir / "MEDIA_HANDOFF.json").read_text(encoding="utf-8"))
    assert state["assistant_review_required"] is False
    assert packet["review_status"] == "routine_assistant_review_waived_after_calibration"
    assert handoff["text_status"] == "auto_checked_routine_review_waived_after_calibration"
    assert handoff["automatic_submit"] is False


@pytest.mark.parametrize(
    ("calibrated_inputs", "calibrated_styles", "expected_reason"),
    [([], ["cinematic_realism"], "unseen_input_profile"),
     ("current", ["2d_illustrated_animation"], "unseen_style_class")],
)
def test_calibrated_policy_reopens_for_new_input_or_style(
    tmp_path, monkeypatch, calibrated_inputs, calibrated_styles, expected_reason,
):
    from src.content_factory import creative_workflow
    from src.content_factory.creative_calibration import material_input_profile_sha256

    bundle = _bundle(tmp_path)
    current_input = material_input_profile_sha256(bundle.manifest)
    input_profiles = [current_input] if calibrated_inputs == "current" else calibrated_inputs
    monkeypatch.setattr(creative_workflow, "calibration_status", lambda _root: {
        "stop_per_draft_assistant_review": True,
        "calibration_milestone": {"at": "2026-09-22T00:00:03+00:00"},
        "current_workflow_profile_sha256": "profile",
        "calibrated_input_profile_sha256": input_profiles,
        "calibrated_style_classes": calibrated_styles,
    })
    state = CreativeWorkflow(
        tmp_path / f"reopened_{expected_reason}", clients=FakeClients(_answers()),
    ).run(bundle)
    assert state["assistant_review_required"] is True
    assert expected_reason in state["review_reopen_reasons"]


def test_logical_task_claim_blocks_budget_reset_by_new_directory(tmp_path):
    bundle = _bundle(tmp_path)
    registry = tmp_path / "task_registry"
    first = tmp_path / "first"
    task_id = claim_logical_task(bundle, "停车场冲突", first, registry=registry)
    assert claim_logical_task(bundle, "停车场冲突", first, registry=registry) == task_id
    receipt = json.loads((registry / f"{task_id}.json").read_text(encoding="utf-8"))
    assert receipt["budget"]["policy_version"] == "v5_20261001"
    assert receipt["budget"]["max_revisions"] == 5
    assert receipt["budget"]["max_contract_repairs"] == 8
    with pytest.raises(RuntimeError, match="不能改变调用、用量或返修预算"):
        claim_logical_task(bundle, "停车场冲突", first, registry=registry, max_calls=40)
    with pytest.raises(RuntimeError, match="不能改变调用、用量或返修预算"):
        claim_logical_task(bundle, "停车场冲突", first, registry=registry,
                           budget_policy_version="v1_20260922")
    with pytest.raises(RuntimeError, match="不能改变调用、用量或返修预算"):
        claim_logical_task(bundle, "停车场冲突", first, registry=registry,
                           budget_policy_version="v2_20260922", max_contract_repairs=2)
    with pytest.raises(RuntimeError, match="已有逻辑任务"):
        claim_logical_task(bundle, "停车场冲突", tmp_path / "second", registry=registry)
    copied = tmp_path / "copied_novel.txt"
    copied.write_text(SOURCE, encoding="utf-8")
    retitled = load_materials(source_driver="novel", title="另一个标题", novel_path=copied)
    with pytest.raises(RuntimeError, match="已有逻辑任务"):
        claim_logical_task(retitled, "停车场冲突", tmp_path / "second", registry=registry)
    assert claim_logical_task(bundle, "另一段高光", tmp_path / "second", registry=registry) != task_id


def test_uninitialized_launch_claim_can_be_reclaimed_without_losing_receipt(tmp_path):
    bundle = _bundle(tmp_path)
    registry = tmp_path / "task_registry"
    failed = tmp_path / "failed"
    failed.mkdir()
    launch_error = {
        "schema": "creative_launch_error/v1", "status": "needs_attention",
        "error": "启动目录冲突", "automatic_media_submit": False,
    }
    (failed / "LAUNCH_ERROR.json").write_text(
        json.dumps(launch_error, ensure_ascii=False), encoding="utf-8",
    )
    task_id = claim_logical_task(bundle, "宿舍发票", failed, registry=registry)
    resumed = tmp_path / "new"
    assert claim_logical_task(bundle, "宿舍发票", resumed, registry=registry) == task_id
    receipt = json.loads((registry / f"{task_id}.json").read_text(encoding="utf-8"))
    assert receipt["run_dir"] == str(resumed.resolve())
    assert receipt["reclaimed_after_uninitialized_launch"] is True
    assert receipt["prior_uninitialized_claims"][0]["run_dir"] == str(failed.resolve())
    assert receipt["prior_uninitialized_claims"][0]["launch_error"] == launch_error


def test_dirty_new_run_directory_is_rejected_before_claim(tmp_path):
    path = tmp_path / "dirty"
    path.mkdir()
    (path / "LAUNCH_ERROR.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="不能登记逻辑任务"):
        validate_run_dir_before_claim(path)
    resumable = tmp_path / "resumable"
    resumable.mkdir()
    (resumable / "state.json").write_text("{}", encoding="utf-8")
    validate_run_dir_before_claim(resumable)


def test_rejected_candidate_cannot_count_clean_first_draft(tmp_path):
    answers = _answers()
    answers[0]["candidates"].append(dict(answers[0]["candidates"][0], id="C03"))
    answers[0]["candidates"].append(dict(
        answers[0]["candidates"][0], id="C02", end_quote="虚构的结尾句。"
    ))
    run_dir = tmp_path / "sample"
    CreativeWorkflow(run_dir, clients=FakeClients(answers)).run(_bundle(tmp_path))
    evidence = tmp_path / "review.md"
    evidence.write_text("人物归属准确、起止引文核对完成。动机从误会到解释成立；"
                        "情绪高光包含迟疑、停顿与放松。分镜所选事件连续。" * 3,
                        encoding="utf-8")
    review = record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)
    assert review["rejected_candidates"] == 1
    assert review["first_draft_no_major"] is False


def test_incomplete_draft_cannot_be_reviewed_as_passed(tmp_path):
    run_dir = tmp_path / "unfinished"
    state = CreativeWorkflow(run_dir, clients=FakeClients(_answers()[:-1]), max_calls=7)
    with pytest.raises(StopIteration):
        state.run(_bundle(tmp_path))
    evidence = tmp_path / "review.md"
    evidence.write_text("质量分析" * 100, encoding="utf-8")
    with pytest.raises(ValueError, match="没有完整文本产物"):
        record_review(run_dir, category="campus_novel", outcome="passed", evidence_file=evidence)


def test_insufficient_text_budget_stops_before_spending_or_skipping_review(tmp_path):
    clients = FakeClients(_answers())
    run_dir = tmp_path / "limited"
    with pytest.raises(RuntimeError, match="token 预算不足"):
        CreativeWorkflow(run_dir, clients=clients, max_total_tokens=10000).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 0
    assert state["text_pass_sequence"] == 0
    assert clients.calls == []


def test_oversized_source_never_silently_truncates(tmp_path):
    source = tmp_path / "long_novel.txt"
    source.write_text("第一章 起因。\n" + "完整情节句。\n" * 900, encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="长正文", novel_path=source)
    clients = FakeClients([])
    with pytest.raises(RuntimeError, match="分层阅读.*预算不足"):
        CreativeWorkflow(tmp_path / "long_run", clients=clients, max_calls=5,
                         direct_context_chars=1000).run(bundle)
    assert clients.calls == []


def test_hierarchical_source_reads_all_chunks_then_compiles_selected_raw_excerpt(tmp_path):
    source = tmp_path / "long_novel.txt"
    source.write_text(SOURCE + "\n" + "".join(f"第{i:04}字" for i in range(650)), encoding="utf-8")
    bundle = load_materials(source_driver="novel", title="长材料", novel_path=source)

    class SummaryClients(FakeClients):
        def call(self, role, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            if "source_chunk" in payload:
                self.calls.append((role, messages))
                chunk = payload["source_chunk"]
                answer = {"summary": "本块已阅读", "characters": [], "limits": [],
                          "events": [{"event": "连续原文", "cause": "来源", "consequence": "进入后文",
                                      "start_quote": chunk[:24], "end_quote": chunk[-24:]}]}
                return RoleResult(json.dumps(answer, ensure_ascii=False),
                                  {"role": role, "total_tokens": 1})
            return super().call(role, messages, **kwargs)

    clients = SummaryClients(_answers())
    run_dir = tmp_path / "run"
    state = CreativeWorkflow(
        run_dir, clients=clients, direct_context_chars=3000, max_calls=12
    ).run(bundle)
    assert state["status"] == "media_handoff_pending_capability"
    assert state["context_strategy"]["mode"] == "hierarchical"
    assert state["context_strategy"]["source_chunks"] >= 2
    assert len(list(run_dir.glob("source_summary__*.json"))) == state["context_strategy"]["source_chunks"]
    context_receipt = json.loads(
        (run_dir / "CONTEXT_STRATEGY.json").read_text(encoding="utf-8")
    )
    assert context_receipt["source_delivery"] == (
        "all_source_chunks_summarized_then_selected_raw_excerpt_reloaded"
    )
    assert context_receipt["not_sent_verbatim_to_initial_analysis"][0]["material"] == (
        "story_source"
    )
    assert context_receipt["final_payload_sha256"] == state["context_strategy"][
        "sent_payload_sha256"
    ]
    excerpt = json.loads((run_dir / "SELECTED_SOURCE.json").read_text(encoding="utf-8"))
    assert excerpt["text"] == SOURCE


def test_quote_repair_uses_nearby_raw_source_not_entire_book():
    source = "前文。\n" + "无关章节。\n" * 100 + "没有为什么，我不喜欢无缘无故用别人钱。\n结尾。"
    output = {"candidates": [{"start_quote": "林夏不喜欢无缘无故用别人钱。",
                               "end_quote": "结尾。"}]}
    evidence = _repair_evidence({"story_source": source}, output, "引文不在原文")
    assert "没有为什么，我不喜欢无缘无故用别人钱。" in str(evidence["source_evidence"])
    assert len(str(evidence)) < len(source)


def test_readable_screenplay_cannot_reorder_source_dialogue():
    source = "甲说：「第一句。」乙回答：「第二句。」"
    script = _answers()[2]
    script["beats"][0]["dialogue"] = [
        {"speaker": "甲", "text": "第一句。"},
        {"speaker": "乙", "text": "第二句。"},
    ]
    script["screenplay_markdown"] = "乙：第二句。甲：第一句。"
    with pytest.raises(CreativeContractError, match="可读剧本"):
        validate_script(script, "C01", source, "novel")


def test_unlisted_voiceover_cannot_sneak_into_readable_script():
    script = _answers()[2]
    script["screenplay_markdown"] += "\n**（甲画外心声）**：原文没有的内心台词。"
    with pytest.raises(CreativeContractError, match="画外心声"):
        validate_script(script, "C01", SOURCE, "novel")


def test_english_narrator_label_may_quote_continuous_source_narration():
    source = "Anne sat down. “You will do well,” Matthew said."
    script = deepcopy(_answers()[2])
    script["beats"][0]["dialogue"] = [
        {"speaker": "Narrator", "text": "Anne sat down."},
    ]
    script["beats"][1]["dialogue"] = [
        {"speaker": "Matthew", "text": "You will do well,"},
    ]
    script["screenplay_markdown"] = compile_beat_screenplay(script)

    validate_script(script, "C01", source, "novel")
    assert _invalid_novel_dialogue_paths(script, source) == []


def test_missing_director_event_lock_is_restored_from_immutable_script_event():
    _, _, script, shots, _ = _answers()
    shot = deepcopy(shots["shots"][0])
    shot.pop("event_lock")
    patch = {"replace_beats": [{"beat_id": "B01", "shots": [shot]}]}
    result = _project_director_beat_event_locks(patch, script, ["B01"])
    assert result is not None
    projected, changes = result
    assert projected["replace_beats"][0]["shots"][0]["event_lock"] == script["beats"][0]["event"]
    assert changes[0]["from"] == "<missing>"

def test_director_repair_patch_cannot_rewrite_script_or_insert_shots():
    shots = _answers()[3]
    corrected = _apply_repair_patches(shots, {
        "patches": [{"path": ["shots", 0, "dialogue_lock"],
                     "value": [{"speaker": "甲", "text": "起因句。"}]}],
    })
    assert corrected["shots"][0]["dialogue_lock"] == [{"speaker": "甲", "text": "起因句。"}]
    assert shots["shots"][0]["dialogue_lock"] == []
    with pytest.raises(CreativeContractError, match="允许修订范围"):
        _apply_repair_patches(shots, {
            "patches": [{"path": ["script", "title"], "value": "新故事"}],
        })
    with pytest.raises(CreativeContractError, match="已有字段"):
        _apply_repair_patches(shots, {
            "patches": [{"path": ["shots", 0, "new_event"], "value": "新剧情"}],
        })


def test_director_repair_evidence_targets_all_stale_event_locks_without_full_draft():
    _, _, script, shots, _ = _answers()
    script["beats"][1]["event"] = "解释后和解"
    prior = deepcopy(shots["shots"][0])
    stale = deepcopy(shots["shots"][1])
    shots["shots"] = []
    for index in range(1, 10):
        extra = deepcopy(prior)
        extra["id"] = f"SH{index:02}"
        shots["shots"].append(extra)
    for index in range(10, 13):
        extra = deepcopy(stale)
        extra["id"] = f"SH{index:02}"
        shots["shots"].append(extra)
    payload = {"script": script}
    evidence = _director_repair_evidence(
        payload, shots, "SH10 未绑定编剧定稿事件",
    )
    assert "original" not in evidence
    assert evidence["original_sha256"]
    assert evidence["beat_locks"]["B02"]["event"] == "解释后和解"
    assert [row["index"] for row in evidence["invalid_event_locks"]] == [9, 10, 11]
    assert evidence["affected_shots"][0]["index"] == 9
    assert evidence["affected_shots"][-1]["index"] == 11
    assert all(row["shot"]["beat_id"] in ("B01", "B02") for row in evidence["affected_shots"])


def test_contract_repair_uses_shared_revision_cap(tmp_path):
    answers = _answers()
    answers[0]["candidates"][0]["start_quote"] = "不存在的原文句子"
    clients = FakeClients(answers)
    run_dir = tmp_path / "capped"
    with pytest.raises(CreativeContractError, match="共享实质返修轮数已满"):
        CreativeWorkflow(
            run_dir, clients=clients, max_revisions=0, budget_policy_version="v1_20260922",
        ).run(_bundle(tmp_path))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["calls_started"] == 1
    assert state["revision_rounds"] == 0


def test_traditional_source_quote_recovers_original_punctuation_only():
    source = "道：「那一個有本事的，鑽進去尋個源頭出來，不傷身體者，我等即拜他為王。」"
    canonical, index = _canonical_source_quote(
        source, "那一個有本事的,鑽進去尋個源頭出來,不傷身體者,我等即拜他為王。", "quote"
    )
    assert index == source.index("那一個")
    assert canonical == "那一個有本事的，鑽進去尋個源頭出來，不傷身體者，我等即拜他為王。」"
    with pytest.raises(CreativeContractError, match="唯一定位"):
        _canonical_source_quote(source, "那一個人沒有本事", "quote")


def test_continuous_movement_focus_rejects_physical_foot_stop():
    script = deepcopy(_answers()[2])
    script["beats"][0]["during"] = "林夏脚步微顿一拍，目光仍望向前方。"
    with pytest.raises(CreativeContractError, match="持续行走改成身体停步"):
        validate_creative_focus_action_constraints(
            script, "林夏全程缓慢前行，不停止。"
        )


def test_continuous_movement_focus_allows_emotional_pause_while_walking():
    script = deepcopy(_answers()[2])
    script["beats"][0]["during"] = (
        "林夏眉头轻动，认真想了一瞬，脚步保持均匀。"
    )
    validate_creative_focus_action_constraints(
        script, "林夏全程缓慢前行，不停止。"
    )


def test_shots_reject_physical_stop_against_character_movement_lock():
    _, brief, script, shots, _ = _answers()
    shots["style"]["character_lock"] += "；甲全程前行，脚步不停。"
    shots["shots"][0]["visible_performance"] = "甲停住脚步，抬眼看向乙。"
    with pytest.raises(CreativeContractError, match="持续行走改成身体停步"):
        validate_shots(shots, brief, script)


def test_redundant_action_dialogue_quote_projection_is_narrow_and_auditable():
    script = deepcopy(_answers()[2])
    script["beats"][1]["dialogue"] = [
        {"speaker": "林夏", "text": "真的，很漂亮，你放心，我丑的也不会要的。"}
    ]
    script["beats"][1]["during"] = "林夏语气平稳，尾音“放心”带着安抚。"
    script["beats"][1]["after"] = "林夏在“要的”落下后轻轻一笑。"

    projection = _project_redundant_action_dialogue_quotes(script)

    assert projection is not None
    corrected, changes = projection
    assert corrected["beats"][1]["during"] == "林夏语气平稳，尾音带着安抚。"
    assert corrected["beats"][1]["after"] == "林夏在回答落音后轻轻一笑。"
    assert [row["path"] for row in changes] == [
        ["beats", 1, "during"], ["beats", 1, "after"],
    ]


def test_redundant_action_dialogue_quote_projection_refuses_unsafe_form():
    script = deepcopy(_answers()[2])
    script["beats"][1]["dialogue"] = [{"speaker": "甲", "text": "你放心。"}]
    script["beats"][1]["during"] = "甲说出“放心”，随后抬眼。"
    assert _project_redundant_action_dialogue_quotes(script) is None


def test_body_gaze_rule_does_not_cross_sentence_into_unrelated_lips():
    script = deepcopy(_answers()[2])
    script["beats"][0]["during"] = "林夏目光落到手机，随后嘴唇微张准备回应。"
    script["beats"][0]["dialogue"] = [{"speaker": "林夏", "text": "好。"}]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", "林夏看着手机接听电话，说：「好。」", "novel")


def test_body_gaze_rule_does_not_treat_lips_action_after_object_as_gaze_target():
    script = deepcopy(_answers()[2])
    script["beats"][0]["during"] = "陈默视线停在律师函上嘴唇微抿。"
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", "陈默收到律师函。", "reference_video")


def test_whole_film_duration_issue_routes_all_beats():
    script = deepcopy(_answers()[2])
    script["beats"].append({
        "id": "B03", "duration_seconds": 8, "event": "收束", "trigger": "前拍完成",
        "before": "甲站定。", "during": "甲抬眼。", "after": "甲离开。", "dialogue": [],
    })
    issue = {
        "owner": "writer", "location": "全片 duration_seconds 与 beat 总时长",
        "evidence": "总时长超出上限", "impact": "整片过长",
        "proposal": "压缩总时长至范围内", "severity": "major",
    }
    assert _issue_beat_ids(script, [issue]) == ["B01", "B02", "B03"]


def test_source_pre_dialogue_laugh_must_be_in_before():
    source = "她嘴里发出一声轻笑：“吻了我还想跑？你跑得掉吗？”"
    script = deepcopy(_answers()[2])
    script["beats"][0]["before"] = "她望着前方空路，唇角逐渐扬起。"
    script["beats"][0]["during"] = "她发出一声轻笑，目光保持笃定。"
    script["beats"][0]["dialogue"] = [
        {"speaker": "她", "text": "吻了我还想跑？你跑得掉吗？"}
    ]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    with pytest.raises(CreativeContractError, match="先轻笑再说话必须把轻笑写入 before"):
        validate_script(script, "C01", source, "novel")


def test_source_pre_dialogue_laugh_passes_when_before_contains_it():
    source = "她嘴里发出一声轻笑：“吻了我还想跑？你跑得掉吗？”"
    script = deepcopy(_answers()[2])
    script["beats"][0]["before"] = "她望着前方空路，发出一声轻笑。"
    script["beats"][0]["during"] = "她说完后目光保持笃定。"
    script["beats"][0]["dialogue"] = [
        {"speaker": "她", "text": "吻了我还想跑？你跑得掉吗？"}
    ]
    script["screenplay_markdown"] = compile_beat_screenplay(script)
    validate_script(script, "C01", source, "novel")


def test_explicit_post_dialogue_reaction_window_rejects_long_dedicated_hold():
    _, brief, script, shots, _ = _answers()
    script["beats"][1]["duration_seconds"] = 11
    script["duration_seconds"] = script["beats"][0]["duration_seconds"] + 11
    shots["shots"][1]["duration_seconds"] = 6
    script["beats"][1]["dialogue"] = [{"speaker": "乙", "text": "回答。"}]
    shots["shots"][1]["dialogue_lock"] = [{"speaker": "乙", "text": "回答。"}]
    hold = deepcopy(shots["shots"][1])
    hold["id"] = "SH03"
    hold["duration_seconds"] = 5
    hold["dialogue_lock"] = []
    hold["start_state"] = shots["shots"][1]["end_state"]
    hold["end_state"] = hold["start_state"]
    hold["continuity_mode"] = "raw_tail_continuation"
    shots["shots"].append(hold)
    focus = "B02用十到十二秒完整回答，落音后保留一到两秒克制目光。"
    with pytest.raises(CreativeContractError, match="超过 creative_focus 明确落音后窗口"):
        validate_shots(shots, brief, script, "", focus)


def test_explicit_post_dialogue_reaction_window_allows_two_second_hold():
    _, brief, script, shots, _ = _answers()
    script["beats"][1]["duration_seconds"] = 8
    script["duration_seconds"] = script["beats"][0]["duration_seconds"] + 8
    shots["shots"][1]["duration_seconds"] = 6
    script["beats"][1]["dialogue"] = [{"speaker": "乙", "text": "回答。"}]
    shots["shots"][1]["dialogue_lock"] = [{"speaker": "乙", "text": "回答。"}]
    hold = deepcopy(shots["shots"][1])
    hold["id"] = "SH03"
    hold["duration_seconds"] = 2
    hold["dialogue_lock"] = []
    hold["start_state"] = shots["shots"][1]["end_state"]
    hold["end_state"] = hold["start_state"]
    hold["continuity_mode"] = "raw_tail_continuation"
    shots["shots"].append(hold)
    focus = "B02用八秒完整回答，落音后保留一到两秒克制目光。"
    validate_shots(shots, brief, script, "", focus)




