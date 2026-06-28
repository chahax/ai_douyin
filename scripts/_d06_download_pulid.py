# -*- coding: utf-8 -*-
"""D0.6 - 后台下载 PuLID + AntelopeV2 权重。

绕过 SSL 证书吊销检查（跟之前 RAG 部署一样用 urllib + ssl._create_unverified_context）。

下载清单：
1. PuLID 模型: models/pulid/ip-adapter_pulid_sdxl_fp16.safetensors (~1.5GB)
2. AntelopeV2:  models/insightface/models/antelopev2/ 多个 .onnx 文件 (~300MB)

EVA02-CLIP-L-14-336 由 PuLID 节点自动下载到 HF cache，不在此脚本管。
"""
import os
import ssl
import urllib.request
import time
from pathlib import Path

# Allow passing through Windows SSL cert revocation check
ctx = ssl._create_unverified_context()

DOWNLOADS = [
    # PuLID model
    {
        "url": "https://huggingface.co/huchenlei/ipadapter_pulid/resolve/main/ip-adapter_pulid_sdxl_fp16.safetensors?download=true",
        "out": "D:/IT/AI_vido/ComfyUI/models/pulid/ip-adapter_pulid_sdxl_fp16.safetensors",
    },
    # AntelopeV2 - insightface face detection/recognition
    {
        "url": "https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2/1k3d68.onnx",
        "out": "D:/IT/AI_vido/ComfyUI/models/insightface/models/antelopev2/1k3d68.onnx",
    },
    {
        "url": "https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2/2d106det.onnx",
        "out": "D:/IT/AI_vido/ComfyUI/models/insightface/models/antelopev2/2d106det.onnx",
    },
    {
        "url": "https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2/det_10g.onnx",
        "out": "D:/IT/AI_vido/ComfyUI/models/insightface/models/antelopev2/det_10g.onnx",
    },
    {
        "url": "https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2/genderage.onnx",
        "out": "D:/IT/AI_vido/ComfyUI/models/insightface/models/antelopev2/genderage.onnx",
    },
    {
        "url": "https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2/w600k_r50.onnx",
        "out": "D:/IT/AI_vido/ComfyUI/models/insightface/models/antelopev2/w600k_r50.onnx",
    },
]


def main():
    total_bytes = 0
    total_start = time.time()
    for item in DOWNLOADS:
        out = Path(item["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists() and out.stat().st_size > 0:
            print(f"[skip] already exists: {out} ({out.stat().st_size} bytes)")
            total_bytes += out.stat().st_size
            continue

        url = item["url"]
        print(f"[get] {url}")
        print(f"  -> {out}")
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=1800) as resp:
                total = int(resp.headers.get("content-length", 0))
                written = 0
                with open(out, "wb") as f:
                    while True:
                        chunk = resp.read(131072)
                        if not chunk:
                            break
                        f.write(chunk)
                        written += len(chunk)
                        if written % (50 * 1024 * 1024) == 0:
                            pct = written / total * 100 if total else 0
                            speed = written / (time.time() - t0) / 1024 / 1024
                            print(
                                f"  {written / 1024 / 1024:.1f}MB / {total / 1024 / 1024:.1f}MB "
                                f"({pct:.0f}%) at {speed:.2f}MB/s",
                                flush=True,
                            )
            elapsed = time.time() - t0
            size = out.stat().st_size
            print(f"  OK: {size} bytes in {elapsed:.1f}s ({(size / elapsed / 1024 / 1024):.2f}MB/s)")
            total_bytes += size
        except Exception as exc:
            print(f"  FAIL: {type(exc).__name__}: {exc}")
            if out.exists() and out.stat().st_size == 0:
                out.unlink()

    print(f"\nTotal: {total_bytes / 1024 / 1024:.1f}MB in {time.time() - total_start:.1f}s")


if __name__ == "__main__":
    main()
