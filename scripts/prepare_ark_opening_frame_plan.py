"""Prepare the actual reviewed S01 static image plan; no model or media generation."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_factory.opening_frame_plan import prepare_opening_frame_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    run, output = Path(args.run_dir).resolve(), Path(args.output).resolve()
    run.relative_to(ROOT / 'data/video_generation')
    plan = prepare_opening_frame_plan(run, output)
    print(json.dumps({'plan': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'model_calls': 0, 'media_generation': False, 'text_review': 'pending', 'media_review': 'pending',
        'source_script_sha256': plan['script_sha256']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
