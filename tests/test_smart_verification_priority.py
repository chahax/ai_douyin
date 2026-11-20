"""A confirmed search challenge survives later sync errors at scheduler admission."""
import json

import pytest

from src.scheduler import account_refresh as scheduler


@pytest.mark.parametrize("later_error", ["failed", "network_error", "unexpected_error"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_search_verification_pauses_even_when_creator_sync_fails(tmp_path, later_error, confirmed):
    receipt = dict(run_id="maintenance:original", account_key="account01",
        error_code=later_error, failure_stage="published_data_sync",
        blocked_search={"detection": "visible_challenge"},
        challenge_evidence=dict(blocking=True,
            surface_state="challenge_ready" if confirmed else "unconfirmed",
            confirmations=2 if confirmed else 0))
    log = tmp_path / "maintenance.json"
    log.write_text(json.dumps(receipt), encoding="utf8")
    report = dict(maintenance_run_id=receipt["run_id"], maintenance_log=str(log),
                  error_code=later_error)
    code = scheduler._smart_error_code(report, "account01")
    assert code == ("human_required" if confirmed else "verification_ui_unconfirmed")
    path = tmp_path / "schedule.db"
    run = scheduler.claim_smart("acct:one", "account01", reason="functional-test", path=path)
    assert run
    scheduler.finish_smart(run, "failed", {"error_code": code}, path=path)
    controls = scheduler.snapshot(path)["controls"]
    assert controls[0]["state"] == "paused" and controls[0]["error_code"] == code
    assert json.loads(log.read_text()) == receipt  # Original latest sync failure is retained.


def test_other_account_or_original_run_receipt_does_not_pause_this_account(tmp_path):
    log = tmp_path / "other.json"
    log.write_text(json.dumps(dict(run_id="other", account_key="other",
        error_code="human_required", blocked_search={"detection": "visible_challenge"})))
    assert scheduler._smart_error_code(dict(maintenance_log=str(log),
        maintenance_run_id="original", error_code="network_error"), "account01") == "network_error"


def test_original_unknown_outcome_stays_primary_even_with_search_challenge(tmp_path):
    log = tmp_path / "unknown.json"
    log.write_text(json.dumps(dict(run_id="original", account_key="account01",
        error_code="outcome_unknown", blocked_search={"detection": "visible_challenge"},
        challenge_evidence={"blocking": True, "surface_state": "challenge_ready", "confirmations": 2})))
    assert scheduler._smart_error_code(dict(maintenance_log=str(log),
        maintenance_run_id="original"), "account01") == "outcome_unknown"
