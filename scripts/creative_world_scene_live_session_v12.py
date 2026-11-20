"""Isolated frozen source claims and facts; one selected original body, explicit review supplement."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from scripts import creative_world_scene_live_session_v10 as prior
from scripts import creative_world_scene_live_session_v7 as original_material
from scripts import creative_world_scene_live_session_v5 as body_flow

base, mechanics, Config = prior.base, prior.mechanics, prior.Config
read, write, digest, sha = prior.read, prior.write, prior.digest, prior.sha
VERSION = "creative_world_scene_live_session/v12"
SOURCE_VERSION = "creative_isolated_source_claims/v1"
LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 1, "full_review": 7}
PARENT_LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 2, "full_review": 6}
PARENT_USED = {"goal_plan": 0, "goal_audit": 0, "complete_script": 0, "full_review": 2}
PARENT_REMAINING = {"goal_plan": 0, "goal_audit": 0, "complete_script": 2, "full_review": 4}
TOTAL, BODY_VERSIONS, DEFERRED_BODY_VERSIONS = 8, [15], [16]
LABELS = r"complete_script_15|(?:source_claims|claims_comparison)_(?:calibration_14|15)|observable_events_15|full_review_(?:semantic|physical)_15"
POLICY = mechanics.FixedPolicy(VERSION, tuple(LIMITS.items()), LABELS)
REF_KEYS = (*prior.REF_KEYS, "accepted_observable_events_receipt", "accepted_observable_events_prepared_ref", "accepted_observable_events_decision_ref")


def strict_clients(): return importlib.import_module("scripts.creative_isolated_claims_strict_role_clients_v1")


def strict_stage(request):
    provenance = request.get("input_provenance", {})
    if provenance.get("isolated_source_claims_version") != SOURCE_VERSION: return False
    if provenance.get("stage_kind") not in ("source_claims", "claims_comparison"):
        raise ValueError("unknown strict source-claims substage cannot use ordinary fallback")
    if not strict_clients().is_strict_claims_request(request): raise ValueError("invalid strict source-claims request")
    return True


def client_factory(request):
    return strict_clients().make_client_factory(request, strict_claims=True) if strict_stage(request) else base.clients.make_client_factory(request)


def scope_metadata():
    return {"parent_scope_stage_limits": deepcopy(PARENT_LIMITS), "parent_scope_stage_calls": deepcopy(PARENT_USED),
        "parent_scope_remaining": deepcopy(PARENT_REMAINING), "parent_scope_calls_used": 2, "parent_scope_calls_remaining": 6,
        "original_body_capacity_total": 2, "selected_original_body_versions": BODY_VERSIONS,
        "deferred_original_body_versions": DEFERRED_BODY_VERSIONS, "original_review_capacity_remaining": 4,
        "supplemental_review_calls": 3, "creative_body_capacity_regranted": False,
        "body_capacity_is_original_grant_balance_only": True, "unused_capacity_is_original_grant_balance_only": False,
        "min_reviews_before_body": 5, "reuses_validated_observable_events_for_calibration": True}


class Runtime(prior.Runtime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.stage_limits = deepcopy(LIMITS)

    def _policy(self):
        value = super()._policy(); value.update(schema=VERSION + "/runtime_policy", total_new_calls_limit=TOTAL,
            complete_script_versions=BODY_VERSIONS, source_claims_review_cap=16000, **scope_metadata())
        return value

    def _request_gate(self, request):
        if not strict_stage(request): return super()._request_gate(request)
        expected = deepcopy(self.profile["director"]["parameters"])
        expected.update(self.profile.get("stage_parameters", {}).get("full_review", {})); expected["max_completion_tokens"] = 16000
        if (request.get("stage") != "full_review" or request.get("role") != "director"
                or request.get("model") != self.models["director"]["model"] or request.get("parameters") != expected):
            raise RuntimeError("only the two fixed strict reviewer contracts may use the16k substage projection")
        strict_clients().expected_wire_request(request, strict_claims=True)
        Draft202012Validator.check_schema(request["structured_schema"])


class Driver(prior.Driver):
    def preflight(self, label):
        if label == "complete_script_16":
            raise base.Halt("halt_selected_original_body_capacity", selected_original_body_versions=BODY_VERSIONS,
                deferred_original_body_versions=DEFERRED_BODY_VERSIONS, original_body_capacity_preserved=True)
        if label.startswith("complete_script_"):
            remaining = LIMITS["full_review"] - sum(not r["label"].startswith("complete_script_") for r in self.calls)
            if remaining < 5: raise base.Halt("halt_review_capacity_for_complete_chain", remaining_reviews=remaining,
                required_reviews=5, deferred_original_body_versions=DEFERRED_BODY_VERSIONS, original_body_capacity_preserved=True)

    def invoke(self, label, prepared, validator):
        self.preflight(label)
        return mechanics.dispatch(self, POLICY, label, prepared, validator)

    def _focused(self, native, views, label):
        match = re.fullmatch(r"enacted_causality_(calibration_14|15)", label)
        if not match: raise ValueError("only calibration14 and selected original body15 are authorized")
        suffix = match[1]
        if suffix == "calibration_14":
            events, events_prepared, _ = self.session.accepted_observable_material(self.wf, native, views)
        else:
            events_prepared = self.wf.prepare_observable_events_request(self.inputs, self.profile, native, views)
            events, decision, _ = self.invoke("observable_events_" + suffix, events_prepared,
                lambda value: self.wf.validate_observable_events(value, events_prepared))
            if not self.audit_gate(decision, "observable_events") or decision.get("ledger_usable") is not True:
                raise base.Halt("halt_observable_events_requires_diagnosis", decision=decision)
        claims_prepared = self.wf.prepare_source_claims_request(self.inputs, self.profile, native, views)
        claims, claims_decision, _ = self.invoke("source_claims_" + suffix, claims_prepared,
            lambda value: self.wf.validate_source_claims(value, claims_prepared))
        if not self.audit_gate(claims_decision, "source_claims") or claims_decision.get("claims_usable") is not True:
            raise base.Halt("halt_source_claims_requires_diagnosis", decision=claims_decision)
        prepared = self.wf.prepare_claims_comparison_request(self.inputs, self.profile, native, views,
            claims, claims_prepared, events, events_prepared)
        comparison, decision, _ = self.invoke("claims_comparison_" + suffix, prepared,
            lambda value: self.wf.validate_claims_comparison(value, prepared))
        accepted = self.audit_gate(decision, "claims_comparison")
        if decision.get("requires_new_goal_plan"):
            raise base.Halt("halt_requires_new_complete_goal", decision=decision, no_replanning_authorized=True)
        args = (claims, claims_prepared, events, events_prepared, comparison, prepared)
        packet = (self.wf.build_event_entailment_review_packet if accepted else self.wf.build_event_entailment_repair_feedback)(*args)
        packet.update(coordinator_packet_schema=VERSION + "/three_native_report_packet", packet_is_model_native=False)
        return accepted, packet, decision


class Session(prior.Session):
    POLICY, REF_KEYS, driver_type = POLICY, REF_KEYS, Driver

    def __init__(self, *args, **kwargs):
        if kwargs.get("client_factory_builder") is None: kwargs["client_factory_builder"] = client_factory
        super().__init__(*args, **kwargs)

    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_invalid_comparison_spend_anchor_v2").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256); account = anchor.get("current_text_scope_accounting", {})
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited") or account.get("limits") != PARENT_LIMITS
                or account.get("consumed") != PARENT_USED or account.get("remaining") != PARENT_REMAINING
                or account.get("calls_used") != 2 or account.get("calls_remaining") != 6 or account.get("body_used") != 0
                or account.get("body_limit") != 2 or anchor.get("current_body_versions_unused") != [15,16]
                or anchor.get("creative_body_capacity_regranted") is not False or not anchor.get("continuation_of_original_grant")):
            raise ValueError("settled684 and preserved original two bodies/four reviews required before explicit supplement")
        prior.source_refs.creative_root(anchor)
        for key in ("inputs", "profile"):
            path = base._inside(anchor["current_" + key + "_path"])
            if sha(path) != anchor["current_" + key + "_file_sha256"] or digest(read(path)) != anchor["current_" + key + "_sha256"]:
                raise ValueError("current original authority changed")
        return anchor, checked

    def _workflow(self):
        adapter = self._reviews(read(self.root/"USER_SCOPE.json")) if (self.root/"USER_SCOPE.json").exists() else self.injected_review_adapter
        return importlib.import_module("scripts.creative_world_scene_replanned_workflow_v8").ReviewWorkflow(base.workflow, adapter)

    def accepted_observable_material(self, wf, native, views):
        anchor = read(self.config.parent_anchor_path)
        receipt, events = original_material.references._ref_document(anchor["accepted_observable_events_receipt"])
        prepared = original_material.referenced_json(anchor["accepted_observable_events_prepared_ref"])
        decision = original_material.referenced_json(anchor["accepted_observable_events_decision_ref"])
        inputs = read(self.root/"INPUTS.json") if (self.root/"INPUTS.json").exists() else read(anchor["current_inputs_path"])
        if (receipt["status"] != "contract_valid" or receipt["request"] != prepared["request"] or receipt.get("validation") != decision
                or prepared["views"]["native_script"] != native or prepared["views"]["compiler_views"] != views
                or prepared["views"]["inputs"] != inputs or prepared["views"]["profile"] != self.profile):
            raise ValueError("original683 source/native/prepared request differs")
        if (wf.validate_observable_events(events, prepared) != decision or decision.get("valid") is not True
                or decision.get("ledger_usable") is not True or decision.get("uncertainties")):
            raise ValueError("original683 observable facts are not reusable")
        return events, prepared, decision

    def source_material(self, wf):
        seed = original_material.Session.source_material(self, wf); anchor = read(self.config.parent_anchor_path)
        native = original_material.references._ref_document(anchor["current_valid_body_receipt"])[1]
        prepared = original_material.referenced_json(anchor["accepted_observable_events_prepared_ref"])
        views = prepared["views"]["compiler_views"]
        if views["goal"] != seed["goal"] or views["opening_setup"] != seed["setup"]:
            raise ValueError("original683 goal/opening differ")
        wf.validate_script_document(native, views, read(anchor["current_inputs_path"])["production_preferences"])
        self.accepted_observable_material(wf, native, views)
        return {**seed, "calibration_native_script": native, "calibration_views": views, "_caller_profile": self.profile}

    @staticmethod
    def first_prepared(inputs, wf, seed):
        return wf.prepare_source_claims_request(inputs, seed["_caller_profile"], seed["calibration_native_script"], seed["calibration_views"])

    def authorization_template(self, preview):
        value = super().authorization_template(preview)
        value.update(schema=VERSION + "/supplemented_review_authorization", stage_limits=deepcopy(LIMITS), total_new_calls_limit=TOTAL,
            complete_script_versions=BODY_VERSIONS, **scope_metadata(),
            new_authority="select original body15 only, defer16; preserve four unused reviews plus three explicitly authorized necessary reviews")
        return value

    def _binding(self, parent):
        value = super()._binding(parent); value.update(schema=VERSION + "/successor_claim", selected_stage_limits=deepcopy(LIMITS),
            remaining_original_capacity=deepcopy(PARENT_REMAINING), supplemental_review_calls=3,
            selected_original_body_versions=BODY_VERSIONS, deferred_original_body_versions=DEFERRED_BODY_VERSIONS)
        return value

    def preview(self): return mechanics.preview(self, POLICY)
    def prepare(self): return mechanics.prepare(self, POLICY)
    def _guard(self): return mechanics.guard(self, POLICY)
    def _admit(self, label, request, ledger):
        mechanics.admit(self, POLICY, label, request, ledger)
        if strict_stage(request): strict_clients().expected_wire_request(request, strict_claims=True)
        return True

    def runtime(self):
        freeze = read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            inherited_guard=self._guard, admission=self._admit, shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",
            quota_state=None, client_factory_builder=self.client_factory_builder)

    def _replay(self, ledger, label=None, *, verify_validations=False):
        owner, rows = self, ledger["calls"]
        class Replay(Driver):
            def invoke(self, current, prepared, validator):
                self.preflight(current)
                if self.position == len(rows):
                    if current != label: raise ValueError("fixed claims/facts sequence differs")
                    raise body_flow.NextRequest(prepared)
                row = rows[self.position]; self.position += 1; path = owner.root/row["receipt"]; receipt = read(path)
                if current != row["label"] or sha(path) != row["receipt_sha256"] or receipt["request"] != prepared["request"]:
                    raise ValueError("original claims prerequisite differs")
                native, decision = prior.native_proof.known_native(receipt), base._decision(receipt)
                if verify_validations and receipt["status"] == "contract_valid" and validator(native) != decision:
                    raise ValueError("source/facts/comparison validation changed")
                self.calls.append(row); return native, decision, row
        replay = Replay(self, None, read(self.root/"INPUTS.json"), self._workflow()); replay.position = 0
        try: result = replay.flow()
        except body_flow.NextRequest as found:
            if label is None: raise ValueError("source-claims handoff flow unfinished")
            return found.prepared
        if label is not None or replay.position != len(rows): raise ValueError("terminal flow or extra claims receipts")
        return result

    def state_metadata(self):
        value = super().state_metadata(); value.update(**scope_metadata()); return value

    def artifacts(self, result):
        paths, values = super().artifacts(result); packet = result["native_enacted_review"]
        for key, file in (("native_source_claims_report", "NATIVE_SOURCE_CLAIMS.json"), ("verified_compiled_source_claims", "COMPILED_SOURCE_CLAIMS.json")):
            values[key] = packet[key]; paths[key] = self.root/"scripts"/file
        return paths, values

    @staticmethod
    def extra_identities(values):
        return {**prior.Session.extra_identities(values), "native_source_claims_sha256": digest(values["native_source_claims_report"]),
            "compiled_source_claims_sha256": digest(values["verified_compiled_source_claims"])}

    def state(self, runtime, status, **details): return mechanics.state(self, POLICY, runtime, status, **details)
    def _save_text(self, result, driver, runtime): return mechanics.save_text(self, POLICY, result, driver, runtime)
    def run(self): return mechanics.run(self, POLICY)


def verify_text_handoff(root):
    return verify_handoff(Session.open(root))


def verify_handoff(session):
    """Full mechanical proof; only original-wire verification is explicitly routed to the new fixed client."""
    runtime = session.runtime(); session._guard(); anchor, _ = session._parent()
    state, handoff, ledger = (read(session.root/(name+".json")) for name in ("STATE","TEXT_HANDOFF","CALL_LEDGER"))
    if (state.get("status") != "text_ready_for_director" or state.get("spend_verification_pending") is not False
            or handoff.get("schema") != VERSION+"/text_handoff" or state.get("text_handoff_sha256") != digest(handoff)
            or handoff.get("freeze_sha256") != sha(session.root/"PRODUCTION_FREEZE.json")
            or not (handoff.get("run_claim_sha256") == state.get("run_claim_sha256") == sha(session.root/"RUN_CLAIM.json"))):
        raise ValueError("known original source-claims handoff required")
    current = runtime.summary()
    if current != state["spend"] or current["new_unknown_token_reservations"] != 0: raise ValueError("settled accounting differs")
    reader = base.evidence.Reader()
    receipts = [strict_clients().verify_original_receipt(session.root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    base.evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    if handoff.get("receipt_identities") != [base._receipt_identity(session.root,row) for row in ledger["calls"]]: raise ValueError("receipt identities differ")
    for i, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = read(session.root/"call_intents"/(row["label"]+".json"))
        if (intent.get("schema") != VERSION+"/call_intent" or intent["prepared"]["request"] != receipt["request"]
                or intent["ledger_prefix_sha256"] != digest(ledger["calls"][:i])): raise ValueError("original strict intent differs")
    result = session._replay(ledger, verify_validations=True); expected = session.artifacts(result)[1]
    if handoff.get("inherited_current_native_receipt_references") != {key:anchor[key] for key in REF_KEYS}: raise ValueError("inherited accepted-source refs differ")
    for path, expected_sha in handoff["artifact_file_sha256"].items(): reader.verify(base._inside(path),expected_sha)
    if handoff.get("native_identity") != {key:digest(value) for key,value in expected.items()}: raise ValueError("native/derived identities differ")
    for key,value in expected.items():
        if read(base._inside(handoff["paths"][key])) != value: raise ValueError("artifact differs from actual native flow: "+key)
    if (read(handoff["paths"]["inputs"]) != read(session.root/"INPUTS.json") or read(handoff["paths"]["profile"]) != session.profile
            or handoff.get("source_descriptor") != result["source_descriptor"] or handoff.get("decision") != result["decision"]
            or handoff.get("source_state_decision") != result["source_state_decision"]
            or (session.root/"scripts/FULL_SCRIPT.md").read_text(encoding="utf-8") != result["rendered_script"]):
        raise ValueError("source authority/compiled proof/render differs")
    identity = {"root":str(session.root),"terminal_state_sha256":sha(session.root/"STATE.json"),"native_ledger_sha256":sha(session.root/"CALL_LEDGER.json"),
        "production_freeze_sha256":sha(session.root/"PRODUCTION_FREEZE.json"),"end_ordinal":current["effective_calls_started"]}
    inherited = {"calls_started":current["effective_calls_started"],"reported_tokens":current["effective_reported_tokens"],
        "calls_with_known_usage":current["effective_calls_with_known_usage"],"pending_ordinals":deepcopy(current["historical_pending_ordinals"]),
        "unknown_token_reservations":current["unknown_token_reservations"]}
    files = {**read(session.root/"PRODUCTION_FREEZE.json")["files"], **{path:item["sha256"] for path,item in reader.files.items()},
        **base._hashes(session.root/(name+".json") for name in ("STATE","TEXT_HANDOFF","CALL_LEDGER","PRODUCTION_FREEZE","RUN_CLAIM"))}
    return {"schema":VERSION+"/verified_text_handoff","valid":True,"accepted":True,"status":"text_ready_for_director","root":str(session.root),
        "source_root":str(session.root),"handoff_path":str(session.root/"TEXT_HANDOFF.json"),"handoff_sha256":sha(session.root/"TEXT_HANDOFF.json"),
        "paths":deepcopy(handoff["paths"]),"identity":{"native_goal_sha256":digest(expected["goal"]),"native_setup_sha256":digest(expected["setup"]),
            "native_script_sha256":digest(expected["raw_script"]),"derived_script_sha256":digest(expected["derived_script"]),
            "compiled_script_sha256":digest(expected["compiled_script"]),"goal_audit_bundle_sha256":digest(expected["goal_audit_bundle"]),
            "full_review_bundle_sha256":digest(expected["full_review_bundle"]),"source_state_audit_sha256":digest(expected["source_state_audit"]),**session.extra_identities(expected)},
        "source_descriptor":deepcopy(result["source_descriptor"]),"receipt_identities":deepcopy(handoff["receipt_identities"]),"spend":current,"inherited":inherited,
        "parent_identity":identity,"parent_identity_sha256":digest(identity),"source_files":files,"human_quality_approved":False,
        "creative_quality_passed":False,"authorizes_media_dispatch":False,"model_calls":0}


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("preview","authorization","prepare","run","verify"));p.add_argument("path");a=p.parse_args()
    if a.action=="verify": value=verify_text_handoff(a.path)
    else:
        s=Session.open(a.path) if a.action=="run" else Session(read(a.path))
        value=s.authorization_template(s.preview()) if a.action=="authorization" else getattr(s,a.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
