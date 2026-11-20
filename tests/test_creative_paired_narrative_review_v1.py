"""Offline source/contract proofs, never semantic model approval.

All fabricated pass reports use the tiny synthetic scene below. Actual627/634
are replayed only as unchanged negative/interpretively open source material.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, Draft202012Validator

from src.content_factory import creative_paired_narrative_review_v1 as p

ROOT = Path(__file__).resolve().parents[1]
ACTUAL = ROOT / "data/production_trials/legal_scoped_text_session_20261015/round_01"


def goal():
    beats = []
    for i in (1, 2):
        beats.append({"id": f"B{i}", "actor_id": "a", "scene_id": "room", "goal": "了解卡片去向",
            "resistance": "乙提出另一种处理方法", "stimulus": "乙把卡片放在桌上",
            "response": "甲说要拿走卡片", "visible_change": "甲拿起卡片走向门口",
            "strategy": {"before": "询问", "after": "带走阅读", "effect": "changes"}})
    return {"claims": [{"id": "CC.fixture", "kind": "creative_choice", "text": "仅供离线合同验证的虚构场景"}],
        "whole_plan": {"characters": [{"id": "a", "want": "带走卡片"}, {"id": "b", "want": "保留记录"}],
            "props": [{"id": "card", "description": "卡片"}], "scenes": [{"id": "room", "description": "房间"}],
            "beats": beats, "ending": {"attempt_result": "甲得到卡片", "visible_consequence": "卡片在甲手中",
                "emotional_landing": "甲带卡离开", "open_question": "以后另谈"}}}


def script():
    return {"title": "离线样例", "premise": "虚构合同样例", "beats": [
        {"id": f"B{i}", "event": "甲带走卡片", "trigger": "乙递出卡片", "steps": [
            {"kind": "dialogue", "speaker": "a", "text": "我带走看看。"},
            {"kind": "action", "speaker": "", "text": "甲拿起卡片离开。"}]} for i in (1, 2)]}


def make_native(frame):
    """Synthetic structural fixture, not a model result or truth evaluator."""
    manifest = frame["manifest"]
    doc = {"schema": p.VERSION, "frame_kind": manifest["frame_kind"],
        "goal_sha256": manifest["goal_sha256"], "input_sha256": manifest["input_sha256"],
        "context_sha256": manifest["context_sha256"], "records_by_target": {}}
    for tid, target in frame["_targets"].items():
        refs = target["required_reading_refs"]
        doc["records_by_target"][tid] = {"status": "pass", "readings": {
            ref: [{"quote": frame["_catalog"][ref]["quote"], "mode": "attribution", "actor_id": None,
                  "object_id": None, "literal_reading": "Synthetic fixture reading, not a model approval", "state": None}]
            for ref in refs}, "evidence": list(refs), "counterevidence": [], "transition_evidence": [],
            "comparison": "Synthetic contract fixture only", "required_revision": ""}
    return doc


def setup():
    g = goal(); f = p._frame(g); d = make_native(f)
    args = {"context_sha256": f["manifest"]["context_sha256"], "bundle_sha256": "1" * 64}
    snap = p.compile_snapshot(d, g, **args)
    return g, f, d, args, snap


def test_lossless_global_index_once_and_context_covers_entire_goal():
    g, frame, native, args, _ = setup(); original = deepcopy(g)
    built = p.build_goal_delta(g)
    assert g == original
    targets = p.build_targets(g)
    assert set(targets["targets"]) == {"beat:B1", "beat:B2", "ending"}
    assert all("allowed_source_refs" not in row for row in targets["targets"].values())
    assert all(set(row) == {"document_path"} for row in targets["source_index"].values())
    assert "甲说要拿走卡片" not in json.dumps(built["payload_delta"], ensure_ascii=False)
    assert p.validate_goal(native, g, context_sha256=args["context_sha256"])["accepted"]
    changed = deepcopy(g); changed["unprojected_metadata"] = {"preserve_me": True}
    with pytest.raises(ValueError, match="lossless"):
        p.build_goal_schema(changed, context_sha256=args["context_sha256"])
    assert built["manifest"]["original_fulltext_copies_in_delta"] == 0


@pytest.mark.parametrize("fault", ["missing_target", "missing_ending", "missing_reading", "fake_quote", "bad_ref", "bad_actor", "bad_object", "unknown_pass", "counter_pass", "revision_pass"])
def test_closed_native_coverage_and_quote_failures(fault):
    g, frame, d, args, _ = setup(); row = d["records_by_target"]["beat:B1"]; ref = next(iter(row["readings"]))
    if fault == "missing_target": d["records_by_target"].pop("beat:B2")
    elif fault == "missing_ending": d["records_by_target"].pop("ending")
    elif fault == "missing_reading": row["readings"].pop(ref)
    elif fault == "fake_quote": row["readings"][ref][0]["quote"] = "没有写过的动作"
    elif fault == "bad_ref": row["evidence"].append("OTHER_MANUSCRIPT")
    elif fault == "bad_actor": row["readings"][ref][0]["actor_id"] = "not_declared"
    elif fault == "bad_object": row["readings"][ref][0]["object_id"] = "unrelated_undeclared_object"
    elif fault == "unknown_pass": row["readings"][ref][0]["mode"] = "uncertain"
    elif fault == "counter_pass": row["counterevidence"] = [ref]
    else: row["required_revision"] = "原文需修改"
    with pytest.raises((ValueError, ValidationError)):
        p.validate_goal(d, g, context_sha256=args["context_sha256"])


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_known_nonaccepted_comparison_cannot_compile_or_enter_body(status):
    g, frame, d, args, _ = setup()
    row = d["records_by_target"]["ending"]; row.update(status=status, required_revision="保留真实冲突或歧义，整稿修订")
    if status == "unknown": next(iter(row["readings"].values()))[0]["mode"] = "uncertain"
    decision = p.validate_goal(d, g, context_sha256=args["context_sha256"])
    assert decision["valid"] and not decision["accepted"]
    with pytest.raises(ValueError, match="unaccepted"):
        p.compile_snapshot(d, g, **args)


def test_native_declared_incompatible_final_states_cannot_hide_in_pass():
    g, frame, d, args, _ = setup()
    row = d["records_by_target"]["ending"]
    for atoms, holder in zip(row["readings"].values(), ("a", "b")):
        reading = atoms[0]
        reading.update(mode="observed_state", object_id="card",
            state={"dimension": "holder", "phase": "ending", "participant_id": None, "value": holder})
    with pytest.raises(ValueError, match="final states"):
        p.validate_goal(d, g, context_sha256=args["context_sha256"])


def test_holder_cannot_split_one_object_into_different_participant_slots():
    g, frame, d, args, _ = setup(); row = d["records_by_target"]["ending"]
    for atoms, holder in zip(row["readings"].values(), ("a", "b")):
        atoms[0].update(mode="observed_state", object_id="card",
            state={"dimension": "holder", "phase": "ending", "participant_id": holder, "value": holder})
    with pytest.raises(ValueError, match="participant must be null"):
        p.validate_goal(d, g, context_sha256=args["context_sha256"])


def test_uncertain_reading_cannot_be_relabelled_known_content_failure():
    g, frame, d, args, _ = setup(); row = d["records_by_target"]["ending"]
    row.update(status="fail", required_revision="必须先澄清")
    next(iter(row["readings"].values()))[0]["mode"] = "uncertain"
    with pytest.raises(ValueError, match="requires unknown"):
        p.validate_goal(d, g, context_sha256=args["context_sha256"])


def test_same_source_sentence_can_bind_two_objects_with_different_destinations():
    g = goal(); g["whole_plan"]["props"].append({"id": "copy", "description": "另一张副本"})
    g["whole_plan"]["beats"][0]["response"] = "甲把原卡留给乙，说要带走副本。"
    g["whole_plan"]["beats"][0]["visible_change"] = "甲带走副本，乙收好原卡。"
    f = p._frame(g); d = make_native(f); row = d["records_by_target"]["beat:B1"]
    bypath = {v["document_path"]: k for k,v in f["_catalog"].items()}
    response = bypath["whole_plan.beats.0.response"]
    original = deepcopy(row["readings"][response][0])
    original.update(quote="原卡留给乙", object_id="card", mode="completed_action", actor_id="a",
        literal_reading="原卡由乙保留", state={"dimension":"holder","phase":"ending","participant_id":None,"value":"b"})
    copy = deepcopy(original)
    copy.update(quote="带走副本", object_id="copy", mode="intention", literal_reading="甲表示要带副本", state=None)
    row["readings"][response] = [original, copy]
    assert p.validate_goal(d,g,context_sha256=f["manifest"]["context_sha256"])["accepted"]
    snapshot = p.compile_snapshot(d,g,context_sha256=f["manifest"]["context_sha256"],bundle_sha256="1"*64)
    assert len(snapshot["records_by_target"]["beat:B1"]["readings"][response]) == 2


@pytest.mark.parametrize("resolution", ["intention_fulfilled", "explicitly_blocked", "explicitly_abandoned", "different_objects_or_times"])
def test_contract_does_not_equate_intention_with_mandatory_success(resolution):
    # Contract acceptance is supplied by this synthetic native fixture; these
    # names do not claim that a real reviewing model reads the cases correctly.
    g = goal()
    visible = {"intention_fulfilled": "甲拿起卡片带走，乙同意。",
        "explicitly_blocked": "乙挡住甲并收回卡片，甲空手离开。",
        "explicitly_abandoned": "甲改口说不拿了，放下卡片空手离开。",
        "different_objects_or_times": "甲带走副本，乙将另一张原卡收进文件夹。"}[resolution]
    g["whole_plan"]["beats"][0]["visible_change"] = visible
    g["whole_plan"]["ending"].update(attempt_result=visible, visible_consequence=visible, emotional_landing="双方分开")
    if resolution == "different_objects_or_times":
        g["whole_plan"]["props"].append({"id": "copy", "description": "另一张副本"})
        g["whole_plan"]["beats"][0]["response"] = "甲说要拿走副本"
    frame = p._frame(g); d = make_native(frame); row = d["records_by_target"]["beat:B1"]
    ref_by_path = {v["document_path"]: k for k,v in frame["_catalog"].items()}
    intent = ref_by_path["whole_plan.beats.0.response"]
    completed = ref_by_path["whole_plan.beats.0.visible_change"]
    row["readings"][intent][0].update(mode="intention", object_id="copy" if resolution == "different_objects_or_times" else "card",
        literal_reading=frame["_catalog"][intent]["quote"])
    row["readings"][completed][0].update(mode="completed_action", object_id="card", literal_reading=visible)
    row["transition_evidence"] = [completed]
    row["comparison"] = "Synthetic native interpretation: " + resolution
    assert p.validate_goal(d, g, context_sha256=frame["manifest"]["context_sha256"])["accepted"]


def test_snapshot_native_goal_bundle_identity_and_once_only_attachment():
    g, frame, d, args, snap = setup()
    payload = {"native_goal_document": deepcopy(g), "other_authority": {"unchanged": True}}
    attached = p.attach_snapshot(payload, snap, g, native_comparison=d, **args)
    assert attached["native_goal_document"] == g and payload.keys() == {"native_goal_document", "other_authority"}
    assert '"quote"' not in json.dumps(snap)
    with pytest.raises(ValueError, match="once"):
        p.attach_snapshot(attached, snap, g, native_comparison=d, **args)
    with pytest.raises(ValueError):
        p.validate_snapshot(snap, g, native_comparison=d, **{**args, "bundle_sha256": "2" * 64})
    altered = deepcopy(snap); altered["records_by_target"]["ending"]["comparison"] = "changed conclusion"
    with pytest.raises(ValueError): p.validate_snapshot(altered, g, native_comparison=d, **args)


def test_actual_script_and_compiled_object_are_distinct_and_bound_to_payload():
    g, frame, d, args, snap = setup(); s = script(); compiled = {**deepcopy(s), "selected_candidate_id": "fixture"}
    kwargs = {"native_comparison": d, "goal_context_sha256": args["context_sha256"], "bundle_sha256": args["bundle_sha256"]}
    payload = {"native_goal_document": g, "native_script_document": s, "full_current_script": compiled}
    attached = p.attach_script_delta(payload, s, g, snap, **kwargs)
    assert attached["manifest"]["native_script_sha256"] == p.digest(s)
    assert attached["manifest"]["compiled_script_sha256"] == p.digest(compiled) != p.digest(s)
    f = p._script_frame(s, g, snap, **kwargs, compiled_script=compiled); native = make_native(f)
    assert p.validate_script(native, s, g, snap, **kwargs, compiled_script=compiled,
        context_sha256=f["manifest"]["context_sha256"])["accepted"]
    changed = deepcopy(s); changed["beats"][0]["steps"][0]["speaker"] = "b"
    with pytest.raises(ValueError, match="actual semantic"):
        p.attach_script_delta(payload, changed, g, snap, **kwargs)
    with pytest.raises(ValueError, match="lossless"):
        p.build_script_schema(s, g, snap, **kwargs, compiled_script=None,
            context_sha256=f["manifest"]["context_sha256"])


def test_actual_style_header_binds_compiled_identity_without_repeating_object():
    g, frame, d, args, snap = setup(); s = script(); compiled = {**deepcopy(s), "selected_candidate_id": "fixture"}
    kwargs = {"native_comparison": d, "goal_context_sha256": args["context_sha256"], "bundle_sha256": args["bundle_sha256"]}
    headers = {"script_sha256": p.digest(compiled), "goal_contract_sha256": p.digest(g)}
    payload = {"native_goal_document": g, "native_script_document": s, "same_source_sha256": headers}
    attached = p.attach_script_delta(payload, s, g, snap, **kwargs, compiled_script=compiled)
    assert attached["manifest"]["request_same_source_sha256"] == headers
    assert attached["manifest"]["compiled_object_supplied"]
    assert "full_current_script" not in attached["payload"]
    bad = {**compiled, "selected_candidate_id": "another"}
    with pytest.raises(ValueError, match="compiled object differs"):
        p.attach_script_delta(payload, s, g, snap, **kwargs, compiled_script=bad)
    altered = deepcopy(headers); altered["goal_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="lossless"):
        p.build_script_schema(s,g,snap,**kwargs,compiled_script=compiled,
            request_same_source_sha256=altered,context_sha256=attached["manifest"]["context_sha256"])


def test_new_closed_outer_schema_merges_definitions_without_old_report_conversion():
    g, f, d, args, _ = setup()
    base = {"type": "object", "properties": {"schema": {"const": "old/v1"}}, "required": ["schema"], "additionalProperties": False}
    added = p.add_to_schema(base, p.build_goal_schema(g, context_sha256=args["context_sha256"]), native_version="new/v1")
    assert base["properties"]["schema"]["const"] == "old/v1"
    Draft202012Validator(added).validate({"schema": "new/v1", "paired_checks": d})
    with pytest.raises(ValidationError): Draft202012Validator(added).validate({"schema": "old/v1", "paired_checks": d})


def test_actual627_631_634_replay_is_source_only_not_fabricated_pass():
    read = lambda n: json.loads((ACTUAL / n).read_text(encoding="utf-8"))
    g = read("call_627_whole_plan_04.json")["output"]
    old = read("call_631_drama_audit_04.json")["output"]
    s = read("call_634_complete_script_01.json")["output"]
    before = deepcopy((g, old, s)); targets = p.build_targets(g)
    source = p.goal_evidence.build_evidence_catalog(g)
    assert {"G062", "G067"} <= set(targets["targets"]["beat:B8"]["required_reading_refs"])
    assert "带走看" in source["G062"]["quote"] and "留在桌面" in source["G067"]["quote"]
    scripted = p.build_script_targets(s, g)
    assert {"E0046", "E0048"} <= set(scripted["targets"]["beat:B8"]["required_reading_refs"])
    context = p.build_goal_delta(g)["manifest"]["context_sha256"]
    with pytest.raises(ValidationError): p.validate_goal(old, g, context_sha256=context)
    assert before == (g, old, s)
