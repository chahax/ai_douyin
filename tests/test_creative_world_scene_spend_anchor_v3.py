"""Pure accounting against read-only653 receipts; no SDK/claim/network/old writes."""
from copy import deepcopy
import socket
import pytest
from scripts import creative_world_scene_spend_anchor_v3 as m


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("spend certificate tests never use a service")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def records():
    ledger = m.session.read(m.ROOT / "CALL_LEDGER.json")
    config = m.session.read(m.ROOT / "SESSION_CONFIG.json")
    parent = m.session.read(config["parent_anchor_path"])
    receipts = [m.session.read(m.ROOT / row["receipt"]) for row in ledger["calls"]]
    state = m.session.read(m.ROOT / "STATE.json")
    return parent, ledger, receipts, state


def test_actual653_pure_accounting_preserves_history_and_three_exhausted_bodies(records):
    parent, ledger, receipts, state = records
    original = m.digest(records)
    assert m.validate_accounting(*records) == m.EXPECTED
    assert m.digest(records) == original
    assert state["spend"]["new_calls"] == 9 and state["spend"]["new_reported_tokens"] == 280576
    assert m.CONSUMED == {"goal_plan": 3, "goal_audit": 7, "complete_script": 3, "full_review": 0}
    assert m.REMAINING == {"goal_plan": 2, "goal_audit": 5, "complete_script": 0, "full_review": 6}
    assert m.EXPECTED["pending_ordinals"] == [70, 160] and m.EXPECTED["unknown_token_reservations"] == 93117


@pytest.mark.parametrize("fault", ["unknown_usage", "truncated", "missing_call", "duplicate_response", "drop_pending", "revive_body", "adopt_rejected_body", "bool_usage"])
def test_unknown_tamper_omission_or_capacity_reset_cannot_settle(records, fault):
    parent, ledger, receipts, state = deepcopy(records)
    if fault == "unknown_usage": receipts[-1]["response_metadata"]["total_tokens"] = None
    elif fault == "truncated": receipts[-1]["response_metadata"]["finish_reason"] = "length"
    elif fault == "missing_call": ledger["calls"].pop(); receipts.pop()
    elif fault == "duplicate_response": receipts[-1]["response_metadata"]["response_id"] = receipts[0]["response_metadata"]["response_id"]
    elif fault == "drop_pending": parent["inherited"]["pending_ordinals"] = []
    elif fault == "revive_body": state["spend"]["stage_limits"]["complete_script"] = 4
    elif fault == "adopt_rejected_body": receipts[-1]["status"] = "contract_valid"
    else:
        receipts[-1]["response_metadata"]["total_tokens"] = True
        receipts[-1]["response_payload"]["usage"]["total_tokens"] = True
    with pytest.raises((ValueError, m.session.base.Halt)):
        m.validate_accounting(parent, ledger, receipts, state)


def test_anchor_digest_tamper_rejected_before_original_read_or_verification(monkeypatch):
    def deny(): raise AssertionError("wrong anchor SHA must stop before reading original evidence")
    monkeypatch.setattr(m, "build_anchor", deny)
    with pytest.raises(ValueError, match="anchor identity"):
        m.verify_anchor({"schema": m.VERSION, "inherited": m.EXPECTED}, expected_anchor_sha256="0" * 64)
