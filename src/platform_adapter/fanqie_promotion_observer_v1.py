"""Opt-in passive promotion metadata observation in one managed worker Page.

This is discovery evidence, not a promotion contract. Only already observed
XHR/fetch paths may be armed. No requests, storage or native bodies are
persisted. Only content-type response metadata and completed request body-size
metadata are read; request/authentication/aggregate headers are never read.
Native field names retain their original meaning (``id`` is not a task ID).
A managed owner must guard the supplied context before each action.
"""
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

VERSION = 'fanqie_promotion_observer/v1'
ORIGIN = 'https://kol.fanqieopen.com'
EXTRACTION_PROFILE = 'fanqie_promotion_observed_native_subset/20261116/v2'
PROMOTION_ENDPOINT = '/api/platform/promotion/plan/list/v:version'
ENUM_ENDPOINT = '/api/platform/kol/enum_config/v1'
PROMOTION_NATIVE_FIELDS = {'alias_name', 'task_type', 'alias_start_time',
                           'alias_end_time', 'alias_post_type'}
MAX_BODY_BYTES = 262144
MAX_CAPTURES = 8
MAX_ROWS = 50
MAX_RESOURCES = 128
MAX_OBSERVE_SECONDS = 60
MAX_DEPTH = 8
MAX_NODES = 3000
MAX_STRUCTURE_FIELDS = 256
SUBJECT_FIELDS = {'resource_id', 'binding_version', 'platform_identity_key',
                  'environment_key', 'owner_id', 'generation', 'task_id'}
CONTAINERS = {'data', 'result', 'payload', 'list', 'rows', 'items', 'records',
    'books', 'book_list', 'bookList', 'promotion_list', 'promotionList',
    'promotions', 'aliases', 'alias_list', 'aliasList', 'word_list', 'wordList',
    'words', 'tasks', 'task_list', 'taskList', 'detail', 'details', 'pagination'}
ANCHORS = {'book_id', 'bookId', 'bookID', 'novel_id', 'novelId', 'item_id',
    'book_name', 'bookName', 'book_title', 'bookTitle', 'novel_name',
    'promotion_alias', 'promotionAlias', 'alias', 'keyword', 'promotion_word',
    'promotionWord', 'word', 'alias_id', 'aliasId', 'promotion_id', 'promotionId',
    'platform_task_id', 'promotion_task_id', 'task_id', 'taskId'}
FIELDS = ANCHORS | {'id', 'name', 'title', 'promotion_path', 'promotionPath',
    'path', 'channel', 'channel_name', 'channelName', 'publish_type',
    'publishType', 'article_type', 'articleType', 'status', 'state',
    'alias_status', 'book_status', 'task_status', 'is_valid', 'isValid',
    'valid_from', 'valid_until', 'validFrom', 'validUntil', 'start_time',
    'end_time', 'startTime', 'endTime', 'expire_time', 'expireTime',
    'effective_time', 'effectiveTime', 'create_time', 'update_time',
    'created_at', 'updated_at', 'createdAt', 'updatedAt', 'promotion_status',
    'promotionStatus', 'promotion_type', 'promotionType'}
RESOURCE_JS = """() => performance.getEntriesByType('resource')
 .filter(e => ['fetch','xmlhttprequest'].includes(e.initiatorType))
 .map(e => {try {const u=new URL(e.name);return u.origin==='https://kol.fanqieopen.com'
   ? {origin:u.origin,path:u.pathname,initiator_type:e.initiatorType}:null;}catch(_){return null;}})
 .filter(Boolean).slice(-128)"""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _endpoint(url):
    try:
        u = urlsplit(url)
        if (u.scheme != 'https' or u.hostname != 'kol.fanqieopen.com'
                or u.port not in (None, 443) or u.username or u.password
                or not re.fullmatch(r'/[A-Za-z0-9_./:%-]{0,255}', u.path)):
            return None
        if re.search(r'(?i)/(?:auth|oauth|login|logout|token|session|cookie|credential|password|secret)(?:/|$)', u.path):
            return None
        return u.path
    except (TypeError, ValueError):
        return None


def _page_location(page):
    path = _endpoint(page.url)
    if path != '/page/promotion-list':
        raise ValueError('promotion_observer_requires_same_promotion_list_page')
    return {'origin': ORIGIN, 'path': path}


def validate_subject(value):
    if not isinstance(value, dict) or set(value) != SUBJECT_FIELDS:
        raise ValueError('promotion_observer_exact_managed_subject_required')
    if type(value['generation']) is not int or value['generation'] < 1:
        raise ValueError('promotion_observer_generation_invalid')
    for key in SUBJECT_FIELDS - {'generation'}:
        item = value[key]
        if (not isinstance(item, str) or not item.strip() or len(item) > 160
                or any(ord(c) < 32 for c in item)):
            raise ValueError('promotion_observer_subject_invalid')
    return dict(value)


def discover_resources(page):
    """Read performance entries only; never issues a request or navigation."""
    location = _page_location(page)
    raw = page.evaluate(RESOURCE_JS)
    if not isinstance(raw, list) or len(raw) > MAX_RESOURCES:
        raise ValueError('promotion_resource_inventory_invalid')
    found = set()
    for row in raw:
        if (not isinstance(row, dict) or row.get('origin') != ORIGIN
                or row.get('initiator_type') not in {'fetch', 'xmlhttprequest'}):
            continue
        path = _endpoint(ORIGIN + str(row.get('path', '')))
        if path is not None and path == row.get('path'):
            found.add((path, row['initiator_type']))
    return {'schema': 'fanqie_promotion_resource_inventory/v1',
            'page_location': location,
            'resources': [{'path': p, 'initiator_type': t} for p, t in sorted(found)],
            'query_values_saved': False, 'native_requests_issued': 0,
            'limitations': ['Existing performance entries have no response body.',
                            'Paths do not establish stable-ID semantics.']}


def _safe_scalar(key, value):
    if value is None or type(value) in (bool, int):
        if type(value) is int and len(str(value)) > 24:
            return False
        return True
    if not isinstance(value, str) or len(value) > (80 if key == 'id' else 200):
        return False
    if (any(ord(c) < 32 for c in value) or '://' in value
            or re.search(r'(?i)(bearer\s|(?:token|cookie|session|password|secret)\s*[=:])', value)
            or re.fullmatch(r'eyJ[A-Za-z0-9_.-]{30,}', value)):
        return False
    return True


def _allowed_field(name, value, record_path, endpoint_path):
    if name in FIELDS:
        return _safe_scalar(name, value)
    if (endpoint_path == PROMOTION_ENDPOINT
            and re.fullmatch(r'\$\.data\.promotion_list\[\d{1,2}\]', record_path)
            and name in PROMOTION_NATIVE_FIELDS):
        if name in {'task_type', 'alias_post_type'}:
            return type(value) is int and -(2 ** 31) <= value < 2 ** 31
        return isinstance(value, str) and _safe_scalar(name, value)
    if (endpoint_path == ENUM_ENDPOINT
            and re.fullmatch(r'\$\.data\.kol_alias_post_type\[\d{1,2}\]', record_path)):
        return ((name == 'text' and isinstance(value, str) and len(value) <= 80
                 and _safe_scalar(name, value))
                or (name == 'value' and type(value) is int and -(2 ** 31) <= value < 2 ** 31))
    return False


def _allowed_response_field(field, endpoint_path):
    if not isinstance(field, dict) or set(field) != {'name', 'path', 'value'}:
        return False
    if (endpoint_path in {PROMOTION_ENDPOINT, ENUM_ENDPOINT}
            and field['name'] == 'code' and field['path'] == '$.code'):
        return type(field['value']) is int and -(2 ** 31) <= field['value'] < 2 ** 31
    if (endpoint_path == PROMOTION_ENDPOINT and field['name'] == 'total'
            and field['path'] == '$.data.total'):
        return type(field['value']) is int and 0 <= field['value'] <= 10 ** 9
    return False


def sanitize_metadata(body, *, endpoint_path=None):
    """Keep native whitelisted scalar fields; do not infer or rename IDs."""
    if not isinstance(body, (dict, list)):
        raise ValueError('promotion_metadata_json_object_required')
    records, stats = [], {'visited_nodes': 0, 'omitted_fields': 0, 'truncated': False,
        'structure_nodes': 0, 'structure_truncated': False, 'filtered_structure_keys': 0}

    def walk(value, path, depth):
        stats['visited_nodes'] += 1
        if depth > MAX_DEPTH or stats['visited_nodes'] > MAX_NODES or len(records) >= MAX_ROWS:
            stats['truncated'] = True
            return
        if isinstance(value, list):
            for i, child in enumerate(value[:MAX_ROWS]):
                walk(child, path + '[' + str(i) + ']', depth + 1)
            if len(value) > MAX_ROWS:
                stats['truncated'] = True
        elif isinstance(value, dict):
            # A user/account object with only id/name is deliberately not a row.
            if set(value) & ANCHORS:
                fields = []
                for key, item in value.items():
                    if _allowed_field(key, item, path, endpoint_path):
                        fields.append({'name': key, 'path': path + '.' + key, 'value': item})
                    elif key not in CONTAINERS:
                        stats['omitted_fields'] += 1
                if fields:
                    records.append({'native_path': path, 'fields': fields})
            for key, child in value.items():
                if key in CONTAINERS and isinstance(child, (dict, list)):
                    walk(child, path + '.' + key, depth + 1)
    walk(body, '$', 0)
    # Only this observed enum container may expose text/value. Other enums,
    # arbitrary nested labels and generic IDs remain structure-only.
    data = body.get('data') if isinstance(body, dict) else None
    if endpoint_path == ENUM_ENDPOINT and isinstance(data, dict):
        items = data.get('kol_alias_post_type')
        if isinstance(items, list):
            for index, item in enumerate(items[:MAX_ROWS]):
                path = '$.data.kol_alias_post_type[' + str(index) + ']'
                if len(records) >= MAX_ROWS:
                    stats['truncated'] = True
                    break
                if (isinstance(item, dict) and set(item) == {'text', 'value'}
                        and all(_allowed_field(k, v, path, endpoint_path) for k, v in item.items())):
                    records.append({'native_path': path, 'fields': [
                        {'name': k, 'path': path + '.' + k, 'value': v} for k, v in item.items()]})
                else:
                    stats['omitted_fields'] += 1
            if len(items) > MAX_ROWS:
                stats['truncated'] = True
    response_fields = []
    if isinstance(body, dict):
        for field in [{'name': 'code', 'path': '$.code', 'value': body.get('code')},
                      {'name': 'total', 'path': '$.data.total',
                       'value': data.get('total') if isinstance(data, dict) else None}]:
            if _allowed_response_field(field, endpoint_path):
                response_fields.append(field)
    structure = []

    def shape(value, path, depth):
        stats['structure_nodes'] += 1
        if (depth > MAX_DEPTH or stats['structure_nodes'] > MAX_NODES
                or len(structure) >= MAX_STRUCTURE_FIELDS):
            stats['structure_truncated'] = True
            return
        kind = ('null' if value is None else 'boolean' if type(value) is bool
            else 'integer' if type(value) is int else 'number' if type(value) is float
            else 'string' if isinstance(value, str) else 'array' if isinstance(value, list)
            else 'object' if isinstance(value, dict) else 'unsupported')
        entry = {'path': path, 'type': kind}
        if isinstance(value, (dict, list)):
            entry['item_count'] = len(value)
        structure.append(entry)
        if isinstance(value, list):
            for i, child in enumerate(value[:MAX_ROWS]):
                shape(child, path + '[' + str(i) + ']', depth + 1)
            if len(value) > MAX_ROWS:
                stats['structure_truncated'] = True
        elif isinstance(value, dict):
            for key, child in value.items():
                if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}', key)
                        or re.search(r'(?i)(token|cookie|session|password|secret|credential|authorization|phone|mobile|email|nickname|avatar|^invite_|income|revenue|earnings?|thumbnail|thumb_url|cover_url|cursor|search_after)', key)):
                    stats['filtered_structure_keys'] += 1
                    continue
                shape(child, path + '.' + key, depth + 1)
    shape(body, '$', 0)
    result = {'schema': 'fanqie_promotion_sanitized_metadata/v1',
              'records': records, 'statistics': stats, 'structure': structure,
              'response_fields': response_fields, 'extraction_profile': EXTRACTION_PROFILE,
              'field_semantics': 'Original native names only; generic id/name/status are unclassified.',
              'native_body_saved': False, 'native_body_sha256': None}
    result['sanitized_sha256'] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


class PromotionObserver:
    def __init__(self, page, subject, endpoint_paths, *, page_id, clock=time.time):
        self.page, self.clock = page, clock
        self.subject = validate_subject(subject)
        self.page_id = page_id
        if not isinstance(page_id, str) or not page_id or len(page_id) > 160:
            raise ValueError('promotion_observer_worker_page_id_required')
        self.inventory = discover_resources(page)
        observed = {row['path'] for row in self.inventory['resources']}
        if (not isinstance(endpoint_paths, list) or not 1 <= len(endpoint_paths) <= 8
                or any(not isinstance(p, str) or p not in observed for p in endpoint_paths)
                or len(set(endpoint_paths)) != len(endpoint_paths)):
            raise ValueError('promotion_observer_endpoint_not_previously_observed')
        self.endpoint_paths = sorted(endpoint_paths)
        self.captures, self.skips = [], {}
        self.inflight = 0
        self.active = True
        self.armed_at = self.clock()
        page.on('requestfinished', self.on_request_finished)

    def _skip(self, code):
        self.skips[code] = self.skips.get(code, 0) + 1

    def on_request_finished(self, request):
        if not self.active:
            return
        if self.clock() - self.armed_at > MAX_OBSERVE_SECONDS:
            self._skip('observation_window_expired')
            self.active = False
            return
        reserved = False
        try:
            _page_location(self.page)
            path = _endpoint(request.url)
            if path not in self.endpoint_paths:
                return
            if (request.frame != self.page.main_frame
                    or request.resource_type not in {'xhr', 'fetch'}
                    or request.method not in {'GET', 'POST'}):
                return
            if len(self.captures) + self.inflight >= MAX_CAPTURES:
                self._skip('capture_limit_reached')
                return
            self.inflight += 1
            reserved = True
            response = request.response()
            if response is None:
                self._skip('finished_response_missing')
                return
            if _endpoint(response.url) != path or response.request.frame != self.page.main_frame:
                self._skip('finished_response_subject_mismatch')
                return
            if response.status != 200:
                self._skip('non_success_response')
                return
            # requestfinished is emitted after the complete body is downloaded.
            # sizes() reads numeric transport metadata, not header/postData values.
            # Never accesses aggregate headers or any request payload.
            content_type = response.header_value('content-type') or ''
            if content_type.split(';', 1)[0].strip().lower() not in {'application/json', 'text/json'}:
                self._skip('non_json_response')
                return
            sizes = request.sizes()
            size = sizes.get('responseBodySize') if isinstance(sizes, dict) else None
            if type(size) is not int or not 0 < size <= MAX_BODY_BYTES:
                self._skip('bounded_finished_response_size_required')
                return
            if self.clock() - self.armed_at > MAX_OBSERVE_SECONDS:
                self._skip('observation_window_expired')
                self.active = False
                return
            raw = response.body()
            if not isinstance(raw, bytes) or len(raw) > MAX_BODY_BYTES:
                self._skip('decoded_body_too_large')
                return
            metadata = sanitize_metadata(json.loads(raw), endpoint_path=path)
            if not metadata['records']:
                self._skip('no_whitelisted_values_structure_only')
            self.captures.append({'endpoint': {'origin': ORIGIN, 'path': path},
                'observed_at': self.clock(), 'status': 200,
                'resource_type': request.resource_type, 'method': request.method,
                'body_size_evidence': {'source': 'request.sizes.responseBodySize',
                    'completion_event': 'requestfinished', 'response_body_size': size,
                    'decoded_body_bytes': len(raw)},
                'metadata': metadata})
        except Exception as exc:
            # Exception messages can contain signed URLs/native body fragments.
            self._skip('response_unreadable_' + type(exc).__name__)
        finally:
            if reserved:
                self.inflight -= 1

    def stop(self):
        self.active = False
        remove = getattr(self.page, 'remove_listener', None)
        if callable(remove):
            remove('requestfinished', self.on_request_finished)
        return self.snapshot()

    def snapshot(self):
        return {'schema': VERSION, 'subject': dict(self.subject),
            'worker_page_id': self.page_id, 'page_location': _page_location(self.page),
            'armed_at': self.armed_at, 'observed_at': self.clock(),
            'active': self.active, 'endpoint_inventory': self.inventory,
            'selected_endpoint_paths': self.endpoint_paths,
            'captures': list(self.captures), 'skipped': dict(self.skips),
            'native_body_saved': False, 'native_body_sha256': None,
            'native_requests_issued': 0, 'query_values_saved': False,
            'managed_context_requires_caller_guard': True,
            'promotion_contract_verified': False,
            'limitations': ['Sanitized discovery subset; not an original native-body capture.',
                'Absent fields do not prove the platform lacks that concept.',
                'No stable task/alias/path/validity inference or production acceptance.']}


def worker_action(page, observers, page_id, *, mode, subject=None, endpoint_paths=None):
    """Typed worker dispatch; old actions and existing observers stay untouched."""
    if mode == 'resources':
        return discover_resources(page)
    if mode == 'arm':
        if page_id in observers:
            raise ValueError('promotion_observer_already_armed_stop_first')
        observers[page_id] = PromotionObserver(page, subject, endpoint_paths, page_id=page_id)
        return observers[page_id].snapshot()
    if mode not in {'snapshot', 'stop'} or page_id not in observers:
        raise ValueError('promotion_observer_mode_or_session_invalid')
    observer = observers[page_id]
    if validate_subject(subject) != observer.subject:
        raise ValueError('promotion_observer_managed_subject_changed')
    if mode == 'stop':
        result = observer.stop()
        del observers[page_id]
        return result
    return observer.snapshot()


def save_observation(output_path, evidence):
    """Persist the sanitized worker result only, under a fresh project data path."""
    root = Path(__file__).resolve().parents[2] / 'data'
    path = Path(output_path).resolve()
    if not path.is_relative_to(root) or path.exists():
        raise ValueError('new_project_data_evidence_path_required')
    allowed = {'schema', 'subject', 'worker_page_id', 'page_location', 'armed_at',
        'observed_at', 'active', 'endpoint_inventory', 'selected_endpoint_paths',
        'captures', 'skipped', 'native_body_saved', 'native_body_sha256',
        'native_requests_issued', 'query_values_saved',
        'managed_context_requires_caller_guard', 'promotion_contract_verified', 'limitations'}
    if (not isinstance(evidence, dict) or set(evidence) != allowed
            or evidence.get('schema') != VERSION
            or evidence.get('native_body_saved') is not False
            or evidence.get('native_body_sha256') is not None
            or evidence.get('native_requests_issued') != 0
            or evidence.get('query_values_saved') is not False
            or evidence.get('promotion_contract_verified') is not False):
        raise ValueError('sanitized_promotion_observation_required')
    validate_subject(evidence['subject'])
    captures = evidence.get('captures')
    if not isinstance(captures, list) or len(captures) > MAX_CAPTURES:
        raise ValueError('sanitized_capture_limit_invalid')
    for capture in captures:
        if (not isinstance(capture, dict) or set(capture) != {'endpoint',
                'observed_at', 'status', 'resource_type', 'method', 'metadata', 'body_size_evidence'}
                or capture['endpoint'].get('origin') != ORIGIN
                or _endpoint(ORIGIN + capture['endpoint'].get('path', '')) is None):
            raise ValueError('sanitized_capture_invalid')
        size = capture['body_size_evidence']
        if (not isinstance(size, dict) or set(size) != {'source', 'completion_event',
                'response_body_size', 'decoded_body_bytes'}
                or size['source'] != 'request.sizes.responseBodySize'
                or size['completion_event'] != 'requestfinished'
                or any(type(size[k]) is not int or not 0 < size[k] <= MAX_BODY_BYTES
                       for k in ('response_body_size', 'decoded_body_bytes'))):
            raise ValueError('sanitized_completed_size_evidence_invalid')
        metadata = capture['metadata']
        if (set(metadata) != {'schema', 'records', 'structure', 'statistics', 'field_semantics',
                'response_fields', 'extraction_profile',
                'native_body_saved', 'native_body_sha256', 'sanitized_sha256'}
                or metadata['schema'] != 'fanqie_promotion_sanitized_metadata/v1'
                or metadata['extraction_profile'] != EXTRACTION_PROFILE
                or metadata['native_body_saved'] is not False
                or metadata['native_body_sha256'] is not None
                or len(metadata['records']) > MAX_ROWS
                or len(metadata['structure']) > MAX_STRUCTURE_FIELDS
                or not isinstance(metadata['response_fields'], list)
                or len(metadata['response_fields']) > 2
                or any(not _allowed_response_field(f, capture['endpoint']['path'])
                       for f in metadata['response_fields'])):
            raise ValueError('sanitized_metadata_invalid')
        body = {k: v for k, v in metadata.items() if k != 'sanitized_sha256'}
        if hashlib.sha256(_canonical(body)).hexdigest() != metadata['sanitized_sha256']:
            raise ValueError('sanitized_metadata_changed')
        for field in metadata['structure']:
            if (set(field) not in ({'path', 'type'}, {'path', 'type', 'item_count'})
                    or field['type'] not in {'null', 'boolean', 'integer', 'number',
                        'string', 'array', 'object', 'unsupported'}
                    or not re.fullmatch(r'\$(?:\.[A-Za-z_][A-Za-z0-9_-]{0,63}|\[\d{1,3}\])*', field['path'])):
                raise ValueError('sanitized_structure_invalid')
        for record in metadata['records']:
            if set(record) != {'native_path', 'fields'}:
                raise ValueError('sanitized_record_invalid')
            for field in record['fields']:
                if (set(field) != {'name', 'path', 'value'}
                        or not _allowed_field(field['name'], field['value'],
                            record['native_path'], capture['endpoint']['path'])
                        or field['path'] != record['native_path'] + '.' + field['name']):
                    raise ValueError('sanitized_field_invalid')
    raw = _canonical(evidence)
    if len(raw) > 400000:
        raise ValueError('sanitized_promotion_observation_too_large')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
