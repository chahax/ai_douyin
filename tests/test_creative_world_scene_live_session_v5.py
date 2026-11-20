"""Two installed-SDK MockTransport paths and two small pure routing controls.

All outputs and parent certificates here are synthetic, never actual acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_live_session_v5 as m

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"
TEMPLATE = ROOT / "data/production_trials/world_scene_live_20261015/round_02/call_653_complete_script_03.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("real network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(m.base.clients, "role_config", lambda role: SimpleNamespace(
        model=m.base.clients.WRITER_MODEL if role == "writer" else m.base.clients.REVIEW_MODEL,
        base_url="https://api.minimax.cn/v1" if role == "writer" else "https://api.deepseek.com/v1", api_key="offline-only"))


def setup_session(tmp_path, monkeypatch, *, unknown=False):
    scenario = m.read(SCENARIO); inputs, documents = scenario["inputs"], scenario["documents"]
    monkeypatch.setattr(m.base, "PROJECT", tmp_path)
    for name, value in (("CODE", {"offline": True}), ("SOURCE", {"offline": True}), ("PROFILE", scenario["profile"]),
            ("PREFS", inputs["production_preferences"]), ("GOALS", inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1", {"offline": True}), ("USER_COUNT_UNIT_CONFIRMATION_v1", {"offline": True})):
        m.write(tmp_path / (name + ".json"), value, True)
    source = tmp_path / "original_creation"; source.mkdir()
    m.write(source / "INPUTS.json", inputs, True)
    m.write(source / "SESSION_CONFIG.json", {"profile_path": str(tmp_path / "PROFILE.json")}, True)
    goal, setup = documents["whole_plan_01"]["output"], documents["opening_setup_01"]["output"]
    from scripts import creative_world_scene_source_state_audit_v2 as old_audit
    audit_profile = deepcopy(scenario["profile"]); audit_profile["stage_parameters"]["goal_audit"]["max_completion_tokens"] = 32000
    historical = old_audit.prepare(inputs, audit_profile, goal, setup)
    native = {"schema": "OFFLINE historical refused report"}
    decision = {"valid": False, "accepted": False, "findings": [{"code": "OFFLINE_HISTORY_CONTRACT"}],
        "contract_findings": [{"code": "OFFLINE_HISTORY_CONTRACT"}], "uncertainties": [], "status": "source_state_contract_rejected"}
    template = m.read(TEMPLATE)
    def ref(ordinal, label, output, *, request=None, validation=None):
        receipt = deepcopy(template); receipt.update(ordinal=ordinal, label=label, output=deepcopy(output),
            status="contract_rejected" if validation is not None else "contract_valid")
        if request is not None:
            receipt["request"] = deepcopy(request); receipt["request_sha256"] = m.digest(request); receipt["stage"] = request["stage"]
            receipt["response_metadata"].update(requested_model=request["model"], response_model=request["model"])
        if validation is not None: receipt["validation"] = deepcopy(validation)
        path = source / (label + ".json"); m.write(path, receipt, True)
        return {"path": str(path), "file_sha256": m.sha(path), "ordinal": ordinal, "label": label,
            "request_sha256": receipt["request_sha256"], "native_sha256": m.digest(output), "status": receipt["status"]}
    latest = ref(664, "source_state_audit_01", native, request=historical["request"], validation=decision)
    decision_path = source / "OLD_DECISION.json"; m.write(decision_path, decision, True)
    anchor = {"schema": "OFFLINE injected settled664 certificate", "root": str(tmp_path / "typed664"),
        "parent_identity": {"root": str(tmp_path / "typed664"), "end_ordinal": 664}, "creative_source_root": str(source),
        "source_files": {str(source / name): m.sha(source / name) for name in ("INPUTS.json", "SESSION_CONFIG.json")},
        "inherited": {"calls_started": 664, "reported_tokens": 14206125, "calls_with_known_usage": 662,
            "pending_ordinals": [70, 160], "unknown_token_reservations": 93117},
        "native_goal_receipt": ref(645, "whole_plan_02", goal), "native_opening_setup_receipt": ref(650, "opening_setup_01", setup),
        "latest_source_state_audit_receipt": latest, "latest_source_state_audit_decision_ref": {
            "path": str(decision_path), "file_sha256": m.sha(decision_path), "native_sha256": m.digest(decision)},
        "source_state_audit_receipts": [{"offline": True}, latest], "source_state_audit_contract_valid": False,
        "source_state_audit_semantically_accepted": False}
    m.write(tmp_path / "PARENT.json", anchor, True)
    counter = m.base.CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round21", "OFFLINE complete replan closure")
    sent, holder = [], {}
    def builder(request):
        def respond(outgoing):
            label = holder["session"].pending_intent["label"]; sent.append({"label": label, "wire": json.loads(outgoing.read())})
            if unknown: raise httpx.ReadTimeout("OFFLINE unknown; no retry", request=outgoing)
            if label.startswith("source_state_audit"):
                from tests.test_creative_world_scene_source_state_audit_v3 import synthetic_report
                prepared = m.read(holder["session"].pending_intent["path"])["prepared"]
                output = synthetic_report(prepared)
            else:
                key = "opening_setup_01" if label.startswith("opening_setup") else "complete_script_01" if label.startswith("complete_script") else label.rsplit("_", 1)[0] + "_01"
                output = deepcopy(documents[key]["output"])
            body = {"id": "offline-" + label, "model": request["model"], "choices": [{"index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "tool-" + label, "type": "function",
                    "function": {"name": m.base.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]},
                "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            return httpx.Response(200, content=json.dumps(body, ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request, http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(respond), verify=False, **kwargs))
    config = m.Config(str(tmp_path / "run"), "offline-v5-complete-replan", str(tmp_path / "PARENT.json"), m.digest(anchor),
        str(tmp_path / "source"), str(tmp_path / "PREFS.json"), str(tmp_path / "GOALS.json"), str(tmp_path / "PROFILE.json"),
        str(tmp_path / "AUTH.json"), str(tmp_path), "round21", review_admission_module="src.content_factory.creative_full_review_protocol_v6")
    session = m.Session(config, parent_verifier=lambda anchor, **kwargs: {"verified": True,
        "inherited": anchor["inherited"], "source_files": anchor["source_files"]},
        input_builder=lambda *args, **kwargs: {"inputs": deepcopy(inputs), "evidence": {"offline": True}, "source_files": [str(tmp_path / "SOURCE.json")]},
        source_gate=lambda *args, **kwargs: {"valid": True, "current_source_freshness_verified": True},
        client_factory_builder=builder, review_adapter=m.base.workflow.full_reviews())
    holder["session"] = session; monkeypatch.setattr(session, "code_files", lambda: [tmp_path / "CODE.json"])
    preview = session.preview(); m.write(config.authorization_path, session.authorization_template(preview), True)
    session.prepare()  # The real v5 guard/freeze/33 policy is exercised, never replaced.
    return session, sent, scenario


def test_sdk_complete_new_plan_fifth_gate_and_deep_handoff(tmp_path, monkeypatch):
    session, sent, scenario = setup_session(tmp_path, monkeypatch)
    result = session.run(); assert result["status"] == "text_ready_for_director", result
    assert [row["label"] for row in sent] == ["whole_plan_01", "scope_audit_01", "source_audit_01", "commitment_audit_01",
        "drama_audit_01", "opening_setup_01_01", "source_state_audit_01", "complete_script_09", "full_review_semantic_09", "full_review_physical_09"]
    assert m.read(session.root / "PRODUCTION_FREEZE.json")["schema"] == m.VERSION + "/freeze"
    assert result["spend"]["stage_limits"] == m.LIMITS and result["spend"]["effective_calls_started"] == 674
    assert result["spend"]["effective_reported_tokens"] == 14207125
    for row in sent:
        cap = row["wire"].get("max_completion_tokens", row["wire"].get("max_tokens"))
        if row["label"].startswith("source_state"): assert cap == 32000
        elif "_audit_" in row["label"]: assert cap == 16000
    monkeypatch.setattr(m.Session, "open", classmethod(lambda cls, root, **kwargs: session))
    verified = m.verify_text_handoff(session.root)
    assert verified["valid"] and not verified["authorizes_media_dispatch"]
    assert verified["identity"]["source_state_audit_sha256"] == m.digest(m.read(verified["paths"]["source_state_audit"]))
    with pytest.raises(FileExistsError): session.run()


def test_sdk_unknown_single_send_stops_without_downstream_or_handoff(tmp_path, monkeypatch):
    session, sent, _ = setup_session(tmp_path, monkeypatch, unknown=True)
    result = session.run()
    assert result["status"] == "halt_interface_or_unknown" and len(sent) == 1, result
    assert result["spend"]["new_unknown_token_reservations"] > 0
    assert not (session.root / "TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError): session.run()


class RoutingWorkflow:
    """Small logic fixture, deliberately not a production schema/SDK proof."""
    AUDITS = ("scope", "source", "commitment", "drama")
    def __getattr__(self, name):
        if name.startswith("validate_"): return lambda *args, **kwargs: accepted()
        if name.startswith("prepare_"):
            def prepared(*args, **kwargs):
                goal = next((value for value in args if type(value) is dict and "goal_id" in value), {})
                return {"request": {"goal_id": goal.get("goal_id"), "operation": name}, "views": {"goal": goal, "brief": {}, "plan": {}},
                    "scope_context_sha256": "offline", "audit_context_sha256": "offline", "source_authority_context": {},
                    "part_context_sha256": "offline", "review_legal_context": {}}
            return prepared
        raise AttributeError(name)
    def full_reviews(self): return self
    def origin_ids(self, inputs): return {}
    def build_goal_audit_bundle(self, *reports): return {"reports": reports}
    def validate_goal_audit(self, *args, **kwargs): return accepted()
    def validate_script_document(self, native, *args): return {"script": native}
    def seed_feedback(self, goal, setup, native, decision, **kwargs): return {"previous_complete_document": goal, "revision_diagnostics": decision}


def accepted(): return {"valid": True, "accepted": True, "findings": [], "uncertainties": []}


class RoutingDriver(m.Driver):
    def __init__(self, *, contract_failure=False):
        session = SimpleNamespace(seed_feedback=lambda wf: {}, profile={})
        super().__init__(session, None, {"production_preferences": {}}, RoutingWorkflow())
        self.contract_failure = contract_failure; self.labels = []; self.current_plan = 0; self.source_calls = 0
    def invoke(self, label, prepared, validator):
        self.labels.append((label, deepcopy(prepared))); decision = accepted()
        if label.startswith("whole_plan"):
            self.current_plan += 1; native = {"goal_id": self.current_plan}
        elif label.startswith("opening_setup"): native = {"setup_for_goal": self.current_plan}
        elif label.startswith("source_state"):
            self.source_calls += 1; native = {"audit_for_goal": self.current_plan}
            if self.current_plan == 1: decision.update(accepted=False, findings=[{"code": "OFFLINE_SOURCE_STATE_FAIL"}])
        elif label == "scope_audit_01" and self.contract_failure:
            native = {}; decision = {"valid": False, "findings": [{"code": "OFFLINE_REVIEW_PROTOCOL"}]}
        elif label.startswith("complete_script"):
            native = {"body_for_goal": self.current_plan}
            if self.body_used > 1: decision = {"valid": False, "findings": [{"code": "OFFLINE_BODY_CONTRACT"}]}
        elif label.startswith("full_review"):
            native = {"review_for_goal": self.current_plan}; decision.update(accepted=False, requires_new_goal_plan=True,
                findings=[{"code": "OFFLINE_REQUIRES_NEW_GOAL"}])
        else: native = {"audit_for_goal": self.current_plan}
        return native, decision, {"label": label}


def test_source_failure_rebuilds_upstream_and_body_capacity_is_shared_across_plans():
    driver = RoutingDriver()
    with pytest.raises(m.base.Halt, match="halt_live_shared_script_capacity"): driver.flow()
    labels = [label for label, _ in driver.labels]
    assert [label for label in labels if label.startswith("whole_plan")] == ["whole_plan_01", "whole_plan_02", "whole_plan_03"]
    assert [label for label in labels if label.startswith("complete_script")] == ["complete_script_09", "complete_script_10", "complete_script_11"]
    assert labels.index("complete_script_09") > labels.index("source_state_audit_02")
    assert "full_review_physical_09" not in labels
    for plan in (1, 2, 3):
        for kind in RoutingWorkflow.AUDITS:
            prepared = next(value for label, value in driver.labels if label == f"{kind}_audit_{plan:02}")
            assert prepared["request"]["goal_id"] == plan
        assert f"opening_setup_{plan:02}_01" in labels and f"source_state_audit_{plan:02}" in labels
    assert driver.body_used == 3


def test_reviewer_contract_failure_is_not_routed_into_creative_rewrite():
    driver = RoutingDriver(contract_failure=True)
    with pytest.raises(m.base.stages.OfflineStop, match="halt_review_contract"): driver.flow()
    assert [label for label, _ in driver.labels] == ["whole_plan_01", "scope_audit_01"]


def test_wrong_opening_goal_header_stops_without_rewriting_it_or_replanning():
    class WrongOpening(RoutingDriver):
        def invoke(self, label, prepared, validator):
            self.labels.append((label, prepared))
            return {"goal_sha256": "OFFLINE_WRONG"}, {"valid": False, "findings": [{"code": "OFFLINE_HEADER"}]}, {"ordinal": 1}
    driver = WrongOpening()
    with pytest.raises(m.base.Halt, match="halt_opening_feedback_identity_contract") as stopped:
        driver._opening({"goal_id": "OFFLINE"}, 1)
    assert [label for label, _ in driver.labels] == ["opening_setup_01_01"]
    assert stopped.value.details["remaining_setup_attempts"] == 1
    assert stopped.value.details["original_native_modified"] is False
