"""Bounded continuation of a completed native-plan session; no frozen edits.

v1 supplies receipt classification, safe terminal persistence and run ownership.
This entry owns its new spend anchor, workflow, ceilings and stage identities.
"""
from __future__ import annotations
import base64
from copy import deepcopy
from dataclasses import asdict,dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys

from scripts import creative_fresh_source_session_v1 as shared
from scripts import creative_session_text_driver_v1 as driver

VERSION="creative_fresh_source_session/v2"
PROJECT=shared.PROJECT
DEFAULT_PROFILE=PROJECT/"config/creative_fresh_source_session_profile_v2.json"
LIMITS={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}
TOTAL=19
read,write,digest,sha=shared.read,shared.write,shared.digest,shared.sha


@dataclass(frozen=True)
class SessionConfig(shared.SessionConfig):
    profile_path:str=str(DEFAULT_PROFILE)


class RevisionRuntime(shared.FreshRuntime):
    def __init__(self,*args,stage_limits=None,**kwargs):
        if stage_limits is not None and stage_limits!=LIMITS:raise ValueError("exact continuation ceilings required")
        shared.general_runtime.GoalContextRuntime.__init__(self,*args,stage_limits=deepcopy(LIMITS),**kwargs)

    def _policy(self):
        result=super()._policy()
        result.update(schema=VERSION+"/runtime_policy",whole_plan_limit=2,whole_plan_lineage_limit=3,
            opening_setup_limit=2,total_new_calls_limit=TOTAL,known_complete_revision_only=True)
        return result


class Session(shared.Session):
    version=VERSION

    def __init__(self,config,*,workflow_adapter=None,anchor_verifier=None,**dependencies):
        config=config if isinstance(config,SessionConfig) else SessionConfig(**config)
        if anchor_verifier is None:
            anchor_verifier=importlib.import_module("scripts.creative_session_spend_anchor_v1").verify_anchor
        super().__init__(config,anchor_verifier=anchor_verifier,**dependencies)
        self.wf=workflow_adapter or importlib.import_module("src.content_factory.creative_goal_context_workflow_v24")

    def _anchor(self):
        anchor=read(self.config.anchor_path)
        verified=self.anchor_verifier(anchor,expected_anchor_sha256=self.config.anchor_sha256)
        inherited=verified.get("inherited",{})
        if (verified.get("verified") is not True or not anchor.get("root")
                or set(inherited)!={"calls_started","reported_tokens","calls_with_known_usage","pending_ordinals","unknown_token_reservations"}
                or any(type(inherited[k]) is not int or inherited[k]<0 for k in inherited if k!="pending_ordinals")
                or type(inherited["pending_ordinals"]) is not list):raise ValueError("verified complete parent-session spend required")
        return anchor,verified

    def _seed(self,anchor):
        """Read only already-verified session ancestry; never revalidate old rounds/freshness."""
        lineage=[];seen=set();current=anchor
        while str(current.get("schema","")).startswith("creative_session_spend_anchor/"):
            root=Path(current["root"]).resolve();root.relative_to(PROJECT)
            if str(root).casefold() in seen:raise ValueError("cyclic parent-session ancestry")
            seen.add(str(root).casefold());config=read(root/"SESSION_CONFIG.json");ledger=read(root/"CALL_LEDGER.json")
            if any(not re.fullmatch(r"whole_plan_\d{2}",row["label"]) for row in ledger["calls"]):
                raise ValueError("this continuation cannot regrant previously consumed audit/setup/body/review stages")
            for row in ledger["calls"]:
                if re.fullmatch(r"whole_plan_\d{2}",row["label"]):
                    receipt=read(root/row["receipt"]);self.known(receipt,"historical_whole_plan",require_valid=False)
                    lineage.append((root,receipt))
            current=read(config["anchor_path"])
        if not lineage:raise ValueError("a known complete native parent whole plan is required")
        lineage.sort(key=lambda item:item[1]["ordinal"])
        if len({row[1]["ordinal"] for row in lineage})!=len(lineage) or len(lineage)>=3:
            raise ValueError("same-source whole-plan capacity exhausted or duplicated; parent candidates count")
        root,receipt=lineage[-1]
        terminal=read(Path(anchor["root"])/"STATE.json")
        if (terminal.get("status")!="halt_contract_requires_pipeline_diagnosis" or terminal.get("stage")!="whole_plan"
                or terminal.get("receipt_ordinal")!=receipt["ordinal"] or receipt.get("status")!="contract_rejected"):
            raise ValueError("only a terminated known-complete rejected whole_plan can continue here")
        pointer=anchor.get("latest_native_goal_receipt",{})
        if (anchor.get("whole_goal_candidates_used")!=len(lineage) or pointer.get("ordinal")!=receipt["ordinal"]
                or pointer.get("native_goal_sha256")!=digest(receipt["output"])
                or pointer.get("diagnostics_sha256")!=digest(self._diagnosis(receipt))):
            raise ValueError("verified parent native plan/candidate lineage changed")
        return {"used":len(lineage),"parent_root":str(Path(anchor["root"]).resolve()),"receipt_root":str(root),
            "receipt":receipt,"native_goal":deepcopy(receipt["output"]),"diagnostics":self._diagnosis(receipt),
            "original_inputs":read(root/"INPUTS.json"),"ordinal":receipt["ordinal"]}

    def _revision_inputs(self,inputs,seed):
        return {**deepcopy(inputs),"previous_complete_document":deepcopy(seed["native_goal"]),
            "revision_diagnostics":deepcopy(seed["diagnostics"])}

    def _parent_claim(self,anchor):
        identity=os.path.normcase(str(Path(anchor["root"]).resolve()))
        return PROJECT/"data/creative_consumption_successors/by_parent_session"/digest(identity)/"CLAIM.json"

    def preview(self):
        anchor,verified=self._anchor();seed=self._seed(anchor);built=self._inputs();self._profile_gate()
        if digest(built["inputs"])!=digest(seed["original_inputs"]):raise ValueError("revision source/original functional inputs changed")
        prepared=self.wf.prepare_goal_request(self._revision_inputs(built["inputs"],seed),self.profile)
        payload=json.loads(prepared["request"]["messages"][1]["content"])
        if (payload.get("reference_fulltext")!=built["inputs"]["reference_fulltext"]
                or payload.get("previous_complete_document")!=seed["native_goal"]):
            raise ValueError("complete original parent native plan and R01 must enter actual revision request")
        return {"schema":VERSION+"/preview","inputs":built["inputs"],"evidence":built["evidence"],
            "source_files":built["source_files"],"first_request":prepared,"inputs_sha256":digest(built["inputs"]),
            "profile_sha256":sha(self.config.profile_path),"anchor_sha256":digest(anchor),"inherited":verified["inherited"],
            "ownership_evidence":self.wf.ownership_evidence(built["inputs"]),"parent_session_root":seed["parent_root"],
            "native_parent_ordinal":seed["ordinal"],"native_parent_goal_sha256":digest(seed["native_goal"]),
            "native_parent_diagnostics_sha256":digest(seed["diagnostics"]),"whole_plans_used":seed["used"],
            "whole_plans_remaining":3-seed["used"],"stage_limits":LIMITS,"total_new_calls_limit":TOTAL,
            "provider_calls":0,"media_calls":0,"creative_quality_passed":False}

    def authorization_template(self,preview):
        value=super().authorization_template(preview)
        value.update(schema=VERSION+"/derived_authorization",stage_limits=LIMITS,whole_plan_limit=preview["whole_plans_remaining"],
            whole_plan_lineage_limit=3,whole_plans_already_used=preview["whole_plans_used"],total_new_calls_limit=TOTAL,
            parent_session_root=preview["parent_session_root"],native_parent_ordinal=preview["native_parent_ordinal"],
            native_parent_goal_sha256=preview["native_parent_goal_sha256"],
            native_parent_diagnostics_sha256=preview["native_parent_diagnostics_sha256"],
            shared_run_claim_protocol=shared.VERSION+"/run_claim",
            continuation_entry_kind="known_complete_rejected_whole_plan_only",
            ownership_evidence_sha256=digest(preview["ownership_evidence"]))
        return value

    def prepare(self):
        if self.root.exists() or self.claim.exists():raise FileExistsError("existing root/grant cannot restart")
        preview=self.preview();anchor,_=self._anchor();parent_claim=self._parent_claim(anchor)
        if self.successor.exists() or parent_claim.exists():raise FileExistsError("parent session or canonical anchor already has a successor")
        if read(self.config.authorization_path)!=self.authorization_template(preview):raise ValueError("actual continuation authorization mismatch")
        closure=[]
        for module in tuple(sys.modules.values()):
            path=getattr(module,"__file__",None)
            if path:
                target=Path(path).resolve()
                if target.suffix==".py" and any(target.is_relative_to(PROJECT/name) for name in ("scripts","src")):closure.append(target)
        extra=[Path(__file__),PROJECT/"scripts/run_fresh_source_session_v2.py",Path(self.wf.__file__),
            Path(self.config.profile_path),Path(self.config.anchor_path),Path(self.config.authorization_path),
            Path(self.config.counter_root)/"AUTHORIZATION_AND_CADENCE_v1.json",Path(self.config.counter_root)/"USER_COUNT_UNIT_CONFIRMATION_v1.json"]
        files={str(Path(p).resolve()):sha(p) for p in [*closure,*extra,*preview["source_files"],*self.config.extra_source_files]}
        binding={"schema":VERSION+"/successor_claim","anchor_sha256":self.config.anchor_sha256,
            "parent_session_root":preview["parent_session_root"],"parent_state_sha256":sha(Path(anchor["root"])/"STATE.json"),
            "parent_ledger_sha256":sha(Path(anchor["root"])/"CALL_LEDGER.json"),"parent_end_ordinal":preview["inherited"]["calls_started"],
            "parent_identity":deepcopy(anchor["parent_identity"]),"parent_identity_sha256":anchor["parent_identity_sha256"],
            "root":str(self.root),"grant_id":self.config.grant_id,"authorization_sha256":sha(self.config.authorization_path),"old_budget_reset":False}
        # Two independent atomic reservations. Partial preparation is terminal;
        # never remove a reservation or let a changed verifier regrant a parent.
        write(parent_claim,binding,True);write(self.successor,binding,True)
        write(self.claim,{"schema":VERSION+"/claim","root":str(self.root),"grant_id":self.config.grant_id,
            "authorization_sha256":sha(self.config.authorization_path),"old_budget_reset":False},True)
        self.root.mkdir(parents=True)
        for p in (parent_claim,self.successor):files[str(p)]=sha(p)
        for name,value in (("SESSION_CONFIG",asdict(self.config)),("INPUTS",preview["inputs"]),("INPUT_EVIDENCE",preview["evidence"]),
            ("FIRST_REQUEST_PREVIEW",preview["first_request"]),("OWNERSHIP_EVIDENCE",preview["ownership_evidence"]),
            ("USER_SCOPE",read(self.config.authorization_path))):
            p=self.root/(name+".json");write(p,value,True);files[str(p)]=sha(p)
        write(self.root/"PRODUCTION_FREEZE.json",{"schema":VERSION+"/freeze","files":files,"claim_sha256":sha(self.claim),
            "inherited":preview["inherited"],"inputs_sha256":preview["inputs_sha256"],
            "shared_run_claim_protocol":shared.VERSION+"/run_claim",
            "parent_successor_claim":{"path":str(parent_claim),"sha256":sha(parent_claim),"binding":binding}},True)
        runtime=self.runtime();runtime.prepare();return self.state(runtime,"prepared")

    def _guard(self):
        super()._guard()
        freeze=read(self.root/"PRODUCTION_FREEZE.json");anchor,_=self._anchor();parent_claim=self._parent_claim(anchor)
        proof=freeze.get("parent_successor_claim",{})
        if (str(parent_claim)!=proof.get("path") or sha(parent_claim)!=proof.get("sha256")
                or read(parent_claim)!=proof.get("binding") or read(parent_claim)!=read(self.successor)):
            raise ValueError("parent-session unique successor binding changed")

    def runtime(self):
        freeze=read(self.root/"PRODUCTION_FREEZE.json")
        return RevisionRuntime(PROJECT,self.root,[Path(p) for p in freeze["files"]],freeze["inherited"],profile=self.profile,
            stage_limits=LIMITS,inherited_guard=self._guard,admission=self._admit,
            shared_lock=PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock",quota_state=None,client_factory_builder=self.client_factory_builder)

    def _admit(self,label,request,ledger):
        self._guard();shared.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"])>=TOTAL:raise ValueError("continuation19 calls exhausted")
        if not re.fullmatch(r"whole_plan_0[23]|(?:source|commitment|drama)_audit_0[23]|opening_setup_0[12]|complete_script_0[123]|full_review_(?:semantic|physical)_0[123]",label):
            raise ValueError("exact continuation stage identity required")
        if any(row["label"]==label for row in ledger["calls"]):raise ValueError("stage identity already consumed")
        seed=self._seed(self._anchor()[0]);whole_rows=[row for row in ledger["calls"] if row["label"].startswith("whole_plan_")]
        if label.startswith("whole_plan_"):
            expected_index=seed["used"]+len(whole_rows)+1
            if expected_index>3 or label!=f"whole_plan_{expected_index:02}":raise ValueError("same-source parent candidates count toward total3")
        elif "_audit_" in label:
            if not whole_rows or label[-2:]!=whole_rows[-1]["label"][-2:]:raise ValueError("audit must bind latest new whole native plan")
            planned=read(self.root/whole_rows[-1]["receipt"])
            self.known(planned,"audit_parent")
            props=request.get("structured_schema",{}).get("properties",{});expected_goal=digest(planned["output"])
            if (props.get("goal_sha256",{}).get("const")!=expected_goal
                    or request.get("input_provenance",{}).get("native_goal_sha256",expected_goal)!=expected_goal):
                raise ValueError("audit native plan SHA differs")
        props=request.get("structured_schema",{}).get("properties",{});version=props.get("schema",props.get("contract_version",{})).get("const")
        if label.startswith("whole_plan_"):expected=("goal_plan","creative_goal_source_v4")
        elif label.startswith("opening_setup_"):expected=("goal_plan",self.wf.OPENING_SETUP_VERSION)
        elif label.startswith("source_audit_"):expected=("goal_audit",self.wf.SOURCE_AUDIT_VERSION)
        elif label.startswith("commitment_audit_"):expected=("goal_audit",self.wf.commitment_audit.VERSION)
        elif label.startswith("drama_audit_"):expected=("goal_audit",self.wf.DRAMA_AUDIT_VERSION)
        elif label.startswith("full_review_"):
            expected=("full_review",shared.reviews.VERSION)
            if props.get("part",{}).get("const")!=label.split("_")[2]:raise ValueError("review part identity changed")
        else:
            # The existing native body has no schema/version discriminator.
            # Pin its full derived schema instead of inventing a new field.
            if version is not None:raise ValueError("stage/request contract mismatch: unexpected body discriminator")
            setup_rows=[row for row in ledger["calls"] if row["label"].startswith("opening_setup_")]
            if not whole_rows or not setup_rows:raise ValueError("body requires native goal and opening setup")
            goal_receipt=read(self.root/whole_rows[-1]["receipt"]);setup_receipt=read(self.root/setup_rows[-1]["receipt"])
            goal=self.known(goal_receipt,"body_goal");setup=self.known(setup_receipt,"body_setup")
            views=self.wf.compile_native_views(goal,setup,**self.wf.origin_ids(read(self.root/"INPUTS.json")))
            expected_schema=self.wf.windows.build_script_schema(views["brief"]);beats=expected_schema["properties"]["beats"]
            beat_ids=[row["id"] for row in views["plan"]["beats"]]
            beats.update(minItems=len(beat_ids),maxItems=len(beat_ids));beats["items"]["properties"]["id"]={"enum":beat_ids}
            if request["structured_schema"]!=expected_schema:raise ValueError("exact current native body schema required")
            expected=("complete_script",None)
        if (request.get("stage"),version)!=expected:raise ValueError("stage/request contract mismatch")
        return True

    def invoke(self,runtime,label,prepared,validator):
        """Same native SDK/DAG protocol as v1, with this entry's actual ceilings."""
        request=prepared["request"];wire=shared.strict.expected_wire_request(request,source_strict=shared.strict_source(request))
        for row in read(runtime.ledger)["calls"]:
            if runtime.effective_receipt(row)["request_sha256"]==digest(request):return runtime.dispatch(label,request,validator)
        self._guard();shared.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        write(self.root/"requests"/(label+".json"),prepared,True)
        store=shared.tasks.TaskStore(self.root/"TASKS.sqlite3");gid="call_"+digest([self.config.grant_id,label])[:24]
        store.register_graph({"schema_version":shared.tasks.GRAPH_SCHEMA,"graph_id":gid,"nodes":[
            {"node_id":"source","kind":"source","input":{"source_manifest":digest(read(runtime.ledger)["source_manifest"]),"request_sha256":digest(request)},"depends_on":[]},
            {"node_id":"result","kind":"text","input":{"label":label,"stage":request["stage"]},"depends_on":["source"]}]})
        scope=self.root/"USER_SCOPE.json"
        attempt=store.claim(gid,"result",{"provider_id":request["model"],"payload":request},{"schema_version":shared.tasks.AUTH_SCHEMA,
            "authorization_id":gid+":scope","graph_id":gid,"node_ids":["result"],"scope":"text","purpose":"dispatch",
            "source_sha256":store.snapshot(gid)["source_sha256"],"max_attempts":LIMITS[request["stage"]],"prior_attempts":0,
            "allows_content_revision":False,"evidence_ref":str(scope)+"#"+request["stage"],"evidence_sha256":sha(scope)})
        receipt=runtime.dispatch(label,request,validator);directory=shared.evidence.verify_receipt_evidence(runtime,receipt,request)
        if (directory/"request_body.raw").exists() and shared.io.strict_json((directory/"request_body.raw").read_text(encoding="utf-8"))!=wire:
            raise ValueError("actual SDK wire differs from frozen request")
        raw=(directory/"response_body.raw").read_bytes() if (directory/"response_body.raw").exists() else b""
        known,outcome,tool=self.classify_native(receipt);meta=receipt.get("response_metadata",{});total=meta.get("total_tokens")
        store.accept_result(attempt["claim_id"],{"schema_version":shared.tasks.RESULT_SCHEMA,"claim_id":attempt["claim_id"],
            "request_sha256":attempt["request_sha256"],"service_task_id":None,"outcome":outcome,"result_known":known,
            "usage_known":type(total)is int and total>=0,"usage":{"unit":"reported_tokens","amount":total} if type(total)is int and total>=0 else None,
            "complete":meta.get("response_body_complete") is True,"complete_end":meta.get("finish_reason") in ("stop","tool_calls"),
            "schema_tool_status":tool,"contract_valid":receipt["status"]=="contract_valid" if known else None,
            "raw_receipt":{"encoding":"base64","body":base64.b64encode(raw).decode(),"sha256":hashlib.sha256(raw).hexdigest(),"http_status":meta.get("http_status_code")},
            "output":{"ordinal":receipt["ordinal"],"native_output":receipt.get("output")}})
        return receipt

    def state(self,runtime,status,**details):
        value=super().state(runtime,status,**details)
        value.update(schema=VERSION+"/state",flow_version=VERSION,shared_state_protocol=shared.VERSION,
            shared_run_claim_protocol=shared.VERSION+"/run_claim")
        write(self.root/"STATE.json",value);return value

    @staticmethod
    def known(receipt,stage,*,require_valid=True):
        known,outcome,tool=shared.Session.classify_native(receipt)
        if receipt.get("cached_response_read_only"):raise shared.Halt("halt_cached_stage_no_new_progress",stage=stage,receipt_ordinal=receipt["ordinal"])
        if known and (outcome=="protocol_rejected" or tool!="accepted"):
            raise shared.Halt("halt_protocol_requires_diagnosis",stage=stage,receipt_ordinal=receipt["ordinal"])
        return shared.Session.known(receipt,stage,require_valid=require_valid)

    def _source_request(self,inputs,goal):
        prepared=self.wf.prepare_goal_source_audit_request(inputs,self.profile,goal);request=prepared["request"]
        binding=shared.strict.protocol_binding(request,review_base_url=self.profile["source_strict"]["base_url"])
        prepared["source_schema_compilation_manifest"]=shared.strict.schema_compilation_manifest(request)
        request["input_provenance"]["source_protocol_binding"]=binding;prepared["manifest"]["source_protocol_binding"]=deepcopy(binding)
        request["input_provenance"]["context_manifest_sha256"]=digest(prepared["manifest"])
        prepared["request_sha256"]=digest(request);prepared["wire"]=shared.strict.expected_wire_request(request,source_strict=True)
        size=len(json.dumps(prepared["wire"],ensure_ascii=False,separators=(",",":")).encode("utf8"))
        if size>self.profile["source_strict"]["max_wire_utf8_bytes"]:raise ValueError("actual strict source wire exceeds explicit bound")
        prepared["strict_wire_measurement"]={"utf8_bytes":size,"wire_sha256":digest(prepared["wire"])}
        return prepared

    def _flow(self,runtime,inputs):
        anchor,_=self._anchor();seed=self._seed(anchor);current=self._revision_inputs(inputs,seed)
        for index in range(seed["used"]+1,4):
            prepared=self.wf.prepare_goal_request(current,self.profile)
            if index==seed["used"]+1 and prepared!=read(self.root/"FIRST_REQUEST_PREVIEW.json"):
                raise ValueError("actual revision request differs from frozen complete-parent preview")
            receipt=self.invoke(runtime,f"whole_plan_{index:02}",prepared,lambda value:self.wf.validate_goal_document(value,inputs=inputs))
            goal=self.known(receipt,"whole_plan",require_valid=False)
            folder=self.root/"goal"/f"version_{index:02}";write(folder/"NATIVE_GOAL.json",goal,True)
            if receipt["status"]!="contract_valid":
                current={**deepcopy(inputs),"previous_complete_document":goal,"revision_diagnostics":self._diagnosis(receipt)};continue
            audits={};failed=None
            for kind in ("source","commitment","drama"):
                prepared=self._source_request(inputs,goal) if kind=="source" else getattr(self.wf,f"prepare_goal_{kind}_audit_request")(inputs,self.profile,goal)
                args={"context_sha256":prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]}
                if kind=="source":args.update(authority_context=prepared["source_authority_context"],inputs=inputs)
                validator=getattr(self.wf,f"validate_goal_{kind}_audit")
                reviewed=self.invoke(runtime,f"{kind}_audit_{index:02}",prepared,lambda value,v=validator,a=args:v(value,goal,**a))
                native=self.known(reviewed,kind,require_valid=False)
                write(folder/(kind+"_native.json"),native,True)
                if reviewed["status"]!="contract_valid":
                    write(folder/(kind+"_contract_diagnostics.json"),self._diagnosis(reviewed),True)
                    raise shared.Halt("halt_goal_audit_contract_requires_diagnosis",audit_kind=kind,receipt_ordinal=reviewed["ordinal"])
                decision=reviewed["validation"];write(folder/(kind+"_decision.json"),decision,True)
                if decision["uncertainties"]:raise shared.Halt("halt_goal_audit_uncertain",audit_kind=kind,receipt_ordinal=reviewed["ordinal"],decision=decision)
                if not decision["accepted"]:failed={"goal_audit_decisions":[decision],"native_audit":native};break
                audits[kind]=native
            if failed is not None:
                current={**deepcopy(inputs),"previous_complete_document":goal,"revision_diagnostics":failed};continue
            bundle=self.wf.build_goal_audit_bundle(audits["source"],audits["drama"],audits["commitment"])
            setup=driver.opening(self,runtime,inputs,goal)
            return driver.body(self,runtime,inputs,goal,bundle,setup,receipt["ordinal"])
        raise shared.Halt("halt_whole_plan_lineage_capacity_exhausted",whole_plan_lineage_limit=3,parent_candidates_counted=seed["used"])

    def execution_evidence(self,runtime,inputs,goal_ordinal,script_ordinal,review_ordinals,*,views,compiled):
        ledger=read(runtime.ledger);rows=ledger["calls"];needed={goal_ordinal,script_ordinal,*review_ordinals.values()};receipts=[];originals={}
        goal_row=next(row for row in rows if row["ordinal"]==goal_ordinal);suffix=goal_row["label"][-2:]
        audits=[row for row in rows if row["label"] in {f"{kind}_audit_{suffix}" for kind in ("source","commitment","drama")}]
        if len(audits)!=3:raise ValueError("all three native goal audits required for execution evidence")
        needed.update(row["ordinal"] for row in audits)
        for row in rows:
            if row["ordinal"] not in needed:continue
            native=runtime.effective_receipt(row);self.known(native,"execution_evidence")
            directory=shared.evidence.verify_receipt_evidence(runtime,native,native["request"])
            if shared.io.strict_json((directory/"request_body.raw").read_text(encoding="utf-8"))!=shared.strict.expected_wire_request(
                    native["request"],source_strict=shared.strict_source(native["request"])):raise ValueError("execution raw wire changed")
            calls=native["response_payload"]["choices"][0]["message"].get("tool_calls",[])
            if (len(calls)!=1 or calls[0]["function"]["name"]!=shared.ordinary.TOOL_NAME
                    or shared.io.strict_json(calls[0]["function"]["arguments"])!=native["output"]):
                raise ValueError("complete native output differs from original provider tool arguments")
            if native.get("source_binding_sha256")!=digest(ledger["source_manifest"]):raise ValueError("native execution source identity changed")
            if "_audit_" in row["label"] and (not native["validation"]["accepted"] or native["validation"]["uncertainties"]):
                raise ValueError("accepted complete same-goal native audits required")
            originals[row["ordinal"]]=native
            receipts.append({"ordinal":row["ordinal"],"receipt":row["receipt"],"receipt_sha256":row["receipt_sha256"],
                "request_sha256":native["request_sha256"],"native_output_sha256":digest(native["output"])})
        if {r["ordinal"] for r in receipts}!=needed:raise ValueError("complete native generation and both same-source full reviews required")
        reference=inputs["reference_fulltext"]
        def occurrences(value):
            if isinstance(value,str):return value.count(reference)
            if isinstance(value,dict):return sum(occurrences(item) for item in value.values())
            if isinstance(value,list):return sum(occurrences(item) for item in value)
            return 0
        request_messages=originals[goal_ordinal]["request"]["messages"]
        actual_occurrences=occurrences(request_messages[0]["content"])+occurrences(json.loads(request_messages[1]["content"])) if reference else 0
        if actual_occurrences!=1:
            raise ValueError("R01 must occur exactly once in actual native planning request")
        native_script=originals[script_ordinal]["output"]
        if shared.text.contract.compile_script(native_script,views["brief"])!=compiled:raise ValueError("compiler input differs from complete native body")
        for ordinal in review_ordinals.values():
            payload=json.loads(originals[ordinal]["request"]["messages"][1]["content"])
            if payload.get("native_script_document")!=native_script:raise ValueError("full review must receive the unmodified same native script")
        return {"schema":VERSION+"/execution_requirements","ownership":self.wf.ownership_evidence(inputs),
            "native_receipts":receipts,"r01_actual_planning_occurrences":1,"r01_fulltext_sha256":digest(reference),
            "native_script_sha256":digest(native_script),"compiler_input_native_sha256":digest(native_script),
            "compiled_script_sha256":digest(compiled),"same_native_full_review_inputs_verified":True,
            "bounded_whole_native_revisions":True,"manual_native_content_patch":False,
            "human_quality_approved":False,"semantic_generalization_proven":False}
