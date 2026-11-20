"""Read-only barrier against reusing budget spent by external text diagnostics."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


SHARED_DIAGNOSTIC_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "data" / "production_trials" / "_shared_text_diagnostics"
)
LEDGER_SCHEMA = "creative_shared_text_diagnostic/v1"
CALL_STATUSES = frozenset({
    "pending_response", "response_received", "interface_rejected",
    "validation_rejected", "contract_validated", "outcome_unknown",
})


class SharedDiagnosticSpendError(RuntimeError):
    """The model transport has not been started when this barrier rejects."""
    provider_dispatch_started = False


def _canonical_parent(run_dir: str | Path) -> str:
    return os.path.normcase(str(Path(run_dir).resolve()))


def shared_diagnostic_root(run_dir: str | Path) -> Path:
    """Return the shared registry location without creating or modifying it."""
    identity = hashlib.sha256(_canonical_parent(run_dir).encode("utf-8")).hexdigest()[:24]
    return SHARED_DIAGNOSTIC_DIRECTORY / identity


def assert_no_unreconciled_diagnostic_spend(run_dir: str | Path) -> None:
    """Block a frozen workflow until diagnostic reservations are reconciled.

    Existing workflow state cannot by itself know about external diagnostic
    calls. Even successful calls require reconciliation before that old state
    may be used again. This function never clears a reservation or resets budget.
    """
    try:
        canonical_parent = _canonical_parent(run_dir)
        ledger_path = shared_diagnostic_root(run_dir) / "CALL_LEDGER.json"
        try:
            ledger_path.lstat()
        except FileNotFoundError:
            return
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(ledger, dict) or ledger.get("schema") != LEDGER_SCHEMA:
            raise ValueError("invalid ledger schema")
        parent = ledger.get("parent_run")
        if not isinstance(parent, str) or not Path(parent).is_absolute():
            raise ValueError("ledger parent must be absolute")
        if _canonical_parent(parent) != canonical_parent:
            raise ValueError("ledger parent differs from workflow")
        calls = ledger.get("calls")
        if not isinstance(calls, list):
            raise ValueError("ledger calls must be a list")
        for item in calls:
            if not isinstance(item, dict):
                raise ValueError("invalid call reservation")
            if type(item.get("ordinal")) is not int or item["ordinal"] not in (22, 23, 24):
                raise ValueError("invalid shared call ordinal")
            if item.get("status") not in CALL_STATUSES:
                raise ValueError("invalid shared call status")
            reservation = item.get("token_reservation")
            if type(reservation) is not int or reservation < 0:
                raise ValueError("invalid token reservation")
            if not isinstance(item.get("response_metadata"), dict):
                raise ValueError("invalid response metadata")
    except (OSError, ValueError, TypeError, UnicodeError):
        raise SharedDiagnosticSpendError(
            "共享文本诊断账本无法安全读取；必须核对共享实际预算后才能派发模型请求"
        ) from None
    if calls:
        raise SharedDiagnosticSpendError(
            "共享文本诊断账本已有预留调用；必须核对共享实际预算，不能重用冻结 state 的剩余额度"
        )