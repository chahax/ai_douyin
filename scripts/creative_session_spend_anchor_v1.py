"""Read-only settled Session accounting, independent of live admission gates.

No runtime/client/claim is constructed here. A successor must separately verify
current source freshness, current repair-round admission and its unique claim.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import sqlite3

from scripts import creative_probe_spend_anchor_v1 as probe
from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_m31_flash_role_clients_v1 as ordinary
from scripts import creative_deepseek_strict_role_clients_v5 as strict

VERSION = "creative_session_spend_anchor/v1"
PROJECT = Path(__file__).resolve().parents[1]
SESSION_VERSIONS = {"creative_fresh_source_session/v1", "creative_fresh_source_session/v2"}
TERMINAL_STATES = {
    "halt_contract_requires_pipeline_diagnosis", "halt_goal_content_requires_pipeline_diagnosis",
    "halt_opening_setup_capacity_exhausted", "halt_complete_script_capacity_exhausted",
    "halt_full_review_bundle_contract_requires_pipeline_diagnosis", "halt_full_review_uncertain",
    "halt_full_review_requires_new_complete_goal", "halt_same_story_prior_allowance_exhausted",
    "halt_prior_story_relation_unknown", "halt_plan_capacity_exhausted", "text_ready_for_director",
    "halt_whole_plan_lineage_capacity_exhausted", "halt_goal_audit_uncertain",
    "halt_goal_audit_contract_requires_diagnosis",
}
STAGES = {"goal_plan": "writer", "goal_audit": "director", "complete_script": "writer", "full_review": "director"}
SPEND_KEYS = {"calls_started", "reported_tokens", "calls_with_known_usage", "pending_ordinals", "unknown_token_reservations"}
read, digest, sha_file = io.read, io.digest, io.sha_file


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value):
    return type(value) is int and value >= 0


def _spend(value):
    _require(type(value) is dict and set(value) == SPEND_KEYS, "complete inherited spend required")
    _require(all(_integer(value[k]) for k in SPEND_KEYS - {"pending_ordinals"}), "typed nonnegative inherited spend required")
    pending = value["pending_ordinals"]
    _require(type(pending) is list and all(type(x) is int and 0 < x <= value["calls_started"] for x in pending)
             and pending == sorted(set(pending)), "ordered original pending ordinals required")
    _require(value["calls_with_known_usage"] + len(pending) == value["calls_started"], "known and historical pending counts differ")
    return deepcopy(value)


class Reader:
    """Per-verification file inventory; never persist a verification cache."""
    def __init__(self):
        self.files = {}

    def bytes(self, path):
        path = Path(path).resolve()
        raw = path.read_bytes()
        entry = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        _require(str(path) not in self.files or self.files[str(path)] == entry, "file changed during verification: " + str(path))
        self.files[str(path)] = entry
        return raw

    def json(self, path):
        return io.strict_json(self.bytes(path).decode("utf-8-sig"))

    def verify(self, path, expected):
        _require(type(expected) is str and re.fullmatch(r"[a-f0-9]{64}", expected), "complete file SHA required")
        self.bytes(path)
        _require(self.files[str(Path(path).resolve())]["sha256"] == expected, "original frozen file changed: " + str(path))


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    _require(path.is_relative_to(root) and path != root, "path escapes bound root: " + str(path))
    return path


def _body(reader, directory, name, identity_sha):
    manifest = reader.json(directory / (name.upper() + "_BODY_MANIFEST.json"))
    path = _inside(directory / manifest.get("body_file", ""), directory)
    raw = reader.bytes(path)
    actual = hashlib.sha256(raw).hexdigest()
    _require(manifest.get("identity_sha256") == identity_sha and manifest.get("body_complete") is True
             and manifest.get("raw_bytes_preserved") is True and manifest.get("credential_redacted") is False
             and manifest.get("stored_sha256") == manifest.get("original_sha256") == actual
             and type(manifest.get("bytes")) is int and manifest["bytes"] == len(raw)
             and manifest.get("original_bytes", len(raw)) == len(raw), "original complete " + name + " body required")
    return io.strict_json(raw.decode("utf-8")), raw, manifest


def _wire(reader, directory, request, identity_sha):
    actual, raw, _ = _body(reader, directory, "request", identity_sha)
    is_strict = (directory / "DEEPSEEK_STRICT_WIRE_PREFLIGHT.json").exists()
    _require(not (is_strict and (directory / "M31_WIRE_PREFLIGHT.json").exists()), "conflicting outbound protocol proofs")
    proof = reader.json(directory / ("DEEPSEEK_STRICT_WIRE_PREFLIGHT.json" if is_strict else "M31_WIRE_PREFLIGHT.json"))
    if is_strict:
        _require(proof.get("schema") == strict.VERSION + "/outbound_proof", "unsupported strict transport schema")
        expected = strict.expected_wire_request(request)
        compilation = strict.schema_compilation_manifest(request)
        binding = strict.protocol_binding(request)
        _require(reader.json(directory / "DEEPSEEK_STRICT_SCHEMA_MANIFEST.json") == compilation
                 and request.get("input_provenance", {}).get("source_protocol_binding") == binding
                 and proof.get("source_protocol_binding_sha256") == digest(binding)
                 and proof.get("schema_compilation_manifest_sha256") == digest(compilation)
                 and proof.get("original_contract_sha256") == digest(request["structured_schema"])
                 and proof.get("service_schema_sha256") == digest(expected["tools"][0]["function"]["parameters"])
                 and proof.get("function_strict") is True and proof.get("server_strict_schema_requested") is True
                 and proof.get("original_local_contract_validation_required") is True
                 and type(proof.get("max_wire_utf8_bytes")) is int
                 and len(raw) <= proof["max_wire_utf8_bytes"] <= strict.MAX_BODY_BYTES,
                 "strict source6 projection or protocol binding changed")
    else:
        _require(proof.get("schema") == ordinary.VERSION + "/outbound_proof", "unsupported ordinary transport schema")
        expected = ordinary.expected_wire_request(request)
    host = "api.minimax.cn" if request["role"] == "writer" else "api.deepseek.com"
    operation = "/beta/chat/completions" if is_strict else "/v1/chat/completions"
    _require(actual == expected and proof.get("status") == "wire_verified_before_send"
             and proof.get("identity_sha256") == identity_sha
             and proof.get("logical_request_sha256") == digest(request)
             and proof.get("expected_wire_sha256") == proof.get("actual_wire_sha256") == digest(expected)
             and proof.get("actual_request_body_sha256") == hashlib.sha256(raw).hexdigest()
             and proof.get("body_bytes") == len(raw) and proof.get("mapped_fields") == sorted(expected)
             and proof.get("full_wire_equals_mapped_logical_request") is True
             and proof.get("messages_sha256") == digest(request["messages"])
             and proof.get("structured_schema_sha256") == digest(request["structured_schema"])
             and proof.get("provider_endpoint_host") == host
             and proof.get("endpoint_method") == "POST" and proof.get("endpoint_path") == operation
             and proof.get("verified_endpoint_sha256") == digest(["POST", "https://" + host + operation])
             and proof.get("writer_reasoning_effort") == ("medium" if request["role"] == "writer" else None)
             and type(proof.get("SDK_max_retries")) is int and proof["SDK_max_retries"] == 0
             and all(proof.get(k) is False for k in ("HTTP_follow_redirects", "server_stream_requested", "server_schema_guarantee",
                 "new_provider_acceptance_verified", "calls_authorized_by_proof", "automatic_retry"))
             and proof.get("provider_received_request") is None, "actual SDK wire or endpoint evidence differs")
    return expected, is_strict


def verify_original_receipt(root, row, manifest, *, reader=None):
    """Original SDK evidence, including source6 beta strict; no runtime gate."""
    reader = reader or Reader()
    root = Path(root).resolve()
    name = row.get("receipt")
    _require(type(name) is str and re.fullmatch(r"call_[0-9]+_[a-zA-Z0-9_]{1,90}\.json", name), "safe original receipt required")
    path = _inside(root / name, root)
    reader.verify(path, row.get("receipt_sha256"))
    receipt = reader.json(path)
    request = receipt.get("request")
    _require(type(request) is dict and receipt.get("ordinal") == row.get("ordinal")
             and receipt.get("label") == row.get("label") and receipt.get("request_sha256") == digest(request)
             and receipt.get("source_binding_sha256") == digest(manifest)
             and receipt.get("token_reservation") == row.get("token_reservation"), "original request/receipt/source identity differs")
    evidence = receipt.get("call_evidence", {})
    directory = Path(evidence.get("directory", ""))
    directory = _inside(directory if directory.is_absolute() else root / directory, root / "call_evidence")
    identity = {"ordinal": receipt["ordinal"], "label": receipt["label"], "request_sha256": receipt["request_sha256"],
        "source_binding_sha256": receipt["source_binding_sha256"], "role": request["role"], "model": request["model"]}
    identity_sha = digest(identity)
    _require(reader.json(directory / "IDENTITY.json") == {"schema": "creative_call_evidence/v1", "identity": identity,
             "identity_sha256": identity_sha} and evidence.get("identity_sha256") == identity_sha, "SDK evidence identity differs")
    wire, is_strict = _wire(reader, directory, request, identity_sha)
    payload, raw, body = _body(reader, directory, "response", identity_sha)
    metadata = receipt.get("response_metadata", {})
    _require(metadata.get("response_body_complete") is True and metadata.get("raw_body_sha256") == hashlib.sha256(raw).hexdigest()
             and body.get("http_metadata", {}).get("http_status_code") == metadata.get("http_status_code")
             and payload == receipt.get("response_payload") and metadata.get("strict_mode") is is_strict,
             "original response body/strict protocol differs")
    choices = payload.get("choices")
    _require(type(choices) is list and len(choices) == 1 and type(choices[0]) is dict, "single original response choice required")
    calls = choices[0].get("message", {}).get("tool_calls")
    _require(type(calls) is list and len(calls) == 1 and calls[0].get("type") == "function", "complete original tool result required")
    function = calls[0].get("function", {})
    _require(function.get("name") == wire["tools"][0]["function"]["name"]
             and function.get("arguments") == receipt.get("response_text")
             and io.strict_json(function["arguments"]) == receipt.get("output"), "original tool arguments differ")
    _require(metadata.get("requested_model") == metadata.get("response_model") == request["model"] == payload.get("model")
             and metadata.get("response_id") == payload.get("id") and type(payload.get("id")) is str and payload["id"]
             and metadata.get("finish_reason") == choices[0].get("finish_reason"), "original response model/finish differs")
    events = sorted(directory.glob("event_*.json"))
    phases = []
    for sequence, event_path in enumerate(events, 1):
        event = reader.json(event_path)
        _require(event.get("sequence") == sequence and event.get("identity_sha256") == identity_sha, "SDK journal sequence/identity differs")
        phases.append(event.get("phase"))
    _require(all(phases.count(p) == 1 for p in ("dispatch_attempt_started", "request_body_saved", "response_body_saved", "result_ready")),
             "single complete SDK dispatch journal required")
    return receipt


def validate_records(ledger, receipts, terminal, freeze, scope, authorization, inherited):
    """Pure exact accounting after source bytes and SDK evidence were checked."""
    inherited = _spend(inherited)
    _require(all(x == inherited for x in (ledger.get("starting_spend"), freeze.get("inherited"),
             scope.get("inherited"), authorization.get("starting_spend"))), "inherited consumption omitted or reset")
    _require(ledger.get("schema") == authorization.get("schema") == "authorized_creative_continuation/v3"
             and ledger.get("max_total_tokens") is authorization.get("max_total_tokens") is None
             and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated"))
             and all(authorization.get(k) is False for k in ("old_budget_reset", "old_governance_migrated", "media_calls_authorized"))
             and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
             "original text-only no-reset/no-retry scope required")
    calls = ledger.get("calls")
    _require(type(calls) is list and calls and len(calls) == len(receipts), "complete nonempty settled ledger required")
    limits = scope.get("stage_limits")
    _require(type(limits) is dict and set(limits) == set(STAGES) and all(_integer(x) for x in limits.values()), "typed original stage limits required")
    stages = dict.fromkeys(STAGES, 0)
    usage_total = 0
    seen_ids, seen_requests, seen_labels = set(), set(), set()
    for index, (row, receipt) in enumerate(zip(calls, receipts), 1):
        request, meta = receipt.get("request", {}), receipt.get("response_metadata", {})
        usage = receipt.get("response_payload", {}).get("usage", {})
        stage = request.get("stage")
        _require(type(row.get("ordinal")) is int and row["ordinal"] == inherited["calls_started"] + index
                 and receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row.get("label")
                 and _integer(row.get("token_reservation")) and row["token_reservation"] == receipt.get("token_reservation")
                 and stage in STAGES and request.get("role") == STAGES[stage], "contiguous original call/stage identity required")
        _require(receipt.get("status") in ("contract_valid", "contract_rejected")
                 and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False
                 and not receipt.get("cached_response_read_only") and bool(receipt.get("completed_at"))
                 and type(receipt.get("output")) is dict and bool(receipt["output"])
                 and type(meta.get("http_status_code")) is int and 200 <= meta["http_status_code"] < 300
                 and meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop", "tool_calls")
                 and meta.get("output_mode") == "tool_call" and not meta.get("response_fault_code"),
                 "unknown, truncated, protocol or incomplete native result cannot be anchored")
        if receipt["status"] == "contract_rejected":
            failure = receipt.get("failure", {})
            _require(failure.get("category") in ("validation", "state_contract", "compilation")
                     and failure.get("response_received") is True and failure.get("automatic_retry") is False,
                     "known full native content rejection required")
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            _require(_integer(meta.get(key)) and _integer(usage.get(key)) and meta[key] == usage[key], "known nonnegative original integer usage required")
        _require(meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "original usage sum differs")
        rid, req, label = meta.get("response_id"), receipt.get("request_sha256"), row.get("label")
        _require(type(rid) is str and bool(rid) and rid not in seen_ids and req not in seen_requests and label not in seen_labels,
                 "duplicate response, request or stage identity cannot be double-counted")
        seen_ids.add(rid); seen_requests.add(req); seen_labels.add(label)
        usage_total += meta["total_tokens"]
        stages[stage] += 1
    _require(all(stages[k] <= limits[k] for k in stages), "original stage capacity exceeded")
    expected = {"schema": "authorized_creative_continuation/v3", "new_calls": len(calls),
        "effective_calls_started": inherited["calls_started"] + len(calls), "new_reported_tokens": usage_total,
        "effective_reported_tokens": inherited["reported_tokens"] + usage_total,
        "unknown_token_reservations": inherited["unknown_token_reservations"], "max_total_tokens": None,
        "unbounded_aggregate_text_authorized": True, "old_budget_reset": False, "old_governance_migrated": False,
        "media_calls": 0, "semantic_approval": False, "new_unknown_token_reservations": 0,
        "inherited_unknown_token_reservations": inherited["unknown_token_reservations"],
        "historical_pending_ordinals": deepcopy(inherited["pending_ordinals"]), "new_calls_with_known_usage": len(calls),
        "effective_calls_with_known_usage": inherited["calls_with_known_usage"] + len(calls), "stage_calls": stages, "stage_limits": limits}
    summary = terminal.get("spend", {})
    _require(type(summary) is dict and all(type(summary.get(k)) is type(v) for k, v in expected.items()),
             "typed original terminal spend required")
    _require(terminal.get("status") in TERMINAL_STATES and terminal.get("spend_verification_pending") is False
             and digest(terminal.get("spend")) == digest(expected) and terminal.get("text_ready_for_director") is (terminal["status"] == "text_ready_for_director")
             and all(terminal.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized"))
             and terminal.get("old_director_capacity") == scope.get("old_director_capacity") == {"used": 7, "limit": 7, "remaining": 0},
             "nonterminal, unknown or inconsistent original STATE cannot be anchored")
    return {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}


def _tasks(reader, root, ledger, receipts, grant):
    path = root / "TASKS.sqlite3"
    for suffix in ("-wal", "-journal"):
        side = Path(str(path) + suffix)
        _require(not side.exists() or not reader.bytes(side), "active task SQLite journal; original session is unsettled")
    memory = bytearray(reader.bytes(path))
    _require(memory[:16] == b"SQLite format 3\x00", "original settled task database required")
    memory[18:20] = b"\x01\x01"
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.deserialize(bytes(memory))
        attempts = [dict(x) for x in conn.execute("SELECT * FROM attempts ORDER BY rowid")]
        graphs = {x["graph_id"]: dict(x) for x in conn.execute("SELECT * FROM graphs")}
        grants = {x["authorization_id"]: dict(x) for x in conn.execute("SELECT * FROM authorizations")}
        nodes = {(x["graph_id"], x["node_id"]): dict(x) for x in conn.execute("SELECT * FROM nodes")}
        revisions = {(x["graph_id"], x["node_id"], x["revision"]): dict(x) for x in conn.execute("SELECT * FROM revisions")}
    scope = reader.json(root / "USER_SCOPE.json")
    _require(len(attempts) == len(receipts) == len(graphs) == len(grants), "unreconciled or missing durable task claim")
    _require(len(nodes) == len(revisions) == 2 * len(receipts), "orphan or unconsumed task node/revision")
    for attempt, receipt in zip(attempts, receipts):
        gid = "call_" + digest([grant, receipt["label"]])[:24]
        request = io.strict_json(attempt["request"])
        result = io.strict_json(attempt["result"] or "{}")
        graph = io.strict_json(graphs[gid]["definition"]) if gid in graphs else {}
        expected_graph = {"schema_version": "creative_studio_dag/v1", "graph_id": gid, "nodes": [
            {"node_id": "source", "kind": "source", "input": {"source_manifest": digest(ledger["source_manifest"]), "request_sha256": receipt["request_sha256"]}, "depends_on": []},
            {"node_id": "result", "kind": "text", "input": {"label": receipt["label"], "stage": receipt["request"]["stage"]}, "depends_on": ["source"]}]}
        source_input_sha = digest(expected_graph["nodes"][0]["input"])
        source_sha = digest({"source": source_input_sha})
        bindings = [{"node_id": "source", "revision": 1, "input_sha256": source_input_sha, "output_sha256": source_input_sha}]
        expected_auth = {"schema_version": "creative_studio_authorization/v1", "authorization_id": gid + ":scope", "graph_id": gid,
            "node_ids": ["result"], "scope": "text", "purpose": "dispatch", "source_sha256": source_sha,
            "max_attempts": scope["stage_limits"][receipt["request"]["stage"]], "prior_attempts": 0,
            "allows_content_revision": False, "evidence_ref": str(root / "USER_SCOPE.json") + "#" + receipt["request"]["stage"],
            "evidence_sha256": sha_file(root / "USER_SCOPE.json")}
        grant_row = grants.get(gid + ":scope", {})
        _require(grant_row.get("graph_id") == gid and io.strict_json(grant_row.get("body", "{}")) == expected_auth
                 and grant_row.get("sha") == digest(expected_auth) and attempt["authorization_id"] == expected_auth["authorization_id"]
                 and io.strict_json('{"bindings":' + attempt["bindings"] + '}')["bindings"] == bindings
                 and attempt["revision"] == attempt["attempt_index"] == 1
                 and attempt["identity_sha"] == digest({"graph_id": gid, "node_id": "result", "revision": 1,
                     "request_sha256": digest(request), "source_sha256": source_sha, "bindings": bindings}),
                 "durable original task authorization/claim binding differs")
        raw = base64.b64decode(result.get("raw_receipt", {}).get("body", ""), validate=True)
        outcome = "completed" if receipt["status"] == "contract_valid" else "content_rejected"
        for definition in expected_graph["nodes"]:
            node = nodes.get((gid, definition["node_id"]), {})
            revision = revisions.get((gid, definition["node_id"], 1), {})
            output = definition["input"] if definition["kind"] == "source" else result.get("output") if outcome == "completed" else None
            _require(node.get("kind") == definition["kind"] and node.get("current_revision") == 1
                     and io.strict_json('{"deps":' + node.get("dependencies", "[]") + '}')["deps"] == definition["depends_on"]
                     and io.strict_json(revision.get("input", "{}")) == definition["input"]
                     and revision.get("input_sha") == digest(definition["input"])
                     and revision.get("status") == ("source_ready" if definition["kind"] == "source" else outcome)
                     and (io.strict_json(revision["output"]) if revision.get("output") is not None else None) == output
                     and revision.get("output_sha") == (digest(output) if output is not None else None),
                     "durable task node/revision differs from frozen graph and result")
        _require(attempt["graph_id"] == gid and attempt["node_id"] == "result" and attempt["status"] == outcome
                 and attempt["provider_id"] == receipt["request"]["model"] and attempt["service_task_id"] is None
                 and request == {"provider_id": receipt["request"]["model"], "payload": receipt["request"]}
                 and attempt["request_sha"] == digest(request) and attempt["result_sha"] == digest(result)
                 and graph == expected_graph and graphs[gid]["sha"] == digest(graph)
                 and result.get("claim_id") == attempt["claim_id"] and result.get("request_sha256") == attempt["request_sha"]
                 and result.get("result_known") is True and result.get("usage_known") is True
                 and result.get("complete") is True and result.get("complete_end") is True
                 and result.get("schema_tool_status") == "accepted" and result.get("outcome") == outcome
                 and result.get("usage") == {"unit": "reported_tokens", "amount": receipt["response_metadata"]["total_tokens"]}
                 and result.get("contract_valid") is (receipt["status"] == "contract_valid")
                 and result.get("output") == {"ordinal": receipt["ordinal"], "native_output": receipt["output"]}
                 and result.get("raw_receipt", {}).get("encoding") == "base64"
                 and result["raw_receipt"].get("http_status") == receipt["response_metadata"]["http_status_code"]
                 and hashlib.sha256(raw).hexdigest() == result["raw_receipt"].get("sha256") == receipt["response_metadata"]["raw_body_sha256"],
                 "durable original claim/result differs from native SDK receipt")


def _verify_parent(anchor, *, expected_sha256, session_version, ancestors):
    """Explicit supported ancestry protocols; never call production admission."""
    if session_version == "creative_fresh_source_session/v1":
        _require(anchor.get("schema") == probe.VERSION, "v1 requires original probe620 anchor")
        return probe.verify_anchor(anchor, expected_anchor_sha256=expected_sha256)
    _require(session_version == "creative_fresh_source_session/v2" and anchor.get("schema") == VERSION,
             "v2 requires a settled Session parent anchor")
    return verify_anchor(anchor, expected_anchor_sha256=expected_sha256, _ancestors=ancestors)


def build_anchor(session_root, *, _ancestors=()):
    """Deterministic audit only; never writes an anchor, claim or other file."""
    root = _inside(Path(session_root), PROJECT)
    _require(str(root) not in _ancestors and len(_ancestors) < 100, "cyclic or excessive session anchor ancestry")
    reader = Reader()
    config, freeze, state, ledger, scope, authorization = (reader.json(root / (n + ".json")) for n in
        ("SESSION_CONFIG", "PRODUCTION_FREEZE", "STATE", "CALL_LEDGER", "USER_SCOPE", "AUTHORIZATION"))
    version = str(freeze.get("schema", "")).removesuffix("/freeze")
    _require(version in SESSION_VERSIONS and state.get("schema") == version + "/state"
             and scope.get("schema") == version + "/derived_authorization" and Path(config.get("root", "")).resolve() == root,
             "unsupported or mismatched Session schema/root")
    _require(state.get("status") in TERMINAL_STATES and state.get("spend_verification_pending") is False,
             "original Session must have a known reconciled terminal STATE")
    parent_path = _inside(config["anchor_path"], PROJECT)
    parent_anchor = reader.json(parent_path)
    _require(digest(parent_anchor) == config.get("anchor_sha256"), "original parent canonical anchor changed")
    verified = _verify_parent(parent_anchor, expected_sha256=config["anchor_sha256"], session_version=version,
        ancestors=(*_ancestors, str(root)))
    _require(verified.get("verified") is True, "verified parent consumption required")
    inherited = _spend(verified["inherited"])
    files = freeze.get("files")
    _require(type(files) is dict and bool(files), "complete production freeze required")
    manifest = {}
    for name, expected in files.items():
        path = _inside(name, PROJECT)
        _require(str(path) == name, "canonical absolute frozen source path required")
        reader.verify(path, expected)
        rel = path.relative_to(PROJECT).as_posix()
        _require(rel not in manifest, "duplicate frozen source identity")
        manifest[rel] = expected
        reader.verify(_inside(root / "source_at_dispatch" / rel, root / "source_at_dispatch"), expected)
    _require(ledger.get("source_manifest") == manifest, "complete frozen source snapshot/ledger binding differs")
    for filename in ("SESSION_CONFIG.json", "INPUTS.json", "INPUT_EVIDENCE.json", "FIRST_REQUEST_PREVIEW.json", "USER_SCOPE.json"):
        _require(str(root / filename) in files, "required frozen Session input missing: " + filename)
    for name in ("profile_path", "anchor_path", "authorization_path"):
        _require(str(Path(config[name]).resolve()) in files, "required configured freeze dependency missing: " + name)
    _require(reader.json(config["authorization_path"]) == scope and reader.files[str((root / "AUTHORIZATION.json").resolve())]["sha256"] == ledger.get("authorization_sha256")
             and scope.get("anchor_sha256") == config["anchor_sha256"] and scope.get("grant_id") == config["grant_id"]
             and Path(scope.get("root", "")).resolve() == root and digest(reader.json(root / "INPUTS.json")) == freeze.get("inputs_sha256") == scope.get("inputs_sha256"),
             "original input, scope or runtime authorization binding differs")
    grant = config["grant_id"]
    _require(type(grant) is str and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", grant), "safe original grant required")
    claim_path = PROJECT / "data/creative_fresh_background_claims" / grant / "CLAIM.json"
    claim = reader.json(claim_path)
    reader.verify(claim_path, freeze.get("claim_sha256"))
    auth_sha = sha_file(config["authorization_path"])
    successor_path = PROJECT / "data/creative_consumption_successors" / config["anchor_sha256"] / "CLAIM.json"
    successor = reader.json(successor_path)
    _require(str(successor_path) in files and claim.get("schema") == version + "/claim"
             and successor.get("schema") == version + "/successor_claim"
             and all(x.get("root") == str(root) and x.get("grant_id") == grant and x.get("authorization_sha256") == auth_sha
                 and x.get("old_budget_reset") is False for x in (claim, successor))
             and successor.get("anchor_sha256") == config["anchor_sha256"], "original unique successor/claim binding differs")
    if version == "creative_fresh_source_session/v2":
        parent_identity = parent_anchor.get("parent_identity", {})
        parent_root = str(Path(parent_anchor["root"]).resolve())
        _require(parent_identity.get("root") == parent_root and parent_identity.get("end_ordinal") == inherited["calls_started"]
                 and parent_anchor.get("parent_identity_sha256") == digest(parent_identity), "verified real parent identity differs")
        parent_claim_path = PROJECT / "data/creative_consumption_successors/by_parent_session" / digest(os.path.normcase(parent_root)) / "CLAIM.json"
        expected_binding = {"schema": version + "/successor_claim", "anchor_sha256": config["anchor_sha256"],
            "parent_session_root": parent_root, "parent_state_sha256": parent_identity["terminal_state_sha256"],
            "parent_ledger_sha256": parent_identity["native_ledger_sha256"], "parent_end_ordinal": inherited["calls_started"],
            "parent_identity": parent_identity, "parent_identity_sha256": parent_anchor["parent_identity_sha256"],
            "root": str(root), "grant_id": grant, "authorization_sha256": auth_sha, "old_budget_reset": False}
        info = freeze.get("parent_successor_claim")
        _require(type(info) is dict and info == {"path": str(parent_claim_path), "sha256": sha_file(parent_claim_path), "binding": expected_binding}
                 and str(parent_claim_path) in files and files[str(parent_claim_path)] == info["sha256"]
                 and reader.json(parent_claim_path) == successor == expected_binding,
                 "real parent-root and canonical-anchor successor claims differ")
    run_claim = reader.json(root / "RUN_CLAIM.json")
    declared_run_protocol = freeze.get("shared_run_claim_protocol", version + "/run_claim")
    if version == "creative_fresh_source_session/v2":
        _require(declared_run_protocol == scope.get("shared_run_claim_protocol") == "creative_fresh_source_session/v1/run_claim",
                 "v2 shared original run-claim protocol must be explicitly frozen")
    _require(run_claim.get("schema") == declared_run_protocol and run_claim.get("automatic_restart") is False,
             "original non-restart run claim required")
    policy = reader.json(root / "DISPATCH_POLICY.json")
    profile = reader.json(config["profile_path"])
    _require(policy.get("schema") == version + "/runtime_policy" and policy.get("profile") == profile
             and policy.get("stage_limits") == scope.get("stage_limits") and policy.get("automatic_retry") is False
             and policy.get("old_budget_reset") is False and policy.get("media_authorized") is False
             and ledger.get("model_configs") == {role: {k: profile[role][k] for k in ("provider", "model", "base_url")} for role in ("writer", "director")},
             "original dispatch policy/model configuration differs")
    calls = ledger.get("calls")
    _require(type(calls) is list and bool(calls), "no completed Session calls to anchor")
    _require({p.name for p in root.iterdir() if p.is_file() and p.name.startswith("call_") and p.suffix == ".json"} == {r.get("receipt") for r in calls}
             and len({r.get("receipt") for r in calls}) == len(calls), "orphan, duplicate or missing original receipt")
    _require({p.name for p in (root / "call_evidence").iterdir() if p.is_dir()} == {"call_" + str(r["ordinal"]) for r in calls},
             "orphan or missing SDK call evidence directory")
    _require({p.name for p in (root / "requests").iterdir() if p.is_file()} == {r["label"] + ".json" for r in calls},
             "orphan or missing prepared native request")
    receipts = [verify_original_receipt(root, row, manifest, reader=reader) for row in calls]
    first_preview = reader.json(root / "FIRST_REQUEST_PREVIEW.json")
    _require(first_preview.get("request") == receipts[0]["request"]
             and first_preview.get("request_sha256") == receipts[0]["request_sha256"] == scope.get("first_request_sha256"),
             "first actual request differs from frozen preview/scope")
    for receipt in receipts:
        prepared = reader.json(root / "requests" / (receipt["label"] + ".json"))
        _require(prepared.get("request") == receipt["request"] and prepared.get("request_sha256") == receipt["request_sha256"],
                 "stored prepared request differs from actual dispatch")
        request = receipt["request"]
        role, stage = request.get("role"), request.get("stage")
        _require(stage in STAGES and role == STAGES[stage] and request.get("model") == profile[role]["model"],
                 "native model differs from frozen role profile")
        parameters = {**profile[role]["parameters"], **profile.get("stage_parameters", {}).get(stage, {})}
        source6 = request.get("structured_schema", {}).get("properties", {}).get("schema", {}).get("const") == strict.SOURCE_VERSION
        if source6:
            parameters["max_completion_tokens"] = profile["source_strict"]["max_completion_tokens"]
        _require(request.get("parameters") == parameters, "native parameters differ from frozen stage profile")
    inherited_result = validate_records(ledger, receipts, state, freeze, scope, authorization, inherited)
    if (root / "RESULT.json").exists():
        _require(reader.json(root / "RESULT.json") == state["spend"], "optional original RESULT disagrees with STATE/ledger")
    _tasks(reader, root, ledger, receipts, grant)
    for code in (Path(__file__), Path(io.__file__), Path(probe.__file__), Path(ordinary.__file__), Path(strict.__file__)):
        reader.bytes(code)
    goal_receipts = [r for r in receipts if r["request"]["stage"] == "goal_plan" and r["request"].get("structured_schema", {}).get("properties", {}).get("contract_version", {}).get("const") == "creative_goal_source_v4"]
    new_plans = len(goal_receipts)
    parent_plan_count = parent_anchor.get("lineage_whole_plan_candidates_used", 0)
    historical_plans = parent_anchor.get("inherited_whole_goal_candidates_used", 0)
    latest_goal = deepcopy(parent_anchor.get("latest_native_goal_receipt"))
    if goal_receipts:
        last = goal_receipts[-1]
        latest_goal = {"root": str(root), "receipt": next(r["receipt"] for r in calls if r["ordinal"] == last["ordinal"]),
            "label": last["label"], "ordinal": last["ordinal"], "request_sha256": last["request_sha256"],
            "native_goal_sha256": digest(last["output"]),
            "diagnostics_sha256": digest({k: last[k] for k in ("failure", "validation_error", "validation") if k in last})}
    parent_identity = {"root": str(root), "terminal_state_sha256": sha_file(root / "STATE.json"),
        "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"),
        "end_ordinal": inherited_result["calls_started"]}
    return {"schema": VERSION, "root": str(root), "session_schema": version,
        "parent_anchor_path": str(parent_path), "parent_anchor_sha256": config["anchor_sha256"],
        "original_parent_inherited": inherited, "inherited": inherited_result, "new_calls": [r["ordinal"] for r in receipts],
        "new_reported_tokens": sum(r["response_metadata"]["total_tokens"] for r in receipts),
        "new_whole_plan_candidates_used": new_plans, "lineage_whole_plan_candidates_used": parent_plan_count + new_plans,
        "whole_goal_candidates_used": parent_plan_count + new_plans, "latest_native_goal_receipt": latest_goal,
        "parent_identity": parent_identity, "parent_identity_sha256": digest(parent_identity),
        "inherited_whole_goal_candidates_used": historical_plans + new_plans,
        "terminal_status": state["status"], "terminal_state_sha256": sha_file(root / "STATE.json"),
        "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"), "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"),
        "source_manifest_sha256": digest(manifest), "verified_files": reader.files,
        "verified_files_canonical_sha256": digest(reader.files), "verifier_code_sha256": sha_file(__file__),
        "old_director_capacity": deepcopy(state["old_director_capacity"]), "historical_integrity_verified": True,
        "old_dispatch_round_key_is_history_only": True, "next_dispatch_requires_current_counted_round": True,
        "current_source_freshness_checked": False, "current_source_freshness_verified": False,
        "text_ready_for_director": False, "creative_quality_passed": False, "human_quality_approved": False,
        "authorizes_new_dispatch": False, "creates_successor_claim": False, "media_authorized": False,
        "publish_authorized": False, "old_budget_reset": False, "model_calls": 0, "media_calls": 0}


def verify_anchor(anchor, *, expected_anchor_sha256, _ancestors=()):
    _require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256,
             "frozen Session consumption anchor SHA/schema changed")
    actual = build_anchor(anchor.get("root", ""), _ancestors=_ancestors)
    _require(actual == anchor, "original Session consumption changed since anchor freeze")
    return {"verified": True, "inherited": deepcopy(actual["inherited"]),
        "root": actual["root"], "parent_identity": deepcopy(actual["parent_identity"]),
        "parent_identity_sha256": actual["parent_identity_sha256"],
        "whole_goal_candidates_used": actual["whole_goal_candidates_used"],
        "latest_native_goal_receipt": deepcopy(actual["latest_native_goal_receipt"]),
        "current_source_freshness_verified": False, "authorizes_new_dispatch": False,
        "lineage_whole_plan_candidates_used": actual["lineage_whole_plan_candidates_used"],
        "old_director_capacity": deepcopy(actual["old_director_capacity"])}
