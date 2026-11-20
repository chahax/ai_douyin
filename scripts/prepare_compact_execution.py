"""Prepare an explicit S01 prompt projection from a reviewed opening; no API calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.compact_execution import prepare_compact_execution
from src.content_factory.seedance_client import SeedanceConfig


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--first-frame', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--grounding-plan', help='显式采用一次项目模型定位说明并生成 compact_execution/v2')
    args = parser.parse_args(argv)
    folder, output = Path(args.run_dir).resolve(), Path(args.output).resolve()
    folder.relative_to(ROOT / 'data/video_generation')
    plan = prepare_compact_execution(folder, Path(args.first_frame), output,
                                     SeedanceConfig.from_env('ark_api'),
                                     grounding_plan=Path(args.grounding_plan) if args.grounding_plan else None)
    print(json.dumps({'plan': str(output), 'profile': plan['profile'],
        'original_prompt_sha256': plan['original_prompt_sha256'], 'prompt_sha256': plan['prompt_sha256'],
        'prompt_characters': len(plan['prompt']), 'text_review': 'pending',
        'model_calls': 0, 'media_generation': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
