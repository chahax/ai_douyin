"""CPU-only synthetic waveforms. No fixture is a real child's accepted voice."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.content_factory import voice_asset_registry_v1 as v


def waveform(path, *, rate=16000, channels=1, frequency=220):
    # Merely a deterministic test signal, never asserted to contain speech.
    data = .12 * np.sin(2 * np.pi * frequency * np.arange(rate // 5) / rate)
    if channels == 2:
        data = np.column_stack((data, data))
    sf.write(path, data, rate, subtype='PCM_16')
    return path


def candidate(tmp_path, character='child_a', *, file=None, library=None, **changes):
    args = dict(book_id='novel', character_id=character, reference_text='Synthetic fixture transcript placeholder.',
                source=dict(kind='synthetic_CPU_fixture_not_human_voice'), voice_description='test signal, not an audition')
    args.update(changes)
    return v.register_candidate(library or tmp_path / 'voice_library', file or waveform(tmp_path / (character + '.wav')), **args)


def confirm(tmp_path, row, decision='reviewed', **changes):
    args = dict(book_id=row['book_id'], asset_id=row['asset_id'], version=row['version'],
                audio_sha256=row['audio']['sha256'], decision=decision, reviewer='explicit_CPU_fixture_only',
                checks={name: True for name in v.REVIEW_CHECKS},
                evidence=dict(audio_sha256=row['audio']['sha256'], listening_performed=True,
                              observations=['Controlled test review; no real voice or child identity assertion.']))
    args.update(changes)
    return v.review(tmp_path / 'voice_library', **args)


def binding(tmp_path, row):
    return v.make_binding(tmp_path / 'voice_library', book_id=row['book_id'], character_id=row['character_id'],
                          asset_id=row['asset_id'], version=row['version'])


def resolve(tmp_path, speakers, bindings, **changes):
    return v.resolve_speakers(tmp_path / 'voice_library', book_id='novel', speaker_ids=speakers,
                              bindings=bindings, **changes)


def test_missing_lookup_and_resolution_do_not_create_a_library(tmp_path):
    path = tmp_path / 'voice_library'
    assert v.get(path, book_id='novel') == [] and not path.exists()
    result = resolve(tmp_path, ['child_a'], {})
    assert result['status'] == 'missing_notice' and result['voices'] == [] and not path.exists()
    assert result['fallback_used'] is False


@pytest.mark.parametrize('extension', ['wav', 'flac'])
def test_actual_waveform_metadata_and_imported_bytes_are_preserved(tmp_path, extension):
    path = waveform(tmp_path / ('sample.' + extension), rate=24000, channels=2)
    row = candidate(tmp_path, file=path)
    assert row['status'] == 'candidate' and row['audio']['sample_rate'] == 24000
    assert row['audio']['channels'] == 2 and row['audio']['frames'] == 4800
    assert row['audio']['duration_seconds'] == .2 and row['audio']['waveform_decode_verified'] is True
    assert Path(row['audio']['path']).read_bytes() == path.read_bytes()
    assert row['voice_identity_locked'] is False and row['production_approved'] is False


def test_same_import_is_idempotent_and_changed_voice_is_a_new_version(tmp_path):
    path = waveform(tmp_path / 'first.wav'); first = candidate(tmp_path, file=path)
    assert candidate(tmp_path, file=path) == first
    second = candidate(tmp_path, file=waveform(tmp_path / 'other.wav', frequency=330))
    assert second['asset_id'] == first['asset_id'] and second['version'] == 2
    assert Path(first['registry_record']['path']).exists() and Path(first['audio']['path']).exists()


def test_candidate_cannot_be_bound_or_used_in_voice_required_mode(tmp_path):
    row = candidate(tmp_path)
    with pytest.raises(ValueError, match='reviewed_voice_required'):
        binding(tmp_path, row)
    fake = dict(schema=v.BINDING_SCHEMA, book_id='novel', character_id='child_a',
                voice_asset_id=row['asset_id'], version=1, audio_sha256=row['audio']['sha256'])
    result = resolve(tmp_path, ['child_a'], {'child_a': fake})
    assert result['status'] == 'missing_notice' and result['voices'] == []
    assert any('candidate' in n['code'] for n in result['notices'])


def test_review_needs_explicit_listening_and_version_audio_evidence(tmp_path):
    row = candidate(tmp_path)
    with pytest.raises(ValueError, match='explicit_listening'):
        confirm(tmp_path, row, evidence=dict(audio_sha256=row['audio']['sha256'], listening_performed=False, observations=['not heard']))
    with pytest.raises(ValueError, match='version_audio_bound'):
        confirm(tmp_path, row, evidence=dict(audio_sha256='0' * 64, listening_performed=True, observations=['wrong version']))
    assert v.get(tmp_path / 'voice_library', book_id='novel')[0]['status'] == 'candidate'


def test_review_events_append_and_rejection_invalidates_prior_binding(tmp_path):
    row = candidate(tmp_path); event = confirm(tmp_path, row); fixed = binding(tmp_path, row)
    assert confirm(tmp_path, row) == event
    assert resolve(tmp_path, ['child_a'], {'child_a': fixed})['status'] == 'ready'
    rejected = confirm(tmp_path, row, decision='rejected')
    assert rejected['sequence'] == 2 and Path(event['binding']['path']).exists()
    assert resolve(tmp_path, ['child_a'], {'child_a': fixed})['status'] == 'missing_notice'


def test_exact_version_is_pinned_instead_of_automatically_taking_new_candidate(tmp_path):
    first = candidate(tmp_path); confirm(tmp_path, first); fixed = binding(tmp_path, first)
    candidate(tmp_path, file=waveform(tmp_path / 'second.wav', frequency=440))
    resolved = resolve(tmp_path, ['child_a', 'child_a'], {'child_a': fixed})
    assert resolved['status'] == 'ready' and len(resolved['voices']) == 1
    assert resolved['voices'][0]['binding']['version'] == 1 and resolved['voices'][0]['tag'] == '<Audio 1>'


def test_three_independent_waveform_slots_and_four_speakers_are_not_truncated(tmp_path):
    fixed = {}
    for cid in ('a', 'b', 'c', 'd'):
        row = candidate(tmp_path, cid); confirm(tmp_path, row); fixed[cid] = binding(tmp_path, row)
    result = resolve(tmp_path, ['a', 'b', 'c'], fixed)
    assert result['status'] == 'ready' and [r['slot'] for r in result['voices']] == [0, 1, 2]
    assert all(Path(r['audio']['path']).is_file() for r in result['voices'])
    overflow = resolve(tmp_path, ['a', 'b', 'c', 'd'], fixed)
    assert overflow['status'] == 'missing_notice' and overflow['voices'] == []
    assert any(r['code'] == 'voice_reference_capacity_exceeded' for r in overflow['notices'])


def test_wrong_character_or_book_does_not_get_another_or_adult_default_voice(tmp_path):
    row = candidate(tmp_path, 'adult'); confirm(tmp_path, row); fixed = binding(tmp_path, row)
    result = resolve(tmp_path, ['child_a'], {'child_a': fixed})
    assert result['status'] == 'missing_notice' and not result['voices'] and not result['fallback_used']
    changed = deepcopy(fixed); changed['book_id'] = 'different'
    assert resolve(tmp_path, ['adult'], {'adult': changed})['status'] == 'missing_notice'


def test_prompt_only_is_explicit_and_never_claims_a_waveform_or_locked_identity(tmp_path):
    result = resolve(tmp_path, ['child_a'], {}, mode='prompt_only')
    assert result['status'] == 'ready' and result['control_mode'] == 'prompt_only'
    assert not result['voices'] and result['voice_identity_locked'] is False
    assert result['reference_conditioning_verified'] is False and result['actual_waveform_references_required'] is False


def test_mutated_stored_audio_or_forged_metadata_is_not_resolvable(tmp_path):
    row = candidate(tmp_path); confirm(tmp_path, row); fixed = binding(tmp_path, row)
    Path(row['audio']['path']).write_bytes(b'not audio')
    assert resolve(tmp_path, ['child_a'], {'child_a': fixed})['status'] == 'missing_notice'


def test_invalid_missing_or_metadata_only_audio_is_rejected_before_registration(tmp_path):
    path = tmp_path / 'fake.wav'; path.write_text('{"sample_rate":16000,"duration":2}', encoding='utf-8')
    with pytest.raises(ValueError): candidate(tmp_path, file=path)
    with pytest.raises(ValueError): candidate(tmp_path, file=tmp_path / 'absent.flac')
    assert not (tmp_path / 'voice_library').exists()


def test_nonfinite_waveform_and_wrong_hash_are_rejected(tmp_path):
    path = tmp_path / 'nan.wav'; sf.write(path, np.array([float('nan'), .1]), 16000, subtype='FLOAT')
    with pytest.raises(ValueError, match='nonfinite'):
        candidate(tmp_path, file=path)
    valid = waveform(tmp_path / 'good.wav')
    with pytest.raises(ValueError, match='sha256_mismatch'):
        candidate(tmp_path, file=valid, expected_sha256='0' * 64)


def test_audio_copy_stays_usable_when_original_source_changes(tmp_path):
    path = waveform(tmp_path / 'source.wav'); row = candidate(tmp_path, file=path)
    path.write_bytes(b'original source removed or changed')
    confirm(tmp_path, row); result = resolve(tmp_path, ['child_a'], {'child_a': binding(tmp_path, row)})
    assert result['status'] == 'ready'
    assert hashlib.sha256(Path(result['voices'][0]['audio']['path']).read_bytes()).hexdigest() == row['audio']['sha256']


def test_directly_edited_review_cannot_claim_reviewed_without_listening(tmp_path):
    row = candidate(tmp_path); event = confirm(tmp_path, row); fixed = binding(tmp_path, row)
    path = Path(event['binding']['path']); data = json.loads(path.read_text(encoding='utf-8'))
    data['evidence']['listening_performed'] = False; path.write_text(json.dumps(data), encoding='utf-8')
    result = resolve(tmp_path, ['child_a'], {'child_a': fixed})
    assert result['status'] == 'missing_notice' and result['voices'] == []


def test_forged_container_metadata_is_not_an_actual_voice_waveform(tmp_path):
    row = candidate(tmp_path); confirm(tmp_path, row); fixed = binding(tmp_path, row)
    path = Path(row['registry_record']['path']); data = json.loads(path.read_text(encoding='utf-8'))
    data['audio']['sample_rate'] = 99999; path.write_text(json.dumps(data), encoding='utf-8')
    assert resolve(tmp_path, ['child_a'], {'child_a': fixed})['status'] == 'missing_notice'


def test_asset_id_cannot_be_reassigned_to_a_different_character(tmp_path):
    first = candidate(tmp_path)
    with pytest.raises(ValueError, match='cannot_change_book_or_character'):
        candidate(tmp_path, 'other_child', asset_id=first['asset_id'])
    assert v.get(tmp_path / 'voice_library', book_id='novel')[0]['character_id'] == 'child_a'


def test_abandoned_local_version_directory_is_preserved_not_overwritten(tmp_path):
    first = candidate(tmp_path)
    orphan = Path(first['registry_record']['path']).parent.parent / 'v000002'; orphan.mkdir()
    (orphan / 'partial_evidence.txt').write_text('Preserve incomplete local import.', encoding='utf-8')
    third = candidate(tmp_path, file=waveform(tmp_path / 'new.wav', frequency=660))
    assert third['version'] == 3 and (orphan / 'partial_evidence.txt').is_file()
