"""Four-native workflow wiring; synthetic audits are never production passes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import creative_goal_context_workflow_v25 as w
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from tests.test_creative_goal_context_workflow_v24 import case
from tests.test_creative_goal_context_workflow_v23 import offline as historical_fixture_clock
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v15 import synthetic_focused
from tests.test_creative_legal_speech_scope_v2 import synthetic_scope, add_ambiguity, add_assertion
from tests.test_creative_scoped_source_review_v2 import synthetic_review

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("workflow25 is offline only")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def profile():
    return json.loads((PROJECT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))


def payload(prepared): return json.loads(prepared["request"]["messages"][1]["content"])


def bundle(inputs, goal):
    scoped = synthetic_scope(goal)
    prepared_source = w.prepare_goal_scoped_source_request(inputs, profile(), goal, scoped)
    source = synthetic_review(goal, scoped, prepared_source["scoped_source_context"])
    drama_request = w.prepare_goal_drama_audit_request(inputs, profile(), goal)
    commitment_request = w.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    first = next(ref for ref in w.drama_contract.build_evidence_catalog(goal) if ref.startswith("G"))
    row = {"status": "pass", "reason": "Synthetic protocol fixture only", "required_revision": "", "evidence_refs": [first],
        "counterexample_analysis": "Synthetic source comparison only", "counterevidence_refs": []}
    drama = {"schema": w.DRAMA_AUDIT_VERSION, "goal_sha256": w.digest(goal),
        "audit_context_sha256": w.digest(payload(drama_request)), "goal_checks": {key: deepcopy(row) for key in w.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in w.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": []}
    focused = synthetic_focused(w.project_inputs(inputs), goal)
    focused["audit_context_sha256"] = w.digest(payload(commitment_request))
    return w.build_goal_audit_bundle(scoped, source, focused, drama)


def assert_wire(prepared, inputs):
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == w.digest(prepared["request"])
    assert prepared["manifest"]["workflow_version"] == w.VERSION
    assert prepared["manifest"]["payload_identity"] == w.contexts._measure(payload(prepared))
    assert prepared["manifest"]["structured_schema_sha256"] == w.digest(prepared["request"]["structured_schema"])
    assert prepared["manifest"]["requirement_ownership"] == w.ownership_evidence(inputs)
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == w.digest(prepared["manifest"])
    assert prepared["sdk_max_retries"] == 0 and prepared["server_schema_guarantee"] is False
    assert prepared["dispatch_performed"] is False


def test_four_actual_native_requests_bundle_and_body_without_old_audit_conversion(causal_scenario, monkeypatch):
    inputs, goal, opening, ids, native = case(causal_scenario)
    original = deepcopy((inputs, goal, opening, native))
    audits = bundle(inputs, goal)
    def deny(*a, **k): raise AssertionError("old source6/three-native admission must not be used")
    monkeypatch.setattr(w.prior, "validate_goal_audit", deny)
    monkeypatch.setattr(w.prior.prior, "validate_goal_audit", deny)
    monkeypatch.setattr(w.source_audit.legal, "validate_source", deny)
    decision = w.validate_goal_audit(audits, goal, inputs=inputs)
    assert decision["accepted"] and decision["four_native_audits_bound"] and not decision["old_source6_report_created"]
    assert not decision["creative_quality_passed"] and not decision["semantic_truth_deterministically_proven"]
    authored = w.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **ids)
    beats = authored["request"]["structured_schema"]["properties"]["beats"]
    beat_ids = [row["id"] for row in goal["whole_plan"]["beats"]]
    assert beats["minItems"] == beats["maxItems"] == len(beat_ids)
    assert beats["items"]["properties"]["id"] == {"enum": beat_ids}
    prov = authored["request"]["input_provenance"]
    for kind in ("scope", "source", "commitment", "drama"):
        assert prov["native_" + kind + "_audit_sha256"] == w.digest(audits["native_" + kind + "_audit"])
    assert prov["goal_audit_sha256"] == w.digest(audits) and prov["native_goal_audit_bundle_version"] == w.BUNDLE_VERSION
    raw_contract = w.original_user_goal_contract(inputs)
    model_contract = payload(authored)["user_goal_contract"]
    assert sum(len(raw_contract[t]) for t in ("constraints", "audience_goals")) == 10
    assert sum(len(model_contract[t]) for t in ("constraints", "audience_goals")) == 8
    assert model_contract == w._fixed_legal_context(inputs)["user_goal_contract"]
    assert "UC_COMPLETE_NATIVE" not in payload(authored)["origin_catalog"]["user"]
    assert {r["id"] for r in model_contract["execution_requirements"]} == {"UC_COMPLETE_NATIVE", "UC_REFERENCE_MECHANISM", "UC_AUTONOMOUS_NATIVE"}
    requests = [w.prepare_goal_request(inputs, profile()), w.prepare_goal_scope_request(inputs, profile(), goal),
        w.prepare_goal_scoped_source_request(inputs, profile(), goal, audits["native_scope_audit"]),
        w.prepare_goal_commitment_audit_request(inputs, profile(), goal), w.prepare_goal_drama_audit_request(inputs, profile(), goal),
        w.prepare_opening_setup_request(inputs, profile(), goal), authored]
    requests.extend(w.prepare_full_review_part_request(inputs, profile(), native, authored["views"], part)
        for part in ("semantic", "physical"))
    for prepared in requests: assert_wire(prepared, inputs)
    assert payload(requests[0])["reference_fulltext"] == inputs["reference_fulltext"]
    assert requests[0]["manifest"]["reference_occurrences"] == authored["manifest"]["reference_occurrences"] == 1
    assert "替代新三审" not in requests[0]["wire"]["messages"][0]["content"]
    assert requests[0]["wire"]["messages"][0]["content"].count(w.FOUR_AUDIT_RULE) == 1
    assert "verified_legal_context" not in payload(requests[1]) and "source_packet" not in payload(requests[1])
    assert payload(requests[2])["verified_legal_context"] == w._fixed_legal_context(inputs)["verified_legal_context"]
    assert (inputs, goal, opening, native) == original


@pytest.mark.parametrize("fault", ["scope_goal", "source_goal", "scope_context", "source_context", "source_scope_sha",
    "commitment_goal", "drama_context", "missing_scope", "old_bundle", "case_batch"])
def test_cross_native_context_missing_and_old_bundle_cannot_admit_body(causal_scenario, fault):
    inputs, goal, opening, ids, _ = case(causal_scenario); audits = bundle(inputs, goal)
    if fault == "scope_goal": audits["native_scope_audit"]["input_sha256"] = "0" * 64
    elif fault == "source_goal": audits["native_source_audit"]["native_goal_sha256"] = "0" * 64
    elif fault == "scope_context": audits["native_scope_audit"]["scope_context_sha256"] = "0" * 64
    elif fault == "source_context": audits["native_source_audit"]["audit_context_sha256"] = "0" * 64
    elif fault == "source_scope_sha": audits["native_source_audit"]["scope_native_sha256"] = "0" * 64
    elif fault == "commitment_goal": audits["native_commitment_audit"]["goal_sha256"] = "0" * 64
    elif fault == "drama_context": audits["native_drama_audit"]["audit_context_sha256"] = "0" * 64
    elif fault == "missing_scope": audits.pop("native_scope_audit")
    elif fault == "old_bundle": audits["schema"] = w.prior.BUNDLE_VERSION
    else: audits["native_scope_audit"]["frame_kind"] = "case_batch"
    with pytest.raises((ValueError, ValidationError)): w.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **ids)


@pytest.mark.parametrize("fault", ["scope_true_u", "source_unknown", "legal_unknown", "scope_challenge", "provenance_fail", "drama_fail"])
def test_native_fail_unknown_and_challenge_block_body_without_local_repair(causal_scenario, fault):
    inputs, goal, opening, ids, _ = case(causal_scenario); audits = bundle(inputs, goal)
    if fault == "scope_true_u":
        ref = next(k for k in audits["native_scope_audit"]["records_by_ref"] if k.startswith("G"))
        add_ambiguity(audits["native_scope_audit"], w.scope_audit.evidence.build_evidence_catalog(goal), ref)
    elif fault in ("source_unknown", "provenance_fail"):
        row = next(iter(audits["native_source_audit"]["claim_checks"].values()))
        row.update(status="unknown" if fault == "source_unknown" else "fail", required_revision="" if fault == "source_unknown" else "Complete new native plan")
    elif fault == "legal_unknown":
        row = audits["native_source_audit"]["legal_observations"][0]["usages"][0]
        row.update(basis_relation="unknown", authority_refs=[])
    elif fault == "scope_challenge":
        ref, row = next(iter(w.scope_audit.evidence.build_evidence_catalog(goal).items()))
        audits["native_source_audit"]["scope_challenges"] = [{"source_ref": ref, "quote": row["quote"],
            "kind": "missed_legal_proposition", "candidate_proposition": "Synthetic scope challenge only", "reason": "Requires original scope recheck"}]
    else: audits["native_drama_audit"]["goal_checks"]["concrete_conflict"].update(status="fail", required_revision="Complete new native plan")
    before = deepcopy(audits)
    with pytest.raises((ValueError, ValidationError)): w.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **ids)
    assert audits == before


def test_current_authority_changes_invalidate_only_matching_source_context(causal_scenario):
    inputs, goal, opening, ids, _ = case(causal_scenario); audits = bundle(inputs, goal)
    changed = deepcopy(inputs); changed["source_packet"]["limitations"].append("new source boundary")
    with pytest.raises((ValueError, ValidationError)): w.prepare_script_request(changed, profile(), goal, audits, opening_setup=opening, **ids)
    changed = deepcopy(inputs); goal["whole_plan"]["premise"] += "Different current native whole plan"
    with pytest.raises((ValueError, ValidationError)): w.prepare_script_request(changed, profile(), goal, audits, opening_setup=opening, **ids)


@pytest.mark.parametrize("stage", ["scope", "source", "body"])
@pytest.mark.parametrize("fault", ["law_drift", "missing_narrative"])
def test_ownership_and_fixed_legal_sources_still_admitted_before_every_new_stage(causal_scenario, stage, fault):
    inputs, goal, opening, ids, _ = case(causal_scenario); audits = bundle(inputs, goal)
    if fault == "law_drift": next(r for r in goal["claims"] if r["kind"] == "verified_legal")["text"] += "删去原条件"
    else: next(r for r in goal["claims"] if r.get("origin_ids") == ["UC_NARRATIVE_ACTION"])["origin_ids"] = ["UC_REFERENCE_MECHANISM"]
    actions = {"scope": lambda: w.prepare_goal_scope_request(inputs, profile(), goal),
        "source": lambda: w.prepare_goal_scoped_source_request(inputs, profile(), goal, audits["native_scope_audit"]),
        "body": lambda: w.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **ids)}
    with pytest.raises(ValueError): actions[stage]()


def test_actual623_full_native132_request_is_lossless_and_not_actual_review_adoption():
    root = PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_02"
    goal = json.loads((root / "call_623_whole_plan_03.json").read_text("utf8"))["output"]
    inputs = json.loads((root / "INPUTS.json").read_text("utf8"))
    prepared = w.prepare_goal_scope_request(inputs, profile(), goal)
    assert prepared["manifest"]["source_ref_count"] == 132
    assert w.evidence_view.reconstruct_goal(payload(prepared)["native_goal_evidence_view"]) == goal
    assert prepared["manifest"]["native_goal_reconstruction_verified"]
    assert prepared["request"]["structured_schema"]["properties"]["frame_kind"] == {"const": "native_goal"}
    assert prepared["production_dispatch_eligible"] is False


def test_body_revisions_keep_complete_script_while_old_goal_clarification_is_not_a_script(causal_scenario):
    inputs, goal, opening, ids, native = case(causal_scenario); audits = bundle(inputs, goal)
    revised = {**deepcopy(inputs), "previous_complete_document": native, "revision_diagnostics": {"known_complete_body_failure": "fixture only"}}
    authored = w.prepare_script_request(revised, profile(), goal, audits, opening_setup=opening, **ids)
    assert payload(authored)["previous_complete_document"] == native
    assert payload(authored)["revision_diagnostics"] == revised["revision_diagnostics"]
    # Only exercise the downstream frame distinction; this is no valid author
    # clarification package and must not be sent through goal preparation.
    old_goal_context = {**deepcopy(inputs), "previous_complete_document": goal,
        "revision_diagnostics": {"schema": w.CLARIFICATION_FRAME, "offline_frame_distinction_only": True}}
    first_body = w.prepare_script_request(old_goal_context, profile(), goal, audits, opening_setup=opening, **ids)
    assert "previous_complete_document" not in payload(first_body) and "revision_diagnostics" not in payload(first_body)


def test_scoped_legal_creative_choice_has_evidence_duty_but_ordinary_positions_do_not(causal_scenario):
    inputs, goal, opening, ids, _ = case(causal_scenario); audits = bundle(inputs, goal)
    scoped = audits["native_scope_audit"]
    ordinary = {ref for ref, row in scoped["records_by_ref"].items() if row["act"] in "FRPMN"}
    assert ordinary.isdisjoint({r["source_ref"] for r in audits["native_source_audit"]["legal_observations"]})
    assert set(audits["native_source_audit"]["claim_checks"]) == {r["id"] for r in goal["claims"]}
    creative = next("C:" + r["id"] for r in goal["claims"] if r["kind"] == "creative_choice")
    add_assertion(scoped, w.scope_audit.evidence.build_evidence_catalog(goal), creative)
    source_request = w.prepare_goal_scoped_source_request(inputs, profile(), goal, scoped)
    audits["native_source_audit"] = synthetic_review(goal, scoped, source_request["scoped_source_context"])
    assert w.validate_goal_audit(audits, goal, inputs=inputs)["accepted"]
    audits["native_source_audit"]["legal_observations"] = [r for r in audits["native_source_audit"]["legal_observations"] if r["source_ref"] != creative]
    with pytest.raises((ValueError, ValidationError)):
        w.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **ids)


def test_source_request_is_identical_across_python_hash_seeds(causal_scenario):
    inputs, goal, _, _, _ = case(causal_scenario); scoped = synthetic_scope(goal)
    content = json.dumps({"inputs": inputs, "goal": goal, "scope": scoped, "profile": profile()}, ensure_ascii=False)
    code = ("import json,sys;from src.content_factory import creative_goal_context_workflow_v25 as w;"
        "v=json.load(sys.stdin);p=w.prepare_goal_scoped_source_request(v['inputs'],v['profile'],v['goal'],v['scope']);"
        "print(p['request_sha256'])")
    results = []
    for seed in (1, 2):
        # Child needs no account/configuration environment. Explicit UTF-8 is
        # necessary on Windows; never place inherited environment in failures.
        environment = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "PYTHONHASHSEED": str(seed), "PYTHONIOENCODING": "utf-8"}
        child = subprocess.run([sys.executable, "-c", code], input=content, encoding="utf-8", capture_output=True,
            cwd=PROJECT, env=environment, check=False)
        assert child.returncode == 0, child.stderr[-1500:]
        results.append(child.stdout.strip())
    assert results[0] == results[1]


def test_actual_known_clarification_keeps_full623_full624_and_r01_once_in_real_request(monkeypatch):
    from src.content_factory import creative_known_native_clarification_v1 as clarification
    from tests.test_creative_known_native_clarification_v1 import count_object, count_text
    root = PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_02"
    read = lambda p: json.loads(p.read_text("utf8"))
    inputs, receipt, historical = [read(root / n) for n in ("INPUTS.json", "call_623_whole_plan_03.json", "call_624_source_audit_03.json")]
    observations = read(PROJECT / "data/qa/creative_source624_diagnosis_20261015/ROOT_NATIVE623_CONTENT_RISKS_v1.json")
    revised = clarification.build_revision_inputs(inputs, receipt, historical, observations)
    def deny(*a, **k): raise AssertionError("known author clarification must not enter old structural feedback projection")
    monkeypatch.setattr(w.contracts, "_project_goal_revision_feedback", deny)
    prepared = w.prepare_goal_request(revised["inputs"], profile()); actual = payload(prepared)
    assert count_object(actual, receipt["output"]) == count_object(actual, historical["output"]) == 1
    assert count_text(actual, inputs["reference_fulltext"]) == 1
    assert actual["previous_complete_document"] == receipt["output"]
    assert actual["revision_diagnostics"] == revised["inputs"]["revision_diagnostics"]
    assert actual["verified_legal_context"] == w._fixed_legal_context(inputs)["verified_legal_context"]
    assert actual["user_goal_contract"] == w._fixed_legal_context(inputs)["user_goal_contract"]
    assert prepared["manifest"]["known_native_clarification"] == revised["manifest"]
    assert prepared["manifest"]["structural_feedback_compiler_used"] is False
    rule = prepared["wire"]["messages"][0]["content"]
    assert "上一完整稿是失败修订证据" not in rule and "旧失败原文" not in rule and "替代新三审" not in rule
    assert rule.count(clarification.RULE) == rule.count(w.FOUR_AUDIT_RULE) == 1
    assert_wire(prepared, inputs)
    changed = deepcopy(revised["inputs"]); changed["revision_diagnostics"]["historical_source_audit"]["schema"] = "pretend_passed"
    with pytest.raises((ValueError, ValidationError)): w.prepare_goal_request(changed, profile())
