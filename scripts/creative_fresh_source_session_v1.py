"""Parameterized, source-bound text session. No historical ROOT is a flow input."""
from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_probe_spend_anchor_v1 as spend
from scripts import creative_m31_flash_role_clients_v1 as ordinary
from scripts import creative_deepseek_strict_role_clients_v5 as strict
from scripts import creative_goal_context_dispatch_v7 as general_runtime
from scripts import creative_goal_context_dispatch_v11 as source_runtime
from scripts import run_fresh_legal_full_flow_v1 as evidence
from scripts import run_goal_context_text_production_v27 as frozen_source_compiler
from src.content_factory import creative_fresh_source_inputs_v1 as source
from src.content_factory import creative_goal_context_workflow_v23 as workflow
from src.content_factory import creative_split_full_review_contract_v4 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as text
from src.content_factory import creative_studio_task_store_v1 as tasks
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION="creative_fresh_source_session/v1"
PROJECT=Path(__file__).resolve().parents[1]
DEFAULT_PROFILE=PROJECT/"config/creative_fresh_source_session_profile_v1.json"
LIMITS={"goal_plan":3,"goal_audit":3,"complete_script":3,"full_review":6}
read,write,digest,sha,now=io.read,io.write,io.digest,io.sha_file,io.now


def strict_source(request):
    return request.get("structured_schema",{}).get("properties",{}).get("schema",{}).get("const")==workflow.SOURCE_AUDIT_VERSION


class FreshRuntime(source_runtime.GoalContextRuntime):
    """Reuse source6's exact protocol gate while admitting one genuinely new plan."""
    def __init__(self,*args,stage_limits=None,**kwargs):
        if stage_limits is not None and stage_limits!=LIMITS:raise ValueError("exact15-call fresh session ceilings required")
        general_runtime.GoalContextRuntime.__init__(self,*args,stage_limits=deepcopy(LIMITS),**kwargs)

    def _request_gate(self,request):
        if strict_source(request):return super()._request_gate(request)
        return general_runtime.GoalContextRuntime._request_gate(self,request)

    def _policy(self):
        result=super()._policy()
        result.update(schema=VERSION+"/runtime_policy",whole_plan_limit=1,opening_setup_limit=2,
            three_native_audits_per_plan=True,total_new_calls_limit=15,new_source_bound=True)
        return result


@dataclass(frozen=True)
class SessionConfig:
    root:str
    source_dir:str
    preferences_path:str
    user_goals_path:str
    anchor_path:str
    anchor_sha256:str
    counter_root:str
    round_key:str
    grant_id:str
    authorization_path:str
    profile_path:str=str(DEFAULT_PROFILE)
    extra_source_files:tuple[str,...]=()


class Halt(Exception):
    def __init__(self,status,**details):self.status,self.details=status,details


class Session:
    def __init__(self,config,*,clock=now,input_builder=source.build_inputs,source_gate=source.verify_source_bundle,
                 anchor_verifier=spend.verify_anchor,client_factory_builder=None):
        self.config=config if isinstance(config,SessionConfig) else SessionConfig(**config)
        self.root=Path(self.config.root).resolve()
        self.root.relative_to(PROJECT)
        if not re.fullmatch(r"[0-9a-f]{64}",self.config.anchor_sha256):raise ValueError("canonical620 anchor digest required")
        if self.root==PROJECT or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}",self.config.grant_id):
            raise ValueError("independent workspace root and safe grant identity required")
        if not self.config.round_key:raise ValueError("explicit current repair round required")
        self.claim=PROJECT/"data/creative_fresh_background_claims"/self.config.grant_id/"CLAIM.json"
        self.successor=PROJECT/"data/creative_consumption_successors"/self.config.anchor_sha256/"CLAIM.json"
        self.clock,self.input_builder,self.source_gate,self.anchor_verifier=clock,input_builder,source_gate,anchor_verifier
        self.client_factory_builder=client_factory_builder or (lambda request:strict.make_client_factory(request,
            source_strict=strict_source(request),review_base_url=self.profile["source_strict"]["base_url"],
            max_wire_utf8_bytes=self.profile["source_strict"]["max_wire_utf8_bytes"]))

    @property
    def profile(self):return read(self.config.profile_path)

    @classmethod
    def open(cls,root,**dependencies):return cls(read(Path(root)/"SESSION_CONFIG.json"),**dependencies)

    def _anchor(self):
        anchor=read(self.config.anchor_path)
        verified=self.anchor_verifier(anchor,expected_anchor_sha256=self.config.anchor_sha256)
        if verified.get("verified") is not True or verified.get("inherited")!=spend.INHERITED:
            raise ValueError("verified620 consumption required;619 omission forbidden")
        return anchor,verified

    def _inputs(self):
        return self.input_builder(self.config.source_dir,self.config.preferences_path,self.config.user_goals_path,now=self.clock())

    def _profile_gate(self):
        profile=self.profile
        expected={"writer":{"provider":"minimax","model":"MiniMax-M3.1-Flash-Preview","base_url":"https://api.minimax.cn/v1",
            "parameters":{"temperature":.4,"thinking":"adaptive","reasoning_effort":"medium","max_completion_tokens":16000}},
            "director":{"provider":"deepseek","model":"deepseek-flash","base_url":"https://api.deepseek.com/v1",
            "parameters":{"temperature":.4,"thinking":"disabled","max_completion_tokens":12000}}}
        if any(profile.get(role)!=value for role,value in expected.items()) or profile.get("stage_parameters")!={"goal_audit":{"max_completion_tokens":16000},"full_review":{"max_completion_tokens":32000}}:
            raise ValueError("confirmed unchanged writer/reviewer models and parameters required")
        return profile

    def preview(self):
        """No root, claim, runtime client or counter mutation."""
        anchor,verified=self._anchor();built=self._inputs();profile=self._profile_gate()
        prepared=workflow.prepare_goal_request(built["inputs"],profile)
        payload=json.loads(prepared["request"]["messages"][1]["content"])
        expected_law=workflow.contexts.build_stage_context("goal_plan",built["inputs"])["payload"]["verified_legal_context"]
        if (payload.get("reference_fulltext")!=built["inputs"]["reference_fulltext"]
                or payload.get("verified_legal_context")!=expected_law
                or any(key in payload for key in ("previous_complete_document","revision_diagnostics"))):
            raise ValueError("fresh complete R01/law and no old native revision template required")
        return {"schema":VERSION+"/preview","inputs":built["inputs"],"evidence":built["evidence"],
            "source_files":built["source_files"],"first_request":prepared,"inputs_sha256":digest(built["inputs"]),
            "profile_sha256":sha(self.config.profile_path),"anchor_sha256":digest(anchor),
            "inherited":verified["inherited"],"stage_limits":LIMITS,"whole_plan_limit":1,"setup_limit":2,
            "provider_calls":0,"media_calls":0,"creative_quality_passed":False}

    def authorization_template(self,preview):
        return {"schema":VERSION+"/derived_authorization","grant_id":self.config.grant_id,
            "root":str(self.root),
            "continuing_text_authority":"minimax随便追加; DeepSeek少量必要全文审查",
            "source_dir":str(Path(self.config.source_dir).resolve()),"inputs_sha256":preview["inputs_sha256"],
            "first_request_sha256":preview["first_request"]["request_sha256"],"profile_sha256":preview["profile_sha256"],
            "anchor_sha256":self.config.anchor_sha256,"inherited":preview["inherited"],
            "counter_root":str(Path(self.config.counter_root).resolve()),"round_key":self.config.round_key,
            "stage_limits":LIMITS,"whole_plan_limit":1,"setup_limit":2,"content_revision_limit":2,
            "old_director_capacity":{"used":7,"limit":7,"remaining":0},"media_authorized":False,
            "publish_authorized":False,"automatic_retry":False,"old_budget_reset":False}

    def prepare(self):
        if self.root.exists() or self.claim.exists():raise FileExistsError("existing independent root/claim cannot be regranted")
        if self.successor.exists():raise FileExistsError("620 anchor already has a successor; a new root/grant cannot reclaim its spend")
        preview=self.preview()
        authorization=read(self.config.authorization_path)
        if authorization!=self.authorization_template(preview):raise ValueError("actual preview/source/620/counter authorization mismatch")
        # Pin actual loaded local execution modules, not ancestor data trees.
        closure=[]
        for module in tuple(sys.modules.values()):
            path=getattr(module,"__file__",None)
            if path:
                target=Path(path).resolve()
                if target.suffix==".py" and any(target.is_relative_to(PROJECT/name) for name in ("scripts","src")):closure.append(target)
        code_files=[*closure,Path(__file__),PROJECT/"scripts/run_fresh_source_session_v1.py",Path(source.__file__),Path(spend.__file__),
            Path(self.config.profile_path),Path(self.config.anchor_path),Path(self.config.authorization_path),
            Path(self.config.counter_root)/"AUTHORIZATION_AND_CADENCE_v1.json",Path(self.config.counter_root)/"USER_COUNT_UNIT_CONFIRMATION_v1.json"]
        files={str(Path(path).resolve()):sha(path) for path in [*preview["source_files"],*code_files,*self.config.extra_source_files]}
        # Atomic, canonical-anchor-scoped single successor. If preparation later
        # fails, preserve this reservation for reconciliation, never regrant it.
        write(self.successor,{"schema":VERSION+"/successor_claim","anchor_sha256":self.config.anchor_sha256,
            "root":str(self.root),"grant_id":self.config.grant_id,"authorization_sha256":sha(self.config.authorization_path),
            "only_one_successor_of620_supported":True,"old_budget_reset":False},True)
        write(self.claim,{"schema":VERSION+"/claim","root":str(self.root),"grant_id":self.config.grant_id,
            "authorization_sha256":sha(self.config.authorization_path),"old_budget_reset":False},True)
        self.root.mkdir(parents=True)
        files[str(self.successor)]=sha(self.successor)
        for name,value in (("SESSION_CONFIG",asdict(self.config)),("INPUTS",preview["inputs"]),("INPUT_EVIDENCE",preview["evidence"]),
            ("FIRST_REQUEST_PREVIEW",preview["first_request"]),("USER_SCOPE",authorization)):
            write(self.root/(name+".json"),value,True)
        for name in ("SESSION_CONFIG","INPUTS","INPUT_EVIDENCE","FIRST_REQUEST_PREVIEW","USER_SCOPE"):
            path=self.root/(name+".json");files[str(path)]=sha(path)
        write(self.root/"PRODUCTION_FREEZE.json",{"schema":VERSION+"/freeze","files":files,
            "claim_sha256":sha(self.claim),"inherited":preview["inherited"],"inputs_sha256":preview["inputs_sha256"]},True)
        runtime=self.runtime();runtime.prepare()
        return self.state(runtime,"prepared")

    def _guard(self):
        freeze=read(self.root/"PRODUCTION_FREEZE.json")
        if sha(self.claim)!=freeze["claim_sha256"] or read(self.claim).get("root")!=str(self.root):raise ValueError("session claim changed")
        continuation=read(self.successor)
        if (continuation.get("anchor_sha256")!=self.config.anchor_sha256 or continuation.get("root")!=str(self.root)
                or continuation.get("grant_id")!=self.config.grant_id):raise ValueError("620 successor consumption binding changed")
        for path,expected in freeze["files"].items():
            if sha(path)!=expected:raise ValueError("frozen session source changed: "+path)
        _,verified=self._anchor()
        if verified["inherited"]!=freeze["inherited"]:raise ValueError("inherited620 consumption changed")
        self.source_gate(self.config.source_dir,now=self.clock())
        if digest(self._inputs()["inputs"])!=freeze["inputs_sha256"]:raise ValueError("current input projection/source identity changed")

    def _admit(self,label,request,ledger):
        # Called by dispatch *inside* its lock immediately before its budget claim.
        self._guard()
        CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"])>=15:raise ValueError("fresh session total15 exhausted")
        if not re.fullmatch(r"whole_plan_01|(?:source|commitment|drama)_audit_01|opening_setup_0[12]|complete_script_0[123]|full_review_(?:semantic|physical)_0[123]",label):
            raise ValueError("exact native stage identity required")
        if any(row["label"]==label for row in ledger["calls"]):raise ValueError("stage identity already consumed")
        properties=request.get("structured_schema",{}).get("properties",{})
        version=properties.get("schema",properties.get("contract_version",{})).get("const")
        if label=="whole_plan_01":expected=("goal_plan","creative_goal_source_v4")
        elif label.startswith("opening_setup_"):expected=("goal_plan",workflow.OPENING_SETUP_VERSION)
        elif label=="source_audit_01":expected=("goal_audit",workflow.SOURCE_AUDIT_VERSION)
        elif label=="commitment_audit_01":expected=("goal_audit",workflow.commitment_audit.VERSION)
        elif label=="drama_audit_01":expected=("goal_audit",workflow.DRAMA_AUDIT_VERSION)
        elif label.startswith("full_review_"):
            expected=("full_review",reviews.VERSION)
            if properties.get("part",{}).get("const")!=label.split("_")[2]:raise ValueError("same-body review part identity changed")
        else:expected=("complete_script",version)
        if (request.get("stage"),version)!=expected:raise ValueError("native stage label and request contract differ")
        return True

    def runtime(self):
        freeze=read(self.root/"PRODUCTION_FREEZE.json")
        return FreshRuntime(PROJECT,self.root,[Path(path) for path in freeze["files"]],freeze["inherited"],
            profile=self.profile,stage_limits=LIMITS,inherited_guard=self._guard,admission=self._admit,
            shared_lock=PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def invoke(self,runtime,label,prepared,validator):
        request=prepared["request"];wire=strict.expected_wire_request(request,source_strict=strict_source(request))
        for row in read(runtime.ledger)["calls"]:
            if runtime.effective_receipt(row)["request_sha256"]==digest(request):return runtime.dispatch(label,request,validator)
        self._guard();CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        write(self.root/"requests"/(label+".json"),prepared,True)
        store=tasks.TaskStore(self.root/"TASKS.sqlite3");gid="call_"+digest([self.config.grant_id,label])[:24]
        store.register_graph({"schema_version":tasks.GRAPH_SCHEMA,"graph_id":gid,"nodes":[
            {"node_id":"source","kind":"source","input":{"source_manifest":digest(read(runtime.ledger)["source_manifest"]),"request_sha256":digest(request)},"depends_on":[]},
            {"node_id":"result","kind":"text","input":{"label":label,"stage":request["stage"]},"depends_on":["source"]}]})
        scope=self.root/"USER_SCOPE.json"
        attempt=store.claim(gid,"result",{"provider_id":request["model"],"payload":request},{"schema_version":tasks.AUTH_SCHEMA,
            "authorization_id":gid+":scope","graph_id":gid,"node_ids":["result"],"scope":"text","purpose":"dispatch",
            "source_sha256":store.snapshot(gid)["source_sha256"],"max_attempts":LIMITS[request["stage"]],"prior_attempts":0,
            "allows_content_revision":False,"evidence_ref":str(scope)+"#"+request["stage"],"evidence_sha256":sha(scope)})
        receipt=runtime.dispatch(label,request,validator)
        directory=evidence.verify_receipt_evidence(runtime,receipt,request)
        if (directory/"request_body.raw").exists() and io.strict_json((directory/"request_body.raw").read_text(encoding="utf-8"))!=wire:
            raise ValueError("actual SDK wire differs from prepared source/model mapping")
        raw=(directory/"response_body.raw").read_bytes() if (directory/"response_body.raw").exists() else b""
        known,outcome,tool=self.classify_native(receipt);meta=receipt.get("response_metadata",{});total=meta.get("total_tokens")
        store.accept_result(attempt["claim_id"],{"schema_version":tasks.RESULT_SCHEMA,"claim_id":attempt["claim_id"],
            "request_sha256":attempt["request_sha256"],"service_task_id":None,"outcome":outcome,"result_known":known,
            "usage_known":type(total)is int and total>=0,"usage":{"unit":"reported_tokens","amount":total} if type(total)is int and total>=0 else None,
            "complete":meta.get("response_body_complete") is True,"complete_end":meta.get("finish_reason") in ("stop","tool_calls"),
            "schema_tool_status":tool,"contract_valid":receipt["status"]=="contract_valid" if known else None,
            "raw_receipt":{"encoding":"base64","body":base64.b64encode(raw).decode(),"sha256":hashlib.sha256(raw).hexdigest(),"http_status":meta.get("http_status_code")},
            "output":{"ordinal":receipt["ordinal"],"native_output":receipt.get("output")}})
        return receipt

    @staticmethod
    def classify_native(receipt):
        known,outcome,tool=evidence.classify_receipt(receipt)
        failure=receipt.get("failure",{});meta=receipt.get("response_metadata",{})
        if (known and receipt.get("status")=="contract_rejected" and failure.get("response_received") is True
                and failure.get("category") in ("validation","state_contract","compilation")
                and not meta.get("response_fault_code") and meta.get("output_mode")=="tool_call"
                and type(receipt.get("output")) is dict and receipt["output"]):
            return True,"content_rejected","accepted"
        return known,outcome,tool

    @staticmethod
    def known(receipt,stage,*,require_valid=True):
        meta=receipt.get("response_metadata",{})
        known,outcome,tool=Session.classify_native(receipt)
        if receipt.get("cached_response_read_only"):raise Halt("halt_cached_stage_no_new_progress",receipt_ordinal=receipt["ordinal"],stage=stage)
        if not (known and meta.get("output_mode")=="tool_call"
                and meta.get("requested_model")==meta.get("response_model")==receipt["request"]["model"]
                and type(receipt.get("output")) is dict and receipt["output"]):
            raise Halt("halt_interface_or_unknown",receipt_ordinal=receipt["ordinal"],stage=stage)
        if outcome=="protocol_rejected" or tool!="accepted":raise Halt("halt_protocol_requires_diagnosis",receipt_ordinal=receipt["ordinal"],stage=stage)
        if require_valid and receipt["status"]!="contract_valid":raise Halt("halt_contract_requires_pipeline_diagnosis",receipt_ordinal=receipt["ordinal"],stage=stage)
        return receipt["output"]

    def state(self,runtime,status,**details):
        try:
            if runtime is None:raise ValueError("runtime not constructed; current spend not verified")
            current_spend=runtime.summary();pending=False;spend_error=None
        except Exception as exc:
            current_spend=None;pending=True;spend_error={"type":type(exc).__name__,"message":str(exc)}
        value={"schema":VERSION+"/state","status":status,"updated_at":self.clock(),"spend":current_spend,
            "spend_verification_pending":pending,
            "text_ready_for_director":False,"human_quality_approved":False,"creative_quality_passed":False,
            "media_authorized":False,"old_director_capacity":{"used":7,"limit":7,"remaining":0},**details}
        if pending:
            value["spend_error"]=spend_error
            if (self.root/"STATE.json").exists():
                previous=read(self.root/"STATE.json")
                value["last_saved_spend_checkpoint"]={"updated_at":previous.get("updated_at"),"spend":previous.get("spend"),"not_current_verified_spend":True}
        write(self.root/"STATE.json",value);return value

    def run(self):
        if (self.root/"RUN_CLAIM.json").exists():raise FileExistsError("original run claim exists; no automatic restart")
        write(self.root/"RUN_CLAIM.json",{"schema":VERSION+"/run_claim","pid":os.getpid(),"started_at":self.clock(),"automatic_restart":False},True)
        runtime=None
        try:
            runtime=self.runtime();runtime.inherited_guard()
            CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(runtime.ledger)["calls"]:raise ValueError("nonempty claimed ledger cannot restart")
            return self._flow(runtime,read(self.root/"INPUTS.json"))
        except Halt as halt:return self.state(runtime,halt.status,**halt.details)
        except Exception as exc:
            write(self.root/"EXECUTION_ERROR.json",{"status":"stopped_original_request_requires_reconciliation","error_type":type(exc).__name__,"error":str(exc),"automatic_restart":False},True)
            self.state(runtime,"halt_execution_exception_requires_reconciliation",error_type=type(exc).__name__,error=str(exc))
            raise

    def _flow(self,runtime,inputs):
        prepared=workflow.prepare_goal_request(inputs,self.profile)
        if prepared!=read(self.root/"FIRST_REQUEST_PREVIEW.json"):raise ValueError("first actual request differs from frozen preview")
        planned=self.invoke(runtime,"whole_plan_01",prepared,lambda value:workflow.validate_goal_document(value,inputs=inputs))
        goal=self.known(planned,"whole_plan");write(self.root/"goal/NATIVE_GOAL.json",goal,True)
        audits={}
        for kind in ("source","commitment","drama"):
            prepared=frozen_source_compiler.prepare_source_audit(inputs,self.profile,goal) if kind=="source" else getattr(workflow,f"prepare_goal_{kind}_audit_request")(inputs,self.profile,goal)
            args={"context_sha256":prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]}
            if kind=="source":args["authority_context"]=prepared["source_authority_context"]
            validate=getattr(workflow,f"validate_goal_{kind}_audit")
            receipt=self.invoke(runtime,kind+"_audit_01",prepared,lambda value,v=validate,a=args:v(value,goal,**a))
            native=self.known(receipt,kind);decision=receipt["validation"]
            write(self.root/"goal"/(kind+"_native.json"),native,True);write(self.root/"goal"/(kind+"_decision.json"),decision,True)
            if not decision["accepted"] or decision["uncertainties"]:raise Halt("halt_goal_content_requires_pipeline_diagnosis",audit_kind=kind,receipt_ordinal=receipt["ordinal"],decision=decision)
            audits[kind]=native
        bundle=workflow.build_goal_audit_bundle(audits["source"],audits["drama"],audits["commitment"])
        setup=self._setup(runtime,inputs,goal)
        return self._body(runtime,inputs,goal,bundle,setup,planned["ordinal"])

    def _setup(self,runtime,inputs,goal):
        current=deepcopy(inputs)
        for index in (1,2):
            prepared=workflow.prepare_opening_setup_request(current,self.profile,goal)
            receipt=self.invoke(runtime,f"opening_setup_{index:02}",prepared,lambda value:{"valid":True,
                "native_setup_sha256":digest(workflow.validate_opening_setup_document(value,goal)),"state_fields_inferred":False})
            native=self.known(receipt,"opening_setup",require_valid=False)
            write(self.root/"setup"/f"NATIVE_{index:02}.json",native,True)
            if receipt["status"]=="contract_valid":return native
            current={**deepcopy(inputs),"previous_opening_setup":native,"opening_setup_diagnostics":self._diagnosis(receipt)}
        raise Halt("halt_opening_setup_capacity_exhausted")

    @staticmethod
    def _diagnosis(receipt):return {key:deepcopy(receipt[key]) for key in ("failure","validation_error","validation") if key in receipt}

    def _body(self,runtime,inputs,goal,audit,setup,goal_ordinal):
        current=deepcopy(inputs)
        for index in (1,2,3):
            prepared=workflow.prepare_script_request(current,self.profile,goal,audit,opening_setup=setup,**workflow.origin_ids(inputs));views=prepared["views"]
            def validate(value):
                result=workflow.validate_script_document(value,views,inputs["production_preferences"])
                if not result["necessary_conditions_only"]:
                    error=ValueError("complete native revision required for necessary timing conditions");error.detail=result["diagnostic"];raise error
                return result
            receipt=self.invoke(runtime,f"complete_script_{index:02}",prepared,validate)
            native=self.known(receipt,"complete_script",require_valid=False)
            folder=self.root/"scripts"/f"version_{index:02}"
            write(folder/"NATIVE_SCRIPT.json",native,True)
            try:
                compiled=text.contract.compile_script(native,views["brief"])
                with (folder/"FULL_SCRIPT.md").open("x",encoding="utf-8") as output:output.write("完整模型原生正文；结论见同目录DECISION和本次STATE，未获用户采用。\n\n"+text.render_script(compiled,views["brief"]))
            except (ValueError,KeyError,TypeError):compiled=None
            if receipt["status"]!="contract_valid":
                current={**deepcopy(inputs),"previous_complete_document":native,"revision_diagnostics":self._diagnosis(receipt)};continue
            documents,decisions,contexts,ordinals={}, {}, {}, {};legal=None;failed=None
            for part in ("semantic","physical"):
                review=workflow.prepare_full_review_part_request(inputs,self.profile,native,views,part)
                if legal is not None and legal!=review["review_legal_context"]:raise ValueError("full-review legal authority changed between same-source parts")
                legal=review["review_legal_context"];context=review["part_context_sha256"]
                reviewed=self.invoke(runtime,f"full_review_{part}_{index:02}",review,lambda value,p=part,c=context:reviews.validate_part(value,p,compiled,views["brief"],views["plan"],legal,context_sha256=c,goal_contract=goal,opening_setup=setup))
                documents[part]=self.known(reviewed,"full_review_"+part);decision=reviewed["validation"]
                write(folder/("NATIVE_"+part.upper()+"_REVIEW.json"),documents[part],True);write(folder/(part.upper()+"_DECISION.json"),decision,True)
                self._review_stop(decision,folder,part,reviewed["ordinal"])
                decisions[part],contexts[part],ordinals[part]=decision,context,reviewed["ordinal"]
                if not decision["accepted"]:failed=decision;break
            if failed is not None:
                current={**deepcopy(inputs),"previous_complete_document":native,"revision_diagnostics":{"complete_same_source_part_review":failed,"native_part_reviews":documents,"native_review_ordinals":ordinals}};continue
            bundle=reviews.build_review_bundle(documents["semantic"],documents["physical"])
            decision=reviews.validate_bundle(bundle,compiled,views["brief"],views["plan"],legal,semantic_context_sha256=contexts["semantic"],physical_context_sha256=contexts["physical"],goal_contract=goal,opening_setup=setup)
            write(folder/"NATIVE_REVIEW_BUNDLE.json",bundle,True);write(folder/"DECISION.json",decision,True)
            self._review_stop(decision,folder,"bundle",ordinals)
            if decision.get("valid") is not True:raise Halt("halt_full_review_bundle_contract_requires_pipeline_diagnosis",script_path=str(folder/"FULL_SCRIPT.md"))
            if decision["accepted"]:
                write(self.root/"TEXT_HANDOFF.json",{"schema":VERSION+"/text_handoff","native_goal":goal,"native_goal_audit":audit,
                    "native_opening_setup":setup,"native_script":native,"views":views,"native_full_review_bundle":bundle,"decision":decision,
                    "script_path":str(folder/"FULL_SCRIPT.md"),"script_ordinal":receipt["ordinal"],"review_ordinals":ordinals,
                    "production_dispatch_eligible":False,"next_stage_requires_reconciled_director_lineage":True,"media_authorized":False},True)
                return self.state(runtime,"text_ready_for_director",text_ready_for_director=True,script_path=str(folder/"FULL_SCRIPT.md"),native_goal_ordinal=goal_ordinal,script_ordinal=receipt["ordinal"],review_ordinals=ordinals,decision=decision)
            current={**deepcopy(inputs),"previous_complete_document":native,"revision_diagnostics":{"complete_same_source_full_review_bundle":decision,"native_review_bundle":bundle,"native_review_ordinals":ordinals}}
        raise Halt("halt_complete_script_capacity_exhausted")

    @staticmethod
    def _review_stop(decision,folder,part,ordinal):
        details={"script_path":str(folder/"FULL_SCRIPT.md"),"review_part":part,"receipt_ordinal":ordinal,"decision":decision}
        if decision.get("status") in ("halt_same_story_prior_allowance_exhausted","halt_prior_story_relation_unknown"):raise Halt(decision["status"],**details)
        if decision.get("uncertainties"):raise Halt("halt_full_review_uncertain",**details)
        if decision.get("requires_new_goal_plan") or any(row.get("target")=="plan" for row in decision.get("findings",[])):
            raise Halt("halt_full_review_requires_new_complete_goal",**details)
