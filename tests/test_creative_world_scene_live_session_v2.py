"""Settled644 inputs are read-only; only synthetic roots/SDK transport are used."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
from types import SimpleNamespace
import httpx
import pytest

from scripts import creative_world_scene_live_session_v2 as m

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "data/production_trials/world_scene_live_20261015/round_01"
QA = ROOT / "data/qa/creative_world_scene_live_20261015"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("real network not authorized in continuation tests")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(m.base.clients, "role_config", lambda role: SimpleNamespace(
        model=m.base.clients.WRITER_MODEL if role == "writer" else m.base.clients.REVIEW_MODEL,
        base_url="https://api.minimax.cn/v1" if role == "writer" else "https://api.deepseek.com/v1", api_key="offline-only"))


def seed():
    goal = m.read(OLD / "call_641_whole_plan_01.json")["output"]
    receipt = m.read(OLD / "call_644_commitment_audit_01.json")
    feedback = m.planning_feedback(goal, {"commitment": receipt["output"]}, {"commitment": receipt["validation"]}, "commitment")
    return goal, receipt, feedback


def test_actual644_full_native_failed_rows_once_and_correct_original_budget(tmp_path):
    goal, receipt, feedback = seed(); inputs = m.read(OLD / "INPUTS.json")
    original = {name: m.sha(OLD / name) for name in ("call_641_whole_plan_01.json", "call_644_commitment_audit_01.json", "RUN_CLAIM.json", "STATE.json")}
    rows = feedback["native_failed_rows"]
    assert set(rows) == {"commitment_checks.CC_TRADE", "commitment_checks.CC_SOBER_MOMENT"}
    assert all(row == receipt["output"]["commitment_checks"][path.split(".")[-1]] for path, row in rows.items())
    assert feedback["complete_native_report_sha256"] == m.digest(receipt["output"])
    assert "citations" not in feedback and "complete_failed_native_report" not in feedback
    profile = m.read(QA / "LIVE_PROFILE_v1.json")
    prepared = m.base.workflow.prepare_goal_request({**deepcopy(inputs), "previous_complete_document": goal,
        "revision_diagnostics": feedback}, profile)
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert payload["previous_complete_document"] == goal and payload["revision_diagnostics"] == feedback
    assert prepared["manifest"]["payload_identity"]["characters"] <= 100000
    assert prepared["manifest"]["payload_identity"]["utf8_bytes"] <= 300000
    assert m.base.workflow.contexts._reference_occurrences(payload, inputs["reference_fulltext"]) == 1
    # Reproduce old oversized feedback solely for measurement, never dispatch.
    reports, decisions = {}, {}
    for kind, ordinal in (("scope", 642), ("source", 643), ("commitment", 644)):
        r = m.read(OLD / f"call_{ordinal}_{kind}_audit_01.json")
        reports[kind], decisions[kind] = r["output"], r["validation"]
    old = {**deepcopy(inputs), "previous_complete_document": goal,
        "revision_diagnostics": {"complete_current_goal_reviews": reports, "decisions": decisions}}
    with pytest.raises(ValueError, match="context exceeds"):
        m.base.workflow.prepare_goal_request(old, profile)
    old["context_policy"] = {"max_payload_characters": 1000000, "max_payload_utf8_bytes": 3000000}
    measured = m.base.workflow.prepare_goal_request(old, profile)
    proof = {"classification": "read-only actual641/644 source projection, no model call",
        "old_actual_payload": measured["manifest"]["payload_identity"], "new_actual_payload": prepared["manifest"]["payload_identity"],
        "original_budget": {"max_payload_characters": 100000, "max_payload_utf8_bytes": 300000},
        "whole_previous_goal_sha256": m.digest(goal), "failed_native_report_sha256": m.digest(receipt["output"]),
        "failed_rows": list(rows), "original_files_sha256": original, "native_goal_modified": False, "budget_raised_in_actual_request": False}
    m.write(tmp_path / "ACTUAL_FEEDBACK_SIZE_PROOF.json", proof, True)
    m.write(tmp_path / "ACTUAL_COMPACT_REQUEST_PREVIEW.json", prepared, True)
    assert all(m.sha(OLD / name) == sha for name, sha in original.items())


def test_unknown_or_not_failed_review_is_never_compacted_into_repair():
    goal, receipt, _ = seed()
    for changed in ({**receipt["validation"], "uncertainties": [{"reason": "unknown"}]},
                    {**receipt["validation"], "valid": False}, {**receipt["validation"], "accepted": True}):
        with pytest.raises(ValueError): m.planning_feedback(goal, {"commitment": receipt["output"]}, {"commitment": changed}, "commitment")


def test_original_remaining_scope_no_plan01_or_global_stage_reset(tmp_path, monkeypatch):
    assert m.REMAINING == {"goal_plan": 4, "goal_audit": 9, "complete_script": 3, "full_review": 6}
    assert m.TOTAL_REMAINING == 22 and sum(m.CONSUMED.values()) == 4
    session = object.__new__(m.Session); session.root = tmp_path
    with pytest.raises(ValueError, match="planning version"):
        session._admit("whole_plan_01", {"stage": "goal_plan"}, {"calls": []})
    rows = []
    for i in range(4):
        name = f"fake_scope_only_{i}.json"; m.write(tmp_path / name, {"request": {"stage": "goal_plan"}}, True)
        rows.append({"receipt": name})
    with pytest.raises(ValueError, match="global original"):
        session._admit("whole_plan_03", {"stage": "goal_plan"}, {"calls": rows})


def test_frozen_authoritative_remaining_scope_cannot_be_replaced_by_original26(tmp_path, monkeypatch):
    anchor = m.read(QA / "SETTLED644_SPEND_ANCHOR_v1.json")
    session = object.__new__(m.Session); session.root = tmp_path
    session.config = SimpleNamespace(parent_anchor_path=str(QA / "SETTLED644_SPEND_ANCHOR_v1.json"), parent_anchor_sha256=m.digest(anchor))
    scope = {"schema": m.VERSION + "/derived_authorization", "stage_limits": deepcopy(m.REMAINING),
        "original_scope_stage_limits": deepcopy(m.ORIGINAL_LIMITS), "previous_scope_stage_calls": deepcopy(m.CONSUMED),
        "total_new_calls_limit": 22, "original_total_call_limit": 26, "whole_plan_versions_available": [2, 3],
        "parent_anchor_sha256": m.digest(anchor), "original_scope_root": anchor["root"], "inherited": anchor["inherited"],
        "continuation_is_new_authority": False}
    # Isolate the additional v2 semantic gate, after base hash guards succeeded.
    monkeypatch.setattr(m.base.Session, "_guard", lambda self: True)
    m.write(tmp_path / "USER_SCOPE.json", scope, True); assert session._guard()
    for key, value in (("stage_limits", m.ORIGINAL_LIMITS), ("total_new_calls_limit", 26), ("whole_plan_versions_available", [1, 2, 3])):
        m.write(tmp_path / "USER_SCOPE.json", {**deepcopy(scope), key: value})
        with pytest.raises(ValueError, match="scope differs"): session._guard()


def test_new_driver_starts02_and_rechecks_all_four_audits_not_old_pass_certificates():
    goal, _, feedback = seed()
    class WF:
        AUDITS = m.base.workflow.AUDITS
        digest = staticmethod(m.digest)
        def prepare_goal_request(self, current, profile):
            assert current["previous_complete_document"] == goal
            assert current["revision_diagnostics"] == feedback
            return {"request": {"stage": "goal_plan"}}
        def __getattr__(self, name):
            if name.startswith("prepare_goal_"): return lambda *a: {"scope_context_sha256": "s", "audit_context_sha256": "a", "source_authority_context": {}}
            if name.startswith("validate_goal_"): return lambda *a, **k: {"valid": True, "accepted": True, "findings": [], "uncertainties": []}
            if name == "build_goal_audit_bundle": return lambda *a: {"new_four": list(a)}
            raise AttributeError(name)
    class D(m.Driver):
        def invoke(self, label, prepared, validator):
            self.labels.append(label)
            if label.startswith("whole_plan"): return goal, {"valid": True}, {}
            return {"OFFLINE": label}, {"valid": True, "accepted": True, "findings": [], "uncertainties": []}, {}
    driver = object.__new__(D); driver.wf = WF(); driver.inputs = {}; driver.profile = {}; driver.labels = []
    driver.session = SimpleNamespace(seed_feedback=lambda: {"previous_complete_document": goal, "revision_diagnostics": feedback})
    actual, bundle = driver._planning()
    assert actual == goal and len(bundle["new_four"]) == 4
    assert driver.labels == ["whole_plan_02", "scope_audit_02", "source_audit_02", "commitment_audit_02", "drama_audit_02"]


def test_sdk_unknown_first_continuation_is645_only_and_cannot_restart(tmp_path, monkeypatch):
    cfg = m.Config(**m.read(QA / "LIVE_CONFIG_v1.json"))
    anchor = m.read(QA / "SETTLED644_SPEND_ANCHOR_v1.json")
    cfg = replace(cfg, root=str(tmp_path / "run"), grant_id="offline644-continuation", authorization_path=str(tmp_path / "AUTH.json"),
        parent_anchor_path=str(QA / "SETTLED644_SPEND_ANCHOR_v1.json"), parent_anchor_sha256=m.digest(anchor),
        counter_root=str(tmp_path / "counter"), round_key="round15", extra_source_files=())
    m.write(tmp_path / "counter/AUTHORIZATION_AND_CADENCE_v1.json", {"OFFLINE": True}, True)
    m.write(tmp_path / "counter/USER_COUNT_UNIT_CONFIRMATION_v1.json", {"OFFLINE": True}, True)
    counter = m.base.CountedExecution(cfg.counter_root); counter.initialize(Path(cfg.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round15", "OFFLINE continuation guard validation")
    sent = []
    def builder(request):
        def handler(outgoing):
            sent.append(json.loads(outgoing.read()))
            raise httpx.ReadTimeout("OFFLINE unknown; never repeat", request=outgoing)
        return m.base.clients.make_client_factory(request, http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), verify=False, **kw))
    session = m.Session(cfg, parent_verifier=lambda value, **k: {"verified": True, "inherited": value["inherited"], "source_files": {}},
        client_factory_builder=builder)
    session.claim = tmp_path / "grant/CLAIM.json"
    monkeypatch.setattr(m.base.policy, "successor_paths", lambda *a: [tmp_path / "successor1.json", tmp_path / "successor2.json"])
    monkeypatch.setattr(session, "code_files", lambda: [Path(m.__file__)])
    preview = session.preview(); assert preview["first_request_label"] == "whole_plan_02"
    m.write(cfg.authorization_path, session.authorization_template(preview), True)
    session.prepare(); result = session.run()
    assert result["status"] == "halt_interface_or_unknown" and len(sent) == 1
    ledger = m.read(session.root / "CALL_LEDGER.json")
    assert ledger["calls"][0]["ordinal"] == 645 and ledger["calls"][0]["label"] == "whole_plan_02"
    assert result["spend"]["stage_limits"] == m.REMAINING
    assert result["spend"]["historical_pending_ordinals"] == [70, 160]
    with pytest.raises(FileExistsError): session.run()
