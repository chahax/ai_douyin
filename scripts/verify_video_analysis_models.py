"""Offline integrity and optional ASR smoke checks for local analysis models."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from safetensors import safe_open
from transformers import AutoConfig, AutoProcessor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / ".local_models" / "video_analysis"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--asr-smoke",
        action="store_true",
        help="Load Paraformer on CPU and transcribe its bundled example audio.",
    )
    return parser.parse_args()


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def stable_file_listing_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(str(item.stat().st_size).encode("ascii"))
    return digest.hexdigest()


def verify_manifest(root: Path) -> dict:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "local_video_analysis_models/v1":
        raise RuntimeError("unexpected model manifest schema")
    for entry in manifest.get("models", []):
        model_path = Path(entry["path"])
        if not model_path.is_dir():
            raise RuntimeError(f"missing model directory: {model_path}")
        missing = [name for name in entry["required_files"] if not (model_path / name).is_file()]
        if missing:
            raise RuntimeError(f"{entry['key']} is missing required files: {missing}")
        actual_size = directory_size(model_path)
        if actual_size != entry["size_bytes"]:
            raise RuntimeError(
                f"{entry['key']} size changed: manifest={entry['size_bytes']} actual={actual_size}"
            )
        actual_hash = stable_file_listing_hash(model_path)
        if actual_hash != entry["file_listing_sha256"]:
            raise RuntimeError(
                f"{entry['key']} file listing changed: "
                f"manifest={entry['file_listing_sha256']} actual={actual_hash}"
            )
    return manifest


def verify_qwen(root: Path) -> dict:
    model_path = root / "Qwen3-VL-4B-Instruct"
    index = json.loads(
        (model_path / "model.safetensors.index.json").read_text(encoding="utf-8")
    )
    shard_names = sorted(set(index["weight_map"].values()))
    tensor_count = 0
    for shard_name in shard_names:
        shard_path = model_path / shard_name
        if not shard_path.is_file():
            raise RuntimeError(f"missing Qwen shard: {shard_path}")
        with safe_open(shard_path, framework="pt", device="cpu") as handle:
            tensor_count += len(handle.keys())

    config = AutoConfig.from_pretrained(model_path, local_files_only=True)
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    return {
        "model_type": config.model_type,
        "processor": type(processor).__name__,
        "shards": shard_names,
        "indexed_tensors": len(index["weight_map"]),
        "header_tensors": tensor_count,
    }


def run_asr_smoke(root: Path) -> dict:
    os.environ.setdefault("NUMBA_CACHE_DIR", str(PROJECT_ROOT / "data" / ".numba_cache"))
    from funasr import AutoModel

    model_path = root / "paraformer-zh"
    audio_path = model_path / "example" / "asr_example.wav"
    model = AutoModel(
        model=str(model_path),
        device="cpu",
        disable_update=True,
    )
    result = model.generate(
        input=str(audio_path),
        batch_size_s=60,
        hotword="劳动合同 劳动仲裁 律师 法院",
    )
    return {"audio": str(audio_path), "result": result}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = args.root.resolve()
    result = {
        "manifest_models": len(verify_manifest(root).get("models", [])),
        "qwen": verify_qwen(root),
    }
    if args.asr_smoke:
        result["asr_smoke"] = run_asr_smoke(root)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
