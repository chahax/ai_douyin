"""Prepare or submit one original Ark S01 image; never submit video."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_factory.ark_opening_frame import (
    prepare_opening_frame, submit_opening_frame, resume_opening_download, import_opening_frame,
)
from src.content_factory.seedance_client import SeedanceConfig


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'submit', 'resume-download', 'import-opening'))
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--run-dir')
    parser.add_argument('--plan')
    parser.add_argument('--model')
    parser.add_argument('--size')
    parser.add_argument('--source-run-dir')
    parser.add_argument('--source-image')
    args = parser.parse_args(argv)
    output = Path(args.output_dir).resolve()
    output.relative_to(ROOT / 'data/video_generation')
    config = SeedanceConfig.from_env('ark_api')
    if args.operation != 'import-opening' and (args.source_run_dir or args.source_image):
        parser.error('source-run-dir/source-image are import-opening only')
    if args.operation == 'prepare':
        if not all((args.run_dir, args.plan, args.model, args.size)):
            parser.error('prepare requires --run-dir --plan --model --size')
        run = Path(args.run_dir).resolve()
        run.relative_to(ROOT / 'data/video_generation')
        receipt = prepare_opening_frame(run, args.plan, output, config, model=args.model, size=args.size)
    elif args.operation == 'import-opening':
        if not all((args.run_dir, args.source_run_dir, args.source_image)) or any((args.plan, args.model, args.size)):
            parser.error('import-opening requires run-dir/source-run-dir/source-image/output-dir only')
        for value in (args.run_dir, args.source_run_dir, args.source_image):
            Path(value).resolve().relative_to(ROOT / 'data/video_generation')
        receipt = import_opening_frame(args.run_dir, args.source_run_dir, args.source_image, output, config)
    else:
        if any((args.run_dir, args.plan, args.model, args.size)):
            parser.error('submit/resume-download use only the already prepared --output-dir')
        receipt = (submit_opening_frame(output, config) if args.operation == 'submit'
                   else resume_opening_download(output, config))
    print(json.dumps({'status': receipt['status'], 'output_dir': str(output),
        'image': receipt['image'], 'model': receipt.get('model'), 'api_calls': receipt['api_calls'],
        'image_sha256': receipt.get('image_sha256'), 'media_review': receipt['media_review'],
        'video_generation_submitted': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Provider errors can contain signed URLs; the durable receipt is the audit.
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'message': 'Inspect the preserved receipt; do not automatically resubmit.'}))
        raise SystemExit(1)
