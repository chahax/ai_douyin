"""Observe the current original manual Page. No navigation or input exists.

This is a new read-only stage after a source-bound preselection failure. It
does not clear or consume another upload claim and does not retry preparation.
"""
import hashlib
import json
from pathlib import Path
import threading
import time
import types
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SAFE_REASONS = frozenset({"observation_request_invalid", "observation_binding_changed", "observation_prior_failure_changed",
    "observation_claim_changed", "observation_output_changed", "observation_session_changed",
    "observation_page_changed", "observation_rpc_failed", "observation_inventory_too_large"})


class ObservationBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def need(ok, code):
    if not ok:
        raise ObservationBlocked(code)


def reference(path):
    path = Path(path).resolve()
    need(path.is_relative_to(ROOT) and path.is_file(), "observation_binding_changed")
    with path.open("rb") as stream:sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": sha}


def read(ref):
    need(isinstance(ref, dict) and set(ref) == {"path", "sha256"} and reference(ref["path"]) == ref,
         "observation_binding_changed")
    need(Path(ref["path"]).stat().st_size <= 2 * 1024 * 1024, "observation_binding_changed")
    return json.loads(Path(ref["path"]).read_text(encoding="utf8"))


def once(path, value):
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return reference(path)


def _location(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:host += ":" + str(parsed.port)
    return {"origin": parsed.scheme + "://" + host, "path": parsed.path}


def _load_reader(config):
    ref = config["sources"]["flow_v1"]
    path = ROOT / "src/operations_accounts/manual_republication_flow_v1.py"
    need(reference(path) == ref, "observation_binding_changed")
    raw = path.read_bytes()
    module = types.ModuleType("src.operations_accounts._manual_observe_reader_" + ref["sha256"][:16])
    module.__file__, module.__package__ = str(path), "src.operations_accounts"
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _script(script):
    # The gate runs inside the actual renderer as well as before the RPC.
    return "() => { if(!['https://www.douyin.com','https://creator.douyin.com'].includes(location.origin)) return {schema:'manual_location_only/v3',location:{origin:location.origin,path:location.pathname}}; return (" + script + ")(); }"


def run_action(actor, resource, config, request, outdir):
    from . import manual_republication_runtime_v3 as runtime
    need(isinstance(request, dict) and set(request) == {"schema", "config", "action", "prior_upload_claim", "prior_failure"}
         and request["schema"] == "manual_republication_operator_request/v3" and request["action"] == "observe_current",
         "observation_request_invalid")
    need(read(request["config"]) == config, "observation_binding_changed")
    directory = Path(outdir).resolve()
    need(directory.is_relative_to(ROOT / "data") and directory.name == "observation", "observation_output_changed")
    claim_ref = reference(directory.parent / "ACTION_CLAIM.json")
    claim = read(claim_ref);plan = read(claim["plan"])
    need(claim.get("schema") == "manual_republication_observation_claim/v3" and claim.get("action") == "observe_current"
         and claim.get("config") == request["config"] and read(claim["request"]) == request
         and claim.get("prior_upload_claim") == request["prior_upload_claim"] and claim.get("prior_failure") == request["prior_failure"]
         and claim.get("actor_thread_id") == threading.get_ident()
         and all(claim.get(k) is False for k in ("navigation_allowed", "input_allowed", "file_selection_allowed"))
         and plan.get("config") == request["config"] and plan.get("request") == claim["request"]
         and directory == Path(claim["plan"]["path"]).resolve().parent / "observation", "observation_claim_changed")
    prior = read(request["prior_upload_claim"]);failure = read(request["prior_failure"])
    need(prior.get("action") == "prepare_upload" and prior.get("metadata") == config["metadata"]
         and prior.get("authority") == config["authority"] and prior.get("owner_id") == actor.owner_id
         and prior.get("generation") == actor.generation and prior.get("tab_id") == config["tab_id"]
         and failure.get("upload_attempted") is False and failure.get("submitted") is False,
         "observation_prior_failure_changed")
    original = resource.session
    def guard():
        need(resource.session is original, "observation_session_changed")
        runtime.validate_live(actor, resource, config)
        need(reference(claim_ref["path"]) == claim_ref and read(request["config"]) == config,
             "observation_claim_changed")
        for ref in (request["prior_upload_claim"], request["prior_failure"]):read(ref)
        b = resource.runtime.bindings.get(config["account_key"]);p = resource.runtime.profiles.get(config["account_key"])
        need(b.account_uuid == p.account_uuid == config["account_id"]
             and reader._binding_version(SimpleNamespace(binding=b, profile=p)) == config["binding_version"], "observation_binding_changed")
    reader = _load_reader(config)
    guard();page = original.get_page(config["tab_id"]);guard()
    need(page.tab_id == config["tab_id"] and page._session is original, "observation_page_changed")
    def rpc(action, *args):
        guard()
        if action == "current_url":value = page._cmd("current_url")
        elif action == "evaluate":value = page.evaluate(args[0])
        elif action == "wait":value = page.wait_for_timeout(250)
        else:raise ObservationBlocked("observation_rpc_failed")
        guard();return value
    authority = read(config["authority"]);metadata = read(config["metadata"])
    target = {"post_id": authority["old_post_id"], "title": metadata["title"],
              "title_basis": "frozen republication metadata; candidate inventory only"}
    samples = [];previous = None
    for _ in range(3):
        actual = _location(rpc("current_url")["url"])
        if actual["origin"] not in {"https://www.douyin.com", "https://creator.douyin.com"}:
            samples.append({"location": actual, "status": "unsupported_origin_location_only", "content_read": False})
            break
        uid = rpc("evaluate", _script(reader.UID_JS))
        inventory = rpc("evaluate", _script(reader.inventory_script(target)))
        need(isinstance(uid, dict) and isinstance(inventory, dict), "observation_rpc_failed")
        need(len(json.dumps(inventory, ensure_ascii=False).encode()) <= 192 * 1024, "observation_inventory_too_large")
        ending = _location(rpc("current_url")["url"])
        stable_location = (actual == ending == inventory.get("location")
            == {"origin": uid.get("origin"), "path": uid.get("path")})
        signature = hashlib.sha256(json.dumps([uid, inventory, actual], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        samples.append({"location": actual, "ending_location": ending, "location_stable": stable_location,
                        "uid_observation": uid, "inventory": inventory, "stable_with_previous": signature == previous})
        if signature == previous and stable_location:break
        previous = signature
        rpc("wait")
    directory.mkdir(parents=True, exist_ok=True)
    observation = once(directory / "CURRENT_SURFACE.json", {"schema": "manual_current_surface_samples/v3", "samples": samples,
        "navigation_performed": False, "input_performed": False, "query_or_fragment_saved": False})
    last = samples[-1];uid = last.get("uid_observation", {});inventory = last.get("inventory", {})
    uids = uid.get("public_uids", [])
    matched = bool(last.get("location_stable") and uid.get("truncated") is False
                   and uids == [authority["expected_public_uid"]])
    result = {"schema": "manual_republication_observation/v3", "action": "observe_current", "status": "observed_current",
        "observation": observation, "claim": claim_ref, "prior_upload_claim": request["prior_upload_claim"],
        "prior_failure": request["prior_failure"], "location": last.get("ending_location", last["location"]),
        "same_page_rendered_expected_uid_observed": matched, "observed_public_uids": uids,
        "creator_identity_verified_for_write": False, "stable_render_observed": bool(last.get("stable_with_previous")),
        "visible_control_count": len(inventory.get("controls", [])), "native_snapshot_only": True,
        "tab_id": page.tab_id, "owner_id": actor.owner_id, "generation": actor.generation,
        "uploaded": False, "submitted": False, "input_performed": False, "navigation_performed": False,
        "file_selected": False, "observed_at": time.time(), "resume_preparation_authorized": False,
        "limits": ["Prior failure has no navigation-stage trace; this observation does not assign the timeout to SELF or upload navigation.",
                   "No navigation, reload, click, field input, file selection, identity persistence or upload-claim reset.",
                   "An empty/sidebar-only surface or missing controls does not prove business controls do not exist."]}
    guard();once(directory / "OBSERVATION_RESULT.json", result);return result
