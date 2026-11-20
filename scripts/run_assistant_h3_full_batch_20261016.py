"""Exact authorized H3 S02–S12 batch; prepare/status do not dispatch media."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import assistant_h3_full_batch as batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'status', 'start'])
    parser.add_argument('--wait-timeout', type=float, default=21600)
    parser.add_argument('--poll-seconds', type=float, default=30)
    args = parser.parse_args()
    temporary = batch.OUT/'runtime/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    for key in ('TEMP', 'TMP', 'TMPDIR'):
        os.environ[key] = str(temporary)
    if args.operation == 'prepare':
        result = batch.prepare()
    elif args.operation == 'status':
        result = batch.status()
    else:
        try:
            result = batch.run(timeout=args.wait_timeout, poll=args.poll_seconds)
        except Exception as exc:
            batch.durable(batch.OUT/'BATCH_STATUS.json', dict(at=batch.now(),status='stopped',
                          error_type=type(exc).__name__,error=str(exc),automatic_retry=False))
            raise
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
