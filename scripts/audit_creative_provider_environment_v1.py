"""Read-only local/provider capability discovery. No generation or balance API.

The optional remote operation is one GET /models to the configured DeepSeek
origin. Output uses an allowlist; credentials, headers and raw error bodies are
never written. This is an operator audit, not a production approval gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
TRIAL = Path("data/production_revisions/shared_full_production_20261012")
REGISTRY = Path("config/creative_provider_capabilities_20261012.json")
MODEL_FIELDS = ("id", "name", "context_window", "max_output_tokens",
                "input_modalities", "output_modalities", "effort", "api_capabilities")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_audit(project, relative):
    root = project / relative
    ledger_path = root / "CALL_LEDGER.json"
    ledger = read(ledger_path)
    mismatches = []
    for rel, expected in ledger["source_manifest"].items():
        for label, path in (("working_copy", project / rel),
                            ("frozen_copy", root / "source_at_dispatch" / rel)):
            if not path.is_file() or sha(path) != expected:
                mismatches.append({"kind": label, "path": rel})
    return {"run": relative.as_posix(), "ledger_sha256": sha(ledger_path),
            "bound_files": len(ledger["source_manifest"]),
            "frozen_sources_unchanged": not mismatches, "mismatches": mismatches}


def sanitize_models(body):
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ValueError("invalid model directory")
    rows = []
    for row in body["data"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("invalid model entry")
        # Only documented, public model metadata. No response headers/errors.
        rows.append({key: row[key] for key in MODEL_FIELDS if key in row})
    return rows


def query_deepseek_models(config, client_factory=None):
    import httpx
    parsed = urlsplit(config.base_url)
    if (config.provider != "deepseek" or parsed.scheme != "https"
        or parsed.netloc != "api.deepseek.com" or parsed.path.rstrip("/") not in ("", "/v1")
        or parsed.query or parsed.fragment or parsed.username or parsed.password):
        return {"status": "blocked_unverified_origin", "request_sent": False}
    url = config.base_url.rstrip("/") + "/models"
    try:
        if client_factory is None:
            client_factory = lambda: httpx.Client(timeout=20, follow_redirects=False,
                                                  transport=httpx.HTTPTransport(retries=0))
        with client_factory() as client:
            response = client.get(url, headers={"Authorization": "Bearer " + config.api_key})
            if response.status_code != 200:
                return {"status": "http_rejected", "request_sent": True,
                        "http_status": response.status_code, "endpoint": url}
            rows = sanitize_models(response.json())
        selected = next((r for r in rows if r["id"] == config.model), None)
        return {"status": "directory_received", "request_sent": True, "http_status": 200,
                "endpoint": url, "models": rows, "configured_model": config.model,
                "configured_model_metadata": selected, "configured_model_listed": selected is not None,
                "generation_request_sent": False, "account_balance_requested": False,
                "automatic_retry": False}
    except Exception as exc:
        # Never stringify exceptions: URLs, headers or credentials can appear.
        return {"status": "directory_result_unavailable", "request_sent": True,
                "error_type": type(exc).__name__, "generation_request_sent": False,
                "automatic_retry": False}


def collect(project=PROJECT, query_models=False):
    registry = read(project / REGISTRY)
    local_config = read(project / "config/seedance_models.json")
    manifest = read(project / TRIAL / "run_01/SHARED_MANIFEST.json")
    result = read(project / TRIAL / "probe_v4/PRODUCTION_RESULT.json")
    loop = read(project / TRIAL / "probe_v4/LOOP_STATE.json")
    packages = {}
    for name in ("openai", "httpx", "jsonschema", "langchain-core", "langgraph",
                 "temporalio", "volcengine-python-sdk"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    directory = {"status": "not_queried", "request_sent": False}
    if query_models:
        from src.content_factory.creative_workflow_roles import role_config
        try:
            config = role_config("director")  # Existing label means text reviewer.
        except Exception as exc:
            directory = {"status": "configuration_unavailable", "request_sent": False,
                         "error_type": type(exc).__name__}
        else:
            directory = query_deepseek_models(config)
    return {"schema": "creative_provider_environment_audit/v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "registry_path": REGISTRY.as_posix(), "registry_sha256": sha(project / REGISTRY),
            "official_claims_are_documentation_not_account_verification": True,
            "seedance_selected_catalog_config": local_config["preferred"],
            "shared_frozen_manifest": {
                "path": (TRIAL / "run_01/SHARED_MANIFEST.json").as_posix(),
                "sha256": sha(project / TRIAL / "run_01/SHARED_MANIFEST.json"),
                "allowed_reference_modes": manifest["provider_policy"].get("allowed_reference_modes"),
                "allows_actor_asset_mapping": manifest["provider_policy"]["allows_actor_asset_mapping"],
                "actors": [{"id": a["id"], "name": a["name"],
                            "asset_binding_status": a["asset_binding"]["status"],
                            "voice_status": a["voice"]["status"]} for a in manifest["actors"]]},
            "current_stop": {"status": result["status"], "reason": result["reason"],
                             "complete_text_handoff_ready": result["complete_text_handoff_ready"],
                             "media_dispatch_allowed": result["media_dispatch_allowed"],
                             "loop_state_sha256": sha(project / TRIAL / "probe_v4/LOOP_STATE.json"),
                             "director_capacity": loop["coordinator_terminal"]["failure_route"]["capacity"]},
            "frozen_sources": [freeze_audit(project, TRIAL / name) for name in ("run_01", "probe_v4")],
            "packages": packages,
            "cli_on_path": {name: shutil.which(name) for name in ("comfy", "kling", "arkcli", "ffprobe")},
            "deepseek_live_model_directory": directory,
            "generation_calls": 0, "media_calls": 0, "model_configuration_changed": False,
            "ledger_changed": False, "production_integration_completed": False,
            "creative_quality_passed": False, "media_quality_passed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-models", action="store_true", help="One read-only DeepSeek GET /models")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(query_models=args.query_models)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps({"output": str(args.output.resolve()), "generation_calls": 0,
                      "directory_status": result["deepseek_live_model_directory"]["status"],
                      "frozen_sources_unchanged": all(r["frozen_sources_unchanged"] for r in result["frozen_sources"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
