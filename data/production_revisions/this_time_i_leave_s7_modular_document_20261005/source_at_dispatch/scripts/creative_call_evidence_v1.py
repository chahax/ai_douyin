"""Append-only evidence for one synchronous text call; no credentials or dispatch."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

VERSION = 'creative_call_evidence/v1'

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def atomic_create(path, data):
    path = Path(path)
    if path.exists():
        raise FileExistsError('immutable evidence already exists: '+path.name)
    temporary = path.with_name(path.name+'.tmp_'+uuid.uuid4().hex)
    try:
        with temporary.open('xb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link publishes an already-flushed file without overwriting a peer.
        os.link(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

class CallEvidenceJournal:
    def __init__(self, root, identity, *, create=True):
        self.root = Path(root).resolve()
        self.identity = deepcopy(identity)
        self.identity_sha256 = digest(identity)
        self.secrets = ()
        if create:
            self.root.mkdir(parents=True, exist_ok=False)
            self._json('IDENTITY.json', {'schema': VERSION, 'identity': self.identity,
                                       'identity_sha256': self.identity_sha256})
            self.record('call_prepared', {'provider_received_request': None})
        else:
            stored = read(self.root/'IDENTITY.json')
            if stored['schema'] != VERSION or stored['identity'] != identity or stored['identity_sha256'] != self.identity_sha256:
                raise RuntimeError('call evidence identity changed')
            self.events()

    def register_secrets(self, *values):
        self.secrets = tuple(v for v in values if isinstance(v, str) and v)

    def protect(self, raw):
        result = raw
        for value in self.secrets:
            for spelling in (value, json.dumps(value, ensure_ascii=False)[1:-1]):
                result = result.replace(spelling.encode('utf-8'), b'[REDACTED]')
        return result, result != raw

    def _json(self, name, value):
        data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')+b'\n'
        safe, redacted = self.protect(data)
        if redacted:
            # Metadata is not an original response, so redact before publication.
            data = safe
        atomic_create(self.root/name, data)

    def events(self):
        result = []
        for index, path in enumerate(sorted(self.root.glob('event_[0-9]*.json')), 1):
            if path.name != f'event_{index:04}.json':
                raise RuntimeError('evidence event sequence incomplete')
            event = read(path)
            if event['identity_sha256'] != self.identity_sha256 or event['sequence'] != index:
                raise RuntimeError('evidence event identity changed')
            result.append(event)
        return result

    def record(self, phase, details=None):
        if not re.fullmatch('[a-z_]{1,64}', phase):
            raise ValueError('safe evidence phase required')
        sequence = len(self.events())+1
        self._json(f'event_{sequence:04}.json', {'schema': VERSION, 'sequence': sequence,
            'identity_sha256': self.identity_sha256, 'at_utc': datetime.now(timezone.utc).isoformat(),
            'phase': phase, 'details': deepcopy(details or {})})

    def save_body(self, raw, http_metadata):
        if not isinstance(raw, bytes):
            raise TypeError('original HTTP bytes required')
        protected, redacted = self.protect(raw)
        atomic_create(self.root/'response_body.raw', protected)
        manifest = {'schema': VERSION, 'identity_sha256': self.identity_sha256,
            'body_file': 'response_body.raw', 'stored_sha256': hashlib.sha256(protected).hexdigest(),
            'original_sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(protected),
            'body_complete': True, 'raw_bytes_preserved': not redacted,
            'credential_redacted': redacted, 'http_metadata': json.loads(self.protect(json.dumps(http_metadata,ensure_ascii=False).encode('utf-8'))[0])}
        self._json('RESPONSE_BODY_MANIFEST.json', manifest)
        self.record('response_body_saved', {'stored_sha256': manifest['stored_sha256'],
                                         'body_complete': True, 'credential_redacted': redacted})
        return protected, manifest

    def load_body(self):
        manifest = read(self.root/'RESPONSE_BODY_MANIFEST.json')
        if manifest['schema'] != VERSION or manifest['identity_sha256'] != self.identity_sha256 or manifest['body_file'] != 'response_body.raw':
            raise RuntimeError('response body identity changed')
        path = self.root/manifest['body_file']
        if path.resolve().parent != self.root:
            raise RuntimeError('response body escaped evidence directory')
        raw = path.read_bytes()
        if len(raw) != manifest['bytes'] or hashlib.sha256(raw).hexdigest() != manifest['stored_sha256'] or manifest['body_complete'] is not True:
            raise RuntimeError('response body evidence changed or incomplete')
        if manifest['raw_bytes_preserved'] and manifest['original_sha256'] != manifest['stored_sha256']:
            raise RuntimeError('original body proof changed')
        return raw, manifest
