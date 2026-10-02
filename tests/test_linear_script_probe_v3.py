"""Offline protection checks for the frozen linear operator; no model transport."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_linear_script_probe_v3 as operator
from tests.test_creative_linear_script_v2 import raw as linear_fixture


PROJECT = Path(__file__).resolve().parents[1]
REAL_CONTEXT = PROJECT / "data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/CONTEXT.json"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "operator"
    root.mkdir()
    context = json.loads(REAL_CONTEXT.read_text(encoding="utf-8"))
    monkeypatch.setattr(operator.base, "ROOT", root)
    monkeypatch.setattr(operator.base, "LEDGER", root / "CALL_LEDGER.json")
    monkeypatch.setattr(operator, "BINDING", root / "LINEAR_OPERATOR_BINDING_v3.json")
    operator.base.write(root / "ORIGINAL_CONTEXT.json", context, True)
    calls = {
        "linear_draft_v3": {"label": "linear_draft_v3", "ordinal": 46,
            "status": "contract_valid", "output": linear_fixture()},
        "linear_script_review_v3": {"label": "linear_script_review_v3", "ordinal": 47,
            "status": "contract_valid", "output": {"issues": [], "story_preserved": True}},
    }
    selected = []
    def get_call(label):
        selected.append(label)
        receipt = calls[label]
        if receipt["status"] != "contract_valid":
            raise RuntimeError("upstream not validated " + label)
        return deepcopy(receipt)
    monkeypatch.setattr(operator.base, "get_call", get_call)
    monkeypatch.setattr(operator.base, "request",
        lambda role, messages, schema, maximum: {
            "role": role, "messages": messages, "structured_schema": schema,
            "max_tokens": maximum})
    wires = []
    def dispatch(label, wire, validator, retain_review_tokens=0):
        wires.append(deepcopy(wire))
        value = calls[label]["output"]
        return {"label": label, "status": "contract_valid",
                "output": deepcopy(value), "validation": validator(deepcopy(value))}
    monkeypatch.setattr(operator.base, "dispatch", dispatch)
    return SimpleNamespace(root=root, context=context, calls=calls,
                           selected=selected, wires=wires)


def test_failed_linear_output_is_not_converted_or_adopted(runtime):
    runtime.calls["linear_draft_v3"]["status"] = "contract_rejected"
    raw_before = deepcopy(runtime.calls["linear_draft_v3"]["output"])
    with pytest.raises(RuntimeError, match="upstream not validated linear_draft_v3"):
        operator.context()
    assert not (runtime.root / "DERIVED_LINEAR_SCRIPT_v3.json").exists()
    assert runtime.calls["linear_draft_v3"]["output"] == raw_before
    assert runtime.selected == ["linear_draft_v3"]
    assert runtime.wires == []


def test_derived_artifact_is_recomputed_from_unchanged_raw_and_tampering_is_blocked(runtime):
    ctx = operator.context()
    raw_before = deepcopy(runtime.calls["linear_draft_v3"]["output"])
    assert ctx["raw_linear_script"] == raw_before
    artifact_path = runtime.root / "DERIVED_LINEAR_SCRIPT_v3.json"
    artifact = operator.base.read(artifact_path)
    assert artifact["script"] == operator.derive(raw_before)
    artifact["script"]["beats"][0]["after"] = "unbound invented action"
    operator.base.write(artifact_path, artifact)
    with pytest.raises(RuntimeError, match="derived script changed"):
        operator.context()
    assert runtime.calls["linear_draft_v3"]["output"] == raw_before
    assert runtime.wires == []


def test_operator_source_snapshot_tampering_blocks_context(runtime):
    operator.binding()
    snapshot = (runtime.root / "operator_sources" / operator.VERSION
                / Path(operator.linear.__file__).name)
    snapshot.write_text("unbound adapter snapshot", encoding="utf-8")
    with pytest.raises(RuntimeError, match="linear source snapshot changed"):
        operator.context()
    assert runtime.wires == []


def test_zero_issue_review_preserves_reference_and_raw_but_does_not_approve_automatically(runtime, monkeypatch):
    monkeypatch.setattr(operator, "validate_review_v6", lambda value, ctx: None)
    record = operator.review()
    assert record["validation"]["semantic_approval"] is False
    assert record["validation"]["requires_assistant_evidence_verification"] is True
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v3.json").exists()
    assert len(runtime.wires) == 1
    wire = runtime.wires[0]
    submitted = json.loads(wire["messages"][1]["content"])
    assert submitted["reference_pack"] == runtime.context["reference_pack"]
    assert submitted["raw_linear_script"] == runtime.calls["linear_draft_v3"]["output"]
    assert submitted["script"] == operator.derive(submitted["raw_linear_script"])
    assert "raw_linear_script.beats.N.steps" in wire["messages"][0]["content"]
    assert "实际图片已生成" in wire["messages"][0]["content"]


def test_unresolved_review_blocks_explicit_approval_and_does_not_write_decision(runtime):
    runtime.calls["linear_script_review_v3"]["output"] = {
        "story_preserved": True, "issues": [{"id": "still_unresolved"}]}
    with pytest.raises(RuntimeError, match="unresolved required issues"):
        operator.decision(True, [{"checked": "full source text"}])
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v3.json").exists()
    assert runtime.wires == []

def test_v4_canonical_review_retains_reference_and_raw_binding_without_auto_approval(runtime, monkeypatch):
    from scripts import review_linear_script_probe_v4 as review_v4
    runtime.calls["linear_script_review_v4"] = {
        "label": "linear_script_review_v4", "ordinal": 47,
        "status": "contract_valid", "output": {"issues": [], "story_preserved": True}}
    monkeypatch.setattr(review_v4, "validate_review_v6", lambda value, ctx: None)
    record = review_v4.run()
    assert record["validation"]["semantic_approval"] is False
    assert record["validation"]["requires_assistant_evidence_verification"] is True
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v4.json").exists()
    submitted = json.loads(runtime.wires[0]["messages"][1]["content"])
    raw = runtime.calls["linear_draft_v3"]["output"]
    assert "raw_linear_script" not in submitted
    assert submitted["script"] == operator.derive(raw)
    assert submitted["reference_pack"] == runtime.context["reference_pack"]
    assert submitted["script_revision_source"]["raw_sha256"] == operator.base.digest(raw)
    assert runtime.wires[0]["max_tokens"] == 11000
    assert runtime.wires[0]["operator_binding"] == review_v4.binding()


@pytest.mark.parametrize("evidence", [[], None, {}])
def test_v4_explicit_decision_requires_nonempty_evidence_before_any_source_access(runtime, evidence):
    from scripts import review_linear_script_probe_v4 as review_v4
    with pytest.raises(RuntimeError, match="requires explicit verified evidence"):
        review_v4.decision(True, evidence)
    assert runtime.selected == []
    assert runtime.wires == []
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v4.json").exists()
