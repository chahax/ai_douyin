from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


MODELS = [
    {
        "repo_id": "TMElyralab/MuseTalk",
        "local_subdir": ".",
        "allow_patterns": None,
    },
    {
        "repo_id": "stabilityai/sd-vae-ft-mse",
        "local_subdir": "sd-vae",
        "allow_patterns": ["config.json", "diffusion_pytorch_model.bin"],
    },
    {
        "repo_id": "openai/whisper-tiny",
        "local_subdir": "whisper",
        "allow_patterns": ["config.json", "pytorch_model.bin", "preprocessor_config.json"],
    },
    {
        "repo_id": "yzd-v/DWPose",
        "local_subdir": "dwpose",
        "allow_patterns": ["dw-ll_ucoco_384.pth"],
    },
    {
        "repo_id": "ManyOtherFunctions/face-parse-bisent",
        "local_subdir": "face-parse-bisent",
        "allow_patterns": ["79999_iter.pth", "resnet18-5c106cde.pth"],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the official MuseTalk runtime weights.")
    parser.add_argument("--model-root", default=r"D:\IT\MuseTalk\models")
    parser.add_argument("--cache-dir", default=r"D:\IT\MuseTalk\.hf_cache")
    args = parser.parse_args()

    model_root = Path(args.model_root).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    model_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    for item in MODELS:
        local_dir = model_root / item["local_subdir"]
        local_dir.mkdir(parents=True, exist_ok=True)
        print(f"downloading {item['repo_id']} -> {local_dir}", flush=True)
        snapshot_download(
            repo_id=item["repo_id"],
            local_dir=str(local_dir),
            cache_dir=str(cache_dir),
            allow_patterns=item["allow_patterns"],
            resume_download=True,
        )
        print(f"completed {item['repo_id']}", flush=True)


if __name__ == "__main__":
    main()
