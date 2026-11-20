"""Detect an opening-frame face; crop is a separate explicit CPU-only action."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_continuity_input_v33 as core
from src.content_factory import visual_opening_frame as opening
from src.content_factory import visual_opening_crop as cropper

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = PROJECT / 'data/models/yunet/face_detection_yunet_2023mar.onnx'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['detect', 'crop'])
    p.add_argument('--source', type=Path)
    p.add_argument('--source-case', type=Path)
    p.add_argument('--shot', default='S02')
    p.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    p.add_argument('--detection', type=Path)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    if args.action == 'detect':
        if args.source is None or args.source_case is None:
            p.error('detect requires --source and --source-case')
        source_binding = core.binding(args.source_case)
        rows = [row for row in core._entries(source_binding) if row['shot_id'] == args.shot]
        if len(rows) != 1:
            raise ValueError('unique_source_shot_required')
        core.validate_entry(rows[0])
        value = cropper.detect(args.source, opening.contract(rows[0]), args.model,
                               contract_binding=source_binding)
        cropper.freeze(args.out / 'DETECTION.json', value)
    else:
        if args.detection is None:
            p.error('crop requires --detection')
        value = cropper.crop(args.detection, args.out)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value.get('status') != 'unresolved' else 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
