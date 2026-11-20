"""Seven OFFLINE distinction families; fixtures are not actual source judgements."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_world_scene_source_state_audit_v2 as m
from test_creative_world_scene_source_state_audit_v1 import synthetic_context

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no provider authorization in pure tests")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def proof(prepared, source, path):
    catalog = prepared["views"]["source_catalog"]
    ref = next(ref for ref, row in catalog.items() if row["source"] == source and row["path"] == path)
    document = prepared["views"][source]
    return {"ref": ref, "quote": m.prior._resolve(document, path)[:160]}


def beat_proof(p, i): return proof(p, "goal", f"/whole_plan/beats/{i}/visible_change")


def synthetic_report(prepared, local_conflict=False):
    """Fake-SDK data only; never send this as an actual plan's semantic proof."""
    goal, setup = prepared["views"]["goal"], prepared["views"]["setup"]
    beats = goal["whole_plan"]["beats"]
    rows = [{"beat_id": b["id"], "coverage_summary": "OFFLINE合成覆盖，非真实模型审查。",
        "source_evidence": [beat_proof(prepared, i)]} for i, b in enumerate(beats)]
    result = {"schema": m.VERSION, "native_goal_sha256": m.digest(goal), "native_setup_sha256": m.digest(setup),
        "context_sha256": prepared["context_sha256"], "beat_reviews": rows, "state_coverage": {},
        "quantity_chains": [], "custody_chains": [],
        "semantic_checks": {name: {"status": "pass", "reason": "OFFLINE合成语义正控，不能当生产结论。",
            "beat_ids": [], "evidence": [beat_proof(prepared, 0)]} for name in m.CHECKS}}
    for i, prop in enumerate(goal["whole_plan"]["props"]):
        row = {"status": "not_applicable", "reason": "OFFLINE合成不适用声明，非对真实来源的提取证明。", "chain_ids": [],
            "evidence": [proof(prepared, "goal", f"/whole_plan/props/{i}/description")]}
        result["state_coverage"][prop["id"]] = {"quantity": deepcopy(row), "custody": deepcopy(row)}
    if local_conflict:
        chain = quantity_chain(prepared)
        chain["steps"] = [quantity_step(prepared, 1, 3, 0, 3, "observe", "prerequisite", "")]
        attach_chain(result, chain, "quantity")
    return result


def quantity_chain(p):
    return {"id": "Q_OFFLINE", "object_id": p["views"]["goal"]["whole_plan"]["props"][0]["id"],
        "scope": "OFFLINE合成同一待处理总体", "unit": "OFFLINE单位", "initial_reading": "prerequisite", "initial_value": 2,
        "initial_evidence": [beat_proof(p, 0)], "steps": []}


def quantity_step(p, i, before, delta, after, op, reading="occurred", event="EV_OFFLINE"):
    return {"beat_id": p["views"]["goal"]["whole_plan"]["beats"][i]["id"], "reading": reading,
        "event_id": event, "evidence": [beat_proof(p, i)], "operation": op,
        "before": before, "delta": delta, "after": after}


def attach_chain(native, chain, family):
    native[family + "_chains"].append(chain)
    row = native["state_coverage"][chain["object_id"]][family]
    row["status"] = "traced"; row["chain_ids"].append(chain["id"])


def source_context():
    inputs, profile, goal, setup = synthetic_context()
    texts = ["OFFLINE合成：初始待处理物件2个。", "OFFLINE合成：新增1个，实际变成3个。",
        "OFFLINE合成：重述前拍同一次新增，并无第二次。", "OFFLINE合成：待处理物件仍3个。"]
    for beat, text in zip(goal["whole_plan"]["beats"], texts): beat["visible_change"] = text
    setup["goal_sha256"] = m.digest(goal)
    return inputs, profile, goal, setup


def test_unsourced_quantity_increase_cannot_be_overridden_by_all_semantic_pass():
    p = m.prepare(*source_context()); native = synthetic_report(p, local_conflict=True); before = deepcopy(native)
    d = m.validate(native, p)
    assert d["valid"] and not d["accepted"] and not d["uncertainties"]
    assert any(f["code"] == "QUANTITY_PRECONDITION_CONFLICT" for f in d["findings"])
    assert native == before and not d["program_proves_extraction_complete"]


def test_explicit_added_event_and_intended_target_math_do_not_confuse_actual_state():
    p = m.prepare(*source_context()); native = synthetic_report(p); chain = quantity_chain(p)
    chain["steps"] = [quantity_step(p, 0, 2, -2, 0, "remove", "intent", "EV_FUTURE"),
        quantity_step(p, 1, 2, 1, 3, "add"), quantity_step(p, 3, 3, 0, 3, "observe", "prerequisite", "")]
    attach_chain(native, chain, "quantity"); d = m.validate(native, p)
    assert d["valid"] and d["accepted"]
    assert d["typed_replay"][0]["state_after"] == 2
    future = deepcopy(native)
    for key in ("before", "delta", "after"): future["quantity_chains"][0]["steps"][0][key] = None
    future["quantity_chains"][0]["steps"][0]["operation"] = "unknown"
    assert m.validate(future, p)["accepted"]
    broken = deepcopy(native); broken["quantity_chains"][0]["steps"][1]["after"] = 4
    assert any(f["code"] == "QUANTITY_ARITHMETIC_CONFLICT" for f in m.validate(broken, p)["findings"])
    broken = deepcopy(native); broken["quantity_chains"][0]["initial_value"] = 2.0
    assert not m.validate(broken, p)["valid"]


def test_same_event_multiple_quoted_descriptions_are_applied_once():
    p = m.prepare(*source_context()); native = synthetic_report(p); chain = quantity_chain(p)
    chain["steps"] = [quantity_step(p, 1, 2, 1, 3, "add"), quantity_step(p, 2, 2, 1, 3, "add"),
        quantity_step(p, 3, 3, 0, 3, "observe", "prerequisite", "")]
    attach_chain(native, chain, "quantity"); d = m.validate(native, p)
    assert d["valid"] and d["accepted"] and d["typed_replay"][1]["applied"] is False
    broken = deepcopy(native); broken["quantity_chains"][0]["steps"][1]["delta"] = 2
    assert not m.validate(broken, p)["valid"]


def test_custody_repeated_put_away_and_static_owner_cannot_satisfy_current_prerequisite():
    p = m.prepare(*source_context()); native = synthetic_report(p)
    prop = next(key for key, value in p["views"]["setup"]["props"].items() if value["kind"] == "actor")
    initial = p["views"]["setup"]["props"][prop]
    start = {"kind": "actor", "holder_id": initial["actor_id"], "location": initial["location"]}
    away = {**start, "location": "OFFLINE合成收纳位置"}
    chain = {"id": "C_OFFLINE", "object_id": prop, "initial_state": start,
        "initial_evidence": [proof(p, "setup", f"/props/{prop}/location")], "steps": []}
    for i in (1, 2):
        chain["steps"].append({"beat_id": p["views"]["goal"]["whole_plan"]["beats"][i]["id"],
            "reading": "occurred", "event_id": f"EV_{i}", "before": deepcopy(start), "after": deepcopy(away),
            "evidence": [beat_proof(p, i)]})
    attach_chain(native, chain, "custody"); d = m.validate(native, p)
    assert d["valid"] and not d["accepted"] and any(f["code"] == "CUSTODY_PRECONDITION_CONFLICT" for f in d["findings"])
    chain["steps"].pop(); assert m.validate(native, p)["accepted"]
    chain["initial_state"] = {"kind": "scene", "holder_id": p["views"]["goal"]["whole_plan"]["scenes"][0]["id"], "location": "OFFLINE非首态"}
    assert any(f["code"] == "CUSTODY_INITIAL_CONFLICT" for f in m.validate(native, p)["findings"])


def test_quiet_listener_does_not_require_invented_operation_but_full_beat_coverage_is_required():
    p = m.prepare(*synthetic_context(quiet_hold=True)); native = synthetic_report(p)
    assert not native["quantity_chains"] and not native["custody_chains"]
    assert m.validate(native, p)["accepted"]
    native["beat_reviews"].pop(); assert not m.validate(native, p)["valid"]


def test_actual_catalog_projection_exact_quotes_and_context_identity_are_not_normalized():
    root = ROOT / "data/production_trials/world_scene_live_20261015/round_02"
    inputs = json.loads((root / "INPUTS.json").read_text("utf-8-sig"))
    goal = json.loads((root / "call_645_whole_plan_02.json").read_text("utf-8-sig"))["output"]
    setup = json.loads((root / "call_650_opening_setup_01.json").read_text("utf-8-sig"))["output"]
    profile = json.loads((ROOT / "data/qa/creative_world_scene_live_20261015/LIVE_PROFILE_v1.json").read_text("utf-8-sig"))
    profile["stage_parameters"]["goal_audit"]["max_completion_tokens"] = 32000
    p = m.prepare(inputs, profile, goal, setup); payload = json.loads(p["request"]["messages"][1]["content"])
    assert payload["native_goal_document"] == goal and payload["native_opening_setup_document"] == setup
    assert "full_prior_script" not in payload["authority_inputs"]["production_preferences"]["prior_story_scope"]
    assert sum(s.count(inputs["reference_fulltext"]) for s in m.prior._string_leaves(payload)) == 1
    assert all(row["source"] in ("goal", "setup") for row in p["views"]["source_catalog"].values())
    assert not any(row["path"].endswith("/id") for row in p["views"]["source_catalog"].values())
    native = synthetic_report(p); native["beat_reviews"][0]["source_evidence"][0]["ref"] = "R_NOT_REAL"
    assert not m.validate(native, p)["valid"]
    native = synthetic_report(p); native["beat_reviews"][0]["source_evidence"][0]["quote"] = "OFFLINE假引用不存在"
    assert any(f["code"] == "SOURCE_QUOTE_INVALID" for f in m.validate(native, p)["contract_findings"])
    altered = deepcopy(p); altered["views"]["source_catalog"].pop(next(iter(altered["views"]["source_catalog"])))
    with pytest.raises(ValueError, match="bindings changed"): m.validate(synthetic_report(p), altered)


def test_unknown_quantity_and_native_semantic_unknown_are_never_pass():
    p = m.prepare(*source_context()); native = synthetic_report(p); chain = quantity_chain(p)
    chain["initial_reading"] = "unknown"; chain["initial_value"] = None
    chain["steps"] = [quantity_step(p, 1, None, None, None, "unknown", "unknown", "")]
    attach_chain(native, chain, "quantity"); d = m.validate(native, p)
    assert d["valid"] and not d["accepted"] and d["uncertainties"]
    native["state_coverage"][chain["object_id"]]["quantity"]["status"] = "unknown"
    d = m.validate(native, p)
    assert d["valid"] and not d["accepted"] and d["uncertainties"]
    native["state_coverage"][chain["object_id"]]["quantity"]["chain_ids"] = []
    assert not m.validate(native, p)["valid"]
    native = synthetic_report(p); native["semantic_checks"]["spatial_presence"]["status"] = "unknown"
    assert m.validate(native, p)["status"] == "source_state_unknown"
