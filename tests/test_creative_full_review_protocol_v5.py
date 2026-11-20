"""Offline protocol witnesses; synthetic judgments never certify story quality."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_full_review_protocol_v5 as protocol
from src.content_factory import creative_goal_context_workflow_v25 as workflow
from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from tests.test_creative_split_full_review_contract_v4 import fixture as shape_fixture
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests.test_creative_split_full_review_contract_v1 import fixture as nonzero_shape_fixture

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/legal_scoped_text_session_20261015/round_01"
CONTEXTS = {"semantic": "1" * 64, "physical": "2" * 64}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("review protocol tests cannot contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def fixture(*, zero_plan=True):
    # Test-only synthetic rows constructed from the existing source fixture.
    # Never reads or converts any historical provider response.
    if zero_plan:
        case, opening, old_shapes = shape_fixture()
    else:
        case, opening, old_shapes = nonzero_shape_fixture(zero_plan=False)
        old_shapes["semantic"].update(synthetic_consistency(*case[:3]))
    reports = deepcopy(old_shapes)
    for part, native in reports.items():
        native["schema"] = protocol.VERSION
        if part != "semantic":
            continue
        for table, identifier, row in protocol._judgement_rows(native):
            old_refs = row.pop("source_refs", None)
            old_witnesses = row.pop("evidence", None)
            row["evidence"] = (old_refs if old_refs is not None else [row["source_ref"]] if table == "legal_claims"
                               else [next(iter(protocol.checks.reviews.base.base.prior.contract.evidence_catalog(case[0])))])
            row["counterevidence"] = []
            if table == "goal_checks":
                assert {item["source_ref"] for item in old_witnesses}.issubset(set(row["evidence"]))
    return case, opening, reports


def validate(case, opening, reports, part="semantic"):
    return protocol.validate_part(reports[part], part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=opening)


def validate_bundle(case, opening, reports):
    return protocol.validate_bundle(protocol.build_review_bundle(reports["semantic"], reports["physical"]),
        *case[:4], semantic_context_sha256=CONTEXTS["semantic"], physical_context_sha256=CONTEXTS["physical"], opening_setup=opening)


def actual_sources():
    load = lambda name: json.loads((ACTUAL / name).read_text("utf-8"))
    inputs = load("INPUTS.json")
    goal, opening, native_script = (load(name)["output"] for name in (
        "call_627_whole_plan_04.json", "call_633_opening_setup_02.json", "call_634_complete_script_01.json"))
    views = workflow.compile_native_views(goal, opening, **workflow.origin_ids(workflow._planning_authority_inputs(inputs)))
    compiled = workflow.validate_script_document(native_script, views, inputs["production_preferences"])["script"]
    profile = json.loads((PROJECT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return inputs, goal, opening, native_script, views, compiled, profile


def test_two_complete_native_v5_reports_preserve_all_duties_and_original_identity():
    case, opening, reports = fixture()
    before = deepcopy((case, opening, reports))
    for part in protocol.PART_TABLES:
        schema = protocol.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=opening)
        Draft202012Validator(schema).validate(reports[part])
        result = validate(case, opening, reports, part)
        assert result["valid"] and result["accepted"], result
        assert result["native_part_sha256"] == protocol.digest(reports[part])
        assert not result["compiler_projection_is_native_review"] and not result["native_response_rewritten"]
        assert result["native_version"] == protocol.VERSION
        assert protocol.part_table_contract(part, *case[:3])["coverage"] == protocol.checks.part_table_contract(part, *case[:3])["coverage"]
    result = validate_bundle(case, opening, reports)
    assert result["valid"] and result["accepted"] and result["status"] == "text_ready_for_director", result
    assert result["native_bundle_sha256"] == protocol.digest(protocol.build_review_bundle(reports["semantic"], reports["physical"]))
    assert result["review_origin"] == "two_native_same_source_v5_parts"
    assert not result["human_quality_approved"] and not result["creative_quality_passed"] and not result["old_budget_reset"]
    assert (case, opening, reports) == before


def test_goal_id_binding_expands_only_unchanged_exact_quote_for_old_quote_checker():
    case, opening, reports = fixture()
    native = reports["semantic"]
    before = deepcopy(native)
    projected = protocol._checking_projection(native, "semantic", case[0])
    entries = protocol.checks.reviews.base.base.prior.contract.evidence_catalog(case[0])
    for identifier, row in native["goal_checks"].items():
        assert projected["goal_checks"][identifier]["source_refs"] == row["evidence"]
        assert projected["goal_checks"][identifier]["evidence"] == [
            {"source_ref": ref, "quote": entries[ref]["quote"]} for ref in row["evidence"]]
    assert validate(case, opening, reports)["accepted"]
    assert native == before


def test_shared_definition_renaming_preserves_constraints_and_only_rewrites_actual_refs():
    before = {"type": "object", "properties": {"item": {"$ref": "#/$defs/a_long_definition"}},
        "required": ["item"], "additionalProperties": False,
        "$defs": {"a_long_definition": {"type": "string", "const": "#/$defs/a_long_definition"}}}
    after = protocol._compact_definition_names(before)
    assert after["$defs"]["d0"]["const"] == "#/$defs/a_long_definition"
    assert before["properties"]["item"]["$ref"] == "#/$defs/a_long_definition"
    for value in ({"item": "#/$defs/a_long_definition"}, {"item": "other"}, {}, {"item": 1}, {"item": "#/$defs/a_long_definition", "extra": 1}):
        assert Draft202012Validator(before).is_valid(value) == Draft202012Validator(after).is_valid(value)


def test_nonzero_plan_support_obligations_and_order_keep_native_coverage_and_plan_fail_route():
    case, opening, reports = fixture(zero_plan=False)
    assert reports["semantic"]["plan_support"] and reports["semantic"]["obligations"]
    assert validate_bundle(case, opening, reports)["accepted"]
    row = next(iter(reports["semantic"]["plan_support"].values()))
    row.update(status="fail", required_revision="完整新规划修复因果", counterevidence=list(row["evidence"]))
    reports["semantic"]["revision_target"] = "script"
    assert not validate(case, opening, reports)["valid"]
    reports["semantic"]["revision_target"] = "plan"
    result = validate_bundle(case, opening, reports)
    assert result["valid"] and not result["accepted"] and result["requires_new_goal_plan"], result
    assert result["status"] == "halt_full_review_requires_new_complete_goal"


@pytest.mark.parametrize("fault", [None, "quote", "own_evidence", "legal_ref", "counter_pass"])
def test_legal_claims_keep_exact_statement_quote_independent_law_and_own_E_binding(fault):
    case, opening, reports = fixture()
    entries = protocol.checks.reviews.base.base.prior.contract.evidence_catalog(case[0])
    ref = next(iter(reports["semantic"]["dialogue_checks"]))
    row = {"source_ref": ref, "quote": entries[ref]["quote"], "legal_fact_refs": ["L001"],
        "status": "pass", "reason": "Synthetic claim binding only, not legal semantic gold", "required_revision": "",
        "evidence": [ref], "counterevidence": []}
    reports["semantic"]["legal_claims"] = [row]
    if fault == "quote": row["quote"] = "not an original quote"
    elif fault == "own_evidence": row["evidence"] = [next(x for x in entries if x != ref)]
    elif fault == "legal_ref": row["legal_fact_refs"] = ["FOREIGN"]
    elif fault == "counter_pass": row["counterevidence"] = [ref]
    result = validate(case, opening, reports)
    assert result["valid"] == (fault is None), result


@pytest.mark.parametrize("table", ["fact_checks", "dialogue_checks", "criteria", "ending_checks", "goal_checks"])
@pytest.mark.parametrize("fault", ["old_source_refs", "unexpected", "object_witness", "target_ref", "foreign_ref", "empty_pass", "counter_pass", "missing_counter", "duplicate"])
def test_uniform_semantic_rows_are_closed_typed_and_require_resolved_actual_proof(table, fault):
    case, opening, reports = fixture()
    row = next(iter(reports["semantic"][table].values()))
    ref = row["evidence"][0]
    if fault == "old_source_refs": row["source_refs"] = [ref]
    elif fault == "unexpected": row["supporting_proof"] = [ref]
    elif fault == "object_witness": row["evidence"] = [{"source_ref": ref, "quote": "synthetic"}]
    elif fault == "target_ref": row["evidence"] = ["T:B1:script.event"]
    elif fault == "foreign_ref": row["evidence"] = ["E9999"]
    elif fault == "empty_pass": row["evidence"] = []
    elif fault == "counter_pass": row["counterevidence"] = [ref]
    elif fault == "missing_counter": row.pop("counterevidence")
    else: row["evidence"] = [ref, ref]
    assert not validate(case, opening, reports)["valid"]
    assert not validate_bundle(case, opening, reports)["accepted"]


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_native_counterproof_and_status_survive_the_checking_projection(status):
    case, opening, reports = fixture()
    identifier, row = next(iter(reports["semantic"]["fact_checks"].items()))
    row.update(status=status, counterevidence=list(row["evidence"]), required_revision="完整新稿修复事实" if status == "fail" else "")
    reports["semantic"]["revision_target"] = "script" if status == "fail" else "none"
    result = validate_bundle(case, opening, reports)
    assert result["valid"] and not result["accepted"], result
    assert result["status"] == ("needs_whole_revision" if status == "fail" else "halt_review_uncertain")
    found = next(item for item in result["findings" if status == "fail" else "uncertainties"] if item["item_id"] == identifier)
    assert found["finding"] == row and "source_refs" not in found["finding"]


@pytest.mark.parametrize("part", ["semantic", "physical"])
@pytest.mark.parametrize("field", [*protocol.SOURCE_HEADERS, "schema", "part", "context_sha256"])
def test_exact_native_source_and_protocol_identity_cannot_drift(part, field):
    case, opening, reports = fixture()
    reports[part][field] = "0" * 64
    assert not validate(case, opening, reports, part)["valid"]
    assert not validate_bundle(case, opening, reports)["accepted"]


@pytest.mark.parametrize("part,table", [("semantic", "fact_checks"), ("semantic", "dialogue_checks"),
    ("semantic", "beat_intent_checks"), ("semantic", "dialogue_role_checks"), ("physical", "action_checks")])
@pytest.mark.parametrize("fault", ["missing", "empty", "extra"])
def test_every_real_coverage_row_is_required_once_and_typed(part, table, fault):
    case, opening, reports = fixture()
    if fault == "missing": reports[part].pop(table)
    elif fault == "empty": reports[part][table] = {}
    else: reports[part][table]["FOREIGN"] = deepcopy(next(iter(reports[part][table].values())))
    assert not validate(case, opening, reports, part)["valid"]


def test_dialogue_roles_fragments_and_physical_initial_quote_checks_remain_in_force():
    case, opening, reports = fixture()
    row = next(iter(reports["semantic"]["dialogue_role_checks"].values()))
    row["propositions"][0]["quote"] = "not in the original dialogue"
    assert not validate(case, opening, reports)["valid"]
    case, opening, reports = fixture()
    physical = next(iter(reports["physical"]["action_checks"].values()))
    prop = case[1]["initial_state"]["prop_states"][0]
    physical["preconditions"] = [{"entity_id": prop["id"], "state_key": "holder_character_id",
        "expected_value": prop["holder_character_id"], "actual_value": prop["holder_character_id"],
        "established_by": "initial:prop:" + prop["id"], "quote": "not in the frozen initial source"}]
    assert not validate(case, opening, reports, "physical")["valid"]


def test_actual_635_is_still_rejected_without_cleaning_under_old_and_new_protocols():
    before = hashlib.sha256((ACTUAL / "call_635_full_review_semantic_01.json").read_bytes()).hexdigest()
    receipt = json.loads((ACTUAL / "call_635_full_review_semantic_01.json").read_text("utf-8"))
    old_errors = list(Draft202012Validator(receipt["request"]["structured_schema"]).iter_errors(receipt["output"]))
    assert len(old_errors) == 9 and all(error.validator == "additionalProperties" for error in old_errors)
    inputs, goal, opening, native_script, views, script, profile = actual_sources()
    prepared = protocol.prepare_full_review_part_request(inputs, profile, native_script, views, "semantic")
    new = protocol.validate_part(receipt["output"], "semantic", script, views["brief"], views["plan"], prepared["review_legal_context"],
        context_sha256=prepared["context_sha256"], goal_contract=goal, opening_setup=opening)
    assert not new["valid"] and not new["accepted"]
    rejected = protocol.validate_received_part(receipt, prepared, script, views["brief"], views["plan"], prepared["review_legal_context"],
        goal_contract=goal, opening_setup=opening)
    assert rejected["findings"][0]["code"] == "FULL_REVIEW_PROTOCOL_RECEIPT_UNSETTLED"
    assert before == hashlib.sha256((ACTUAL / "call_635_full_review_semantic_01.json").read_bytes()).hexdigest()


def test_actual_native627_633_634_prepare_exact_future_two_part_request_without_duplication_or_dispatch():
    inputs, goal, opening, native_script, views, script, profile = actual_sources()
    before = deepcopy((inputs, goal, opening, native_script, views, profile))
    for part in protocol.PART_TABLES:
        prepared = protocol.prepare_full_review_part_request(inputs, profile, native_script, views, part)
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        assert payload["native_goal_document"] == goal and payload["native_opening_setup_document"] == opening
        assert payload["native_script_document"] == native_script
        assert prepared["native_script_sha256"] == protocol.digest(native_script)
        assert prepared["compiled_script_sha256"] == protocol.digest(script)
        assert prepared["same_source_sha256"]["script_sha256"] == protocol.digest(script)
        assert native_script != script and "selected_candidate_id" not in native_script and "selected_candidate_id" in script
        assert prepared["wire"] == expected_wire_request(prepared["request"])
        assert prepared["request_sha256"] == protocol.digest(prepared["request"])
        assert prepared["context_sha256"] == protocol.digest(payload)
        assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == protocol.digest(prepared["manifest"])
        assert prepared["manifest"]["structured_schema_sha256"] == protocol.digest(prepared["request"]["structured_schema"])
        assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"] and not prepared["production_dispatch_eligible"]
        assert not prepared["server_schema_guarantee"] and not prepared["manifest"]["source_text_omitted_or_truncated"]
        assert "part_coverage_catalog" not in payload and "compiled_initial_atoms" not in payload and "initial_evidence_catalog" not in payload
        assert payload["review_table_contract"]["coverage"] == protocol.part_table_contract(part, script, views["brief"], views["plan"])["coverage"]
        assert prepared["request"]["messages"][0]["content"] == (protocol.SEMANTIC_RULE if part == "semantic" else protocol.PHYSICAL_RULE)
        if part == "semantic":
            assert payload["reference_fulltext"] == inputs["reference_fulltext"]
            assert prepared["manifest"]["reference_proof"]["payload_occurrences"] == 1
            assert "actual_steps" not in payload["consistency_evidence_catalog"]
    assert (inputs, goal, opening, native_script, views, profile) == before


def synthetic_receipt(native):
    request = {"model": "offline-only", "role": "director", "parameters": {"temperature": 1}, "messages": [], "structured_schema": {}, "input_provenance": {}}
    prepared = {"request": request, "request_sha256": protocol.digest(request), "sdk_max_retries": 0,
        "part": "semantic", "context_sha256": CONTEXTS["semantic"],
        "wire": {"tools": [{"function": {"name": "submit_creative_json"}}]}}
    usage = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}
    receipt = {"request": deepcopy(request), "request_sha256": protocol.digest(request), "output": deepcopy(native),
        "status": "response_received", "automatic_retry": False, "failure": None,
        "response_metadata": {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls",
            "output_mode": "tool_call", "requested_model": "offline-only", "response_model": "offline-only",
            "response_id": "offline-response", "role": "director", **usage},
        "response_payload": {"id": "offline-response", "model": "offline-only", "usage": deepcopy(usage), "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"type": "function", "function": {"name": "submit_creative_json", "arguments": json.dumps(native)}}]}}]}}
    return receipt, prepared


@pytest.mark.parametrize("fault", [None, "http", "truncated", "body_incomplete", "unknown_usage", "bool_usage", "bool_payload_usage", "usage_sum", "missing_tool", "wrong_tool", "two_tools", "malformed_json", "duplicate_json", "nonfinite_json", "output_changed", "request_changed", "request_bool", "request_sha", "sdk_retry", "sdk_bool", "extra_field", "receipt_unknown", "receipt_failure", "receipt_retry", "wrong_response_model", "wrong_requested_model", "wrong_payload_model", "wrong_response_id", "wrong_role"])
def test_known_exact_envelope_only_never_repairs_retries_dispatches_or_changes_usage(fault):
    case, opening, reports = fixture()
    receipt, prepared = synthetic_receipt(reports["semantic"])
    if fault == "http": receipt["response_metadata"]["http_status_code"] = 502
    elif fault == "truncated": receipt["response_metadata"]["finish_reason"] = "length"
    elif fault == "body_incomplete": receipt["response_metadata"]["response_body_complete"] = False
    elif fault == "unknown_usage": receipt["response_metadata"]["total_tokens"] = None
    elif fault == "bool_usage": receipt["response_metadata"]["prompt_tokens"] = True
    elif fault == "bool_payload_usage":
        receipt["response_metadata"]["prompt_tokens"] = 1
        receipt["response_metadata"]["total_tokens"] = 6
        receipt["response_payload"]["usage"]["prompt_tokens"] = True
        receipt["response_payload"]["usage"]["total_tokens"] = 6
    elif fault == "usage_sum":
        receipt["response_metadata"]["total_tokens"] = receipt["response_payload"]["usage"]["total_tokens"] = 13
    elif fault == "missing_tool": receipt["response_payload"]["choices"][0]["message"]["tool_calls"] = []
    elif fault == "wrong_tool": receipt["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "foreign_tool"
    elif fault == "two_tools": receipt["response_payload"]["choices"][0]["message"]["tool_calls"] *= 2
    elif fault == "malformed_json": receipt["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{"
    elif fault == "duplicate_json":
        raw = json.dumps(receipt["output"])
        receipt["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"schema":"wrong",' + raw[1:]
    elif fault == "nonfinite_json": receipt["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"bad":NaN}'
    elif fault == "output_changed": receipt["output"]["schema"] = "foreign"
    elif fault == "request_changed": receipt["request"]["model"] = "foreign"
    elif fault == "request_bool": receipt["request"]["parameters"]["temperature"] = True
    elif fault == "request_sha": receipt["request_sha256"] = "0" * 64
    elif fault == "sdk_retry": prepared["sdk_max_retries"] = 1
    elif fault == "sdk_bool": prepared["sdk_max_retries"] = False
    elif fault == "extra_field":
        receipt["output"]["extra"] = "forbidden"
        receipt["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(receipt["output"])
    elif fault == "receipt_unknown": receipt["status"] = "result_unknown"
    elif fault == "receipt_failure": receipt["failure"] = {"code": "TRANSPORT_UNKNOWN"}
    elif fault == "receipt_retry": receipt["automatic_retry"] = True
    elif fault == "wrong_response_model": receipt["response_metadata"]["response_model"] = "foreign"
    elif fault == "wrong_requested_model": receipt["response_metadata"]["requested_model"] = "foreign"
    elif fault == "wrong_payload_model": receipt["response_payload"]["model"] = "foreign"
    elif fault == "wrong_response_id": receipt["response_payload"]["id"] = "foreign"
    elif fault == "wrong_role": receipt["response_metadata"]["role"] = "foreign"
    before = deepcopy((receipt, prepared))
    result = protocol.validate_received_part(receipt, prepared, *case[:4], opening_setup=opening)
    assert result["valid"] == (fault is None), result
    assert result["accepted"] == (fault is None)
    assert not result["automatic_retry"] and not result["old_budget_reset"]
    assert (receipt, prepared) == before
