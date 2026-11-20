"""Read-only, per-shot, reviewed canonical/view references for a new H3 handoff.

This collector does not compose an image, write a registry, rewrite a prompt,
choose a model capacity or grant production approval. A video adapter must
separately prove that its actual model can consume this complete reference set.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from . import visual_asset_pipeline_v3 as pipeline
from . import visual_asset_registry_v3 as library
from .visual_shot_binding_v3 import AUDIO_MODES, fingerprint

SCHEMA = 'reviewed_h3_reference_bundle/v20'


class ReferenceBundleError(ValueError):
    pass


def _file(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ReferenceBundleError('reference_evidence_file_missing')
    return dict(path=str(path), sha256=pipeline.file_sha(path))


def _check_file(bound):
    if (not isinstance(bound, dict) or set(bound) != {'path', 'sha256'}
            or _file(bound['path']) != bound):
        raise ReferenceBundleError('reference_evidence_file_changed')


def _named(items, name):
    if not isinstance(items, list) or any(not isinstance(x, dict) or not isinstance(x.get('id'), str) or not x['id'] for x in items):
        raise ReferenceBundleError('explicit_named_' + name + '_required')
    result = {x['id']: x for x in items}
    if len(result) != len(items):
        raise ReferenceBundleError('duplicate_' + name)
    return result


def _shot(packet, shot_id):
    shots = _named(packet.get('shots'), 'shot')
    if shot_id not in shots:
        raise ReferenceBundleError('source_shot_not_found')
    shot = shots[shot_id]
    characters = _named(packet.get('characters'), 'character')
    places = _named(packet.get('places'), 'place')
    visible = shot.get('visible_cast')
    if (not isinstance(visible, list) or any(not isinstance(x, str) for x in visible)
            or len(visible) != len(set(visible)) or not set(visible) <= set(characters)):
        raise ReferenceBundleError('explicit_known_visible_cast_required')
    views = shot.get('character_views')
    if not isinstance(views, dict) or set(views) != set(visible):
        raise ReferenceBundleError('exact_view_for_each_visible_character_required')
    if any(v not in library.CHARACTER_VIEWS for v in views.values()):
        raise ReferenceBundleError('unsupported_character_reference_view')
    if not isinstance(shot.get('scene_id'), str) or not shot['scene_id'] or shot.get('place_id') not in places:
        raise ReferenceBundleError('source_scene_and_place_required')
    # A layout drawing is a technical guide, not a camera plate. Custom named
    # camera views are allowed only when the source layout actually defines them.
    place = places[shot['place_id']]
    place_view = shot.get('place_view', 'front')
    cameras = place.get('spatial_layout', {}).get('cameras', {})
    if (not isinstance(place_view, str) or place_view == 'layout'
            or place_view not in {'front', 'reverse', 'side', *cameras}):
        raise ReferenceBundleError('explicit_scene_camera_view_required')
    if place.get('spatial_layout') and place_view not in cameras:
        raise ReferenceBundleError('camera_view_not_in_source_place_layout')
    if packet.get('scenes') is not None:
        scene = _named(packet['scenes'], 'scene').get(shot['scene_id'])
        if (not scene or scene.get('place_id', shot['place_id']) != shot['place_id']
                or 'cast' in scene and not set(visible) <= set(scene['cast'])):
            raise ReferenceBundleError('shot_outside_source_scene')
    for item in shot.get('audio', []):
        if (item.get('mode') not in AUDIO_MODES
                or item['mode'] == 'onscreen' and item.get('speaker') not in visible):
            raise ReferenceBundleError('onscreen_audio_not_in_visible_cast')
    return shot, characters, place, place_view


def _strict_review(row):
    event = row.get('review') or {}
    source = pipeline._latest_review({}, row)
    keys = library.REVIEW_CHECKS[row['kind']]
    evidence = source.get('visual_evidence')
    if (row.get('status') != 'reviewed' or row.get('dependency_stale')
            or event.get('decision') != 'accepted' or event.get('file_sha256') != row['sha256']
            or event.get('asset_id') != row['asset_id'] or event.get('version') != row['version']
            or source.get('decision') != 'accepted' or source.get('target_sha256') != row['sha256']
            or source.get('completion_known') is not True or source.get('outcome_unknown') is not False
            or any(source.get('checks', {}).get(k) is not True for k in keys)
            or not isinstance(evidence, list) or not evidence
            or any(not isinstance(x, str) or not x.strip() for x in evidence)):
        raise ReferenceBundleError('current_sha_bound_complete_review_required:' + row['entity_id'] + '/' + row['view'])
    return dict(review_id=event['review_id'], review_target=event['target'],
                event_sha256=fingerprint(event), source_review_sha256=fingerprint(source),
                checks={k: source['checks'][k] for k in keys},
                completion_known=True, outcome_unknown=False, decision='accepted')


def _provenance_files(row):
    provenance = row.get('provenance', {})
    result = []
    if provenance.get('manifest_path'):
        bound = dict(path=str(Path(provenance['manifest_path']).resolve()), sha256=provenance.get('manifest_sha256'))
        _check_file(bound)
        result.append(dict(role='import_manifest', **bound))
    source = provenance.get('source')
    if source is not None:
        bound = dict(path=str(Path(source['path']).resolve()), sha256=source['sha256'])
        _check_file(bound)
        result.append(dict(role='asset_source', **bound))
    return result


def _asset(plan, requirement, proofs, seen=()):
    row = pipeline._lookup(plan, requirement)
    if not row:
        raise ReferenceBundleError('required_reviewed_reference_missing:' + requirement['entity_id'] + '/' + requirement['view'])
    if str(row.get('book_id')) != str(plan['packet']['book_id']):
        raise ReferenceBundleError('cross_book_reference')
    if any(row.get(k) != requirement[k] for k in ('entity_id', 'kind', 'view', 'design_version')):
        raise ReferenceBundleError('reference_scope_or_exact_view_changed')
    if row.get('status') != 'reviewed' or row.get('dependency_stale'):
        raise ReferenceBundleError('required_reference_not_currently_reviewed:' + requirement['entity_id'] + '/' + requirement['view'])
    key = (row['asset_id'], row['version'])
    if key in seen:
        raise ReferenceBundleError('reference_dependency_cycle')
    review = _strict_review(row)
    deps, known = pipeline._dependencies(plan, row)
    if not known:
        raise ReferenceBundleError('reference_dependencies_unbound')
    if row.get('dependency_fingerprint') != fingerprint(deps):
        raise ReferenceBundleError('reference_dependency_fingerprint_changed')
    dependency_keys = []
    for expected in deps:
        req = {k: expected[k] for k in ('entity_id', 'kind', 'view', 'design_version')}
        current = _asset(plan, req, proofs, seen + (key,))
        if {k: current[k] for k in ('asset_id', 'version', 'entity_id', 'kind', 'view', 'design_version', 'sha256')} != expected:
            raise ReferenceBundleError('reference_dependency_version_changed')
        dependency_keys.append(current['proof_id'])
    image = _file(pipeline._image_path(plan, row))
    record_path = Path(plan['config']['library']) / f"{row['asset_id']}_v{row['version']}.json"
    review_path = Path(plan['config']['library']) / 'reviews' / (review['review_id'] + '.json')
    proof = dict(proof_id=row['asset_id'] + ':v' + str(row['version']),
                 **{k: row[k] for k in ('asset_id', 'version', 'book_id', 'entity_id', 'kind', 'view',
                                       'design_version', 'input_sha256', 'identity_group', 'sha256')},
                 image=image, asset_record=_file(record_path), review_record=_file(review_path), review=review,
                 provenance_sha256=fingerprint(row.get('provenance', {})),
                 provenance_files=_provenance_files(row), dependency_fingerprint=fingerprint(deps),
                 dependencies=dependency_keys)
    if key in proofs and proofs[key] != proof:
        raise ReferenceBundleError('reference_changed_during_collection')
    proofs[key] = proof
    return proof


def _collect(asset_run, shot_id, *, expected_book_id=None):
    """Read current reviewed canonical+exact-view assets; never silently drop any.

    Output references contain only visible roles and this shot's physical place.
    Transitive dependency evidence is separate and is not another model image.
    Canonical front is mandatory even when a different shot view is requested.
    """
    run = Path(asset_run).resolve()
    plan_file = _file(run / 'PLAN.json')
    snapshot = pipeline.status(run)
    plan = snapshot['plan']
    packet = plan['packet']
    book = str(packet['book_id'])
    if expected_book_id is not None and book != str(expected_book_id):
        raise ReferenceBundleError('source_book_scope_changed')
    shot, characters, place, place_view = _shot(packet, shot_id)
    source = dict(path=str(Path(packet['source']['path']).resolve()), sha256=packet['source']['sha256'])
    _check_file(source)
    # Detect a concurrent index transaction without binding unrelated library
    # rows into this shot. Unrelated future asset imports do not stale a bundle.
    index_file = _file(Path(plan['config']['library']) / 'INDEX.json')
    proofs, selected = {}, {}

    def add(entity_id, kind, view, entity, role):
        req = dict(entity_id=entity_id, kind=kind, view=view, design_version=entity.get('design_version', 'v1'))
        proof = _asset(plan, req, proofs)
        ref_id = kind + ':' + entity_id + ':' + view
        if ref_id not in selected:
            selected[ref_id] = dict(reference_id=ref_id, entity_id=entity_id,
                display_name=entity.get('name') or entity_id, kind=kind, view=view,
                proof_id=proof['proof_id'], asset_id=proof['asset_id'], version=proof['version'],
                design_version=proof['design_version'], identity_group=proof['identity_group'],
                image=proof['image'], roles=[])
        selected[ref_id]['roles'].append(role)
        return ref_id

    character_references = []
    for cid in shot['visible_cast']:
        canonical = add(cid, 'character', 'front', characters[cid], 'canonical_identity')
        view = add(cid, 'character', shot['character_views'][cid], characters[cid], 'shot_character_view')
        character_references.append(dict(entity_id=cid, canonical_reference=canonical, shot_reference=view))
    canonical = add(place['id'], 'place', 'front', place, 'canonical_environment')
    camera = add(place['id'], 'place', place_view, place, 'shot_environment_view')
    _check_file(index_file); _check_file(plan_file); _check_file(source)
    bundle = dict(schema=SCHEMA, asset_run=str(run), asset_plan=plan_file, book_id=book,
                  source=source, packet_sha256=plan['packet_sha256'],
                  source_shot=dict(id=shot_id, scene_id=shot['scene_id'], place_id=shot['place_id'],
                                   shot_sha256=fingerprint(shot), visible_cast=deepcopy(shot['visible_cast']),
                                   character_views=deepcopy(shot['character_views']), place_view=place_view),
                  characters=character_references,
                  environment=dict(entity_id=place['id'], scene_id=shot['scene_id'], canonical_reference=canonical,
                                   shot_reference=camera, design_sha256=pipeline._environment_design_sha(place)),
                  references=list(selected.values()), asset_proofs=list(proofs.values()),
                  reference_policy='visible_canonical_and_exact_shot_view/v20',
                  tail_policy='auxiliary_only_never_replaces_global_references',
                  reference_count=len(selected), model_capacity_checked=False,
                  media_generated=False, prompt_rewritten=False, production_approved=False, publication=False)
    bundle['bundle_sha256'] = fingerprint(bundle)
    return bundle


def collect(asset_run, shot_id, *, expected_book_id=None):
    """Collect without mutations; malformed/stale upstream evidence fails closed."""
    try:
        return _collect(asset_run, shot_id, expected_book_id=expected_book_id)
    except ReferenceBundleError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReferenceBundleError('reference_source_integrity:' + str(error)) from error


def validate(bundle):
    """Recollect exact current evidence. No records are created or updated."""
    if isinstance(bundle, dict) and bundle.get('reuse_contract') is not None:
        from . import visual_h3_reference_reuse_v21
        return visual_h3_reference_reuse_v21.validate(bundle)
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        raise ReferenceBundleError('invalid_reference_bundle')
    supplied = deepcopy(bundle)
    claimed = supplied.pop('bundle_sha256', None)
    if not isinstance(claimed, str) or fingerprint(supplied) != claimed:
        raise ReferenceBundleError('reference_bundle_changed')
    _check_file(bundle['asset_plan'])
    fresh = collect(bundle['asset_run'], bundle['source_shot']['id'], expected_book_id=bundle['book_id'])
    if fresh != bundle:
        raise ReferenceBundleError('reference_bundle_no_longer_current')
    return fresh
