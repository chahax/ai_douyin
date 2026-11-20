"""Durable cadence for substantive repair rounds; separate from provider budgets.

Evidence is hashed, completed rounds are idempotent, and every tenth round
blocks further work until its review is recorded. Review ten seals the session.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

VERSION = "creative_counted_execution/v1"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identity(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("evidence must be an existing file")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class CountedExecution:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "EXECUTION.json"
        self.lock = self.root / "EXECUTION.lock"

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.close(fd)
            yield
        finally:
            self.lock.unlink()

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, state):
        state["updated_at_utc"] = _now()
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("x", encoding="utf-8", newline="\n") as out:
            json.dump(state, out, ensure_ascii=False, indent=2)
            out.write("\n")
        tmp.replace(self.path)

    def initialize(self, authorization_path, *, unit="repair_validation_round"):
        if unit != "repair_validation_round":
            raise ValueError("this entry counts substantive repair rounds, not provider calls")
        authorization = _identity(authorization_path)
        with self._locked():
            if self.path.exists():
                state = self.read()
                if state["authorization"] != authorization or state["unit"] != unit:
                    raise ValueError("existing session cannot be reset or rebound")
                return state
            state = {"schema": VERSION, "authorization": authorization, "unit": unit,
                     "review_every_rounds": 10, "maximum_reviews": 10,
                     "maximum_rounds": 100, "rounds": [], "reviews": [],
                     "active_round": None, "status": "ready", "stop_reason": None,
                     "provider_budget_reset": False, "created_at_utc": _now()}
            self._save(state)
            return state

    @staticmethod
    def _guard(state):
        if (state.get("schema") != VERSION or state.get("unit") != "repair_validation_round"
                or state.get("review_every_rounds") != 10 or state.get("maximum_reviews") != 10
                or state.get("maximum_rounds") != 100):
            raise ValueError("original cadence and stop limits must be preserved")
        if _identity(state["authorization"]["path"]) != state["authorization"]:
            raise ValueError("original cadence authorization changed")
        if state.get("unit_confirmation") and _identity(state["unit_confirmation"]["path"]) != state["unit_confirmation"]:
            raise ValueError("unit confirmation changed")
        if ([row["number"] for row in state["rounds"]] != list(range(1, len(state["rounds"]) + 1))
                or [row["number"] for row in state["reviews"]] != list(range(1, len(state["reviews"]) + 1))):
            raise ValueError("round and review history must be contiguous")
        if state["status"] == "stopped":
            raise ValueError("execution stopped: " + str(state["stop_reason"]))
        if len(state["reviews"]) >= 10 or len(state["rounds"]) >= 100:
            raise ValueError("ten-block execution cap reached")
        if len(state["rounds"]) >= state["review_every_rounds"] * (len(state["reviews"]) + 1):
            raise ValueError("review required before further dispatch")

    def begin_round(self, key, objective):
        if not key or not objective.strip():
            raise ValueError("stable key and substantive objective required")
        with self._locked():
            state = self.read()
            self._guard(state)
            if any(row["key"] == key for row in state["rounds"]):
                raise ValueError("completed round cannot restart")
            active = state["active_round"]
            if active:
                if active["key"] == key and active["objective"] == objective:
                    return state
                raise ValueError("another round is active")
            state["active_round"] = {"key": key, "number": len(state["rounds"]) + 1,
                                     "objective": objective, "started_at_utc": _now()}
            state["status"] = "working"
            self._save(state)
            return state

    def confirm_unit(self, confirmation_path):
        evidence = _identity(confirmation_path)
        confirmation = json.loads(Path(evidence["path"]).read_text(encoding="utf-8"))
        with self._locked():
            state = self.read()
            if (confirmation.get("unit") != state["unit"]
                    or confirmation.get("authorization_sha256") != state["authorization"]["sha256"]):
                raise ValueError("confirmation must match the original authorization and unit")
            old = state.get("unit_confirmation")
            if old and old != evidence:
                raise ValueError("unit confirmation cannot be replaced")
            state["unit_confirmation"] = evidence
            state["unit_confirmed"] = True
            self._save(state)
            return state

    def assert_dispatch_allowed(self, round_key):
        state = self.read()
        self._guard(state)
        if not state["active_round"] or state["active_round"]["key"] != round_key:
            raise ValueError("dispatch requires the actual active repair round")
        return state

    def complete_round(self, key, *, action, conclusion, evidence_paths):
        if not action.strip() or not conclusion.strip() or not evidence_paths:
            raise ValueError("actual action, conclusion and saved evidence required")
        evidence = [_identity(path) for path in evidence_paths]
        result = {"action": action, "conclusion": conclusion, "evidence": evidence}
        with self._locked():
            state = self.read()
            old = next((row for row in state["rounds"] if row["key"] == key), None)
            if old:
                if all(old[field] == value for field, value in result.items()):
                    return state
                raise ValueError("completed round evidence is immutable")
            self._guard(state)
            active = state["active_round"]
            if not active or active["key"] != key:
                raise ValueError("only the active round can complete")
            state["rounds"].append({**active, **result, "completed_at_utc": _now()})
            state["active_round"] = None
            state["status"] = "review_due" if len(state["rounds"]) % 10 == 0 else "ready"
            self._save(state)
            return state

    def record_review(self, number, report_path):
        evidence = _identity(report_path)
        with self._locked():
            state = self.read()
            old = next((row for row in state["reviews"] if row["number"] == number), None)
            if old:
                if old["report"] == evidence:
                    return state
                raise ValueError("recorded review cannot be replaced")
            if state["status"] != "review_due" or state["active_round"]:
                raise ValueError("a completed ten-round block is required")
            if number != len(state["reviews"]) + 1 or len(state["rounds"]) != number * 10:
                raise ValueError("reviews must follow exactly ten new rounds")
            state["reviews"].append({"number": number, "through_round": len(state["rounds"]),
                                     "report": evidence, "recorded_at_utc": _now()})
            if number == state["maximum_reviews"]:
                state["status"], state["stop_reason"] = "stopped", "ten_reviews_completed"
            else:
                state["status"] = "ready"
            self._save(state)
            return state

    def stop(self, reason, evidence_path):
        if not reason.strip():
            raise ValueError("explicit stop reason required")
        evidence = _identity(evidence_path)
        with self._locked():
            state = self.read()
            if state["status"] == "stopped":
                return state
            state["status"], state["stop_reason"] = "stopped", reason
            state["stop_evidence"] = evidence
            self._save(state)
            return state
