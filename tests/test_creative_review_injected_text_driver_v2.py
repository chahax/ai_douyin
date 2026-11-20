"""Routing and native-review integration; synthetic judgments are not quality."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from scripts import creative_review_injected_text_driver_v2 as driver
from scripts import creative_fresh_source_session_v1 as shared
from src.content_factory import creative_full_review_protocol_v5 as reviews
from tests.test_creative_full_review_protocol_v5 import fixture as source_fixture, CONTEXTS


def session_at(tmp_path, monkeypatch, *, fault=None, force_valid_status=False):
    case, setup, originals = source_fixture()
    compiled, brief, plan, legal = case[:4]
    native = {k: deepcopy(v) for k, v in compiled.items() if k != "selected_candidate_id"}
    inputs = {"production_preferences": {}}
    calls, previous_inputs, source_documents = [], [], []
    views = {"brief": brief, "plan": plan}

    def script_request(current, *args, **kwargs):
        previous_inputs.append(deepcopy(current))
        return {"views": views}

    def review_request(*args):
        part = args[-1]
        return {"request": {"input_provenance": {"native_review_part_version":
            "wrong_protocol" if fault == "wrong_protocol" else reviews.VERSION}},
            "review_legal_context": legal, "part_context_sha256": CONTEXTS[part]}

    wf = SimpleNamespace(prepare_script_request=script_request, origin_ids=lambda i: {},
        prepare_full_review_part_request=review_request,
        validate_script_document=lambda value, *_: {"necessary_conditions_only": True, "script": compiled})

    class Session:
        version = "offline_review_injection_session/v1"
        profile = {}
        root = tmp_path

        def invoke(self, runtime, label, prepared, validator):
            calls.append(label)
            if label.startswith("complete_script"):
                output = deepcopy(native)
            else:
                part = label.split("_")[2]
                output = deepcopy(originals[part])
                if fault == "bad_schema" and part == "semantic":
                    output["schema"] = "unexpected"
                if fault == "unknown" and part == "semantic":
                    output["criteria"][next(iter(output["criteria"]))]["status"] = "unknown"
                if fault in ("script_fail", "plan_fail") and label == "full_review_semantic_01":
                    row = output["criteria"][next(iter(output["criteria"]))]
                    row.update(status="fail", required_revision="Complete native revision is required.")
                    output["revision_target"] = "script" if fault == "script_fail" else "plan"
            result = validator(output)
            source_documents.append(deepcopy(output))
            return {"ordinal": len(calls), "output": output, "validation": result,
                "status": "contract_valid" if result.get("valid", True) or force_valid_status else "contract_rejected"}

        def known(self, receipt, stage, *, require_valid=True):
            if require_valid and receipt["status"] != "contract_valid":
                raise shared.Halt("halt_contract_requires_pipeline_diagnosis")
            return receipt["output"]

        _review_stop = staticmethod(shared.Session._review_stop)

        def _diagnosis(self, receipt):
            return receipt["validation"]

        def execution_evidence(self, *args, **kwargs):
            return {"offline_stub_not_actual_sdk": True, "media_authorized": False}

        def state(self, runtime, status, **kwargs):
            return {"status": status, **kwargs}

    session = Session()
    session.wf = wf
    # Both exact v5 part validators and v5 bundle are exercised. Tracking the
    # explicitly supplied adapter proves the new driver does not select a
    # module-global validator in place of it.
    used = []
    def validated(*args, **kwargs):
        used.append(args[1])
        return reviews.validate_part(*args, **kwargs)
    injected = SimpleNamespace(VERSION=reviews.VERSION, validate_part=validated,
        build_review_bundle=reviews.build_review_bundle, validate_bundle=reviews.validate_bundle)
    return session, inputs, setup, native, calls, previous_inputs, source_documents, injected, used


def run(value):
    session, inputs, setup, *_ = value
    return driver.body(session, None, inputs, None, {}, setup, 1, reviews=value[-2])


def test_both_native_v5_parts_and_bundle_are_explicitly_injected(tmp_path, monkeypatch):
    value = session_at(tmp_path, monkeypatch)
    result = run(value)
    assert result["status"] == "text_ready_for_director"
    assert value[4] == ["complete_script_01", "full_review_semantic_01", "full_review_physical_01"]
    assert value[-1] == ["semantic", "physical"]
    handoff = json.loads((tmp_path / "TEXT_HANDOFF.json").read_text("utf-8"))
    assert handoff["review_protocol_version"] == reviews.VERSION
    assert handoff["native_script"] == value[3]
    assert handoff["native_script_sha256"] != handoff["compiled_script_sha256"]
    assert not handoff["media_authorized"] and not handoff["human_quality_approved"]
    assert not handoff["production_dispatch_eligible"] and not handoff["creative_quality_passed"]


@pytest.mark.parametrize("force_valid_status", [False, True])
def test_complete_review_schema_failure_never_authorizes_another_screenplay(tmp_path, monkeypatch, force_valid_status):
    value = session_at(tmp_path, monkeypatch, fault="bad_schema", force_valid_status=force_valid_status)
    with pytest.raises(shared.Halt, match="contract_requires_pipeline_diagnosis"):
        run(value)
    assert value[4] == ["complete_script_01", "full_review_semantic_01"]
    assert not (tmp_path / "TEXT_HANDOFF.json").exists()


@pytest.mark.parametrize("fault", ["unknown", "plan_fail"])
def test_uncertainty_and_plan_revision_stop_without_new_body(tmp_path, monkeypatch, fault):
    value = session_at(tmp_path, monkeypatch, fault=fault)
    with pytest.raises(shared.Halt):
        run(value)
    assert value[4] == ["complete_script_01", "full_review_semantic_01"]
    assert not (tmp_path / "TEXT_HANDOFF.json").exists()


def test_only_valid_content_failure_requests_a_complete_native_new_body(tmp_path, monkeypatch):
    value = session_at(tmp_path, monkeypatch, fault="script_fail")
    result = run(value)
    assert result["status"] == "text_ready_for_director"
    assert value[4] == ["complete_script_01", "full_review_semantic_01", "complete_script_02",
        "full_review_semantic_02", "full_review_physical_02"]
    assert value[5][1]["previous_complete_document"] == value[3]
    assert value[5][0] == value[1]
    assert value[5][1]["revision_diagnostics"]["complete_same_source_part_review"]["valid"] is True


def test_request_protocol_mismatch_stops_before_review_dispatch(tmp_path, monkeypatch):
    value = session_at(tmp_path, monkeypatch, fault="wrong_protocol")
    with pytest.raises(ValueError, match="protocol differ"):
        run(value)
    assert value[4] == ["complete_script_01"]


@pytest.mark.parametrize("decision", [None, {}, {"valid":False,"accepted":False},
    {"valid":True,"accepted":1}, {"valid":True,"accepted":True,"findings":[{}]},
    {"valid":True,"accepted":True,"uncertainties":[{}]},
    {"valid":True,"accepted":False},
    {"valid":True,"accepted":False,"findings":"failure","uncertainties":[]},
    {"valid":True,"accepted":False,"findings":[],"uncertainties":{}}])
def test_gate_cannot_treat_malformed_or_contradictory_review_as_content_failure(tmp_path, decision):
    session = SimpleNamespace(_review_stop=lambda *a: pytest.fail("invalid review reached content router"))
    with pytest.raises(shared.Halt, match="contract_requires_pipeline_diagnosis"):
        driver.review_gate(session, decision, tmp_path, "semantic", 1)


def test_empty_rejection_cannot_authorize_an_unexplained_new_draft(tmp_path):
    session = SimpleNamespace(_review_stop=lambda *a: None)
    with pytest.raises(shared.Halt, match="contract_requires_pipeline_diagnosis"):
        driver.review_gate(session, {"valid":True,"accepted":False,"findings":[],"uncertainties":[]},
            tmp_path, "semantic", 1)
