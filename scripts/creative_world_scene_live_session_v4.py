"""Clean-first direct-wire screenplay continuation; canonical local checks stay strict."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v1 as base
from scripts import creative_world_scene_live_session_v3 as previous
from scripts import creative_world_scene_script_contract_v2 as contract

VERSION="creative_world_scene_live_session/v4"
Config=base.Config
LIMITS={"goal_plan":0,"goal_audit":0,"complete_script":2,"full_review":4}
TOTAL=6
BODY_VERSIONS=[7,8]
read,write,digest,sha=base.read,base.write,base.digest,base.sha


def material(anchor):
    """No failed body or toy diagnostic is used as the first writer template."""
    goal=previous._ref_document(anchor["native_goal_receipt"])[1]
    reports={kind:previous._ref_document(anchor["native_goal_audit_receipts"][kind])[1] for kind in base.workflow.AUDITS}
    setup=previous._ref_document(anchor["native_opening_setup_receipt"])[1]
    return {"goal":goal,"audit_bundle":base.workflow.build_goal_audit_bundle(*(reports[k] for k in base.workflow.AUDITS)),"setup":setup}


def creative_root(anchor):
    root=base._inside(anchor["creative_source_root"])
    if root==Path(anchor["root"]).resolve():raise ValueError("toy diagnostic root is not creative authority")
    for name in ("INPUTS.json","SESSION_CONFIG.json"):
        path=root/name;expected=anchor["source_files"].get(str(path))
        if type(expected) is dict:expected=expected.get("sha256")
        if not expected or sha(path)!=expected:raise ValueError("certified original creative authority changed")
    return root


class ReviewWorkflow(base.ReviewWorkflow):
    def __init__(self,workflow,adapter):
        super().__init__(workflow,adapter);self.body_preparations=0

    def prepare_script_request(self,inputs,profile,goal,audit,**kwargs):
        if self.body_preparations>=2:raise base.stages.OfflineStop("halt_live_script_capacity")
        self.body_preparations+=1
        result=super().prepare_script_request(inputs,profile,goal,audit,**kwargs)
        canonical=contract.refine_schema(result["request"]["structured_schema"])
        direct=importlib.import_module("scripts.creative_world_scene_direct_wire_schema_v1").prepare_schema(goal,canonical_schema=canonical)
        result["request"]["structured_schema"]=direct["schema"]
        result["request"]["messages"][0]["content"]+="\n"+contract.RELATION_RULE
        result["manifest"].update(direct_wire_representation=deepcopy(direct["manifest"]),
            canonical_local_schema_sha256=digest(canonical),actual_wire_schema_sha256=digest(direct["schema"]),
            wire_schema_is_full_local_contract=False,local_contract_uses_default_canonical=True,
            first_request_bad_native_seed_injected=False)
        return self.base._mark(result,inputs)

    def validate_script_document(self,native,views,production_preferences=None):
        contract.validate(native,views["goal"])
        return self.base.validate_script_document(native,views,production_preferences)

    def prepare_full_review_part_request(self,inputs,profile,native,views,part):
        self.validate_script_document(native,views,inputs["production_preferences"])
        return super().prepare_full_review_part_request(inputs,profile,native,views,part)


class Runtime(base.Runtime):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,stage_limits=base.LIMITS,**kwargs);self.stage_limits=deepcopy(LIMITS)
    def _policy(self):
        result=super()._policy();result.update(schema=VERSION+"/runtime_policy",total_new_calls_limit=6,
            body_versions_available=BODY_VERSIONS,old_complete_body_calls_used=6,old_complete_body_capacity=6,
            diagnostic_calls_previously_used=4,no_replanning=True,whole_plan_limit=0,opening_setup_limit=0,
            new_body_scope_is_separate=True,clean_first_writer_context=True)
        return result


def _label(label):
    match=re.fullmatch(r"(complete_script|full_review_semantic|full_review_physical)_0([12])",label)
    if not match:raise base.stages.OfflineStop("halt_live_script_capacity")
    return match[1]+f"_{int(match[2])+6:02}"


class Driver(base.LiveDriver):
    def invoke(self,label,prepared,validator):
        label=_label(label);s,rt=self.session,self.runtime;ledger=read(rt.ledger)
        if any(row["label"]==label for row in ledger["calls"]):raise base.Halt("halt_duplicate_live_stage",label=label)
        intent={"schema":VERSION+"/call_intent","label":label,"prepared":deepcopy(prepared),
            "request_sha256":digest(prepared["request"]),"ledger_prefix_sha256":digest(ledger["calls"]),
            "inputs_sha256":digest(self.inputs),"automatic_retry":False}
        path=s.root/"call_intents"/(label+".json");write(path,intent,True)
        s.pending_intent={"path":str(path),"sha256":sha(path),"label":label}
        receipt=base.policy.dispatch_claimed(rt,label,prepared,validator,root=s.root,grant_id=s.config.grant_id,
            stage_limits=LIMITS,current_round_root=s.config.counter_root,current_round_key=s.config.round_key,guard=s._guard)
        native=base.NativeSession.known(receipt,label,require_valid=False);decision=base._decision(receipt)
        self.calls.append({"label":label,"ordinal":receipt["ordinal"],"status":receipt["status"],"native_output":native,"validation":decision})
        return native,decision,self.calls[-1]


class Session(base.Session):
    def _parent(self):
        anchor=read(self.config.parent_anchor_path)
        verifier=self.parent_verifier or importlib.import_module("scripts.creative_world_scene_array_probe_spend_anchor_v1").verify_anchor
        checked=verifier(anchor,expected_anchor_sha256=self.config.parent_anchor_sha256)
        if (digest(anchor)!=self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited")!=anchor.get("inherited") or not anchor.get("creative_source_root")):
            raise ValueError("settled660 diagnostic accounting and original creative source required")
        creative_root(anchor)
        return anchor,checked

    def _workflow(self,anchor=None):return ReviewWorkflow(base.workflow,self._reviews(read(self.root/"USER_SCOPE.json")))

    def preview(self):
        anchor,checked=self._parent();built=self._inputs();self._profile_gate();original_root=creative_root(anchor)
        original=read(original_root/"INPUTS.json");cfg=read(original_root/"SESSION_CONFIG.json")
        if built["inputs"]!=original or self.profile!=read(cfg["profile_path"]):raise ValueError("exact original creative INPUTS/profile required")
        if any(k in original for k in ("previous_complete_document","revision_diagnostics")):raise ValueError("first creative authority must be clean")
        seed=material(anchor);wf=ReviewWorkflow(base.workflow,None)
        first=wf.prepare_script_request(original,self.profile,seed["goal"],seed["audit_bundle"],opening_setup=seed["setup"],**wf.origin_ids(original))
        files=base._hashes([*built["source_files"],self.config.parent_anchor_path,self.config.profile_path,self.config.preferences_path,
            self.config.user_goals_path,*self.config.extra_source_files,*self.code_files()])
        for path,item in checked.get("source_files",{}).items():
            expected=item.get("sha256") if type(item) is dict else item
            if sha(base._inside(path))!=expected:raise ValueError("certified original parent changed")
            files[str(base._inside(path))]=expected
        value={"schema":VERSION+"/preview","root":str(self.root),"grant_id":self.config.grant_id,"inputs":original,
            "input_evidence":built["evidence"],"first_request":first,"inputs_sha256":digest(original),
            "profile_sha256":sha(self.config.profile_path),"parent_anchor_sha256":digest(anchor),"inherited":checked["inherited"],
            "parent_root":anchor["root"],"parent_identity":anchor["parent_identity"],"creative_source_root":str(original_root),
            "source_files":files,"stage_limits":deepcopy(LIMITS),"total_new_calls_limit":6,
            "first_request_label":"complete_script_07","body_versions_available":BODY_VERSIONS,
            "clean_first_writer_context":True,"old_complete_body_calls_used":6,"diagnostic_calls_previously_used":4,
            "provider_calls":0,"media_calls":0,"old_budget_reset":False}
        value["preparation_identity_sha256"]=digest({k:value[k] for k in (
            "root","grant_id","inputs_sha256","profile_sha256","parent_anchor_sha256","inherited","source_files","first_request")})
        return value

    def authorization_template(self,preview):
        result=super().authorization_template(preview)
        result.update(schema=VERSION+"/derived_authorization",stage_limits=deepcopy(LIMITS),total_new_calls_limit=6,
            body_versions_available=BODY_VERSIONS,whole_plan_limit=0,opening_setup_limit=0,content_revision_limit=1,
            old_complete_body_calls_used=6,old_complete_body_capacity=6,diagnostic_calls_previously_used=4,
            creative_source_root=preview["creative_source_root"],clean_first_writer_context=True,no_replanning=True,
            new_body_scope_is_separate=True,new_authority="user autonomous MiniMax continuation and real test; bounded two complete direct-wire bodies plus four full reviews")
        return result

    def _binding(self,parent):
        value=super()._binding(parent);value.update(schema=VERSION+"/successor_claim",old_complete_body_calls_used=6);return value

    def _guard(self):
        super()._guard();scope=read(self.root/"USER_SCOPE.json");a=read(self.config.parent_anchor_path)
        if (scope.get("schema")!=VERSION+"/derived_authorization" or scope.get("stage_limits")!=LIMITS
                or any(type(v) is not int for v in scope["stage_limits"].values())
                or scope.get("total_new_calls_limit")!=6 or type(scope.get("total_new_calls_limit")) is not int
                or scope.get("body_versions_available")!=BODY_VERSIONS or scope.get("old_complete_body_calls_used")!=6
                or scope.get("old_complete_body_capacity")!=6 or scope.get("diagnostic_calls_previously_used")!=4
                or scope.get("whole_plan_limit")!=0 or scope.get("opening_setup_limit")!=0
                or scope.get("clean_first_writer_context") is not True or scope.get("no_replanning") is not True
                or scope.get("new_body_scope_is_separate") is not True or scope.get("inherited")!=a["inherited"]
                or scope.get("parent_anchor_sha256")!=self.config.parent_anchor_sha256 or digest(a)!=self.config.parent_anchor_sha256
                or scope.get("creative_source_root")!=str(creative_root(a))):raise ValueError("frozen independent direct-wire scope differs")
        if read(self.root/"INPUTS.json")!=read(creative_root(a)/"INPUTS.json"):raise ValueError("original creative inputs changed")
        p=self.root/"RUN_CLAIM.json"
        if p.exists():
            run=read(p)
            if not(run.get("schema")==VERSION+"/run_claim" and run.get("root")==str(self.root) and type(run.get("pid")) is int and run["pid"]>0
                    and run.get("automatic_restart") is False and run.get("freeze_sha256")==sha(self.root/"PRODUCTION_FREEZE.json")):
                raise ValueError("single-use RUN differs")
        return True

    def runtime(self):
        f=read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT,self.root,list(f["files"]),f["inherited"],profile=self.profile,inherited_guard=self._guard,
            admission=self._admit,shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def _rebuild(self,label,ledger):
        seed=material(read(self.config.parent_anchor_path));owner=self;rows=ledger["calls"]
        class Replay(base.LiveDriver):
            def invoke(self,old_label,prepared,validator):
                current=_label(old_label)
                if self.position==len(rows):
                    if current!=label:raise ValueError("body/review ordering differs")
                    raise previous._NextRequest(prepared)
                row=rows[self.position];self.position+=1;p=owner.root/row["receipt"];r=read(p)
                if current!=row["label"] or sha(p)!=row["receipt_sha256"]:raise ValueError("ordered native prerequisite differs")
                native=base.NativeSession.known(r,current,require_valid=False)
                if r["request"]!=prepared["request"]:raise ValueError("original request cannot be rebuilt")
                return native,base._decision(r),row
        replay=Replay(self,None,read(self.root/"INPUTS.json"),self._workflow());replay.position=0
        try:replay._body(seed["goal"],seed["audit_bundle"],seed["setup"])
        except previous._NextRequest as found:return found.prepared
        raise ValueError("native body loop is already terminal")

    def _admit(self,label,request,ledger):
        self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"])>=6 or not re.fullmatch(r"complete_script_0[78]|full_review_(?:semantic|physical)_0[78]",label):raise ValueError("two-body scope exhausted/unregistered label")
        if request.get("stage")!=("complete_script" if label.startswith("complete_script") else "full_review"):raise ValueError("stage mapping differs")
        p=self.pending_intent
        if not p or p["label"]!=label or sha(p["path"])!=p["sha256"]:raise ValueError("trusted builder intent missing")
        i=read(p["path"])
        if(i.get("schema")!=VERSION+"/call_intent" or i["prepared"]["request"]!=request or i["request_sha256"]!=digest(request)
                or i["ledger_prefix_sha256"]!=digest(ledger["calls"]) or i["inputs_sha256"]!=digest(read(self.root/"INPUTS.json"))):raise ValueError("exact call intent differs")
        if self._rebuild(label,ledger)["request"]!=request:raise ValueError("same-source builder differs")
        base.clients.expected_wire_request(request);return True

    def state(self,rt,status,**details):
        value=super().state(rt,status,**details);value.update(schema=VERSION+"/state",flow_version=VERSION,
            new_stage_limits=deepcopy(LIMITS),body_versions_available=BODY_VERSIONS,old_complete_body_calls_used=6,
            diagnostic_calls_previously_used=4,clean_first_writer_context=True,new_body_scope_is_separate=True)
        write(self.root/"STATE.json",value);return value

    def _save_text(self,result,driver,rt):
        paths={"inputs":self.root/"INPUTS.json","profile":Path(self.config.profile_path),"goal":self.root/"goal/NATIVE_GOAL.json",
            "goal_audit_bundle":self.root/"goal/NATIVE_GOAL_AUDIT_BUNDLE.json","setup":self.root/"opening/NATIVE_OPENING_SETUP.json",
            "raw_script":self.root/"scripts/NATIVE_SCRIPT.json","compiled_script":self.root/"scripts/COMPILED_SCRIPT.json",
            "full_review_bundle":self.root/"scripts/NATIVE_FULL_REVIEW_BUNDLE.json"}
        values={"goal":result["native_goal"],"goal_audit_bundle":result["native_goal_audit"],"setup":result["native_opening_setup"],
            "raw_script":result["native_script"],"compiled_script":result["compiled_script"],"full_review_bundle":result["native_full_review_bundle"]}
        for key,value in values.items():write(paths[key],value,True)
        (self.root/"scripts/FULL_SCRIPT.md").write_text(result["rendered_script"],encoding="utf-8")
        a=read(self.config.parent_anchor_path)
        h={"schema":VERSION+"/text_handoff","status":"text_ready_for_director","source_root":str(self.root),
            "paths":{k:str(v.resolve()) for k,v in paths.items()},"artifact_file_sha256":base._hashes(paths.values()),
            "native_identity":{k:digest(v) for k,v in values.items()},"receipt_identities":[base._receipt_identity(self.root,row) for row in read(rt.ledger)["calls"]],
            "decision":result["decision"],"freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json"),"run_claim_sha256":sha(self.root/"RUN_CLAIM.json"),
            "native_reports_unchanged":True,"text_only_machine_admission":True,"human_quality_approved":False,"creative_quality_passed":False,
            "media_submitted":False,"old_budget_reset":False,"old_director_capacity":base.DIRECTOR,
            "inherited_native_receipt_references":{k:deepcopy(a[k]) for k in ("native_goal_receipt","native_goal_audit_receipts","native_opening_setup_receipt")}}
        write(self.root/"TEXT_HANDOFF.json",h,True)
        return self.state(rt,"text_ready_for_director",text_handoff_sha256=digest(h),handoff_path=str(self.root/"TEXT_HANDOFF.json"))

    def run(self):
        if not(self.root/"PRODUCTION_FREEZE.json").is_file():raise ValueError("separately prepared root required")
        base.policy.new_claim(self.root/"RUN_CLAIM.json",{"schema":VERSION+"/run_claim","root":str(self.root),"pid":base.os.getpid(),
            "started_at":self.clock(),"automatic_restart":False,"freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json")})
        rt=None
        try:
            rt=self.runtime();self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]:raise ValueError("nonempty original RUN cannot restart")
            seed=material(read(self.config.parent_anchor_path));driver=Driver(self,rt,read(self.root/"INPUTS.json"),self._workflow())
            return self._save_text(driver._body(seed["goal"],seed["audit_bundle"],seed["setup"]),driver,rt)
        except(base.Halt,base.stages.OfflineStop) as stop:return self.state(rt,stop.status.replace("halt_mock_","halt_live_"),**stop.details)
        except Exception as exc:
            write(self.root/"EXECUTION_ERROR.json",{"type":type(exc).__name__,"message":str(exc),"automatic_restart":False},True)
            return self.state(rt,"halt_execution_reconciliation",exception_type=type(exc).__name__,error=str(exc))


def verify_text_handoff(root):
    """Deep original SDK/SQL verification, including inherited creative natives."""
    s=Session.open(root);rt=s.runtime();s._guard();a,parent=s._parent();seed=material(a)
    state,h,ledger=(read(s.root/(n+".json")) for n in ("STATE","TEXT_HANDOFF","CALL_LEDGER"))
    if(state.get("status")!="text_ready_for_director" or state.get("spend_verification_pending") is not False
            or state.get("text_handoff_sha256")!=digest(h) or h.get("schema")!=VERSION+"/text_handoff"
            or h.get("freeze_sha256")!=sha(s.root/"PRODUCTION_FREEZE.json")
            or not(h.get("run_claim_sha256")==state.get("run_claim_sha256")==sha(s.root/"RUN_CLAIM.json"))):raise ValueError("original known text-ready handoff required")
    current=rt.summary()
    if current!=state["spend"] or current["new_unknown_token_reservations"]!=0:raise ValueError("settled text spend differs")
    reader=base.evidence.Reader();receipts=[base.evidence.verify_original_receipt(s.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    base.evidence._tasks(reader,s.root,ledger,receipts,s.config.grant_id)
    if h["receipt_identities"]!=[base._receipt_identity(s.root,row) for row in ledger["calls"]]:raise ValueError("receipt/intent identities differ")
    for i,(row,r) in enumerate(zip(ledger["calls"],receipts)):
        intent=read(s.root/"call_intents"/(row["label"]+".json"))
        if(intent["prepared"]["request"]!=r["request"] or intent["ledger_prefix_sha256"]!=digest(ledger["calls"][:i])
                or s._rebuild(row["label"],{**ledger,"calls":ledger["calls"][:i]})["request"]!=r["request"]):raise ValueError("original request/native sequence differs")
    if h.get("inherited_native_receipt_references")!={k:a[k] for k in ("native_goal_receipt","native_goal_audit_receipts","native_opening_setup_receipt")}:
        raise ValueError("inherited native reference differs")
    for path,expected in h["artifact_file_sha256"].items():reader.verify(base._inside(path),expected)
    files={k:read(base._inside(p)) for k,p in h["paths"].items()}
    if files["inputs"]!=read(s.root/"INPUTS.json") or files["profile"]!=s.profile:raise ValueError("handoff authority differs")
    for key,source in (("goal","goal"),("goal_audit_bundle","audit_bundle"),("setup","setup")):
        if files[key]!=seed[source]:raise ValueError("original inherited creative artifact differs")
    values={k:files[k] for k in ("goal","goal_audit_bundle","setup","raw_script","compiled_script","full_review_bundle")}
    if h["native_identity"]!={k:digest(v) for k,v in values.items()}:raise ValueError("artifact native identity differs")
    reports=[files["full_review_bundle"]["native_"+p+"_review"] for p in ("semantic","physical")]
    for native in [files["raw_script"],*reports]:
        if not any(r.get("output")==native and r.get("status")=="contract_valid" for r in receipts):raise ValueError("new body/review not an actual valid native")
    wf=s._workflow();base._require_accepted(wf.validate_goal_audit(files["goal_audit_bundle"],files["goal"],inputs=files["inputs"]),"inherited_goal")
    views=wf.compile_native_views(files["goal"],files["setup"],**wf.origin_ids(files["inputs"]))
    compiled=wf.validate_script_document(files["raw_script"],views,files["inputs"]["production_preferences"])["script"]
    if compiled!=files["compiled_script"]:raise ValueError("compiled body differs from native")
    parts={p:wf.prepare_full_review_part_request(files["inputs"],files["profile"],files["raw_script"],views,p) for p in ("semantic","physical")}
    checked=wf.full_reviews().validate_bundle(files["full_review_bundle"],compiled,views["brief"],views["plan"],parts["semantic"]["review_legal_context"],
        semantic_context_sha256=parts["semantic"]["part_context_sha256"],physical_context_sha256=parts["physical"]["part_context_sha256"],
        goal_contract=files["goal"],opening_setup=files["setup"],prior_story_scope=files["inputs"]["production_preferences"].get("prior_story_scope"))
    base._require_accepted(checked,"full")
    if checked!=h["decision"]:raise ValueError("recomputed complete decision differs")
    identity={"root":str(s.root),"terminal_state_sha256":sha(s.root/"STATE.json"),"native_ledger_sha256":sha(s.root/"CALL_LEDGER.json"),
        "production_freeze_sha256":sha(s.root/"PRODUCTION_FREEZE.json"),"end_ordinal":current["effective_calls_started"]}
    inherited={"calls_started":current["effective_calls_started"],"reported_tokens":current["effective_reported_tokens"],
        "calls_with_known_usage":current["effective_calls_with_known_usage"],"pending_ordinals":deepcopy(current["historical_pending_ordinals"]),
        "unknown_token_reservations":current["unknown_token_reservations"]}
    source_files={**read(s.root/"PRODUCTION_FREEZE.json")["files"],**{p:(v.get("sha256") if type(v) is dict else v) for p,v in parent["source_files"].items()},
        **{p:v["sha256"] for p,v in reader.files.items()},**base._hashes(s.root/(n+".json") for n in ("STATE","TEXT_HANDOFF","CALL_LEDGER","PRODUCTION_FREEZE","RUN_CLAIM"))}
    return {"schema":VERSION+"/verified_text_handoff","valid":True,"accepted":True,"status":"text_ready_for_director","root":str(s.root),"source_root":str(s.root),
        "handoff_path":str(s.root/"TEXT_HANDOFF.json"),"handoff_sha256":sha(s.root/"TEXT_HANDOFF.json"),"paths":deepcopy(h["paths"]),
        "identity":{"native_goal_sha256":digest(files["goal"]),"native_script_sha256":digest(files["raw_script"]),"compiled_script_sha256":digest(compiled),
            "native_setup_sha256":digest(files["setup"]),"goal_audit_bundle_sha256":digest(files["goal_audit_bundle"]),"full_review_bundle_sha256":digest(files["full_review_bundle"])},
        "receipt_identities":deepcopy(h["receipt_identities"]),"spend":current,"inherited":inherited,"parent_identity":identity,"parent_identity_sha256":digest(identity),
        "source_files":source_files,"human_quality_approved":False,"creative_quality_passed":False,"old_director_capacity":base.DIRECTOR,
        "authorizes_media_dispatch":False,"model_calls":0}


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("preview","authorization","prepare","run","verify"));p.add_argument("path")
    args=p.parse_args()
    if args.action=="verify":value=verify_text_handoff(args.path)
    else:
        s=Session.open(args.path) if args.action=="run" else Session(read(args.path))
        value=s.authorization_template(s.preview()) if args.action=="authorization" else getattr(s,args.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
