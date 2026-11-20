"""Four preregistered small interface comparisons, never a screenplay pipeline."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import importlib
import json
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v1 as base

VERSION = "creative_world_scene_array_probe_session/v1"
CASE_IDS = ["compound_clean", "direct_clean", "compound_bad_previous", "direct_bad_previous"]
LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 4, "full_review": 0}
TOTAL = 4
read, write, digest, sha = base.read, base.write, base.digest, base.sha


@dataclass(frozen=True)
class Config:
    root: str
    grant_id: str
    parent_anchor_path: str
    parent_anchor_sha256: str
    profile_path: str
    authorization_path: str
    counter_root: str
    round_key: str
    extra_source_files: tuple = ()


class Runtime(base.Runtime):
    """Explicit diagnostic four-call override; no creative stage is regranted."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, stage_limits=base.LIMITS, **kwargs)
        self.stage_limits = deepcopy(LIMITS)

    def _policy(self):
        value = super()._policy()
        value.update(schema=VERSION+"/runtime_policy", diagnostic_only=True,
            explicit_diagnostic_complete_script_capacity=4, total_new_calls_limit=4,
            whole_plan_limit=0, opening_setup_limit=0, full_review_parts_per_complete_script=0,
            ordered_case_ids=CASE_IDS, creative_body_capacity_regranted=False)
        return value


def known_native(receipt):
    """Known complete tool object, including a schema-invalid empty object."""
    meta=receipt.get("response_metadata",{})
    known, outcome, tool=base.NativeSession.classify_native(receipt)
    if not known:
        raise base.Halt("halt_interface_or_unknown",receipt_ordinal=receipt["ordinal"])
    if outcome=="protocol_rejected" or tool!="accepted":
        raise base.Halt("halt_protocol_requires_diagnosis",receipt_ordinal=receipt["ordinal"])
    if not (outcome in ("completed","content_rejected") and meta.get("output_mode")=="tool_call"
            and meta.get("requested_model")==meta.get("response_model")==receipt["request"]["model"]
            and type(receipt.get("output")) is dict and not receipt.get("cached_response_read_only")):
        raise base.Halt("halt_protocol_requires_diagnosis",receipt_ordinal=receipt["ordinal"])
    choices=receipt.get("response_payload",{}).get("choices",[])
    if type(choices) is not list or len(choices)!=1:
        raise base.Halt("halt_protocol_requires_diagnosis",receipt_ordinal=receipt["ordinal"])
    calls=choices[0].get("message",{}).get("tool_calls",[])
    if len(calls)!=1 or calls[0].get("function",{}).get("name")!=base.clients.TOOL_NAME:
        raise base.Halt("halt_protocol_requires_diagnosis",receipt_ordinal=receipt["ordinal"])
    if base.io.strict_json(calls[0]["function"]["arguments"])!=receipt["output"]:
        raise ValueError("original native arguments differ from recorded output")
    return deepcopy(receipt["output"])


class Session(base.Session):
    def __init__(self, config, *, parent_verifier=None, cases_module=None, client_factory_builder=None, clock=base.now):
        self.config=config if isinstance(config,Config) else Config(**config)
        self.root=base._inside(self.config.root)
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}",self.config.grant_id):raise ValueError("safe explicit grant required")
        if not re.fullmatch(r"[a-f0-9]{64}",self.config.parent_anchor_sha256) or not self.config.round_key:raise ValueError("parent and current round required")
        self.parent_verifier=parent_verifier
        self.cases_module=cases_module or importlib.import_module("scripts.creative_world_scene_array_probe_cases_v1")
        self.client_factory_builder=client_factory_builder or base.clients.make_client_factory
        self.clock=clock;self.pending_intent=None
        self.claim=base.PROJECT/"data/creative_fresh_background_claims"/self.config.grant_id/"CLAIM.json"

    def _parent(self):
        anchor=read(self.config.parent_anchor_path)
        verifier=self.parent_verifier or importlib.import_module("scripts.creative_world_scene_spend_anchor_v4").verify_anchor
        checked=verifier(anchor,expected_anchor_sha256=self.config.parent_anchor_sha256)
        if (digest(anchor)!=self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited")!=anchor.get("inherited") or checked.get("body_capacity_exhausted") is not True
                or anchor.get("cumulative_body_attempts_used")!=6 or anchor.get("remaining_complete_scripts")!=0):
            raise ValueError("settled656 original six spent bodies required; no body regrant")
        return anchor,checked

    def _cases(self):
        cases=self.cases_module.build_cases(self.profile)
        if type(cases) is not list or [row.get("id") for row in cases]!=CASE_IDS:raise ValueError("four exact preregistered cases required")
        for case in cases:
            request=case["request"]
            if request.get("stage")!="complete_script" or request.get("role")!="writer" or case.get("diagnostic_only") is not True:
                raise ValueError("only small writer interface diagnostics are allowed")
            if case["expected_output_schema"]!=request["structured_schema"]:raise ValueError("original diagnostic schema differs")
            base.clients.expected_wire_request(request)
        return cases

    def code_files(self):
        files={Path(__file__).resolve(),Path(self.cases_module.__file__).resolve()}
        for module in tuple(base.sys.modules.values()):
            raw=getattr(module,"__file__",None)
            if raw:
                path=Path(raw).resolve()
                if path.suffix==".py" and any(path.is_relative_to(base.PROJECT/d) for d in ("src","scripts")):files.add(path)
        return sorted(files)

    def preview(self):
        parent,checked=self._parent();self._profile_gate();cases=self._cases()
        files=base._hashes([self.config.parent_anchor_path,self.config.profile_path,*self.config.extra_source_files,*self.code_files()])
        for path,item in checked.get("source_files",{}).items():
            expected=item.get("sha256") if type(item) is dict else item
            if sha(base._inside(path))!=expected:raise ValueError("certified original parent changed")
            files[str(base._inside(path))]=expected
        inputs={"schema":VERSION+"/case_frame","diagnostic_only":True,"cases":cases}
        value={"schema":VERSION+"/preview","root":str(self.root),"grant_id":self.config.grant_id,
            "inputs":inputs,"inputs_sha256":digest(inputs),"input_evidence":{"diagnostic_only":True,"no_fresh_story_source_claimed":True},
            "first_request":cases[0],"cases":cases,"profile_sha256":sha(self.config.profile_path),
            "parent_anchor_sha256":digest(parent),"parent_root":parent["root"],"parent_identity":parent["parent_identity"],
            "inherited":checked["inherited"],"source_files":files,"stage_limits":deepcopy(LIMITS),
            "total_new_calls_limit":4,"provider_calls":0,"media_calls":0,"old_budget_reset":False}
        value["preparation_identity_sha256"]=digest({k:value[k] for k in (
            "root","grant_id","inputs_sha256","profile_sha256","parent_anchor_sha256","inherited","source_files","cases")})
        return value

    def authorization_template(self, preview):
        return {"schema":VERSION+"/derived_authorization","root":str(self.root),"grant_id":self.config.grant_id,
            "preparation_identity_sha256":preview["preparation_identity_sha256"],"inputs_sha256":preview["inputs_sha256"],
            "parent_anchor_sha256":self.config.parent_anchor_sha256,"inherited":preview["inherited"],
            "stage_limits":deepcopy(LIMITS),"total_new_calls_limit":4,"ordered_case_ids":CASE_IDS,
            "case_request_sha256":{c["id"]:digest(c["request"]) for c in preview["cases"]},
            "counter_root":str(Path(self.config.counter_root).resolve()),"round_key":self.config.round_key,
            "old_director_capacity":base.DIRECTOR,"old_complete_body_calls_used":6,"old_complete_body_capacity":6,
            "creative_body_capacity_regranted":False,"diagnostic_only":True,"independent_preregistered_comparisons":True,
            "automatic_retry":False,"old_budget_reset":False,"media_authorized":False,"publish_authorized":False,
            "new_authority":"user MiniMax autonomous additions and real-interface test; root preregistered bounded four small comparisons"}

    def _binding(self,parent):
        value=super()._binding(parent);value.update(schema=VERSION+"/successor_claim",diagnostic_only=True);return value

    def _guard(self):
        freeze=read(self.root/"PRODUCTION_FREEZE.json")
        if freeze.get("schema")!=base.VERSION+"/freeze" or freeze.get("stage_limits")!=base.LIMITS:raise ValueError("original shared freeze differs")
        if digest(asdict(self.config))!=digest(read(self.root/"SESSION_CONFIG.json")):raise ValueError("frozen config differs")
        for path,expected in freeze["files"].items():
            if sha(base._inside(path))!=expected:raise ValueError("frozen dependency changed: "+path)
        if sha(self.claim)!=freeze["claim_sha256"]:raise ValueError("grant claim changed")
        for path in freeze["successor_claim_paths"]:
            if read(path)!=freeze["binding"]:raise ValueError("original unique parent successor differs")
        scope=read(self.root/"USER_SCOPE.json");cases=self._cases();inputs=read(self.root/"INPUTS.json")
        if (inputs!={"schema":VERSION+"/case_frame","diagnostic_only":True,"cases":cases}
                or scope.get("schema")!=VERSION+"/derived_authorization" or scope.get("stage_limits")!=LIMITS
                or any(type(v) is not int for v in scope["stage_limits"].values())
                or scope.get("total_new_calls_limit")!=4 or type(scope.get("total_new_calls_limit")) is not int
                or scope.get("ordered_case_ids")!=CASE_IDS or scope.get("diagnostic_only") is not True
                or scope.get("creative_body_capacity_regranted") is not False
                or scope.get("old_complete_body_calls_used")!=6 or scope.get("old_complete_body_capacity")!=6
                or scope.get("case_request_sha256")!={c["id"]:digest(c["request"]) for c in cases}
                or scope.get("parent_anchor_sha256")!=self.config.parent_anchor_sha256):raise ValueError("exact four-case diagnostic scope differs")
        run=self.root/"RUN_CLAIM.json"
        if run.exists():
            c=read(run)
            if not(c.get("schema")==VERSION+"/run_claim" and c.get("root")==str(self.root) and type(c.get("pid")) is int and c["pid"]>0
                    and c.get("automatic_restart") is False and c.get("freeze_sha256")==sha(self.root/"PRODUCTION_FREEZE.json")):
                raise ValueError("single-use original RUN differs")
        return True

    def runtime(self):
        f=read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT,self.root,list(f["files"]),f["inherited"],profile=self.profile,
            inherited_guard=self._guard,admission=self._admit,shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",
            quota_state=None,client_factory_builder=self.client_factory_builder)

    def _admit(self,label,request,ledger):
        self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        index=len(ledger["calls"])
        if index>=4:raise ValueError("four diagnostic calls exhausted")
        case=self._cases()[index]
        if label!="array_probe_"+case["id"] or request!=case["request"]:raise ValueError("ordered preregistered case request differs")
        for row in ledger["calls"]:
            path=self.root/row["receipt"]
            if sha(path)!=row["receipt_sha256"]:raise ValueError("original previous receipt changed")
            known_native(read(path))
        pending=self.pending_intent
        if not pending or pending["label"]!=label or sha(pending["path"])!=pending["sha256"]:raise ValueError("original call intent missing")
        intent=read(pending["path"])
        if intent["request"]!=request or intent["ledger_prefix_sha256"]!=digest(ledger["calls"]):raise ValueError("exact request/prerequisite prefix differs")
        return True

    def state(self,rt,status,**details):
        value=base.NativeSession.state(self,rt,status,**details)
        value.update(schema=VERSION+"/state",diagnostic_only=True,text_ready_for_director=False,creative_body_capacity_regranted=False)
        if (self.root/"RUN_CLAIM.json").exists():value["run_claim_sha256"]=sha(self.root/"RUN_CLAIM.json")
        write(self.root/"STATE.json",value);return value

    def _summary(self,rt,rows,status,details=None):
        # NativeSession.state safely records unverified spend if the failure was
        # the guard itself; never call a broken summary twice and lose terminal
        # evidence, and never substitute a previous spend checkpoint.
        state=self.state(rt,status,**(details or {}))
        value={"schema":VERSION+"/summary","status":status,"diagnostic_only":True,"ordered_case_ids":CASE_IDS,
            "completed_known_cases":rows,"complete_factorial":len(rows)==4,"stop_details":details or {},
            "spend":deepcopy(state["spend"]),"spend_verification_pending":state["spend_verification_pending"],
            "old_complete_body_calls_used":6,"old_complete_body_capacity":6,
            "does_not_estimate_general_pass_rate":True,"does_not_isolate_one_schema_keyword":True,
            "text_ready_for_director":False,"creative_quality_passed":False,"human_quality_approved":False,"media_submitted":False}
        write(self.root/"SUMMARY.json",value,True)
        state.update(summary_sha256=digest(value),complete_factorial=value["complete_factorial"])
        write(self.root/"STATE.json",state)
        return state

    def run(self):
        if not(self.root/"PRODUCTION_FREEZE.json").is_file():raise ValueError("separately prepared diagnostic root required")
        base.policy.new_claim(self.root/"RUN_CLAIM.json",{"schema":VERSION+"/run_claim","root":str(self.root),"pid":base.os.getpid(),
            "started_at":self.clock(),"automatic_restart":False,"freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json")})
        rt=None;rows=[]
        try:
            rt=self.runtime();self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]:raise ValueError("nonempty original RUN cannot restart")
            for case in self._cases():
                label="array_probe_"+case["id"];prefix=read(rt.ledger)["calls"]
                path=self.root/"call_intents"/(label+".json")
                write(path,{"schema":VERSION+"/call_intent","label":label,"request":case["request"],"case_sha256":digest(case),
                    "ledger_prefix_sha256":digest(prefix),"automatic_retry":False},True)
                self.pending_intent={"label":label,"path":str(path),"sha256":sha(path)}
                receipt=base.policy.dispatch_claimed(rt,label,case,lambda value,c=case:self.cases_module.validate(value,c),
                    root=self.root,grant_id=self.config.grant_id,stage_limits=LIMITS,current_round_root=self.config.counter_root,
                    current_round_key=self.config.round_key,guard=self._guard)
                native=known_native(receipt)
                rows.append({"id":case["id"],"representation":case["representation"],"context_variant":case["context_variant"],
                    "context_sha256":case["context_sha256"],"ordinal":receipt["ordinal"],"receipt_status":receipt["status"],
                    "receipt_path":str(self.root/f"call_{receipt['ordinal']:03}_{label}.json"),"native_sha256":digest(native),
                    "request_sha256":receipt["request_sha256"],"validation":self.cases_module.validate(native,case)})
            return self._summary(rt,rows,"diagnostic_completed_not_creative")
        except base.Halt as stop:return self._summary(rt,rows,stop.status,stop.details)
        except Exception as exc:
            write(self.root/"EXECUTION_ERROR.json",{"type":type(exc).__name__,"message":str(exc),"automatic_restart":False},True)
            return self._summary(rt,rows,"halt_execution_reconciliation",{"exception_type":type(exc).__name__,"error":str(exc)})


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("preview","authorization","prepare","run"));p.add_argument("path")
    args=p.parse_args();s=Session.open(args.path) if args.action=="run" else Session(read(args.path))
    value=s.authorization_template(s.preview()) if args.action=="authorization" else getattr(s,args.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
