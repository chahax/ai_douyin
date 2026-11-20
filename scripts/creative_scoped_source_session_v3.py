"""One known-native clarification, four real planning audits, native text.

Only this independent entry owns the new scope. Frozen sessions provide their
ordinary receipt/run protocols and text driver; none of their globals change.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import importlib
import json
from pathlib import Path
import re
import sys

from scripts import creative_fresh_source_session_v1 as shared
from scripts import creative_fresh_source_session_v2 as previous
from scripts import creative_session_text_driver_v1 as driver
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts import creative_m31_flash_role_clients_v1 as ordinary

VERSION = "creative_scoped_source_session/v3"
PROJECT = shared.PROJECT
DEFAULT_PROFILE = previous.DEFAULT_PROFILE
LIMITS = {"goal_plan": 3, "goal_audit": 4, "complete_script": 3, "full_review": 6}
TOTAL = 16
AUDITS = ("scope", "source", "commitment", "drama")
read, write, digest, sha = shared.read, shared.write, shared.digest, shared.sha
ANCESTRY_SCHEMAS = frozenset(("creative_single_scope_probe_spend_anchor/v2", "creative_legal_scope_probe_spend_anchor/v1",
    "creative_session_spend_anchor/v1"))


def verified_original_file(anchor, path):
    """Find a file in an already-verified typed ancestry, without full replay.

    Each traversed parent is still bound by both original file bytes and the
    canonical parent identity. This is not a replacement for _anchor's verifier.
    """
    path = Path(path).resolve(); path.relative_to(PROJECT)
    current, seen, proof = anchor, set(), []
    for _ in range(12):
        if current.get("schema") not in ANCESTRY_SCHEMAS or type(current.get("verified_files")) is not dict:
            raise ValueError("unsupported or incomplete verified parent ancestry")
        native = current["verified_files"].get(str(path))
        if native is not None:
            if type(native) is not dict or type(native.get("sha256")) is not str or sha(path) != native["sha256"]:
                raise ValueError("original file differs from verified ancestor bytes")
            return {"path": str(path), "sha256": native["sha256"], "parent_anchor_files": proof}
        parent = Path(current.get("parent_anchor_path", "")).resolve(); parent.relative_to(PROJECT)
        if str(parent) in seen: raise ValueError("cyclic parent ancestry")
        seen.add(str(parent)); binding = current["verified_files"].get(str(parent))
        if type(binding) is not dict or sha(parent) != binding.get("sha256"):
            raise ValueError("parent anchor original file hash is not bound")
        parent_value = read(parent)
        if digest(parent_value) != current.get("parent_anchor_sha256"):
            raise ValueError("parent anchor canonical identity changed")
        proof.append(str(parent)); current = parent_value
    raise ValueError("verified ancestry depth exceeded")


@dataclass(frozen=True)
class SessionConfig(shared.SessionConfig):
    profile_path: str = str(DEFAULT_PROFILE)
    goal_receipt_path: str = ""
    source_audit_receipt_path: str = ""
    root_observations_path: str = ""


class ScopedRuntime(shared.general_runtime.GoalContextRuntime):
    def __init__(self, *args, stage_limits=None, **kwargs):
        if stage_limits is not None and stage_limits != LIMITS:
            raise ValueError("exact scoped-source16-call policy required")
        super().__init__(*args, stage_limits=deepcopy(LIMITS), **kwargs)

    def _policy(self):
        value = super()._policy()
        value.update(schema=VERSION + "/runtime_policy", native_goal_audit_parts_per_plan=4,
            whole_plan_limit=1, whole_plan_lineage_limit=4, opening_setup_limit=2,
            total_new_calls_limit=TOTAL, source_transport="ordinary_exact_tool_local_contract")
        return value


class Session(shared.Session):
    version = VERSION

    def __init__(self, config, *, workflow_adapter=None, clarification_builder=None,
                 anchor_verifier=None, clock=shared.now, input_builder=shared.source.build_inputs,
                 source_gate=shared.source.verify_source_bundle, client_factory_builder=None):
        self.config = config if isinstance(config, SessionConfig) else SessionConfig(**config)
        self.root = Path(self.config.root).resolve(); self.root.relative_to(PROJECT)
        if self.root == PROJECT or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", self.config.grant_id):
            raise ValueError("independent root and safe grant required")
        if not re.fullmatch(r"[a-f0-9]{64}", self.config.anchor_sha256) or not self.config.round_key:
            raise ValueError("canonical latest parent and current repair round required")
        if not all((self.config.goal_receipt_path, self.config.source_audit_receipt_path, self.config.root_observations_path)):
            raise ValueError("explicit original native goal/source audit/observations required")
        self.wf = workflow_adapter or importlib.import_module("src.content_factory.creative_goal_context_workflow_v25")
        self.clarify = clarification_builder or importlib.import_module("src.content_factory.creative_known_native_clarification_v1").build_revision_inputs
        self.anchor_verifier = anchor_verifier or importlib.import_module("scripts.creative_single_scope_probe_spend_anchor_v2").verify_probe_spend_anchor
        self.clock, self.input_builder, self.source_gate = clock, input_builder, source_gate
        self.client_factory_builder = client_factory_builder or ordinary.make_client_factory
        self.claim = PROJECT / "data/creative_fresh_background_claims" / self.config.grant_id / "CLAIM.json"
        self.successor = PROJECT / "data/creative_consumption_successors" / self.config.anchor_sha256 / "CLAIM.json"

    known = staticmethod(previous.Session.known)

    def _anchor(self):
        anchor = read(self.config.anchor_path)
        verified = self.anchor_verifier(anchor, expected_anchor_sha256=self.config.anchor_sha256)
        if (digest(anchor) != self.config.anchor_sha256 or verified.get("verified") is not True
                or verified.get("inherited") != anchor.get("inherited")
                or anchor.get("schema") != "creative_single_scope_probe_spend_anchor/v2"
                or type(anchor.get("scope_probe_calls_used")) is not int or anchor["scope_probe_calls_used"] != 2
                or anchor.get("remaining_scope_probe_calls") != 0
                or type(anchor.get("whole_goal_candidates_used")) is not int or anchor["whole_goal_candidates_used"] != 3
                or anchor.get("terminal_status") != "diagnostic_completed_not_creative"
                or anchor.get("old_director_capacity") != {"used": 7, "limit": 7, "remaining": 0}):
            raise ValueError("settled successful626 diagnostic; same-source plans3/3 and diagnostic2/2 must be inherited")
        return anchor, verified

    def _seed(self, anchor):
        goal_path = Path(self.config.goal_receipt_path).resolve()
        audit_path = Path(self.config.source_audit_receipt_path).resolve()
        proofs = [verified_original_file(anchor, path) for path in (goal_path, audit_path)]
        goal, audit = read(goal_path), read(audit_path)
        pointer = anchor["latest_native_goal_receipt"]
        if (goal_path != Path(pointer["root"]) / pointer["receipt"] or goal["ordinal"] != pointer["ordinal"]
                or digest(goal["output"]) != pointer["native_goal_sha256"]):
            raise ValueError("clarification must use the verified latest complete original native goal")
        self.known(goal, "historical_goal"); self.known(audit, "historical_source")
        original_inputs_path = Path(pointer["root"]).resolve() / "INPUTS.json"
        original_inputs_path.relative_to(PROJECT)
        proofs.append(verified_original_file(anchor, original_inputs_path))
        return {"goal_receipt": goal, "audit_receipt": audit, "original_inputs": read(original_inputs_path),
            "original_inputs_path": str(original_inputs_path), "original_file_proofs": proofs,
            "observations": read(self.config.root_observations_path)}

    def _revision(self, inputs, anchor):
        seed = self._seed(anchor)
        if digest(inputs) != digest(seed["original_inputs"]):
            raise ValueError("current raw inputs differ from original verified same-source inputs")
        result = self.clarify(inputs, seed["goal_receipt"], seed["audit_receipt"], seed["observations"])
        if result["inputs"].get("previous_complete_document") != seed["goal_receipt"]["output"]:
            raise ValueError("full original native goal was changed or omitted")
        return {**result, "original_inputs_path": seed["original_inputs_path"], "original_file_proofs": seed["original_file_proofs"]}

    def preview(self):
        anchor, verified = self._anchor(); built = self._inputs(); self._profile_gate()
        revision = self._revision(built["inputs"], anchor)
        prepared = self.wf.prepare_goal_request(revision["inputs"], self.profile)
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        if payload.get("reference_fulltext") != built["inputs"]["reference_fulltext"]:
            raise ValueError("complete unchanged R01 required in actual request")
        return {"schema": VERSION + "/preview", "inputs": built["inputs"], "evidence": built["evidence"],
            "source_files": built["source_files"], "first_request": prepared, "clarification_manifest": revision["manifest"],
            "inputs_sha256": digest(built["inputs"]), "profile_sha256": sha(self.config.profile_path),
            "anchor_sha256": digest(anchor), "inherited": verified["inherited"],
            "parent_session_root": anchor["root"], "parent_identity": anchor["parent_identity"],
            "parent_identity_sha256": anchor["parent_identity_sha256"],
            "native_parent_goal_sha256": digest(read(self.config.goal_receipt_path)["output"]),
            "original_inputs_path": revision["original_inputs_path"],
            "original_file_proofs": revision["original_file_proofs"],
            "same_source_whole_plans_used": 3, "whole_plan_lineage_limit": 4, "whole_plans_remaining": 1,
            "stage_limits": LIMITS, "total_new_calls_limit": TOTAL, "provider_calls": 0,
            "media_calls": 0, "creative_quality_passed": False}

    def authorization_template(self, preview):
        return {"schema": VERSION + "/derived_authorization", "root": str(self.root), "grant_id": self.config.grant_id,
            "source_dir": str(Path(self.config.source_dir).resolve()), "inputs_sha256": preview["inputs_sha256"],
            "first_request_sha256": preview["first_request"]["request_sha256"], "profile_sha256": preview["profile_sha256"],
            "clarification_manifest_sha256": digest(preview["clarification_manifest"]),
            "anchor_sha256": self.config.anchor_sha256, "inherited": preview["inherited"],
            "parent_session_root": preview["parent_session_root"], "parent_identity": preview["parent_identity"],
            "parent_identity_sha256": preview["parent_identity_sha256"],
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "stage_limits": LIMITS, "total_new_calls_limit": TOTAL, "whole_plans_already_used": 3,
            "whole_plan_limit": 1, "whole_plan_lineage_limit": 4, "setup_limit": 2, "content_revision_limit": 2,
            "native_goal_audit_parts": 4, "shared_run_claim_protocol": shared.VERSION + "/run_claim",
            "source_transport": "ordinary_exact_tool_local_contract", "continuation_entry_kind": "known_native_author_clarification",
            "old_director_capacity": {"used": 7, "limit": 7, "remaining": 0},
            "media_authorized": False, "publish_authorized": False, "automatic_retry": False, "old_budget_reset": False}

    def _binding(self, anchor):
        return {"schema": VERSION + "/successor_claim", "anchor_sha256": self.config.anchor_sha256,
            "parent_session_root": anchor["root"], "parent_identity": anchor["parent_identity"],
            "parent_identity_sha256": anchor["parent_identity_sha256"], "root": str(self.root),
            "grant_id": self.config.grant_id, "authorization_sha256": sha(self.config.authorization_path),
            "whole_plans_already_used": 3, "whole_plan_lineage_limit": 4, "whole_plan_limit": 1, "old_budget_reset": False}

    def prepare(self):
        if self.root.exists() or self.claim.exists(): raise FileExistsError("existing root/grant cannot restart")
        preview = self.preview(); anchor, _ = self._anchor()
        successors = policy.successor_paths(PROJECT, anchor, self.config.anchor_sha256)
        if any(p.exists() for p in successors): raise FileExistsError("parent already has a successor; no scope regrant")
        if read(self.config.authorization_path) != self.authorization_template(preview):
            raise ValueError("exact reviewed independent16-call authorization required")
        closure = []
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name:
                path = Path(name).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / p) for p in ("scripts", "src")): closure.append(path)
        extras = [Path(__file__), PROJECT / "scripts/run_creative_scoped_source_session_v3.py", Path(self.wf.__file__),
            Path(self.config.profile_path), Path(self.config.anchor_path), Path(self.config.authorization_path),
            Path(self.config.goal_receipt_path), Path(self.config.source_audit_receipt_path), Path(self.config.root_observations_path),
            Path(preview["original_inputs_path"]),
            Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json", Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json"]
        ancestor_files = {p for proof in preview["original_file_proofs"] for p in proof["parent_anchor_files"]}
        files = {str(Path(p).resolve()): sha(p) for p in [*closure, *extras, *ancestor_files, *preview["source_files"], *self.config.extra_source_files]}
        binding = self._binding(anchor)
        for p in successors: policy.new_claim(p, binding)
        policy.new_claim(self.claim, {"schema": VERSION + "/claim", "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha(self.config.authorization_path), "old_budget_reset": False})
        self.root.mkdir(parents=True)
        for p in successors: files[str(p)] = sha(p)
        for name, value in (("SESSION_CONFIG", asdict(self.config)), ("INPUTS", preview["inputs"]),
                ("INPUT_EVIDENCE", preview["evidence"]), ("FIRST_REQUEST_PREVIEW", preview["first_request"]),
                ("CLARIFICATION_MANIFEST", preview["clarification_manifest"]), ("USER_SCOPE", read(self.config.authorization_path))):
            p = self.root / (name + ".json"); write(p, value, True); files[str(p)] = sha(p)
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "claim_sha256": sha(self.claim), "inherited": preview["inherited"], "inputs_sha256": preview["inputs_sha256"],
            "stage_limits": LIMITS, "total_new_calls_limit": TOTAL, "shared_run_claim_protocol": shared.VERSION + "/run_claim",
            "parent_successor_claim": {"path": str(successors[1]), "sha256": sha(successors[1]), "binding": binding}}, True)
        runtime = self.runtime(); runtime.prepare(); return self.state(runtime, "prepared")

    def _guard(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        if read(self.root / "SESSION_CONFIG.json") != json.loads(json.dumps(asdict(self.config))): raise ValueError("frozen config changed")
        for p, expected in freeze["files"].items():
            if sha(p) != expected: raise ValueError("frozen dependency changed: " + p)
        if sha(self.claim) != freeze["claim_sha256"]: raise ValueError("original grant claim changed")
        anchor, verified = self._anchor()
        if verified["inherited"] != freeze["inherited"]: raise ValueError("inherited consumption changed")
        for p in policy.successor_paths(PROJECT, anchor, self.config.anchor_sha256):
            if read(p) != self._binding(anchor): raise ValueError("unique successor changed")
        self.source_gate(self.config.source_dir, now=self.clock())
        if digest(self._inputs()["inputs"]) != freeze["inputs_sha256"]: raise ValueError("current source/input projection changed")

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return ScopedRuntime(PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            stage_limits=LIMITS, inherited_guard=self._guard, admission=self._admit,
            shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def invoke(self, runtime, label, prepared, validator):
        ordinary.expected_wire_request(prepared["request"])
        return policy.dispatch_claimed(runtime, label, prepared, validator, root=self.root, grant_id=self.config.grant_id,
            stage_limits=LIMITS, current_round_root=self.config.counter_root, current_round_key=self.config.round_key, guard=self._guard)

    def state(self, runtime, status, **details):
        value = shared.Session.state(self, runtime, status, **details)
        value.update(schema=VERSION + "/state", flow_version=VERSION, shared_state_protocol=shared.VERSION,
            shared_run_claim_protocol=shared.VERSION + "/run_claim", same_source_whole_plans_before=3, whole_plan_lineage_limit=4)
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha(self.root / "RUN_CLAIM.json")
        write(self.root / "STATE.json", value); return value

    def _receipt(self, ledger, label):
        rows = [r for r in ledger["calls"] if r["label"] == label]
        if len(rows) != 1: raise ValueError("exact prerequisite native receipt required: " + label)
        return read(self.root / rows[0]["receipt"])

    def _accepted(self, receipt, kind):
        self.known(receipt, kind); decision = receipt.get("validation")
        if type(decision) is not dict or decision.get("valid") is not True:
            raise shared.Halt("halt_goal_audit_contract_requires_diagnosis", audit_kind=kind)
        if kind == "scope":
            if decision.get("scope_ready_for_authority_review") is not True:
                raise shared.Halt("halt_goal_scope_requires_author_clarification", decision=decision)
        else:
            if decision.get("scope_challenges"): raise shared.Halt("halt_goal_scope_challenge", decision=decision)
            if decision.get("uncertainties"): raise shared.Halt("halt_goal_audit_uncertain", audit_kind=kind, decision=decision)
            if decision.get("accepted") is not True: raise shared.Halt("halt_goal_audit_rejected", audit_kind=kind, decision=decision)
        return receipt["output"]

    def _goal(self, ledger): return self.known(self._receipt(ledger, "whole_plan_04"), "whole_plan")

    def _audit_request(self, kind, inputs, goal, ledger):
        if kind == "scope": return self.wf.prepare_goal_scope_request(inputs, self.profile, goal)
        if kind == "source":
            native_scope = self._accepted(self._receipt(ledger, "scope_audit_04"), "scope")
            return self.wf.prepare_goal_scoped_source_request(inputs, self.profile, goal, native_scope)
        return getattr(self.wf, f"prepare_goal_{kind}_audit_request")(inputs, self.profile, goal)

    def _bundle(self, ledger, inputs, goal):
        reports = [self._accepted(self._receipt(ledger, kind + "_audit_04"), kind) for kind in AUDITS]
        bundle = self.wf.build_goal_audit_bundle(*reports)
        decision = self.wf.validate_goal_audit(bundle, goal, inputs=inputs)
        if decision.get("valid") is not True or decision.get("accepted") is not True:
            raise ValueError("all four current native planning audits must accept the identical goal and contexts")
        return bundle

    def _setup_native(self, ledger, goal):
        rows = [r for r in ledger["calls"] if r["label"].startswith("opening_setup_")]
        if not rows: raise ValueError("native opening setup required")
        native = self.known(read(self.root / rows[-1]["receipt"]), "opening_setup")
        self.wf.validate_opening_setup_document(native, goal); return native

    def _body_inputs(self, index, ledger, inputs):
        if index == 1: return deepcopy(inputs)
        previous_body = self._receipt(ledger, f"complete_script_{index-1:02}")
        native = self.known(previous_body, "previous_body", require_valid=False)
        if previous_body["status"] != "contract_valid": feedback = self._diagnosis(previous_body)
        else:
            documents, ordinals, failed = {}, {}, None
            for part in ("semantic", "physical"):
                receipt = self._receipt(ledger, f"full_review_{part}_{index-1:02}")
                documents[part] = self.known(receipt, "prior_full_review"); decision = receipt["validation"]
                self._review_stop(decision, self.root / "scripts", part, receipt["ordinal"])
                ordinals[part] = receipt["ordinal"]
                if decision["accepted"] is False: failed = decision; break
            if failed is None: raise ValueError("no known content failure permits another complete body")
            feedback = {"complete_same_source_part_review": failed, "native_part_reviews": documents, "native_review_ordinals": ordinals}
        return {**deepcopy(inputs), "previous_complete_document": native, "revision_diagnostics": feedback}

    def _expected(self, label, ledger):
        inputs = read(self.root / "INPUTS.json")
        if label == "whole_plan_04":
            if ledger["calls"]: raise ValueError("only one native plan4 is permitted; no plan5")
            return read(self.root / "FIRST_REQUEST_PREVIEW.json")
        goal = self._goal(ledger)
        if label.endswith("_audit_04"):
            kind = label.split("_")[0]; index = AUDITS.index(kind)
            for prior_kind in AUDITS[:index]: self._accepted(self._receipt(ledger, prior_kind + "_audit_04"), prior_kind)
            return self._audit_request(kind, inputs, goal, ledger)
        bundle = self._bundle(ledger, inputs, goal)
        if label.startswith("opening_setup_"):
            index = int(label[-2:]); rows = [r for r in ledger["calls"] if r["label"].startswith("opening_setup_")]
            if index != len(rows)+1: raise ValueError("ordered opening setup maximum2 required")
            current = deepcopy(inputs)
            if index == 2:
                receipt = self._receipt(ledger, "opening_setup_01"); native = self.known(receipt, "prior_setup", require_valid=False)
                if receipt["status"] == "contract_valid": raise ValueError("valid setup cannot be regenerated")
                current.update(previous_opening_setup=native, opening_setup_diagnostics=self._diagnosis(receipt))
            return self.wf.prepare_opening_setup_request(current, self.profile, goal)
        setup = self._setup_native(ledger, goal)
        if label.startswith("complete_script_"):
            index = int(label[-2:]); rows = [r for r in ledger["calls"] if r["label"].startswith("complete_script_")]
            if index != len(rows)+1: raise ValueError("ordered complete-native body maximum3 required")
            return self.wf.prepare_script_request(self._body_inputs(index, ledger, inputs), self.profile, goal, bundle,
                opening_setup=setup, **self.wf.origin_ids(inputs))
        _, _, part, suffix = label.split("_"); index = int(suffix)
        bodies = [r for r in ledger["calls"] if r["label"].startswith("complete_script_")]
        if index != len(bodies): raise ValueError("full review must bind latest native body")
        native = self.known(self._receipt(ledger, f"complete_script_{index:02}"), "review_body")
        if part == "physical":
            semantic = self._receipt(ledger, f"full_review_semantic_{index:02}"); self.known(semantic, "semantic")
            self._review_stop(semantic["validation"], self.root / "scripts", "semantic", semantic["ordinal"])
            if semantic["validation"]["accepted"] is not True: raise ValueError("physical review cannot follow failed semantic review")
        views = self.wf.compile_native_views(goal, setup, **self.wf.origin_ids(inputs))
        return self.wf.prepare_full_review_part_request(inputs, self.profile, native, views, part)

    def _admit(self, label, request, ledger):
        self._guard(); shared.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"]) >= TOTAL: raise ValueError("16-call scope exhausted")
        if not re.fullmatch(r"whole_plan_04|(?:scope|source|commitment|drama)_audit_04|opening_setup_0[12]|complete_script_0[123]|full_review_(?:semantic|physical)_0[123]", label):
            raise ValueError("exact one-plan4/four-review native stage required")
        if any(r["label"] == label for r in ledger["calls"]): raise ValueError("native stage already consumed")
        if request != self._expected(label, ledger)["request"]:
            raise ValueError("actual request differs from exact workflow25 stage/schema/source/native context")
        return True

    def _flow(self, runtime, inputs):
        prepared = self.wf.prepare_goal_request(self._revision(inputs, self._anchor()[0])["inputs"], self.profile)
        if prepared != read(self.root / "FIRST_REQUEST_PREVIEW.json"): raise ValueError("actual plan4 request differs from frozen preview")
        planned = self.invoke(runtime, "whole_plan_04", prepared, lambda v: self.wf.validate_goal_document(v, inputs=inputs))
        goal = self.known(planned, "whole_plan4", require_valid=False); folder = self.root / "goal/version_04"
        write(folder / "NATIVE_GOAL.json", goal, True)
        if planned["status"] != "contract_valid": raise shared.Halt("halt_plan4_contract_rejected_no_plan5", receipt_ordinal=planned["ordinal"])
        reports = {}
        for kind in AUDITS:
            ledger = read(runtime.ledger); prepared = self._audit_request(kind, inputs, goal, ledger)
            context = prepared.get("scope_context_sha256") if kind == "scope" else prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"]
            args = {"context_sha256": context}
            if kind in ("scope", "source"): args["inputs"] = inputs
            if kind == "source": args.update(native_scope=reports["scope"], authority_context=prepared["source_authority_context"])
            validator = getattr(self.wf, "validate_goal_" + ("scope" if kind == "scope" else kind + "_audit"))
            reviewed = self.invoke(runtime, kind + "_audit_04", prepared, lambda v, f=validator, a=args: f(v, goal, **a))
            native = self.known(reviewed, kind, require_valid=False); write(folder / (kind + "_native.json"), native, True)
            if reviewed["status"] != "contract_valid":
                write(folder / (kind + "_contract_diagnostics.json"), self._diagnosis(reviewed), True)
                raise shared.Halt("halt_goal_audit_contract_requires_diagnosis", audit_kind=kind, receipt_ordinal=reviewed["ordinal"])
            write(folder / (kind + "_decision.json"), reviewed["validation"], True)
            reports[kind] = self._accepted(reviewed, kind)
        bundle = self._bundle(read(runtime.ledger), inputs, goal)
        write(folder / "NATIVE_GOAL_AUDIT_BUNDLE.json", bundle, True)
        setup = driver.opening(self, runtime, inputs, goal)
        return driver.body(self, runtime, inputs, goal, bundle, setup, planned["ordinal"])

    def execution_evidence(self, runtime, inputs, goal_ordinal, script_ordinal, review_ordinals, *, views, compiled):
        # The frozen helper proves the three original audit roles, R01, original
        # tool arguments, compiler input and both full-native review inputs.
        value = previous.Session.execution_evidence(self, runtime, inputs, goal_ordinal, script_ordinal,
            review_ordinals, views=views, compiled=compiled)
        ledger = read(runtime.ledger); row = next(r for r in ledger["calls"] if r["label"] == "scope_audit_04")
        receipt = runtime.effective_receipt(row); self._accepted(receipt, "scope")
        directory = shared.evidence.verify_receipt_evidence(runtime, receipt, receipt["request"])
        if shared.io.strict_json((directory / "request_body.raw").read_text(encoding="utf-8")) != ordinary.expected_wire_request(receipt["request"]):
            raise ValueError("scope original raw wire differs")
        tool = receipt["response_payload"]["choices"][0]["message"]["tool_calls"]
        if len(tool) != 1 or tool[0]["function"]["name"] != ordinary.TOOL_NAME or shared.io.strict_json(tool[0]["function"]["arguments"]) != receipt["output"]:
            raise ValueError("scope native differs from original provider arguments")
        if receipt.get("source_binding_sha256") != digest(ledger["source_manifest"]):
            raise ValueError("scope native execution source identity changed")
        bundle = self._bundle(ledger, inputs, self._goal(ledger))
        value["native_receipts"].append({"ordinal": row["ordinal"], "receipt": row["receipt"], "receipt_sha256": row["receipt_sha256"],
            "request_sha256": receipt["request_sha256"], "native_output_sha256": digest(receipt["output"])})
        value.update(schema=VERSION + "/execution_requirements", native_planning_review_count=4,
            native_scope_receipt_path=str(self.root / row["receipt"]), native_scope_receipt_sha256=row["receipt_sha256"],
            native_scope_sha256=digest(receipt["output"]), current_four_review_bundle_sha256=digest(bundle),
            case_diagnostic_used_as_full_review=False, complete_current_four_review_bundle_verified=True)
        return value
