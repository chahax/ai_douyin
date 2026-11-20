"""Prepare, submit once, or query only the authorized S02 continuation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory.assistant_seedance_s02 import execute
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('prepare', 'submit', 'query'))
    args = parser.parse_args()
    config = SeedanceConfig.from_env('ark_api', require_key=args.operation != 'prepare')
    with SeedanceClient(config, record_calls=args.operation != 'prepare') as client:
        print(json.dumps(execute(args.operation, client), ensure_ascii=False))


if __name__ == '__main__':
    main()
