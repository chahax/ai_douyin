"""Versioned, book-scoped voice candidates and explicit listening reviews.

This registry reads real WAV/FLAC waveforms. It never synthesizes, transcribes,
downloads, calls a service, or silently substitutes a default voice. A reviewed
reference is still a soft conditioning asset, not a hard speaker-identity lock.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

from . import visual_image_jobs_v3 as jobs

SCHEMA = 'voice_asset/v1'
REVIEW_SCHEMA = 'voice_asset_listening_review/v1'
BINDING_SCHEMA = 'voice_asset_binding/v1'
RESOLUTION_SCHEMA = 'voice_asset_resolution/v1'
REVIEW_CHECKS = ('audible_single_speaker', 'reference_text_matches',
                 'character_voice_matches', 'no_music_or_overlapping_speech')
PROJECT = Path(__file__).resolve().parents[2]


def _text(value, name, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or '\x00' in value:
        raise ValueError('invalid_' + name)
    return value


def _asset_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', value):
        raise ValueError('invalid_voice_asset_id')
    return value


def _version(value):
    if type(value) is not int or value < 1:
        raise ValueError('positive_voice_version_required')
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('invalid_voice_audio_sha256')
    return value


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _bind(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=_digest(path))


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _freeze(path, value):
    path = Path(path).resolve()
    if not path.is_relative_to(PROJECT):
        raise ValueError('voice_registry_writes_must_stay_in_project')
    if path.exists():
        if _read(path) != value:
            raise ValueError('immutable_voice_record_conflict')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def _library(path, *, writing=False):
    path = Path(path).resolve()
    if writing and not path.is_relative_to(PROJECT):
        raise ValueError('voice_registry_writes_must_stay_in_project')
    if writing:
        path.mkdir(parents=True, exist_ok=True)
        if not (path / 'VOICE_REGISTRY.lock').resolve().is_relative_to(path):
            raise ValueError('voice_registry_lock_scope_changed')
    return path


def inspect_audio(path, expected_sha256=None):
    """Decode all frames on CPU; a path/metadata claim is never a waveform."""
    import numpy as np
    import soundfile as sf

    path = Path(path).resolve()
    if path.suffix.lower() not in ('.wav', '.flac') or not path.is_file():
        raise ValueError('existing_WAV_or_FLAC_waveform_required')
    before = _digest(path)
    if expected_sha256 is not None and before != _sha(expected_sha256):
        raise ValueError('voice_audio_sha256_mismatch')
    try:
        with sf.SoundFile(path) as stream:
            container = stream.format
            allowed = ('WAV', 'WAVEX', 'RF64') if path.suffix.lower() == '.wav' else ('FLAC',)
            if container not in allowed or stream.channels not in (1, 2) or stream.samplerate <= 0 or stream.frames <= 0:
                raise ValueError('nonempty_mono_or_stereo_audio_required')
            frames, rate, channels, subtype = stream.frames, stream.samplerate, stream.channels, stream.subtype
            decoded = 0
            for block in stream.blocks(blocksize=16384, dtype='float32', always_2d=True):
                if not np.isfinite(block).all():
                    raise ValueError('nonfinite_audio_samples')
                decoded += len(block)
            if decoded != frames:
                raise ValueError('incomplete_audio_decode')
    except (OSError, RuntimeError) as error:
        raise ValueError('voice_waveform_decode_failed') from error
    if _digest(path) != before:
        raise ValueError('voice_audio_changed_during_read')
    return dict(path=str(path), sha256=before, format=container, subtype=subtype,
                sample_rate=rate, channels=channels, frames=frames,
                duration_seconds=frames / rate, waveform_decode_verified=True)


def _folder(library, asset_id, version):
    target = (library / 'assets' / _asset_id(asset_id) / ('v%06d' % _version(version))).resolve()
    if not target.is_relative_to(library):
        raise ValueError('voice_registry_asset_scope_changed')
    return target


def _review_evidence(decision, reviewer, checks, evidence, audio_sha256):
    if decision not in ('reviewed', 'rejected'):
        raise ValueError('explicit_voice_review_decision_required')
    _text(reviewer, 'reviewer'); _sha(audio_sha256)
    if (not isinstance(evidence, dict) or evidence.get('audio_sha256') != audio_sha256
            or not isinstance(evidence.get('observations'), list) or not evidence['observations']
            or any(not isinstance(v, str) or not v.strip() for v in evidence['observations'])):
        raise ValueError('version_audio_bound_listening_evidence_required')
    if (decision == 'reviewed' and (evidence.get('listening_performed') is not True
            or not isinstance(checks, dict) or any(checks.get(key) is not True for key in REVIEW_CHECKS))):
        raise ValueError('explicit_listening_and_all_voice_checks_required')
    if not isinstance(checks, dict):
        raise ValueError('explicit_voice_review_checks_required')


def _present(path):
    row = _read(path)
    if row.get('schema') != SCHEMA or row.get('status') != 'candidate':
        raise ValueError('immutable_candidate_voice_record_required')
    if Path(path) != _folder(Path(path).parents[3], row['asset_id'], row['version']) / 'record.json':
        raise ValueError('voice_record_scope_changed')
    audio = row['audio']
    expected = Path(path).parent / ('audio' + Path(audio['path']).suffix.lower())
    if Path(audio['path']).resolve() != expected.resolve() or inspect_audio(expected, audio['sha256']) != audio:
        raise ValueError('stored_voice_waveform_or_metadata_changed')
    value = deepcopy(row)
    value.update(registry_record=_bind(path), status='candidate', review=None,
                 voice_identity_locked=False, production_approved=False)
    events = sorted((Path(path).parent / 'reviews').glob('*.json'))
    for number, event_path in enumerate(events, 1):
        event = _read(event_path)
        if (event.get('schema') != REVIEW_SCHEMA or event.get('sequence') != number
                or event.get('record') != value['registry_record'] or event.get('audio_sha256') != audio['sha256']
                or event.get('decision') not in ('reviewed', 'rejected')):
            raise ValueError('voice_review_event_or_version_changed')
        _review_evidence(event['decision'], event.get('reviewer'), event.get('checks'),
                         event.get('evidence'), audio['sha256'])
        value.update(status=event['decision'], review=dict(event, binding=_bind(event_path)))
    return value


def get(library, *, book_id, asset_id=None, version=None, character_id=None):
    """Read only. A missing library is not created."""
    library = _library(library); _text(book_id, 'book_id')
    if asset_id is not None:
        _asset_id(asset_id)
    if version is not None:
        _version(version)
    if character_id is not None:
        _text(character_id, 'character_id')
    rows = []
    for path in sorted((library / 'assets').glob('*/v*/record.json')):
        raw = _read(path)
        if (raw.get('book_id') != book_id or asset_id is not None and raw.get('asset_id') != asset_id
                or version is not None and raw.get('version') != version
                or character_id is not None and raw.get('character_id') != character_id):
            continue
        rows.append(_present(path))
    return sorted(rows, key=lambda row: (row['asset_id'], row['version']))


def register_candidate(library, audio_path, *, book_id, character_id, reference_text,
                       source, voice_description='', asset_id=None, expected_sha256=None):
    _text(book_id, 'book_id'); _text(character_id, 'character_id'); _text(reference_text, 'reference_text')
    _text(voice_description, 'voice_description', empty=True)
    if not isinstance(source, dict) or not source or not isinstance(source.get('kind'), str):
        raise ValueError('explicit_voice_source_provenance_required')
    _text(source['kind'], 'voice_source_kind')
    json.dumps(source, ensure_ascii=False)
    observed = inspect_audio(audio_path, expected_sha256)
    identity = _asset_id(asset_id or uuid.uuid5(uuid.NAMESPACE_URL, 'voice:' + book_id + ':' + character_id).hex)
    library = _library(library, writing=True)
    with jobs.run_lock(library, 'VOICE_REGISTRY.lock'):
        existing = []
        for path in sorted((library / 'assets' / identity).glob('v*/record.json')):
            old = _present(path)
            if old['book_id'] != book_id or old['character_id'] != character_id:
                raise ValueError('voice_asset_id_cannot_change_book_or_character')
            existing.append(old)
            if (old['audio']['sha256'] == observed['sha256'] and old['reference_text'] == reference_text
                    and old['source'] == source and old['voice_description'] == voice_description):
                return old
        occupied = [int(p.name[1:]) for p in (library / 'assets' / identity).glob('v*')
                    if p.is_dir() and re.fullmatch(r'v[0-9]{6,}', p.name)]
        version = max([r['version'] for r in existing] + occupied, default=0) + 1
        folder = _folder(library, identity, version); folder.mkdir(parents=True, exist_ok=False)
        target = folder / ('audio' + Path(audio_path).suffix.lower())
        shutil.copyfile(audio_path, target)
        stored = inspect_audio(target, observed['sha256'])
        record = dict(schema=SCHEMA, asset_id=identity, version=version, book_id=book_id,
                      character_id=character_id, status='candidate', audio=stored,
                      reference_text=reference_text, voice_description=voice_description,
                      source=deepcopy(source), original_audio=dict(path=observed['path'], sha256=observed['sha256']),
                      registered_at=datetime.now(timezone.utc).isoformat(),
                      production_approved=False, voice_identity_locked=False)
        _freeze(folder / 'record.json', record)
        return _present(folder / 'record.json')


def review(library, *, book_id, asset_id, version, audio_sha256, decision, reviewer, checks, evidence):
    _review_evidence(decision, reviewer, checks, evidence, audio_sha256)
    library = _library(library, writing=True)
    with jobs.run_lock(library, 'VOICE_REGISTRY.lock'):
        rows = get(library, book_id=book_id, asset_id=asset_id, version=version)
        if len(rows) != 1 or rows[0]['audio']['sha256'] != audio_sha256:
            raise ValueError('exact_voice_candidate_version_required')
        row = rows[0]; folder = _folder(library, asset_id, version) / 'reviews'
        events = sorted(folder.glob('*.json'))
        payload = dict(decision=decision, reviewer=reviewer, checks=checks, evidence=evidence)
        if events:
            latest = _read(events[-1])
            if all(latest.get(k) == v for k, v in payload.items()):
                return dict(latest, binding=_bind(events[-1]))
        event = dict(schema=REVIEW_SCHEMA, sequence=len(events) + 1, record=row['registry_record'],
                     audio_sha256=audio_sha256, reviewed_at=datetime.now(timezone.utc).isoformat(), **deepcopy(payload))
        target = folder / ('%06d.json' % event['sequence']); _freeze(target, event)
        return dict(event, binding=_bind(target))


def make_binding(library, *, book_id, character_id, asset_id, version):
    rows = get(library, book_id=book_id, character_id=character_id, asset_id=asset_id, version=version)
    if len(rows) != 1 or rows[0]['status'] != 'reviewed':
        raise ValueError('reviewed_voice_required_for_fixed_binding')
    row = rows[0]
    return dict(schema=BINDING_SCHEMA, book_id=book_id, character_id=character_id,
                voice_asset_id=asset_id, version=version, audio_sha256=row['audio']['sha256'],
                registry_record=row['registry_record'], review_event=row['review']['binding'])


def resolve_speakers(library, *, book_id, speaker_ids, bindings, mode='voice_required'):
    """Resolve only explicitly pinned voices; never a default adult substitute."""
    if mode not in ('voice_required', 'prompt_only'):
        raise ValueError('explicit_supported_voice_control_mode_required')
    _text(book_id, 'book_id')
    if not isinstance(speaker_ids, (list, tuple)) or not isinstance(bindings, dict):
        raise ValueError('explicit_speaker_ids_and_bindings_required')
    speakers = list(dict.fromkeys(_text(s, 'speaker_id') for s in speaker_ids))
    value = dict(schema=RESOLUTION_SCHEMA, status='ready', control_mode=mode, voices=[], notices=[],
                 requested_speaker_ids=speakers, voice_identity_locked=False, production_approved=False,
                 actual_waveform_references_required=mode == 'voice_required', fallback_used=False,
                 reference_conditioning_verified=False)
    if mode == 'prompt_only':
        value['reference_conditioning_verified'] = False
        return value
    if len(speakers) > 3:
        value['notices'].append(dict(code='voice_reference_capacity_exceeded', requested=len(speakers), maximum=3,
                                     action='split_speaking_turns_without_truncation'))
    for speaker in speakers:
        selected = bindings.get(speaker)
        try:
            if (not isinstance(selected, dict) or selected.get('schema') != BINDING_SCHEMA
                    or selected.get('book_id') != book_id or selected.get('character_id') != speaker):
                raise ValueError('fixed_character_voice_binding_missing')
            rows = get(library, book_id=book_id, character_id=speaker,
                       asset_id=selected['voice_asset_id'], version=selected['version'])
            if len(rows) != 1:
                raise ValueError('bound_voice_asset_missing')
            row = rows[0]
            if row['status'] != 'reviewed':
                raise ValueError('bound_voice_not_reviewed:' + row['status'])
            if make_binding(library, book_id=book_id, character_id=speaker,
                            asset_id=row['asset_id'], version=row['version']) != selected:
                raise ValueError('voice_binding_audio_record_or_review_changed')
            value['voices'].append(dict(speaker_id=speaker, slot=len(value['voices']),
                tag='<Audio %d>' % (len(value['voices']) + 1), binding=deepcopy(selected),
                audio={k:row['audio'][k] for k in ('path', 'sha256')}, audio_metadata=deepcopy(row['audio']),
                reference_text=row['reference_text'], voice_description=row['voice_description']))
        except (ValueError, OSError, KeyError, TypeError) as error:
            value['notices'].append(dict(code=str(error), speaker_id=speaker, action='provide_and_confirm_matching_voice_asset'))
    if value['notices']:
        value.update(status='missing_notice', voices=[])
    return value
