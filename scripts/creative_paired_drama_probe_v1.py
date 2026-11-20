"""One explicitly granted live paired-drama diagnostic; no authoring or media.

Preview is read-only. Prepare/run are separate commands. Parent verification is
historical; current source and counted-round admission remain dispatch gates.
"""
from __future__ import annotations

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
from scripts import creative_scope_probe_execution_policy_v1 as policy
from scripts import creative_scoped_session_spend_anchor_v1 as parent_spend
from scripts import creative_scope_probe_spend_anchor_v1 as evidence
from scripts import creative_fresh_source_session_v1 as original
from src.content_factory import creative_goal_context_workflow_v26 as workflow
from src.content_factory import creative_fresh_source_inputs_v1 as sources
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "creative_paired_drama_probe/v1"
PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = PROJECT / "config/creative_fresh_source_session_profile_v2.json"
LIMITS = {"goal_plan": 0, "goal_audit": 1, "complete_script": 0, "full_review": 0}
LABEL = "paired_drama_diagnostic_01"
BASE_SPEND = {"calls_started": 635, "reported_tokens": 13368222, "calls_with_known_usage": 633,
              "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
DIRECTOR = {"used": 7, "limit": 7, "remaining": 0}
TERMINAL = {"diagnostic_expectation_matched_not_creative", "diagnostic_expectation_not_matched_not_creative",
            "diagnostic_inconclusive_not_creative", "halt_drama_contract_rejected", "halt_protocol_requires_diagnosis"}
read, write, digest, sha_file, now = io.read, io.write, io.digest, io.sha_file, io.now
require = parent_spend.require


@dataclass(frozen=True)
class ProbeConfig:
    root: str
    parent_anchor_path: str
    parent_anchor_sha256: str
    expectation_path: str
    counter_root: str
    round_key: str
    grant_id: str
    authorization_path: str
    profile_path: str = str(DEFAULT_PROFILE)
    extra_source_files: tuple[str, ...] = ()


def inherited_files(anchor):
    """Hash inventory of the already fully verified typed ancestry, no cache.

    Following canonical parent-anchor links avoids rerunning all semantic/SQL
    readers at every runtime check. Every inventoried original byte is still
    rehashed by the guard; this is not an mtime or process-lifetime cache.
    """
    files, seen = {}, set()
    while True:
        identity = digest(anchor)
        require(identity not in seen and len(seen) < 100, "cyclic/excessive parent certificate chain")
        seen.add(identity)
        for name, row in anchor.get("verified_files", {}).items():
            path = parent_spend.native._inside(name, PROJECT)
            expected = row["sha256"]
            require(str(path) not in files or files[str(path)] == expected, "conflicting original ancestry bytes")
            files[str(path)] = expected
        name = anchor.get("parent_anchor_path")
        if name is None:
            break
        path = parent_spend.native._inside(name, PROJECT)
        prior = read(path)
        require(digest(prior) == anchor["parent_anchor_sha256"], "typed parent canonical identity changed")
        files[str(path)] = sha_file(path)
        anchor = prior
    return files


def _verify_files(files):
    require(type(files) is dict and bool(files), "nonempty original byte inventory required")
    for name, expected in files.items():
        path = parent_spend.native._inside(name, PROJECT)
        require(sha_file(path) == expected, "frozen original bytes changed: " + str(path))


def evaluate_expectation(document, expectation):
    """Local registered preference comparison, never a model report rewrite."""
    row = deepcopy(document["paired_checks"]["records_by_target"][expectation["target"]])
    status = row["status"]
    return {"schema": VERSION + "/diagnostic_comparison", "native_drama_sha256": digest(document),
        "registered_expectation_sha256": digest(expectation), "target": expectation["target"],
        "native_status": status, "registered_expected_status": expectation["expected_status"],
        "expectation_match": status == expectation["expected_status"], "native_record": row,
        "expectation_authority": "assistant_diagnostic_preference_not_user_gold",
        "mismatch_proves_semantic_error": False, "intention_requires_success": False,
        "creative_quality_passed": False, "human_approved": False}


class Probe:
    def __init__(self, config, *, parent_verifier=parent_spend.verify_anchor, input_builder=sources.build_inputs,
                 source_gate=sources.verify_source_bundle, client_factory_builder=None, clock=now):
        self.config = config if isinstance(config, ProbeConfig) else ProbeConfig(**config)
        self.root = parent_spend.native._inside(self.config.root, PROJECT)
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.config.grant_id)
            and re.fullmatch(r"[a-f0-9]{64}", self.config.parent_anchor_sha256) and self.config.round_key,
            "safe explicit diagnostic root/grant/parent/round required")
        self.parent_verifier, self.input_builder, self.source_gate = parent_verifier, input_builder, source_gate
        self.client_factory_builder = client_factory_builder or clients.make_client_factory
        self.clock = clock
        self.claim = PROJECT / "data/creative_paired_drama_probe_claims" / self.config.grant_id / "CLAIM.json"

    @property
    def profile(self):
        return read(self.config.profile_path)

    def _parent(self):
        parent = read(self.config.parent_anchor_path)
        checked = self.parent_verifier(parent, expected_anchor_sha256=self.config.parent_anchor_sha256)
        require(checked.get("verified") is True and digest(parent) == self.config.parent_anchor_sha256
            and parent.get("schema") == parent_spend.VERSION and checked.get("inherited") == parent.get("inherited")
            and parent_spend.native._spend(parent["inherited"]) == BASE_SPEND
            and parent.get("whole_goal_candidates_used") == 4 and parent.get("scope_probe_calls_used") == 2
            and parent.get("remaining_scope_probe_calls") == 0 and parent.get("old_director_capacity") == DIRECTOR,
            "settled635 exact cumulative consumption and exhausted original capacities required")
        return parent

    def _seed(self, parent):
        root = parent_spend.native._inside(parent["root"], PROJECT)
        inventory = parent["verified_files"]
        def load(name):
            path = root / name
            require(str(path) in inventory and sha_file(path) == inventory[str(path)]["sha256"], "original parent file unbound: " + name)
            return read(path)
        config, inputs = load("SESSION_CONFIG.json"), load("INPUTS.json")
        pointer = parent["latest_native_goal_receipt"]
        require(Path(pointer["root"]).resolve() == root and pointer["ordinal"] == 627 and pointer["label"] == "whole_plan_04",
            "original627 native planning pointer required")
        goal = load(pointer["receipt"])
        original.Session.known(goal, "historical627")
        require(goal["ordinal"] == 627 and goal["request_sha256"] == pointer["request_sha256"]
            and digest(goal["output"]) == pointer["native_goal_sha256"], "original complete627 identity changed")
        receipts = {kind: load("call_" + str(ordinal) + "_" + kind + "_audit_04.json")
            for kind, ordinal in (("scope", 628), ("source", 629), ("commitment", 630))}
        for kind, receipt in receipts.items():
            original.Session.known(receipt, "historical_" + kind)
            require(receipt["validation"].get("valid") is True and receipt["validation"].get("accepted") is True,
                "original scope/source/commitment must remain accepted")
        return {"config": config, "inputs": inputs, "goal": goal["output"], "goal_receipt": goal,
            "original_audits": receipts, "root": str(root)}

    def _expectation(self, seed):
        value = read(self.config.expectation_path)
        catalog = workflow.drama_contract.build_evidence_catalog(seed["goal"])
        require(value.get("schema") == "creative_paired_live_diagnostic_expectation/v1"
            and value.get("goal_sha256") == digest(seed["goal"]) and value.get("target") == "ending"
            and value.get("expected_status") == "fail"
            and value.get("expectation_authority") == "assistant_diagnostic_preference_not_user_gold",
            "exact pre-registered local preference required, never a semantic gold label")
        pointer = value["original_receipt"]
        actual = Path(seed["root"]) / "call_627_whole_plan_04.json"
        require(Path(pointer["path"]).resolve() == actual and pointer["file_sha256"] == sha_file(actual)
            and pointer["request_sha256"] == seed["goal_receipt"]["request_sha256"]
            and pointer["ordinal"] == 627 and pointer["label"] == "whole_plan_04", "registered original receipt changed")
        require(type(value.get("evidence_refs")) is list and bool(value["evidence_refs"])
            and set(value["evidence_refs"]) <= set(catalog), "registered comparison references required")
        for row in value["evidence"]:
            require(row["source_ref"] in catalog and all(row[key] == catalog[row["source_ref"]][key]
                for key in ("document_path", "quote")), "registered exact source quotation changed")
        return value

    def preview(self):
        parent = self._parent(); seed = self._seed(parent)
        original.Session._profile_gate(self)
        built = self.input_builder(seed["config"]["source_dir"], seed["config"]["preferences_path"],
            seed["config"]["user_goals_path"], now=self.clock())
        require(built.get("evidence", {}).get("source_gate", {}).get("current_source_freshness_verified") is True,
            "current actual source gate is required separately from historical parent integrity")
        require(digest(built["inputs"]) == digest(seed["inputs"]), "current complete raw inputs differ from original627 source")
        expectation = self._expectation(seed)
        prepared = workflow.prepare_goal_drama_audit_request(seed["inputs"], self.profile, seed["goal"])
        # No expectation object, assessment policy or registration is added.
        require(prepared["request"]["model"] == "deepseek-flash"
            and prepared["request"]["parameters"] == {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 16000},
            "exact original DeepSeek model/parameters/output boundary required")
        parent_files = inherited_files(parent); _verify_files(parent_files)
        return {"schema": VERSION + "/preview", "request": prepared, "inherited": deepcopy(parent["inherited"]),
            "parent_identity": parent["parent_identity"], "parent_identity_sha256": parent["parent_identity_sha256"],
            "parent_integrity_files": parent_files, "original_source_dir": seed["config"]["source_dir"],
            "source_files": built["source_files"], "inputs_sha256": digest(seed["inputs"]), "native_goal_sha256": digest(seed["goal"]),
            "expectation_canonical_sha256": digest(expectation), "expectation_file_sha256": sha_file(self.config.expectation_path),
            "stage_limits": deepcopy(LIMITS), "whole_goal_candidates_used": 4, "old_director_capacity": DIRECTOR,
            "scope_probe_calls_used": 2, "new_paired_diagnostic_limit": 1, "unspent_old_capacity_regranted": False,
            "inherited_stage_calls": parent["stage_calls"], "provider_calls": 0, "media_calls": 0,
            "expectation_sent_to_provider": False, "authorizes_new_dispatch": False, "creative_quality_passed": False}

    prepare_preview = preview

    def authorization_template(self, preview):
        return {"schema": VERSION + "/scope", "root": str(self.root), "grant_id": self.config.grant_id,
            "parent_anchor_sha256": self.config.parent_anchor_sha256, "parent_identity": preview["parent_identity"],
            "parent_identity_sha256": preview["parent_identity_sha256"], "inherited": preview["inherited"],
            "preview_sha256": digest(preview), "request_sha256": preview["request"]["request_sha256"],
            "inputs_sha256": preview["inputs_sha256"], "native_goal_sha256": preview["native_goal_sha256"],
            "expectation_sha256": preview["expectation_file_sha256"], "stage_limits": LIMITS,
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "whole_goal_candidates_used": 4, "old_director_capacity": DIRECTOR, "scope_probe_calls_used": 2,
            "new_paired_diagnostic_limit": 1, "unspent_old_capacity_regranted": False,
            "automatic_retry": False, "old_budget_reset": False, "media_authorized": False, "publish_authorized": False}

    def _binding(self, parent):
        return {"schema": VERSION + "/successor_claim", "anchor_sha256": self.config.parent_anchor_sha256,
            "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"],
            "parent_identity_sha256": parent["parent_identity_sha256"], "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "new_paired_diagnostic_limit": 1, "old_budget_reset": False}

    def prepare(self):
        require(not self.root.exists() and not self.claim.exists(), "existing probe or grant cannot restart")
        preview = self.preview(); parent = read(self.config.parent_anchor_path)
        require(digest(parent) == self.config.parent_anchor_sha256, "reviewed parent changed")
        require(digest(read(self.config.authorization_path)) == digest(self.authorization_template(preview)), "exact reviewed new one-call scope required")
        successors = policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256)
        require(not any(p.exists() for p in successors), "parent already has a successor; directory/grant change cannot reset")
        files = {}
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name:
                path = Path(name).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / p) for p in ("scripts", "src")):
                    files[str(path)] = sha_file(path)
        extra = [self.config.parent_anchor_path, self.config.expectation_path, self.config.authorization_path,
            self.config.profile_path, *preview["source_files"], *self.config.extra_source_files,
            Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json",
            Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json"]
        for name in extra:
            path = parent_spend.native._inside(name, PROJECT); files[str(path)] = sha_file(path)
        binding = self._binding(parent)
        for path in successors: policy.new_claim(path, binding)
        policy.new_claim(self.claim, {"schema": VERSION + "/claim", "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "old_budget_reset": False})
        self.root.mkdir(parents=True)
        for name, value in (("PROBE_CONFIG", asdict(self.config)), ("PREPARED_PROBE", preview), ("USER_SCOPE", read(self.config.authorization_path))):
            path = self.root / (name + ".json"); write(path, value, True); files[str(path)] = sha_file(path)
        for path in successors: files[str(path)] = sha_file(path)
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "parent_integrity_files": preview["parent_integrity_files"], "inherited": preview["inherited"],
            "claim_sha256": sha_file(self.claim), "stage_limits": LIMITS, "new_paired_diagnostic_limit": 1}, True)
        runtime = self.runtime(); runtime.prepare()
        return self.state(runtime, "prepared")

    def _guard(self):
        frozen = read(self.root / "PRODUCTION_FREEZE.json")
        require(frozen["schema"] == VERSION + "/freeze"
            and digest(read(self.root / "PROBE_CONFIG.json")) == digest(asdict(self.config)), "frozen probe config/version changed")
        _verify_files(frozen["files"]); _verify_files(frozen["parent_integrity_files"])
        parent = read(self.config.parent_anchor_path)
        require(digest(parent) == self.config.parent_anchor_sha256 and frozen["inherited"] == parent["inherited"]
            and sha_file(self.claim) == frozen["claim_sha256"], "parent spend or unique grant changed")
        for path in policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256):
            require(digest(read(path)) == digest(self._binding(parent)), "dual successor identity changed")
        preview = read(self.root / "PREPARED_PROBE.json")
        gate = self.source_gate(preview["original_source_dir"], now=self.clock())
        require(gate.get("current_source_freshness_verified") is True, "current actual source is not fresh/valid")

    def _admit(self, label, request, ledger):
        # The oldest620 accounting anchor has no flattened verified_files.
        # Re-run the full historical verifier ONCE at locked admission rather
        # than treating the quick inventory as a complete cached certificate.
        self._parent()
        self._guard(); CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        item = read(self.root / "PREPARED_PROBE.json")["request"]
        require(not ledger["calls"] and label == LABEL and digest(request) == digest(item["request"])
            and request["stage"] == "goal_audit" and request["role"] == "director", "only the frozen one diagnostic request is authorized")
        return True

    def runtime(self):
        frozen = read(self.root / "PRODUCTION_FREEZE.json")
        return runtime7.GoalContextRuntime(PROJECT, self.root, list(frozen["files"]), frozen["inherited"],
            profile=self.profile, stage_limits=LIMITS, inherited_guard=self._guard, admission=self._admit,
            shared_lock=PROJECT / "data/creative_paired_drama_probe_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        try:
            require(runtime is not None, "runtime not constructed; spend pending")
            spend = runtime.summary(); pending = False; error = None
        except Exception as exc:
            spend = None; pending = True; error = {"type": type(exc).__name__, "message": str(exc)}
        value = {"schema": VERSION + "/state", "status": status, "updated_at": self.clock(), "spend": spend,
            "spend_verification_pending": pending, "diagnostic_only": True, "text_ready_for_director": False,
            "human_quality_approved": False, "creative_quality_passed": False, "media_authorized": False,
            "old_director_capacity": DIRECTOR, "whole_goal_candidates_used": 4, "scope_probe_calls_used": 2, **details}
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha_file(self.root / "RUN_CLAIM.json")
        if pending: value["spend_error"] = error
        write(self.root / "STATE.json", value); return value

    def run(self):
        require((self.root / "PRODUCTION_FREEZE.json").is_file() and (self.root / "PREPARED_PROBE.json").is_file(),
            "probe must be separately prepared before a run claim")
        require(not (self.root / "RUN_CLAIM.json").exists(), "original RUN_CLAIM exists; never restart")
        policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "grant_id": self.config.grant_id, "prepared_sha256": sha_file(self.root / "PREPARED_PROBE.json"),
            "pid": os.getpid(), "started_at": self.clock(), "automatic_restart": False})
        runtime = None
        try:
            runtime = self.runtime(); require(not read(runtime.ledger)["calls"], "nonempty original ledger cannot restart")
            preview = read(self.root / "PREPARED_PROBE.json"); item = preview["request"]
            parent = read(self.config.parent_anchor_path); seed = self._seed(parent)
            receipt = policy.dispatch_claimed(runtime, LABEL, item,
                lambda output: workflow.validate_goal_drama_audit(output, seed["goal"], inputs=seed["inputs"],
                    context_sha256=item["drama_context_sha256"]), root=self.root, grant_id=self.config.grant_id,
                stage_limits=LIMITS, current_round_root=self.config.counter_root, current_round_key=self.config.round_key, guard=self._guard)
            known, outcome, _ = original.Session.classify_native(receipt)
            if not known: return self.state(runtime, "halt_interface_or_unknown", receipt_ordinal=receipt["ordinal"])
            if outcome == "protocol_rejected": return self.state(runtime, "halt_protocol_requires_diagnosis", receipt_ordinal=receipt["ordinal"])
            if receipt["status"] != "contract_valid": return self.state(runtime, "halt_drama_contract_rejected", receipt_ordinal=receipt["ordinal"])
            ledger = read(runtime.ledger)
            evidence.verify_known_receipt(self.root, ledger["calls"][0], ledger["source_manifest"], evidence.session.Reader())
            require(sha_file(self.config.expectation_path) == preview["expectation_file_sha256"],
                "registered local expectation changed while original request was in flight")
            gate = evaluate_expectation(receipt["output"], read(self.config.expectation_path))
            write(self.root / "DIAGNOSTIC_COMPARISON.json", gate, True)
            status = ("diagnostic_inconclusive_not_creative" if gate["native_status"] == "unknown" else
                "diagnostic_expectation_matched_not_creative" if gate["expectation_match"] else "diagnostic_expectation_not_matched_not_creative")
            return self.state(runtime, status, receipt_ordinal=receipt["ordinal"], diagnostic_comparison=gate)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_retry": False}, True)
            self.state(runtime, "halt_execution_reconciliation", error_type=type(exc).__name__)
            raise

    def status(self):
        return read(self.root / "STATE.json")
