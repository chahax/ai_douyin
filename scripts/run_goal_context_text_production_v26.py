"""New native goal -> audited full screenplay, preserving the spent old lineage.

Only this new text grant is dispatched. No media, publication or old-call retry.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_m31_flash_role_clients_v1 as clients
from scripts import creative_deepseek_strict_role_clients_v4 as strict_clients
from scripts import run_m31_flash_script_test_v1 as parent
from scripts import run_fresh_legal_full_flow_v1 as original
from scripts import preview_goal_context_workflow_v3 as preview
from scripts import run_goal_context_text_production_v25 as previous
from src.content_factory import creative_goal_context_workflow_v22 as workflow
from src.content_factory import creative_goal_drama_audit_contract_v11 as drama_contract
from src.content_factory import creative_goal_source_contract_v4 as goals
from src.content_factory import creative_opening_setup_contract_v4 as setups
from src.content_factory import creative_split_full_review_contract_v4 as reviews
from src.content_factory import creative_full_review_contract_v5 as complete_reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks

VERSION = "goal_context_text_production/v26"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_25"
GRANT = "fixed_legal_source_sparse_audit_20261014"
PREFLIGHT_PARENT = previous.ROOT
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
APPROVAL = CLAIM.parent / "USER_CONTINUATION_v1.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v7.json"
PLAN = PROJECT / "docs/CREATIVE_FIXED_LEGAL_SOURCE_AND_SPARSE_AUDIT_PLAN_20261014.md"
PARENT_STATE = PREFLIGHT_PARENT / "STATE.json"
CERTIFICATE = ROOT / "CERTIFIED_PARENT_LINEAGE.json"
USER_DIRECTION_CONFIRMATION = previous.USER_DIRECTION_CONFIRMATION
INPUT_SUPPLEMENT_AUTHORIZATION = previous.INPUT_SUPPLEMENT_AUTHORIZATION
SUPPLEMENTED_INPUTS = previous.SUPPLEMENTED_INPUTS
SUPPLEMENTED_PREVIEW = previous.SUPPLEMENTED_PREVIEW
REQUEST_PREVIEW = PROJECT / "data/qa/creative_fixed_legal_sparse_20261014/FIRST_NATIVE_PLAN29_REQUEST_PREVIEW_v1.json"
REVIEW_QUESTIONS = PROJECT / "data/qa/creative_fixed_legal_sparse_20261014/ROOT_616_617_DIAGNOSTICS_v1.json"
FIRST_DIAGNOSTICS = REQUEST_PREVIEW.parent / "FIRST_COMPLETE_NATIVE_PLAN_REVISION_DIAGNOSTICS_v1.json"
read, write, digest, sha_file, now = control.read, control.write, control.digest, control.sha_file, control.now


def prior_guard():
    runtime=previous.get_runtime();runtime.inherited_guard();summary=runtime.summary()
    ledger=read(runtime.ledger)
    if [row["ordinal"] for row in ledger["calls"]]!=[616,617]:raise ValueError("exact616/617 closed parent ledger required")
    for row in ledger["calls"]:
        path=PREFLIGHT_PARENT/row["receipt"];receipt=read(path)
        if sha_file(path)!=row["receipt_sha256"]:raise ValueError("exact original parent receipt changed")
        original.verify_receipt_evidence(runtime,receipt,receipt["request"])
        if not repairable(receipt):raise ValueError("complete known parent native output required")
        expected="contract_valid" if row["ordinal"]==616 else "contract_rejected"
        if receipt.get("status")!=expected:raise ValueError("exact616 planning/617 source rejection required")
        if (receipt["response_metadata"]["total_tokens"]!=(49054 if row["ordinal"]==616 else 51543)
                or (row["ordinal"]==617 and original.classify_receipt(receipt)!=(True,"content_rejected","accepted"))):
            raise ValueError("exact616/617 known complete consumption required")
    terminal=read(PARENT_STATE);scope=read(PREFLIGHT_PARENT/"USER_SCOPE.json")
    if (terminal.get("status")!="halt_goal_audit_contract_requires_pipeline_diagnosis"
            or terminal.get("receipt_ordinal")!=617 or terminal.get("audit_kind")!="source"
            or terminal.get("text_ready_for_director") is not False or terminal.get("spend")!=summary
            or terminal.get("cumulative_goal_candidates_used")!=28 or terminal.get("opening_setup_calls")!=0
            or (summary["effective_calls_started"],summary["effective_reported_tokens"],summary["effective_calls_with_known_usage"])!=(617,12833156,615)
            or summary["stage_calls"]!={"goal_plan":1,"goal_audit":1,"complete_script":0,"full_review":0}
            or summary.get("new_unknown_token_reservations")!=0 or summary.get("unknown_token_reservations")!=93117
            or summary.get("historical_pending_ordinals")!=[70,160]
            or scope.get("inherited_goal_candidates_used")!=27 or scope.get("local_goal_candidates_limit")!=2
            or scope.get("cumulative_goal_candidates_this_run_maximum")!=29
            or summary["stage_limits"]!=scope["stage_limits"]):
        raise ValueError("exact617 spend/stages/used28/max29/closedunused1 required")
    verify_seed_native(read(PREFLIGHT_PARENT/"goals/native_01.json"))
    return summary


def models(profile):
    return {role: {key: profile[role][key] for key in ("provider", "model", "base_url")}
            for role in ("writer", "director")}


def verify_seed_native(seed):
    rows=[row for row in read(PREFLIGHT_PARENT/"CALL_LEDGER.json")["calls"] if row["ordinal"]==616]
    if len(rows)!=1:raise ValueError("exact616 planning receipt required")
    row=rows[0];path=PREFLIGHT_PARENT/row["receipt"];receipt=read(path)
    if (sha_file(path)!=row["receipt_sha256"] or not repairable(receipt) or receipt.get("status")!="contract_valid"
            or receipt["request"]["stage"]!="goal_plan" or receipt.get("output")!=seed
            or seed!=read(PREFLIGHT_PARENT/"goals/native_01.json")):
        raise ValueError("exact complete616 pending source admission required")
    return {"ordinal":616,"receipt_path":str(path),"receipt_sha256":row["receipt_sha256"],
        "native_sha256":digest(seed),"contract_valid":True,"semantic_approved":False,
        "used_only_as_complete_native_revision_seed":True}


def get_runtime():
    from scripts.creative_goal_context_dispatch_v10 import GoalContextRuntime
    from scripts import creative_flat_lineage_guard_v6 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v6 as verifier
    freeze = read(ROOT / "PRODUCTION_FREEZE.json")
    profile = read(PROFILE)
    def guard():
        lineage.verify_lineage_certificate(read(CERTIFICATE),
            expected_certificate_sha256=freeze["parent_certificate_sha256"],
            fresh_source_gate=parent.source_gate, expected_inherited=freeze["inherited"])
        if sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json") != freeze["parent_ledger_sha256"]:
            raise ValueError("parent consumption ledger changed")
        if verify_seed_native(read(ROOT / "INHERITED_NATIVE_GOAL.json")) != freeze["seed_native_identity"]:
            raise ValueError("seed native receipt binding changed")
        if (read(CLAIM)["root"] != str(ROOT)
                or sha_file(APPROVAL) != freeze["continuation_authorization_sha256"]
                or sha_file(INPUT_SUPPLEMENT_AUTHORIZATION) != freeze["input_supplement_authorization_sha256"]
                or sha_file(CLAIM) != freeze["global_claim_sha256"]):
            raise ValueError("global authorization claim changed")
        for path, expected in freeze["files"].items():
            if sha_file(path) != expected:
                raise ValueError("new independent frozen input changed: " + path)
    return GoalContextRuntime(PROJECT, ROOT, [Path(path) for path in freeze["sources"]],
        freeze["inherited"], freeze["models"], inherited_guard=guard, profile=profile,
        stage_limits=read(ROOT / "USER_SCOPE.json")["stage_limits"], quota_state=None,
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock",
        client_factory_builder=lambda request: strict_clients.make_client_factory(request,
            source_strict=is_strict_source(request),review_base_url=profile["source_strict"]["base_url"],
            max_wire_utf8_bytes=profile["source_strict"]["max_wire_utf8_bytes"]))


def authorization_request_identity(diagnostic, prepared):
    """Pin local recovery and dispatch preparation to one actual text request."""
    return {
        "source_inputs_sha256": sha_file(PREFLIGHT_PARENT / "INPUTS.json"),
        "model_profile_sha256": sha_file(PROFILE),
        "derived_revision_diagnostics_sha256": digest(diagnostic),
        "actual_prepared_preview_sha256": digest(prepared),
    }


def verify_authorization_request_binding(approval, diagnostic, first_request, seed_identity):
    """Pure binding checks run before the global new-run claim is created."""
    if (any(approval.get(key) != value for key, value in authorization_request_identity(diagnostic, first_request).items())
            or approval.get("schema")!=VERSION+"/derived_authorization_binding"
            or approval.get("parent_root")!=str(PREFLIGHT_PARENT)
            or approval.get("parent_state_sha256")!=sha_file(PARENT_STATE)
            or approval.get("seed_native_identity")!=seed_identity
            or approval.get("new_local_bound_from_existing_authority")!=1
            or approval.get("new_cumulative_goal_candidates_maximum")!=29
            or approval.get("first_action_is_native_plan_rebuild") is not True
            or approval.get("source_only_strict_protocol") is not True
            or approval.get("known_complete_source_fail_allows_bounded_native_goal_revision") is not True
            or approval.get("known_native_goal_audit_content_uncertainty_allows_bounded_plan_revision") is not True
            or approval.get("source_interface_unknown_or_protocol_failure_stops_new_run") is not True
            or approval.get("body_requires_all_three_audits_accepted_without_uncertainty") is not True
            or approval.get("new_format_or_report_recovery_claimed") is not False
            or approval.get("parent_unused_capacity_stays_in_closed_run") is not True
            or approval.get("old_ledger_reset") is not False
            or approval.get("automatic_transport_retry") is not False
            or approval.get("media_authorized") is not False or approval.get("publish_authorized") is not False):
        raise ValueError("continuing authorization inputs, profile, diagnosis or actual request changed")


def verify_inherited_direction_inputs(inputs):
    """Latest ten human rows are inherited exactly, never appended or reauthorized."""
    if inputs!=read(SUPPLEMENTED_INPUTS) or inputs!=read(PREFLIGHT_PARENT/"INPUTS.json"):
        raise ValueError("latest direction supplemented source inputs changed")
    proof=read(PREFLIGHT_PARENT/"USER_DIRECTION_INPUT_SUPPLEMENT.json")
    if proof!=read(INPUT_SUPPLEMENT_AUTHORIZATION):
        raise ValueError("original direction supplement binding changed")
    if (proof.get("supplemented_inputs_sha256")!=digest(inputs)
            or proof.get("human_direction_confirmation_sha256")!=sha_file(USER_DIRECTION_CONFIRMATION)
            or proof.get("appended_user_ids")!=["UC_CONFIRMED_SUPERMARKET_DIRECTION","UG_INTENSIFIED_EMOTIONAL_EXCHANGE"]
            or proof.get("append_only_user_rows") is not True
            or proof.get("confirmation_is_direction_not_manuscript_adoption") is not True
            or proof.get("media_authorized") is not False or proof.get("publish_authorized") is not False
            or proof.get("old_ledger_reset") is not False or proof.get("automatic_transport_retry") is not False
            or read(SUPPLEMENTED_PREVIEW).get("input_supplement_binding")!=proof):
        raise ValueError("original exact direction identity and no-adoption boundary required")
    return proof


def prepare():
    if ROOT.exists() or CLAIM.exists():
        raise RuntimeError("existing global grant/root; inspect original, never regrant")
    from scripts import creative_flat_lineage_guard_v6 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v6 as verifier
    expected = read(PARENT_STATE)["spend"]
    certificate = lineage.build_lineage_certificate(PROJECT, PREFLIGHT_PARENT,
        certified_check=prior_guard, expected_summary=expected,
        dependency_paths=[PARENT_STATE],
        guard_code_paths=[Path(__file__), Path(lineage.__file__), Path(verifier.__file__)])
    consumed = expected
    approval = read(APPROVAL)
    if (approval.get("human_authorized") is not True or approval.get("user_quote") != "minimax随便追加"
            or approval.get("parent_ledger_sha256") != sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")
            or approval.get("parent_goal_candidates_used") != 28
            or approval.get("parent_whole_plan_maximum") != 29
            or approval.get("parent_whole_plan_unused_capacity") != 1
            or approval.get("authority_source_sha256") != sha_file(previous.APPROVAL)
            or approval.get("input_supplement_authorization_sha256") != sha_file(INPUT_SUPPLEMENT_AUTHORIZATION)
            or approval.get("human_direction_confirmation_sha256") != sha_file(USER_DIRECTION_CONFIRMATION)):
        raise ValueError("explicit continuing user authorization and unchanged spent lineage required")
    inputs = read(PREFLIGHT_PARENT / "INPUTS.json")
    input_supplement = verify_inherited_direction_inputs(inputs)
    seed = read(PREFLIGHT_PARENT / "goals/native_01.json")
    seed_identity = verify_seed_native(seed)
    diagnostic = build_revision_diagnostics(seed)
    source_check = parent.source_gate()
    first_request = prepare_first_goal_request(inputs,read(PROFILE),seed,diagnostic)
    verify_authorization_request_binding(approval, diagnostic, first_request, seed_identity)
    saved_preview=read(REQUEST_PREVIEW)
    if (saved_preview.get("prepared") != first_request or saved_preview.get("seed_native_identity")!=seed_identity
            or type(saved_preview.get("provider_calls")) is not int or saved_preview.get("provider_calls")!=0
            or type(saved_preview.get("media_calls")) is not int or saved_preview.get("media_calls")!=0
            or saved_preview.get("creative_quality_approved") is not False
            or saved_preview.get("old_source617_not_converted") is not True
            or saved_preview.get("pending_content_risks_not_native_judgments") is not True):
        raise ValueError("actual authorization preview changed; no new run claim created")
    inherited = {"calls_started": consumed["effective_calls_started"],
        "reported_tokens": consumed["effective_reported_tokens"],
        "calls_with_known_usage": consumed["effective_calls_with_known_usage"],
        "unknown_token_reservations": consumed["unknown_token_reservations"],
        "pending_ordinals": consumed["historical_pending_ordinals"]}
    scope = {"schema": VERSION + "/user_scope", "grant_id": GRANT,
        "user_quote": approval["user_quote"], "writer_total_call_user_limit": None,
        "stage_limits": {"goal_plan": 3, "goal_audit": 3, "complete_script": 3, "full_review": 6},
        "stage_limits_are_local_run_safety_bounds": True,
        "inherited_goal_candidates_used": 28, "local_goal_candidates_limit": 1,
        "local_opening_setup_limit": 2, "cumulative_goal_candidates_this_run_maximum": 29,
        "seed_goal_ordinal": 616, "seed_goal_semantic_approved": False,
        "seed_used_only_for_complete_model_revision": True, "seed_used_for_fresh_native_source_readmission": False, "first_request_is_fresh_reconception": False, "first_action_is_native_plan_rebuild": True,
        "known_complete_source_fail_allows_bounded_native_goal_revision": True,
        "source_interface_unknown_or_protocol_failure_stops_new_run":True,
        "known_native_goal_audit_content_uncertainty_allows_bounded_plan_revision":True,
        "body_requires_all_three_audits_accepted_without_uncertainty":True,
        "parent_whole_plan_maximum": 29, "parent_whole_plans_used": 28,
        "parent_whole_plan_unused_capacity": 1, "parent_unused_capacity_stays_in_closed_run": True,
        "new_local_bound_from_existing_authority": 1,
        "old_goal_allowance_reset": False, "deepseek_scope": "few necessary source and whole-text reviews",
        "content_revision_limit": 2, "old_m31_one_writer_one_review_used": 2,
        "old_director_candidates_used": 7, "old_director_candidates_limit": 7,
        "additional_director_candidates": 0, "media_authorized": False, "publish_authorized": False,
        "automatic_transport_retry": False, "new_format_recovery_claimed": False,
        "human_direction_confirmation_sha256":sha_file(USER_DIRECTION_CONFIRMATION),
        "input_supplement_authorization_sha256":sha_file(INPUT_SUPPLEMENT_AUTHORIZATION),
        "max_total_tokens": None, "starting_spend": inherited,
        "parent_ledger_sha256": sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")}
    write(CLAIM, {"schema": VERSION + "/continuation_claim", "grant_id": GRANT,
        "root": str(ROOT), "created_at": now(), "parent_root": str(PREFLIGHT_PARENT),
        "authorization_sha256": sha_file(APPROVAL),
        "input_supplement_authorization_sha256":sha_file(INPUT_SUPPLEMENT_AUTHORIZATION),
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "inherited_goal_candidates_used": 28,
        "old_allowance_reset": False}, True)
    ROOT.mkdir(parents=True)
    write(CERTIFICATE, certificate, True)
    write(ROOT / "USER_SCOPE.json", scope, True)
    write(ROOT / "INPUTS.json", inputs, True)
    write(ROOT / "ORIGINAL_PARENT_INPUTS.json", read(PREFLIGHT_PARENT/"INPUTS.json"), True)
    write(ROOT / "USER_DIRECTION_INPUT_SUPPLEMENT.json", input_supplement, True)
    write(ROOT / "INHERITED_NATIVE_GOAL.json", seed, True)
    write(ROOT / "INHERITED_DIAGNOSTICS.json", diagnostic, True)
    write(ROOT / "SOURCE_GATE.json", source_check, True)
    write(ROOT / "FIRST_NATIVE_PLAN_REQUEST_PREVIEW.json", first_request, True)
    # Freeze every old production dependency plus all new independent modules.
    paths = set(read(PREFLIGHT_PARENT / "PRODUCTION_FREEZE.json")["files"])
    paths.update(str(p.resolve()) for p in (Path(__file__), PROFILE, PLAN,
        PARENT_STATE, PROJECT / "src/content_factory/creative_goal_revision_feedback_v1.py",
        Path(strict_clients.__file__), Path(workflow.__file__), PROJECT / "src/content_factory/creative_goal_evidence_view_v1.py", PROJECT / "src/content_factory/creative_goal_legal_usage_source_audit_v5.py", PROJECT / "src/content_factory/creative_goal_commitment_audit_v2.py", Path(drama_contract.__file__), Path(goals.__file__), Path(reviews.__file__), Path(complete_reviews.__file__), Path(setups.__file__),
        PROJECT / "src/content_factory/creative_stage_context_v3.py", APPROVAL, CERTIFICATE,
        USER_DIRECTION_CONFIRMATION,INPUT_SUPPLEMENT_AUTHORIZATION,SUPPLEMENTED_INPUTS,SUPPLEMENTED_PREVIEW,
        REQUEST_PREVIEW, REVIEW_QUESTIONS, FIRST_DIAGNOSTICS,
        PROJECT / "src/content_factory/creative_goal_audit_citation_contract_v1.py",
        PROJECT / "scripts/record_fixed_legal_source_sparse_continuation_v1.py",
        PROJECT / "scripts/creative_goal_context_dispatch_v10.py", Path(lineage.__file__), Path(verifier.__file__), Path(clients.__file__),
        PREFLIGHT_PARENT / "RUN_CLAIM.json", PREFLIGHT_PARENT / "CALL_LEDGER.json",
        ROOT / "USER_SCOPE.json", ROOT / "INPUTS.json", ROOT / "INHERITED_NATIVE_GOAL.json",
        ROOT / "ORIGINAL_PARENT_INPUTS.json",ROOT / "USER_DIRECTION_INPUT_SUPPLEMENT.json",
        ROOT / "INHERITED_DIAGNOSTICS.json", ROOT / "SOURCE_GATE.json",
        ROOT / "FIRST_NATIVE_PLAN_REQUEST_PREVIEW.json"))
    paths.add(str((PROJECT/"src/content_factory/creative_deepseek_strict_schema_v1.py").resolve()))
    paths.update(diagnostic["source_file_sha256"])
    freeze = {"schema": VERSION + "/freeze", "inherited": inherited,
        "parent_certificate_sha256": digest(certificate),
        "seed_native_identity": seed_identity,
        "models": models(read(PROFILE)), "global_claim_sha256": sha_file(CLAIM),
        "continuation_authorization_sha256": sha_file(APPROVAL),
        "input_supplement_authorization_sha256":sha_file(INPUT_SUPPLEMENT_AUTHORIZATION),
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "sources": sorted(paths),
        "files": {path: sha_file(path) for path in sorted(paths)}, "media_authorized": False}
    write(ROOT / "PRODUCTION_FREEZE.json", freeze, True)
    result = get_runtime().prepare()
    write(ROOT / "STATE.json", {"status": "prepared", "text_ready_for_director": False,
        "human_quality_approved": False, "creative_quality_passed": False, "spend": result})
    return result


def known_parent_source():
    from src.content_factory import creative_flat_lineage_verifier_v6 as verifier
    ledger=read(PREFLIGHT_PARENT/"CALL_LEDGER.json")
    rows=[row for row in ledger["calls"] if row["ordinal"]==617]
    if len(rows)!=1:raise ValueError("one exact617 complete source receipt required")
    cycle=verifier.VerificationCycle()
    receipt=verifier._receipt(cycle,PROJECT,PREFLIGHT_PARENT,rows[0],ledger["source_manifest"])
    if (receipt.get("status")!="contract_rejected" or not repairable(receipt)
            or original.classify_receipt(receipt)!=(True,"content_rejected","accepted")):
        raise ValueError("original617 rejected native report retained, no new approval")
    return receipt,{path:cycle.sha(path) for path in sorted(cycle._bytes)}


def load_rebuild_questions(seed,receipt):
    questions=read(REVIEW_QUESTIONS)
    expected={"native_goal_ordinal":616,"native_goal_sha256":digest(seed),
        "native_source_report_ordinal":617,"native_source_report_sha256":digest(receipt["output"]),
        "parent_terminal_state_sha256":sha_file(PARENT_STATE)}
    if (questions.get("schema")!="creative_fixed_legal_source_sparse_diagnostics/v1"
            or any(questions.get(key)!=value for key,value in expected.items())
            or questions.get("original_complete_report_required") is not True
            or any(questions.get(key) is not False for key in ("native_goal_locally_patched","native_report_locally_converted","human_adopted","creative_quality_passed"))
            or questions.get("original_source617_failure")!=receipt["failure"]
            or questions.get("original_source617_validation_error")!=receipt["validation_error"]):
        raise ValueError("exact616/617 bound complete diagnosis required")
    catalog=workflow.source_audit.build_evidence_catalog(seed)
    failure=questions["exact_frame_quote_failure"]
    frame=receipt["output"]["source_observations"][152]
    witness=frame["usages"][0]["interpretation_frame_evidence"][1]
    source=catalog[witness["frame_ref"]]
    if (failure["observation_source_ref"]!=frame["source_ref"] or failure["native_usage"]!=witness
            or failure["actual_source"]!={"document_path":source["document_path"],"quote":source["quote"]}
            or failure["quote_is_verbatim"] is not False or witness["quote"] in source["quote"]):
        raise ValueError("exact617 rejected cross-quote evidence required")
    drift=questions["legal_source_drift"]
    claims={row["id"]:row for row in seed["claims"]}
    legal_context=read(PREFLIGHT_PARENT/"INPUTS.json")["verified_legal_context"]
    legal_facts={f"L{index:03}":deepcopy(row) for index,row in enumerate(legal_context["facts"],1)}
    if (drift["claim"]!=claims.get(drift["claim"]["id"])
            or drift["fixed_source_fact"]!=legal_facts.get(drift["authority_id"])
            or drift["native_statement_is_not_identical_to_fixed_source"] is not True
            or drift["claim"]["text"]==drift["fixed_source_fact"]["paraphrase"]):
        raise ValueError("original616 statement and immutable legal source difference changed")
    for row in questions["creative_causal_review_questions"]:
        if row.get("pending_model_adjudication") is not True:raise ValueError("creative questions remain pending")
        if row["source_refs"]!=[source["source_ref"] for source in row["native_sources"]]:
            raise ValueError("creative question directory references differ")
        for source in row["native_sources"]:
            ref=source["source_ref"]
            if (ref not in catalog or source["document_path"]!=catalog[ref]["document_path"]
                    or source["quote"]!=catalog[ref]["quote"]):
                raise ValueError("creative question must retain exact original616 evidence")
    return questions


def build_revision_diagnostics(seed):
    verify_seed_native(seed)
    receipt,files=known_parent_source();questions=load_rebuild_questions(seed,receipt)
    files[str(REVIEW_QUESTIONS)]=sha_file(REVIEW_QUESTIONS)
    return {"schema":VERSION+"/qualified_native_plan_rebuild_diagnosis","native_goal_ordinal":616,
        "native_goal_sha256":digest(seed),"original_receipt_ordinal":617,
        "original_source_context_sha256":receipt["request"]["input_provenance"]["source_context_sha256"],
        "original_authority_context_sha256":receipt["request"]["input_provenance"]["authority_context_sha256"],
        "original_native_report_sha256":digest(receipt["output"]),"original_request_sha256":receipt["request_sha256"],
        "complete_native_previous_source_report":deepcopy(receipt["output"]),
        "original_source_failure":deepcopy(receipt["failure"]),"original_validation_error":deepcopy(receipt["validation_error"]),
        "complete_fixed_legal_and_sparse_repair_qa":questions,"source_file_sha256":files,
        "first_action_is_complete_native_plan_rebuild":True,"native_goal_locally_patched":False,
        "original617_rejected_report_preserved":True,"original617_not_new_goal_approval":True,
        "new_format_or_report_recovery_claimed":False}


def model_rebuild_diagnostics(diagnostic):
    qa=diagnostic["complete_fixed_legal_and_sparse_repair_qa"]
    projected={key:deepcopy(qa[key]) for key in ("schema","native_goal_ordinal","native_goal_sha256",
        "native_source_report_ordinal","native_source_report_sha256","parent_terminal_state_sha256",
        "exact_frame_quote_failure","legal_source_drift","creative_causal_review_questions",
        "original_complete_report_required","native_goal_locally_patched","native_report_locally_converted","human_adopted","creative_quality_passed")}
    projected.update(original_complete_qa_file_sha256=sha_file(REVIEW_QUESTIONS),original617_is_not_new_goal_approval=True)
    output={key:deepcopy(value) for key,value in diagnostic.items()
        if key not in ("source_file_sha256","complete_fixed_legal_and_sparse_repair_qa")}
    output["fixed_legal_and_causal_review"]=projected
    return output


def prepare_first_goal_request(inputs,profile,seed,diagnostic):
    model_diagnostic=model_rebuild_diagnostics(diagnostic)
    write(FIRST_DIAGNOSTICS,model_diagnostic,True)
    if read(FIRST_DIAGNOSTICS)!=model_diagnostic:raise ValueError("first full native revision diagnostics changed")
    bound=revision_planning_inputs(inputs,seed,model_diagnostic)
    bound["goal_revision_feedback_evidence_path"]=str(FIRST_DIAGNOSTICS.resolve())
    prepared=workflow.prepare_goal_request(bound,profile)
    payload=json.loads(prepared["request"]["messages"][1]["content"])
    supplied=payload["revision_diagnostics"]
    if (payload.get("previous_complete_document")!=seed or payload.get("reference_fulltext")!=inputs["reference_fulltext"]
            or supplied["complete_native_previous_source_report"]!=model_diagnostic["complete_native_previous_source_report"]
            or supplied["fixed_legal_and_causal_review"]!=model_diagnostic["fixed_legal_and_causal_review"]
            or prepared["request"].get("stage")!="goal_plan" or prepared["request"].get("role")!="writer"):
        raise ValueError("first MM native plan29 must preserve full616/617, R01 and exact bound QA")
    return prepared


def is_strict_source(request):
    return (request.get("role")=="director" and request.get("stage")=="goal_audit"
        and request.get("structured_schema",{}).get("properties",{}).get("schema",{}).get("const")
            =="creative_goal_legal_usage_source_audit/v5")


def prepare_source_audit(inputs,profile,goal):
    policy=profile.get("source_strict",{})
    if (policy.get("enabled") is not True or policy.get("base_url")!="https://api.deepseek.com/beta"
            or policy.get("function_strict") is not True or policy.get("other_deepseek_stages_strict") is not False
            or policy.get("role")!="director" or policy.get("stage")!="goal_audit"
            or policy.get("schema_version")!="creative_goal_legal_usage_source_audit/v5"
            or policy.get("max_completion_tokens")!=24000
            or type(policy.get("max_wire_utf8_bytes")) is not int
            or not 0 < policy["max_wire_utf8_bytes"] <= 600000
            or policy.get("sdk_max_retries")!=0 or policy.get("http_follow_redirects") is not False):
        raise ValueError("exact source-only strict policy required")
    prepared=workflow.prepare_goal_source_audit_request(inputs,profile,goal)
    request=prepared["request"]
    binding=strict_clients.protocol_binding(request,review_base_url=policy["base_url"])
    prepared["source_schema_compilation_manifest"]=strict_clients.schema_compilation_manifest(request)
    request["input_provenance"]["source_protocol_binding"]=binding
    prepared["manifest"]["source_protocol_binding"]=deepcopy(binding)
    request["input_provenance"]["context_manifest_sha256"]=digest(prepared["manifest"])
    prepared["request_sha256"]=digest(request)
    prepared["wire"]=strict_clients.expected_wire_request(request,source_strict=True)
    raw=json.dumps(prepared["wire"],ensure_ascii=False,separators=(",",":")).encode("utf8")
    maximum=policy.get("max_wire_utf8_bytes")
    if type(maximum) is not int or len(raw)>maximum:raise ValueError("actual strict wire exceeds explicit new wire budget")
    prepared["strict_wire_measurement"]={"utf8_bytes":len(raw),"wire_sha256":digest(prepared["wire"]),
        "original_contract_utf8_bytes":len(json.dumps(request["structured_schema"],ensure_ascii=False,separators=(",",":")).encode("utf8")),
        "service_schema_utf8_bytes":len(json.dumps(prepared["wire"]["tools"][0]["function"]["parameters"],ensure_ascii=False,separators=(",",":")).encode("utf8")),
        "max_wire_utf8_bytes":maximum,"logical_payload_budget_does_not_certify_full_wire":True}
    return prepared


def invoke(runtime, label, prepared, validator):
    request = prepared["request"]
    strict_clients.expected_wire_request(request,source_strict=is_strict_source(request))
    # Cached native response is read-only, before any SQLite service attempt.
    # It is never charged or claimed twice under a new label.
    for row in read(runtime.ledger)["calls"]:
        original_receipt = runtime.effective_receipt(row)
        if original_receipt["request_sha256"] == digest(request):
            return runtime.dispatch(label, request, validator)
    write(ROOT / "requests" / (label + ".json"), prepared, True)
    store = tasks.TaskStore(ROOT / "TASKS.sqlite3")
    gid = "call_" + digest({"grant": GRANT, "label": label})[:24]
    store.register_graph({"schema_version": tasks.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
        {"node_id": "source", "kind": "source", "input": {"source_manifest": digest(read(runtime.ledger)["source_manifest"]),
         "request_sha256": digest(request)}, "depends_on": []},
        {"node_id": "result", "kind": "text", "input": {"label": label, "stage": request["stage"]}, "depends_on": ["source"]}]})
    scope_path = ROOT / "USER_SCOPE.json"
    auth = {"schema_version": tasks.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid,
        "node_ids": ["result"], "scope": "text", "purpose": "dispatch",
        "source_sha256": store.snapshot(gid)["source_sha256"],
        "max_attempts": read(scope_path)["stage_limits"][request["stage"]], "prior_attempts": 0,
        "allows_content_revision": False, "evidence_ref": str(scope_path) + "#" + request["stage"],
        "evidence_sha256": sha_file(scope_path)}
    attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, auth)
    receipt = runtime.dispatch(label, request, validator)
    evidence = original.verify_receipt_evidence(runtime, receipt, request)
    outbound = evidence / "request_body.raw"
    if outbound.exists() and control.strict_json(outbound.read_text(encoding="utf-8")) != strict_clients.expected_wire_request(request,source_strict=is_strict_source(request)):
        raise ValueError("actual request differs from verified exact mapping")
    raw_path = evidence / "response_body.raw"
    raw = raw_path.read_bytes() if raw_path.exists() else b""
    known, outcome, tool_status = original.classify_receipt(receipt)
    meta = receipt.get("response_metadata", {})
    total, http = meta.get("total_tokens"), meta.get("http_status_code")
    store.accept_result(attempt["claim_id"], {"schema_version": tasks.RESULT_SCHEMA,
        "claim_id": attempt["claim_id"], "request_sha256": attempt["request_sha256"], "service_task_id": None,
        "outcome": outcome, "result_known": known, "usage_known": type(total) is int and total >= 0,
        "usage": {"unit": "reported_tokens", "amount": total} if type(total) is int and total >= 0 else None,
        "complete": meta.get("response_body_complete") is True, "complete_end": meta.get("finish_reason") in ("stop", "tool_calls"),
        "schema_tool_status": tool_status, "contract_valid": receipt["status"] == "contract_valid" if known else None,
        "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest(), "http_status": http if type(http) is int else None},
        "output": {"ordinal": receipt["ordinal"], "native_output": receipt.get("output")}})
    return receipt


def repairable(receipt):
    meta = receipt.get("response_metadata", {})
    return (original.classify_receipt(receipt)[0] and meta.get("output_mode") == "tool_call"
        and meta.get("requested_model") == receipt["request"]["model"]
        and meta.get("response_model") == receipt["request"]["model"]
        and isinstance(receipt.get("output"), dict) and bool(receipt["output"]))


def diagnosis(receipt):
    return {key: deepcopy(receipt[key]) for key in ("failure", "validation_error", "validation") if key in receipt}


def script_source_inputs(inputs):
    """A goal revision is not a previous screenplay for the author to repair."""
    return {key: deepcopy(value) for key, value in inputs.items()
        if key not in ("previous_complete_document", "revision_diagnostics",
                       "revision_requirements", "complete_script_feasibility_diagnostics",
                       "fresh_reconception_context", "goal_revision_feedback_evidence_path")}


def revision_planning_inputs(inputs, seed, diagnostic):
    """Only this new run's known complete native version is a revision template."""
    return {**script_source_inputs(inputs), "previous_complete_document": deepcopy(seed),
        "revision_diagnostics": deepcopy(diagnostic)}


def persist_goal_revision_feedback(inputs, index):
    """Save complete original feedback before any lossless compiler projection."""
    if type(index) is not int or index not in (1, 2):
        raise ValueError("only two complete native goal revision identities are permitted")
    if (type(inputs.get("previous_complete_document")) is not dict
            or type(inputs.get("revision_diagnostics")) is not dict
            or not inputs["revision_diagnostics"]):
        raise ValueError("complete native current goal and original diagnostics required")
    path = ROOT / "goals" / f"revision_diagnostics_{index:02}.json"
    write(path, inputs["revision_diagnostics"], True)
    if read(path) != inputs["revision_diagnostics"]:
        raise ValueError("saved complete original revision diagnostics changed")
    return {**deepcopy(inputs), "goal_revision_feedback_evidence_path": str(path.resolve())}


def fresh_planning_inputs(inputs, diagnostic):
    return {**script_source_inputs(inputs), "fresh_reconception_context":deepcopy(diagnostic)}


def validate_opening_setup(value, goal):
    """Known complete setup gaps require native revision, never local placement."""
    native = workflow.validate_opening_setup_document(value, goal)
    return {"valid": True, "native_setup_sha256": digest(native),
        "native_goal_sha256": digest(goal), "state_fields_inferred": False,
        "semantic_quality_approved": False}


def state(runtime, status, **extra):
    result = {"schema": VERSION + "/state", "status": status, "updated_at": now(),
        "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False,
        "media_authorized": False, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "spend": runtime.summary(), **extra}
    result["inherited_goal_candidates_used"] = 28
    labels = [row.get("label", "") for row in read(runtime.ledger)["calls"]]
    # Setup writer calls consume the same stage, but are not new whole-film candidates.
    result["cumulative_goal_candidates_used"] = 28 + sum(label.startswith("goal_plan_") for label in labels)
    result["opening_setup_calls"] = sum(label.startswith("opening_setup_") for label in labels)
    result["parent_whole_plan_unused_capacity"] = 1
    result["parent_unused_capacity_stays_in_closed_run"] = True
    write(ROOT / "STATE.json", result)
    return result


def run():
    runtime = get_runtime()
    runtime.inherited_guard()
    if (ROOT / "RUN_CLAIM.json").exists():
        raise FileExistsError("existing run claim; inspect without provider restart")
    write(ROOT / "RUN_CLAIM.json", {"schema": VERSION + "/claim", "started_at": now(),
        "pid": os.getpid(), "automatic_restart": False}, True)
    # A completed run claim is not a new authorization. No cached-stage replay run.
    if read(ROOT / "RUN_CLAIM.json")["pid"] != os.getpid() or read(runtime.ledger)["calls"]:
        raise RuntimeError("run already claimed; inspect original receipts")
    inputs, profile = read(ROOT / "INPUTS.json"), read(PROFILE)
    ids = workflow.origin_ids(inputs)
    goal = read(ROOT / "INHERITED_NATIVE_GOAL.json")
    seed=deepcopy(goal)
    audit=None;goal_ordinal=None
    initial_diagnostic=build_revision_diagnostics(seed)
    goal_inputs=revision_planning_inputs(inputs,seed,model_rebuild_diagnostics(initial_diagnostic))
    write(ROOT/"goals/inherited_native616.json",seed,True)
    for index in range(1,2):
        planned=(prepare_first_goal_request(inputs,profile,seed,initial_diagnostic) if index==1
            else workflow.prepare_goal_request(persist_goal_revision_feedback(goal_inputs,index),profile))
        if index==1 and planned!=read(ROOT/"FIRST_NATIVE_PLAN_REQUEST_PREVIEW.json"):
            raise ValueError("actual first native plan request differs from immutable preview")
        receipt=invoke(runtime,f"goal_plan_{index+28:02}",planned,lambda value:workflow.validate_goal_document(value,inputs=inputs))
        if receipt.get("cached_response_read_only"):return state(runtime,"halt_no_new_native_goal_progress",receipt_ordinal=receipt["ordinal"])
        if not repairable(receipt):return state(runtime,"halt_goal_interface_or_unknown",receipt_ordinal=receipt["ordinal"])
        goal=receipt["output"];goal_ordinal=receipt["ordinal"];write(ROOT/"goals"/f"native_{index:02}.json",goal,True)
        if receipt["status"]!="contract_valid":
            goal_inputs=revision_planning_inputs(inputs,goal,diagnosis(receipt));continue
        if digest(goal)==digest(seed):
            return state(runtime,"halt_unchanged_native_goal_requires_pipeline_diagnosis",receipt_ordinal=receipt["ordinal"])
        bundle,decisions={},[]
        for kind in ("source","commitment","drama"):
            if runtime.summary()["stage_calls"]["goal_audit"]>=3:
                return state(runtime,"halt_goal_audit_capacity_exhausted",audit_kind=kind,remaining_goal_audits=0)
            prepared=(prepare_source_audit(inputs,profile,goal) if kind=="source"
                else getattr(workflow,f"prepare_goal_{kind}_audit_request")(inputs,profile,goal))
            args={"context_sha256":prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]}
            if kind=="source":args["authority_context"]=deepcopy(prepared["source_authority_context"])
            validate=getattr(workflow,f"validate_goal_{kind}_audit")
            receipt=invoke(runtime,f"goal_{kind}_audit_{index:02}",prepared,lambda value,v=validate,a=args:v(value,goal,**a))
            if receipt.get("cached_response_read_only"):return state(runtime,"halt_cached_goal_audit_no_new_claim",receipt_ordinal=receipt["ordinal"])
            if not repairable(receipt):return state(runtime,"halt_goal_audit_interface_or_unknown",receipt_ordinal=receipt["ordinal"],audit_kind=kind)
            if receipt["status"]!="contract_valid":return state(runtime,"halt_goal_audit_contract_requires_pipeline_diagnosis",receipt_ordinal=receipt["ordinal"],audit_kind=kind)
            verdict=receipt["validation"];write(ROOT/"goals"/f"{kind}_audit_decision_{index:02}.json",verdict,True);write(ROOT/"goals"/f"{kind}_native_audit_{index:02}.json",receipt["output"],True)
            decisions.append(verdict);bundle[f"native_{kind}_audit"]=receipt["output"]
            if not verdict["accepted"] or verdict["uncertainties"]:break
        if len(bundle)==3 and all(d["accepted"] and not d["uncertainties"] for d in decisions):
            audit=workflow.build_goal_audit_bundle(bundle["native_source_audit"],bundle["native_drama_audit"],bundle["native_commitment_audit"]);break
        goal_inputs=revision_planning_inputs(inputs,goal,{"complete_same_source_goal_audits":decisions,
            "complete_native_same_source_goal_audit_reports":deepcopy(bundle)})
    if audit is None:return state(runtime,"halt_goal_content_capacity_exhausted")
    opening_setup = None
    setup_inputs = deepcopy(script_source_inputs(inputs))
    for index in range(1, 3):
        prepared_setup = workflow.prepare_opening_setup_request(setup_inputs, profile, goal)
        setup_receipt = invoke(runtime, f"opening_setup_{index:02}", prepared_setup,
            lambda value: validate_opening_setup(value, goal))
        if setup_receipt.get("cached_response_read_only"):
            return state(runtime, "halt_no_new_opening_setup_progress", receipt_ordinal=setup_receipt["ordinal"])
        if not repairable(setup_receipt):
            return state(runtime, "halt_opening_setup_interface_or_unknown", receipt_ordinal=setup_receipt["ordinal"])
        native_setup = setup_receipt["output"]
        write(ROOT / "setups" / f"native_{index:02}.json", native_setup, True)
        if setup_receipt["status"] == "contract_valid":
            opening_setup = native_setup
            break
        setup_inputs = {**deepcopy(script_source_inputs(inputs)), "previous_opening_setup": native_setup,
            "opening_setup_diagnostics": diagnosis(setup_receipt)}
    if opening_setup is None:
        return state(runtime, "halt_opening_setup_content_capacity_exhausted")
    base_script_inputs = script_source_inputs(inputs)
    script_inputs = deepcopy(base_script_inputs)
    for index in range(1, 4):
        prepared = workflow.prepare_script_request(script_inputs, profile, goal, audit,
            opening_setup=opening_setup, **ids)
        views = prepared["views"]
        def script_validator(value):
            result = workflow.validate_script_document(value, views, inputs["production_preferences"])
            if not result["necessary_conditions_only"]:
                exc = ValueError("necessary timing conditions failed; complete native revision required")
                exc.detail = result["diagnostic"]
                raise exc
            return result
        receipt = invoke(runtime, f"complete_script_{index:02}", prepared, script_validator)
        if receipt.get("cached_response_read_only"):
            return state(runtime, "halt_no_new_native_script_progress", receipt_ordinal=receipt["ordinal"])
        if not repairable(receipt):
            return state(runtime, "halt_script_interface_or_unknown", receipt_ordinal=receipt["ordinal"])
        native = receipt["output"]
        folder = ROOT / "scripts" / f"version_{index:02}"
        write(folder / "NATIVE_SCRIPT.json", native, True)
        try:
            compiled = legacy.contract.compile_script(native, views["brief"])
            with (folder / "FULL_SCRIPT.md").open("x", encoding="utf-8") as handle:
                handle.write("完整模型原生正文，验收结论见本目录DECISION及本轮STATE；未获用户采用。\n\n" + legacy.render_script(compiled, views["brief"]))
        except (ValueError, KeyError, TypeError):
            compiled = None
        if receipt["status"] != "contract_valid":
            script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
                "revision_diagnostics": diagnosis(receipt)}
            continue
        part_documents, part_decisions, part_contexts, part_ordinals = {}, {}, {}, {}
        failed_part_decision = None
        review_legal_context = None
        for part in ("semantic", "physical"):
            prepared_review = workflow.prepare_full_review_part_request(inputs, profile, native, views, part)
            context_sha = prepared_review["part_context_sha256"]
            if review_legal_context is not None and review_legal_context != prepared_review["review_legal_context"]:
                raise ValueError("split review parts must bind the exact same legal context")
            review_legal_context = prepared_review["review_legal_context"]
            reviewed = invoke(runtime, f"full_review_{part}_{index:02}", prepared_review,
                lambda v: reviews.validate_part(v, part, compiled, views["brief"], views["plan"],
                    review_legal_context, context_sha256=context_sha,
                    goal_contract=goal, opening_setup=opening_setup))
            if reviewed.get("cached_response_read_only"):
                return state(runtime, "halt_cached_full_review_no_new_claim", review_part=part,
                    receipt_ordinal=reviewed["ordinal"])
            if not repairable(reviewed):
                return state(runtime, "halt_review_interface_or_unknown", review_part=part,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
            if reviewed["status"] != "contract_valid":
                return state(runtime, "halt_full_review_contract_requires_pipeline_diagnosis", review_part=part,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
            part_decision = reviewed["validation"]
            write(folder / f"NATIVE_{part.upper()}_REVIEW.json", reviewed["output"], True)
            write(folder / f"{part.upper()}_DECISION.json", part_decision, True)
            if part_decision.get("status") in (
                    "halt_same_story_prior_allowance_exhausted", "halt_prior_story_relation_unknown"):
                return state(runtime, part_decision["status"], review_part=part, decision=part_decision,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"],
                    prior_story_guard_preserved=True, new_body_revision_dispatched=False)
            if part_decision.get("uncertainties"):
                return state(runtime, "halt_full_review_uncertain", review_part=part, decision=part_decision,
                    script_path=str(folder / "FULL_SCRIPT.md"), receipt_ordinal=reviewed["ordinal"])
            if (part_decision.get("requires_new_goal_plan")
                    or any(item.get("target") == "plan" for item in part_decision.get("findings", []))):
                return state(runtime, "halt_full_review_requires_new_complete_goal", review_part=part,
                    decision=part_decision, script_path=str(folder / "FULL_SCRIPT.md"),
                    receipt_ordinal=reviewed["ordinal"], upstream_goal_revision_required=True)
            part_documents[part] = reviewed["output"]
            part_decisions[part] = part_decision
            part_contexts[part] = context_sha
            part_ordinals[part] = reviewed["ordinal"]
            if not part_decision["accepted"]:
                failed_part_decision = part_decision
                break
        if failed_part_decision is not None:
            script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
                "revision_diagnostics": {"complete_same_source_part_review": failed_part_decision,
                    "native_part_reviews": part_documents, "native_review_ordinals": part_ordinals}}
            continue
        bundle = reviews.build_review_bundle(part_documents["semantic"], part_documents["physical"])
        decision = reviews.validate_bundle(bundle, compiled, views["brief"], views["plan"], review_legal_context,
            semantic_context_sha256=part_contexts["semantic"], physical_context_sha256=part_contexts["physical"],
            goal_contract=goal, opening_setup=opening_setup)
        write(folder / "NATIVE_REVIEW_BUNDLE.json", bundle, True)
        write(folder / "DECISION.json", decision, True)
        if decision.get("valid") is not True:
            return state(runtime, "halt_full_review_bundle_contract_requires_pipeline_diagnosis",
                decision=decision, review_ordinals=part_ordinals, script_path=str(folder / "FULL_SCRIPT.md"))
        if decision.get("status") in (
                "halt_same_story_prior_allowance_exhausted", "halt_prior_story_relation_unknown"):
            return state(runtime, decision["status"], decision=decision, review_ordinals=part_ordinals,
                script_path=str(folder / "FULL_SCRIPT.md"), prior_story_guard_preserved=True,
                new_body_revision_dispatched=False)
        if decision["uncertainties"]:
            return state(runtime, "halt_full_review_uncertain", decision=decision, script_path=str(folder / "FULL_SCRIPT.md"))
        if (decision.get("requires_new_goal_plan")
                or any(finding.get("target") == "plan" for finding in decision["findings"])):
            return state(runtime, "halt_full_review_requires_new_complete_goal", decision=decision,
                script_path=str(folder / "FULL_SCRIPT.md"), review_ordinals=part_ordinals,
                upstream_goal_revision_required=True, native_script_locally_patched=False)
        if decision["accepted"]:
            write(ROOT / "TEXT_HANDOFF.json", {"schema": VERSION + "/text_handoff", "native_goal": goal,
                "native_opening_setup": opening_setup,
                "native_goal_audit": audit, "native_script": native, "views": views,
                "native_full_review_bundle": bundle, "decision": decision,
                "script_path": str(folder / "FULL_SCRIPT.md"), "script_ordinal": receipt["ordinal"],
                "review_ordinals": part_ordinals, "production_dispatch_eligible": False,
                "next_stage_requires_reconciled_director_lineage": True, "media_authorized": False}, True)
            return state(runtime, "text_ready_for_director", text_ready_for_director=True,
                script_path=str(folder / "FULL_SCRIPT.md"), native_goal_ordinal=goal_ordinal,
                script_ordinal=receipt["ordinal"], review_ordinals=part_ordinals, decision=decision)
        script_inputs = {**deepcopy(base_script_inputs), "previous_complete_document": native,
            "revision_diagnostics": {"complete_same_source_full_review_bundle": decision,
                "native_review_bundle": bundle, "native_review_ordinals": part_ordinals}}
    return state(runtime, "halt_script_content_capacity_exhausted")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "status"))
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare()
    elif args.command == "status":
        result = read(ROOT / "STATE.json")
    else:
        try:
            result = run()
        except Exception as exc:
            write(ROOT / "EXECUTION_ERROR.json", {"status": "stopped_original_request_requires_reconciliation",
                "error_type": type(exc).__name__, "error": str(exc), "new_request_dispatched_by_recovery": False}, True)
            raise
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
