"""Restricted mechanical evidence plumbing for the v9 continuation.

Fixed policy and flow come from the calling code, never a document-supplied
module. The frozen v8 implementation is not modified or monkeypatched.
"""
from dataclasses import dataclass, asdict
from copy import deepcopy
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v8 as prior
base, source_refs, native_proof = prior.base, prior.source_refs, prior.native_proof
read, write, digest, sha = prior.read, prior.write, prior.digest, prior.sha

@dataclass(frozen=True)
class FixedPolicy:
    version: str
    stage_pairs: tuple
    label_pattern: str
    @property
    def limits(self): return dict(self.stage_pairs)
    @property
    def total(self): return sum(self.limits.values())

def _locals(session, policy):
    if policy is not session.POLICY: raise ValueError("fixed entry policy identity required")
    if any(type(v) is not int or v < 0 for v in policy.limits.values()): raise ValueError("integer fixed stage limits required")
    return session, policy.version, policy.limits, policy.total

def preview(session, policy):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    anchor, checked = self._parent(); built = self._inputs(); self._profile_gate(); inputs = read(anchor["current_inputs_path"])
    if built["inputs"] != inputs or inputs != read(source_refs.creative_root(anchor)/"INPUTS.json") or self.profile != read(anchor["current_profile_path"]):
        raise ValueError("exact original current inputs/profile required")
    wf = self._workflow(); seed = self.source_material(wf)
    first = self.first_prepared(inputs,wf,seed)
    files = base._hashes([*built["source_files"], self.config.parent_anchor_path, self.config.profile_path,
        self.config.preferences_path, self.config.user_goals_path, *self.config.extra_source_files, *self.code_files()])
    for path, item in checked.get("source_files", {}).items():
        expected = item.get("sha256") if type(item) is dict else item
        if sha(base._inside(path)) != expected: raise ValueError("certified original parent changed")
        files[str(base._inside(path))] = expected
    value = {"schema": VERSION+"/preview", "root": str(self.root), "grant_id": self.config.grant_id, "inputs": inputs,
        "input_evidence": built["evidence"], "inputs_sha256": digest(inputs), "first_request": first,
        "profile_sha256": sha(self.config.profile_path), "parent_anchor_sha256": digest(anchor), "parent_root": anchor["root"],
        "parent_identity": anchor["parent_identity"], "inherited": checked["inherited"], "source_files": files,
        "creative_source_root": str(source_refs.creative_root(anchor)), "stage_limits": deepcopy(LIMITS), "total_new_calls_limit": TOTAL,
        "provider_calls": 0, "media_calls": 0}
    value["preparation_identity_sha256"] = digest({key: value[key] for key in (
        "root", "grant_id", "inputs_sha256", "profile_sha256", "parent_anchor_sha256", "inherited", "source_files", "first_request")})
    return value

def prepare(session, policy):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    if self.root.exists() or self.claim.exists(): raise FileExistsError("existing root/grant cannot restart")
    preview = self.preview(); parent, _ = self._parent(); binding = self._binding(parent)
    if read(self.config.authorization_path) != self.authorization_template(preview): raise ValueError("exact new fixed-capacity authorization required")
    successors = base.policy.successor_paths(base.PROJECT, parent, self.config.parent_anchor_sha256)
    if any(path.exists() for path in successors): raise ValueError("settled real parent already has a successor")
    self.root.mkdir(parents=True, exist_ok=False)
    for name, value in (("SESSION_CONFIG", asdict(self.config)), ("INPUTS", preview["inputs"]), ("INPUT_EVIDENCE", preview["input_evidence"]),
            ("FIRST_REQUEST_PREVIEW", preview["first_request"]), ("USER_SCOPE", read(self.config.authorization_path))): write(self.root/(name+".json"), value, True)
    base.policy.new_claim(self.claim, {**binding, "schema": VERSION+"/grant_claim"})
    for path in successors: base.policy.new_claim(path, binding)
    files = {**preview["source_files"], **base._hashes([self.config.authorization_path, self.claim, *successors,
        *(self.root/(name+".json") for name in ("SESSION_CONFIG", "INPUTS", "INPUT_EVIDENCE", "FIRST_REQUEST_PREVIEW", "USER_SCOPE")),
        Path(self.config.counter_root)/"AUTHORIZATION_AND_CADENCE_v1.json", Path(self.config.counter_root)/"USER_COUNT_UNIT_CONFIRMATION_v1.json"])}
    write(self.root/"PRODUCTION_FREEZE.json", {"schema": VERSION+"/freeze", "files": files, "inputs_sha256": preview["inputs_sha256"],
        "inherited": preview["inherited"], "binding": binding, "successor_claim_paths": [str(path) for path in successors],
        "claim_sha256": sha(self.claim), "stage_limits": deepcopy(LIMITS), "total_new_calls_limit": TOTAL, "old_director_capacity": base.DIRECTOR}, True)
    runtime = self.runtime(); runtime.prepare(); return self.state(runtime, "prepared")

def guard(session, policy):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    freeze, scope = read(self.root/"PRODUCTION_FREEZE.json"), read(self.root/"USER_SCOPE.json")
    if (freeze.get("schema") != VERSION+"/freeze" or freeze.get("stage_limits") != LIMITS or freeze.get("total_new_calls_limit") != TOTAL
            or scope != self.authorization_template({"preparation_identity_sha256": scope.get("preparation_identity_sha256"),
                "inherited": freeze["inherited"], "inputs_sha256": freeze["inputs_sha256"], "creative_source_root": scope.get("creative_source_root"),
                "inputs": read(self.root/"INPUTS.json")})): raise ValueError("exact versioned continuation fixed-capacity scope required")
    if any(type(value) is not int for value in scope["stage_limits"].values()) or type(scope["total_new_calls_limit"]) is not int: raise ValueError("integer limits required")
    if digest(asdict(self.config)) != digest(read(self.root/"SESSION_CONFIG.json")): raise ValueError("frozen config differs")
    for path, expected in freeze["files"].items():
        if sha(base._inside(path)) != expected: raise ValueError("frozen dependency changed: "+path)
    anchor = read(self.config.parent_anchor_path)
    if digest(anchor) != self.config.parent_anchor_sha256 or anchor["inherited"] != freeze["inherited"]: raise ValueError("parent accounting changed")
    paths = base.policy.successor_paths(base.PROJECT, anchor, self.config.parent_anchor_sha256); binding = self._binding(anchor)
    if freeze["successor_claim_paths"] != [str(path) for path in paths] or freeze["binding"] != binding: raise ValueError("real parent binding differs")
    if sha(self.claim) != freeze["claim_sha256"] or read(self.claim) != {**binding, "schema": VERSION+"/grant_claim"}: raise ValueError("grant changed")
    for path in paths:
        if read(path) != binding: raise ValueError("unique real parent successor changed")
    if (scope["creative_source_root"] != str(source_refs.creative_root(anchor)) or read(self.root/"INPUTS.json") != read(anchor["current_inputs_path"])
            or read(self.root/"INPUTS.json") != read(source_refs.creative_root(anchor)/"INPUTS.json")): raise ValueError("current authority changed")
    self._profile_gate(); gate = self.source_gate(self.config.source_dir, now=self.clock())
    if gate.get("valid") is not True or gate.get("current_source_freshness_verified") is not True: raise ValueError("current source freshness required")
    path = self.root/"RUN_CLAIM.json"
    if path.exists():
        claim = read(path)
        if not (claim.get("schema") == VERSION+"/run_claim" and claim.get("root") == str(self.root) and type(claim.get("pid")) is int
                and claim["pid"] > 0 and claim.get("automatic_restart") is False and claim.get("freeze_sha256") == sha(self.root/"PRODUCTION_FREEZE.json")):
            raise ValueError("original single-use continuation RUN differs")
    return True

def admit(session, policy, label, request, ledger):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
    if len(ledger["calls"]) >= TOTAL or not re.fullmatch(policy.label_pattern,label):
        raise ValueError("only code-registered continuation stages are authorized")
    stage = self.stage_for_label(label)
    if request.get("stage") != stage: raise ValueError("registered stage mapping differs")
    pending = self.pending_intent
    if not pending or pending["label"] != label or sha(pending["path"]) != pending["sha256"]: raise ValueError("original builder intent missing")
    intent = read(pending["path"])
    if (intent.get("schema") != VERSION+"/call_intent" or intent["prepared"]["request"] != request or intent["request_sha256"] != digest(request)
            or intent["ledger_prefix_sha256"] != digest(ledger["calls"]) or intent["inputs_sha256"] != digest(read(self.root/"INPUTS.json"))
            or self._replay(ledger, label)["request"] != request): raise ValueError("exact linked request cannot be rebuilt")
    base.clients.expected_wire_request(request); return True

def save_text(session, policy, result, driver, runtime):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    paths, values = self.artifacts(result)
    for key, value in values.items(): write(paths[key], value, True)
    rendered = self.root/"scripts/FULL_SCRIPT.md"
    with rendered.open("x", encoding="utf-8", newline="\n") as stream: stream.write(result["rendered_script"])
    anchor = read(self.config.parent_anchor_path)
    handoff = {"schema": VERSION+"/text_handoff", "status": "text_ready_for_director", "source_root": str(self.root),
        "paths": {key:str(path.resolve()) for key,path in paths.items()}, "artifact_file_sha256": base._hashes([*paths.values(), rendered]),
        "native_identity": {key:digest(value) for key,value in values.items()}, "source_descriptor": result["source_descriptor"],
        "inherited_current_native_receipt_references": {key:deepcopy(anchor[key]) for key in self.REF_KEYS},
        "receipt_identities": [base._receipt_identity(self.root,row) for row in read(runtime.ledger)["calls"]], "decision": result["decision"],
        "source_state_decision": result["source_state_decision"], "freeze_sha256": sha(self.root/"PRODUCTION_FREEZE.json"),
        "run_claim_sha256": sha(self.root/"RUN_CLAIM.json"), "native_reports_unchanged": True,
        "human_quality_approved": False, "creative_quality_passed": False, "media_submitted": False, "old_budget_reset": False}
    write(self.root/"TEXT_HANDOFF.json", handoff, True)
    return self.state(runtime,"text_ready_for_director",text_handoff_sha256=digest(handoff),handoff_path=str(self.root/"TEXT_HANDOFF.json"))

def run(session, policy):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    if not (self.root/"PRODUCTION_FREEZE.json").is_file(): raise ValueError("separately prepared continuation root required")
    base.policy.new_claim(self.root/"RUN_CLAIM.json", {"schema":VERSION+"/run_claim","root":str(self.root),"pid":base.os.getpid(),
        "started_at":self.clock(),"automatic_restart":False,"freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json")})
    runtime = None
    try:
        runtime=self.runtime();self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if read(runtime.ledger)["calls"]: raise ValueError("original nonempty RUN cannot restart")
        driver=self.driver_type(self,runtime,read(self.root/"INPUTS.json"),self._workflow());return self._save_text(driver.flow(),driver,runtime)
    except (base.Halt,base.stages.OfflineStop) as stop:return self.state(runtime,stop.status,**stop.details)
    except Exception as exc:
        write(self.root/"EXECUTION_ERROR.json",{"type":type(exc).__name__,"message":str(exc),"automatic_restart":False},True)
        return self.state(runtime,"halt_execution_reconciliation",exception_type=type(exc).__name__,error=str(exc))

def state(session, policy, runtime, status, **details):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    value=base.NativeSession.state(self,runtime,status,**details)
    value.update(schema=VERSION+"/state",flow_version=VERSION,new_stage_limits=LIMITS,
        text_ready_for_director=status=="text_ready_for_director",**self.state_metadata())
    if (self.root/"RUN_CLAIM.json").exists():value["run_claim_sha256"]=sha(self.root/"RUN_CLAIM.json")
    write(self.root/"STATE.json",value);return value


def dispatch(driver, policy, label, prepared, validator):
    session,runtime=driver.session,driver.runtime;_locals(session,policy);ledger=read(runtime.ledger)
    if any(row["label"]==label for row in ledger["calls"]):raise base.Halt("halt_duplicate_live_stage",label=label)
    intent={"schema":policy.version+"/call_intent","label":label,"prepared":deepcopy(prepared),
        "request_sha256":digest(prepared["request"]),"ledger_prefix_sha256":digest(ledger["calls"]),
        "inputs_sha256":digest(driver.inputs),"automatic_retry":False}
    path=session.root/"call_intents"/(label+".json");write(path,intent,True)
    session.pending_intent={"path":str(path),"sha256":sha(path),"label":label}
    receipt=base.policy.dispatch_claimed(runtime,label,prepared,validator,root=session.root,grant_id=session.config.grant_id,
        stage_limits=policy.limits,current_round_root=session.config.counter_root,current_round_key=session.config.round_key,guard=session._guard)
    native,decision=native_proof.known_native(receipt),base._decision(receipt)
    row={"label":label,"ordinal":receipt["ordinal"],"receipt":f"call_{receipt['ordinal']:03}_{label}.json",
        "status":receipt["status"],"request_sha256":receipt["request_sha256"]}
    driver.calls.append(row);return native,decision,row

def verify_handoff(session, policy):
    self, VERSION, LIMITS, TOTAL = _locals(session,policy)
    runtime=session.runtime();session._guard();anchor,parent=session._parent()
    state,handoff,ledger=(read(session.root/(name+".json")) for name in ("STATE","TEXT_HANDOFF","CALL_LEDGER"))
    if (state.get("status")!="text_ready_for_director" or state.get("spend_verification_pending") is not False
            or handoff.get("schema")!=VERSION+"/text_handoff" or state.get("text_handoff_sha256")!=digest(handoff)
            or handoff.get("freeze_sha256")!=sha(session.root/"PRODUCTION_FREEZE.json")
            or not(handoff.get("run_claim_sha256")==state.get("run_claim_sha256")==sha(session.root/"RUN_CLAIM.json"))):raise ValueError("known original versioned handoff required")
    current=runtime.summary()
    if current!=state["spend"] or current["new_unknown_token_reservations"]!=0:raise ValueError("settled accounting differs")
    reader=base.evidence.Reader();receipts=[base.evidence.verify_original_receipt(session.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    base.evidence._tasks(reader,session.root,ledger,receipts,session.config.grant_id)
    if handoff.get("receipt_identities")!=[base._receipt_identity(session.root,row) for row in ledger["calls"]]:raise ValueError("receipt/intent identities differ")
    for index,(row,receipt) in enumerate(zip(ledger["calls"],receipts)):
        intent=read(session.root/"call_intents"/(row["label"]+".json"))
        if (intent.get("schema")!=VERSION+"/call_intent" or intent["prepared"]["request"]!=receipt["request"]
                or intent["ledger_prefix_sha256"]!=digest(ledger["calls"][:index])):raise ValueError("original intent/prefix differs")
    result=session._replay(ledger,verify_validations=True);expected=session.artifacts(result)[1]
    if handoff.get("inherited_current_native_receipt_references")!={key:anchor[key] for key in session.REF_KEYS}:raise ValueError("inherited accepted-source refs differ")
    for path,expected_sha in handoff["artifact_file_sha256"].items():reader.verify(base._inside(path),expected_sha)
    if handoff.get("native_identity")!={key:digest(value) for key,value in expected.items()}:raise ValueError("raw/derived/compiled identities differ")
    for key,value in expected.items():
        if read(base._inside(handoff["paths"][key]))!=value:raise ValueError("artifact differs from native derivation: "+key)
    if (read(handoff["paths"]["inputs"])!=read(session.root/"INPUTS.json") or read(handoff["paths"]["profile"])!=session.profile
            or handoff.get("source_descriptor")!=result["source_descriptor"] or handoff.get("decision")!=result["decision"]
            or handoff.get("source_state_decision")!=result["source_state_decision"]
            or (session.root/"scripts/FULL_SCRIPT.md").read_text(encoding="utf-8")!=result["rendered_script"]):raise ValueError("authority/derived proof/render differs")
    identity={"root":str(session.root),"terminal_state_sha256":sha(session.root/"STATE.json"),"native_ledger_sha256":sha(session.root/"CALL_LEDGER.json"),
        "production_freeze_sha256":sha(session.root/"PRODUCTION_FREEZE.json"),"end_ordinal":current["effective_calls_started"]}
    inherited={"calls_started":current["effective_calls_started"],"reported_tokens":current["effective_reported_tokens"],
        "calls_with_known_usage":current["effective_calls_with_known_usage"],"pending_ordinals":deepcopy(current["historical_pending_ordinals"]),
        "unknown_token_reservations":current["unknown_token_reservations"]}
    files={**read(session.root/"PRODUCTION_FREEZE.json")["files"],**{path:item["sha256"] for path,item in reader.files.items()},
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
