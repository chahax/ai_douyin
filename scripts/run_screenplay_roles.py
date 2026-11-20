"""Explicit experimental role pipeline and identical-input model comparison."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory.screenplay_role_runner_v5 import prepare, execute, benchmark, read, local_routes, hybrid_routes, report, record_evaluation
from src.content_factory.screenplay_roles_v5 import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'execute', 'benchmark', 'routes', 'report', 'evaluate'])
    parser.add_argument('--run')
    parser.add_argument('--source-request')
    parser.add_argument('--chapters', nargs='+', type=int)
    parser.add_argument('--episode')
    parser.add_argument('--routes')
    parser.add_argument('--model', default='qwen3.5:9b-q4_K_M')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11435')
    parser.add_argument('--user-statement')
    parser.add_argument('--target-seconds', type=int, default=90)
    parser.add_argument('--reference-run')
    parser.add_argument('--call-number', type=int)
    parser.add_argument('--runs', nargs='+')
    parser.add_argument('--allow-cloud', action='store_true', help='Explicit new cloud experiment scope; never reuses old campaign budget')
    parser.add_argument('--profile', choices=['local', 'hybrid'], default='local')
    parser.add_argument('--evaluation')
    args = parser.parse_args()
    routes = read(args.routes) if args.routes else (hybrid_routes() if args.profile == 'hybrid' else local_routes(args.model, args.endpoint))
    if args.action == 'routes':
        result = routes
    elif args.action == 'report':
        if not args.runs:
            parser.error('report needs --runs')
        result = report(args.runs)
    elif not args.run:
        parser.error('--run required')
    elif args.action == 'execute':
        result = execute(args.run)
    elif args.action == 'evaluate':
        if not args.call_number or not args.evaluation:
            parser.error('evaluate needs call-number and evaluation')
        result = record_evaluation(args.run, args.call_number, read(args.evaluation))
    elif args.action == 'prepare':
        if not all((args.source_request, args.episode, args.user_statement)):
            parser.error('prepare needs source-request, episode and user-statement')
        request = read(args.source_request)
        context = json.loads(next(m['content'] for m in request['messages'] if m['role'] == 'user'))
        chapters = context['selected_original_chapters']
        if args.chapters:
            if not set(args.chapters) <= {c['index'] for c in chapters}:
                parser.error('selected chapters must exist in frozen source')
            chapters = [c for c in chapters if c['index'] in args.chapters]
        result = prepare(args.run, chapters, args.episode, routes, user_statement=args.user_statement,
                         target_seconds=args.target_seconds, cloud_authorized=args.allow_cloud,
                         provenance={'source_request': str(Path(args.source_request).resolve()),
                                     'source_request_sha256': digest(request),
                                     'original_source_sha256': request.get('source_sha256'),
                                     'source_acquisition': 'reuse frozen source; no acquisition or legacy campaign replay'})
    else:
        if not all((args.reference_run, args.call_number, args.user_statement)):
            parser.error('benchmark needs reference-run, call-number and user-statement')
        result = benchmark(args.reference_run, args.call_number, args.run, routes, user_statement=args.user_statement,
                           cloud_authorized=args.allow_cloud)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
