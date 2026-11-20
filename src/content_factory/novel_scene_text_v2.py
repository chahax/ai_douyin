"""Full scene/event text continuation of a stopped, known-billed novel task.

Independent protocol and receipts; the parent task, source boundary and budgets
are inherited unchanged. No legacy screenplay projection or media dispatch.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from .account_novel_creation_v1 import _code_bindings, _digest, _provider_protocol, _read, _write
from .creative_workflow import _hash
from .creative_workflow_inputs import file_binding, verify_binding
from .creative_workflow_roles import CreativeRoleClients
from .creative_workflow_roles import _response_model_matches
from .creative_workflow_contract import CreativeContractError, parse_json_object

ROOT = Path(__file__).resolve().parents[2]
VERSION = "novel_scene_text/v2"
SCRIPT_SCHEMA = "novel_scene_screenplay/v2"
REVIEW_SCHEMA = "novel_scene_full_review/v2"


def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": required or list(properties), "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1}
STATE = obj({"character": TEXT, "action": TEXT, "expression": TEXT, "gaze": TEXT})
EVENT = obj({"id": TEXT, "kind": {"type": "string", "enum": ["action", "dialogue", "reaction", "voiceover"]},
             "actor": TEXT, "text": TEXT, "duration_seconds": {"type": "integer", "minimum": 1},
             "performers": {"type": "array", "items": STATE, "minItems": 1},
             "other_present_state": TEXT, "source_quote": TEXT})
SCENE = obj({"id": TEXT, "timeline": TEXT, "location": TEXT, "time": TEXT,
             "present": {"type": "array", "items": STATE, "minItems": 1},
             "start_state": TEXT, "end_state": TEXT,
             "events": {"type": "array", "items": EVENT, "minItems": 2}})
WRITER_SCHEMA = obj({"schema": {"const": SCRIPT_SCHEMA}, "title": TEXT, "candidate_id": TEXT,
    "source_sha256": TEXT, "duration_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
    "world": obj({"era": TEXT, "daily_context": TEXT, "space_and_prior_events": TEXT, "relationships": TEXT}),
    "characters": {"type": "array", "minItems": 1, "items": obj({"name": TEXT, "situation": TEXT, "goal": TEXT, "source_quote": TEXT})},
    "scenes": {"type": "array", "items": SCENE, "minItems": 1},
    "screenplay_markdown": {"type": "string", "minLength": 200}})
REVIEW_OUTPUT_SCHEMA = obj({"schema": {"const": REVIEW_SCHEMA}, "script_sha256": TEXT, "source_sha256": TEXT,
    "candidate_id": TEXT, "whole_text_reviewed": {"const": True}, "summary": TEXT,
    "issues": {"type": "array", "items": obj({"severity": {"type": "string", "enum": ["blocking", "major", "minor"]},
        "location": TEXT, "evidence": TEXT, "impact": TEXT, "proposal": TEXT})}})

WRITER_PROMPT = """你是MiniMax小说编剧。本次对已知失败剧本重新创作完整场景事件稿，调用submit_creative_json提交完整原生JSON。
唯一事实来源是selected_source.text。世界、人物关系、前情和对白都不得越过该片段，未知明确写“原文未交代”。
来源起点锁定，不能补回片段之前或之后的对白；不要因为参考旧失败原因而补写来源外情节。
按schema逐场交代世界/人物处境目标、时间线/地点/时间、所有在场人物动作神情视线、段首尾状态。
events严格按真实播放先后排列action/dialogue/reaction/voiceover；重要对白前中后的刺激与反应必须在事件序列真实演出。
动作对白可以自然交叠，不能用固定before/during/after槽、堆动作、长时间空等或摘要代替表演。
dialogue是原文直接对白，text逐字保留，不把间接叙述改作人物新台词；心理活动必要时用voiceover，不能冒充当面说话。
每事件source_quote是selected_source.text内的原文连续引证，明确该动作/对白/人物依据；不拼引文，不要求引文唯一。
performers写实际参与者的动作神情视线，other_present_state明确其余在场者持续反应；不能漏掉在场者或让未到场角色突然出现。
每场events合计秒数，总和等于duration_seconds；参考45—180秒可随完整表达浮动，最多600秒。
screenplay_markdown必须是你自主写出的完整可读剧本，不只JSON摘要：先写世界框架，再逐场ID/时间地点/在场人物/段首状态，
逐字包含world各字段、角色处境目标、所有events.text、present和performers的action/expression/gaze及other_present_state、段尾状态；每句对白标说话人。不是程序补写或提纲。
若有previous_script/issues，请提交完整新稿，允许重排整篇事件和场景，不返回补丁；保留原source/candidate身份。
不能声称用户采用、内容人工批准、声音口型或视频已经通过。"""
REVIEW_PROMPT = """你是DeepSeek独立全文审查员，只审查不代写。阅读完整selected_source与完整script（含Markdown），输出review_schema规定JSON。
核对世界/关系/前情仅来自选段，不能恢复选段起点之前的内容；直接台词逐字源自原文，间接叙述不能冒充直接对白。
逐场核对时间地点、在场人物、动作/视线/神情、顺序事件、刺激反应先后、首尾状态、秒数及可表演性，全文Markdown不得缺演。
尤其核对每句话真实说话人，不能在亲属或相似角色之间误分台词；位置变化必须有可见推进，不能空间跳变。
不要从原文未提供的常识推定具体背景，不为收束而编新剧情；未知可明确写原文未交代。
每个问题必须是真实可定位错误，evidence直接引用script现有实词；正常省略和已有事件不重复报错。
严格回传actual_script_sha256/actual_source_sha256/candidate_id及whole_text_reviewed=true，不返回改写后的剧本。
无major/blocking也不代表用户采用或视频通过。"""


def _locks(parent, owner=None):
    for path in (parent / ".novel_trial_execution.lock", parent / "creative/.creative_execution.lock"):
        if path.exists() and not (path.name == ".novel_trial_execution.lock" and owner is not None
                and _read(path).get("schema") == "novel_scene_dispatch_takeover/v2"
                and _read(path).get("owner_run") == str(owner)):
            raise RuntimeError("原任务仍有执行锁，不能派发续行")


def _parent_snapshot(parent, *, owner=None):
    _locks(parent, owner=owner)
    binding, state = _read(parent / "BINDING.json"), _read(parent / "creative/state.json")
    if (_read(parent / "BINDING_ANCHOR.json")["sha256"] != _digest(binding)
            or state["status"] != "needs_attention" or state["logical_task_id"] != binding["logical_task_id"]):
        raise ValueError("原任务不是已冻结明确停止的同一逻辑故事")
    for item in [*binding["files"].values(), *binding.get("code_bindings", [])]:
        verify_binding(item)
    rows = []
    for path in sorted((parent / "creative").glob("NATIVE_RESPONSE_*.json")):
        record = _read(path)
        metadata = record.get("response_metadata", {})
        tokens = metadata.get("total_tokens")
        if type(tokens) is not int or tokens < 0 or metadata.get("finish_reason") not in ("stop", "tool_calls"):
            raise ValueError("原响应结束或用量不明，不能另派续行")
        native = record.get("response_payload") or {}
        if (native.get("usage", {}).get("total_tokens") != tokens
                or not native.get("choices") or native["choices"][0].get("finish_reason") != metadata["finish_reason"]):
            raise ValueError("原生响应与元数据用量/结束标记不一致")
        rows.append({"ordinal": record["call_ordinal"], "tokens": tokens, "binding": file_binding(path)})
    if ([row["ordinal"] for row in rows] != list(range(1, state["calls_started"] + 1))
            or sum(row["tokens"] for row in rows) != state["reported_tokens"]):
        raise ValueError("原始调用回执与旧账本不一致")
    selected = _read(parent / "creative/SELECTED_SOURCE.json")
    whole = (parent / "frozen/story_source.txt").read_text(encoding="utf-8-sig").strip()
    if (selected["text"] != whole[selected["start_character"]:selected["end_character"]]
            or not selected["text"].strip() or selected["source_sha256"] != _hash(whole)
            or selected["excerpt_sha256"] != _hash(selected["text"])):
        raise ValueError("旧选段与原正文边界不符")
    return binding, state, rows, selected


def prepare(parent_run, run_dir, *, continuation_registry=None, diagnostics=None):
    parent, run = Path(parent_run).resolve(), Path(run_dir).resolve()
    if (run / "BINDING.json").exists():
        bound, _, _ = verify(run)
        if bound["parent_run"] != str(parent):
            raise ValueError("恢复不能更换原故事")
        return inspect(run)
    if run.exists() and any(run.iterdir()):
        raise RuntimeError("续行目录已有文件，停止；不得覆盖旧回执")
    old_binding, old, old_rows, selected = _parent_snapshot(parent)
    if old_binding["provider_protocol"] != _provider_protocol():
        raise ValueError("不能静默更换原模型服务")
    budget = {key: old[key] for key in ("max_calls", "max_total_tokens", "max_revisions", "max_contract_repairs")}
    if budget != {"max_calls": 20, "max_total_tokens": 500000, "max_revisions": 2, "max_contract_repairs": 8}:
        raise ValueError("本轮续行必须承接原20次/500000/2/8范围")
    registry = Path(continuation_registry or (Path(old_binding["task_registry"]) / "_scene_continuations")).resolve()
    registry.mkdir(parents=True, exist_ok=True)
    claim_path = registry / (old["logical_task_id"] + ".json")
    claim = {"schema": VERSION, "logical_task_id": old["logical_task_id"], "parent_run": str(parent), "run_dir": str(run), "budget": budget}
    if claim_path.exists():
        if _read(claim_path) != claim:
            raise RuntimeError("同一故事已有事件续行，不得换目录重领额度")
    else:
        with claim_path.open("x", encoding="utf-8") as stream:
            json.dump(claim, stream, ensure_ascii=False, indent=2)
    takeover_path = parent / ".novel_trial_execution.lock"
    takeover = {"schema": "novel_scene_dispatch_takeover/v2", "owner_run": str(run),
                "logical_task_id": old["logical_task_id"], "actual_inflight": False,
                "reason": "本故事派发由独立事件续行承接；原9次账本冻结，不允许旧入口分叉消费"}
    with takeover_path.open("x", encoding="utf-8") as stream:
        json.dump(takeover, stream, ensure_ascii=False, indent=2)
    locked_snapshot = _parent_snapshot(parent, owner=run)
    if locked_snapshot != (old_binding, old, old_rows, selected):
        raise RuntimeError("接管前原调用账本或来源已变化，保留接管证据并停止，不沿用旧费用基线")
    run.mkdir(parents=True)
    old_files = [file_binding(path) for path in sorted(parent.rglob("*")) if path.is_file() and path.suffix in (".json", ".md", ".txt")]
    old_files += list(old_binding["files"].values())
    old_files += [row["binding"] for row in old_rows] + old_binding.get("code_bindings", [])
    for item in old_files:
        verify_binding(item)
    _write(run / "SELECTED_SOURCE.json", selected)
    _write(run / "PARENT_CONSUMPTION.json", {"calls": old["calls_started"], "reported_tokens": old["reported_tokens"], "responses": old_rows,
        "contract_repairs_used": old["contract_repairs_used"], "format_repairs_used": old["format_repairs_used"]})
    code = [*_code_bindings(), file_binding(Path(__file__)), file_binding(ROOT / "scripts/run_novel_scene_text_v2.py")]
    binding = {"schema": VERSION, "parent_run": str(parent), "run_dir": str(run), "logical_task_id": old["logical_task_id"],
        "budget": budget, "base_calls": old["calls_started"], "base_tokens": old["reported_tokens"],
        "base_revision_rounds": old["revision_rounds"], "base_contract_repairs": old["contract_repairs_used"],
        "base_format_repairs": old["format_repairs_used"], "provider_protocol": _provider_protocol(),
        "candidate_id": selected["candidate_id"], "source_sha256": _hash(selected["text"]),
        "old_files": old_files, "code_bindings": code, "claim": file_binding(claim_path),
        "takeover": file_binding(takeover_path),
        "files": [file_binding(run / name) for name in ("SELECTED_SOURCE.json", "PARENT_CONSUMPTION.json")],
        "writer_schema": WRITER_SCHEMA, "review_schema": REVIEW_OUTPUT_SCHEMA,
        "prior_diagnostics": diagnostics if diagnostics is not None else [old.get("last_error", "旧稿合同失败，重新提交完整事件稿")],
        "writer_prompt": WRITER_PROMPT, "review_prompt": REVIEW_PROMPT, "automatic_media_submit": False}
    _write(run / "BINDING_ANCHOR.json", {"sha256": _digest(binding)})
    _write(run / "BINDING.json", binding)
    _write(run / "state.json", {"schema": VERSION, "status": "prepared", "logical_task_id": old["logical_task_id"],
        "calls_started": old["calls_started"], "reported_tokens": old["reported_tokens"], "known_reported_tokens": old["reported_tokens"],
        "revision_rounds": old["revision_rounds"], "drafts_created": 0,
        "contract_repairs_used": old["contract_repairs_used"], "format_repairs_used": old["format_repairs_used"], "pending_call": None})
    return inspect(run)


def verify(run_dir, *, parent_lock_owner=None):
    run = Path(run_dir).resolve()
    binding, state = _read(run / "BINDING.json"), _read(run / "state.json")
    if (binding["schema"] != VERSION or binding["run_dir"] != str(run)
            or _read(run / "BINDING_ANCHOR.json")["sha256"] != _digest(binding)):
        raise ValueError("事件续行冻结身份变化")
    if binding["provider_protocol"] != _provider_protocol():
        raise ValueError("服务协议变化")
    if (state["logical_task_id"] != binding["logical_task_id"] or not 0 <= state["drafts_created"] <= 2
            or state["revision_rounds"] != binding["base_revision_rounds"] + state["drafts_created"]
            or state["contract_repairs_used"] != binding["base_contract_repairs"]
            or state["format_repairs_used"] != binding["base_format_repairs"]):
        raise ValueError("续行任务、内容返修或旧合同预算不能修改")
    try:
        verify_binding(binding["takeover"])
    except ValueError:
        raise RuntimeError("原任务派发接管门已变化，不接管或移除该锁") from None
    _locks(Path(binding["parent_run"]), owner=run)
    for item in [*binding["old_files"], *binding["code_bindings"], *binding["files"], binding["claim"]]:
        verify_binding(item)
    selected = _read(run / "SELECTED_SOURCE.json")
    if _hash(selected["text"]) != binding["source_sha256"]:
        raise ValueError("选段来源变化")
    records = sorted(run.glob("CALL_*.json"))
    known = binding["base_tokens"]
    for index, path in enumerate(records, binding["base_calls"] + 1):
        record = _read(path)
        metadata = record.get("response_metadata", {})
        tokens = metadata.get("total_tokens")
        if record["ordinal"] != index or record["status"] == "pending" or type(tokens) is not int or tokens < 0:
            raise RuntimeError("已有在途/结果或用量未知请求，保存原ID，不重新派发")
        known += tokens
    if (state["pending_call"] is not None or state["calls_started"] != binding["base_calls"] + len(records)
            or state["known_reported_tokens"] != known):
        raise RuntimeError("续行账本与原请求不一致或仍有在途请求")
    return binding, state, selected


def validate_script(value, binding, source):
    from jsonschema import Draft202012Validator
    Draft202012Validator(WRITER_SCHEMA).validate(value)
    if value["candidate_id"] != binding["candidate_id"] or value["source_sha256"] != binding["source_sha256"]:
        raise ValueError("完整稿更换已选来源")
    names = [row["name"] for row in value["characters"]]
    if len(names) != len(set(names)):
        raise ValueError("角色重复")
    for row in value["characters"]:
        if row["name"] not in source or row["source_quote"] not in source:
            raise ValueError("角色或角色证据不在原文")
        if any(row[key] not in value["screenplay_markdown"] for key in ("name", "situation", "goal")):
            raise ValueError("可读剧本缺人物处境或目标")
    total, identifiers, kinds = 0, [], []
    markdown = value["screenplay_markdown"]
    for text in value["world"].values():
        if text not in markdown:
            raise ValueError("可读剧本缺世界框架正文")
    for scene in value["scenes"]:
        identifiers.append(scene["id"])
        present = [row["character"] for row in scene["present"]]
        if len(present) != len(set(present)) or any(name not in names for name in present):
            raise ValueError("在场角色未完整登记或重复")
        if any(scene[key] not in markdown for key in ("id", "time", "location", "timeline", "start_state", "end_state")):
            raise ValueError("可读剧本缺场景时间地点或首尾状态")
        if any(row[key] not in markdown for row in scene["present"] for key in ("character", "action", "expression", "gaze")):
            raise ValueError("可读剧本漏掉在场人物动作、表情或视线")
        for event in scene["events"]:
            identifiers.append(event["id"])
            kinds.append(event["kind"])
            total += event["duration_seconds"]
            if event["source_quote"] not in source or event["text"] not in markdown:
                raise ValueError("事件证据越界或可读剧本未完整演出")
            if (event["other_present_state"] not in markdown
                    or any(row[key] not in markdown for row in event["performers"] for key in ("character", "action", "expression", "gaze"))):
                raise ValueError("可读剧本漏掉事件演员动作、表情、视线或他人反应")
            performers = [row["character"] for row in event["performers"]]
            if len(performers) != len(set(performers)) or any(name not in present for name in performers):
                raise ValueError("事件人物不在当前场景")
            if event["actor"] not in present and not (event["kind"] == "voiceover" and event["actor"] == "旁白"):
                raise ValueError("事件主体未在场或旁白类型错误")
            if event["kind"] in ("dialogue", "voiceover") and event["text"] not in source:
                raise ValueError("对白/旁白不在锁定原文")
    if len(identifiers) != len(set(identifiers)) or total != value["duration_seconds"]:
        raise ValueError("事件/场景ID重复或总时长不符")
    if "reaction" not in kinds or "action" not in kinds or not any(kind in kinds for kind in ("dialogue", "voiceover")):
        raise ValueError("完整稿缺动作、对白或实际反应事件")


def _dispatch(run, binding, state, role, payload, clients, *, stage_key, parent_lock_owner=None):
    verify(run, parent_lock_owner=parent_lock_owner)
    for path in sorted(run.glob("CALL_*.json")):
        prior = _read(path)
        if prior.get("stage_key") == stage_key:
            if prior["status"] != "response_received":
                raise RuntimeError("原请求尚未明确完成，不能重派")
            return parse_json_object(prior["response_text"]), file_binding(path)
    if state["calls_started"] >= binding["budget"]["max_calls"]:
        raise RuntimeError("累计调用预算已满")
    prompt = binding["writer_prompt"] if role == "writer" else binding["review_prompt"]
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    max_tokens = 20000 if role == "writer" else 12000
    estimated = (len(json.dumps({"messages": messages,
        "structured_schema": binding["writer_schema"] if role == "writer" else None}, ensure_ascii=False).encode("utf-8"))
        + max_tokens + 4096)
    if state["known_reported_tokens"] + estimated > binding["budget"]["max_total_tokens"]:
        raise RuntimeError("累计token预算不足，未派发")
    ordinal = state["calls_started"] + 1
    path = run / f"CALL_{ordinal:03}.json"
    record = {"schema": VERSION, "ordinal": ordinal, "role": role, "stage_key": stage_key, "status": "pending", "request": messages,
              "parameters": {"max_tokens": max_tokens, "temperature": 0.4 if role == "writer" else 0.1,
                             "thinking": "disabled", "structured_schema": binding["writer_schema"] if role == "writer" else None}}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    state.update(calls_started=ordinal, pending_call=ordinal, status="running")
    _write(run / "state.json", state)
    try:
        result = clients.call(role, messages, **record["parameters"])
        record.update(response_text=result.text, response_metadata=result.metadata, response_payload=result.response_payload)
    except Exception as exc:
        record.update(status="uncertain", error=str(exc), response_text=getattr(exc, "response_text", None),
            response_metadata=getattr(exc, "response_metadata", {}), response_payload=getattr(exc, "response_payload", None))
    tokens = record.get("response_metadata", {}).get("total_tokens")
    reason = record.get("response_metadata", {}).get("finish_reason")
    native = record.get("response_payload") if isinstance(record.get("response_payload"), dict) else {}
    native_usage = native.get("usage") if isinstance(native.get("usage"), dict) else {}
    native_tokens = native_usage.get("total_tokens")
    native_choices = native.get("choices") if isinstance(native.get("choices"), list) else []
    native_first = native_choices[0] if native_choices and isinstance(native_choices[0], dict) else {}
    native_reason = native_first.get("finish_reason")
    known = type(tokens) is int and tokens >= 0 and type(native_tokens) is int and native_tokens == tokens
    if known:
        state["known_reported_tokens"] += tokens
    state["reported_tokens"] = state["known_reported_tokens"] if known else None
    state["pending_call"] = None if known and reason in ("stop", "tool_calls") else ordinal
    failure = (not known or reason not in ("stop", "tool_calls") or record.get("error")
               or native_reason != reason
               or record.get("response_metadata", {}).get("response_fault_code")
               or (role == "writer" and record.get("response_metadata", {}).get("output_mode") != "tool_call"))
    record["status"] = "response_rejected" if failure else "response_received"
    expected_model = binding["provider_protocol"]["roles"][role]["model"]
    metadata_model = record.get("response_metadata", {}).get("response_model", "")
    native_model = native.get("model", "")
    if (not isinstance(metadata_model, str) or not isinstance(native_model, str)
            or not _response_model_matches(role, expected_model, metadata_model)
            or not _response_model_matches(role, expected_model, native_model) or metadata_model != native_model):
        failure = True
        record["status"] = "response_rejected"
    _write(path, record)
    if failure:
        state.update(status="needs_attention", halt_reason="响应/结束标记/用量或工具合同不可继续；原请求不重派")
        _write(run / "state.json", state)
        raise RuntimeError(state["halt_reason"])
    _write(run / "state.json", state)
    value = parse_json_object(record["response_text"])
    return value, file_binding(path)


def execute(run_dir, *, clients=None):
    run = Path(run_dir).resolve()
    lock = run / ".scene_execution.lock"
    owner = uuid.uuid4().hex
    with lock.open("x", encoding="utf-8") as stream:
        json.dump({"schema": VERSION, "automatic_unlock": False, "owner": owner}, stream)
    try:
        binding, state, selected = verify(run, parent_lock_owner=owner)
        if state["status"] in ("machine_text_complete", "needs_attention", "content_revision_exhausted"):
            return inspect(run, parent_lock_owner=owner)
        clients = clients or CreativeRoleClients()
        available_drafts = max(0, min(2, binding["budget"]["max_revisions"] - binding["base_revision_rounds"]))
        for number in range(1, available_drafts + 1):
            payload = {"selected_source": selected, "actual_source_sha256": binding["source_sha256"],
                       "candidate_id": binding["candidate_id"], "output_schema": binding["writer_schema"]}
            payload["prior_diagnostics"] = binding["prior_diagnostics"]
            if number > 1:
                if (run / "DRAFT_01.json").exists():
                    payload["previous_script"] = _read(run / "DRAFT_01.json")
                failure_path = run / "CONTRACT_FAILURE_01.json"
                payload["issues"] = (_read(failure_path)["issues"] if failure_path.exists() else _read(run / "REVIEW_01.json")["issues"])
                if failure_path.exists():
                    payload["previous_native_response"] = _read(failure_path)["native_response"]
            try:
                script, script_receipt = _dispatch(run, binding, state, "writer", payload, clients,
                    stage_key=f"writer_{number:02}", parent_lock_owner=owner)
            except CreativeContractError as exc:
                # Unknown/transport/tool faults are never content-repaired.
                latest = _read(run / f"CALL_{state['calls_started']:03}.json") if state["calls_started"] > binding["base_calls"] else {}
                if latest.get("status") != "response_received":
                    raise
                script, script_receipt = None, file_binding(run / f"CALL_{state['calls_started']:03}.json")
                parse_error = str(exc)
            state.update(drafts_created=number, revision_rounds=binding["base_revision_rounds"] + number)
            if script is not None:
                _write(run / f"DRAFT_{number:02}.json", script)
            _write(run / "state.json", state)
            try:
                if script is None:
                    raise ValueError(parse_error)
                validate_script(script, binding, selected["text"])
            except Exception as exc:
                raw = _read(Path(script_receipt["path"]))
                _write(run / f"CONTRACT_FAILURE_{number:02}.json", {"schema": VERSION,
                    "issues": [{"severity": "major", "location": "complete_script", "evidence": str(exc),
                                "impact": "完整事件稿合同失败", "proposal": "提交完整新原生稿，不返回补丁"}],
                    "native_response": raw["response_text"], "response_receipt": script_receipt})
                state.update(status="needs_full_revision" if number < available_drafts else "content_revision_exhausted",
                             halt_reason="完整事件稿合同失败：" + str(exc))
                _write(run / "state.json", state)
                if number < available_drafts:
                    continue
                return inspect(run, parent_lock_owner=owner)
            review_payload = {"selected_source": selected, "script": script, "actual_script_sha256": _hash(script),
                              "actual_source_sha256": binding["source_sha256"], "candidate_id": binding["candidate_id"],
                              "review_schema": binding["review_schema"]}
            review, review_receipt = _dispatch(run, binding, state, "director", review_payload, clients,
                stage_key=f"review_{number:02}", parent_lock_owner=owner)
            _write(run / f"REVIEW_{number:02}.json", review)
            from jsonschema import Draft202012Validator
            Draft202012Validator(REVIEW_OUTPUT_SCHEMA).validate(review)
            if (review["script_sha256"] != _hash(script) or review["source_sha256"] != binding["source_sha256"]
                    or review["candidate_id"] != binding["candidate_id"]):
                raise ValueError("全文审查回传的同稿身份不符")
            if any(issue["evidence"] not in json.dumps(script, ensure_ascii=False) for issue in review["issues"]):
                raise ValueError("全文审查问题证据不在当前完整稿")
            major = [row for row in review["issues"] if row["severity"] in ("blocking", "major")]
            if not major:
                _write(run / "SCREENPLAY.json", script)
                (run / "SCREENPLAY.md").write_bytes(script["screenplay_markdown"].encode("utf-8"))
                _write(run / "FULL_TEXT_REVIEW.json", review)
                manifest = {"schema": VERSION, "logical_task_id": binding["logical_task_id"],
                    "source_sha256": binding["source_sha256"], "script_sha256": _hash(script), "review_sha256": _hash(review),
                    "files": [file_binding(run / name) for name in ("SCREENPLAY.json", "SCREENPLAY.md", "FULL_TEXT_REVIEW.json")],
                    "script_receipt": script_receipt, "review_receipt": review_receipt, "automatic_media_submit": False}
                _write(run / "OUTPUT_MANIFEST.json", manifest)
                state.update(status="machine_text_complete", output_manifest_sha256=_hash(manifest))
                state.pop("halt_reason", None)
                _write(run / "state.json", state)
                return inspect(run, parent_lock_owner=owner)
            state["status"] = "needs_full_revision" if number < available_drafts else "content_revision_exhausted"
            _write(run / "state.json", state)
        if not available_drafts:
            state.update(status="content_revision_exhausted", halt_reason="原故事整稿内容返修额度已耗尽")
            _write(run / "state.json", state)
        return inspect(run, parent_lock_owner=owner)
    except Exception as exc:
        if (run / "state.json").exists():
            saved = _read(run / "state.json")
            saved.update(status="needs_attention", halt_reason=str(exc))
            _write(run / "state.json", saved)
        raise
    finally:
        if lock.exists() and _read(lock).get("owner") == owner:
            lock.unlink()


def inspect(run_dir, *, parent_lock_owner=None):
    run = Path(run_dir).resolve()
    if not (run / "state.json").exists():
        return {"schema": VERSION, "run_dir": str(run), "status": "unprepared", "automatic_media_submit": False}
    state = _read(run / "state.json")
    status, error, files = state["status"], state.get("halt_reason"), {}
    if status == "machine_text_complete":
        try:
            binding, _, selected = verify(run, parent_lock_owner=parent_lock_owner)
            manifest = _read(run / "OUTPUT_MANIFEST.json")
            if _hash(manifest) != state["output_manifest_sha256"]:
                raise ValueError("输出总清单变化")
            for row in [*manifest["files"], manifest["script_receipt"], manifest["review_receipt"]]:
                verify_binding(row)
            script, review = _read(run / "SCREENPLAY.json"), _read(run / "FULL_TEXT_REVIEW.json")
            validate_script(script, binding, selected["text"])
            if (manifest["script_sha256"] != _hash(script) or review["script_sha256"] != _hash(script)
                    or manifest["review_sha256"] != _hash(review) or review["whole_text_reviewed"] is not True
                    or any(row["severity"] in ("major", "blocking") for row in review["issues"])):
                raise ValueError("完整稿或同源全文审查不符")
            files = {Path(row["path"]).name: row for row in manifest["files"]}
        except Exception as exc:
            status, error = "incomplete_artifacts", str(exc)
    return {"schema": VERSION, "run_dir": str(run), "status": status, "state": state,
            "artifacts": files, "error": error, "human_approved": False, "automatic_media_submit": False}


def preview(run_dir):
    binding, state, selected = verify(run_dir)
    return {**inspect(run_dir), "source": selected, "binding": binding,
            "remaining_calls": binding["budget"]["max_calls"] - state["calls_started"],
            "remaining_known_tokens": binding["budget"]["max_total_tokens"] - state["known_reported_tokens"]}
