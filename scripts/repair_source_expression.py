"""Perform one allowlisted source-expression text revision; never process media."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.trend_intelligence.content_analysis.targeted_revision import repair_source_expression


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("qwen", "frame-manifest", "transcript", "review", "feedback", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--allow-path", action="append", required=True,
                        help="Existing synthesis JSON Pointer, e.g. /audio_expression/0/text; repeat as needed")
    parser.add_argument("--context-evidence-id", action="append",
                        help="Explicit whole evidence rows to supply; repeat for every cited ID and needed ASR neighbor. Default: full evidence, never truncated.")
    args = parser.parse_args()
    trace = repair_source_expression(args.qwen, args.frame_manifest, args.transcript, args.review,
                                     args.feedback, args.output, args.allow_path,
                                     context_evidence_ids=args.context_evidence_id)
    print(f"Saved targeted text candidate: {trace['output_path']}; independent semantic review is still required.")


if __name__ == "__main__":
    main()
