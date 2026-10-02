"""Compact JSON review must preserve complete inputs and the original validator."""
from copy import deepcopy
import json

import pytest

from scripts import review_linear_script_probe_v6 as compact
from scripts import revise_linear_script_probe_v5 as prior
from src.content_factory.creative_review_v3 import CHECKS
from src.content_factory.creative_review_v6 import validate_review_v6
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_linear_script_probe_v3 import runtime
from tests.test_linear_script_probe_v5 import install_calls


def install_fourteen_beat_review(runtime):
    install_calls(runtime)
    original = runtime.calls["linear_draft_v5"]["output"]
    expanded = deepcopy(original)
    expanded["beats"] = []
    for index in range(14):
        beat = deepcopy(original["beats"][index % len(original["beats"])])
        beat["id"] = "B" + str(index + 1)
        expanded["beats"].append(beat)
    runtime.calls["linear_draft_v5"]["output"] = expanded
    ctx = prior.context()
    coverage = []
    for index, beat in enumerate(ctx["script"]["beats"]):
        checks = {}
        for name in CHECKS:
            not_applicable = name == "first_frame" or (name == "dialogue_timing" and not beat["dialogue"])
            checks[name] = {"status": "not_applicable" if not_applicable else "pass",
                "reason": "Script scope only" if not_applicable else "Offline evidence fixture",
                "evidence_refs": [] if not_applicable else [{
                    "path": f"script.beats.{index}.before", "quote": beat["before"]}],
                "issue_ids": []}
        coverage.append({"id": beat["id"], "checks": checks})
    review = {"story_preserved": True, "issues": [], "suggestions": [],
              "calibration_focus": [], "coverage": coverage}
    validate_review_v6(review, ctx)
    runtime.calls["linear_script_review_v6"] = {"label": "linear_script_review_v6",
        "ordinal": 49, "status": "contract_valid", "output": review}
    return ctx, review


def test_compact_json_keeps_all_actions_dialogues_references_and_11000_output(runtime):
    expected, _ = install_fourteen_beat_review(runtime)
    before = deepcopy(runtime.calls)
    ctx, request = compact.wire()
    assert ctx == expected
    assert json.loads(request["messages"][1]["content"]) == expected
    assert request["messages"][1]["content"] == json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
    assert request["max_tokens"] == 11000
    assert len(ctx["script"]["beats"]) * len(CHECKS) == 84
    assert ctx["reference_pack"] == runtime.context["reference_pack"]
    assert compact.validate_review_v6 is validate_review_v6
    assert runtime.calls == before
    assert runtime.wires == []


def test_zero_issue_complete_review_uses_real_validator_and_never_auto_approves(runtime):
    ctx, value = install_fourteen_beat_review(runtime)
    result = compact.run()
    assert result["validation"]["validation_contract"] == "unchanged evidence_review_v6"
    assert result["validation"]["semantic_approval"] is False
    assert result["validation"]["requires_assistant_evidence_verification"] is True
    assert sum(len(row["checks"]) for row in value["coverage"]) == 84
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v6.json").exists()
    assert len(runtime.wires) == 1
    assert json.loads(runtime.wires[0]["messages"][1]["content"]) == ctx


@pytest.mark.parametrize("defect", ["missing_beat", "missing_check", "missing_own_evidence", "skip_required"])
def test_real_original_validator_rejects_incomplete_or_skipped_review(runtime, defect):
    _, value = install_fourteen_beat_review(runtime)
    if defect == "missing_beat":
        value["coverage"].pop()
    elif defect == "missing_check":
        value["coverage"][0]["checks"].pop("assets")
    elif defect == "missing_own_evidence":
        value["coverage"][0]["checks"]["timing"]["evidence_refs"] = []
    else:
        value["coverage"][0]["checks"]["requirements"]["status"] = "not_applicable"
    with pytest.raises(CreativeContractError):
        compact.run()
    assert not (runtime.root / "LINEAR_SCRIPT_REVIEW_DECISION_v6.json").exists()
