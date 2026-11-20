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
from scripts import run_m31_flash_script_test_v1 as parent
from scripts import run_fresh_legal_full_flow_v1 as original
from scripts import preview_goal_context_workflow_v3 as preview
from scripts import run_goal_context_text_production_v17 as previous
from src.content_factory import creative_goal_context_workflow_v17 as workflow
from src.content_factory import creative_goal_drama_audit_contract_v11 as drama_contract
from src.content_factory import creative_goal_source_contract_v4 as goals
from src.content_factory import creative_opening_setup_contract_v3 as setups
from src.content_factory import creative_split_full_review_contract_v4 as reviews
from src.content_factory import creative_full_review_contract_v5 as complete_reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks

VERSION = "goal_context_text_production/v18"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_17"
GRANT = "legal_usage_compact_review_20261014"
PREFLIGHT_PARENT = previous.ROOT
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
APPROVAL = CLAIM.parent / "USER_CONTINUATION.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v3.json"
PLAN = PROJECT / "docs/CREATIVE_LEGAL_USAGE_AND_COMPACT_REVIEW_PLAN_20261014.md"
PARENT_STATE = PREFLIGHT_PARENT / "STATE.json"
CONTENT_DIAGNOSIS = PROJECT / "data/qa/creative_legal_usage_20261014/ROUND16_LEGAL_USAGE_AND_TRUNCATION_DIAGNOSIS_v2.json"
CERTIFICATE = ROOT / "CERTIFIED_PARENT_LINEAGE.json"
USER_DIRECTION_CONFIRMATION = PROJECT / "data/qa/creative_legal_usage_20261014/USER_STORY_DIRECTION_CONFIRMATION_v2.json"
INPUT_SUPPLEMENT_AUTHORIZATION = APPROVAL.parent / "AUTHORIZE_INPUT_SUPPLEMENT_v1.json"
SUPPLEMENTED_INPUTS = PROJECT / "data/qa/creative_legal_usage_20261014/INPUTS_DIRECTION_SUPPLEMENT_v1.json"
SUPPLEMENTED_PREVIEW = PROJECT / "data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v2.json"
USER_DIRECTION_QUOTE = "继续超市老员工方向，强化情绪交锋"
USER_DIRECTION_QUESTION = "这轮故事已转为超市老员工被劝退：经理也有调任压力，员工坚持公司提出离职要写清，结尾保留她明天的班。下一份新稿默认继续这个方向，并加强双方当场的情绪交锋；这个取舍符合你的预期吗？这是方向核对，不是要求采用当前未复审草稿。"
read, write, digest, sha_file, now = control.read, control.write, control.digest, control.sha_file, control.now


def known_truncated_review(receipt):
    """Known original length failure is consumed evidence, never a valid review."""
    meta = receipt.get("response_metadata", {})
    payload = receipt.get("response_payload", {})
    choice = payload.get("choices", [{}])[0] if payload.get("choices") else {}
    usage = payload.get("usage", {})
    return (receipt.get("status") == "interface_rejected"
        and receipt.get("request", {}).get("stage") == "full_review"
        and meta.get("http_status_code") == 200 and meta.get("response_body_complete") is True
        and meta.get("finish_reason") == choice.get("finish_reason") == "length"
        and meta.get("response_fault_code") == "RESPONSE_TRUNCATED"
        and meta.get("output_mode") == "unusable_response"
        and meta.get("requested_model") == meta.get("response_model") == receipt["request"].get("model")
        and type(meta.get("total_tokens")) is int and meta["total_tokens"] >= 0
        and all(type(usage.get(key)) is int and usage[key] >= 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
        and usage["total_tokens"] == meta["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        and receipt.get("validation") is None and receipt.get("output") is None)


def prior_guard():
    prior_runtime = previous.get_runtime()
    prior_runtime.inherited_guard()
    summary = prior_runtime.summary()
    ledger = read(prior_runtime.ledger)
    if [row["ordinal"] for row in ledger["calls"]] != list(range(591, 602)):
        raise ValueError("parent must contain exact closed calls591 through601")
    statuses = {ordinal: "contract_rejected" if ordinal == 599 else "interface_rejected" if ordinal == 601 else "contract_valid"
        for ordinal in range(591, 602)}
    for row in ledger["calls"]:
        path = PREFLIGHT_PARENT / row["receipt"]
        receipt = read(path)
        if sha_file(path) != row["receipt_sha256"] or receipt.get("status") != statuses[row["ordinal"]]:
            raise ValueError("parent original response changed; never redispatch")
        original.verify_receipt_evidence(prior_runtime, receipt, receipt["request"])
        if row["ordinal"] == 601:
            if not known_truncated_review(receipt):
                raise ValueError("original601 must be an evidenced known-usage length rejection, never accepted review")
        elif not repairable(receipt):
            raise ValueError("parent591 through600 must remain complete known native responses")
    terminal = read(PARENT_STATE)
    if (terminal.get("status") != "halt_review_interface_or_unknown"
            or terminal.get("receipt_ordinal") != 601 or terminal.get("review_part") != "semantic"
            or terminal.get("text_ready_for_director") is not False
            or terminal.get("spend") != summary or terminal.get("cumulative_goal_candidates_used") != 24
            or terminal.get("opening_setup_calls") != 1
            or summary["stage_calls"] != {"goal_plan": 3, "goal_audit": 5, "complete_script": 2, "full_review": 1}
            or (summary["effective_calls_started"], summary["effective_reported_tokens"],
                summary["effective_calls_with_known_usage"]) != (601, 12004575, 599)
            or summary.get("new_unknown_token_reservations") != 0
            or summary.get("historical_pending_ordinals") != [70, 160]
            or summary.get("unknown_token_reservations") != 93117):
        raise ValueError("exact terminal601 and known stage/spend/candidate consumption required")
    scope = read(PREFLIGHT_PARENT / "USER_SCOPE.json")
    if (scope.get("inherited_goal_candidates_used") != 22 or scope.get("local_goal_candidates_limit") != 2
            or scope.get("cumulative_goal_candidates_this_run_maximum") != 24
            or summary["stage_limits"] != scope["stage_limits"]
            or summary["stage_limits"] != {"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6}):
        raise ValueError("parent maximum24/used24 must remain unchanged in the closed run")
    for ordinal in (595, 596, 597):
        row = next(r for r in ledger["calls"] if r["ordinal"] == ordinal)
        verdict = read(PREFLIGHT_PARENT / row["receipt"]).get("validation", {})
        if verdict.get("accepted") is not True or verdict.get("valid") is not True or verdict.get("uncertainties"):
            raise ValueError("original reported planning passes must remain unchanged, not legal/creative acceptance")
    return summary


def models(profile):
    return {role: {key: profile[role][key] for key in ("provider", "model", "base_url")}
            for role in ("writer", "director")}


def verify_seed_native(seed):
    matches = [row for row in read(PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 594]
    if len(matches) != 1:
        raise ValueError("unique complete native594 receipt required")
    row = matches[0]
    path = PREFLIGHT_PARENT / row["receipt"]
    if sha_file(path) != row["receipt_sha256"]:
        raise ValueError("native594 receipt changed")
    receipt = read(path)
    if (not repairable(receipt) or receipt.get("output") != seed
            or receipt["request"]["stage"] != "goal_plan" or receipt.get("status") != "contract_valid"
            or read(PREFLIGHT_PARENT / "goals/native_02.json") != seed):
        raise ValueError("seed must be exact complete known native594; old source passes are not legal acceptance")
    return {"ordinal": 594, "receipt_path": str(path), "receipt_sha256": row["receipt_sha256"],
        "native_sha256": digest(seed), "contract_valid": True, "semantic_approved": False,
        "used_only_for_complete_model_revision": True, "sent_as_first_request_template": True}


def get_runtime():
    from scripts.creative_goal_context_dispatch_v7 import GoalContextRuntime
    from scripts import creative_flat_lineage_guard_v2 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v2 as verifier
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
        shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock")


def authorization_request_identity(diagnostic, prepared):
    """Pin local recovery and dispatch preparation to one actual text request."""
    return {
        "source_inputs_sha256": sha_file(PREFLIGHT_PARENT / "INPUTS.json"),
        "model_profile_sha256": sha_file(PROFILE),
        "derived_revision_diagnostics_sha256": digest(diagnostic),
        "actual_prepared_preview_sha256": digest(prepared),
    }


def build_direction_supplemented_inputs(inputs, confirmation):
    """Append current human goals; preserve every original source/goal value."""
    if (confirmation.get("schema") != "user_story_direction_confirmation/v2"
            or confirmation.get("user_quote") != USER_DIRECTION_QUOTE
            or confirmation.get("confirms_story_direction") is not True
            or confirmation.get("adopts_current_unreviewed_script") is not False
            or confirmation.get("media_or_publish_authorized") is not False
            or confirmation.get("changes_frozen_old_inputs") is not False
            or confirmation.get("applies_to_new_unfrozen_run") is not True
            or confirmation.get("question_context") != USER_DIRECTION_QUESTION):
        raise ValueError("exact current human direction confirmation required; not manuscript adoption")
    output = deepcopy(inputs)
    contract = output["user_goal_contract"]
    existing = {row["id"] for table in ("constraints", "audience_goals") for row in contract[table]}
    new_ids = {"UC_CONFIRMED_SUPERMARKET_DIRECTION", "UG_INTENSIFIED_EMOTIONAL_EXCHANGE"}
    if existing & new_ids:
        raise ValueError("direction goal IDs already present; do not duplicate or replace original goals")
    contract["constraints"].append({"id":"UC_CONFIRMED_SUPERMARKET_DIRECTION",
        "text":"用户已确认“继续超市老员工方向，强化情绪交锋”。延续超市老员工被劝退、经理也有调任压力、员工坚持公司提出离职要写清、结尾保留她明天的班的故事方向；这不是采用当前未复审正文。",
        "source_quote":confirmation["user_quote"]})
    contract["audience_goals"].append({"id":"UG_INTENSIFIED_EMOTIONAL_EXCHANGE",
        "text":"强化双方当场相互影响的情绪交锋：人物的目的、感受和对手回应互相推动，具体刺激引起反应与策略变化，压力和让步有现实代价，结尾的可见变化从此前交锋产生。保持人物自己的自然立场，不锁对白、句数或动作。",
        "source_quote":confirmation["user_quote"]})
    return output


def input_supplement_identity(inputs, prepared):
    return {"original_authorization_sha256":sha_file(APPROVAL),
        "human_direction_confirmation_sha256":sha_file(USER_DIRECTION_CONFIRMATION),
        "parent_inputs_sha256":sha_file(PREFLIGHT_PARENT/"INPUTS.json"),
        "supplemented_inputs_sha256":digest(inputs),
        "actual_prepared_preview_sha256":digest(prepared)}


def verify_input_supplement(parent_inputs, seed, diagnostic):
    """Validate supplement before any new production artifact or claim write."""
    expected_inputs = build_direction_supplemented_inputs(parent_inputs,read(USER_DIRECTION_CONFIRMATION))
    prepared = workflow.prepare_goal_request(revision_planning_inputs(expected_inputs,seed,diagnostic),read(PROFILE))
    binding = read(INPUT_SUPPLEMENT_AUTHORIZATION)
    saved_preview = read(SUPPLEMENTED_PREVIEW)
    if (binding.get("schema") != VERSION+"/user_direction_input_supplement"
            or binding.get("original_preview_sha256") != sha_file(PROJECT/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json")
            or binding.get("parent_root") != str(PREFLIGHT_PARENT)
            or binding.get("parent_ledger_sha256") != sha_file(PREFLIGHT_PARENT/"CALL_LEDGER.json")
            or binding.get("model_profile_sha256") != sha_file(PROFILE)
            or binding.get("derived_revision_diagnostics_sha256") != digest(diagnostic)
            or binding.get("appended_user_ids") != ["UC_CONFIRMED_SUPERMARKET_DIRECTION","UG_INTENSIFIED_EMOTIONAL_EXCHANGE"]
            or binding.get("append_only_user_rows") is not True
            or binding.get("original_law_collection_reference_and_user_rows_unchanged") is not True
            or binding.get("confirmation_is_direction_not_manuscript_adoption") is not True
            or binding.get("confirmation_user_quote") != USER_DIRECTION_QUOTE
            or binding.get("existing_text_authority_only") is not True
            or binding.get("automatic_transport_retry") is not False
            or binding.get("seed_native_identity") != verify_seed_native(seed)
            or binding.get("old_ledger_reset") is not False
            or binding.get("media_authorized") is not False or binding.get("publish_authorized") is not False
            or any(binding.get(key)!=value for key,value in input_supplement_identity(expected_inputs,prepared).items())
            or read(SUPPLEMENTED_INPUTS) != expected_inputs
            or saved_preview.get("prepared") != prepared
            or saved_preview.get("input_supplement_binding") != binding
            or type(saved_preview.get("provider_calls")) is not int or saved_preview.get("provider_calls") != 0
            or type(saved_preview.get("media_calls")) is not int or saved_preview.get("media_calls") != 0
            or saved_preview.get("creative_quality_approved") is not False
            or saved_preview.get("old_preview_preserved") is not True):
        raise ValueError("direction supplement identity, append-only inputs or actual request changed; no claim")
    return expected_inputs,prepared,binding


def prepare():
    if ROOT.exists() or CLAIM.exists():
        raise RuntimeError("existing global grant/root; inspect original, never regrant")
    from scripts import creative_flat_lineage_guard_v2 as lineage
    from src.content_factory import creative_flat_lineage_verifier_v2 as verifier
    expected = read(PARENT_STATE)["spend"]
    certificate = lineage.build_lineage_certificate(PROJECT, PREFLIGHT_PARENT,
        certified_check=prior_guard, expected_summary=expected,
        dependency_paths=[PARENT_STATE],
        guard_code_paths=[Path(__file__), Path(lineage.__file__), Path(verifier.__file__)])
    consumed = expected
    approval = read(APPROVAL)
    if (approval.get("human_authorized") is not True or approval.get("user_quote") != "minimax随便追加"
            or approval.get("parent_ledger_sha256") != sha_file(PREFLIGHT_PARENT / "CALL_LEDGER.json")
            or approval.get("parent_goal_candidates_used") != 24
            or approval.get("authority_source_sha256") != sha_file(previous.APPROVAL)):
        raise ValueError("explicit continuing user authorization and unchanged spent lineage required")
    inputs = read(PREFLIGHT_PARENT / "INPUTS.json")
    seed_row = [row for row in read(PREFLIGHT_PARENT / "CALL_LEDGER.json")["calls"] if row["ordinal"] == 594][0]
    seed = read(PREFLIGHT_PARENT / seed_row["receipt"])["output"]
    seed_identity = verify_seed_native(seed)
    diagnostic = build_revision_diagnostics(seed)
    source_check = parent.source_gate()
    first_request = workflow.prepare_goal_request(revision_planning_inputs(inputs, seed, diagnostic), read(PROFILE))
    if any(approval.get(key) != value for key, value in authorization_request_identity(diagnostic, first_request).items()):
        raise ValueError("continuing authorization inputs, profile, diagnosis or actual request changed")
    preview_path = PROJECT / "data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json"
    if read(preview_path).get("prepared") != first_request:
        raise ValueError("actual authorization preview changed; no new run claim created")
    inputs,first_request,input_supplement = verify_input_supplement(inputs,seed,diagnostic)
    inherited = {"calls_started": consumed["effective_calls_started"],
        "reported_tokens": consumed["effective_reported_tokens"],
        "calls_with_known_usage": consumed["effective_calls_with_known_usage"],
        "unknown_token_reservations": consumed["unknown_token_reservations"],
        "pending_ordinals": consumed["historical_pending_ordinals"]}
    scope = {"schema": VERSION + "/user_scope", "grant_id": GRANT,
        "user_quote": approval["user_quote"], "writer_total_call_user_limit": None,
        "stage_limits": {"goal_plan": 4, "goal_audit": 6, "complete_script": 3, "full_review": 6},
        "stage_limits_are_local_run_safety_bounds": True,
        "inherited_goal_candidates_used": 24, "local_goal_candidates_limit": 2,
        "local_opening_setup_limit": 2, "cumulative_goal_candidates_this_run_maximum": 26,
        "seed_goal_ordinal": 594, "seed_goal_semantic_approved": False,
        "seed_used_only_for_complete_model_revision": True, "first_request_is_fresh_reconception": False,
        "parent_whole_plan_maximum": 24, "parent_whole_plans_used": 24,
        "parent_whole_plan_unused_capacity": 0, "parent_unused_capacity_stays_in_closed_run": True,
        "new_local_bound_from_existing_authority": 2,
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
        "parent_ledger_sha256": scope["parent_ledger_sha256"], "inherited_goal_candidates_used": 24,
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
    write(ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json", first_request, True)
    # Freeze every old production dependency plus all new independent modules.
    paths = set(read(PREFLIGHT_PARENT / "PRODUCTION_FREEZE.json")["files"])
    paths.update(str(p.resolve()) for p in (Path(__file__), PROFILE, PLAN, CONTENT_DIAGNOSIS,
        PARENT_STATE, PROJECT / "src/content_factory/creative_goal_revision_feedback_v1.py",
        Path(workflow.__file__), PROJECT / "src/content_factory/creative_goal_evidence_view_v1.py", PROJECT / "src/content_factory/creative_goal_legal_usage_source_audit_v1.py", PROJECT / "src/content_factory/creative_goal_commitment_audit_v2.py", Path(drama_contract.__file__), Path(goals.__file__), Path(reviews.__file__), Path(complete_reviews.__file__), Path(setups.__file__),
        PROJECT / "src/content_factory/creative_stage_context_v3.py", APPROVAL, CERTIFICATE,
        USER_DIRECTION_CONFIRMATION,INPUT_SUPPLEMENT_AUTHORIZATION,SUPPLEMENTED_INPUTS,SUPPLEMENTED_PREVIEW,
        PROJECT/"data/qa/creative_legal_usage_20261014/LEGAL_USAGE_REQUEST_PREVIEW_v1.json",
        PROJECT / "src/content_factory/creative_goal_audit_citation_contract_v1.py",
        PROJECT / "scripts/record_legal_usage_continuation_v1.py",
        PROJECT / "scripts/record_legal_usage_diagnosis_v1.py",
        PROJECT / "scripts/record_legal_usage_direction_supplement_v1.py",
        PROJECT / "scripts/creative_goal_context_dispatch_v7.py", Path(lineage.__file__), Path(verifier.__file__), Path(clients.__file__),
        PREFLIGHT_PARENT / "RUN_CLAIM.json", PREFLIGHT_PARENT / "CALL_LEDGER.json",
        ROOT / "USER_SCOPE.json", ROOT / "INPUTS.json", ROOT / "INHERITED_NATIVE_GOAL.json",
        ROOT / "ORIGINAL_PARENT_INPUTS.json",ROOT / "USER_DIRECTION_INPUT_SUPPLEMENT.json",
        ROOT / "INHERITED_DIAGNOSTICS.json", ROOT / "SOURCE_GATE.json",
        ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json"))
    paths.update(read(CONTENT_DIAGNOSIS)["source_file_sha256"])
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


def build_revision_diagnostics(seed):
    """Bind qualified law/source observations and length evidence without adopting old reviews."""
    from scripts import record_legal_usage_diagnosis_v1 as recorder
    verify_seed_native(seed)
    verified = read(CONTENT_DIAGNOSIS)
    expected = recorder.build_diagnosis()
    if verified != expected:
        raise ValueError("exact original594/595/596 legal-usage and601 length diagnosis changed")
    for path, expected_sha in verified["source_file_sha256"].items():
        if sha_file(path) != expected_sha:
            raise ValueError("original legal/truncation diagnosis witness changed")
    failure, truncation = verified["verified_failures"]
    chain = failure["prior_literal_delivery_feedback_chain"]
    focused_fields = ("literal_requirement", "status", "reason", "required_revision")
    # Native/provenance proofs stay frozen locally; the planner receives only
    # the exact content fault and the observed feedback chain, not 30 paths or
    # compiler-expanded audit evidence. Nothing in this projection is a new
    # semantic judgment or a replacement for the complete revision source.
    model_diagnosis = {
        "schema": VERSION + "/content_owned_diagnosis_projection",
        "complete_local_diagnosis_sha256": digest(verified),
        "complete_local_source_manifest_sha256": digest(verified["source_file_sha256"]),
        "full_original_diagnosis_and_receipts_retained_locally": True,
        "verified_failures": [{
            "kind": failure["kind"], "exact_claims": deepcopy(failure["exact_claims"]),
            "beat_evidence": deepcopy(failure["beat_evidence"]),
            "native_source_595_cc6_judgment": deepcopy(failure["native_source_cc6_judgment"]),
            "native_source_595_vl2_judgment": deepcopy(failure["native_source_vl2_judgment"]),
            "native_focused_596_cc6_judgment": {key:deepcopy(failure["native_focused_cc6_judgment"][key])
                for key in focused_fields},
            "prior_feedback_chain": {
                "original_claim_591": deepcopy(chain["original_claim_591"]),
                "native_source_592_cc6_judgment": deepcopy(chain["native_source_592_cc6_judgment"]),
                "native_focused_593_cc6_judgment": {key:deepcopy(chain["native_focused_593_cc6_judgment"][key])
                    for key in focused_fields},
                "original_593_required_revision_entered_actual_594_request": True,
                "former_required_revision_is_fault_evidence_not_current_instruction": True},
            "diagnosis": failure["diagnosis"]}, {
            "kind": truncation["kind"],
            "known_output_tokens": truncation["response_metadata"]["completion_tokens"],
            "argument_prefix_characters": truncation["argument_prefix_characters"],
            "argument_prefix_key_occurrences": deepcopy(truncation["argument_prefix_key_occurrences"]),
            "native_review_not_converted": True, "diagnosis": truncation["diagnosis"]}],
        "creative_risks": deepcopy(verified["creative_risks"]),
        "stage_ownership_direction": deepcopy(verified["stage_ownership_direction"]),
        "diagnosis_is_human_reading_not_automated_semantic_proof": True}
    return {"schema": VERSION + "/qualified_revision_diagnostics",
        "native_goal_ordinal": 594, "native_goal_sha256": digest(seed),
        "verified_pipeline_diagnosis": model_diagnosis,
        "workflow_change": "Submit one complete native revision of original594. Fix actual legal meaning across all claim kinds, beats and ending; creative_choice or character dialogue cannot exempt article/rights assertions. Preserve original legal conditions, user goals and platform/R01 authority. A character may express a deliberately disputed misconception only with actual current narrative framing/correction; do not turn the film into legal exposition. Resolve the article38 portrayal against verified VL2/L002 instead of locally deleting one line. Source owns legal coverage, focused owns literal creative commitments, drama owns functional causal payoff and registered scope. New compact semantic/physical reviews preserve all responsibilities and exact evidence while reducing duplicated output. Original601 is a known-usage truncated rejection, not a review to continue or adopt. Entire new goal, setup and body remain model-native with same-source audits; no hand patched screenplay.",
        "previous_complete_script_sent_to_planner": False, "old_complete_documents_retained": True,
        "native_text_locally_patched": False}


def invoke(runtime, label, prepared, validator):
    request = prepared["request"]
    clients.expected_wire_request(request)
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
    if outbound.exists() and control.strict_json(outbound.read_text(encoding="utf-8")) != clients.expected_wire_request(request):
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
                       "fresh_reconception_context")}


def revision_planning_inputs(inputs, seed, diagnostic):
    """Only this new run's known complete native version is a revision template."""
    return {**script_source_inputs(inputs), "previous_complete_document": deepcopy(seed),
        "revision_diagnostics": deepcopy(diagnostic)}


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
    result["inherited_goal_candidates_used"] = 24
    labels = [row.get("label", "") for row in read(runtime.ledger)["calls"]]
    # Setup writer calls consume the same stage, but are not new whole-film candidates.
    result["cumulative_goal_candidates_used"] = 24 + sum(label.startswith("goal_plan_") for label in labels)
    result["opening_setup_calls"] = sum(label.startswith("opening_setup_") for label in labels)
    result["parent_whole_plan_unused_capacity"] = 0
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
    goal_inputs = revision_planning_inputs(inputs, goal, read(ROOT / "INHERITED_DIAGNOSTICS.json"))
    audit = None
    goal_ordinal = None
    for index in range(1, 3):
        planned = workflow.prepare_goal_request(goal_inputs, profile)
        if index == 1 and (ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json").exists():
            if planned != read(ROOT / "FIRST_GOAL_REQUEST_PREVIEW.json"):
                raise ValueError("first actual goal request differs from frozen exact preview")
        def goal_validator(value):
            return workflow._validate_planning_input(inputs, value)
        receipt = invoke(runtime, f"goal_plan_{index+24:02}", planned,
            goal_validator)
        if receipt.get("cached_response_read_only"):
            return state(runtime, "halt_no_new_native_goal_progress", receipt_ordinal=receipt["ordinal"])
        state(runtime, "goal_received", goal_ordinal=receipt["ordinal"], goal_status=receipt["status"])
        if not repairable(receipt):
            return state(runtime, "halt_goal_interface_or_unknown", receipt_ordinal=receipt["ordinal"])
        goal = receipt["output"]
        goal_ordinal = receipt["ordinal"]
        write(ROOT / "goals" / f"native_{index:02}.json", goal, True)
        if receipt["status"] != "contract_valid":
            goal_inputs = revision_planning_inputs(inputs, goal, diagnosis(receipt))
            continue
        bundle, decisions = {}, []
        for kind in ("source", "commitment", "drama"):
            prepare_audit = getattr(workflow, f"prepare_goal_{kind}_audit_request")
            validate_audit = getattr(workflow, f"validate_goal_{kind}_audit")
            prepared = prepare_audit(inputs, profile, goal)
            context_sha = prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
            validate_args = {"context_sha256": context_sha}
            if kind == "source":
                validate_args["authority_context"] = deepcopy(prepared["source_authority_context"])
            audited = invoke(runtime, f"goal_{kind}_audit_{index:02}", prepared,
                lambda value, validate=validate_audit, args=validate_args: validate(value, goal, **args))
            if audited.get("cached_response_read_only"):
                return state(runtime, "halt_cached_goal_audit_no_new_claim", receipt_ordinal=audited["ordinal"])
            if not repairable(audited):
                return state(runtime, "halt_goal_audit_interface_or_unknown", receipt_ordinal=audited["ordinal"], audit_kind=kind)
            if audited["status"] != "contract_valid":
                return state(runtime, "halt_goal_audit_contract_requires_pipeline_diagnosis", receipt_ordinal=audited["ordinal"], audit_kind=kind)
            verdict = audited["validation"]
            write(ROOT / "goals" / f"{kind}_audit_decision_{index:02}.json", verdict, True)
            write(ROOT / "goals" / f"{kind}_native_audit_{index:02}.json", audited["output"], True)
            if verdict["uncertainties"]:
                return state(runtime, "halt_goal_audit_uncertain", goal_decision=verdict, audit_kind=kind)
            decisions.append(verdict)
            bundle[f"native_{kind}_audit"] = audited["output"]
            if not verdict["accepted"]:
                break
        if len(bundle) == 3 and all(decision["accepted"] for decision in decisions):
            audit = workflow.build_goal_audit_bundle(bundle["native_source_audit"], bundle["native_drama_audit"], bundle["native_commitment_audit"])
            break
        goal_inputs = revision_planning_inputs(inputs, goal, {"complete_same_source_goal_audits": decisions})
    if audit is None:
        return state(runtime, "halt_goal_content_capacity_exhausted")
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
