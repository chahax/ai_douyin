"""One project M3 text call to ground unchanged S01 against actual failed evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.ark_opening_frame import _bytes, _inside, _now, _sha, _write
from src.content_factory.execution_grounding import (
    MODEL, RUN_SCHEMA, SCHEMA, FOCUS_NAME, _identity, build_messages, collect_grounding_source, validate_grounding_value)
from src.content_factory.seedance_client import SeedanceConfig
from src.shared.llm_client import LLMClient
from src.trend_intelligence.production_revision import parse_unique_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir', 'first-frame', 'failed-run', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--previous-grounding-run')
    parser.add_argument('--feedback-file')
    parser.add_argument('--focus', choices=[FOCUS_NAME])
    args = parser.parse_args(argv)
    if bool(args.previous_grounding_run) != bool(args.feedback_file):
        raise ValueError('Provide both previous-grounding-run and feedback-file')
    folder = Path(args.run_dir).resolve()
    output = _inside(args.output_dir, folder)
    if output == folder:
        raise ValueError('Use a new grounding output directory inside this run')
    revision_args = {'previous_grounding_run': args.previous_grounding_run, 'feedback_file': args.feedback_file,
                     'focus': args.focus}
    source = collect_grounding_source(folder, args.first_frame, args.failed_run,
                                     SeedanceConfig.from_env('ark_api'), **revision_args)
    messages = build_messages(source)
    output.mkdir(parents=True, exist_ok=False)
    request_sha = _write(output / 'request.json', messages, exclusive=True)
    source_sha = _write(output / 'source.json', source, exclusive=True)
    reservation = Path(source['campaign']['path']).parent / 'execution_grounding_reservations' / f'{request_sha}.json'
    run = {'schema': RUN_SCHEMA, 'status': 'prepared', 'started_at': _now().isoformat(),
        'model': MODEL, 'model_calls': 0, 'source_sha256': source_sha, 'request_sha256': request_sha,
        'reservation_path': str(reservation)}
    _write(output / 'run.json', run)
    received = False
    metadata = {}
    try:
        client = LLMClient(model=MODEL, extra_body={'thinking': {'type': 'disabled'}, 'reasoning_split': True},
            max_retries=0, max_tokens=2200, preserve_invalid_json=True, timeout_seconds=180)
        if client.provider_name == 'mock':
            raise ValueError('A real configured project model is required')
        reservation.parent.mkdir(parents=True, exist_ok=True)
        _write(reservation, {'schema': RUN_SCHEMA, 'output_dir': str(output),
            'request_sha256': request_sha, 'source_sha256': source_sha, 'model': MODEL, 'model_calls': 1}, exclusive=True)
        run.update(status='outcome_unknown', model_calls=1)
        _write(output / 'run.json', run)
        try:
            raw = client.chat_completion_tracked(messages, caller='pre_video_execution_grounding_revision',
                temperature=0.2, json_mode=True, use_cache=False)
        finally:
            metadata = getattr(client.provider, 'last_response_metadata', {})
            run['metadata_sha256'] = _write(output / 'response_metadata.json', metadata)
        run['output_sha256'] = _write(output / 'model_output.json', raw)
        received = raw is not None or bool(metadata.get('finish_reason'))
        value = validate_grounding_value(parse_unique_json(raw), source)
        # Preserve any concurrent upstream change as a failed candidate, never
        # overwrite the original request or transplant output to a new source.
        if collect_grounding_source(folder, args.first_frame, args.failed_run,
                                    SeedanceConfig.from_env('ark_api'), **revision_args) != source:
            raise ValueError('Grounding source changed while awaiting the model response')
    except Exception as exc:
        run.update(status=('failed_model_output' if received else 'outcome_unknown' if run['model_calls'] else 'preflight_rejected'),
            error_type=type(exc).__name__, finished_at=_now().isoformat())
        if metadata.get('error_type'):
            run['provider_error_type'] = metadata['error_type']
        _write(output / 'run.json', run)
        raise
    plan = {'schema': SCHEMA, 'run_dir': str(folder), 'model': MODEL, 'model_calls': 1,
        'source': source, **value, 'request': _identity(output / 'request.json'),
        'model_output': _identity(output / 'model_output.json'),
        'response_metadata': _identity(output / 'response_metadata.json'),
        'text_review': 'pending', 'media_review': 'pending'}
    run['candidate_sha256'] = _write(output / 'grounding_plan.json', plan, exclusive=True)
    run.update(status='candidate_pending_independent_review', finished_at=_now().isoformat())
    _write(output / 'run.json', run)
    print(json.dumps({'status': run['status'], 'plan': str(output / 'grounding_plan.json'),
                     'sha256': run['candidate_sha256'], 'model_calls': 1}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
