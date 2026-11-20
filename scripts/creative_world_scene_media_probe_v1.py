"""Prepare one H3 first-segment graph after two real source verifiers.

No POST, SDK, claim, retry, pixel decoding or video/audio review exists here.
The live CLI imports only the two project-owned verifier modules named below.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import shutil
import sys
import urllib.request
from jsonschema import ValidationError

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))
from src.content_factory import creative_world_scene_context_v1 as world
from src.content_factory import creative_video_trial_contract_v1 as sources

VERSION = "creative_world_scene_media_probe/v1"
PRODUCTION_VERSION = "creative_world_scene_production_probe/v1/verified_first_segment"
SERVICE = PROJECT / "data/local_media_tests/minimax_h3_20261015"
OLD = PROJECT / "data/video_generation/h3_project_script_20261015"
CATALOG = PROJECT / "data/visual_asset_library/personal_catalog_v1/CATALOG.json"
DEFAULT_TEMPLATE = OLD / "03_opening/workflow_api.json"
DEFAULT_LEDGER = OLD / "STORY_VIDEO_FAILURE_LEDGER.json"
FIXED_ASSETS = (("h3.scene.supermarket_backroom.20261015.v2", "v2"),
    ("nativeboard.photoreal.20261006.r1.C01", "round_01"),
    ("nativeboard.photoreal.20261006.r1.C02", "round_01"))


class PreparationBlocked(ValueError): pass
def check(value, reason):
    if not value: raise PreparationBlocked(reason)
def read(path): return json.loads(Path(path).read_text("utf-8-sig"))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def text_sha(value): return hashlib.sha256(value.encode("utf-8")).hexdigest()
def dump(path, value):
    with Path(path).open("x", encoding="utf-8") as f: json.dump(value, f, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class Config:
    text_root: str
    production_root: str
    output_root: str
    seed: int
    project: str = str(PROJECT)
    service_root: str = str(SERVICE)
    catalog_path: str = str(CATALOG)
    template_path: str = str(DEFAULT_TEMPLATE)
    ledger_path: str = str(DEFAULT_LEDGER)


def _inside(path, project):
    result = Path(path).resolve()
    check(result.is_relative_to(Path(project).resolve()), "path must stay inside the project workspace")
    return result


def _binding(row, project):
    check(type(row) is dict and set(row) >= {"path", "file_sha256"}, "exact source file binding required")
    path = _inside(row["path"], project)
    check(path.is_file() and sha(path) == row["file_sha256"], "bound source bytes changed: " + str(path))
    return path


def frame_timing(duration):
    check(type(duration) in (int, float) and math.isfinite(duration) and 0 < duration <= 362/24,
        "native first-segment duration must be finite, positive and no more than362/24 seconds")
    frames = max(5, math.ceil(duration * 24 - 1e-8)); frames += (5 - frames) % 17
    error = frames / 24 - duration
    check(frames <= 362 and -1e-8 <= error <= .084,
        "native duration does not fit17k+5 H3 frames within0.084s; revise native production, never speed/pad silently")
    return {"length": frames, "fps": 24, "source_duration_seconds": duration,
        "encoded_duration_seconds": frames/24, "tail_hold_seconds": max(0, error)}


def inspect_service():
    """Only allowlisted read-only localhost GETs; never execute a graph."""
    result = {"observed_at": datetime.now(timezone.utc).isoformat(), "read_only": True}
    for key, path in (("queue", "/queue"), ("system_stats", "/system_stats"),
            ("reference_node", "/object_info/MiniMaxH3ReferenceToVideo"), ("unet", "/object_info/UNETLoader")):
        with urllib.request.urlopen("http://127.0.0.1:8190" + path, timeout=10) as response:
            value = json.load(response)
        if key == "queue": result[key] = {name: [{"number": x[0], "prompt_id": x[1]} for x in value.get(name, [])]
            for name in ("queue_running", "queue_pending")}
        elif key == "system_stats": result[key] = {"devices": value.get("devices"), "argv": value.get("system", {}).get("argv", [])}
        elif key == "reference_node": result[key] = value.get("MiniMaxH3ReferenceToVideo", {}).get("input", {})
        else: result["h3_model_names"] = [name for name in value["UNETLoader"]["input"]["required"]["unet_name"][0] if "h3" in name.lower()]
    result.update(provider_calls=0, media_submissions=0, content_inspected=False)
    return result


def _text_verify(root):
    module = importlib.import_module("scripts.creative_world_scene_text_handoff_verifier_v1")
    return module.verify_text_handoff(root)


def _production_verify(root, *, text_verified):
    module = importlib.import_module("scripts.creative_world_scene_production_probe_v1")
    return module.verify_first_segment_handoff(root, text_verified=text_verified)


def verified_sources(config, *, text_verifier=_text_verify, production_verifier=_production_verify, offline_test=False, encoding_verifier=None):
    if not offline_test:
        check(text_verifier is _text_verify and production_verifier is _production_verify, "live preparation requires fixed project verifiers")
    project = Path(config.project).resolve()
    text_root, production_root = (_inside(p, project) for p in (config.text_root, config.production_root))
    text = text_verifier(text_root)
    check(text.get("valid") is True and text.get("accepted") is True and text.get("status") == "text_ready_for_director", "actual complete text is not ready")
    handoff = _binding({"path": text["handoff_path"], "file_sha256": text["handoff_sha256"]}, project)
    check(handoff.parent == text_root, "text certificate belongs to another source root")
    paths = {key: _inside(text["paths"][key], project) for key in ("goal", "setup", "raw_script", "compiled_script")}
    check(all(p.is_relative_to(text_root) for p in paths.values()), "native text paths belong to another source root")
    native = {key: read(path) for key, path in paths.items()}
    world.validate_script(native["raw_script"], native["goal"])
    identities = {"native_goal_sha256": world.digest(native["goal"]), "native_script_sha256": world.digest(native["raw_script"]),
        "compiled_script_sha256": world.digest(native["compiled_script"]), "native_setup_sha256": world.digest(native["setup"])}
    check(all(text["identity"].get(k) == v for k, v in identities.items()), "verified text native identity differs from actual bytes")
    production = production_verifier(production_root, text_verified=text)
    check(production.get("schema") == PRODUCTION_VERSION and production.get("valid") is True
        and production.get("accepted") is True and production.get("status") == "first_segment_ready_for_media", "native first-segment production is not ready")
    check(production.get("text_handoff_sha256") == text["handoff_sha256"]
        and all(production.get(k) == v for k, v in identities.items() if k != "compiled_script_sha256"), "production binds another text source")
    prod_cert = _binding({"path": production["production_handoff_path"], "file_sha256": production["production_handoff_sha256"]}, project)
    check(prod_cert.is_relative_to(production_root), "production certificate belongs to another run")
    check(type(production.get("proof_files")) is list and bool(production["proof_files"]), "original production/review proof files required")
    for row in production["proof_files"]: _binding(row, project)
    first = native["raw_script"]["beats"][0]
    check(production.get("segment_ordinal") == 1 and production.get("beat_id") == first["id"], "only first native segment in first beat is supported")
    bank = sources.catalog(native["raw_script"]); refs = production.get("source_refs")
    check(type(refs) is list and bool(refs) and refs == list(bank)[:len(refs)]
        and all(bank[ref]["beat_id"] == first["id"] for ref in refs), "current source must be the exact first-beat prefix, never cut/rewrite a native line")
    prompt = production.get("actual_video_prompt")
    check(isinstance(prompt, str) and bool(prompt.strip()) and text_sha(prompt) == production.get("video_prompt_sha256"), "actual machine-reviewed video prompt identity changed")
    timing = frame_timing(production["duration_seconds"])
    if encoding_verifier is not None:
        timing["native_encoding"] = encoding_verifier(production)
    return text, production, native, paths, timing


def reference_bindings(config, production, goal):
    catalog = read(config.catalog_path); rows = production.get("reference_map")
    check(type(rows) is list and len(rows) == 3 and [r.get("picture") for r in rows] == [1, 2, 3], "three explicit ordered reference bindings required")
    check([(r.get("asset_id"), r.get("version")) for r in rows] == list(FIXED_ASSETS), "actual selected environment/female/male assets must match fixed versions")
    actors = {r["id"]: r for r in goal["whole_plan"]["characters"]}; scenes = {r["id"] for r in goal["whole_plan"]["scenes"]}
    check(rows[0].get("role") == "environment" and set(rows[0].get("scene_ids", [])) <= scenes and bool(rows[0].get("scene_ids")), "environment map must name canonical scenes")
    actual = []
    for i, row in enumerate(rows):
        entries = [r for r in catalog["assets"] if (r["asset_id"], r["version"]) == (row["asset_id"], row["version"])]
        check(len(entries) == 1, "reference must resolve to one exact catalog entry")
        asset = entries[0]; source = _inside(asset["image"]["path"], config.project)
        check(sha(source) == asset["image"]["expected_sha256"], "selected reference image bytes changed")
        if i:
            actor = actors.get(row.get("character_id")); check(actor is not None, "reference actor is not in the native goal")
            check(row.get("role") == "character" and row.get("name") == actor["name"]
                and row.get("gender_presentation") == actor["profile"]["gender_presentation"]
                and row.get("asset_presentation") == ("female" if i == 1 else "male")
                and row.get("gender_mapping_reviewed") is True, "canonical actor/name/gender and reviewed asset mapping required; never infer from C01/C02")
            evidence = row.get("asset_gender_evidence", {}); path = _binding(evidence, config.project)
            request = read(path)
            check(path == Path(asset["evidence_paths"][0]).parent / "IMAGEGEN_REQUEST.json"
                and isinstance(evidence.get("quote"), str) and bool(evidence["quote"].strip()) and evidence["quote"] in request["prompt"], "gender evidence must quote the original asset generation request")
        actual.append({**deepcopy(row), "source_path": str(source), "source_sha256": sha(source)})
    check(len({r["character_id"] for r in rows[1:]}) == 2 and set(r["character_id"] for r in rows[1:]) == set(actors), "two bound actors must cover the canonical closed cast")
    return actual


def build_graph(template, prompt, references, timing, prefix, seed):
    graph = deepcopy(template)
    check(type(seed) is int and 0 <= seed < 2**64, "seed must be an explicit uint64")
    check(graph["condition"]["class_type"] == "MiniMaxH3ReferenceToVideo", "original REF2VA template required")
    check(len([n for n in graph.values() if n["class_type"] == "LoadImage"]) == 3, "exactly three actual images required")
    check(not any(n["class_type"] in ("MiniMaxH3AddGuide", "LoraLoaderModelOnly") or "scale" in n["class_type"].lower() for n in graph.values()), "no old tail, guide, upscale or LoRA branch allowed")
    condition = graph["condition"]["inputs"]
    condition.update(prompt=prompt, width=1280, height=704, length=timing["length"], ref_image_size="match")
    # Old node labels are just graph keys. Identity comes exclusively from the
    # canonical reference map and its exact root/model order, never the label.
    for i, key in enumerate(("ref_scene", "ref_C01", "ref_C02")):
        graph[key]["inputs"]["image"] = references[i]["input_relative_path"]
        condition["ref_images.ref_image_" + str(i)] = [key, 0]
    graph["129"]["inputs"]["noise_seed"] = seed
    graph["pick_first"]["inputs"]["batch_index"] = 0
    graph["pick_last"]["inputs"]["batch_index"] = timing["length"] - 1
    for key, suffix in (("save_video", "opening"), ("save_audio", "opening"), ("save_first", "first"), ("save_last", "last")):
        graph[key]["inputs"]["filename_prefix"] = prefix + "/" + suffix
    return graph


def prepare(config, *, text_verifier=_text_verify, production_verifier=_production_verify, service_snapshot=None, offline_test=False, encoding_verifier=None):
    text, production, native, paths, timing = verified_sources(config, text_verifier=text_verifier,
        production_verifier=production_verifier, offline_test=offline_test, encoding_verifier=encoding_verifier)
    actual = reference_bindings(config, production, native["goal"])
    output = _inside(config.output_root, config.project)
    check(not output.is_relative_to(OLD.resolve()), "never share the other chat's old media/preparation root")
    check(not output.exists(), "existing preparation/output cannot be overwritten or automatically retried")
    service = _inside(config.service_root, config.project)
    snapshot = service_snapshot if offline_test else inspect_service()
    check(type(snapshot) is dict and snapshot.get("read_only") is True, "actual read-only service snapshot required")
    check(not snapshot["queue"]["queue_running"] and not snapshot["queue"]["queue_pending"], "service has an active task; preserve existing task identity")
    check("minimax_h3_ref2va_pruned_int8_convrot.safetensors" in snapshot["h3_model_names"], "actual REF2VA model unavailable")
    argv = snapshot.get("system_stats", {}).get("argv", [])
    for flag, target in (("--input-directory", service / "input"), ("--output-directory", service / "output")):
        check(flag in argv and Path(argv[argv.index(flag)+1]).resolve() == target.resolve(), "service input/output path differs from the reviewed D-disk workspace")
    check("--offline" in argv and "--preview-method" in argv and argv[argv.index("--preview-method")+1] == "none", "existing offline/no-preview service required")
    template = _inside(config.template_path, config.project)
    old_status = read(template.parent / "RUN_STATUS.json")
    check(old_status.get("state") == "success" and old_status.get("completed") is True
        and sha(template) == old_status["graph_sha256"], "reuse only byte-bound successfully executed graph wiring; never its old prompt or tail")
    ledger_path = _inside(config.ledger_path, config.project); ledger = read(ledger_path)
    check(ledger.get("schema") == "same_story_local_h3_video_failure_ledger/v1" and ledger.get("not_a_new_story_reset") is True
        and ledger.get("old_receipts_and_unknowns_retained") is True
        and all(type(ledger.get(k)) is int and ledger[k] >= 0 for k in ("failure_limit", "failures_used", "known_rejections", "technical_failures", "observed_local_video_submissions"))
        and ledger["failure_limit"] > 0 and ledger["failures_used"] < ledger["failure_limit"]
        and production.get("story_id") == ledger.get("story_id"), "same-story failure ledger must be inherited, not reset")
    check(ledger["failures_used"] == ledger["known_rejections"] + ledger["technical_failures"], "failure ledger arithmetic changed")
    unique = "world_scene_" + text_sha(str(output))[:20]
    prefix = "world_scene_live/" + unique
    for i, row in enumerate(actual, 1):
        target = service / "input" / unique / ("reference_" + str(i) + ".png")
        check(not target.exists() or sha(target) == row["source_sha256"], "never overwrite different staged reference bytes")
        row.update(input_path=str(target), input_relative_path=target.relative_to(service / "input").as_posix())
    graph = build_graph(read(template), production["actual_video_prompt"], actual, timing, prefix, config.seed)
    # No write or claim occurs until all model/text/source/asset gates pass.
    output.mkdir(parents=True, exist_ok=False)
    for row in actual:
        target = Path(row["input_path"]); target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists(): shutil.copyfile(row["source_path"], target)
        check(sha(target) == row["source_sha256"], "staged reference copy differs")
    dump(output / "workflow_api.json", graph)
    with (output / "PROMPT.txt").open("x", encoding="utf-8") as file: file.write(production["actual_video_prompt"])
    dump(output / "REFERENCE_MAP.json", actual); dump(output / "TEXT_VERIFIED.json", text)
    dump(output / "PRODUCTION_VERIFIED.json", production); dump(output / "SERVICE_READONLY.json", snapshot)
    proof = {"schema": VERSION + "/prepared", "status": "prepared_requires_root_review_and_single_submitter",
        "synthetic": bool(offline_test), "eligible_for_root_single_submit_review": not offline_test,
        "provider_calls": 0, "media_submissions": 0, "media_claim_created": False, "submit_supported_here": False,
        "graph_sha256": sha(output / "workflow_api.json"), "prompt_sha256": sha(output / "PROMPT.txt"),
        "reference_map_sha256": sha(output / "REFERENCE_MAP.json"), "text_handoff_sha256": text["handoff_sha256"],
        "production_handoff_sha256": production["production_handoff_sha256"], "source_refs": production["source_refs"],
        "native_identity": deepcopy(text["identity"]), "timing": timing, "width": 1280, "height": 704,
        "native1280_generation_verified": False, "output_root": str(service / "output"), "output_prefix": prefix,
        "template": {"path": str(template), "file_sha256": sha(template), "reuse": "node_wiring_only_not_rejected_content"},
        "failure_ledger": {"path": str(ledger_path), "file_sha256": sha(ledger_path), "story_id": ledger["story_id"],
            "failures_used": ledger["failures_used"], "failure_limit": ledger["failure_limit"], "reset": False},
        "source_paths": {key: {"path": str(path), "file_sha256": sha(path)} for key, path in paths.items()},
        "save_contract": {"video": "MP4 with native audio", "audio": "independent FLAC", "first_last": "same native decode image tensor PNG; never MP4 extraction",
            "expected_dimensions": [1280, 704], "expected_frame_count": timing["length"], "expected_fps": 24,
            "verify": "original history plus saved containers/packets/hash and encoded PNG structure only; never decode/listen/ASR"},
        "review_status": "awaiting_human_review", "content_review": None, "old_rejected_tail_used": False,
        "automatic_retry": False, "automatic_resolution_fallback": False, "following_segment_authorized": False}
    dump(output / "PREPARED.json", proof)
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "prepare")); parser.add_argument("--text-root")
    parser.add_argument("--production-root"); parser.add_argument("--output-root"); parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect": result = inspect_service()
        else:
            check(all((args.text_root, args.production_root, args.output_root)) and args.seed is not None, "explicit text/production/output roots and seed required")
            result = prepare(Config(args.text_root, args.production_root, args.output_root, args.seed))
    except (PreparationBlocked, ImportError, OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
        result = {"schema": VERSION + "/blocked", "status": "blocked_before_media_preparation", "reason": str(exc),
            "provider_calls": 0, "media_submissions": 0, "media_claim_created": False, "automatic_retry": False}
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
