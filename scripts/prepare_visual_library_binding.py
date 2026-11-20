"""Prepare source-bound feature cards from exact existing registry selections."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_asset_feature_cards_v1 as features

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=PROJECT / 'data/serial_story_assets')
    parser.add_argument('--book-id', default=features.BOOK_ID)
    parser.add_argument('--cast-plan', type=Path, default=PROJECT / 'data/image_model_trials/20261106_novel_cast_turnaround/CAST_PLAN.json')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--selection', type=Path)
    source.add_argument('--default-novel-test', action='store_true')
    args = parser.parse_args()
    selection = features.DEFAULT_SELECTION if args.default_novel_test else features.read(args.selection)
    result = features.prepare_binding(args.output, library=args.library, book_id=args.book_id,
        cast_plan=args.cast_plan, selection=selection)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'binding_prepared' else 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
