"""Focused candidate tests. Model judgments are simulated; no API or production run."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_order_witness_contract_v1 as contract

PROJECT = Path(__file__).resolve().parents[1]
LEGAL15 = PROJECT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15"


def source_for(plan, brief, mode="paired_response"):
    _, _, edges = contract._source_inputs(plan, brief)
    return {"plan_sha256": contract._digest(plan), "brief_sha256": contract._digest(brief),
        "edges": [{**deepcopy(row), "mode": mode, "explanation": "离线模拟源分类，不是实际模型验收。"}
                  for row in edges.values()]}


def witness_for(source, audit, script, plan, brief):
    _, edges, entries, _, _, quotes = contract._actual_inputs(source, audit, script, plan, brief)
    positions = {ref: i for i, ref in enumerate(entries)}
    result = {"plan_sha256": contract._digest(plan), "brief_sha256": contract._digest(brief),
        "script_sha256": contract._digest(script), "native_audit_sha256": contract._digest(audit),
        "source_semantics_sha256": contract._digest(source), "edges": []}
    for key, edge in edges.items():
        before, after = quotes[edge["before_id"]], quotes[edge["after_id"]]
        links = []
        for ref in after:
            preceding = [a for a in before if positions[a] < positions[ref]]
            parent = max(preceding, key=positions.get) if preceding else next(iter(before), "")
            links.append({"before_ref_id": parent, "after_ref_id": ref,
                "relation": "responds_to" if parent else "unknown",
                "explanation": "离线模拟关联，不是实际语义批准。"})
        result["edges"].append({"edge_id": key, "status": "pass", "explanation": "离线协议样本。",
            "required_revision": "", "episodes": [{
                "before_occurrences": [{"ref_id": ref, "quote": quote} for ref, quote in before.items()],
                "after_occurrences": [{"ref_id": ref, "quote": quote} for ref, quote in after.items()],
                "response_links": links}]})
    return result


def fixture(early_response=False):
    brief = {"facts": [{"id": "F1", "text": "进入请求阶段后，对方回应；继续交锋不等于所有请求先说完。"}]}
    plan = {"source_obligations": [
        {"id": "S1", "fact_id": "F1", "mode": "event", "actor_id": "a", "required_kind": "dialogue", "allowed_speech_functions": ["request"]},
        {"id": "S2", "fact_id": "F1", "mode": "event", "actor_id": "b", "required_kind": "dialogue", "allowed_speech_functions": ["refusal"]}],
        "source_order": [{"before_id": "S1", "after_id": "S2", "fact_id": "F1", "source_quote": brief["facts"][0]["text"]}]}
    turns = [("a", "帮我这一回。", "request"), ("b", "我不能答应。", "refusal"),
             ("a", "再考虑一下？", "request"), ("b", "还是不行。", "refusal")]
    if early_response:
        turns.insert(0, ("b", "还没有这项请求就先作了回应。", "refusal"))
    script = {"beats": [{"id": "B1", "steps": [{"kind": "dialogue", "speaker": actor, "text": text}
                                               for actor, text, _ in turns]}]}
    entries = contract.base.evidence_catalog(script)
    events = [{"source_ref": ref, "kind": "dialogue", "speaker": turns[i][0],
        "actual_actor": turns[i][0], "speech_functions": [turns[i][2]]} for i, ref in enumerate(entries)]
    audit = {"script_sha256": contract._digest(script), "plan_sha256": contract._digest(plan),
        "literal_events": events, "obligation_evidence": [
            {"obligation_id": key, "status": "pass", "explanation": "离线模拟分类。",
             "occurrence_refs": [row["source_ref"] for row in events if row["speaker"] == actor],
             "support_refs": [], "occurrence_spans": []} for key, actor in (("S1", "a"), ("S2", "b"))]}
    return plan, brief, script, audit


def decide_fixture(mode, early=False):
    plan, brief, script, audit = fixture(early)
    source = source_for(plan, brief, mode)
    witness = witness_for(source, audit, script, plan, brief)
    return contract.decide_occurrence_episode_witness(witness, source, audit, script, plan, brief)


@pytest.mark.parametrize("mode", ["first_transition", "paired_response"])
def test_valid_interleaving_is_not_all_before_all(mode):
    assert decide_fixture(mode)["status"] == "order_witness_ready"


def test_all_occurrences_quantifier_remains_strict():
    decision = decide_fixture("all_occurrences")
    assert decision["status"] == "needs_whole_revision"
    assert any(row["code"].startswith("ALL_OCCURRENCES_ORDER_FAILURE") for row in decision["revision_requirements"])


@pytest.mark.parametrize("mode", ["first_transition", "paired_response"])
def test_later_valid_pair_cannot_erase_early_response(mode):
    assert decide_fixture(mode, early=True)["status"] == "needs_whole_revision"


def test_missing_request_classifier_remains_unknown_without_mutation():
    plan, brief, script, audit = fixture()
    audit["literal_events"][0]["speech_functions"] = ["statement"]
    before = deepcopy(audit)
    source = source_for(plan, brief, "first_transition")
    witness = witness_for(source, audit, script, plan, brief)
    decision = contract.decide_occurrence_episode_witness(witness, source, audit, script, plan, brief)
    assert decision["status"] == "halt_review_uncertain"
    assert any(row["code"].startswith("NATIVE_CLASSIFIER_CONFLICT") for row in decision["uncertainties"])
    assert audit == before


def test_dropping_early_response_is_rejected_by_public_schema():
    plan, brief, script, audit = fixture(True)
    source = source_for(plan, brief)
    witness = witness_for(source, audit, script, plan, brief)
    episode = witness["edges"][0]["episodes"][0]
    early_ref = episode["after_occurrences"][0]["ref_id"]
    episode["after_occurrences"] = [q for q in episode["after_occurrences"] if q["ref_id"] != early_ref]
    episode["response_links"] = [q for q in episode["response_links"] if q["after_ref_id"] != early_ref]
    schema = contract.build_occurrence_episode_witness_schema(source, audit, script, plan, brief)
    assert list(Draft202012Validator(schema).iter_errors(witness))


def test_source_unknown_stops_before_actual_witness():
    plan, brief, script, audit = fixture()
    source = source_for(plan, brief, "unknown")
    assert contract.decide_source_order_semantics(source, plan, brief)["status"] == "halt_source_uncertain"
    with pytest.raises(ValueError, match="known source-only"):
        contract.build_occurrence_episode_witness_schema(source, audit, script, plan, brief)


def test_source_payload_contains_no_creative_beats_body_or_reviews():
    plan, brief, script, audit = fixture()
    plan["beats"] = [{"private_marker": "旧创作正文不能进入源分类"}]
    payload = contract.source_order_semantics_payload(plan, brief)
    assert set(payload) == {"brief", "source_edges", "provenance"}
    assert "旧创作正文不能进入源分类" not in json.dumps(payload, ensure_ascii=False)
    assert payload["provenance"]["actual_script_or_review_in_payload"] is False


@pytest.mark.parametrize("bad_field", ["hash", "quote"])
def test_source_hash_and_fact_quote_are_immutable(bad_field):
    plan, brief, _, _ = fixture()
    source = source_for(plan, brief)
    if bad_field == "hash":
        source["brief_sha256"] = "0" * 64
    else:
        source["edges"][0]["source_quote"] = "人为替换源要求"
    with pytest.raises(ValueError):
        contract.validate_source_order_semantics(source, plan, brief)


@pytest.mark.parametrize("bad_field", ["hash", "span"])
def test_witness_hash_and_native_span_cannot_change(bad_field):
    plan, brief, script, audit = fixture()
    source = source_for(plan, brief)
    witness = witness_for(source, audit, script, plan, brief)
    if bad_field == "hash":
        witness["native_audit_sha256"] = "0" * 64
    else:
        witness["edges"][0]["episodes"][0]["before_occurrences"][0]["quote"] = "改写发生引文"
    with pytest.raises(ValueError):
        contract.validate_occurrence_episode_witness(witness, source, audit, script, plan, brief)


def test_native_source_failure_cannot_be_passed_by_witness():
    plan, brief, script, audit = fixture()
    audit["obligation_evidence"][0].update(status="fail", explanation="实际事件未演出。", occurrence_refs=[])
    source = source_for(plan, brief)
    witness = witness_for(source, audit, script, plan, brief)
    assert contract.decide_occurrence_episode_witness(witness, source, audit, script, plan, brief)["status"] == "needs_whole_revision"


def actual(version):
    brief = json.loads((LEGAL15 / "INPUT.json").read_text(encoding="utf-8"))["brief"]
    plan = json.loads((LEGAL15 / "SCENE_PLAN.json").read_text(encoding="utf-8"))
    script = json.loads((LEGAL15 / "versions" / f"{version:02}" / "FULL_SCRIPT.json").read_text(encoding="utf-8"))
    ordinal = 484 if version == 6 else 489
    audit = json.loads((LEGAL15 / f"call_{ordinal}_literal_audit_{version:02}.json").read_text(encoding="utf-8"))["output"]
    return plan, brief, script, audit


def test_actual6_native_indirect_request_conflict_is_preserved():
    plan, brief, script, audit = actual(6)
    before = deepcopy((plan, brief, script, audit))
    source = source_for(plan, brief, "first_transition")
    witness = witness_for(source, audit, script, plan, brief)
    decision = contract.decide_occurrence_episode_witness(witness, source, audit, script, plan, brief)
    row = next(q for q in decision["edge_evidence"] if q["edge_id"] == "SO7_BEFORE_SO8")
    assert {"obligation_id": "SO7", "ref_id": "E0014", "mismatch_fields": ["speech_function"]} in row["native_classifier_conflicts"]
    assert any(q["edge_id"] == row["edge_id"] for q in decision["uncertainties"])
    assert decision["status"] != "order_witness_ready"
    assert (plan, brief, script, audit) == before


@pytest.mark.parametrize("mode", ["first_transition", "paired_response", "all_occurrences"])
def test_actual7_missing_company_phase_refusal_stays_failure(mode):
    plan, brief, script, audit = actual(7)
    source = source_for(plan, brief, mode)
    witness = witness_for(source, audit, script, plan, brief)
    decision = contract.decide_occurrence_episode_witness(witness, source, audit, script, plan, brief)
    assert decision["status"] == "needs_whole_revision"
    assert any(q["edge_id"] == "SO6_BEFORE_SO7" for q in decision["revision_requirements"])


def test_public_schemas_are_valid_for_empty_order_table():
    plan, brief, script, audit = fixture()
    plan["source_order"] = []
    audit["plan_sha256"] = contract._digest(plan)
    source = source_for(plan, brief)
    Draft202012Validator.check_schema(contract.build_source_order_semantics_schema(plan, brief))
    Draft202012Validator.check_schema(contract.build_occurrence_episode_witness_schema(source, audit, script, plan, brief))
