"""Explicit local policy helpers; no implicit stage, version or dispatch grant."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_fresh_source_session_v1 as native
from scripts import creative_session_spend_anchor_v1 as evidence
from src.content_factory import creative_studio_task_store_v1 as tasks
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "creative_scope_probe_execution_policy/v1"


def new_claim(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def successor_paths(project, parent, canonical_sha256):
    identity = os.path.normcase(str(Path(parent["root"]).resolve()))
    return (Path(project) / "data/creative_consumption_successors" / canonical_sha256 / "CLAIM.json",
        Path(project) / "data/creative_consumption_successors/by_parent_session" / io.digest(identity) / "CLAIM.json")


def accounting_summary(inherited, receipts, *, stage_limits, unknown_reservations):
    known = [r for r in receipts if type(r.get("response_metadata", {}).get("total_tokens")) is int
        and r["response_metadata"]["total_tokens"] >= 0]
    total = sum(r["response_metadata"]["total_tokens"] for r in known)
    stages = dict.fromkeys(stage_limits, 0)
    for receipt in receipts: stages[receipt["request"]["stage"]] += 1
    return {"schema": "authorized_creative_continuation/v3", "new_calls": len(receipts),
        "effective_calls_started": inherited["calls_started"] + len(receipts), "new_reported_tokens": total,
        "effective_reported_tokens": inherited["reported_tokens"] + total,
        "unknown_token_reservations": inherited["unknown_token_reservations"] + unknown_reservations,
        "max_total_tokens": None, "unbounded_aggregate_text_authorized": True, "old_budget_reset": False,
        "old_governance_migrated": False, "media_calls": 0, "semantic_approval": False,
        "new_unknown_token_reservations": unknown_reservations,
        "inherited_unknown_token_reservations": inherited["unknown_token_reservations"],
        "historical_pending_ordinals": deepcopy(inherited["pending_ordinals"]), "new_calls_with_known_usage": len(known),
        "effective_calls_with_known_usage": inherited["calls_with_known_usage"] + len(known),
        "stage_calls": stages, "stage_limits": deepcopy(stage_limits)}


def dispatch_claimed(runtime, label, prepared, validator, *, root, grant_id, stage_limits,
                     current_round_root, current_round_key, guard):
    """Claim before calling runtime; its own locked admission remains mandatory."""
    root = Path(root).resolve(); request = prepared["request"]
    if root != Path(runtime.root).resolve(): raise ValueError("task root differs from actual runtime root")
    if (type(stage_limits) is not dict or set(stage_limits) != set(runtime.stage_limits)
            or any(type(v) is not int or type(runtime.stage_limits[k]) is not int or v != runtime.stage_limits[k]
                   for k, v in stage_limits.items())):
        raise ValueError("task stage policy differs from actual runtime policy")
    guard(); CountedExecution(current_round_root).assert_dispatch_allowed(current_round_key)
    if request["stage"] not in stage_limits or stage_limits[request["stage"]] <= 0:
        raise ValueError("explicit stage policy does not permit this dispatch")
    if any(row["label"] == label for row in io.read(runtime.ledger)["calls"]):
        raise ValueError("already dispatched label cannot replay")
    io.write(root / "requests" / (label + ".json"), prepared, True)
    store = tasks.TaskStore(root / "TASKS.sqlite3")
    gid = "call_" + io.digest([grant_id, label])[:24]
    store.register_graph({"schema_version": tasks.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
        {"node_id": "source", "kind": "source", "input": {"source_manifest": io.digest(io.read(runtime.ledger)["source_manifest"]),
            "request_sha256": io.digest(request)}, "depends_on": []},
        {"node_id": "result", "kind": "text", "input": {"label": label, "stage": request["stage"]}, "depends_on": ["source"]}]})
    scope = root / "USER_SCOPE.json"
    attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, {
        "schema_version": tasks.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid, "node_ids": ["result"],
        "scope": "text", "purpose": "dispatch", "source_sha256": store.snapshot(gid)["source_sha256"],
        "max_attempts": stage_limits[request["stage"]], "prior_attempts": 0, "allows_content_revision": False,
        "evidence_ref": str(scope) + "#" + request["stage"], "evidence_sha256": io.sha_file(scope)})
    receipt = runtime.dispatch(label, request, validator)
    directory = evidence._inside(root / receipt["call_evidence"]["directory"], root / "call_evidence")
    raw = (directory / "response_body.raw").read_bytes() if (directory / "response_body.raw").exists() else b""
    known, outcome, tool = native.Session.classify_native(receipt)
    meta = receipt.get("response_metadata", {}); total = meta.get("total_tokens")
    store.accept_result(attempt["claim_id"], {"schema_version": tasks.RESULT_SCHEMA, "claim_id": attempt["claim_id"],
        "request_sha256": attempt["request_sha256"], "service_task_id": None, "outcome": outcome, "result_known": known,
        "usage_known": type(total) is int and total >= 0,
        "usage": {"unit": "reported_tokens", "amount": total} if type(total) is int and total >= 0 else None,
        "complete": meta.get("response_body_complete") is True, "complete_end": meta.get("finish_reason") in ("stop", "tool_calls"),
        "schema_tool_status": tool, "contract_valid": receipt["status"] == "contract_valid" if known else None,
        "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest(), "http_status": meta.get("http_status_code")},
        "output": {"ordinal": receipt["ordinal"], "native_output": receipt.get("output")}})
    return receipt
