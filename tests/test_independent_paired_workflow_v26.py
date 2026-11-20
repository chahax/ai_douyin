"""Independent pure v26 wiring checks; historical natives are never repaired.

No provider/client/claim is allowed here. Actual627 is request source only;
actual631 remains an unchanged rejection under the new native protocol.
"""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import ValidationError

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_drama_audit_contract_v11 as drama_sources
from src.content_factory import creative_paired_narrative_review_v1 as paired
from tests.test_creative_goal_context_workflow_v23 import offline as historical_fixture_clock
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/legal_scoped_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent workflow review cannot dispatch or construct provider clients")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def workflow():
    return importlib.import_module("src.content_factory.creative_goal_context_workflow_v26")


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def actual_case():
    return (
        load(ACTUAL / "INPUTS.json"),
        load(ACTUAL / "call_627_whole_plan_04.json")["output"],
        load(PROJECT / "config/creative_fresh_source_session_profile_v2.json"),
    )


def count_object(value, target):
    own = int(value == target)
    if isinstance(value, dict):
        return own + sum(count_object(child, target) for child in value.values())
    if isinstance(value, list):
        return own + sum(count_object(child, target) for child in value)
    return own


def count_text(value, text):
    if isinstance(value, str):
        return value.count(text)
    if isinstance(value, dict):
        return sum(count_text(child, text) for child in value.values())
    if isinstance(value, list):
        return sum(count_text(child, text) for child in value)
    return 0


def at_path(document, path):
    for key in path.split("."):
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def test_actual627_drama_wire_contains_exact_global_paths_and_one_native_one_r01():
    w = workflow()
    inputs, goal, profile = actual_case()
    original = deepcopy((inputs, goal, profile))
    prepared = w.prepare_goal_drama_audit_request(inputs, profile, goal)
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert count_object(payload, goal) == 1
    assert payload["native_goal_document"] == goal
    assert "native_goal_evidence_view" not in payload
    assert count_text(payload, inputs["reference_fulltext"]) == 1
    current = drama_sources.build_evidence_catalog(goal)
    indexed = payload["paired_narrative_comparison"]["comparison_targets"]["source_index"]
    assert set(indexed) == set(current)
    for ref, row in current.items():
        assert indexed[ref] == {"document_path": row["document_path"]}
        assert at_path(payload["native_goal_document"], indexed[ref]["document_path"]) == row["quote"]
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == w.digest(prepared["request"])
    assert prepared["manifest"]["payload_identity"] == w.contexts._measure(payload)
    assert prepared["manifest"]["structured_schema_sha256"] == w.digest(prepared["request"]["structured_schema"])
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    assert not prepared["production_dispatch_eligible"]
    assert (inputs, goal, profile) == original


def test_actual627_pair_context_and_entire_drama_request_context_stay_distinct():
    w = workflow()
    inputs, goal, profile = actual_case()
    prepared = w.prepare_goal_drama_audit_request(inputs, profile, goal)
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    expected_pair = paired.build_goal_delta(goal)
    assert prepared["drama_context_sha256"] == w.digest(payload)
    assert prepared["paired_context_sha256"] == expected_pair["manifest"]["context_sha256"]
    assert prepared["paired_context_sha256"] != prepared["drama_context_sha256"]
    schema = prepared["request"]["structured_schema"]
    assert schema["properties"]["audit_context_sha256"] == {"const": w.digest(payload)}
    assert schema["properties"]["paired_checks"]["properties"]["context_sha256"] == {
        "const": expected_pair["manifest"]["context_sha256"]}
    assert prepared["manifest"]["paired_context"] == expected_pair["manifest"]


def test_original631_cannot_be_used_as_new_paired_drama_or_modified_locally():
    w = workflow()
    inputs, goal, profile = actual_case()
    path = ACTUAL / "call_631_drama_audit_04.json"
    original_bytes_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = load(path)
    original = deepcopy(receipt)
    prepared = w.prepare_goal_drama_audit_request(inputs, profile, goal)
    decision = w.validate_goal_drama_audit(receipt["output"], goal,
        context_sha256=prepared["drama_context_sha256"], inputs=inputs)
    assert not decision["valid"] and not decision["accepted"]
    assert not decision["native_response_rewritten"]
    assert receipt == original
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_bytes_sha


def synthetic_case(scenario):
    # Author's factories construct a new explicitly labelled synthetic story;
    # actual627/631/634/635 are never used as fabricated positive reports.
    factories = importlib.import_module("tests.test_creative_goal_context_workflow_v26")
    inputs, goal, opening, ids, native = factories.synthetic_case(scenario)
    profile = factories.profile()
    bundle = factories.synthetic_bundle(inputs, goal)
    return inputs, goal, opening, ids, native, profile, bundle


def test_two_independently_accepted_bundles_cannot_change_a_bound_writer(causal_scenario):
    w = workflow()
    inputs, goal, opening, ids, native, profile, bundle_a = synthetic_case(causal_scenario)
    assert w.validate_goal_audit(bundle_a, goal, inputs=inputs)["accepted"]
    bundle_b = deepcopy(bundle_a)
    first = next(iter(bundle_b["native_drama_audit"]["paired_checks"]["records_by_target"].values()))
    first["comparison"] = "Independent alternate synthetic explanation; still a valid native comparison."
    assert w.validate_goal_audit(bundle_b, goal, inputs=inputs)["accepted"]
    assert w.digest(bundle_a) != w.digest(bundle_b)
    adapter = w.make_review_adapter(inputs, profile, bundle_a)
    with pytest.raises(ValueError):
        adapter.workflow.prepare_script_request(inputs, profile, goal, bundle_b, opening_setup=opening, **ids)


def test_bound_writer_rejects_changed_goal_or_injected_existing_snapshot(causal_scenario):
    w = workflow()
    inputs, goal, opening, ids, native, profile, bundle = synthetic_case(causal_scenario)
    adapter = w.make_review_adapter(inputs, profile, bundle)
    changed_goal = deepcopy(goal)
    changed_goal["whole_plan"]["premise"] += " Changed native identity."
    with pytest.raises((ValueError, ValidationError)):
        adapter.workflow.prepare_script_request(inputs, profile, changed_goal, bundle, opening_setup=opening, **ids)
    injected = deepcopy(inputs)
    injected["accepted_goal_comparison_snapshot"] = w.validate_goal_audit(bundle, goal, inputs=inputs)["accepted_goal_comparison_snapshot"]
    with pytest.raises(ValueError):
        adapter.workflow.prepare_script_request(injected, profile, goal, bundle, opening_setup=opening, **ids)


def test_driver_facade_binds_writer_and_semantic_review_to_one_exact_snapshot(causal_scenario):
    w = workflow()
    inputs, goal, opening, ids, native, profile, bundle = synthetic_case(causal_scenario)
    adapter = w.make_review_adapter(inputs, profile, bundle)
    assert adapter.workflow.prepare_script_request.__self__ is adapter
    assert adapter.workflow.prepare_full_review_part_request.__self__ is adapter
    authored = adapter.workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    writer_payload = json.loads(authored["request"]["messages"][1]["content"])
    reviewed = adapter.workflow.prepare_full_review_part_request(inputs, profile, native, authored["views"], "semantic")
    payload = json.loads(reviewed["request"]["messages"][1]["content"])
    snapshot = writer_payload["accepted_goal_comparison_snapshot"]
    assert payload["accepted_goal_comparison_snapshot"] == snapshot
    assert snapshot["bundle_sha256"] == w.digest(bundle)
    assert writer_payload["native_goal_document"] == payload["native_goal_document"] == goal
    assert payload["native_script_document"] == native
    compiled = w.validate_script_document(native, authored["views"], inputs["production_preferences"])["script"]
    assert compiled != native and w.digest(compiled) != w.digest(native)
    assert compiled["beats"] == native["beats"]
    assert payload["same_source_sha256"]["script_sha256"] == w.digest(compiled)
    assert reviewed["native_script_sha256"] == w.digest(native)
    assert reviewed["compiled_script_sha256"] == w.digest(compiled)
    expected_pair = paired.build_script_delta(native, goal, snapshot,
        native_comparison=bundle["native_drama_audit"]["paired_checks"],
        goal_context_sha256=snapshot["goal_context_sha256"], bundle_sha256=w.digest(bundle),
        compiled_script=compiled, request_same_source_sha256=payload["same_source_sha256"])
    assert reviewed["paired_context_sha256"] == expected_pair["manifest"]["context_sha256"]
    assert reviewed["context_sha256"] == w.digest(payload)
    assert reviewed["paired_context_sha256"] != reviewed["context_sha256"]
    assert count_text(writer_payload, inputs["reference_fulltext"]) == count_text(payload, inputs["reference_fulltext"]) == 1
    assert count_object(writer_payload, snapshot) == count_object(payload, snapshot) == 1
    assert reviewed["wire"] == expected_wire_request(reviewed["request"])
    assert not reviewed["dispatch_performed"] and not reviewed["production_dispatch_eligible"]

