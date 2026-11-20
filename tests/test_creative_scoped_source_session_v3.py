"""New four-audit entry through offline SDK only; no real grant or providers."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_scoped_source_session_v3 as flow
from src.content_factory import creative_goal_context_workflow_v25 as wf
from src.content_factory.creative_counted_execution_v1 import CountedExecution
from tests.test_creative_fresh_source_session_v1 import offline, causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v24 import case
from tests.test_creative_goal_context_workflow_v25 import bundle as four_bundle
from tests.test_creative_opening_setup_contract_v4 import synthetic_v4
from tests.test_creative_legal_speech_scope_v2 import add_ambiguity
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as full_helpers

REAL = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_disk_durability_claim(monkeypatch, request):
    # Root approved this process-only performance isolation after a real fsync
    # stall. Atomic link/SQL/raw wire/hash checks still run; power-loss durability
    # and the actual production fsync environment are explicitly not tested.
    if not request.node.name.startswith("test_default_fsync_"):
        monkeypatch.setattr(os, "fsync", lambda descriptor: None)


def setup_session(tmp_path, monkeypatch, scenario, *, fault=None):
    inputs, goal, opening, ids, script = case(scenario)
    profile = flow.read(REAL / "config/creative_fresh_source_session_profile_v2.json")
    # Isolate every atomic grant, parent successor and shared dispatch lock.
    monkeypatch.setattr(flow, "PROJECT", tmp_path)
    for module, name in ((flow, "scripts/creative_scoped_source_session_v3.py"),):
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REAL / name).read_bytes()); monkeypatch.setattr(module, "__file__", str(target))
    cli = tmp_path / "scripts/run_creative_scoped_source_session_v3.py"
    cli.write_bytes((REAL / "scripts/run_creative_scoped_source_session_v3.py").read_bytes())
    adapter = SimpleNamespace(**{k: getattr(wf, k) for k in dir(wf) if not k.startswith("__")})
    local_wf = tmp_path / "src/content_factory/creative_goal_context_workflow_v25.py"
    local_wf.parent.mkdir(parents=True, exist_ok=True); local_wf.write_bytes(Path(wf.__file__).read_bytes())
    adapter.__file__ = str(local_wf)
    # Stage-flow fixture only: the actual typed clarification is tested below.
    def planning(value, model_profile):
        built = wf.prepare_goal_request(inputs, model_profile)
        payload = json.loads(built["request"]["messages"][1]["content"])
        payload.update(previous_complete_document=deepcopy(value["previous_complete_document"]),
            revision_diagnostics=deepcopy(value["revision_diagnostics"]))
        built["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False)
        built["wire"] = flow.ordinary.expected_wire_request(built["request"])
        built["request_sha256"] = flow.digest(built["request"]); return built
    adapter.prepare_goal_request = planning
    parent = tmp_path / "parent"; parent.mkdir()
    native_goal = deepcopy(goal); native_goal["whole_plan"]["title"] = "Full original historical native; not adopted"
    def old_receipt(ordinal, output):
        return {"ordinal": ordinal, "request": {"model": flow.ordinary.WRITER_MODEL}, "status": "contract_valid", "output": output,
            "response_metadata": {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls",
                "total_tokens": 100, "output_mode": "tool_call", "requested_model": flow.ordinary.WRITER_MODEL,
                "response_model": flow.ordinary.WRITER_MODEL}}
    goal_path, audit_path = parent / "call_623.json", parent / "call_624.json"
    flow.write(goal_path, old_receipt(623, native_goal)); flow.write(audit_path, old_receipt(624, {"original_uncertainties": 8}))
    flow.write(parent / "INPUTS.json", inputs)
    for name in ("STATE", "CALL_LEDGER", "PRODUCTION_FREEZE"): flow.write(parent / (name + ".json"), {"offline": True})
    identity = {"root": str(parent), "terminal_state_sha256": flow.sha(parent / "STATE.json"),
        "native_ledger_sha256": flow.sha(parent / "CALL_LEDGER.json"),
        "production_freeze_sha256": flow.sha(parent / "PRODUCTION_FREEZE.json"), "end_ordinal": 626}
    inherited = {"calls_started": 626, "reported_tokens": 13079943, "calls_with_known_usage": 624,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    anchor = {"schema": "creative_single_scope_probe_spend_anchor/v2", "root": str(parent), "inherited": inherited,
        "scope_probe_calls_used": 2, "remaining_scope_probe_calls": 0, "whole_goal_candidates_used": 3,
        "terminal_status": "diagnostic_completed_not_creative", "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
        "parent_identity": identity, "parent_identity_sha256": flow.digest(identity),
        "latest_native_goal_receipt": {"root": str(parent), "receipt": goal_path.name, "ordinal": 623,
            "native_goal_sha256": flow.digest(native_goal)},
        "verified_files": {str(p): {"sha256": flow.sha(p)} for p in (goal_path, audit_path, parent / "INPUTS.json")}}
    for name, value in (("ANCHOR", anchor), ("PROFILE", profile), ("PREFERENCES", {}), ("GOALS", {}),
            ("OBSERVATIONS", {"offline": True}), ("AUTHORIZATION_AND_CADENCE_v1", {"offline": True}),
            ("USER_COUNT_UNIT_CONFIRMATION_v1", {"offline": True}), ("SOURCE", {"offline": True})):
        flow.write(tmp_path / (name + ".json"), value)
    counter = CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round8", "offline four-native audit session")
    def build(*a, now): return {"inputs": deepcopy(inputs), "evidence": {"offline": True}, "source_files": [str(tmp_path / "SOURCE.json")]}
    def verify(value, *, expected_anchor_sha256):
        assert flow.digest(value) == expected_anchor_sha256
        return {"verified": True, "inherited": value["inherited"]}
    def clarify(clean, old_goal, old_source, observations):
        return {"inputs": {**deepcopy(clean), "previous_complete_document": deepcopy(old_goal["output"]),
            "revision_diagnostics": {"offline_known_native_clarification": True}}, "manifest": {"offline": True}}
    config = flow.SessionConfig(str(tmp_path / "run"), str(tmp_path / "source"), str(tmp_path / "PREFERENCES.json"),
        str(tmp_path / "GOALS.json"), str(tmp_path / "ANCHOR.json"), flow.digest(anchor), str(tmp_path), "round8", "offline-v3",
        str(tmp_path / "AUTH.json"), profile_path=str(tmp_path / "PROFILE.json"), goal_receipt_path=str(goal_path),
        source_audit_receipt_path=str(audit_path), root_observations_path=str(tmp_path / "OBSERVATIONS.json"))
    seen = []; audits = four_bundle(inputs, goal)
    def factory(request):
        version = request["structured_schema"]["properties"].get("schema", {}).get("const")
        phase = next((kind for kind, v in (("scope", wf.SCOPE_AUDIT_VERSION), ("source", wf.SOURCE_AUDIT_VERSION),
            ("commitment", wf.commitment_audit.VERSION), ("drama", wf.DRAMA_AUDIT_VERSION), ("setup", wf.OPENING_SETUP_VERSION))
            if version == v), request["input_provenance"].get("review_part", request["stage"]))
        if phase == "goal_plan": phase = "plan"
        def respond(outgoing):
            seen.append((phase, json.loads(outgoing.read())))
            p = request["structured_schema"]["properties"]; payload = json.loads(request["messages"][1]["content"])
            if phase == "plan": value = deepcopy(goal)
            elif phase in flow.AUDITS: value = deepcopy(audits["native_" + phase + "_audit"])
            elif phase == "setup": value = deepcopy(opening); value["goal_sha256"] = flow.digest(goal)
            elif phase == "complete_script": value = deepcopy(script)
            else:
                views = wf.compile_native_views(goal, payload["native_opening_setup_document"], **ids)
                compiled = flow.shared.text.contract.compile_script(payload["native_script_document"], views["brief"])
                legal = wf.prepare_full_review_part_request(inputs, profile, payload["native_script_document"], views, phase)["review_legal_context"]
                full = full_helpers.full_review({"full_current_script": compiled, "brief": views["brief"], "creative_scene_plan": views["plan"],
                    "native_goal_document": goal, "verified_legal_context": legal})
                full["opening_setup_sha256"] = flow.digest(views["opening_setup"])
                if phase == "semantic": full.update(synthetic_consistency(compiled, views["brief"], views["plan"], goal_contract=goal))
                value = {k: deepcopy(full[k]) for k in p if k in full}
                for k in ("schema", "part", "context_sha256"): value[k] = p[k]["const"]
                if "revision_target" in p: value["revision_target"] = "none"
            mode = fault.get(phase) if fault else None
            if mode == "transport": raise httpx.ReadTimeout("offline unknown", request=outgoing)
            if mode == "type": value["whole_plan"] = []
            if mode == "scope_u":
                ref = next(k for k in value["records_by_ref"] if k.startswith("G"))
                add_ambiguity(value, wf.scope_audit.evidence.build_evidence_catalog(goal), ref)
            if mode == "contract": value.pop(next(iter(value)))
            if mode == "source_challenge":
                ref, row = next(iter(wf.scope_audit.evidence.build_evidence_catalog(goal).items()))
                value["scope_challenges"] = [{"source_ref": ref, "quote": row["quote"], "kind": "missed_legal_proposition",
                    "candidate_proposition": "Fixture legal scope challenge", "reason": "Must stop; not change original scope"}]
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline", "type": "function",
                "function": {"name": flow.ordinary.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
            if mode == "missing_tool": message = {"role": "assistant", "content": json.dumps(value)}
            response = {"id": "offline-v3-" + str(len(seen)), "model": request["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "length" if mode == "truncated" else "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            return httpx.Response(200, content=json.dumps(response, ensure_ascii=False).encode())
        return flow.ordinary.make_client_factory(request, http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(respond), **kw))
    session = flow.Session(config, workflow_adapter=adapter, clarification_builder=clarify, anchor_verifier=verify,
        input_builder=build, source_gate=lambda *a, **k: {"offline": True}, client_factory_builder=factory)
    return session, inputs, goal, audits, seen, counter


def prepare(session):
    flow.write(session.config.authorization_path, session.authorization_template(session.preview()), True)
    return session.prepare()


def test_nine_real_sdk_calls_four_native_audits_original_scope_receipt_and_machine_handoff(tmp_path, monkeypatch, causal_scenario):
    session, inputs, goal, audits, seen, counter = setup_session(tmp_path, monkeypatch, causal_scenario)
    preview = session.preview(); assert preview["stage_limits"] == flow.LIMITS and not session.root.exists() and not seen
    prepare(session); result = session.run()
    assert result["status"] == "text_ready_for_director", result
    assert [p for p, _ in seen] == ["plan", "scope", "source", "commitment", "drama", "setup", "complete_script", "semantic", "physical"]
    assert result["spend"]["effective_calls_started"] == 635 and result["spend"]["effective_reported_tokens"] == 13080843
    assert result["spend"]["historical_pending_ordinals"] == [70, 160] and result["spend"]["unknown_token_reservations"] == 93117
    handoff = flow.read(session.root / "TEXT_HANDOFF.json"); evidence = handoff["execution_requirement_evidence"]
    assert handoff["native_goal_audit"] == audits and evidence["native_planning_review_count"] == 4
    assert flow.read(evidence["native_scope_receipt_path"])["output"] == audits["native_scope_audit"]
    assert evidence["native_scope_receipt_sha256"] == flow.sha(evidence["native_scope_receipt_path"])
    assert evidence["complete_current_four_review_bundle_verified"] and evidence["same_native_full_review_inputs_verified"]
    assert not result["human_quality_approved"] and not result["creative_quality_passed"] and not handoff["media_authorized"]
    assert result["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    before = (session.root / "CALL_LEDGER.json").read_bytes()
    with pytest.raises(FileExistsError): session.run()
    assert len(seen) == 9 and (session.root / "CALL_LEDGER.json").read_bytes() == before


@pytest.mark.parametrize("phase,mode,status,count", [("plan", "type", "halt_plan4_contract_rejected_no_plan5", 1),
    ("plan", "missing_tool", "halt_protocol_requires_diagnosis", 1), ("plan", "transport", "halt_interface_or_unknown", 1),
    ("plan", "truncated", "halt_interface_or_unknown", 1), ("scope", "scope_u", "halt_goal_scope_requires_author_clarification", 2),
    ("source", "source_challenge", "halt_goal_scope_challenge", 3),
    ("commitment", "contract", "halt_goal_audit_contract_requires_diagnosis", 4)])
def test_known_protocol_unknown_and_scope_gates_stop_without_plan5_or_body(tmp_path, monkeypatch, causal_scenario, phase, mode, status, count):
    session, _, _, _, seen, _ = setup_session(tmp_path, monkeypatch, causal_scenario, fault={phase: mode})
    prepare(session); result = session.run()
    assert result["status"] == status, result
    assert len(seen) == count and not (session.root / "TEXT_HANDOFF.json").exists()
    assert result["spend"]["effective_calls_started"] == 626 + count and not result["spend"]["old_budget_reset"]


def test_raw_goal_metadata_change_rejected_before_claim(tmp_path, monkeypatch, causal_scenario):
    session, inputs, _, _, seen, _ = setup_session(tmp_path, monkeypatch, causal_scenario)
    inputs["user_goal_contract"]["constraints"][0]["source_quote"] += " raw metadata changed"
    def deny(*a, **kw): raise AssertionError("raw same-source gate must run before clarification or model projection")
    monkeypatch.setattr(session, "clarify", deny)
    with pytest.raises(ValueError, match="raw inputs"): session.preview()
    assert not session.root.exists() and not session.claim.exists() and not seen


def test_same_parent_different_anchor_identity_cannot_regrant_plan4(tmp_path, monkeypatch, causal_scenario):
    session, _, _, _, seen, _ = setup_session(tmp_path, monkeypatch, causal_scenario); prepare(session)
    anchor = flow.read(session.config.anchor_path); anchor["verifier_revision"] = "different canonical identity"
    path = tmp_path / "ANCHOR2.json"; flow.write(path, anchor)
    config = replace(session.config, root=str(tmp_path / "other"), grant_id="other", anchor_path=str(path),
        anchor_sha256=flow.digest(anchor), authorization_path=str(tmp_path / "AUTH2.json"))
    other = flow.Session(config, workflow_adapter=session.wf, clarification_builder=session.clarify, anchor_verifier=session.anchor_verifier,
        input_builder=session.input_builder, source_gate=session.source_gate, client_factory_builder=session.client_factory_builder)
    flow.write(config.authorization_path, other.authorization_template(other.preview()), True)
    with pytest.raises(FileExistsError, match="parent already"): other.prepare()
    assert not seen and not other.root.exists()


def test_round_stop_after_taskstore_claim_before_locked_dispatch_has_no_provider(tmp_path, monkeypatch, causal_scenario):
    session, _, _, _, seen, counter = setup_session(tmp_path, monkeypatch, causal_scenario); prepare(session)
    original = flow.shared.tasks.TaskStore.claim
    def stop(*a, **kw):
        value = original(*a, **kw)
        counter.complete_round("round8", action="offline_mock", conclusion="stopped before locked provider dispatch",
            evidence_paths=[session.root / "USER_SCOPE.json"])
        return value
    monkeypatch.setattr(flow.shared.tasks.TaskStore, "claim", stop)
    with pytest.raises(Exception): session.run()
    assert not seen and flow.read(session.root / "STATE.json")["status"] == "halt_execution_exception_requires_reconciliation"
    assert flow.read(session.root / "CALL_LEDGER.json")["calls"] == []
    assert counter.read()["active_round"] is None


def test_actual_body_schema_exact_admission_rejects_version_drift(tmp_path, monkeypatch, causal_scenario):
    session, inputs, goal, audits, seen, _ = setup_session(tmp_path, monkeypatch, causal_scenario)
    prepare(session)
    native = deepcopy(case(causal_scenario)[2]); native["goal_sha256"] = flow.digest(goal)
    rows = []
    for index, (label, value) in enumerate([("whole_plan_04", goal), *[(k + "_audit_04", audits["native_" + k + "_audit"]) for k in flow.AUDITS], ("opening_setup_01", native)]):
        path = session.root / ("fixture_" + str(index) + ".json")
        receipt = flow.read(session.config.goal_receipt_path); receipt.update(output=value, label=label, ordinal=627 + index,
            validation={"valid": True, "accepted": True, "uncertainties": [], "scope_ready_for_authority_review": True})
        flow.write(path, receipt); rows.append({"label": label, "ordinal": receipt["ordinal"], "receipt": path.name})
    ledger = {"calls": rows}; request = wf.prepare_script_request(inputs, session.profile, goal, audits, opening_setup=native, **wf.origin_ids(inputs))["request"]
    assert session._admit("complete_script_01", request, ledger)
    changed = deepcopy(request); changed["structured_schema"]["properties"]["schema"] = {"const": "wrong_version"}
    with pytest.raises(ValueError, match="actual request differs"): session._admit("complete_script_01", changed, ledger)
    assert not seen


def test_actual626_typed_ancestry_finds_original623_624_and_clean_inputs_without_replaying_parent_verifier():
    anchor = flow.read(REAL / "data/qa/creative_scope_single_record_20261015/PROBE626_SPEND_ANCHOR_v1.json")
    root = REAL / "data/production_trials/fresh_source_text_session_20261015/round_02"
    for name in ("call_623_whole_plan_03.json", "call_624_source_audit_03.json", "INPUTS.json"):
        target = root / name; proof = flow.verified_original_file(anchor, target)
        assert proof["sha256"] == flow.sha(target) and len(proof["parent_anchor_files"]) >= 1
        assert str(target) not in anchor["verified_files"]


def test_default_fsync_real_sdk_known_plan_rejection_consumes_once_and_stops(tmp_path, monkeypatch, causal_scenario):
    session, _, _, _, seen, _ = setup_session(tmp_path, monkeypatch, causal_scenario, fault={"plan": "type"})
    prepare(session); result = session.run()
    assert result["status"] == "halt_plan4_contract_rejected_no_plan5" and len(seen) == 1
    ledger = flow.read(session.root / "CALL_LEDGER.json"); receipt = flow.read(session.root / ledger["calls"][0]["receipt"])
    directory = session.root / receipt["call_evidence"]["directory"]
    assert (directory / "request_body.raw").exists() and (directory / "response_body.raw").exists()
    assert receipt["status"] == "contract_rejected" and receipt["response_metadata"]["total_tokens"] == 100
    assert result["spend"]["effective_calls_started"] == 627 and not result["spend"]["old_budget_reset"]


@pytest.mark.parametrize("fault", ["parent_bytes", "canonical", "unknown_schema", "outside", "missing_original"])
def test_ancestry_links_cannot_hide_file_or_contract_drift(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(flow, "PROJECT", tmp_path)
    target = tmp_path / "ORIGINAL.json"; flow.write(target, {"original": True})
    ancestor = {"schema": "creative_session_spend_anchor/v1", "verified_files": {str(target): {"sha256": flow.sha(target)}}}
    path = tmp_path / "PARENT.json"; flow.write(path, ancestor)
    anchor = {"schema": "creative_single_scope_probe_spend_anchor/v2", "parent_anchor_path": str(path),
        "parent_anchor_sha256": flow.digest(ancestor), "verified_files": {str(path): {"sha256": flow.sha(path)}}}
    if fault == "parent_bytes": flow.write(path, {**ancestor, "changed": True})
    elif fault == "canonical": anchor["parent_anchor_sha256"] = "0" * 64
    elif fault == "unknown_schema": ancestor["schema"] = "unreviewed/v9"; flow.write(path, ancestor); anchor.update(parent_anchor_sha256=flow.digest(ancestor)); anchor["verified_files"][str(path)]["sha256"] = flow.sha(path)
    elif fault == "outside": anchor["parent_anchor_path"] = str(tmp_path.parent / "OTHER.json")
    else: flow.write(target, {"original": False})
    with pytest.raises(ValueError): flow.verified_original_file(anchor, target)
