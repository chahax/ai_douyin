"""One remaining diagnostic call; the original v1 run is never restarted."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_goal_context_dispatch_v7 as runtime7
from scripts import creative_m31_flash_role_clients_v1 as clients
from scripts import creative_legal_scope_probe_v1 as first
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts import creative_single_scope_probe_spend_anchor_v2 as spend
from src.content_factory import creative_legal_speech_scope_v2 as scope
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "creative_single_scope_probe/v2"
PROJECT = Path(__file__).resolve().parents[1]
LIMITS = {"goal_plan": 0, "goal_audit": 1, "complete_script": 0, "full_review": 0}
LABELS = ["scope_cases_single_01"]
read, write, digest, sha_file, now = io.read, io.write, io.digest, io.sha_file, io.now
require = first.require


@dataclass(frozen=True)
class ProbeConfig:
    root: str
    parent_anchor_path: str
    parent_anchor_sha256: str
    blinded_cases_path: str
    private_expectations_path: str
    counter_root: str
    round_key: str
    grant_id: str
    authorization_path: str
    profile_path: str = str(first.DEFAULT_PROFILE)
    extra_source_files: tuple[str, ...] = ()


def prepared_request(blind, profile):
    built = scope.build_case_scope_context(blind); context = built["manifest"]["scope_context_sha256"]
    schema = scope.build_case_scope_schema(blind, context_sha256=context)
    request = {"stage": "goal_audit", "role": "director", "model": profile["director"]["model"],
        "parameters": {**profile["director"]["parameters"], **profile["stage_parameters"]["goal_audit"]},
        "messages": [{"role": "system", "content": scope.SCOPE_RULE}, {"role": "user", "content": json.dumps(built["payload"], ensure_ascii=False, separators=(",", ":"))}],
        "structured_schema": schema, "input_provenance": {"scope_context_sha256": context,
            "input_sha256": built["manifest"]["input_sha256"], "frame_kind": "case_batch", "diagnostic_only": True,
            "external_authorities_provided": False}}
    require(set(built["payload"]["blinded_cases"]) == {"schema", "cases"}
        and all(set(r) == {"source_ref", "text", "role_context"} for r in built["payload"]["blinded_cases"]["cases"]),
        "private expectations must never enter the diagnostic wire")
    return {"request": request, "request_sha256": digest(request), "wire": clients.expected_wire_request(request),
        "context_sha256": context, "manifest": built["manifest"], "expected_labels_in_wire": False,
        "provider_calls": 0, "server_strict_requested": False, "server_schema_guarantee": False, "creative_quality_passed": False}


def comparison_binding(parent, blind, private, profile, *, read_json=read):
    """Bind the controlled comparison to the verified parent's actual inputs."""
    parent_root = Path(parent["root"]).resolve()
    config = read_json(parent_root / "PROBE_CONFIG.json")
    prepared = read_json(parent_root / "PREPARED_PROBE.json")
    original_blind = read_json(config["blinded_cases_path"])
    original_private = read_json(config["private_expectations_path"])
    original_profile = read_json(config["profile_path"])
    original = prepared["requests"][0]["request"]
    payload = json.loads(original["messages"][1]["content"])
    require(payload.get("frame_kind") == "case_batch" and payload.get("blinded_cases") == original_blind == blind
        and original_private == private and original_profile == profile,
        "controlled comparison must preserve parent's exact blind cases, role context, private expectations and profile")
    request = prepared_request(blind, profile)["request"]
    require(original["model"] == request["model"] and original["parameters"] == request["parameters"]
        and original["role"] == request["role"] == "director" and original["stage"] == request["stage"] == "goal_audit",
        "controlled comparison changed actual model or parameters")
    return {"parent_original_case_request_sha256": digest(original), "blinded_input_sha256": digest(original_blind),
        "private_expectations_canonical_sha256": digest(original_private), "profile_canonical_sha256": digest(original_profile),
        "model": original["model"], "parameters_sha256": digest(original["parameters"]), "same_case_text_and_role_context": True,
        "same_private_gate": True, "same_model_and_parameters": True, "response_representation_changed_only": True}


def evaluate_cases(document, prepared, private):
    blind = json.loads(prepared["request"]["messages"][1]["content"])["blinded_cases"]
    first.validate_case_expectations(blind, private)
    decision = scope.validate_case_scope(document, blind, context_sha256=prepared["context_sha256"])
    mapping = private["blind_case_mapping"]; cases = {r["input"]["case_id"]: r for r in private["cases"]}
    results = []
    for row in blind["cases"]:
        ref = row["source_ref"]; expected = cases[mapping[ref]]["private_expectation"]
        act = decision["act_by_ref"][ref]; legal = act in ("L", "U")
        desired = expected["law_route"] == "legal_or_uncertain"
        correct = legal == desired and (not desired or act in {first.ACT_CODES[a] for a in expected["allowed_speech_acts"]})
        results.append({"source_ref": ref, "case_id": mapping[ref], "hard_gate": expected["hard_gate"],
            "native_speech_act": act, "actual_legal_route": legal, "assistant_preferred_legal_route": desired,
            "hard_routing_correct": correct if expected["hard_gate"] else None, "observational_only": not expected["hard_gate"],
            "native_record": deepcopy(document["records_by_ref"][ref])})
    hard = [r for r in results if r["hard_gate"]]
    return {"schema": VERSION + "/case_gate", "valid": True, "scope_native_sha256": digest(document),
        "hard_route_gate_passed": all(r["hard_routing_correct"] for r in hard), "hard_total": 17,
        "hard_correct": sum(r["hard_routing_correct"] for r in hard), "observational_total": 3,
        "results": results, "contract_decision": decision, "assistant_expectations_not_user_gold": True,
        "semantic_classification_proven": False, "legal_truth_proven": False, "creative_quality_passed": False}


class Probe:
    def __init__(self, config, *, parent_verifier=spend.verify_parent_anchor, client_factory_builder=None, clock=now):
        self.config = config if isinstance(config, ProbeConfig) else ProbeConfig(**config)
        self.root = spend.prior.session._inside(self.config.root, PROJECT)
        require(re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", self.config.grant_id)
            and re.fullmatch(r"[a-f0-9]{64}", self.config.parent_anchor_sha256) and bool(self.config.round_key), "safe explicit diagnostic identity required")
        self.parent_verifier = parent_verifier; self.client_factory_builder = client_factory_builder or clients.make_client_factory
        self.clock = clock
        self.claim = PROJECT / "data/creative_diagnostic_probe_claims" / self.config.grant_id / "CLAIM.json"

    def _parent(self):
        parent = read(self.config.parent_anchor_path)
        verified = self.parent_verifier(parent, expected_anchor_sha256=self.config.parent_anchor_sha256)
        require(verified.get("verified") is True and digest(parent) == self.config.parent_anchor_sha256
            and verified["inherited"] == parent["inherited"], "verified unchanged parent consumption required")
        require(type(parent.get("scope_probe_calls_used")) is int and parent["scope_probe_calls_used"] == 1,
            "exactly one of the original two diagnostic calls must remain")
        return parent, verified

    def prepare_preview(self):
        parent, verified = self._parent(); profile = first.validate_profile(read(self.config.profile_path))
        blind, private = read(self.config.blinded_cases_path), read(self.config.private_expectations_path)
        first.validate_case_expectations(blind, private)
        comparison = comparison_binding(parent, blind, private, profile)
        item = prepared_request(blind, profile)
        return {"schema": VERSION + "/preview", "requests": [item], "labels": LABELS, "inherited": verified["inherited"],
            "parent_identity": deepcopy(parent["parent_identity"]), "parent_identity_sha256": parent["parent_identity_sha256"],
            "scope_probe_calls_used": 1, "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 1,
            "same_source_whole_plans_used": parent["whole_goal_candidates_used"], "stage_limits": LIMITS,
            "new_deepseek_calls_limit": 1, "writer_calls_limit": 0, "full_goal_calls_limit": 0,
            "blinded_case_sha256": digest(blind), "private_expectations_sha256": sha_file(self.config.private_expectations_path),
            "response_protocol": scope.VERSION, "shared_execution_policy": policy.VERSION,
            "controlled_comparison": comparison,
            "provider_calls": 0, "media_calls": 0, "authorizes_new_dispatch": False, "creative_quality_passed": False}

    def authorization_template(self, preview):
        return {"schema": VERSION + "/scope", "root": str(self.root), "grant_id": self.config.grant_id,
            "inherited": preview["inherited"], "parent_anchor_sha256": self.config.parent_anchor_sha256,
            "parent_identity": preview["parent_identity"], "parent_identity_sha256": preview["parent_identity_sha256"],
            "request_sha256s": [preview["requests"][0]["request_sha256"]], "preview_canonical_sha256": digest(preview),
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "stage_limits": LIMITS, "scope_probe_calls_used": 1, "original_scope_probe_call_limit": 2,
            "remaining_scope_probe_calls": 1, "new_deepseek_calls_limit": 1, "writer_calls_limit": 0, "full_goal_calls_limit": 0,
            "response_protocol": scope.VERSION, "shared_execution_policy": policy.VERSION,
            "controlled_comparison": preview["controlled_comparison"],
            "hard_case_gate_total": 17, "observational_ambiguity_total": 3, "automatic_retry": False,
            "old_budget_reset": False, "media_authorized": False, "publish_authorized": False,
            "assistant_case_expectations_not_user_gold": True, "creative_quality_passed": False}

    def prepare(self):
        require(not self.root.exists() and not self.claim.exists(), "existing single probe cannot be prepared/restarted")
        preview = self.prepare_preview(); parent, _ = self._parent()
        require(read(self.config.authorization_path) == self.authorization_template(preview), "exact reviewed remaining-one-call scope required")
        canonical, parent_claim = policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256)
        require(not canonical.exists() and not parent_claim.exists(), "parent already consumed by another successor")
        code = []
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name:
                path = Path(name).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / p) for p in ("scripts", "src")): code.append(path)
        extra = [Path(__file__), Path(spend.__file__), Path(scope.__file__), Path(policy.__file__), Path(self.config.profile_path),
            Path(self.config.parent_anchor_path), Path(self.config.blinded_cases_path), Path(self.config.private_expectations_path),
            Path(self.config.authorization_path), Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json",
            Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json", *map(Path, self.config.extra_source_files)]
        files = {str(p.resolve()): sha_file(p) for p in [*code, *extra]}
        binding = self._binding(parent)
        for path in (canonical, parent_claim): policy.new_claim(path, binding)
        policy.new_claim(self.claim, {"schema": VERSION + "/claim", "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "old_budget_reset": False})
        self.root.mkdir(parents=True)
        for path in (canonical, parent_claim): files[str(path)] = sha_file(path)
        for name, value in (("PROBE_CONFIG", asdict(self.config)), ("PREPARED_PROBE", preview), ("USER_SCOPE", read(self.config.authorization_path))):
            path = self.root / (name + ".json"); write(path, value, True); files[str(path)] = sha_file(path)
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "claim_sha256": sha_file(self.claim), "inherited": preview["inherited"], "response_protocol": scope.VERSION,
            "shared_execution_policy": policy.VERSION}, True)
        runtime = self.runtime(); runtime.prepare()
        return self.state(runtime, "prepared")

    def _binding(self, parent):
        return {"schema": VERSION + "/successor_claim", "anchor_sha256": self.config.parent_anchor_sha256,
            "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"],
            "parent_identity_sha256": parent["parent_identity_sha256"], "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "scope_probe_calls_used": 1,
            "original_scope_probe_call_limit": 2, "remaining_scope_probe_calls": 1, "old_budget_reset": False}

    def _guard(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        require(freeze["schema"] == VERSION + "/freeze" and read(self.root / "PROBE_CONFIG.json") == json.loads(json.dumps(asdict(self.config))),
            "frozen single-probe config/version changed")
        for path, expected in freeze["files"].items(): require(sha_file(path) == expected, "frozen single-probe dependency changed: " + path)
        require(sha_file(self.claim) == freeze["claim_sha256"], "original grant claim changed")
        parent, verified = self._parent(); require(verified["inherited"] == freeze["inherited"], "parent consumption changed")
        for path in policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256):
            require(read(path) == self._binding(parent), "dual successor claim identity changed")

    def _admit(self, label, request, ledger):
        self._guard(); CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        item = read(self.root / "PREPARED_PROBE.json")["requests"][0]
        require(not ledger["calls"] and label == LABELS[0] and request == item["request"]
            and request["stage"] == "goal_audit" and request["role"] == "director", "only the one original remaining case diagnostic is authorized")
        return True

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return runtime7.GoalContextRuntime(PROJECT, self.root, list(freeze["files"]), freeze["inherited"],
            profile=first.validate_profile(read(self.config.profile_path)), stage_limits=LIMITS, inherited_guard=self._guard,
            admission=self._admit, shared_lock=PROJECT / "data/creative_diagnostic_probe_claims/DISPATCH.lock",
            quota_state=None, client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        try:
            if runtime is None: raise ValueError("runtime not constructed; spend not verified")
            summary = runtime.summary(); pending = False; error = None
        except Exception as exc: summary = None; pending = True; error = {"type": type(exc).__name__, "message": str(exc)}
        value = {"schema": VERSION + "/state", "status": status, "updated_at": self.clock(), "spend": summary,
            "spend_verification_pending": pending, "text_ready_for_director": False, "creative_quality_passed": False,
            "media_authorized": False, "diagnostic_only": True, "scope_probe_calls_inherited": 1,
            "original_scope_probe_call_limit": 2, **details}
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha_file(self.root / "RUN_CLAIM.json")
        if pending: value["spend_error"] = error
        write(self.root / "STATE.json", value); return value

    def run(self):
        require(not (self.root / "RUN_CLAIM.json").exists(), "original RUN_CLAIM exists; never restart")
        policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "grant_id": self.config.grant_id, "prepared_sha256": sha_file(self.root / "PREPARED_PROBE.json"),
            "pid": os.getpid(), "started_at": self.clock(), "automatic_restart": False})
        runtime = None
        try:
            runtime = self.runtime(); require(not read(runtime.ledger)["calls"], "nonempty original ledger cannot restart")
            item = read(self.root / "PREPARED_PROBE.json")["requests"][0]; blind = read(self.config.blinded_cases_path)
            receipt = policy.dispatch_claimed(runtime, LABELS[0], item,
                lambda output: scope.validate_case_scope(output, blind, context_sha256=item["context_sha256"]),
                root=self.root, grant_id=self.config.grant_id, stage_limits=LIMITS,
                current_round_root=self.config.counter_root, current_round_key=self.config.round_key, guard=self._guard)
            meta = receipt.get("response_metadata", {})
            known = type(meta.get("total_tokens")) is int and meta["total_tokens"] >= 0 and meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop", "tool_calls")
            if not known: return self.state(runtime, "halt_interface_or_unknown", receipt_ordinal=receipt["ordinal"], automatic_retry=False)
            if receipt["status"] == "interface_rejected": return self.state(runtime, "halt_protocol_requires_diagnosis", receipt_ordinal=receipt["ordinal"])
            if receipt["status"] != "contract_valid": return self.state(runtime, "halt_case_contract_rejected", receipt_ordinal=receipt["ordinal"])
            ledger = read(runtime.ledger)
            spend.prior.verify_known_receipt(self.root, ledger["calls"][0], ledger["source_manifest"], spend.prior.session.Reader())
            gate = evaluate_cases(receipt["output"], item, read(self.config.private_expectations_path))
            write(self.root / "CASE_GATE.json", gate, True)
            return self.state(runtime, "diagnostic_completed_not_creative" if gate["hard_route_gate_passed"] else "halt_case_routing_mismatch",
                receipt_ordinal=receipt["ordinal"], hard_case_gate=gate)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"error_type": type(exc).__name__, "error": str(exc), "automatic_retry": False}, True)
            self.state(runtime, "halt_execution_reconciliation", error_type=type(exc).__name__, error=str(exc)); raise


def prepare_preview(config, **dependencies): return Probe(config, **dependencies).prepare_preview()
