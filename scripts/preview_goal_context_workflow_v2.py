"""Read-only production lineage -> independent offline request/contract preview.

No live dispatcher, client, service claim, credential read or media operation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.content_factory import creative_goal_context_workflow_v2 as workflow
from src.content_factory import creative_goal_source_contract_v2 as goals
from src.content_factory import creative_full_review_contract_v2 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy

M31_ROOT = PROJECT / "data/production_trials/m31_flash_script_test_20261013/round_01"
SOURCE_ROOT = PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01"
DEFAULT_OUTPUT = PROJECT / "data/qa/goal_context_contract_refactor_20261013/request_preview_r1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def production_inputs():
    writer = read(M31_ROOT / "call_529_m31_complete_script_01.json")
    review = read(M31_ROOT / "call_530_m31_full_review_01.json")
    source = json.loads(writer["request"]["messages"][1]["content"])
    packet = read(SOURCE_ROOT / "source/SOURCE_PACKET.json")
    source_check = legacy.graph_bridge.validate_packet(packet, now=datetime.now(timezone.utc).isoformat())
    identity = source["source_packet"]["source_identity"]
    if (identity["source_packet_semantic_sha256"] != workflow.digest(packet)
            or identity["source_semantic_sha256"] != packet["source_sha256"]
            or identity["graph_semantic_sha256"] != packet["graph_sha256"]):
        raise ValueError("complete source authority and actual compact request identity differ")
    inputs = {key: deepcopy(source[key]) for key in (
        "source_packet", "verified_legal_context", "reference_fulltext", "expression_standards", "production_preferences")}
    inputs["user_goal_contract"] = goals.build_user_goal_contract()
    return inputs, source, writer, review, {
        "validated_complete_authority": True,
        "source_packet_sha256": workflow.digest(packet),
        "revalidation_snapshot_sha256": workflow.digest(source_check),
        "compact_projection_matches_complete_authority": True}


def build_preview():
    inputs, source, writer, review, source_check = production_inputs()
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v2.json")
    planned = workflow.prepare_goal_request(inputs, profile)
    native = read(M31_ROOT / "NATIVE_SCRIPT.json")
    script = legacy.contract.compile_script(native, source["brief"])
    old_full_review = review["output"]
    replay = reviews.validate_full_review(old_full_review, script, source["brief"], source["creative_scene_plan"],
        source["verified_legal_context"], goal_contract=inputs["user_goal_contract"])
    schema = reviews.build_review_schema(script, source["brief"], source["creative_scene_plan"],
        source["verified_legal_context"], goal_contract=inputs["user_goal_contract"])
    old_wire = read(M31_ROOT / "EXPECTED_SDK_BODY.json")
    sizes = {"old_writer_user_payload_characters": len(writer["request"]["messages"][1]["content"]),
        "new_goal_user_payload_characters": len(planned["request"]["messages"][1]["content"]),
        "old_writer_actual_prompt_tokens": writer["response_metadata"]["prompt_tokens"],
        "new_goal_actual_prompt_tokens": None,
        "comparison_scope": "different-stage payload character measurements; not controlled model quality/token experiment",
        "new_goal_schema_characters": len(json.dumps(planned["request"]["structured_schema"], ensure_ascii=False, separators=(",", ":"))),
        "new_review_schema_characters": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))}
    freeze = read(M31_ROOT / "TEST_FREEZE.json")
    frozen_status = []
    for relative, expected in freeze["files"].items():
        actual = sha_file(PROJECT / relative)
        if actual != expected:
            raise ValueError("previous production freeze changed: " + relative)
        frozen_status.append({"path": relative, "sha256": actual})
    ledger = read(M31_ROOT / "CALL_LEDGER.json")
    return {"summary": {
        "schema": workflow.VERSION + "/offline_preview", "created_at": datetime.now(timezone.utc).isoformat(),
        "actual_provider_dispatches": 0, "client_constructed": False, "paid_claims": 0,
        "native_new_goal_received": False, "new_complete_script_generated": False,
        "text_ready_for_director": False, "production_quality_passed": False,
        "source_check": source_check, "measurement": sizes,
        "previous_530_replay": replay,
        "inherited_ledger_sha256": sha_file(M31_ROOT / "CALL_LEDGER.json"),
        "historical_ledger_sha256": sha_file(SOURCE_ROOT / "CALL_LEDGER.json"),
        "original_frozen_files_unchanged": frozen_status,
        "existing_call_ordinals": [row["ordinal"] for row in ledger["calls"]],
        "candidate_dispatch_gate": "requires a separately reconciled lineage, authorization and durable runtime; no scope reset by preview",
        "original_model_request_retained": isinstance(old_wire, dict),
        "limitations": ["Typed goal classification still requires native semantic audit.",
            "Reported action-state witnesses do not deterministically understand natural-language actions.",
            "Live text dispatcher and downstream director/performance/media are not switched by this offline entry."]},
        "goal_request": planned, "old_529_new_review_schema_only": schema,
        "user_goal_contract": inputs["user_goal_contract"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    allowed = (PROJECT / "data/qa/goal_context_contract_refactor_20261013").resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("fresh output subdirectory inside the independent QA root required")
    result = build_preview()
    output.mkdir(parents=True)
    write(output / "SUMMARY.json", result["summary"])
    write(output / "GOAL_PLAN_LOGICAL_REQUEST.json", result["goal_request"]["request"])
    write(output / "GOAL_PLAN_EXPECTED_WIRE.json", result["goal_request"]["wire"])
    write(output / "CONTEXT_MANIFEST.json", result["goal_request"]["manifest"])
    write(output / "OLD_529_NEW_REVIEW_SCHEMA_ONLY.json", result["old_529_new_review_schema_only"])
    write(output / "USER_GOAL_CONTRACT.json", result["user_goal_contract"])
    print(json.dumps({"output": str(output), "paid_claims": 0,
        "old_530_replay": result["summary"]["previous_530_replay"], "measurement": result["summary"]["measurement"]},
        ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
