"""One typed state-trace diagnostic, retaining the settled v1 refusal unchanged.

The common storage/SDK/TaskStore proof is reused explicitly.  This independent
scope does not authorize a creative draft, repair the old audit, or make media.
"""
from copy import deepcopy
import importlib
import json

from scripts import creative_world_scene_source_state_audit_session_v1 as prior

VERSION = "creative_world_scene_source_state_audit_session/v2"
AUDIT_VERSION = "creative_world_scene_source_state_audit/v2"
Config, LIMITS, LABEL = prior.Config, deepcopy(prior.LIMITS), prior.LABEL
base = prior.base
read, write, digest, sha = prior.read, prior.write, prior.digest, prior.sha


class Runtime(prior.Runtime):
    def _policy(self):
        value = super()._policy()
        value.update(schema=VERSION + "/runtime_policy", native_audit_version=AUDIT_VERSION,
            prior_source_state_diagnostics_used=1, prior_source_state_diagnostics_limit=1,
            prior_source_state_contract_accepted=False, new_diagnostic_calls_limit=1,
            previous_audit_is_not_repaired=True)
        return value


class Session(prior.Session):
    def __init__(self, *args, audit_module=None, **kwargs):
        module = audit_module or importlib.import_module("scripts.creative_world_scene_source_state_audit_v2")
        super().__init__(*args, audit_module=module, **kwargs)

    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module(
            "scripts.creative_world_scene_source_audit_spend_anchor_v1").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
        used = anchor.get("source_state_audit_scope_accounting", {})
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited")
                or not anchor.get("creative_source_root")
                or used.get("used") != 1 or used.get("limit") != 1 or used.get("remaining") != 0
                or anchor.get("source_state_audit_contract_valid") is not False
                or anchor.get("source_state_audit_semantically_accepted") is not False
                or type(anchor.get("latest_source_state_audit_receipt")) is not dict):
            raise ValueError("settled original refused source audit required; no admission or old scope reset")
        prior.creative_root(anchor)
        return anchor, checked

    def _profile_gate(self):
        profile = super()._profile_gate()
        anchor = read(self.config.parent_anchor_path)
        path = base._inside(anchor["source_state_audit_profile_path"])
        if (sha(path) != anchor["source_state_audit_profile_file_sha256"]
                or digest(profile) != anchor["source_state_audit_profile_sha256"] or profile != read(path)):
            raise ValueError("same original32k DeepSeek audit profile must be retained exactly")
        return profile

    def _request(self, inputs=None):
        prepared = super()._request(inputs)
        request = prepared["request"]
        if (request.get("input_provenance", {}).get("source_state_audit_version") != AUDIT_VERSION
                or request.get("structured_schema", {}).get("properties", {}).get("schema", {}).get("const") != AUDIT_VERSION):
            raise ValueError("only the native typed state-trace v2 request is admitted")
        return prepared

    def preview(self):
        value = super().preview()
        value.update(schema=VERSION + "/preview", native_audit_version=AUDIT_VERSION,
            prior_source_state_diagnostics_used=1, prior_source_state_contract_accepted=False,
            profile_changed_from_parent_audit=False, prior_audit_in_model_payload=False)
        return value

    def authorization_template(self, preview):
        value = super().authorization_template(preview)
        value.update(schema=VERSION + "/derived_authorization", native_audit_version=AUDIT_VERSION,
            prior_source_state_diagnostics_used=1, prior_source_state_diagnostics_limit=1,
            prior_source_state_contract_accepted=False, profile_changed_from_parent_audit=False,
            prior_audit_in_model_payload=False, previous_audit_is_not_repaired=True,
            new_authority="user autonomous text repair and one necessary typed source-state diagnostic; no creative or media stage")
        return value

    def _binding(self, parent):
        value = super()._binding(parent)
        value.update(schema=VERSION + "/successor_claim", native_audit_version=AUDIT_VERSION)
        return value

    def _guard(self):
        # Common freeze format is explicitly shared; the operative new scope,
        # runtime and RUN identities below are v2, never the old v1 authority.
        base.Session._guard(self)
        anchor = read(self.config.parent_anchor_path)
        scope = read(self.root / "USER_SCOPE.json")
        if (scope.get("schema") != VERSION + "/derived_authorization"
                or scope.get("native_audit_version") != AUDIT_VERSION or scope.get("stage_limits") != LIMITS
                or any(type(v) is not int for v in scope["stage_limits"].values())
                or type(scope.get("total_new_calls_limit")) is not int or scope["total_new_calls_limit"] != 1
                or scope.get("diagnostic_only") is not True or scope.get("creative_stage_authorized") is not False
                or scope.get("old_complete_body_calls_used") != 8 or scope.get("old_complete_body_capacity") != 8
                or scope.get("diagnostic_calls_previously_used") != 4 or scope.get("old_director_capacity") != base.DIRECTOR
                or scope.get("prior_source_state_diagnostics_used") != 1 or scope.get("prior_source_state_diagnostics_limit") != 1
                or scope.get("prior_source_state_contract_accepted") is not False
                or scope.get("profile_changed_from_parent_audit") is not False or scope.get("prior_audit_in_model_payload") is not False
                or scope.get("previous_audit_is_not_repaired") is not True
                or scope.get("inherited") != anchor["inherited"]
                or scope.get("parent_anchor_sha256") != self.config.parent_anchor_sha256
                or digest(anchor) != self.config.parent_anchor_sha256
                or scope.get("creative_source_root") != str(prior.creative_root(anchor))):
            raise ValueError("exact new one-call typed state diagnostic scope differs")
        if read(self.root / "INPUTS.json") != read(prior.creative_root(anchor) / "INPUTS.json"):
            raise ValueError("original current creative inputs changed")
        self._profile_gate()
        path = self.root / "RUN_CLAIM.json"
        if path.exists():
            claim = read(path)
            if not (claim.get("schema") == VERSION + "/run_claim" and claim.get("root") == str(self.root)
                    and type(claim.get("pid")) is int and claim["pid"] > 0
                    and claim.get("automatic_restart") is False
                    and claim.get("freeze_sha256") == sha(self.root / "PRODUCTION_FREEZE.json")):
                raise ValueError("single-use typed source diagnostic RUN differs")
        return True

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            inherited_guard=self._guard, admission=self._admit,
            shared_lock=base.PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        value = base.NativeSession.state(self, runtime, status, **details)
        value.update(schema=VERSION + "/state", diagnostic_only=True, text_ready_for_director=False,
            native_audit_version=AUDIT_VERSION, new_stage_limits=deepcopy(LIMITS),
            old_complete_body_calls_used=8, diagnostic_calls_previously_used=4,
            prior_source_state_diagnostics_used=1, prior_source_state_contract_accepted=False)
        if (self.root / "RUN_CLAIM.json").exists():
            value["run_claim_sha256"] = sha(self.root / "RUN_CLAIM.json")
        write(self.root / "STATE.json", value)
        return value

    def _save(self, runtime, status, decision=None, native=None, receipt=None, details=None):
        paths = {}
        for key, name, value in (("native_audit", "NATIVE_SOURCE_STATE_AUDIT", native),
                ("derived_decision", "SOURCE_STATE_AUDIT_DECISION", decision)):
            if value is not None:
                path = self.root / (name + ".json"); write(path, value, True); paths[key] = str(path)
        state = self.state(runtime, status, **(details or {}))
        summary = {"schema": VERSION + "/summary", "status": status, "diagnostic_only": True,
            "native_audit_version": AUDIT_VERSION, "paths": paths, "artifact_file_sha256": base._hashes(paths.values()),
            "native_audit_sha256": digest(native) if native is not None else None,
            "derived_decision_sha256": digest(decision) if decision is not None else None,
            "receipt_ordinal": receipt["ordinal"] if receipt is not None else None, "spend": deepcopy(state["spend"]),
            "spend_verification_pending": state["spend_verification_pending"], "stop_details": details or {},
            "prior_source_state_diagnostics_used": 1, "prior_source_state_contract_accepted": False,
            "text_ready_for_director": False, "human_quality_approved": False, "creative_quality_passed": False, "media_submitted": False}
        write(self.root / "SUMMARY.json", summary, True)
        state["summary_sha256"] = digest(summary); write(self.root / "STATE.json", state)
        return state

    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file():
            raise ValueError("separately prepared typed-audit root required")
        base.policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "pid": base.os.getpid(), "started_at": self.clock(), "automatic_restart": False,
            "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json")})
        runtime = None
        try:
            runtime = self.runtime(); self._guard()
            base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(runtime.ledger)["calls"]: raise ValueError("nonempty original RUN cannot restart")
            prepared = self._request(read(self.root / "INPUTS.json"))
            path = self.root / "call_intents" / (LABEL + ".json")
            write(path, {"schema": VERSION + "/call_intent", "label": LABEL, "request": prepared["request"],
                "request_sha256": digest(prepared["request"]), "ledger_prefix_sha256": digest(read(runtime.ledger)["calls"]),
                "automatic_retry": False}, True)
            self.pending_intent = {"label": LABEL, "path": str(path), "sha256": sha(path)}
            receipt = base.policy.dispatch_claimed(runtime, LABEL, prepared, lambda value: self.audit.validate(value, prepared),
                root=self.root, grant_id=self.config.grant_id, stage_limits=LIMITS,
                current_round_root=self.config.counter_root, current_round_key=self.config.round_key, guard=self._guard)
            native = prior.native_proof.known_native(receipt); decision = base._decision(receipt)
            status = ("halt_source_state_audit_contract" if decision.get("valid") is not True else
                "halt_source_state_audit_uncertain" if decision.get("uncertainties") else
                "diagnostic_completed_known_content_failure" if decision.get("accepted") is False else
                "diagnostic_completed_not_creative" if decision.get("accepted") is True else "halt_source_state_audit_contract")
            return self._save(runtime, status, decision, native, receipt)
        except base.Halt as stop:
            return self._save(runtime, stop.status, details=stop.details)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_restart": False}, True)
            return self._save(runtime, "halt_execution_reconciliation", details={"exception_type": type(exc).__name__, "error": str(exc)})


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization", "prepare", "run")); parser.add_argument("path")
    args = parser.parse_args()
    session = Session.open(args.path) if args.action == "run" else Session(read(args.path))
    value = session.authorization_template(session.preview()) if args.action == "authorization" else getattr(session, args.action)()
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
