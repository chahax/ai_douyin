"""Reviewable repaired request from unchanged production sources; zero dispatch."""
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
from src.content_factory import creative_goal_context_workflow_v3 as workflow
from src.content_factory import creative_goal_source_contract_v3 as goals
from src.content_factory import creative_stage_context_v3 as contexts
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request

PARENT = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_02"
DEFAULT_OUTPUT = PROJECT / "data/qa/goal_context_production_repair_20261013/request_preview_r1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def build_preview():
    inputs = read(PARENT / "INPUTS.json")
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v2.json")
    catalog = contexts.build_stage_context("goal_plan", inputs)["payload"]["origin_catalog"]
    replay = {}
    for index in (1, 2, 3):
        native = read(PARENT / "goals" / f"native_{index:02}.json")
        replay[str(530 + index)] = goals.diagnose_goal_document(native,
            **contexts.alias_origin_ids(catalog), origin_catalog=catalog,
            max_characters=inputs["production_preferences"]["max_characters"])
    # The old native is supplied whole. The model, never this compiler, must
    # submit a complete new version in the new contract and exact source aliases.
    repair_inputs = {**deepcopy(inputs),
        "previous_complete_document": read(PARENT / "goals/native_03.json"),
        "revision_diagnostics": {"current_contract": replay["533"],
            "authority_projection": {
                "historical_examples": "user_goal_contract.text is the functional requirement; historical source_quote is local provenance, not a required resignation plot",
                "legal_boundaries": "Optional fictional handling sequence is not mandatory legal law; complete facts and conditions remain supplied",
                "scope": "Focus on the chosen audience question; the complete law catalog need not become a list of separate disputes"}}}
    request = workflow.prepare_goal_request(repair_inputs, profile)
    wire = request["wire"]
    if wire != expected_wire_request(request["request"]):
        raise ValueError("expected wire mapping differs")
    actual = json.loads(wire["messages"][1]["content"])
    if actual["previous_complete_document"] != repair_inputs["previous_complete_document"]:
        raise ValueError("previous native was changed")
    historical = inputs["user_goal_contract"]["audience_goals"][2]["source_quote"]
    if historical in json.dumps(actual["user_goal_contract"], ensure_ascii=False):
        raise ValueError("historical plot quote entered functional goal context")
    for key, value in inputs["verified_legal_context"].items():
        if key != "creative_boundaries" and actual["verified_legal_context"][key] != value:
            raise ValueError("complete legal authority changed: " + key)
    if contexts._reference_occurrences(actual, inputs["reference_fulltext"]) != 1:
        raise ValueError("complete R01 must enter actual request once")
    freeze = read(PARENT / "PRODUCTION_FREEZE.json")
    for path, expected in freeze["files"].items():
        if sha(path) != expected:
            raise ValueError("old production freeze changed: " + path)
    return {"request": request, "inputs": repair_inputs, "replay": replay,
        "summary": {"schema": workflow.VERSION + "/offline_repair_preview",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "paid_calls": 0, "media_calls": 0, "client_constructed": False,
            "old_freeze_files_unchanged": len(freeze["files"]),
            "parent_ledger_sha256": sha(PARENT / "CALL_LEDGER.json"),
            "parent_state": read(PARENT / "STATE.json"),
            "parent_goal_candidates_used": 3, "parent_goal_candidates_limit": 3,
            "additional_candidate_authorized": False, "production_dispatch_eligible": False,
            "model": wire["model"], "payload_characters": len(wire["messages"][1]["content"]),
            "schema_characters": len(json.dumps(request["request"]["structured_schema"], ensure_ascii=False)),
            "platform_aliases": len(catalog["platform_metadata"]),
            "legal_facts": len(actual["verified_legal_context"]["facts"]),
            "reference_characters": len(actual["reference_fulltext"]),
            "native_previous_modified": False, "new_native_script_received": False,
            "human_quality_approved": False, "creative_quality_passed": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    destination = args.output.resolve()
    allowed = (PROJECT / "data/qa/goal_context_production_repair_20261013").resolve()
    if not destination.is_relative_to(allowed) or destination == allowed or destination.exists():
        raise ValueError("fresh independent QA subdirectory required")
    result = build_preview()
    destination.mkdir(parents=True)
    write(destination / "SUMMARY.json", result["summary"])
    write(destination / "GOAL_PLAN_LOGICAL_REQUEST.json", result["request"]["request"])
    write(destination / "GOAL_PLAN_EXPECTED_WIRE.json", result["request"]["wire"])
    write(destination / "CONTEXT_MANIFEST.json", result["request"]["manifest"])
    write(destination / "REPAIR_INPUTS.json", result["inputs"])
    write(destination / "UNCHANGED_531_533_REPLAY.json", result["replay"])
    print(json.dumps({"output": str(destination), **result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
