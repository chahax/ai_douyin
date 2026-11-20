"""Fixed-registry production adapter; original v1 native/storage protocol shared.

No old module globals are changed. The only duplicated verification glue is the
old public verifier's noninjectable Session construction; all native compilers,
requests, SDK/SQL readers and execution are reused explicitly.
"""
from copy import deepcopy
from pathlib import Path
import sys
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))

from scripts import creative_world_scene_production_probe_v1 as base
from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
from scripts import creative_world_scene_production_source_v1 as source_entry

VERSION = "creative_world_scene_production_probe/v2"
SHARED_PROTOCOL = base.VERSION
Config = base.Config
load_material = source_entry.load_material


def direction_request(material, profile, diagnostics=()):
    return source_entry.bind_request(base.direction_request(material, profile, diagnostics), material)


def performance_request(material, profile, native, diagnostics=()):
    return source_entry.bind_request(base.performance_request(material, profile, native, diagnostics), material)


def review_request(material, profile, direction, performance):
    return source_entry.bind_request(base.review_request(material, profile, direction, performance), material)


def entry_binding():
    return {"schema": VERSION + "/entry_binding", "shared_production_protocol": SHARED_PROTOCOL,
        "fixed_registry_version": registry.VERSION, "entry_module_path": str(Path(__file__).resolve()),
        "entry_module_sha256": base.sha(__file__), "registry_module_path": str(Path(registry.__file__).resolve()),
        "registry_module_sha256": base.sha(registry.__file__),
        "source_compiler_files": base._hashes((source_entry.__file__, source_entry.derived.__file__))}


class Session(base.Session):
    def __init__(self, config, *, client_factory_builder=None):
        super().__init__(config, text_verifier=registry.verify_text_handoff, client_factory_builder=client_factory_builder)

    def preview(self):
        parent = self.parent(); material = load_material(parent); profile = material["values"]["profile"]
        first = direction_request(material, profile)
        code = {Path(__file__).resolve(), Path(source_entry.__file__).resolve(), Path(source_entry.derived.__file__).resolve()}
        for module in tuple(base.sys.modules.values()):
            raw = getattr(module, "__file__", None)
            if raw:
                path = Path(raw).resolve()
                if path.suffix == ".py" and any(path.is_relative_to(base.PROJECT / d) for d in ("src", "scripts")): code.add(path)
        files = {**parent["source_files"], **base._hashes([*sorted(code), self.config.story_ledger_path,
            base.media.CATALOG, *(r["path"] for r in material["selected_stills"]),
            *(r["asset_gender_evidence"]["path"] for r in material["selected_stills"] if "asset_gender_evidence" in r), *self.config.extra_source_files])}
        result = {"schema": SHARED_PROTOCOL + "/preview", "config": base.asdict(self.config), "parent": parent,
            "parent_identity_sha256": base.digest(parent["parent_identity"]), "source_files": files,
            "stage_limits": base.LIMITS, "first_request": first, "first_request_sha256": base.digest(first["request"]),
            "provider_calls": 0, "media_submissions": 0, "first_segment_only": True}
        result["entry_binding"] = entry_binding()
        result["source_files"].update(base._hashes((__file__, registry.__file__)))
        return result

    def authorization_template(self, preview):
        result = super().authorization_template(preview)
        result["entry_binding"] = entry_binding()
        return result

    def _guard(self):
        super()._guard()
        if (self.text_verifier is not registry.verify_text_handoff
                or base.read(self.root / "PREVIEW.json").get("entry_binding") != entry_binding()
                or base.read(self.config.authorization_path).get("entry_binding") != entry_binding()):
            raise ValueError("fixed v2 production entry/registry differs from frozen scope")
        return True

    def _rebuild(self, label, ledger):
        """Reuse original native sequence, with an explicit source loader."""
        material = load_material(base.read(self.root / "PARENT_TEXT_VERIFIED.json")); profile = base.read(self.root / "PROFILE.json")
        receipts = [base.read(self.root / row["receipt"]) for row in ledger["calls"]]
        directions, perfs, reviews = [], [], []; direction_diagnostics, perf_diagnostics = [], []
        latest_direction = latest_perf = None
        for receipt in receipts:
            value = base.NativeSession.known(receipt, receipt["label"], require_valid=False); decision = self._decision(receipt)
            if receipt["label"].startswith("whole_direction"):
                directions.append(receipt); latest_direction = value
                if value.get("direction", {}).get("availability") == "unknown": raise ValueError("uncertain native whole direction cannot continue")
                if not decision["valid"]: direction_diagnostics.append({"previous_complete_document": value, "diagnostics": decision})
            elif receipt["label"].startswith("first_performance"):
                perfs.append(receipt); latest_perf = value
                if value.get("availability") == "unknown": raise ValueError("uncertain native performance cannot continue")
                if not decision["valid"]:
                    diag = {"previous_complete_document": value, "diagnostics": decision}; perf_diagnostics.append(diag)
                    direction_diagnostics.append({"previous_complete_direction": latest_direction, "failed_local_performance": diag})
            else:
                reviews.append(receipt)
                if not decision.get("valid") or decision.get("uncertainties") or decision.get("accepted"): raise ValueError("terminal production review cannot continue")
                perf_diagnostics.append({"previous_complete_document": latest_perf, "native_production_review": value, "diagnostics": decision})
        if label.startswith("whole_direction"):
            if label != f"whole_direction_{len(directions)+1:02}": raise ValueError("direction ordinal differs")
            if receipts and not ((receipts[-1]["label"].startswith("whole_direction") or receipts[-1]["label"].startswith("first_performance")) and not self._decision(receipts[-1])["valid"]):
                raise ValueError("no known complete direction-revision predecessor")
            return direction_request(material, profile, direction_diagnostics)
        if not directions or not self._decision(directions[-1])["valid"]: raise ValueError("valid actual whole direction required")
        if label.startswith("first_performance"):
            if label != f"first_performance_{len(perfs)+1:02}" or not receipts[-1]["label"].startswith(("whole_direction", "first_production_review")): raise ValueError("valid actual acting predecessor and ordinal required")
            return performance_request(material, profile, latest_direction, perf_diagnostics)
        if label != f"first_production_review_{len(reviews)+1:02}" or not perfs or not receipts[-1]["label"].startswith("first_performance") or not self._decision(perfs[-1])["valid"]:
            raise ValueError("valid actual performance required before production review")
        return review_request(material, profile, latest_direction, latest_perf)

    def run(self):
        if not (self.root / "PRODUCTION_FREEZE.json").is_file(): raise ValueError("separate prepare required")
        base.policy.new_claim(self.root / "RUN_CLAIM.json", {"schema": SHARED_PROTOCOL + "/run_claim", "root": str(self.root),
            "pid": base.os.getpid(), "started_at": base.now(), "automatic_restart": False, "freeze_sha256": base.sha(self.root / "PRODUCTION_FREEZE.json")})
        runtime = None
        try:
            runtime = self.runtime(); self._guard(); base.CountedExecution(self.config.counter_root).assert_dispatch_allowed(self.config.round_key)
            if base.read(runtime.ledger)["calls"]: raise ValueError("nonempty original RUN cannot restart")
            material = load_material(base.read(self.root / "PARENT_TEXT_VERIFIED.json")); profile = base.read(self.root / "PROFILE.json")
            direction_diagnostics, perf_diagnostics = [], []; perf_count = review_count = 0
            for d in (1, 2, 3):
                prepared = direction_request(material, profile, direction_diagnostics)
                direction, decision, _ = self.invoke(runtime, f"whole_direction_{d:02}", prepared, lambda value: base.compile_direction(value, material))
                if direction.get("direction", {}).get("availability") == "unknown": return self.state(runtime, "halt_whole_direction_uncertain")
                if not decision["valid"]: direction_diagnostics.append({"previous_complete_document": direction, "diagnostics": decision}); continue
                while perf_count < 3:
                    perf_count += 1; prepared = performance_request(material, profile, direction, perf_diagnostics)
                    performance, decision, _ = self.invoke(runtime, f"first_performance_{perf_count:02}", prepared,
                        lambda value: base.compile_performance(value, material, direction))
                    if performance.get("availability") == "unknown": return self.state(runtime, "halt_first_performance_uncertain")
                    if not decision["valid"]:
                        diag = {"previous_complete_document": performance, "diagnostics": decision}; perf_diagnostics.append(diag)
                        direction_diagnostics.append({"previous_complete_direction": direction, "failed_local_performance": diag}); break
                    prepared = review_request(material, profile, direction, performance); review_count += 1
                    review, decision, _ = self.invoke(runtime, f"first_production_review_{review_count:02}", prepared, lambda value: base.validate_review(value, prepared))
                    if not decision["valid"]: return self.state(runtime, "halt_production_review_contract", native_review_ordinal=base.read(runtime.ledger)["calls"][-1]["ordinal"])
                    if decision["uncertainties"]: return self.state(runtime, "halt_production_review_uncertain", decision=decision)
                    if decision["accepted"]: return self._save(runtime, material, direction, performance, review, prepared, decision)
                    perf_diagnostics.append({"previous_complete_document": performance, "native_production_review": review, "diagnostics": decision})
                if perf_count >= 3: break
            return self.state(runtime, "halt_first_production_capacity_exhausted")
        except base.Halt as stopped: return self.state(runtime, stopped.status, **stopped.details)
        except Exception as error:
            base.write(self.root / "EXECUTION_ERROR.json", {"type": type(error).__name__, "message": str(error), "automatic_restart": False}, True)
            return self.state(runtime, "halt_execution_reconciliation", error=str(error))


def verify_first_segment_handoff(root, *, text_verified=None):
    """Same deep v1 proof checks, using the closed v2 Session and text selector."""
    s = Session.open(root); s._guard(); actual_parent = s.parent()
    if text_verified is not None and base.digest(actual_parent) != base.digest(text_verified):
        raise ValueError("provided text proof differs from actual fixed native verifier")
    rt = s.runtime(); state = base.read(s.root / "STATE.json"); proofpath = s.root / "FIRST_SEGMENT_HANDOFF.json"; proof = base.read(proofpath)
    if not (state["status"] == "first_segment_ready_for_media" and state["spend_verification_pending"] is False
            and proof.get("schema") == SHARED_PROTOCOL + "/first_segment_handoff" and proof.get("first_segment_only") is True
            and proof.get("text_handoff_sha256") == actual_parent["handoff_sha256"] and proof.get("native_identity") == actual_parent["identity"]
            and proof.get("media_submitted") is False and proof.get("human_quality_approved") is False and proof.get("later_segments_acting_approved") is False
            and state["production_handoff_sha256"] == base.sha(proofpath) and proof["freeze_sha256"] == base.sha(s.root / "PRODUCTION_FREEZE.json")
            and proof["run_claim_sha256"] == state["run_claim_sha256"] == base.sha(s.root / "RUN_CLAIM.json")):
        raise ValueError("original complete first-segment production state required")
    summary = rt.summary(); ledger = base.read(rt.ledger)
    if summary != state["spend"] or summary["new_unknown_token_reservations"] != 0:
        raise ValueError("original settled production usage differs")
    reader = base.evidence.Reader()
    receipts = [base._verify_receipt(s.root, row, ledger["source_manifest"], reader) for row in ledger["calls"]]
    base.evidence._tasks(reader, s.root, ledger, receipts, s.config.grant_id)
    for index, (row, receipt) in enumerate(zip(ledger["calls"], receipts)):
        intent = reader.json(s.root / "call_intents" / (row["label"] + ".json")); prefix = {**ledger, "calls": ledger["calls"][:index]}
        if (base.digest(intent) != base.digest({"label": row["label"], "request": receipt["request"], "ledger_prefix_sha256": base.digest(prefix["calls"])})
                or base.digest(s._rebuild(row["label"], prefix)["request"]) != base.digest(receipt["request"])):
            raise ValueError("original request/native predecessor reconstruction differs")
    names = ("NATIVE_DIRECTION", "COMPILED_DIRECTION", "NATIVE_FIRST_PERFORMANCE", "COMPILED_FIRST_PERFORMANCE",
        "NATIVE_FIRST_PRODUCTION_REVIEW", "FIRST_PRODUCTION_DECISION", "RENDERED_FIRST_SEGMENT")
    if set(proof["artifact_files"]) != {str((s.root / (key + ".json")).resolve()) for key in names}:
        raise ValueError("exact first-segment native and derived artifact set required")
    for path, expected in proof["artifact_files"].items(): reader.verify(base._inside(path), expected)
    records = {key: base.read(s.root / (key + ".json")) for key in ("NATIVE_DIRECTION", "NATIVE_FIRST_PERFORMANCE", "NATIVE_FIRST_PRODUCTION_REVIEW")}
    for value in records.values():
        if not any(base.digest(r.get("output")) == base.digest(value) and r["status"] == "contract_valid" for r in receipts):
            raise ValueError("production artifact is not an actual valid native receipt")
    material = load_material(actual_parent); direction, performance, review = records.values()
    prepared = review_request(material, base.read(s.root / "PROFILE.json"), direction, performance)
    checked = base.validate_review(review, prepared)
    if not (checked["accepted"] and base.digest(checked) == base.digest(proof["decision"]) and prepared["context_sha256"] == proof["review_context_sha256"]):
        raise ValueError("same-native production review does not pass")
    rendered = prepared["rendered"]
    if base.digest(base.read(s.root / "RENDERED_FIRST_SEGMENT.json")) != base.digest(rendered): raise ValueError("actual deterministic render changed")
    for name, expected in {"COMPILED_DIRECTION": base.compile_direction(direction, material)["compiled_direction"],
            "COMPILED_FIRST_PERFORMANCE": rendered["performance"], "FIRST_PRODUCTION_DECISION": checked}.items():
        if base.digest(base.read(s.root / (name + ".json"))) != base.digest(expected): raise ValueError("derived production artifact differs from original native: " + name)
    story = base.read(s.config.story_ledger_path)
    for name in ("STATE.json", "CALL_LEDGER.json", "PRODUCTION_FREEZE.json", "RUN_CLAIM.json", "FIRST_SEGMENT_HANDOFF.json"):
        reader.bytes(s.root / name)
    result = {"schema": SHARED_PROTOCOL + "/verified_first_segment", "valid": True, "accepted": True, "status": "first_segment_ready_for_media",
        "text_handoff_sha256": actual_parent["handoff_sha256"], **{k: v for k, v in actual_parent["identity"].items() if k in ("native_goal_sha256", "native_script_sha256", "native_setup_sha256", "compiled_script_sha256", "derived_script_sha256")},
        "segment_ordinal": 1, "beat_id": material["script"]["beats"][0]["id"], "story_id": story["story_id"],
        "source_refs": rendered["performance"]["source_refs"], "duration_seconds": rendered["encoded_duration_seconds"],
        **{k: rendered[k] for k in ("native_source_duration_seconds", "native_integer_duration_seconds", "encoded_duration_seconds", "encoding_hold_seconds", "frame_length")},
        "production_review_context_sha256": prepared["context_sha256"], "encoding_hold_reviewed": checked["accepted"],
        "actual_video_prompt": rendered["prompt"], "video_prompt_sha256": rendered["prompt_sha256"],
        "reference_map": base.reference_map(material, direction, reviewed=True), "production_handoff_path": str(proofpath), "production_handoff_sha256": base.sha(proofpath),
        "proof_files": [{"path": p, "file_sha256": h} for p, h in {**proof["artifact_files"], **{p: row["sha256"] for p, row in reader.files.items()}}.items()],
        "spend": summary, "first_segment_only": True, "later_segments_acting_approved": False, "authorizes_media_dispatch": False,
        "human_quality_approved": False, "entry_binding": entry_binding()}
    if "script_source_descriptor" in material: result["source_descriptor"] = deepcopy(material["script_source_descriptor"])
    result["encoding_certificate_sha256"] = base.digest({k: result[k] for k in ("native_source_duration_seconds", "native_integer_duration_seconds",
        "encoded_duration_seconds", "encoding_hold_seconds", "frame_length", "video_prompt_sha256", "production_review_context_sha256")})
    # Bind the new closed entry itself as well as the original shared protocol.
    result["proof_files"].extend({"path": str(Path(p).resolve()), "file_sha256": base.sha(p)} for p in (__file__, registry.__file__, source_entry.__file__, source_entry.derived.__file__))
    return result


def main(argv=None):
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("action", choices=("preview", "authorization", "prepare", "run", "verify")); parser.add_argument("path")
    args = parser.parse_args(argv)
    if args.action == "verify": result = verify_first_segment_handoff(args.path)
    else:
        s = Session.open(args.path) if args.action == "run" else Session(base.read(args.path))
        result = s.authorization_template(s.preview()) if args.action == "authorization" else getattr(s, args.action)()
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
