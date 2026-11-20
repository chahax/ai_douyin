"""Prepare one library-bound opening photo and collect only its original native ID.

The opening composition is separate from the video's complete cast reference set.
This helper never changes the library, starts services, or retries unknown POSTs.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_image_jobs_v3 as jobs

PROJECT = Path(__file__).resolve().parents[1]
RUN = PROJECT / 'data/video_generation/h3_library_bound_minute_20261112_v1'
JOB = RUN / 'initial_scene/job'
SPEC = RUN / 'initial_scene/SPEC.json'
JOB_ID = RUN.name


def bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=jobs.file_sha(path))


def check(value):
    if bind(value['path']) != value:
        raise jobs.JobIntegrityError('initial_scene_bound_file_changed')
    return Path(value['path'])


def specification():
    spec = jobs._read(SPEC)
    if spec.get('schema') != 'library_initial_scene/v1':
        raise ValueError('library_initial_scene_schema_required')
    for field in ('authorization', 'binding_index', 'source_case'):
        check(spec[field])
    refs = spec['references']
    if not refs or len(refs) > 9 or len({r['input_name'] for r in refs}) != len(refs):
        raise ValueError('explicit_unique_library_references_required')
    kinds = set()
    index = jobs._read(check(spec['binding_index']))
    available = [r for group in ('characters', 'places')
                 for entry in index[group].values() for r in entry['images'].values()]
    source = jobs._read(check(spec['source_case']))['shots'][0]
    opening_actors = set(source['camera_beats'][0]['actors'])
    actual_actors = set()
    for ref in refs:
        image = check(ref['image'])
        record = jobs._read(check(ref['registry_record']))
        if (image.parent != PROJECT / 'data/serial_story_assets'
                or record['asset_id'] != ref['asset_id']
                or record['version'] != ref['version']
                or record['sha256'] != ref['image']['sha256']
                or record['file'] != image.name
                or record['entity_id'] != ref['entity_id']):
            raise ValueError('initial_reference_must_match_global_library_record')
        if not any(all(ref[k] == item[k] for k in ('asset_id', 'version', 'entity_id', 'image'))
                   for item in available):
            raise ValueError('initial_reference_not_in_project_binding')
        if record['kind'] == 'character':
            actual_actors.add(record['entity_id'])
        kinds.add(record['kind'])
    if actual_actors != opening_actors:
        raise ValueError('all_and_only_opening_actors_need_initial_identity_references')
    if kinds != {'character', 'place'} or not spec.get('prompt', '').strip():
        raise ValueError('character_place_and_opening_prompt_required')
    if spec.get('width') != 736 or spec.get('height') != 1312 or spec.get('steps') != 4:
        raise ValueError('initial_scene_profile_changed')
    return spec


def request():
    specification()
    return dict(spec=bind(SPEC), native_plan=bind(JOB / 'PLAN.json'),
                graph=bind(JOB / 'workflow_api.json'),
                code=[bind(__file__), bind(jobs.__file__)],
                publication=False, unknown_replay=False)


def prepare():
    spec = specification()
    config = jobs.Config(**spec['image_config'])
    refs = [dict(input_name=r['input_name']) for r in spec['references']]
    graph = jobs.build_graph([dict(id='initial', prompt=spec['prompt'],
                                   seed=spec['seed'], references=refs)],
                             'visual_assets_v3/' + JOB_ID,
                             width=736, height=1312, steps=4)
    inputs = [dict(path=r['image']['path'], sha256=r['image']['sha256'],
                   input_name=r['input_name']) for r in spec['references']]
    result = jobs.prepare_job(JOB, graph, config, inputs, JOB_ID)
    jobs._freeze(RUN / 'initial_scene/LAUNCH_REQUEST.json', request())
    return result


def collect():
    req = request()
    result = jobs.collect(JOB)
    if len(result['images']) != 1 or result['images'][0]['dimensions'] != [736, 1312]:
        raise ValueError('one_correct_native_initial_image_required')
    image = result['images'][0]
    value = dict(schema='library_initial_guide/v2', image=bind(image['path']),
                 source_image=bind(image['source_path']),
                 native_output=dict(node_id=image['save_node'], index=0,
                                    source_path=image['source_path']),
                 native_prompt_id=result['prompt_id'],
                 generation_records={name: bind(JOB / (name.upper() + '.json'))
                                     for name in ('plan', 'request', 'history', 'result')},
                 initial_request=req, completion_known=True, outcome_unknown=False,
                 production_approved=False)
    jobs._freeze(RUN / 'INITIAL_GUIDE.json', value)
    return value


def execute(max_seconds=10800, poll_seconds=30):
    req = request()
    approval = jobs._read(RUN / 'initial_scene/ROOT_LAUNCH_IMAGE.json')
    if approval.get('request') != req or not approval.get('approved_by'):
        raise ValueError('actual_initial_scene_launch_approval_required')
    start = time.monotonic()
    state = jobs.status(JOB)
    if state['status'] == 'prepared':
        state = jobs.submit(JOB)
        pid = state.get('prompt_id')
        if pid:
            line = 'initial_scene ' + pid + '\n'
            ledger = RUN / 'job_ids.txt'
            if not ledger.exists() or line not in ledger.read_text(encoding='utf-8'):
                with ledger.open('a', encoding='utf-8') as output:
                    output.write(line)
            with (RUN / 'LOG.md').open('a', encoding='utf-8') as output:
                output.write('- SUBMIT initial_scene ' + pid + '\n')
    while True:
        if state['status'] in ('saved', 'native_complete'):
            return collect()
        if state['status'] not in ('submitted', 'running'):
            return dict(status='preserved_without_resubmit', original_state=state)
        if time.monotonic() - start > max_seconds:
            return dict(status='wait_window_elapsed_original_id_preserved', original_state=state)
        time.sleep(poll_seconds)
        state = jobs.poll(JOB)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'status', 'execute', 'collect'])
    parser.add_argument('--poll-seconds', type=int, default=30)
    parser.add_argument('--max-seconds', type=int, default=10800)
    args = parser.parse_args()
    if args.action == 'prepare':
        value = prepare()
    elif args.action == 'status':
        value = jobs.status(JOB)
    elif args.action == 'collect':
        value = collect()
    else:
        value = execute(args.max_seconds, args.poll_seconds)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
