"""Independent settled644 continuation. No old RUN, budget or native is edited."""
from copy import deepcopy
from dataclasses import asdict
import importlib
from pathlib import Path
import re

from scripts import creative_world_scene_live_session_v1 as base

VERSION = "creative_world_scene_live_session/v2"
Config = base.Config
ORIGINAL_LIMITS = deepcopy(base.LIMITS)
CONSUMED = {"goal_plan": 1, "goal_audit": 3, "complete_script": 0, "full_review": 0}
REMAINING = {key: value - CONSUMED[key] for key, value in ORIGINAL_LIMITS.items()}
TOTAL_REMAINING = sum(REMAINING.values())
read, write, digest, sha = base.read, base.write, base.digest, base.sha

workflow, ReviewWorkflow, evidence = base.workflow, base.ReviewWorkflow, base.evidence
_inside, _hashes, _receipt_identity = base._inside, base._hashes, base._receipt_identity
_require_accepted, DIRECTOR = base._require_accepted, base.DIRECTOR


def planning_feedback(goal, reports, decisions, failed_kind):
    """One complete native failed row representation, no compiled citations."""
    native, checked = reports[failed_kind], decisions[failed_kind]
    if (native.get("goal_sha256", digest(goal)) != digest(goal)
            or checked.get("native_goal_sha256", digest(goal)) != digest(goal)):
        raise ValueError("native failed review belongs to another complete goal")
    if (checked.get("valid") is not True or checked.get("accepted") is not False
            or checked.get("uncertainties") != [] or not checked.get("findings")):
        raise ValueError("only known complete explicit native content failure can revise planning")
    rows = {}
    def visit(value, path):
        if type(value) is dict:
            if value.get("status") == "fail":
                rows[path] = deepcopy(value)
            else:
                for key, child in value.items(): visit(child, path + "." + key if path else key)
        elif type(value) is list:
            for i, child in enumerate(value): visit(child, path + "." + str(i))
    visit(native, "")
    catalog = base.workflow.legacy.commitment_audit.build_evidence_catalog(goal)
    strings = set()
    def values(value):
        if isinstance(value, str): strings.add(value)
        elif type(value) is dict:
            for child in value.values(): values(child)
        elif type(value) is list:
            for child in value: values(child)
    values(rows or native)
    references = {ref: {"document_path": item["document_path"]}
        for ref, item in catalog.items() if ref in strings}
    feedback = {"schema": VERSION + "/native_planning_failure_feedback", "audit_kind": failed_kind,
        "native_goal_sha256": digest(goal), "complete_native_report_sha256": digest(native),
        "complete_derived_decision_sha256": digest(checked),
        "original_report_schema": native.get("schema"), "original_audit_context_sha256": native.get("audit_context_sha256"),
        "valid": True, "accepted": False, "uncertainties": [],
        "source_directory": references, "source_directory_role": "exact paths into previous_complete_document; original text is there once",
        "full_native_report_remains_in_original_receipt": True, "native_rows_rewritten": False,
        "decision_role": "fallible model critique; current user and legal sources remain authoritative; submit a complete new native goal"}
    feedback["previous_goal_passed_audit_identities"] = {
        kind: {"native_report_sha256": digest(report), "original_schema": report.get("schema"),
               "original_decision_sha256": digest(decisions[kind]), "valid": True, "accepted": True}
        for kind, report in reports.items() if kind != failed_kind
        and decisions[kind].get("valid") is True and decisions[kind].get("accepted") is True}
    if rows: feedback["native_failed_rows"] = rows
    else: feedback["complete_failed_native_report"] = deepcopy(native)
    return feedback


class Runtime(base.Runtime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, stage_limits=ORIGINAL_LIMITS, **kwargs)
        self.stage_limits = deepcopy(REMAINING)
    def _policy(self):
        result = super()._policy()
        result.update(schema=VERSION + "/runtime_policy", total_new_calls_limit=TOTAL_REMAINING,
            original_scope_stage_limits=ORIGINAL_LIMITS, previous_scope_stage_calls=CONSUMED,
            original_total_call_limit=base.TOTAL, planning_versions_available=[2, 3])
        return result


class Driver(base.LiveDriver):
    def invoke(self, label, prepared, validator):
        session, rt = self.session, self.runtime
        ledger = read(rt.ledger)
        if any(row["label"] == label for row in ledger["calls"]): raise base.Halt("halt_duplicate_live_stage", label=label)
        intent = {"schema": VERSION + "/call_intent", "label": label, "prepared": deepcopy(prepared),
            "request_sha256": digest(prepared["request"]), "ledger_prefix_sha256": digest(ledger["calls"]),
            "prerequisite_receipts": [{"ordinal": row["ordinal"], "label": row["label"],
                "receipt": row["receipt"], "sha256": row["receipt_sha256"]} for row in ledger["calls"]],
            "inputs_sha256": digest(self.inputs), "automatic_retry": False}
        path = session.root / "call_intents" / (label + ".json"); write(path, intent, True)
        session.pending_intent = {"path": str(path), "sha256": sha(path), "label": label}
        receipt = base.policy.dispatch_claimed(rt, label, prepared, validator, root=session.root,
            grant_id=session.config.grant_id, stage_limits=REMAINING,
            current_round_root=session.config.counter_root, current_round_key=session.config.round_key, guard=session._guard)
        native = base.NativeSession.known(receipt, label, require_valid=False)
        checked = base._decision(receipt)
        row = {"label": label, "receipt": f"call_{receipt['ordinal']:03}_{label}.json", "ordinal": receipt["ordinal"],
            "prepared": deepcopy(prepared), "status": receipt["status"], "request_sha256": receipt["request_sha256"],
            "provider_result_is_actual_receipt": True, "native_output": deepcopy(native), "validation": deepcopy(checked)}
        self.calls.append(row)
        return native, checked, row

    def _planning(self):
        wf = self.wf
        current = {**deepcopy(self.inputs), **self.session.seed_feedback()}
        for version in (2, 3):
            goal, decision, _ = self.invoke(f"whole_plan_{version:02}", wf.prepare_goal_request(current, self.profile),
                lambda value: {"valid": True, "native_goal_sha256": wf.digest(wf.validate_goal_document(value, inputs=self.inputs))})
            if not decision["valid"]:
                current = {**deepcopy(self.inputs), "previous_complete_document": goal,
                    "revision_diagnostics": {"valid": False, "findings": deepcopy(decision.get("findings", [])),
                        "complete_derived_decision_sha256": digest(decision)}}
                continue
            reports, decisions, failed = {}, {}, False
            for kind in wf.AUDITS:
                if kind == "scope": request = wf.prepare_goal_scope_request(self.inputs, self.profile, goal)
                elif kind == "source": request = wf.prepare_goal_scoped_source_request(self.inputs, self.profile, goal, reports["scope"])
                else: request = getattr(wf, "prepare_goal_" + kind + "_audit_request")(self.inputs, self.profile, goal)
                context = request.get("scope_context_sha256") if kind == "scope" else request["audit_context_sha256"]
                kwargs = {"context_sha256": context, "inputs": self.inputs}
                if kind == "source": kwargs.update(native_scope=reports["scope"], authority_context=request["source_authority_context"])
                validator = wf.validate_goal_scope if kind == "scope" else getattr(wf, "validate_goal_" + kind + "_audit")
                native, checked, _ = self.invoke(f"{kind}_audit_{version:02}", request,
                    lambda value, fn=validator, args=kwargs: fn(value, goal, **args))
                reports[kind], decisions[kind] = native, checked
                if not self.audit_gate(checked, kind):
                    current = {**deepcopy(self.inputs), "previous_complete_document": goal,
                        "revision_diagnostics": planning_feedback(goal, reports, decisions, kind)}
                    failed = True; break
            if failed: continue
            bundle = wf.build_goal_audit_bundle(*(reports[key] for key in wf.AUDITS))
            if not self.audit_gate(wf.validate_goal_audit(bundle, goal, inputs=self.inputs), "planning_bundle"):
                raise base.stages.OfflineStop("halt_planning_bundle_rejected")
            return goal, bundle
        raise base.stages.OfflineStop("halt_live_original_plan_capacity_exhausted")


class Session(base.Session):
    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_spend_anchor_v2").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited") or anchor.get("parent_identity", {}).get("end_ordinal") != 644):
            raise ValueError("settled644 original source certificate required")
        old = Path(anchor["root"]); ledger = read(old / "CALL_LEDGER.json")
        expected = ["whole_plan_01", "scope_audit_01", "source_audit_01", "commitment_audit_01"]
        if [row["label"] for row in ledger["calls"]] != expected:
            raise ValueError("original four-call planning predecessor differs")
        if any(row["ordinal"] != 641 + i for i, row in enumerate(ledger["calls"])):
            raise ValueError("original scope ordinal predecessor differs")
        counts = dict.fromkeys(ORIGINAL_LIMITS, 0)
        for row in ledger["calls"]:
            receipt = read(old / row["receipt"])
            if sha(old / row["receipt"]) != row["receipt_sha256"]: raise ValueError("original predecessor receipt changed")
            base.NativeSession.known(receipt, row["label"], require_valid=False)
            counts[receipt["request"]["stage"]] += 1
        if counts != CONSUMED or anchor["inherited"]["calls_started"] != 644:
            raise ValueError("original consumed scope cannot be reset")
        return anchor, checked

    def seed_feedback(self):
        anchor, _ = self._parent(); root = Path(anchor["root"])
        goal = read(root / "call_641_whole_plan_01.json")["output"]
        receipt = read(root / "call_644_commitment_audit_01.json")
        inputs = read(root / "INPUTS.json")
        base.workflow.validate_goal_document(goal, inputs=inputs)
        prepared = base.workflow.prepare_goal_commitment_audit_request(inputs, self.profile, goal)
        if prepared["request"] != receipt["request"]: raise ValueError("original failed commitment request cannot drift")
        checked = base.workflow.validate_goal_commitment_audit(receipt["output"], goal,
            context_sha256=prepared["audit_context_sha256"], inputs=inputs)
        if checked != receipt["validation"]: raise ValueError("original known failed commitment decision differs")
        reports, decisions = {"commitment": receipt["output"]}, {"commitment": checked}
        for kind, ordinal in (("scope", 642), ("source", 643)):
            prior = read(root / f"call_{ordinal}_{kind}_audit_01.json")
            reports[kind], decisions[kind] = prior["output"], prior["validation"]
            if decisions[kind].get("valid") is not True or decisions[kind].get("accepted") is not True:
                raise ValueError("original preceding audit is not a known pass")
        return {"previous_complete_document": deepcopy(goal),
            "revision_diagnostics": planning_feedback(goal, reports, decisions, "commitment")}

    def preview(self):
        parent, checked = self._parent(); built = self._inputs(); self._profile_gate()
        original = read(Path(parent["root"]) / "INPUTS.json")
        if built["inputs"] != original: raise ValueError("continuation must retain exact original INPUTS")
        old_config = read(Path(parent["root"]) / "SESSION_CONFIG.json")
        if self.profile != read(old_config["profile_path"]): raise ValueError("original model profile changed")
        first = base.workflow.prepare_goal_request({**deepcopy(original), **self.seed_feedback()}, self.profile)
        base.clients.expected_wire_request(first["request"])
        files = base._hashes([*built["source_files"], self.config.parent_anchor_path, self.config.profile_path,
            self.config.preferences_path, self.config.user_goals_path, *self.config.extra_source_files, *self.code_files()])
        for path, item in checked.get("source_files", {}).items():
            expected = item.get("sha256") if type(item) is dict else item
            if sha(base._inside(path)) != expected: raise ValueError("certified original parent file changed")
            files[str(base._inside(path))] = expected
        value = {"schema": VERSION + "/preview", "root": str(self.root), "grant_id": self.config.grant_id,
            "inputs": original, "input_evidence": built["evidence"], "first_request": first,
            "inputs_sha256": digest(original), "profile_sha256": sha(self.config.profile_path), "parent_anchor_sha256": digest(parent),
            "inherited": checked["inherited"], "parent_root": parent["root"], "parent_identity": parent["parent_identity"],
            "source_files": files, "stage_limits": REMAINING, "total_new_calls_limit": TOTAL_REMAINING,
            "original_scope_stage_limits": ORIGINAL_LIMITS, "previous_scope_stage_calls": CONSUMED,
            "first_request_label": "whole_plan_02", "provider_calls": 0, "media_calls": 0, "old_budget_reset": False}
        value["preparation_identity_sha256"] = digest({k: value[k] for k in (
            "root", "grant_id", "inputs_sha256", "profile_sha256", "parent_anchor_sha256", "inherited", "source_files", "first_request")})
        return value

    def authorization_template(self, preview):
        result = super().authorization_template(preview)
        result.update(schema=VERSION + "/derived_authorization", stage_limits=REMAINING, total_new_calls_limit=TOTAL_REMAINING,
            original_total_call_limit=base.TOTAL, original_scope_stage_limits=ORIGINAL_LIMITS,
            previous_scope_stage_calls=CONSUMED, whole_plan_versions_available=[2, 3],
            original_scope_root=preview["parent_root"], continuation_is_new_authority=False)
        return result

    def _guard(self):
        # The inherited freeze format records original26. Its exact hashed
        # USER_SCOPE carries authoritative local22, checked here and by Runtime.
        super()._guard()
        scope = read(self.root / "USER_SCOPE.json"); anchor = read(self.config.parent_anchor_path)
        tables = (("stage_limits", REMAINING), ("original_scope_stage_limits", ORIGINAL_LIMITS),
                  ("previous_scope_stage_calls", CONSUMED))
        if any(type(scope.get(key)) is not dict or scope[key] != value
               or any(type(n) is not int for n in scope[key].values()) for key, value in tables):
            raise ValueError("frozen original/consumed/remaining stage scope differs")
        if not (scope.get("schema") == VERSION + "/derived_authorization"
                and type(scope.get("total_new_calls_limit")) is int and scope["total_new_calls_limit"] == TOTAL_REMAINING
                and type(scope.get("original_total_call_limit")) is int and scope["original_total_call_limit"] == base.TOTAL
                and scope.get("whole_plan_versions_available") == [2, 3]
                and scope.get("parent_anchor_sha256") == self.config.parent_anchor_sha256 == digest(anchor)
                and scope.get("original_scope_root") == anchor["root"]
                and scope.get("inherited") == anchor["inherited"]
                and scope.get("continuation_is_new_authority") is False):
            raise ValueError("frozen settled644 continuation scope differs")
        return True

    def _admit(self, label, request, ledger):
        if (len(ledger["calls"]) >= TOTAL_REMAINING or
                not re.fullmatch(r"whole_plan_0[23]|(?:scope|source|commitment|drama)_audit_0[23]|opening_setup_0[12]|complete_script_0[123]|full_review_(?:semantic|physical)_0[123]", label)):
            raise ValueError("original remaining scope or planning version exhausted")
        counts = deepcopy(CONSUMED)
        for row in ledger["calls"]: counts[read(self.root / row["receipt"])["request"]["stage"]] += 1
        if counts[request["stage"]] >= ORIGINAL_LIMITS[request["stage"]] or sum(counts.values()) >= base.TOTAL:
            raise ValueError("global original stage/26-call capacity exhausted")
        return super()._admit(label, request, ledger)

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            inherited_guard=self._guard, admission=self._admit,
            shared_lock=base.PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        result = super().state(runtime, status, **details)
        result.update(schema=VERSION + "/state", flow_version=VERSION, original_scope_stage_limits=ORIGINAL_LIMITS,
            previous_scope_stage_calls=CONSUMED, remaining_scope_stage_limits=REMAINING,
            original_total_call_limit=base.TOTAL, remaining_calls_at_run_start=TOTAL_REMAINING)
        write(self.root / "STATE.json", result)
        return result

    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file(): raise ValueError("separately prepared root required")
        if (self.root / "RUN_CLAIM.json").exists(): raise FileExistsError("original RUN cannot restart")
        base.policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "started_at": self.clock(),
            "pid": base.os.getpid(), "automatic_restart": False, "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json")})
        rt = None
        try:
            rt = self.runtime(); self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]: raise ValueError("original continuation cannot restart")
            inputs = read(self.root / "INPUTS.json"); wf = base.ReviewWorkflow(base.workflow, self._reviews(read(self.root / "USER_SCOPE.json")))
            driver = Driver(self, rt, inputs, wf)
            goal, bundle = driver._planning(); setup = driver._opening(goal)
            return self._save_text(driver._body(goal, bundle, setup), driver, rt)
        except (base.Halt, base.stages.OfflineStop) as stop:
            return self.state(rt, stop.status.replace("halt_mock_", "halt_live_"), **stop.details)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_restart": False}, True)
            return self.state(rt, "halt_execution_reconciliation", exception_type=type(exc).__name__, error=str(exc))


    def _save_text(self, result, driver, rt):
        paths = {"inputs": self.root / "INPUTS.json", "profile": Path(self.config.profile_path),
            "goal": self.root / "goal/NATIVE_GOAL.json", "goal_audit_bundle": self.root / "goal/NATIVE_GOAL_AUDIT_BUNDLE.json",
            "setup": self.root / "opening/NATIVE_OPENING_SETUP.json", "raw_script": self.root / "scripts/NATIVE_SCRIPT.json",
            "compiled_script": self.root / "scripts/COMPILED_SCRIPT.json", "full_review_bundle": self.root / "scripts/NATIVE_FULL_REVIEW_BUNDLE.json"}
        values = {"goal": result["native_goal"], "goal_audit_bundle": result["native_goal_audit"], "setup": result["native_opening_setup"],
            "raw_script": result["native_script"], "compiled_script": result["compiled_script"], "full_review_bundle": result["native_full_review_bundle"]}
        for key, value in values.items(): write(paths[key], value, True)
        (self.root / "scripts/FULL_SCRIPT.md").write_text(result["rendered_script"], encoding="utf-8")
        # Do not adopt the mock driver's offline snapshot qualifier. A media
        # caller must verify this actual handoff, then qualify its own snapshot.
        identities = {key: digest(value) for key, value in values.items()}
        receipt_ids = [_receipt_identity(self.root, row) for row in read(rt.ledger)["calls"]]
        handoff = {"schema": VERSION + "/text_handoff", "status": "text_ready_for_director", "source_root": str(self.root),
            "paths": {k: str(v.resolve()) for k, v in paths.items()}, "artifact_file_sha256": _hashes(paths.values()),
            "native_identity": identities, "receipt_identities": receipt_ids, "decision": result["decision"],
            "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json"), "run_claim_sha256": sha(self.root / "RUN_CLAIM.json"),
            "native_reports_unchanged": True, "text_only_machine_admission": True,
            "human_quality_approved": False, "creative_quality_passed": False, "media_submitted": False,
            "old_director_capacity": DIRECTOR, "new_director_scope_declared_separately": 3, "old_budget_reset": False}
        write(self.root / "TEXT_HANDOFF.json", handoff, True)
        return self.state(rt, "text_ready_for_director", text_handoff_sha256=digest(handoff),
            handoff_path=str(self.root / "TEXT_HANDOFF.json"))


def verify_text_handoff(root):
    """Read-only SDK/SQL/full native binding for the separately gated media caller."""
    session = Session.open(root); rt = session.runtime(); session._guard()
    state, handoff, ledger = (read(session.root / (name + ".json")) for name in ("STATE", "TEXT_HANDOFF", "CALL_LEDGER"))
    if (state.get("status") != "text_ready_for_director" or state.get("spend_verification_pending") is not False
            or state.get("text_handoff_sha256") != digest(handoff) or handoff.get("schema") != VERSION + "/text_handoff"
            or handoff.get("freeze_sha256") != sha(session.root / "PRODUCTION_FREEZE.json")
            or not (handoff.get("run_claim_sha256") == state.get("run_claim_sha256") == sha(session.root / "RUN_CLAIM.json"))):
        raise ValueError("original known text-ready state/handoff required")
    current = rt.summary()
    if current != state["spend"] or current["new_unknown_token_reservations"] != 0: raise ValueError("original settled text spend differs")
    reader = evidence.Reader()
    receipts = [evidence.verify_original_receipt(session.root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    if handoff.get("receipt_identities") != [_receipt_identity(session.root, row) for row in ledger["calls"]]:
        raise ValueError("original receipt/intent handoff identities differ")
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = read(session.root / "call_intents" / (row["label"] + ".json"))
        if (intent["prepared"]["request"] != receipt["request"] or intent["request_sha256"] != receipt["request_sha256"]
                or intent["ledger_prefix_sha256"] != digest(ledger["calls"][:index])):
            raise ValueError("original trusted-builder intent or native prerequisite sequence differs")
    for path, expected in handoff["artifact_file_sha256"].items(): reader.verify(_inside(path), expected)
    files = {key: read(_inside(path)) for key, path in handoff["paths"].items()}
    values = {"goal": files["goal"], "goal_audit_bundle": files["goal_audit_bundle"], "setup": files["setup"],
        "raw_script": files["raw_script"], "compiled_script": files["compiled_script"], "full_review_bundle": files["full_review_bundle"]}
    if handoff["native_identity"] != {key: digest(value) for key, value in values.items()}: raise ValueError("full native artifact identity differs")
    for key in ("goal", "setup", "raw_script"):
        if not any(receipt.get("output") == files[key] and receipt.get("status") == "contract_valid" for receipt in receipts):
            raise ValueError("artifact is not a complete original valid native: " + key)
    native_reports = [files["goal_audit_bundle"]["native_" + kind + "_audit"] for kind in workflow.AUDITS]
    native_reports += [files["full_review_bundle"]["native_" + part + "_review"] for part in ("semantic", "physical")]
    for document in native_reports:
        if type(document) is not dict or not any(receipt.get("output") == document and receipt.get("status") == "contract_valid" for receipt in receipts):
            raise ValueError("handoff report was not an original service result")
    wf = ReviewWorkflow(workflow, session._reviews(read(session.root / "USER_SCOPE.json")))
    _require_accepted(wf.validate_goal_audit(files["goal_audit_bundle"], files["goal"], inputs=files["inputs"]), "handoff_goal")
    views = wf.compile_native_views(files["goal"], files["setup"], **wf.origin_ids(files["inputs"]))
    compiled = wf.validate_script_document(files["raw_script"], views, files["inputs"]["production_preferences"])["script"]
    if compiled != files["compiled_script"]: raise ValueError("compiled body differs from complete raw native")
    parts = {part: wf.prepare_full_review_part_request(files["inputs"], files["profile"], files["raw_script"], views, part)
        for part in ("semantic", "physical")}
    checked = wf.full_reviews().validate_bundle(files["full_review_bundle"], compiled, views["brief"], views["plan"],
        parts["semantic"]["review_legal_context"], semantic_context_sha256=parts["semantic"]["part_context_sha256"],
        physical_context_sha256=parts["physical"]["part_context_sha256"], goal_contract=files["goal"], opening_setup=files["setup"],
        prior_story_scope=files["inputs"]["production_preferences"].get("prior_story_scope"))
    _require_accepted(checked, "handoff_full")
    if checked != handoff["decision"]: raise ValueError("original full decision differs from same-source recomputation")
    parent_identity = {"root": str(session.root), "terminal_state_sha256": sha(session.root / "STATE.json"),
        "native_ledger_sha256": sha(session.root / "CALL_LEDGER.json"),
        "production_freeze_sha256": sha(session.root / "PRODUCTION_FREEZE.json"), "end_ordinal": current["effective_calls_started"]}
    inherited = {"calls_started": current["effective_calls_started"], "reported_tokens": current["effective_reported_tokens"],
        "calls_with_known_usage": current["effective_calls_with_known_usage"],
        "pending_ordinals": deepcopy(current["historical_pending_ordinals"]), "unknown_token_reservations": current["unknown_token_reservations"]}
    proof_files = {**read(session.root / "PRODUCTION_FREEZE.json")["files"],
        **{path: item["sha256"] for path, item in reader.files.items()},
        **_hashes(session.root / (name + ".json") for name in (
            "STATE", "TEXT_HANDOFF", "CALL_LEDGER", "PRODUCTION_FREEZE", "RUN_CLAIM"))}
    return {"schema": VERSION + "/verified_text_handoff", "valid": True, "accepted": True,
        "status": "text_ready_for_director", "source_root": str(session.root), "root": str(session.root),
        "handoff_path": str(session.root / "TEXT_HANDOFF.json"), "handoff_sha256": sha(session.root / "TEXT_HANDOFF.json"),
        "paths": deepcopy(handoff["paths"]), "identity": {"native_goal_sha256": digest(files["goal"]),
            "native_script_sha256": digest(files["raw_script"]), "compiled_script_sha256": digest(compiled),
            "native_setup_sha256": digest(files["setup"]), "goal_audit_bundle_sha256": digest(files["goal_audit_bundle"]),
            "full_review_bundle_sha256": digest(files["full_review_bundle"])}, "receipt_identities": deepcopy(handoff["receipt_identities"]),
        "spend": current, "human_quality_approved": False, "creative_quality_passed": False,
        "inherited": inherited, "parent_identity": parent_identity, "parent_identity_sha256": digest(parent_identity),
        "source_files": proof_files, "old_director_capacity": DIRECTOR,
        "authorizes_media_dispatch": False, "model_calls": 0}


def main():
    import argparse, json
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("action", choices=("preview", "authorization", "prepare", "run", "verify")); p.add_argument("path")
    args = p.parse_args()
    if args.action == "verify": result = verify_text_handoff(args.path)
    else:
        session = Session(read(args.path)) if args.action in ("preview", "authorization", "prepare") else Session.open(args.path)
        result = session.authorization_template(session.preview()) if args.action == "authorization" else getattr(session, args.action)()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
