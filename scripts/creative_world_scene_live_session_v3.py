"""Independent body04--06 contract repair; original planning and spend stay frozen.

Import/preview is pure. Only an explicitly prepared new nine-call scope can run.
The previous complete native script is feedback, never an adopted screenplay.
"""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v1 as base
from scripts import creative_world_scene_script_contract_v2 as contract

VERSION = "creative_world_scene_live_session/v3"
Config = base.Config
LIMITS = {"goal_plan": 0, "goal_audit": 0, "complete_script": 3, "full_review": 6}
TOTAL = 9
BODY_VERSIONS = [4, 5, 6]
OLD_CONSUMED = {"goal_plan": 3, "goal_audit": 7, "complete_script": 3, "full_review": 0}
read, write, digest, sha = base.read, base.write, base.digest, base.sha


def _ref_document(ref):
    path = base._inside(ref["path"])
    if sha(path) != ref["file_sha256"]: raise ValueError("original certified receipt changed")
    receipt = read(path)
    native = base.NativeSession.known(receipt, ref["label"], require_valid=False)
    if (receipt["ordinal"] != ref["ordinal"] or receipt["request_sha256"] != ref["request_sha256"]
            or receipt["status"] != ref["status"] or digest(native) != ref["native_sha256"]):
        raise ValueError("certified original native reference differs")
    return receipt, native


def material(anchor):
    """Only original receipt objects, never a reconstructed or corrected script."""
    _, goal = _ref_document(anchor["native_goal_receipt"])
    reports = {kind: _ref_document(anchor["native_goal_audit_receipts"][kind])[1] for kind in base.workflow.AUDITS}
    _, setup = _ref_document(anchor["native_opening_setup_receipt"])
    last_receipt, rejected = _ref_document(anchor["rejected_body_receipts"][-1])
    diagnostic = contract.diagnose(rejected, goal)
    if diagnostic["valid"]: raise ValueError("original seed must retain an explicit complete structural failure")
    return {"goal": goal, "audit_bundle": base.workflow.build_goal_audit_bundle(*(reports[k] for k in base.workflow.AUDITS)),
        "setup": setup, "rejected": rejected, "diagnostic": diagnostic, "rejected_receipt": last_receipt}


class ReviewWorkflow(base.ReviewWorkflow):
    def __init__(self, workflow, adapter, seed):
        super().__init__(workflow, adapter)
        self.seed = deepcopy(seed)

    def prepare_script_request(self, inputs, *args, **kwargs):
        current = deepcopy(inputs)
        if "previous_complete_document" not in current and "revision_diagnostics" not in current:
            current.update(previous_complete_document=deepcopy(self.seed["rejected"]),
                revision_diagnostics=deepcopy(self.seed["diagnostic"]))
        result = super().prepare_script_request(current, *args, **kwargs)
        original_schema = result["request"]["structured_schema"]
        result["request"]["structured_schema"] = contract.refine_schema(original_schema)
        result["request"]["messages"][0]["content"] += "\n" + contract.RELATION_RULE
        result["manifest"].update(script_contract_repair_version=contract.VERSION,
            original_writer_schema_sha256=digest(original_schema), original_native_seed_sha256=digest(self.seed["rejected"]))
        return self.base._mark(result, current)

    def validate_script_document(self, native, views, production_preferences=None):
        contract.validate(native, views["goal"])
        return self.base.validate_script_document(native, views, production_preferences)

    def prepare_full_review_part_request(self, inputs, profile, native, views, part):
        # The same complete native must pass the new contract before either review.
        self.validate_script_document(native, views, inputs["production_preferences"])
        return super().prepare_full_review_part_request(inputs, profile, native, views, part)


class Runtime(base.Runtime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, stage_limits=base.LIMITS, **kwargs)
        self.stage_limits = deepcopy(LIMITS)

    def _policy(self):
        result = super()._policy()
        result.update(schema=VERSION + "/runtime_policy", total_new_calls_limit=TOTAL,
            original_scope_stage_limits=deepcopy(base.LIMITS), previous_scope_stage_calls=deepcopy(OLD_CONSUMED),
            body_versions_available=BODY_VERSIONS, old_body_capacity_exhausted=True,
            new_body_scope_is_separate=True, no_replanning=True, whole_plan_limit=0, opening_setup_limit=0)
        return result


def _label(label):
    match = re.fullmatch(r"(complete_script|full_review_semantic|full_review_physical)_0([123])", label)
    if not match: raise ValueError("only inherited body-driver labels may be mapped")
    return match[1] + f"_{int(match[2])+3:02}"


class Driver(base.LiveDriver):
    """Reuse the complete native-body loop, changing only its declared identities."""
    def invoke(self, label, prepared, validator):
        label = _label(label)
        session, rt = self.session, self.runtime
        ledger = read(rt.ledger)
        if any(row["label"] == label for row in ledger["calls"]): raise base.Halt("halt_duplicate_live_stage", label=label)
        intent = {"schema": VERSION + "/call_intent", "label": label, "prepared": deepcopy(prepared),
            "request_sha256": digest(prepared["request"]), "ledger_prefix_sha256": digest(ledger["calls"]),
            "prerequisite_receipts": [{"ordinal": row["ordinal"], "label": row["label"], "receipt": row["receipt"],
                "sha256": row["receipt_sha256"]} for row in ledger["calls"]],
            "inputs_sha256": digest(self.inputs), "automatic_retry": False}
        path = session.root / "call_intents" / (label + ".json"); write(path, intent, True)
        session.pending_intent = {"path": str(path), "sha256": sha(path), "label": label}
        receipt = base.policy.dispatch_claimed(rt, label, prepared, validator, root=session.root,
            grant_id=session.config.grant_id, stage_limits=LIMITS,
            current_round_root=session.config.counter_root, current_round_key=session.config.round_key, guard=session._guard)
        native = base.NativeSession.known(receipt, label, require_valid=False)
        decision = base._decision(receipt)
        self.calls.append({"label": label, "ordinal": receipt["ordinal"], "receipt": f"call_{receipt['ordinal']:03}_{label}.json",
            "prepared": deepcopy(prepared), "status": receipt["status"], "native_output": deepcopy(native), "validation": deepcopy(decision)})
        return native, decision, self.calls[-1]


class _NextRequest(Exception):
    def __init__(self, prepared): self.prepared = prepared


class Session(base.Session):
    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_spend_anchor_v3").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited") or checked.get("body_capacity_exhausted") is not True
                or anchor.get("consumed_stage_calls") != OLD_CONSUMED or anchor.get("consumed_calls") != sum(OLD_CONSUMED.values())
                or anchor.get("complete_scripts_used") != 3 or anchor.get("remaining_complete_scripts") != 0):
            raise ValueError("settled original body3/3 certificate required; it does not grant new calls")
        refs = anchor["rejected_body_receipts"]
        if ([r["label"] for r in refs] != [f"complete_script_{i:02}" for i in (1, 2, 3)]
                or any(r["status"] != "contract_rejected" for r in refs)):
            raise ValueError("all three original body failures must remain spent")
        return anchor, checked

    def _workflow(self, inputs=None, anchor=None):
        if anchor is None: anchor = read(self.config.parent_anchor_path)
        return ReviewWorkflow(base.workflow, self._reviews(read(self.root / "USER_SCOPE.json")), material(anchor))

    def preview(self):
        anchor, checked = self._parent(); built = self._inputs(); self._profile_gate()
        original = read(Path(anchor["root"]) / "INPUTS.json")
        prior_config = read(Path(anchor["root"]) / "SESSION_CONFIG.json")
        if built["inputs"] != original or self.profile != read(prior_config["profile_path"]):
            raise ValueError("body continuation must retain exact original INPUTS and model profile")
        seed = material(anchor)
        # Writer preparation does not invoke the full-review adapter; no fabricated
        # USER_SCOPE or prepared production directory is necessary for preview.
        wf = ReviewWorkflow(base.workflow, None, seed)
        first = wf.prepare_script_request(original, self.profile, seed["goal"], seed["audit_bundle"],
            opening_setup=seed["setup"], **wf.origin_ids(original))
        base.clients.expected_wire_request(first["request"])
        files = base._hashes([*built["source_files"], self.config.parent_anchor_path, self.config.profile_path,
            self.config.preferences_path, self.config.user_goals_path, *self.config.extra_source_files, *self.code_files()])
        for path, item in checked.get("source_files", {}).items():
            expected = item.get("sha256") if type(item) is dict else item
            if sha(base._inside(path)) != expected: raise ValueError("certified original parent changed")
            files[str(base._inside(path))] = expected
        value = {"schema": VERSION + "/preview", "root": str(self.root), "grant_id": self.config.grant_id,
            "inputs": original, "input_evidence": built["evidence"], "first_request": first,
            "inputs_sha256": digest(original), "profile_sha256": sha(self.config.profile_path),
            "parent_anchor_sha256": digest(anchor), "inherited": checked["inherited"],
            "parent_root": anchor["root"], "parent_identity": anchor["parent_identity"], "source_files": files,
            "stage_limits": deepcopy(LIMITS), "total_new_calls_limit": TOTAL, "first_request_label": "complete_script_04",
            "old_scope_stage_calls": deepcopy(OLD_CONSUMED), "original_scope_stage_limits": deepcopy(base.LIMITS),
            "native_seed_diagnostic": seed["diagnostic"], "body_versions_available": BODY_VERSIONS,
            "provider_calls": 0, "media_calls": 0, "old_budget_reset": False}
        value["preparation_identity_sha256"] = digest({k: value[k] for k in (
            "root", "grant_id", "inputs_sha256", "profile_sha256", "parent_anchor_sha256", "inherited", "source_files", "first_request")})
        return value

    def authorization_template(self, preview):
        result = super().authorization_template(preview)
        result.update(schema=VERSION + "/derived_authorization", stage_limits=deepcopy(LIMITS), total_new_calls_limit=TOTAL,
            old_scope_stage_calls=deepcopy(OLD_CONSUMED), original_scope_stage_limits=deepcopy(base.LIMITS),
            original_total_call_limit=base.TOTAL, old_scope_calls_used=13, body_versions_available=BODY_VERSIONS,
            old_body_calls_used=3, old_body_capacity=3, original_scope_root=preview["parent_root"],
            new_body_scope_is_separate=True, no_replanning=True, old_scope_restarted=False,
            whole_plan_limit=0, opening_setup_limit=0,
            new_authority="user broad MiniMax continuation/autonomous repair and actual interface test; independent bounded body contract repair scope")
        return result

    def _binding(self, parent):
        result = super()._binding(parent)
        result.update(schema=VERSION + "/successor_claim", separate_body_scope=True, old_body_calls_used=3)
        return result

    def _guard(self):
        super()._guard()
        scope = read(self.root / "USER_SCOPE.json"); anchor = read(self.config.parent_anchor_path)
        if (scope.get("schema") != VERSION + "/derived_authorization" or scope.get("stage_limits") != LIMITS
                or any(type(v) is not int for v in scope["stage_limits"].values())
                or scope.get("total_new_calls_limit") != TOTAL or type(scope.get("total_new_calls_limit")) is not int
                or scope.get("old_scope_stage_calls") != OLD_CONSUMED
                or scope.get("original_scope_stage_limits") != base.LIMITS
                or scope.get("old_scope_calls_used") != 13 or scope.get("old_body_calls_used") != 3 or scope.get("old_body_capacity") != 3
                or scope.get("body_versions_available") != BODY_VERSIONS or scope.get("no_replanning") is not True
                or scope.get("whole_plan_limit") != 0 or scope.get("opening_setup_limit") != 0
                or scope.get("new_body_scope_is_separate") is not True or scope.get("old_scope_restarted") is not False
                or scope.get("parent_anchor_sha256") != self.config.parent_anchor_sha256 or digest(anchor) != self.config.parent_anchor_sha256
                or scope.get("original_scope_root") != anchor["root"] or scope.get("inherited") != anchor["inherited"]):
            raise ValueError("frozen independent nine-call scope or old spent body scope differs")
        if read(self.root / "INPUTS.json") != read(Path(anchor["root"]) / "INPUTS.json"):
            raise ValueError("frozen original INPUTS changed")
        run_path = self.root / "RUN_CLAIM.json"
        if run_path.exists():
            run = read(run_path)
            if (run.get("schema") != VERSION + "/run_claim" or run.get("root") != str(self.root)
                    or type(run.get("pid")) is not int or run["pid"] <= 0 or run.get("automatic_restart") is not False
                    or run.get("freeze_sha256") != sha(self.root / "PRODUCTION_FREEZE.json")):
                raise ValueError("original single-use RUN differs")
        return True

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            inherited_guard=self._guard, admission=self._admit,
            shared_lock=base.PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def _rebuild(self, label, ledger):
        anchor = read(self.config.parent_anchor_path); seed = material(anchor)
        owner = self; rows = ledger["calls"]
        class Replay(base.LiveDriver):
            def invoke(self, old_label, prepared, validator):
                current = _label(old_label)
                if self.position == len(rows):
                    if current != label: raise ValueError("stage ordering differs from original body/review loop")
                    raise _NextRequest(prepared)
                row = rows[self.position]; self.position += 1
                receipt = read(owner.root / row["receipt"])
                if current != row["label"] or sha(owner.root / row["receipt"]) != row["receipt_sha256"]:
                    raise ValueError("ordered native prerequisite differs")
                native = base.NativeSession.known(receipt, current, require_valid=False)
                if prepared["request"] != receipt["request"]: raise ValueError("original native request cannot be rebuilt")
                return native, base._decision(receipt), row
        wf = self._workflow(anchor=anchor)
        replay = Replay(self, None, read(self.root / "INPUTS.json"), wf); replay.position = 0
        try: replay._body(seed["goal"], seed["audit_bundle"], seed["setup"])
        except _NextRequest as found: return found.prepared
        raise ValueError("body loop is already terminal; no further request is allowed")

    def _admit(self, label, request, ledger):
        self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"]) >= TOTAL or not re.fullmatch(r"complete_script_0[456]|full_review_(?:semantic|physical)_0[456]", label):
            raise ValueError("independent body04--06 scope exhausted/unregistered label")
        stage = "complete_script" if label.startswith("complete_script") else "full_review"
        if request.get("stage") != stage: raise ValueError("native stage mapping differs")
        pending = self.pending_intent
        if not pending or pending["label"] != label or sha(pending["path"]) != pending["sha256"]:
            raise ValueError("original trusted builder intent missing")
        intent = read(pending["path"])
        if (intent.get("schema") != VERSION + "/call_intent" or intent["prepared"]["request"] != request
                or intent["request_sha256"] != digest(request) or intent["ledger_prefix_sha256"] != digest(ledger["calls"])
                or intent["inputs_sha256"] != digest(read(self.root / "INPUTS.json"))):
            raise ValueError("actual request/prerequisite sequence differs")
        if self._rebuild(label, ledger)["request"] != request: raise ValueError("actual source-native request builder differs")
        base.clients.expected_wire_request(request)
        return True

    def state(self, rt, status, **details):
        value = super().state(rt, status, **details)
        value.update(schema=VERSION + "/state", flow_version=VERSION, new_body_scope_is_separate=True,
            old_scope_stage_calls=deepcopy(OLD_CONSUMED), new_stage_limits=deepcopy(LIMITS), body_versions_available=BODY_VERSIONS)
        write(self.root / "STATE.json", value); return value

    def _save_text(self, result, driver, rt):
        paths = {"inputs": self.root / "INPUTS.json", "profile": Path(self.config.profile_path),
            "goal": self.root / "goal/NATIVE_GOAL.json", "goal_audit_bundle": self.root / "goal/NATIVE_GOAL_AUDIT_BUNDLE.json",
            "setup": self.root / "opening/NATIVE_OPENING_SETUP.json", "raw_script": self.root / "scripts/NATIVE_SCRIPT.json",
            "compiled_script": self.root / "scripts/COMPILED_SCRIPT.json", "full_review_bundle": self.root / "scripts/NATIVE_FULL_REVIEW_BUNDLE.json"}
        values = {"goal":result["native_goal"], "goal_audit_bundle":result["native_goal_audit"], "setup":result["native_opening_setup"],
            "raw_script":result["native_script"], "compiled_script":result["compiled_script"], "full_review_bundle":result["native_full_review_bundle"]}
        for key,value in values.items(): write(paths[key], value, True)
        (self.root / "scripts/FULL_SCRIPT.md").write_text(result["rendered_script"], encoding="utf-8")
        anchor = read(self.config.parent_anchor_path)
        handoff = {"schema":VERSION+"/text_handoff", "status":"text_ready_for_director", "source_root":str(self.root),
            "paths":{k:str(v.resolve()) for k,v in paths.items()}, "artifact_file_sha256":base._hashes(paths.values()),
            "native_identity":{k:digest(v) for k,v in values.items()},
            "receipt_identities":[base._receipt_identity(self.root,row) for row in read(rt.ledger)["calls"]],
            "decision":result["decision"], "freeze_sha256":sha(self.root/"PRODUCTION_FREEZE.json"),
            "run_claim_sha256":sha(self.root/"RUN_CLAIM.json"),
            "native_reports_unchanged":True, "text_only_machine_admission":True,"human_quality_approved":False,
            "creative_quality_passed":False,"media_submitted":False,"old_director_capacity":base.DIRECTOR,
            "old_budget_reset":False,"inherited_native_receipt_references":{
                key:deepcopy(anchor[key]) for key in ("native_goal_receipt","native_goal_audit_receipts","native_opening_setup_receipt")}}
        write(self.root / "TEXT_HANDOFF.json", handoff, True)
        return self.state(rt, "text_ready_for_director", text_handoff_sha256=digest(handoff), handoff_path=str(self.root / "TEXT_HANDOFF.json"))

    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file(): raise ValueError("separately prepared root required")
        base.policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "pid": base.os.getpid(), "started_at": self.clock(), "automatic_restart": False,
            "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json")})
        rt = None
        try:
            rt = self.runtime(); self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]: raise ValueError("nonempty original RUN cannot restart")
            seed = material(read(self.config.parent_anchor_path)); inputs = read(self.root / "INPUTS.json")
            driver = Driver(self, rt, inputs, self._workflow())
            return self._save_text(driver._body(seed["goal"], seed["audit_bundle"], seed["setup"]), driver, rt)
        except (base.Halt, base.stages.OfflineStop) as stop:
            return self.state(rt, stop.status.replace("halt_mock_", "halt_live_"), **stop.details)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_restart": False}, True)
            return self.state(rt, "halt_execution_reconciliation", exception_type=type(exc).__name__, error=str(exc))


def verify_text_handoff(root):
    """Actual parent and current SDK/SQL proof; no inherited acceptance flags."""
    session = Session.open(root); rt = session.runtime(); session._guard()
    anchor, parent_checked = session._parent()
    seed = material(anchor)
    state, handoff, ledger = (read(session.root / (n + ".json")) for n in ("STATE", "TEXT_HANDOFF", "CALL_LEDGER"))
    if (state.get("status") != "text_ready_for_director" or state.get("spend_verification_pending") is not False
            or state.get("text_handoff_sha256") != digest(handoff) or handoff.get("schema") != VERSION + "/text_handoff"
            or handoff.get("freeze_sha256") != sha(session.root / "PRODUCTION_FREEZE.json")
            or not (handoff.get("run_claim_sha256") == state.get("run_claim_sha256") == sha(session.root / "RUN_CLAIM.json"))):
        raise ValueError("original known text-ready state/handoff required")
    current = rt.summary()
    if current != state["spend"] or current["new_unknown_token_reservations"] != 0: raise ValueError("settled text spend differs")
    reader = base.evidence.Reader()
    receipts = [base.evidence.verify_original_receipt(session.root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    base.evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    if handoff["receipt_identities"] != [base._receipt_identity(session.root, row) for row in ledger["calls"]]:
        raise ValueError("original current receipt/intent identities differ")
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = read(session.root / "call_intents" / (row["label"] + ".json"))
        if (intent["prepared"]["request"] != receipt["request"] or intent["ledger_prefix_sha256"] != digest(ledger["calls"][:index])
                or session._rebuild(row["label"], {**ledger, "calls": ledger["calls"][:index]})["request"] != receipt["request"]):
            raise ValueError("original request/native prerequisite builder differs")
    expected_refs = {k: anchor[k] for k in ("native_goal_receipt", "native_goal_audit_receipts", "native_opening_setup_receipt")}
    if handoff.get("inherited_native_receipt_references") != expected_refs: raise ValueError("inherited original native refs differ")
    for path, expected in handoff["artifact_file_sha256"].items(): reader.verify(base._inside(path), expected)
    files = {k: read(base._inside(p)) for k, p in handoff["paths"].items()}
    if files["inputs"] != read(session.root / "INPUTS.json") or files["profile"] != session.profile:
        raise ValueError("handoff authority inputs/profile differ")
    for key in ("goal", "goal_audit_bundle", "setup"):
        if files[key] != seed[{"goal":"goal", "goal_audit_bundle":"audit_bundle", "setup":"setup"}[key]]:
            raise ValueError("inherited accepted native artifact differs: " + key)
    values = {k:files[k] for k in ("goal", "goal_audit_bundle", "setup", "raw_script", "compiled_script", "full_review_bundle")}
    if handoff["native_identity"] != {k:digest(v) for k,v in values.items()}: raise ValueError("complete artifact identity differs")
    native_reports = [files["full_review_bundle"]["native_"+part+"_review"] for part in ("semantic", "physical")]
    for native in [files["raw_script"], *native_reports]:
        if not any(r.get("output") == native and r.get("status") == "contract_valid" for r in receipts):
            raise ValueError("new body/review is not an actual complete valid original result")
    wf = session._workflow(anchor=anchor)
    base._require_accepted(wf.validate_goal_audit(files["goal_audit_bundle"], files["goal"], inputs=files["inputs"]), "inherited_goal")
    views = wf.compile_native_views(files["goal"], files["setup"], **wf.origin_ids(files["inputs"]))
    compiled = wf.validate_script_document(files["raw_script"], views, files["inputs"]["production_preferences"])["script"]
    if compiled != files["compiled_script"]: raise ValueError("compiled body differs from actual native")
    parts = {part:wf.prepare_full_review_part_request(files["inputs"], files["profile"], files["raw_script"], views, part) for part in ("semantic", "physical")}
    checked = wf.full_reviews().validate_bundle(files["full_review_bundle"], compiled, views["brief"], views["plan"], parts["semantic"]["review_legal_context"],
        semantic_context_sha256=parts["semantic"]["part_context_sha256"], physical_context_sha256=parts["physical"]["part_context_sha256"],
        goal_contract=files["goal"], opening_setup=files["setup"], prior_story_scope=files["inputs"]["production_preferences"].get("prior_story_scope"))
    base._require_accepted(checked, "full")
    if checked != handoff["decision"]: raise ValueError("same-source recomputed decision differs")
    parent_identity = {"root":str(session.root), "terminal_state_sha256":sha(session.root/"STATE.json"),
        "native_ledger_sha256":sha(session.root/"CALL_LEDGER.json"), "production_freeze_sha256":sha(session.root/"PRODUCTION_FREEZE.json"),
        "end_ordinal":current["effective_calls_started"]}
    inherited = {"calls_started":current["effective_calls_started"], "reported_tokens":current["effective_reported_tokens"],
        "calls_with_known_usage":current["effective_calls_with_known_usage"], "pending_ordinals":deepcopy(current["historical_pending_ordinals"]),
        "unknown_token_reservations":current["unknown_token_reservations"]}
    source_files = {**read(session.root/"PRODUCTION_FREEZE.json")["files"],
        **{p:(v.get("sha256") if type(v) is dict else v) for p,v in parent_checked["source_files"].items()},
        **{p:v["sha256"] for p,v in reader.files.items()},
        **base._hashes(session.root/(n+".json") for n in ("STATE","TEXT_HANDOFF","CALL_LEDGER","PRODUCTION_FREEZE","RUN_CLAIM"))}
    return {"schema":VERSION+"/verified_text_handoff", "valid":True,"accepted":True,"status":"text_ready_for_director",
        "root":str(session.root),"source_root":str(session.root),"handoff_path":str(session.root/"TEXT_HANDOFF.json"),
        "handoff_sha256":sha(session.root/"TEXT_HANDOFF.json"),"paths":deepcopy(handoff["paths"]),
        "identity":{"native_goal_sha256":digest(files["goal"]),"native_script_sha256":digest(files["raw_script"]),
            "compiled_script_sha256":digest(compiled),"native_setup_sha256":digest(files["setup"]),
            "goal_audit_bundle_sha256":digest(files["goal_audit_bundle"]),"full_review_bundle_sha256":digest(files["full_review_bundle"])},
        "receipt_identities":deepcopy(handoff["receipt_identities"]),"spend":current,"inherited":inherited,
        "parent_identity":parent_identity,"parent_identity_sha256":digest(parent_identity),"source_files":source_files,
        "human_quality_approved":False,"creative_quality_passed":False,"old_director_capacity":base.DIRECTOR,
        "authorizes_media_dispatch":False,"model_calls":0}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization", "prepare", "run", "verify")); parser.add_argument("path")
    args = parser.parse_args()
    if args.action == "verify": result = verify_text_handoff(args.path)
    else:
        session = Session.open(args.path) if args.action == "run" else Session(read(args.path))
        result = session.authorization_template(session.preview()) if args.action == "authorization" else getattr(session,args.action)()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
