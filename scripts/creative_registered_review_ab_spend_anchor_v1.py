"""Read-only registered A/B cost handoff; no live freshness, claim or grant."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from scripts import creative_registered_review_ab_probe_v1 as flow

VERSION = "creative_registered_review_ab_spend_anchor/v1"
PROJECT = Path(__file__).resolve().parents[1]
read, digest, sha_file, require = flow.read, flow.digest, flow.sha_file, flow.require


def verify_parent(anchor, *, expected_anchor_sha256):
    return flow.parent_spend.verify_anchor(anchor, expected_anchor_sha256=expected_anchor_sha256)


def build_anchor(probe_root):
    """Re-read settled original bytes/SDK/SQL, never the current source gate."""
    root = flow.shared.parent_spend.native._inside(probe_root, PROJECT)
    reader = flow.shared.evidence.session.Reader()
    config, frozen, state, ledger, scope = [reader.json(root / (name + ".json")) for name in
        ("PROBE_CONFIG", "PRODUCTION_FREEZE", "STATE", "CALL_LEDGER", "USER_SCOPE")]
    require(frozen.get("schema") == flow.VERSION + "/freeze" and state.get("schema") == flow.VERSION + "/state"
        and state.get("status") in {"diagnostic_completed_not_creative", "halt_protocol_requires_diagnosis"}
        and state.get("spend_verification_pending") is False and Path(config["root"]).resolve() == root,
        "known settled A/B result required; zero/unknown/truncated cannot settle")
    probe = flow.Probe(config, parent_verifier=verify_parent)
    parent = probe._parent(); inherited = deepcopy(parent["inherited"])
    require(frozen["inherited"] == scope.get("inherited") == ledger.get("starting_spend") == inherited,
        "complete settled636 consumption cannot be omitted/reset")
    manifest = {}
    for name, expected in frozen["files"].items():
        path = flow.shared.parent_spend.native._inside(name, PROJECT)
        reader.verify(path, expected)
        relative = path.relative_to(PROJECT).as_posix(); manifest[relative] = expected
        reader.verify(root / "source_at_dispatch" / relative, expected)
    require(frozen.get("parent_integrity_files") == flow.shared.inherited_files(parent), "original parent inventory changed")
    for name, expected in frozen["parent_integrity_files"].items(): reader.verify(name, expected)
    require(ledger.get("source_manifest") == manifest and frozen.get("stage_limits") == flow.LIMITS,
        "original source manifest/stage policy changed")
    preview = reader.json(root / "PREPARED_PROBE.json")
    require(scope == reader.json(config["authorization_path"])
        and digest(scope) == digest(probe.authorization_template(preview)), "exact registered A/B scope changed")
    required = [root / (name + ".json") for name in ("PROBE_CONFIG", "PREPARED_PROBE", "USER_SCOPE")]
    required += [Path(config[key]).resolve() for key in ("parent_anchor_path", "profile_path", "authorization_path")]
    require(all(str(path) in frozen["files"] for path in required), "required original frozen input missing")
    reader.verify(probe.claim, frozen["claim_sha256"])
    require(reader.json(probe.claim) == {"schema": flow.VERSION + "/claim", "root": str(root),
        "grant_id": config["grant_id"], "authorization_sha256": sha_file(config["authorization_path"])}, "unique grant changed")
    for path in flow.shared.policy.successor_paths(PROJECT, parent, config["parent_anchor_sha256"]):
        require(str(path) in frozen["files"] and reader.json(path) == probe._binding(parent), "dual unique successor changed")
    run = reader.json(root / "RUN_CLAIM.json")
    require(set(run) == {"schema", "root", "grant_id", "prepared_sha256", "pid", "started_at", "automatic_restart"}
        and run["schema"] == flow.VERSION + "/run_claim" and run["root"] == str(root) and run["grant_id"] == config["grant_id"]
        and run["prepared_sha256"] == sha_file(root / "PREPARED_PROBE.json") and type(run["pid"]) is int and run["pid"] > 0
        and bool(datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")).tzinfo)
        and run["automatic_restart"] is False and state.get("run_claim_sha256") == sha_file(root / "RUN_CLAIM.json"),
        "exact original single RUN identity required")
    authorization = reader.json(root / "AUTHORIZATION.json")
    dispatch_policy = reader.json(root / "DISPATCH_POLICY.json")
    require(dispatch_policy.get("schema") == "creative_goal_context_dispatch/v7/policy"
        and dispatch_policy.get("profile") == probe.profile and dispatch_policy.get("stage_limits") == flow.LIMITS
        and all(dispatch_policy.get(key) is False for key in ("automatic_retry", "old_budget_reset", "media_authorized")),
        "original finite runtime policy differs")
    require(ledger.get("schema") == authorization.get("schema") == "authorized_creative_continuation/v3"
        and ledger.get("max_total_tokens") is authorization.get("max_total_tokens") is None
        and all(ledger.get(key) is False for key in ("automatic_retry", "old_budget_reset", "old_governance_migrated"))
        and all(authorization.get(key) is False for key in ("old_budget_reset", "old_governance_migrated", "media_calls_authorized"))
        and sha_file(root / "AUTHORIZATION.json") == ledger.get("authorization_sha256")
        and authorization.get("starting_spend") == inherited,
        "original runtime authorization differs")
    seed = probe._seed(parent)
    experiment = flow.contract().prepare_experiment(probe.profile, seed["receipt"])
    require(preview.get("schema") == flow.VERSION + "/preview" and preview.get("experiment") == experiment
        and preview.get("registered_requests") == probe._requests(experiment)
        and preview.get("parent_identity") == parent["parent_identity"]
        and preview.get("parent_identity_sha256") == parent["parent_identity_sha256"]
        and preview.get("original_source_dir") == seed["source_dir"], "original corpus/registration/source identity changed")
    rows = ledger.get("calls")
    require(type(rows) is list and len(rows) in (1, 2)
        and [row["label"] for row in rows] == list(flow.LABELS[:len(rows)])
        and [row["ordinal"] for row in rows] == list(range(inherited["calls_started"] + 1, inherited["calls_started"] + 1 + len(rows))),
        "only the continuous registered A/B prefix may settle")
    require({p.name for p in root.iterdir() if p.is_file() and p.name.startswith("call_") and p.suffix == ".json"}
            == {row["receipt"] for row in rows}
        and {p.name for p in (root / "requests").glob("*.json")} == {row["label"] + ".json" for row in rows}
        and {p.name for p in (root / "call_evidence").iterdir() if p.is_dir()} == {"call_" + str(row["ordinal"]) for row in rows},
        "missing/orphan/duplicate original request, receipt or SDK evidence")
    receipts, results, response_ids = [], [], set()
    for index, row in enumerate(rows):
        receipt = flow.shared.evidence.verify_known_receipt(root, row, manifest, reader)
        known, outcome, _ = flow.shared.original.Session.classify_native(receipt)
        require(known, "unknown result or usage cannot settle")
        item = preview["registered_requests"][index]
        require(receipt["request"] == item["prepared"]["request"]
            and receipt["request_sha256"] == item["prepared"]["request_sha256"]
            and reader.json(root / "requests" / (row["label"] + ".json")) == item["prepared"], "original registered request changed")
        rid = receipt["response_metadata"]["response_id"]
        require(rid not in response_ids, "duplicate provider response identity cannot count twice")
        response_ids.add(rid)
        if outcome == "protocol_rejected":
            require(index == len(rows) - 1, "original protocol rejection must stop the remaining representation")
        else:
            decision = flow.contract().validate_response(receipt["output"], experiment["corpus"], item["representation"],
                context_sha256=item["prepared"]["context_sha256"])
            require(decision == receipt.get("validation") and type(decision.get("valid")) is bool
                and receipt["status"] == ("contract_valid" if decision["valid"] else "contract_rejected"),
                "original native contract decision differs; never convert a failed result")
        receipts.append(receipt)
        results.append({"representation": item["representation"], "label": row["label"], "ordinal": row["ordinal"],
            "status": receipt["status"], "known": known, "outcome": outcome, "validation": deepcopy(receipt.get("validation"))})
    expected_status = "halt_protocol_requires_diagnosis" if results[-1]["outcome"] == "protocol_rejected" else "diagnostic_completed_not_creative"
    require((len(rows) == 2 or expected_status == "halt_protocol_requires_diagnosis")
        and state["status"] == expected_status and state.get("diagnostic_results") == results, "original terminal branch differs")
    if expected_status == "diagnostic_completed_not_creative":
        require(reader.json(root / "DIAGNOSTIC_RESULTS.json") == {"results": results, "creative_quality_passed": False},
            "original diagnostic results differ")
    flow.shared.evidence._verify_tasks(reader, root, ledger, receipts, config["grant_id"])
    summary = flow.shared.policy.accounting_summary(inherited, receipts, stage_limits=flow.LIMITS, unknown_reservations=0)
    require(state.get("spend") == summary and all(state.get(key) is False for key in
        ("text_ready_for_director", "human_quality_approved", "creative_quality_passed", "media_authorized")),
        "known spend or diagnostic-only boundary changed")
    final = {"calls_started": summary["effective_calls_started"], "reported_tokens": summary["effective_reported_tokens"],
        "calls_with_known_usage": summary["effective_calls_with_known_usage"], "pending_ordinals": inherited["pending_ordinals"],
        "unknown_token_reservations": inherited["unknown_token_reservations"]}
    identity = {"root": str(root), "terminal_state_sha256": sha_file(root / "STATE.json"), "native_ledger_sha256": sha_file(root / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha_file(root / "PRODUCTION_FREEZE.json"), "end_ordinal": final["calls_started"]}
    reader.bytes(__file__)
    return {"schema": VERSION, "root": str(root), "parent_anchor_path": str(Path(config["parent_anchor_path"]).resolve()),
        "parent_anchor_sha256": config["parent_anchor_sha256"], "inherited": final, "original_parent_inherited": inherited,
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "new_calls": [r["ordinal"] for r in receipts],
        "new_reported_tokens": summary["new_reported_tokens"], "stage_calls": summary["stage_calls"], "stage_limits": flow.LIMITS,
        "inherited_stage_calls": parent["stage_calls"], "inherited_accounted_stage_calls": parent["accounted_stage_calls_after_probe"],
        "accounted_stage_calls_after_probe": {key: parent["accounted_stage_calls_after_probe"][key] + summary["stage_calls"][key] for key in flow.LIMITS},
        "inherited_unspent_original_stage_capacity": deepcopy(parent.get("inherited_unspent_original_stage_capacity")),
        "inherited_whole_goal_candidates_used": parent.get("inherited_whole_goal_candidates_used"),
        "whole_goal_candidates_used": parent["whole_goal_candidates_used"], "old_director_capacity": parent["old_director_capacity"],
        "scope_probe_calls_used": 2, "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 0,
        "paired_drama_probe_calls_used": 1, "paired_drama_probe_call_limit": 1,
        "registered_ab_calls_used": len(rows), "registered_ab_call_limit": 2, "registered_ab_unused_calls": 2 - len(rows),
        "registered_representations": [{"representation": i["representation"], "label": i["label"],
            "request_sha256": i["prepared"]["request_sha256"], "used": index < len(rows)}
            for index, i in enumerate(preview["registered_requests"])],
        "capacity_is_accounting_only_not_regranted": True, "unused_calls_authorize_dispatch": False,
        "terminal_status": state["status"], "latest_native_goal_receipt": deepcopy(parent["latest_native_goal_receipt"]),
        "corpus_sha256": experiment["corpus_sha256"], "new_native_goal_created": False,
        "verified_files": reader.files, "verifier_code_sha256": sha_file(__file__),
        "current_source_freshness_verified": False, "old_round_key_is_history_only": True,
        "authorizes_new_dispatch": False, "creative_quality_passed": False, "text_ready_for_director": False,
        "media_authorized": False, "old_budget_reset": False}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and anchor.get("schema") == VERSION and digest(anchor) == expected_anchor_sha256,
        "registered A/B anchor schema/canonical SHA changed")
    actual = build_anchor(anchor["root"])
    require(actual == anchor, "original registered A/B consumption or evidence changed")
    return {"verified": True, **{key: deepcopy(actual[key]) for key in
        ("root", "inherited", "parent_identity", "parent_identity_sha256", "whole_goal_candidates_used", "old_director_capacity",
         "scope_probe_calls_used", "paired_drama_probe_calls_used", "registered_ab_calls_used", "registered_ab_call_limit",
         "registered_ab_unused_calls", "latest_native_goal_receipt")}, "authorizes_new_dispatch": False}
