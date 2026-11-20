"""Closed v5-aware live preparation, sharing v1/v2 graph certificate formats.

No offline bypass, model call, media claim or POST is provided. New fixed source
verifiers and this adapter's bytes are independently bound and rebuilt.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import shutil
import sys
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))

from scripts import creative_world_scene_media_probe_v1 as base
from scripts import creative_world_scene_media_probe_v2 as encoding
from scripts import creative_world_scene_production_probe_v2 as production_entry
from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
from scripts import creative_world_scene_production_source_v1 as source_entry
from scripts.creative_resume_dispatch_v3 import digest

VERSION = "creative_world_scene_media_probe/v3"
Config = base.Config


def entry_binding():
    paths = (__file__, base.__file__, encoding.__file__, production_entry.__file__, registry.__file__, source_entry.__file__, source_entry.derived.__file__)
    return {"schema": VERSION + "/entry_binding", "shared_prepared_protocols": [base.VERSION, encoding.VERSION],
        "fixed_text_registry_version": registry.VERSION, "fixed_production_entry_version": production_entry.VERSION,
        "code_files": {str(Path(p).resolve()): base.sha(p) for p in paths}}


def verified_sources(config):
    project = Path(config.project).resolve()
    base.check(project == base.PROJECT.resolve(), "actual project workspace required")
    text_root, production_root = (base._inside(p, project) for p in (config.text_root, config.production_root))
    text = registry.verify_text_handoff(text_root)
    base.check(text.get("valid") is True and text.get("accepted") is True and text.get("status") == "text_ready_for_director", "actual complete text is not ready")
    handoff = base._binding({"path": text["handoff_path"], "file_sha256": text["handoff_sha256"]}, project)
    base.check(handoff.parent == text_root, "text certificate belongs to another source root")
    documents = source_entry.verify_documents(text); paths, native = documents["paths"], documents["values"]
    base.check(all(p.is_relative_to(text_root) for p in paths.values()), "native text paths belong to another source root")
    identities = {"native_goal_sha256": digest(native["goal"]), "native_script_sha256": digest(native["raw_script"]),
        "compiled_script_sha256": digest(native["compiled_script"]), "native_setup_sha256": digest(native["setup"])}
    if documents["source_descriptor"] is not None: identities["derived_script_sha256"] = digest(native["derived_script"])
    base.check(all(text["identity"].get(k) == v for k, v in identities.items()), "verified native text identity differs")
    production = production_entry.verify_first_segment_handoff(production_root, text_verified=text)
    base.check(production.get("schema") == base.PRODUCTION_VERSION and production.get("valid") is True
        and production.get("accepted") is True and production.get("status") == "first_segment_ready_for_media"
        and production.get("entry_binding") == production_entry.entry_binding(), "actual fixed-entry first-segment proof required")
    base.check(production.get("text_handoff_sha256") == text["handoff_sha256"]
        and all(production.get(k) == v for k, v in identities.items() if k != "compiled_script_sha256"), "production binds another text source")
    if documents["source_descriptor"] is not None:
        base.check(production.get("source_descriptor") == documents["source_descriptor"]
            and production.get("compiled_script_sha256") == identities["compiled_script_sha256"], "actual canonical production source identity differs")
    certificate = base._binding({"path": production["production_handoff_path"], "file_sha256": production["production_handoff_sha256"]}, project)
    base.check(certificate.is_relative_to(production_root), "production certificate belongs to another run")
    base.check(type(production.get("proof_files")) is list and bool(production["proof_files"]), "original production proof files required")
    for row in production["proof_files"]: base._binding(row, project)
    canonical = documents["canonical_script"]; first = canonical["beats"][0]
    base.check(production.get("segment_ordinal") == 1 and production.get("beat_id") == first["id"], "only first native segment in first beat supported")
    bank = base.sources.catalog(canonical); refs = production.get("source_refs")
    base.check(type(refs) is list and bool(refs) and refs == list(bank)[:len(refs)]
        and all(bank[ref]["beat_id"] == first["id"] for ref in refs), "exact first-beat source prefix required; no native line rewritten")
    prompt = production.get("actual_video_prompt")
    base.check(isinstance(prompt, str) and bool(prompt.strip()) and base.text_sha(prompt) == production.get("video_prompt_sha256"), "actual reviewed prompt identity differs")
    timing = base.frame_timing(production["duration_seconds"])
    timing["native_encoding"] = encoding.verify_encoding(production)
    return text, production, native, paths, timing


def prepare(config):
    """Live fixed verifiers; only explicit caller action inspects the service."""
    text, production, native, paths, timing = verified_sources(config)
    references = base.reference_bindings(config, production, native["goal"])
    output = base._inside(config.output_root, config.project)
    base.check(not output.is_relative_to(base.OLD.resolve()), "never share the other chat's old media root")
    base.check(not output.exists(), "existing preparation cannot be overwritten/retried")
    service = base._inside(config.service_root, config.project); snapshot = base.inspect_service()
    base.check(type(snapshot) is dict and snapshot.get("read_only") is True, "actual read-only service snapshot required")
    base.check(not snapshot["queue"]["queue_running"] and not snapshot["queue"]["queue_pending"], "preserve active service task")
    base.check("minimax_h3_ref2va_pruned_int8_convrot.safetensors" in snapshot["h3_model_names"], "actual REF2VA model unavailable")
    argv = snapshot.get("system_stats", {}).get("argv", [])
    for flag, target in (("--input-directory", service / "input"), ("--output-directory", service / "output")):
        base.check(flag in argv and Path(argv[argv.index(flag)+1]).resolve() == target.resolve(), "service input/output workspace differs")
    base.check("--offline" in argv and "--preview-method" in argv and argv[argv.index("--preview-method")+1] == "none", "existing offline/no-preview service required")
    template = base._inside(config.template_path, config.project); old_status = base.read(template.parent / "RUN_STATUS.json")
    base.check(old_status.get("state") == "success" and old_status.get("completed") is True and base.sha(template) == old_status["graph_sha256"], "reuse only original successful graph wiring")
    ledger_path = base._inside(config.ledger_path, config.project); ledger = base.read(ledger_path)
    base.check(ledger.get("schema") == "same_story_local_h3_video_failure_ledger/v1"
        and ledger.get("not_a_new_story_reset") is True and ledger.get("old_receipts_and_unknowns_retained") is True
        and all(type(ledger.get(k)) is int and ledger[k] >= 0 for k in ("failure_limit", "failures_used", "known_rejections", "technical_failures", "observed_local_video_submissions"))
        and 0 <= ledger["failures_used"] < ledger["failure_limit"] and production.get("story_id") == ledger.get("story_id")
        and ledger["failures_used"] == ledger["known_rejections"] + ledger["technical_failures"], "same-story failure ledger must be inherited, never reset")
    unique = "world_scene_" + base.text_sha(str(output))[:20]; prefix = "world_scene_live/" + unique
    for i, row in enumerate(references, 1):
        target = service / "input" / unique / ("reference_" + str(i) + ".png")
        base.check(not target.exists() or base.sha(target) == row["source_sha256"], "never overwrite different reference bytes")
        row.update(input_path=str(target), input_relative_path=target.relative_to(service / "input").as_posix())
    graph = base.build_graph(base.read(template), production["actual_video_prompt"], references, timing, prefix, config.seed)
    output.mkdir(parents=True, exist_ok=False)
    for row in references:
        target = Path(row["input_path"]); target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists(): shutil.copyfile(row["source_path"], target)
        base.check(base.sha(target) == row["source_sha256"], "staged reference copy differs")
    base.dump(output / "workflow_api.json", graph)
    with (output / "PROMPT.txt").open("x", encoding="utf-8") as stream: stream.write(production["actual_video_prompt"])
    for name, value in (("REFERENCE_MAP", references), ("TEXT_VERIFIED", text), ("PRODUCTION_VERIFIED", production), ("SERVICE_READONLY", snapshot)):
        base.dump(output / (name + ".json"), value)
    # These are genuinely generated shared protocols, not converted old flags.
    shared = {"schema": base.VERSION + "/prepared", "status": "prepared_requires_root_review_and_single_submitter",
        "synthetic": False, "eligible_for_root_single_submit_review": True, "provider_calls": 0, "media_submissions": 0,
        "media_claim_created": False, "submit_supported_here": False, "graph_sha256": base.sha(output / "workflow_api.json"),
        "prompt_sha256": base.sha(output / "PROMPT.txt"), "reference_map_sha256": base.sha(output / "REFERENCE_MAP.json"),
        "text_handoff_sha256": text["handoff_sha256"], "production_handoff_sha256": production["production_handoff_sha256"],
        "source_refs": production["source_refs"], "native_identity": deepcopy(text["identity"]), "timing": timing,
        "width": 1280, "height": 704, "native1280_generation_verified": False, "output_root": str(service / "output"), "output_prefix": prefix,
        "template": {"path": str(template), "file_sha256": base.sha(template), "reuse": "node_wiring_only_not_rejected_content"},
        "failure_ledger": {"path": str(ledger_path), "file_sha256": base.sha(ledger_path), "story_id": ledger["story_id"], "failures_used": ledger["failures_used"], "failure_limit": ledger["failure_limit"], "reset": False},
        "source_paths": {key: {"path": str(path), "file_sha256": base.sha(path)} for key, path in paths.items()},
        "save_contract": {"video": "MP4 with native audio", "audio": "independent FLAC", "first_last": "same native decode image tensor PNG; never MP4 extraction",
            "expected_dimensions": [1280, 704], "expected_frame_count": timing["length"], "expected_fps": 24,
            "verify": "original history plus containers/packets/hash and PNG structure; never decode/listen/ASR"},
        "review_status": "awaiting_human_review", "content_review": None, "old_rejected_tail_used": False,
        "automatic_retry": False, "automatic_resolution_fallback": False, "following_segment_authorized": False}
    base.dump(output / "PREPARED.json", shared); base.dump(output / "MEDIA_CONFIG_V2.json", asdict(config))
    v2 = {"schema": encoding.VERSION + "/prepared", "status": shared["status"], "config_path": str(output / "MEDIA_CONFIG_V2.json"),
        "config_sha256": base.sha(output / "MEDIA_CONFIG_V2.json"), "base_prepared_path": str(output / "PREPARED.json"), "base_prepared_sha256": base.sha(output / "PREPARED.json"),
        "native_encoding": timing["native_encoding"], "graph_sha256": shared["graph_sha256"], "production_handoff_sha256": shared["production_handoff_sha256"],
        "text_handoff_sha256": shared["text_handoff_sha256"], "synthetic": False, "eligible_for_root_single_submit_review": True,
        "media_submissions": 0, "media_claim_created": False, "submit_supported_here": False, "review_status": "awaiting_human_review"}
    base.dump(output / "PREPARED_V2.json", v2)
    base.dump(output / "MEDIA_ENTRY_V3.json", entry_binding())
    return {"schema": VERSION + "/prepared", "status": shared["status"], "entry_binding": entry_binding(),
        "shared_prepared_path": str(output / "PREPARED.json"), "shared_v2_path": str(output / "PREPARED_V2.json"),
        "media_submissions": 0, "media_claim_created": False, "submit_supported_here": False}


def verify_prepared(root):
    root = base._inside(root, base.PROJECT)
    base.check(base.read(root / "MEDIA_ENTRY_V3.json") == entry_binding(), "frozen fixed media entry changed")
    v2, shared = base.read(root / "PREPARED_V2.json"), base.read(root / "PREPARED.json")
    base.check(v2.get("schema") == encoding.VERSION + "/prepared" and shared.get("schema") == base.VERSION + "/prepared"
        and v2.get("synthetic") is False and shared.get("synthetic") is False
        and v2.get("eligible_for_root_single_submit_review") is True and shared.get("eligible_for_root_single_submit_review") is True,
        "synthetic/offline preparation cannot be used live")
    base.check(v2.get("base_prepared_path") == str(root / "PREPARED.json") and v2.get("base_prepared_sha256") == base.sha(root / "PREPARED.json")
        and v2.get("config_path") == str(root / "MEDIA_CONFIG_V2.json") and v2.get("config_sha256") == base.sha(root / "MEDIA_CONFIG_V2.json"), "shared prepared/config identity changed")
    config = Config(**base.read(root / "MEDIA_CONFIG_V2.json"))
    base.check(Path(config.output_root).resolve() == root, "preparation belongs to another root")
    text, production, native, paths, timing = verified_sources(config)
    base.check(base.read(root / "TEXT_VERIFIED.json") == text and base.read(root / "PRODUCTION_VERIFIED.json") == production, "actual native source proof differs")
    base.check(v2["native_encoding"] == shared["timing"]["native_encoding"] == timing["native_encoding"] and shared["timing"] == timing, "actual native encoding changed")
    references = base.reference_bindings(config, production, native["goal"])
    unique = "world_scene_" + base.text_sha(str(root))[:20]; prefix = "world_scene_live/" + unique; files = {}
    def bind(path):
        path = base._inside(path, config.project); files[str(path)] = base.sha(path); return path
    for i, row in enumerate(references, 1):
        target = Path(config.service_root).resolve() / "input" / unique / ("reference_" + str(i) + ".png")
        row.update(input_path=str(target), input_relative_path=target.relative_to(Path(config.service_root).resolve() / "input").as_posix())
        base.check(base.sha(target) == row["source_sha256"], "staged reference bytes changed")
        bind(target); bind(row["source_path"])
        if "asset_gender_evidence" in row: bind(row["asset_gender_evidence"]["path"])
    base.check(base.read(root / "REFERENCE_MAP.json") == references, "ordered reference bindings changed")
    template, ledger = bind(config.template_path), bind(config.ledger_path)
    base.check(shared["template"]["file_sha256"] == base.sha(template) and shared["failure_ledger"]["file_sha256"] == base.sha(ledger), "template or same-story ledger changed")
    graph = base.build_graph(base.read(template), production["actual_video_prompt"], references, timing, prefix, config.seed)
    actual = base.read(root / "workflow_api.json")
    base.check(actual == graph and base.sha(root / "workflow_api.json") == shared["graph_sha256"] == v2["graph_sha256"], "actual graph compilation differs")
    base.check((root / "PROMPT.txt").read_text("utf-8") == production["actual_video_prompt"] and base.sha(root / "PROMPT.txt") == shared["prompt_sha256"], "actual reviewed prompt differs")
    base.check(shared["output_prefix"] == prefix and shared["reference_map_sha256"] == base.sha(root / "REFERENCE_MAP.json")
        and shared["output_root"] == str(Path(config.service_root).resolve() / "output")
        and (shared["width"], shared["height"]) == (1280, 704)
        and shared["native_identity"] == text["identity"] and shared["source_refs"] == production["source_refs"]
        and shared["text_handoff_sha256"] == v2["text_handoff_sha256"] == text["handoff_sha256"]
        and shared["production_handoff_sha256"] == v2["production_handoff_sha256"] == production["production_handoff_sha256"], "actual shared source/namespace differs")
    base.check(shared["source_paths"] == {key: {"path": str(path), "file_sha256": base.sha(path)} for key, path in paths.items()}
        and shared["template"]["path"] == str(template) and shared["failure_ledger"]["path"] == str(ledger)
        and shared["failure_ledger"]["story_id"] == production["story_id"] and shared["failure_ledger"]["reset"] is False,
        "native source/template/story path binding differs")
    for row in shared["source_paths"].values():
        base.check(base.sha(row["path"]) == row["file_sha256"], "native source file changed"); bind(row["path"])
    for row in production["proof_files"]:
        base.check(base.sha(row["path"]) == row["file_sha256"], "original production proof changed"); bind(row["path"])
    for path, expected in text["source_files"].items():
        base.check(base.sha(path) == expected, "original text dependency changed"); bind(path)
    for name in ("PREPARED.json", "PREPARED_V2.json", "MEDIA_CONFIG_V2.json", "MEDIA_ENTRY_V3.json", "workflow_api.json",
            "PROMPT.txt", "REFERENCE_MAP.json", "TEXT_VERIFIED.json", "PRODUCTION_VERIFIED.json", "SERVICE_READONLY.json"): bind(root / name)
    for path in entry_binding()["code_files"]: bind(path)
    bind(config.catalog_path)
    return {"schema": VERSION + "/verified_prepared", "valid": True, "accepted": True, "prepared_root": str(root), "config": asdict(config),
        "paths": {"text_root": config.text_root, "production_root": config.production_root}, "base_prepared": shared, "prepared_v2": v2,
        "graph": actual, "reference_map": references, "text_verified": text, "production_verified": production,
        "source_files": files, "entry_binding": entry_binding(), "media_submissions": 0, "media_claim_created": False, "authorizes_media_dispatch": False}


def main(argv=None):
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("action", choices=("run", "verify")); parser.add_argument("path")
    args = parser.parse_args(argv)
    result = prepare(Config(**base.read(args.path))) if args.action == "run" else verify_prepared(args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
