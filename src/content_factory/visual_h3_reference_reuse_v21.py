"""Explicit original-prompt reuse of fully validated, reviewed donor assets.

Donor packets keep their original source/generation policy. New source shots
are bound here, never inserted into an old staged packet or old PLAN.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import visual_asset_pipeline_v3 as assets
from . import visual_image_jobs_v3 as jobs
from .visual_shot_binding_v3 import fingerprint

CONTRACT = 'reviewed_donor_assets/v21'
SCHEMA = 'original_prompt_reference_reuse/v21'
IDS = ('S01', 'S02', 'S03', 'S04')


class ReuseError(ValueError):
    pass


def _binding(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=assets.file_sha(path))


def _check(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'} or _binding(value['path']) != value:
        raise ReuseError('reuse_bound_file_changed')
    return Path(value['path'])


def _freeze(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs._freeze(path, value)


def _text(request):
    values = [x.get('text') for x in request.get('content', []) if isinstance(x, dict) and x.get('type') == 'text']
    if len(values) != 1 or not isinstance(values[0], str) or not values[0].strip():
        raise ReuseError('one_original_request_text_required')
    return values[0]


def _authorization(value):
    document = assets.read(_check(value))
    if (not isinstance(document.get('user_statement'), str) or not document['user_statement'].strip()
            or document.get('max_new_native_submissions') != 4 or document.get('publication') is not False
            or document.get('new_cloud_calls') != 0):
        raise ReuseError('explicit_four_local_original_prompt_authorization_required')


def dialogue_spans(text):
    return [dict(start=m.start(), end=m.end(), text=m.group()) for m in re.finditer('“[^”]*”|「[^」]*」', text)]


def verify_prompt_adaptation(audit_binding, approval_binding):
    audit = assets.read(_check(audit_binding)); approval = assets.read(_check(approval_binding))
    if (audit.get('schema') != 'reference_prompt_adaptation/v21'
            or approval.get('schema') != 'root_reference_prompt_approval/v21'
            or approval.get('approved_for_generation') is not True or approval.get('reviewed_by') != 'root_agent'
            or approval.get('audit') != audit_binding or audit.get('prompt_model_calls') != 0
            or [x['id'] for x in audit.get('segments', [])] != list(IDS)):
        raise ReuseError('explicit_root_prompt_adaptation_approval_required')
    for row in audit['segments']:
        original = _text(assets.read(_check(row['original_request'])))
        original_data = _check(row['original_prompt_file']).read_bytes()
        data = _check(row['adapted_prompt_file']).read_bytes(); text = data.decode('utf-8')
        if (original_data != original.encode('utf-8')
                or hashlib.sha256(original_data).hexdigest() != row['original_prompt_utf8_sha256']
                or hashlib.sha256(data).hexdigest() != row['adapted_prompt_utf8_sha256']
                or approval.get('adapted_prompt_sha256', {}).get(row['id']) != row['adapted_prompt_utf8_sha256']):
            raise ReuseError('prompt_original_or_approved_adaptation_changed')
        replay = original
        for change in row['changes']:
            if (not isinstance(change.get('old'), str) or not change['old'] or not isinstance(change.get('new'), str)
                    or type(change.get('count')) is not int or change['count'] <= 0
                    or replay.count(change['old']) != change['count']):
                raise ReuseError('prompt_adaptation_replacement_count_changed')
            replay = replay.replace(change['old'], change['new'])
        old_spans, new_spans = dialogue_spans(original), dialogue_spans(text)
        if (replay != text or old_spans != row['original_dialogue_spans'] or new_spans != row['adapted_dialogue_spans']
                or [x['text'] for x in old_spans] != [x['text'] for x in new_spans]
                or row.get('dialogue_texts_equal') is not True):
            raise ReuseError('prompt_adaptation_changed_original_dialogue_or_unlogged_text')
    return audit


def prepare_manifest(root, *, donor_bundles, role_sources, environment, segments, authorization,
                     prompt_adaptation_audit, prompt_approval):
    """CPU files only. Validates each full donor before freezing the new scope."""
    from . import visual_h3_reference_bundle_v20 as bundles
    root = Path(root).resolve()
    _authorization(authorization)
    audit = verify_prompt_adaptation(prompt_adaptation_audit, prompt_approval)
    adapted = {x['id']: x for x in audit['segments']}
    if set(x['id'] for x in segments) != set(IDS) or len(segments) != 4:
        raise ReuseError('four_original_segments_required')
    if len(role_sources) != 3 or len({x['entity_id'] for x in role_sources}) != 3:
        raise ReuseError('three_distinct_named_roles_required')
    donors = {}
    for name, value in donor_bundles.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name):
            raise ReuseError('safe_donor_identifier_required')
        if value.get('reuse_contract'):
            raise ReuseError('nested_donor_reuse_refused')
        checked = bundles.validate(value)
        path = root/'donors'/(name+'.json')
        _freeze(path, checked)
        donors[name] = dict(bundle=_binding(path), bundle_sha256=checked['bundle_sha256'])
    first = next(iter(donor_bundles.values()))
    if any(str(b['book_id']) != str(first['book_id']) or b['source'] != first['source'] for b in donor_bundles.values()):
        raise ReuseError('donors_must_share_book_and_original_novel_source')
    rows = []
    by_id = {x['id']: x for x in segments}
    for sid in IDS:
        spec = by_id[sid]
        request_binding = _binding(spec['request_path'])
        if request_binding != adapted[sid]['original_request']:
            raise ReuseError('segment_original_request_not_approved')
        text = _check(adapted[sid]['adapted_prompt_file']).read_bytes().decode('utf-8')
        target = root/'sources'/(sid+'.prompt.txt')
        target.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode('utf-8')
        if target.exists():
            if target.read_bytes() != data:
                raise ReuseError('original_prompt_copy_changed')
        else:
            with target.open('xb') as stream:
                stream.write(data); stream.flush()
        shot = dict(id=sid, scene_id='seedance_original_room_scene', place_id=environment['entity_id'],
                    visible_cast=[x['entity_id'] for x in role_sources],
                    character_views={x['entity_id']: 'front' for x in role_sources}, place_view=environment['view'],
                    start=0, end=15, requested_seconds=15, source_native_frames=362, source_native_seconds=362/24,
                    complete_video_prompt=text, audio=[], audio_contract='embedded_original_prompt_verbatim',
                    source_request=request_binding, production_approved=False)
        rows.append(dict(id=sid, source_request=request_binding, source_prompt_file=_binding(target),
                         original_prompt_utf8_sha256=adapted[sid]['original_prompt_utf8_sha256'],
                         adapted_prompt_utf8_sha256=hashlib.sha256(data).hexdigest(), characters=len(text),
                         delivery_run=str(Path(spec['delivery_run']).resolve()), source_shot=shot))
    manifest = dict(schema=SCHEMA, reuse_contract=CONTRACT, authorization=deepcopy(authorization),
                    prompt_adaptation_audit=deepcopy(prompt_adaptation_audit), prompt_approval=deepcopy(prompt_approval),
                    user_statement=assets.read(authorization['path'])['user_statement'],
                    book_id=first['book_id'], source=deepcopy(first['source']), donors=donors,
                    role_sources=deepcopy(role_sources), environment=deepcopy(environment), segments=rows,
                    width=736, height=1312, fps=24, native_frames_per_segment=362,
                    max_new_native_submissions=4, prompt_rewritten=False,
                    production_approved=False, publication=False, media_generated=False)
    manifest['content_sha256'] = fingerprint(manifest)
    path = root/'MANIFEST.json'
    _freeze(path, manifest)
    # Recheck selection scope, source and exact original values before return.
    _manifest(path, validate_donors=False)
    return _binding(path)


def _manifest(path, *, validate_donors=True):
    from . import visual_h3_reference_bundle_v20 as bundles
    path = Path(path).resolve()
    value = assets.read(path)
    content = deepcopy(value); digest = content.pop('content_sha256', None)
    if (value.get('schema') != SCHEMA or value.get('reuse_contract') != CONTRACT
            or fingerprint(content) != digest or value.get('publication') is not False
            or value.get('production_approved') is not False or value.get('prompt_rewritten') is not False
            or value.get('media_generated') is not False or value.get('max_new_native_submissions') != 4
            or (value.get('width'), value.get('height'), value.get('fps'), value.get('native_frames_per_segment')) != (736,1312,24,362)):
        raise ReuseError('reuse_manifest_contract_changed')
    _authorization(value['authorization']); _check(value['source'])
    audit = verify_prompt_adaptation(value['prompt_adaptation_audit'], value['prompt_approval'])
    adapted = {x['id']: x for x in audit['segments']}
    if [x['id'] for x in value['segments']] != list(IDS):
        raise ReuseError('reuse_segment_order_changed')
    for row in value['segments']:
        if row['source_request'] != adapted[row['id']]['original_request']:
            raise ReuseError('manifest_original_request_changed')
        _check(row['source_request'])
        text = _check(adapted[row['id']]['adapted_prompt_file']).read_bytes().decode('utf-8')
        data = _check(row['source_prompt_file']).read_bytes()
        shot = row['source_shot']
        if (text.encode('utf-8') != data or hashlib.sha256(data).hexdigest() != row['adapted_prompt_utf8_sha256']
                or row['original_prompt_utf8_sha256'] != adapted[row['id']]['original_prompt_utf8_sha256']
                or shot.get('complete_video_prompt') != text or shot.get('source_request') != row['source_request']
                or shot.get('id') != row['id'] or shot.get('audio') != []
                or (shot.get('start'), shot.get('end'), shot.get('source_native_frames')) != (0,15,362)
                or shot.get('visible_cast') != [r['entity_id'] for r in value['role_sources']]
                or shot.get('character_views') != {r['entity_id']: 'front' for r in value['role_sources']}
                or shot.get('place_id') != value['environment']['entity_id']
                or shot.get('place_view') != value['environment']['view']):
            raise ReuseError('original_segment_text_or_scope_changed')
    donors = {}
    for name, record in value['donors'].items():
        donor = assets.read(_check(record['bundle']))
        if (donor.get('reuse_contract') or donor.get('bundle_sha256') != record['bundle_sha256']
                or str(donor.get('book_id')) != str(value['book_id']) or donor.get('source') != value['source']):
            raise ReuseError('donor_book_source_or_identity_changed')
        donors[name] = bundles.validate(donor) if validate_donors else donor
    if len(value['role_sources']) != 3 or len({r['entity_id'] for r in value['role_sources']}) != 3:
        raise ReuseError('three_distinct_named_roles_required')
    _selection(value, donors)
    return value, donors


def _selection(manifest, donors):
    refs = []
    for role in manifest['role_sources']:
        if set(role) != {'entity_id', 'donor_id', 'reference_id'}:
            raise ReuseError('explicit_named_role_source_required')
        donor = donors[role['donor_id']]
        matches = [r for r in donor['references'] if r['reference_id'] == role['reference_id']]
        if (len(matches) != 1 or matches[0]['kind'] != 'character' or matches[0]['view'] != 'front'
                or matches[0]['entity_id'] != role['entity_id']
                or 'canonical_identity' not in matches[0]['roles']):
            raise ReuseError('exact_reviewed_donor_character_front_required')
        refs.append((role['donor_id'], matches[0]))
    environment = manifest['environment']
    if set(environment) != {'donor_id', 'entity_id', 'view', 'canonical_reference', 'shot_reference'}:
        raise ReuseError('single_donor_environment_scope_required')
    donor = donors[environment['donor_id']]
    for field, expected_view in [('canonical_reference', 'front'), ('shot_reference', environment['view'])]:
        matches = [r for r in donor['references'] if r['reference_id'] == environment[field]]
        if (len(matches) != 1 or matches[0]['kind'] != 'place' or matches[0]['view'] != expected_view
                or matches[0]['entity_id'] != environment['entity_id'] or expected_view == 'layout'):
            raise ReuseError('single_donor_room_front_and_camera_required')
        refs.append((environment['donor_id'], matches[0]))
    if refs[-1][1]['design_version'] != refs[-2][1]['design_version']:
        raise ReuseError('room_front_and_camera_design_changed')
    if len({r['reference_id'] for _, r in refs}) != 5:
        raise ReuseError('three_canonical_roles_plus_two_room_views_required')
    return refs


def collect(manifest_path, segment_id):
    """Read current full-policy donors, then bind only this explicit new shot."""
    from . import visual_h3_reference_bundle_v20 as bundles
    path = Path(manifest_path).resolve()
    manifest, donors = _manifest(path)
    rows = [r for r in manifest['segments'] if r['id'] == segment_id]
    if len(rows) != 1:
        raise ReuseError('reuse_source_segment_missing')
    row = rows[0]; shot = row['source_shot']
    selected, proofs = [], {}
    for donor_id, original in _selection(manifest, donors):
        donor = donors[donor_id]; ref = deepcopy(original)
        ref['roles'] = (['canonical_identity', 'shot_character_view'] if ref['kind'] == 'character' else
                        ['canonical_environment'] if ref['view'] == 'front' else ['shot_environment_view'])
        ref['donor'] = dict(id=donor_id, asset_run=donor['asset_run'], source_shot=deepcopy(donor['source_shot']),
                            bundle=manifest['donors'][donor_id]['bundle'], bundle_sha256=donor['bundle_sha256'])
        selected.append(ref)
        available = {p['proof_id']: p for p in donor['asset_proofs']}
        pending = [ref['proof_id']]
        while pending:
            key = pending.pop(); proof = available[key]
            if key in proofs:
                if proofs[key] != proof:raise ReuseError('same_asset_donor_proofs_disagree')
                continue
            proofs[key] = deepcopy(proof); pending.extend(proof['dependencies'])
    room_donor = donors[manifest['environment']['donor_id']]
    env = manifest['environment']
    bundle = dict(schema=bundles.SCHEMA, reuse_contract=CONTRACT, reuse_manifest=_binding(path),
        reuse_segment_id=segment_id, asset_run=room_donor['asset_run'], asset_plan=room_donor['asset_plan'],
        book_id=manifest['book_id'], source=manifest['source'], packet_sha256=fingerprint(shot),
        source_shot=dict(id=segment_id,scene_id=shot['scene_id'],place_id=shot['place_id'],
            shot_sha256=fingerprint(shot),visible_cast=shot['visible_cast'],character_views=shot['character_views'],place_view=shot['place_view']),
        original_source_shot=deepcopy(shot), source_request=row['source_request'], source_prompt_file=row['source_prompt_file'],
        original_prompt_utf8_sha256=row['original_prompt_utf8_sha256'], adapted_prompt_utf8_sha256=row['adapted_prompt_utf8_sha256'],
        prompt_adaptation_audit=manifest['prompt_adaptation_audit'],prompt_approval=manifest['prompt_approval'],expected_delivery_run=row['delivery_run'],
        characters=[dict(entity_id=r['entity_id'],canonical_reference=r['reference_id'],shot_reference=r['reference_id'])
                    for r in selected if r['kind']=='character'],
        environment=dict(entity_id=env['entity_id'],scene_id=shot['scene_id'],canonical_reference=env['canonical_reference'],
                         shot_reference=env['shot_reference'],design_sha256=room_donor['environment']['design_sha256']),
        references=selected,asset_proofs=list(proofs.values()),reference_policy='visible_canonical_and_exact_shot_view/v20',
        tail_policy='auxiliary_only_never_replaces_global_references',reference_count=5,model_capacity_checked=False,
        media_generated=False,prompt_rewritten=False,production_approved=False,publication=False)
    bundle['bundle_sha256'] = fingerprint(bundle)
    return bundle


def validate(bundle):
    data = deepcopy(bundle); digest = data.pop('bundle_sha256', None)
    if bundle.get('reuse_contract') != CONTRACT or fingerprint(data) != digest:
        raise ReuseError('reused_bundle_changed')
    path = _check(bundle['reuse_manifest'])
    fresh = collect(path, bundle['reuse_segment_id'])
    if fresh != bundle:
        raise ReuseError('reused_bundle_no_longer_current')
    return fresh
