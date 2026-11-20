"""Standalone bootstrap/download/offline entry point; never imports project code."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
MODEL_ID = "urchade/gliner_multi-v2.1"
REVISION = "443d26d654e0324125a96bebd8e796c14ff2efe6"
WEIGHT_SHA = "2100142f31627531497850659dcb3821c99d5e71c08a8e01a98e4b11ef32a199"


def configure():
    for relative in ("cache/huggingface", "cache/torch", "cache/pip", "cache/uv", "tmp", "results", "models"):
        (ROOT / relative).mkdir(parents=True, exist_ok=True)
    values = {
        "HF_HOME": str(ROOT / "cache/huggingface"),
        "HF_HUB_CACHE": str(ROOT / "cache/huggingface/hub"),
        "HUGGINGFACE_HUB_CACHE": str(ROOT / "cache/huggingface/hub"),
        "TORCH_HOME": str(ROOT / "cache/torch"),
        "XDG_CACHE_HOME": str(ROOT / "cache"),
        "PIP_CACHE_DIR": str(ROOT / "cache/pip"),
        "UV_CACHE_DIR": str(ROOT / "cache/uv"),
        "TEMP": str(ROOT / "tmp"), "TMP": str(ROOT / "tmp"),
        "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
        "HF_HUB_DISABLE_XET": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "HF_HUB_ETAG_TIMEOUT": "20", "HF_HUB_DOWNLOAD_TIMEOUT": "60",
        "TOKENIZERS_PARALLELISM": "false", "CUDA_VISIBLE_DEVICES": "",
        "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
    }
    os.environ.update(values)
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "PYTHONPATH", "PYTHONHOME"):
        os.environ.pop(name, None)
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        raise RuntimeError("Run with this laboratory's .venv Python, using -I")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def baseline():
    target = ROOT / "results/BASELINE.json"
    if target.exists():
        raise RuntimeError("Baseline already exists; do not overwrite")
    paths = [PROJECT / p for p in (
        ".venv/pyvenv.cfg", "requirements.txt", "requirements-video-analysis.txt", "requirements-volcengine.txt",
        "src/content_factory/novel_video_trial_v1.py",
        "data/video_generation/novel_ferry_first_trial_20261018/S1A/REQUEST.json",
        "data/video_generation/novel_ferry_first_trial_20261018/S1A/PROMPT.txt",
        "data/video_generation/novel_ferry_first_trial_20261018/S1A/RECIPE.json",
        "data/video_generation/novel_ferry_first_trial_20261018/S1A/NATIVE_QUERY_003.json",
    )]
    source = json.loads((PROJECT / "data/video_generation/novel_ferry_first_trial_20261018/TEXT_PRESERVATION_BASELINE.json").read_text(encoding="utf-8"))
    paths.extend(Path(x["path"]) for x in source["files"])
    command = [str(PROJECT / ".venv/Scripts/python.exe"), "-I", "-c",
               "import importlib.metadata as m,json;print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions())))"]
    packages = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
    save(target, {"captured_at": datetime.now(timezone.utc).isoformat(), "files": [{"path": str(p), "sha256": digest(p)} for p in paths], "production_packages": packages,
                  "note": "Captured after independent package installation, before any inference. Installer commands targeted only lab venv."})
    print(f"Baseline: {len(paths)} protected files", flush=True)


def download(endpoint):
    os.environ["HF_ENDPOINT"] = endpoint
    from huggingface_hub import HfApi, snapshot_download
    api = HfApi(endpoint=endpoint, token=False)
    specs = [(MODEL_ID, REVISION, ["README.md", "gliner_config.json", "model.safetensors"]),
             ("microsoft/mdeberta-v3-base", "a0484667b22365f84929a935b5e50a51f71f159d", ["config.json", "tokenizer*.json", "special_tokens_map.json", "added_tokens.json", "spm.model"])]
    records = []
    for repo_id, revision, patterns in specs:
        info = api.model_info(repo_id, revision=revision, files_metadata=True)
        revision = info.sha
        print(f"Downloading {repo_id}@{revision}", flush=True)
        local = snapshot_download(repo_id, revision=revision, allow_patterns=patterns,
                                  cache_dir=os.environ["HF_HUB_CACHE"], token=False, max_workers=2)
        files = []
        for p in sorted(Path(local).iterdir()):
            if not p.is_file():
                continue
            sha = digest(p)
            files.append({"name": p.name, "path": str(p), "bytes": p.stat().st_size, "sha256": sha})
            if repo_id == MODEL_ID and p.name == "model.safetensors" and sha != WEIGHT_SHA:
                raise RuntimeError("Model hash does not match author's official Hugging Face pointer")
        records.append({"repo": repo_id, "revision": revision, "snapshot": local, "files": files})
        save(ROOT / "results/MODEL_DOWNLOAD.json", {"transport_endpoint": endpoint,
             "official_weight_source": f"https://huggingface.co/{MODEL_ID}/blob/{REVISION}/model.safetensors",
             "official_weight_sha256": WEIGHT_SHA, "repos": records})
    (ROOT / "models/model_path.txt").write_text(records[0]["snapshot"], encoding="utf-8")
    bind_cache()
    print("Download and SHA256 verification complete", flush=True)


def bind_cache():
    """Bind the default offline cache ref to our already downloaded pinned revision."""
    data = json.loads((ROOT / "results/MODEL_DOWNLOAD.json").read_text(encoding="utf-8"))
    records = []
    for repo in data["repos"]:
        snapshot = Path(repo["snapshot"]).resolve()
        if not snapshot.is_relative_to(ROOT / "cache"):
            raise RuntimeError("Unexpected snapshot outside lab")
        for item in repo["files"]:
            if digest(item["path"]) != item["sha256"]:
                raise RuntimeError("Downloaded file changed")
        ref = snapshot.parent.parent / "refs/main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(repo["revision"], encoding="utf-8")
        records.append({"ref": str(ref), "pinned_revision": repo["revision"]})
    save(ROOT / "results/OFFLINE_CACHE_BINDING.json", {"bindings": records,
         "reason": "Pinned snapshot download does not create main refs; legacy GLiNER requests base tokenizer/config by repo name. Local cache main resolves only to this frozen revision."})
    print("Offline cache refs bound to downloaded pinned revisions", flush=True)


def offline():
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    def blocked(*args, **kwargs):
        raise RuntimeError("Network disabled in local inference process")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    try:
        socket.create_connection(("127.0.0.1", 9))
    except RuntimeError:
        print("Offline socket guard self-check passed", flush=True)
    else:
        raise RuntimeError("Socket guard failed")


def verify():
    data = json.loads((ROOT / "results/BASELINE.json").read_text(encoding="utf-8"))
    changes = [x["path"] for x in data["files"] if digest(x["path"]) != x["sha256"]]
    command = [str(PROJECT / ".venv/Scripts/python.exe"), "-I", "-c",
               "import importlib.metadata as m,json;print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions())))"]
    current = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
    origins = {}
    for name in ("gliner", "spacy", "torch", "transformers", "huggingface-hub"):
        d = importlib.metadata.distribution(name)
        origin = str(Path(d.locate_file("")).resolve())
        if not Path(origin).is_relative_to(ROOT / ".venv"):
            raise RuntimeError(f"Package escaped independent venv: {name}")
        origins[name] = {"version": d.version, "location": origin}
    result = {"python": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
              "system_site_packages": False, "package_origins": origins,
              "protected_file_count": len(data["files"]), "changed_files": changes,
              "production_packages_unchanged_since_baseline": current == data["production_packages"],
              "isolation": "venv/cache isolation and Python socket guard, not an OS security sandbox"}
    save(ROOT / "results/ISOLATION_VERIFICATION.json", result)
    if changes or current != data["production_packages"]:
        raise RuntimeError("Protected production state changed")
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("baseline", "download", "bind-cache", "run", "verify"))
    parser.add_argument("--endpoint", default="https://huggingface.co")
    parser.add_argument("--output", default="results/benchmark_01.json")
    parser.add_argument("--splitter", choices=("default", "spacy-zh", "spacy-zh-nonspace"), default="spacy-zh-nonspace")
    args = parser.parse_args()
    configure()
    if args.command == "baseline": baseline()
    elif args.command == "download": download(args.endpoint)
    elif args.command == "bind-cache": bind_cache()
    elif args.command == "verify": verify()
    elif args.command == "run":
        offline()
        model = (ROOT / "models/model_path.txt").read_text(encoding="utf-8").strip()
        output = (ROOT / args.output).resolve()
        if not output.is_relative_to(ROOT) or output.exists():
            raise RuntimeError("Use a new output path inside this lab")
        sys.argv = [str(ROOT / "benchmark.py"), "--model-dir", model,
                    "--prompt", str(PROJECT / "data/video_generation/novel_ferry_first_trial_20261018/S1A/PROMPT.txt"),
                    "--output", str(output), "--splitter", args.splitter]
        runpy.run_path(str(ROOT / "benchmark.py"), run_name="__main__")


if __name__ == "__main__": main()
