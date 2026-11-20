import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_multiview_continuity_stills_v37 as scene


def main():
    parser = argparse.ArgumentParser(description='v37 CPU preparation and root-controlled original-ID image lifecycle')
    parser.add_argument('action', choices=('prepare', 'prepare-shot', 'status', 'collect-known', 'submit-next', 'budget'))
    parser.add_argument('--run', required=True)
    parser.add_argument('--spec')
    parser.add_argument('--shot')
    parser.add_argument('--prior-video-result')
    args = parser.parse_args()
    if args.action=='prepare':
        if not args.spec:
            parser.error('--spec required')
        value = scene.prepare(args.spec, args.run)
    elif args.action=='prepare-shot':
        if not args.shot:
            parser.error('--shot required')
        prior = scene.bind(args.prior_video_result) if args.prior_video_result else None
        value = scene.prepare_shot(args.run, args.shot, prior)
    else:
        value = getattr(scene, args.action.replace('-', '_'))(args.run)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__=='__main__':
    main()
