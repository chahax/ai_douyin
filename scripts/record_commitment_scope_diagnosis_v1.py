"""Record exact closed round14 evidence; never modify native outputs."""
from scripts import run_goal_context_text_production_v15 as parent


def main():
    root = parent.ROOT
    ledger, terminal = parent.read(root / "CALL_LEDGER.json"), parent.read(root / "STATE.json")
    if (terminal["status"] != "halt_goal_content_capacity_exhausted"
            or terminal["cumulative_goal_candidates_used"] != 21
            or [r["ordinal"] for r in ledger["calls"]] != list(range(581, 585))):
        raise ValueError("exact closed four-call round14 required")
    parent.get_runtime().inherited_guard()
    receipts, paths = {}, []
    for row in ledger["calls"]:
        path = root / row["receipt"]
        if parent.sha_file(path) != row["receipt_sha256"]:
            raise ValueError("original receipt changed")
        receipt = parent.read(path)
        if not parent.repairable(receipt):
            raise ValueError("complete known native responses only")
        receipts[row["ordinal"]] = receipt
        paths.append(path)
    goal, report = receipts[582]["output"], receipts[584]["output"]
    if (receipts[582]["status"] != "contract_valid" or receipts[583]["status"] != "contract_valid"
            or receipts[584]["status"] != "contract_valid" or receipts[584]["validation"]["accepted"]):
        raise ValueError("known native goal and rejected complete semantic verdict required")
    catalog = parent.drama_contract.build_evidence_catalog(goal)
    refs = ["C:c_choice_premise", "C:c_choice_paper", "C:c_choice_boundary", "G006", "G007", "G023",
            "G031", "G039", "G045", "G060", "G063", "G064", "G076", "G086", "G091", "G093"]
    selected = {ref: catalog[ref] for ref in refs}
    checks = report["commitment_checks"]
    # Claims do not contain a same-beat requirement. This is a recorded human
    # diagnosis with actual native words, not automatic Chinese interpretation.
    if ("同一拍" not in checks["c_choice_premise"]["literal_requirement"]
            or "拍内" not in checks["c_choice_paper"]["literal_requirement"]
            or checks["c_choice_boundary"]["status"] != "pass"
            or checks["c_choice_boundary"]["counterevidence_refs"]):
        raise ValueError("exact witnessed reviewer scope and missed contradiction changed")
    for relative in ("STATE.json", "CALL_LEDGER.json", "USER_SCOPE.json", "goals/native_01.json",
            "goals/native_02.json", "goals/source_native_audit_02.json", "goals/source_audit_decision_02.json",
            "goals/commitment_native_audit_02.json", "goals/commitment_audit_decision_02.json"):
        paths.append(root / relative)
    diagnosis = {
        "schema": "verified_commitment_application_scope_diagnosis/v1", "source_root": str(root),
        "source_file_sha256": {str(path.resolve()): parent.sha_file(path) for path in paths},
        "native_goal_sha256": parent.digest(goal), "native_commitment_audit_sha256": parent.digest(report),
        "native_goal_ordinal": 582, "native_commitment_audit_ordinal": 584,
        "verified_failures": [
            {"kind": "invented_same_beat_requirement",
             "checks": {key: {"literal_requirement": checks[key]["literal_requirement"],
                              "status": checks[key]["status"], "required_revision": checks[key]["required_revision"]}
                        for key in ("c_choice_premise", "c_choice_paper")},
             "evidence": {ref: selected[ref] for ref in
                ("C:c_choice_premise", "C:c_choice_paper", "G007", "G023", "G031", "G039", "G045", "G076", "G086", "G093")},
             "diagnosis": "Original C has no same-beat all-clause deadline. Background identities and defined paper content are authoritative global definitions; later collection and white-shift consequence actually occur in relevant later beats. Usage links are not all-clauses-must-happen-now obligations."},
            {"kind": "state_contradiction_missed", "check": "c_choice_boundary", "native_status": "pass",
             "native_counterevidence_refs": [],
             "evidence": {ref: selected[ref] for ref in ("C:c_choice_boundary", "G060", "G063", "G064", "G091")},
             "diagnosis": "Only attendance book leaves under her arm in b8, while ending says its overtime records stay in the same warehouse. No duplicate or return mechanism. Full lossless context was supplied; false pass is not missing input."},
            {"kind": "unregistered_actual_operated_prop",
             "evidence": {"G006": selected["G006"]},
             "declared_prop_ids": [row["id"] for row in goal["whole_plan"]["props"]],
             "diagnosis": "b1 explicitly puts a turnover box down; box has no entry in the complete global prop registry. This is actual operation, not merely mentioning a background object."}],
        "creative_risks": [
            "Inventory board may have separate account and actual columns; do not declare fraud from an ambiguous difference row. New whole plan must clarify actual truth and its causal use.",
            "Credible causal link between inventory discrepancy and supervisor recognizing wage debt is not established by generic pressure alone.",
            "Emotion reward again centers on signatures, records and exhausted reassurance; actual character resistance, response and visible human payoff need a fresh conception.",
            "Locking the warehouse while supervisor stays inside needs a clear spatial/execution premise; keys mentioned in wardrobe are not proof of their actual use."],
        "stage_ownership_direction": [
            "Background definitions support compatibility without forcing expository opening dialogue.",
            "Actual dynamic conditions and cross-beat/ending state must be compared against real events; definitions, goals or ending claims cannot invent actions.",
            "Planning registers actually operated props and resolves declared state contradiction; later setup/performance handles local execution detail."],
        "forwarding_boundary": {"old_full_plan_not_first_request_template": True,
            "old_full_review_not_adopted": True, "no_manual_native_patch": True,
            "complete_old_evidence_retained": True, "diagnosis_is_human_reading_not_automated_semantic_proof": True},
        "parent_spend": terminal["spend"], "media_calls": 0}
    target = parent.PROJECT / "data/qa/creative_commitment_scope_20261014/ROUND14_APPLICATION_SCOPE_DIAGNOSIS_v1.json"
    parent.write(target, diagnosis, True)
    print(str(target))


if __name__ == "__main__":
    main()
