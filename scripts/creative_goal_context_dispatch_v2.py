"""Independent, durable one-send dispatch for the goal-first text workflow.

The coordinator owns source admission and semantic revision decisions. This
adapter owns immutable request identities, inherited spend, stage capacity and
strict response acceptance. It never constructs a client until after a claim.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, ValidationError

from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_m31_flash_role_clients_v1 as clients
from scripts.creative_call_evidence_v1 import CallEvidenceJournal
from scripts.creative_evidenced_role_clients_v1 import (
    EvidenceCallError, evidence_exception_failure as exception_failure,
)
from src.content_factory.creative_response_contract import (
    fault, response_failure, validation_failure,
)

VERSION = "creative_goal_context_dispatch/v2"
STAGE_ROLES = {"goal_plan": "writer", "goal_audit": "director",
               "complete_script": "writer", "full_review": "director"}
DEFAULT_STAGE_LIMITS = {stage: 3 for stage in STAGE_ROLES}
DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "config/creative_goal_context_model_profile_v2.json"
write, read, digest, sha_file, now, strict_json = (
    control.write, control.read, control.digest, control.sha_file, control.now, control.strict_json,
)


class GoalContextRuntime(control.ContinuationRuntime):
    def __init__(self, project, root, sources, inherited, models=None, *,
                 inherited_guard=lambda: None, profile=None, stage_limits=None,
                 shared_lock=None, quota_state=None, admission=None,
                 client_factory_builder=None):
        self.profile = deepcopy(profile if profile is not None else read(DEFAULT_PROFILE))
        for role in ("writer", "director"):
            clients._official_endpoint(self.profile[role]["base_url"], role)
        expected_models = {role: {key: self.profile[role][key] for key in ("provider", "model", "base_url")}
                           for role in ("writer", "director")}
        if models is not None and models != expected_models:
            raise ValueError("runtime model configs must match the independent profile")
        self.stage_limits = deepcopy(stage_limits if stage_limits is not None else DEFAULT_STAGE_LIMITS)
        if set(self.stage_limits) != set(STAGE_ROLES) or any(
            type(value) is not int or not 0 <= value <= 3 for value in self.stage_limits.values()
        ):
            raise ValueError("explicit per-stage limits must be integers from zero to three")
        self.admission = admission
        self.client_factory_builder = client_factory_builder or (
            lambda request: clients.make_client_factory(request, writer_base_url=self.profile["writer"]["base_url"])
        )
        super().__init__(project, root, sources, inherited, expected_models,
                         inherited_guard=inherited_guard, quota_state=quota_state, shared_lock=shared_lock)
        self.policy_path = self.root / "DISPATCH_POLICY.json"

    def _policy(self):
        return {"schema": VERSION + "/policy", "profile": deepcopy(self.profile),
                "stage_limits": deepcopy(self.stage_limits), "automatic_retry": False,
                "old_budget_reset": False, "media_authorized": False}

    def prepare(self):
        super().prepare()
        with self.lock():
            write(self.policy_path, self._policy(), True)
        return self.summary()

    def check(self, ledger):
        super().check(ledger)
        if self.policy_path.exists():
            if read(self.policy_path) != self._policy():
                raise RuntimeError("independent dispatch policy or stage allowance changed")
        elif ledger["calls"]:
            raise RuntimeError("missing independent dispatch policy; reconcile original claims")
        counts = {stage: 0 for stage in self.stage_limits}
        for row in ledger["calls"]:
            receipt = self.effective_receipt(row)
            if digest(receipt["request"]) != receipt["request_sha256"]:
                raise RuntimeError("stored request identity changed")
            if receipt["source_binding_sha256"] != digest(ledger["source_manifest"]):
                raise RuntimeError("stored source binding changed")
            stage = receipt["request"].get("stage")
            if stage not in counts:
                raise RuntimeError("stored request has an unmapped stage")
            self._request_gate(receipt["request"])
            counts[stage] += 1
        if any(counts[stage] > self.stage_limits[stage] for stage in counts):
            raise RuntimeError("stored stage capacity exceeds the frozen allowance")

    def summary(self):
        current = super().summary()
        ledger = read(self.ledger)
        current["new_unknown_token_reservations"] = current["unknown_token_reservations"]
        current["inherited_unknown_token_reservations"] = self.inherited.get("unknown_token_reservations", 0)
        current["unknown_token_reservations"] += current["inherited_unknown_token_reservations"]
        current["historical_pending_ordinals"] = deepcopy(self.inherited.get("pending_ordinals", []))
        current["new_calls_with_known_usage"] = sum(
            type((self.effective_receipt(row).get("response_metadata") or {}).get("total_tokens")) is int
            and self.effective_receipt(row)["response_metadata"]["total_tokens"] >= 0
            for row in ledger["calls"]
        )
        current["effective_calls_with_known_usage"] = self.inherited.get("calls_with_known_usage", 0) + current["new_calls_with_known_usage"]
        current["stage_calls"] = {stage: sum(self.effective_receipt(row)["request"]["stage"] == stage
                                            for row in ledger["calls"]) for stage in self.stage_limits}
        current["stage_limits"] = deepcopy(self.stage_limits)
        return current

    def _request_gate(self, wire):
        stage = wire.get("stage")
        if stage not in STAGE_ROLES or wire.get("role") != STAGE_ROLES[stage]:
            raise RuntimeError("request stage/role is not mapped by this workflow")
        role = wire["role"]
        if wire.get("model") != self.models[role]["model"]:
            raise RuntimeError("role model changed")
        parameters = deepcopy(self.profile[role]["parameters"])
        override = self.profile.get("stage_parameters", {}).get(stage, {})
        if set(override) - {"max_completion_tokens"}:
            raise RuntimeError("stage profile can only override output allowance")
        parameters.update(override)
        if wire.get("parameters") != parameters:
            raise RuntimeError("request differs from its exact selected stage profile")
        clients.expected_wire_request(wire)
        Draft202012Validator.check_schema(wire["structured_schema"])

    @staticmethod
    def _response_gate(receipt, wire):
        metadata = receipt.get("response_metadata") or {}
        failure = response_failure(metadata, receipt.get("response_text"), require_tool=True)
        if failure:
            return failure
        if (type(metadata.get("http_status_code")) is not int
            or not 200 <= metadata["http_status_code"] < 300
            or metadata.get("response_body_complete") is not True):
            return fault("RESPONSE_EVIDENCE_INCOMPLETE", "interface", "reconcile_original_request", received=True)
        if metadata.get("finish_reason") not in ("stop", "tool_calls"):
            return fault("RESPONSE_NOT_COMPLETED", "interface", "reconcile_original_request", received=True)
        if metadata.get("requested_model") != wire["model"] or metadata.get("response_model") != wire["model"]:
            return fault("MODEL_MISMATCH", "interface", "diagnose_output_protocol", received=True)
        if type(metadata.get("total_tokens")) is not int or metadata["total_tokens"] < 0:
            return fault("USAGE_UNKNOWN", "control", "reconcile_original_usage", received=True)
        return None

    def _validate_output(self, receipt, wire, validator):
        try:
            # Keep diagnostics returned by the local validator, including a
            # semantic rejection that is distinct from wire/schema validity.
            validation = validator(deepcopy(receipt["output"]))
            if validation is None:
                validation = {}
            if not isinstance(validation, dict) or ("valid" in validation and type(validation["valid"]) is not bool):
                raise ValueError("local validator must return a dictionary with boolean validity, or None")
            receipt["validation"] = deepcopy(validation)
            Draft202012Validator(wire["structured_schema"]).validate(receipt["output"])
            if isinstance(validation, dict) and validation.get("valid") is False:
                receipt.update(status="contract_rejected", failure=fault(
                    "MODULE_VALIDATION_REJECTED", "state_contract", "complete_new_response_then_full_validation", received=True),
                    validation_error={"message": "local complete-document validation rejected", "detail": deepcopy(validation)})
            else:
                receipt["status"] = "contract_valid"
                receipt.pop("failure", None)
                receipt.pop("validation_error", None)
        except ValidationError as exc:
            receipt.update(status="contract_rejected", failure=fault(
                "MODULE_SCHEMA_INVALID", "state_contract", "complete_new_response_then_full_validation", received=True),
                validation_error={"message": exc.message, "path": list(exc.absolute_path)})
        except Exception as exc:
            receipt.update(status="contract_rejected", failure=validation_failure(exc),
                           validation_error={"message": str(exc), "detail": deepcopy(getattr(exc, "detail", {}))})
        return receipt

    def dispatch(self, label, wire, validator):
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,90}", label):
            raise ValueError("safe stage label required")
        self._request_gate(wire)
        request_sha = digest(wire)
        with self.lock():
            ledger = read(self.ledger)
            self.check(ledger)
            self.usage(ledger)
            for row in ledger["calls"]:
                original = self.effective_receipt(row)
                if original["request_sha256"] == request_sha:
                    cached = deepcopy(original)
                    if original["status"] in ("contract_valid", "contract_rejected") and self._response_gate(original, wire) is None:
                        if strict_json(original["response_text"]) != original.get("output"):
                            raise RuntimeError("cached output differs from its immutable original response")
                        self._validate_output(cached, wire, validator)
                    cached["cached_response_read_only"] = True
                    cached["provider_called"] = False
                    return cached
                if row["label"] == label:
                    raise RuntimeError("existing label bound to another request; use an explicit complete version")
            for row in ledger["calls"]:
                previous = self.effective_receipt(row)
                if previous["status"] not in ("contract_valid", "contract_rejected"):
                    raise RuntimeError("unaccepted interface or unknown outcome; no new dispatch")
                if self._response_gate(previous, previous["request"]) is not None:
                    raise RuntimeError("unknown/incomplete result or usage; no new dispatch")
                if strict_json(previous["response_text"]) != previous["output"]:
                    raise RuntimeError("stored output differs from the immutable original response")
            stage = wire["stage"]
            stage_count = sum(self.effective_receipt(row)["request"]["stage"] == stage for row in ledger["calls"])
            if stage_count >= self.stage_limits[stage]:
                raise RuntimeError("stage complete-version allowance exhausted")
            if self.admission is not None:
                admission = self.admission(label, deepcopy(wire), deepcopy(ledger))
                if admission is False or (isinstance(admission, dict) and admission.get("allowed") is False):
                    raise RuntimeError("source/stage admission rejected before claim")
            ordinal = self.inherited["calls_started"] + len(ledger["calls"]) + 1
            name = f"call_{ordinal:03}_{label}.json"
            cap = wire["parameters"]["max_completion_tokens"]
            reservation = len(json.dumps(wire, ensure_ascii=False, allow_nan=False)) + cap + 1024
            receipt = {"schema": VERSION, "ordinal": ordinal, "label": label, "stage": stage,
                       "request": deepcopy(wire), "request_sha256": request_sha,
                       "source_binding_sha256": digest(ledger["source_manifest"]),
                       "status": "pending_response", "started_at": now(), "token_reservation": reservation,
                       "automatic_retry": False, "semantic_approval": False}
            write(self.root / name, receipt, True)
            ledger["calls"].append({"ordinal": ordinal, "label": label, "receipt": name,
                                    "token_reservation": reservation, "receipt_sha256": sha_file(self.root / name)})
            write(self.ledger, ledger)
            print(json.dumps({"status": "dispatching", "ordinal": ordinal, "label": label, "stage": stage}), flush=True)
            journal, client_method_entered = None, False
            try:
                journal = CallEvidenceJournal(self.evidence_path(ordinal), self.evidence_identity(receipt))
                client = self.client_factory_builder(deepcopy(wire))()
                parameters = wire["parameters"]
                client_method_entered = True
                result = client.call(wire["role"], wire["messages"], max_tokens=cap,
                                     temperature=parameters["temperature"], thinking=parameters["thinking"],
                                     structured_schema=wire["structured_schema"], evidence=journal)
            except Exception as exc:
                if not client_method_entered and not isinstance(exc, EvidenceCallError):
                    exc = EvidenceCallError("LOCAL_PREFLIGHT_FAILED", started=False, outcome_known=True,
                                            cause_type=type(exc).__name__)
                failure = exception_failure(exc)
                known = failure.get("provider_outcome_known", failure["response_received"])
                status = "blocked_before_dispatch" if getattr(exc, "provider_dispatch_started", None) is False else (
                    "interface_rejected" if known else "outcome_unknown")
                receipt.update(status=status, failure=failure, error=str(exc), completed_at=now())
                if getattr(exc, "response_metadata", None) is not None:
                    receipt.update(response_metadata=exc.response_metadata,
                                   response_text=getattr(exc, "response_text", None),
                                   response_payload=getattr(exc, "response_payload", None))
            else:
                receipt.update(status="response_received", response_metadata=deepcopy(result.metadata),
                               response_text=result.text, response_payload=deepcopy(result.response_payload), completed_at=now())
                # Persist the complete received body metadata before parsing or
                # acceptance, so a local validation crash cannot look unsent.
                write(self.root / name, receipt)
                failure = self._response_gate(receipt, wire)
                if failure:
                    receipt.update(status="interface_rejected", failure=failure)
                else:
                    try:
                        receipt["output"] = strict_json(result.text)
                    except (json.JSONDecodeError, ValueError) as exc:
                        receipt.update(status="interface_rejected", failure=fault(
                            "INVALID_JSON_RESPONSE", "interface", "diagnose_output_protocol", received=True), error=str(exc))
                    else:
                        self._validate_output(receipt, wire, validator)
            if journal is not None:
                receipt["call_evidence"] = {"directory": str(self.evidence_path(ordinal).relative_to(self.root)),
                                            "identity_sha256": journal.identity_sha256}
            write(self.root / name, receipt)
            ledger["calls"][-1]["receipt_sha256"] = sha_file(self.root / name)
            write(self.ledger, ledger)
            write(self.root / "RESULT.json", self.summary())
            return receipt


# A concise alias for coordinators that name their independent adapter Runtime.
Runtime = GoalContextRuntime
