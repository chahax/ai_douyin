from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a small emotion audition set through a local GPT-SoVITS SDK."
    )
    parser.add_argument("specs")
    parser.add_argument("--sdk-root", required=True)
    parser.add_argument("--tts-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--gpt-weights",
        default="GPT_weights_v2ProPlus/xxx-e10.ckpt",
    )
    parser.add_argument(
        "--sovits-weights",
        default="SoVITS_weights_v2ProPlus/xxx_e12_s192.pth",
    )
    args = parser.parse_args()

    specs_path = Path(args.specs).resolve()
    config_path = Path(args.tts_config).resolve()
    output_dir = Path(args.output_dir).resolve()
    sdk_root = Path(args.sdk_root).resolve()
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    if not isinstance(specs, list) or not specs:
        raise ValueError("specs must be a non-empty JSON array")
    output_dir.mkdir(parents=True, exist_ok=True)

    os.chdir(sdk_root)
    sys.path.insert(0, str(sdk_root))
    sys.path.insert(0, str(sdk_root / "GPT_SoVITS"))
    from sdk.tts_client import ClientConfig, TTSClient

    client = TTSClient(
        ClientConfig(
            tts_config=str(config_path),
            gpt_weights=args.gpt_weights,
            sovits_weights=args.sovits_weights,
            output_dir=str(output_dir / "sdk"),
            default_text_lang="zh",
            default_prompt_lang="zh",
            default_output_format="wav",
            default_request_version="v2ProPlus",
        )
    )

    report: list[dict[str, object]] = []
    for item in specs:
        item_id = str(item["id"])
        started_at = time.time()
        result = client.synthesize(
            text=str(item["text"]),
            ref_audio_path=str(Path(item["ref_audio"]).resolve()),
            prompt_text=str(item.get("prompt_text", "")),
            text_lang="zh",
            prompt_lang="zh",
            output_format="wav",
            speed_factor=float(item.get("speed_factor", 1.0)),
            trace_id=item_id,
            request_version="v2ProPlus",
            top_k=int(item.get("top_k", 12)),
            top_p=float(item.get("top_p", 0.9)),
            temperature=float(item.get("temperature", 0.95)),
            text_split_method="cut5",
            sample_steps=int(item.get("sample_steps", 32)),
            repetition_penalty=float(item.get("repetition_penalty", 1.35)),
            seed=int(item.get("seed", 20260729)),
            tts_config=str(config_path),
            gpt_weights=args.gpt_weights,
            sovits_weights=args.sovits_weights,
        )
        if not result.get("success"):
            raise RuntimeError(
                f"{item_id}: {result.get('error_code')} {result.get('error_msg')}"
            )
        source = Path(result["audio_path"])
        if not source.is_absolute():
            source = sdk_root / source
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = output_dir / f"{item_id}.wav"
        shutil.copy2(source, destination)
        report.append(
            {
                "id": item_id,
                "text": item["text"],
                "emotion": item.get("emotion", ""),
                "ref_audio": str(Path(item["ref_audio"]).resolve()),
                "prompt_text": item.get("prompt_text", ""),
                "speed_factor": item.get("speed_factor", 1.0),
                "temperature": item.get("temperature", 0.95),
                "seed": item.get("seed", 20260729),
                "elapsed_seconds": round(time.time() - started_at, 3),
                "output": str(destination),
            }
        )
        print(f"generated {item_id}: {destination}", flush=True)

    (output_dir / "audition_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
