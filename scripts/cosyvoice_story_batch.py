#!/usr/bin/env python
"""Render an emotion-directed multi-role story with one CosyVoice3 model load.

All runtime paths are supplied explicitly by the production provider.  The
runner never silently substitutes a different model, project, or cache root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _install_offline_modelscope_guard() -> None:
    """Force ModelScope lookups to already-cached local files only."""
    import modelscope

    original_snapshot_download = modelscope.snapshot_download

    def _local_snapshot_download(model_id, *args, **kwargs):
        kwargs["local_files_only"] = True
        return original_snapshot_download(model_id, *args, **kwargs)

    modelscope.snapshot_download = _local_snapshot_download


def _resolve_path(value: str, project_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CosyVoice3 batch story renderer (one model load)"
    )
    parser.add_argument("spec", type=Path)
    parser.add_argument("--cosyvoice-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-fp16", action="store_true")
    args = parser.parse_args()

    cosyvoice_root = args.cosyvoice_root.resolve()
    model_dir = args.model_dir.resolve()
    project_root = (args.project_root or Path.cwd()).resolve()
    cache_dir = (args.cache_dir or project_root / "data" / "cosyvoice_cache").resolve()
    if not cosyvoice_root.is_dir():
        print(f"[error] CosyVoice root not found: {cosyvoice_root}", flush=True)
        return 2
    if not (cosyvoice_root / "cosyvoice").is_dir():
        print(f"[error] CosyVoice root missing cosyvoice/ package: {cosyvoice_root}", flush=True)
        return 2
    if not model_dir.joinpath("cosyvoice3.yaml").is_file():
        print(f"[error] CosyVoice3 model not found at: {model_dir}", flush=True)
        return 2

    numba_cache = cache_dir / "numba"
    huggingface_cache = cache_dir / "huggingface"
    numba_cache.mkdir(parents=True, exist_ok=True)
    huggingface_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(numba_cache))
    os.environ.setdefault("HF_HOME", str(huggingface_cache))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ["TEMP"] = str(cache_dir)
    os.environ["TMP"] = str(cache_dir)
    sys.path.insert(0, str(cosyvoice_root))
    sys.path.insert(0, str(cosyvoice_root / "third_party" / "Matcha-TTS"))
    _install_offline_modelscope_guard()

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
    output_dir = _resolve_path(spec["output_dir"], project_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    cast = spec["cast"]
    for role in cast.values():
        prompt = _resolve_path(role["prompt_wav"], project_root)
        if not prompt.is_file():
            raise FileNotFoundError(prompt)
    started = time.perf_counter()
    model = AutoModel(
        model_dir=str(model_dir),
        load_trt=False,
        load_vllm=False,
        fp16=not args.no_fp16,
    )
    print(f"model_load_seconds={time.perf_counter() - started:.2f}", flush=True)

    report: list[dict[str, object]] = []
    for index, item in enumerate(spec["lines"]):
        output = output_dir / f"{item['id']}_{item['speaker']}.wav"
        if output.is_file() and not args.overwrite:
            info = torchaudio.info(str(output))
            duration = info.num_frames / info.sample_rate
            print(f"skip {item['id']} ({duration:.2f}s)", flush=True)
        else:
            instruction = (
                "You are a helpful assistant. "
                + item["instruct"].strip()
                + "<|endofprompt|>"
            )
            chunks = []
            with torch.inference_mode():
                for result in model.inference_instruct2(
                    item["text"],
                    instruction,
                    str(_resolve_path(cast[item["speaker"]]["prompt_wav"], project_root)),
                    stream=False,
                    speed=float(item.get("speed", 1.08)),
                ):
                    chunks.append(result["tts_speech"].cpu())
            if not chunks:
                raise RuntimeError(f"CosyVoice returned no audio for {item['id']}")
            speech = torch.cat(chunks, dim=1)
            torchaudio.save(
                str(output),
                speech,
                model.sample_rate,
                encoding="PCM_S",
                bits_per_sample=16,
            )
            duration = speech.shape[1] / model.sample_rate
            print(f"rendered {index + 1}/{len(spec['lines'])} {item['id']} ({duration:.2f}s)", flush=True)
        report.append(
            {
                "id": item["id"],
                "scene_id": item["scene_id"],
                "speaker": item["speaker"],
                "text": item["text"],
                "audio_path": str(output.resolve()),
                "duration_seconds": round(duration, 3),
                "speed": float(item.get("speed", 1.08)),
                "instruct": item["instruct"],
            }
        )

    report_path = output_dir / "voice_render_report.json"
    report_path.write_text(
        json.dumps({"cast": cast, "lines": report}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"report={report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
