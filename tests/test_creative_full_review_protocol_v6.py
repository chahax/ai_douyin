"""New synthetic reviewer fixtures exercise contracts, never creative quality."""
from copy import deepcopy
import json
import socket
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_full_review_protocol_v6 as p
from src.content_factory import creative_goal_context_workflow_v28 as workflow
from tests.test_creative_goal_context_workflow_v28 import case as world_case
from tests.test_creative_world_scene_context_v1 import profile
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency

CONTEXTS = {"semantic": "1" * 64, "physical": "2" * 64}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("v6 protocol tests have no network authority")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def _shape(node, definitions):
    if "$ref" in node: return _shape(definitions[node["$ref"].split("/")[-1]], definitions)
    if "const" in node: return deepcopy(node["const"])
    if "enum" in node: return deepcopy(node["enum"][0])
    if "allOf" in node and "type" not in node:
        values = [_shape(child, definitions) for child in node["allOf"] if "if" not in child
            and any(key in child for key in ("$ref", "type", "allOf", "properties"))]
        if values and all(isinstance(value, dict) for value in values):
            return {key: value for item in values for key, value in item.items()}
        if values: return values[0]
    for choice in ("oneOf", "anyOf"):
        if choice in node: return _shape(node[choice][0], definitions)
    kind = node.get("type")
    if isinstance(kind, list):
        if "null" in kind: return None
        kind = kind[0]
    if kind == "object" or "properties" in node: return {key: _shape(node["properties"][key], definitions) for key in node.get("required", list(node["properties"]))}
    if kind == "array": return [_shape(node["items"], definitions) for _ in range(node.get("minItems", 0))]
    if kind == "string": return "OFFLINE synthetic model judgment" if node.get("minLength", 0) else ""
    if kind == "boolean": return False
    if kind == "integer": return node.get("minimum", 0)
    if kind == "null": return None
    return {}


def synthetic_full_reports(views, legal_context, contexts=None, *, prior_story_scope=None):
    """Fresh fake reviewer objects for same-source Mock wiring only.

    No provider response is read or normalized. Physical facts/preconditions are
    intentionally empty assertions: passing this fixture tests routing and
    complete coverage, not whether this screenplay actually needs no premises.
    """
    contexts = contexts or CONTEXTS
    script, goal, setup = views["compiled_script"], views["goal"], views["opening_setup"]
    raw, old_script, old_goal, old_setup = p._sources(script, goal, setup, views["brief"])
    entries = p.previous.checks.reviews.base.base.prior.contract.evidence_catalog(old_script)
    refs = list(entries); first = refs[0]
    actors = views["brief"]["constraints"]["allowed_character_ids"]
    reports = {}
    for part in p.PART_TABLES:
        schema = p.build_part_schema(part, script, views["brief"], views["plan"], legal_context,
            context_sha256=contexts[part], goal_contract=goal, opening_setup=setup, prior_story_scope=prior_story_scope)
        native = _shape(schema, schema["$defs"])
        native["temporal_relations"] = []
        if part == "semantic":
            native.update(synthetic_consistency(old_script, views["brief"], views["plan"], goal_contract=old_goal))
            for table, identifier, row in p.previous._judgement_rows(native):
                row["evidence"] = [identifier if table == "dialogue_checks" else first]
                row["counterevidence"] = []; row["required_revision"] = ""
                if table == "dialogue_checks": row.update(stimulus_ref=None, reaction_refs=[])
            for ref, row in native["literal_events"].items():
                row["speech_functions"] = ["action"] if entries[ref]["kind"] == "action" else ["other"]
            native["legal_claims"] = []
            for key, own in p.world.review_fragment(goal, raw)["targets"].items():
                native["world_scene_checks"][key] = {"status": "pass", "reason": "OFFLINE synthetic context control",
                    "evidence": [own[0]], "required_revision": ""}
            for key, target in p.build_review_context(goal, raw)["narrative_targets"].items():
                native["narrative_consistency_checks"][key] = {"status": "pass", "comparison": "OFFLINE synthetic comparison, not quality gold",
                    "readings": {ref: {"role": "support" if ref.startswith("E") else "context",
                        "mode": "observed_state", "literal_reading": "OFFLINE synthetic extraction"}
                        for ref in [*target["goal_refs"], target["actual_refs"][0]]}, "required_revision": ""}
            if "prior_story_relation" in native:
                native["prior_story_relation"].update(relation="new_story", current_evidence=[{"source_ref": first, "quote": entries[first]["quote"]}])
        else:
            action_refs = [ref for ref, row in entries.items() if row["kind"] == "action"]
            for row in native["action_checks"].values():
                row.update(source_refs=action_refs, subjects=[actors[0]], preconditions=[], state_changes=[], required_revision="")
            for row in native["initial_checks"].values(): row.update(source_refs=action_refs, required_revision="")
            original = {row["id"]: row for row in views["brief"]["initial_state"]["prop_states"]}
            for identifier, row in native["observed_prop_initial"].items():
                row.update({key: deepcopy(original[identifier][key]) for key in ("holder_character_id", "support", "orientation")})
                row.update(source_refs=[], required_revision="")
        native["revision_target"] = "none"
        reports[part] = native
    return reports


@pytest.fixture
def case():
    inputs, goal, setup, raw = world_case.__wrapped__()
    views = workflow.compile_native_views(goal, setup, **workflow.origin_ids(inputs))
    views["compiled_script"] = workflow.world.compile_script(raw, goal, views["brief"])["script"]
    legal = workflow.prior._fixed_legal_context(inputs)["verified_legal_context"]
    return inputs, raw, views, legal


def checked(case, reports, part="semantic"):
    _, _, v, law = case
    return p.validate_part(reports[part], part, v["compiled_script"], v["brief"], v["plan"], law,
        context_sha256=CONTEXTS[part], goal_contract=v["goal"], opening_setup=v["opening_setup"])


def bundle(case, reports):
    _, _, v, law = case
    return p.validate_bundle(p.build_review_bundle(reports["semantic"], reports["physical"]),
        v["compiled_script"], v["brief"], v["plan"], law, semantic_context_sha256=CONTEXTS["semantic"],
        physical_context_sha256=CONTEXTS["physical"], goal_contract=v["goal"], opening_setup=v["opening_setup"])


def relation(case, left, right, kind="completed_before_start"):
    _, raw, v, _ = case; catalog = p.world.build_evidence_catalog(v["goal"], raw)
    return {"relation": kind, "from_ref": left, "to_ref": right,
        "evidence": [{"source_ref": ref, "quote": catalog[ref]["quote"]} for ref in (left, right)],
        "reason": "OFFLINE explicit relative-time control"}


def test_new_complete_native_two_part_fixture_and_original_identity(case):
    reports = synthetic_full_reports(case[2], case[3]); before = deepcopy(reports)
    for part in p.PART_TABLES:
        result = checked(case, reports, part)
        assert result["valid"] and result["accepted"], result
        assert result["native_part_sha256"] == p.digest(reports[part]) and not result["source_order_used"]
    result = bundle(case, reports)
    assert result["accepted"] and result["status"] == "text_ready_for_director", result
    assert not result["creative_quality_passed"] and not result["human_quality_approved"] and reports == before


def test_actual_requests_once_native_sources_r01_and_ownership_projection(case):
    inputs, raw, views, _ = case
    for part in p.PART_TABLES:
        prepared = p.prepare_full_review_part_request(inputs, profile(), raw, views, part)
        value = json.loads(prepared["request"]["messages"][1]["content"])
        assert value["native_goal_document"] == views["goal"] and value["native_script_document"] == raw
        assert "full_current_script" not in value and prepared["compiled_script_sha256"] != prepared["native_script_sha256"]
        assert workflow.contexts._reference_occurrences(value, inputs["reference_fulltext"]) == (1 if part == "semantic" else 0)
        assert "full_prior_script" not in value["production_preferences"].get("prior_story_scope", {})
        if part == "semantic":
            assert sum(len(value["user_goal_contract"][key]) for key in ("constraints", "audience_goals")) == 8
            assert "world_scene_review_context" in value and "prior_story_scope" in value
        else: assert "verified_legal_context" not in value and "world_scene_review_context" not in value
        assert prepared["sdk_max_retries"] == 0 and not prepared["server_schema_guarantee"]


def test_missing_new_context_or_wrong_raw_goal_source_rejected(case):
    reports = synthetic_full_reports(case[2], case[3])
    reports["semantic"].pop("world_scene_checks")
    assert not checked(case, reports)["valid"]
    reports = synthetic_full_reports(case[2], case[3]); reports["semantic"]["native_script_sha256"] = "0" * 64
    assert not checked(case, reports)["valid"]


def test_unresolved_reading_is_unknown_not_definite_content_rewrite(case):
    reports = synthetic_full_reports(case[2], case[3]); row = reports["semantic"]["narrative_consistency_checks"]["ending"]
    next(iter(row["readings"].values()))["mode"] = "unresolved_reading"
    row.update(status="fail", required_revision="OFFLINE cannot establish meaning")
    reports["semantic"]["revision_target"] = "script"
    assert not checked(case, reports)["valid"]
    row.update(status="unknown", required_revision=""); reports["semantic"]["revision_target"] = "none"
    result = bundle(case, reports)
    assert result["valid"] and not result["accepted"] and result["status"] == "halt_review_uncertain", result


def test_two_parts_same_edge_different_proofs_allowed_union_not_equalset(case):
    reports = synthetic_full_reports(case[2], case[3])
    # Dialogue endpoints do not change the initial-use frontier of this mock.
    refs = list(reports["semantic"]["dialogue_checks"])
    edge = relation(case, refs[0], refs[1])
    reports["semantic"]["temporal_relations"] = [edge]
    other = deepcopy(edge); other["reason"] = "OFFLINE independent reviewer wording"
    reports["physical"]["temporal_relations"] = [other]
    result = bundle(case, reports)
    assert result["accepted"], result
    reports["physical"]["temporal_relations"] = []
    assert bundle(case, reports)["accepted"]


@pytest.mark.parametrize("fault", ["cycle", "overlap", "quote", "self"])
def test_native_temporal_proofs_reject_cycle_overlap_and_unbound_quote(case, fault):
    reports = synthetic_full_reports(case[2], case[3]); refs = list(reports["semantic"]["dialogue_checks"])
    edge = relation(case, refs[0], refs[1]); edges = [edge]
    if fault == "cycle": edges.append(relation(case, refs[1], refs[0]))
    elif fault == "overlap": edges.append(relation(case, refs[0], refs[1], "overlaps"))
    elif fault == "quote": edge["evidence"][0]["quote"] = "not in source"
    else: edge["to_ref"] = edge["from_ref"]
    reports["semantic"]["temporal_relations"] = edges
    assert not checked(case, reports)["valid"]


def test_cross_part_opposite_edges_rejected_only_on_bundle(case):
    reports = synthetic_full_reports(case[2], case[3]); refs = list(reports["semantic"]["dialogue_checks"])
    reports["semantic"]["temporal_relations"] = [relation(case, refs[0], refs[1])]
    reports["physical"]["temporal_relations"] = [relation(case, refs[1], refs[0])]
    assert all(checked(case, reports, part)["valid"] for part in p.PART_TABLES)
    assert not bundle(case, reports)["valid"]


def physical_transition(case, reports, *, holds=False, conflicting=False):
    """Explicit synthetic state witnesses, not extraction from real actions."""
    _, raw, v, _ = case
    entries = p.world.build_evidence_catalog(v["goal"], raw)
    actions = list(reports["physical"]["action_checks"])
    left, right = actions[:2]
    actors = v["brief"]["constraints"]["allowed_character_ids"]
    initials = p.previous.checks.reviews.base.initial_evidence_catalog(v["brief"], p._sources(v["compiled_script"], v["goal"], v["opening_setup"], v["brief"])[3])
    origin, source = next((ref, row) for ref, row in initials.items()
        if ref.startswith("initial:prop:") and p.previous.checks.reviews.base._native_initial_atoms(row).get("holder_character_id", "missing") is None)
    prop = source["entity_id"]
    fragment = next(value for value in p.previous.checks.reviews.base._source_fragments(source["value"]) if isinstance(value, str) and value.strip())
    for ref, before, after, from_ref, quote in (
        (left, None, None if holds else actors[0], origin, fragment),
        (right, None if holds or conflicting else actors[0], None if holds else actors[-1],
            origin if holds or conflicting else left, fragment if holds or conflicting else entries[left]["quote"])):
        row = reports["physical"]["action_checks"][ref]
        row.update(subjects=[prop], source_refs=[ref], preconditions=[{"entity_id": prop,
            "state_key": "holder_character_id", "expected_value": before, "actual_value": before,
            "established_by": from_ref, "quote": quote}], state_changes=[{"entity_id": prop,
            "state_key": "holder_character_id", "before": before, "after": after, "quote": entries[ref]["quote"]}])
    return left, right


def sync_initial_coverage(case, reports):
    _, raw, v, _ = case
    graph = p.partial.temporal_proof(reports["physical"]["temporal_relations"], p.world.build_evidence_catalog(v["goal"], raw))
    uses = {}
    for ref, row in reports["physical"]["action_checks"].items():
        for entity in row["subjects"]: uses.setdefault(entity, set()).add(ref)
    for table in ("initial_checks", "observed_prop_initial"):
        for identifier, row in reports["physical"][table].items():
            entity = identifier.split(":", 1)[1] if table == "initial_checks" else identifier
            actual = uses.get(entity, set())
            row["source_refs"] = sorted(ref for ref in actual if not any(p.partial.related(graph, other, ref) for other in actual))


def test_completed_before_proves_physical_transition_missing_or_overlap_never_does(case):
    reports = synthetic_full_reports(case[2], case[3]); left, right = physical_transition(case, reports)
    sync_initial_coverage(case, reports)
    assert not checked(case, reports, "physical")["valid"]
    reports["physical"]["temporal_relations"] = [relation(case, left, right, "overlaps")]
    sync_initial_coverage(case, reports)
    assert not checked(case, reports, "physical")["valid"]
    reports["physical"]["temporal_relations"] = [relation(case, left, right)]
    sync_initial_coverage(case, reports)
    assert checked(case, reports, "physical")["accepted"], checked(case, reports, "physical")


def test_unordered_conflicting_writes_cannot_fall_back_to_initial_but_holds_can(case):
    reports = synthetic_full_reports(case[2], case[3]); physical_transition(case, reports, conflicting=True)
    sync_initial_coverage(case, reports)
    assert not checked(case, reports, "physical")["valid"]
    reports = synthetic_full_reports(case[2], case[3]); physical_transition(case, reports, holds=True)
    sync_initial_coverage(case, reports)
    assert checked(case, reports, "physical")["accepted"], checked(case, reports, "physical")


def test_explicit_unproved_precondition_unknown_stops_without_synthetic_completion(case):
    reports = synthetic_full_reports(case[2], case[3]); left, right = physical_transition(case, reports)
    # Both actions remain unresolved; neither asserts a current state change.
    for ref in (left, right):
        row = reports["physical"]["action_checks"][ref]
        row.update(status="unknown", state_changes=[])
        for condition in row["preconditions"]: condition.update(established_by=None, actual_value=None, quote="")
    sync_initial_coverage(case, reports)
    result = bundle(case, reports)
    assert result["valid"] and result["status"] == "halt_review_uncertain" and not result["accepted"], result


def test_original_635_is_rejected_without_response_cleaning(case):
    path = Path(__file__).resolve().parents[1] / "data/production_trials/legal_scoped_text_session_20261015/round_01/call_635_full_review_semantic_01.json"
    original = path.read_bytes(); receipt = json.loads(original)
    reports = synthetic_full_reports(case[2], case[3]); reports["semantic"] = receipt["output"]
    result = checked(case, reports)
    assert not result["valid"] and not result["accepted"]
    assert path.read_bytes() == original and not result["native_response_rewritten"]


def test_explicit_prior_scope_same_body_unknown_and_sha_cannot_create_new_allowance(case):
    inputs, _, v, law = case
    prior = deepcopy(inputs["production_preferences"]["prior_story_scope"])
    prior.update(full_prior_script=deepcopy(v["compiled_script"]), prior_script_sha256=p.digest(v["compiled_script"]))
    reports = synthetic_full_reports(v, law, prior_story_scope=prior)
    kwargs = {"context_sha256": CONTEXTS["semantic"], "goal_contract": v["goal"], "opening_setup": v["opening_setup"], "prior_story_scope": prior}
    result = p.validate_part(reports["semantic"], "semantic", v["compiled_script"], v["brief"], v["plan"], law, **kwargs)
    assert result["valid"] and result["revision_dispatch_blocked"] and result["status"] == "halt_same_story_prior_allowance_exhausted", result
    prior = deepcopy(inputs["production_preferences"]["prior_story_scope"])
    reports = synthetic_full_reports(v, law, prior_story_scope=prior)
    reports["semantic"]["prior_story_relation"]["relation"] = "unknown"
    kwargs["prior_story_scope"] = prior
    result = p.validate_part(reports["semantic"], "semantic", v["compiled_script"], v["brief"], v["plan"], law, **kwargs)
    assert result["valid"] and result["status"] == "halt_prior_story_relation_unknown" and result["revision_dispatch_blocked"], result
    kwargs["prior_story_scope"] = {**prior, "prior_script_sha256": "0" * 64}
    assert not p.validate_part(reports["semantic"], "semantic", v["compiled_script"], v["brief"], v["plan"], law, **kwargs)["valid"]
