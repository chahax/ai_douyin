"""Read-only cost proof for one settled paired-drama diagnostic, no authority."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from scripts import creative_paired_drama_probe_v1 as flow

VERSION = "creative_paired_drama_probe_spend_anchor/v1"
PROJECT = Path(__file__).resolve().parents[1]
read, digest, sha_file, require = flow.read, flow.digest, flow.sha_file, flow.require


def verify_parent(anchor, *, expected_anchor_sha256):
    return flow.parent_spend.verify_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256)


def build_anchor(probe_root):
    """Re-read original settled bytes and SQL, never current freshness/round."""
    root = flow.parent_spend.native._inside(probe_root, PROJECT)
    reader = flow.evidence.session.Reader()
    config, frozen, state, ledger, scope = [reader.json(root / (name + ".json")) for name in
        ("PROBE_CONFIG", "PRODUCTION_FREEZE", "STATE", "CALL_LEDGER", "USER_SCOPE")]
    require(frozen.get("schema") == flow.VERSION + "/freeze" and state.get("schema") == flow.VERSION + "/state"
        and state.get("status") in flow.TERMINAL and state.get("spend_verification_pending") is False
        and Path(config["root"]).resolve() == root, "known settled paired diagnostic required; unknown/truncated cannot settle")
    probe = flow.Probe(config, parent_verifier=verify_parent)
    parent = probe._parent(); inherited = deepcopy(parent["inherited"])
    require(frozen["inherited"] == scope.get("inherited") == ledger.get("starting_spend") == inherited,
        "full635 inherited consumption cannot be omitted/reset")
    manifest = {}
    for name, expected in frozen["files"].items():
        path = flow.parent_spend.native._inside(name, PROJECT)
        reader.verify(path, expected)
        relative = path.relative_to(PROJECT).as_posix(); manifest[relative] = expected
        reader.verify(root / "source_at_dispatch" / relative, expected)
    require(frozen.get("parent_integrity_files") == flow.inherited_files(parent), "parent inventory changed")
    for name, expected in frozen["parent_integrity_files"].items(): reader.verify(name, expected)
    require(ledger.get("source_manifest") == manifest and frozen.get("stage_limits") == flow.LIMITS
        and frozen.get("new_paired_diagnostic_limit") == 1, "frozen source manifest/policy differs")
    preview = reader.json(root / "PREPARED_PROBE.json")
    require(scope == reader.json(config["authorization_path"])
        and digest(scope) == digest(probe.authorization_template(preview)), "reviewed one-call diagnostic scope differs")
    required = [root / (name + ".json") for name in ("PROBE_CONFIG", "PREPARED_PROBE", "USER_SCOPE")]
    required += [Path(config[key]).resolve() for key in ("parent_anchor_path", "profile_path", "expectation_path", "authorization_path")]
    require(all(str(path) in frozen["files"] for path in required), "missing required frozen diagnostic input")
    reader.verify(probe.claim, frozen["claim_sha256"])
    require(reader.json(probe.claim) == {"schema": flow.VERSION + "/claim", "root": str(root), "grant_id": config["grant_id"],
        "authorization_sha256": sha_file(config["authorization_path"]), "old_budget_reset": False}, "original grant identity changed")
    for path in flow.policy.successor_paths(PROJECT, parent, config["parent_anchor_sha256"]):
        require(str(path) in frozen["files"] and reader.json(path) == probe._binding(parent), "dual unique successor changed")
    run = reader.json(root / "RUN_CLAIM.json")
    require(set(run) == {"schema", "root", "grant_id", "prepared_sha256", "pid", "started_at", "automatic_restart"}
        and run["schema"] == flow.VERSION + "/run_claim" and run["root"] == str(root) and run["grant_id"] == config["grant_id"]
        and run["prepared_sha256"] == sha_file(root / "PREPARED_PROBE.json") and type(run["pid"]) is int and run["pid"] > 0
        and bool(datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")).tzinfo)
        and run["automatic_restart"] is False and state.get("run_claim_sha256") == sha_file(root / "RUN_CLAIM.json"), "exact original RUN claim required")
    require(ledger.get("schema") == "authorized_creative_continuation/v3" and ledger.get("max_total_tokens") is None
        and all(ledger.get(key) is False for key in ("automatic_retry", "old_budget_reset", "old_governance_migrated"))
        and sha_file(root / "AUTHORIZATION.json") == ledger.get("authorization_sha256")
        and reader.json(root / "AUTHORIZATION.json").get("starting_spend") == inherited, "original runtime authorization differs")
    rows = ledger.get("calls")
    require(type(rows) is list and len(rows) == 1 and rows[0]["label"] == flow.LABEL and rows[0]["ordinal"] == inherited["calls_started"] + 1,
        "only one continuous diagnostic call may settle")
    require({p.name for p in root.iterdir() if p.is_file() and p.name.startswith("call_") and p.suffix == ".json"} == {rows[0]["receipt"]}
        and {p.name for p in (root / "requests").glob("*.json")} == {flow.LABEL + ".json"}
        and {p.name for p in (root / "call_evidence").iterdir() if p.is_dir()} == {"call_" + str(rows[0]["ordinal"])},
        "missing/orphan/duplicate diagnostic request, receipt or SDK evidence")
    receipt = flow.evidence.verify_known_receipt(root, rows[0], manifest, reader)
    item = preview["request"]
    seed = probe._seed(parent); expectation = probe._expectation(seed)
    prepared = flow.workflow.prepare_goal_drama_audit_request(seed["inputs"], probe.profile, seed["goal"])
    require(item == prepared and receipt["request"] == item["request"] and receipt["request_sha256"] == item["request_sha256"]
        and reader.json(root / "requests" / (flow.LABEL + ".json")) == item,
        "original request differs from complete same-native workflow26 preparation")
    flow.evidence._verify_tasks(reader, root, ledger, [receipt], config["grant_id"])
    known, outcome, _ = flow.original.Session.classify_native(receipt)
    require(known, "unsettled original response cannot form a cost anchor")
    if outcome == "protocol_rejected": expected_status = "halt_protocol_requires_diagnosis"
    elif receipt["status"] != "contract_valid": expected_status = "halt_drama_contract_rejected"
    else:
        decision = flow.workflow.validate_goal_drama_audit(receipt["output"], seed["goal"],
            inputs=seed["inputs"], context_sha256=item["drama_context_sha256"])
        require(decision.get("valid") is True and decision == receipt["validation"], "original native drama validation differs")
        gate = flow.evaluate_expectation(receipt["output"], expectation)
        require(reader.json(root / "DIAGNOSTIC_COMPARISON.json") == state.get("diagnostic_comparison") == gate, "local comparison changed")
        expected_status = ("diagnostic_inconclusive_not_creative" if gate["native_status"] == "unknown" else
            "diagnostic_expectation_matched_not_creative" if gate["expectation_match"] else "diagnostic_expectation_not_matched_not_creative")
    require(state["status"] == expected_status and state.get("receipt_ordinal") == receipt["ordinal"], "original terminal branch differs")
    summary = flow.policy.accounting_summary(inherited, [receipt], stage_limits=flow.LIMITS, unknown_reservations=0)
    require(state.get("spend") == summary and all(state.get(key) is False for key in
        ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")), "original known spend or diagnostic-only boundary differs")
    final = {"calls_started": summary["effective_calls_started"], "reported_tokens": summary["effective_reported_tokens"],
        "calls_with_known_usage": summary["effective_calls_with_known_usage"], "pending_ordinals": inherited["pending_ordinals"],
        "unknown_token_reservations": inherited["unknown_token_reservations"]}
    identity = {"root": str(root), "terminal_state_sha256": sha_file(root / "STATE.json"), "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"), "end_ordinal": final["calls_started"]}
    reader.bytes(__file__)
    return {"schema": VERSION, "root": str(root), "parent_anchor_path": str(Path(config["parent_anchor_path"]).resolve()),
        "parent_anchor_sha256": config["parent_anchor_sha256"], "inherited": final, "original_parent_inherited": inherited,
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "new_calls": [receipt["ordinal"]],
        "new_reported_tokens": summary["new_reported_tokens"], "stage_calls": summary["stage_calls"], "stage_limits": flow.LIMITS,
        "inherited_stage_calls": parent["stage_calls"], "capacity_is_accounting_only_not_regranted": True,
        "accounted_stage_calls_after_probe": {key: parent["stage_calls"][key] + summary["stage_calls"][key] for key in flow.LIMITS},
        "inherited_unspent_original_stage_capacity": deepcopy(parent.get("unspent_original_stage_capacity")),
        "whole_goal_candidates_used": 4, "old_director_capacity": flow.DIRECTOR, "scope_probe_calls_used": 2,
        "inherited_whole_goal_candidates_used": parent.get("inherited_whole_goal_candidates_used"),
        "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 0,
        "paired_drama_probe_calls_used": 1, "paired_drama_probe_call_limit": 1, "terminal_status": state["status"],
        "latest_native_goal_receipt": parent["latest_native_goal_receipt"], "new_native_goal_created": False,
        "verified_files": reader.files, "verifier_code_sha256": sha_file(__file__),
        "current_source_freshness_verified": False, "old_round_key_is_history_only": True,
        "authorizes_new_dispatch": False, "creative_quality_passed": False, "text_ready_for_director": False,
        "media_authorized": False, "old_budget_reset": False}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256,
        "paired diagnostic anchor schema/canonical SHA changed")
    actual = build_anchor(anchor["root"])
    require(actual == anchor, "original paired diagnostic evidence/consumption changed")
    return {"verified": True, **{key: deepcopy(actual[key]) for key in
        ("root", "inherited", "parent_identity", "parent_identity_sha256", "whole_goal_candidates_used", "old_director_capacity",
         "scope_probe_calls_used", "paired_drama_probe_calls_used", "latest_native_goal_receipt")}, "authorizes_new_dispatch": False}
