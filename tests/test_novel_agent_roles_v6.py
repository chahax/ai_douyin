"""Lossless native-string compatibility without inventing world-state facts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from src.content_factory import novel_agent_roles_v5 as old
from src.content_factory import novel_agent_roles_v6 as roles
from src.content_factory.novel_scene_logic_v4 import analyze_scene_ledger

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_novel_agent_roles_v5.py")))


def parse(raw):
    return roles.parse_review_bundle(json.dumps(raw, ensure_ascii=False), source_binding="s", draft_binding="d",
                                    native_response_ref="native-sha", artifact_prefix="review-002")


def test_native_strings_are_preserved_exactly_as_unknown_not_physical_facts():
    raw = HELPERS["raw_bundle"]()
    raw["scene_ledger"]["events"][0]["before"] = ["他站着，另一只手可能拿着信。", "“照着这句话站起来”只是纸上的字。"]
    original = deepcopy(raw)
    result = parse(raw)
    values = result["scene_ledger"]["events"][0]["before"]
    assert [row["value"] for row in values] == raw["scene_ledger"]["events"][0]["before"]
    assert all(row["certainty"] == "unknown" and row["qualifiers"]["not_physical_fact"] for row in values)
    assert all(row["predicate"] == "native_state_description" for row in values)
    assert result["scene_ledger"]["state_projection"]["physical_facts_inferred"] is False
    assert raw == original
    assert result["review"]["native_verdict"] == raw["full_review"]["native_verdict"]


def test_old_v5_rejection_is_not_changed_and_typed_states_remain_exact():
    raw = HELPERS["raw_bundle"]()
    typed = deepcopy(raw["scene_ledger"]["events"][0]["after"])
    raw["scene_ledger"]["events"][1]["before"] = ["自然语言状态"]
    with pytest.raises(ValueError, match="Auxiliary review contract invalid"):
        old.parse_review_bundle(json.dumps(raw), source_binding="s", draft_binding="d",
                                native_response_ref="native-sha", artifact_prefix="review-002")
    result = parse(raw)
    assert result["scene_ledger"]["events"][0]["after"] == typed
    assert old.VERSION.endswith("/v5")


def test_typed_physical_contradiction_still_produces_candidate():
    raw = HELPERS["raw_bundle"]()
    events = raw["scene_ledger"]["events"]
    events[1].update(relation="new_event", referent_event_id=None, narrative_layer="performance")
    events[1]["before"][0]["value"] = "sitting"
    result = parse(raw)
    assert len(analyze_scene_ledger(result["scene_ledger"])["candidates"]) == 1


@pytest.mark.parametrize("value", [None, 1, True, ""])
def test_unsupported_state_values_are_not_guessed_into_valid_facts(value):
    raw = HELPERS["raw_bundle"]()
    raw["scene_ledger"]["events"][0]["before"] = [value]
    with pytest.raises(ValueError):
        parse(raw)


@pytest.mark.parametrize("change", ["missing_dimension", "not_whole", "revise"])
def test_state_projection_never_fills_missing_review_coverage_or_changes_verdict(change):
    raw = HELPERS["raw_bundle"]()
    raw["scene_ledger"]["events"][0]["before"] = ["他在桌旁。"]
    if change == "missing_dimension":
        raw["full_review"]["checks"].pop()
    elif change == "not_whole":
        raw["full_review"]["whole_text_reviewed"] = False
    else:
        raw["full_review"]["native_verdict"] = "revise"
        assert parse(raw)["review"]["native_verdict"] == "revise"
        return
    with pytest.raises(ValueError):
        parse(raw)


def test_actual_bound_native_files_are_still_required_for_v6_proof(tmp_path):
    data = HELPERS["native_case"](tmp_path)
    text = data["response"]["response_text"]
    data["review"] = roles.parse_review_bundle(text, source_binding=data["source"]["binding_id"],
        draft_binding=hashlib.sha256(data["screenplay"].encode()).hexdigest(),
        native_response_ref=data["response_binding"]["sha256"], artifact_prefix="review-002")["review"]
    assert roles.verify_review_evidence(**data)["native_verdict"] == "pass"
    del data["response_binding"]
    with pytest.raises(ValueError):
        roles.verify_review_evidence(**data)
