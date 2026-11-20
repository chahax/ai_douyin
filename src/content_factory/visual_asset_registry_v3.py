"""Book-scoped immutable image versions, compatible with the v2 INDEX layout.

Registration is not visual approval. Queries do not create files. A review is an
append-only, image/version-bound event and never grants final video approval.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from PIL import Image
from .visual_review_scope_v4 import verify_scope

CHARACTER_VIEWS = ('front', 'left_oblique', 'right_oblique', 'left_profile',
                   'right_profile', 'back', 'face', 'clothing', 'hands')
PLACE_VIEWS = ('front', 'reverse', 'side', 'layout')
VIEW_ALIASES = {'front_full': 'front', 'face_detail': 'face', 'back_full': 'back',
                'clothing_detail': 'clothing', 'hands_detail': 'hands'}
REVIEW_CHECKS = {'character': ('identity', 'view', 'clothing', 'anatomy'),
                 'place': ('layout', 'view', 'consistency', 'artifact_free')}
DECISIONS = {'accepted': 'reviewed', 'rejected': 'rejected',
             'repair_required': 'candidate', 'unavailable': 'candidate'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _hash(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _text(value, name):
    value = str(value) if value is not None else ''
    if not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid_' + name)
    return value


def _sha(value, name='sha256'):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError('invalid_' + name)
    return value.lower()


def _view(kind, view, *, legacy=False):
    if kind not in REVIEW_CHECKS:
        raise ValueError('invalid_asset_kind')
    view = VIEW_ALIASES.get(view, view)
    if not isinstance(view, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', view):
        raise ValueError('invalid_view')
    if kind == 'character' and view not in CHARACTER_VIEWS and not legacy:
        raise ValueError('unsupported_character_view')
    return view


def _image(path, expected=None):
    path = Path(path).resolve()
    if (path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp') or
            not path.is_file() or path.stat().st_size > 50 * 1024 * 1024):
        raise ValueError('invalid_image_file')
    with Image.open(path) as image:
        image.verify()
    observed = _hash(path)
    if expected is not None and observed != _sha(expected):
        raise ValueError('asset_sha_mismatch')
    return path, observed


def _atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _immutable(path, value):
    if path.exists():
        if _read(path) != value:
            raise ValueError('immutable_record_conflict')
        return
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _lock(library, timeout=30):
    """Uses the v2 EXECUTION.lock protocol; only explicit mutations acquire it."""
    library.mkdir(parents=True, exist_ok=True)
    with (library / 'EXECUTION.lock').open('a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError('asset_library_busy') from None
                time.sleep(.025)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _index(library):
    path = library / 'INDEX.json'
    if not path.exists():
        return {'assets': [], 'reviews': []}
    index = _read(path)
    if not isinstance(index, dict) or not isinstance(index.get('assets'), list):
        raise ValueError('invalid_asset_index')
    index.setdefault('reviews', [])
    if not isinstance(index['reviews'], list):
        raise ValueError('invalid_review_index')
    keys = []
    for row in index['assets']:
        if (not isinstance(row,dict) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',str(row.get('asset_id','')))
                or type(row.get('version')) is not int or row['version']<1):
            raise ValueError('invalid_asset_version_record')
        for name in ('book_id','entity_id'):_text(row.get(name),name)
        _sha(row.get('sha256'))
        _view(row.get('kind'),row.get('view'),legacy=True)
        keys.append((row['asset_id'],row['version']))
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate_asset_version')
    return index


def _asset_file(library, row):
    path = (library / row['file']).resolve()
    if not path.is_relative_to(library) or not path.is_file():
        raise ValueError('asset_file_missing_or_outside_library')
    if _hash(path) != row['sha256']:
        raise ValueError('asset_file_changed')
    record = library / f"{row['asset_id']}_v{row['version']}.json"
    if not record.is_file() or _read(record) != row:
        raise ValueError('asset_record_changed_or_missing')
    return path


def _normalized(row):
    """v2 rows are readable candidates, never implicitly reviewed."""
    result = deepcopy(row)
    result['view'] = _view(row['kind'], row['view'], legacy=True)
    result.setdefault('design_version', 'legacy')
    result.setdefault('input_sha256', row['sha256'])
    result.setdefault('identity_group', row['entity_id'])
    return result


def review_target(row):
    row = _normalized(row)
    return digest({k: row[k] for k in ('asset_id', 'version', 'book_id', 'entity_id',
        'kind', 'view', 'design_version', 'input_sha256', 'identity_group', 'sha256')})


def _needs_detail_scope(evidence):
    source=evidence.get('source_review') if isinstance(evidence,dict) else None
    scope=source.get('view_scope') if isinstance(source,dict) else None
    return isinstance(scope,dict) and scope.get('canonical_roi_required') is True


def _present(library, index, row, verify_file=True):
    result = _normalized(row)
    path=(library/row['file']).resolve()
    if not path.is_relative_to(library):raise ValueError('asset_outside_library')
    result['path'] = str(_asset_file(library, row) if verify_file else path)
    result.update(status='candidate', production_approved=False, review=None,
                  review_target=review_target(row))
    for event in index['reviews']:
        if event.get('target') != result['review_target']:
            continue
        expected_keys={'target','asset_id','version','book_id','file_sha256','decision','reviewer','checks','evidence'}
        if not re.fullmatch(r'[0-9a-f]{64}',str(event.get('review_id',''))):raise ValueError('invalid_review_identity')
        if digest({k:event.get(k) for k in expected_keys})!=event['review_id']:
            raise ValueError('review_payload_changed')
        if (event.get('asset_id')!=row['asset_id'] or event.get('version')!=row['version']
                or event.get('book_id')!=row['book_id'] or event.get('file_sha256')!=row['sha256']):
            raise ValueError('review_scope_mismatch')
        _review_payload(row,event['decision'],event['reviewer'],event['checks'],event['evidence'])
        record = library / 'reviews' / (event['review_id'] + '.json')
        if not record.is_file() or _read(record) != event:
            raise ValueError('review_record_changed_or_missing')
        result['status'] = DECISIONS[event['decision']]
        result['review'] = deepcopy(event)
    latest=result.get('review') or {}
    if result['status']=='reviewed' and _needs_detail_scope(latest.get('evidence')):
        try:_detail_lineage(library,index,row,latest['evidence'])
        except ValueError as error:
            if str(error) not in ('detail_canonical_version_changed','detail_canonical_not_currently_reviewed'):
                raise
            result.update(status='candidate',dependency_stale=True,dependency_error=str(error))
    return result


def get(library, *, book_id, asset_id=None, version=None, entity_id=None, kind=None,
        view=None, design_version=None, input_sha256=None, identity_group=None,
        status=None, verify_file=True):
    library = Path(library).resolve()
    book_id = _text(book_id, 'book_id')
    index = _index(library)
    if asset_id is not None and any(a['asset_id'] == asset_id and a['book_id'] != book_id for a in index['assets']):
        raise ValueError('asset_scope_mismatch')
    if view is not None:
        view = VIEW_ALIASES.get(view, view)
    result = []
    filters = {'asset_id': asset_id, 'version': version, 'entity_id': entity_id,
               'kind': kind, 'view': view, 'design_version': design_version,
               'input_sha256': input_sha256,'identity_group':identity_group}
    for row in index['assets']:
        normalized = _normalized(row)
        if row['book_id'] != book_id or any(v is not None and normalized.get(k) != v for k,v in filters.items()):
            continue
        value = _present(library, index, row, verify_file)
        if status is None or value['status'] == status:
            result.append(value)
    return sorted(result, key=lambda a: (a['entity_id'], a['kind'], a['view'], a['version']))


def _prepare(image_path, *, book_id, entity_id, kind, view, design_version='v1',
             input_sha256=None, expected_sha256=None, identity_group=None, provenance=None):
    book_id = _text(book_id, 'book_id')
    entity_id = _text(entity_id, 'entity_id')
    view = _view(kind, view)
    path, file_sha = _image(image_path, expected_sha256)
    provenance = deepcopy(provenance or {})
    # Accept only serializable evidence, and pin it independently of caller mutation.
    digest(provenance)
    return dict(path=path, book_id=book_id, entity_id=entity_id, kind=kind, view=view,
        design_version=_text(design_version, 'design_version'),
        input_sha256=_sha(input_sha256, 'input_sha256') if input_sha256 is not None else file_sha,
        sha256=file_sha, identity_group=_text(entity_id if identity_group is None else identity_group, 'identity_group'),
        provenance=provenance)


def _register_prepared(library, prepared):
    created = 0
    with _lock(library):
        index = _index(library)
        rows = []
        for item in prepared:
            slot = {k:item[k] for k in ('book_id','entity_id','kind','view')}
            prior = [a for a in index['assets'] if all(_normalized(a)[k] == v for k,v in slot.items())]
            key = {**slot, **{k:item[k] for k in ('design_version','input_sha256','identity_group','sha256')}}
            same = [a for a in prior if all(_normalized(a).get(k)==v for k,v in key.items())]
            if same:
                row = same[-1]
                _asset_file(library, row)
                rows.append(row)
                continue
            asset_id = prior[0]['asset_id'] if prior else digest(slot)[:32]
            version = max((a['version'] for a in prior), default=0) + 1
            # Same-book old data may supply an identical immutable blob; no needless copy.
            reusable = next((a for a in index['assets'] if a['book_id']==item['book_id'] and a['sha256']==item['sha256']), None)
            if reusable:
                _asset_file(library, reusable)
                filename = reusable['file']
            else:
                filename = f"{asset_id}_v{version}{item['path'].suffix.lower()}"
                destination = library / filename
                if destination.exists():
                    if _hash(destination) != item['sha256']:
                        raise ValueError('orphan_asset_conflict')
                else:
                    with item['path'].open('rb') as source, destination.open('xb') as dest:
                        shutil.copyfileobj(source, dest)
                    if _hash(destination) != item['sha256']:
                        raise ValueError('source_changed_during_copy')
            row = {k:v for k,v in item.items() if k != 'path'}
            row.update(schema='visual_asset/v3', asset_id=asset_id, version=version,
                       file=filename, production_approved=False)
            _immutable(library / f'{asset_id}_v{version}.json', row)
            index['assets'].append(row)
            rows.append(row)
            created += 1
        if created:
            index['registry_version'] = 3
            _atomic(library / 'INDEX.json', index)
        return {'assets': [_present(library,index,row) for row in rows],
                'created_count':created,'reused_count':len(rows)-created}


def register(library, image_path, **kwargs):
    """Idempotent by scope, design, input and output; returns one current row."""
    item = _prepare(image_path, **kwargs)
    return _register_prepared(Path(library).resolve(), [item])['assets'][0]


def _scoped_review(row,evidence,checks):
    """Check the immutable review receipt; current lineage is rechecked separately."""
    source=evidence.get('source_review') or {}
    scope=verify_scope(source.get('view_scope'),row['view'])
    if (row['kind']!='character' or source.get('decision')!='accepted' or
            source.get('target_sha256')!=row['sha256'] or source.get('completion_known') is not True or
            source.get('outcome_unknown') is not False or evidence.get('review')!=digest(source)):
        raise ValueError('detail_review_receipt_not_bound')
    observed=source.get('checks',{})
    if (set(observed)!=set(REVIEW_CHECKS['character']) or
            any(type(v) is not bool and v is not None for v in observed.values()) or
            any(v is False for v in observed.values()) or
            any(observed.get(k) is not True or checks.get(k) is not True for k in scope['required'])):
        raise ValueError('required_detail_visual_checks_not_passed')
    if checks!={k:v for k,v in observed.items() if type(v) is bool}:
        raise ValueError('detail_review_checks_changed')
    return source


def _detail_lineage(library,index,row,evidence):
    """Independently bind scoped details to a current reviewed canonical and crop."""
    source=evidence['source_review'];crop=source.get('reference_roi_evidence') or {}
    origin=crop.get('roi_source') or {}
    if (set(origin)!={'asset_id','version','image_sha256','review_sha256'} or
            crop.get('roi_name')!=row['view'] or crop.get('coordinate_system')!='source_pixels' or
            crop.get('roi_source_sha256')!=digest(origin)):
        raise ValueError('detail_canonical_lineage_required')
    candidates=[a for a in index['assets'] if a['book_id']==row['book_id'] and a['entity_id']==row['entity_id'] and
        a['kind']=='character' and a['view']=='front' and a.get('design_version','legacy')==row.get('design_version','legacy')]
    if not candidates:raise ValueError('detail_canonical_missing')
    canonical=max(candidates,key=lambda a:a['version'])
    if (canonical['asset_id']!=origin['asset_id'] or canonical['version']!=origin['version'] or
            canonical['sha256']!=origin['image_sha256'] or source.get('reference_sha256')!=canonical['sha256'] or
            crop.get('source_sha256')!=canonical['sha256']):
        raise ValueError('detail_canonical_version_changed')
    provenance=row.get('provenance',{})
    parent_keys=('asset_id','version','entity_id','kind','view','design_version','sha256')
    generated=any(all(dep.get(k)==canonical.get(k) for k in parent_keys) for dep in provenance.get('dependencies',[]) if isinstance(dep,dict))
    if not generated and provenance.get('native_verified') is True and provenance.get('manifest_path'):
        manifest=Path(provenance['manifest_path'])
        if not manifest.is_file() or _hash(manifest)!=provenance.get('manifest_sha256'):
            raise ValueError('detail_generation_manifest_changed')
        items=[i for i in _read(manifest).get('items',[]) if i.get('character_id')==row['entity_id'] and
            i.get('view')==row['view'] and i.get('sha256')==row['sha256']]
        generated=len(items)==1 and items[0].get('ultimate_canonical_sha256')==canonical['sha256']
    if not generated:raise ValueError('detail_generation_lineage_unconfirmed')
    current=_present(library,index,canonical)
    event=current.get('review') or {};native=event.get('evidence',{}).get('source_review') or {}
    if (current['status']!='reviewed' or native.get('decision')!='accepted' or
            event['evidence'].get('review')!=digest(native) or digest(native)!=origin['review_sha256'] or
            native.get('target_sha256')!=canonical['sha256'] or native.get('completion_known') is not True or
            native.get('outcome_unknown') is not False or
            any(native.get('checks',{}).get(k) is not True for k in REVIEW_CHECKS['character'])):
        raise ValueError('detail_canonical_not_currently_reviewed')
    roi=crop.get('pixel_roi')
    if (not isinstance(roi,dict) or set(roi)!={'x','y','width','height'} or
            any(type(v) is not int for v in roi.values()) or min(roi['x'],roi['y'])<0 or
            min(roi['width'],roi['height'])<1 or native.get('rois',{}).get(row['view'])!=roi):
        raise ValueError('detail_roi_not_from_reviewed_canonical')
    with Image.open(current['path']) as image:
        if (crop.get('source_dimensions')!=list(image.size) or roi['x']+roi['width']>image.width or
                roi['y']+roi['height']>image.height):raise ValueError('detail_roi_outside_canonical')
        output=io.BytesIO();image.convert('RGB').crop((roi['x'],roi['y'],roi['x']+roi['width'],roi['y']+roi['height'])).save(output,format='PNG')
    if hashlib.sha256(output.getvalue()).hexdigest()!=crop.get('crop_sha256'):
        raise ValueError('detail_source_crop_changed')
    return True


def _review_payload(row,decision,reviewer,checks,evidence):
    if decision not in DECISIONS or not isinstance(checks,dict) or any(type(v) is not bool for v in checks.values()):
        raise ValueError('invalid_visual_review')
    _text(reviewer,'reviewer')
    if not isinstance(evidence,dict) or not evidence:
        raise ValueError('review_evidence_required')
    if decision=='accepted':
        if _needs_detail_scope(evidence):
            _scoped_review(row,evidence,checks)
        elif any(checks.get(key) is not True for key in REVIEW_CHECKS[row['kind']]):
            raise ValueError('required_visual_checks_not_passed')
        observations=evidence.get('observations')
        valid=(isinstance(observations,str) and bool(observations.strip())) or (
            isinstance(observations,list) and bool(observations) and all(isinstance(x,str) and x.strip() for x in observations))
        if evidence.get('image_sha256')!=row['sha256'] or not valid:
            raise ValueError('visual_review_image_evidence_required')


def review(library, *, book_id, asset_id, version, file_sha256, decision,
           reviewer, checks, evidence, input_sha256=None, target=None,expected_review_sha256=None):
    library = Path(library).resolve()
    book_id = _text(book_id, 'book_id')
    with _lock(library):
        index = _index(library)
        matches = [a for a in index['assets'] if a['asset_id']==asset_id and a['version']==version]
        if len(matches)!=1 or matches[0]['book_id']!=book_id:
            raise ValueError('asset_scope_or_version_mismatch')
        row = matches[0]
        _asset_file(library,row)
        if expected_review_sha256 is not None and digest(_present(library,index,row).get('review'))!=_sha(expected_review_sha256):
            raise ValueError('stale_review_previous_event')
        _review_payload(row,decision,reviewer,checks,evidence)
        if decision=='accepted' and _needs_detail_scope(evidence):
            _detail_lineage(library,index,row,evidence)
        normalized = _normalized(row)
        if _sha(file_sha256) != row['sha256'] or (input_sha256 is not None and _sha(input_sha256) != normalized['input_sha256']):
            raise ValueError('stale_review_asset_binding')
        actual_target = review_target(row)
        if target is not None and target != actual_target:
            raise ValueError('stale_review_target')
        payload = dict(target=actual_target, asset_id=asset_id, version=version,
                       book_id=book_id, file_sha256=row['sha256'], decision=decision,
                       reviewer=reviewer, checks=deepcopy(checks), evidence=deepcopy(evidence))
        review_id = digest(payload)
        if not any(e['review_id']==review_id for e in index['reviews']):
            event = dict(payload,review_id=review_id,created_at=datetime.now(timezone.utc).isoformat())
            folder = library/'reviews';folder.mkdir(exist_ok=True)
            receipt=folder/(review_id+'.json')
            if receipt.exists():
                original=_read(receipt)
                if {k:v for k,v in original.items() if k not in ('created_at','review_id')}!=payload or original.get('review_id')!=review_id:
                    raise ValueError('immutable_review_conflict')
                event=original  # Crash after receipt, before INDEX: reuse the same event.
            else:_immutable(receipt,event)
            index['reviews'].append(event)
            _atomic(library/'INDEX.json',index)
        # Replaying an old accepted event cannot override a later rejection/unavailability.
        return _present(library,index,row)


def requirements_status(library, *, book_id, requirements, require_reviewed=True):
    """Latest matching version wins; never falls back past a newer candidate."""
    if not isinstance(requirements,list) or not requirements:
        raise ValueError('asset_requirements_required')
    result = dict(ready=True, complete=True, require_reviewed=bool(require_reviewed),
                  selected=[], missing=[], pending=[], rejected=[], errors=[])
    for requirement in requirements:
        kind = requirement.get('kind','character')
        views = requirement.get('views') or ([requirement['view']] if requirement.get('view') else
                list(CHARACTER_VIEWS if kind=='character' else PLACE_VIEWS))
        for view in views:
            key = dict(entity_id=_text(requirement.get('entity_id'),'entity_id'),kind=kind,view=_view(kind,view))
            filters = {k:requirement[k] for k in ('design_version','input_sha256','identity_group') if requirement.get(k) is not None}
            try:
                rows = get(library,book_id=book_id,**key,**filters)
            except (ValueError,OSError,KeyError) as error:
                result['errors'].append(dict(**key,reason=str(error)))
                continue
            if not rows:
                result['missing'].append(key)
                continue
            row = max(rows,key=lambda a:a['version'])
            if row['status']=='rejected':result['rejected'].append(dict(**key,asset_id=row['asset_id'],version=row['version']))
            elif require_reviewed and row['status']!='reviewed':result['pending'].append(dict(**key,asset_id=row['asset_id'],version=row['version']))
            else:result['selected'].append(row)
    result['complete'] = not (result['missing'] or result['errors'])
    result['ready'] = not (result['missing'] or result['pending'] or result['rejected'] or result['errors'])
    return result


def import_manifest(library, manifest_path, *, book_id, design_version='v1', verify_native=True):
    """Import a complete cast FINAL_MAP into this versioned library as candidates."""
    manifest_path=Path(manifest_path).resolve();home=manifest_path.parent
    manifest_bytes=manifest_path.read_bytes();manifest=json.loads(manifest_bytes.decode('utf-8'))
    manifest_sha=hashlib.sha256(manifest_bytes).hexdigest();items=manifest.get('items');cache={}
    if not isinstance(items,list) or not items or manifest.get('selected_images')!=len(items):
        raise ValueError('invalid_cast_manifest')
    source=manifest.get('source_script',{})
    if not source.get('path') or _hash(source['path'])!=_sha(source.get('sha256')):
        raise ValueError('cast_source_script_changed')
    source_text=Path(source['path']).read_text(encoding='utf-8')
    cast_cards=None
    if manifest.get('cast_plan_sha256') and _hash(home/'CAST_PLAN.json')!=manifest['cast_plan_sha256']:
        raise ValueError('cast_plan_changed')
    if manifest.get('cast_plan_sha256'):
        cast_cards={c['id']:c for c in _read(home/'CAST_PLAN.json')['characters']}
    slots=set();role_views={};prepared=[]
    for entry in items:
        cid=_text(entry.get('character_id'),'entity_id');view=_view('character',entry.get('view'))
        if (cid,view) in slots:raise ValueError('duplicate_cast_view')
        slots.add((cid,view));role_views.setdefault(cid,set()).add(view)
        facts=entry.get('source_facts')
        if facts is not None:
            if (not isinstance(facts,dict) or Path(facts.get('script','')).resolve()!=Path(source['path']).resolve()
                    or type(facts.get('start')) is not int or type(facts.get('end')) is not int
                    or not 0<=facts['start']<facts['end']<=len(source_text)
                    or source_text[facts['start']:facts['end']]!=facts.get('quote')):
                raise ValueError('cast_source_fact_binding_changed')
        if cast_cards is not None:
            if cid not in cast_cards or any(entry.get(k)!=cast_cards[cid].get(k) for k in
                    ('identity_group','source_facts','fact_age','visual_design_age')):
                raise ValueError('cast_character_card_mismatch')
        path=Path(entry['path']).resolve()
        if not path.is_relative_to(home):raise ValueError('cast_image_outside_manifest_scope')
        path,file_sha=_image(path,entry['sha256'])
        if verify_native:
            execution=_text(entry.get('execution_case'),'execution_case')
            if not re.fullmatch(r'[a-zA-Z0-9_-]+',execution):raise ValueError('unsafe_execution_case')
            folder=home/'cases'/execution;original=Path(entry['original_generated_path']).resolve()
            if not original.is_relative_to(folder.resolve()) or _hash(original)!=file_sha:
                raise ValueError('native_original_changed')
            workflow=Path(entry['workflow_path']).resolve()
            if not workflow.is_relative_to(folder.resolve()) or _hash(workflow)!=entry['workflow_sha256']:
                raise ValueError('native_workflow_changed')
            if execution not in cache:cache[execution]=(_read(folder/'HISTORY.json'),_read(workflow))
            history,graph=cache[execution];native=history.get(entry['prompt_id'],{})
            if not native.get('status',{}).get('completed') or native['status'].get('status_str')!='success':
                raise ValueError('native_generation_not_succeeded')
            if native.get('prompt',[None,None,None])[2]!=graph:raise ValueError('native_history_graph_changed')
            images=native.get('outputs',{}).get(entry['save_node'],{}).get('images',[])
            if original.name not in [x.get('filename') for x in images if x.get('type')=='output']:
                raise ValueError('native_save_node_mismatch')
            with Image.open(original) as image:
                if json.loads(image.info.get('prompt','null'))!=graph:raise ValueError('native_png_graph_changed')
        provenance=dict(manifest_path=str(manifest_path),manifest_sha256=manifest_sha,
            source_script=source, native_verified=bool(verify_native),
            execution_case=entry.get('execution_case'),prompt_id=entry.get('prompt_id'),
            save_node=entry.get('save_node'),source_facts=entry.get('source_facts'),
            source_production_approved=entry.get('production_approved',False))
        input_sha=digest(dict(source_script_sha256=source['sha256'],
            cast_plan_sha256=manifest.get('cast_plan_sha256'),source_facts=entry.get('source_facts'),
            inputs={k:entry.get(k) for k in ('reference_sha256','ultimate_canonical_sha256','prompt','seed')}))
        prepared.append(_prepare(path,book_id=book_id,entity_id=cid,kind='character',view=view,
            design_version=design_version,input_sha256=input_sha,expected_sha256=file_sha,
            identity_group=entry.get('identity_group') or cid,provenance=provenance))
    if any(views!=set(CHARACTER_VIEWS) for views in role_views.values()):raise ValueError('incomplete_nine_view_character')
    if manifest.get('characters')!=len(role_views):raise ValueError('cast_character_count_mismatch')
    if _hash(manifest_path)!=manifest_sha:raise ValueError('cast_manifest_changed_during_import')
    result=_register_prepared(Path(library).resolve(),prepared)
    result.update(manifest_sha256=manifest_sha,status='candidate_imported',
                  production_approved=False,native_verified=bool(verify_native))
    return result


import_current_cast = import_manifest
