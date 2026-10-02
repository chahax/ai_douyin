"""Offline guards for complete v5 rewrites and canonical full reviews."""
from copy import deepcopy
import json

import pytest

from scripts import revise_linear_script_probe_v5 as revision
from scripts import run_linear_script_probe_v3 as original_operator
from tests.test_linear_script_probe_v3 import runtime


def install_calls(runtime):
    runtime.calls["linear_script_review_v4"] = {
        "label": "linear_script_review_v4", "ordinal": 47, "status": "contract_valid",
        "output": {"story_preserved": False, "issues": [{
            "id": "I01", "rule": "visible repeated past help", "evidence": "original evidence",
            "proposal": "proposal is not rewritten content"}]}}
    runtime.calls["linear_draft_v5"] = {
        "label": "linear_draft_v5", "ordinal": 48, "status": "contract_valid",
        "output": deepcopy(runtime.calls["linear_draft_v3"]["output"])}
    runtime.calls["linear_script_review_v5"] = {
        "label": "linear_script_review_v5", "ordinal": 49, "status": "contract_valid",
        "output": {"story_preserved": True, "issues": []}}


def test_writer_projection_preserves_complete_bound_sources_and_previous_raw_once(runtime):
    install_calls(runtime)
    before = deepcopy(runtime.calls)
    wire = revision.draft_wire()
    payload = json.loads(wire["messages"][1]["content"])
    expected = deepcopy(runtime.context)
    expected.pop("script")
    assert payload["context"] == expected
    assert payload["previous_script"] == runtime.calls["linear_draft_v3"]["output"]
    assert payload["revision_mode"] == "complete_new_script"
    assert payload["issues"]["previous_review_issues"] == [{
        "id": "I01", "rule": "visible repeated past help", "evidence": "original evidence"}]
    assert payload["issues"]["assistant_verified_disposition"] == revision.DISPOSITION
    assert wire["input_provenance"]["reference_pack_sha256"] == revision.base.digest(expected["reference_pack"])
    assert runtime.calls == before
    assert runtime.wires == []


def test_review_projection_omits_only_duplicate_screenplay_and_keeps_complete_actions(runtime):
    install_calls(runtime)
    raw = deepcopy(runtime.calls["linear_draft_v5"]["output"])
    expected = original_operator.derive(raw)
    expected.pop("screenplay_markdown")
    context, wire = revision.review_wire()
    submitted = json.loads(wire["messages"][1]["content"])
    assert submitted == context
    assert submitted["script"] == expected
    assert {key: submitted[key] for key in runtime.context if key != "script"} == {
        key: value for key, value in runtime.context.items() if key != "script"}
    assert submitted["script_revision_source"]["raw_sha256"] == revision.base.digest(raw)
    assert wire["input_provenance"]["projection"].endswith("screenplay_markdown only")
    assert runtime.calls["linear_draft_v5"]["output"] == raw
    assert runtime.wires == []


def test_v5_derived_artifact_tampering_is_rejected_without_dispatch(runtime):
    install_calls(runtime)
    revision.context()
    path = runtime.root / "DERIVED_LINEAR_SCRIPT_v5.json"
    artifact = revision.base.read(path)
    artifact["script"]["beats"][0]["dialogue"][0]["text"] = "manually inserted line"
    revision.base.write(path, artifact)
    with pytest.raises(RuntimeError, match="v5 derived script changed"):
        revision.review_wire()
    assert runtime.wires == []


def test_unresolved_current_review_cannot_be_approved_or_merged_with_previous_pass(runtime):
    install_calls(runtime)
    runtime.calls["linear_script_review_v5"]["output"]["issues"] = [{"id": "current_unresolved"}]
    with pytest.raises(RuntimeError, match="unresolved required issues"):
        revision.decision(True, [{"checked": "complete new script"}])
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v5.json").exists()
    assert runtime.wires == []


def test_failed_v5_raw_cannot_fall_back_to_valid_v3_script(runtime):
    install_calls(runtime)
    runtime.calls["linear_draft_v5"]["status"] = "contract_rejected"
    with pytest.raises(RuntimeError, match="upstream not validated linear_draft_v5"):
        revision.context()
    assert runtime.selected == ["linear_draft_v5"]
    assert not (runtime.root / "DERIVED_LINEAR_SCRIPT_v5.json").exists()
    assert runtime.wires == []
