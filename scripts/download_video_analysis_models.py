"""Download the pinned local video-analysis models from ModelScope.

The models are stored under ``.local_models/video_analysis`` by default.  That
directory is intentionally gitignored.  Downloads are resumable and a manifest
is written only after every requested model has completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / ".local_models" / "video_analysis"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    key: str
    repo_id: str
    directory: str
    purpose: str
    required_files: tuple[str, ...]
    minimum_size_bytes: int


MODELS = {
    spec.key: spec
    for spec in (
        ModelSpec(
            key="qwen3_vl_4b",
            repo_id="Qwen/Qwen3-VL-4B-Instruct",
            directory="Qwen3-VL-4B-Instruct",
            purpose="video frame understanding, OCR, structure and timeline analysis",
            required_files=("config.json", "preprocessor_config.json"),
            minimum_size_bytes=5_000_000_000,
        ),
        ModelSpec(
            key="paraformer_zh",
            repo_id="iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            directory="paraformer-zh",
            purpose="Mandarin speech recognition with timestamps and hotwords",
            required_files=("config.yaml", "model.pt"),
            minimum_size_bytes=100_000_000,
        ),
        ModelSpec(
            key="fsmn_vad",
            repo_id="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            directory="fsmn-vad",
            purpose="speech activity detection before transcription",
            required_files=("config.yaml", "model.pt"),
            minimum_size_bytes=1_000_000,
        ),
        ModelSpec(
            key="ct_punc",
            repo_id="iic/punc_ct-transformer_cn-en-common-vocab471067-large",
            directory="ct-punc",
            purpose="Chinese and English punctuation restoration",
            required_files=("config.yaml", "model.pt"),
            minimum_size_bytes=100_000_000,
        ),
    )
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "models",
        nargs="*",
        choices=sorted(MODELS),
        default=list(MODELS),
        help="Model keys to download; defaults to the complete primary stack.",
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args()


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def stable_file_listing_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(entry for entry in path.rglob("*") if entry.is_file()):
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(str(item.stat().st_size).encode("ascii"))
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    # ModelScope creates cross-process locks even when local_dir is supplied.
    # Keep both locks and temporary chunks inside the writable, gitignored root.
    os.environ.setdefault("MODELSCOPE_CACHE", str(root / ".modelscope_cache"))
    from modelscope import snapshot_download

    completed = []

    for key in args.models:
        spec = MODELS[key]
        target = root / spec.directory
        print(f"[download] {key}: {spec.repo_id} -> {target}", flush=True)
        resolved = Path(
            snapshot_download(
                spec.repo_id,
                local_dir=str(target),
            )
        ).resolve()
        size_bytes = directory_size(resolved)
        missing = [name for name in spec.required_files if not (resolved / name).is_file()]
        if missing:
            raise RuntimeError(f"{key} download is incomplete; missing files: {missing}")
        if key == "qwen3_vl_4b" and not any(resolved.glob("*.safetensors")):
            raise RuntimeError("qwen3_vl_4b download is incomplete; no safetensors weights found")
        if size_bytes < spec.minimum_size_bytes:
            raise RuntimeError(
                f"{key} download is too small: {size_bytes} < {spec.minimum_size_bytes} bytes"
            )
        completed.append(
            {
                **asdict(spec),
                "path": str(resolved),
                "size_bytes": size_bytes,
                "file_listing_sha256": stable_file_listing_hash(resolved),
            }
        )
        print(f"[complete] {key}", flush=True)

    manifest = {
        "schema": "local_video_analysis_models/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "models": completed,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[manifest] {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
