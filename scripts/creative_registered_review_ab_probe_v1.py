"""Two preregistered representations, one request each; no authoring or retry."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import sys

from scripts import creative_paired_drama_probe_v1 as shared
from scripts import creative_paired_drama_probe_spend_anchor_v1 as parent_spend

VERSION = "creative_registered_review_ab_probe/v1"
PROJECT = Path(__file__).resolve().parents[1]
LIMITS = {"goal_plan": 0, "goal_audit": 2, "complete_script": 0, "full_review": 0}
LABELS = ("review_ab_A", "review_ab_B")
BASE_SPEND = {"calls_started": 636, "reported_tokens": 13408816, "calls_with_known_usage": 634,
              "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
read, write, digest, sha_file, require = shared.read, shared.write, shared.digest, shared.sha_file, shared.require


def contract():
    from src.content_factory import creative_paired_review_ab_v2
    return creative_paired_review_ab_v2


@dataclass(frozen=True)
class ProbeConfig:
    root: str
    parent_anchor_path: str
    parent_anchor_sha256: str
    counter_root: str
    round_key: str
    grant_id: str
    authorization_path: str
    profile_path: str = str(shared.DEFAULT_PROFILE)
    extra_source_files: tuple[str, ...] = ()


class Probe:
    def __init__(self, config, *, parent_verifier=parent_spend.verify_anchor,
                 source_gate=shared.sources.verify_source_bundle, client_factory_builder=None, clock=shared.now):
        self.config = config if isinstance(config, ProbeConfig) else ProbeConfig(**config)
        self.root = shared.parent_spend.native._inside(self.config.root, PROJECT)
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.config.grant_id)
            and re.fullmatch(r"[a-f0-9]{64}", self.config.parent_anchor_sha256) and self.config.round_key,
            "explicit safe diagnostic identity required")
        self.parent_verifier, self.source_gate = parent_verifier, source_gate
        self.client_factory_builder = client_factory_builder or shared.clients.make_client_factory
        self.clock = clock
        self.claim = PROJECT / "data/creative_registered_review_ab_claims" / self.config.grant_id / "CLAIM.json"

    @property
    def profile(self): return read(self.config.profile_path)

    def _parent(self):
        parent = read(self.config.parent_anchor_path)
        checked = self.parent_verifier(parent, expected_anchor_sha256=self.config.parent_anchor_sha256)
        require(checked.get("verified") is True and digest(parent) == self.config.parent_anchor_sha256
            and parent.get("schema") == parent_spend.VERSION and checked.get("inherited") == parent.get("inherited")
            and shared.parent_spend.native._spend(parent["inherited"]) == BASE_SPEND
            and parent.get("whole_goal_candidates_used") == 4 and parent.get("old_director_capacity") == shared.DIRECTOR
            and parent.get("scope_probe_calls_used") == 2
            and parent.get("paired_drama_probe_calls_used") == parent.get("paired_drama_probe_call_limit") == 1,
            "settled636 exact cumulative costs and exhausted old capacities required")
        return parent

    def _seed(self, parent):
        inventory = shared.inherited_files(parent)
        def load(path):
            path = shared.parent_spend.native._inside(path, PROJECT)
            require(str(path) in inventory and sha_file(path) == inventory[str(path)], "original source file unbound")
            return read(path)
        root = shared.parent_spend.native._inside(parent["root"], PROJECT)
        receipt = load(root / "call_636_paired_drama_diagnostic_01.json")
        known, _, _ = shared.original.Session.classify_native(receipt)
        require(known and receipt["ordinal"] == 636, "complete known original636 required; never normalize its failed output")
        goal_ref = parent["latest_native_goal_receipt"]
        require(goal_ref["ordinal"] == 627 and goal_ref["label"] == "whole_plan_04", "original627 pointer required")
        goal = load(Path(goal_ref["root"]) / goal_ref["receipt"])
        require(goal["request_sha256"] == goal_ref["request_sha256"]
            and digest(goal["output"]) == goal_ref["native_goal_sha256"], "original627 identity changed")
        preview = load(root / "PREPARED_PROBE.json")
        return {"receipt": receipt, "goal_receipt": goal, "source_dir": preview["original_source_dir"]}

    @staticmethod
    def _requests(experiment):
        require(type(experiment.get("requests")) is dict and set(experiment["requests"]) == {"A", "B"},
            "exactly two preregistered representations A and B required")
        items = [{"label": label, "representation": representation, "prepared": experiment["requests"][representation]}
            for label, representation in zip(LABELS, ("A", "B"))]
        require(len({item["label"] for item in items}) == 2, "duplicate registered labels forbidden")
        for item in items:
            prepared = item["prepared"]; request = prepared["request"]
            require(request["stage"] == "goal_audit" and request["role"] == "director"
                and request["model"] == "deepseek-flash" and request["parameters"] == {
                    "temperature": .4, "thinking": "disabled", "max_completion_tokens": 16000}
                and digest(request) == prepared["request_sha256"] and type(request.get("structured_schema")) is dict,
                "exact request schema/model/parameters/identity required")
        require(items[0]["prepared"]["request_sha256"] != items[1]["prepared"]["request_sha256"],
            "two registered representations must remain distinct requests")
        return items

    def preview(self):
        parent = self._parent(); seed = self._seed(parent)
        shared.original.Session._profile_gate(self)
        gate = self.source_gate(seed["source_dir"], now=self.clock())
        require(gate.get("current_source_freshness_verified") is True, "current actual source gate required")
        experiment = contract().prepare_experiment(self.profile, seed["receipt"])
        require(experiment["source_receipt_sha256"] == digest(seed["receipt"])
            and experiment["native_goal_sha256"] == digest(seed["goal_receipt"]["output"]),
            "controlled corpus must bind the unchanged original636 and original627")
        items = self._requests(experiment)
        inventory = shared.inherited_files(parent); shared._verify_files(inventory)
        return {"schema": VERSION + "/preview", "experiment": experiment, "registered_requests": items,
            "inherited": deepcopy(parent["inherited"]), "parent_identity": parent["parent_identity"],
            "parent_identity_sha256": parent["parent_identity_sha256"], "parent_integrity_files": inventory,
            "original_source_dir": seed["source_dir"], "stage_limits": LIMITS, "provider_calls": 0,
            "old_director_capacity": shared.DIRECTOR, "whole_goal_candidates_used": 4,
            "paired_drama_probe_calls_used": 1, "scope_probe_calls_used": 2,
            "original_scope_probe_call_limit": 2, "derived_remaining_original_scope_probe_calls": 0,
            "old_capacity_regranted": False, "expectations_sent_to_provider": False,
            "authorizes_new_dispatch": False, "creative_quality_passed": False}

    prepare_preview = preview

    def authorization_template(self, preview):
        return {"schema": VERSION + "/scope", "root": str(self.root), "grant_id": self.config.grant_id,
            "parent_anchor_sha256": self.config.parent_anchor_sha256, "parent_identity": preview["parent_identity"],
            "parent_identity_sha256": preview["parent_identity_sha256"], "inherited": preview["inherited"],
            "preview_sha256": digest(preview), "corpus_sha256": preview["experiment"]["corpus_sha256"],
            "registered_requests": [{"label": i["label"], "representation": i["representation"],
                "request_sha256": i["prepared"]["request_sha256"]} for i in preview["registered_requests"]],
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "stage_limits": LIMITS, "max_calls_per_representation": 1, "known_complete_contract_rejection_may_continue_to_registered_B": True,
            "known_protocol_rejection_stops_remaining": True,
            "unknown_truncated_or_unknown_usage_stops_remaining": True, "automatic_retry": False,
            "whole_goal_candidates_used": 4, "old_director_capacity": shared.DIRECTOR,
            "scope_probe_calls_used": 2, "paired_drama_probe_calls_used": 1, "old_capacity_regranted": False,
            "original_scope_probe_call_limit": 2, "derived_remaining_original_scope_probe_calls": 0,
            "old_budget_reset": False, "media_authorized": False, "publish_authorized": False}

    def _binding(self, parent):
        return {"schema": VERSION + "/successor_claim", "anchor_sha256": self.config.parent_anchor_sha256,
            "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"],
            "parent_identity_sha256": parent["parent_identity_sha256"], "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "new_registered_ab_limit": 2,
            "old_budget_reset": False}

    def prepare(self):
        require(not self.root.exists() and not self.claim.exists(), "existing root/grant cannot restart")
        preview = self.preview(); parent = read(self.config.parent_anchor_path)
        require(digest(parent) == self.config.parent_anchor_sha256
            and digest(read(self.config.authorization_path)) == digest(self.authorization_template(preview)),
            "exact reviewed fixed two-request scope required")
        successors = shared.policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256)
        require(not any(path.exists() for path in successors), "parent already has a successor; changing root/grant cannot reset")
        files = {}
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name:
                path = Path(name).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / p) for p in ("scripts", "src")):
                    files[str(path)] = sha_file(path)
        for name in (self.config.parent_anchor_path, self.config.authorization_path, self.config.profile_path,
            *self.config.extra_source_files, Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json",
            Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json"):
            path = shared.parent_spend.native._inside(name, PROJECT); files[str(path)] = sha_file(path)
        for path in successors: shared.policy.new_claim(path, self._binding(parent))
        shared.policy.new_claim(self.claim, {"schema": VERSION + "/claim", "root": str(self.root),
            "grant_id": self.config.grant_id, "authorization_sha256": sha_file(self.config.authorization_path)})
        self.root.mkdir(parents=True)
        for name, value in (("PROBE_CONFIG", asdict(self.config)), ("PREPARED_PROBE", preview),
            ("USER_SCOPE", read(self.config.authorization_path))):
            path = self.root / (name + ".json"); write(path, value, True); files[str(path)] = sha_file(path)
        for path in successors: files[str(path)] = sha_file(path)
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "parent_integrity_files": preview["parent_integrity_files"], "inherited": preview["inherited"],
            "claim_sha256": sha_file(self.claim), "stage_limits": LIMITS}, True)
        runtime = self.runtime(); runtime.prepare(); return self.state(runtime, "prepared")

    def _guard(self):
        frozen = read(self.root / "PRODUCTION_FREEZE.json")
        require(frozen["schema"] == VERSION + "/freeze"
            and digest(read(self.root / "PROBE_CONFIG.json")) == digest(asdict(self.config)), "frozen config changed")
        shared._verify_files(frozen["files"]); shared._verify_files(frozen["parent_integrity_files"])
        parent = read(self.config.parent_anchor_path)
        require(digest(parent) == self.config.parent_anchor_sha256 and frozen["inherited"] == parent["inherited"]
            and sha_file(self.claim) == frozen["claim_sha256"], "parent spend or unique grant changed")
        for path in shared.policy.successor_paths(PROJECT, parent, self.config.parent_anchor_sha256):
            require(digest(read(path)) == digest(self._binding(parent)), "dual successor changed")
        preview = read(self.root / "PREPARED_PROBE.json")
        require(self.source_gate(preview["original_source_dir"], now=self.clock()).get("current_source_freshness_verified") is True,
            "current actual source no longer fresh/valid")

    def _admit(self, label, request, ledger):
        self._parent()  # Full certificate once per locked actual dispatch; never every ordinary guard.
        self._guard(); shared.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        items = read(self.root / "PREPARED_PROBE.json")["registered_requests"]
        count = len(ledger["calls"])
        require(count < 2 and label == items[count]["label"]
            and digest(request) == digest(items[count]["prepared"]["request"])
            and [row["label"] for row in ledger["calls"]] == list(LABELS[:count]),
            "only the next exact registered label/request is authorized; no duplicate or replay")
        for row in ledger["calls"]:
            receipt = shared.evidence.verify_known_receipt(self.root, row, ledger["source_manifest"], shared.evidence.session.Reader())
            require(shared.original.Session.classify_native(receipt)[0], "unknown preceding result stops B")
        return True

    def runtime(self):
        frozen = read(self.root / "PRODUCTION_FREEZE.json")
        return shared.runtime7.GoalContextRuntime(PROJECT, self.root, list(frozen["files"]), frozen["inherited"],
            profile=self.profile, stage_limits=LIMITS, inherited_guard=self._guard, admission=self._admit,
            shared_lock=PROJECT / "data/creative_registered_review_ab_claims/DISPATCH.lock", quota_state=None,
            client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        try:
            require(runtime is not None, "runtime not constructed; spend pending")
            spend = runtime.summary(); pending = False; error = None
        except Exception as exc:
            spend = None; pending = True; error = {"type": type(exc).__name__, "message": str(exc)}
        value = {"schema": VERSION + "/state", "status": status, "updated_at": self.clock(), "spend": spend,
            "spend_verification_pending": pending, "diagnostic_only": True, "creative_quality_passed": False,
            "human_quality_approved": False, "text_ready_for_director": False, "media_authorized": False,
            "old_director_capacity": shared.DIRECTOR, "whole_goal_candidates_used": 4,
            "scope_probe_calls_used": 2, "paired_drama_probe_calls_used": 1, **details}
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha_file(self.root / "RUN_CLAIM.json")
        if pending: value["spend_error"] = error
        write(self.root / "STATE.json", value); return value

    def run(self):
        require((self.root / "PRODUCTION_FREEZE.json").is_file() and (self.root / "PREPARED_PROBE.json").is_file(),
            "separately prepared immutable requests required before RUN")
        require(not (self.root / "RUN_CLAIM.json").exists(), "original RUN_CLAIM exists; never restart")
        shared.policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "root": str(self.root),
            "grant_id": self.config.grant_id, "prepared_sha256": sha_file(self.root / "PREPARED_PROBE.json"),
            "pid": os.getpid(), "started_at": self.clock(), "automatic_restart": False})
        runtime = None
        try:
            runtime = self.runtime(); require(not read(runtime.ledger)["calls"], "original ledger cannot restart")
            preview = read(self.root / "PREPARED_PROBE.json"); experiment = preview["experiment"]
            require(self._requests(experiment) == preview["registered_requests"], "registered list changed")
            results = []
            for item in preview["registered_requests"]:
                receipt = shared.policy.dispatch_claimed(runtime, item["label"], item["prepared"],
                    lambda output, i=item: contract().validate_response(output, experiment["corpus"], i["representation"],
                        context_sha256=i["prepared"]["context_sha256"]), root=self.root, grant_id=self.config.grant_id,
                    stage_limits=LIMITS, current_round_root=self.config.counter_root,
                    current_round_key=self.config.round_key, guard=self._guard)
                known, outcome, _ = shared.original.Session.classify_native(receipt)
                results.append({"representation": item["representation"], "label": item["label"], "ordinal": receipt["ordinal"],
                    "status": receipt["status"], "known": known, "outcome": outcome,
                    "validation": deepcopy(receipt.get("validation"))})
                if not known:
                    return self.state(runtime, "halt_interface_or_unknown", diagnostic_results=results)
                ledger = read(runtime.ledger)
                shared.evidence.verify_known_receipt(self.root, ledger["calls"][-1], ledger["source_manifest"], shared.evidence.session.Reader())
                if outcome == "protocol_rejected":
                    return self.state(runtime, "halt_protocol_requires_diagnosis", diagnostic_results=results)
            write(self.root / "DIAGNOSTIC_RESULTS.json", {"results": results, "creative_quality_passed": False}, True)
            return self.state(runtime, "diagnostic_completed_not_creative", diagnostic_results=results)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"type": type(exc).__name__, "message": str(exc), "automatic_retry": False}, True)
            self.state(runtime, "halt_execution_reconciliation", error_type=type(exc).__name__)
            raise

    def status(self): return read(self.root / "STATE.json")
