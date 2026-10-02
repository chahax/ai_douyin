"""Prepare and generate an immutable Seedream character/background asset pack."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_factory.seedance_client import SeedanceConfig
from src.content_factory.seedance_frames import image_info
from src.services.provider_call_ledger import ProviderCallLedger

SCHEMA = "ark_visual_asset_pack/v1"
RECEIPT_SCHEMA = "ark_visual_asset_receipt/v1"
TRUSTED_MODELS = {"doubao-seedream-5-0-pro-260628"}
TRUSTED_SIZES = {"1440x2560", "2560x1440"}
SAFE_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
MAX_IMAGE_BYTES = 30 * 1024 * 1024
REUSABLE_LIBRARY = ROOT / "data" / "visual_asset_library" / "reusable_assets.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value, *, exclusive: bool = False):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if exclusive:
        with path.open("xb") as handle:
            handle.write(raw)
    else:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(raw)
        tmp.replace(path)
    return sha(raw)


def config_checked(require_key: bool):
    config = SeedanceConfig.from_env("ark_api", require_key=require_key)
    parsed = urlsplit(config.base_url.rstrip("/"))
    if parsed.scheme != "https" or parsed.hostname != "ark.cn-beijing.volces.com" or parsed.path != "/api/v3":
        raise ValueError("Asset generation requires the Beijing Ark HTTPS endpoint")
    return config


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("wrong asset pack schema")
    if data.get("model") not in TRUSTED_MODELS:
        raise ValueError("unregistered Seedream model")
    if data.get("size") not in TRUSTED_SIZES:
        raise ValueError("this workflow uses an account-verified portrait or landscape size")
    assets = data.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must be a non-empty array")
    if "text_acceptance_run" in data:
        from src.content_factory.performance_revision_gate import validate_accepted
        validate_accepted(data["text_acceptance_run"])
    seen = set()
    for item in assets:
        required = {"id", "type", "prompt", "review_checks"}
        if not isinstance(item, dict) or not required.issubset(item) or set(item) - required - {"reference_image", "regeneration_reason"}:
            raise ValueError("each asset needs id/type/prompt/review_checks and optional reference_image")
        if not SAFE_ID.fullmatch(item["id"]) or item["id"] in seen:
            raise ValueError("asset ids must be unique safe uppercase identifiers")
        seen.add(item["id"])
        if REUSABLE_LIBRARY.is_file():
            library = read(REUSABLE_LIBRARY)
            reusable = {row.get("reuse_key"): row for row in library.get("assets", [])}
            hit = reusable.get(item["id"])
            reason = item.get("regeneration_reason")
            if hit and (not isinstance(reason, str) or not reason.strip()):
                raise ValueError(
                    "reusable asset already accepted: " + item["id"]
                    + "; use " + hit["image"]["path"]
                    + " or provide regeneration_reason"
                )
        if item["type"] not in {"character_turnaround", "background", "opening_frame"}:
            raise ValueError("unsupported asset type")
        if not isinstance(item["prompt"], str) or len(item["prompt"].strip()) < 40:
            raise ValueError("asset prompt is too short")
        if not isinstance(item["review_checks"], list) or not item["review_checks"]:
            raise ValueError("review_checks must be non-empty")
        ref = item.get("reference_image")
        if ref is not None and (not isinstance(ref, dict) or not {"path", "sha256", "purpose"}.issubset(ref) or set(ref) - {"path", "sha256", "purpose", "review_path", "review_sha256", "review_intent"}
                                or not isinstance(ref["purpose"], str) or not ref["purpose"].strip()):
            raise ValueError("reference_image needs path/sha256/purpose")
        if ref is not None and data.get("text_acceptance_run"):
            if not ref.get("review_path") or not ref.get("review_sha256"):
                raise ValueError("new media references require a bound image review")
            review_path = Path(ref["review_path"]).resolve()
            source_path = Path(ref["path"]).resolve()
            review_path.relative_to(ROOT / "data" / "video_generation")
            source_path.relative_to(ROOT / "data" / "video_generation")
            if sha(review_path.read_bytes()) != ref["review_sha256"] or sha(source_path.read_bytes()) != ref["sha256"]:
                raise ValueError("reference image or review changed")
            review = read(review_path)
            repair = ref.get("review_intent") == "repair_failed_visual_asset"
            allowed = review.get("decision") == "passed" or (repair and review.get("decision") == "failed")
            if not allowed or review.get("image_sha256") != ref["sha256"]:
                raise ValueError("reference image is not approved or explicitly bound for visual repair")



def prepare(manifest_path: Path, output: Path):
    raw = manifest_path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    validate_manifest(data)
    output.resolve().relative_to(ROOT / "data" / "video_generation")
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.original.json").write_bytes(raw)
    pack = {
        "schema": RECEIPT_SCHEMA,
        "status": "prepared",
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha(raw),
        "model": data["model"],
        "size": data["size"],
        "prepared_at": now(),
        "assets": [],
    }
    for item in data["assets"]:
        folder = output / item["id"]
        folder.mkdir()
        request = {
            "model": data["model"],
            "prompt": item["prompt"].strip(),
            "size": data["size"],
            "response_format": "url",
            "watermark": False,
        }
        reference_binding = None
        if "reference_image" in item:
            ref = item["reference_image"]
            ref_path = Path(ref["path"]).resolve()
            ref_path.relative_to(ROOT / "data" / "video_generation")
            raw_ref = ref_path.read_bytes()
            info = image_info(ref_path)
            if info["sha256"] != ref["sha256"]:
                raise ValueError("reference image changed: " + item["id"])
            request["image"] = "data:" + info["mime"] + ";base64," + base64.b64encode(raw_ref).decode("ascii")
            reference_binding = {"path": str(ref_path), "sha256": info["sha256"],
                                 "mime": info["mime"], "purpose": ref["purpose"]}
        request_sha = write(folder / "request.json", request, exclusive=True)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "asset_id": item["id"],
            "asset_type": item["type"],
            "status": "prepared",
            "model": data["model"],
            "size": data["size"],
            "request_sha256": request_sha,
            "prompt_sha256": sha(item["prompt"].strip().encode("utf-8")),
            "review_checks": item["review_checks"],
            "reference_image": reference_binding,
            "api_calls": 0,
            "media_review": "pending",
            "prepared_at": now(),
        }
        write(folder / "receipt.json", receipt, exclusive=True)
        pack["assets"].append({"id": item["id"], "folder": str(folder), "status": "prepared"})
    write(output / "pack.receipt.json", pack, exclusive=True)
    return pack


def verify_pack(output: Path):
    pack = read(output / "pack.receipt.json")
    raw = (output / "manifest.original.json").read_bytes()
    if pack.get("schema") != RECEIPT_SCHEMA or sha(raw) != pack.get("manifest_sha256"):
        raise ValueError("pack receipt or manifest changed")
    source = Path(pack["manifest_path"])
    if not source.is_file() or sha(source.read_bytes()) != pack["manifest_sha256"]:
        raise ValueError("source manifest changed")
    manifest = json.loads(raw.decode("utf-8-sig"))
    validate_manifest(manifest)
    return pack, manifest


def submit_all(output: Path):
    config = config_checked(True)
    pack, manifest = verify_pack(output)
    ledger = ProviderCallLedger()
    api = config.base_url.rstrip("/") + "/images/generations"
    headers = {"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=config.timeout_seconds) as http, httpx.Client(
        timeout=config.timeout_seconds, follow_redirects=True
    ) as downloader:
        for asset in manifest["assets"]:
            folder = output / asset["id"]
            receipt_path = folder / "receipt.json"
            receipt = read(receipt_path)
            if receipt.get("status") == "downloaded":
                continue
            if receipt.get("status") != "prepared" or receipt.get("api_calls") != 0:
                raise RuntimeError("unresolved asset attempt: " + asset["id"])
            request_raw = (folder / "request.json").read_bytes()
            request = json.loads(request_raw)
            if sha(request_raw) != receipt["request_sha256"]:
                raise ValueError("request changed: " + asset["id"])
            receipt.update(status="submit_outcome_unknown", api_calls=1, submitted_at=now())
            write(receipt_path, receipt)
            call_id = ledger.begin_call(
                provider="ark_api",
                operation="image_generation",
                model=receipt["model"],
                request=request,
                source_path=receipt_path,
                created_at=receipt["submitted_at"],
            )
            try:
                response = http.post(api, json=request, headers=headers)
                raw = response.content
                (folder / "response.json").write_bytes(raw)
                receipt.update(http_status=response.status_code, response_sha256=sha(raw), response_received_at=now())
                write(receipt_path, receipt)
                response.raise_for_status()
                body = json.loads(raw)
                rows = body.get("data")
                if body.get("model") != receipt["model"] or not isinstance(rows, list) or len(rows) != 1:
                    raise ValueError("unexpected Seedream response")
                url = rows[0].get("url")
                if not isinstance(url, str) or not url.startswith("https://"):
                    raise ValueError("missing Seedream image URL")
                receipt.update(status="image_created_pending_download", original_url=url,
                               provider_created=body.get("created"), usage=body.get("usage", {}))
                write(receipt_path, receipt)
                ledger.mark_submitted(
                    call_id,
                    status="image_created_pending_download",
                    response=body,
                    http_status=response.status_code,
                )
                with downloader.stream("GET", url) as media:
                    media.raise_for_status()
                    image = bytearray()
                    for chunk in media.iter_bytes():
                        image.extend(chunk)
                        if len(image) > MAX_IMAGE_BYTES:
                            raise ValueError("image exceeds 30 MiB")
                image_path = folder / "original.jpeg"
                with image_path.open("xb") as handle:
                    handle.write(image)
                info = image_info(image_path)
                receipt.update(status="downloaded", image=str(image_path), image_sha256=sha(image),
                               image_info=info, media_review="pending", finished_at=now())
                write(receipt_path, receipt)
                ledger.mark_submitted(
                    call_id,
                    status="downloaded",
                    response=body,
                    http_status=response.status_code,
                )
                print(json.dumps({"asset_id": asset["id"], "status": "downloaded",
                                  "image": str(image_path), "usage": receipt.get("usage")}, ensure_ascii=False), flush=True)
            except Exception as exc:
                receipt.update(error_type=type(exc).__name__, finished_at=now())
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (400, 401, 403, 404):
                    receipt["status"] = "request_rejected"
                write(receipt_path, receipt)
                try:
                    ledger.mark_failed(
                        call_id,
                        exc,
                        status=receipt["status"],
                        http_status=receipt.get("http_status"),
                    )
                except Exception:
                    pass
                raise
    pack["status"] = "downloaded_pending_review"
    pack["finished_at"] = now()
    for row in pack["assets"]:
        row["status"] = read(output / row["id"] / "receipt.json")["status"]
    write(output / "pack.receipt.json", pack)
    return pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "submit-all", "status"))
    parser.add_argument("--manifest")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output_dir).resolve()
    output.relative_to(ROOT / "data" / "video_generation")
    if args.operation == "prepare":
        if not args.manifest:
            parser.error("prepare requires --manifest")
        result = prepare(Path(args.manifest).resolve(), output)
    elif args.operation == "submit-all":
        if args.manifest:
            parser.error("submit-all uses the preserved manifest")
        result = submit_all(output)
    else:
        result, _ = verify_pack(output)
    print(json.dumps({"status": result["status"], "output_dir": str(output),
                      "assets": result["assets"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "message": "Inspect preserved receipts; unresolved attempts are never resubmitted."}))
        raise

