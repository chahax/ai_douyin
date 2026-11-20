from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from src.content_factory.story_video import audit_story_video_controls

    parser = argparse.ArgumentParser(description="Audit every controlled shot in a story manifest.")
    parser.add_argument("manifest", help="Path to a story_video/v1 JSON manifest")
    parser.add_argument("--output-dir", required=True, help="Directory for scene control reports")
    args = parser.parse_args()

    reports = audit_story_video_controls(args.manifest, args.output_dir)
    print(
        json.dumps(
            {
                "passed": all(report.passed for report in reports),
                "scenes": [
                    {
                        "path": report.path,
                        "mode": report.mode,
                        "passed": report.passed,
                        "strict_gate_passed": report.metadata.get(
                            "strict_gate_passed",
                            report.passed,
                        ),
                        "user_override": report.metadata.get("user_override"),
                    }
                    for report in reports
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(report.passed for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
