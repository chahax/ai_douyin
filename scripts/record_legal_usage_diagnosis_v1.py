"""Record original source false positives and known truncation; never dispatch."""
from copy import deepcopy
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def build_diagnosis(root=None):
    from scripts import run_goal_context_text_production_v18 as run
    root = Path(root) if root is not None else run.PREFLIGHT_PARENT
    ledger, terminal = run.read(root / "CALL_LEDGER.json"), run.read(root / "STATE.json")
    if ([row["ordinal"] for row in ledger["calls"]] != list(range(591, 602))
            or terminal.get("status") != "halt_review_interface_or_unknown"
            or terminal.get("receipt_ordinal") != 601
            or terminal.get("cumulative_goal_candidates_used") != 24
            or terminal.get("opening_setup_calls") != 1):
        raise ValueError("exact closed round16 eleven-call lineage required")
    receipts, paths = {}, []
    for row in ledger["calls"]:
        path = root / row["receipt"]
        if run.sha_file(path) != row["receipt_sha256"]:
            raise ValueError("original legal/truncation receipt changed")
        receipt = run.read(path)
        if row["ordinal"] == 601:
            if not run.known_truncated_review(receipt):
                raise ValueError("601 must remain known usage length failure without an adopted review")
        elif not run.repairable(receipt):
            raise ValueError("591 through600 must remain complete known native responses")
        receipts[row["ordinal"]] = receipt
        paths.append(path)
    goal, source, commitment = (receipts[n] for n in (594, 595, 596))
    native = goal["output"]
    if run.read(root / "goals/native_02.json") != native:
        raise ValueError("exact original594 native planning identity required")
    source_context = run.control.strict_json(source["request"]["messages"][1]["content"])
    if (source_context.get("native_goal_claims") != native["claims"]
            or source_context.get("native_goal_sha256") != run.digest(native)
            or set(source_context) != {"source_packet", "verified_legal_context", "user_goal_contract",
                "origin_catalog", "native_goal_claims", "native_goal_sha256"}
            or set(source["request"]["structured_schema"]["properties"]) != {
                "schema", "goal_sha256", "audit_context_sha256", "claim_checks"}
            or source["validation"].get("accepted") is not True
            or commitment["validation"].get("accepted") is not True):
        raise ValueError("original claims-only request and reported595/596 passes changed")
    claims = {row["id"]: row for row in native["claims"]}
    catalog = run.drama_contract.build_evidence_catalog(native)
    earlier_goal = receipts[591]["output"]
    earlier_source = receipts[592]["output"]["claim_checks"]["CC6"]
    earlier_focused = receipts[593]["output"]["commitment_checks"]["CC6"]
    revision_context = run.control.strict_json(receipts[594]["request"]["messages"][1]["content"])
    forwarded_findings = [finding for decision in revision_context["revision_diagnostics"]["complete_same_source_goal_audits"]
        for finding in decision.get("findings", []) if finding.get("check") == "CC6"]
    if (revision_context.get("previous_complete_document") != earlier_goal
            or earlier_source.get("status") != "pass" or earlier_focused.get("status") != "fail"
            or receipts[593]["validation"].get("accepted") is not False
            or len(forwarded_findings) != 1
            or forwarded_findings[0].get("required_revision") != earlier_focused["required_revision"]):
        raise ValueError("exact592 exemption/593 failed delivery forwarded into complete594 revision changed")
    if (claims["CC6"]["kind"] != "creative_choice"
            or "第三十八条" not in claims["CC6"]["text"]
            or "自己担后果" not in catalog["G047"]["quote"]
            or claims["VL2"]["kind"] != "verified_legal"
            or claims["VL2"]["origin_ids"] != ["L002"]
            or source["output"]["claim_checks"]["CC6"]["status"] != "pass"
            or "非本表法律结论" not in source["output"]["claim_checks"]["CC6"]["reason"]
            or commitment["output"]["commitment_checks"]["CC6"]["status"] != "pass"):
        raise ValueError("exact qualified legal-usage witnesses changed")
    for kind, ordinal in (("source",595),("commitment",596),("drama",597)):
        if (run.read(root / f"goals/{kind}_native_audit_02.json") != receipts[ordinal]["output"]
                or run.read(root / f"goals/{kind}_audit_decision_02.json") != receipts[ordinal]["validation"]):
            raise ValueError("native audit/decision identity changed")
    truncated = receipts[601]
    evidence = root / "call_evidence/call_601"
    raw_path = evidence / "response_body.raw"
    raw = raw_path.read_bytes()
    raw_payload = run.control.strict_json(raw.decode("utf-8"))
    manifest = run.read(evidence / "RESPONSE_BODY_MANIFEST.json")
    if (raw_payload != truncated["response_payload"]
            or run.sha_file(raw_path) != truncated["response_metadata"]["raw_body_sha256"]
            or manifest.get("stored_sha256") != run.sha_file(raw_path)
            or manifest.get("original_sha256") != manifest.get("stored_sha256")
            or manifest.get("body_complete") is not True or manifest.get("bytes") != len(raw)):
        raise ValueError("601 complete outer HTTP capture or usage evidence changed")
    usage = raw_payload["usage"]
    if (usage["prompt_tokens"],usage["completion_tokens"],usage["total_tokens"]) != (58219,32000,90219):
        raise ValueError("original601 known token usage changed")
    arguments = raw_payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    if len(arguments) != 77774:
        raise ValueError("exact601 truncated tool argument prefix changed")
    for relative in ("STATE.json","CALL_LEDGER.json","USER_SCOPE.json","INPUTS.json","goals/native_02.json",
            "goals/source_native_audit_02.json","goals/source_audit_decision_02.json",
            "goals/commitment_native_audit_02.json","goals/commitment_audit_decision_02.json",
            "goals/drama_native_audit_02.json","goals/drama_audit_decision_02.json",
            "setups/native_01.json","scripts/version_02/NATIVE_SCRIPT.json","requests/full_review_semantic_02.json",
            "call_evidence/call_601/IDENTITY.json","call_evidence/call_601/request_body.raw",
            "call_evidence/call_601/REQUEST_BODY_MANIFEST.json","call_evidence/call_601/response_body.raw",
            "call_evidence/call_601/RESPONSE_BODY_MANIFEST.json"):
        paths.append(root / relative)
    scope = run.read(root / "USER_SCOPE.json")
    return {
        "schema": "verified_legal_usage_and_truncation_diagnosis/v1", "source_root": str(root),
        "source_file_sha256": {str(path.resolve()): run.sha_file(path) for path in paths},
        "native_goal_ordinal":594,"native_goal_sha256":run.digest(native),
        "native_source_audit_ordinal":595,"native_source_audit_sha256":run.digest(source["output"]),
        "native_commitment_audit_ordinal":596,"native_commitment_audit_sha256":run.digest(commitment["output"]),
        "truncated_full_review_ordinal":601,"truncated_full_review_not_adopted":True,
        "verified_failures": [
            {"kind":"creative_choice_legal_meaning_exempted_by_claims_only_source_audit",
             "exact_claims":{key:deepcopy(claims[key]) for key in ("CC6","VL2","CC10")},
             "beat_evidence":{"G047":deepcopy(catalog["G047"])},
             "actual_source_input_keys":sorted(source_context),
             "actual_source_schema_tables":list(source["request"]["structured_schema"]["properties"]),
             "actual_source_system_rule":source["request"]["messages"][0]["content"],
             "native_source_cc6_judgment":deepcopy(source["output"]["claim_checks"]["CC6"]),
             "native_source_vl2_judgment":deepcopy(source["output"]["claim_checks"]["VL2"]),
             "native_focused_cc6_judgment":deepcopy(commitment["output"]["commitment_checks"]["CC6"]),
             "prior_literal_delivery_feedback_chain":{
                "original_claim_591":deepcopy(next(row for row in earlier_goal["claims"] if row["id"]=="CC6")),
                "native_source_592_cc6_judgment":deepcopy(earlier_source),
                "native_focused_593_cc6_judgment":deepcopy(earlier_focused),
                "original_593_required_revision_entered_actual_594_request":True,
                "former_required_revision_is_fault_evidence_not_current_instruction":True},
             "diagnosis":"Actual595 contains claims but no beat/ending prose and exempts CC6's named legal route as fictional dialogue. VL2's correct conditions coexist but are not compared with CC6/G047. Actual596 checks literal commitment delivery, so passing it does not establish legal truth. The phrase is legally misleading in framing; it does not literally say no compensation. Article38/46(1) conditions and compensation linkage remain authority, not editable plot facts."},
            {"kind":"known_usage_semantic_review_output_truncated",
             "response_metadata":deepcopy(truncated["response_metadata"]),
             "actual_request_max_completion_tokens":truncated["request"]["parameters"]["max_completion_tokens"],
             "original_native_review_validation":None,"native_review_not_converted":True,
             "argument_prefix_characters":len(arguments),
             "argument_prefix_key_occurrences":{key:arguments.count('"'+key+'"') for key in
                 ("reason","quote","evidence_refs","actual_interpretation","checks","status","required_revision")},
             "diagnosis":"HTTP outer JSON and usage are complete, but the single tool argument prefix ended with length after32000 output tokens. Repeated judgment layers and exact quotation fields are measurable output obligations, not proof of the provider's internal reason. The prefix is not a complete native semantic audit and cannot be accepted, continued or converted locally. New compact full-review contract must retain every semantic/physical responsibility while reducing duplicated prose."}],
        "creative_risks":[{"kind":"legal_statement_framing",
            "evidence":{"G047":deepcopy(catalog["G047"])},
            "diagnosis":"Character speech can intentionally be wrong when current narrative framing and actual correction/dispute make this clear. A creative_choice label or an ending's unresolved-law declaration alone does not prove this. Do not forbid ordinary legal dialogue or replace emotion with recited statutes."}],
        "stage_ownership_direction":[
            "Source audit owns claim provenance and complete current C/G legal usage against preserved authoritative conditions.",
            "Focused audit owns creative commitment scope/relationships, not legal correctness by fiction label.",
            "Drama audit owns event causality, emotional conflict, visible payoff and closed registered production scope.",
            "Opening owns native frozen positions/current prop support; complete screenplay owns performance and reaction execution.",
            "Compact same-source semantic and physical full reviews retain all responsibilities; exact references are not semantic proof."],
        "forwarding_boundary":{"exact_native_goal_is_revision_source":True,"old_native_review_not_adopted":True,
            "old_truncated_review_not_converted":True,"no_manual_native_patch":True,"complete_old_evidence_retained":True,
            "diagnosis_is_human_reading_not_automated_semantic_proof":True},
        "parent_spend":deepcopy(terminal["spend"]),"parent_goal_candidates_used":24,
        "parent_goal_candidates_maximum":scope["cumulative_goal_candidates_this_run_maximum"],
        "parent_unused_goal_candidates":scope["cumulative_goal_candidates_this_run_maximum"]-24,
        "parent_claim_not_restarted":True,"media_calls":0}


def main():
    from scripts import run_goal_context_text_production_v18 as run
    run.prior_guard()
    diagnosis=build_diagnosis()
    run.write(run.CONTENT_DIAGNOSIS,diagnosis,True)
    print(str(run.CONTENT_DIAGNOSIS))


if __name__ == "__main__":
    main()
