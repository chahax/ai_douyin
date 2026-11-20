"""Narrow continuation SDK tests; all parent proofs and responses synthetic."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_live_session_v6 as m

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
    original = tmp_path / "original_creation"; original.mkdir(); current = tmp_path / "v5_source_gate_refusal"; current.mkdir()
    for directory in (original, current):
        m.write(directory / "INPUTS.json", inputs, True)
        m.write(directory / "SESSION_CONFIG.json", {"profile_path": str(tmp_path / "PROFILE.json")}, True)
    template = m.read(TEMPLATE)
    def ref(ordinal, label, output):
        receipt = deepcopy(template); receipt.update(ordinal=ordinal, label=label, output=deepcopy(output), status="contract_valid")
        path = current / (label + ".json"); m.write(path, receipt, True)
        return {"path": str(path), "file_sha256": m.sha(path), "ordinal": ordinal, "label": label,
            "request_sha256": receipt["request_sha256"], "native_sha256": m.digest(output), "status": "contract_valid"}
    anchor = {"schema": "OFFLINE injected settled671 proof", "root": str(current), "creative_source_root": str(original),
        "parent_identity": {"root": str(current), "end_ordinal": 671},
        "source_files": {str(original / name): m.sha(original / name) for name in ("INPUTS.json", "SESSION_CONFIG.json")},
        "inherited": {"calls_started": 671, "reported_tokens": 14447219, "calls_with_known_usage": 669,
            "pending_ordinals": [70, 160], "unknown_token_reservations": 93117},
        "current_text_scope_accounting": {"limits": m.PARENT_LIMITS, "consumed": m.PARENT_USED, "remaining": m.PARENT_REMAINING,
            "calls_used": 7, "calls_remaining": 26, "body_used": 0, "body_limit": 3, "body_versions_available": m.BODY_VERSIONS},
        "current_native_goal_receipt": ref(665, "whole_plan_01", documents["whole_plan_01"]["output"]),
        "current_native_goal_audit_receipts": {kind: ref(666+i, kind + "_audit_01", documents[kind + "_audit_01"]["output"])
            for i, kind in enumerate(m.base.workflow.AUDITS)},
        "current_native_opening_setup_receipt": ref(670, "opening_setup_01_01", documents["opening_setup_01"]["output"])}
    for key, path in (("inputs", current / "INPUTS.json"), ("profile", tmp_path / "PROFILE.json")):
        anchor.update({"current_" + key + "_path": str(path), "current_" + key + "_file_sha256": m.sha(path),
            "current_" + key + "_sha256": m.digest(m.read(path))})
    m.write(tmp_path / "PARENT.json", anchor, True)
    counter = m.base.CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round22", "OFFLINE unused-body continuation")
    sent, holder = [], {}
    def builder(request):
        def respond(outgoing):
            label = holder["session"].pending_intent["label"]; sent.append({"label": label, "wire": json.loads(outgoing.read())})
            if unknown: raise httpx.ReadTimeout("OFFLINE unknown; no retry", request=outgoing)
            if label == "source_state_audit_01":
                from tests.test_creative_world_scene_source_state_audit_v4 import synthetic_report
                prepared = m.read(holder["session"].pending_intent["path"])["prepared"]; output = synthetic_report(prepared)
            else:
                key = "complete_script_01" if label.startswith("complete_script") else label.rsplit("_", 1)[0] + "_01"
                output = deepcopy(documents[key]["output"])
            body = {"id": "offline-" + label, "model": request["model"], "choices": [{"index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "tool-" + label, "type": "function",
                    "function": {"name": m.base.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]},
                "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            return httpx.Response(200, content=json.dumps(body, ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request, http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(respond), verify=False, **kwargs))
    config = m.Config(str(tmp_path / "run"), "offline-v6-unused-body", str(tmp_path / "PARENT.json"), m.digest(anchor),
        str(tmp_path / "source"), str(tmp_path / "PREFS.json"), str(tmp_path / "GOALS.json"), str(tmp_path / "PROFILE.json"),
        str(tmp_path / "AUTH.json"), str(tmp_path), "round22")
    session = m.Session(config, parent_verifier=lambda anchor, **kwargs: {"verified": True,
        "inherited": anchor["inherited"], "source_files": anchor["source_files"]},
        input_builder=lambda *args, **kwargs: {"inputs": deepcopy(inputs), "evidence": {"offline": True}, "source_files": [str(tmp_path / "SOURCE.json")]},
        source_gate=lambda *args, **kwargs: {"valid": True, "current_source_freshness_verified": True}, client_factory_builder=builder)
    holder["session"] = session; monkeypatch.setattr(session, "code_files", lambda: [tmp_path / "CODE.json"])
    preview = session.preview(); m.write(config.authorization_path, session.authorization_template(preview), True); session.prepare()
    return session, sent, scenario


def test_sdk_source4_then_unused_body_double_review_and_original_handoff(tmp_path, monkeypatch):
    session, sent, _ = setup_session(tmp_path, monkeypatch)
    result = session.run(); assert result["status"] == "text_ready_for_director", result
    assert [row["label"] for row in sent] == ["source_state_audit_01", "complete_script_09", "full_review_semantic_09", "full_review_physical_09"]
    assert result["spend"]["stage_limits"] == m.LIMITS and result["spend"]["effective_calls_started"] == 675
    assert result["spend"]["effective_reported_tokens"] == 14447619
    freeze = m.read(session.root / "PRODUCTION_FREEZE.json"); assert freeze["schema"] == m.VERSION + "/freeze"
    scope = m.read(session.root / "USER_SCOPE.json")
    assert scope["whole_plan_limit"] == 0 and scope["parent_scope_calls_remaining"] == 26 and scope["total_new_calls_limit"] == 10
    monkeypatch.setattr(m.Session, "open", classmethod(lambda cls, root, **kwargs: session))
    proof = m.verify_text_handoff(session.root)
    assert proof["valid"] and proof["schema"] == m.VERSION + "/verified_text_handoff"
    assert not proof["authorizes_media_dispatch"]
    assert m.read(proof["paths"]["source_state_audit"])["schema"] == m.SOURCE_VERSION
    assert m.read(session.root / "TEXT_HANDOFF.json")["decision"]["review_admission_version"] == "creative_world_scene_review_admission/v1"
    with pytest.raises(FileExistsError): session.run()


def test_sdk_unknown_source_only_one_send_no_body_or_restart(tmp_path, monkeypatch):
    session, sent, _ = setup_session(tmp_path, monkeypatch, unknown=True); result = session.run()
    assert result["status"] == "halt_interface_or_unknown" and [row["label"] for row in sent] == ["source_state_audit_01"], result
    assert result["spend"]["new_unknown_token_reservations"] > 0
    assert not (session.root / "TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError): session.run()


def test_known_source_content_failure_stops_before_any_body_or_replanning():
    class PureDriver(m.Driver):
        def invoke(self, label, prepared, validator):
            self.labels.append(label)
            return {"schema": "OFFLINE"}, {"valid": True, "accepted": False, "findings": [{"code": "OFFLINE_STATE_FAIL"}], "uncertainties": []}, {}
        def _body(self, *args): raise AssertionError("failed source gate must never enter a body")
    wf = SimpleNamespace(prepare_source_state_audit_request=lambda *args: {}, validate_source_state_audit=lambda *args: None)
    session = SimpleNamespace(profile={}, source_material=lambda wf: {"goal": {}, "setup": {}, "audit_bundle": {}})
    driver = PureDriver(session, None, {}, wf); driver.labels = []
    with pytest.raises(m.base.Halt, match="halt_source_state_content_requires_new_goal"): driver.flow()
    assert driver.labels == ["source_state_audit_01"] and driver.body_used == 0
