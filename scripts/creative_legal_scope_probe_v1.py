"""Two bounded scope diagnostics with native SDK evidence and inherited spend.

Preview is read-only. Preparation/run are separate explicit actions. This is
neither a replacement source approval nor a screenplay-production coordinator.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import base64
import hashlib
import os
import json
from pathlib import Path
import re
import sys

from scripts import creative_resume_dispatch_v3 as io
from scripts import creative_goal_context_dispatch_v7 as runtime7
from scripts import creative_m31_flash_role_clients_v1 as clients
from scripts import creative_scope_probe_spend_anchor_v1 as spend
from src.content_factory import creative_legal_speech_scope_v1 as scope
from src.content_factory.creative_counted_execution_v1 import CountedExecution
from src.content_factory import creative_studio_task_store_v1 as tasks
from scripts import creative_fresh_source_session_v1 as session_protocol

VERSION = "creative_legal_scope_probe/v1"
PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = PROJECT / "config/creative_legal_scope_probe_profile_v1.json"
LIMITS = {"goal_plan": 0, "goal_audit": 2, "complete_script": 0, "full_review": 0}
LABELS = ["scope_cases_01", "scope_full_goal_01"]
ACT_CODES = {"factual_description": "F", "request_or_preference": "R", "conditional_offer_or_promise": "P",
    "management_motive_or_process": "M", "narrative_scope_or_intent": "N", "legal_assertion": "L", "uncertain": "U"}
read, write, digest, sha_file, now = io.read, io.write, io.digest, io.sha_file, io.now
require = spend.require


def _claim_new(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


@dataclass(frozen=True)
class ProbeConfig:
    root: str
    parent_anchor_path: str
    parent_anchor_sha256: str
    blinded_cases_path: str
    private_expectations_path: str
    goal_receipt_path: str
    counter_root: str
    round_key: str
    grant_id: str
    authorization_path: str
    profile_path: str = str(DEFAULT_PROFILE)
    extra_source_files: tuple[str, ...] = ()


def validate_profile(profile):
    confirmed = read(PROJECT / "config/creative_fresh_source_session_profile_v2.json")
    require(profile.get("schema") == "creative_legal_scope_probe_profile/v1"
        and all(profile.get(role) == confirmed[role] for role in ("writer", "director"))
        and profile.get("stage_parameters") == {"goal_audit": confirmed["stage_parameters"]["goal_audit"]}
        and profile["stage_parameters"]["goal_audit"] == {"max_completion_tokens": 16000}
        and type(profile.get("sdk_max_retries")) is int and profile["sdk_max_retries"] == 0
        and all(profile.get(k) is False for k in ("http_follow_redirects", "server_schema_guarantee", "server_strict_requested")),
        "confirmed unchanged DeepSeek model/temperature/thinking/16k ordinary-tool profile required")
    return profile


def _prepared(data, profile, *, case_frame):
    built = scope.build_case_scope_context(data) if case_frame else scope.build_scope_context(data)
    context = built["manifest"]["scope_context_sha256"]
    schema = scope.build_case_scope_schema(data, context_sha256=context) if case_frame else scope.build_scope_schema(data, context_sha256=context)
    params = {**profile["director"]["parameters"], **profile["stage_parameters"]["goal_audit"]}
    request = {"stage": "goal_audit", "role": "director", "model": profile["director"]["model"], "parameters": params,
        "messages": [{"role": "system", "content": scope.SCOPE_RULE},
            {"role": "user", "content": json.dumps(built["payload"], ensure_ascii=False, separators=(",", ":"))}],
        "structured_schema": schema, "input_provenance": {"scope_context_sha256": context,
            "input_sha256": built["manifest"]["input_sha256"], "frame_kind": built["manifest"]["frame_kind"],
            "diagnostic_only": True, "external_authorities_provided": False}}
    wire = clients.expected_wire_request(request)
    # Blind role context contains quotations, not a provenance/score table.
    payload = built["payload"]
    if case_frame:
        require(set(payload["blinded_cases"]) == {"schema", "cases"}
            and all(set(row) == {"source_ref", "text", "role_context"} for row in payload["blinded_cases"]["cases"]),
            "private provenance or expected fields on diagnostic wire")
    return {"request": request, "request_sha256": digest(request), "wire": wire, "context_sha256": context,
        "manifest": built["manifest"], "expected_labels_in_wire": False, "provider_calls": 0,
        "server_strict_requested": False, "server_schema_guarantee": False, "creative_quality_passed": False}


def evaluate_cases(document, prepared, private):
    """Assistant diagnostic expectations, with three ambiguities observational.

    This never changes the original model report, proves law, or supplies a
    user gold label. Fine F/R/P/M/N differences remain descriptive only.
    """
    mapping = private["blind_case_mapping"]
    cases = {row["input"]["case_id"]: row for row in private["cases"]}
    blind = json.loads(prepared["request"]["messages"][1]["content"])["blinded_cases"]
    validate_case_expectations(blind, private)
    decision = scope.validate_case_scope(document, blind, context_sha256=prepared["context_sha256"])
    details = {row["source_ref"]: row["content"] for row in document["scope_observations"]}
    results = []
    for row in blind["cases"]:
        ref = row["source_ref"]; source = cases[mapping[ref]]
        require(source["input"]["target_quote"] == row["text"], "private target quote differs from actual blind target")
        expected = source["private_expectation"]
        require(type(expected.get("hard_gate")) is bool, "explicit private hard/observational designation required")
        act = document["speech_act_by_ref"][ref]
        legal = act in ("L", "U")
        desired = expected["law_route"] == "legal_or_uncertain"
        # A hard positive which unambiguously asserts law must not be replaced
        # by a spurious U. Three actual ambiguities do not enter this score.
        routing_ok = legal == desired and (not desired or act in {ACT_CODES[x] for x in expected["allowed_speech_acts"]})
        results.append({"source_ref": ref, "case_id": mapping[ref], "hard_gate": expected["hard_gate"],
            "native_speech_act": act, "actual_legal_route": legal, "assistant_preferred_legal_route": desired,
            "hard_routing_correct": routing_ok if expected["hard_gate"] else None,
            "native_detail": deepcopy(details.get(ref)), "observational_only": not expected["hard_gate"]})
    hard = [r for r in results if r["hard_gate"]]
    require(len(results) == 20 and len(hard) == 17 and len(results) - len(hard) == 3, "reviewed20 cases with17 hard and3 observational controls required")
    return {"schema": VERSION + "/case_gate", "valid": True, "scope_native_sha256": digest(document),
        "hard_route_gate_passed": all(row["hard_routing_correct"] for row in hard), "hard_total": len(hard),
        "hard_correct": sum(row["hard_routing_correct"] for row in hard), "observational_total": 3,
        "results": results, "contract_decision": decision, "assistant_expectations_not_user_gold": True,
        "semantic_classification_proven": False, "legal_truth_proven": False, "creative_quality_passed": False}


def validate_case_expectations(blind, private):
    """Check the reviewed private gate before any dispatch, never put it on wire."""
    mapping = private["blind_case_mapping"]
    cases = {r["input"]["case_id"]: r for r in private["cases"]}
    require(len(cases) == len(private["cases"]) == len(blind["cases"]) == 20
        and digest(blind) == private["blinded_input_canonical_sha256"]
        and set(mapping) == {r["source_ref"] for r in blind["cases"]}
        and set(mapping.values()) == set(cases) and len(set(mapping.values())) == 20,
        "complete private scoring identity differs from exact blinded20 input")
    counts = {"ordinary": 0, "legal_or_uncertain": 0}; observations = set()
    for row in blind["cases"]:
        original = cases[mapping[row["source_ref"]]]
        expected = original["private_expectation"]; allowed = expected["allowed_speech_acts"]
        require(original["input"]["target_quote"] == row["text"] and type(expected.get("hard_gate")) is bool
            and expected.get("law_route") in counts and type(allowed) is list and bool(allowed)
            and len(allowed) == len(set(allowed)) and all(a in ACT_CODES for a in allowed)
            and expected.get("primary_speech_act") in allowed and expected.get("legal_truth_evaluated") is False,
            "reviewed case quote, route or allowed-act designation is incomplete")
        if expected["hard_gate"]:
            codes = {ACT_CODES[x] for x in allowed}
            require(codes <= ({"L", "U"} if expected["law_route"] == "legal_or_uncertain" else set("FRPMN")),
                "hard-case private route and allowed acts disagree")
            counts[expected["law_route"]] += 1
        else: observations.add(row["source_ref"])
    require(counts == {"ordinary": 9, "legal_or_uncertain": 8} and observations == {"T02", "T05", "T06"},
        "reviewed17 hard controls and3 real ambiguities must be preserved")


def accounting_summary(inherited, receipts, *, unknown_reservations):
    known = [r for r in receipts if type(r.get("response_metadata", {}).get("total_tokens")) is int
        and r["response_metadata"]["total_tokens"] >= 0]
    total = sum(r["response_metadata"]["total_tokens"] for r in known)
    return {"schema": "authorized_creative_continuation/v3", "new_calls": len(receipts),
        "effective_calls_started": inherited["calls_started"] + len(receipts), "new_reported_tokens": total,
        "effective_reported_tokens": inherited["reported_tokens"] + total,
        "unknown_token_reservations": inherited["unknown_token_reservations"] + unknown_reservations,
        "max_total_tokens": None, "unbounded_aggregate_text_authorized": True, "old_budget_reset": False,
        "old_governance_migrated": False, "media_calls": 0, "semantic_approval": False,
        "new_unknown_token_reservations": unknown_reservations, "inherited_unknown_token_reservations": inherited["unknown_token_reservations"],
        "historical_pending_ordinals": deepcopy(inherited["pending_ordinals"]), "new_calls_with_known_usage": len(known),
        "effective_calls_with_known_usage": inherited["calls_with_known_usage"] + len(known),
        "stage_calls": {"goal_plan": 0, "goal_audit": len(receipts), "complete_script": 0, "full_review": 0}, "stage_limits": LIMITS}


class Probe:
    def __init__(self, config, *, parent_verifier=spend.verify_parent_anchor, client_factory_builder=None, clock=now):
        self.config = config if isinstance(config, ProbeConfig) else ProbeConfig(**config)
        self.root = spend.session._inside(self.config.root, PROJECT)
        require(re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", self.config.grant_id) and bool(self.config.round_key), "safe new diagnostic grant/current round required")
        require(re.fullmatch(r"[a-f0-9]{64}", self.config.parent_anchor_sha256), "canonical parent accounting digest required")
        self.parent_verifier, self.clock = parent_verifier, clock
        self.client_factory_builder = client_factory_builder or clients.make_client_factory
        self.claim = PROJECT / "data/creative_diagnostic_probe_claims" / self.config.grant_id / "CLAIM.json"

    def _parent(self):
        parent = read(self.config.parent_anchor_path)
        verified = self.parent_verifier(parent, expected_anchor_sha256=self.config.parent_anchor_sha256)
        require(verified.get("verified") is True and digest(parent) == self.config.parent_anchor_sha256, "verified original parent accounting required")
        require(verified["inherited"] == parent["inherited"], "parent consumption changed")
        return parent, verified

    def prepare_preview(self):
        parent, verified = self._parent()
        require(parent.get("scope_probe_calls_used", 0) == 0,
            "this two-call diagnostic scope was already consumed; another stage needs its own explicit scope")
        profile = validate_profile(read(self.config.profile_path))
        blind, private = read(self.config.blinded_cases_path), read(self.config.private_expectations_path)
        validate_case_expectations(blind, private)
        pointer = parent["latest_native_goal_receipt"]
        path = Path(self.config.goal_receipt_path).resolve()
        require(path == Path(pointer["root"]) / pointer["receipt"], "full scope must use verified latest original native goal receipt")
        receipt = read(path); goal = receipt["output"]
        require(digest(goal) == pointer["native_goal_sha256"] and receipt["ordinal"] == pointer["ordinal"]
            and receipt["request_sha256"] == pointer["request_sha256"], "original full native goal pointer changed")
        requests = [_prepared(blind, profile, case_frame=True), _prepared(goal, profile, case_frame=False)]
        require(requests[1]["manifest"]["source_ref_count"] == 132 and requests[1]["manifest"]["native_goal_reconstruction_verified"] is True,
            "full132 original native evidence, not selected disputed excerpts, required")
        return {"schema": VERSION + "/preview", "requests": requests, "labels": LABELS, "inherited": verified["inherited"],
            "native_goal_sha256": digest(goal), "original_goal_receipt_sha256": sha_file(path),
            "blinded_case_sha256": digest(blind), "private_expectations_sha256": sha_file(self.config.private_expectations_path),
            "parent_identity": deepcopy(parent["parent_identity"]), "parent_identity_sha256": parent["parent_identity_sha256"],
            "same_source_whole_plans_used": parent["whole_goal_candidates_used"], "stage_limits": LIMITS,
            "new_deepseek_calls_limit": 2, "writer_calls_limit": 0, "provider_calls": 0, "media_calls": 0,
            "authorizes_new_dispatch": False, "creative_quality_passed": False}

    def authorization_template(self, preview):
        return {"schema": VERSION + "/scope", "root": str(self.root), "grant_id": self.config.grant_id,
            "inherited": preview["inherited"], "parent_anchor_sha256": self.config.parent_anchor_sha256,
            "parent_identity": preview["parent_identity"], "parent_identity_sha256": preview["parent_identity_sha256"],
            "request_sha256s": [r["request_sha256"] for r in preview["requests"]], "preview_canonical_sha256": digest(preview),
            "counter_root": str(Path(self.config.counter_root).resolve()), "round_key": self.config.round_key,
            "stage_limits": LIMITS, "new_deepseek_calls_limit": 2, "writer_calls_limit": 0,
            "hard_case_gate_total": 17, "observational_ambiguity_total": 3, "automatic_retry": False,
            "old_budget_reset": False, "media_authorized": False, "publish_authorized": False,
            "assistant_case_expectations_not_user_gold": True, "creative_quality_passed": False}

    def prepare(self):
        require(not self.root.exists() and not self.claim.exists(), "existing probe cannot be prepared/restarted")
        preview = self.prepare_preview(); parent, _ = self._parent()
        require(read(self.config.authorization_path) == self.authorization_template(preview), "exact reviewed diagnostic authorization required")
        canonical, parent_claim = spend.claim_paths(parent, self.config.parent_anchor_sha256)
        require(not canonical.exists() and not parent_claim.exists(), "parent already consumed by another successor; profile/root cannot regrant it")
        code = []
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name:
                path = Path(name).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(PROJECT / part) for part in ("scripts", "src")): code.append(path)
        extra = [Path(__file__), Path(spend.__file__), Path(scope.__file__), DEFAULT_PROFILE,
            Path(self.config.profile_path), Path(self.config.parent_anchor_path), Path(self.config.blinded_cases_path),
            Path(self.config.private_expectations_path), Path(self.config.goal_receipt_path), Path(self.config.authorization_path),
            Path(self.config.counter_root) / "AUTHORIZATION_AND_CADENCE_v1.json",
            Path(self.config.counter_root) / "USER_COUNT_UNIT_CONFIRMATION_v1.json", *map(Path, self.config.extra_source_files)]
        files = {str(p.resolve()): sha_file(p) for p in [*code, *extra]}
        binding = {"schema": VERSION + "/successor_claim", "anchor_sha256": self.config.parent_anchor_sha256,
            "parent_session_root": parent["root"], "parent_identity": parent["parent_identity"],
            "parent_identity_sha256": parent["parent_identity_sha256"], "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "old_budget_reset": False}
        # Atomic first-writer reservations. Partial preparation remains claimed;
        # no cleanup deletes a reservation or creates a replacement dispatch.
        for p in (canonical, parent_claim): _claim_new(p, binding)
        _claim_new(self.claim, {"schema": VERSION + "/claim", "root": str(self.root), "grant_id": self.config.grant_id,
            "authorization_sha256": sha_file(self.config.authorization_path), "old_budget_reset": False})
        self.root.mkdir(parents=True)
        for p in (canonical, parent_claim): files[str(p)] = sha_file(p)
        for name, value in (("PROBE_CONFIG", asdict(self.config)), ("PREPARED_PROBE", preview),
            ("USER_SCOPE", read(self.config.authorization_path))):
            p = self.root / (name + ".json"); write(p, value, True); files[str(p)] = sha_file(p)
        write(self.root / "PRODUCTION_FREEZE.json", {"schema": VERSION + "/freeze", "files": files,
            "claim_sha256": sha_file(self.claim), "inherited": preview["inherited"]}, True)
        runtime = self.runtime(); runtime.prepare()
        return self.state(runtime, "prepared")

    def _guard(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        require(read(self.root / "PROBE_CONFIG.json") == json.loads(json.dumps(asdict(self.config))),
            "in-memory probe configuration differs from original frozen config")
        for p, expected in freeze["files"].items(): require(sha_file(p) == expected, "frozen diagnostic dependency changed: " + p)
        require(sha_file(self.claim) == freeze["claim_sha256"], "diagnostic grant claim changed")
        parent, verified = self._parent()
        require(verified["inherited"] == freeze["inherited"], "full parent cost changed")
        canonical, parent_claim = spend.claim_paths(parent, self.config.parent_anchor_sha256)
        require(read(canonical) == read(parent_claim) and read(canonical)["root"] == str(self.root), "dual successor identity changed")

    def _admit(self, label, request, ledger):
        self._guard()
        CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        prepared = read(self.root / "PREPARED_PROBE.json")
        index = len(ledger["calls"])
        require(index < 2 and label == LABELS[index] and request == prepared["requests"][index]["request"], "exact next bounded diagnostic identity required")
        require(request["role"] == "director" and request["stage"] == "goal_audit", "no writer or production stage authorized")
        if index:
            first = read(self.root / ledger["calls"][0]["receipt"])
            require(first["status"] == "contract_valid" and read(self.root / "CASE_GATE.json") == evaluate_cases(first["output"], prepared["requests"][0], read(self.config.private_expectations_path))
                and read(self.root / "CASE_GATE.json")["hard_route_gate_passed"] is True,
                "second diagnostic requires complete first contract and17 accepted controls")
        return True

    def runtime(self):
        freeze = read(self.root / "PRODUCTION_FREEZE.json")
        return runtime7.GoalContextRuntime(PROJECT, self.root, list(freeze["files"]), freeze["inherited"],
            profile=validate_profile(read(self.config.profile_path)), stage_limits=LIMITS, inherited_guard=self._guard,
            admission=self._admit, shared_lock=PROJECT / "data/creative_diagnostic_probe_claims/DISPATCH.lock",
            quota_state=None, client_factory_builder=self.client_factory_builder)

    def state(self, runtime, status, **details):
        try:
            if runtime is None: raise ValueError("runtime not constructed; current spend not verified")
            summary = runtime.summary(); pending = False; error = None
        except Exception as exc:
            summary = None; pending = True; error = {"type": type(exc).__name__, "message": str(exc)}
        value = {"schema": VERSION + "/state", "status": status, "updated_at": self.clock(), "spend": summary,
            "spend_verification_pending": pending, "text_ready_for_director": False, "creative_quality_passed": False,
            "media_authorized": False, "diagnostic_only": True, **details}
        if (self.root / "RUN_CLAIM.json").exists(): value["run_claim_sha256"] = sha_file(self.root / "RUN_CLAIM.json")
        if pending: value["spend_error"] = error
        write(self.root / "STATE.json", value)
        return value

    def invoke(self, runtime, label, prepared, validator):
        """Durable task claim precedes the SDK call; a claim is never refunded."""
        self._guard()
        CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
        request = prepared["request"]
        require(not any(row["label"] == label for row in read(runtime.ledger)["calls"]),
            "an already dispatched diagnostic cannot be replayed")
        write(self.root / "requests" / (label + ".json"), prepared, True)
        store = tasks.TaskStore(self.root / "TASKS.sqlite3")
        gid = "call_" + digest([self.config.grant_id, label])[:24]
        store.register_graph({"schema_version": tasks.GRAPH_SCHEMA, "graph_id": gid, "nodes": [
            {"node_id": "source", "kind": "source", "input": {"source_manifest": digest(read(runtime.ledger)["source_manifest"]),
                "request_sha256": digest(request)}, "depends_on": []},
            {"node_id": "result", "kind": "text", "input": {"label": label, "stage": request["stage"]}, "depends_on": ["source"]}]})
        scope_file = self.root / "USER_SCOPE.json"
        attempt = store.claim(gid, "result", {"provider_id": request["model"], "payload": request}, {
            "schema_version": tasks.AUTH_SCHEMA, "authorization_id": gid + ":scope", "graph_id": gid, "node_ids": ["result"],
            "scope": "text", "purpose": "dispatch", "source_sha256": store.snapshot(gid)["source_sha256"],
            "max_attempts": LIMITS[request["stage"]], "prior_attempts": 0, "allows_content_revision": False,
            "evidence_ref": str(scope_file) + "#" + request["stage"], "evidence_sha256": sha_file(scope_file)})
        receipt = runtime.dispatch(label, request, validator)
        directory = spend.session._inside(self.root / receipt["call_evidence"]["directory"], self.root / "call_evidence")
        raw = (directory / "response_body.raw").read_bytes() if (directory / "response_body.raw").exists() else b""
        known, outcome, tool = session_protocol.Session.classify_native(receipt)
        meta = receipt.get("response_metadata", {}); total = meta.get("total_tokens")
        store.accept_result(attempt["claim_id"], {"schema_version": tasks.RESULT_SCHEMA, "claim_id": attempt["claim_id"],
            "request_sha256": attempt["request_sha256"], "service_task_id": None, "outcome": outcome, "result_known": known,
            "usage_known": type(total) is int and total >= 0,
            "usage": {"unit": "reported_tokens", "amount": total} if type(total) is int and total >= 0 else None,
            "complete": meta.get("response_body_complete") is True, "complete_end": meta.get("finish_reason") in ("stop", "tool_calls"),
            "schema_tool_status": tool, "contract_valid": receipt["status"] == "contract_valid" if known else None,
            "raw_receipt": {"encoding": "base64", "body": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
                "http_status": meta.get("http_status_code")},
            "output": {"ordinal": receipt["ordinal"], "native_output": receipt.get("output")}})
        return receipt

    def run(self):
        require(not (self.root / "RUN_CLAIM.json").exists(), "probe RUN_CLAIM exists; never restart original run")
        _claim_new(self.root / "RUN_CLAIM.json", {"schema": VERSION + "/run_claim", "pid": os.getpid(),
            "root": str(self.root), "grant_id": self.config.grant_id,
            "prepared_sha256": sha_file(self.root / "PREPARED_PROBE.json"),
            "started_at": self.clock(), "automatic_restart": False})
        runtime = None
        try:
            runtime = self.runtime()
            require(not read(runtime.ledger)["calls"], "nonempty original probe ledger cannot restart")
            prepared = read(self.root / "PREPARED_PROBE.json")
            data = [read(self.config.blinded_cases_path), read(self.config.goal_receipt_path)["output"]]
            for index, label in enumerate(LABELS):
                item = prepared["requests"][index]; context = item["context_sha256"]
                validator = (lambda output: scope.validate_case_scope(output, data[0], context_sha256=context)) if not index else (lambda output: scope.validate_scope(output, data[1], context_sha256=context))
                receipt = self.invoke(runtime, label, item, validator)
                meta = receipt.get("response_metadata", {})
                complete_known = type(meta.get("total_tokens")) is int and meta["total_tokens"] >= 0 and meta.get("response_body_complete") is True and meta.get("finish_reason") in ("stop", "tool_calls")
                if not complete_known: return self.state(runtime, "halt_interface_or_unknown", receipt_ordinal=receipt["ordinal"], automatic_retry=False)
                if receipt["status"] == "interface_rejected": return self.state(runtime, "halt_protocol_requires_diagnosis", receipt_ordinal=receipt["ordinal"])
                if receipt["status"] != "contract_valid": return self.state(runtime, "halt_case_contract_rejected" if not index else "halt_scope_contract_rejected", receipt_ordinal=receipt["ordinal"])
                # Reconcile exact bytes/wire before using a native report as a gate.
                ledger = read(runtime.ledger)
                spend.verify_known_receipt(self.root, ledger["calls"][-1], ledger["source_manifest"], spend.session.Reader())
                if not index:
                    gate = evaluate_cases(receipt["output"], item, read(self.config.private_expectations_path))
                    write(self.root / "CASE_GATE.json", gate, True)
                    if not gate["hard_route_gate_passed"]: return self.state(runtime, "halt_case_routing_mismatch", receipt_ordinal=receipt["ordinal"], hard_case_gate=gate)
                else:
                    decision = receipt["validation"]
                    write(self.root / "FULL_SCOPE_DECISION.json", decision, True)
                    return self.state(runtime, "halt_scope_textual_ambiguity" if decision["known_text_content_requires_clarification"] else "diagnostic_completed_not_creative",
                        receipt_ordinal=receipt["ordinal"], scope_decision=decision, creative_quality_passed=False)
        except Exception as exc:
            write(self.root / "EXECUTION_ERROR.json", {"error_type": type(exc).__name__, "error": str(exc), "automatic_retry": False}, True)
            self.state(runtime, "halt_execution_reconciliation", error_type=type(exc).__name__, error=str(exc))
            raise


def prepare_preview(config, **dependencies):
    return Probe(config, **dependencies).prepare_preview()
