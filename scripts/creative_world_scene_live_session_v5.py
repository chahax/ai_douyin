"""Bounded complete source replanning, fifth source gate and same-source text.

Import/preview never dispatches.  The old eight bodies and two diagnostics are
settled ancestry, not reusable allowances.  No media caller is implemented here.
"""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from scripts import creative_world_scene_live_session_v1 as base
from scripts import creative_world_scene_live_session_v3 as references
from scripts import creative_world_scene_source_state_audit_session_v1 as source_refs
from scripts import creative_world_scene_array_probe_session_v1 as native_proof

VERSION = "creative_world_scene_live_session/v5"
Config = base.Config
LIMITS = {"goal_plan": 9, "goal_audit": 15, "complete_script": 3, "full_review": 6}
TOTAL = 33
BODY_VERSIONS = [9, 10, 11]
read, write, digest, sha = base.read, base.write, base.digest, base.sha
SOURCE_PARAMETERS = {"goal_audit_default_max_completion_tokens": 16000,
    "source_state_max_completion_tokens": 32000, "other_profile_parameters_changed": False}


class NextRequest(Exception):
    def __init__(self, prepared): self.prepared = prepared


class Replan(Exception):
    def __init__(self, feedback): self.feedback = feedback


class Runtime(base.Runtime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, stage_limits=base.LIMITS, **kwargs)
        self.stage_limits = deepcopy(LIMITS)

    def _request_gate(self, request):
        version = "creative_world_scene_source_state_audit/v3"
        schema_version = request.get("structured_schema", {}).get("properties", {}).get("schema", {}).get("const")
        provenance_version = request.get("input_provenance", {}).get("source_state_audit_version")
        # Writer provenance also cites its accepted source audit.  That is an
        # ancestry reference, not a request for this reviewer-only exception.
        if schema_version != version:
            return super()._request_gate(request)
        if (schema_version != version or provenance_version != version or request.get("stage") != "goal_audit"
                or request.get("role") != "director" or request.get("model") != self.models["director"]["model"]):
            raise RuntimeError("exact native source-state v3 reviewer identity required for32k substage")
        parameters = deepcopy(self.profile["director"]["parameters"])
        override = self.profile.get("stage_parameters", {}).get("goal_audit", {})
        if set(override) - {"max_completion_tokens"}:
            raise RuntimeError("stage profile can only override output allowance")
        parameters.update(override); parameters["max_completion_tokens"] = 32000
        if request.get("parameters") != parameters:
            raise RuntimeError("only source-state output cap may differ from original creative profile")
        base.clients.expected_wire_request(request)
        Draft202012Validator.check_schema(request["structured_schema"])

    def _policy(self):
        value = super()._policy()
        value.update(schema=VERSION + "/runtime_policy", total_new_calls_limit=TOTAL,
            whole_plan_limit=3, opening_setup_limit_per_plan=2, opening_setup_limit=6,
            native_goal_audit_parts_per_plan=5, complete_script_versions=BODY_VERSIONS,
            complete_script_limit_shared_across_plans=3, source_state_parameters=SOURCE_PARAMETERS,
            old_complete_body_calls_used=8, diagnostic_calls_previously_used=4,
            old_source_state_diagnostics_used=2, old_budget_reset=False)
        return value


class Driver(base.LiveDriver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.body_used = 0

    def invoke(self, label, prepared, validator):
        session, runtime = self.session, self.runtime; ledger = read(runtime.ledger)
        if any(row["label"] == label for row in ledger["calls"]):
            raise base.Halt("halt_duplicate_live_stage", label=label)
        intent = {"schema": VERSION + "/call_intent", "label": label, "prepared": deepcopy(prepared),
            "request_sha256": digest(prepared["request"]), "ledger_prefix_sha256": digest(ledger["calls"]),
            "inputs_sha256": digest(self.inputs), "automatic_retry": False,
            "prerequisite_receipts": [{key: row[key] for key in ("ordinal", "label", "receipt", "receipt_sha256")}
                for row in ledger["calls"]]}
        path = session.root / "call_intents" / (label + ".json"); write(path, intent, True)
        session.pending_intent = {"path": str(path), "sha256": sha(path), "label": label}
        receipt = base.policy.dispatch_claimed(runtime, label, prepared, validator, root=session.root,
            grant_id=session.config.grant_id, stage_limits=LIMITS, current_round_root=session.config.counter_root,
            current_round_key=session.config.round_key, guard=session._guard)
        native = native_proof.known_native(receipt); checked = base._decision(receipt)
        row = {"label": label, "ordinal": receipt["ordinal"], "receipt": f"call_{receipt['ordinal']:03}_{label}.json",
            "status": receipt["status"], "request_sha256": receipt["request_sha256"],
            "native_output": deepcopy(native), "validation": deepcopy(checked), "provider_result_is_actual_receipt": True}
        self.calls.append(row)
        return native, checked, row

    def _feedback(self, goal, setup, native, decision, *, kind, prepared=None, passed=None, body=None):
        return self.wf.seed_feedback(goal, setup, native, decision, prepared=prepared,
            passed_audits=passed, failed_kind=kind, failed_body=body)

    def _four_audits(self, goal, version):
        wf = self.wf; reports, decisions = {}, {}
        for kind in wf.AUDITS:
            if kind == "scope": prepared = wf.prepare_goal_scope_request(self.inputs, self.profile, goal)
            elif kind == "source": prepared = wf.prepare_goal_scoped_source_request(self.inputs, self.profile, goal, reports["scope"])
            else: prepared = getattr(wf, "prepare_goal_" + kind + "_audit_request")(self.inputs, self.profile, goal)
            context = prepared.get("scope_context_sha256") if kind == "scope" else prepared["audit_context_sha256"]
            kwargs = {"context_sha256": context, "inputs": self.inputs}
            if kind == "source": kwargs.update(native_scope=reports["scope"], authority_context=prepared["source_authority_context"])
            validator = wf.validate_goal_scope if kind == "scope" else getattr(wf, "validate_goal_" + kind + "_audit")
            native, decision, _ = self.invoke(f"{kind}_audit_{version:02}", prepared,
                lambda value, fn=validator, args=kwargs: fn(value, goal, **args))
            reports[kind], decisions[kind] = native, decision
            if not self.audit_gate(decision, kind):
                return None, self._feedback(goal, None, native, decision, kind=kind, prepared=prepared,
                    passed={key: value for key, value in reports.items() if key != kind})
        bundle = wf.build_goal_audit_bundle(*(reports[kind] for kind in wf.AUDITS))
        if not self.audit_gate(wf.validate_goal_audit(bundle, goal, inputs=self.inputs), "four_audit_bundle"):
            raise base.Halt("halt_planning_bundle_rejected")
        return bundle, None

    def _opening(self, goal, plan_version):
        current = deepcopy(self.inputs); last = None
        for attempt in (1, 2):
            prepared = self.wf.prepare_opening_setup_request(current, self.profile, goal)
            native, decision, row = self.invoke(f"opening_setup_{plan_version:02}_{attempt:02}", prepared,
                lambda value: {"valid": True, "native_setup_sha256": digest(self.wf.validate_opening_setup_document(value, goal))})
            if decision.get("valid") is True: return native, None
            if native.get("goal_sha256") != digest(goal):
                raise base.Halt("halt_opening_feedback_identity_contract", native_setup_sha256=digest(native),
                    requested_native_goal_sha256=digest(goal), receipt_ordinal=row.get("ordinal"),
                    remaining_setup_attempts=2-attempt, original_native_modified=False, decision=decision)
            last = native, decision, prepared
            current = {**deepcopy(self.inputs), "previous_opening_setup": native, "opening_setup_diagnostics": decision}
        native, decision, prepared = last
        return None, self._feedback(goal, native, None, decision, kind="opening_setup", prepared=prepared)

    def _body(self, goal, bundle, setup, source_report, source_prepared, source_decision):
        wf, current, reviews = self.wf, deepcopy(self.inputs), self.wf.full_reviews()
        while self.body_used < len(BODY_VERSIONS):
            version = BODY_VERSIONS[self.body_used]; self.body_used += 1
            authored = wf.prepare_script_request(current, self.profile, goal, bundle, opening_setup=setup,
                source_state_audit=source_report, source_state_prepared=source_prepared, **wf.origin_ids(self.inputs))
            views = authored["views"]
            native, decision, _ = self.invoke(f"complete_script_{version:02}", authored,
                lambda value: {**wf.validate_script_document(value, views, self.inputs["production_preferences"]), "valid": True})
            if decision.get("valid") is not True:
                current = {**deepcopy(self.inputs), "previous_complete_document": native, "revision_diagnostics": decision}
                continue
            compiled = wf.validate_script_document(native, views, self.inputs["production_preferences"])["script"]
            documents, contexts, legal, failed, failed_prepared = {}, {}, None, None, None
            for part in ("semantic", "physical"):
                prepared = wf.prepare_full_review_part_request(self.inputs, self.profile, native, views, part)
                context = prepared["part_context_sha256"]
                if legal is not None and legal != prepared["review_legal_context"]:
                    raise base.Halt("halt_review_authority_changed")
                legal = prepared["review_legal_context"]
                report, checked, _ = self.invoke(f"full_review_{part}_{version:02}", prepared,
                    lambda value, p=part, c=context: reviews.validate_part(value, p, compiled, views["brief"], views["plan"], legal,
                        context_sha256=c, goal_contract=goal, opening_setup=setup,
                        prior_story_scope=self.inputs["production_preferences"].get("prior_story_scope")))
                documents[part], contexts[part] = report, context
                if not self.audit_gate(checked, part):
                    failed, failed_prepared = checked, prepared; break
            if failed is not None:
                if failed.get("requires_new_goal_plan") or failed.get("new_scope_requires_new_goal_plan"):
                    raise Replan(self._feedback(goal, setup, documents[part], failed, kind="full_review_" + part,
                        prepared=failed_prepared, body=native))
                current = {**deepcopy(self.inputs), "previous_complete_document": native,
                    "revision_diagnostics": {"complete_same_source_part_review": failed, "native_part_reviews": documents}}
                continue
            full = reviews.build_review_bundle(documents["semantic"], documents["physical"])
            checked = reviews.validate_bundle(full, compiled, views["brief"], views["plan"], legal,
                semantic_context_sha256=contexts["semantic"], physical_context_sha256=contexts["physical"],
                goal_contract=goal, opening_setup=setup,
                prior_story_scope=self.inputs["production_preferences"].get("prior_story_scope"))
            if not self.audit_gate(checked, "full_bundle"):
                if checked.get("requires_new_goal_plan") or checked.get("new_scope_requires_new_goal_plan"):
                    raise Replan(self._feedback(goal, setup, full, checked, kind="full_review_bundle", body=native))
                current = {**deepcopy(self.inputs), "previous_complete_document": native,
                    "revision_diagnostics": {"complete_same_source_full_review_bundle": checked, "native_review_bundle": full}}
                continue
            return {"native_goal": goal, "native_goal_audit": bundle, "native_opening_setup": setup,
                "native_source_state_audit": source_report, "source_state_decision": source_decision,
                "native_script": native, "compiled_script": compiled, "native_full_review_bundle": full,
                "decision": checked, "rendered_script": wf.render_script(native, goal), "views": views}
        raise base.Halt("halt_live_shared_script_capacity", shared_body_calls_used=self.body_used)

    def flow(self):
        current = {**deepcopy(self.inputs), **self.session.seed_feedback(self.wf)}
        for version in (1, 2, 3):
            if self.body_used >= len(BODY_VERSIONS):
                raise base.Halt("halt_live_shared_script_capacity", shared_body_calls_used=self.body_used)
            goal, decision, _ = self.invoke(f"whole_plan_{version:02}", self.wf.prepare_goal_request(current, self.profile),
                lambda value: {"valid": True, "native_goal_sha256": digest(self.wf.validate_goal_document(value, inputs=self.inputs))})
            if decision.get("valid") is not True:
                current = {**deepcopy(self.inputs), **self._feedback(goal, None, None, decision, kind="goal_contract")}; continue
            bundle, feedback = self._four_audits(goal, version)
            if feedback is not None: current = {**deepcopy(self.inputs), **feedback}; continue
            setup, feedback = self._opening(goal, version)
            if feedback is not None: current = {**deepcopy(self.inputs), **feedback}; continue
            prepared = self.wf.prepare_source_state_audit_request(self.inputs, self.profile, goal, setup)
            report, checked, _ = self.invoke(f"source_state_audit_{version:02}", prepared,
                lambda value: self.wf.validate_source_state_audit(value, prepared))
            if not self.audit_gate(checked, "source_state"):
                current = {**deepcopy(self.inputs), **self._feedback(goal, setup, report, checked,
                    kind="source_state", prepared=prepared, passed=bundle)}; continue
            try: return self._body(goal, bundle, setup, report, prepared, checked)
            except Replan as repair: current = {**deepcopy(self.inputs), **repair.feedback}
        raise base.Halt("halt_live_complete_plan_capacity")


class Session(base.Session):
    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_typed_audit_spend_anchor_v1").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited")
                or len(anchor.get("source_state_audit_receipts", [])) != 2
                or anchor.get("source_state_audit_contract_valid") is not False
                or anchor.get("source_state_audit_semantically_accepted") is not False):
            raise ValueError("settled two refused source diagnostics required; no old budget reset")
        source_refs.creative_root(anchor); return anchor, checked

    def _profile_gate(self):
        profile = super()._profile_gate(); anchor = read(self.config.parent_anchor_path)
        original = read(read(source_refs.creative_root(anchor) / "SESSION_CONFIG.json")["profile_path"])
        if profile != original: raise ValueError("original creative profile must remain exact; only source-state request has explicit32k override")
        return profile

    def _workflow(self):
        adapter = self._reviews(read(self.root / "USER_SCOPE.json")) if (self.root / "USER_SCOPE.json").exists() else self.injected_review_adapter
        return importlib.import_module("scripts.creative_world_scene_replanned_workflow_v1").ReviewWorkflow(base.workflow, adapter)

    def seed_feedback(self, wf):
        anchor = read(self.config.parent_anchor_path)
        goal = references._ref_document(anchor["native_goal_receipt"])[1]
        setup = references._ref_document(anchor["native_opening_setup_receipt"])[1]
        receipt, native = references._ref_document(anchor["latest_source_state_audit_receipt"])
        ref = anchor["latest_source_state_audit_decision_ref"]; path = base._inside(ref["path"])
        decision = read(path)
        if (sha(path) != ref["file_sha256"] or digest(decision) != ref["native_sha256"]
                or receipt.get("validation") != decision): raise ValueError("settled original refused diagnostic decision changed")
        payload = json.loads(receipt["request"]["messages"][1]["content"])
        if payload.get("native_goal_document") != goal or payload.get("native_opening_setup_document") != setup:
            raise ValueError("original diagnostic wire source differs from its native references")
        prepared = {"views": {"goal": goal, "setup": setup, "source_catalog": payload["source_catalog"]}}
        return wf.seed_feedback(goal, setup, native, decision, prepared=prepared, failed_kind="historical_diagnostic")

    def preview(self):
        anchor, checked = self._parent(); built = self._inputs(); self._profile_gate()
        original = read(source_refs.creative_root(anchor) / "INPUTS.json")
        if built["inputs"] != original: raise ValueError("original creative inputs must remain exact")
        first = self._workflow().prepare_goal_request({**deepcopy(original), **self.seed_feedback(self._workflow())}, self.profile)
        base.clients.expected_wire_request(first["request"])
        files = base._hashes([*built["source_files"], self.config.parent_anchor_path, self.config.profile_path,
            self.config.preferences_path, self.config.user_goals_path, *self.config.extra_source_files, *self.code_files()])
        for path, item in checked.get("source_files", {}).items():
            expected = item.get("sha256") if type(item) is dict else item
            if sha(base._inside(path)) != expected: raise ValueError("original certified parent changed")
            files[str(base._inside(path))] = expected
        value = {"schema": VERSION + "/preview", "root": str(self.root), "grant_id": self.config.grant_id,
            "inputs": original, "input_evidence": built["evidence"], "inputs_sha256": digest(original), "first_request": first,
            "profile_sha256": sha(self.config.profile_path), "parent_anchor_sha256": digest(anchor), "parent_root": anchor["root"],
            "parent_identity": anchor["parent_identity"], "inherited": checked["inherited"], "source_files": files,
            "creative_source_root": str(source_refs.creative_root(anchor)), "stage_limits": deepcopy(LIMITS),
            "total_new_calls_limit": TOTAL, "provider_calls": 0, "media_calls": 0, "source_state_parameters": SOURCE_PARAMETERS}
        value["preparation_identity_sha256"] = digest({k: value[k] for k in (
            "root", "grant_id", "inputs_sha256", "profile_sha256", "parent_anchor_sha256", "inherited", "source_files", "first_request")})
        return value

    def authorization_template(self, preview):
        value = super().authorization_template(preview)
        value.update(schema=VERSION + "/derived_authorization", stage_limits=deepcopy(LIMITS), total_new_calls_limit=TOTAL,
            whole_plan_limit=3, opening_setup_limit=6, opening_setup_limit_per_plan=2, complete_script_versions=BODY_VERSIONS,
            complete_script_limit_shared_across_plans=3, native_goal_audit_parts_per_plan=5,
            old_complete_body_calls_used=8, old_complete_body_capacity=8, diagnostic_calls_previously_used=4,
            old_source_state_diagnostics_used=2, source_state_parameters=SOURCE_PARAMETERS,
            creative_source_root=preview["creative_source_root"], fresh_goal_audits_and_opening_required=True,
            new_authority="user autonomous complete source replan and bounded full text; three new plans and shared three complete bodies; no media")
        return value

    def _binding(self, parent):
        value = super()._binding(parent); value.update(schema=VERSION + "/successor_claim", old_source_state_diagnostics_used=2)
        return value

    def prepare(self):
        if self.root.exists() or self.claim.exists(): raise FileExistsError("existing root/grant cannot restart")
        preview = self.preview(); parent, _ = self._parent(); binding = self._binding(parent)
        if read(self.config.authorization_path) != self.authorization_template(preview): raise ValueError("reviewed new33-call authorization differs")
        successors = base.policy.successor_paths(base.PROJECT, parent, self.config.parent_anchor_sha256)
        if any(path.exists() for path in successors): raise ValueError("real settled parent already has a successor")
        self.root.mkdir(parents=True, exist_ok=False)
        for name, value in (("SESSION_CONFIG", asdict(self.config)), ("INPUTS", preview["inputs"]),
                ("INPUT_EVIDENCE", preview["input_evidence"]), ("FIRST_REQUEST_PREVIEW", preview["first_request"]),
                ("USER_SCOPE", read(self.config.authorization_path))): write(self.root / (name + ".json"), value, True)
        base.policy.new_claim(self.claim, {**binding, "schema": VERSION + "/grant_claim"})
        for path in successors: base.policy.new_claim(path, binding)
        files = {**preview["source_files"], **base._hashes([self.config.authorization_path, self.claim, *successors,
            *(self.root / (name + ".json") for name in ("SESSION_CONFIG", "INPUTS", "INPUT_EVIDENCE", "FIRST_REQUEST_PREVIEW", "USER_SCOPE")),
            Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json", Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json"])}
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "inputs_sha256": preview["inputs_sha256"], "inherited": preview["inherited"], "binding": binding,
            "successor_claim_paths": [str(path) for path in successors], "claim_sha256": sha(self.claim),
            "stage_limits": deepcopy(LIMITS), "total_new_calls_limit": TOTAL, "old_director_capacity": base.DIRECTOR}, True)
        runtime = self.runtime(); runtime.prepare(); return self.state(runtime, "prepared")

    def _guard(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json"); scope = read(self.root / "USER_SCOPE.json")
        if (freeze.get("schema") != VERSION + "/freeze" or freeze.get("stage_limits") != LIMITS
                or freeze.get("total_new_calls_limit") != TOTAL or scope != self.authorization_template({
                    "preparation_identity_sha256": scope.get("preparation_identity_sha256"), "inherited": freeze["inherited"],
                    "inputs_sha256": freeze["inputs_sha256"], "creative_source_root": scope.get("creative_source_root"),
                    "inputs": read(self.root / "INPUTS.json") } )):
            raise ValueError("exact v5 scope/freeze33 policy differs")
        if any(type(value) is not int for value in scope["stage_limits"].values()) or type(scope["total_new_calls_limit"]) is not int:
            raise ValueError("integer stage limits required")
        if digest(asdict(self.config)) != digest(read(self.root / "SESSION_CONFIG.json")): raise ValueError("frozen config differs")
        for path, expected in freeze["files"].items():
            if sha(base._inside(path)) != expected: raise ValueError("frozen dependency changed: " + path)
        if sha(self.claim) != freeze["claim_sha256"]: raise ValueError("original grant claim changed")
        anchor = read(self.config.parent_anchor_path)
        if digest(anchor) != self.config.parent_anchor_sha256 or freeze["inherited"] != anchor["inherited"]:
            raise ValueError("original parent accounting differs")
        if scope["creative_source_root"] != str(source_refs.creative_root(anchor)):
            raise ValueError("original creative source root differs")
        expected_paths = base.policy.successor_paths(base.PROJECT, anchor, self.config.parent_anchor_sha256)
        if freeze["successor_claim_paths"] != [str(path) for path in expected_paths]: raise ValueError("real parent successor paths differ")
        if freeze["binding"] != self._binding(anchor): raise ValueError("frozen successor binding differs")
        for path in expected_paths:
            if read(path) != freeze["binding"]: raise ValueError("unique parent successor changed")
        if read(self.claim) != {**freeze["binding"], "schema": VERSION + "/grant_claim"}: raise ValueError("grant binding differs")
        if read(self.root / "INPUTS.json") != read(source_refs.creative_root(anchor) / "INPUTS.json"):
            raise ValueError("original creative authority changed")
        self._profile_gate()
        gate = self.source_gate(self.config.source_dir, now=self.clock())
        if gate.get("valid") is not True or gate.get("current_source_freshness_verified") is not True:
            raise ValueError("current original source freshness required")
        path = self.root / "RUN_CLAIM.json"
        if path.exists():
            claim = read(path)
            if not (claim.get("schema") == VERSION + "/run_claim" and claim.get("root") == str(self.root)
                    and type(claim.get("pid")) is int and claim["pid"] > 0 and claim.get("automatic_restart") is False
                    and claim.get("freeze_sha256") == sha(self.root / "PRODUCTION_FREEZE.json")):
                raise ValueError("single original v5 RUN binding differs")
        return True

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return Runtime(base.PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            inherited_guard=self._guard, admission=self._admit,
            shared_lock=base.PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def _replay(self, ledger, label=None, *, verify_validations=False):
        owner = self; rows = ledger["calls"]
        class Replay(Driver):
            def invoke(self, current_label, prepared, validator):
                if self.position == len(rows):
                    if current_label != label: raise ValueError("native linked stage order differs")
                    raise NextRequest(prepared)
                row = rows[self.position]; self.position += 1; path = owner.root / row["receipt"]; receipt = read(path)
                if (current_label != row["label"] or sha(path) != row["receipt_sha256"]
                        or receipt["request"] != prepared["request"]): raise ValueError("original request/native prerequisite differs")
                native = native_proof.known_native(receipt); checked = base._decision(receipt)
                if verify_validations and receipt["status"] == "contract_valid" and validator(native) != checked:
                    raise ValueError("original native decision differs from same-source recomputation")
                return native, checked, row
        replay = Replay(self, None, read(self.root / "INPUTS.json"), self._workflow()); replay.position = 0
        try: result = replay.flow()
        except NextRequest as found:
            if label is None: raise ValueError("terminal handoff has an unfinished stage")
            return found.prepared
        if label is not None: raise ValueError("linked native flow is already terminal")
        if replay.position != len(rows): raise ValueError("extra receipts after terminal native flow")
        return result

    def _admit(self, label, request, ledger):
        self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"]) >= TOTAL or not re.fullmatch(
                r"whole_plan_0[123]|(?:scope|source|commitment|drama|source_state)_audit_0[123]|opening_setup_0[123]_0[12]|complete_script_(?:09|10|11)|full_review_(?:semantic|physical)_(?:09|10|11)", label):
            raise ValueError("unregistered linked v5 label or scope exhausted")
        expected_stage = ("goal_plan" if label.startswith(("whole_plan_", "opening_setup_")) else
            "goal_audit" if "_audit_" in label else "complete_script" if label.startswith("complete_script_") else "full_review")
        if request.get("stage") != expected_stage: raise ValueError("registered native stage mapping differs")
        pending = self.pending_intent
        if not pending or pending["label"] != label or sha(pending["path"]) != pending["sha256"]:
            raise ValueError("original builder intent missing")
        intent = read(pending["path"])
        if (intent.get("schema") != VERSION + "/call_intent" or intent["prepared"]["request"] != request
                or intent["request_sha256"] != digest(request) or intent["ledger_prefix_sha256"] != digest(ledger["calls"])
                or intent["inputs_sha256"] != digest(read(self.root / "INPUTS.json"))
                or self._replay(ledger, label)["request"] != request): raise ValueError("exact linked request cannot be rebuilt")
        cap = 32000 if label.startswith("source_state_audit_") else (16000 if expected_stage == "goal_audit" else None)
        if cap is not None and request["parameters"].get("max_completion_tokens") != cap:
            raise ValueError("only the source-state substage has the explicit32k exception")
        base.clients.expected_wire_request(request); return True

    def state(self, runtime, status, **details):
        value = base.NativeSession.state(self, runtime, status, **details)
        value.update(schema=VERSION + "/state", flow_version=VERSION, new_stage_limits=deepcopy(LIMITS),
            text_ready_for_director=status == "text_ready_for_director", old_complete_body_calls_used=8,
            diagnostic_calls_previously_used=4, old_source_state_diagnostics_used=2, source_state_parameters=SOURCE_PARAMETERS)
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha(self.root / "RUN_CLAIM.json")
        write(self.root / "STATE.json", value); return value

    def _save_text(self, result, driver, runtime):
        paths = {"inputs": self.root / "INPUTS.json", "profile": Path(self.config.profile_path),
            "goal": self.root / "goal/NATIVE_GOAL.json", "goal_audit_bundle": self.root / "goal/NATIVE_GOAL_AUDIT_BUNDLE.json",
            "setup": self.root / "opening/NATIVE_OPENING_SETUP.json", "source_state_audit": self.root / "goal/NATIVE_SOURCE_STATE_AUDIT.json",
            "source_state_decision": self.root / "goal/SOURCE_STATE_DECISION.json", "raw_script": self.root / "scripts/NATIVE_SCRIPT.json",
            "compiled_script": self.root / "scripts/COMPILED_SCRIPT.json", "full_review_bundle": self.root / "scripts/NATIVE_FULL_REVIEW_BUNDLE.json"}
        values = {"goal": result["native_goal"], "goal_audit_bundle": result["native_goal_audit"], "setup": result["native_opening_setup"],
            "source_state_audit": result["native_source_state_audit"], "source_state_decision": result["source_state_decision"],
            "raw_script": result["native_script"], "compiled_script": result["compiled_script"], "full_review_bundle": result["native_full_review_bundle"]}
        for key, value in values.items(): write(paths[key], value, True)
        rendered = self.root / "scripts/FULL_SCRIPT.md"
        with rendered.open("x", encoding="utf-8", newline="\n") as stream: stream.write(result["rendered_script"])
        handoff = {"schema": VERSION + "/text_handoff", "status": "text_ready_for_director", "source_root": str(self.root),
            "paths": {key: str(path.resolve()) for key, path in paths.items()}, "artifact_file_sha256": base._hashes([*paths.values(), rendered]),
            "native_identity": {key: digest(value) for key, value in values.items()},
            "receipt_identities": [base._receipt_identity(self.root, row) for row in read(runtime.ledger)["calls"]],
            "decision": result["decision"], "source_state_decision": result["source_state_decision"],
            "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json"), "run_claim_sha256": sha(self.root / "RUN_CLAIM.json"),
            "native_reports_unchanged": True, "fresh_goal_four_audits_opening_and_source_gate": True,
            "text_only_machine_admission": True, "human_quality_approved": False, "creative_quality_passed": False,
            "media_submitted": False, "old_budget_reset": False, "old_director_capacity": base.DIRECTOR}
        write(self.root / "TEXT_HANDOFF.json", handoff, True)
        return self.state(runtime, "text_ready_for_director", text_handoff_sha256=digest(handoff), handoff_path=str(self.root / "TEXT_HANDOFF.json"))

    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file(): raise ValueError("separately prepared v5 root required")
        base.policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "pid": base.os.getpid(), "started_at": self.clock(), "automatic_restart": False, "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json")})
        runtime = None
        try:
            runtime = self.runtime(); self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(runtime.ledger)["calls"]: raise ValueError("nonempty original RUN cannot restart")
            driver = Driver(self, runtime, read(self.root / "INPUTS.json"), self._workflow())
            return self._save_text(driver.flow(), driver, runtime)
        except (base.Halt, base.stages.OfflineStop) as stop:
            return self.state(runtime, stop.status, **stop.details)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_restart": False}, True)
            return self.state(runtime, "halt_execution_reconciliation", exception_type=type(exc).__name__, error=str(exc))


def verify_text_handoff(root):
    """Rebuild all adopted native stages against original SDK/TaskStore evidence."""
    session = Session.open(root); runtime = session.runtime(); session._guard(); anchor, parent = session._parent()
    state, handoff, ledger = (read(session.root / (name + ".json")) for name in ("STATE", "TEXT_HANDOFF", "CALL_LEDGER"))
    if (state.get("status") != "text_ready_for_director" or state.get("spend_verification_pending") is not False
            or handoff.get("schema") != VERSION + "/text_handoff" or state.get("text_handoff_sha256") != digest(handoff)
            or handoff.get("freeze_sha256") != sha(session.root / "PRODUCTION_FREEZE.json")
            or not (handoff.get("run_claim_sha256") == state.get("run_claim_sha256") == sha(session.root / "RUN_CLAIM.json"))):
        raise ValueError("known final v5 handoff/STATE/RUN required")
    current = runtime.summary()
    if current != state["spend"] or current["new_unknown_token_reservations"] != 0: raise ValueError("original settled text accounting differs")
    reader = base.evidence.Reader()
    receipts = [base.evidence.verify_original_receipt(session.root, row, ledger["source_manifest"], reader=reader) for row in ledger["calls"]]
    base.evidence._tasks(reader, session.root, ledger, receipts, session.config.grant_id)
    if handoff.get("receipt_identities") != [base._receipt_identity(session.root, row) for row in ledger["calls"]]:
        raise ValueError("original receipt/intent identities differ")
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = read(session.root / "call_intents" / (row["label"] + ".json"))
        if (intent.get("schema") != VERSION + "/call_intent" or intent["prepared"]["request"] != receipt["request"]
                or intent["ledger_prefix_sha256"] != digest(ledger["calls"][:index])):
            raise ValueError("original builder intent/prefix differs")
    result = session._replay(ledger, verify_validations=True)
    expected = {"goal": result["native_goal"], "goal_audit_bundle": result["native_goal_audit"], "setup": result["native_opening_setup"],
        "source_state_audit": result["native_source_state_audit"], "source_state_decision": result["source_state_decision"],
        "raw_script": result["native_script"], "compiled_script": result["compiled_script"], "full_review_bundle": result["native_full_review_bundle"]}
    for path, expected_sha in handoff["artifact_file_sha256"].items(): reader.verify(base._inside(path), expected_sha)
    if handoff.get("native_identity") != {key: digest(value) for key, value in expected.items()}:
        raise ValueError("adopted complete native identities differ")
    for key, value in expected.items():
        if read(base._inside(handoff["paths"][key])) != value: raise ValueError("artifact differs from rebuilt native: " + key)
    if (read(handoff["paths"]["inputs"]) != read(session.root / "INPUTS.json") or read(handoff["paths"]["profile"]) != session.profile
            or handoff.get("decision") != result["decision"] or handoff.get("source_state_decision") != result["source_state_decision"]
            or (session.root / "scripts/FULL_SCRIPT.md").read_text(encoding="utf-8") != result["rendered_script"]):
        raise ValueError("native authority/derived decision/render differs")
    identity = {"root": str(session.root), "terminal_state_sha256": sha(session.root / "STATE.json"),
        "native_ledger_sha256": sha(session.root / "CALL_LEDGER.json"), "production_freeze_sha256": sha(session.root / "PRODUCTION_FREEZE.json"),
        "end_ordinal": current["effective_calls_started"]}
    inherited = {"calls_started": current["effective_calls_started"], "reported_tokens": current["effective_reported_tokens"],
        "calls_with_known_usage": current["effective_calls_with_known_usage"], "pending_ordinals": deepcopy(current["historical_pending_ordinals"]),
        "unknown_token_reservations": current["unknown_token_reservations"]}
    files = {**read(session.root / "PRODUCTION_FREEZE.json")["files"],
        **{path: item["sha256"] for path, item in reader.files.items()},
        **base._hashes(session.root / (name + ".json") for name in ("STATE", "TEXT_HANDOFF", "CALL_LEDGER", "PRODUCTION_FREEZE", "RUN_CLAIM"))}
    return {"schema": VERSION + "/verified_text_handoff", "valid": True, "accepted": True, "status": "text_ready_for_director",
        "root": str(session.root), "source_root": str(session.root), "handoff_path": str(session.root / "TEXT_HANDOFF.json"),
        "handoff_sha256": sha(session.root / "TEXT_HANDOFF.json"), "paths": deepcopy(handoff["paths"]),
        "identity": {"native_goal_sha256": digest(expected["goal"]), "native_setup_sha256": digest(expected["setup"]),
            "native_script_sha256": digest(expected["raw_script"]), "compiled_script_sha256": digest(expected["compiled_script"]),
            "goal_audit_bundle_sha256": digest(expected["goal_audit_bundle"]), "full_review_bundle_sha256": digest(expected["full_review_bundle"]),
            "source_state_audit_sha256": digest(expected["source_state_audit"])},
        "receipt_identities": deepcopy(handoff["receipt_identities"]), "spend": current, "inherited": inherited,
        "parent_identity": identity, "parent_identity_sha256": digest(identity), "source_files": files,
        "human_quality_approved": False, "creative_quality_passed": False, "authorizes_media_dispatch": False, "model_calls": 0}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization", "prepare", "run", "verify")); parser.add_argument("path")
    args = parser.parse_args()
    if args.action == "verify": value = verify_text_handoff(args.path)
    else:
        session = Session.open(args.path) if args.action == "run" else Session(read(args.path))
        value = session.authorization_template(session.preview()) if args.action == "authorization" else getattr(session, args.action)()
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
