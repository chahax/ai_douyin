"""Parameterized read-only accounting for a settled scope diagnostic probe."""
from __future__ import annotations

from copy import deepcopy
import base64
from datetime import datetime
import hashlib
import os
from pathlib import Path
import sqlite3

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_session_spend_anchor_v1 as session

VERSION = "creative_legal_scope_probe_spend_anchor/v1"
PROBE_VERSION = "creative_legal_scope_probe/v1"
PROJECT = Path(__file__).resolve().parents[1]
TERMINAL = {"diagnostic_completed_not_creative", "halt_case_routing_mismatch", "halt_case_contract_rejected",
    "halt_scope_contract_rejected", "halt_scope_textual_ambiguity", "halt_protocol_requires_diagnosis"}
read, digest, sha_file = io.read, io.digest, io.sha_file
require = session._require


def verify_parent_anchor(anchor, *, expected_anchor_sha256, ancestors=()):
    if anchor.get("schema") == session.VERSION:
        return session.verify_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256)
    require(anchor.get("schema") == VERSION, "unsupported parent accounting-anchor schema")
    return verify_probe_spend_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256, _ancestors=ancestors)


def claim_paths(parent, canonical_sha256):
    root = os.path.normcase(str(Path(parent["root"]).resolve()))
    return (PROJECT / "data/creative_consumption_successors" / canonical_sha256 / "CLAIM.json",
        PROJECT / "data/creative_consumption_successors/by_parent_session" / digest(root) / "CLAIM.json")


def verify_known_receipt(root, row, manifest, reader):
    """Accounting only, preserving even a known protocol failure as failure.

    Complete tool documents use the exact Session SDK verifier. A complete
    missing/invalid-tool response can carry known cost without adopting a body
    as a tool. Unknown/truncated results never become settled anchors.
    """
    path = session._inside(Path(root) / row["receipt"], root)
    reader.verify(path, row["receipt_sha256"])
    receipt = reader.json(path)
    if receipt.get("status") in ("contract_valid", "contract_rejected"):
        result = session.verify_original_receipt(root, row, manifest, reader=reader)
    else:
        require(receipt.get("status") == "interface_rejected", "unsettled native probe result")
        request = receipt["request"]
        require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
            and receipt.get("request_sha256") == digest(request) and receipt.get("source_binding_sha256") == digest(manifest)
            and receipt.get("token_reservation") == row["token_reservation"], "protocol-failure receipt identity changed")
        evidence = receipt["call_evidence"]
        directory = session._inside(Path(root) / evidence["directory"], Path(root) / "call_evidence")
        identity = {"ordinal": receipt["ordinal"], "label": receipt["label"], "request_sha256": receipt["request_sha256"],
            "source_binding_sha256": receipt["source_binding_sha256"], "role": request["role"], "model": request["model"]}
        identity_sha = digest(identity)
        require(reader.json(directory / "IDENTITY.json") == {"schema": "creative_call_evidence/v1", "identity": identity,
            "identity_sha256": identity_sha} and evidence["identity_sha256"] == identity_sha, "original protocol SDK identity changed")
        session._wire(reader, directory, request, identity_sha)
        payload, raw, body = session._body(reader, directory, "response", identity_sha)
        meta = receipt["response_metadata"]
        require(payload == receipt.get("response_payload") and meta.get("raw_body_sha256") == hashlib.sha256(raw).hexdigest()
            and body.get("http_metadata", {}).get("http_status_code") == meta.get("http_status_code"), "original protocol response bytes changed")
        phases = []
        for index, p in enumerate(sorted(directory.glob("event_*.json")), 1):
            event = reader.json(p)
            require(event.get("sequence") == index and event.get("identity_sha256") == identity_sha, "original SDK journal changed")
            phases.append(event.get("phase"))
        require(all(phases.count(k) == 1 for k in ("dispatch_attempt_started", "request_body_saved", "response_body_saved")),
            "complete single SDK attempt required for protocol cost")
        result = receipt
    meta, payload = result.get("response_metadata", {}), result.get("response_payload", {})
    choices = payload.get("choices", [])
    require(type(meta.get("http_status_code")) is int and 200 <= meta["http_status_code"] < 300
        and meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop", "tool_calls")
        and len(choices) == 1 and meta["finish_reason"] == choices[0].get("finish_reason")
        and meta.get("response_id") == payload.get("id") and type(meta.get("response_id")) is str and bool(meta["response_id"])
        and meta.get("requested_model") == meta.get("response_model") == payload.get("model") == result["request"]["model"]
        and result.get("automatic_retry") is False and result.get("semantic_approval") is False and bool(result.get("completed_at")),
        "unknown, truncated or unmatched native model response cannot be settled")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        require(type(meta.get(key)) is int and meta[key] >= 0 and type(payload.get("usage", {}).get(key)) is int
            and meta[key] == payload["usage"][key], "known original integer usage required")
    require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
    return result


def _verify_tasks(reader, root, ledger, receipts, grant):
    """Read the original committed SQLite bytes without opening its WAL."""
    path = root / "TASKS.sqlite3"
    for suffix in ("-wal", "-journal"):
        side = Path(str(path) + suffix)
        require(not side.exists() or not reader.bytes(side), "active task journal; probe is unsettled")
    memory = bytearray(reader.bytes(path))
    require(memory[:16] == b"SQLite format 3\x00", "original settled task database required")
    memory[18:20] = b"\x01\x01"
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row; conn.deserialize(bytes(memory))
        attempts = [dict(x) for x in conn.execute("SELECT * FROM attempts ORDER BY rowid")]
        graphs = {x["graph_id"]: dict(x) for x in conn.execute("SELECT * FROM graphs")}
        grants = {x["authorization_id"]: dict(x) for x in conn.execute("SELECT * FROM authorizations")}
        nodes = {(x["graph_id"], x["node_id"]): dict(x) for x in conn.execute("SELECT * FROM nodes")}
        revisions = {(x["graph_id"], x["node_id"], x["revision"]): dict(x) for x in conn.execute("SELECT * FROM revisions")}
    from scripts import creative_fresh_source_session_v1 as native_protocol
    scope = reader.json(root / "USER_SCOPE.json")
    require(len(attempts) == len(receipts) == len(graphs) == len(grants), "missing/orphan durable task claim")
    require(len(nodes) == len(revisions) == 2 * len(receipts), "orphan/unconsumed task node/revision")
    require(len({a["claim_id"] for a in attempts}) == len(attempts), "duplicate task claim")
    for attempt, receipt in zip(attempts, receipts):
        gid = "call_" + digest([grant, receipt["label"]])[:24]
        request = io.strict_json(attempt["request"])
        result = io.strict_json(attempt["result"] or "{}")
        graph = io.strict_json(graphs[gid]["definition"]) if gid in graphs else {}
        expected_graph = {"schema_version": "creative_studio_dag/v1", "graph_id": gid, "nodes": [
            {"node_id": "source", "kind": "source", "input": {"source_manifest": digest(ledger["source_manifest"]),
                "request_sha256": receipt["request_sha256"]}, "depends_on": []},
            {"node_id": "result", "kind": "text", "input": {"label": receipt["label"], "stage": receipt["request"]["stage"]}, "depends_on": ["source"]}]}
        source_input_sha = digest(expected_graph["nodes"][0]["input"])
        source_sha = digest({"source": source_input_sha})
        bindings = [{"node_id": "source", "revision": 1, "input_sha256": source_input_sha, "output_sha256": source_input_sha}]
        expected_auth = {"schema_version": "creative_studio_authorization/v1", "authorization_id": gid + ":scope", "graph_id": gid,
            "node_ids": ["result"], "scope": "text", "purpose": "dispatch", "source_sha256": source_sha,
            "max_attempts": scope["stage_limits"][receipt["request"]["stage"]], "prior_attempts": 0, "allows_content_revision": False,
            "evidence_ref": str(root / "USER_SCOPE.json") + "#" + receipt["request"]["stage"], "evidence_sha256": sha_file(root / "USER_SCOPE.json")}
        auth = grants.get(gid + ":scope", {})
        require(auth.get("graph_id") == gid and io.strict_json(auth.get("body", "{}")) == expected_auth
            and auth.get("sha") == digest(expected_auth) and attempt["authorization_id"] == expected_auth["authorization_id"]
            and io.strict_json('{"bindings":' + attempt["bindings"] + '}')["bindings"] == bindings
            and attempt["revision"] == attempt["attempt_index"] == 1
            and attempt["identity_sha"] == digest({"graph_id": gid, "node_id": "result", "revision": 1,
                "request_sha256": digest(request), "source_sha256": source_sha, "bindings": bindings}), "task claim/authorization binding differs")
        known, outcome, tool = native_protocol.Session.classify_native(receipt)
        require(known and outcome in ("completed", "content_rejected", "protocol_rejected"), "unsettled TaskStore outcome")
        for definition in expected_graph["nodes"]:
            node = nodes.get((gid, definition["node_id"]), {})
            revision = revisions.get((gid, definition["node_id"], 1), {})
            output = definition["input"] if definition["kind"] == "source" else result.get("output") if outcome == "completed" else None
            require(node.get("kind") == definition["kind"] and node.get("current_revision") == 1
                and io.strict_json('{"deps":' + node.get("dependencies", "[]") + '}')["deps"] == definition["depends_on"]
                and io.strict_json(revision.get("input", "{}")) == definition["input"] and revision.get("input_sha") == digest(definition["input"])
                and revision.get("status") == ("source_ready" if definition["kind"] == "source" else outcome)
                and (io.strict_json(revision["output"]) if revision.get("output") is not None else None) == output
                and revision.get("output_sha") == (digest(output) if output is not None else None), "task node status/output differs")
        raw = base64.b64decode(result.get("raw_receipt", {}).get("body", ""), validate=True)
        require(attempt["graph_id"] == gid and attempt["node_id"] == "result" and attempt["status"] == outcome
            and attempt["provider_id"] == receipt["request"]["model"] and attempt["service_task_id"] is None
            and request == {"provider_id": receipt["request"]["model"], "payload": receipt["request"]}
            and attempt["request_sha"] == digest(request) and attempt["result_sha"] == digest(result)
            and graph == expected_graph and graphs[gid]["sha"] == digest(graph)
            and result.get("schema_version") == "creative_studio_result/v1" and result.get("claim_id") == attempt["claim_id"]
            and result.get("request_sha256") == attempt["request_sha"] and result.get("service_task_id") is None
            and result.get("result_known") is True and result.get("usage_known") is True
            and result.get("complete") is True and result.get("complete_end") is True
            and result.get("schema_tool_status") == tool and result.get("outcome") == outcome
            and result.get("usage") == {"unit": "reported_tokens", "amount": receipt["response_metadata"]["total_tokens"]}
            and result.get("contract_valid") is (receipt["status"] == "contract_valid")
            and result.get("output") == {"ordinal": receipt["ordinal"], "native_output": receipt.get("output")}
            and result.get("raw_receipt", {}).get("encoding") == "base64"
            and result["raw_receipt"].get("http_status") == receipt["response_metadata"]["http_status_code"]
            and hashlib.sha256(raw).hexdigest() == result["raw_receipt"].get("sha256") == receipt["response_metadata"]["raw_body_sha256"],
            "durable claim/result identity differs from original SDK result")


def build_probe_spend_anchor(probe_root, *, _ancestors=()):
    root = session._inside(probe_root, PROJECT)
    require(str(root) not in _ancestors and len(_ancestors) < 100, "cyclic/excessive probe ancestry")
    reader = session.Reader()
    config, freeze, state, ledger, scope, authorization = (reader.json(root / (n + ".json")) for n in
        ("PROBE_CONFIG", "PRODUCTION_FREEZE", "STATE", "CALL_LEDGER", "USER_SCOPE", "AUTHORIZATION"))
    require(freeze.get("schema") == PROBE_VERSION + "/freeze" and state.get("schema") == PROBE_VERSION + "/state"
        and state.get("status") in TERMINAL and state.get("spend_verification_pending") is False
        and Path(config["root"]).resolve() == root, "known settled probe terminal schema/root required")
    parent_path = session._inside(config["parent_anchor_path"], PROJECT)
    parent = reader.json(parent_path)
    verified = verify_parent_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"], ancestors=(*_ancestors, str(root)))
    inherited = session._spend(verified["inherited"])
    manifest = {}
    for path, expected in freeze["files"].items():
        source = session._inside(path, PROJECT)
        require(str(source) == path, "canonical frozen probe dependency required")
        reader.verify(source, expected)
        rel = source.relative_to(PROJECT).as_posix()
        require(rel not in manifest, "duplicate source identity")
        manifest[rel] = expected
        reader.verify(root / "source_at_dispatch" / rel, expected)
    required = [root / (n + ".json") for n in ("PROBE_CONFIG", "PREPARED_PROBE", "USER_SCOPE")]
    required += [Path(config[k]).resolve() for k in ("profile_path", "parent_anchor_path", "blinded_cases_path",
        "private_expectations_path", "goal_receipt_path", "authorization_path")]
    require(all(str(p) in freeze["files"] for p in required), "required original probe input absent from freeze")
    require(ledger.get("source_manifest") == manifest and ledger.get("starting_spend") == inherited == freeze.get("inherited") == scope.get("inherited") == authorization.get("starting_spend"),
        "full inherited probe accounting/source snapshot required")
    require(ledger.get("max_total_tokens") is None and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated"))
        and authorization.get("max_total_tokens") is None and authorization.get("media_calls_authorized") is False
        and sha_file(root / "AUTHORIZATION.json") == ledger.get("authorization_sha256"), "original no-reset text authorization changed")
    claim = PROJECT / "data/creative_diagnostic_probe_claims" / config["grant_id"] / "CLAIM.json"
    reader.verify(claim, freeze["claim_sha256"])
    require(reader.json(config["authorization_path"]) == scope, "frozen probe scope changed")
    auth_sha = sha_file(config["authorization_path"])
    canonical_claim, root_claim = claim_paths(parent, config["parent_anchor_sha256"])
    binding = {"schema": PROBE_VERSION + "/successor_claim", "anchor_sha256": config["parent_anchor_sha256"],
        "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"],
        "parent_identity_sha256": parent["parent_identity_sha256"], "root": str(root), "grant_id": config["grant_id"],
        "authorization_sha256": auth_sha, "old_budget_reset": False}
    for path in (canonical_claim, root_claim):
        require(str(path) in freeze["files"] and reader.json(path) == binding, "unique probe successor binding changed")
    grant = reader.json(claim)
    require(grant.get("root") == str(root) and grant.get("schema") == PROBE_VERSION + "/claim"
        and grant.get("authorization_sha256") == auth_sha and grant.get("grant_id") == config["grant_id"], "probe grant identity changed")
    run = reader.json(root / "RUN_CLAIM.json")
    require(set(run) == {"schema", "root", "grant_id", "prepared_sha256", "pid", "started_at", "automatic_restart"}
        and run["schema"] == PROBE_VERSION + "/run_claim" and run["root"] == str(root) and run["grant_id"] == config["grant_id"]
        and run["prepared_sha256"] == sha_file(root / "PREPARED_PROBE.json") and type(run["pid"]) is int and run["pid"] > 0
        and type(run["started_at"]) is str and bool(datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")).tzinfo)
        and run["automatic_restart"] is False and state.get("run_claim_sha256") == sha_file(root / "RUN_CLAIM.json"),
        "original exact non-restart probe run claim required")
    from scripts import creative_legal_scope_probe_v1 as execution
    profile = reader.json(config["profile_path"])
    execution.validate_profile(profile)
    require(scope.get("stage_limits") == execution.LIMITS and scope.get("new_deepseek_calls_limit") == 2
        and scope.get("writer_calls_limit") == 0 and scope.get("media_authorized") is False and scope.get("publish_authorized") is False,
        "original bounded diagnostic scope changed")
    calls = ledger.get("calls")
    require(type(calls) is list and 1 <= len(calls) <= 2 and [r.get("label") for r in calls] == execution.LABELS[:len(calls)], "exact ordered bounded probe calls required")
    require({p.name for p in root.iterdir() if p.is_file() and p.name.startswith("call_") and p.suffix == ".json"} == {r["receipt"] for r in calls}, "orphan/missing probe receipt")
    receipts = [verify_known_receipt(root, row, manifest, reader) for row in calls]
    require(all(type(row["ordinal"]) is int and row["ordinal"] == inherited["calls_started"] + index for index, row in enumerate(calls, 1)), "continuous inherited probe ordinals required")
    require(len({r["response_metadata"]["response_id"] for r in receipts}) == len(receipts), "duplicate response billing identity")
    prepared = reader.json(root / "PREPARED_PROBE.json")
    blind = reader.json(config["blinded_cases_path"])
    goal = reader.json(config["goal_receipt_path"])["output"]
    require(prepared["requests"] == [execution._prepared(blind, profile, case_frame=True),
        execution._prepared(goal, profile, case_frame=False)], "original request is not the complete frozen scope input")
    for index, receipt in enumerate(receipts):
        require(receipt["request"] == prepared["requests"][index]["request"] and receipt["request_sha256"] == prepared["requests"][index]["request_sha256"], "original prepared probe request changed")
        require(reader.json(root / "requests" / (receipt["label"] + ".json")) == prepared["requests"][index], "actual dispatched prepared file differs")
    require({p.stem for p in (root / "requests").glob("*.json")} == {r["label"] for r in receipts}, "undispatched or missing actual request evidence")
    _verify_tasks(reader, root, ledger, receipts, config["grant_id"])
    if len(receipts) == 2:
        require(receipts[0]["status"] == "contract_valid", "second diagnostic cannot follow rejected first contract")
        gate = execution.evaluate_cases(receipts[0]["output"], prepared["requests"][0], reader.json(config["private_expectations_path"]))
        require(gate["hard_route_gate_passed"] is True and reader.json(root / "CASE_GATE.json") == gate,
            "second diagnostic lacks original accepted hard-case route gate")
    last = receipts[-1]
    if last["status"] == "interface_rejected":
        expected_terminal = "halt_protocol_requires_diagnosis"
    elif last["status"] == "contract_rejected":
        expected_terminal = "halt_case_contract_rejected" if len(receipts) == 1 else "halt_scope_contract_rejected"
    elif len(receipts) == 1:
        gate = execution.evaluate_cases(last["output"], prepared["requests"][0], reader.json(config["private_expectations_path"]))
        require(gate["hard_route_gate_passed"] is False and reader.json(root / "CASE_GATE.json") == gate,
            "one-call terminal lacks actual failed hard-case gate")
        expected_terminal = "halt_case_routing_mismatch"
    else:
        decision = execution.scope.validate_scope(last["output"], goal, context_sha256=prepared["requests"][1]["context_sha256"])
        require(last.get("validation") == reader.json(root / "FULL_SCOPE_DECISION.json") == state.get("scope_decision") == decision,
            "full scope terminal differs from complete original native classification")
        expected_terminal = "halt_scope_textual_ambiguity" if decision["known_text_content_requires_clarification"] else "diagnostic_completed_not_creative"
    require(state["status"] == expected_terminal and state.get("receipt_ordinal") == last["ordinal"], "native result and terminal branch disagree")
    summary = execution.accounting_summary(inherited, receipts, unknown_reservations=0)
    require(digest(state.get("spend")) == digest(summary), "original terminal probe spend differs")
    if (root / "RESULT.json").exists(): require(reader.json(root / "RESULT.json") == summary, "original optional RESULT differs")
    require(all(state.get(k) is False for k in ("creative_quality_passed", "text_ready_for_director", "media_authorized")), "diagnostic proof cannot adopt creative content")
    final = {"calls_started": summary["effective_calls_started"], "reported_tokens": summary["effective_reported_tokens"],
        "calls_with_known_usage": summary["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}
    identity = {"root": str(root), "terminal_state_sha256": sha_file(root / "STATE.json"), "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"), "end_ordinal": final["calls_started"]}
    reader.bytes(__file__)
    return {"schema": VERSION, "root": str(root), "parent_anchor_path": str(parent_path), "parent_anchor_sha256": config["parent_anchor_sha256"],
        "inherited": final, "original_parent_inherited": inherited, "new_calls": [r["ordinal"] for r in receipts],
        "new_reported_tokens": summary["new_reported_tokens"], "whole_goal_candidates_used": parent["whole_goal_candidates_used"],
        "scope_probe_calls_used": parent.get("scope_probe_calls_used", 0) + len(receipts),
        "lineage_whole_plan_candidates_used": parent["whole_goal_candidates_used"],
        "inherited_whole_goal_candidates_used": parent["inherited_whole_goal_candidates_used"],
        "latest_native_goal_receipt": deepcopy(parent["latest_native_goal_receipt"]), "old_director_capacity": deepcopy(parent["old_director_capacity"]),
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "verified_files": reader.files,
        "verifier_code_sha256": sha_file(__file__), "terminal_status": state["status"], "historical_integrity_verified": True,
        "current_source_freshness_checked": False, "current_source_freshness_verified": False,
        "next_dispatch_requires_current_counted_round": True, "authorizes_new_dispatch": False,
        "creates_successor_claim": False, "media_authorized": False, "publish_authorized": False,
        "creative_quality_passed": False, "text_ready_for_director": False, "old_budget_reset": False}


def verify_probe_spend_anchor(anchor, *, expected_anchor_sha256, _ancestors=()):
    require(anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "probe anchor canonical identity changed")
    actual = build_probe_spend_anchor(anchor["root"], _ancestors=_ancestors)
    require(actual == anchor, "original probe source or accounting changed since anchor freeze")
    return {"verified": True, "root": actual["root"], "inherited": deepcopy(actual["inherited"]),
        "parent_identity": deepcopy(actual["parent_identity"]), "parent_identity_sha256": actual["parent_identity_sha256"],
        "whole_goal_candidates_used": actual["whole_goal_candidates_used"], "latest_native_goal_receipt": deepcopy(actual["latest_native_goal_receipt"]),
        "current_source_freshness_verified": False, "authorizes_new_dispatch": False}
