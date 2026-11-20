"""Actual installed SDK with synthetic responses and injected parent certificates.

No real ancestor verification, service judgment, or network occurs in this file.
"""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_source_state_audit_session_v2 as m

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json"
TEMPLATE = ROOT / "data/production_trials/world_scene_live_20261015/round_02/call_653_complete_script_03.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("real network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(m.base.clients, "role_config", lambda role: SimpleNamespace(model=m.base.clients.REVIEW_MODEL,
        base_url="https://api.deepseek.com/v1", api_key="offline-only"))


def setup_session(tmp_path, monkeypatch, *, unknown=False):
    scenario = m.read(SCENARIO); inputs = scenario["inputs"]; documents = scenario["documents"]
    monkeypatch.setattr(m.base, "PROJECT", tmp_path)
    profile = deepcopy(scenario["profile"]); profile["stage_parameters"]["goal_audit"]["max_completion_tokens"] = 32000
    for name, value in (("CODE", {"offline": True}), ("SOURCE", {"offline": True}),
            ("ORIGINAL_PROFILE", scenario["profile"]), ("PROFILE", profile),
            ("PREFS", inputs["production_preferences"]), ("GOALS", inputs["user_goal_contract"]),
            ("AUTHORIZATION_AND_CADENCE_v1", {"offline": True}), ("USER_COUNT_UNIT_CONFIRMATION_v1", {"offline": True})):
        m.write(tmp_path / (name + ".json"), value, True)
    source = tmp_path / "original_creation"; source.mkdir()
    m.write(source / "INPUTS.json", inputs, True)
    m.write(source / "SESSION_CONFIG.json", {"profile_path": str(tmp_path / "ORIGINAL_PROFILE.json")}, True)
    template = m.read(TEMPLATE)
    def ref(ordinal, label, output):
        receipt = deepcopy(template); receipt.update(ordinal=ordinal, label=label, output=deepcopy(output), status="contract_valid")
        path = source / (label + ".json"); m.write(path, receipt, True)
        return {"path": str(path), "file_sha256": m.sha(path), "ordinal": ordinal, "label": label,
            "request_sha256": receipt["request_sha256"], "native_sha256": m.digest(output), "status": "contract_valid"}
    anchor = {"schema": "offline-injected-refused-source-audit-proof", "root": str(tmp_path / "historical663"),
        "creative_source_root": str(source), "parent_identity": {"root": str(tmp_path / "historical663"), "end_ordinal": 663},
        "source_files": {str(source / name): m.sha(source / name) for name in ("INPUTS.json", "SESSION_CONFIG.json")},
        "inherited": {"calls_started": 663, "reported_tokens": 14163272, "calls_with_known_usage": 661,
            "pending_ordinals": [70, 160], "unknown_token_reservations": 93117},
        "native_goal_receipt": ref(645, "whole_plan_02", documents["whole_plan_01"]["output"]),
        "native_opening_setup_receipt": ref(650, "opening_setup_01", documents["opening_setup_01"]["output"]),
        "latest_source_state_audit_receipt": {"offline": True},
        "source_state_audit_scope_accounting": {"used": 1, "limit": 1, "remaining": 0},
        "source_state_audit_contract_valid": False, "source_state_audit_semantically_accepted": False,
        "source_state_audit_profile_path": str(tmp_path / "PROFILE.json"),
        "source_state_audit_profile_file_sha256": m.sha(tmp_path / "PROFILE.json"), "source_state_audit_profile_sha256": m.digest(profile)}
    m.write(tmp_path / "PARENT.json", anchor, True)
    counter = m.base.CountedExecution(tmp_path); counter.initialize(tmp_path / "AUTHORIZATION_AND_CADENCE_v1.json")
    counter.begin_round("round20", "OFFLINE one typed state trace diagnostic")
    sent, outputs, holder = [], [], {}
    def builder(request):
        def respond(outgoing):
            sent.append(json.loads(outgoing.read()))
            if unknown: raise httpx.ReadTimeout("OFFLINE unknown; no retry", request=outgoing)
            from tests.test_creative_world_scene_source_state_audit_v2 import synthetic_report
            prepared = holder["session"]._request(m.read(holder["session"].root / "INPUTS.json"))
            output = synthetic_report(prepared, local_conflict=True)
            outputs.append(deepcopy(output))
            body = {"id": "offline-typed-state-diagnostic", "model": request["model"], "choices": [{"index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-tool", "type": "function",
                    "function": {"name": m.base.clients.TOOL_NAME, "arguments": json.dumps(output, ensure_ascii=False)}}]},
                "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
            return httpx.Response(200, content=json.dumps(body, ensure_ascii=False).encode())
        return m.base.clients.make_client_factory(request, http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(respond), verify=False, **kwargs))
    config = m.Config(str(tmp_path / "run"), "offline-one-typed-source-audit", str(tmp_path / "PARENT.json"), m.digest(anchor),
        str(tmp_path / "source"), str(tmp_path / "PREFS.json"), str(tmp_path / "GOALS.json"), str(tmp_path / "PROFILE.json"),
        str(tmp_path / "AUTH.json"), str(tmp_path), "round20")
    session = m.Session(config, parent_verifier=lambda anchor, **kwargs: {"verified": True,
        "inherited": anchor["inherited"], "source_files": anchor["source_files"]},
        input_builder=lambda *args, **kwargs: {"inputs": deepcopy(inputs), "evidence": {"offline": True},
            "source_files": [str(tmp_path / "SOURCE.json")]},
        source_gate=lambda *args, **kwargs: {"valid": True, "current_source_freshness_verified": True}, client_factory_builder=builder)
    holder["session"] = session; monkeypatch.setattr(session, "code_files", lambda: [tmp_path / "CODE.json"])
    preview = session.preview(); m.write(config.authorization_path, session.authorization_template(preview), True); session.prepare()
    return session, sent, outputs, scenario


def test_known_local_chain_failure_keeps_complete_original_sdk_sql_and_stops(tmp_path, monkeypatch):
    session, sent, outputs, scenario = setup_session(tmp_path, monkeypatch)
    result = session.run()
    assert result["status"] == "diagnostic_completed_known_content_failure", result
    assert len(sent) == len(outputs) == 1 and result["schema"] == m.VERSION + "/state"
    assert not result["text_ready_for_director"] and result["prior_source_state_diagnostics_used"] == 1
    assert m.read(session.root / "NATIVE_SOURCE_STATE_AUDIT.json") == outputs[0]
    decision = m.read(session.root / "SOURCE_STATE_AUDIT_DECISION.json")
    assert decision["valid"] is True and decision["accepted"] is False and decision["findings"]
    assert not decision["uncertainties"]
    assert result["spend"]["stage_limits"] == m.LIMITS and result["spend"]["effective_calls_started"] == 664
    assert result["spend"]["effective_reported_tokens"] == 14163372
    assert result["spend"]["historical_pending_ordinals"] == [70, 160]
    ledger = m.read(session.root / "CALL_LEDGER.json"); reader = m.base.evidence.Reader()
    receipts = [m.base.evidence.verify_original_receipt(session.root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    m.base.evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    assert receipts[0]["status"] == "contract_valid" and receipts[0]["validation"]["accepted"] is False
    assert receipts[0]["output"] == outputs[0]
    payload = json.loads(receipts[0]["request"]["messages"][1]["content"])
    assert payload["native_goal_document"] == scenario["documents"]["whole_plan_01"]["output"]
    assert payload["native_opening_setup_document"] == scenario["documents"]["opening_setup_01"]["output"]
    assert payload["authority_inputs"] == session._request(scenario["inputs"])["views"]["authority_inputs"]
    assert receipts[0]["request"]["parameters"]["max_completion_tokens"] == 32000
    assert not (session.root / "TEXT_HANDOFF.json").exists()
    assert m.read(session.root / "SUMMARY.json")["schema"] == m.VERSION + "/summary"
    with pytest.raises(FileExistsError): session.run()


def test_unknown_one_send_no_native_adoption_or_repeated_run(tmp_path, monkeypatch):
    session, sent, outputs, _ = setup_session(tmp_path, monkeypatch, unknown=True)
    result = session.run()
    assert result["status"] == "halt_interface_or_unknown" and len(sent) == 1, result
    assert outputs == [] and result["spend"]["new_unknown_token_reservations"] > 0
    assert not (session.root / "NATIVE_SOURCE_STATE_AUDIT.json").exists()
    assert not (session.root / "TEXT_HANDOFF.json").exists()
    with pytest.raises(FileExistsError): session.run()
