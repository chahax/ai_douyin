"""Record closed round15 evidence without changing any native response."""
from scripts import run_goal_context_text_production_v16 as parent


def main():
    root = parent.ROOT
    ledger, terminal = parent.read(root / "CALL_LEDGER.json"), parent.read(root / "STATE.json")
    if (terminal["status"] != "halt_opening_setup_content_capacity_exhausted"
            or terminal["cumulative_goal_candidates_used"] != 22
            or terminal["opening_setup_calls"] != 2
            or [row["ordinal"] for row in ledger["calls"]] != list(range(585, 591))):
        raise ValueError("exact closed six-call round15 required")
    runtime = parent.get_runtime()
    runtime.inherited_guard()
    if terminal["spend"] != runtime.summary():
        raise ValueError("original terminal spend differs from original ledger")
    receipts, paths = {}, []
    for row in ledger["calls"]:
        path = root / row["receipt"]
        if parent.sha_file(path) != row["receipt_sha256"]:
            raise ValueError("original receipt changed")
        receipt = parent.read(path)
        if not parent.repairable(receipt):
            raise ValueError("only complete known native responses can support this diagnosis")
        receipts[row["ordinal"]] = receipt
        paths.append(path)
    if ([receipts[n]["status"] for n in range(585, 591)]
            != ["contract_valid"] * 4 + ["contract_rejected"] * 2):
        raise ValueError("original known planning/audit/setup statuses changed")
    goal, report = receipts[585]["output"], receipts[588]["output"]
    catalog = parent.drama_contract.build_evidence_catalog(goal)
    if (goal != parent.read(root / "goals/native_01.json")
            or report != parent.read(root / "goals/drama_native_audit_01.json")
            or report["closed_scope_findings"]
            or report["goal_checks"]["closed_production_scope"]["status"] != "pass"
            or any(row["source_ref"] == "G083" for row in report["scope_observations"]["b10"]["operated_props"])
            or "文件夹" not in catalog["G083"]["quote"]
            or "G083" not in report["goal_checks"]["closed_production_scope"]["evidence_refs"]):
        raise ValueError("exact witnessed container omission changed")
    if (receipts[589]["output"]["props"]["pr_water"] != {"kind": "absent"}
            or receipts[590]["output"]["props"]["pr_water"] != {"kind": "absent", "orientation": ""}):
        raise ValueError("exact witnessed absence failures changed")
    requests = [root / "requests" / f"opening_setup_{i:02}.json" for i in (1, 2)]
    for path in requests:
        request = parent.read(path)["request"]
        branches = request["structured_schema"]["properties"]["props"]["properties"]["pr_water"]["oneOf"]
        absent = next(row for row in branches if row["properties"]["kind"]["const"] == "absent")
        if (absent["properties"]["orientation"] != {"const": None}
                or set(absent["required"]) != {"kind", "orientation"}
                or "absent只填kind和orientation:null" in request["messages"][0]["content"]
                or "absent表示尚未在场" not in request["messages"][0]["content"]):
            raise ValueError("actual null schema or witnessed missing system field rule changed")
    for relative in ("STATE.json", "CALL_LEDGER.json", "USER_SCOPE.json", "goals/native_01.json",
            "goals/source_native_audit_01.json", "goals/commitment_native_audit_01.json",
            "goals/drama_native_audit_01.json", "goals/drama_audit_decision_01.json",
            "setups/native_01.json", "setups/native_02.json"):
        paths.append(root / relative)
    paths.extend(requests)
    scope = parent.read(root / "USER_SCOPE.json")
    diagnosis = {
        "schema": "verified_scope_coverage_and_absence_diagnosis/v1", "source_root": str(root),
        "source_file_sha256": {str(path.resolve()): parent.sha_file(path) for path in paths},
        "native_goal_ordinal": 585, "native_goal_sha256": parent.digest(goal),
        "native_drama_audit_ordinal": 588, "native_drama_audit_sha256": parent.digest(report),
        "native_setup_ordinals": [589, 590],
        "verified_failures": [
            {"kind": "unregistered_actual_container_missed_by_native_audit",
             "evidence": {ref: catalog[ref] for ref in ("G083", "G107")},
             "declared_props": goal["whole_plan"]["props"],
             "native_b10_observations": report["scope_observations"]["b10"],
             "native_closed_scope_judgment": report["goal_checks"]["closed_production_scope"],
             "native_closed_scope_findings": [],
             "diagnosis": "G083 explicitly folds and puts the agreement into a folder, which the complete registry does not declare. Native588 reads G083/G107 for agreement-state consistency but never observes the operated container. v10 permits the omitted field because it validates submitted observations rather than every beat/ending G field."},
            {"kind": "known_native_absence_schema_failure",
             "responses": {str(n): receipts[n]["output"]["props"]["pr_water"] for n in (589, 590)},
             "actual_requested_absent_fields": {"kind": "absent", "orientation": None},
             "request_schema_rule_present": True, "explicit_module_field_rule_in_actual_system": False,
             "diagnosis": "Absent objects have no physical orientation, but v2 demands an explicit null. Both actual tool Schemas state this rule; the module's explicit absent field rule is not wired into the actual system message, which only explains absence. Writer first omits it, then submits an empty string. Neither failed native output is locally filled or adopted. New v3 must wire its single contract rule to the actual request, not convert the old outputs."}],
        "creative_risks": [
            {"kind": "promised_vs_completed_result", "evidence": {ref: catalog[ref] for ref in ("G071", "G078", "G104", "G107")},
             "diagnosis": "Photographing and saying one will send/write do not demonstrate that sending and signed paper work already happened. A whole native revision must clarify exactly which action occurs and what remains a promise; do not use an ending assertion to fill a missing cause."},
            {"kind": "prop_entity_granularity", "evidence": {ref: catalog[ref] for ref in ("G113", "G127")},
             "diagnosis": "Two entries describe a roster clipboard; one combines clipboard and lamp. This is an identity/atomic-prop ambiguity, not a proven owner/holder contradiction."},
            {"kind": "drama_payoff_center", "evidence": {ref: catalog[ref] for ref in ("G003", "G023", "G027", "G039", "G055", "G078", "G105", "G108")},
             "diagnosis": "Keep bodily cost, opponent pressure and human responses while making the choice/payoff visible. Do not let signatures, classification and repeated reassurance take the place of dramatic events. This is a creative risk, not a forbidden-word check or a hand-authored replacement plot."}],
        "stage_ownership_direction": [
            "Whole native plan registers actually operated objects and containers and clarifies explicit causal/terminal states.",
            "Opening owns exact frozen character positions and current prop holder/support; absence carries no physical direction.",
            "Focused commitment audit owns C requirements and same-source relationships; drama owns functional storytelling and field-covered operation extraction without duplicating commitment checks.",
            "Complete native screenplay and performance own local execution and reaction windows; same-source semantic and physical full reviews must both pass."],
        "forwarding_boundary": {"exact_native_goal_is_revision_source": True,
            "old_native_review_not_adopted": True, "old_native_setup_not_converted": True,
            "no_manual_native_patch": True, "complete_old_evidence_retained": True,
            "diagnosis_is_human_reading_not_automated_semantic_proof": True},
        "parent_spend": terminal["spend"],
        "parent_goal_candidates_used": 22,
        "parent_goal_candidates_maximum": scope["cumulative_goal_candidates_this_run_maximum"],
        "parent_unused_goal_candidates": scope["cumulative_goal_candidates_this_run_maximum"] - 22,
        "parent_claim_not_restarted": True, "media_calls": 0}
    target = parent.PROJECT / "data/qa/creative_scope_coverage_20261014/ROUND15_DIAGNOSIS_v1.json"
    parent.write(target, diagnosis, True)
    print(str(target))


if __name__ == "__main__":
    main()
