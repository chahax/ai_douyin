"""One same-source DeepSeek planning-state diagnostic; no creative/media stage."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

from scripts import creative_world_scene_live_session_v1 as base
from scripts import creative_world_scene_live_session_v3 as references
from scripts import creative_world_scene_array_probe_session_v1 as native_proof

VERSION="creative_world_scene_source_state_audit_session/v1"
Config=base.Config
LIMITS={"goal_plan":0,"goal_audit":1,"complete_script":0,"full_review":0}
LABEL="source_state_audit_01"
read,write,digest,sha=base.read,base.write,base.digest,base.sha


def creative_root(anchor):
    root=base._inside(anchor["creative_source_root"])
    for name in ("INPUTS.json","SESSION_CONFIG.json"):
        path=root/name;expected=anchor["source_files"].get(str(path))
        if type(expected) is dict:expected=expected.get("sha256")
        if not expected or sha(path)!=expected:raise ValueError("certified original creative authority changed")
    return root


def material(anchor):
    return {"goal":references._ref_document(anchor["native_goal_receipt"])[1],
        "setup":references._ref_document(anchor["native_opening_setup_receipt"])[1]}


class Runtime(base.Runtime):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,stage_limits=base.LIMITS,**kwargs);self.stage_limits=deepcopy(LIMITS)
    def _policy(self):
        value=super()._policy();value.update(schema=VERSION+"/runtime_policy",diagnostic_only=True,total_new_calls_limit=1,
            whole_plan_limit=0,opening_setup_limit=0,full_review_parts_per_complete_script=0,
            old_complete_body_calls_used=8,old_complete_body_capacity=8,diagnostic_calls_previously_used=4,
            review_max_completion_tokens=32000,no_creative_stage_authorized=True)
        return value


class Session(base.Session):
    def __init__(self,*args,audit_module=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.audit=audit_module or importlib.import_module("scripts.creative_world_scene_source_state_audit_v1")

    def _parent(self):
        anchor=read(self.config.parent_anchor_path)
        verifier=self.parent_verifier or importlib.import_module("scripts.creative_world_scene_known_text_spend_anchor_v1").verify_anchor
        checked=verifier(anchor,expected_anchor_sha256=self.config.parent_anchor_sha256)
        if(digest(anchor)!=self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited")!=anchor.get("inherited") or not anchor.get("creative_source_root")):
            raise ValueError("original settled662 accounting and creative source required")
        creative_root(anchor);return anchor,checked

    def _profile_gate(self):
        a=read(self.config.parent_anchor_path);original=creative_root(a)
        original_profile=read(read(original/"SESSION_CONFIG.json")["profile_path"])
        if original_profile.get("stage_parameters",{}).get("goal_audit",{}).get("max_completion_tokens")!=16000:
            raise ValueError("certified original goal-audit cap must be16000 before this explicit32000 diagnostic scope")
        expected=deepcopy(original_profile)
        expected.setdefault("stage_parameters",{}).setdefault("goal_audit",{})["max_completion_tokens"]=32000
        if self.profile!=expected:raise ValueError("only goal_audit output cap may change to32000; original roles/model/thinking must remain exact")
        if (expected["director"]["model"]!=base.clients.REVIEW_MODEL or expected["director"]["parameters"]["temperature"]!=.4
                or expected["director"]["parameters"]["thinking"]!="disabled"):
            raise ValueError("exact current DeepSeek reviewer profile required")
        return self.profile

    def _request(self,inputs=None):
        a=read(self.config.parent_anchor_path);source=material(a)
        inputs=read(creative_root(a)/"INPUTS.json") if inputs is None else inputs
        if any(k in inputs for k in ("previous_complete_document","revision_diagnostics")):
            raise ValueError("source diagnosis cannot use a rejected body or human repair answer as template")
        prepared=self.audit.prepare(inputs,self.profile,source["goal"],source["setup"])
        request=prepared["request"]
        if (request.get("stage")!="goal_audit" or request.get("role")!="director"
                or request["parameters"].get("max_completion_tokens")!=32000):raise ValueError("one32000-token reviewer diagnostic required")
        base.clients.expected_wire_request(request);return prepared

    def preview(self):
        a,checked=self._parent();built=self._inputs();self._profile_gate();original=read(creative_root(a)/"INPUTS.json")
        if built["inputs"]!=original:raise ValueError("exact current original creative INPUTS required")
        request=self._request(original)
        files=base._hashes([*built["source_files"],self.config.parent_anchor_path,self.config.profile_path,
            self.config.preferences_path,self.config.user_goals_path,*self.config.extra_source_files,*self.code_files()])
        for path,item in checked.get("source_files",{}).items():
            expected=item.get("sha256") if type(item) is dict else item
            if sha(base._inside(path))!=expected:raise ValueError("certified original parent changed")
            files[str(base._inside(path))]=expected
        value={"schema":VERSION+"/preview","root":str(self.root),"grant_id":self.config.grant_id,"inputs":original,
            "input_evidence":built["evidence"],"inputs_sha256":digest(original),"first_request":request,
            "profile_sha256":sha(self.config.profile_path),"parent_anchor_sha256":digest(a),"parent_root":a["root"],
            "parent_identity":a["parent_identity"],"inherited":checked["inherited"],"creative_source_root":str(creative_root(a)),
            "source_files":files,"stage_limits":deepcopy(LIMITS),"total_new_calls_limit":1,"provider_calls":0,"media_calls":0,
            "only_profile_difference":{"stage_parameters.goal_audit.max_completion_tokens":{"previous":16000,"current":32000}}}
        value["preparation_identity_sha256"]=digest({k:value[k] for k in (
            "root","grant_id","inputs_sha256","profile_sha256","parent_anchor_sha256","inherited","source_files","first_request")})
        return value

    def authorization_template(self,preview):
        return {"schema":VERSION+"/derived_authorization","root":str(self.root),"grant_id":self.config.grant_id,
            "preparation_identity_sha256":preview["preparation_identity_sha256"],"inputs_sha256":preview["inputs_sha256"],
            "parent_anchor_sha256":self.config.parent_anchor_sha256,"inherited":preview["inherited"],
            "stage_limits":deepcopy(LIMITS),"total_new_calls_limit":1,"diagnostic_only":True,
            "creative_source_root":preview["creative_source_root"],"old_complete_body_calls_used":8,"old_complete_body_capacity":8,
            "diagnostic_calls_previously_used":4,"old_director_capacity":base.DIRECTOR,
            "only_profile_difference":preview["only_profile_difference"],"counter_root":str(Path(self.config.counter_root).resolve()),
            "round_key":self.config.round_key,"automatic_retry":False,"old_budget_reset":False,
            "media_authorized":False,"publish_authorized":False,"creative_stage_authorized":False,
            "new_authority":"user autonomous text repair and necessary DeepSeek review; one source-state diagnostic only"}

    def _binding(self,parent):
        value=super()._binding(parent);value.update(schema=VERSION+"/successor_claim",diagnostic_only=True);return value

    def _guard(self):
        super()._guard();a=read(self.config.parent_anchor_path);scope=read(self.root/"USER_SCOPE.json")
        if(scope.get("schema")!=VERSION+"/derived_authorization" or scope.get("stage_limits")!=LIMITS
                or any(type(v) is not int for v in scope["stage_limits"].values())
                or type(scope.get("total_new_calls_limit")) is not int or scope["total_new_calls_limit"]!=1
                or scope.get("diagnostic_only") is not True or scope.get("creative_stage_authorized") is not False
                or scope.get("old_complete_body_calls_used")!=8 or scope.get("old_complete_body_capacity")!=8
                or scope.get("diagnostic_calls_previously_used")!=4 or scope.get("old_director_capacity")!=base.DIRECTOR
                or scope.get("inherited")!=a["inherited"] or scope.get("parent_anchor_sha256")!=self.config.parent_anchor_sha256
                or digest(a)!=self.config.parent_anchor_sha256 or scope.get("creative_source_root")!=str(creative_root(a))):
            raise ValueError("exact one-call source-diagnostic scope differs")
        if read(self.root/"INPUTS.json")!=read(creative_root(a)/"INPUTS.json"):raise ValueError("original current inputs changed")
        self._profile_gate()
        p=self.root/"RUN_CLAIM.json"
        if p.exists():
            c=read(p)
            if not(c.get("schema")==VERSION+"/run_claim" and c.get("root")==str(self.root) and type(c.get("pid")) is int and c["pid"]>0
                    and c.get("automatic_restart") is False and c.get("freeze_sha256")==sha(self.root/"PRODUCTION_FREEZE.json")):
                raise ValueError("single-use source-diagnostic RUN differs")
        return True

    def runtime(self):
        f=read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT,self.root,list(f["files"]),f["inherited"],profile=self.profile,inherited_guard=self._guard,
            admission=self._admit,shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def _admit(self,label,request,ledger):
        self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if label!=LABEL or ledger["calls"]:raise ValueError("single source-audit capacity exhausted or unregistered label")
        if request!=self._request(read(self.root/"INPUTS.json"))["request"]:raise ValueError("exact same-source diagnostic builder differs")
        p=self.pending_intent
        if not p or p["label"]!=label or sha(p["path"])!=p["sha256"]:raise ValueError("original builder intent missing")
        i=read(p["path"])
        if(i["request"]!=request or i["request_sha256"]!=digest(request) or i["ledger_prefix_sha256"]!=digest(ledger["calls"])):
            raise ValueError("original native call intent differs")
        return True

    def state(self,rt,status,**details):
        value=base.NativeSession.state(self,rt,status,**details)
        value.update(schema=VERSION+"/state",diagnostic_only=True,text_ready_for_director=False,
            new_stage_limits=deepcopy(LIMITS),old_complete_body_calls_used=8,diagnostic_calls_previously_used=4)
        if(self.root/"RUN_CLAIM.json").exists():value["run_claim_sha256"]=sha(self.root/"RUN_CLAIM.json")
        write(self.root/"STATE.json",value);return value

    def _save(self,rt,status,decision=None,native=None,receipt=None,details=None):
        paths={}
        if native is not None:
            path=self.root/"NATIVE_SOURCE_STATE_AUDIT.json";write(path,native,True);paths["native_audit"]=str(path)
        if decision is not None:
            path=self.root/"SOURCE_STATE_AUDIT_DECISION.json";write(path,decision,True);paths["derived_decision"]=str(path)
        state=self.state(rt,status,**(details or {}))
        summary={"schema":VERSION+"/summary","status":status,"diagnostic_only":True,"paths":paths,
            "artifact_file_sha256":base._hashes(paths.values()),"native_audit_sha256":digest(native) if native is not None else None,
            "derived_decision_sha256":digest(decision) if decision is not None else None,
            "receipt_ordinal":receipt["ordinal"] if receipt is not None else None,"spend":deepcopy(state["spend"]),
            "spend_verification_pending":state["spend_verification_pending"],"stop_details":details or {},
            "text_ready_for_director":False,"human_quality_approved":False,"creative_quality_passed":False,"media_submitted":False}
        write(self.root/"SUMMARY.json",summary,True);state["summary_sha256"]=digest(summary);write(self.root/"STATE.json",state);return state

    def run(self):
        if not(self.root/"PRODUCTION_FREEZE.json").is_file():raise ValueError("separately prepared audit root required")
        base.policy.new_claim(self.root/"RUN_CLAIM.json",{"schema":VERSION+"/run_claim","root":str(self.root),"pid":base.os.getpid(),
            "started_at":self.clock(),"automatic_restart":False,"freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json")})
        rt=None
        try:
            rt=self.runtime();self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]:raise ValueError("nonempty original RUN cannot restart")
            prepared=self._request(read(self.root/"INPUTS.json"));path=self.root/"call_intents"/(LABEL+".json")
            write(path,{"schema":VERSION+"/call_intent","label":LABEL,"request":prepared["request"],"request_sha256":digest(prepared["request"]),
                "ledger_prefix_sha256":digest(read(rt.ledger)["calls"]),"automatic_retry":False},True)
            self.pending_intent={"label":LABEL,"path":str(path),"sha256":sha(path)}
            receipt=base.policy.dispatch_claimed(rt,LABEL,prepared,lambda value:self.audit.validate(value,prepared),root=self.root,
                grant_id=self.config.grant_id,stage_limits=LIMITS,current_round_root=self.config.counter_root,current_round_key=self.config.round_key,guard=self._guard)
            native=native_proof.known_native(receipt);decision=base._decision(receipt)
            status=("halt_source_state_audit_contract" if decision.get("valid") is not True else
                "halt_source_state_audit_uncertain" if decision.get("uncertainties") else
                "diagnostic_completed_known_content_failure" if decision.get("accepted") is False else
                "diagnostic_completed_not_creative" if decision.get("accepted") is True else "halt_source_state_audit_contract")
            return self._save(rt,status,decision,native,receipt)
        except base.Halt as stop:return self._save(rt,stop.status,details=stop.details)
        except Exception as exc:
            write(self.root/"EXECUTION_ERROR.json",{"type":type(exc).__name__,"message":str(exc),"automatic_restart":False},True)
            return self._save(rt,"halt_execution_reconciliation",details={"exception_type":type(exc).__name__,"error":str(exc)})


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("preview","authorization","prepare","run"));p.add_argument("path")
    args=p.parse_args();s=Session.open(args.path) if args.action=="run" else Session(read(args.path))
    value=s.authorization_template(s.preview()) if args.action=="authorization" else getattr(s,args.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
