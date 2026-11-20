"""Sequential beat-level performance authoring, with explicit semantic gates."""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_reference_director import read, digest, check, approved, validate
from scripts.test_director_pipeline import author_stage
from src.content_factory.director_json import repair_failed_output

PROMPT = ROOT/'src/content_factory/prompts/reference_performance_beat_v1.md'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def upstream(run):
    layers = {}
    for stage in ('story', 'emotion', 'visual'):
        value = approved(run/stage)
        validate(stage, value, layers)
        layers[stage] = value
    return layers


def validate_beat(value, beat_id, layers):
    beat = next(b for b in layers['emotion']['beats'] if b['id'] == beat_id)
    check(value.get('id') == beat_id, 'One exact locked beat required')
    check(isinstance(value.get('risks'), list) and len(value['risks']) <= 1,
          'At most one observation risk per beat')
    validate('performance', {'beats': [value]},
             {'emotion': {'beats': [beat]}, 'visual': layers['visual']})


def source_binding(folder):
    return {'folder': str(folder.resolve()),
            'candidate_sha256': digest(folder/'candidate.json'),
            'review_sha256': digest(folder/'review.json')}


def context_binding(run, previous=None):
    return {'upstream': {s: source_binding(run/s) for s in ('story', 'emotion', 'visual')},
            'previous': source_binding(previous) if previous else None}


def verify_context(run, folder, previous=None):
    payload = json.loads(read(folder/'request.json')[1]['content'])
    check(payload.get('source_bindings') == context_binding(run, previous),
          'Beat was authored against different upstream or previous performance')


def compose(run):
    layers = upstream(run)
    selections = read(run/'performance_selection.json')
    values = []
    sources = []
    previous = None
    for beat in layers['story']['beats']:
        folder = run/'performance_beats'/selections[beat['id']]
        value = approved(folder)
        verify_context(run, folder, previous)
        validate_beat(value, beat['id'], layers)
        values.append(value)
        sources.append(source_binding(folder))
        previous = folder
    result = {'beats': [{k: v for k, v in value.items() if k != 'risks'} for value in values],
              'risks': [risk for value in values for risk in value['risks']]}
    validate('performance', result, layers)
    return result, {'recipe': 'approved_performance_beats/v1', 'sources': sources}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--adopt-run')
    parser.add_argument('--beat', choices=['B01', 'B02', 'B03', 'B04'])
    parser.add_argument('--attempt', default='first')
    parser.add_argument('--revision')
    parser.add_argument('--feedback')
    parser.add_argument('--assemble', action='store_true')
    args = parser.parse_args()
    run = Path(args.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    binding = {name: digest(path) for name, path in {
        'runner': Path(__file__), 'prompt': PROMPT,
        'validator': ROOT/'scripts/run_reference_director.py',
        'author': ROOT/'scripts/test_director_pipeline.py',
        'syntax': ROOT/'src/content_factory/director_json.py'}.items()}
    binding.update(model='MiniMax-M3', thinking='disabled', temperature=0.5, max_tokens=8192)
    protocol = run/'beat_protocol.json'
    if protocol.exists():
        check(read(protocol) == binding, 'Beat protocol changed; use a new run')
    else:
        save(protocol, binding)
    if args.adopt_run:
        source = Path(args.adopt_run).resolve()
        selection = read(source/'stage_selection.json')
        check(not any((run/s).exists() for s in ('story', 'emotion', 'visual')), 'Cannot overwrite upstream')
        layers = {}
        for stage in ('story', 'emotion', 'visual'):
            origin = source/selection.get(stage, stage)
            value = approved(origin)
            validate(stage, value, layers)
            layers[stage] = value
            shutil.copytree(origin, run/stage)
            save(run/stage/'origin.json', {'path': str(origin),
                 'candidate_sha256': digest(origin/'candidate.json'),
                 'review_sha256': digest(origin/'review.json'), 'new_model_calls': 0})
        save(run/'stage_selection.json', {s: s for s in ('story', 'emotion', 'visual')})
    layers = upstream(run)
    if args.assemble:
        result, provenance = compose(run)
        folder = run/'performance'
        folder.mkdir(exist_ok=False)
        save(folder/'candidate.json', result)
        save(folder/'assembly.json', provenance)
        save(folder/'validation.json', {'status': 'structure_valid_semantics_pending', 'media_approved': False})
        selection = read(run/'stage_selection.json')
        selection['performance'] = 'performance'
        save(run/'stage_selection.json', selection)
        print('Assembled; full cross-beat semantic review still required')
        return
    check(bool(args.beat), 'Specify a beat or --assemble')
    check(args.attempt.replace('_', '').isalnum(), 'Invalid attempt')
    story = next(b for b in layers['story']['beats'] if b['id'] == args.beat)
    index = layers['story']['beats'].index(story)
    selection_file = run/'performance_selection.json'
    selection = read(selection_file) if selection_file.exists() else {}
    prior = []
    previous = None
    for earlier in layers['story']['beats'][:index]:
        check(earlier['id'] in selection, 'Previous beat must be authored and reviewed first')
        origin = run/'performance_beats'/selection[earlier['id']]
        value = approved(origin)
        verify_context(run, origin, previous)
        validate_beat(value, earlier['id'], layers)
        prior.append(value)
        previous = origin
    payload = {'story': layers['story'], 'current_beat': story,
               'current_emotion': layers['emotion']['beats'][index],
               'space': layers['visual']['space'],
               'current_shots': [s for s in layers['visual']['shots'] if s['beat_id'] == args.beat],
               'previous_approved_performance': prior[-1] if prior else None,
               'opening_positions': prior[-1]['end_positions'] if prior else layers['visual']['space']['opening_positions'],
               'source_bindings': context_binding(run, previous)}
    if args.feedback:
        payload['review_feedback'] = args.feedback
    if args.revision:
        check(bool(args.feedback), 'A revision needs feedback')
        origin = Path(args.revision).resolve()
        payload['revision'] = {'source': str(origin), 'sha256': digest(origin), 'value': read(origin)}
    root = run/'performance_beats'
    root.mkdir(exist_ok=True)
    name = args.beat if args.attempt == 'first' else args.beat+'_'+args.attempt
    folder = root/name
    check(not folder.exists(), 'Attempt already exists; inspect before retrying')
    selection[args.beat] = name
    save(selection_file, selection)
    try:
        value = author_stage(folder, PROMPT.read_text(encoding='utf-8'), payload,
                             'reference_performance_'+args.beat, thinking='disabled',
                             temperature=0.5, max_tokens=8192)
    except Exception:
        if not (folder/'raw.txt').exists() or not (folder/'response.json').exists():
            raise
        value = repair_failed_output(folder)
    try:
        validate_beat(value, args.beat, layers)
        status = {'status': 'structure_valid_semantics_pending', 'media_approved': False}
    except Exception as exc:
        status = {'status': 'structure_failed', 'error': str(exc), 'media_approved': False}
    save(folder/'validation.json', status)
    print(json.dumps(status))


if __name__ == '__main__':
    main()
