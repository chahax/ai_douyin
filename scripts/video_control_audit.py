from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.video_control_gate import VideoControlGate

    parser = argparse.ArgumentParser(description="Audit AI video motion and lighting control.")
    parser.add_argument("manifest", help="Path to a video_control/v1 JSON manifest")
    parser.add_argument("--output", help="Optional report JSON path")
    args = parser.parse_args()

    report = VideoControlGate().inspect_manifest(args.manifest, args.output)
    print(
        json.dumps(
            {
                "path": report.path,
                "mode": report.mode,
                "passed": report.passed,
                "issues": [asdict_issue(issue) for issue in report.issues],
                "metadata": report.metadata,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.passed else 2


def asdict_issue(issue: object) -> dict[str, object]:
    return {
        "code": getattr(issue, "code"),
        "message": getattr(issue, "message"),
        "severity": getattr(issue, "severity"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
