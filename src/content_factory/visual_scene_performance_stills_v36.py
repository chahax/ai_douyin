"""Photo-based performance anchors, independent of the frozen 3-D stage route.

The photographed room is a real positive-conditioning reference, not prose-only
context.  Output validation is technical; the completed film belongs to the user
for content review.  This module never restarts services or retries unknown POSTs.
"""
from pathlib import Path
import copy
import json

from PIL import Image

from . import visual_image_jobs_v3 as jobs

VERSION = 'scene_performance_stills/v36'
SPEC_SCHEMA = 'scene_performance_stills_spec/v36'
CAST = ('su_mo', 'ye_nan', 'ye_xijue')
SHOTS = ('S01', 'S02', 'S03', 'S04')
REFERENCE_POLICY = 'same_photographic_room_mother_and_three_identities/v36'


def _binding(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=jobs.file_sha(path))


def _check_binding(binding):
    if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
        raise jobs.JobIntegrityError('exact_file_binding_required')
    actual = _binding(binding['path'])
    if actual != binding:
        raise jobs.JobIntegrityError('bound_file_changed:' + str(binding['path']))
    return actual


def source_states():
    """Only the four opening instants; the video owns subsequent performance."""
    asleep = dict(
        su_mo=dict(posture='lying_on_bed', eyes='closed', gaze='resting', hands='empty'),
        ye_nan=dict(posture='standing_beside_younger_brother', eyes='open', gaze='ye_xijue', hands='empty'),
        ye_xijue=dict(posture='standing_beside_bed', eyes='open', gaze='ye_nan', hands='holding_single_bread_bag'))
    second = copy.deepcopy(asleep)
    second['ye_xijue']['gaze'] = 'su_mo'
    awake = copy.deepcopy(asleep)
    awake['su_mo'].update(eyes='open', gaze='ye_xijue_and_bread')
    awake['ye_xijue'].update(gaze='su_mo', hands='offering_single_bread_bag')
    standing = dict(
        su_mo=dict(posture='standing_beside_same_bed', eyes='open', gaze='bread_and_children', hands='holding_single_bread_bag'),
        ye_nan=dict(posture='standing_close_to_and_protecting_younger_brother', eyes='open', gaze='ye_xijue', hands='empty'),
        ye_xijue=dict(posture='standing_next_to_older_brother', eyes='open', gaze='su_mo', hands='empty'))
    return {
        'S01': dict(actors=asleep, bread_owner='ye_xijue', instant='before_the_first_child_line'),
        'S02': dict(actors=second, bread_owner='ye_xijue', instant='father_eyes_closed_before_inner_voice'),
        'S03': dict(actors=awake, bread_owner='ye_xijue', instant='father_awake_before_accepting_the_offered_bread'),
        'S04': dict(actors=standing, bread_owner='su_mo', instant='father_standing_with_bread_brothers_together')}


def performance_prompt(shot_id):
    common = (
        'Edit Image 1, the existing live-action photograph, into one opening instant of a Chinese family drama. '
        'Image 1 is the authoritative same photographed room and composition: preserve its cracked grey walls, '
        'window placements and frames, worn cement floor, single wooden bed with grey bedding, '
        'and the small wooden table in their existing relative positions. Preserve the photographed room pixels '
        'and natural daylight as closely as the edit permits. Make the actor pose and gaze changes described below '
        'within this same photograph. Images 2, 3 and 4 supply the identities and clothing of Su Mo, '
        'the older boy Ye Nan, and the younger boy Ye Xijue respectively. The father wears the dark jacket '
        'and grey shirt, the older boy the grey polo, and the younger boy the worn beige T-shirt and grey shorts. '
        'Stage a candid story moment: their attention belongs to each other and to the bread. '
        'The portrait references identify the performers; the performance gaze follows the story objects. '
        'Keep natural complete head-to-body connections and the visible bodily support on the bed or floor. '
        'There is one clear plastic bag containing the bread. '
    )
    changes = {
        'S01': 'Su Mo lies naturally supported on the same bed, eyes closed, resting, both hands empty. '
               'Ye Xijue stands beside the bed holding the bread bag with both hands, looking up toward Ye Nan. '
               'Ye Nan stands close beside his younger brother and turns his eyes and head toward the younger boy, concerned.',
        'S02': 'Su Mo remains lying naturally supported on the same bed with his eyes closed and hands empty. '
               'Ye Xijue holds the bread bag and turns his eyes and head toward his father. Ye Nan looks down toward his younger brother '
               'with a quiet worried expression. Their body positions continue this same bedside conversation.',
        'S03': 'Su Mo is awake but still naturally lying on the same bed. His eyes are open and his gaze meets '
               'Ye Xijue and the offered bread; his hands are still empty. Ye Xijue lifts the bread bag toward '
               'his father and looks at his father, retaining the bag in his own hands at this instant. '
               'Ye Nan stays beside his younger brother and watches the younger boy with concern.',
        'S04': 'Su Mo now stands beside the same bed, holding the single bread bag in front of his own chest '
               'where his hands and the bag are visible; he looks down at the bread and the children. '
               'Ye Nan stands close to Ye Xijue in a protective attitude, his attention on his younger brother. '
               'Ye Xijue stands beside his older brother with empty hands and looks toward their father. '
               'The boys remain in the same room at the same bedside.'}
    return common + changes[shot_id]


def make_spec(mother_photo, identities, image_config, authorization, source_case,
              *, mother_native_result, width=736, height=1312, steps=4):
    """Create explicit editable input; caller freezes the returned JSON before prepare."""
    if set(identities) != set(CAST):
        raise ValueError('three_named_identity_bindings_required')
    return dict(schema=SPEC_SCHEMA, mother_photo=_binding(mother_photo),
                mother_native_result=_binding(mother_native_result),
                identities={name: _binding(identities[name]) for name in CAST},
                image_config=_binding(image_config), authorization=_binding(authorization),
                source_case=_binding(source_case), reference_policy=REFERENCE_POLICY,
                width=width, height=height, steps=steps,
                review_policy='user_reviews_completed_film', semantic_generation_gates=False,
                shots=[dict(id=sid, prompt=performance_prompt(sid), source_state=source_states()[sid],
                            seed=36110901+i) for i, sid in enumerate(SHOTS)])


def _validate_spec(spec):
    if (spec.get('schema') != SPEC_SCHEMA or spec.get('reference_policy') != REFERENCE_POLICY
            or spec.get('semantic_generation_gates') is not False
            or spec.get('review_policy') != 'user_reviews_completed_film'):
        raise ValueError('scene_spec_policy_mismatch')
    if set(spec.get('identities', {})) != set(CAST):
        raise ValueError('exact_named_cast_required')
    shots = spec.get('shots', [])
    if [s.get('id') for s in shots] != list(SHOTS):
        raise ValueError('four_ordered_opening_images_required')
    for shot in shots:
        if not isinstance(shot.get('prompt'), str) or not shot['prompt'].strip():
            raise ValueError('opening_image_prompt_required')
        if (shot.get('source_state') != source_states()[shot['id']]
                or type(shot.get('seed')) is not int or not 0 <= shot['seed'] < 2**64):
            raise ValueError('source_opening_state_or_seed_changed')
    for name in ('width', 'height'):
        if type(spec.get(name)) is not int or spec[name] < 64 or spec[name] % 16:
            raise ValueError('invalid_dimensions')
    if type(spec.get('steps')) is not int or not 1 <= spec['steps'] <= 100:
        raise ValueError('invalid_steps')


def _source_bindings(spec):
    return [('mother_photo', spec['mother_photo'])] + [
        (name, spec['identities'][name]) for name in CAST]


def reference_graph_evidence(graph, sid, inputs):
    """Prove each exact photograph reaches the sampler's positive guider branch."""
    try:
        sample = graph[sid+'__sample']
        if sample['class_type'] != 'SamplerCustomAdvanced':
            raise KeyError('sampler')
        guider_link = sample['inputs']['guider']
        guider = graph[guider_link[0]]
        if guider['class_type'] != 'CFGGuider' or guider_link[1] != 0:
            raise KeyError('guider')
        link = guider['inputs']['positive']
        found = []
        seen = set()
        while True:
            if not isinstance(link, list) or len(link) != 2 or link[1] != 0 or link[0] in seen:
                raise KeyError('positive_link')
            seen.add(link[0])
            node = graph[link[0]]
            if node['class_type'] == 'CLIPTextEncode':
                break
            if node['class_type'] != 'ReferenceLatent':
                raise KeyError('positive_reference')
            latent = node['inputs']['latent']
            encode = graph[latent[0]]
            pixels = encode['inputs']['pixels']
            loader = graph[pixels[0]]
            if (latent[1] != 0 or encode['class_type'] != 'VAEEncode'
                    or pixels[1] != 0 or loader['class_type'] != 'LoadImage'):
                raise KeyError('actual_photographic_pixels_required')
            found.append(dict(load_node=pixels[0], encode_node=latent[0],
                              positive_reference_node=link[0], input_name=loader['inputs']['image']))
            link = node['inputs']['conditioning']
        found.reverse()
        if [r['input_name'] for r in found] != [r['input_name'] for r in inputs]:
            raise KeyError('ordered_photo_and_identity_ancestors')
        return dict(policy=REFERENCE_POLICY, positive_ancestry_verified=True,
                    mother_is_actual_positive_photographic_reference=True,
                    references=[dict(**r, role=inputs[i]['role'], sha256=inputs[i]['sha256'])
                                for i, r in enumerate(found)])
    except (KeyError, IndexError, TypeError) as exc:
        raise jobs.JobIntegrityError('positive_photographic_reference_chain_invalid') from exc


def prepare(spec_path, run, authorization=None):
    spec_path = Path(spec_path).resolve()
    spec = jobs._read(spec_path)
    _validate_spec(spec)
    if authorization is not None and authorization != spec['authorization']:
        raise ValueError('coordinator_authorization_mismatch')
    for binding in [spec['image_config'], spec['authorization'], spec['source_case'], spec['mother_native_result']]:
        _check_binding(binding)
    native_mother = jobs._read(spec['mother_native_result']['path'])
    if (native_mother.get('technical_status') != 'saved' or not native_mother.get('prompt_id')
            or not any(str(Path(im.get('path', '')).resolve()) == spec['mother_photo']['path']
                       and im.get('sha256') == spec['mother_photo']['sha256']
                       for im in native_mother.get('images', []))):
        raise jobs.JobIntegrityError('mother_must_match_actual_saved_native_result')
    auth = jobs._read(spec['authorization']['path'])
    if (auth.get('semantic_generation_gates') is not False
            or auth.get('review_policy') != 'user_reviews_completed_film'
            or auth.get('engineering_limits', {}).get('image_submissions', 0) < 4):
        raise ValueError('four_photo_edits_authorization_required')
    cfg = jobs.Config(**jobs._read(spec['image_config']['path'])).normalized()
    run = Path(run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    with jobs.run_lock(run):
        jobs._freeze(run/'SPEC.snapshot.json', spec)
        inputs = []
        for role, binding in _source_bindings(spec):
            _check_binding(binding)
            with Image.open(binding['path']) as im:
                im.verify()
            snapshot = run/'source_snapshots'/(role+Path(binding['path']).suffix.lower())
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not snapshot.exists():
                jobs._copy_new(binding['path'], snapshot)
            if jobs.file_sha(snapshot) != binding['sha256']:
                raise jobs.JobIntegrityError('snapshot_source_changed')
            # Digest-based namespace is independent of any external filename.
            name = 'scene_performance_v36/'+jobs.digest(spec)[:20]+'/'+snapshot.name
            inputs.append(dict(role=role, input_name=name, path=str(snapshot),
                               sha256=binding['sha256'], original_source=binding))
        prepared = []
        for shot in spec['shots']:
            sid = shot['id']
            jid = 'scene_v36_'+jobs.digest(dict(spec=spec, run=str(run), sid=sid))[:20]+'_'+sid
            graph = jobs.build_graph([dict(id=sid, prompt=shot['prompt'], seed=shot['seed'],
                                          references=[dict(input_name=r['input_name']) for r in inputs])],
                                     cfg['allowed_prefix']+'/'+jid,
                                     width=spec['width'], height=spec['height'], steps=spec['steps'])
            evidence = reference_graph_evidence(graph, sid, inputs)
            job = run/'jobs'/sid
            jobs.prepare_job(job, graph, cfg, inputs, jid)
            prepared.append(dict(id=sid, job_dir=str(job), job_id=jid,
                                 job_plan=_binding(job/'PLAN.json'), graph=_binding(job/'workflow_api.json'),
                                 source_state=shot['source_state'], reference_graph_evidence=evidence))
        plan = dict(version=VERSION, spec=_binding(spec_path), spec_snapshot=_binding(run/'SPEC.snapshot.json'),
                    authorization=spec['authorization'], config=spec['image_config'], source_case=spec['source_case'],
                    mother_native_result=spec['mother_native_result'], mother_native_id=native_mother['prompt_id'],
                    inputs=inputs, width=spec['width'], height=spec['height'], shots=prepared,
                    max_new_image_submissions=4, user_review_pending=True,
                    semantic_generation_gates=False, review_policy='user_reviews_completed_film')
        jobs._freeze(run/'PLAN.json', plan)
        jobs._freeze(run/'SCENE_STATE.json', dict(version=VERSION, plan_sha256=jobs.digest(plan)))
    return status(run)


def _load(run):
    run = Path(run).resolve()
    plan = jobs._read(run/'PLAN.json')
    state = jobs._read(run/'SCENE_STATE.json')
    if plan.get('version') != VERSION or state != dict(version=VERSION, plan_sha256=jobs.digest(plan)):
        raise jobs.JobIntegrityError('scene_plan_version_mismatch')
    _check_binding(plan['spec_snapshot'])
    spec = jobs._read(plan['spec_snapshot']['path'])
    _validate_spec(spec)
    if [r['id'] for r in plan['shots']] != list(SHOTS):
        raise jobs.JobIntegrityError('frozen_scene_order_changed')
    for shot in plan['shots']:
        _check_binding(shot['job_plan'])
        _check_binding(shot['graph'])
        graph = jobs._read(shot['graph']['path'])
        if reference_graph_evidence(graph, shot['id'], plan['inputs']) != shot['reference_graph_evidence']:
            raise jobs.JobIntegrityError('frozen_positive_reference_evidence_changed')
    return run, plan


def _record_result(run, plan, shot):
    native = jobs.collect(shot['job_dir'])
    if len(native['images']) != 1 or native['images'][0]['save_node'] != shot['id']+'__save':
        raise jobs.JobIntegrityError('one_native_opening_image_required')
    image = native['images'][0]
    if image['dimensions'] != [plan['width'], plan['height']]:
        raise jobs.JobIntegrityError('native_opening_dimensions_mismatch')
    receipt = dict(version=VERSION, shot_id=shot['id'], technical_status='saved',
                   prompt_id=native['prompt_id'], native_id=native['prompt_id'], job_id=native['job_id'],
                   image={k: image[k] for k in ('path', 'sha256', 'dimensions')},
                   native_result=_binding(Path(shot['job_dir'])/'RESULT.json'),
                   scene_plan=_binding(run/'PLAN.json'), source_state=shot['source_state'],
                   photographic_mother=plan['inputs'][0]['original_source'],
                   photographic_mother_native_result=plan['mother_native_result'],
                   photographic_mother_native_id=plan['mother_native_id'],
                   reference_graph_evidence=shot['reference_graph_evidence'],
                   content_status='user_review_pending', user_review_pending=True,
                   production_approved=False, semantic_generation_gates=False)
    target = run/'results'/(shot['id']+'.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    jobs._freeze(target, receipt)
    return receipt


def result(run, sid):
    run, plan = _load(run)
    if sid not in SHOTS:
        raise ValueError('unknown_shot')
    shot = next(s for s in plan['shots'] if s['id'] == sid)
    return _record_result(run, plan, shot)


def status(run):
    run, plan = _load(run)
    rows = []
    for shot in plan['shots']:
        state = jobs.status(shot['job_dir'])
        receipt_path = run/'results'/(shot['id']+'.json')
        receipt = _record_result(run, plan, shot) if receipt_path.exists() else None
        rows.append(dict(id=shot['id'], status=('saved' if receipt else
                         'native_saved' if state['status'] == 'saved' else state['status']),
                         job_dir=shot['job_dir'], prompt_id=state.get('prompt_id'),
                         result_path=str(receipt_path) if receipt else None,
                         image=receipt['image'] if receipt else None, paused=state.get('paused', False)))
    return dict(version=VERSION, run=str(run), shots=rows, user_review_pending=True,
                semantic_generation_gates=False, complete=all(s['status']=='saved' for s in rows))


def complete(run):
    return status(run)['complete']


def budget(run):
    run, plan = _load(run)
    rows = status(run)['shots']
    claimed = sum((Path(s['job_dir'])/'CLAIM.json').exists() for s in rows)
    return dict(max_new_image_submissions=plan['max_new_image_submissions'],
                claimed=claimed, remaining=plan['max_new_image_submissions']-claimed,
                known=sum(bool(s['prompt_id']) for s in rows),
                outcome_unknown=sum(s['status']=='outcome_unknown' for s in rows))


def collect_known(run):
    """Collect original IDs using frozen local snapshots, even if external source changed."""
    run, plan = _load(run)
    with jobs.run_lock(run):
        for shot in plan['shots']:
            state = jobs.status(shot['job_dir'])
            if not state.get('prompt_id'):
                continue
            if state['status'] not in ('saved', 'native_complete', 'failed', 'rejected', 'cancelled', 'interrupted'):
                state = jobs.poll(shot['job_dir'])
            if state['status'] in ('saved', 'native_complete'):
                _record_result(run, plan, shot)
    return status(run)


def submit_next(run):
    """One ordered dispatch; a known or unknown prior job is never re-submitted."""
    run, plan = _load(run)
    with jobs.run_lock(run):
        rows = status(run)['shots']
        for row in rows:
            if row['status'] == 'saved':
                continue
            if row['status'] != 'prepared' or row['prompt_id']:
                return dict(status(run), dispatch='waiting_original_or_terminal_job', current=row['id'])
            if budget(run)['remaining'] <= 0:
                return dict(status(run), dispatch='image_budget_exhausted')
            # These are NEW-dispatch gates only.  Known-ID collection never calls them.
            for binding in (plan['spec'], plan['authorization'], plan['config'], plan['source_case'], plan['mother_native_result']):
                _check_binding(binding)
            for ref in plan['inputs']:
                _check_binding(ref['original_source'])
            jobs.submit(row['job_dir'])
            return dict(status(run), dispatch='one_image_job_processed', current=row['id'])
        return dict(status(run), dispatch='all_images_saved')
