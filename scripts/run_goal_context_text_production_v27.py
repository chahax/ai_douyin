"""Source-v6 readmission of immutable native618, then bounded whole text.

No whole-film planning call, report recovery, media, publication or old-run replay.
Parent619's certificate remains the unchanged v6 historical verifier scope.
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
from scripts import run_goal_context_text_production_v26 as previous
from scripts import creative_deepseek_strict_role_clients_v5 as strict_clients
from scripts import creative_flat_lineage_guard_v6 as lineage
from scripts.creative_goal_context_dispatch_v11 import GoalContextRuntime
from src.content_factory import creative_goal_context_workflow_v23 as workflow
from src.content_factory import creative_split_full_review_contract_v4 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from src.content_factory import creative_studio_task_store_v1 as tasks
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "goal_context_text_production/v27"
ROOT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_26"
GRANT = "native618_speech_act_source_20261015"
PREFLIGHT_PARENT = previous.ROOT
PARENT_STATE = PREFLIGHT_PARENT / "STATE.json"
CLAIM = PROJECT / "data/creative_fresh_background_claims" / GRANT / "CLAIM.json"
APPROVAL = CLAIM.parent / "USER_CONTINUATION_v1.json"
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v8.json"
PLAN = PROJECT / "docs/CREATIVE_COUNTED_REPAIR_EXECUTION_20261015.md"
CERTIFICATE = ROOT / "CERTIFIED_PARENT_LINEAGE.json"
REQUEST_PREVIEW = PROJECT / "data/qa/creative_speech_act_producer_20261015/FIRST_NATIVE618_SOURCE6_REQUEST_PREVIEW_v1.json"
COUNTED_EXECUTION_ROOT = PROJECT / "data/creative_counted_execution/20261015_v1"
COUNTED_ROUND_KEY = "source_speech_act_v6_attempt_01"
CADENCE_AUTH = COUNTED_EXECUTION_ROOT / "AUTHORIZATION_AND_CADENCE_v1.json"
CADENCE_CONFIRMATION = COUNTED_EXECUTION_ROOT / "USER_COUNT_UNIT_CONFIRMATION_v1.json"
HISTORICAL_PROBE_CLAIM = PROJECT / "data/creative_fresh_background_claims/historical_legal_speech_act_probe_20261015/CLAIM.json"
HISTORICAL_PROBE_ROOT = PROJECT / "data/production_trials/legal_speech_act_probe_20261015/round_01"
STAGE_LIMITS = {"goal_plan": 2, "goal_audit": 3, "complete_script": 3, "full_review": 6}
read, write, digest, sha_file, now = previous.read, previous.write, previous.digest, previous.sha_file, previous.now
parent, original, clients = previous.parent, previous.original, previous.clients
control = previous.control
drama_contract = previous.drama_contract
repairable, diagnosis = previous.repairable, previous.diagnosis
models, script_source_inputs = previous.models, previous.script_source_inputs


def assert_counted_dispatch_allowed():
    """Only the already-active repair round authorizes a new live dispatch."""
    return CountedExecution(COUNTED_EXECUTION_ROOT).assert_dispatch_allowed(COUNTED_ROUND_KEY)


def require_unspent_probe_anchor():
    if HISTORICAL_PROBE_CLAIM.exists() or (HISTORICAL_PROBE_ROOT/"CALL_LEDGER.json").exists():
        raise ValueError("historical probe claim/ledger exists; native619 anchor is stale; new production must inherit original probe consumption and unknown state")


def verify_seed_native(seed):
    ledger = read(PREFLIGHT_PARENT / "CALL_LEDGER.json")
    rows = [row for row in ledger["calls"] if row["ordinal"] == 618]
    if len(rows) != 1:
        raise ValueError("one exact native618 plan receipt required")
    row = rows[0]
    path = PREFLIGHT_PARENT / row["receipt"]
    receipt = read(path)
    if (sha_file(path) != row["receipt_sha256"] or not repairable(receipt)
            or receipt.get("status") != "contract_valid" or receipt["request"]["stage"] != "goal_plan"
            or receipt.get("output") != seed or seed != read(PREFLIGHT_PARENT / "goals/native_01.json")
            or receipt["response_metadata"]["total_tokens"] != 50377):
        raise ValueError("unchanged complete known native618 required; no new plan or local patch")
    workflow.validate_goal_document(seed, inputs=read(PREFLIGHT_PARENT / "INPUTS.json"))
    return {"ordinal": 618, "receipt_path": str(path), "receipt_sha256": row["receipt_sha256"],
        "native_sha256": digest(seed), "contract_valid": True, "semantic_approved": False,
        "used_for_fresh_native_source_readmission": True, "native_goal_locally_patched": False}


def prior_guard():
    require_unspent_probe_anchor()
    runtime = previous.get_runtime()
    runtime.inherited_guard()
    summary = runtime.summary()
    ledger = read(runtime.ledger)
    if [row["ordinal"] for row in ledger["calls"]] != [618, 619]:
        raise ValueError("exact closed618/619 parent ledger required")
    for row in ledger["calls"]:
        receipt = read(PREFLIGHT_PARENT / row["receipt"])
        if sha_file(PREFLIGHT_PARENT / row["receipt"]) != row["receipt_sha256"]:
            raise ValueError("parent native receipt changed")
        original.verify_receipt_evidence(runtime, receipt, receipt["request"])
        if not repairable(receipt) or receipt["response_metadata"]["total_tokens"] != {618:50377,619:47390}[row["ordinal"]]:
            raise ValueError("known complete618/619 usage required")
        if receipt["status"] != ("contract_valid" if row["ordinal"] == 618 else "contract_rejected"):
            raise ValueError("native618 valid, source619 rejected history required")
    state = read(PARENT_STATE)
    if (state.get("status") != "halt_goal_audit_contract_requires_pipeline_diagnosis"
            or state.get("receipt_ordinal") != 619 or state.get("audit_kind") != "source"
            or state.get("text_ready_for_director") is not False or state.get("spend") != summary
            or state.get("cumulative_goal_candidates_used") != 29 or state.get("opening_setup_calls") != 0
            or (summary["effective_calls_started"], summary["effective_reported_tokens"], summary["effective_calls_with_known_usage"]) != (619,12930923,617)
            or summary["stage_calls"] != {"goal_plan":1,"goal_audit":1,"complete_script":0,"full_review":0}
            or summary.get("new_unknown_token_reservations") != 0 or summary.get("unknown_token_reservations") != 93117
            or summary.get("historical_pending_ordinals") != [70,160]):
        raise ValueError("exact terminal619 state, consumption and pending history required")
    verify_seed_native(read(PREFLIGHT_PARENT / "goals/native_01.json"))
    previous.verify_inherited_direction_inputs(read(PREFLIGHT_PARENT / "INPUTS.json"))
    return summary


def authorization_request_identity(prepared):
    return {"source_inputs_sha256":sha_file(PREFLIGHT_PARENT / "INPUTS.json"),
        "model_profile_sha256":sha_file(PROFILE), "actual_prepared_preview_sha256":digest(prepared),
        "counted_execution_root":str(COUNTED_EXECUTION_ROOT), "counted_round_key":COUNTED_ROUND_KEY}


def verify_authorization(approval, prepared, identity):
    expected = {"schema":VERSION+"/derived_authorization_binding", "human_authorized":True,
        "user_quote":"minimax随便追加", "parent_root":str(PREFLIGHT_PARENT),
        "parent_state_sha256":sha_file(PARENT_STATE), "parent_ledger_sha256":sha_file(PREFLIGHT_PARENT/"CALL_LEDGER.json"),
        "authority_source_sha256":sha_file(previous.APPROVAL), "seed_native_identity":identity,
        "whole_plan_candidates_authorized":0, "inherited_goal_candidates_used":29,
        "stage_limits":STAGE_LIMITS, "source619_locally_converted":False,
        "first_action_is_native618_source_readmission":True, "source_interface_or_semantic_failure_stops":True,
        "new_format_or_report_recovery_claimed":False, "old_ledger_reset":False,
        "automatic_transport_retry":False, "media_authorized":False, "publish_authorized":False,
        **authorization_request_identity(prepared)}
    if any(approval.get(key) != value for key,value in expected.items()):
        raise ValueError("continuing authority, native618, preview or counted round binding changed")


def prepare():
    require_unspent_probe_anchor()
    if ROOT.exists() or CLAIM.exists():
        raise RuntimeError("existing root/claim cannot be replayed or regranted")
    expected = read(PARENT_STATE)["spend"]
    certificate = lineage.build_lineage_certificate(PROJECT, PREFLIGHT_PARENT,
        certified_check=prior_guard, expected_summary=expected, dependency_paths=[PARENT_STATE],
        guard_code_paths=[Path(__file__), Path(lineage.__file__)])
    inputs = read(PREFLIGHT_PARENT / "INPUTS.json")
    seed = read(PREFLIGHT_PARENT / "goals/native_01.json")
    identity = verify_seed_native(seed)
    prepared = prepare_source_audit(inputs, read(PROFILE), seed)
    approval = read(APPROVAL)
    verify_authorization(approval, prepared, identity)
    preview = read(REQUEST_PREVIEW)
    if (preview.get("prepared") != prepared or preview.get("seed_native_identity") != identity
            or preview.get("provider_calls") != 0 or preview.get("media_calls") != 0
            or preview.get("creative_quality_approved") is not False
            or preview.get("source619_locally_converted") is not False):
        raise ValueError("immutable first-source preview differs; no claim created")
    inherited = {"calls_started":expected["effective_calls_started"], "reported_tokens":expected["effective_reported_tokens"],
        "calls_with_known_usage":expected["effective_calls_with_known_usage"], "unknown_token_reservations":expected["unknown_token_reservations"],
        "pending_ordinals":expected["historical_pending_ordinals"]}
    scope = {"schema":VERSION+"/user_scope", "grant_id":GRANT, "user_quote":approval["user_quote"],
        "stage_limits":deepcopy(STAGE_LIMITS), "stage_limits_are_local_run_safety_bounds":True,
        "inherited_goal_candidates_used":29, "local_goal_candidates_limit":0, "local_opening_setup_limit":2,
        "cumulative_goal_candidates_this_run_maximum":29, "seed_goal_ordinal":618,
        "seed_used_for_fresh_native_source_readmission":True, "content_revision_limit":2,
        "old_director_candidates_used":7, "old_director_candidates_limit":7, "additional_director_candidates":0,
        "new_format_recovery_claimed":False, "source619_locally_converted":False,
        "automatic_transport_retry":False, "media_authorized":False, "publish_authorized":False,
        "old_ledger_reset":False, "writer_total_call_user_limit":None, "max_total_tokens":None,
        "parent_unused_capacity_stays_in_closed_run":True, "starting_spend":inherited,
        "counted_execution_root":str(COUNTED_EXECUTION_ROOT), "counted_round_key":COUNTED_ROUND_KEY,
        "parent_ledger_sha256":sha_file(PREFLIGHT_PARENT/"CALL_LEDGER.json")}
    write(CLAIM, {"schema":VERSION+"/continuation_claim", "grant_id":GRANT, "root":str(ROOT),
        "created_at":now(), "parent_root":str(PREFLIGHT_PARENT), "authorization_sha256":sha_file(APPROVAL),
        "parent_ledger_sha256":scope["parent_ledger_sha256"], "old_allowance_reset":False}, True)
    ROOT.mkdir(parents=True)
    write(CERTIFICATE, certificate, True)
    for name,value in (("USER_SCOPE",scope),("INPUTS",inputs),("INHERITED_NATIVE_GOAL",seed),
            ("FIRST_NATIVE_SOURCE_REQUEST_PREVIEW",prepared),("SOURCE_GATE",parent.source_gate())):
        write(ROOT/(name+".json"),value,True)
    paths = set(read(PREFLIGHT_PARENT/"PRODUCTION_FREEZE.json")["files"])
    paths.update(str(path.resolve()) for path in (Path(__file__), PROFILE, PLAN, PARENT_STATE, APPROVAL,
        CERTIFICATE, REQUEST_PREVIEW, Path(workflow.__file__), Path(strict_clients.__file__), Path(clients.__file__),
        PROJECT/"src/content_factory/creative_goal_legal_usage_source_audit_v6.py",
        PROJECT/"src/content_factory/creative_counted_execution_v1.py",
        CADENCE_AUTH, CADENCE_CONFIRMATION,
        PROJECT/"scripts/creative_goal_context_dispatch_v11.py",
        PROJECT/"scripts/record_native618_speech_act_continuation_v1.py",
        PREFLIGHT_PARENT/"CALL_LEDGER.json", PREFLIGHT_PARENT/"RUN_CLAIM.json",
        *(ROOT/(name+".json") for name in ("USER_SCOPE","INPUTS","INHERITED_NATIVE_GOAL","FIRST_NATIVE_SOURCE_REQUEST_PREVIEW","SOURCE_GATE"))))
    freeze = {"schema":VERSION+"/freeze", "inherited":inherited,
        "parent_certificate_sha256":digest(certificate), "seed_native_identity":identity,
        "models":models(read(PROFILE)), "global_claim_sha256":sha_file(CLAIM),
        "continuation_authorization_sha256":sha_file(APPROVAL), "parent_ledger_sha256":scope["parent_ledger_sha256"],
        "sources":sorted(paths), "files":{path:sha_file(path) for path in sorted(paths)},
        "parent_certificate_scope":"closed round25 through619 only; new source6 future inheritance not implemented",
        "media_authorized":False}
    write(ROOT/"PRODUCTION_FREEZE.json",freeze,True)
    runtime = get_runtime()
    runtime.prepare()
    return state(runtime,"prepared")


def get_runtime():
    freeze, profile = read(ROOT/"PRODUCTION_FREEZE.json"), read(PROFILE)
    def guard():
        require_unspent_probe_anchor()
        lineage.verify_lineage_certificate(read(CERTIFICATE), expected_certificate_sha256=freeze["parent_certificate_sha256"],
            fresh_source_gate=parent.source_gate, expected_inherited=freeze["inherited"])
        if sha_file(PREFLIGHT_PARENT/"CALL_LEDGER.json") != freeze["parent_ledger_sha256"]:
            raise ValueError("parent consumption changed")
        if verify_seed_native(read(ROOT/"INHERITED_NATIVE_GOAL.json")) != freeze["seed_native_identity"]:
            raise ValueError("native618 identity changed")
        if (read(CLAIM)["root"] != str(ROOT) or sha_file(APPROVAL) != freeze["continuation_authorization_sha256"]
                or sha_file(CLAIM) != freeze["global_claim_sha256"]):
            raise ValueError("new authorization claim changed")
        for path, expected in freeze["files"].items():
            if sha_file(path) != expected:
                raise ValueError("independent frozen input changed: "+path)
    return GoalContextRuntime(PROJECT,ROOT,[Path(path) for path in freeze["sources"]],freeze["inherited"],
        freeze["models"], inherited_guard=guard, profile=profile,
        stage_limits=read(ROOT/"USER_SCOPE.json")["stage_limits"], quota_state=None,
        shared_lock=PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",
        admission=lambda label,request,ledger:assert_counted_dispatch_allowed(),
        client_factory_builder=lambda request:strict_clients.make_client_factory(request,
            source_strict=is_strict_source(request),review_base_url=profile["source_strict"]["base_url"],
            max_wire_utf8_bytes=profile["source_strict"]["max_wire_utf8_bytes"]))


def validate_opening_setup(value, goal):
    native = workflow.validate_opening_setup_document(value,goal)
    return {"valid":True,"native_setup_sha256":digest(native),"native_goal_sha256":digest(goal),
        "state_fields_inferred":False,"semantic_quality_approved":False}


def state(runtime, status, **extra):
    result = {"schema":VERSION+"/state", "status":status, "updated_at":now(),
        "text_ready_for_director":False, "human_quality_approved":False, "creative_quality_passed":False,
        "media_authorized":False, "old_director_capacity":{"used":7,"limit":7,"remaining":0},
        "inherited_goal_candidates_used":29, "cumulative_goal_candidates_used":29,
        "new_whole_goal_calls":0, "source619_locally_converted":False,
        "counted_execution_root":str(COUNTED_EXECUTION_ROOT), "counted_round_key":COUNTED_ROUND_KEY,
        "spend":runtime.summary(), **extra}
    result["opening_setup_calls"] = sum(row.get("label","").startswith("opening_setup_") for row in read(runtime.ledger)["calls"])
    write(ROOT/"STATE.json",result)
    return result


def run():
    require_unspent_probe_anchor()
    runtime = get_runtime()
    runtime.inherited_guard()
    if (ROOT/"RUN_CLAIM.json").exists():
        raise FileExistsError("original run claim exists; inspect without restart")
    assert_counted_dispatch_allowed()
    write(ROOT/"RUN_CLAIM.json",{"schema":VERSION+"/claim","started_at":now(),"pid":os.getpid(),
        "automatic_restart":False},True)
    if read(runtime.ledger)["calls"]:
        raise RuntimeError("claimed run has previous calls; no replay")
    inputs, profile = read(ROOT/"INPUTS.json"),read(PROFILE)
    goal = read(ROOT/"INHERITED_NATIVE_GOAL.json")
    verify_seed_native(goal)
    bundle, decisions = {}, []
    for kind in ("source","commitment","drama"):
        prepared = prepare_source_audit(inputs,profile,goal) if kind=="source" else getattr(workflow,f"prepare_goal_{kind}_audit_request")(inputs,profile,goal)
        if kind=="source" and prepared!=read(ROOT/"FIRST_NATIVE_SOURCE_REQUEST_PREVIEW.json"):
            raise ValueError("actual native618 source request differs from immutable preview")
        args = {"context_sha256":prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]}
        if kind=="source":args["authority_context"]=deepcopy(prepared["source_authority_context"])
        validator = getattr(workflow,f"validate_goal_{kind}_audit")
        receipt = invoke(runtime,f"goal_{kind}_audit_01",prepared,lambda value,v=validator,a=args:v(value,goal,**a))
        if receipt.get("cached_response_read_only"):
            return state(runtime,"halt_cached_goal_audit_no_new_claim",receipt_ordinal=receipt["ordinal"])
        if not repairable(receipt):
            return state(runtime,"halt_goal_audit_interface_or_unknown",receipt_ordinal=receipt["ordinal"],audit_kind=kind)
        if receipt["status"]!="contract_valid":
            return state(runtime,"halt_goal_audit_contract_requires_pipeline_diagnosis",receipt_ordinal=receipt["ordinal"],audit_kind=kind)
        verdict = receipt["validation"]
        write(ROOT/"goals"/f"{kind}_native_audit_01.json",receipt["output"],True)
        write(ROOT/"goals"/f"{kind}_audit_decision_01.json",verdict,True)
        if not verdict["accepted"] or verdict["uncertainties"]:
            return state(runtime,"halt_goal_content_requires_pipeline_diagnosis",receipt_ordinal=receipt["ordinal"],audit_kind=kind,decision=verdict,new_whole_goal_dispatched=False)
        decisions.append(verdict)
        bundle[f"native_{kind}_audit"] = receipt["output"]
    audit = workflow.build_goal_audit_bundle(bundle["native_source_audit"],bundle["native_drama_audit"],bundle["native_commitment_audit"])
    return complete_text(runtime,inputs,profile,goal,audit,618)


def is_strict_source(request):
    return (request.get("role")=="director" and request.get("stage")=="goal_audit"
        and request.get("structured_schema",{}).get("properties",{}).get("schema",{}).get("const")
            =="creative_goal_legal_usage_source_audit/v6")


def prepare_source_audit(inputs,profile,goal):
    policy=profile.get("source_strict",{})
    if (policy.get("enabled") is not True or policy.get("base_url")!="https://api.deepseek.com/beta"
            or policy.get("function_strict") is not True or policy.get("other_deepseek_stages_strict") is not False
            or policy.get("role")!="director" or policy.get("stage")!="goal_audit"
            or policy.get("schema_version")!="creative_goal_legal_usage_source_audit/v6"
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
    assert_counted_dispatch_allowed()
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



def complete_text(runtime, inputs, profile, goal, audit, goal_ordinal):
    ids = workflow.origin_ids(inputs)
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
    parser.add_argument("command",choices=("prepare","run","status"))
    args = parser.parse_args(argv)
    if args.command=="prepare":result=prepare()
    elif args.command=="status":result=read(ROOT/"STATE.json")
    else:
        try:result=run()
        except Exception as exc:
            write(ROOT/"EXECUTION_ERROR.json",{"status":"stopped_original_request_requires_reconciliation",
                "error_type":type(exc).__name__,"error":str(exc),"new_request_dispatched_by_recovery":False},True)
            raise
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
