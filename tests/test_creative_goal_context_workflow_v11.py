"""Independent offline request wiring, source identity and native gate review.

The synthetic reports below test reported control flow only. They are never
rewrites of provider responses or semantic, artistic or video quality proofs.
Actual round_10 files are opened read-only and checked for byte preservation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request, M31FlashRoleClients
from src.content_factory import creative_goal_context_workflow_v10 as frozen
from src.content_factory import creative_goal_context_workflow_v11 as workflow
from src.content_factory import creative_split_full_review_contract_v1 as old_split
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_split_full_review_contract_v2 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as old_helpers


PROJECT = Path(__file__).resolve().parents[1]
PROFILE = PROJECT / "config/creative_goal_context_model_profile_v3.json"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("v11 request review may not create clients or contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def synthetic_bundle(inputs, profile, goal):
    """Fresh fake v9 report with the identities of actual prepared requests."""
    source = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    drama = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    judgement = {"status": "pass", "reason": "合成接线报告，程序未证明语义或审美。", "required_revision": ""}
    catalog = workflow.drama_contract.build_evidence_catalog(goal)
    first_g = next(ref for ref in catalog if ref.startswith("G"))
    observation = {**deepcopy(judgement), "evidence_refs": [first_g],
        "counterexample_analysis": "合成比较仅检验原生表及接线，不作为内容金标。", "counterevidence_refs": []}
    checks = {}
    for identifier, item in workflow.drama_contract.build_commitment_usage_catalog(goal).items():
        checked = {key: [usage["evidence_refs"][0]] for key, usage in item["usages"].items()}
        checks[identifier] = {**deepcopy(observation), "claim_ref": item["claim_ref"],
            "evidence_refs": list(dict.fromkeys([item["claim_ref"], *[refs[0] for refs in checked.values()]])),
            "checked_usages": checked}
    return workflow.build_goal_audit_bundle(
        {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
         "audit_context_sha256": workflow.digest(payload(source)),
         "claim_checks": {claim["id"]: deepcopy(judgement) for claim in goal["claims"]}},
        {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
         "audit_context_sha256": workflow.digest(payload(drama)),
         "goal_checks": {key: deepcopy(observation) for key in workflow.GOAL_CHECKS},
         "scope_observations": {beat["id"]: {"audible_speakers": [], "operated_props": []}
                                for beat in goal["whole_plan"]["beats"]},
         "commitment_checks": checks})


@pytest.fixture
def current_case(causal_scenario):
    inputs, _, goal, opening, _, ids, native = deepcopy(causal_scenario)
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    bundle = synthetic_bundle(inputs, profile, goal)
    return inputs, profile, goal, opening, bundle, ids, native


def author(case):
    inputs, profile, goal, opening, bundle, ids, _ = case
    return workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


def synthetic_parts(case):
    """New fake service reports bound to workflow11's final part requests."""
    inputs, profile, goal, opening, _, _, native = case
    views = author(case)["views"]
    script = workflow.validate_script_document(native, views, inputs["production_preferences"])["script"]
    prepared = {part: workflow.prepare_full_review_part_request(inputs, profile, native, views, part)
                for part in workflow.split_reviews.PART_TABLES}
    legal = prepared["semantic"]["review_legal_context"]
    full = old_helpers.full_review({"full_current_script": script, "brief": views["brief"],
        "creative_scene_plan": views["plan"], "native_goal_document": goal, "verified_legal_context": legal})
    full.update(schema=workflow.reviews.VERSION, opening_setup_sha256=workflow.digest(opening))
    reports = {}
    for part, request in prepared.items():
        reports[part] = {key: deepcopy(full[key]) for key in request["request"]["structured_schema"]["properties"] if key in full}
        reports[part].update(schema=workflow.split_reviews.VERSION, part=part,
            context_sha256=request["part_context_sha256"], revision_target="none")
    reports["semantic"].update(synthetic_consistency(script, views["brief"], views["plan"], goal_contract=goal))
    return views, script, prepared, reports


def validate_parts(case, parts):
    views, script, prepared, _ = synthetic_parts(case)
    return workflow.split_reviews.validate_bundle(workflow.split_reviews.build_review_bundle(
        parts["semantic"], parts["physical"]), script, views["brief"], views["plan"],
        prepared["semantic"]["review_legal_context"], semantic_context_sha256=prepared["semantic"]["part_context_sha256"],
        physical_context_sha256=prepared["physical"]["part_context_sha256"],
        goal_contract=views["goal"], opening_setup=views["opening_setup"])


def request_for(case, stage):
    inputs, profile, goal, opening, _, ids, native = case
    if stage == "goal":
        return workflow.prepare_goal_request(inputs, profile)
    if stage == "source":
        return workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    if stage == "drama":
        return workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    if stage == "setup":
        return workflow.prepare_opening_setup_request(inputs, profile, goal)
    if stage == "script":
        return author(case)
    views = workflow.compile_native_views(goal, opening, **ids)
    return workflow.prepare_full_review_part_request(inputs, profile, native, views, stage)


@pytest.mark.parametrize("stage", ["goal", "source", "drama", "setup", "script", "semantic", "physical"])
def test_final_actual_wire_schema_manifest_and_reference_identity(current_case, stage):
    inputs, _, goal, opening, bundle, _, native = current_case
    before = deepcopy(current_case)
    request = request_for(current_case, stage)
    actual = payload(request)
    schema = request["request"]["structured_schema"]
    provenance = request["request"]["input_provenance"]
    assert current_case == before
    assert request["manifest"]["workflow_version"] == provenance["workflow_version"] == workflow.VERSION
    assert request["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert provenance["context_manifest_sha256"] == workflow.digest(request["manifest"])
    assert request["request_sha256"] == workflow.digest(request["request"])
    assert request["wire"] == expected_wire_request(request["request"])
    assert request["wire"]["tools"][0]["function"]["parameters"] == schema
    assert not request["dispatch_performed"] and request["sdk_max_retries"] == 0
    expected_reference_count = 0 if stage in ("source", "setup", "physical") else 1
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == expected_reference_count
    if "reference_proof" in request["manifest"]:
        assert request["manifest"]["reference_proof"]["payload_occurrences"] == expected_reference_count
    else:
        assert request["manifest"]["reference_occurrences"] == expected_reference_count
    if expected_reference_count:
        assert actual["reference_fulltext"] == inputs["reference_fulltext"]
    if stage in ("goal", "setup", "script"):
        assert request["wire"]["model"] == "MiniMax-M3.1-Flash-Preview"
        assert request["wire"]["reasoning_effort"] == "medium"
    else:
        assert request["wire"]["model"] == "deepseek-flash"
        assert request["wire"]["thinking"] == {"type": "disabled"}
        assert request["wire"]["max_tokens"] == (32000 if stage in ("semantic", "physical") else 16000)
    if stage in ("source", "drama"):
        assert schema["properties"]["audit_context_sha256"]["const"] == workflow.digest(actual)
        if stage == "source":
            assert actual["native_goal_claims"] == goal["claims"]
            assert actual["native_goal_sha256"] == workflow.digest(goal)
        else:
            assert actual["native_goal_document"] == goal
    if stage in ("script", "semantic", "physical"):
        assert actual["native_opening_setup_document"] == opening
        assert provenance["native_goal_sha256"] == workflow.digest(goal)
        assert provenance["native_opening_setup_sha256"] == workflow.digest(opening)
    if stage == "script":
        assert provenance["native_goal_audit_bundle_version"] == workflow.BUNDLE_VERSION
        assert provenance["native_drama_audit_sha256"] == workflow.digest(bundle["native_drama_audit"])
    if stage in ("semantic", "physical"):
        assert actual["native_script_document"] == native
        assert schema["properties"]["schema"]["const"] == workflow.split_reviews.VERSION
        assert request["context_sha256"] == request["part_context_sha256"] == workflow.digest(actual)
        assert schema["properties"]["context_sha256"]["const"] == provenance["part_context_sha256"] == workflow.digest(actual)
        assert request["manifest"]["part_context_sha256"] == workflow.digest(actual)
        assert provenance["native_review_part_version"] == request["manifest"]["native_review_part_version"] == workflow.split_reviews.VERSION
        assert actual["same_source_sha256"] == request["same_source_sha256"] == request["manifest"]["same_source_sha256"]
        for key, value in actual["same_source_sha256"].items():
            assert schema["properties"][key]["const"] == value


def test_drama_actual_prompt_catalog_and_schema_allow_commitments_and_keep_own_scope_G(current_case):
    request = request_for(current_case, "drama")
    actual, goal = payload(request), current_case[2]
    system = request["wire"]["messages"][0]["content"]
    assert workflow.COMMITMENT_REVIEW_RULE in system
    assert "全部goal_checks、scope_observations与commitment_checks" in system
    assert "仅提交Schema中的全部goal_checks" not in system
    assert "不提交claim_checks或额外检查" not in system
    assert "scope_observations仍限自身拍G" in system
    catalog = workflow.drama_contract.build_evidence_catalog(goal)
    old_g = workflow.citations.build_evidence_catalog(goal)
    assert {ref: row for ref, row in catalog.items() if ref.startswith("G")} == old_g
    assert actual["goal_evidence_catalog"] == {ref: {"document_path": row["document_path"]} for ref, row in catalog.items()}
    assert actual["creative_commitment_usage_catalog"] == workflow.drama_contract.build_commitment_usage_catalog(goal)
    assert set(actual["creative_commitment_usage_catalog"]) == {"C1"}
    assert set(actual["creative_commitment_usage_catalog"]["C1"]["usages"]) == {"beat:B1", "beat:B2", "ending"}
    schema = request["request"]["structured_schema"]
    assert schema["properties"]["schema"]["const"] == workflow.DRAMA_AUDIT_VERSION
    assert set(schema["properties"]["commitment_checks"]["properties"]) == {"C1"}
    for beat_id, scope in actual["production_scope_catalog"]["beat_scopes"].items():
        row = schema["properties"]["scope_observations"]["properties"][beat_id]
        for table in ("audible_speakers", "operated_props"):
            assert row["properties"][table]["items"]["properties"]["source_ref"]["enum"] == scope["evidence_refs"]
            assert all(ref.startswith("G") for ref in scope["evidence_refs"])
    for field in ("goal_evidence_catalog", "creative_commitment_usage_catalog", "production_scope_catalog", "stage_responsibility_contract"):
        manifests = [row for row in request["manifest"]["field_manifest"] if row["path"] == field]
        assert len(manifests) == 1 and manifests[0]["projected"] == workflow.contexts._measure(actual[field])


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_reported_planning_failure_or_unknown_blocks_bundle_and_author(current_case, status):
    table = "commitment_checks"
    changed = deepcopy(current_case)
    report = changed[4]["native_source_audit" if table == "claim_checks" else "native_drama_audit"]
    row = next(iter(report[table].values()))
    row.update(status=status, required_revision="原生完整新规划修复已报告内容问题。" if status == "fail" else "")
    result = workflow.validate_goal_audit(changed[4], changed[2], inputs=changed[0])
    assert result["valid"] and not result["accepted"]
    assert bool(result["findings"]) == (status == "fail")
    assert bool(result["uncertainties"]) == (status == "unknown")
    with pytest.raises(ValueError, match="must pass"):
        author(changed)


@pytest.mark.parametrize("fault", ["old_bundle", "old_drama", "old_header_only", "commitment_missing"])
def test_old_v8_or_mixed_audit_cannot_become_new_author_authority(current_case, fault):
    changed = deepcopy(current_case)
    bundle, drama = changed[4], changed[4]["native_drama_audit"]
    if fault == "old_bundle":
        bundle["schema"] = frozen.BUNDLE_VERSION
    elif fault == "old_drama":
        drama["schema"] = frozen.DRAMA_AUDIT_VERSION
    elif fault == "old_header_only":
        old = frozen.prepare_goal_drama_audit_request(changed[0], changed[1], changed[2])
        drama["audit_context_sha256"] = workflow.digest(payload(old))
    elif fault == "context":
        drama["audit_context_sha256"] = "f" * 64
    elif fault == "goal":
        drama["goal_sha256"] = "f" * 64
    else:
        drama.pop("commitment_checks")
    with pytest.raises((ValueError, ValidationError)):
        author(changed)


@pytest.mark.parametrize("field", ["reference_fulltext"])
def test_author_recomputes_immutable_source_identity(current_case, field):
    changed = deepcopy(current_case)
    if field == "reference_fulltext":
        changed[0][field] += "\n合成参考变更。"
    elif field == "user_goal_contract":
        changed[0][field]["audience_goals"][0]["text"] += "合成变更。"
    else:
        changed[0][field]["scope"] += "合成变更。"
    with pytest.raises(ValidationError):
        author(changed)


def test_semantic_actual_request_has_only_two_targets_and_exact_utterance_authority(current_case):
    views, script, prepared, parts = synthetic_parts(current_case)
    request, native = prepared["semantic"], current_case[6]
    actual = payload(request)
    catalog = actual["consistency_evidence_catalog"]
    assert len(catalog["target_assertions"]) == 2 * len(native["beats"])
    for index, beat in enumerate(native["beats"]):
        target_refs = {f"T:{beat['id']}:script.event", f"T:{beat['id']}:script.trigger"}
        assert {ref for ref, row in catalog["target_assertions"].items() if row["beat_id"] == beat["id"]} == target_refs
        for field in ("event", "trigger"):
            row = catalog["target_assertions"][f"T:{beat['id']}:script.{field}"]
            assert row["quote"] == beat[field] and row["authority"] == "target_assertion_only"
            assert row["document_path"] == f"native_script_document.beats.{index}.{field}"
    old_e = workflow.split_reviews.reviews.base.base.prior.contract.evidence_catalog(script)
    assert set(catalog["actual_steps"]) == set(actual["evidence_catalog"]) == set(old_e)
    for ref, row in catalog["actual_steps"].items():
        assert row["quote"] == old_e[ref]["quote"] and row["authority"] == "actual_performed_step"
        assert row["document_path"] == actual["evidence_catalog"][ref]["document_path"]
    dialogues = {ref: row for ref, row in old_e.items() if row["kind"] == "dialogue"}
    assert set(parts["semantic"]["dialogue_role_checks"]) == set(dialogues)
    for ref, row in parts["semantic"]["dialogue_role_checks"].items():
        assert row["quote"] == dialogues[ref]["quote"] and row["speaker_id"] == dialogues[ref]["speaker"]
        assert set(row["checks"]) == {"referents", "agent_patient", "negation_scope", "purpose_alignment"}
    Draft202012Validator(request["request"]["structured_schema"]).validate(parts["semantic"])
    assert workflow.SEMANTIC_CONSISTENCY_RULE in request["wire"]["messages"][0]["content"]
    for field in ("review_table_contract", "part_coverage_catalog", "consistency_evidence_catalog"):
        records = [row for row in request["manifest"]["field_manifest"] if row["path"] == field]
        assert len(records) == 1 and records[0]["projected"] == workflow.contexts._measure(actual[field])
    for omitted in ("brief", "creative_scene_plan", "full_current_script"):
        assert omitted not in actual
    assert validate_parts(current_case, parts)["accepted"]
    assert not validate_parts(current_case, parts)["creative_quality_passed"]


def test_physical_actual_request_retains_original_prerequisites_without_full_reference(current_case):
    request = request_for(current_case, "physical")
    old = frozen.prepare_full_review_part_request(current_case[0], current_case[1], current_case[6],
        workflow.compile_native_views(current_case[2], current_case[3], **current_case[5]), "physical")
    actual = payload(request)
    assert "consistency_evidence_catalog" not in actual
    assert "reference_fulltext" not in actual and "verified_legal_context" not in actual
    assert all(table not in actual["review_table_contract"]["required_tables"] for table in workflow.split_reviews.SEMANTIC_TABLES)
    for field in ("compiled_initial_atoms", "initial_evidence_catalog", "evidence_catalog", "same_source_sha256"):
        assert actual[field] == payload(old)[field]
    old_schema = deepcopy(old["request"]["structured_schema"])
    old_schema["properties"]["schema"] = request["request"]["structured_schema"]["properties"]["schema"]
    old_schema["properties"]["context_sha256"] = request["request"]["structured_schema"]["properties"]["context_sha256"]
    assert old_schema == request["request"]["structured_schema"]


@pytest.mark.parametrize("part", ["semantic", "physical"])
@pytest.mark.parametrize("field", ["script_sha256", "context_sha256"])
def test_final_part_native_response_rejects_any_mixed_source_or_context(current_case, part, field):
    _, _, _, parts = synthetic_parts(current_case)
    parts[part][field] = "f" * 64
    result = validate_parts(current_case, parts)
    assert not result["valid"] and not result["accepted"]


@pytest.mark.parametrize("table", workflow.split_reviews.SEMANTIC_TABLES)
@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_actual_part_context_bundle_does_not_hide_new_consistency_failure(current_case, table, status):
    target = "plan" if table == "beat_intent_checks" else "script"
    _, _, _, parts = synthetic_parts(current_case)
    row = next(iter(parts["semantic"][table].values()))
    child = next(iter(row["target_checks" if table == "beat_intent_checks" else "checks"].values()))
    for item in (row, child):
        item.update(status=status, required_revision="提交完整新稿或规划修复已证实矛盾。" if status == "fail" else "")
        item["counterevidence"] = deepcopy(item["evidence"])
    parts["semantic"]["revision_target"] = target if status == "fail" else "none"
    result = validate_parts(current_case, parts)
    assert result["valid"] and not result["accepted"]
    expected = "halt_review_uncertain" if status == "unknown" else "halt_full_review_requires_new_complete_goal" if target == "plan" else "needs_whole_revision"
    assert result["status"] == expected


@pytest.mark.parametrize("fault", ["v1_native", "header_only", "missing_fourth_check", "target_as_E"])
def test_old_or_incomplete_utterance_review_never_passes_actual_request_contract(current_case, fault):
    _, _, _, parts = synthetic_parts(current_case)
    semantic = parts["semantic"]
    first = next(iter(semantic["dialogue_role_checks"].values()))
    if fault in ("v1_native", "header_only"):
        semantic.pop("beat_intent_checks")
        semantic.pop("dialogue_role_checks")
        if fault == "v1_native":
            semantic["schema"] = old_split.VERSION
            parts["physical"]["schema"] = old_split.VERSION
    elif fault == "missing_beat":
        semantic["beat_intent_checks"].pop(next(iter(semantic["beat_intent_checks"])))
    elif fault == "missing_dialogue":
        semantic["dialogue_role_checks"].pop(next(iter(semantic["dialogue_role_checks"])))
    elif fault == "missing_fourth_check":
        first["checks"].pop("purpose_alignment")
    elif fault == "wrong_speaker":
        first["speaker_id"] = "hr" if first["speaker_id"] != "hr" else "worker"
    elif fault == "changed_quote":
        first["quote"] = "别稿原句无法获得当前审查身份。"
    else:
        ref, child = next(iter(next(iter(semantic["beat_intent_checks"].values()))["target_checks"].items()))
        child["evidence"] = [{"source_ref": ref, "quote": child["target_quote"]}]
    assert not validate_parts(current_case, parts)["accepted"]


@pytest.fixture
def actual_round10():
    source = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_10"
    paths = {name: source / name for name in ("INPUTS.json", "goals/native_01.json", "setups/native_01.json", "scripts/version_01/NATIVE_SCRIPT.json",
        "call_563_goal_drama_audit_01.json", "call_566_full_review_semantic_01.json", "call_567_full_review_physical_01.json")}
    before = {name: path.read_bytes() for name, path in paths.items()}
    values = {name: json.loads(raw) for name, raw in before.items()}
    yield values
    assert {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()} == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in before.items()}


def test_real561_commitment_and_real565_utterance_contexts_are_native_and_bounded(actual_round10):
    values = actual_round10
    inputs, goal, opening, native = (values[key] for key in ("INPUTS.json", "goals/native_01.json", "setups/native_01.json", "scripts/version_01/NATIVE_SCRIPT.json"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    before = deepcopy(values)
    drama = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    views = workflow.compile_native_views(goal, opening, **workflow.origin_ids(workflow._planning_authority_inputs(inputs)))
    semantic = workflow.prepare_full_review_part_request(inputs, profile, native, views, "semantic")
    physical = workflow.prepare_full_review_part_request(inputs, profile, native, views, "physical")
    d_payload, s_payload, p_payload = map(payload, (drama, semantic, physical))
    assert d_payload["native_goal_document"] == s_payload["native_goal_document"] == p_payload["native_goal_document"] == goal
    usages = d_payload["creative_commitment_usage_catalog"]
    assert set(usages["CC_FINGER_HOLD"]["usages"]) == {"beat:b1", "beat:b2"}
    assert set(usages["CC_PHOTO_TIMING"]["usages"]) == {"beat:b7"}
    assert "C:CC_FINGER_HOLD" in d_payload["goal_evidence_catalog"] and "C:CC_PHOTO_TIMING" in d_payload["goal_evidence_catalog"]
    catalog = s_payload["consistency_evidence_catalog"]
    assert len(native["beats"]) == 10 and len(catalog["target_assertions"]) == 20
    dialogue = {ref: row for ref, row in catalog["actual_steps"].items() if row["kind"] == "dialogue"}
    assert len(dialogue) == 19
    assert any("厂里不让她上班" in row["quote"] for row in dialogue.values())
    assert any("我要的就是不是你走" in row["quote"] for row in dialogue.values())
    assert set(s_payload["part_coverage_catalog"]["dialogue_role_checks"]) == set(dialogue)
    assert set(s_payload["part_coverage_catalog"]["beat_intent_checks"]) == {beat["id"] for beat in native["beats"]}
    assert len(json.dumps(semantic["request"]["structured_schema"], ensure_ascii=False, separators=(",", ":")).encode()) < 100000
    assert workflow.contexts._reference_occurrences(s_payload, inputs["reference_fulltext"]) == 1
    assert workflow.contexts._reference_occurrences(p_payload, inputs["reference_fulltext"]) == 0
    assert s_payload["same_source_sha256"] == p_payload["same_source_sha256"]
    assert semantic["part_context_sha256"] != physical["part_context_sha256"]
    for request in (drama, semantic, physical):
        assert request["wire"] == expected_wire_request(request["request"])
        assert request["manifest"]["payload_identity"] == workflow.contexts._measure(payload(request))
        assert request["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(request["manifest"])
    with pytest.raises(ValidationError):
        workflow.validate_goal_drama_audit(values["call_563_goal_drama_audit_01.json"]["output"], goal,
            context_sha256=workflow.digest(d_payload))
    for part, request, name in (("semantic", semantic, "call_566_full_review_semantic_01.json"),
                               ("physical", physical, "call_567_full_review_physical_01.json")):
        script = workflow.validate_script_document(native, views, inputs["production_preferences"])["script"]
        result = workflow.split_reviews.validate_part(values[name]["output"], part, script, views["brief"], views["plan"],
            request["review_legal_context"], context_sha256=request["part_context_sha256"], goal_contract=goal, opening_setup=opening)
        assert not result["valid"] and not result["accepted"]
    assert values == before
