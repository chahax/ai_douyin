"""Independent, bounded v28 live caller. Import/preview never dispatches.

The previously tested pure stage driver is reused explicitly. SDK calls, durable
claims, current admission and the final raw-receipt handoff belong to this entry;
none of the frozen sessions, runtimes, budgets or mock flags are rewritten.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import importlib
import json
import os
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_goal_context_dispatch_v7 as runtime7
from scripts import creative_m31_flash_role_clients_v1 as clients
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts import creative_session_spend_anchor_v1 as evidence
from scripts import creative_world_scene_text_driver_v1 as stages
from scripts.creative_fresh_source_session_v1 import Session as NativeSession, Halt
from src.content_factory import creative_goal_context_workflow_v28 as workflow
from src.content_factory import creative_fresh_source_inputs_v1 as source
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "creative_world_scene_live_session/v1"
LIMITS = {"goal_plan": 5, "goal_audit": 12, "complete_script": 3, "full_review": 6}
TOTAL = 26
DIRECTOR = {"used": 7, "limit": 7, "remaining": 0}
read, write, digest, sha, now = io.read, io.write, io.digest, io.sha_file, io.now


def _inside(path):
    path = Path(path).resolve()
    if path == PROJECT or not path.is_relative_to(PROJECT): raise ValueError("independent project path required")
    return path


def _hashes(files):
    return {str(_inside(path)): sha(path) for path in files}


class Runtime(runtime7.GoalContextRuntime):
    def __init__(self, *args, stage_limits=None, **kwargs):
        if stage_limits is not None and stage_limits != LIMITS: raise ValueError("exact independent26-call policy required")
        super().__init__(*args, stage_limits={k: min(v, runtime7.LIMIT_CEILINGS[k]) for k, v in LIMITS.items()}, **kwargs)
        self.stage_limits = deepcopy(LIMITS)

    def _policy(self):
        result = super()._policy()
        result.update(schema=VERSION + "/runtime_policy", whole_plan_limit=3, opening_setup_limit=2,
            native_goal_audit_parts_per_plan=4, full_review_parts_per_complete_script=2,
            total_new_calls_limit=TOTAL, old_director_capacity=DIRECTOR, media_authorized=False)
        return result


@dataclass(frozen=True)
class Config:
    root: str
    grant_id: str
    parent_anchor_path: str
    parent_anchor_sha256: str
    source_dir: str
    preferences_path: str
    user_goals_path: str
    profile_path: str
    authorization_path: str
    counter_root: str
    round_key: str
    extra_source_files: tuple = ()
    review_admission_module: str = "scripts.creative_world_scene_review_admission_v1"


class ReviewWorkflow:
    """Explicit review injection, with unchanged full native v28 compilation."""
    def __init__(self, base, adapter): self.base, self.adapter = base, adapter
    def __getattr__(self, key): return getattr(self.base, key)
    def full_reviews(self): return self.adapter
    def prepare_script_request(self, inputs, *args, **kwargs):
        current, projection = compile_revision_feedback(inputs)
        feedback_keys = ("previous_complete_document", "revision_diagnostics")
        supplied = [key in current for key in feedback_keys]
        if not any(supplied): return self.base.prepare_script_request(current, *args, **kwargs)
        if not all(supplied): raise ValueError("complete original draft and native feedback must be paired")
        clean = {key: deepcopy(value) for key, value in current.items() if key not in feedback_keys}
        # Origin/schema/audit lookups belong to the stable authority. They must
        # not accidentally apply the smaller goal-plan budget to a complete
        # screenplay and its full native review feedback.
        result = self.base.prepare_script_request(clean, *args, **kwargs)
        views = result["views"]; goal = views["goal"]
        staged = self.base.legacy.base_requests._context("complete_script", {
            **self.base.prior._planning_authority_inputs(current), "native_goal_document": goal,
            "brief": views["brief"], "creative_scene_plan": views["plan"]})
        payload = json.loads(result["request"]["messages"][1]["content"])
        for key in self.base.world.CORE_KEYS: payload[key] = deepcopy(staged["payload"][key])
        for key in feedback_keys: payload[key] = deepcopy(current[key])
        if self.base.contexts._reference_occurrences(payload, current["reference_fulltext"]) != 1:
            raise ValueError("full current R01 must occur once in the actual repair writer request")
        result["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        result["request"]["input_provenance"]["context_sha256"] = digest(payload)
        result["manifest"].update(context_sha256=digest(payload), raw_inputs_sha256=digest(current),
            ownership_projected_inputs_sha256=digest(self.base.project_inputs(current)),
            stage_projected_core_sha256=digest({key: payload[key] for key in self.base.world.CORE_KEYS}),
            writer_stage_projection_manifest=deepcopy(staged["manifest"]),
            preserved_feedback_identity={key + "_sha256": digest(current[key]) for key in feedback_keys},
            stable_authority_inputs_sha256=digest(clean), origin_lookup_received_writer_feedback=False,
            complete_writer_context_budget_enforced=True,
            live_revision_feedback_compilation=projection)
        return self.base._mark(result, current)
    def prepare_full_review_part_request(self, inputs, profile, native, views, part):
        self.base._verify_views(inputs, views)
        compiled = self.base.validate_script_document(native, views, inputs["production_preferences"])["script"]
        result = self.adapter.prepare_full_review_part_request(inputs, profile, native,
            {**deepcopy(views), "compiled_script": compiled}, part)
        return self.base._mark(result, inputs)


def compile_revision_feedback(inputs):
    """Project derived review metadata only; keep every native document exact.

    Native reports remain once in native_part_reviews/native_review_bundle.
    The failed service receipt retains the complete original outer and
    underlying decisions. This functional feedback is a labelled compilation,
    never a rewritten native review or an acceptance decision.
    """
    current = deepcopy(inputs); diagnostics = current.get("revision_diagnostics")
    if type(diagnostics) is not dict: return current, None
    changes = {}
    headers = ("valid", "accepted", "status", "part", "revision_target", "requires_new_goal_plan",
        "revision_dispatch_blocked", "full_review_protocol_version", "split_review_contract_version", "native_version",
        "native_part_sha256", "native_bundle_sha256", "native_script_sha256", "compiled_script_sha256",
        "native_prior_story_scope_sha256", "original_native_source_sha256", "native_context_sha256",
        "review_admission_version", "content_checks_satisfied", "new_scope_admitted", "new_scope_revision_admitted",
        "new_scope_requires_new_goal_plan", "admission_user_scope_sha256", "admission_inputs_sha256",
        "inherited_prior_scope_sha256")
    for key in ("complete_same_source_part_review", "complete_same_source_full_review_bundle"):
        original = diagnostics.get(key)
        if (type(original) is not dict or original.get("review_admission_version") != "creative_world_scene_review_admission/v1"
                or type(original.get("underlying_v6_decision")) is not dict): continue
        if any(type(original.get(field)) is not list for field in ("findings", "uncertainties")):
            raise ValueError("typed derived review feedback required before compilation")
        projection = {field: deepcopy(original[field]) for field in headers if field in original}
        for field in ("findings", "uncertainties"):
            seen = set(); projection[field] = []
            for row in original[field]:
                identity = digest(row)
                if identity not in seen: projection[field].append(deepcopy(row)); seen.add(identity)
        projection.update(feedback_compilation_version=VERSION + "/functional_review_feedback",
            original_derived_decision_sha256=digest(original),
            underlying_v6_decision_sha256=digest(original["underlying_v6_decision"]),
            complete_original_review_is_in_native_report_field=True, native_review_modified=False)
        diagnostics[key] = projection
        changes[key] = {"original_derived_decision_sha256": digest(original), "projected_feedback_sha256": digest(projection),
            "underlying_v6_decision_sha256": digest(original["underlying_v6_decision"]),
            "omitted_derived_fields": sorted(set(original) - set(projection)),
            "original_characters": len(json.dumps(original, ensure_ascii=False, separators=(",", ":"))),
            "projected_characters": len(json.dumps(projection, ensure_ascii=False, separators=(",", ":")))}
    if not changes: return current, None
    for key in ("native_part_reviews", "native_review_bundle"):
        if current["revision_diagnostics"].get(key) != inputs["revision_diagnostics"].get(key):
            raise ValueError("feedback compilation changed a complete native report")
    if current.get("previous_complete_document") != inputs.get("previous_complete_document"):
        raise ValueError("feedback compilation changed the complete native draft")
    return current, {"schema": VERSION + "/feedback_compilation_manifest", "changes": changes,
        "original_revision_diagnostics_sha256": digest(inputs["revision_diagnostics"]),
        "compiled_revision_diagnostics_sha256": digest(current["revision_diagnostics"]),
        "previous_complete_document_sha256": digest(inputs.get("previous_complete_document")),
        "native_reports_preserved_by_value": True, "native_response_rewritten": False,
        "context_budget_increased": False}


def _decision(receipt):
    value = receipt.get("validation")
    if type(value) is dict and type(value.get("valid")) is bool: return deepcopy(value)
    if receipt.get("status") != "contract_rejected": raise ValueError("typed native validation missing")
    return {"valid": False, "findings": [{"code": "KNOWN_NATIVE_CONTRACT_REJECTION",
        "original_failure": deepcopy(receipt.get("failure")),
        "original_validation_error": deepcopy(receipt.get("validation_error"))}],
        "native_output_modified": False}


class LiveDriver(stages.Driver):
    def __init__(self, session, runtime, inputs, wf):
        super().__init__(inputs, session.profile, {}, workflow=wf)
        self.session, self.runtime = session, runtime

    @staticmethod
    def audit_gate(decision, stage):
        if (type(decision) is dict and decision.get("valid") is True
                and decision.get("new_scope_admitted") is True and decision.get("content_checks_satisfied") is True
                and decision.get("findings") == [] and decision.get("uncertainties") == []):
            return True
        if (type(decision) is dict and decision.get("valid") is True
                and (decision.get("new_scope_revision_admitted") is True or decision.get("new_scope_requires_new_goal_plan") is True)
                and type(decision.get("findings")) is list and decision["findings"]
                and decision.get("uncertainties") == []):
            # The underlying old-scope halt is retained verbatim. Only the
            # explicitly admitted script/plan route applies to the new scope.
            return False
        return stages.Driver.audit_gate(decision, stage)

    def invoke(self, label, prepared, validator):
        session, rt = self.session, self.runtime
        ledger = read(rt.ledger)
        if any(row["label"] == label for row in ledger["calls"]): raise Halt("halt_duplicate_live_stage", label=label)
        intent = {"schema": VERSION + "/call_intent", "label": label, "prepared": deepcopy(prepared),
            "request_sha256": digest(prepared["request"]), "ledger_prefix_sha256": digest(ledger["calls"]),
            "prerequisite_receipts": [{"ordinal": row["ordinal"], "label": row["label"],
                "receipt": row["receipt"], "sha256": row["receipt_sha256"]} for row in ledger["calls"]],
            "inputs_sha256": digest(self.inputs), "automatic_retry": False}
        path = session.root / "call_intents" / (label + ".json")
        write(path, intent, True)
        # The locked admission sees this exact trusted-builder intent, bound
        # to the original ledger prefix; it never accepts an arbitrary request.
        session.pending_intent = {"path": str(path), "sha256": sha(path), "label": label}
        receipt = policy.dispatch_claimed(rt, label, prepared, validator, root=session.root,
            grant_id=session.config.grant_id, stage_limits=LIMITS,
            current_round_root=session.config.counter_root, current_round_key=session.config.round_key,
            guard=session._guard)
        row = {"label": label, "receipt": f"call_{receipt['ordinal']:03}_{label}.json",
            "ordinal": receipt["ordinal"], "prepared": deepcopy(prepared), "status": receipt["status"],
            "request_sha256": receipt["request_sha256"], "provider_result_is_actual_receipt": True}
        self.calls.append(row)
        try: native = NativeSession.known(receipt, label, require_valid=False)
        except Halt:
            if (receipt.get("failure") or {}).get("code") == "REQUIRED_TOOL_MISSING":
                raise Halt("halt_required_tool_missing_format_recovery_requires_registration", receipt_ordinal=receipt["ordinal"])
            raise
        checked = _decision(receipt)
        row.update(native_output=deepcopy(native), validation=deepcopy(checked))
        return native, checked, row


class Session:
    def __init__(self, config, *, parent_verifier=None, input_builder=source.build_inputs,
                 source_gate=source.verify_source_bundle, client_factory_builder=None,
                 review_adapter=None, clock=now):
        self.config = config if isinstance(config, Config) else Config(**config)
        self.root = _inside(self.config.root)
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", self.config.grant_id): raise ValueError("safe new grant required")
        if not re.fullmatch(r"[a-f0-9]{64}", self.config.parent_anchor_sha256) or not self.config.round_key:
            raise ValueError("canonical latest640 and current round required")
        self.parent_verifier = parent_verifier
        self.input_builder, self.source_gate, self.clock = input_builder, source_gate, clock
        self.client_factory_builder = client_factory_builder or clients.make_client_factory
        self.injected_review_adapter = review_adapter
        self.claim = PROJECT / "data/creative_fresh_background_claims" / self.config.grant_id / "CLAIM.json"
        self.pending_intent = None

    @property
    def profile(self): return read(self.config.profile_path)

    @classmethod
    def open(cls, root, **dependencies): return cls(read(Path(root) / "SESSION_CONFIG.json"), **dependencies)

    def _parent(self):
        anchor = read(self.config.parent_anchor_path)
        verifier = self.parent_verifier or importlib.import_module("scripts.creative_world_scene_spend_anchor_v1").verify_anchor
        checked = verifier(anchor, expected_anchor_sha256=self.config.parent_anchor_sha256)
        if (digest(anchor) != self.config.parent_anchor_sha256 or checked.get("verified") is not True
                or checked.get("inherited") != anchor.get("inherited")
                or anchor["inherited"] != {"calls_started": 640, "reported_tokens": 13544245,
                    "calls_with_known_usage": 638, "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
                or anchor.get("parent_identity", {}).get("end_ordinal") != 640):
            raise ValueError("exact latest settled640 accounting required; old candidate scope is not regranted")
        return anchor, checked

    def _inputs(self):
        return self.input_builder(self.config.source_dir, self.config.preferences_path,
            self.config.user_goals_path, now=self.clock())

    def _profile_gate(self):
        p = self.profile
        expected = {"writer": {"provider": "minimax", "model": clients.WRITER_MODEL, "base_url": clients.WRITER_BASE_URL,
            "parameters": {"temperature": .4, "thinking": "adaptive", "reasoning_effort": "medium", "max_completion_tokens": 16000}},
            "director": {"provider": "deepseek", "model": clients.REVIEW_MODEL, "base_url": "https://api.deepseek.com/v1",
                "parameters": {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 12000}}}
        if any(p.get(role) != value for role, value in expected.items()) or p.get("stage_parameters") != {
                "goal_audit": {"max_completion_tokens": 16000}, "full_review": {"max_completion_tokens": 32000}}:
            raise ValueError("unchanged official models and exact role/stage parameters required")
        # Mapping every real prepared request subsequently verifies all exact
        # models/endpoints, .4/thinking/output limits without creating a client.
        return p

    def _reviews(self, scope):
        if self.injected_review_adapter is not None: return self.injected_review_adapter
        if self.config.review_admission_module == "src.content_factory.creative_full_review_protocol_v6":
            return workflow.full_reviews()
        if self.config.review_admission_module != "scripts.creative_world_scene_review_admission_v1":
            raise ValueError("explicit reviewed admission adapter required")
        module = importlib.import_module(self.config.review_admission_module)
        return module.make_review_adapter(scope, expected_user_scope_sha256=digest(scope),
            prior_story_scope=read(self.root / "INPUTS.json")["production_preferences"].get("prior_story_scope"),
            expected_root=str(self.root), expected_inputs_sha256=digest(read(self.root / "INPUTS.json")))

    def code_files(self):
        # Actual local import closure, not every historical frozen source tree.
        importlib.import_module(self.config.review_admission_module)
        paths = {Path(__file__).resolve(), Path(workflow.__file__).resolve()}
        for module in tuple(sys.modules.values()):
            raw = getattr(module, "__file__", None)
            if raw:
                path = Path(raw).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / directory) for directory in ("src", "scripts")):
                    paths.add(path)
        return sorted(paths)

    def preview(self):
        parent, checked = self._parent(); built = self._inputs(); self._profile_gate()
        first = workflow.prepare_goal_request(built["inputs"], self.profile)
        clients.expected_wire_request(first["request"])
        files = _hashes([*built["source_files"], self.config.parent_anchor_path, self.config.profile_path,
            self.config.preferences_path, self.config.user_goals_path, *self.config.extra_source_files, *self.code_files()])
        for path, item in checked.get("source_files", {}).items():
            expected = item.get("sha256") if type(item) is dict else item
            if sha(_inside(path)) != expected: raise ValueError("certified parent original file changed")
            files[str(_inside(path))] = expected
        value = {"schema": VERSION + "/preview", "root": str(self.root), "grant_id": self.config.grant_id,
            "inputs": built["inputs"], "input_evidence": built["evidence"], "first_request": first,
            "inputs_sha256": digest(built["inputs"]), "profile_sha256": sha(self.config.profile_path),
            "parent_anchor_sha256": digest(parent), "inherited": checked["inherited"],
            "parent_root": parent["root"], "parent_identity": parent["parent_identity"],
            "source_files": files, "stage_limits": LIMITS, "total_new_calls_limit": TOTAL,
            "provider_calls": 0, "media_calls": 0, "old_budget_reset": False}
        value["preparation_identity_sha256"] = digest({k: value[k] for k in (
            "root", "grant_id", "inputs_sha256", "profile_sha256", "parent_anchor_sha256", "inherited", "source_files", "first_request")})
        return value

    def authorization_template(self, preview):
        return {"schema": VERSION + "/derived_authorization", "root": str(self.root), "grant_id": self.config.grant_id,
            "preparation_identity_sha256": preview["preparation_identity_sha256"], "inherited": preview["inherited"],
            "inputs_sha256": preview["inputs_sha256"],
            "parent_anchor_sha256": self.config.parent_anchor_sha256, "stage_limits": LIMITS,
            "total_new_calls_limit": TOTAL, "whole_plan_limit": 3, "opening_setup_limit": 2,
            "content_revision_limit": 2, "text_same_story_allowed": True, "new_director_scope_limit": 3,
            "prior_scope_sha256": digest(preview["inputs"]["production_preferences"].get("prior_story_scope")),
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "old_director_capacity": DIRECTOR, "old_body_scope_exhausted_and_preserved": True,
            "new_authority": "user20261015 real-interface test; reviewed text then one test video under separate production scope",
            "automatic_retry": False, "old_budget_reset": False, "media_authorized": False, "publish_authorized": False}

    def _binding(self, parent):
        return {"schema": VERSION + "/successor_claim", "anchor_sha256": self.config.parent_anchor_sha256,
            "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"],
            "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha(self.config.authorization_path), "old_budget_reset": False}

    def prepare(self):
        if self.root.exists() or self.claim.exists(): raise FileExistsError("existing root/grant cannot restart")
        preview = self.preview(); parent, _ = self._parent(); binding = self._binding(parent)
        if read(self.config.authorization_path) != self.authorization_template(preview): raise ValueError("reviewed independent authorization differs")
        successors = policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256)
        if any(p.exists() for p in successors): raise ValueError("latest640 already has a unique successor")
        self.root.mkdir(parents=True, exist_ok=False)
        for name, value in (("SESSION_CONFIG", asdict(self.config)), ("INPUTS", preview["inputs"]),
                ("INPUT_EVIDENCE", preview["input_evidence"]), ("FIRST_REQUEST_PREVIEW", preview["first_request"]),
                ("USER_SCOPE", read(self.config.authorization_path))): write(self.root / (name + ".json"), value, True)
        policy.new_claim(self.claim, {**binding, "schema": VERSION + "/grant_claim"})
        for path in successors: policy.new_claim(path, binding)
        files = {**preview["source_files"], **_hashes([self.config.authorization_path, self.claim, *successors,
            *(self.root / (name + ".json") for name in ("SESSION_CONFIG", "INPUTS", "INPUT_EVIDENCE", "FIRST_REQUEST_PREVIEW", "USER_SCOPE")),
            Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json",
            Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json"])}
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "inputs_sha256": preview["inputs_sha256"], "inherited": preview["inherited"], "binding": binding,
            "successor_claim_paths": [str(p) for p in successors], "claim_sha256": sha(self.claim),
            "stage_limits": LIMITS, "old_director_capacity": DIRECTOR}, True)
        rt = self.runtime(); rt.prepare()
        return self.state(rt, "prepared")

    def _guard(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        if freeze.get("schema") != VERSION + "/freeze" or freeze.get("stage_limits") != LIMITS:
            raise ValueError("original independent freeze/policy differs")
        if digest(asdict(self.config)) != digest(read(self.root / "SESSION_CONFIG.json")):
            raise ValueError("calling config differs from the original frozen run/round/source binding")
        for path, expected in freeze["files"].items():
            if sha(_inside(path)) != expected: raise ValueError("frozen dependency changed: " + path)
        if sha(self.claim) != freeze["claim_sha256"]: raise ValueError("grant claim changed")
        for path in freeze["successor_claim_paths"]:
            if read(path) != freeze["binding"]: raise ValueError("original unique parent successor differs")
        gate = self.source_gate(self.config.source_dir, now=self.clock())
        if gate.get("valid") is not True or gate.get("current_source_freshness_verified") is not True:
            raise ValueError("current actual source gate must explicitly pass")
        return True

    def _admit(self, label, request, ledger):
        self._guard(); CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        if len(ledger["calls"]) >= TOTAL: raise ValueError("26-call independent scope exhausted")
        if not re.fullmatch(r"whole_plan_0[123]|(?:scope|source|commitment|drama)_audit_0[123]|opening_setup_0[12]|complete_script_0[123]|full_review_(?:semantic|physical)_0[123]", label):
            raise ValueError("unregistered native stage label")
        expected_stage = ("goal_plan" if label.startswith(("whole_plan_", "opening_setup_")) else
            "goal_audit" if "_audit_" in label else "complete_script" if label.startswith("complete_script_") else "full_review")
        if request.get("stage") != expected_stage: raise ValueError("label belongs to another native stage")
        pending = self.pending_intent
        if not pending or pending["label"] != label or sha(pending["path"]) != pending["sha256"]:
            raise ValueError("exact trusted-builder call intent missing or changed")
        intent = read(pending["path"])
        if (request != intent["prepared"]["request"] or digest(request) != intent["request_sha256"]
                or intent["ledger_prefix_sha256"] != digest(ledger["calls"])
                or intent["inputs_sha256"] != read(self.root / "PRODUCTION_FREEZE.json")["inputs_sha256"]):
            raise ValueError("actual request or native prerequisites differ from builder intent")
        clients.expected_wire_request(request)
        return True

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return Runtime(PROJECT, self.root, list(freeze["files"]), freeze["inherited"], profile=self.profile,
            stage_limits=LIMITS, inherited_guard=self._guard, admission=self._admit,
            shared_lock=PROJECT / "data/creative_fresh_background_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        value = NativeSession.state(self, runtime, status, **details)
        value.update(schema=VERSION + "/state", flow_version=VERSION, text_ready_for_director=status == "text_ready_for_director")
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha(self.root / "RUN_CLAIM.json")
        write(self.root / "STATE.json", value)
        return value

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

    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file(): raise ValueError("separately prepared root required")
        if (self.root / "RUN_CLAIM.json").exists(): raise FileExistsError("original RUN_CLAIM exists; no restart")
        rt = None
        policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "started_at": self.clock(),
            "pid": os.getpid(), "automatic_restart": False, "freeze_sha256": sha(self.root / "PRODUCTION_FREEZE.json")})
        try:
            rt = self.runtime(); self._guard(); CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if read(rt.ledger)["calls"]: raise ValueError("nonempty original ledger cannot restart")
            inputs = read(self.root / "INPUTS.json")
            wf = ReviewWorkflow(workflow, self._reviews(read(self.root / "USER_SCOPE.json")))
            driver = LiveDriver(self, rt, inputs, wf)
            goal, bundle = driver._planning(); setup = driver._opening(goal)
            result = driver._body(goal, bundle, setup)
            return self._save_text(result, driver, rt)
        except (Halt, stages.OfflineStop) as stop:
            return self.state(rt, stop.status.replace("halt_mock_", "halt_live_"), **stop.details)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_restart": False}, True)
            return self.state(rt, "halt_execution_reconciliation", exception_type=type(exc).__name__, error=str(exc))


def _receipt_identity(root, row):
    path = root / row["receipt"]; receipt = read(path)
    intent = root / "call_intents" / (row["label"] + ".json")
    return {"path": str(path), "file_sha256": sha(path), "ordinal": row["ordinal"], "label": row["label"],
        "request_sha256": receipt["request_sha256"], "raw_response_sha256": receipt["response_metadata"]["raw_body_sha256"],
        "intent_path": str(intent), "intent_file_sha256": sha(intent)}


def _require_accepted(decision, stage):
    if not LiveDriver.audit_gate(decision, stage):
        raise ValueError("original native review does not accept this handoff: " + stage)


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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization", "prepare", "run", "status", "verify"))
    parser.add_argument("--config"); parser.add_argument("--root"); parser.add_argument("--output")
    args = parser.parse_args()
    session = Session(read(args.config)) if args.config else Session.open(args.root)
    if args.action == "preview": result = session.preview()
    elif args.action == "authorization": result = session.authorization_template(session.preview())
    elif args.action == "prepare": result = session.prepare()
    elif args.action == "run": result = session.run()
    elif args.action == "verify": result = verify_text_handoff(session.root)
    else: result = read(session.root / "STATE.json")
    if args.output:
        write(args.output, result, True)
        print(json.dumps({"path": str(Path(args.output).resolve()), "canonical_sha256": digest(result), "status": result.get("status")}, ensure_ascii=False))
    else: print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
