"""Independent bounded endpoint production adapter; no media dispatch entry.

Preparation freezes this new code and inherits all 512--517 source/candidate/
spend history. The caller authorizes this one bounded run, never a reset. Tests
inject fake lineage/runtime only inside fresh temporary roots.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import run_creative_shared_full_production_v1 as old
from scripts import run_creative_shared_full_production_v3 as original_intake
from scripts import run_creative_shared_full_production_v4 as parent
from scripts import creative_capability_role_clients_v2 as clients
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from src.content_factory import creative_complete_production_coordinator_v4 as coordinator
from src.content_factory import creative_production_revision_loop_v3 as loop
from src.content_factory import creative_provider_preflight_v1 as capability
from src.content_factory import creative_reference_compiler_v4 as references

ROOT = PROJECT / "data/production_revisions/shared_full_production_20261012/capability_v5"
VERSION = "creative_capability_production/v5"
USER_QUOTE = "这些审核你可以直接进行，人物你可以主动接取，这些都是正常的重构修复流程的你可以自动运行的"
GRANT_ID = "creative_capability_production_20261012_autonomous_three_directors"
ADDITIONAL_DIRECTORS = 3


def grant_for(state):
    return {"authority": "explicit_user", "grant_id": GRANT_ID, "user_quote": USER_QUOTE,
        "additional_candidates": ADDITIONAL_DIRECTORS, "source_binding_sha256": state["source_binding_sha256"],
        "context": "本轮自主重构接线及有界文本生产测试；继承原四次而最多新增三份完整导演，不授权媒体。",
        "automatic_retry": False, "old_budget_reset": False}


def verified_lineage():
    """Read real immutable parents; no new grant, preparation or dispatch."""
    x, script, manifest, initial, _, proof = original_intake.verified_parent()
    rt = parent.runtime()
    ledger = old.control.read(rt.ledger)
    rt.check(ledger)
    state = parent.verify_loop_history(rt)
    inherited, receipts = old.prior.inherited_known_parent(ledger, parent.ROOT)
    if [row["ordinal"] for row in receipts] != [517]:
        raise ValueError("exact 517 parent continuation lineage required")
    if inherited["calls_started"] != 517 or inherited["reported_tokens"] != 7886808:
        raise ValueError("inherited actual spend changed; reconcile before freezing")
    material = {"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial}
    capacity = loop.candidate_capacity(state)
    if (state["stable_scope_material"] != material or capacity["candidate_limit"] != 4
        or capacity["attempts_including_claims"] != 4 or capacity["remaining"] != 0
        or capacity["unresolved_claims"] or capacity["unresolved_result_ids"]):
        raise ValueError("parent original four complete candidates or source scope changed")
    proof = deepcopy(proof)
    proof["production_context_sha256"] = coordinator.production_context_digest(x["brief"],
        x["reference_fulltext"], x["production_preferences"])
    proof["production_context_binding_kind"] = "verified_frozen_input_identity_only"
    proof["preferences_semantically_reviewed_by_513"] = False
    paths = [parent.ROOT / name for name in ("CALL_LEDGER.json", "AUTHORIZATION.json", "ANCHOR.json",
        "INPUT.json", "USER_SCOPE.json", "INHERITED_DIRECTOR_STATE.json", "INITIAL_LOOP_STATE.json",
        "LOOP_STATE.json", "EXTRA_CANDIDATE_GRANT.json", "PRODUCTION_RESULT.json")]
    paths += [parent.ROOT / row["receipt"] for row in ledger["calls"]]
    paths += [path for path in (parent.ROOT / "call_evidence").rglob("*") if path.is_file()]
    original_ledger = old.control.read(old.ROOT / "CALL_LEDGER.json")
    paths += [old.ROOT / name for name in ("CALL_LEDGER.json", "AUTHORIZATION.json", "ANCHOR.json", "INPUT.json",
        "ADOPTED_SOURCE.json", "SHARED_MANIFEST.json", "PLANNED_INITIAL_STATE.json", "USER_SCOPE.json")]
    paths += [old.ROOT / row["receipt"] for row in original_ledger["calls"]]
    paths += [path for path in (old.ROOT / "call_evidence").rglob("*") if path.is_file()]
    intake_root = PROJECT / "data/qa/creative_capability_production_adapter_20261012/asset_intake/r2"
    paths += [intake_root / name for name in ("ASSET_INVENTORY.json", "SOURCE_CANDIDATES.json", "INTAKE_OFFLINE_EVIDENCE.json")]
    return {"original_input": x, "script": script, "manifest": manifest, "initial": initial,
        "source_review_binding": proof, "parent_state": state, "inherited": inherited,
        "models": deepcopy(ledger["model_configs"]),
        "parent_files": {str(path): old.control.sha_file(path) for path in paths}}


def _reference_bundle(path):
    if path is None:
        return None, {}
    path = Path(path).resolve()
    bundle = old.control.read(path)
    if (not isinstance(bundle, dict) or not isinstance(bundle.get("binding_contract"), dict)
        or not isinstance(bundle.get("selected_asset_ids"), list) or not bundle["selected_asset_ids"]):
        raise ValueError("reference intake needs an explicit v4 binding contract and selected independent asset IDs")
    files = {str(path): old.control.sha_file(path)}
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("local_path", "path") and isinstance(child, str):
                    candidate = Path(child).resolve()
                    if candidate.is_file(): files[str(candidate)] = old.control.sha_file(candidate)
                else: visit(child)
        elif isinstance(value, list):
            for row in value: visit(row)
    visit(bundle)
    return {"original_path": str(path), "original_sha256": old.control.sha_file(path), "bundle": bundle}, files


def _enricher(reference_intake):
    if reference_intake is None:
        return None
    bundle = reference_intake["bundle"]
    def enrich(request):
        visual = references.build_director_visual_messages(request["messages"], bundle["binding_contract"],
            bundle["selected_asset_ids"], now=old.control.now(),
            expected_account_binding_sha256=bundle.get("expected_account_binding_sha256"),
            provider_get_evidence=bundle.get("provider_get_evidence"),
            required_entities=bundle.get("required_entities"))
        actual = deepcopy(request)
        actual["messages"] = visual["messages"]
        return {"request": actual, "proof": visual["coverage"]}
    return enrich


def runtime():
    anchor = old.control.read(ROOT / "ANCHOR.json")
    def guard():
        old.prior.verify_files(anchor["parent_files"])
        # These original runtimes validate their own immutable operator/source
        # snapshots. No default pipeline, ledger or global is replaced.
        parent.runtime().check(old.control.read(parent.ROOT / "CALL_LEDGER.json"))
        old.runtime().check(old.control.read(old.ROOT / "CALL_LEDGER.json"))
    def unbound_client():
        raise RuntimeError("stage-bound capability client must be set before dispatch")
    return old.control.ContinuationRuntime(PROJECT, ROOT,
        [PROJECT / path for path in anchor["runtime_sources"]], anchor["inherited"], anchor["models"],
        inherited_guard=guard, client_factory=unbound_client, quota_state=None)


def prepare(reference_intake_path=None):
    if not (ROOT / "ANCHOR.json").exists():
        lineage = verified_lineage()
        parent_state = deepcopy(lineage["parent_state"])
        grant = grant_for(parent_state)
        state = loop.authorize_extra_candidate(parent_state, grant)
        cap = loop.candidate_capacity(state)
        if cap["candidate_limit"] != 7 or cap["remaining"] != 3:
            raise ValueError("new three-candidate grant must retain original four attempts")
        selected, reference_files = _reference_bundle(reference_intake_path)
        inp = {key: deepcopy(lineage[key]) for key in
            ("original_input", "script", "manifest", "initial", "source_review_binding")}
        inp["reference_intake"] = selected
        # Verify original source identity and capability before freezing. This
        # produces no SDK client and no service request.
        x = inp["original_input"]
        direction_input = pipeline.build_director_input(inp["script"], inp["manifest"], inp["initial"],
            x["reference_fulltext"], x["production_preferences"])
        direction_input.update(brief=deepcopy(x["brief"]), production_context_binding={
            "production_context_sha256": inp["source_review_binding"]["production_context_sha256"],
            "binding_kind": "external_frozen_input_identity", "prior_semantic_review_claim": False})
        request = pipeline.build_request("whole_direction", direction_input,
            pipeline.whole_direction_schema(inp["script"], inp["manifest"]), lineage["models"]["writer"]["model"])
        if selected is not None:
            request = _enricher(selected)(request)["request"]
        report = capability.preflight_text_request(request)
        if report["status"] != "capability_preflight_passed" or report["blocked"] is not False:
            raise ValueError("production input capability preflight is incomplete")
        scope = {"schema": VERSION + "/scope", "user_statement": USER_QUOTE,
            "additional_director_candidates": 3, "original_director_candidates_consumed": 4,
            "reused_native_script_ordinal": 512, "reused_full_review_ordinal": 513,
            "script_sha256": pipeline.digest(inp["script"]), "max_new_video_submissions": 0,
            "media_dispatch_in_this_entry": False, "batch_authorized": False,
            "automatic_retry": False, "publishing_authorized": False, "budget_reset": False,
            "trial_scope": "approved_visual_material_text_trial" if selected else "text_contract_trial_only",
            "complete_visual_materials_claimed": False, "voice_binding": "unbound"}
        for name, value in (("INPUT.json", inp), ("USER_SCOPE.json", scope),
            ("PARENT_LOOP_STATE.snapshot.json", parent_state), ("INHERITED_DIRECTOR_STATE.json", state),
            ("EXTRA_CANDIDATE_GRANT.json", grant)):
            old.control.write(ROOT / name, value, True)
        claim_path = PROJECT / "data/creative_continuation_stages" / old.control.digest({
            "grant_id": GRANT_ID, "original_binding": state["source_binding_sha256"]}) / "CLAIM.json"
        old.control.write(claim_path, {"grant_id": GRANT_ID, "root": str(ROOT), "additional_candidates": 3,
            "parent_state_sha256": old.control.digest(parent_state), "user_quote": USER_QUOTE,
            "budget_reset": False}, True)
        parent_files = {**lineage["parent_files"], **reference_files, str(claim_path): old.control.sha_file(claim_path)}
        paths = [path for folder in (PROJECT / "src", PROJECT / "scripts") for path in folder.rglob("*.py")]
        if capability.REGISTRY_PATH.is_file() and capability.REGISTRY_PATH.is_relative_to(PROJECT):
            paths.append(capability.REGISTRY_PATH)
        paths += [ROOT / name for name in ("INPUT.json", "USER_SCOPE.json", "ANCHOR.json",
            "PARENT_LOOP_STATE.snapshot.json", "INHERITED_DIRECTOR_STATE.json", "EXTRA_CANDIDATE_GRANT.json")]
        old.control.write(ROOT / "ANCHOR.json", {"inherited": lineage["inherited"], "models": lineage["models"],
            "parent_files": parent_files, "runtime_sources": [path.relative_to(PROJECT).as_posix() for path in paths],
            "text_contract_trial_only": selected is None}, True)
    elif reference_intake_path is not None:
        frozen = old.control.read(ROOT / "INPUT.json")["reference_intake"]
        if frozen is None or Path(reference_intake_path).resolve() != Path(frozen["original_path"]):
            raise ValueError("reference selection cannot change after preparation")
    rt = runtime()
    rt.prepare()
    inherited = old.control.read(ROOT / "INHERITED_DIRECTOR_STATE.json")
    bound = loop.register_successor_binding(inherited, old.control.digest(old.control.read(rt.ledger)["source_manifest"]),
        inherited["stable_scope_material"], old.control.digest(inherited))
    old.control.write(ROOT / "INITIAL_LOOP_STATE.json", bound, True)
    if not (ROOT / "LOOP_STATE.json").exists(): old.control.write(ROOT / "LOOP_STATE.json", bound, True)
    verify_loop_history(rt)
    return status()


def verify_loop_history(rt):
    rt.check(old.control.read(rt.ledger))
    parent_state = old.control.read(ROOT / "PARENT_LOOP_STATE.snapshot.json")
    granted = loop.authorize_extra_candidate(parent_state, grant_for(parent_state))
    if old.control.read(ROOT / "EXTRA_CANDIDATE_GRANT.json") != grant_for(parent_state):
        raise ValueError("new grant evidence changed")
    if old.control.read(ROOT / "INHERITED_DIRECTOR_STATE.json") != granted:
        raise ValueError("inherited four candidates or new bounded grant changed")
    ledger = old.control.read(rt.ledger)
    expected = loop.register_successor_binding(granted, old.control.digest(ledger["source_manifest"]),
        granted["stable_scope_material"], old.control.digest(granted))
    baseline = old.control.read(ROOT / "INITIAL_LOOP_STATE.json")
    if baseline != expected: raise ValueError("derived successor baseline changed")
    state = old.control.read(ROOT / "LOOP_STATE.json")
    for key in ("schema", "source_binding_sha256", "stable_scope_material", "stable_scope_sha256",
        "successor_source_bindings", "original_candidate_limit", "additional_candidate_grants", "budget_reset",
        "history_preserved", "automatic_transport_retry"):
        if state.get(key) != expected.get(key): raise ValueError("inherited loop scope or allowance changed: " + key)
    prefix = expected["director_events"]
    if state["director_events"][:len(prefix)] != prefix: raise ValueError("original four director events changed")
    suffix = state["director_events"][len(prefix):]
    claims = [row for row in suffix if row.get("event") == "claim"]
    results = [row for row in suffix if row.get("event") == "result"]
    if len(claims) > 3 or len(results) > 3 or len(suffix) != len(claims) + len(results):
        raise ValueError("bounded new three-director history exceeded or malformed")
    if len({row["request_identity"] for row in claims}) != len(claims): raise ValueError("duplicate director claims")
    directors = [row for row in ledger["calls"] if row["label"].startswith("whole_direction_v4_")]
    if len(directors) > 3: raise ValueError("bounded new director ledger exceeded")
    for row in directors:
        receipt = rt.effective_receipt(row)
        if not any(claim["request_identity"] == receipt["request_sha256"] for claim in claims):
            raise ValueError("director call lacks exact durable claim")
    for event in results:
        match = next((row for row in directors if str(row["ordinal"]) == event["result"]["result_id"]), None)
        if match is None: raise ValueError("director result lacks original ledger receipt")
        receipt = rt.effective_receipt(match)
        stage_request = old.control.read(ROOT / "stage_requests" / (match["label"] + ".json"))
        if event["result"] != loop.normalize_receipt(receipt, stage_request):
            raise ValueError("director progress differs from immutable receipt or original request")
        if event["request_identity"] != old.control.digest(stage_request):
            raise ValueError("director result changed its durable request")
    old_journal = expected.get("stage_dispatch_events", [])
    journal = state.get("stage_dispatch_events", [])
    if journal[:len(old_journal)] != old_journal: raise ValueError("original stage dispatch history changed")
    pending, resolved = {}, set()
    for event in journal[len(old_journal):]:
        identity = event.get("dispatch_identity")
        if event.get("event") == "claim":
            if identity in pending: raise ValueError("duplicate stage dispatch claim")
            if event.get("preflight", {}).get("request_sha256") != event.get("request_sha256"):
                raise ValueError("stage claim differs from capability preflight identity")
            pending[identity] = event
        elif event.get("event") == "result":
            claim = pending.get(identity)
            if claim is None or identity in resolved: raise ValueError("stage result lacks unique durable claim")
            row = next((row for row in ledger["calls"] if str(row["ordinal"]) == event["evidence"]["result_id"]), None)
            if row is None: raise ValueError("stage result has no immutable ledger receipt")
            receipt = rt.effective_receipt(row)
            request = old.control.read(ROOT / "stage_requests" / (row["label"] + ".json"))
            if (claim["request_sha256"] != old.control.digest(request)
                or event["receipt_sha256"] != old.control.digest(receipt)
                or event["evidence"] != loop.normalize_receipt(receipt, request)):
                raise ValueError("stage result/request evidence changed")
            resolved.add(identity)
        elif event.get("event") == "dispatch_exception":
            if identity not in pending or identity in resolved: raise ValueError("dispatch exception lacks unresolved claim")
            resolved.add(identity)
        else: raise ValueError("unknown stage history event")
    return state


def summary_result(result, rt):
    anchor = old.control.read(ROOT / "ANCHOR.json")
    scope = old.control.read(ROOT / "USER_SCOPE.json")
    return {"schema": VERSION, "status": result["status"], "reason": result.get("reason"), **rt.summary(),
        "director_capacity": loop.candidate_capacity(result["loop_state"]),
        "historical_unknown_token_reservations": anchor["inherited"]["unknown_token_reservations"],
        "historical_unknown_calls": anchor["inherited"]["pending_ordinals"],
        "complete_text_handoff_ready": result["complete_text_handoff_ready"],
        "complete_visual_material_handoff_ready": False, "trial_scope": scope["trial_scope"],
        "actual_media_quality_passed": False, "human_creative_quality_passed": False, "new_video_calls": 0,
        "result_path": str(ROOT / "PRODUCTION_RESULT.json"), "report_path": str(ROOT / "PRODUCTION_REPORT.md")}


def status():
    if not (ROOT / "ANCHOR.json").exists(): return {"schema": VERSION, "status": "not_prepared", "new_calls": 0, "new_video_calls": 0}
    rt = runtime()
    state = verify_loop_history(rt)
    if (ROOT / "PRODUCTION_RESULT.json").exists():
        result = old.control.read(ROOT / "PRODUCTION_RESULT.json")
        if result.get("loop_state") != state: raise ValueError("saved production result differs from current durable state")
        output_manifest = ROOT / "OUTPUT_MANIFEST.json"
        if not output_manifest.exists():
            return {**rt.summary(), "schema": VERSION, "status": "saved_result_artifacts_incomplete_reconcile_original",
                "complete_text_handoff_ready": False, "new_request_redispatch_allowed": False, "new_video_calls": 0}
        old.prior.verify_files(old.control.read(output_manifest)["files"])
        if actual_request_proofs(rt, old.control.read(ROOT / "INPUT.json")) != old.control.read(ROOT / "ACTUAL_REQUEST_PROOF.json"):
            raise ValueError("actual outgoing capability/body evidence changed after saved result")
        return summary_result(result, rt)
    anchor = old.control.read(ROOT / "ANCHOR.json")
    return {"schema": VERSION, "status": "prepared_not_dispatched", **rt.summary(),
        "director_capacity": loop.candidate_capacity(state), "coordinator_status": state.get("coordinator_status"),
        "historical_unknown_token_reservations": anchor["inherited"]["unknown_token_reservations"],
        "historical_unknown_calls": anchor["inherited"]["pending_ordinals"], "new_video_calls": 0,
        "text_contract_trial_only": anchor["text_contract_trial_only"]}


def preview():
    if not (ROOT / "ANCHOR.json").exists(): return status()
    rt = runtime()
    state = verify_loop_history(rt)
    inp = old.control.read(ROOT / "INPUT.json")
    x = inp["original_input"]
    failures = [event["result"] for event in state["director_events"]
        if event.get("result", {}).get("known_complete") and event["result"].get("status") == "contract_rejected"]
    diagnostics = [pipeline.known_failure_diagnostic(failures[-1], inp["script"])] if failures else []
    terminal = state.get("coordinator_terminal")
    if terminal and terminal.get("reason") == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED" and loop.candidate_capacity(state)["remaining"]:
        stop_summary, resumed_feedback = coordinator.CompleteProductionCoordinator._terminal_prompt_context(terminal, state)
        diagnostics = [stop_summary, resumed_feedback] if resumed_feedback is not None else [stop_summary, *diagnostics]
    inputs = pipeline.build_director_input(inp["script"], inp["manifest"], inp["initial"],
        x["reference_fulltext"], x["production_preferences"], diagnostics)
    inputs.update(brief=deepcopy(x["brief"]), production_context_binding={
        "production_context_sha256": inp["source_review_binding"]["production_context_sha256"],
        "binding_kind": "external_frozen_input_identity", "prior_semantic_review_claim": False})
    request = pipeline.build_request("whole_direction", inputs, pipeline.whole_direction_schema(inp["script"], inp["manifest"]), rt.models["writer"]["model"])
    enricher = _enricher(inp["reference_intake"])
    visual = enricher(request) if enricher is not None else {"request": request, "proof": {"status": "no_selected_visual_material"}}
    preflight = capability.preflight_text_request(visual["request"])
    preview_row = {"request": visual["request"], "capability_preflight": preflight, "visual_coverage": visual["proof"],
        "director_capacity": loop.candidate_capacity(state), "dispatched": False, "new_paid_calls": 0}
    old.control.write(ROOT / "previews" / (old.control.digest(preview_row) + ".json"), preview_row, True)
    return {**status(), "preview_path": str(ROOT / "previews" / (old.control.digest(preview_row) + ".json")),
        "request_sha256": old.control.digest(visual["request"]), "capability_status": preflight["status"],
        "images_in_request": len(visual["proof"].get("ordered_images", []))}


def actual_request_proofs(rt, inp):
    reference = inp["original_input"]["reference_fulltext"]
    rows = []
    for call in old.control.read(rt.ledger)["calls"]:
        receipt = rt.effective_receipt(call)
        original_request = old.control.read(ROOT / "stage_requests" / (call["label"] + ".json"))
        logical_input = loop.normalize_receipt(receipt, original_request)["actual_input"]
        journal = rt.evidence_path(call["ordinal"])
        capture_path, raw_path = journal / "REQUEST_BODY_MANIFEST.json", journal / "request_body.raw"
        capture = old.control.read(capture_path) if capture_path.exists() else None
        capture_valid = bool(capture and capture.get("body_complete") is True and capture.get("raw_bytes_preserved") is True
            and capture.get("identity_sha256") == receipt.get("call_evidence", {}).get("identity_sha256")
            and raw_path.exists() and old.control.sha_file(raw_path) == capture.get("stored_sha256") == capture.get("original_sha256"))
        try: actual = json.loads(raw_path.read_bytes()) if capture_valid else None
        except (ValueError, UnicodeDecodeError): actual, capture_valid = None, False
        if not isinstance(actual, dict): actual, capture_valid = None, False
        contents = [message.get("content") for message in (actual or {}).get("messages", []) if message.get("role") == "user"]
        serialized_inputs = []
        for value in contents:
            texts = [value] if isinstance(value, str) else [part.get("text") for part in value
                if isinstance(part, dict) and part.get("type") == "text"] if isinstance(value, list) else []
            for text in texts:
                if not isinstance(text, str): continue
                try: parsed = json.loads(text)
                except ValueError: continue
                if isinstance(parsed, dict): serialized_inputs.append(parsed)
        raw_images = [part for value in contents if isinstance(value, list) for part in value if part.get("type") == "image_url"]
        logical_images = [part for message in original_request["messages"] if isinstance(message.get("content"), list)
            for part in message["content"] if part.get("type") == "image_url"]
        capability_path = journal / "CAPABILITY_PREFLIGHT.json"
        cap = old.control.read(capability_path) if capability_path.exists() else None
        try: expected_wire = clients.expected_wire_request(original_request)
        except Exception: expected_wire = None
        capability_valid = bool(capture_valid and isinstance(cap, dict)
            and cap.get("schema") == clients.VERSION + "/outbound_capability_proof"
            and cap.get("status") == "capability_preflight_passed" and cap.get("dispatch_before_verify") is False
            and cap.get("identity_sha256") == receipt.get("call_evidence", {}).get("identity_sha256")
            and cap.get("logical_request_sha256") == old.control.digest(original_request)
            and cap.get("actual_request_body_sha256") == cap.get("original_body_sha256") == capture["original_sha256"]
            and cap.get("full_wire_equals_mapped_logical_request") is True
            and actual == expected_wire
            and cap.get("expected_wire_sha256") == cap.get("actual_wire_sha256") == old.control.digest(actual)
            and cap.get("messages_sha256") == old.control.digest(original_request["messages"])
            and cap.get("structured_schema_sha256") == old.control.digest(original_request.get("structured_schema"))
            and cap.get("SDK_max_retries") == 0 and cap.get("HTTP_follow_redirects") is False
            and all(isinstance(cap.get(key), dict) and cap[key].get("status") == "capability_preflight_passed"
                and cap[key].get("blocked") is False for key in ("logical_capability_report", "wire_capability_report")))
        rows.append({"ordinal": call["ordinal"], "stage": original_request["stage"],
            "logical_reference_equal": bool(logical_input and logical_input.get("reference_fulltext") == reference),
            "actual_serialized_reference_equal": any(value.get("reference_fulltext") == reference for value in serialized_inputs),
            "actual_request_body_binding_verified": capture_valid,
            "actual_messages_equal_to_frozen_logical_request": bool(actual and actual.get("messages") == original_request["messages"]),
            "actual_image_payloads_equal": bool(actual is not None and raw_images == logical_images),
            "image_count": len(raw_images), "request_body_sha256": capture.get("stored_sha256") if capture else None,
            "logical_request_sha256": old.control.digest(original_request),
            "capability_preflight_path": str(capability_path), "capability_preflight_report_present": cap is not None,
            "actual_capability_preflight_binding_verified": capability_valid,
            "capability_preflight_report_sha256": old.control.sha_file(capability_path) if cap is not None else None,
            "reference_sha256": old.control.digest(reference), "provider_received_request": None,
            "actual_media_quality_passed": False})
    return rows


def save_artifacts(result, rt, inp):
    old.control.write(ROOT / "COORDINATOR_RESULT.json", result, True)
    proofs = actual_request_proofs(rt, inp)
    if result["complete_text_handoff_ready"] and (not proofs or not all(row["actual_capability_preflight_binding_verified"]
        and row["actual_request_body_binding_verified"] and row["logical_reference_equal"]
        and row["actual_serialized_reference_equal"] and row["actual_messages_equal_to_frozen_logical_request"]
        and row["actual_image_payloads_equal"] for row in proofs)):
        result = {**deepcopy(result), "status": "needs_attention", "reason": "ACTUAL_REQUEST_PROOF_INVALID",
            "complete_text_handoff_ready": False, "media_dispatch_allowed": False,
            "original_coordinator_result_sha256": old.control.digest(result)}
    old.control.write(ROOT / "PRODUCTION_RESULT.json", result, True)
    old.control.write(ROOT / "ACTUAL_REQUEST_PROOF.json", proofs, True)
    summary = summary_result(result, rt)
    lines = ["# 能力优先流程真实文本测试", "", "沿用512《" + inp["script"]["title"] + "》与513同源全文审查。",
        "状态：" + result["status"] + "；原因：" + str(result.get("reason")),
        "原四份导演、累计517次/7886808 reported tokens及70/160未知完整承接；本轮最多新增三份导演。",
        "本入口只执行文本；视频0，不自动重试、不发布。未选定合格实际人物图时仅为文本合同试验。", ""]
    for call in old.control.read(rt.ledger)["calls"]:
        receipt = rt.effective_receipt(call)
        meta = receipt.get("response_metadata", {})
        lines.append(f"- {receipt['ordinal']} / {receipt['label']} / {receipt['status']} / reported_tokens={meta.get('total_tokens')} / finish={meta.get('finish_reason')}")
        if receipt.get("validation_error"): lines.append("  合同：" + str(receipt["validation_error"].get("message")))
        if receipt.get("failure"): lines.append("  故障：" + str(receipt["failure"].get("code")))
    lines += ["", "接口成功、完整文本合同通过、素材可用与用户创作/视频批准分别记录。声线仍unbound。",
        "历史未知预留93117不因本轮当前未知为0而结清。", "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```"]
    (ROOT / "PRODUCTION_REPORT.md").write_text("\n".join(lines), encoding="utf8")
    if not result["complete_text_handoff_ready"]:
        _save_output_manifest()
        return result
    out = ROOT / "DELIVERABLE"
    for name, value in (("FULL_SCRIPT.json", inp["script"]), ("NATIVE_ENDPOINT_DIRECTION.json", result["whole_direction_native"]),
        ("WHOLE_DIRECTION.json", result["direction"]), ("ALL_LOCAL_PERFORMANCES.json", result["performances"]),
        ("COMPLETE_PRODUCTION_COMPILED.json", result["complete_compilation"]),
        ("OPENING_REQUEST_PREVIEW.json", result["opening_actual_preview"]),
        ("REVIEWED_REQUEST_PROOF.json", result["reviewed_request_identity_proof"]),
        ("DIRECTOR_VISUAL_REQUEST_PROOF.json", result["director_visual_request_proof"])):
        old.control.write(out / name, value, True)
    (out / "FULL_SCRIPT.md").write_text(old.source_text(inp["script"]), encoding="utf8")
    handoff = [old.source_text(inp["script"]), "## 原生导演、逐段表演和交接", "机器全文制作复审通过；未证明人物/声音或视频质量。"]
    for performance, prompt in zip(result["performances"], result["planned_prompts"]):
        handoff += ["### " + performance["segment_id"], "```json\n" + json.dumps(performance, ensure_ascii=False, indent=2) + "\n```",
            "```text\n" + prompt + "\n```"]
    (out / "DIRECTOR_PERFORMANCE_HANDOFF.md").write_text("\n\n".join(handoff), encoding="utf8")
    _save_output_manifest()
    return result


def _save_output_manifest():
    paths = [ROOT / name for name in ("COORDINATOR_RESULT.json", "PRODUCTION_RESULT.json",
        "ACTUAL_REQUEST_PROOF.json", "PRODUCTION_REPORT.md")]
    if (ROOT / "DELIVERABLE").exists(): paths += [path for path in (ROOT / "DELIVERABLE").rglob("*") if path.is_file()]
    old.control.write(ROOT / "OUTPUT_MANIFEST.json", {"schema": VERSION + "/output_manifest",
        "files": {str(path): old.control.sha_file(path) for path in paths}}, True)


def execute(reference_intake_path=None, *, director_request_enricher=None):
    prepare(reference_intake_path)
    if (ROOT / "PRODUCTION_RESULT.json").exists(): return status()
    rt = runtime()
    lock_path = ROOT / "COORDINATOR_EXECUTION.lock"
    try:
        with lock_path.open("x", encoding="utf8") as lock:
            lock.write(json.dumps({"started_at": old.control.now(), "user_quote": USER_QUOTE}))
    except FileExistsError:
        return {"schema": VERSION, "status": "execution_claimed_reconcile_original", "automatic_retry": False,
            "new_request_redispatch_allowed": False, "new_video_calls": 0}
    try:
        inp = old.control.read(ROOT / "INPUT.json")
        x, script, manifest, initial = inp["original_input"], inp["script"], inp["manifest"], inp["initial"]
        if director_request_enricher is not None and inp["reference_intake"] is None:
            raise ValueError("external visual callback requires a frozen actual reference intake bundle")
        def verify():
            verify_loop_history(rt)
            for role, expected in rt.models.items():
                cfg = clients.role_config(role)
                if any(getattr(cfg, key) != expected[key] for key in ("provider", "model", "base_url")):
                    raise ValueError("actual role configuration differs from inherited frozen model")
        def invoke(label, request, validate):
            old.control.write(ROOT / "stage_requests" / (label + ".json"), request, True)
            rt.client_factory = clients.make_client_factory(deepcopy(request))
            return rt.dispatch(label, request, validate)
        flow = coordinator.CompleteProductionCoordinator(invoke=invoke,
            persist_state=lambda state: old.control.write(ROOT / "LOOP_STATE.json", state), verify_frozen_source=verify,
            opening_context_builder=lambda performance: old.shared.compile_segment_context(manifest, script,
                old.bootstrap_dynamic_state(manifest, x), performance["source_refs"], bootstrap=True),
            models={role: cfg["model"] for role, cfg in rt.models.items()},
            director_request_enricher=director_request_enricher or _enricher(inp["reference_intake"]))
        result = flow.run(script=script, manifest=manifest, initial=initial,
            reference_fulltext=x["reference_fulltext"], preferences=x["production_preferences"], brief=x["brief"],
            source_review_binding=inp["source_review_binding"], state=old.control.read(ROOT / "LOOP_STATE.json"),
            scope=old.control.read(ROOT / "USER_SCOPE.json"))
        result = save_artifacts(result, rt, inp)
        return summary_result(result, rt)
    except Exception as exc:
        try: runtime_summary = rt.summary()
        except Exception as failure: runtime_summary = {"status": "unavailable_guard_failure", "error_type": type(failure).__name__}
        evidence = {"schema": VERSION, "status": "execution_interrupted_reconcile_original", "error_type": type(exc).__name__,
            "message": str(exc), "new_request_redispatch_allowed": False, "automatic_retry": False,
            "timestamp": old.control.now(), "runtime_summary": runtime_summary, "new_video_calls": 0}
        old.control.write(ROOT / ("INTERRUPTION_" + old.control.digest(evidence)[:16] + ".json"), evidence, True)
        if not (ROOT / "PRODUCTION_REPORT.md").exists():
            (ROOT / "PRODUCTION_REPORT.md").write_text("# 新流程文本执行中断\n\n原请求、claim与原证据保留；不重复派发。\n\n"
                + json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf8")
        return evidence
    finally:
        lock_path.unlink()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf8")
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "preview", "status", "execute"))
    parser.add_argument("--reference-intake", type=Path)
    args = parser.parse_args()
    operations = {"prepare": lambda: prepare(args.reference_intake), "preview": preview,
        "status": status, "execute": lambda: execute(args.reference_intake)}
    print(json.dumps(operations[args.operation](), ensure_ascii=False), flush=True)
