"""CPU protocol fixtures; accepted test receipts are not real visual approvals."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_h3_reference_bundle_v20 as refs
from src.content_factory import visual_asset_pipeline_v3 as pipeline
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory.visual_shot_binding_v3 import fingerprint


def picture(path, color):
    Image.new('RGB', (32, 48), color).save(path)
    return path


def accepted(lib, row, *, known=True, source=True):
    result = dict(decision='accepted', target_sha256=row['sha256'], completion_known=known,
                  outcome_unknown=not known, checks={k: True for k in library.REVIEW_CHECKS[row['kind']]},
                  visual_evidence=['CPU protocol fixture; no actual visual claim'])
    evidence = dict(image_sha256=row['sha256'], observations=result['visual_evidence'])
    if source:
        evidence.update(source_review=deepcopy(result), review=fingerprint(result))
    return library.review(lib, book_id=row['book_id'], asset_id=row['asset_id'], version=row['version'],
                          file_sha256=row['sha256'], decision='accepted', reviewer='protocol-test-only',
                          checks=result['checks'], evidence=evidence)


@pytest.fixture
def setup(tmp_path):
    lib = tmp_path / 'library'
    script = tmp_path / 'script.md'
    script.write_text('A child and an adult speak in a room. The narrator stays offscreen.', encoding='utf-8')
    source = dict(path=str(script), sha256=pipeline.file_sha(script))
    packet = dict(schema='visual_asset_packet/v3', book_id='book1', source=source,
                  characters=[dict(id='adult', name='成人甲', design_version='v1'),
                              dict(id='child', name='儿童乙', design_version='v1'),
                              dict(id='voice_only', name='画外声', design_version='v1')],
                  places=[dict(id='room', name='旧居', design_version='room-v1')],
                  scenes=[dict(id='scene1', place_id='room', cast=['adult', 'child', 'voice_only'])],
                  shots=[dict(id='shot1', scene_id='scene1', place_id='room', place_view='side',
                              visible_cast=['adult', 'child'], character_views={'adult': 'left_profile', 'child': 'front'},
                              visual_prompt='The child hands a bag to the adult.',
                              audio=[dict(speaker='voice_only', mode='voiceover', text='A memory returns.')])])
    run = tmp_path / 'asset_run'
    pipeline.prepare(run, packet, dict(library=str(lib)))
    rows = {}

    def add(entity_id, kind, view, *, color='gray', reviewed=True, deps=None, known=True,
            evidence_source=True, book='book1', manifest=None):
        design = 'room-v1' if kind == 'place' else 'v1'
        source_file = picture(tmp_path / f'{entity_id}_{view}_{color}_{book}.png', color)
        provenance = dict(source=source, dependencies=deps or [], dependency_fingerprint=fingerprint(deps or []))
        if manifest:
            provenance.update(manifest_path=str(manifest), manifest_sha256=pipeline.file_sha(manifest))
        row = library.register(lib, source_file, book_id=book, entity_id=entity_id, kind=kind, view=view,
                               design_version=design, provenance=provenance)
        if reviewed:
            row = accepted(lib, row, known=known, source=evidence_source)
        rows[(entity_id, view)] = row
        return row

    adult = add('adult', 'character', 'front')
    add('adult', 'character', 'left_profile', color='red', deps=[pipeline._asset_identity(adult)])
    add('child', 'character', 'front', color='green')
    room = add('room', 'place', 'front', color='blue')
    add('room', 'place', 'side', color='yellow', deps=[pipeline._asset_identity(room)])
    return dict(run=run, lib=lib, packet=packet, rows=rows, add=add, tmp=tmp_path)


def all_files(root):
    return {str(p): (p.stat().st_mtime_ns, pipeline.file_sha(p)) for p in root.rglob('*') if p.is_file()}


def test_collect_canonical_and_exact_views_in_stable_order_without_writes(setup, monkeypatch):
    s = setup
    before = all_files(s['tmp'])
    monkeypatch.setattr(pipeline, 'write', lambda *a, **k: pytest.fail('collector wrote pipeline state'))
    monkeypatch.setattr(pipeline, 'freeze', lambda *a, **k: pytest.fail('collector froze a new artifact'))
    bundle = refs.collect(s['run'], 'shot1', expected_book_id='book1')
    assert [(r['kind'], r['entity_id'], r['view']) for r in bundle['references']] == [
        ('character', 'adult', 'front'), ('character', 'adult', 'left_profile'),
        ('character', 'child', 'front'), ('place', 'room', 'front'), ('place', 'room', 'side')]
    child = bundle['references'][2]
    assert child['roles'] == ['canonical_identity', 'shot_character_view']
    assert bundle['characters'][1]['canonical_reference'] == bundle['characters'][1]['shot_reference']
    assert all(r['entity_id'] != 'voice_only' for r in bundle['references'])
    assert len(bundle['asset_proofs']) == 5
    assert bundle['tail_policy'] == 'auxiliary_only_never_replaces_global_references'
    assert bundle['model_capacity_checked'] is False
    assert bundle['production_approved'] is False and bundle['publication'] is False
    assert refs.validate(bundle) == bundle
    assert all_files(s['tmp']) == before


def test_unrelated_new_asset_does_not_stale_selected_shot_bundle(setup):
    s = setup
    bundle = refs.collect(s['run'], 'shot1')
    s['add']('unrelated_role', 'character', 'front', color='purple')
    assert refs.validate(bundle) == bundle


def test_newer_candidate_cannot_fall_back_to_old_accepted_canonical(setup):
    s = setup
    s['add']('adult', 'character', 'front', color='pink', reviewed=False)
    with pytest.raises(ValueError, match='not_currently_reviewed'):
        refs.collect(s['run'], 'shot1')


def test_canonical_is_required_even_if_requested_view_is_accepted(setup):
    s = setup
    row = s['rows'][('adult', 'front')]
    library.review(s['lib'], book_id='book1', asset_id=row['asset_id'], version=row['version'],
                   file_sha256=row['sha256'], decision='unavailable', reviewer='protocol-provider',
                   checks={}, evidence=dict(reason='provider unavailable'))
    with pytest.raises(ValueError, match='not_currently_reviewed'):
        refs.collect(s['run'], 'shot1')


def test_changed_dependency_version_invalidates_old_view_and_bundle(setup):
    s = setup
    bundle = refs.collect(s['run'], 'shot1')
    s['add']('adult', 'character', 'front', color='pink')
    with pytest.raises(ValueError, match='not_currently_reviewed'):
        refs.validate(bundle)


@pytest.mark.parametrize('known,evidence_source', [(False, True), (True, False)])
def test_status_reviewed_without_known_sha_bound_source_review_is_insufficient(setup, known, evidence_source):
    s = setup
    s['add']('child', 'character', 'front', color='orange', known=known, evidence_source=evidence_source)
    with pytest.raises(ValueError, match='complete_review_required'):
        refs.collect(s['run'], 'shot1')


def test_cross_book_and_wrong_view_lookup_is_defensively_rejected(setup, monkeypatch):
    s = setup
    original = pipeline._lookup
    def wrong(plan, req, *args, **kwargs):
        row = original(plan, req, *args, **kwargs)
        if req['entity_id'] == 'adult' and req['view'] == 'front':
            row['book_id'] = 'other-book'
        return row
    monkeypatch.setattr(pipeline, '_lookup', wrong)
    with pytest.raises(refs.ReferenceBundleError, match='cross_book'):
        refs.collect(s['run'], 'shot1')


def test_asset_pixels_and_review_receipt_tamper_are_rejected(setup):
    s = setup
    bundle = refs.collect(s['run'], 'shot1')
    proof = bundle['asset_proofs'][0]
    record = Path(proof['review_record']['path'])
    original = record.read_bytes()
    record.write_text('{}')
    with pytest.raises(ValueError, match='review_record_changed'):
        refs.validate(bundle)
    record.write_bytes(original)
    Path(proof['image']['path']).write_bytes(b'not original image')
    with pytest.raises(ValueError, match='asset_file_changed'):
        refs.validate(bundle)


def test_source_script_and_source_shot_binding_are_verified(setup):
    s = setup
    bundle = refs.collect(s['run'], 'shot1')
    assert bundle['source_shot']['shot_sha256'] == fingerprint(s['packet']['shots'][0])
    with pytest.raises(refs.ReferenceBundleError, match='source_book_scope_changed'):
        refs.collect(s['run'], 'shot1', expected_book_id='wrong-book')
    with pytest.raises(refs.ReferenceBundleError, match='source_shot_not_found'):
        refs.collect(s['run'], 'missing-shot')
    Path(bundle['source']['path']).write_text('script revised')
    with pytest.raises(ValueError, match='script_changed'):
        refs.validate(bundle)


def test_bundle_role_or_source_shot_edits_fail_own_digest(setup):
    bundle = refs.collect(setup['run'], 'shot1')
    for change in (lambda x: x['references'].append(deepcopy(x['references'][0])),
                   lambda x: x['source_shot'].update(scene_id='another_scene')):
        bad = deepcopy(bundle)
        change(bad)
        with pytest.raises(refs.ReferenceBundleError, match='bundle_changed'):
            refs.validate(bad)


@pytest.mark.parametrize('change,message', [
    (lambda x: x['shots'][0].update(character_views={'adult': 'left_profile'}), 'exact_view'),
    (lambda x: x['shots'][0].update(place_view='layout'), 'scene_camera'),
    (lambda x: x['shots'][0].update(scene_id='wrong_scene'), 'outside_source_scene'),
    (lambda x: x['shots'][0].update(audio=[dict(mode='onscreen', speaker='voice_only')]), 'onscreen_audio'),
])
def test_scene_membership_and_offscreen_audio_never_expand_camera_cast(setup, change, message):
    packet = deepcopy(setup['packet'])
    change(packet)
    with pytest.raises(refs.ReferenceBundleError, match=message):
        refs._shot(packet, 'shot1')


def test_three_visible_people_and_same_pixel_roles_are_preserved_without_implicit_cap(setup):
    s = setup
    packet = deepcopy(s['packet'])
    packet['characters'].append(dict(id='twin_child', name='独立双胞胎角色', design_version='v1'))
    packet['scenes'][0]['cast'].append('twin_child')
    shot = packet['shots'][0]
    shot['visible_cast'].append('twin_child')
    shot['character_views']['twin_child'] = 'front'
    # Same actual pixels; independent named role and registry identity.
    s['add']('twin_child', 'character', 'front', color='green')
    run = s['tmp'] / 'three_people_run'
    pipeline.prepare(run, packet, dict(library=str(s['lib'])))
    bundle = refs.collect(run, 'shot1')
    chars = [r for r in bundle['references'] if r['kind'] == 'character']
    assert [(r['entity_id'], r['view']) for r in chars] == [('adult', 'front'), ('adult', 'left_profile'),
                                                         ('child', 'front'), ('twin_child', 'front')]
    assert chars[-1]['image']['sha256'] == chars[-2]['image']['sha256']
    assert chars[-1]['reference_id'] != chars[-2]['reference_id']
    assert chars[-1]['asset_id'] != chars[-2]['asset_id']
    assert bundle['reference_count'] == 6 and bundle['model_capacity_checked'] is False


def test_new_accepted_review_invalidates_old_bundle_even_same_image_version(setup):
    s = setup
    bundle = refs.collect(s['run'], 'shot1')
    row = s['rows'][('child', 'front')]
    event = deepcopy(row['review'])
    source = event['evidence']['source_review']
    source['visual_evidence'] = ['different completed protocol review']
    evidence = deepcopy(event['evidence'])
    evidence.update(source_review=source, review=fingerprint(source), observations=source['visual_evidence'])
    library.review(s['lib'], book_id='book1', asset_id=row['asset_id'], version=row['version'],
                   file_sha256=row['sha256'], decision='accepted', reviewer='protocol-new-review',
                   checks=event['checks'], evidence=evidence)
    with pytest.raises(refs.ReferenceBundleError, match='no_longer_current'):
        refs.validate(bundle)


def test_wrong_exact_view_cannot_be_substituted_by_canonical_or_same_pixel_asset(setup, monkeypatch):
    s = setup
    original = pipeline._lookup
    def wrong(plan, req, *args, **kwargs):
        if req['entity_id'] == 'adult' and req['view'] == 'left_profile':
            return original(plan, dict(req, view='front'), *args, **kwargs)
        return original(plan, req, *args, **kwargs)
    monkeypatch.setattr(pipeline, '_lookup', wrong)
    with pytest.raises(refs.ReferenceBundleError, match='exact_view_changed'):
        refs.collect(s['run'], 'shot1')


def test_no_requested_view_fallback_when_exact_view_missing(setup, monkeypatch):
    s = setup
    original = pipeline._lookup
    def missing(plan, req, *args, **kwargs):
        if req['kind'] == 'place' and req['view'] == 'side':
            return None
        return original(plan, req, *args, **kwargs)
    monkeypatch.setattr(pipeline, '_lookup', missing)
    with pytest.raises(refs.ReferenceBundleError, match='reference_missing:room/side'):
        refs.collect(s['run'], 'shot1')


def test_canonical_front_missing_is_not_replaced_by_reviewed_requested_view(setup, monkeypatch):
    s = setup
    original = pipeline._lookup
    def missing(plan, req, *args, **kwargs):
        if req['entity_id'] == 'adult' and req['view'] == 'front':
            return None
        return original(plan, req, *args, **kwargs)
    monkeypatch.setattr(pipeline, '_lookup', missing)
    with pytest.raises(refs.ReferenceBundleError, match='reference_missing:adult/front'):
        refs.collect(s['run'], 'shot1')


def test_import_manifest_and_asset_source_files_are_bound(setup):
    s = setup
    manifest = s['tmp'] / 'IMPORT_SOURCE.json'
    manifest.write_text('{"fixture":"immutable import evidence"}')
    s['add']('child', 'character', 'front', color='purple', manifest=manifest)
    bundle = refs.collect(s['run'], 'shot1')
    proof = next(x for x in bundle['asset_proofs'] if x['entity_id'] == 'child')
    assert {x['role'] for x in proof['provenance_files']} == {'asset_source', 'import_manifest'}
    manifest.write_text('{"fixture":"changed"}')
    with pytest.raises(refs.ReferenceBundleError, match='evidence_file_changed'):
        refs.validate(bundle)


def test_zero_visible_people_keeps_both_environment_views_without_voice_cast_assets(setup):
    s = setup
    packet = deepcopy(s['packet'])
    packet['shots'][0].update(visible_cast=[], character_views={})
    run = s['tmp'] / 'empty_camera_run'
    pipeline.prepare(run, packet, dict(library=str(s['lib'])))
    bundle = refs.collect(run, 'shot1')
    assert bundle['characters'] == []
    assert [(r['entity_id'], r['view']) for r in bundle['references']] == [('room', 'front'), ('room', 'side')]
