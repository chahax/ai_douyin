"""Independent source-to-production-text workflow with durable native receipts.

Every external request is admitted under the run lock. Framework checkpoints
never grant another request identity, and received results are replayed locally.
This module does not generate media or grant human approval.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from . import novel_adaptation_pipeline_v1 as core
from . import novel_plaintext_contracts_v3 as native
from . import novel_logic_contracts_v4 as contracts
from . import novel_logic_workflow_v4 as workflow
from . import novel_agent_roles_v5 as roles
from . import novel_director_handoff_v5 as director
from .creative_workflow_roles import CreativeRoleClients

VERSION = "novel_agent_pipeline/v5"
CANONICAL_REGISTRY = core.CANONICAL_REGISTRY
TERMINAL = {"needs_attention", "content_revision_exhausted", "director_revision_exhausted",
            "legacy_dispatch_blocked", "text_ready_for_production"}


def _aliases(source):
    result = ["source_" + source["full_source_sha256"]]
    if source["book_id"]:
        result.append("book_" + core._digest(source["book_id"]))
    if source["title"]:
        result.append("title_" + core._digest(source["title"].strip()))
    return result


def _code_bindings():
    modules = (core, native, contracts, workflow, roles, director)
    paths = {Path(module.__file__).resolve() for module in modules} | {Path(__file__).resolve()}
    paths.update(Path(row["path"]) for row in core._code_bindings())
    for filename in ("novel_logic_adjudication_v4.py", "novel_scene_logic_v4.py"):
        paths.add(Path(__file__).with_name(filename))
    graph = Path(__file__).with_name("novel_agent_graph_v5.py")
    if graph.exists():
        paths.add(graph)
    return [core._binding(path) for path in sorted(paths)]


def prepare(run_dir, *, source_path=None, acquisition_receipt=None, title=None, book_id=None,
            scope=None, registry_dir=None, max_calls=20, max_total_tokens=500000,
            max_revisions=2, per_draft_clarifications=1, max_clarifications=2,
            max_director_revisions=1, brief=None, catalog_path=None):
    """Freeze this independent version without changing any older registration."""
    run = Path(run_dir).resolve()
    source, evidence, paths = core._source(source_path, acquisition_receipt, title, book_id, scope)
    if brief is not None and not isinstance(brief, dict):
        raise ValueError("创作要求必须为对象或None")
    target = (brief or {}).get("target_duration_seconds")
    if target is not None and (type(target) is not int or not 60 <= target <= 900):
        raise ValueError("目标时长必须为60至900秒的整数")
    budget = {"max_calls": max_calls, "max_total_tokens": max_total_tokens,
              "max_revisions": max_revisions, "per_draft_clarifications": per_draft_clarifications,
              "max_clarifications": max_clarifications, "max_director_revisions": max_director_revisions}
    if (any(type(v) is not int or v < 1 for v in (max_calls, max_total_tokens))
            or type(max_revisions) is not int or not 0 <= max_revisions <= 2
            or type(per_draft_clarifications) is not int or not 0 <= per_draft_clarifications <= 1
            or type(max_clarifications) is not int or not 0 <= max_clarifications <= 2
            or type(max_director_revisions) is not int or not 0 <= max_director_revisions <= 1):
        raise ValueError("预算非法；整稿返修最多2、同稿核实每稿1/总2、导演返修最多1")
    if (run / "BINDING.json").exists():
        binding, _ = _verify(run)
        if binding["source"] != source or binding["budget"] != budget or binding["brief"] != brief:
            raise ValueError("恢复不能改变来源、预算或创作要求")
        return inspect(run)
    if run.exists() and any(run.iterdir()):
        raise ValueError("新运行目录必须为空")
    catalog = Path(catalog_path).resolve() if catalog_path else core.ROOT / "data/visual_asset_library/personal_catalog_v1/CATALOG.json"
    if catalog.is_dir():
        catalog = catalog / "CATALOG.json"
    if catalog_path and not catalog.is_file():
        raise ValueError("显式资产目录缺CATALOG.json")
    catalog_original = core._binding(catalog) if catalog.is_file() else None
    catalog_value = core._read(catalog) if catalog.is_file() else {"assets": []}
    if not isinstance(catalog_value, dict) or not isinstance(catalog_value.get("assets"), list):
        raise ValueError("资产目录结构非法")
    for asset in catalog_value["assets"]:
        image = asset.get("image") if isinstance(asset, dict) else None
        if isinstance(image, dict) and isinstance(image.get("path"), str) and image["path"]:
            candidate_path = Path(image["path"])
            if not candidate_path.is_absolute():
                image["path"] = str((catalog.parent / candidate_path).resolve())
    protocol = core._protocol()
    if protocol["writer"]["model"] != "MiniMax-M3" or protocol["director"]["model"] != "deepseek-flash":
        raise ValueError("冻结协议不是已核实的MiniMax/DeepSeek")
    canonical = Path(CANONICAL_REGISTRY).resolve()
    canonical.mkdir(parents=True, exist_ok=True)
    aliases = _aliases(source)
    claim = {"schema": VERSION, "run_dir": str(run), "source_binding_id": source["binding_id"],
             "story_id": aliases[0]}
    registry = [canonical / (alias + ".json") for alias in aliases]
    if registry_dir and Path(registry_dir).resolve() != canonical:
        registry.append(Path(registry_dir).resolve() / (aliases[0] + ".json"))
    with core._lock(canonical / ".registration.lock"):
        for path in registry:
            if path.exists() and core._read(path) != claim:
                raise RuntimeError("同故事已登记，不能换目录/版本/registry重领容量：" + str(path))
        for row in evidence:
            core._verify_file(row)
        if catalog_original:
            core._verify_file(catalog_original)
        blocks = core._legacy_blocks(source, paths)
        for path in registry:
            if not path.exists():
                core._write(path, claim)
        run.mkdir(parents=True, exist_ok=True)
        core._write(run / "CATALOG_FROZEN.json", catalog_value)
        core._write(run / "SOURCE.json", source)
        binding = {"schema": VERSION, "run_dir": str(run), "source": source,
                   "source_file": core._binding(run / "SOURCE.json"), "source_evidence": evidence,
                   "original_source_paths": [str(p) for p in paths], "protocol": protocol,
                   "code_bindings": _code_bindings(), "budget": budget, "brief": brief,
                   "registry": [core._binding(p) for p in registry], "legacy_blockers": blocks,
                   "catalog_path": str(catalog), "catalog_snapshot": core._binding(run / "CATALOG_FROZEN.json"),
                   "catalog_original": catalog_original,
                   "contracts": {"writer_prompt": roles.WRITER_PROMPT, "review_prompt": roles.REVIEW_PROMPT},
                   "human_approved": False, "automatic_media_submit": False}
        core._write(run / "BINDING.json", binding)
        core._write(run / "BINDING_ANCHOR.json", {"sha256": core._digest(binding)})
        _save_state(run, {"schema": VERSION, "status": "legacy_dispatch_blocked" if blocks else "prepared",
                          "stage": "writer_full", "calls_started": 0, "known_reported_tokens": 0,
                          "reported_tokens": 0, "pending_call": None, "pending_request_binding": None,
                          "call_bindings": [], "active": {}, "revisions_used": 0,
                          "director_revisions_used": 0, "clarifications_used": 0,
                          "draft_clarifications_used": 0, "full_reviews_used": 0,
                          "previous_draft": None, "feedback": None, "previous_bundle": None})
    return inspect(run)


def _save_state(run, state):
    core._save_state(run, deepcopy(state))


def _response_evidence(response, binding):
    role = response.get("role")
    if role not in binding["protocol"]:
        return ["响应角色非法"], None, None
    errors, tokens, text = native.response_evidence(response, {**binding["protocol"][role], "role": role})
    payload = response.get("response_payload") or {}
    choices = payload.get("choices") or []
    message = choices[0].get("message", {}) if len(choices) == 1 and isinstance(choices[0], dict) else {}
    if (response.get("response_metadata", {}).get("finish_reason") != "stop"
            or message.get("tool_calls") or message.get("content") != text):
        errors.append("本流程只接受明确stop的完整原生content")
    return errors, tokens, text


def _verify(run, *, _state_override=None):
    run = Path(run).resolve()
    binding = core._read(run / "BINDING.json")
    state = core._read(run / "state.json") if _state_override is None else _state_override
    if (binding.get("schema") != VERSION or binding.get("run_dir") != str(run)
            or core._read(run / "BINDING_ANCHOR.json").get("sha256") != core._digest(binding)):
        raise ValueError("冻结身份变化")
    snapshots = sorted(run.glob("STATE_*.json"))
    if not snapshots or core._read(snapshots[-1]) != state:
        raise ValueError("状态与不可变检查点不符")
    if binding["protocol"] != core._protocol() or core._read(run / "SOURCE.json") != binding["source"]:
        raise ValueError("冻结来源或协议变化")
    for row in [binding["source_file"], *binding["source_evidence"], *binding["code_bindings"], *binding["registry"]]:
        core._verify_file(row)
    core._verify_file(binding["catalog_snapshot"])
    if binding.get("catalog_original"):
        core._verify_file(binding["catalog_original"])
    requests = sorted(run.glob("REQUEST_*.json"))
    claims = sorted(run.glob("CLAIM_*.json"))
    if len(requests) != state["calls_started"] or len(claims) != len(requests):
        raise ValueError("派发claim/请求与检查点不符，保留未知门不能重派")
    adopted = {row["path"] for row in state["call_bindings"]}
    known = 0
    observed = {"writer_full": 0, "review_full": 0, "clarify_full": 0,
                "director_full": 0, "director_review": 0}
    for number, path in enumerate(requests, 1):
        request = core._read(path)
        claim = core._read(run / f"CLAIM_{number:03}.json")
        if (request.get("ordinal") != number or request.get("source_binding_id") != binding["source"]["binding_id"]
                or claim.get("request_binding") != core._binding(path)
                or claim.get("stage_key") != request.get("stage_key")
                or request.get("stage") not in observed
                or request.get("role") != ("writer" if request["stage"] in {"writer_full", "director_full"} else "director")):
            raise ValueError("请求/claim身份错误")
        observed[request["stage"]] += 1
        response_path = run / f"RESPONSE_{number:03}.json"
        if response_path.exists():
            response = core._read(response_path)
            if (response.get("request_binding") != core._binding(path)
                    or any(response.get(k) != request.get(k) for k in ("ordinal", "stage", "role", "stage_key"))):
                raise ValueError("响应与唯一原请求不符")
            _, tokens, _ = _response_evidence(response, binding)
            if str(response_path.resolve()) in adopted and tokens is not None:
                known += tokens
        ledger_path = run / f"CALL_LEDGER_{number:03}.json"
        if ledger_path.exists():
            ledger = core._read(ledger_path)
            if (ledger.get("request_binding") != core._binding(path)
                    or not response_path.exists() or ledger.get("response_binding") != core._binding(response_path)):
                raise ValueError("独立调用账本身份变化")
    for row in state["call_bindings"]:
        core._verify_file(row)
    if known != state["known_reported_tokens"] or state["reported_tokens"] not in (None, known):
        raise ValueError("实际用量与已保存原生回执不符")
    if state["pending_call"] is not None:
        if state["pending_request_binding"] != core._binding(run / f"REQUEST_{state['pending_call']:03}.json"):
            raise ValueError("未决请求身份变化")
    elif len(state["call_bindings"]) != 3 * len(requests):
        raise ValueError("原生请求响应或调用账本缺失")
    if (state["revisions_used"] != max(0, observed["writer_full"] - 1)
            or state["director_revisions_used"] != max(0, observed["director_full"] - 1)
            or state["clarifications_used"] != observed["clarify_full"]
            or state["full_reviews_used"] != observed["review_full"] + observed["clarify_full"]):
        raise ValueError("阶段用量与实际请求计数不符")
    for row in state["active"].values():
        if isinstance(row, dict) and "file" in row:
            core._verify_file(row["file"])
            if "receipt" in row:
                core._verify_file(row["receipt"])
    if "asset_candidates" in state["active"]:
        for candidate in _value(state, "asset_candidates")["candidates"]:
            if candidate.get("integrity") == "ok" and core._binding(candidate["path"])["sha256"] != candidate["actual_sha256"]:
                raise ValueError("本次资产候选文件变化")
    return binding, state


def _recover_state_projection(run):
    """Recover only a fully verified immutable checkpoint, never a request.

    The state projection can lag when snapshot publication succeeded but its
    atomic replacement failed. All request/native/billing proofs are checked
    against that exact snapshot before replacing the local projection.
    """
    snapshots = sorted(run.glob("STATE_*.json"))
    if not snapshots:
        return
    latest = core._read(snapshots[-1])
    current = core._read(run / "state.json") if (run / "state.json").exists() else None
    if latest == current:
        return
    _verify(run, _state_override=latest)
    temp = run / (".verified-state-recovery-" + core._digest(latest))
    data = json.dumps(latest, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if temp.exists() and temp.read_bytes() != data:
        raise ValueError("本地检查点恢复临时文件不符")
    if not temp.exists():
        with temp.open("xb") as stream:
            stream.write(data)
    temp.replace(run / "state.json")


def recover_projection(run_dir):
    """Repair a verified local checkpoint projection, making zero API calls."""
    run = Path(run_dir).resolve()
    binding = core._read(run / "BINDING.json")
    if binding.get("schema") != VERSION:
        raise ValueError("不能恢复其他冻结版本的检查点")
    with core._lock(run / ".execution.lock") as owner:
        _recover_state_projection(run)
        _verify(run)
        return inspect(run, _lock_owner=owner)


def _adopt_response(run, binding, state, number):
    request_path, response_path = run / f"REQUEST_{number:03}.json", run / f"RESPONSE_{number:03}.json"
    request, response = core._read(request_path), core._read(response_path)
    if response["request_binding"] != core._binding(request_path):
        raise ValueError("原生响应身份不符")
    errors, tokens, text = _response_evidence(response, binding)
    ledger_path = run / f"CALL_LEDGER_{number:03}.json"
    core._ensure(ledger_path, {"schema": VERSION, "ordinal": number, "stage_key": request["stage_key"],
                             "request_binding": core._binding(request_path), "response_binding": core._binding(response_path),
                             "reported_tokens": tokens, "usage_known": tokens is not None,
                             "finish_reason": response.get("response_metadata", {}).get("finish_reason"),
                             "errors": errors})
    existing = {row["path"] for row in state["call_bindings"]}
    if str(response_path.resolve()) not in existing and tokens is not None:
        state["known_reported_tokens"] += tokens
    for path in (request_path, response_path, ledger_path):
        if str(path.resolve()) not in existing:
            state["call_bindings"].append(core._binding(path))
    state["reported_tokens"] = state["known_reported_tokens"] if tokens is not None else None
    if errors:
        state.update(status="needs_attention", halt_reason="；".join(errors))
    else:
        state.update(status="running", pending_call=None, pending_request_binding=None)
    _save_state(run, state)
    if errors:
        raise RuntimeError(state["halt_reason"])
    return text, core._binding(response_path)


def _request_spec(binding, stage, payload):
    if stage in {"writer_full", "review_full", "clarify_full"}:
        prompt = binding["contracts"]["writer_prompt" if stage == "writer_full" else "review_prompt"]
        messages = [{"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
        parameters = {"max_tokens": 20000 if stage == "writer_full" else 16000,
                      "temperature": 0.4 if stage == "writer_full" else 0.1}
    else:
        messages, parameters = payload["messages"], dict(payload["parameters"])
    parameters.update(thinking="disabled", structured_schema=None)
    if set(parameters) != {"max_tokens", "temperature", "thinking", "structured_schema"}:
        raise ValueError("请求参数超出冻结文本客户端支持")
    return messages, parameters


def _dispatch(run, binding, state, stage, payload, clients):
    _verify(run)
    # The payload includes the exact parent draft/review. Counters change at
    # admission, so they must never change the identity during crash recovery.
    parent_key = {"writer_full": "review_bundle", "review_full": "writer_full", "clarify_full": "review_bundle",
                  "director_full": "director_review" if "director_review" in state["active"] else "gate",
                  "director_review": "director_full"}[stage]
    parent = state["active"].get(parent_key)
    if stage == "director_full" and state.get("director_rejected_receipt"):
        parent = state["director_rejected_receipt"]
    stage_key = core._digest({"stage": stage, "payload": payload, "parent": parent})
    for path in sorted(run.glob("REQUEST_*.json")):
        prior = core._read(path)
        if prior["stage_key"] == stage_key:
            received = run / f"RESPONSE_{prior['ordinal']:03}.json"
            if not received.exists():
                raise RuntimeError("已有唯一请求结果未知，不能重派")
            return _adopt_response(run, binding, state, prior["ordinal"])
    if state["pending_call"] is not None or state["status"] in TERMINAL:
        raise RuntimeError("任务已停止或存在未知请求")
    if core._legacy_blocks(binding["source"], [Path(p) for p in binding["original_source_paths"]]):
        raise RuntimeError("同故事历史停止门存在")
    budget = binding["budget"]
    if state["calls_started"] >= budget["max_calls"]:
        raise RuntimeError("调用预算耗尽")
    prior_stages = [core._read(path)["stage"] for path in sorted(run.glob("REQUEST_*.json"))]
    if stage == "writer_full" and "writer_full" in prior_stages and state["revisions_used"] >= budget["max_revisions"]:
        raise RuntimeError("整稿内容返修容量耗尽")
    if stage == "clarify_full" and (state["draft_clarifications_used"] >= budget["per_draft_clarifications"]
                                     or state["clarifications_used"] >= budget["max_clarifications"]):
        raise RuntimeError("同稿核实容量耗尽")
    if stage == "director_full" and "director_full" in prior_stages and state["director_revisions_used"] >= budget["max_director_revisions"]:
        raise RuntimeError("导演本层返修容量耗尽")
    messages, parameters = _request_spec(binding, stage, payload)
    request_bytes = len(json.dumps({"messages": messages, "parameters": parameters}, ensure_ascii=False).encode("utf-8"))
    reservation = request_bytes + parameters["max_tokens"] + 4096
    if request_bytes > core.MAX_REQUEST_BYTES or state["known_reported_tokens"] + reservation > budget["max_total_tokens"]:
        raise RuntimeError("完整输入或token预留超过冻结预算，不截文")
    number = state["calls_started"] + 1
    request_path = run / f"REQUEST_{number:03}.json"
    role = "writer" if stage in {"writer_full", "director_full"} else "director"
    request = {"schema": VERSION, "ordinal": number, "stage": stage, "stage_key": stage_key,
               "role": role, "source_binding_id": binding["source"]["binding_id"],
               "messages": messages, "parameters": parameters, "payload_sha256": core._digest(payload),
               "input_bindings": deepcopy(state["active"]), "reservation_tokens": reservation}
    # Immutable admission files and checkpoint precede the only external call.
    core._write(request_path, request)
    core._write(run / f"CLAIM_{number:03}.json", {"schema": VERSION, "ordinal": number,
                "stage_key": stage_key, "request_binding": core._binding(request_path), "automatic_replay": False})
    if stage == "writer_full" and "writer_full" in prior_stages:
        state["revisions_used"] += 1
    if stage == "director_full" and "director_full" in prior_stages:
        state["director_revisions_used"] += 1
    if stage in {"review_full", "clarify_full"}:
        state["full_reviews_used"] += 1
    if stage == "clarify_full":
        state["clarifications_used"] += 1
        state["draft_clarifications_used"] += 1
    state.update(calls_started=number, pending_call=number,
                 pending_request_binding=core._binding(request_path), status="running")
    _save_state(run, state)
    response = {k: request[k] for k in ("schema", "ordinal", "stage", "stage_key", "role")}
    response["request_binding"] = core._binding(request_path)
    try:
        result = clients.call(role, messages, **parameters)
        response.update(response_text=result.text, response_metadata=result.metadata, response_payload=result.response_payload)
    except Exception as exc:
        response.update(error=str(exc), response_text=getattr(exc, "response_text", None),
                        response_metadata=getattr(exc, "response_metadata", {}),
                        response_payload=getattr(exc, "response_payload", None))
    errors, _, _ = _response_evidence(response, binding)
    response.update(status="response_rejected" if errors else "response_received", response_errors=errors)
    core._write(run / f"RESPONSE_{number:03}.json", response)
    return _adopt_response(run, binding, state, number)


def _ensure_text(path, text):
    path, data = Path(path), text.encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("派生文本与原生正文不符")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def _text(state, stage="writer_full"):
    return Path(state["active"][stage]["file"]["path"]).read_bytes().decode("utf-8")


def _value(state, stage):
    return core._read(state["active"][stage]["file"]["path"])


def _store(run, state, key, filename, value, receipt=None, *, text=False):
    path = run / filename
    if text:
        _ensure_text(path, value)
    else:
        core._ensure(path, value)
    state["active"][key] = {"file": core._binding(path)}
    if receipt:
        state["active"][key]["receipt"] = receipt


def _capacity(binding, state):
    b = binding["budget"]
    return {"per_draft_clarification_limit": b["per_draft_clarifications"],
            "per_draft_clarification_used": state["draft_clarifications_used"],
            "run_clarification_limit": b["max_clarifications"], "run_clarification_used": state["clarifications_used"],
            "content_revision_limit": b["max_revisions"], "content_revisions_used": state["revisions_used"],
            "full_review_limit": b["max_revisions"] + 1 + b["max_clarifications"],
            "full_reviews_used": state["full_reviews_used"], "call_limit": b["max_calls"],
            "calls_used": state["calls_started"], "token_limit": b["max_total_tokens"],
            "tokens_used": state["known_reported_tokens"], "request_token_reservation": 1}


def _evaluate_review(run, binding, state, bundle, receipt):
    response = core._read(receipt["path"])
    request_binding = response["request_binding"]
    request = core._read(request_binding["path"])
    payload = core._parse(request["messages"][-1]["content"])
    errors, _, native_text = _response_evidence(response, binding)
    if errors:
        raise ValueError("全文审查原生响应无效")
    reproduced = roles.parse_review_bundle(native_text, source_binding=binding["source"]["binding_id"],
        draft_binding=state["active"]["writer_full"]["file"]["sha256"], native_response_ref=receipt["sha256"],
        artifact_prefix=bundle["review"]["header"]["artifact_id"].removesuffix("/review"),
        required_issues=payload.get("required_issues"))
    if bundle != reproduced:
        raise ValueError("场记、审查或核实并非本次原生回执的完整派生")
    evidence = roles.verify_review_evidence(request, response, source=binding["source"],
        screenplay=_text(state), protocol=binding["protocol"], review=bundle["review"],
        request_binding=request_binding, response_binding=receipt)
    source_binding = binding["source"]["binding_id"]
    draft_binding = state["active"]["writer_full"]["file"]["sha256"]
    historical = roles.historical_candidates_from_payload(payload, source_binding=source_binding,
                                                        draft_binding=draft_binding)
    result = roles.evaluate_review_bundle(bundle, source_binding=source_binding,
        draft_binding=draft_binding, evidence=evidence, capacity=_capacity(binding, state),
        historical_candidates=historical)
    return {**result, "artifact_id": "gate-" + str(response["ordinal"]), "native_evidence": evidence}


def _episode(binding, bundle):
    source = binding["source"]
    return {"header": {"artifact_id": "episode-001", "schema_version": contracts.VERSION,
            "source_binding": source["binding_id"], "draft_binding": None, "producer_version": VERSION,
            "parent_artifact_ids": [], "status": "complete"}, "episode_id": "episode-001",
            "source_range": {"chapter_ids": ["acquired-scope"],
                             "start_anchor": str(source["start_character"]), "end_anchor": str(source["end_character"])},
            "selected_event_ids": [row["event_id"] for row in bundle["scene_ledger"]["events"]],
            "prior_end_state": [], "unrevealed_facts": ["未获取章节与正文未交代事实不得视为已知"],
            "adaptation_boundaries": {"preserve": ["当前正文主线、人物身份与关键因果"],
                "allowed_changes": ["对白措辞、可拍化的动作与场景组织"], "unknown_facts": ["已获取范围以外事实"]}}


def _director_kwargs(binding, state):
    bundle = _value(state, "review_bundle")
    return {"source_binding": binding["source"]["binding_id"],
            "draft_binding": state["active"]["writer_full"]["file"]["sha256"],
            "text_gate_artifact_id": _value(state, "gate")["artifact_id"],
            "scene_ledger": bundle["scene_ledger"], "episode_artifact_id": "episode-001",
            "catalog_candidates": _value(state, "asset_candidates")["candidates"] if "asset_candidates" in state["active"] else []}


def _verify_director_native(binding, state):
    plan, review = _value(state, "director_full"), _value(state, "director_review")
    for stage in ("director_full", "director_review"):
        receipt = state["active"][stage]["receipt"]
        core._verify_file(receipt)
        response = core._read(receipt["path"])
        core._verify_file(response["request_binding"])
        request = core._read(response["request_binding"]["path"])
        errors, _, text = _response_evidence(response, binding)
        if errors or request["stage"] != stage:
            raise ValueError("导演原生证据非法")
        materials = roles.parse_json(request["messages"][-1]["content"])
        if (materials.get("source_text") != binding["source"]["text"]
                or materials.get("accepted_full_draft") != _text(state)):
            raise ValueError("导演请求并未包含完整同源同稿")
        if stage == "director_full":
            if (materials.get("scene_ledger") != _value(state, "review_bundle")["scene_ledger"]
                    or materials.get("catalog_candidates") != director._candidate_summaries(
                        _value(state, "asset_candidates")["candidates"])
                    or materials.get("source_binding") != binding["source"]["binding_id"]
                    or materials.get("draft_binding") != state["active"]["writer_full"]["file"]["sha256"]
                    or materials.get("text_gate_artifact_id") != _value(state, "gate")["artifact_id"]):
                raise ValueError("导演请求场记或候选来源不符")
            expected = director.parse_director(text, **_director_kwargs(binding, state),
                        artifact_id=plan["header"]["artifact_id"], producer_version=VERSION)
        else:
            if materials.get("director") != plan:
                raise ValueError("DeepSeek未收到当前完整导演稿")
            expected = director.parse_director_review(text, source_binding=binding["source"]["binding_id"],
                draft_binding=state["active"]["writer_full"]["file"]["sha256"], director=plan,
                artifact_id=review["header"]["artifact_id"], native_response_ref=receipt["sha256"])
            if request["input_bindings"].get("director_full") != state["active"]["director_full"]:
                raise ValueError("导演审查未绑定当前导演全文")
        if expected != (plan if stage == "director_full" else review):
            raise ValueError("导演派生产物与原生回执不符")
    return plan, review


def _director_native_evidence(binding, state):
    plan_receipt = state["active"]["director_full"]["receipt"]
    review_receipt = state["active"]["director_review"]["receipt"]
    return {"protocol": binding["protocol"], "source": binding["source"], "screenplay": _text(state),
            "director_request_binding": core._read(plan_receipt["path"])["request_binding"],
            "director_response_binding": plan_receipt,
            "review_request_binding": core._read(review_receipt["path"])["request_binding"],
            "review_response_binding": review_receipt}


def _complete(run, binding, state):
    bundle = _value(state, "review_bundle")
    gate = _evaluate_review(run, binding, state, bundle, state["active"]["review_bundle"]["receipt"])
    if gate["gate"]["decision"] != "pass":
        raise ValueError("当前同稿原生审查与程序门未通过")
    plan, review = _verify_director_native(binding, state)
    handoff = director.make_handoff(plan, review, source_binding=binding["source"]["binding_id"],
        draft_binding=state["active"]["writer_full"]["file"]["sha256"],
        artifact_id="production-handoff", native_evidence=_director_native_evidence(binding, state))
    _ensure_text(run / "SCREENPLAY.md", _text(state))
    core._ensure(run / "PRODUCTION_HANDOFF.json", handoff)
    files = [core._binding(run / name) for name in ("SCREENPLAY.md", "PRODUCTION_HANDOFF.json")]
    files.extend(row["file"] for row in state["active"].values())
    manifest = {"schema": VERSION, "status": "text_ready_for_production", "source_binding": binding["source"]["binding_id"],
                "files": files, "stages": deepcopy(state["active"]), "human_approved": False,
                "automatic_media_submit": False, "media_generated": False}
    core._ensure(run / "OUTPUT_MANIFEST.json", manifest)
    state.update(status="text_ready_for_production", stage="complete",
                 output_manifest=core._binding(run / "OUTPUT_MANIFEST.json"))
    _save_state(run, state)


def execute(run_dir, *, clients=None, max_steps=None):
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError("max_steps必须为正整数或None")
    run = Path(run_dir).resolve()
    with core._lock(run / ".execution.lock") as owner:
        _recover_state_projection(run)
        binding, state = _verify(run)
        if state["status"] in TERMINAL:
            return inspect(run, _lock_owner=owner)
        clients = clients or CreativeRoleClients()
        steps = 0
        try:
            if state["pending_call"] is not None:
                number = state["pending_call"]
                if not (run / f"RESPONSE_{number:03}.json").exists():
                    raise RuntimeError("在途请求结果未知，不重派")
                _adopt_response(run, binding, state, number)
            while True:
                stage = state["stage"]
                if stage == "complete":
                    _complete(run, binding, state)
                    return inspect(run, _lock_owner=owner)
                if stage == "writer_full":
                    payload = roles.build_writer_payload(binding["source"], previous_draft=state["previous_draft"],
                        feedback=state["feedback"], brief=binding["brief"])
                elif stage in {"review_full", "clarify_full"}:
                    prior = _value(state, "review_bundle") if stage == "clarify_full" else None
                    candidates = _value(state, "gate")["scene_candidate_issues"] if stage == "clarify_full" else None
                    payload = roles.build_review_payload(binding["source"], _text(state), previous_bundle=prior,
                        candidate_issues=candidates, brief=binding["brief"])
                elif stage == "director_full":
                    kwargs = _director_kwargs(binding, state)
                    scene_ledger = kwargs.pop("scene_ledger")
                    payload = director.build_director_payload(binding["source"]["text"], _text(state), scene_ledger,
                        **kwargs, previous_director=state.get("director_previous") or
                        (_value(state, "director_full") if "director_full" in state["active"] else None),
                        revision_feedback=state.get("director_feedback"),
                        target_duration_seconds=(binding["brief"] or {}).get("target_duration_seconds"))
                elif stage == "director_review":
                    payload = director.build_director_review_payload(binding["source"]["text"], _text(state),
                        _value(state, "director_full"),
                        target_duration_seconds=(binding["brief"] or {}).get("target_duration_seconds"))
                else:
                    raise ValueError("未知阶段")
                text, receipt = _dispatch(run, binding, state, stage, payload, clients)
                number = core._read(receipt["path"])["ordinal"]
                if stage == "writer_full":
                    state["active"] = {}
                    _store(run, state, "writer_full", f"DRAFT_{number:03}.md", text, receipt, text=True)
                    state.update(stage="review_full", previous_draft=None, feedback=None,
                                 draft_clarifications_used=0, previous_bundle=None)
                elif stage in {"review_full", "clarify_full"}:
                    bundle = roles.parse_review_bundle(text, source_binding=binding["source"]["binding_id"],
                        draft_binding=state["active"]["writer_full"]["file"]["sha256"],
                        native_response_ref=receipt["sha256"], artifact_prefix=f"review-{number:03}",
                        required_issues=payload.get("required_issues"))
                    _store(run, state, "review_bundle", f"REVIEW_BUNDLE_{number:03}.json", bundle, receipt)
                    for key, name in (("scene_ledger", "SCENE_LEDGER"), ("review", "REVIEW"),
                                      ("adjudication", "ADJUDICATION")):
                        _store(run, state, key, f"{name}_{number:03}.json", bundle[key], receipt)
                    evaluated = _evaluate_review(run, binding, state, bundle, receipt)
                    _store(run, state, "gate", f"GATE_{number:03}.json", evaluated)
                    gate = evaluated["gate"]
                    if gate["decision"] == "pass":
                        _store(run, state, "episode", "EPISODE.json", _episode(binding, bundle))
                        events = bundle["scene_ledger"]["events"]
                        tags = list(dict.fromkeys([entity for row in events for entity in row["entities"]]
                            + [row.get("context", {}).get("scene_id", "") for row in events]))
                        candidates = director.discover_asset_candidates(binding["catalog_snapshot"]["path"],
                            [tag for tag in tags if tag])
                        _store(run, state, "asset_candidates", "ASSET_CANDIDATES.json",
                            {"schema": VERSION, "catalog": binding["catalog_snapshot"], "search_tags": tags,
                             "candidates": candidates, "current_casting_status": "unbound"})
                        state.update(stage="director_full")
                    elif gate["next_action"] == "revise_full_draft":
                        state.update(stage="writer_full", previous_draft=_text(state), feedback={"review": bundle,
                            "gate": evaluated}, status="needs_full_revision")
                    elif gate["next_action"] in {"clarify_same_draft", "full_review_same_draft"}:
                        state.update(stage="clarify_full")
                    else:
                        reason = ";".join(gate["stop_reasons"])
                        state.update(status="content_revision_exhausted" if "revision_limit" in gate["stop_reasons"]
                                     else "needs_attention", halt_reason=reason)
                elif stage == "director_full":
                    try:
                        plan = director.parse_director(text, **_director_kwargs(binding, state),
                            artifact_id=f"director-{number:03}", producer_version=VERSION)
                    except director.DirectorContractError as exc:
                        content_codes = {"DIRECTOR_EVENT_OMITTED", "DIRECTOR_EVENT_INVENTED", "DIRECTOR_CHARACTER_COVERAGE",
                            "DIRECTOR_STATE_INCOMPLETE", "DIRECTOR_ACTOR_INVENTED", "DIRECTOR_TIMELINE_MISMATCH",
                            "DIRECTOR_ASSET_CANDIDATE_UNKNOWN"}
                        if not exc.errors or any(row["code"] not in content_codes for row in exc.errors):
                            raise
                        rejected = roles.parse_json(text)
                        _store(run, state, "director_rejected", f"DIRECTOR_REJECTED_{number:03}.json", rejected, receipt)
                        state.update(director_previous=rejected, director_rejected_receipt=receipt,
                                     director_feedback={"content_contract_errors": exc.errors})
                        if state["director_revisions_used"] >= binding["budget"]["max_director_revisions"]:
                            state.update(status="director_revision_exhausted", halt_reason="导演完整内容返修上限已到")
                        _save_state(run, state)
                        steps += 1
                        if state["status"] in TERMINAL or (max_steps is not None and steps >= max_steps):
                            return inspect(run, _lock_owner=owner)
                        continue
                    _store(run, state, "director_full", f"DIRECTOR_{number:03}.json", plan, receipt)
                    state.update(stage="director_review", director_previous=None, director_rejected_receipt=None)
                else:
                    plan = _value(state, "director_full")
                    review = director.parse_director_review(text, source_binding=binding["source"]["binding_id"],
                        draft_binding=state["active"]["writer_full"]["file"]["sha256"], director=plan,
                        artifact_id=f"director-review-{number:03}", native_response_ref=receipt["sha256"])
                    _store(run, state, "director_review", f"DIRECTOR_REVIEW_{number:03}.json", review, receipt)
                    if review.get("native_verdict") == "pass":
                        state.update(stage="complete")
                    elif state["director_revisions_used"] < binding["budget"]["max_director_revisions"]:
                        state.update(stage="director_full", director_feedback=review)
                    else:
                        state.update(status="director_revision_exhausted", halt_reason="导演本层完整返修上限已到")
                _save_state(run, state)
                steps += 1
                if state["status"] in TERMINAL:
                    return inspect(run, _lock_owner=owner)
                if max_steps is not None and steps >= max_steps:
                    if state["stage"] == "complete":
                        _complete(run, binding, state)
                    return inspect(run, _lock_owner=owner)
        except Exception as exc:
            # Preserve the last durable pending checkpoint when publication fails.
            disk = core._read(run / "state.json")
            if disk == state:
                pending = state.get("pending_call")
                if pending is None or not (run / f"RESPONSE_{pending:03}.json").exists():
                    state.update(status="needs_attention", halt_reason=str(exc))
                    _save_state(run, state)
            elif disk.get("pending_call") is None:
                # A derived-contract failure may have changed only in-memory
                # active artifacts. Keep the complete saved call, then stop.
                disk.update(status="needs_attention", halt_reason=str(exc))
                _save_state(run, disk)
            raise


def _verify_complete(run, binding, state):
    core._verify_file(state["output_manifest"])
    manifest = core._read(run / "OUTPUT_MANIFEST.json")
    if manifest.get("stages") != state["active"] or manifest.get("source_binding") != binding["source"]["binding_id"]:
        raise ValueError("生产交接清单绑定不符")
    for row in manifest["files"]:
        core._verify_file(row)
    bundle = _value(state, "review_bundle")
    gate = _evaluate_review(run, binding, state, bundle, state["active"]["review_bundle"]["receipt"])
    if gate["gate"]["decision"] != "pass":
        raise ValueError("生产文本原生pass证据失效")
    plan, review = _verify_director_native(binding, state)
    handoff = director.make_handoff(plan, review, source_binding=binding["source"]["binding_id"],
        draft_binding=state["active"]["writer_full"]["file"]["sha256"],
        artifact_id="production-handoff", native_evidence=_director_native_evidence(binding, state))
    if core._read(run / "PRODUCTION_HANDOFF.json") != handoff:
        raise ValueError("生产交接并非原生导演与审查的完整派生")
    if (run / "SCREENPLAY.md").read_bytes() != _text(state).encode("utf-8"):
        raise ValueError("最终文本不是原生整稿")
    return manifest


def inspect(run_dir, *, _lock_owner=None):
    run = Path(run_dir).resolve()
    if not (run / "BINDING.json").exists():
        return {"schema": VERSION, "run_dir": str(run), "status": "unprepared", "dispatch_blocked": True,
                "blockers": ["任务未准备"], "artifacts": {}, "human_approved": False, "automatic_media_submit": False}
    binding, state = core._read(run / "BINDING.json"), core._read(run / "state.json")
    blockers, manifest, status = [], None, state["status"]
    projection_recovery_available = False
    projection_recovery_stage, projection_recovery_calls_started = None, None
    try:
        _verify(run)
        if status == "text_ready_for_production":
            manifest = _verify_complete(run, binding, state)
    except Exception as exc:
        status = "incomplete_artifacts" if status == "text_ready_for_production" else "evidence_invalid"
        blockers.append(str(exc))
        snapshots = sorted(run.glob("STATE_*.json"))
        if snapshots:
            latest = core._read(snapshots[-1])
            if latest != state:
                try:
                    _verify(run, _state_override=latest)
                    projection_recovery_available = True
                    projection_recovery_stage = latest["stage"]
                    projection_recovery_calls_started = latest["calls_started"]
                except Exception:
                    pass
    blockers.extend(row["reason"] for row in binding.get("legacy_blockers", []))
    if state.get("pending_call") is not None:
        blockers.append("存在未决请求，只可保存原ID结果")
    if state.get("halt_reason"):
        blockers.append(state["halt_reason"])
    lock = run / ".execution.lock"
    if lock.exists() and core._read(lock).get("owner") != _lock_owner:
        blockers.append("执行锁存在")
    return {"schema": VERSION, "run_dir": str(run), "status": status, "stage": state["stage"], "state": state,
            "source": {k: v for k, v in binding["source"].items() if k != "text"},
            "calls_started": state["calls_started"], "known_reported_tokens": state["known_reported_tokens"],
            "reported_tokens": state["reported_tokens"], "pending_call": state["pending_call"],
            "projection_recovery_available": projection_recovery_available,
            "projection_recovery_stage": projection_recovery_stage,
            "projection_recovery_calls_started": projection_recovery_calls_started,
            "blockers": blockers, "dispatch_blocked": bool(blockers) or status in TERMINAL,
            "artifacts": {Path(row["path"]).name: row["path"] for row in manifest["files"]} if manifest else {},
            "human_approved": False, "automatic_media_submit": False, "media_generated": False}


def preview(run_dir):
    view = inspect(run_dir)
    if view["status"] == "unprepared":
        return view
    binding = core._read(Path(run_dir) / "BINDING.json")
    return {**view, "budget": binding["budget"], "provider_protocol": binding["protocol"],
            "remaining_calls": max(0, binding["budget"]["max_calls"] - view["calls_started"]),
            "remaining_known_tokens": max(0, binding["budget"]["max_total_tokens"] - view["known_reported_tokens"])}
