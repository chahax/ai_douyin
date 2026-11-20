"""Read-only settled H3 637--640 bridge from the already certified636 anchor.

This bounded bridge rechecks four original SDK requests/responses and638 local
recovery. It does not rerun all ancestors or authorize any new request.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_session_spend_anchor_v1 as base
from scripts import creative_m31_screenplay_role_clients_v1 as clients

VERSION = "creative_world_scene_spend_anchor/v1"
PROJECT = Path(__file__).resolve().parents[1]
PARENT = PROJECT / "data/qa/creative_paired_live_diagnostic_20261015/PROBE636_SPEND_ANCHOR_v1.json"
PARENT_SHA = "5901fc8a4325bcf04ed72e806881b16af3fd9ed66d02a0308bdd956e648e4bc2"
H3 = PROJECT / "data/video_generation/h3_project_script_20261015/revision_02"
EXPECTED = {"calls_started": 640, "reported_tokens": 13544245,
    "calls_with_known_usage": 638, "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
digest = io.digest


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _receipt(reader, root, ledger, row):
    path = base._inside(root / row["receipt"], root)
    reader.verify(path, row["receipt_sha256"])
    original = reader.json(path)
    receipt = original
    if row["ordinal"] == 638:
        require(original.get("status") == "pending_response", "original638 pending record changed")
        index = reader.json(root / "RECOVERY_INDEX.json")
        entry = index["recoveries"]["638"]
        recovery_path = base._inside(root / entry["file"], root)
        reader.verify(recovery_path, entry["sha256"])
        recovery = reader.json(recovery_path)
        require(recovery.get("original_receipt_sha256") == row["receipt_sha256"]
            and all(recovery.get(k) is False for k in ("provider_called", "original_receipt_mutated", "budget_reset")),
            "638 recovery must preserve original request and spend")
        receipt = recovery["effective_receipt"]
        require(all(receipt.get(k) == v for k, v in original.items() if k != "status"), "638 recovered request differs")
    request = receipt["request"]
    require(receipt.get("ordinal") == row["ordinal"] and receipt.get("label") == row["label"]
        and receipt.get("request_sha256") == digest(request)
        and receipt.get("source_binding_sha256") == digest(ledger["source_manifest"])
        and receipt.get("token_reservation") == row["token_reservation"]
        and receipt.get("status") in ("contract_valid", "contract_rejected")
        and receipt.get("automatic_retry") is False, "complete original request identity differs")
    directory = base._inside(root / receipt["call_evidence"]["directory"], root / "call_evidence")
    identity = {"ordinal": receipt["ordinal"], "label": receipt["label"], "request_sha256": receipt["request_sha256"],
        "source_binding_sha256": receipt["source_binding_sha256"], "role": request["role"], "model": request["model"]}
    identity_sha = digest(identity)
    require(reader.json(directory / "IDENTITY.json")["identity"] == identity
        and receipt["call_evidence"]["identity_sha256"] == identity_sha, "SDK identity differs")
    wire, request_raw, _ = base._body(reader, directory, "request", identity_sha)
    require(wire == clients.expected_wire_request(request), "original actual SDK wire differs")
    proof = reader.json(directory / "M31_WIRE_PREFLIGHT.json")
    require(proof.get("identity_sha256") == identity_sha
        and proof.get("status") == "wire_verified_before_send"
        and proof.get("logical_request_sha256") == digest(request)
        and proof.get("expected_wire_sha256") == proof.get("actual_wire_sha256") == digest(wire)
        and proof.get("actual_request_body_sha256") == hashlib.sha256(request_raw).hexdigest()
        and type(proof.get("SDK_max_retries")) is int and proof["SDK_max_retries"] == 0,
        "original SDK wire proof differs")
    payload, response_raw, body = base._body(reader, directory, "response", identity_sha)
    if row["ordinal"] == 638:
        require(recovery["body_manifest_sha256"] == digest(reader.json(directory / "RESPONSE_BODY_MANIFEST.json")),
            "638 recovery original response binding differs")
    metadata = receipt["response_metadata"]
    require(metadata.get("http_status_code") == 200 and metadata.get("response_body_complete") is True
        and metadata.get("raw_body_sha256") == hashlib.sha256(response_raw).hexdigest()
        and body["http_metadata"]["http_status_code"] == 200 and payload == receipt["response_payload"],
        "complete original response evidence differs")
    choices = payload["choices"]
    require(len(choices) == 1 and choices[0]["finish_reason"] == metadata["finish_reason"] == "tool_calls",
        "explicit completed tool response required")
    tools = choices[0]["message"]["tool_calls"]
    require(len(tools) == 1 and tools[0]["type"] == "function"
        and tools[0]["function"]["name"] == wire["tools"][0]["function"]["name"]
        and tools[0]["function"]["arguments"] == receipt["response_text"]
        and io.strict_json(receipt["response_text"]) == receipt["output"], "native tool output differs")
    usage = payload["usage"]
    require(all(type(usage.get(k)) is int and usage[k] >= 0 and usage[k] == metadata[k]
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
        and usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"]
        and payload.get("model") == metadata.get("response_model") == request["model"], "known usage/model differs")
    return {"ordinal": receipt["ordinal"], "reported_tokens": usage["total_tokens"],
        "native_output_sha256": digest(receipt["output"]), "content_status": receipt["status"],
        "local_recovery_without_dispatch": row["ordinal"] == 638}


def build_anchor():
    reader = base.Reader()
    parent = reader.json(PARENT)
    require(digest(parent) == PARENT_SHA, "already certified636 anchor changed")
    inherited = base._spend(parent["inherited"])
    calls = []
    for sub, expected_ordinals in (("text", [637, 638]), ("text_successor", [639]), ("text_final", [640])):
        root = H3 / sub
        ledger = reader.json(root / "CALL_LEDGER.json")
        prepared = reader.json(root / "PREPARED.json")
        preview = reader.json(root / "PREVIEW.json")
        require(ledger["starting_spend"] == inherited
            and [row["ordinal"] for row in ledger["calls"]] == expected_ordinals
            and all(ledger.get(k) is False for k in ("automatic_retry", "old_budget_reset", "old_governance_migrated")),
            "settled ledger has extra dispatch, changed ancestry or reset")
        require(prepared["binding"]["root"] == str(root)
            and prepared["binding"]["old_budget_reset"] is False, "successor binding differs")
        for claim in prepared["successor_claim_paths"]:
            require(reader.json(claim) == prepared["binding"], "original unique successor claim differs")
        if sub == "text":
            require(preview["parent_anchor_sha256"] == PARENT_SHA
                and preview["inherited"] == inherited, "636 to637 ancestry differs")
        else:
            require(preview["parent"]["inherited"] == inherited
                and digest(preview["parent"]) == prepared["binding"]["parent_anchor_sha256"], "settled parent differs")
        for row in ledger["calls"]:
            result = _receipt(reader, root, ledger, row)
            calls.append(result)
            inherited["calls_started"] += 1
            inherited["calls_with_known_usage"] += 1
            inherited["reported_tokens"] += result["reported_tokens"]
        state = reader.json(root / "STATE.json")
        require(state.get("text_ready_for_director") is False, "unexpected adopted text needs new reconciliation")
        if sub == "text_successor":
            require(state.get("status") == "awaiting_primary_world_content_review"
                and reader.json(root / "WORLD_PRIMARY_DECISION.json").get("decision") == "rejected",
                "639 final rejection missing despite unchanged earlier state")
        else:
            require(str(state.get("status", "")).startswith("halt_"), "nonterminal text needs reconciliation")
        if sub != "text":
            reader.json(root / "STOP.json")
    final = H3 / "text_final"
    state = reader.json(final / "STATE.json")
    require(inherited == EXPECTED and state["spend"]["effective_calls_started"] == 640
        and state["spend"]["effective_reported_tokens"] == EXPECTED["reported_tokens"], "640 settled total differs")
    require(reader.json(final / "PRIMARY_JOINT_CONTENT_REJECTION.json").get("decision") == "rejected",
        "640 rejected native content cannot be promoted")
    identity = {"root": str(final), "end_ordinal": 640,
        "terminal_state_sha256": io.sha_file(final / "STATE.json"),
        "native_ledger_sha256": io.sha_file(final / "CALL_LEDGER.json")}
    files = {path: entry["sha256"] for path, entry in reader.files.items()}
    return {"schema": VERSION, "root": str(final), "parent_identity": identity,
        "inherited": inherited, "parent_anchor_path": str(PARENT), "parent_anchor_sha256": PARENT_SHA,
        "new_verified_calls": calls, "source_files": files, "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "old_h3_body_capacity": {"used": 3, "limit": 3, "remaining": 0}, "old_budget_reset": False,
        "verification_scope": "Previously certified636 anchor bytes, then original637--640 SDK/wire/usage/recovery/claims; not all ancestor source files reaudited",
        "authorizes_dispatch": False}


def verify_anchor(anchor, *, expected_anchor_sha256):
    require(type(anchor) is dict and digest(anchor) == expected_anchor_sha256, "640 anchor identity differs")
    current = build_anchor()
    require(current == anchor, "640 original settled evidence changed")
    return {"verified": True, "anchor": deepcopy(anchor), "inherited": deepcopy(anchor["inherited"]),
        "source_files": deepcopy(anchor["source_files"]), "authorizes_dispatch": False}
