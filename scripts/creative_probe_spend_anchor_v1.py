"""Read-only native620 consumption bridge; never a dispatch or freshness gate.

The completed historical probe has no task DAG. Reuse its frozen historical
guard and the generic original SDK receipt verifier, without inventing SQLite
history or requiring its now-completed repair round to remain active.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from scripts import run_legal_speech_act_probe_v1 as probe
from src.content_factory import creative_flat_lineage_verifier_v6 as native

VERSION = "creative_probe_spend_anchor/v1"
PROJECT, ROOT = probe.PROJECT, probe.ROOT
PARENT = {"calls_started":619,"reported_tokens":12930923,"calls_with_known_usage":617,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
INHERITED = {"calls_started":620,"reported_tokens":12941524,"calls_with_known_usage":618,
    "pending_ordinals":[70,160],"unknown_token_reservations":93117}
EXPECTED_FREEZE_SHA256 = "96d2adaf96663d7693851007c746bcf7d675aa6bbeacfd25f5cb0e9d9a6ce66b"
EXPECTED_LEDGER_SHA256 = "a5bd4bde9a5ac39ce4fb2f9f89937932efa9a457742c216ed90dfe4831c361ef"
EXPECTED_STATE_SHA256 = "1c3f27d6723f9fa769d6620e4a559877d9d18820f9b05ec718481fee10843dd9"
read, digest, sha_file = probe.read, probe.digest, probe.sha_file


def _spend(value, expected):
    if (type(value) is not dict or set(value)!=set(expected)
            or any(type(value.get(key)) is not int or value[key]<0 for key in expected if key!="pending_ordinals")
            or type(value.get("pending_ordinals")) is not list
            or any(type(item) is not int for item in value["pending_ordinals"])
            or value!=expected):
        raise ValueError("complete original inherited consumption required; no omission/reset")


def validate_records(ledger, receipt, terminal, freeze, scope, authorization):
    """Pure typed accounting check, after the caller verifies original bytes."""
    _spend(freeze.get("inherited"),PARENT)
    _spend(ledger.get("starting_spend"),PARENT)
    _spend(scope.get("starting_spend"),PARENT)
    _spend(authorization.get("starting_spend"),PARENT)
    calls=ledger.get("calls")
    if (type(calls) is not list or len(calls)!=1 or calls[0].get("ordinal")!=620
            or calls[0].get("label")!="historical_speech_act_probe_01"
            or calls[0].get("receipt")!="call_620_historical_speech_act_probe_01.json"):
        raise ValueError("exact unique620 ledger required; missing/duplicate calls cannot be bridged")
    if (ledger.get("max_total_tokens") is not None or ledger.get("automatic_retry") is not False
            or ledger.get("old_budget_reset") is not False or ledger.get("old_governance_migrated") is not False
            or authorization.get("media_calls_authorized") is not False):
        raise ValueError("original no-reset/no-retry text scope required")
    if (receipt.get("ordinal")!=620 or receipt.get("label")!=calls[0]["label"]
            or receipt.get("status")!="contract_valid" or receipt.get("automatic_retry") is not False
            or receipt.get("semantic_approval") is not False):
        raise ValueError("original known620 receipt identity/status required")
    request=receipt.get("request",{})
    meta=receipt.get("response_metadata",{})
    usage=receipt.get("response_payload",{}).get("usage",{})
    if (request.get("stage")!="goal_audit" or request.get("role")!="director"
            or request.get("model")!="deepseek-flash"
            or request.get("structured_schema",{}).get("properties",{}).get("schema")!={"const":probe.VERSION}
            or receipt.get("request_sha256")!=digest(request)
            or meta.get("http_status_code")!=200 or type(meta.get("http_status_code")) is not int
            or meta.get("response_body_complete") is not True or meta.get("finish_reason")!="tool_calls"
            or meta.get("output_mode")!="tool_call" or meta.get("requested_model")!="deepseek-flash"
            or meta.get("response_model")!="deepseek-flash"):
        raise ValueError("original complete model/tool/HTTP identity required")
    for key in ("prompt_tokens","completion_tokens","total_tokens"):
        if type(meta.get(key)) is not int or meta[key]<0 or type(usage.get(key)) is not int or meta[key]!=usage[key]:
            raise ValueError("known nonnegative original integer usage required")
    if (meta["prompt_tokens"]+meta["completion_tokens"]!=meta["total_tokens"]
            or meta["total_tokens"]!=10601):
        raise ValueError("exact620 reported consumption required")
    if (scope.get("stage_limits")!={"goal_plan":0,"goal_audit":1,"complete_script":0,"full_review":0}
            or any(type(value) is not int for value in scope.get("stage_limits",{}).values())
            or type(scope.get("new_deepseek_calls_limit")) is not int or type(scope.get("writer_calls_limit")) is not int
            or scope.get("new_deepseek_calls_limit")!=1 or scope.get("writer_calls_limit")!=0
            or scope.get("old_director_capacity")!={"used":7,"limit":7,"remaining":0}
            or scope.get("historical_diagnostic_only") is not True or scope.get("media_authorized") is not False):
        raise ValueError("original single historical diagnostic scope required")
    summary=terminal.get("spend",{})
    count_fields=("new_calls","new_reported_tokens","effective_calls_started","effective_reported_tokens",
        "effective_calls_with_known_usage","new_calls_with_known_usage","unknown_token_reservations",
        "new_unknown_token_reservations","media_calls")
    if (terminal.get("status")!="historical_probe_routing_passed_not_production"
            or terminal.get("receipt_ordinal")!=620 or terminal.get("historical_diagnostic_only") is not True
            or any(terminal.get(key) is not False for key in ("text_ready_for_director","current_source_freshness_passed",
                "media_authorized","source618_approved","creative_quality_passed"))
            or terminal.get("decision")!=receipt.get("validation")
            or any(type(summary.get(key)) is not int or summary[key]<0 for key in count_fields)
            or summary.get("new_calls")!=1 or summary.get("new_reported_tokens")!=10601
            or summary.get("effective_calls_started")!=620 or summary.get("effective_reported_tokens")!=12941524
            or summary.get("effective_calls_with_known_usage")!=618 or summary.get("new_calls_with_known_usage")!=1
            or summary.get("unknown_token_reservations")!=93117 or summary.get("new_unknown_token_reservations")!=0
            or summary.get("historical_pending_ordinals")!=[70,160]
            or summary.get("stage_calls")!={"goal_plan":0,"goal_audit":1,"complete_script":0,"full_review":0}
            or summary.get("media_calls")!=0 or summary.get("old_budget_reset") is not False):
        raise ValueError("original620 terminal accounting/quality boundaries changed")
    return deepcopy(INHERITED)


def verify_original_receipt(root, ledger):
    """Original wire, response bytes, model, tool arguments and usage, read-only."""
    calls=ledger.get("calls",[])
    if len(calls)!=1 or calls[0].get("ordinal")!=620:
        raise ValueError("exact unique620 receipt required before raw verification")
    return native._receipt(native.VerificationCycle(),PROJECT,Path(root),calls[0],ledger["source_manifest"])


def build_anchor():
    """Deterministic identity and spend only; creates no files/claims/clients."""
    freeze_path,ledger_path,state_path=(ROOT/name for name in ("PRODUCTION_FREEZE.json","CALL_LEDGER.json","STATE.json"))
    for path,expected in ((freeze_path,EXPECTED_FREEZE_SHA256),(ledger_path,EXPECTED_LEDGER_SHA256),(state_path,EXPECTED_STATE_SHA256)):
        if sha_file(path)!=expected:raise ValueError("original620 frozen identity changed: "+str(path))
    freeze,ledger,terminal=read(freeze_path),read(ledger_path),read(state_path)
    # No CountedExecution check: the original dispatch round has ended. This
    # import performs historical reads only, never an old-key dispatch/restart.
    historical=probe.historical_parent_guard()
    if (historical.get("historical_integrity_verified") is not True
            or historical.get("current_source_freshness_passed") is not False
            or historical.get("current_source_freshness_checked") is not False
            or historical.get("inherited")!=PARENT):
        raise ValueError("original619 historical integrity proof required; not a freshness proof")
    if (read(probe.CLAIM).get("root")!=str(ROOT) or sha_file(probe.CLAIM)!=freeze.get("claim_sha256")
            or freeze.get("models")!=probe.production.models(read(probe.PROFILE))):
        raise ValueError("original probe claim/model binding changed")
    for path,expected in freeze["files"].items():
        if sha_file(path)!=expected:raise ValueError("original probe frozen source changed: "+path)
    if sorted(freeze["sources"])!=sorted(freeze["files"]):raise ValueError("complete probe source freeze required")
    manifest={str(Path(path).resolve().relative_to(PROJECT.resolve())).replace("\\","/"):sha
        for path,sha in freeze["files"].items()}
    if ledger.get("source_manifest")!=manifest:raise ValueError("original probe source manifest changed")
    for rel,sha in manifest.items():
        if sha_file(ROOT/"source_at_dispatch"/rel)!=sha:raise ValueError("probe source snapshot changed: "+rel)
    if sha_file(ROOT/"AUTHORIZATION.json")!=ledger.get("authorization_sha256"):
        raise ValueError("original runtime authorization changed")
    # Windows glob is case-insensitive and also matches CALL_LEDGER.json.
    native_calls=sorted(path.name for path in ROOT.iterdir()
        if path.is_file() and path.name.startswith("call_") and path.name.endswith(".json"))
    if native_calls!=["call_620_historical_speech_act_probe_01.json"]:
        raise ValueError("orphan/missing original probe receipt")
    receipt=verify_original_receipt(ROOT,ledger)
    prepared=read(ROOT/"PREPARED_PROBE.json")
    if (prepared!=probe.prepare_probe() or receipt["request"]!=prepared["request"]
            or receipt["request_sha256"]!=prepared["request_sha256"]
            or read(ROOT/"RUN_CLAIM.json").get("automatic_restart") is not False):
        raise ValueError("original probe request/run identity changed")
    inherited=validate_records(ledger,receipt,terminal,freeze,read(ROOT/"USER_SCOPE.json"),read(ROOT/"AUTHORIZATION.json"))
    return {"schema":VERSION,"root":str(ROOT),"inherited":inherited,
        "original_parent_inherited":deepcopy(PARENT),"new_calls":[620],"new_reported_tokens":10601,
        "probe_freeze_sha256":EXPECTED_FREEZE_SHA256,"probe_ledger_sha256":EXPECTED_LEDGER_SHA256,
        "probe_state_sha256":EXPECTED_STATE_SHA256,"native_receipt_sha256":ledger["calls"][0]["receipt_sha256"],
        "native_request_sha256":receipt["request_sha256"],"native_response_raw_sha256":receipt["response_metadata"]["raw_body_sha256"],
        "source_manifest_sha256":digest(manifest),"historical_parent_root":str(probe.PARENT_ROOT),
        "old_director_capacity":{"used":7,"limit":7,"remaining":0},
        "inherited_whole_goal_candidates_used":29,"historical_integrity_verified":True,
        "historical_diagnostic_only":True,"current_source_freshness_verified":False,
        "text_ready_for_director":False,"creative_quality_passed":False,"authorizes_new_dispatch":False,
        "old_dispatch_round_key_is_history_only":True,"next_dispatch_requires_current_counted_round":True,
        "media_authorized":False,"publish_authorized":False,"old_budget_reset":False,
        "verifier_code_sha256":sha_file(Path(__file__))}


def verify_anchor(anchor, *, expected_anchor_sha256):
    if digest(anchor)!=expected_anchor_sha256:raise ValueError("frozen consumption anchor SHA changed")
    actual=build_anchor()
    if actual!=anchor:raise ValueError("original620 consumption changed since anchor freeze")
    return {"verified":True,"inherited":deepcopy(actual["inherited"]),
        "current_source_freshness_verified":False,"authorizes_new_dispatch":False}
