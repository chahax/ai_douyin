"""Explicit preparation or one controller-driven action; no automatic retry."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.content_factory import h3_repair_generation_adapter_v1 as adapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'status', 'launch-request', 'executor-submit', 'executor-collect'))
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--authorization', type=Path)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    run, recipe_binding = args.run.resolve(), adapter.bind(args.recipe.resolve())
    recipe = adapter.recipe_value(recipe_binding)
    api = adapter.for_run(run, recipe_binding)
    if args.action == 'prepare':
        if not args.config or not args.authorization:
            parser.error('prepare requires --config and --authorization')
        result = api.prepare(run, recipe['offline_output'], adapter.read(args.config.resolve()),
            prompt_profiles=recipe['active_profiles'], authorization=adapter.bind(args.authorization.resolve()),
            code_files=[__file__])
    elif args.action == 'status':
        result = api.status(run)
    elif args.action == 'launch-request':
        result = api.launch_request(run)
    else:
        if not args.request:
            parser.error('executor action requires an exact --request from the controller')
        executor = adapter.GenerationExecutor(run, recipe_binding)
        request = adapter.read(args.request.resolve())
        result = getattr(executor, 'submit' if args.action == 'executor-submit' else 'collect')(request)
    if args.output:
        receipt = adapter.freeze(args.output.resolve(), result)
        print(json.dumps(dict(status=result.get('status', 'request_saved'), receipt=receipt), ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
