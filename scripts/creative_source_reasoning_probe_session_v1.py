"""One source-reasoning compatibility diagnostic; never a creative adoption."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

from scripts import creative_world_scene_live_session_v12 as prior

base, mechanics, Config = prior.base, prior.mechanics, prior.Config
read, write, digest, sha = prior.read, prior.write, prior.digest, prior.sha
VERSION = "creative_source_reasoning_probe/v1"
LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 0, "full_review": 1}
PARENT_LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 1, "full_review": 7}
PARENT_USED = {"goal_plan": 0, "goal_audit": 0, "complete_script": 0, "full_review": 1}
PARENT_REMAINING = {"goal_plan": 0, "goal_audit": 0, "complete_script": 1, "full_review": 6}
LABEL = "source_reasoning_diagnostic_01"
POLICY = mechanics.FixedPolicy(VERSION, tuple(LIMITS.items()), LABEL)


def clients(): return importlib.import_module("scripts.creative_isolated_claims_thinking_role_clients_v1")
def audit(): return importlib.import_module("scripts.creative_isolated_source_claims_v1")


def capacity():
    return {"parent_scope_stage_limits": deepcopy(PARENT_LIMITS), "parent_scope_stage_calls": deepcopy(PARENT_USED),
        "parent_scope_remaining": deepcopy(PARENT_REMAINING), "remaining_after_diagnostic": {"complete_script": 1, "full_review": 5},
        "preserved_unused_selected_body_versions": [15], "deferred_original_body_versions": [16],
        "creative_body_capacity_regranted": False, "new_review_capacity_granted": 0,
        "diagnostic_only": True, "source_claims_adopted": False, "text_ready_for_director": False,
        "reasoning_text_displayed": False, "no_replanning": True}


def decision(native, prepared):
    domain = audit().validate_claims(native, prepared["original_domain_prepared"])
    return {"valid": domain["valid"], "diagnostic_only": True, "creative_adoption": False,
        "actual_request_sha256": digest(prepared["request"]), "native_report_sha256": digest(native),
        "original_domain_prepared_sha256": digest(prepared["original_domain_prepared"]),
        "original_domain_request_sha256": digest(prepared["original_domain_prepared"]["request"]),
        "original_request_identity_claimed_for_new_call": False, "source_contract_decision": domain}


class Runtime(base.Runtime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.stage_limits = deepcopy(LIMITS)
    def _policy(self):
        value = super()._policy(); value.update(schema=VERSION+"/runtime_policy", total_new_calls_limit=1, **capacity()); return value
    def _request_gate(self, request):
        if request != read(self.root/"FIRST_REQUEST_PREVIEW.json")["request"]:
            raise ValueError("only exact source-reasoning diagnostic request may dispatch")
        clients().expected_wire_request(request)


class Driver:
    def __init__(self, session, runtime, inputs, wf):
        self.session, self.runtime, self.inputs, self.wf, self.calls = session, runtime, inputs, wf, []
    def flow(self):
        prepared = self.session._prepared()
        native, checked, row = mechanics.dispatch(self, POLICY, LABEL, prepared, lambda value: decision(value, prepared))
        return {"native_report": native, "diagnostic_validation": checked, "receipt_identity": row,
            "actual_request_sha256": digest(prepared["request"]),
            "original_domain_prepared_sha256": digest(prepared["original_domain_prepared"]),
            "diagnostic_only": True, "source_claims_adopted": False, "reasoning_text_displayed": False}


class Session(base.Session):
    POLICY, driver_type = POLICY, Driver
    def __init__(self, *args, **kwargs):
        if kwargs.get("client_factory_builder") is None: kwargs["client_factory_builder"] = lambda req: clients().make_client_factory(req)
        super().__init__(*args, **kwargs)
    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_source_claims_unknown_spend_anchor_v1").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256); scope = anchor["current_text_scope_accounting"]
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor["inherited"] or scope["limits"] != PARENT_LIMITS
                or scope["consumed"] != PARENT_USED or scope["remaining"] != PARENT_REMAINING
                or scope["body_used"] != 0 or scope["body_limit"] != 1
                or scope.get("calls_used") != 1 or scope.get("calls_remaining") != 7):
            raise ValueError("known685 and exact unspent body15/six reviews required")
        for key in ("inputs", "profile"):
            p = base._inside(anchor["current_"+key+"_path"])
            if sha(p) != anchor["current_"+key+"_file_sha256"] or digest(read(p)) != anchor["current_"+key+"_sha256"]:
                raise ValueError("current authority changed")
        return anchor, checked
    def _workflow(self): return audit()
    def _prepared(self):
        anchor = read(self.config.parent_anchor_path)
        receipt, old_native = prior.original_material.references._ref_document(anchor["latest_source_claims_receipt"])
        original = prior.original_material.referenced_json(anchor["latest_source_claims_prepared_ref"])
        old_decision = prior.original_material.referenced_json(anchor["latest_source_claims_decision_ref"])
        if (receipt["request"] != original["request"] or receipt.get("validation") != old_decision
                or receipt["status"] != "contract_valid" or old_decision.get("valid") is not True
                or old_decision.get("claims_usable") is not False or original["views"]["inputs"] != read(anchor["current_inputs_path"])
                or original["views"]["profile"] != self.profile or audit().validate_claims(old_native, original) != old_decision):
            raise ValueError("original685 source/native/domain identity differs; not adopted")
        request = clients().bind_request(original["request"])
        return {"request": request, "request_sha256": digest(request), "wire": clients().expected_wire_request(request),
            "original_domain_prepared": original, "source_domain_context_sha256": original["context_sha256"],
            "manifest": {"schema": VERSION+"/prepared", "original_domain_prepared_sha256": digest(original),
                "actual_request_sha256": digest(request), "domain_request_identity_is_actual_request": False,
                "messages_schema_and_source_unchanged": True, "diagnostic_only": True}}
    def source_material(self, wf): return {"diagnostic_prepared": self._prepared()}
    @staticmethod
    def first_prepared(inputs, wf, seed): return seed["diagnostic_prepared"]
    def preview(self): return mechanics.preview(self, POLICY)
    def authorization_template(self, preview):
        return {"schema": VERSION+"/authorization", "root": str(self.root), "grant_id": self.config.grant_id,
            "preparation_identity_sha256": preview["preparation_identity_sha256"], "inherited": preview["inherited"],
            "inputs_sha256": preview["inputs_sha256"], "parent_anchor_sha256": self.config.parent_anchor_sha256,
            "creative_source_root": preview["creative_source_root"], "stage_limits": deepcopy(LIMITS), "total_new_calls_limit": 1,
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "automatic_retry": False, "old_budget_reset": False, "media_authorized": False, "publish_authorized": False,
            "whole_plan_limit": 0, "opening_setup_limit": 0, "content_revision_limit": 0, **capacity()}
    def _binding(self, parent):
        value = super()._binding(parent); value.update(schema=VERSION+"/successor_claim", stage_limits=deepcopy(LIMITS), **capacity()); return value
    def prepare(self): return mechanics.prepare(self, POLICY)
    def _guard(self): return mechanics.guard(self, POLICY)
    @staticmethod
    def stage_for_label(label):
        if label != LABEL: raise ValueError("only source reasoning diagnostic registered")
        return "full_review"
    def _admit(self, label, request, ledger):
        self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if label != LABEL or ledger["calls"] or request.get("stage") != "full_review": raise ValueError("one diagnostic only")
        pending = self.pending_intent
        if not pending or pending["label"] != label or sha(pending["path"]) != pending["sha256"]: raise ValueError("original intent missing")
        intent = read(pending["path"])
        if (intent.get("schema") != VERSION+"/call_intent" or intent["prepared"]["request"] != request
                or intent["request_sha256"] != digest(request) or intent["ledger_prefix_sha256"] != digest([])
                or intent["inputs_sha256"] != digest(read(self.root/"INPUTS.json")) or self._replay(ledger, label)["request"] != request):
            raise ValueError("exact one-call reasoning request cannot be rebuilt")
        clients().expected_wire_request(request); return True
    def runtime(self):
        freeze = read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            inherited_guard=self._guard, admission=self._admit, quota_state=None,
            shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock", client_factory_builder=self.client_factory_builder)
    def _replay(self, ledger, label=None, *, verify_validations=False):
        prepared = self._prepared(); rows = ledger["calls"]
        if not rows:
            if label == LABEL: return prepared
            raise ValueError("diagnostic not dispatched")
        if len(rows) != 1 or label is not None: raise ValueError("one diagnostic receipt required")
        row = rows[0]; receipt = read(self.root/row["receipt"])
        if row["label"] != LABEL or sha(self.root/row["receipt"]) != row["receipt_sha256"] or receipt["request"] != prepared["request"]:
            raise ValueError("original diagnostic request differs")
        native = prior.original_material.native_proof.known_native(receipt); checked = decision(native, prepared)
        if verify_validations and receipt.get("validation") != checked: raise ValueError("diagnostic validation changed")
        return {"native_report": native, "diagnostic_validation": checked,
            "receipt_identity": {**{k:row[k] for k in ("label","ordinal","receipt","request_sha256")}, "status": receipt["status"]},
            "actual_request_sha256": digest(prepared["request"]), "original_domain_prepared_sha256": digest(prepared["original_domain_prepared"]),
            "diagnostic_only": True, "source_claims_adopted": False, "reasoning_text_displayed": False}
    def state_metadata(self): return capacity()
    def state(self, runtime, status, **details): return mechanics.state(self, POLICY, runtime, status, **details)
    def _save_text(self, result, driver, runtime):
        write(self.root/"DIAGNOSTIC_RESULT.json", result, True)
        return self.state(runtime, "diagnostic_completed_not_creative", diagnostic_result_sha256=digest(result))
    def run(self): return mechanics.run(self, POLICY)


def verify_diagnostic(root):
    session = Session.open(root); session._guard(); runtime = session.runtime(); ledger = read(runtime.ledger); state = read(session.root/"STATE.json")
    if (state.get("status") != "diagnostic_completed_not_creative" or state.get("spend_verification_pending") is not False
            or state.get("run_claim_sha256") != sha(session.root/"RUN_CLAIM.json")):
        raise ValueError("known complete diagnostic required; unknown/protocol failure cannot be adopted")
    spend = runtime.summary()
    if spend != state["spend"] or spend["new_unknown_token_reservations"] or len(ledger["calls"]) != 1: raise ValueError("settled one-call accounting required")
    reader = base.evidence.Reader(); receipts = [clients().verify_original_receipt(session.root, r, ledger["source_manifest"], reader=reader) for r in ledger["calls"]]
    base.evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    result = session._replay(ledger, verify_validations=True)
    intent = read(session.root/"call_intents"/(LABEL+".json"))
    if (intent.get("schema") != VERSION+"/call_intent" or intent["ledger_prefix_sha256"] != digest([])
            or intent.get("label") != LABEL or intent.get("automatic_retry") is not False
            or intent.get("inputs_sha256") != digest(read(session.root/"INPUTS.json"))
            or intent.get("request_sha256") != result["actual_request_sha256"]
            or intent["prepared"] != session._prepared() or result != read(session.root/"DIAGNOSTIC_RESULT.json")
            or digest(result) != state.get("diagnostic_result_sha256")):
        raise ValueError("original diagnostic result/intent differs")
    files = {**read(session.root/"PRODUCTION_FREEZE.json")["files"], **{p:v["sha256"] for p,v in reader.files.items()},
        **base._hashes(session.root/(n+".json") for n in ("STATE","CALL_LEDGER","PRODUCTION_FREEZE","RUN_CLAIM","DIAGNOSTIC_RESULT"))}
    return {"schema": VERSION+"/verified_diagnostic", "valid": True, "diagnostic_only": True,
        "root":str(session.root),"spend":spend,"source_files":files,"native_report_sha256":digest(result["native_report"]),
        "actual_request_sha256":result["actual_request_sha256"],"source_claims_adopted":False,
        "text_ready_for_director":False,"authorizes_dispatch":False,"authorizes_media_dispatch":False,"reasoning_text_displayed":False}


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("preview","authorization","prepare","run","verify"));p.add_argument("path");a=p.parse_args()
    if a.action=="verify": value=verify_diagnostic(a.path)
    else:
        s=Session.open(a.path) if a.action=="run" else Session(read(a.path))
        value=s.authorization_template(s.preview()) if a.action=="authorization" else getattr(s,a.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
