"""Blind enacted-causality calibration, then two bounded whole-script repairs."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v7 as prior
from scripts import creative_world_scene_live_session_v5 as body_flow

base, references, source_refs, native_proof = prior.base, prior.references, prior.source_refs, prior.native_proof
Config = prior.Config
VERSION = "creative_world_scene_live_session/v8"
LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 2, "full_review": 9}
TOTAL, BODY_VERSIONS = 11, [15, 16]
PARENT_LIMITS = deepcopy(prior.LIMITS)
PARENT_USED = {"goal_plan": 0, "goal_audit": 0, "complete_script": 3, "full_review": 1}
PARENT_REMAINING = {key: value-PARENT_USED[key] for key, value in PARENT_LIMITS.items()}
REF_KEYS = (*prior.REF_KEYS, "current_valid_body_receipt")
read, write, digest, sha = prior.read, prior.write, prior.digest, prior.sha


def referenced_json(ref):
    path = base._inside(ref["path"])
    if sha(path) != ref["file_sha256"]: raise ValueError("original embedded evidence file changed")
    value = read(path)
    pointer = ref.get("json_pointer", "")
    if pointer and not pointer.startswith("/"): raise ValueError("absolute JSON pointer required")
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if type(value) is list else value[token]
    if digest(value) != ref["native_sha256"]: raise ValueError("original embedded source identity changed")
    return value


class Runtime(prior.Runtime):
    def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs); self.stage_limits = deepcopy(LIMITS)
    def _request_gate(self, request): return base.Runtime._request_gate(self, request)
    def _policy(self):
        value = super()._policy(); value.update(schema=VERSION + "/runtime_policy", total_new_calls_limit=TOTAL,
            new_source_state_audit_limit=0, reuses_accepted_source_state=True, complete_script_versions=BODY_VERSIONS,
            parent_scope_stage_limits=PARENT_LIMITS, parent_scope_stage_calls=PARENT_USED, parent_scope_remaining=PARENT_REMAINING,
            parent_scope_calls_used=4, parent_scope_calls_remaining=5, parent_unused_body_calls=0,
            old_complete_body_calls_used=14, old_complete_body_capacity=14,
            previous_body_versions_spent=[12, 13, 14], new_body_contract_scope=False, known_content_repair_scope=True)
        return value


class Driver(prior.Driver):
    def invoke(self, label, prepared, validator):
        session, runtime = self.session, self.runtime; ledger = read(runtime.ledger)
        if any(row["label"] == label for row in ledger["calls"]): raise base.Halt("halt_duplicate_live_stage", label=label)
        intent = {"schema": VERSION+"/call_intent", "label":label, "prepared":deepcopy(prepared),
            "request_sha256":digest(prepared["request"]), "ledger_prefix_sha256":digest(ledger["calls"]),
            "inputs_sha256":digest(self.inputs), "automatic_retry":False}
        path=session.root/"call_intents"/(label+".json");write(path,intent,True)
        session.pending_intent={"path":str(path),"sha256":sha(path),"label":label}
        receipt=base.policy.dispatch_claimed(runtime,label,prepared,validator,root=session.root,grant_id=session.config.grant_id,
            stage_limits=LIMITS,current_round_root=session.config.counter_root,current_round_key=session.config.round_key,guard=session._guard)
        native,decision=native_proof.known_native(receipt),base._decision(receipt)
        row={"label":label,"ordinal":receipt["ordinal"],"receipt":f"call_{receipt['ordinal']:03}_{label}.json",
            "status":receipt["status"],"request_sha256":receipt["request_sha256"]}
        self.calls.append(row);return native,decision,row

    def _focused(self,native,views,label):
        prepared=self.wf.prepare_enacted_causality_request(self.inputs,self.profile,native,views)
        report,decision,row=self.invoke(label,prepared,lambda value:self.wf.validate_enacted_causality(value,prepared))
        accepted=self.audit_gate(decision,"enacted_causality")
        if decision.get("requires_new_goal_plan"):
            raise base.Halt("halt_requires_new_complete_goal",native_enacted_review=report,decision=decision,no_replanning_authorized=True)
        return accepted,report,decision

    def flow(self):
        seed=self.session.source_material(self.wf);goal,bundle,setup=seed["goal"],seed["audit_bundle"],seed["setup"]
        native,views=seed["calibration_native_script"],seed["calibration_views"]
        accepted,report,decision=self._focused(native,views,"enacted_causality_calibration_14")
        if accepted:
            raise base.Halt("halt_calibration_missed",native_enacted_review=report,decision=decision,
                registered_native_script_sha256=digest(native),content_approved=False)
        calibration={"native_report":report,"decision":decision,"native_script_sha256":digest(native),"known_counterexample_rejected":True,"semantic_detection_correctness_programmatically_verified":False}
        current={**deepcopy(self.inputs),"previous_complete_document":native,
            "revision_diagnostics":{"complete_same_source_enacted_review":decision,"native_enacted_review":report}}
        reviews=self.wf.full_reviews()
        for version in BODY_VERSIONS:
            self.body_used+=1
            authored=self.wf.prepare_script_request(current,self.profile,goal,bundle,opening_setup=setup,
                source_state_audit=seed["source_report"],source_state_prepared=seed["source_prepared"],**self.wf.origin_ids(self.inputs))
            views=authored["views"]
            native,checked,_=self.invoke(f"complete_script_{version:02}",authored,
                lambda value:{**self.wf.validate_script_document(value,views,self.inputs["production_preferences"]),"valid":True})
            if checked.get("valid") is not True:
                current={**deepcopy(self.inputs),"previous_complete_document":native,"revision_diagnostics":checked};continue
            compiled=self.wf.validate_script_document(native,views,self.inputs["production_preferences"])
            accepted,report,decision=self._focused(native,views,f"enacted_causality_{version:02}")
            if not accepted:
                current={**deepcopy(self.inputs),"previous_complete_document":native,
                    "revision_diagnostics":{"complete_same_source_enacted_review":decision,"native_enacted_review":report}};continue
            documents,contexts,legal,failed={},{},None,None
            for part in ("semantic","physical"):
                prepared=self.wf.prepare_full_review_part_request(self.inputs,self.profile,native,views,part)
                context=prepared["part_context_sha256"]
                if legal is not None and legal!=prepared["review_legal_context"]:raise base.Halt("halt_review_authority_changed")
                legal=prepared["review_legal_context"]
                doc,check,_=self.invoke(f"full_review_{part}_{version:02}",prepared,
                    lambda value,p=part,c=context:reviews.validate_part(value,p,compiled["script"],views["brief"],views["plan"],legal,
                        context_sha256=c,goal_contract=goal,opening_setup=setup,
                        prior_story_scope=self.inputs["production_preferences"].get("prior_story_scope")))
                documents[part],contexts[part]=doc,context
                if not self.audit_gate(check,part):failed=check;break
            if failed is not None:
                if failed.get("requires_new_goal_plan") or failed.get("new_scope_requires_new_goal_plan"):
                    raise base.Halt("halt_requires_new_complete_goal",native_part_reviews=documents,decision=failed,no_replanning_authorized=True)
                current={**deepcopy(self.inputs),"previous_complete_document":native,
                    "revision_diagnostics":{"complete_same_source_part_review":failed,"native_part_reviews":documents}};continue
            full=reviews.build_review_bundle(documents["semantic"],documents["physical"])
            check=reviews.validate_bundle(full,compiled["script"],views["brief"],views["plan"],legal,
                semantic_context_sha256=contexts["semantic"],physical_context_sha256=contexts["physical"],goal_contract=goal,opening_setup=setup,
                prior_story_scope=self.inputs["production_preferences"].get("prior_story_scope"))
            if not self.audit_gate(check,"full_bundle"):
                if check.get("requires_new_goal_plan") or check.get("new_scope_requires_new_goal_plan"):
                    raise base.Halt("halt_requires_new_complete_goal",native_review_bundle=full,decision=check,no_replanning_authorized=True)
                current={**deepcopy(self.inputs),"previous_complete_document":native,
                    "revision_diagnostics":{"complete_same_source_full_review_bundle":check,"native_review_bundle":full}};continue
            return {"native_goal":goal,"native_goal_audit":bundle,"native_opening_setup":setup,
                "native_source_state_audit":seed["source_report"],"source_state_decision":seed["source_decision"],
                "native_script":native,"derived_script":compiled["derived_script"],"compiled_script":compiled["script"],
                "source_descriptor":compiled["source_descriptor"],"native_full_review_bundle":full,"decision":check,
                "native_enacted_review":report,"enacted_review_decision":decision,"calibration":calibration,
                "rendered_script":self.wf.render_script(native,goal),"views":views}
        raise base.Halt("halt_live_content_repair_capacity",shared_body_calls_used=self.body_used)


class Session(prior.Session):
    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_derived_text_spend_anchor_v1").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
        accounting = anchor.get("current_text_scope_accounting", {})
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited") or accounting.get("limits") != PARENT_LIMITS
                or accounting.get("consumed") != PARENT_USED or accounting.get("remaining") != PARENT_REMAINING
                or accounting.get("calls_used") != 4 or accounting.get("calls_remaining") != 5
                or accounting.get("body_used") != 3 or accounting.get("body_limit") != 3):
            raise ValueError("known exhausted parent bodies and valid inherited source required")
        source_refs.creative_root(anchor)
        for key in ("inputs", "profile"):
            path = base._inside(anchor["current_"+key+"_path"])
            if sha(path) != anchor["current_"+key+"_file_sha256"] or digest(read(path)) != anchor["current_"+key+"_sha256"]:
                raise ValueError("current original authority changed")
        return anchor, checked

    def _workflow(self):
        adapter = self._reviews(read(self.root/"USER_SCOPE.json")) if (self.root/"USER_SCOPE.json").exists() else self.injected_review_adapter
        return importlib.import_module("scripts.creative_world_scene_replanned_workflow_v4").ReviewWorkflow(base.workflow, adapter)

    def source_material(self,wf):
        seed=super().source_material(wf);anchor=read(self.config.parent_anchor_path)
        receipt,native=references._ref_document(anchor["current_valid_body_receipt"])
        if receipt["status"]!="contract_valid":raise ValueError("original complete structurally valid counterexample required")
        inputs=read(anchor["current_inputs_path"])
        authored=wf.prepare_script_request(inputs,self.profile,seed["goal"],seed["audit_bundle"],opening_setup=seed["setup"],
            source_state_audit=seed["source_report"],source_state_prepared=seed["source_prepared"],**wf.origin_ids(inputs))
        wf.validate_script_document(native,authored["views"],inputs["production_preferences"])
        return {**seed,"calibration_native_script":native,"calibration_views":authored["views"]}

    def preview(self):
        anchor, checked = self._parent(); built = self._inputs(); self._profile_gate(); inputs = read(anchor["current_inputs_path"])
        if built["inputs"] != inputs or inputs != read(source_refs.creative_root(anchor)/"INPUTS.json") or self.profile != read(anchor["current_profile_path"]):
            raise ValueError("exact original current inputs/profile required")
        wf = self._workflow(); seed = self.source_material(wf)
        first = wf.prepare_enacted_causality_request(inputs,self.profile,seed["calibration_native_script"],seed["calibration_views"])
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

    def authorization_template(self, preview):
        value = super().authorization_template(preview)
        value.update(schema=VERSION+"/derived_authorization", stage_limits=deepcopy(LIMITS), total_new_calls_limit=TOTAL,
            complete_script_versions=BODY_VERSIONS, new_source_state_audit_limit=0, reuses_accepted_source_state=True,
            parent_scope_stage_limits=PARENT_LIMITS, parent_scope_stage_calls=PARENT_USED, parent_scope_remaining=PARENT_REMAINING,
            parent_scope_calls_used=4, parent_scope_calls_remaining=5, parent_unused_body_calls=0,
            previous_body_versions_spent=[12, 13, 14], old_complete_body_calls_used=14, old_complete_body_capacity=14,
            new_body_contract_scope=False, known_content_repair_scope=True, native_derived_script_identities_required=True, enacted_causality_calibration_required=True,
            calibration_native_script_sha256=read(self.config.parent_anchor_path)["current_valid_body_receipt"]["native_sha256"],
            calibration_expected_admission=False, calibration_expectation_is_model_input=False,
            new_authority="user autonomous known content repair: blind counterexample calibration then at most two whole bodies15-16, focused plus same-source full reviews; no source/goal/media")
        return value

    def _binding(self, parent):
        value = super()._binding(parent); value.update(schema=VERSION+"/successor_claim", native_derived_script_identities_required=True)
        return value

    def prepare(self):
        if self.root.exists() or self.claim.exists(): raise FileExistsError("existing root/grant cannot restart")
        preview = self.preview(); parent, _ = self._parent(); binding = self._binding(parent)
        if read(self.config.authorization_path) != self.authorization_template(preview): raise ValueError("exact new eleven-call authorization required")
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

    def _guard(self):
        freeze, scope = read(self.root/"PRODUCTION_FREEZE.json"), read(self.root/"USER_SCOPE.json")
        if (freeze.get("schema") != VERSION+"/freeze" or freeze.get("stage_limits") != LIMITS or freeze.get("total_new_calls_limit") != TOTAL
                or scope != self.authorization_template({"preparation_identity_sha256": scope.get("preparation_identity_sha256"),
                    "inherited": freeze["inherited"], "inputs_sha256": freeze["inputs_sha256"], "creative_source_root": scope.get("creative_source_root"),
                    "inputs": read(self.root/"INPUTS.json")})): raise ValueError("exact v8 calibrated-content eleven-call scope required")
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
                raise ValueError("original single-use v8 RUN differs")
        return True

    def runtime(self):
        freeze = read(self.root/"PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile, inherited_guard=self._guard,
            admission=self._admit, shared_lock=base.PROJECT/"data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def _replay(self, ledger, label=None, *, verify_validations=False):
        owner, rows = self, ledger["calls"]
        class Replay(Driver):
            def invoke(self, old_label, prepared, validator):
                current = old_label
                if self.position == len(rows):
                    if current != label: raise ValueError("native body/review order differs")
                    raise body_flow.NextRequest(prepared)
                row = rows[self.position]; self.position += 1; path = owner.root/row["receipt"]; receipt = read(path)
                if current != row["label"] or sha(path) != row["receipt_sha256"] or receipt["request"] != prepared["request"]: raise ValueError("original prerequisite differs")
                native, decision = native_proof.known_native(receipt), base._decision(receipt)
                if verify_validations and receipt["status"] == "contract_valid" and validator(native) != decision: raise ValueError("same-source validation changed")
                return native, decision, row
        replay = Replay(self, None, read(self.root/"INPUTS.json"), self._workflow()); replay.position = 0
        try: result = replay.flow()
        except body_flow.NextRequest as found:
            if label is None: raise ValueError("handoff native flow unfinished")
            return found.prepared
        if label is not None or replay.position != len(rows): raise ValueError("terminal flow or extra receipts")
        return result

    def _admit(self, label, request, ledger):
        self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"]) >= TOTAL or not re.fullmatch(r"complete_script_(?:15|16)|enacted_causality_calibration_14|enacted_causality_(?:15|16)|full_review_(?:semantic|physical)_(?:15|16)", label):
            raise ValueError("only blind calibration, bodies15-16 and their focused/full reviews are authorized")
        stage = "complete_script" if label.startswith("complete_script") else "full_review"
        if request.get("stage") != stage: raise ValueError("registered stage mapping differs")
        pending = self.pending_intent
        if not pending or pending["label"] != label or sha(pending["path"]) != pending["sha256"]: raise ValueError("original builder intent missing")
        intent = read(pending["path"])
        if (intent.get("schema") != VERSION+"/call_intent" or intent["prepared"]["request"] != request or intent["request_sha256"] != digest(request)
                or intent["ledger_prefix_sha256"] != digest(ledger["calls"]) or intent["inputs_sha256"] != digest(read(self.root/"INPUTS.json"))
                or self._replay(ledger, label)["request"] != request): raise ValueError("exact linked request cannot be rebuilt")
        base.clients.expected_wire_request(request); return True

    def state(self, runtime, status, **details):
        value = base.NativeSession.state(self, runtime, status, **details)
        value.update(schema=VERSION+"/state", flow_version=VERSION, new_stage_limits=deepcopy(LIMITS), text_ready_for_director=status=="text_ready_for_director",
            old_complete_body_calls_used=14, old_complete_body_capacity=14,
            previous_body_versions_spent=[12,13,14], reuses_accepted_source_state=True, enacted_causality_calibration_required=True,
            parent_scope_stage_calls=PARENT_USED, parent_scope_remaining=PARENT_REMAINING, no_replanning=True)
        if (self.root/"RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha(self.root/"RUN_CLAIM.json")
        write(self.root/"STATE.json", value); return value

    def _save_text(self, result, driver, runtime):
        paths = {"inputs": self.root/"INPUTS.json", "profile": Path(self.config.profile_path), "goal": self.root/"goal/NATIVE_GOAL.json",
            "goal_audit_bundle": self.root/"goal/NATIVE_GOAL_AUDIT_BUNDLE.json", "setup": self.root/"opening/NATIVE_OPENING_SETUP.json",
            "source_state_audit": self.root/"goal/NATIVE_SOURCE_STATE_AUDIT.json", "source_state_decision": self.root/"goal/SOURCE_STATE_DECISION.json",
            "raw_script": self.root/"scripts/NATIVE_SCRIPT.json", "derived_script": self.root/"scripts/DERIVED_CANONICAL_SCRIPT.json",
            "compiled_script": self.root/"scripts/COMPILED_SCRIPT.json", "source_descriptor": self.root/"scripts/SCRIPT_SOURCE_DESCRIPTOR.json",
            "enacted_review":self.root/"scripts/NATIVE_ENACTED_REVIEW.json","enacted_review_decision":self.root/"scripts/ENACTED_REVIEW_DECISION.json",
            "calibration":self.root/"scripts/REGISTERED_COUNTEREXAMPLE_RESULT.json",
            "full_review_bundle": self.root/"scripts/NATIVE_FULL_REVIEW_BUNDLE.json"}
        values = _values(result)
        for key, value in values.items(): write(paths[key], value, True)
        rendered = self.root/"scripts/FULL_SCRIPT.md"
        with rendered.open("x", encoding="utf-8", newline="\n") as stream: stream.write(result["rendered_script"])
        anchor = read(self.config.parent_anchor_path)
        handoff = {"schema": VERSION+"/text_handoff", "status": "text_ready_for_director", "source_root": str(self.root),
            "paths": {key:str(path.resolve()) for key,path in paths.items()}, "artifact_file_sha256": base._hashes([*paths.values(), rendered]),
            "native_identity": {key:digest(value) for key,value in values.items()}, "source_descriptor": result["source_descriptor"],
            "inherited_current_native_receipt_references": {key:deepcopy(anchor[key]) for key in REF_KEYS},
            "receipt_identities": [base._receipt_identity(self.root,row) for row in read(runtime.ledger)["calls"]], "decision": result["decision"],
            "source_state_decision": result["source_state_decision"], "freeze_sha256": sha(self.root/"PRODUCTION_FREEZE.json"),
            "run_claim_sha256": sha(self.root/"RUN_CLAIM.json"), "native_reports_unchanged": True,
            "human_quality_approved": False, "creative_quality_passed": False, "media_submitted": False, "old_budget_reset": False}
        write(self.root/"TEXT_HANDOFF.json", handoff, True)
        return self.state(runtime,"text_ready_for_director",text_handoff_sha256=digest(handoff),handoff_path=str(self.root/"TEXT_HANDOFF.json"))

    def run(self):
        if not (self.root/"PRODUCTION_FREEZE.json").is_file(): raise ValueError("separately prepared v8 root required")
        base.policy.new_claim(self.root/"RUN_CLAIM.json", {"schema":VERSION+"/run_claim","root":str(self.root),"pid":base.os.getpid(),
            "started_at":self.clock(),"automatic_restart":False,"freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json")})
        runtime = None
        try:
            runtime=self.runtime();self._guard();base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(runtime.ledger)["calls"]: raise ValueError("original nonempty RUN cannot restart")
            driver=Driver(self,runtime,read(self.root/"INPUTS.json"),self._workflow());return self._save_text(driver.flow(),driver,runtime)
        except (base.Halt,base.stages.OfflineStop) as stop:return self.state(runtime,stop.status,**stop.details)
        except Exception as exc:
            write(self.root/"EXECUTION_ERROR.json",{"type":type(exc).__name__,"message":str(exc),"automatic_restart":False},True)
            return self.state(runtime,"halt_execution_reconciliation",exception_type=type(exc).__name__,error=str(exc))


def _values(result):
    return {**prior._values(result), "enacted_review":result["native_enacted_review"], "enacted_review_decision":result["enacted_review_decision"], "calibration":result["calibration"]}


def verify_text_handoff(root):
    session=Session.open(root);runtime=session.runtime();session._guard();anchor,parent=session._parent()
    state,handoff,ledger=(read(session.root/(name+".json")) for name in ("STATE","TEXT_HANDOFF","CALL_LEDGER"))
    if (state.get("status")!="text_ready_for_director" or state.get("spend_verification_pending") is not False
            or handoff.get("schema")!=VERSION+"/text_handoff" or state.get("text_handoff_sha256")!=digest(handoff)
            or handoff.get("freeze_sha256")!=sha(session.root/"PRODUCTION_FREEZE.json")
            or not(handoff.get("run_claim_sha256")==state.get("run_claim_sha256")==sha(session.root/"RUN_CLAIM.json"))):raise ValueError("known original v8 handoff required")
    current=runtime.summary()
    if current!=state["spend"] or current["new_unknown_token_reservations"]!=0:raise ValueError("settled accounting differs")
    reader=base.evidence.Reader();receipts=[base.evidence.verify_original_receipt(session.root,row,ledger["source_manifest"],reader=reader) for row in ledger["calls"]]
    base.evidence._tasks(reader,session.root,ledger,receipts,session.config.grant_id)
    if handoff.get("receipt_identities")!=[base._receipt_identity(session.root,row) for row in ledger["calls"]]:raise ValueError("receipt/intent identities differ")
    for index,(row,receipt) in enumerate(zip(ledger["calls"],receipts)):
        intent=read(session.root/"call_intents"/(row["label"]+".json"))
        if (intent.get("schema")!=VERSION+"/call_intent" or intent["prepared"]["request"]!=receipt["request"]
                or intent["ledger_prefix_sha256"]!=digest(ledger["calls"][:index])):raise ValueError("original intent/prefix differs")
    result=session._replay(ledger,verify_validations=True);expected=_values(result)
    if handoff.get("inherited_current_native_receipt_references")!={key:anchor[key] for key in REF_KEYS}:raise ValueError("inherited accepted-source refs differ")
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
            "full_review_bundle_sha256":digest(expected["full_review_bundle"]),"source_state_audit_sha256":digest(expected["source_state_audit"]),"enacted_review_sha256":digest(expected["enacted_review"])},
        "source_descriptor":deepcopy(result["source_descriptor"]),"receipt_identities":deepcopy(handoff["receipt_identities"]),"spend":current,"inherited":inherited,
        "parent_identity":identity,"parent_identity_sha256":digest(identity),"source_files":files,"human_quality_approved":False,
        "creative_quality_passed":False,"authorizes_media_dispatch":False,"model_calls":0}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("action",choices=("preview","authorization","prepare","run","verify"));parser.add_argument("path")
    args=parser.parse_args()
    if args.action=="verify":value=verify_text_handoff(args.path)
    else:
        session=Session.open(args.path) if args.action=="run" else Session(read(args.path))
        value=session.authorization_template(session.preview()) if args.action=="authorization" else getattr(session,args.action)()
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
