"""Exercise the production coordinator/runtime through the real SDK serializer.

HTTP is MockTransport and credentials are inert test values. Unlike the runner
unit fixture, the capability proof and raw bodies are emitted by actual hooks.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from scripts import run_creative_capability_production_v5 as runner
from scripts import creative_bounded_format_role_clients_v1 as bounded
from tests.test_creative_capability_production_v5 import setup, no_network


REAL_FACTORY = runner.clients.make_client_factory


def real_sdk_harness(tmp_path, monkeypatch, *, timeout=False):
    h = setup(tmp_path, monkeypatch)
    h.sdk_requests = []
    monkeypatch.setattr(bounded, "role_config", lambda role: SimpleNamespace(
        **h.lineage["models"][role], api_key="offline-sdk-runtime-only"))

    def factory(request):
        def service(outgoing):
            body = json.loads(outgoing.read())
            h.sdk_requests.append(deepcopy(body))
            if timeout:
                raise httpx.ReadTimeout("offline original outcome unknown", request=outgoing)
            inputs = json.loads(body["messages"][1]["content"])
            if request["stage"] == "whole_direction":
                native = deepcopy(h.native)
            elif request["stage"] == "local_performance":
                native = deepcopy(h.performances[int(inputs["current_direction"]["segment_id"][1:]) - 1]["native"])
            else:
                assert request["stage"] == "whole_production_review"
                native = {"checks": [{"check": key, "status": "pass", "source_refs": ["B1.S01"],
                    "reason": "离线SDK接线证据；不证明创作质量"} for key in runner.old.PRODUCTION_CHECKS],
                    "revision_requirements": [], "review_limitations": ["素材与媒体未验收"]}
            if "output_transport" in request:
                native = {"payload_json": json.dumps(native, ensure_ascii=False)}
            response = {"id": "offline-sdk-" + str(len(h.sdk_requests)), "model": request["model"],
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [{"id": "offline-tool",
                        "type": "function", "function": {"name": "submit_creative_json",
                            "arguments": json.dumps(native, ensure_ascii=False)}}]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
            return httpx.Response(200, json=response)

        def http_factory(**kwargs):
            return httpx.Client(transport=httpx.MockTransport(service), **kwargs)
        return REAL_FACTORY(request, http_client_factory=http_factory)

    monkeypatch.setattr(runner.clients, "make_client_factory", factory)
    return h


def test_full_chain_real_sdk_wire_proofs_gate_actual_handoff(tmp_path, monkeypatch):
    h = real_sdk_harness(tmp_path, monkeypatch)
    result = runner.execute()
    assert result["complete_text_handoff_ready"], result
    assert len(h.sdk_requests) == result["new_calls"] == 4
    assert result["effective_reported_tokens"] == 7886888
    proofs = runner.old.control.read(h.root / "ACTUAL_REQUEST_PROOF.json")
    assert len(proofs) == 4
    assert all(row["actual_capability_preflight_binding_verified"] and
        row["actual_request_body_binding_verified"] and row["actual_serialized_reference_equal"] for row in proofs)
    assert h.sdk_requests[-1]["model"] == "deepseek-flash"
    assert "max_tokens" in h.sdk_requests[-1] and "max_completion_tokens" not in h.sdk_requests[-1]
    assert all(body["model"] == "MiniMax-M3" and "max_completion_tokens" in body for body in h.sdk_requests[:-1])
    assert runner.execute() == result and len(h.sdk_requests) == 4
    assert result["historical_unknown_calls"] == [70, 160] and result["new_video_calls"] == 0


def test_real_sdk_timeout_preserves_original_claim_and_does_not_redispatch(tmp_path, monkeypatch):
    h = real_sdk_harness(tmp_path, monkeypatch, timeout=True)
    result = runner.execute()
    assert result["status"] == "needs_attention" and not result["complete_text_handoff_ready"]
    assert len(h.sdk_requests) == result["new_calls"] == 1
    ledger = runner.old.control.read(h.root / "CALL_LEDGER.json")
    receipt = runner.runtime().effective_receipt(ledger["calls"][0])
    assert receipt["failure"]["provider_outcome_known"] is False
    assert result["historical_unknown_token_reservations"] == 93117
    assert runner.execute() == result and len(h.sdk_requests) == 1
    assert (h.root / "COORDINATOR_RESULT.json").is_file()
    assert not (h.root / "DELIVERABLE").exists()
