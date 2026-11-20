"""Lossless identity and malformed-view tests; provider calls are prohibited."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
from src.content_factory import creative_goal_drama_audit_contract_v10 as drama
from src.content_factory import creative_goal_evidence_view_v1 as evidence

PROJECT = Path(__file__).resolve().parents[1]
TRIALS = PROJECT / "data/production_trials/goal_context_text_production_20261013"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("lossless evidence representation may not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


@pytest.fixture
def original():
    # Representation fixture, not an accepted creative planning contract.
    return {"contract_version": "synthetic_original", "untouched_metadata": {"empty": "", "number": 2,
        "boolean": True, "null": None, "whitespace": "  "},
        "claims": [{"id": "c1", "text": "她写完以后才照相。", "kind": "creative_choice"}],
        "whole_plan": {"characters": [{"id": "a", "name": "她", "profile": {"gender": "女"}}],
            "beats": [{"id": "b1", "scene_id": "room", "event": "他把笔横放好。",
                "stimulus": "她看到他松开手。", "claim_refs": ["c1"], "actors": ["a"],
                "steps": ["她按下手机快门。", "她把手机收起。"]}],
            "ending": {"event": "纸留在桌上。", "claim_refs": ["c1"]},
            "escaped_keys": {"slash/key~原": "斜杠和波浪号也是原文键。"},
            "empty": "", "space": " \t ", "numeric": 3.25}}


def locate(document, path):
    parent, key = evidence._location(document, path)
    return parent[key]


def first_ref(view):
    return next(ref for ref in view["evidence_catalog"] if ref.startswith("G"))


def test_every_catalog_string_once_exact_paths_and_complete_object_round_trip(original):
    before = deepcopy(original)
    view = evidence.build_lossless_goal_evidence_view(original)
    assert original == before
    assert view["evidence_catalog"] == drama.build_evidence_catalog(original)
    assert view["native_goal_sha256"] == drama.digest(original)
    for ref, row in view["evidence_catalog"].items():
        assert locate(original, row["document_path"]) == row["quote"]
        assert locate(view["goal_structure"], row["document_path"]) == {evidence.REFERENCE_KEY: ref}
    rebuilt = evidence.reconstruct_goal(view)
    assert rebuilt == original and evidence.digest(rebuilt) == evidence.digest(original)
    assert evidence.validate_lossless_goal_evidence_view(view, original)["external_native_source_verified"]
    assert view["goal_structure"]["untouched_metadata"] == original["untouched_metadata"]
    assert view["goal_structure"]["whole_plan"]["beats"][0]["claim_refs"] == ["c1"]
    assert view["goal_structure"]["whole_plan"]["empty"] == ""
    assert view["goal_structure"]["whole_plan"]["space"] == " \t "
    assert view == evidence.build_lossless_goal_evidence_view(deepcopy(original))
    view_before = deepcopy(view)
    rebuilt["whole_plan"]["beats"][0]["event"] = "调用者修改结果"
    assert view == view_before and original == before


@pytest.mark.parametrize("mutation", ["schema", "extra_top_field", "source_sha", "source_sha_type",
    "catalog_missing", "catalog_extra", "duplicate_path", "wrong_path", "escaped_index", "wrong_quote",
    "wrong_quote_type", "wrong_catalog_fields", "wrong_reference_type", "unknown_reference",
    "duplicate_reference", "typed_reference_extra_fields", "typed_reference_missing", "uncovered_added_string",
    "raw_other_field_change", "structure_type", "catalog_type", "renumber_ref"])
def test_malformed_or_changed_view_is_rejected_without_mutating_original(original, mutation):
    view = evidence.build_lossless_goal_evidence_view(original)
    ref = first_ref(view)
    row = view["evidence_catalog"][ref]
    parent, key = evidence._location(view["goal_structure"], row["document_path"])
    if mutation == "schema": view["schema"] = "older/version"
    elif mutation == "extra_top_field": view["extra"] = "unbound"
    elif mutation == "source_sha": view["native_goal_sha256"] = "0" * 64
    elif mutation == "source_sha_type": view["native_goal_sha256"] = 123
    elif mutation == "catalog_missing": del view["evidence_catalog"][ref]
    elif mutation == "catalog_extra": view["evidence_catalog"]["G999"] = {"document_path": "whole_plan.extra", "quote": "额外行"}
    elif mutation == "duplicate_path": view["evidence_catalog"]["G999"] = deepcopy(row)
    elif mutation == "wrong_path": row["document_path"] = "whole_plan.beats.0.id"
    elif mutation == "escaped_index": row["document_path"] = "whole_plan.beats.00.event"
    elif mutation == "wrong_quote": row["quote"] += "她变成了他"
    elif mutation == "wrong_quote_type": row["quote"] = {"text": row["quote"]}
    elif mutation == "wrong_catalog_fields": row["quote_summary"] = "不允许缩写"
    elif mutation == "wrong_reference_type": parent[key][evidence.REFERENCE_KEY] = [ref]
    elif mutation == "unknown_reference": parent[key][evidence.REFERENCE_KEY] = "G999"
    elif mutation == "duplicate_reference": view["goal_structure"]["extra_reference"] = {evidence.REFERENCE_KEY: ref}
    elif mutation == "typed_reference_extra_fields": parent[key]["escape"] = True
    elif mutation == "typed_reference_missing": parent[key] = row["quote"]
    elif mutation == "uncovered_added_string": view["goal_structure"]["whole_plan"]["new_string"] = "未编目录"
    elif mutation == "raw_other_field_change": view["goal_structure"]["untouched_metadata"]["number"] = 3
    elif mutation == "structure_type": view["goal_structure"] = []
    elif mutation == "catalog_type": view["evidence_catalog"] = list(view["evidence_catalog"].items())
    elif mutation == "renumber_ref":
        view["evidence_catalog"]["G999"] = view["evidence_catalog"].pop(ref)
        parent[key][evidence.REFERENCE_KEY] = "G999"
    changed_before = deepcopy(view)
    with pytest.raises(evidence.GoalEvidenceViewError):
        evidence.reconstruct_goal(view)
    assert view == changed_before


def test_literal_slash_tilde_keys_are_preserved_but_pointer_escaping_is_not_silently_decoded(original):
    view = evidence.build_lossless_goal_evidence_view(original)
    assert evidence.reconstruct_goal(view) == original
    row = next(row for row in view["evidence_catalog"].values() if "slash/key~原" in row["document_path"])
    row["document_path"] = row["document_path"].replace("slash/key~原", "slash~1key~0原")
    with pytest.raises(evidence.GoalEvidenceViewError, match="wrong original document_path"):
        evidence.reconstruct_goal(view)


@pytest.mark.parametrize("invalid_path", ["whole_plan.beats.00.event", "whole_plan.beats.-1.event",
    "whole_plan.beats.999.event", "whole_plan..beats.0.event", "whole_plan.beats.0.event.more",
    "whole_plan.beats.０.event"])
def test_build_rejects_wrong_or_escaped_catalog_paths(original, invalid_path, monkeypatch):
    catalog = deepcopy(drama.build_evidence_catalog(original))
    ref = next(ref for ref, row in catalog.items() if row["document_path"] == "whole_plan.beats.0.event")
    catalog[ref]["document_path"] = invalid_path
    monkeypatch.setattr(drama, "build_evidence_catalog", lambda native: deepcopy(catalog))
    with pytest.raises(evidence.GoalEvidenceViewError):
        evidence.build_lossless_goal_evidence_view(original)


def test_build_rejects_duplicate_path_wrong_quote_and_reserved_reference_collision(original, monkeypatch):
    real_builder = drama.build_evidence_catalog
    catalog = deepcopy(real_builder(original))
    catalog["G999"] = deepcopy(catalog[next(iter(catalog))])
    monkeypatch.setattr(drama, "build_evidence_catalog", lambda native: deepcopy(catalog))
    with pytest.raises(evidence.GoalEvidenceViewError, match="duplicate evidence"):
        evidence.build_lossless_goal_evidence_view(original)
    del catalog["G999"]
    catalog[next(iter(catalog))]["quote"] = "不是原文"
    with pytest.raises(evidence.GoalEvidenceViewError, match="quote or path differs"):
        evidence.build_lossless_goal_evidence_view(original)
    monkeypatch.setattr(drama, "build_evidence_catalog", real_builder)
    original["extra"] = {evidence.REFERENCE_KEY: "G001"}
    with pytest.raises(evidence.GoalEvidenceViewError, match="reserved"):
        evidence.build_lossless_goal_evidence_view(original)


def test_external_source_binding_rejects_coherently_changed_view(original):
    changed = deepcopy(original)
    changed["whole_plan"]["beats"][0]["event"] = "整份不同来源"
    view = evidence.build_lossless_goal_evidence_view(changed)
    assert evidence.reconstruct_goal(view) == changed
    with pytest.raises(evidence.GoalEvidenceViewError, match="externally expected"):
        evidence.reconstruct_goal(view, expected_native_goal_sha256=evidence.digest(original))
    with pytest.raises(evidence.GoalEvidenceViewError, match="externally expected"):
        evidence.validate_lossless_goal_evidence_view(view, original)


@pytest.mark.parametrize("bad", [{}, [], {"nan": float("nan")}, {"tuple": (1, 2)}, {1: "key"},
    {"claims": [{"id": "same", "text": "x"}, {"id": "same", "text": "y"}], "whole_plan": {"event": "x"}}])
def test_invalid_native_json_or_duplicate_claim_refs_is_rejected(bad):
    with pytest.raises(evidence.GoalEvidenceViewError):
        evidence.build_lossless_goal_evidence_view(bad)


@pytest.mark.parametrize("round_name,ordinal,expected_rows", [("round_11", 568, 157), ("round_12", 571, 158)])
def test_actual_complete_568_571_raw_files_catalog_and_canonical_round_trip(round_name, ordinal, expected_rows):
    root = TRIALS / round_name
    if not root.exists(): pytest.skip("read-only historical fixture absent")
    paths = [root / "goals/native_01.json", root / "STATE.json", root / "CALL_LEDGER.json", root / "PRODUCTION_FREEZE.json"]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    native = json.loads(paths[0].read_text(encoding="utf-8"))
    view = evidence.build_lossless_goal_evidence_view(native)
    rebuilt = evidence.reconstruct_goal(view)
    validation = evidence.validate_lossless_goal_evidence_view(view, native)
    assert rebuilt == native and drama.digest(rebuilt) == drama.digest(native) == view["native_goal_sha256"]
    assert len(view["evidence_catalog"]) == expected_rows
    assert view["evidence_catalog"] == drama.build_evidence_catalog(native)
    assert validation["complete_native_round_trip_verified"] and not validation["quote_validation_relaxed"]
    assert not validation["dispatch_performed"] and not validation["semantic_quality_proven"]
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_actual573_wrong_actor_quote_and_g055_still_rejected_after_lossless_reconstruction():
    root = TRIALS / "round_12"
    path = root / "call_573_goal_drama_audit_01.json"
    if not path.exists(): pytest.skip("read-only actual573 fixture absent")
    raw = path.read_bytes()
    receipt = json.loads(raw)
    native = json.loads((root / "goals/native_01.json").read_text(encoding="utf-8"))
    rebuilt = evidence.reconstruct_goal(evidence.build_lossless_goal_evidence_view(native))
    failed = receipt["output"]
    bad_row = failed["scope_observations"]["b7"]["operated_props"][0]
    assert bad_row["source_ref"] == "G055"
    assert bad_row["quote"] not in drama.build_evidence_catalog(rebuilt)["G055"]["quote"]
    with pytest.raises(ValueError, match="verbatim"):
        drama.validate_drama(failed, rebuilt, context_sha256=failed["audit_context_sha256"])
    assert path.read_bytes() == raw
