"""Bounded offline native-text closure, with explicit world compiler/reviews.

The only responder reads preregistered synthetic JSON. This module has no SDK,
credentials, TaskStore claim, live runtime, paid grant or media dispatcher.
"""
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import creative_goal_context_workflow_v28 as default_workflow

VERSION = "creative_world_scene_text_driver/v1"
SCENARIO_VERSION = "creative_world_scene_mock_case/v1"


class OfflineStop(Exception):
    def __init__(self, status, **details):
        self.status, self.details = status, details
        super().__init__(status)


class Driver:
    def __init__(self, inputs, profile, documents, *, workflow=default_workflow):
        self.inputs, self.profile, self.documents = deepcopy(inputs), deepcopy(profile), deepcopy(documents)
        self.wf, self.calls = workflow, []

    def invoke(self, label, prepared, validator):
        if any(row["label"] == label for row in self.calls): raise OfflineStop("halt_duplicate_mock_label")
        if label not in self.documents: raise OfflineStop("halt_missing_mock_response", label=label)
        envelope = self.documents[label]
        if type(envelope) is not dict or set(envelope) != {"kind", "output"}:
            raise OfflineStop("halt_mock_envelope_invalid", label=label)
        row = {"label": label, "prepared": deepcopy(prepared), "mock_response": deepcopy(envelope), "provider_calls": 0}
        self.calls.append(row)
        if envelope["kind"] != "known_complete":
            if envelope["kind"] not in ("transport_unknown", "truncated", "usage_unknown", "missing_tool"):
                raise OfflineStop("halt_mock_envelope_invalid", label=label)
            raise OfflineStop("halt_unknown_or_protocol", label=label, fault=envelope["kind"])
        output = deepcopy(envelope["output"])
        errors = list(Draft202012Validator(prepared["request"]["structured_schema"]).iter_errors(output))
        if errors:
            first = errors[0]
            decision = {"valid": False, "findings": [{"code": "MOCK_NATIVE_SCHEMA_INVALID", "message": first.message,
                "path": "/" + "/".join(map(str, first.absolute_path))}]}
        else:
            try:
                decision = validator(output)
                if type(decision) is not dict or type(decision.get("valid")) is not bool:
                    raise ValueError("explicit typed native validity required")
            except (ValueError, KeyError, TypeError, ValidationError) as exc:
                decision = {"valid": False, "findings": [{"code": "MOCK_NATIVE_CONTRACT_INVALID", "message": str(exc)}]}
        row.update(native_output=output, validation=deepcopy(decision),
            status="contract_valid" if decision["valid"] else "contract_rejected")
        return output, decision, row

    @staticmethod
    def audit_gate(decision, stage):
        if (type(decision) is not dict or decision.get("valid") is not True
                or type(decision.get("accepted")) is not bool
                or type(decision.get("findings")) is not list or type(decision.get("uncertainties")) is not list):
            raise OfflineStop("halt_review_contract", stage=stage, decision=decision)
        if "scope_challenges" in decision:
            if type(decision["scope_challenges"]) is not list: raise OfflineStop("halt_review_contract", stage=stage, decision=decision)
            if decision["scope_challenges"]: raise OfflineStop("halt_scope_challenge", stage=stage, decision=decision)
        if decision.get("revision_dispatch_blocked") is True or str(decision.get("status", "")).startswith(("halt_same_story", "halt_prior_story")):
            raise OfflineStop("halt_revision_dispatch_blocked", stage=stage, decision=decision)
        if decision["uncertainties"]: raise OfflineStop("halt_review_unknown", stage=stage, decision=decision)
        if decision["accepted"] and decision["findings"]: raise OfflineStop("halt_review_contract", stage=stage, decision=decision)
        if not decision["accepted"] and not decision["findings"]:
            raise OfflineStop("halt_review_contract", stage=stage, decision=decision)
        return decision["accepted"]

    def _planning(self):
        wf, current = self.wf, deepcopy(self.inputs)
        for version in (1, 2, 3):
            goal, decision, row = self.invoke(f"whole_plan_{version:02}", wf.prepare_goal_request(current, self.profile),
                lambda value: {"valid": True, "native_goal_sha256": wf.digest(wf.validate_goal_document(value, inputs=self.inputs))})
            if not decision["valid"]:
                current = {**deepcopy(self.inputs), "previous_complete_document": goal, "revision_diagnostics": deepcopy(decision)}
                continue
            reports, decisions, failed = {}, {}, False
            for kind in wf.AUDITS:
                if kind == "scope": request = wf.prepare_goal_scope_request(self.inputs, self.profile, goal)
                elif kind == "source": request = wf.prepare_goal_scoped_source_request(self.inputs, self.profile, goal, reports["scope"])
                else: request = getattr(wf, "prepare_goal_" + kind + "_audit_request")(self.inputs, self.profile, goal)
                context = request.get("scope_context_sha256") if kind == "scope" else request["audit_context_sha256"]
                kwargs = {"context_sha256": context, "inputs": self.inputs}
                if kind == "source": kwargs.update(native_scope=reports["scope"], authority_context=request["source_authority_context"])
                validator = wf.validate_goal_scope if kind == "scope" else getattr(wf, "validate_goal_" + kind + "_audit")
                native, checked, _ = self.invoke(f"{kind}_audit_{version:02}", request,
                    lambda value, fn=validator, args=kwargs: fn(value, goal, **args))
                reports[kind], decisions[kind] = native, checked
                if not self.audit_gate(checked, kind):
                    current = {**deepcopy(self.inputs), "previous_complete_document": goal,
                        "revision_diagnostics": {"complete_current_goal_reviews": deepcopy(reports), "decisions": deepcopy(decisions)}}
                    failed = True; break
            if failed: continue
            bundle = wf.build_goal_audit_bundle(*(reports[key] for key in wf.AUDITS))
            if not self.audit_gate(wf.validate_goal_audit(bundle, goal, inputs=self.inputs), "planning_bundle"):
                raise OfflineStop("halt_planning_bundle_rejected")
            return goal, bundle
        raise OfflineStop("halt_mock_plan_capacity")

    def _opening(self, goal):
        current = deepcopy(self.inputs)
        for version in (1, 2):
            setup, decision, _ = self.invoke(f"opening_setup_{version:02}",
                self.wf.prepare_opening_setup_request(current, self.profile, goal),
                lambda value: {"valid": True, "native_setup_sha256": self.wf.digest(self.wf.validate_opening_setup_document(value, goal))})
            if decision["valid"]: return setup
            current = {**deepcopy(self.inputs), "previous_opening_setup": setup, "opening_setup_diagnostics": deepcopy(decision)}
        raise OfflineStop("halt_mock_setup_capacity")

    def _body(self, goal, bundle, setup):
        wf, current, reviews = self.wf, deepcopy(self.inputs), self.wf.full_reviews()
        for version in (1, 2, 3):
            authored = wf.prepare_script_request(current, self.profile, goal, bundle, opening_setup=setup, **wf.origin_ids(self.inputs))
            views = authored["views"]
            native, decision, _ = self.invoke(f"complete_script_{version:02}", authored,
                lambda value: {**wf.validate_script_document(value, views, self.inputs["production_preferences"]), "valid": True})
            if not decision["valid"]:
                current = {**deepcopy(self.inputs), "previous_complete_document": native, "revision_diagnostics": deepcopy(decision)}
                continue
            compiled = wf.validate_script_document(native, views, self.inputs["production_preferences"])["script"]
            documents, contexts, part_decisions, legal, failed = {}, {}, {}, None, None
            for part in ("semantic", "physical"):
                prepared = wf.prepare_full_review_part_request(self.inputs, self.profile, native, views, part)
                context = prepared["part_context_sha256"]
                if legal is not None and legal != prepared["review_legal_context"]: raise OfflineStop("halt_review_authority_changed")
                legal = prepared["review_legal_context"]
                report, checked, _ = self.invoke(f"full_review_{part}_{version:02}", prepared,
                    lambda value, p=part, c=context: reviews.validate_part(value, p, compiled, views["brief"], views["plan"], legal,
                        context_sha256=c, goal_contract=goal, opening_setup=setup,
                        prior_story_scope=self.inputs["production_preferences"].get("prior_story_scope")))
                documents[part], contexts[part], part_decisions[part] = report, context, checked
                if not self.audit_gate(checked, part): failed = checked; break
            if failed is not None:
                if failed.get("requires_new_goal_plan"): raise OfflineStop("halt_requires_new_complete_goal", decision=failed)
                current = {**deepcopy(self.inputs), "previous_complete_document": native,
                    "revision_diagnostics": {"complete_same_source_part_review": failed, "native_part_reviews": documents}}
                continue
            full = reviews.build_review_bundle(documents["semantic"], documents["physical"])
            checked = reviews.validate_bundle(full, compiled, views["brief"], views["plan"], legal,
                semantic_context_sha256=contexts["semantic"], physical_context_sha256=contexts["physical"],
                goal_contract=goal, opening_setup=setup,
                prior_story_scope=self.inputs["production_preferences"].get("prior_story_scope"))
            if not self.audit_gate(checked, "full_bundle"):
                if checked.get("requires_new_goal_plan"): raise OfflineStop("halt_requires_new_complete_goal", decision=checked)
                current = {**deepcopy(self.inputs), "previous_complete_document": native,
                    "revision_diagnostics": {"complete_same_source_full_review_bundle": checked, "native_review_bundle": full}}
                continue
            first = native["beats"][0]["id"]
            def qualified(snapshot, **identity):
                wf.validate_opening_setup_document(snapshot, goal)
                if identity["snapshot_kind"] != "native_opening_setup" or identity["beat_id"] != first:
                    raise ValueError("only the actual native first-beat setup qualifies in this offline closure")
                return {"verified": True, **identity, "offline_contract_only": True, "actual_performance_approved": False}
            segment = wf.build_segment_context(goal, native, first, setup, snapshot_kind="native_opening_setup",
                expected_snapshot_sha256=wf.digest(setup), snapshot_qualifier=qualified)
            return {"native_goal": goal, "native_goal_audit": bundle, "native_opening_setup": setup,
                "native_script": native, "native_script_sha256": wf.digest(native), "compiled_script": compiled,
                "compiled_script_sha256": wf.digest(compiled), "native_full_review_bundle": full, "decision": checked,
                "rendered_script": wf.render_script(native, goal), "first_segment_context": segment,
                "later_segments_require_qualified_prior_snapshot": True, "views": views}
        raise OfflineStop("halt_mock_script_capacity")

    def run(self):
        result = {"schema": VERSION + "/offline_result", "synthetic_mock": True, "provider_calls": 0,
            "production_claims": 0, "media_calls": 0, "human_quality_approved": False,
            "creative_quality_passed": False, "production_dispatch_eligible": False, "text_ready_for_director": False}
        try:
            goal, bundle = self._planning(); setup = self._opening(goal)
            result.update(status="offline_mock_contract_closure", **self._body(goal, bundle, setup))
        except OfflineStop as stop:
            result.update(status=stop.status, stop_details=stop.details)
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            result.update(status="halt_offline_preparation_contract", stop_details={
                "exception_type": type(exc).__name__, "message": str(exc), "provider_result_unknown": False,
                "automatic_retry": False})
        result["calls"] = deepcopy(self.calls)
        return result


def run_mock(scenario):
    if (type(scenario) is not dict or scenario.get("schema") != SCENARIO_VERSION
            or scenario.get("synthetic") is not True or type(scenario.get("documents")) is not dict):
        raise ValueError("explicit offline synthetic case required; actual receipts cannot be adopted")
    return Driver(scenario["inputs"], scenario["profile"], scenario["documents"]).run()
