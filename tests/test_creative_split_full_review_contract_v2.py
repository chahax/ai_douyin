"""Synthetic v2 meaning bindings only; never production or semantic gold.

Every judgement below is fake. Full tables establish evidence provenance and
dispatch conditions, not that an LLM understood the actual Chinese correctly.
"""
from copy import deepcopy
import socket

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_split_full_review_contract_v1 as frozen
from src.content_factory import creative_split_full_review_contract_v2 as split
from src.content_factory import creative_goal_context_workflow_v8 as old_workflow
from tests.test_creative_split_full_review_contract_v1 import fixture as old_fixture
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests import test_goal_context_text_production_v4 as old_helpers

CONTEXTS = {"semantic": "1" * 64, "physical": "2" * 64}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("v2 audit fixtures cannot contact model or media providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def judgement(witness):
    return {"status": "pass", "reason": "合成模型判断，只测试合同，不证明实际语义正确。",
            "required_revision": "", "evidence": [deepcopy(witness)], "counterevidence": []}


def referent(identifier=None, *, label=None):
    return {"kind": "other_entity" if label is not None else "character" if identifier else "unspecified",
            "character_id": identifier, "label": label}


def synthetic_consistency(script, brief, plan, *, goal_contract=None):
    """Private fake-service constructor. Never modifies an original response."""
    catalog = split.build_consistency_evidence_catalog(script, plan, goal_contract=goal_contract)
    entries, targets = catalog["actual_steps"], catalog["target_assertions"]
    beats = {}
    for beat in script["beats"]:
        ref = next(ref for ref, entry in entries.items() if entry["beat_id"] == beat["id"])
        witness = {"source_ref": ref, "quote": entries[ref]["quote"]}
        beats[beat["id"]] = {**judgement(witness), "counterexample_analysis": "合成反证字段，只验证来源与阻断。",
            "target_checks": {target_ref: {**judgement(witness), "target_quote": target["quote"],
                "actual_reading": "合成提取，程序不判定其意思是否正确。"}
                for target_ref, target in targets.items() if target["beat_id"] == beat["id"]}}
    dialogue = {}
    people = brief["constraints"]["allowed_character_ids"]
    for ref, actual in entries.items():
        if actual["kind"] != "dialogue":
            continue
        witness = {"source_ref": ref, "quote": actual["quote"]}
        listener = next((person for person in people if person != actual["speaker"]), None)
        dialogue[ref] = {**judgement(witness), "speaker_id": actual["speaker"], "quote": actual["quote"],
            "listener_id": listener, "listener_mode": "addressed" if listener else "self_talk",
            "quote_attribution": {"mode": "none", "attributed_to": referent(), "quote_fragment": None},
            "propositions": [{"quote": actual["quote"], "agents": [referent(actual["speaker"])],
                "patients": [], "referents": [], "negation": {"mode": "affirmed", "scope_quote": None}}],
            "literal_meaning": "合成字面解释，不是语义金标。", "character_purpose": "合成人物目的。",
            "checks": {key: judgement(witness) for key in
                ("referents", "agent_patient", "negation_scope", "purpose_alignment")}}
    return {"beat_intent_checks": beats, "dialogue_role_checks": dialogue}


def fixture(*, zero_plan=True):
    case, setup, parts = old_fixture(zero_plan=zero_plan)
    for part in parts:
        parts[part]["schema"] = split.VERSION
    parts["semantic"].update(synthetic_consistency(*case[:3]))
    return case, setup, parts


def validate_part(case, setup, parts, part="semantic", *, goal_contract=None):
    return split.validate_part(parts[part], part, *case[:4], context_sha256=CONTEXTS[part],
        opening_setup=setup, goal_contract=goal_contract)


def validate_bundle(case, setup, parts, *, goal_contract=None):
    return split.validate_bundle(split.build_review_bundle(parts["semantic"], parts["physical"]), *case[:4],
        semantic_context_sha256=CONTEXTS["semantic"], physical_context_sha256=CONTEXTS["physical"],
        opening_setup=setup, goal_contract=goal_contract)


def test_synthetic_full_fixture_has_new_exact_coverage_without_quality_claims():
    case, setup, parts = fixture()
    for part in parts:
        schema = split.build_part_schema(part, *case[:4], context_sha256=CONTEXTS[part], opening_setup=setup)
        Draft202012Validator(schema).validate(parts[part])
        result = validate_part(case, setup, parts, part)
        assert result["valid"] and result["accepted"], result
        assert not result["semantic_meaning_programmatically_verified"]
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and result["accepted"], result
    assert result["split_review_contract_version"] == split.VERSION
    assert result["split_review_bundle_version"] == split.BUNDLE_VERSION
    assert result["semantic_review_is_model_judgement"] and not result["creative_quality_passed"]


@pytest.mark.parametrize("part", ["semantic", "physical"])
@pytest.mark.parametrize("field", [*split.SOURCE_HEADERS, "context_sha256", "part", "schema"])
def test_all_six_source_identities_and_part_contexts_remain_exact(part, field):
    case, setup, parts = fixture()
    parts[part][field] = "0" * 64
    assert not validate_part(case, setup, parts, part)["valid"]
    assert not validate_bundle(case, setup, parts)["accepted"]


@pytest.mark.parametrize("change_header", [False, True])
def test_old_v1_native_semantic_response_cannot_be_promoted(change_header):
    case, setup, parts = old_fixture()
    if change_header:
        for part in parts:
            parts[part]["schema"] = split.VERSION
    assert not validate_part(case, setup, parts)["valid"]
    assert not validate_bundle(case, setup, parts)["accepted"]


@pytest.mark.parametrize("table", split.SEMANTIC_TABLES)
@pytest.mark.parametrize("mode", ["missing", "empty", "missing_row", "foreign_row"])
def test_new_tables_require_each_native_beat_and_actual_dialogue(table, mode):
    case, setup, parts = fixture()
    if mode == "missing":
        parts["semantic"].pop(table)
    elif mode == "empty":
        parts["semantic"][table] = {}
    elif mode == "missing_row":
        parts["semantic"][table].pop(next(iter(parts["semantic"][table])))
    else:
        parts["semantic"][table]["OTHER"] = deepcopy(next(iter(parts["semantic"][table].values())))
    assert not validate_bundle(case, setup, parts)["accepted"]


@pytest.mark.parametrize("mode", ["missing_check", "missing_propositions", "partial_line", "wrong_speaker", "other_line_quote"])
def test_each_dialogue_binds_full_original_line_and_all_role_checks(mode):
    case, setup, parts = fixture()
    row = next(iter(parts["semantic"]["dialogue_role_checks"].values()))
    if mode == "missing_check":
        row["checks"].pop("negation_scope")
    elif mode == "missing_propositions":
        row["propositions"] = []
    elif mode == "partial_line":
        row["propositions"][0]["quote"] = row["quote"][:2]
    elif mode == "wrong_speaker":
        row["speaker_id"] = "hr" if row["speaker_id"] != "hr" else "worker"
    else:
        row["propositions"][0]["quote"] = "另一稿的台词"
    assert not validate_part(case, setup, parts)["valid"]


@pytest.mark.parametrize("mode", ["target_id", "target_quote_as_E", "other_script", "later_beat"])
def test_intended_events_and_wrong_script_quotes_cannot_replace_performed_steps(mode):
    case, setup, parts = fixture()
    catalog = split.build_consistency_evidence_catalog(case[0], case[2])
    row = next(iter(parts["semantic"]["beat_intent_checks"].values()))
    target_ref, item = next(iter(row["target_checks"].items()))
    if mode == "target_id":
        item["evidence"] = [{"source_ref": target_ref, "quote": item["target_quote"]}]
    elif mode == "target_quote_as_E":
        # Choose the existing event which is explicitly not in any E text.
        case[0]["beats"][0]["event"] = "只有摘要承诺的事件"
        parts["semantic"]["script_sha256"] = split.reviews.base.base.prior.digest(case[0])
        item["target_quote"] = case[0]["beats"][0]["event"]
        item["evidence"][0]["quote"] = item["target_quote"]
    elif mode == "other_script":
        item["evidence"][0]["quote"] = "来自另一个原生剧本的演出"
    else:
        ref = next(ref for ref, actual in catalog["actual_steps"].items() if actual["beat_id"] == case[0]["beats"][-1]["id"])
        item["evidence"] = [{"source_ref": ref, "quote": catalog["actual_steps"][ref]["quote"]}]
    assert not validate_part(case, setup, parts)["valid"]


@pytest.mark.parametrize("table", split.SEMANTIC_TABLES)
@pytest.mark.parametrize("location", ["top", "child"])
def test_reported_unresolved_counterexample_cannot_hide_under_pass(table, location):
    case, setup, parts = fixture()
    row = next(iter(parts["semantic"][table].values()))
    item = row if location == "top" else next(iter(row["target_checks" if table == "beat_intent_checks" else "checks"].values()))
    item["counterevidence"] = deepcopy(item["evidence"])
    assert not validate_part(case, setup, parts)["valid"]
    assert not validate_bundle(case, setup, parts)["accepted"]


@pytest.mark.parametrize("table", split.SEMANTIC_TABLES)
@pytest.mark.parametrize("status", ["fail", "unknown"])
@pytest.mark.parametrize("target", ["script", "plan"])
def test_native_child_failure_and_uncertainty_block_whole_acceptance(table, status, target):
    case, setup, parts = fixture()
    row = next(iter(parts["semantic"][table].values()))
    item = next(iter(row["target_checks" if table == "beat_intent_checks" else "checks"].values()))
    for value in (item, row):
        value.update(status=status, required_revision="完整新稿或新规划修复明确问题。" if status == "fail" else "")
        value["counterevidence"] = deepcopy(value["evidence"])
    parts["semantic"]["revision_target"] = target if status == "fail" else "none"
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and not result["accepted"], result
    assert result["status"] == ("halt_review_uncertain" if status == "unknown" else
        "halt_full_review_requires_new_complete_goal" if target == "plan" else "needs_whole_revision")
    assert result["requires_new_goal_plan"] == (status == "fail" and target == "plan")


def test_child_failure_cannot_be_omitted_from_top_judgement():
    case, setup, parts = fixture()
    child = next(iter(parts["semantic"]["dialogue_role_checks"].values()))["checks"]["purpose_alignment"]
    child.update(status="fail", required_revision="完整新稿修复字面意思与人物目的的矛盾。")
    assert not validate_part(case, setup, parts)["valid"]


def test_previous_beat_counterevidence_can_report_summary_time_reversal():
    case, setup, parts = fixture()
    catalog = split.build_consistency_evidence_catalog(case[0], case[2])
    row = parts["semantic"]["beat_intent_checks"][case[0]["beats"][1]["id"]]
    target = next(value for ref, value in row["target_checks"].items() if ref.endswith("script.event"))
    earlier_ref = next(iter(catalog["actual_steps"]))
    witness = {"source_ref": earlier_ref, "quote": catalog["actual_steps"][earlier_ref]["quote"]}
    for item in (target, row):
        item.update(status="fail", required_revision="完整新稿解决上一拍已发生、本拍又回到之前的矛盾。", counterevidence=[deepcopy(witness)])
    parts["semantic"]["revision_target"] = "script"
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and not result["accepted"] and result["status"] == "needs_whole_revision"


def test_target_catalog_does_not_change_actual_E_authority_or_sources():
    case, setup, _ = fixture()
    before = deepcopy(case)
    catalog = split.build_consistency_evidence_catalog(case[0], case[2])
    original = split.reviews.base.base.prior.contract.evidence_catalog(case[0])
    assert set(catalog["actual_steps"]) == set(original)
    assert all(entry["authority"] == "target_assertion_only" and entry["document_path"] for entry in catalog["target_assertions"].values())
    for ref, entry in catalog["actual_steps"].items():
        assert entry["authority"] == "actual_performed_step" and entry["quote"] == original[ref]["quote"]
    assert case == before


def test_quoted_opponent_words_with_compound_roles_and_other_entity_are_legal():
    case, setup, parts = fixture()
    ref, row = next(iter(parts["semantic"]["dialogue_role_checks"].items()))
    # Fake-native edit lives only in this synthetic fixture, not a production
    # response. Existing semantic rows are regenerated as fake service output.
    actual = split.reviews.base.base.prior.contract.evidence_catalog(case[0])[ref]
    bi = next(i for i, beat in enumerate(case[0]["beats"]) if beat["id"] == actual["beat_id"])
    si = next(i for i, step in enumerate(case[0]["beats"][bi]["steps"]) if step["text"] == actual["quote"])
    text = "你刚说‘公司不让她来’，我问的是公司要求谁做什么。"
    case[0]["beats"][bi]["steps"][si]["text"] = text
    # Use the unchanged contract provenance guards with a freshly synthetic
    # response; exact old quotations cannot be silently retained.
    for part in parts:
        parts[part]["script_sha256"] = split.reviews.base.base.prior.digest(case[0])
    parts["semantic"].update(synthetic_consistency(*case[:3]))
    row = parts["semantic"]["dialogue_role_checks"][ref]
    row["quote_attribution"] = {"mode": "direct_quote", "attributed_to": referent("hr"), "quote_fragment": "公司不让她来"}
    row["listener_mode"] = "quoted_speech"
    row["propositions"] = [
        {"quote": "你刚说‘公司不让她来’", "agents": [referent("hr"), referent(label="公司")],
         "patients": [referent()], "referents": [referent(label="公司")],
         "negation": {"mode": "negated", "scope_quote": "不让她来"}},
        {"quote": "我问的是公司要求谁做什么。", "agents": [referent("worker"), referent(label="公司")],
         "patients": [referent()], "referents": [referent()], "negation": {"mode": "question", "scope_quote": None}},
    ]
    result = validate_part(case, setup, parts)
    assert result["valid"] and result["accepted"], result


@pytest.mark.parametrize("atom,value", [("holder_character_id", "hr"), ("open", True), ("support_entity_id", "room")])
def test_physical_native_initial_guards_remain_identical(atom, value):
    case, setup, parts = fixture()
    parts["physical"]["action_checks"]["E0001"]["preconditions"] = [{"entity_id": "slip", "state_key": atom,
        "actual_value": value, "expected_value": value, "established_by": "initial:prop:slip", "quote": "没人持有"}]
    assert not validate_part(case, setup, parts, "physical")["valid"]


def test_physical_schema_cannot_receive_semantic_tables_and_keeps_old_rows():
    case, setup, parts = fixture()
    schema = split.build_part_schema("physical", *case[:4], context_sha256=CONTEXTS["physical"], opening_setup=setup)
    old = frozen.build_part_schema("physical", *case[:4], context_sha256=CONTEXTS["physical"], opening_setup=setup)
    old["properties"]["schema"] = schema["properties"]["schema"]
    assert schema == old
    for table in split.SEMANTIC_TABLES:
        parts["physical"][table] = {}
        assert not validate_part(case, setup, parts, "physical")["valid"]
        parts["physical"].pop(table)


def test_complete_semantic_bindings_still_cannot_prove_model_meaning():
    case, setup, parts = fixture()
    row = next(iter(parts["semantic"]["dialogue_role_checks"].values()))
    row["literal_meaning"] = "有意错误的合成字面解释，程序无中文语义推理器，无法凭结构判伪。"
    result = validate_bundle(case, setup, parts)
    assert result["valid"] and result["accepted"]
    assert result["semantic_meaning_programmatically_verified"] is False
    assert result["semantic_review_is_model_judgement"] is True


def test_causal_scenario_keeps_existing_goal_claim_audits_and_only_two_native_beat_targets(causal_scenario):
    inputs, _, goal, setup, _, ids, native = deepcopy(causal_scenario)
    views = old_workflow.compile_native_views(goal, setup, **ids)
    script = old_workflow.prior.prior.legacy.contract.compile_script(native, views["brief"])
    legal = inputs["verified_legal_context"]
    full = old_helpers.full_review({"full_current_script": script, "brief": views["brief"], "creative_scene_plan": views["plan"],
        "native_goal_document": goal, "verified_legal_context": legal})
    full.update(schema=split.reviews.VERSION, opening_setup_sha256=split.reviews.base.base.prior.digest(setup))
    parts = {}
    for part in split.PART_TABLES:
        schema = split.build_part_schema(part, script, views["brief"], views["plan"], legal,
            context_sha256=CONTEXTS[part], goal_contract=goal, opening_setup=setup)
        parts[part] = {key: deepcopy(full[key]) for key in schema["properties"] if key in full}
        parts[part].update(schema=split.VERSION, part=part, context_sha256=CONTEXTS[part], revision_target="none")
    parts["semantic"].update(synthetic_consistency(script, views["brief"], views["plan"], goal_contract=goal))
    result = validate_bundle([script, views["brief"], views["plan"], legal], setup, parts, goal_contract=goal)
    assert result["valid"] and result["accepted"], result
    catalog = split.build_consistency_evidence_catalog(script, views["plan"], goal_contract=goal)
    assert len(catalog["target_assertions"]) == 2 * len(script["beats"])
    assert catalog["source_context"]["goal_contract_sha256"] == split.reviews.base.base.prior.digest(goal)
    assert catalog["source_context"]["plan_sha256"] == split.reviews.base.base.prior.digest(views["plan"])
    for beat in script["beats"]:
        for field in ("event", "trigger"):
            target = catalog["target_assertions"]["T:" + beat["id"] + ":script." + field]
            assert target["quote"] == beat[field]
            assert target["authority"] == "target_assertion_only"
    # Full native planning, claims and scene-goal semantics retain their exact
    # existing contract. They are not duplicated as new beat-target judgements.
    old_schema = frozen.build_part_schema("semantic", script, views["brief"], views["plan"], legal,
        context_sha256=CONTEXTS["semantic"], goal_contract=goal, opening_setup=setup)
    current_schema = split.build_part_schema("semantic", script, views["brief"], views["plan"], legal,
        context_sha256=CONTEXTS["semantic"], goal_contract=goal, opening_setup=setup)
    for table in ("plan_support", "fact_checks", "goal_checks"):
        assert (table in current_schema["properties"]) == (table in old_schema["properties"])
        if table in current_schema["properties"]:
            assert current_schema["properties"][table] == old_schema["properties"][table]


def test_goal_or_plan_field_volume_cannot_increase_native_beat_target_coverage():
    case, _, _ = fixture()
    catalog = split.build_consistency_evidence_catalog(case[0], case[2])
    assert set(catalog["target_assertions"]) == {
        "T:" + beat["id"] + ":script." + field for beat in case[0]["beats"] for field in ("event", "trigger")}
    assert catalog["source_context"]["existing_review_tables"] == ["plan_support", "fact_checks", "goal_checks"]
    assert "泛称写了一行字" in split.REVIEW_RULE


def test_validation_keeps_native_parts_and_inputs_unchanged():
    case, setup, parts = fixture()
    before = deepcopy([case, setup, parts])
    assert validate_bundle(case, setup, parts)["accepted"]
    assert [case, setup, parts] == before
