"""Read-only, typed accounting for a terminal Session3; no new authority.

Raw SDK and original TaskStore evidence use the existing settled readers. Live
source freshness and repair-round admission are intentionally not called here.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re

from scripts import creative_session_spend_anchor_v1 as native
from scripts import creative_scope_probe_spend_anchor_v1 as known
from scripts import creative_single_scope_probe_spend_anchor_v2 as parent_protocol
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts import creative_fresh_source_session_v1 as classification

VERSION = "creative_scoped_session_spend_anchor/v1"
SESSION_VERSION = "creative_scoped_source_session/v3"
PROJECT = Path(__file__).resolve().parents[1]
LIMITS = {"goal_plan": 3, "goal_audit": 4, "complete_script": 3, "full_review": 6}
DIRECTOR = {"used": 7, "limit": 7, "remaining": 0}
TERMINAL = (native.TERMINAL_STATES - {"halt_whole_plan_lineage_capacity_exhausted", "halt_plan_capacity_exhausted"}) | {
    "halt_plan4_contract_rejected_no_plan5", "halt_goal_scope_requires_author_clarification", "halt_goal_scope_challenge",
    "halt_goal_audit_rejected", "halt_protocol_requires_diagnosis", "halt_interface_or_unknown"}
read, digest, sha_file, require = native.read, native.digest, native.sha_file, native._require


def verify_parent(anchor, *, expected_anchor_sha256, ancestors=()):
    require(anchor.get("schema") == parent_protocol.VERSION, "Session3 requires the settled original626 diagnostic anchor")
    return parent_protocol.verify_probe_spend_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256, _ancestors=ancestors)


def validate_records(ledger, receipts, state, freeze, scope, authorization, inherited):
    """Exact cost/capacity arithmetic, after original bytes/SQL verification."""
    inherited = native._spend(inherited)
    require(all(value == inherited for value in (ledger.get("starting_spend"), freeze.get("inherited"),
        scope.get("inherited"), authorization.get("starting_spend"))), "inherited consumption cannot be omitted or reset")
    require(ledger.get("schema") == authorization.get("schema") == "authorized_creative_continuation/v3"
        and ledger.get("max_total_tokens") is authorization.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated"))
        and all(authorization.get(k) is False for k in ("old_budget_reset", "old_governance_migrated", "media_calls_authorized"))
        and all(scope.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized", "publish_authorized")),
        "original no-reset no-retry text-only policy required")
    require(all(type(obj.get("stage_limits")) is dict and obj["stage_limits"] == LIMITS
        and all(type(v) is int for v in obj["stage_limits"].values()) for obj in (scope, freeze)), "exact typed Session3 stage capacities required")
    calls = ledger.get("calls")
    require(type(calls) is list and 0 < len(calls) == len(receipts) <= 16, "nonempty settled Session3 ledger bounded by16 required")
    seen = [set(), set(), set()]; stages = dict.fromkeys(LIMITS, 0); protocol_failure = False
    for index, (row, receipt) in enumerate(zip(calls, receipts), 1):
        request, meta = receipt.get("request", {}), receipt.get("response_metadata", {})
        label, stage = row.get("label"), request.get("stage")
        expected_stage = ("goal_plan" if label == "whole_plan_04" or re.fullmatch(r"opening_setup_0[12]", str(label))
            else "goal_audit" if re.fullmatch(r"(?:scope|source|commitment|drama)_audit_04", str(label))
            else "complete_script" if re.fullmatch(r"complete_script_0[123]", str(label))
            else "full_review" if re.fullmatch(r"full_review_(?:semantic|physical)_0[123]", str(label)) else None)
        require(type(row.get("ordinal")) is int and row["ordinal"] == inherited["calls_started"] + index
            and receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == label
            and native._integer(row.get("token_reservation")) and row["token_reservation"] == receipt.get("token_reservation")
            and expected_stage is not None and stage == expected_stage and request.get("role") == native.STAGES[stage],
            "contiguous exact Session3 call and stage labels required")
        settled, outcome, tool = classification.Session.classify_native(receipt)
        require(settled and outcome in ("completed", "content_rejected", "protocol_rejected")
            and receipt.get("automatic_retry") is False and receipt.get("semantic_approval") is False
            and not receipt.get("cached_response_read_only") and bool(receipt.get("completed_at")), "unknown or unreturned outcome cannot settle")
        if outcome == "protocol_rejected":
            require(index == len(calls), "known protocol rejection must stop without further dispatch")
            protocol_failure = True
        else:
            require(tool == "accepted" and type(receipt.get("output")) is dict and bool(receipt["output"]), "original native tool document required")
        require(meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop", "tool_calls")
            and meta.get("strict_mode") is False and type(meta.get("http_status_code")) is int
            and 200 <= meta["http_status_code"] < 300, "complete ordinary Session3 response required; truncated/unknown cannot settle")
        usage = receipt.get("response_payload", {}).get("usage", {})
        require(all(native._integer(meta.get(k)) and native._integer(usage.get(k)) and meta[k] == usage[k]
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
            and meta["prompt_tokens"] + meta["completion_tokens"] == meta["total_tokens"], "known original typed usage required")
        for values, value in zip(seen, (meta.get("response_id"), receipt.get("request_sha256"), label)):
            require(type(value) is str and value and value not in values, "duplicate response/request/label cannot be counted twice")
            values.add(value)
        stages[stage] += 1
    require(calls[0]["label"] == "whole_plan_04" and sum(r["label"] == "whole_plan_04" for r in calls) == 1
        and all(stages[k] <= LIMITS[k] for k in LIMITS), "only one plan4 and original aggregate stage limits may be consumed")
    expected = policy.accounting_summary(inherited, receipts, stage_limits=LIMITS, unknown_reservations=0)
    require(state.get("status") in TERMINAL and state.get("spend_verification_pending") is False
        and type(state.get("spend")) is dict and all(type(state["spend"].get(k)) is type(v) for k, v in expected.items())
        and digest(state["spend"]) == digest(expected) and state.get("text_ready_for_director") is (state["status"] == "text_ready_for_director")
        and all(state.get(k) is False for k in ("human_quality_approved", "creative_quality_passed", "media_authorized"))
        and state.get("old_director_capacity") == scope.get("old_director_capacity") == DIRECTOR,
        "known terminal STATE and exact original spend required")
    require(protocol_failure == (state["status"] in ("halt_protocol_requires_diagnosis", "halt_interface_or_unknown")),
        "known protocol cost must keep its stop branch; unknown cannot be relabelled settled")
    if state["status"] == "halt_plan4_contract_rejected_no_plan5":
        require(len(calls) == 1 and receipts[0]["status"] == "contract_rejected", "plan4 rejection branch differs")
    return {"inherited": {"calls_started": expected["effective_calls_started"], "reported_tokens": expected["effective_reported_tokens"],
        "calls_with_known_usage": expected["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}, "stage_calls": stages, "summary": expected}


def verify_machine_handoff(reader, root, rows, receipts, state):
    """Byte/native identity binding, not a new semantic or quality approval."""
    handoff = reader.json(root / "TEXT_HANDOFF.json")
    by_ordinal = {r["ordinal"]: r for r in receipts}
    goal = by_ordinal.get(state.get("native_goal_ordinal"), {})
    body = by_ordinal.get(state.get("script_ordinal"), {})
    setups = [r for r in receipts if r["label"].startswith("opening_setup_")]
    require(setups and goal.get("label") == "whole_plan_04" and body.get("request", {}).get("stage") == "complete_script"
        and goal.get("status") == body.get("status") == setups[-1].get("status") == "contract_valid", "native goal/body/setup identities required for machine handoff")
    reviews = {part: by_ordinal.get(state.get("review_ordinals", {}).get(part), {}) for part in ("semantic", "physical")}
    require(all(r.get("label") == "full_review_" + part + "_" + body["label"][-2:]
        and r.get("status") == "contract_valid" and r.get("validation", {}).get("accepted") is True for part, r in reviews.items()),
        "same native body and two accepted original full-review receipts required")
    scope_receipt = next((r for r in receipts if r["label"] == "scope_audit_04"), {})
    reports = {"native_" + kind + "_audit": next((r["output"] for r in receipts if r["label"] == kind + "_audit_04"), None)
        for kind in ("scope", "source", "commitment", "drama")}
    scope_row = next((r for r in rows if r["ordinal"] == scope_receipt.get("ordinal")), {})
    require(scope_row and all(v is not None for v in reports.values())
        and handoff.get("schema") == SESSION_VERSION + "/text_handoff"
        and handoff.get("native_goal") == goal["output"] and handoff.get("native_opening_setup") == setups[-1]["output"]
        and handoff.get("native_script") == body["output"] and handoff.get("script_ordinal") == body["ordinal"]
        and handoff.get("review_ordinals") == state.get("review_ordinals") and handoff.get("decision") == state.get("decision")
        and handoff.get("native_full_review_bundle") == classification.reviews.build_review_bundle(reviews["semantic"]["output"], reviews["physical"]["output"])
        and handoff.get("execution_requirement_evidence") == state.get("execution_requirement_evidence")
        and all(handoff.get("native_goal_audit", {}).get(k) == v for k, v in reports.items())
        and handoff.get("execution_requirement_evidence", {}).get("native_scope_receipt_sha256") == sha_file(root / scope_row["receipt"])
        and handoff.get("media_authorized") is False and handoff.get("production_dispatch_eligible") is False,
        "original goal/setup/body/four-audit/two-full-review machine handoff differs")
    return sha_file(root / "TEXT_HANDOFF.json")


def build_anchor(session_root, *, _ancestors=()):
    """Deterministic read-only accounting; does not write the returned anchor."""
    root = native._inside(session_root, PROJECT)
    require(str(root) not in _ancestors and len(_ancestors) < 100, "cyclic/excessive anchor ancestry")
    reader = native.Reader()
    config, freeze, state, ledger, scope, authorization = (reader.json(root / (n + ".json")) for n in
        ("SESSION_CONFIG", "PRODUCTION_FREEZE", "STATE", "CALL_LEDGER", "USER_SCOPE", "AUTHORIZATION"))
    require(freeze.get("schema") == SESSION_VERSION + "/freeze" and state.get("schema") == SESSION_VERSION + "/state"
        and state.get("flow_version") == SESSION_VERSION and scope.get("schema") == SESSION_VERSION + "/derived_authorization"
        and Path(config.get("root", "")).resolve() == root and state.get("status") in TERMINAL
        and state.get("spend_verification_pending") is False, "known terminal typed Session3 required")
    parent_path = native._inside(config["anchor_path"], PROJECT); parent = reader.json(parent_path)
    require(digest(parent) == config["anchor_sha256"], "original canonical parent anchor changed")
    verified = verify_parent(parent, expected_anchor_sha256=config["anchor_sha256"], ancestors=(*_ancestors, str(root)))
    inherited = native._spend(verified["inherited"])
    require(verified.get("verified") is True and inherited == parent.get("inherited")
        and type(parent.get("whole_goal_candidates_used")) is int and parent["whole_goal_candidates_used"] == 3
        and type(parent.get("scope_probe_calls_used")) is int and parent["scope_probe_calls_used"] == 2
        and parent.get("remaining_scope_probe_calls") == 0 and parent.get("old_director_capacity") == DIRECTOR
        and parent.get("terminal_status") == "diagnostic_completed_not_creative",
        "full626 consumption, original plans3/3 and diagnostics2/2 required")
    files = freeze.get("files"); require(type(files) is dict and bool(files), "complete production freeze required")
    manifest = {}
    for name, expected in files.items():
        path = native._inside(name, PROJECT); require(str(path) == name, "canonical absolute frozen file required")
        reader.verify(path, expected); rel = path.relative_to(PROJECT).as_posix(); manifest[rel] = expected
        reader.verify(native._inside(root / "source_at_dispatch" / rel, root / "source_at_dispatch"), expected)
    require(ledger.get("source_manifest") == manifest, "original complete source snapshot differs")
    required = [root / (n + ".json") for n in ("SESSION_CONFIG", "INPUTS", "INPUT_EVIDENCE", "FIRST_REQUEST_PREVIEW", "CLARIFICATION_MANIFEST", "USER_SCOPE")]
    required += [Path(config[k]).resolve() for k in ("profile_path", "anchor_path", "authorization_path", "goal_receipt_path", "source_audit_receipt_path", "root_observations_path")]
    require(all(str(p) in files for p in required) and reader.json(config["authorization_path"]) == scope
        and sha_file(root / "AUTHORIZATION.json") == ledger.get("authorization_sha256")
        and scope.get("root") == str(root) and scope.get("grant_id") == config["grant_id"]
        and scope.get("anchor_sha256") == config["anchor_sha256"]
        and digest(reader.json(root / "INPUTS.json")) == freeze.get("inputs_sha256") == scope.get("inputs_sha256")
        and digest(reader.json(root / "CLARIFICATION_MANIFEST.json")) == scope.get("clarification_manifest_sha256"),
        "original configured inputs, scope and runtime authorization differ")
    require(all(type(scope.get(k)) is int and scope[k] == v for k, v in {"whole_plans_already_used": 3,
        "whole_plan_limit": 1, "whole_plan_lineage_limit": 4, "setup_limit": 2, "content_revision_limit": 2, "native_goal_audit_parts": 4}.items())
        and scope.get("total_new_calls_limit") == freeze.get("total_new_calls_limit") == 16
        and scope.get("source_transport") == "ordinary_exact_tool_local_contract", "original16-call and one-plan4 scope differs")
    grant = config["grant_id"]; require(type(grant) is str and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", grant), "safe original grant required")
    auth_sha = sha_file(config["authorization_path"]); claim_path = PROJECT / "data/creative_fresh_background_claims" / grant / "CLAIM.json"
    reader.verify(claim_path, freeze.get("claim_sha256"))
    require(reader.json(claim_path) == {"schema": SESSION_VERSION + "/claim", "root": str(root), "grant_id": grant,
        "authorization_sha256": auth_sha, "old_budget_reset": False}, "original grant claim changed")
    parent_root = str(Path(parent["root"]).resolve()); identity = parent["parent_identity"]
    require(identity.get("root") == parent_root and identity.get("end_ordinal") == inherited["calls_started"]
        and digest(identity) == parent.get("parent_identity_sha256"), "verified real parent identity differs")
    binding = {"schema": SESSION_VERSION + "/successor_claim", "anchor_sha256": config["anchor_sha256"],
        "parent_session_root": parent["root"], "parent_identity": identity, "parent_identity_sha256": parent["parent_identity_sha256"],
        "root": str(root), "grant_id": grant, "authorization_sha256": auth_sha, "whole_plans_already_used": 3,
        "whole_plan_lineage_limit": 4, "whole_plan_limit": 1, "old_budget_reset": False}
    successors = policy.successor_paths(PROJECT, parent, config["anchor_sha256"])
    require(all(str(p) in files and reader.json(p) == binding for p in successors)
        and freeze.get("parent_successor_claim") == {"path": str(successors[1]), "sha256": sha_file(successors[1]), "binding": binding},
        "canonical anchor and real parent-root successor claims differ")
    run = reader.json(root / "RUN_CLAIM.json")
    require(set(run) == {"schema", "pid", "started_at", "automatic_restart"}
        and run["schema"] == scope.get("shared_run_claim_protocol") == freeze.get("shared_run_claim_protocol")
        == state.get("shared_run_claim_protocol") == "creative_fresh_source_session/v1/run_claim"
        and type(run["pid"]) is int and run["pid"] > 0 and type(run["started_at"]) is str
        and bool(datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")).tzinfo)
        and run["automatic_restart"] is False and state.get("run_claim_sha256") == sha_file(root / "RUN_CLAIM.json"), "exact original non-restart RUN required")
    dispatch = reader.json(root / "DISPATCH_POLICY.json"); profile = reader.json(config["profile_path"])
    require(dispatch.get("schema") == SESSION_VERSION + "/runtime_policy" and dispatch.get("stage_limits") == LIMITS
        and dispatch.get("profile") == profile and dispatch.get("native_goal_audit_parts_per_plan") == 4
        and dispatch.get("total_new_calls_limit") == 16 and all(dispatch.get(k) is False for k in ("automatic_retry", "old_budget_reset", "media_authorized"))
        and ledger.get("model_configs") == {role: {k: profile[role][k] for k in ("provider", "model", "base_url")} for role in ("writer", "director")},
        "original exact runtime policy/models differ")
    rows = ledger.get("calls"); require(type(rows) is list and bool(rows), "no settled Session3 calls")
    require({p.name for p in root.iterdir() if p.is_file() and p.name.startswith("call_") and p.suffix == ".json"} == {r.get("receipt") for r in rows}
        and len({r.get("receipt") for r in rows}) == len(rows)
        and {p.name for p in (root / "call_evidence").iterdir() if p.is_dir()} == {"call_" + str(r["ordinal"]) for r in rows}
        and {p.name for p in (root / "requests").iterdir() if p.is_file()} == {r["label"] + ".json" for r in rows},
        "orphan/duplicate/missing original receipt, SDK or request identity")
    receipts = [known.verify_known_receipt(root, row, manifest, reader) for row in rows]
    first = reader.json(root / "FIRST_REQUEST_PREVIEW.json")
    require(first.get("request") == receipts[0]["request"] and first.get("request_sha256")
        == receipts[0]["request_sha256"] == scope.get("first_request_sha256"), "first native request differs from frozen review")
    for receipt in receipts:
        prepared = reader.json(root / "requests" / (receipt["label"] + ".json")); request = receipt["request"]
        role, stage = request["role"], request["stage"]
        require(prepared.get("request") == request and prepared.get("request_sha256") == receipt["request_sha256"]
            and role == native.STAGES[stage] and request["model"] == profile[role]["model"]
            and request["parameters"] == {**profile[role]["parameters"], **profile.get("stage_parameters", {}).get(stage, {})}
            and request.get("input_provenance", {}).get("workflow_version") == "creative_goal_context_workflow/v25", "actual request/model/ordinary parameters changed")
    accounting = validate_records(ledger, receipts, state, freeze, scope, authorization, inherited)
    known._verify_tasks(reader, root, ledger, receipts, grant)
    if (root / "RESULT.json").exists(): require(reader.json(root / "RESULT.json") == state["spend"], "optional RESULT differs")
    handoff_sha = None
    if state["status"] == "text_ready_for_director":
        handoff_sha = verify_machine_handoff(reader, root, rows, receipts, state)
    new_goal = receipts[0]; latest = deepcopy(parent["latest_native_goal_receipt"])
    if new_goal["status"] in ("contract_valid", "contract_rejected"):
        latest = {"root": str(root), "receipt": rows[0]["receipt"], "label": new_goal["label"], "ordinal": new_goal["ordinal"],
            "request_sha256": new_goal["request_sha256"], "native_goal_sha256": digest(new_goal["output"]),
            "diagnostics_sha256": digest({k: new_goal[k] for k in ("failure", "validation_error", "validation") if k in new_goal})}
    identity = {"root": str(root), "terminal_state_sha256": sha_file(root / "STATE.json"), "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"), "end_ordinal": accounting["inherited"]["calls_started"]}
    for module in (__file__, native.__file__, known.__file__, parent_protocol.__file__, policy.__file__): reader.bytes(module)
    return {"schema": VERSION, "root": str(root), "session_schema": SESSION_VERSION, "parent_anchor_path": str(parent_path),
        "parent_anchor_sha256": config["anchor_sha256"], "original_parent_inherited": inherited, "inherited": accounting["inherited"],
        "new_calls": [r["ordinal"] for r in receipts], "new_reported_tokens": accounting["summary"]["new_reported_tokens"],
        "new_whole_plan_candidates_used": 1, "whole_goal_candidates_used": 4, "lineage_whole_plan_candidates_used": 4,
        "inherited_whole_goal_candidates_used": parent["inherited_whole_goal_candidates_used"] + 1,
        "scope_probe_calls_used": 2, "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 0,
        "stage_calls": accounting["stage_calls"], "stage_limits": LIMITS,
        "unspent_original_stage_capacity": {k: LIMITS[k] - accounting["stage_calls"][k] for k in LIMITS},
        "capacity_is_accounting_only_not_regranted": True, "latest_native_goal_receipt": latest,
        "new_plan_native_tool_available": new_goal["status"] in ("contract_valid", "contract_rejected"),
        "new_plan_native_contract_status": new_goal["status"],
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "terminal_status": state["status"],
        "verified_files": reader.files, "verified_files_canonical_sha256": digest(reader.files), "verifier_code_sha256": sha_file(__file__),
        "source_manifest_sha256": digest(manifest), "old_director_capacity": DIRECTOR, "original_text_handoff_sha256": handoff_sha,
        "machine_handoff_native_identity_verified": handoff_sha is not None,
        "machine_text_ready_from_original_state": state["status"] == "text_ready_for_director", "historical_integrity_verified": True,
        "old_dispatch_round_key_is_history_only": True, "current_source_freshness_checked": False, "current_source_freshness_verified": False,
        "next_dispatch_requires_current_counted_round": True, "authorizes_new_dispatch": False, "creates_successor_claim": False,
        "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False,
        "media_authorized": False, "publish_authorized": False, "old_budget_reset": False, "model_calls": 0, "media_calls": 0}


def verify_anchor(anchor, *, expected_anchor_sha256, _ancestors=()):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "typed Session3 anchor SHA changed")
    actual = build_anchor(anchor["root"], _ancestors=_ancestors)
    require(actual == anchor, "original Session3 files or accounting changed since anchor construction")
    return {"verified": True, **{k: deepcopy(actual[k]) for k in ("root", "inherited", "parent_identity", "parent_identity_sha256",
        "whole_goal_candidates_used", "latest_native_goal_receipt", "stage_calls", "stage_limits", "old_director_capacity", "scope_probe_calls_used")},
        "current_source_freshness_verified": False, "authorizes_new_dispatch": False}
