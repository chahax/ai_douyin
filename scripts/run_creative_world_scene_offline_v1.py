"""No-network world/scene preview or static synthetic-response integration."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.creative_world_scene_text_driver_v1 import run_mock
from scripts.creative_resume_dispatch_v3 import read, write, digest
from src.content_factory import creative_goal_context_workflow_v28 as workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "mock"))
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(); scenario = read(args.scenario)
    if args.action == "mock": result = run_mock(scenario)
    else:
        result = {"schema": workflow.VERSION + "/offline_preview", "provider_calls": 0, "production_claims": 0,
            "first_request": workflow.prepare_goal_request(scenario["inputs"], scenario["profile"]), "production_dispatch_eligible": False}
    write(args.output, result, True)
    print(json.dumps({"path": str(Path(args.output).resolve()), "canonical_sha256": digest(result)}, ensure_ascii=False))


if __name__ == "__main__": main()
