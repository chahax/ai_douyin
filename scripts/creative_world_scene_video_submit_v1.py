"""One authorized localhost H3 POST; original-ID polling and container-only saving.

No automatic retry, resolution fallback, frame decoding, audio listening or QC.
Preview never claims; only root's explicit submit action can send the one POST.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import httpx

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as io
from src.content_factory.creative_counted_execution_v1 import CountedExecution

VERSION = "creative_world_scene_video_submit/v1"
AUTHORIZATION_ID = "world_scene_live_20261015_one_video_user_authorization_v1"
BASE_URL = "http://127.0.0.1:8190"
SAVES = {"save_video": ("images", ".mp4", "first_segment.mp4"),
    "save_audio": ("audio", ".flac", "native_audio.flac"),
    "save_first": ("images", ".png", "native_first.png"),
    "save_last": ("images", ".png", "native_last.png")}


class Blocked(ValueError): pass
def check(value, reason):
    if not value: raise Blocked(reason)
def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return io.strict_json(Path(path).read_text("utf-8-sig"))
def sha(path):
    with Path(path).open("rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()
def inside(path, root=PROJECT):
    path, root = Path(path).resolve(), Path(root).resolve()
    check(path != root and path.is_relative_to(root), "path outside the explicit project/root")
    return path


def create(path, value):
    """Durable exclusive file; partial claim is retained, never repaired/released."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush(); os.fsync(f.fileno())


@contextmanager
def locked(path):
    token = str(uuid.uuid4()); create(path, {"schema": VERSION + "/lock", "token": token, "pid": os.getpid(), "at": now()})
    try: yield
    finally:
        check(read(path).get("token") == token, "lock ownership changed; preserve for diagnosis")
        Path(path).unlink()


@dataclass(frozen=True)
class Config:
    prepared_root: str
    authorization_path: str
    counter_root: str
    round_key: str


def _fixed_verify(root):
    from scripts import creative_world_scene_media_probe_v2 as media
    return media.verify_prepared(root)


def _client():
    return httpx.Client(base_url=BASE_URL, timeout=60, follow_redirects=False,
        transport=httpx.HTTPTransport(retries=0), trust_env=False)


class Submitter:
    def __init__(self, config, *, verifier=None, client=None, counter=None, project=PROJECT, metadata_probe=None):
        self.config = config; self.project = Path(project).resolve()
        self.root = inside(config.prepared_root, self.project)
        self.verifier = verifier or _fixed_verify
        self.client = client
        self.counter = counter or CountedExecution(inside(config.counter_root, self.project))
        self.metadata_probe = metadata_probe or probe_container
        self.lock_path = self.project / "data/creative_media_submission_claims/DISPATCH.lock"

    def _request(self, method, path, *, body=None):
        check(method in ("GET", "POST") and path.startswith("/") and "?" not in path, "fixed local API route required")
        check((method == "POST" and path == "/prompt") or (method == "GET" and (
            path in ("/queue", "/system_stats") or path.startswith("/history/"))), "unapproved API route")
        client = self.client or _client()
        try:
            response = client.request(method, BASE_URL + path, content=body,
                headers={"Content-Type": "application/json"} if body is not None else None)
            return response.status_code, response.content
        finally:
            if self.client is None: client.close()

    def _get(self, path):
        status, raw = self._request("GET", path)
        check(status == 200, "read-only local API did not return HTTP200")
        return io.strict_json(raw.decode("utf-8"))

    def _claims(self, prod_sha):
        base = self.project / "data/creative_media_submission_claims"
        return (base / "by_authorization" / io.digest(AUTHORIZATION_ID) / "CLAIM.json",
            base / "by_production_handoff" / prod_sha / "CLAIM.json", self.root / "RUN_CLAIM.json")

    def _prepared(self, *, require_native=True):
        verified = self.verifier(self.root)
        check(verified.get("valid") is True and verified.get("accepted") is True, "original media preparation verifier did not accept")
        base, v2 = read(self.root / "PREPARED.json"), read(self.root / "PREPARED_V2.json")
        check(base.get("schema") == "creative_world_scene_media_probe/v1/prepared"
            and v2.get("schema") == "creative_world_scene_media_probe/v2/prepared", "exact media preparation protocol required")
        check(base.get("synthetic") is False and v2.get("synthetic") is False
            and base.get("eligible_for_root_single_submit_review") is True
            and v2.get("eligible_for_root_single_submit_review") is True, "synthetic preparation cannot submit")
        check(Path(v2["base_prepared_path"]).resolve() == self.root / "PREPARED.json"
            and v2["base_prepared_sha256"] == sha(self.root / "PREPARED.json"), "v2 binds other base preparation")
        for key, filename in (("graph_sha256", "workflow_api.json"), ("prompt_sha256", "PROMPT.txt"),
                ("reference_map_sha256", "REFERENCE_MAP.json")):
            check(base.get(key) == sha(self.root / filename), "prepared file changed: " + filename)
        check(v2["graph_sha256"] == base["graph_sha256"]
            and v2["text_handoff_sha256"] == base["text_handoff_sha256"]
            and v2["production_handoff_sha256"] == base["production_handoff_sha256"]
            and v2["native_encoding"] == base["timing"]["native_encoding"], "v2/base source or encoding mismatch")
        ledger_binding = base["failure_ledger"]; ledger_path = inside(ledger_binding["path"], self.project)
        check(sha(ledger_path) == ledger_binding["file_sha256"], "same-story ledger changed since preparation; reconcile before claim")
        ledger = read(ledger_path)
        check(ledger.get("schema") == "same_story_local_h3_video_failure_ledger/v1"
            and ledger.get("story_id") == ledger_binding["story_id"]
            and ledger.get("not_a_new_story_reset") is True and ledger.get("old_receipts_and_unknowns_retained") is True,
            "original same-story ledger identity required")
        check(all(type(ledger.get(k)) is int and ledger[k] >= 0 for k in
            ("failure_limit", "failures_used", "known_rejections", "technical_failures", "observed_local_video_submissions"))
            and ledger["failures_used"] == ledger["known_rejections"] + ledger["technical_failures"]
            and ledger["failures_used"] < ledger["failure_limit"], "failure ledger exhausted or malformed")
        files = dict(verified.get("source_files", {}))
        for filename in ("PREPARED.json", "PREPARED_V2.json", "workflow_api.json", "PROMPT.txt", "REFERENCE_MAP.json",
                "TEXT_VERIFIED.json", "PRODUCTION_VERIFIED.json", "SERVICE_READONLY.json"):
            files[str(self.root / filename)] = sha(self.root / filename)
        files[str(ledger_path)] = sha(ledger_path); files[str(Path(__file__).resolve())] = sha(__file__)
        native = self.root / "NATIVE_VALIDATION.json"
        if require_native:
            report = read(native)
            check(report.get("schema") == VERSION + "/native_validation" and report.get("valid") is True
                and report.get("node_errors") == {} and report.get("graph_sha256") == base["graph_sha256"]
                and report.get("validator_code_sha256") == sha(__file__)
                and report.get("node_execution_performed") is False
                and report.get("server_native_validation_performed") is False
                and report.get("object_info_sha256") == sha(self.root / "OBJECT_INFO.json"), "exact local graph/schema validation required")
            files[str(native)] = sha(native)
            files[str(self.root / "OBJECT_INFO.json")] = sha(self.root / "OBJECT_INFO.json")
        for path, expected in files.items():
            check(sha(inside(path, self.project)) == expected, "verified preparation source bytes changed")
        return {"base": base, "v2": v2, "ledger": ledger, "source_files": files,
            "config": asdict(self.config), "graph": read(self.root / "workflow_api.json")}

    def preview(self):
        p = self._prepared()
        return {"schema": VERSION + "/preview", "prepared_root": str(self.root),
            "authorization_id": AUTHORIZATION_ID, "prepared_sha256": sha(self.root / "PREPARED_V2.json"),
            "graph_sha256": p["base"]["graph_sha256"], "text_handoff_sha256": p["base"]["text_handoff_sha256"],
            "production_handoff_sha256": p["base"]["production_handoff_sha256"],
            "source_files": p["source_files"], "config": p["config"], "max_submissions": 1,
            "automatic_retries": 0, "following_segment_authorized": False, "publish_authorized": False,
            "content_review": None, "review_status": "awaiting_human_review", "media_submissions": 0,
            "claim_created": False}

    def authorization_template(self):
        return self._authorization(self.preview())

    def _authorization(self, preview):
        return {"schema": VERSION + "/authorization", "authorization_id": AUTHORIZATION_ID,
            "user_authorization": "2026-10-15：真实接口测试，审查达标直接生成一次测试视频。",
            "prepared_root": str(self.root), "preview_sha256": io.digest(preview),
            "config": asdict(self.config), "max_submissions": 1, "automatic_retries": 0,
            "content_requires_human_review": True, "following_segment_authorized": False, "publish_authorized": False}

    def _admit(self):
        preview = self.preview()
        check(read(inside(self.config.authorization_path, self.project)) == self._authorization(preview), "root authorization binding changed")
        self.counter.assert_dispatch_allowed(self.config.round_key)
        return preview

    def _service_gate(self, prepared):
        stats = self._get("/system_stats"); argv = stats.get("system", {}).get("argv", [])
        output = Path(prepared["base"]["output_root"]).resolve()
        check("--output-directory" in argv and Path(argv[argv.index("--output-directory") + 1]).resolve() == output
            and "--input-directory" in argv and Path(argv[argv.index("--input-directory") + 1]).resolve() == output.parent / "input"
            and "--offline" in argv and "--preview-method" in argv and argv[argv.index("--preview-method") + 1] == "none",
            "reviewed offline/no-preview service output root required")
        queue = self._get("/queue")
        check(queue.get("queue_running") == [] and queue.get("queue_pending") == [], "another GPU task is active; preserve its ID")
        resolved = []
        for event in prepared["ledger"].get("events", []):
            if event.get("kind") != "submitted_awaiting_result": continue
            pid = event.get("prompt_id"); check(isinstance(pid, str) and bool(pid)
                and all(c.isalnum() or c in "-_" for c in pid), "old submitted task identity missing")
            original = self._get("/history/" + pid)
            check(pid in original and original[pid].get("status", {}).get("completed") is True,
                "same-story earlier task unresolved; query its original ID first")
            resolved.append({"prompt_id": pid, "history_sha256": io.digest(original), "completed": True})
        return {"system_sha256": io.digest(stats), "queue": queue, "older_original_tasks": resolved}

    def submit(self):
        self._admit()
        with locked(self.lock_path):
            preview = self._admit()
            prepared = {"base": read(self.root / "PREPARED.json")}
            prepared["ledger"] = read(prepared["base"]["failure_ledger"]["path"])
            service = self._service_gate(prepared)
            claims = self._claims(preview["production_handoff_sha256"])
            check(not any(p.exists() for p in claims), "one-video authorization/production/preparation already claimed; never re-POST")
            token = str(uuid.uuid4())
            claim = {"schema": VERSION + "/run_claim", "authorization_id": AUTHORIZATION_ID,
                "prepared_root": str(self.root), "run_id": token, "created_at": now(),
                "preview_sha256": io.digest(preview), "config": asdict(self.config),
                "authorization_path": str(Path(self.config.authorization_path).resolve()),
                "authorization_sha256": sha(self.config.authorization_path),
                "production_handoff_sha256": preview["production_handoff_sha256"],
                "state": "claimed_result_unknown", "submission_count": 1, "automatic_retries": 0,
                "review_status": "awaiting_human_review", "content_review": None}
            for path in claims: create(path, claim)
            create(self.root / "SUBMISSION_FREEZE.json", {"schema": VERSION + "/freeze", "claim": claim,
                "claim_paths": {str(p): sha(p) for p in claims}, "preview": preview, "service_admission": service})
            create(self.root / "MEDIA_CALL_LEDGER.json", {"schema": VERSION + "/media_ledger",
                "story_id": prepared["ledger"]["story_id"], "inherited_ledger": prepared["ledger"],
                "inherited_ledger_file_sha256": prepared["base"]["failure_ledger"]["file_sha256"],
                "inherited_media_submissions": prepared["ledger"]["observed_local_video_submissions"],
                "new_calls_claimed": 1, "max_new_calls": 1, "old_ledger_modified": False,
                "automatic_retry": False, "claims_never_refunded": True})
            # Last locked counter/source check occurs after durable claim; failure retains all claims.
            for path, expected in preview["source_files"].items():
                check(sha(inside(path, self.project)) == expected, "preparation changed after claim")
            check(read(self.config.authorization_path) == self._authorization(preview), "authorization changed after claim")
            self.counter.assert_dispatch_allowed(self.config.round_key)
            payload = {"prompt": read(self.root / "workflow_api.json"), "client_id": token}
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            with (self.root / "SUBMITTED_REQUEST.raw").open("xb") as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            create(self.root / "POST_STARTED.json", {"schema": VERSION + "/post_started", "at": now(),
                "request_sha256": hashlib.sha256(raw).hexdigest(), "method": "POST", "url": BASE_URL + "/prompt",
                "automatic_retries": 0, "do_not_resubmit": True})
            try:
                self.counter.assert_dispatch_allowed(self.config.round_key)
                status, response = self._request("POST", "/prompt", body=raw)
                with (self.root / "SUBMISSION_RESPONSE.raw").open("xb") as f:
                    f.write(response); f.flush(); os.fsync(f.fileno())
                create(self.root / "SUBMISSION_HTTP.json", {"status": status, "response_sha256": hashlib.sha256(response).hexdigest()})
                if status != 200:
                    result = {"schema": VERSION + "/rejected", "state": "submission_http_rejected",
                        "http_status": status, "submission_count": 1, "automatic_retries": 0,
                        "claim_retained": True, "do_not_resubmit": True}
                    create(self.root / "SUBMISSION_REJECTED.json", result)
                    return result
                receipt = io.strict_json(response.decode("utf-8"))
                check(type(receipt.get("prompt_id")) is str and bool(receipt["prompt_id"]), "POST response has no unambiguous accepted original ID")
                create(self.root / "SUBMISSION_RECEIPT.json", receipt)
                result = {"schema": VERSION + "/submitted", "state": "submitted" if receipt.get("node_errors", {}) == {} else "submitted_with_node_errors_requires_diagnosis", "prompt_id": receipt["prompt_id"],
                    "submission_count": 1, "review_status": "awaiting_human_review", "content_review": None}
                create(self.root / "RUN_STATUS.json", result)
                return result
            except Exception as exc:
                create(self.root / "SUBMISSION_UNKNOWN.json", {"schema": VERSION + "/unknown", "at": now(),
                    "state": "submission_result_unknown", "error_type": type(exc).__name__, "error": str(exc),
                    "do_not_resubmit": True, "automatic_retries": 0, "claim_retained": True})
                raise

    def _original(self):
        freeze = read(self.root / "SUBMISSION_FREEZE.json"); claim = read(self.root / "RUN_CLAIM.json")
        check(freeze.get("schema") == VERSION + "/freeze" and freeze["claim"] == claim
            and claim["config"] == asdict(self.config) and claim["authorization_id"] == AUTHORIZATION_ID, "original claim/config changed")
        for path, expected in freeze["claim_paths"].items():
            check(sha(inside(path, self.project)) == expected and read(path) == claim, "global one-video claim changed")
        # Original-ID queries must remain available after unrelated later source/ledger
        # changes. These never authorize another POST and are reported, not hidden.
        drift = []
        for path, expected in freeze["preview"]["source_files"].items():
            p = inside(path, self.project)
            if not p.is_file() or sha(p) != expected: drift.append(str(p))
        freeze["current_source_drift"] = drift
        check(sha(self.config.authorization_path) == claim["authorization_sha256"], "original authorization changed")
        raw = (self.root / "SUBMITTED_REQUEST.raw").read_bytes(); payload = io.strict_json(raw.decode())
        check(payload["client_id"] == claim["run_id"] and payload["prompt"] == read(self.root / "workflow_api.json")
            and hashlib.sha256(raw).hexdigest() == read(self.root / "POST_STARTED.json")["request_sha256"], "actual POST request identity changed")
        response = (self.root / "SUBMISSION_RESPONSE.raw").read_bytes(); http = read(self.root / "SUBMISSION_HTTP.json")
        receipt = read(self.root / "SUBMISSION_RECEIPT.json")
        check(http["status"] == 200 and http["response_sha256"] == hashlib.sha256(response).hexdigest()
            and io.strict_json(response.decode()) == receipt, "original POST response identity changed")
        return freeze, payload, receipt

    def poll(self):
        freeze, payload, receipt = self._original(); pid = receipt["prompt_id"]
        check(all(c.isalnum() or c in "-_" for c in pid), "original task ID is not a path component")
        raw = self._get("/history/" + pid)
        entry = raw.get(pid)
        if entry is not None:
            check(entry.get("prompt", [None]*3)[1:3] == [pid, payload["prompt"]]
                and entry["prompt"][3].get("client_id") == payload["client_id"], "history is not the original service graph/task")
            status = entry.get("status", {})
            state = "success" if status.get("completed") is True and status.get("status_str") == "success" else (
                "service_failed" if status.get("status_str") == "error" else "running_or_pending_original_id")
        else: state = "running_or_pending_original_id"
        snapshot = {"schema": VERSION + "/original_history", "at": now(), "prompt_id": pid,
            "state": state, "history": raw, "automatic_retries": 0, "review_status": "awaiting_human_review", "content_review": None}
        snapshot["source_drift_since_submission"] = freeze["current_source_drift"]
        directory = self.root / "polls"; directory.mkdir(exist_ok=True)
        create(directory / (uuid.uuid4().hex + ".json"), snapshot)
        io.write(self.root / "ORIGINAL_HISTORY.json", snapshot)
        return snapshot

    def finalize(self):
        freeze, payload, receipt = self._original(); pid = receipt["prompt_id"]
        check(receipt.get("node_errors", {}) == {}, "original submission had node errors; save/query without claiming technical completion")
        snapshot = read(self.root / "ORIGINAL_HISTORY.json"); history = snapshot["history"].get(pid)
        check(snapshot["prompt_id"] == pid and history is not None and snapshot["state"] == "success"
            and history["prompt"][1:3] == [pid, payload["prompt"]]
            and history["prompt"][3].get("client_id") == payload["client_id"]
            and history["status"].get("status_str") == "success" and history["status"].get("completed") is True,
            "original successful task history required")
        proof = read(self.root / "PREPARED.json"); output = inside(proof["output_root"], self.project)
        prefix = inside(output / proof["output_prefix"], output)
        delivery = self.root / "deliverables"; delivery.mkdir(exist_ok=True)
        files = {}; checks = {}
        for node, (field, suffix, name) in SAVES.items():
            entries = history["outputs"][node][field]
            check(type(entries) is list and len(entries) == 1 and entries[0].get("type") == "output", "exact one service output per save slot required")
            row = entries[0]; check(Path(row["filename"]).name == row["filename"], "service filename must be a basename")
            source = inside(output / row.get("subfolder", "") / row["filename"], prefix)
            check(source.suffix.lower() == suffix and source.is_file() and source.stat().st_size > 0, "same-task saved output missing/empty/wrong format")
            before = sha(source)
            if node in ("save_video", "save_audio"):
                result = self.metadata_probe(source, node=node, proof=proof)
                check(result.get("valid") is True, "saved container metadata is incomplete; retain original outputs")
                checks[node] = result
            target = delivery / name
            if target.exists(): check(sha(target) == before, "never replace a different delivery file")
            else:
                with source.open("rb") as src, target.open("xb") as dst: shutil.copyfileobj(src, dst)
            check(sha(source) == sha(target) == before and source.stat().st_size == target.stat().st_size, "copy differs from original service bytes")
            files[node] = {"path": str(target.resolve()), "original_service_path": str(source), "sha256": before,
                "size_bytes": target.stat().st_size, "same_service_task": pid, "content_review": None}
        result = {"schema": VERSION + "/technical_delivery", "status": "awaiting_human_review", "prompt_id": pid,
            "technical_file_status": "succeeded", "files": files, "container_checks": checks,
            "media_submissions": 1, "automatic_retries": 0, "generated_media_opened_or_listened": False,
            "frame_extraction_performed": False, "ASR_performed": False, "content_review": None,
            "human_quality_approved": False, "following_segment_dispatched": False, "published": False,
            "source_drift_since_submission": freeze["current_source_drift"],
            "history_sha256": io.digest(snapshot), "native_resolution_generation_verified": [proof["width"], proof["height"]]}
        create(self.root / "TECHNICAL_RESULT.json", result)
        return result


def probe_container(path, *, node, proof):
    """ffprobe headers/stream metadata only: no -show_frames or decode operations."""
    executable = shutil.which("ffprobe"); check(bool(executable), "existing ffprobe required; do not auto-install")
    command = [executable, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    r = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    check(r.returncode == 0, "ffprobe could not read container")
    data = io.strict_json(r.stdout); streams = data.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]; audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(data.get("format", {}).get("duration", "nan"))
    expected = proof["timing"]["encoded_duration_seconds"]
    check(bool(audio) and math.isfinite(duration) and abs(duration - expected) <= .6, "audio/duration metadata missing or different")
    if node == "save_video":
        check(len(video) == 1 and (video[0].get("width"), video[0].get("height")) == (proof["width"], proof["height"])
            and abs(float(Fraction(video[0].get("avg_frame_rate", "0/1"))) - proof["timing"]["fps"]) < .01
            and str(video[0].get("nb_frames")) == str(proof["timing"]["length"]), "video dimensions/fps/frame count differ or unknown")
    else: check(not video, "independent native audio slot must not contain video")
    return {"valid": True, "command": command, "metadata": data, "stderr": r.stderr,
        "checks": "container/stream metadata only; no pixel/audio decoding or content review"}


def validate_graph_schema(graph, infos):
    """Pure necessary node/socket checks, including standard V3 autogrow slots.

    This does NOT call server validate_prompt or reproduce custom VALIDATE_INPUTS.
    """
    check(type(graph) is dict and bool(graph), "nonempty API graph required")
    parents = {key: set() for key in graph}
    for node_id, node in graph.items():
        check(node["class_type"] in infos, "node class missing from actual object_info")
        info = infos[node["class_type"]]; inputs = node["inputs"]
        required = info.get("input", {}).get("required", {})
        all_inputs = {**required, **info.get("input", {}).get("optional", {})}
        expanded = {}; required_names = set()
        for name, spec in all_inputs.items():
            check(type(spec) is list and bool(spec), "unsupported input descriptor shape")
            if spec[0] == "COMFY_AUTOGROW_V3":
                template = spec[1]["template"]; source = template["input"]
                choices = list(source.get("required", {}).values()) or list(source.get("optional", {}).values())
                check(len(choices) == 1, "one autogrow template descriptor required")
                names = template.get("names") or [template["prefix"] + str(i) for i in range(template["max"])]
                for index, sub in enumerate(names):
                    expanded[name + "." + sub] = choices[0]
                    if index < template.get("min", 0) and source.get("required"): required_names.add(name + "." + sub)
            else:
                expanded[name] = spec
                if name in required: required_names.add(name)
        check(required_names <= set(inputs) and set(inputs) <= set(expanded), "required/unknown node input slots")
        for name, value in inputs.items():
            spec = expanded[name]; kind = spec[0]; options = spec[1] if len(spec) > 1 and type(spec[1]) is dict else {}
            if type(value) is list:
                check(len(value) == 2 and value[0] in graph and type(value[1]) is int and value[1] >= 0, "broken graph link")
                outputs = infos[graph[value[0]]["class_type"]]["output"]
                check(value[1] < len(outputs), "graph output index out of range")
                actual = outputs[value[1]]
                check(kind in ("*", "ANY") or actual in ("*", "ANY") or actual == kind,
                    "source output type does not match destination input")
                parents[node_id].add(value[0]); continue
            if type(kind) is list: check(value in kind, "literal not in actual enum/model list")
            elif kind == "INT": check(type(value) is int, "integer input required")
            elif kind == "FLOAT": check(type(value) in (int, float) and math.isfinite(value), "finite numeric input required")
            elif kind == "STRING": check(type(value) is str, "string input required")
            elif kind == "BOOLEAN": check(type(value) is bool, "boolean input required")
            else: raise Blocked("nonliteral socket requires a graph link: " + str(kind))
            if type(value) in (int, float):
                check(("min" not in options or value >= options["min"]) and ("max" not in options or value <= options["max"]), "numeric input outside actual node range")
        check(node_id not in parents[node_id], "self-cycle in graph")
    pending = {k: set(v) for k, v in parents.items()}
    while pending:
        ready = {k for k, v in pending.items() if not v}
        check(bool(ready), "graph has a dependency cycle")
        pending = {k: v - ready for k, v in pending.items() if k not in ready}
    return {"valid": True, "node_count": len(graph), "node_errors": {}}


def native_validate(root, *, client=None):
    """Read-only GET descriptors + local schema/link checks; no native imports."""
    root = inside(root); graph_path = root / "workflow_api.json"
    check(graph_path.is_file() and not (root / "RUN_CLAIM.json").exists(), "prepare graph before local-only validation")
    graph = read(graph_path); own = client is None; client = client or _client(); infos = {}
    try:
        for name in sorted({n["class_type"] for n in graph.values()}):
            check(type(name) is str and name and all(c.isalnum() or c in "_-" for c in name), "class must be one fixed route component")
            response = client.get(BASE_URL + "/object_info/" + name)
            check(response.status_code == 200, "object_info GET failed")
            document = io.strict_json(response.content.decode("utf-8")); check(name in document, "actual node unavailable")
            infos[name] = document[name]
    finally:
        if own: client.close()
    result = validate_graph_schema(graph, infos)
    create(root / "OBJECT_INFO.json", infos)
    report = {"schema": VERSION + "/native_validation", **result,
        "graph_sha256": sha(graph_path), "validator_code_sha256": sha(__file__),
        "object_info_sha256": sha(root / "OBJECT_INFO.json"), "method": "GET object_info plus necessary local input/link checks",
        "server_native_validation_performed": False, "custom_node_validation_performed": False,
        "node_execution_performed": False, "model_load_performed": False, "media_submissions": 0}
    create(root / "NATIVE_VALIDATION.json", report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("preview", "authorization-template", "native-validate", "submit", "poll", "finalize"))
    p.add_argument("--config"); p.add_argument("--root"); p.add_argument("--output")
    a = p.parse_args(argv)
    try:
        if a.action == "native-validate": result = native_validate(a.root)
        else:
            check(bool(a.config), "explicit Config file required")
            session = Submitter(Config(**read(a.config)))
            result = getattr(session, "authorization_template" if a.action == "authorization-template" else a.action)()
        if a.output: create(inside(a.output), result)
    except Exception as exc:
        print(json.dumps({"schema": VERSION + "/blocked", "reason": str(exc), "error_type": type(exc).__name__,
            "automatic_retries": 0, "media_content_passed": False}, ensure_ascii=False, indent=2)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
