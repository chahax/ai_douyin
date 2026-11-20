"""Input-only advisory scope handoff around the frozen v26 native protocol.

Response tables stay v26: no third judge or extra response table. Complete
future semantic requests bind their added advisory through the actual context
SHA. Old checkers receive only an in-memory context-identity projection after
the complete new request Schema is verified; native identities remain original.
"""
from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError

from .creative_goal_context_workflow_v26 import *
from . import creative_goal_context_workflow_v26 as prior
from . import creative_commitment_scope_handoff_v1 as scopes

VERSION = "creative_goal_context_workflow/v27"
ADAPTER_VERSION = "creative_commitment_scope_review_adapter/v1"
_planning_authority_inputs = prior._planning_authority_inputs
_fixed_legal_context = prior._fixed_legal_context
_validate_planning_input = prior._validate_planning_input


def _mark(prepared, inputs, *, payload=None, schema=None, rule=None, expected_reference=None):
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result = prior._finish(prepared, inputs, payload, rule=rule, schema=schema, expected_reference=expected_reference)
    result["manifest"].update(workflow_version=VERSION, review_adapter_version=ADAPTER_VERSION)
    result["request"]["input_provenance"].update(workflow_version=VERSION, review_adapter_version=ADAPTER_VERSION,
        context_manifest_sha256=digest(result["manifest"]))
    result.update(wire=expected_wire_request(result["request"]), request_sha256=digest(result["request"]))
    return result


def prepare_goal_request(inputs, profile):
    return _mark(prior.prepare_goal_request(inputs, profile), inputs)


def prepare_goal_scope_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_scope_request(inputs, profile, native_goal), inputs)


def prepare_goal_scoped_source_request(inputs, profile, native_goal, native_scope):
    return _mark(prior.prepare_goal_scoped_source_request(inputs, profile, native_goal, native_scope), inputs)


def prepare_goal_commitment_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_commitment_audit_request(inputs, profile, native_goal), inputs)


def prepare_goal_drama_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_drama_audit_request(inputs, profile, native_goal), inputs)


def prepare_opening_setup_request(inputs, profile, native_goal):
    return _mark(prior.prepare_opening_setup_request(inputs, profile, native_goal), inputs)


def _body(prepared, inputs, profile, native_goal, native_goal_audit):
    payload = scopes.build_and_attach(json.loads(prepared["request"]["messages"][1]["content"]),
        inputs, profile, native_goal, native_goal_audit)
    snapshot = payload[scopes.FIELD]
    prepared["manifest"].update(commitment_scope_handoff_version=scopes.VERSION,
        commitment_scope_snapshot_sha256=digest(snapshot), commitment_scope_is_new_source_authority=False)
    prepared["request"]["input_provenance"].update(commitment_scope_handoff_version=scopes.VERSION,
        commitment_scope_snapshot_sha256=digest(snapshot))
    return _mark(prepared, inputs, payload=payload,
        rule=prepared["request"]["messages"][0]["content"] + scopes.RULE, expected_reference=1)


def prepare_script_request(inputs, profile, native_goal, native_goal_audit, **kwargs):
    # Original v26 four-audit/paired/cast/whole-native gates still run first.
    return _body(prior.prepare_script_request(inputs, profile, native_goal, native_goal_audit, **kwargs),
        inputs, profile, native_goal, native_goal_audit)


def _full(prepared, inputs, profile, native_script, views, part, native_goal_audit):
    if part == "physical":
        prepared["manifest"].update(commitment_scope_in_model_payload=False)
        return _mark(prepared, inputs, expected_reference=0)
    if part != "semantic":
        raise ValueError("review part must be semantic or physical")
    baseline_context = prepared["part_context_sha256"]
    payload = scopes.build_and_attach(json.loads(prepared["request"]["messages"][1]["content"]),
        inputs, profile, views["goal"], native_goal_audit)
    snapshot = payload[scopes.FIELD]
    context = digest(payload)
    schema = deepcopy(prepared["request"]["structured_schema"])
    schema["properties"]["context_sha256"] = {"const": context}
    Draft202012Validator.check_schema(schema)
    prepared["manifest"].update(part_context_sha256=context, commitment_scope_in_model_payload=True,
        commitment_scope_handoff_version=scopes.VERSION, commitment_scope_snapshot_sha256=digest(snapshot),
        commitment_scope_is_new_source_authority=False, compiler_baseline_context_sha256=baseline_context,
        response_tables_added_for_scope_handoff=0)
    prepared["request"]["input_provenance"].update(part_context_sha256=context,
        commitment_scope_handoff_version=scopes.VERSION, commitment_scope_snapshot_sha256=digest(snapshot))
    prepared.update(part_context_sha256=context, context_sha256=context)
    return _mark(prepared, inputs, payload=payload, schema=schema,
        rule=prepared["request"]["messages"][0]["content"] + scopes.RULE, expected_reference=1)


def prepare_full_review_part_request(inputs, profile, native_script, views, part, *, native_goal_audit=None):
    baseline = prior.prepare_full_review_part_request(inputs, profile, native_script, views, part, native_goal_audit=native_goal_audit)
    return _full(baseline, inputs, profile, native_script, views, part, native_goal_audit)


class _WorkflowFacade:
    __slots__ = ("_adapter",)

    def __init__(self, adapter):
        object.__setattr__(self, "_adapter", adapter)

    def __setattr__(self, name, value):
        raise AttributeError("bound workflow facade is read-only")

    def __getattr__(self, name):
        if name == "__file__": return __file__
        if name == "prepare_script_request": return self._adapter.prepare_script_request
        if name == "prepare_full_review_part_request": return self._adapter.prepare_full_review_part_request
        if name in globals() and not name.startswith("_"): return globals()[name]
        raise AttributeError(name)


class _ScopeReviewAdapter:
    VERSION = prior.FULL_REVIEW_VERSION  # unchanged native response format
    __slots__ = ("_base", "_inputs", "_profile", "_audit", "workflow")

    def __init__(self, inputs, profile, native_goal_audit):
        self._inputs, self._profile, self._audit = deepcopy(inputs), deepcopy(profile), deepcopy(native_goal_audit)
        self._base = prior.make_review_adapter(inputs, profile, native_goal_audit)
        self.workflow = _WorkflowFacade(self)

    def prepare_script_request(self, inputs, profile, native_goal, native_goal_audit, **kwargs):
        # This bound method rejects even another valid same-goal audit bundle;
        # it permits only the original two whole-native feedback fields to vary.
        baseline = self._base.prepare_script_request(inputs, profile, native_goal, native_goal_audit, **kwargs)
        return _body(baseline, inputs, profile, native_goal, native_goal_audit)

    def prepare_full_review_part_request(self, inputs, profile, native_script, views, part):
        baseline = self._base.prepare_full_review_part_request(inputs, profile, native_script, views, part)
        return _full(baseline, inputs, profile, native_script, views, part, self._audit)

    def _prepared(self, script, brief, plan, goal, setup, part):
        native, views = self._base._sources(script, brief, plan, goal, setup)
        baseline = self._base.prepare_full_review_part_request(self._inputs, self._profile, native, views, part)
        current = _full(deepcopy(baseline), self._inputs, self._profile, native, views, part, self._audit)
        return native, baseline, current

    def validate_part(self, document, part, script, brief, plan, legal_context, *, context_sha256, goal_contract=None, opening_setup=None):
        try:
            native, baseline, current = self._prepared(script, brief, plan, goal_contract, opening_setup, part)
            if context_sha256 != current["part_context_sha256"] or not prior._same(legal_context, current["review_legal_context"]):
                raise ValueError("scope-aware native report differs from the exact current request/authority")
            Draft202012Validator(current["request"]["structured_schema"]).validate(document)
            projection = deepcopy(document)
            projection["context_sha256"] = baseline["part_context_sha256"]
            result = self._base.validate_part(projection, part, script, brief, plan, legal_context,
                context_sha256=baseline["part_context_sha256"], goal_contract=goal_contract, opening_setup=opening_setup)
            return {**result, "native_part_sha256": digest(document), "native_context_sha256": context_sha256,
                "native_script_sha256": digest(native), "compiled_script_sha256": digest(script),
                "actual_request_sha256": current["request_sha256"], "review_adapter_version": ADAPTER_VERSION,
                "compiler_context_projection_sha256": digest(projection), "compiler_projection_is_native_review": False,
                "native_response_rewritten": False, "commitment_scope_in_model_payload": part == "semantic",
                "commitment_scope_snapshot_sha256": current["manifest"].get("commitment_scope_snapshot_sha256")}
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            return prior._invalid("COMMITMENT_SCOPE_FULL_REVIEW_CONTRACT_INVALID", exc)

    @staticmethod
    def build_review_bundle(native_semantic_review, native_physical_review):
        return prior._ReviewAdapter.build_review_bundle(native_semantic_review, native_physical_review)

    def validate_bundle(self, bundle, script, brief, plan, legal_context, *, semantic_context_sha256, physical_context_sha256,
                        goal_contract=None, opening_setup=None):
        if (type(bundle) is not dict or set(bundle) != {"schema", "native_semantic_review", "native_physical_review"}
                or bundle["schema"] != prior.FULL_BUNDLE_VERSION or semantic_context_sha256 == physical_context_sha256):
            return prior._invalid("COMMITMENT_SCOPE_FULL_BUNDLE_INVALID", "two exact original same-source native parts required")
        parts = {part: bundle["native_" + part + "_review"] for part in ("semantic", "physical")}
        contexts = {"semantic": semantic_context_sha256, "physical": physical_context_sha256}
        results = {part: self.validate_part(parts[part], part, script, brief, plan, legal_context,
            context_sha256=contexts[part], goal_contract=goal_contract, opening_setup=opening_setup) for part in parts}
        if not all(value["valid"] for value in results.values()):
            return {**prior._invalid("COMMITMENT_SCOPE_FULL_PART_INVALID", "native part failed scope-aware request contract"),
                    "part_results": results, "native_bundle_sha256": digest(bundle)}
        projected, old_contexts = {}, {}
        for part, native_part in parts.items():
            _, baseline, _ = self._prepared(script, brief, plan, goal_contract, opening_setup, part)
            old_contexts[part] = baseline["part_context_sha256"]
            projected[part] = {**deepcopy(native_part), "context_sha256": old_contexts[part]}
        result = self._base.validate_bundle(self._base.build_review_bundle(projected["semantic"], projected["physical"]),
            script, brief, plan, legal_context, semantic_context_sha256=old_contexts["semantic"], physical_context_sha256=old_contexts["physical"],
            goal_contract=goal_contract, opening_setup=opening_setup)
        # All new native content judgments are unchanged by the context-only
        # check projection; return their original rows and identities even on a
        # failed deterministic bundle check.
        return {**result, "part_results": results, "native_bundle_sha256": digest(bundle),
            "native_part_sha256": {part: digest(value) for part, value in parts.items()},
            "findings": [item for value in results.values() for item in value["findings"]],
            "uncertainties": [item for value in results.values() for item in value["uncertainties"]],
            "review_adapter_version": ADAPTER_VERSION, "native_response_rewritten": False,
            "compiler_projection_is_native_review": False, "scope_advisory_not_new_authority": True}


def make_review_adapter(inputs, profile, native_goal_audit):
    return _ScopeReviewAdapter(inputs, profile, native_goal_audit)
