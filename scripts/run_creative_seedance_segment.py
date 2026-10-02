"""Preview, submit or query a source-bound segment through the shared executor."""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig
from src.content_factory.creative_segment_execution import (
    execute_segment,
    validate,
    reference,
    payload,
    sha,
    read,
    save,
)


__all__ = ["execute_segment", "validate", "reference", "payload", "sha", "read", "save"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("operation", choices=["preview", "submit", "query"])
    ap.add_argument("plan")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--wait-timeout", type=float, default=1800)
    a = ap.parse_args()
    config = SeedanceConfig.from_env("ark_api", require_key=a.operation != "preview")
    plan = read(a.plan)
    if a.operation != "query" and plan.get("model") and config.model != plan["model"]:
        raise ValueError("configured video model differs from reviewed plan")
    with SeedanceClient(config) as client:
        record = execute_segment(
            a.plan, a.output_dir, a.operation, client, wait_timeout=a.wait_timeout
        )
    print(
        json.dumps(
            {
                k: record.get(k)
                for k in (
                    "status",
                    "technical_status",
                    "content_status",
                    "task_id",
                    "video_path",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
