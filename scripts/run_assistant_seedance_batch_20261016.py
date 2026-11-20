"""Prepare S03, then start/resume only the frozen ten-segment Seedance batch."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory.assistant_seedance_batch import execute
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('prepare', 'start'))
    parser.add_argument('--wait-timeout', type=float, default=1800)
    parser.add_argument('--poll-seconds', type=float, default=20)
    args = parser.parse_args()
    config = SeedanceConfig.from_env('ark_api', require_key=args.operation != 'prepare')
    with SeedanceClient(config, record_calls=args.operation != 'prepare') as client:
        print(json.dumps(execute(args.operation, client, wait_timeout=args.wait_timeout, poll_seconds=args.poll_seconds), ensure_ascii=False))


if __name__ == '__main__':
    main()
