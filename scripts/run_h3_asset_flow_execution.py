"""Single-shot explicit execution adapter; never automatically resubmits."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import h3_asset_flow_execution_v1 as flow


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'status', 'launch-request', 'submit', 'collect'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--draft', type=Path); parser.add_argument('--config', type=Path)
    parser.add_argument('--prompt-profiles', type=Path); parser.add_argument('--prompt-id')
    parser.add_argument('--authorization', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        if args.draft is None or args.config is None:parser.error('prepare requires --draft and --config')
        value = flow.prepare(args.run, args.draft, flow.read(args.config),
            prompt_profiles=flow.bind(args.prompt_profiles) if args.prompt_profiles else None,
            authorization=flow.bind(args.authorization) if args.authorization else None, code_files=[__file__])
    elif args.action == 'launch-request':
        flow.launch_request(args.run)
        value = dict(status='Root_approval_required', request=flow.bind(args.run / 'LAUNCH_REQUEST.json'))
    elif args.action == 'submit':value = flow.submit(args.run)
    elif args.action == 'collect':value = flow.collect_known(args.run, args.prompt_id)
    else:value = flow.status(args.run)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
