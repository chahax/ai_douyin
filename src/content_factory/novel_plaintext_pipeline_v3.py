"""Native screenplay prose, followed by a source-bound whole-text review.

This independent entry keeps the existing novel registry and immutable receipts.
Only explicit, audited authorization can continue a previously stopped story.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from . import novel_adaptation_pipeline_v1 as core
from . import novel_adaptation_production_v2 as legacy
from . import novel_plaintext_contracts_v3 as contracts
from .creative_workflow_roles import CreativeRoleClients

VERSION = "novel_plaintext_pipeline/v3"
CANONICAL_REGISTRY = core.CANONICAL_REGISTRY
TERMINAL = {"text_ready_for_director", "needs_attention", "content_revision_exhausted", "legacy_dispatch_blocked"}


def _same_source(auth, source):
    if str(source["book_id"]) != str(auth["book_id"]) or any(
            source[key] != auth["source_identity"].get(key)
            for key in ("full_source_sha256", "excerpt_sha256", "binding_id")):
        raise ValueError("授权与真实正文身份不符")


def _audit_authorization(path, run):
    """Audit the one explicitly authorized 11 + 3 response continuation."""
    path, run = Path(path).resolve(), Path(run).resolve()
    auth = core._read(path)
    if (auth.get("schema") != "novel_plaintext_authorization/v3"
            or auth.get("user_instruction") != "修改测试生产测试"
            or Path(auth["run_dir"]).resolve() != run
            or auth.get("automatic_media_submit") is not False
            or auth.get("legacy_totals") != {"calls_started": 14, "reported_tokens": 228513}
            or auth.get("original_budget") != {"max_calls": 20, "max_total_tokens": 500000}
            or auth.get("new_budget") != {"max_calls": 6, "max_total_tokens": 271487, "max_revisions": 2}):
        raise ValueError("续行授权、历史累计或剩余预算不符")
    rows = auth.get("history_bindings")
    if not isinstance(rows, list) or not rows:
        raise ValueError("缺历史原生证据冻结")
    indexed = {}
    for row in rows:
        core._verify_file(row)
        normalized = str(Path(row["path"]).resolve())
        if normalized in indexed:
            raise ValueError("历史冻结重复")
        indexed[normalized] = row

    def required(path):
        row = core._binding(path)
        if indexed.get(row["path"]) != row:
            raise ValueError("授权未冻结必要历史：" + str(path))
        return core._read(path) if Path(path).suffix == ".json" else None

    parent = Path(auth["parent_run"]).resolve()
    core._verify_file(auth["parent_checkpoint"])
    checkpoint = required(auth["parent_checkpoint"]["path"])
    if (Path(checkpoint["run_dir"]).resolve() != parent
            or str(checkpoint["book_id"]) != str(auth["book_id"])
            or checkpoint.get("combined_calls_started") != 14
            or checkpoint.get("combined_known_reported_tokens") != 228513
            or checkpoint.get("accepted") is not False):
        raise ValueError("父检查点身份或累计不符")
    bound, state = required(parent / "BINDING.json"), required(parent / "state.json")
    if required(parent / "BINDING_ANCHOR.json").get("sha256") != core._digest(bound):
        raise ValueError("父冻结anchor不符")
    source = required(parent / "SOURCE.json")
    if source != bound["source"]:
        raise ValueError("父正文与冻结不符")
    _same_source(auth, source)
    prior_auth_path = bound["production_authorization"]["path"]
    prior_auth = required(prior_auth_path)
    # This read-only helper audits all eleven original SDK envelopes, including
    # the explicitly received truncation. It never mutates or dispatches.
    legacy._audit_authorization(prior_auth_path, parent)
    required(prior_auth["legacy_checkpoint"]["path"])
    for row in prior_auth["legacy_responses"]:
        required(row["path"])
    for row in [*bound["registry"], *bound["source_evidence"], *bound["code_bindings"]]:
        core._verify_file(row)
        required(row["path"])
    snapshots = sorted(parent.glob("STATE_*.json"))
    if not snapshots or required(snapshots[-1]) != state:
        raise ValueError("父状态与最后不可变检查点不符")
    for snapshot in snapshots:
        required(snapshot)
    if (state.get("status") != "needs_attention" or state.get("pending_call") != 3
            or state.get("calls_started") != 3 or state.get("known_reported_tokens") != 48434
            or state.get("legacy_calls_started") != 11 or state.get("legacy_reported_tokens") != 180079):
        raise ValueError("父任务不是授权的已收到格式停点")
    if len(list(parent.glob("REQUEST_*.json"))) != 3 or len(list(parent.glob("RESPONSE_*.json"))) != 3:
        raise ValueError("父请求/回执数变化")
    total = 0
    for number in range(1, 4):
        request_path = parent / f"REQUEST_{number:03}.json"
        request, response = required(request_path), required(parent / f"RESPONSE_{number:03}.json")
        if (request.get("ordinal") != number or response.get("ordinal") != number
                or request.get("source_binding_id") != source["binding_id"]
                or response.get("request_binding") != core._binding(request_path)
                or request.get("role") != "writer" or response.get("role") != "writer"):
            raise ValueError("父请求与原生回执身份不符")
        meta, native = response.get("response_metadata", {}), response.get("response_payload", {})
        usage, choices = native.get("usage", {}), native.get("choices", [])
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if type(meta.get(key)) is not int or meta[key] < 0 or type(usage.get(key)) is not int or usage[key] != meta[key]:
                raise ValueError("父用量未知")
        if (meta["prompt_tokens"] + meta["completion_tokens"] != meta["total_tokens"]
                or len(choices) != 1 or choices[0].get("finish_reason") != meta.get("finish_reason")
                or meta.get("finish_reason") not in ("stop", "tool_calls")
                or not native.get("id") or native["id"] != meta.get("response_id")
                or native.get("model") != meta.get("response_model")
                or meta.get("requested_model") != "MiniMax-M3" or native.get("model") != "MiniMax-M3"
                or meta.get("role") != "writer" or meta.get("provider") != "minimax"):
            raise ValueError("父原生响应未明确结束或身份不符")
        expected_fault = "REQUIRED_TOOL_MISSING" if number == 3 else None
        if meta.get("response_fault_code") != expected_fault:
            raise ValueError("父任务存在未授权响应异常")
        if number == 3 and (meta["finish_reason"] != "stop" or response.get("status") != "response_rejected"):
            raise ValueError("父pending不是已收到stop格式停点")
        total += meta["total_tokens"]
    if total != 48434:
        raise ValueError("父新增实际用量不符")
    return auth


def _code_bindings():
    paths = [Path(__file__), Path(contracts.__file__)]
    cli = core.ROOT / "scripts/run_novel_plaintext_v3.py"
    if cli.exists():
        paths.append(cli)
    rows = {row["path"]: row for row in core._code_bindings()}
    rows.update({str(path.resolve()): core._binding(path) for path in paths})
    rows[str(Path(legacy.__file__).resolve())] = core._binding(legacy.__file__)
    return list(rows.values())


def _aliases(source):
    names = ["source_" + source["full_source_sha256"]]
    if source["book_id"]:
        names.append("book_" + core._digest(source["book_id"]))
    if source["title"]:
        names.append("title_" + core._digest(source["title"].strip()))
    return names


def _blockers(binding):
    blocks = core._legacy_blocks(binding["source"], [Path(p) for p in binding["original_source_paths"]])
    if binding.get("authorization"):
        auth = _audit_authorization(binding["authorization"]["path"], binding["run_dir"])
        prior = core._read(Path(auth["parent_run"]) / "BINDING.json")
        allowed = core._read(prior["production_authorization"]["path"])["legacy_checkpoint"]
        blocks = [row for row in blocks if row["checkpoint"] != allowed]
    return blocks


def prepare(run_dir, *, source_path=None, acquisition_receipt=None, title=None, book_id=None, scope=None,
            registry_dir=None, max_calls=20, max_total_tokens=500000, max_revisions=2, authorization=None):
    """Freeze a new source, or the precisely authorized historical continuation."""
    run = Path(run_dir).resolve()
    auth = None
    if authorization:
        if any(value is not None for value in (source_path, acquisition_receipt, title, book_id, scope)):
            raise ValueError("续行授权不得混入另一来源参数")
        auth = _audit_authorization(authorization, run)
        acquisition_receipt, title, book_id, scope = (auth["acquisition_receipt"], auth.get("title"),
                                                    auth["book_id"], auth.get("scope"))
        max_calls, max_total_tokens, max_revisions = (auth["new_budget"][key] for key in
                                                     ("max_calls", "max_total_tokens", "max_revisions"))
    source, evidence, paths = core._source(source_path, acquisition_receipt, title, book_id, scope)
    if auth:
        _same_source(auth, source)
    budget = {"max_calls": max_calls, "max_total_tokens": max_total_tokens, "max_revisions": max_revisions}
    if any(type(value) is not int or value < 1 for value in (max_calls, max_total_tokens)) or type(max_revisions) is not int or not 0 <= max_revisions <= 2:
        raise ValueError("预算必须为正整数，完整内容返修0至2轮")
    if (run / "BINDING.json").exists():
        binding, _ = _verify(run)
        if binding["source"] != source or binding["budget"] != budget:
            raise ValueError("恢复不得更换来源或预算")
        return inspect(run)
    if run.exists() and any(run.iterdir()):
        raise ValueError("新运行目录必须为空")
    protocol = core._protocol()
    if protocol["writer"]["model"] != "MiniMax-M3" or protocol["director"]["model"] != "deepseek-flash":
        raise ValueError("只使用已确认MiniMax/DeepSeek协议")
    canonical = Path(CANONICAL_REGISTRY).resolve()
    canonical.mkdir(parents=True, exist_ok=True)
    auth_binding = core._binding(authorization) if auth else None
    aliases = _aliases(source)
    with core._lock(canonical / ".registration.lock"):
        for row in evidence:
            core._verify_file(row)
        if auth:
            _audit_authorization(authorization, run)
            parent_binding = core._read(Path(auth["parent_run"]) / "BINDING.json")
            # Existing canonical registration remains byte-for-byte unchanged.
            expected = [str(canonical / (alias + ".json")) for alias in aliases]
            if sorted(row["path"] for row in parent_binding["registry"]) != sorted(expected):
                raise ValueError("授权父任务不是本canonical登记")
            key = core._digest({"parent_run": str(Path(auth["parent_run"]).resolve()),
                                "source": source["full_source_sha256"]})
            registry_paths = [canonical / "_plaintext_continuations" / (key + ".json")]
            claim = {"schema": VERSION, "run_dir": str(run), "parent_run": auth["parent_run"],
                     "source_binding_id": source["binding_id"], "authorization": auth_binding,
                     "parent_registry": parent_binding["registry"]}
        else:
            registry_paths = [canonical / (alias + ".json") for alias in aliases]
            claim = {"schema": VERSION, "run_dir": str(run), "source_binding_id": source["binding_id"],
                     "story_id": aliases[0]}
        for path in registry_paths:
            if path.exists() and core._read(path) != claim:
                raise RuntimeError("同故事/同父续行已有登记，不得换目录重领额度")
        if registry_dir and Path(registry_dir).resolve() != canonical:
            registry_paths.append(Path(registry_dir).resolve() / (aliases[0] + ".json"))
        for path in registry_paths:
            if path.exists() and core._read(path) != claim:
                raise RuntimeError("附加登记冲突")
            if not path.exists():
                core._write(path, claim)
        run.mkdir(parents=True, exist_ok=True)
        core._write(run / "SOURCE.json", source)
        binding = {"schema": VERSION, "run_dir": str(run), "source": source, "source_evidence": evidence,
                   "original_source_paths": [str(p) for p in paths], "source_file": core._binding(run / "SOURCE.json"),
                   "protocol": protocol, "code_bindings": _code_bindings(), "budget": budget,
                   "authorization": auth_binding, "legacy_consumption": auth["legacy_totals"] if auth else
                   {"calls_started": 0, "reported_tokens": 0}, "registry": [core._binding(p) for p in registry_paths],
                   "contracts": {"version": contracts.VERSION, "writer_prompt": contracts.WRITER_PROMPT,
                                 "review_prompt": contracts.REVIEW_PROMPT, "review_schema": contracts.REVIEW_SCHEMA},
                   "automatic_media_submit": False}
        blocks = _blockers(binding)
        binding["legacy_blockers"] = blocks
        core._write(run / "BINDING.json", binding)
        core._write(run / "BINDING_ANCHOR.json", {"sha256": core._digest(binding)})
        core._save_state(run, {"schema": VERSION, "status": "legacy_dispatch_blocked" if blocks else "prepared",
                              "stage": "writer_full", "calls_started": 0, "known_reported_tokens": 0,
                              "reported_tokens": 0, "revisions_used": 0, "pending_call": None,
                              "pending_request_binding": None,
                              "call_bindings": [], "active": {}, "issues": []})
    return inspect(run)


def _response_evidence(response, binding):
    role = response["role"]
    return contracts.response_evidence(response, {**binding["protocol"][role], "role": role})


def _verify(run):
    run = Path(run).resolve()
    binding, state = core._read(run / "BINDING.json"), core._read(run / "state.json")
    if (binding.get("schema") != VERSION or binding.get("run_dir") != str(run)
            or core._read(run / "BINDING_ANCHOR.json").get("sha256") != core._digest(binding)):
        raise ValueError("任务冻结身份变化")
    snapshots = sorted(run.glob("STATE_*.json"))
    if not snapshots or core._read(snapshots[-1]) != state:
        raise ValueError("状态与不可变检查点不符")
    if binding["protocol"] != core._protocol() or core._read(run / "SOURCE.json") != binding["source"]:
        raise ValueError("协议或来源变化")
    for row in [binding["source_file"], *binding["source_evidence"], *binding["code_bindings"], *binding["registry"]]:
        core._verify_file(row)
    if binding.get("authorization"):
        core._verify_file(binding["authorization"])
        auth = _audit_authorization(binding["authorization"]["path"], run)
        _same_source(auth, binding["source"])
        if binding["budget"] != auth["new_budget"] or binding["legacy_consumption"] != auth["legacy_totals"]:
            raise ValueError("继承预算或历史用量变化")
    requests, responses = sorted(run.glob("REQUEST_*.json")), sorted(run.glob("RESPONSE_*.json"))
    if state["calls_started"] != len(requests) or len(responses) > len(requests):
        raise ValueError("调用账本与请求数不符")
    known = 0
    for number, path in enumerate(requests, 1):
        request = core._read(path)
        if (request.get("ordinal") != number or request.get("source_binding_id") != binding["source"]["binding_id"]
                or request.get("role") != ("writer" if request.get("stage") == "writer_full" else "director")):
            raise ValueError("原请求序列/来源/角色变化")
        response_path = run / f"RESPONSE_{number:03}.json"
        if response_path.exists():
            response = core._read(response_path)
            if (response.get("request_binding") != core._binding(path) or response.get("ordinal") != number
                    or response.get("role") != request["role"] or response.get("stage") != request["stage"]):
                raise ValueError("原生响应与请求身份不符")
            _, tokens, _ = _response_evidence(response, binding)
            # A receipt saved before its state checkpoint is adopted once on resume.
            adopted = response_path.resolve() in {Path(row["path"]).resolve() for row in state["call_bindings"]}
            if tokens is not None and adopted:
                known += tokens
    for row in state["call_bindings"]:
        core._verify_file(row)
    if state["pending_call"] is not None:
        pending_path = run / f"REQUEST_{state['pending_call']:03}.json"
        if state.get("pending_request_binding") != core._binding(pending_path):
            raise ValueError("未决请求冻结不符")
    if state["known_reported_tokens"] != known or (state["reported_tokens"] is not None and state["reported_tokens"] != known):
        raise ValueError("已知用量与原生账单不符")
    if state["pending_call"] is None and len(state["call_bindings"]) != 2 * len(requests):
        raise ValueError("原生证据缺失或存在未决请求")
    if not 0 <= state["revisions_used"] <= binding["budget"]["max_revisions"]:
        raise ValueError("内容返修计数不符")
    for row in state["active"].values():
        core._verify_file(row["file"])
        core._verify_file(row["receipt"])
    return binding, state


def _adopt_response(run, binding, state, number):
    request_path, response_path = run / f"REQUEST_{number:03}.json", run / f"RESPONSE_{number:03}.json"
    response = core._read(response_path)
    if response["request_binding"] != core._binding(request_path):
        raise ValueError("已收原生回执请求绑定变化")
    errors, tokens, text = _response_evidence(response, binding)
    existing = {row["path"] for row in state["call_bindings"]}
    for path in (request_path, response_path):
        if str(path.resolve()) not in existing:
            state["call_bindings"].append(core._binding(path))
    if str(response_path.resolve()) not in existing and tokens is not None:
        state["known_reported_tokens"] += tokens
    state["reported_tokens"] = state["known_reported_tokens"] if tokens is not None else None
    if errors:
        state.update(status="needs_attention", halt_reason="；".join(errors))
    else:
        state.update(pending_call=None, pending_request_binding=None, status="running")
    core._save_state(run, state)
    if errors:
        raise RuntimeError(state["halt_reason"])
    return text, core._binding(response_path)


def _dispatch(run, binding, state, stage, payload, clients):
    _verify(run)
    if state["pending_call"] is not None or state["status"] in TERMINAL:
        raise RuntimeError("任务已停止或存在未知请求")
    stage_key = core._digest({"stage": stage, "revision": state["revisions_used"], "payload": payload})
    for path in sorted(run.glob("REQUEST_*.json")):
        request = core._read(path)
        if request["stage_key"] == stage_key:
            response_path = run / f"RESPONSE_{request['ordinal']:03}.json"
            response = core._read(response_path)
            errors, _, text = _response_evidence(response, binding)
            if errors:
                raise RuntimeError("已收响应不可恢复，不重派")
            return text, core._binding(response_path)
    if _blockers(binding):
        raise RuntimeError("同故事存在未授权历史停止门")
    if state["calls_started"] >= binding["budget"]["max_calls"]:
        raise RuntimeError("调用预算耗尽")
    is_writer = stage == "writer_full"
    role = "writer" if is_writer else "director"
    messages = [{"role": "system", "content": binding["contracts"]["writer_prompt" if is_writer else "review_prompt"]},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
    parameters = {"max_tokens": 20000 if is_writer else 12000, "temperature": 0.4 if is_writer else 0.1,
                  "thinking": "disabled", "structured_schema": None}
    request_bytes = len(json.dumps({"messages": messages, "parameters": parameters}, ensure_ascii=False).encode("utf-8"))
    reservation = request_bytes + parameters["max_tokens"] + 4096
    if request_bytes > core.MAX_REQUEST_BYTES or state["known_reported_tokens"] + reservation > binding["budget"]["max_total_tokens"]:
        raise RuntimeError("完整输入或累计token预留超过预算，未截文未派发")
    number = state["calls_started"] + 1
    request_path = run / f"REQUEST_{number:03}.json"
    request = {"schema": VERSION, "ordinal": number, "stage": stage, "stage_key": stage_key, "role": role,
               "source_binding_id": binding["source"]["binding_id"], "messages": messages, "parameters": parameters,
               "payload_sha256": core._digest(payload), "input_bindings": deepcopy(state["active"]),
               "reservation_tokens": reservation}
    # Final admission remains inside the execution lock, immediately before the
    # immutable request and state checkpoint. No legacy request is ever replayed.
    _verify(run)
    if _blockers(binding):
        raise RuntimeError("派发前历史停止门变化")
    core._write(request_path, request)
    state.update(calls_started=number, pending_call=number, pending_request_binding=core._binding(request_path), status="running")
    core._save_state(run, state)
    response = {"schema": VERSION, "ordinal": number, "stage": stage, "role": role,
                "request_binding": core._binding(request_path)}
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
    data, path = text.encode("utf-8"), Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("既有正文与原生响应不符")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def _context(binding, state):
    payload = {"source": binding["source"]}
    if "writer_full" in state["active"]:
        row = state["active"]["writer_full"]
        payload["screenplay"] = Path(row["file"]["path"]).read_bytes().decode("utf-8")
    return payload


def _review_value(text):
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    return core._parse(fenced.group(1).strip() if fenced else text)


def _complete(run, binding, state):
    draft = Path(state["active"]["writer_full"]["file"]["path"]).read_bytes().decode("utf-8")
    review = core._read(state["active"]["review_full"]["file"]["path"])
    if contracts.validate_review(review) or review["verdict"] != "pass":
        raise ValueError("全文审核未通过")
    _ensure_text(run / "SCREENPLAY.md", draft)
    core._ensure(run / "FULL_TEXT_REVIEW.json", review)
    handoff = {"schema": VERSION, "status": "text_ready_for_director", "source": binding["source"],
               "screenplay": core._binding(run / "SCREENPLAY.md"), "review": core._binding(run / "FULL_TEXT_REVIEW.json"),
               "stages": deepcopy(state["active"]), "human_approved": False, "automatic_media_submit": False,
               "next_stage": "director_planning_not_yet_generated"}
    core._ensure(run / "DIRECTOR_HANDOFF.json", handoff)
    manifest = {"schema": VERSION, "source_binding_id": binding["source"]["binding_id"],
                "files": [core._binding(run / name) for name in ("SCREENPLAY.md", "FULL_TEXT_REVIEW.json", "DIRECTOR_HANDOFF.json")],
                "stages": deepcopy(state["active"]), "human_approved": False}
    core._ensure(run / "OUTPUT_MANIFEST.json", manifest)
    state.update(status="text_ready_for_director", stage="complete", output_manifest=core._binding(run / "OUTPUT_MANIFEST.json"))
    core._save_state(run, state)


def execute(run_dir, *, clients=None):
    run = Path(run_dir).resolve()
    with core._lock(run / ".execution.lock") as owner:
        binding, state = _verify(run)
        if state["status"] in TERMINAL:
            return inspect(run, _lock_owner=owner)
        clients = clients or CreativeRoleClients()
        try:
            if state["pending_call"] is not None:
                pending = state["pending_call"]
                if not (run / f"RESPONSE_{pending:03}.json").exists():
                    raise RuntimeError("旧请求结果未知，不重新派发")
                _adopt_response(run, binding, state, pending)
            while True:
                if state["stage"] == "complete":
                    _complete(run, binding, state)
                    return inspect(run, _lock_owner=owner)
                stage = state["stage"]
                payload = _context(binding, state)
                if stage == "review_full":
                    payload["review_schema"] = binding["contracts"]["review_schema"]
                elif state.get("previous"):
                    payload.update(previous_draft=state["previous"], review=state["issues"])
                text, receipt = _dispatch(run, binding, state, stage, payload, clients)
                number = core._read(receipt["path"])["ordinal"]
                if stage == "writer_full":
                    path = run / f"DRAFT_{number:03}.md"
                    _ensure_text(path, text)
                    state["active"] = {"writer_full": {"stage": stage, "file": core._binding(path), "receipt": receipt}}
                    state.update(stage="review_full", status="running", previous=None, issues=[])
                    core._save_state(run, state)
                    continue
                try:
                    value = _review_value(text)
                    issues = contracts.validate_review(value)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError("全文审核格式不可读；保存原生证据停止：" + str(exc)) from None
                output = run / f"REVIEW_{number:03}.json"
                core._ensure(output, value)
                core._ensure(run / f"REVIEW_VALIDATION_{number:03}.json", {"issues": issues, "receipt": receipt,
                              "writer": state["active"]["writer_full"], "source_binding_id": binding["source"]["binding_id"]})
                if issues:
                    raise RuntimeError("全文审核合同无效，不以格式问题重写内容")
                state["active"]["review_full"] = {"stage": stage, "file": core._binding(output), "receipt": receipt}
                if value["verdict"] == "pass":
                    state.update(stage="complete")
                    core._save_state(run, state)
                    _complete(run, binding, state)
                    return inspect(run, _lock_owner=owner)
                if state["revisions_used"] >= binding["budget"]["max_revisions"]:
                    state.update(status="content_revision_exhausted", halt_reason="完整内容返修上限已到，保留未通过稿")
                    core._save_state(run, state)
                    return inspect(run, _lock_owner=owner)
                state.update(previous=payload["screenplay"], issues=value, active={}, stage="writer_full",
                             revisions_used=state["revisions_used"] + 1, status="needs_full_revision")
                core._save_state(run, state)
        except Exception as exc:
            # If a receipt/state write failed, preserve its pending checkpoint.
            # Re-entry only adopts the already saved response; it never resends.
            if core._read(run / "state.json") == state:
                pending = state.get("pending_call")
                if state["status"] != "needs_attention" and pending is not None and (run / f"RESPONSE_{pending:03}.json").exists():
                    # Receipt already saved, but checkpoint publication failed.
                    # Leave the previous pending checkpoint for safe adoption.
                    pass
                else:
                    state.update(status="needs_attention", halt_reason=str(exc))
                    core._save_state(run, state)
            raise


def _verify_complete(run, binding, state):
    core._verify_file(state["output_manifest"])
    manifest = core._read(run / "OUTPUT_MANIFEST.json")
    if manifest.get("source_binding_id") != binding["source"]["binding_id"] or manifest.get("stages") != state["active"]:
        raise ValueError("交付清单与同源稿件不符")
    for row in manifest["files"]:
        core._verify_file(row)
    draft = Path(state["active"]["writer_full"]["file"]["path"]).read_bytes().decode("utf-8")
    review = core._read(state["active"]["review_full"]["file"]["path"])
    if contracts.validate_review(review) or review["verdict"] != "pass":
        raise ValueError("同稿全文审查未通过")
    for stage, row in state["active"].items():
        response = core._read(row["receipt"]["path"])
        request = core._read(response["request_binding"]["path"])
        errors, _, native_text = _response_evidence(response, binding)
        payload = core._parse(request["messages"][-1]["content"])
        if errors or request["stage"] != stage or payload.get("source") != binding["source"]:
            raise ValueError("终态不是同源原生响应")
        if stage == "writer_full" and native_text != draft:
            raise ValueError("完整稿不是原生正文")
        if stage == "review_full" and (payload.get("screenplay") != draft or _review_value(native_text) != review
                                      or request["input_bindings"].get("writer_full") != state["active"]["writer_full"]):
            raise ValueError("DeepSeek没有审核完整同一稿")
    if (run / "SCREENPLAY.md").read_bytes() != draft.encode("utf-8") or core._read(run / "FULL_TEXT_REVIEW.json") != review:
        raise ValueError("交付与原生全文不符")
    return manifest


def inspect(run_dir, *, _lock_owner=None):
    run = Path(run_dir).resolve()
    if not (run / "BINDING.json").exists():
        return {"schema": VERSION, "run_dir": str(run), "status": "unprepared", "artifacts": {}, "dispatch_blocked": True,
                "blockers": ["任务未准备"], "human_approved": False}
    binding, state = core._read(run / "BINDING.json"), core._read(run / "state.json")
    status, blockers, manifest = state["status"], [], None
    try:
        _verify(run)
        if status == "text_ready_for_director":
            manifest = _verify_complete(run, binding, state)
    except Exception as exc:
        status = "incomplete_artifacts" if state["status"] == "text_ready_for_director" else "evidence_invalid"
        blockers.append(str(exc))
    blockers += [row["reason"] for row in binding.get("legacy_blockers", [])]
    if state.get("pending_call") is not None:
        blockers.append("保留已派发请求门，不自动重派")
    if state.get("halt_reason"):
        blockers.append(state["halt_reason"])
    lock = run / ".execution.lock"
    if lock.exists() and core._read(lock).get("owner") != _lock_owner:
        blockers.append("执行锁存在")
    old = binding["legacy_consumption"]
    return {"schema": VERSION, "run_dir": str(run), "status": status, "stage": state["stage"], "state": state,
            "source": {key: value for key, value in binding["source"].items() if key != "text"},
            "calls_started": state["calls_started"], "known_reported_tokens": state["known_reported_tokens"],
            "reported_tokens": state["reported_tokens"], "pending_call": state["pending_call"],
            "legacy_consumption": old, "combined_calls_started": old["calls_started"] + state["calls_started"],
            "combined_known_reported_tokens": old["reported_tokens"] + state["known_reported_tokens"],
            "blockers": blockers, "dispatch_blocked": bool(blockers) or status in TERMINAL,
            "artifacts": {Path(row["path"]).name: row["path"] for row in manifest["files"]} if manifest else {},
            "human_approved": False, "automatic_media_submit": False}


def preview(run_dir):
    view = inspect(run_dir)
    if view["status"] == "unprepared":
        return view
    binding = core._read(Path(run_dir) / "BINDING.json")
    return {**view, "budget": binding["budget"], "provider_protocol": binding["protocol"],
            "remaining_calls": max(0, binding["budget"]["max_calls"] - view["calls_started"]),
            "remaining_known_tokens": max(0, binding["budget"]["max_total_tokens"] - view["known_reported_tokens"]),
            "stages": ["writer_full", "review_full"]}
