"""Sequential photo edits with real prior native tails and named multi-view cast.

Only technical checks are performed. No generated image is opened for visual
review, no vision/text model is called, and no unknown submission is replayed.
"""
from pathlib import Path

from PIL import Image

from . import visual_image_jobs_v3 as jobs

VERSION = 'multiview_continuity_stills/v37'
SPEC_SCHEMA = 'multiview_continuity_stills_spec/v37'
POLICY = 'actual_tail_then_current_s01_and_named_multiview_cast/v37'
CAST = ('su_mo', 'ye_nan', 'ye_xijue')
SHOTS = ('S01', 'S02', 'S03', 'S04')
VIEWS = {'left_oblique', 'right_oblique', 'left_profile', 'right_profile'}
ANGLE_VIEWS = {
    'S01': dict(su_mo='right_oblique', ye_nan='left_oblique', ye_xijue='right_oblique'),
    'S02': dict(su_mo='right_oblique', ye_nan='left_oblique', ye_xijue='left_oblique'),
    'S03': dict(su_mo='right_oblique', ye_nan='left_oblique', ye_xijue='left_oblique'),
    'S04': dict(su_mo='right_oblique', ye_nan='left_oblique', ye_xijue='left_oblique')}


def bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=jobs.file_sha(path))


def check(binding):
    if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'} or bind(binding['path']) != binding:
        raise jobs.JobIntegrityError('bound_file_changed')
    return Path(binding['path'])


def _image(binding, dimensions=None):
    path = check(binding)
    with Image.open(path) as im:
        if getattr(im, 'n_frames', 1) != 1 or (dimensions is not None and list(im.size) != dimensions):
            raise jobs.JobIntegrityError('single_image_geometry_mismatch')
        im.verify()
    return path


def _asset(index_path, entity, view, design_version):
    index_path = Path(index_path).resolve()
    entries = [r for r in jobs._read(index_path)['assets'] if r.get('entity_id') == entity
               and r.get('view') == view and r.get('design_version') == design_version and r.get('kind') == 'character']
    if len(entries) != 1:
        raise jobs.JobIntegrityError('one_explicit_asset_version_required')
    entry = entries[0]
    image = index_path.parent/entry['file']
    meta = image.with_suffix('.json')
    if jobs._read(meta) != entry or jobs.file_sha(image) != entry['sha256']:
        raise jobs.JobIntegrityError('index_metadata_or_asset_pixels_mismatch')
    keys = ('book_id', 'entity_id', 'kind', 'view', 'design_version', 'version', 'identity_group', 'asset_id')
    return dict(image=bind(image), metadata=bind(meta), identity={k: entry[k] for k in keys})


def opening_state(sid):
    states = {
        'S01': 'Su Mo lies supported on the same bed with eyes closed and empty hands. '
               'Ye Xijue holds the single bread bag and looks up toward Ye Nan; Ye Nan looks toward his younger brother.',
        'S02': 'The father is still on the bed with eyes closed and empty hands at this opening instant. '
               'The younger boy retains the single bread bag and looks toward his father; the older boy attends to his younger brother.',
        'S03': 'The father is awake, eyes open, still supported on the bed and has not yet accepted the bread. '
               'The younger boy is offering the single bread bag toward his father while still holding it; '
               'the father attends to the boy or the bread, and the older boy attends to his younger brother.',
        'S04': 'The father stands at the same bedside holding the single bread bag; his attention is on the bread and children. '
               'The boys stand close together, the older boy protective of the younger; the younger boy has empty hands and attends to his father.'}
    return states[sid]


def performance_prompt(sid, angle_views):
    if sid == 'S01':
        basis = (
            'Edit Image 1, the photographed room and clothing-layout base, into one candid opening instant. '
            'Keep its existing cracked grey walls, window frames and their placement, worn cement floor, '
            'one wooden bed with grey bedding, and small wooden table in the same room. '
            'Change the photographed performers into the story directions below. '
            'Images 2, 3 and 4 are the front identity references of Su Mo, Ye Nan and Ye Xijue. '
            'Images 5, 6 and 7 are their respective selected angle identity references. ')
    else:
        basis = (
            'Make a minimal continuity edit of Image 1, the actual final frame of the immediately preceding video in this run. '
            'Its existing characters, bodies, relative positions, room perspective, ongoing expressions and head directions '
            'are the primary continuity state. Retain these existing visible states wherever they already fit the source opening below. '
            'Only adjust the source-required eye state, bedside posture, bread ownership or a necessary occlusion. '
            'Image 2 is this run\'s already established S01 scene photograph and supplies the same room, costume and cast context: '
            'its cracked walls, window frames, wooden bed, grey bedding, small table and floor materials. '
            'It depicts the same existing people, not additional people. Its earlier action state does not reset the current action; '
            'Image 1 supplies the current performers, ongoing staging and performance direction. '
            'Images 3, 4 and 5 are the front identities of Su Mo, Ye Nan and Ye Xijue. '
            'Images 6, 7 and 8 are their respective selected angle identities. ')
    angles = '; '.join(name+' '+angle_views[name].replace('_', ' ') for name in CAST)
    return (basis + 'Selected views: '+angles+'. '
            'Use each front and angle pair for the same named person and the same costume/identity version. '
            'The reference portraits show identity from multiple directions; their pose and eye contact are not acting instructions. '
            'Keep the performers absorbed in their partners or bread with natural side turns, rather than re-staging a shared portrait. '
            'Preserve complete head/body connections and natural bodily support. '
            'Opening source state: '+opening_state(sid)+' '
            'This image is one instant; subsequent acting and camera movement belong to the video, not to a fixed-camera rule.')


def make_spec(mother_photo, asset_index, image_config, authorization, source_case, video_run,
              *, mother_native_result, design_version='v1', width=736, height=1312, steps=4):
    assets = {}
    for entity in CAST:
        selected = {'front'} | {ANGLE_VIEWS[sid][entity] for sid in SHOTS}
        for view in sorted(selected):
            assets[entity+'__'+view] = _asset(asset_index, entity, view, design_version)
    return dict(schema=SPEC_SCHEMA, policy=POLICY, mother_photo=bind(mother_photo),
                mother_native_result=bind(mother_native_result), asset_index=bind(asset_index), assets=assets,
                image_config=bind(image_config), authorization=bind(authorization), source_case=bind(source_case),
                video_run=str(Path(video_run).resolve()), width=width, height=height, steps=steps,
                review_policy='user_reviews_completed_film', semantic_generation_gates=False,
                shots=[dict(id=sid, angle_views=ANGLE_VIEWS[sid], seed=37110901+i,
                            opening_source_state=opening_state(sid), prompt=performance_prompt(sid, ANGLE_VIEWS[sid]))
                       for i, sid in enumerate(SHOTS)])


def _validate_spec(spec):
    if (spec.get('schema') != SPEC_SCHEMA or spec.get('policy') != POLICY
            or spec.get('semantic_generation_gates') is not False
            or spec.get('review_policy') != 'user_reviews_completed_film'
            or [r.get('id') for r in spec.get('shots', [])] != list(SHOTS)):
        raise ValueError('explicit_sequential_multiview_spec_required')
    for key in ('width', 'height'):
        if type(spec.get(key)) is not int or spec[key] < 64 or spec[key] % 16:
            raise ValueError('valid_image_dimensions_required')
    if type(spec.get('steps')) is not int or not 1 <= spec['steps'] <= 100:
        raise ValueError('valid_image_steps_required')
    for row in spec['shots']:
        if (set(row.get('angle_views', {})) != set(CAST)
                or any(v not in VIEWS for v in row['angle_views'].values())
                or row.get('opening_source_state') != opening_state(row['id'])
                or type(row.get('seed')) is not int or not 0 <= row['seed'] < 2**64
                or not isinstance(row.get('prompt'), str) or not row['prompt'].strip()):
            raise ValueError('named_source_state_and_angle_selection_required')
        for name in CAST:
            front = spec['assets'][name+'__front']['identity']
            angle = spec['assets'][name+'__'+row['angle_views'][name]]['identity']
            for key in ('book_id', 'entity_id', 'design_version', 'version', 'identity_group'):
                if front[key] != angle[key]:
                    raise jobs.JobIntegrityError('front_angle_identity_version_mismatch')
            if front['entity_id'] != name or front['view'] != 'front' or angle['view'] != row['angle_views'][name]:
                raise jobs.JobIntegrityError('front_angle_role_mismatch')


def _asset_files_current(spec):
    # An unrelated INDEX append does not invalidate the explicitly frozen versions.
    entries = jobs._read(spec['asset_index']['path'])['assets']
    for asset in spec['assets'].values():
        metadata = jobs._read(check(asset['metadata']))
        if metadata not in entries or any(metadata[k] != v for k, v in asset['identity'].items()):
            raise jobs.JobIntegrityError('selected_index_identity_changed')
        if metadata['sha256'] != asset['image']['sha256']:
            raise jobs.JobIntegrityError('selected_asset_sha_changed')
        _image(asset['image'])


def _mother_current(spec):
    _image(spec['mother_photo'])
    native = jobs._read(check(spec['mother_native_result']))
    if (native.get('technical_status') != 'saved' or not native.get('prompt_id')
            or not any(str(Path(r.get('path', '')).resolve()) == spec['mother_photo']['path']
                       and r.get('sha256') == spec['mother_photo']['sha256'] for r in native.get('images', []))):
        raise jobs.JobIntegrityError('actual_saved_photographic_mother_required')


def prepare(spec_path, run, authorization=None):
    spec_path, run = Path(spec_path).resolve(), Path(run).resolve()
    spec = jobs._read(spec_path)
    _validate_spec(spec)
    if authorization is not None and authorization != spec['authorization']:
        raise ValueError('same_coordinator_authorization_required')
    for key in ('authorization', 'image_config', 'source_case', 'asset_index'):
        check(spec[key])
    auth = jobs._read(spec['authorization']['path'])
    if (auth.get('semantic_generation_gates') is not False or auth.get('review_policy') != 'user_reviews_completed_film'
            or auth.get('engineering_limits', {}).get('image_submissions', 0) < 4):
        raise ValueError('explicit_four_image_technical_only_authority_required')
    _asset_files_current(spec); _mother_current(spec)
    cfg = jobs.Config(**jobs._read(spec['image_config']['path'])).normalized()
    if any(not Path(cfg[k]).is_dir() for k in ('input_root', 'output_root')):
        raise ValueError('existing_service_paths_required')
    if run.parent != Path(spec['video_run']).resolve():
        raise ValueError('scene_must_be_child_of_same_video_run')
    run.mkdir(parents=True, exist_ok=True)
    with jobs.run_lock(run):
        jobs._freeze(run/'SPEC.snapshot.json', spec)
        plan = dict(version=VERSION, spec=bind(spec_path), spec_snapshot=bind(run/'SPEC.snapshot.json'),
                    authorization=spec['authorization'], config=spec['image_config'], video_run=spec['video_run'],
                    shots=[dict(id=sid, job_dir=str(run/'jobs'/sid), shot_plan=str(run/'prepared'/sid/'SHOT_PLAN.json')) for sid in SHOTS],
                    max_new_image_submissions=4, semantic_generation_gates=False,
                    content_status='user_review_pending', production_approved=False)
        jobs._freeze(run/'PLAN.json', plan)
        jobs._freeze(run/'SCENE_STATE.json', dict(version=VERSION, plan_sha256=jobs.digest(plan)))
    return status(run)


def _load(run):
    run = Path(run).resolve(); plan = jobs._read(run/'PLAN.json')
    if (plan.get('version') != VERSION or jobs._read(run/'SCENE_STATE.json') != dict(version=VERSION, plan_sha256=jobs.digest(plan))
            or [r.get('id') for r in plan.get('shots', [])] != list(SHOTS)):
        raise jobs.JobIntegrityError('frozen_scene_plan_changed')
    spec = jobs._read(check(plan['spec_snapshot'])); _validate_spec(spec)
    return run, plan, spec


def _snapshot(run, spec, role, binding):
    source = _image(binding)
    target = run/'source_snapshots'/(role+'_'+binding['sha256'][:16]+source.suffix.lower())
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        jobs._copy_new(source, target)
    if jobs.file_sha(target) != binding['sha256']:
        raise jobs.JobIntegrityError('frozen_reference_snapshot_changed')
    return dict(role=role, path=str(target), sha256=binding['sha256'], original_source=binding,
                input_name='multiview_continuity_v37/'+jobs.digest(spec)[:20]+'/'+target.name)


def reference_graph_evidence(graph, sid, inputs):
    try:
        sample = graph[sid+'__sample']; guide_link = sample['inputs']['guider']; guide = graph[guide_link[0]]
        if sample['class_type'] != 'SamplerCustomAdvanced' or guide['class_type'] != 'CFGGuider' or guide_link[1] != 0:
            raise KeyError('active_sampler_guider')
        link = guide['inputs']['positive']; found = []; seen = set()
        while True:
            if len(link) != 2 or link[1] != 0 or link[0] in seen:
                raise KeyError('positive_chain')
            seen.add(link[0]); node = graph[link[0]]
            if node['class_type'] == 'CLIPTextEncode':
                break
            if node['class_type'] != 'ReferenceLatent':
                raise KeyError('reference_latent')
            latent = node['inputs']['latent']; encoder = graph[latent[0]]; pixels = encoder['inputs']['pixels']; image = graph[pixels[0]]
            if (latent[1] != 0 or encoder['class_type'] != 'VAEEncode' or pixels[1] != 0 or image['class_type'] != 'LoadImage'):
                raise KeyError('actual_reference_pixels')
            found.append(dict(input_name=image['inputs']['image'], load_node=pixels[0], encode_node=latent[0], positive_node=link[0]))
            link = node['inputs']['conditioning']
        found.reverse()
        if [r['input_name'] for r in found] != [r['input_name'] for r in inputs] or len(found) != (7 if sid=='S01' else 8):
            raise KeyError('exact_ordered_multiview_pixels')
        first = 'room_mother' if sid=='S01' else 'prior_video_tail'
        if inputs[0]['role'] != first or (sid!='S01' and inputs[1]['role'] != 'current_run_S01_scene'):
            raise KeyError('tail_is_primary_continuity_input')
        return dict(policy=POLICY, positive_ancestry_verified=True, primary_continuity_role=first,
                    actual_tail_in_positive_chain=(sid!='S01'), reference_count=len(found),
                    references=[dict(**r, role=inputs[i]['role'], sha256=inputs[i]['sha256']) for i,r in enumerate(found)])
    except (KeyError, IndexError, TypeError) as exc:
        raise jobs.JobIntegrityError('positive_multiview_tail_reference_chain_invalid') from exc


def _prior(run, plan, spec, sid, binding):
    previous = SHOTS[SHOTS.index(sid)-1]
    folder = Path(plan['video_run'])/'shots'/previous
    if not isinstance(binding, dict) or Path(binding.get('path', '')).resolve() != (folder/'RESULT.json').resolve():
        raise jobs.JobIntegrityError('actual_same_run_immediate_prior_result_required')
    result_path = check(binding); value = jobs._read(result_path)
    state_path, history_path, graph_path = folder/'STATE.json', folder/'HISTORY.json', folder/'workflow_api.json'
    state = jobs._read(state_path); history = jobs._read(history_path); graph = jobs._read(graph_path)
    pid = value.get('prompt_id'); entry = history.get(pid, {})
    if (value.get('schema') != 'visual_h3_handoff/v3' or value.get('shot_id') != previous
            or value.get('technical_status') != 'technical_saved' or not pid
            or state.get('status') != 'technical_saved' or state.get('prompt_id') != pid or state.get('id') != previous
            or value.get('timing', {}).get('native_frames') != 362
            or entry.get('status', {}).get('completed') is not True or entry['status'].get('status_str') != 'success'
            or len(entry.get('prompt', [])) < 3 or entry['prompt'][1] != pid or entry['prompt'][2] != graph
            or jobs.digest(graph) != value.get('graph_sha256')):
        raise jobs.JobIntegrityError('prior_video_not_original_successfully_saved')
    video_streams = [r for r in value.get('native_metadata', {}).get('streams', []) if r.get('codec_type')=='video']
    if len(video_streams)!=1 or [video_streams[0].get('width'), video_streams[0].get('height')] != [spec['width'], spec['height']]:
        raise jobs.JobIntegrityError('prior_video_native_dimensions_mismatch')
    if set(value.get('files', {})) != {'video', 'audio', 'first', 'last'}:
        raise jobs.JobIntegrityError('prior_video_four_originals_required')
    originals = {}
    for key, item in value['files'].items():
        original = dict(path=str(Path(item['path']).resolve()), sha256=item['sha256'])
        if not Path(original['path']).is_relative_to(folder/'artifacts'):
            raise jobs.JobIntegrityError('prior_original_outside_same_run_artifacts')
        check(original); originals[key] = original
    _image(originals['last'], [spec['width'], spec['height']])
    own_previous = result(run, previous)
    if value.get('first_frame_sha256') != own_previous['image']['sha256']:
        raise jobs.JobIntegrityError('prior_video_not_derived_from_this_scene_image')
    return dict(result=binding, prompt_id=pid, shot_id=previous, originals=originals,
                state=bind(state_path), history=bind(history_path), graph=bind(graph_path))


def prepare_shot(run, sid, prior_video_result=None):
    run, plan, spec = _load(run)
    if sid not in SHOTS:
        raise ValueError('unknown_source_shot')
    row = next(r for r in plan['shots'] if r['id']==sid)
    frozen = Path(row['shot_plan'])
    if frozen.exists():
        prepared = _shot(run, row)
        expected_prior = prepared['prior_video']['result'] if prepared['prior_video'] else None
        if prior_video_result is not None and expected_prior != prior_video_result:
            raise jobs.JobIntegrityError('prepared_original_prior_result_changed')
        return status(run)
    for key in ('authorization', 'image_config', 'source_case'):
        check(spec[key])
    check(plan['spec']); _asset_files_current(spec); _mother_current(spec)
    if sid == 'S01' and prior_video_result is not None:
        raise ValueError('first_shot_has_no_prior_video')
    prior = None if sid=='S01' else _prior(run, plan, spec, sid, prior_video_result)
    source = next(r for r in spec['shots'] if r['id']==sid)
    inputs = []
    room_context = None
    if prior:
        inputs.append(_snapshot(run, spec, 'prior_video_tail', prior['originals']['last']))
        initial = result(run, 'S01')
        room_context = dict(scene_result=bind(run/'results/S01.json'), native_id=initial['native_id'],
                            image={k:initial['image'][k] for k in ('path', 'sha256')}, role='current_run_S01_scene')
        inputs.append(_snapshot(run, spec, 'current_run_S01_scene', room_context['image']))
    else:
        inputs.append(_snapshot(run, spec, 'room_mother', spec['mother_photo']))
    identity_refs = []
    for viewkind in ('front', 'angle'):
        for name in CAST:
            view = 'front' if viewkind=='front' else source['angle_views'][name]
            asset = spec['assets'][name+'__'+view]
            inputs.append(_snapshot(run, spec, name+'_'+viewkind, asset['image']))
            identity_refs.append(dict(role=name+'_'+viewkind, metadata=asset['metadata'], identity=asset['identity'], image=asset['image']))
    cfg = jobs.Config(**jobs._read(spec['image_config']['path'])).normalized()
    jid = 'multiview_v37_'+jobs.digest(dict(spec=spec, run=str(run), sid=sid, prior=prior))[:20]+'_'+sid
    graph = jobs.build_graph([dict(id=sid, prompt=source['prompt'], seed=source['seed'],
                                  references=[dict(input_name=r['input_name']) for r in inputs])],
                             cfg['allowed_prefix']+'/'+jid, width=spec['width'], height=spec['height'], steps=spec['steps'])
    evidence = reference_graph_evidence(graph, sid, inputs)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    with jobs.run_lock(run):
        jobs.prepare_job(row['job_dir'], graph, cfg, inputs, jid)
        prepared = dict(version=VERSION, id=sid, job_dir=row['job_dir'], job_id=jid,
                        job_plan=bind(Path(row['job_dir'])/'PLAN.json'), graph=bind(Path(row['job_dir'])/'workflow_api.json'),
                        prior_video=prior, room_context=room_context, inputs=inputs, identity_references=identity_refs,
                        positive_reference_evidence=evidence, opening_source_state=source['opening_source_state'],
                        scene_plan=bind(run/'PLAN.json'), width=spec['width'], height=spec['height'])
        jobs._freeze(frozen, prepared)
        jobs._freeze(frozen.with_name('SHOT_STATE.json'), dict(version=VERSION, shot_plan_sha256=jobs.digest(prepared)))
    return status(run)


def _shot(run, row):
    frozen = Path(row['shot_plan']); prepared = jobs._read(frozen)
    if (jobs._read(frozen.with_name('SHOT_STATE.json')) != dict(version=VERSION, shot_plan_sha256=jobs.digest(prepared))
            or prepared.get('id') != row['id'] or prepared.get('job_dir') != row['job_dir']):
        raise jobs.JobIntegrityError('frozen_per_shot_plan_changed')
    check(prepared['job_plan']); graph = jobs._read(check(prepared['graph']))
    if reference_graph_evidence(graph, row['id'], prepared['inputs']) != prepared['positive_reference_evidence']:
        raise jobs.JobIntegrityError('frozen_per_shot_positive_evidence_changed')
    return prepared


def _record_result(run, row, prepared):
    native = jobs.collect(row['job_dir'])
    if len(native['images']) != 1 or native['images'][0]['save_node'] != row['id']+'__save':
        raise jobs.JobIntegrityError('one_native_continuity_image_required')
    image = native['images'][0]
    if image['dimensions'] != [prepared['width'], prepared['height']]:
        raise jobs.JobIntegrityError('native_continuity_image_dimensions_mismatch')
    receipt = dict(version=VERSION, shot_id=row['id'], technical_status='saved',
                   native_id=native['prompt_id'], prompt_id=native['prompt_id'], job_id=native['job_id'],
                   image={k:image[k] for k in ('path', 'sha256', 'dimensions')},
                   native_result=bind(Path(row['job_dir'])/'RESULT.json'), scene_plan=prepared['scene_plan'],
                   shot_plan=bind(row['shot_plan']), prior_video=prepared['prior_video'],
                   room_context=prepared['room_context'],
                   positive_reference_evidence=prepared['positive_reference_evidence'],
                   identity_references=prepared['identity_references'],
                   opening_source_state=prepared['opening_source_state'], content_status='user_review_pending',
                   user_review_pending=True, production_approved=False, semantic_generation_gates=False)
    target = run/'results'/(row['id']+'.json'); target.parent.mkdir(parents=True, exist_ok=True)
    jobs._freeze(target, receipt)
    return receipt


def result(run, sid):
    run, plan, _ = _load(run)
    if sid not in SHOTS:
        raise ValueError('unknown_source_shot')
    row = next(r for r in plan['shots'] if r['id']==sid)
    return _record_result(run, row, _shot(run, row))


def status(run):
    run, plan, _ = _load(run); rows = []
    for row in plan['shots']:
        status_value = dict(id=row['id'], job_dir=row['job_dir'], prompt_id=None,
                            status='unprepared', result_path=None, image=None, paused=False)
        if Path(row['shot_plan']).exists():
            prepared = _shot(run, row); native = jobs.status(row['job_dir']); target = run/'results'/(row['id']+'.json')
            receipt = _record_result(run, row, prepared) if target.exists() else None
            status_value.update(status=('saved' if receipt else 'native_saved' if native['status']=='saved' else native['status']),
                                prompt_id=native.get('prompt_id'), paused=native.get('paused', False),
                                result_path=str(target) if receipt else None, image=receipt['image'] if receipt else None)
        rows.append(status_value)
    return dict(version=VERSION, run=str(run), shots=rows, complete=all(r['status']=='saved' for r in rows),
                user_review_pending=True, semantic_generation_gates=False)


def complete(run):
    return status(run)['complete']


def budget(run):
    run, plan, _ = _load(run); rows = status(run)['shots']
    claimed = sum((Path(r['job_dir'])/'CLAIM.json').exists() for r in rows)
    return dict(max_new_image_submissions=plan['max_new_image_submissions'], claimed=claimed,
                remaining=plan['max_new_image_submissions']-claimed,
                known=sum(bool(r['prompt_id']) for r in rows),
                outcome_unknown=sum(r['status']=='outcome_unknown' for r in rows))


def collect_known(run):
    run, plan, _ = _load(run)
    with jobs.run_lock(run):
        for row in plan['shots']:
            if not Path(row['shot_plan']).exists():
                continue
            prepared = _shot(run, row); state = jobs.status(row['job_dir'])
            if not state.get('prompt_id'):
                continue
            if state['status'] not in ('saved', 'native_complete', 'failed', 'rejected', 'interrupted', 'cancelled'):
                state = jobs.poll(row['job_dir'])
            if state['status'] in ('saved', 'native_complete'):
                _record_result(run, row, prepared)
    return status(run)


def submit_next(run):
    run, plan, spec = _load(run)
    with jobs.run_lock(run):
        for row in status(run)['shots']:
            if row['status']=='saved':
                continue
            if row['status']!='prepared' or row['prompt_id']:
                return dict(status(run), dispatch='waiting_preparation_original_or_terminal_job', current=row['id'])
            if budget(run)['remaining']<=0:
                return dict(status(run), dispatch='image_budget_exhausted')
            for binding in (plan['spec'], spec['authorization'], spec['image_config'], spec['source_case']):
                check(binding)
            _asset_files_current(spec); _mother_current(spec)
            static = next(r for r in plan['shots'] if r['id']==row['id']); prepared = _shot(run, static)
            for ref in prepared['inputs']:
                _image(ref['original_source'])
            if prepared['prior_video']:
                for key in ('result', 'state', 'history', 'graph'):
                    check(prepared['prior_video'][key])
                for original in prepared['prior_video']['originals'].values():
                    check(original)
                check(prepared['room_context']['scene_result'])
            jobs.submit(row['job_dir'])
            return dict(status(run), dispatch='one_image_job_processed', current=row['id'])
        return dict(status(run), dispatch='all_images_saved')
