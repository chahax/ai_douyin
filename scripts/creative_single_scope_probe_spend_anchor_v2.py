"""Read-only cost proof for a settled one-call single-record diagnostic."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_scope_probe_spend_anchor_v1 as prior
from scripts import creative_scope_probe_execution_policy_v1 as policy

VERSION = "creative_single_scope_probe_spend_anchor/v2"
PROBE_VERSION = "creative_single_scope_probe/v2"
PROJECT = Path(__file__).resolve().parents[1]
TERMINAL = {"diagnostic_completed_not_creative", "halt_case_routing_mismatch", "halt_case_contract_rejected", "halt_protocol_requires_diagnosis"}
read, digest, sha_file, require = io.read, io.digest, io.sha_file, prior.require


def verify_parent_anchor(anchor, *, expected_anchor_sha256, ancestors=()):
    if anchor.get("schema") in (prior.VERSION, prior.session.VERSION):
        return prior.verify_parent_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256, ancestors=ancestors)
    require(anchor.get("schema") == VERSION, "unsupported single-probe parent anchor schema")
    return verify_probe_spend_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256, _ancestors=ancestors)


def build_probe_spend_anchor(probe_root, *, _ancestors=()):
    root = prior.session._inside(probe_root, PROJECT)
    require(str(root) not in _ancestors and len(_ancestors) < 100, "cyclic/excessive probe ancestry")
    reader = prior.session.Reader()
    config, freeze, state, ledger, scope, authorization = (reader.json(root / (n + ".json")) for n in
        ("PROBE_CONFIG", "PRODUCTION_FREEZE", "STATE", "CALL_LEDGER", "USER_SCOPE", "AUTHORIZATION"))
    require(freeze.get("schema") == PROBE_VERSION + "/freeze" and state.get("schema") == PROBE_VERSION + "/state"
        and state.get("status") in TERMINAL and state.get("spend_verification_pending") is False
        and Path(config["root"]).resolve() == root, "known settled single-probe terminal required")
    parent_path = prior.session._inside(config["parent_anchor_path"], PROJECT)
    parent = reader.json(parent_path)
    verified = verify_parent_anchor(parent, expected_anchor_sha256=config["parent_anchor_sha256"], ancestors=(*_ancestors, str(root)))
    inherited = prior.session._spend(verified["inherited"])
    require(type(parent.get("scope_probe_calls_used")) is int and parent["scope_probe_calls_used"] == 1,
        "must inherit one original diagnostic call; cannot grant a new two-call budget")
    manifest = {}
    for path, expected in freeze["files"].items():
        source = prior.session._inside(path, PROJECT); require(str(source) == path, "canonical frozen source required")
        reader.verify(source, expected); rel = source.relative_to(PROJECT).as_posix()
        require(rel not in manifest, "duplicate frozen source"); manifest[rel] = expected
        reader.verify(root / "source_at_dispatch" / rel, expected)
    required = [root / (n + ".json") for n in ("PROBE_CONFIG", "PREPARED_PROBE", "USER_SCOPE")]
    required += [Path(config[k]).resolve() for k in ("profile_path", "parent_anchor_path", "blinded_cases_path", "private_expectations_path", "authorization_path")]
    require(all(str(p) in freeze["files"] for p in required), "missing required frozen single-probe input")
    require(ledger.get("source_manifest") == manifest and ledger.get("starting_spend") == inherited == freeze.get("inherited")
        == scope.get("inherited") == authorization.get("starting_spend"), "full original inherited accounting required")
    require(ledger.get("schema") == authorization.get("schema") == "authorized_creative_continuation/v3"
        and ledger.get("max_total_tokens") is authorization.get("max_total_tokens") is None
        and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated"))
        and all(authorization.get(k) is False for k in ("old_budget_reset", "old_governance_migrated", "media_calls_authorized"))
        and sha_file(root / "AUTHORIZATION.json") == ledger.get("authorization_sha256"), "original no-retry/no-reset text policy changed")
    from scripts import creative_single_scope_probe_v2 as execution
    require(scope.get("schema") == PROBE_VERSION + "/scope" and scope == reader.json(config["authorization_path"])
        and scope.get("root") == str(root) and scope.get("grant_id") == config["grant_id"]
        and scope.get("parent_anchor_sha256") == config["parent_anchor_sha256"] and scope.get("stage_limits") == execution.LIMITS
        and scope.get("scope_probe_calls_used") == scope.get("remaining_scope_probe_calls") == scope.get("new_deepseek_calls_limit") == 1
        and scope.get("original_scope_probe_call_limit") == 2 and scope.get("writer_calls_limit") == scope.get("full_goal_calls_limit") == 0
        and all(scope.get(k) is False for k in ("media_authorized", "publish_authorized", "automatic_retry", "old_budget_reset"))
        and freeze.get("response_protocol") == scope.get("response_protocol") == execution.scope.VERSION
        and freeze.get("shared_execution_policy") == scope.get("shared_execution_policy") == policy.VERSION,
        "single remaining case call scope/protocol changed")
    claim = PROJECT / "data/creative_diagnostic_probe_claims" / config["grant_id"] / "CLAIM.json"
    reader.verify(claim, freeze["claim_sha256"]); auth_sha = sha_file(config["authorization_path"])
    require(reader.json(claim) == {"schema": PROBE_VERSION + "/claim", "root": str(root), "grant_id": config["grant_id"],
        "authorization_sha256": auth_sha, "old_budget_reset": False}, "original diagnostic grant changed")
    binding = {"schema": PROBE_VERSION + "/successor_claim", "anchor_sha256": config["parent_anchor_sha256"],
        "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"], "parent_identity_sha256": parent["parent_identity_sha256"],
        "root": str(root), "grant_id": config["grant_id"], "authorization_sha256": auth_sha, "scope_probe_calls_used": 1,
        "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 1, "old_budget_reset": False}
    for path in policy.successor_paths(PROJECT, parent, config["parent_anchor_sha256"]):
        require(str(path) in freeze["files"] and reader.json(path) == binding, "canonical/real-parent successor identity changed")
    run = reader.json(root / "RUN_CLAIM.json")
    require(set(run) == {"schema", "root", "grant_id", "prepared_sha256", "pid", "started_at", "automatic_restart"}
        and run["schema"] == PROBE_VERSION + "/run_claim" and run["root"] == str(root) and run["grant_id"] == config["grant_id"]
        and run["prepared_sha256"] == sha_file(root / "PREPARED_PROBE.json") and type(run["pid"]) is int and run["pid"] > 0
        and type(run["started_at"]) is str and bool(datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")).tzinfo)
        and run["automatic_restart"] is False and state.get("run_claim_sha256") == sha_file(root / "RUN_CLAIM.json"), "exact original non-restart run claim required")
    profile = execution.first.validate_profile(reader.json(config["profile_path"]))
    blind, private = reader.json(config["blinded_cases_path"]), reader.json(config["private_expectations_path"])
    execution.first.validate_case_expectations(blind, private)
    prepared = reader.json(root / "PREPARED_PROBE.json"); item = execution.prepared_request(blind, profile)
    comparison = execution.comparison_binding(parent, blind, private, profile, read_json=reader.json)
    require(prepared["requests"] == [item] and prepared["labels"] == execution.LABELS
        and prepared["stage_limits"] == execution.LIMITS and scope["request_sha256s"] == [item["request_sha256"]]
        and scope["preview_canonical_sha256"] == digest(prepared)
        and prepared.get("controlled_comparison") == scope.get("controlled_comparison") == comparison,
        "original one-request preview/controlled comparison changed")
    calls = ledger.get("calls")
    require(type(calls) is list and len(calls) == 1 and calls[0]["label"] == execution.LABELS[0]
        and type(calls[0]["ordinal"]) is int and calls[0]["ordinal"] == inherited["calls_started"] + 1,
        "only the single continuous remaining call may be settled")
    require({p.name for p in root.iterdir() if p.is_file() and p.name.startswith("call_") and p.suffix == ".json"} == {calls[0]["receipt"]}, "orphan/missing native receipt")
    receipt = prior.verify_known_receipt(root, calls[0], manifest, reader)
    require(receipt["request"] == item["request"] and receipt["request_sha256"] == item["request_sha256"]
        and reader.json(root / "requests" / (execution.LABELS[0] + ".json")) == item
        and {p.stem for p in (root / "requests").glob("*.json")} == set(execution.LABELS), "actual request differs or undeclared request exists")
    prior._verify_tasks(reader, root, ledger, [receipt], config["grant_id"])
    if receipt["status"] == "interface_rejected": expected_terminal = "halt_protocol_requires_diagnosis"
    elif receipt["status"] == "contract_rejected": expected_terminal = "halt_case_contract_rejected"
    else:
        gate = execution.evaluate_cases(receipt["output"], item, private)
        require(reader.json(root / "CASE_GATE.json") == state.get("hard_case_gate") == gate, "original native gate differs")
        expected_terminal = "diagnostic_completed_not_creative" if gate["hard_route_gate_passed"] else "halt_case_routing_mismatch"
    require(state["status"] == expected_terminal and state.get("receipt_ordinal") == receipt["ordinal"], "native result and terminal branch differ")
    summary = policy.accounting_summary(inherited, [receipt], stage_limits=execution.LIMITS, unknown_reservations=0)
    require(state.get("spend") == summary and state.get("scope_probe_calls_inherited") == 1
        and state.get("original_scope_probe_call_limit") == 2 and all(state.get(k) is False for k in ("text_ready_for_director", "creative_quality_passed", "media_authorized")),
        "original spend or diagnostic-only terminal changed")
    if (root / "RESULT.json").exists(): require(reader.json(root / "RESULT.json") == summary, "optional original result differs")
    final = {"calls_started": summary["effective_calls_started"], "reported_tokens": summary["effective_reported_tokens"],
        "calls_with_known_usage": summary["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(inherited["pending_ordinals"]),
        "unknown_token_reservations": inherited["unknown_token_reservations"]}
    identity = {"root": str(root), "terminal_state_sha256": sha_file(root / "STATE.json"), "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"), "end_ordinal": final["calls_started"]}
    reader.bytes(__file__); reader.bytes(policy.__file__)
    return {"schema": VERSION, "root": str(root), "parent_anchor_path": str(parent_path), "parent_anchor_sha256": config["parent_anchor_sha256"],
        "inherited": final, "original_parent_inherited": inherited, "new_calls": [receipt["ordinal"]], "new_reported_tokens": summary["new_reported_tokens"],
        "scope_probe_calls_used": 2, "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 0,
        "whole_goal_candidates_used": parent["whole_goal_candidates_used"], "lineage_whole_plan_candidates_used": parent["whole_goal_candidates_used"],
        "inherited_whole_goal_candidates_used": parent["inherited_whole_goal_candidates_used"],
        "latest_native_goal_receipt": deepcopy(parent["latest_native_goal_receipt"]), "old_director_capacity": deepcopy(parent["old_director_capacity"]),
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "verified_files": reader.files,
        "verifier_code_sha256": sha_file(__file__), "terminal_status": state["status"], "historical_integrity_verified": True,
        "current_source_freshness_checked": False, "current_source_freshness_verified": False,
        "next_dispatch_requires_current_counted_round": True, "authorizes_new_dispatch": False, "creates_successor_claim": False,
        "media_authorized": False, "publish_authorized": False, "creative_quality_passed": False, "text_ready_for_director": False, "old_budget_reset": False}


def verify_probe_spend_anchor(anchor, *, expected_anchor_sha256, _ancestors=()):
    require(anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256, "single-probe canonical anchor changed")
    actual = build_probe_spend_anchor(anchor["root"], _ancestors=_ancestors)
    require(anchor == actual, "single-probe source or accounting changed")
    return {"verified": True, "root": actual["root"], "inherited": deepcopy(actual["inherited"]),
        "parent_identity": deepcopy(actual["parent_identity"]), "parent_identity_sha256": actual["parent_identity_sha256"],
        "whole_goal_candidates_used": actual["whole_goal_candidates_used"], "scope_probe_calls_used": 2,
        "latest_native_goal_receipt": deepcopy(actual["latest_native_goal_receipt"]), "current_source_freshness_verified": False,
        "authorizes_new_dispatch": False}
