"""Explicit CPU preparation and root-controlled image lifecycle for v36."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_scene_performance_stills_v36 as scene


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'status', 'collect-known', 'submit-next', 'budget'))
    parser.add_argument('--run', required=True)
    parser.add_argument('--spec')
    args = parser.parse_args()
    if args.action == 'prepare':
        if not args.spec:
            parser.error('--spec required for prepare')
        value = scene.prepare(args.spec, args.run)
    else:
        value = getattr(scene, args.action.replace('-', '_'))(args.run)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
