"""Fixed v9 continuation: isolated events then entailment; no capacity regrant."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v8 as prior
from scripts import creative_world_scene_continuation_mechanics_v1 as mechanics

base,references,source_refs,native_proof=prior.base,prior.references,prior.source_refs,prior.native_proof
read,write,digest,sha=prior.read,prior.write,prior.digest,prior.sha
Config=prior.Config
VERSION="creative_world_scene_live_session/v9"
LIMITS={"goal_plan":0,"goal_audit":0,"complete_script":2,"full_review":8}
TOTAL=sum(LIMITS.values())
BODY_VERSIONS=[15,16]
PARENT_LIMITS=deepcopy(prior.LIMITS)
PARENT_USED={"goal_plan":0,"goal_audit":0,"complete_script":0,"full_review":1}
PARENT_REMAINING={key:value-PARENT_USED[key] for key,value in PARENT_LIMITS.items()}
LABELS=r"complete_script_(?:15|16)|(?:observable_events|event_entailment)_(?:calibration_14|15|16)|full_review_(?:semantic|physical)_(?:15|16)"
POLICY=mechanics.FixedPolicy(VERSION,tuple(LIMITS.items()),LABELS)
REF_KEYS=(*prior.REF_KEYS,"latest_calibration_receipt","latest_calibration_decision_ref","latest_calibration_prepared_ref")


class Runtime(prior.Runtime):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.stage_limits=deepcopy(LIMITS)
    def _policy(self):
        value=super()._policy();value.update(schema=VERSION+"/runtime_policy",total_new_calls_limit=TOTAL,
            parent_scope_stage_limits=PARENT_LIMITS,parent_scope_stage_calls=PARENT_USED,parent_scope_remaining=PARENT_REMAINING,
            parent_scope_calls_used=1,parent_scope_calls_remaining=10,parent_unused_body_calls=2,
            creative_body_capacity_regranted=False,unused_capacity_is_original_grant_balance_only=True,
            isolated_events_before_entailment=True,min_reviews_before_body=4)
        return value


class Driver(prior.Driver):
    def reserve_complete_chain(self,label):
        if not label.startswith("complete_script_"):return
        remaining=LIMITS["full_review"]-sum(not row["label"].startswith("complete_script_") for row in self.calls)
        if remaining<4:
            used={row["label"] for row in self.calls}
            raise base.Halt("halt_review_capacity_for_complete_chain",remaining_reviews=remaining,required_reviews=4,
                unused_body_versions=[v for v in BODY_VERSIONS if f"complete_script_{v:02}" not in used],
                original_body_capacity_preserved=True)
    def invoke(self,label,prepared,validator):
        self.reserve_complete_chain(label)
        return mechanics.dispatch(self,POLICY,label,prepared,validator)
    def _focused(self,native,views,label):
        match=re.fullmatch(r"enacted_causality_(calibration_14|15|16)",label)
        if not match:raise ValueError("fixed inherited body-flow comparison label required")
        suffix=match[1]
        events_prepared=self.wf.prepare_observable_events_request(self.inputs,self.profile,native,views)
        events,events_decision,_=self.invoke("observable_events_"+suffix,events_prepared,
            lambda value:self.wf.validate_observable_events(value,events_prepared))
        if not self.audit_gate(events_decision,"observable_events"):
            raise base.Halt("halt_observable_events_requires_diagnosis",native_events_report=events,decision=events_decision)
        if events_decision.get("ledger_usable") is not True:raise base.Halt("halt_observable_events_requires_diagnosis",decision=events_decision)
        prepared=self.wf.prepare_event_entailment_request(self.inputs,self.profile,native,views,events,events_prepared)
        comparison,decision,_=self.invoke("event_entailment_"+suffix,prepared,
            lambda value:self.wf.validate_event_entailment(value,prepared))
        accepted=self.audit_gate(decision,"event_entailment")
        if decision.get("requires_new_goal_plan"):
            raise base.Halt("halt_requires_new_complete_goal",native_entailment_report=comparison,decision=decision,no_replanning_authorized=True)
        typed=importlib.import_module("scripts.creative_isolated_event_entailment_v1")
        if not accepted:
            packet=typed.build_repair_feedback(events,events_prepared,comparison,prepared)
        else:
            packet=typed.build_review_packet(events,events_prepared,comparison,prepared)
        packet.update(coordinator_packet_schema=VERSION+"/two_native_report_packet",packet_is_model_native=False)
        return accepted,packet,decision


class Session(prior.Session):
    POLICY=POLICY
    REF_KEYS=REF_KEYS
    driver_type=Driver
    def _parent(self):
        anchor=read(self.config.parent_anchor_path)
        verifier=self.parent_verifier or importlib.import_module("scripts.creative_world_scene_calibration_spend_anchor_v1").verify_anchor
        checked=verifier(anchor,expected_anchor_sha256=self.config.parent_anchor_sha256)
        accounting=anchor.get("current_text_scope_accounting",{})
        if (digest(anchor)!=self.config.parent_anchor_sha256 or checked.get("verified") is not True or checked.get("inherited")!=anchor.get("inherited")
                or accounting.get("limits")!=PARENT_LIMITS or accounting.get("consumed")!=PARENT_USED or accounting.get("remaining")!=LIMITS
                or accounting.get("calls_used")!=1 or accounting.get("calls_remaining")!=10 or accounting.get("body_used")!=0 or accounting.get("body_limit")!=2
                or anchor.get("current_body_versions_unused")!=BODY_VERSIONS
                or anchor.get("unused_capacity_is_original_grant_balance_only") is not True
                or anchor.get("creative_body_capacity_regranted") is not False or not anchor.get("continuation_of_original_grant")):
            raise ValueError("known calibration parent and exact unused original 2body/8review balance required")
        source_refs.creative_root(anchor)
        for key in ("inputs","profile"):
            path=base._inside(anchor["current_"+key+"_path"])
            if sha(path)!=anchor["current_"+key+"_file_sha256"] or digest(read(path))!=anchor["current_"+key+"_sha256"]:raise ValueError("current authority changed")
        return anchor,checked
    def _workflow(self):
        adapter=self._reviews(read(self.root/"USER_SCOPE.json")) if (self.root/"USER_SCOPE.json").exists() else self.injected_review_adapter
        return importlib.import_module("scripts.creative_world_scene_replanned_workflow_v5").ReviewWorkflow(base.workflow,adapter)
    @staticmethod
    def first_prepared(inputs,wf,seed):
        return wf.prepare_observable_events_request(inputs,seed["_caller_profile"],seed["calibration_native_script"],seed["calibration_views"])
    def source_material(self,wf):return {**super().source_material(wf),"_caller_profile":self.profile}
    def preview(self):return mechanics.preview(self,POLICY)
    def authorization_template(self,preview):
        value=super().authorization_template(preview);anchor=read(self.config.parent_anchor_path)
        value.update(schema=VERSION+"/remaining_capacity_authorization",stage_limits=deepcopy(LIMITS),total_new_calls_limit=TOTAL,
            parent_scope_stage_limits=PARENT_LIMITS,parent_scope_stage_calls=PARENT_USED,parent_scope_remaining=PARENT_REMAINING,
            parent_scope_calls_used=1,parent_scope_calls_remaining=10,parent_unused_body_calls=2,
            continuation_of_original_grant=anchor["continuation_of_original_grant"],
            original_grant_scope_sha256=sha(Path(anchor["root"])/"USER_SCOPE.json"),
            unused_capacity_is_original_grant_balance_only=True,creative_body_capacity_regranted=False,
            isolated_events_before_entailment=True,min_reviews_before_body=4,
            new_authority="continue only the original unused two bodies15-16 and eight reviews; no new body/review capacity, source/goal/media")
        return value
    def _binding(self,parent):
        value=super()._binding(parent);value.update(schema=VERSION+"/successor_claim",
            continuation_of_original_grant=parent["continuation_of_original_grant"],remaining_original_capacity=deepcopy(LIMITS),creative_body_capacity_regranted=False)
        return value
    def prepare(self):return mechanics.prepare(self,POLICY)
    def _guard(self):return mechanics.guard(self,POLICY)
    def _admit(self,label,request,ledger):return mechanics.admit(self,POLICY,label,request,ledger)
    @staticmethod
    def stage_for_label(label):return "complete_script" if label.startswith("complete_script_") else "full_review"
    def runtime(self):
        freeze=read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT,self.root,list(freeze["files"]),freeze["inherited"],profile=self.profile,inherited_guard=self._guard,
            admission=self._admit,shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",quota_state=None,client_factory_builder=self.client_factory_builder)
    def _replay(self,ledger,label=None,*,verify_validations=False):
        owner,rows=self,ledger["calls"]
        class Replay(Driver):
            def invoke(self,current,prepared,validator):
                self.reserve_complete_chain(current)
                if self.position==len(rows):
                    if current!=label:raise ValueError("fixed isolated-event sequence differs")
                    raise prior.body_flow.NextRequest(prepared)
                row=rows[self.position];self.position+=1;path=owner.root/row["receipt"];receipt=read(path)
                if current!=row["label"] or sha(path)!=row["receipt_sha256"] or receipt["request"]!=prepared["request"]:raise ValueError("original prerequisite differs")
                native,decision=native_proof.known_native(receipt),base._decision(receipt)
                if verify_validations and receipt["status"]=="contract_valid" and validator(native)!=decision:raise ValueError("same-source validation changed")
                self.calls.append(row);return native,decision,row
        replay=Replay(self,None,read(self.root/"INPUTS.json"),self._workflow());replay.position=0
        try:result=replay.flow()
        except prior.body_flow.NextRequest as found:
            if label is None:raise ValueError("handoff native flow unfinished")
            return found.prepared
        if label is not None or replay.position!=len(rows):raise ValueError("terminal flow or extra receipts")
        return result
    def state_metadata(self):
        return {"old_complete_body_calls_used":14,"old_complete_body_capacity":14,"reuses_accepted_source_state":True,
            "parent_scope_stage_calls":PARENT_USED,"parent_scope_remaining":PARENT_REMAINING,
            "unused_capacity_is_original_grant_balance_only":True,"creative_body_capacity_regranted":False,
            "isolated_events_before_entailment":True,"min_reviews_before_body":4,"no_replanning":True}
    def state(self,runtime,status,**details):return mechanics.state(self,POLICY,runtime,status,**details)
    def artifacts(self,result):
        values=prior._values(result)
        extra={"observable_events_report":result["native_enacted_review"]["native_observable_events_report"],
            "event_entailment_report":result["native_enacted_review"]["native_claim_comparison_report"],
            "compiled_observable_ledger":result["native_enacted_review"]["verified_compiled_event_ledger"]}
        values.update(extra)
        paths={"inputs":self.root/"INPUTS.json","profile":Path(self.config.profile_path)}
        names={"goal":"goal/NATIVE_GOAL.json","goal_audit_bundle":"goal/NATIVE_GOAL_AUDIT_BUNDLE.json","setup":"opening/NATIVE_OPENING_SETUP.json",
            "source_state_audit":"goal/NATIVE_SOURCE_STATE_AUDIT.json","source_state_decision":"goal/SOURCE_STATE_DECISION.json",
            "raw_script":"scripts/NATIVE_SCRIPT.json","derived_script":"scripts/DERIVED_CANONICAL_SCRIPT.json","compiled_script":"scripts/COMPILED_SCRIPT.json",
            "source_descriptor":"scripts/SCRIPT_SOURCE_DESCRIPTOR.json","full_review_bundle":"scripts/NATIVE_FULL_REVIEW_BUNDLE.json",
            "enacted_review":"scripts/TWO_NATIVE_REVIEW_PACKET.json","enacted_review_decision":"scripts/ENTAILMENT_DECISION.json","calibration":"scripts/CALIBRATION_RESULT.json",
            "observable_events_report":"scripts/NATIVE_OBSERVABLE_EVENTS.json","event_entailment_report":"scripts/NATIVE_EVENT_ENTAILMENT.json",
            "compiled_observable_ledger":"scripts/COMPILED_OBSERVABLE_LEDGER.json"}
        paths.update({key:self.root/path for key,path in names.items()});return paths,values
    @staticmethod
    def extra_identities(values):
        return {"enacted_review_sha256":digest(values["enacted_review"]),"observable_events_sha256":digest(values["observable_events_report"]),
            "event_entailment_sha256":digest(values["event_entailment_report"]),"compiled_observable_ledger_sha256":digest(values["compiled_observable_ledger"])}
    def _save_text(self,result,driver,runtime):return mechanics.save_text(self,POLICY,result,driver,runtime)
    def run(self):return mechanics.run(self,POLICY)


def verify_text_handoff(root):return mechanics.verify_handoff(Session.open(root),POLICY)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("action",choices=("preview","authorization","prepare","run","verify"));parser.add_argument("path");args=parser.parse_args()
    if args.action=="verify":value=verify_text_handoff(args.path)
    else:
        session=Session.open(args.path) if args.action=="run" else Session(read(args.path))
        value=session.authorization_template(session.preview()) if args.action=="authorization" else getattr(session,args.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
