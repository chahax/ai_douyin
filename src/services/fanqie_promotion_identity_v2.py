"""One versioned native-alias identity and evidence normalizer.

Pure local evidence parsing. No guessed task IDs, API calls or implicit DB
migration. Old snapshots retain their exact parser and authorization subject.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'fanqie_promotion_snapshot/v2'
VERSION = 'native_alias_v2'
EVIDENCE_SCHEMA = 'fanqie_promotion_evidence/v2'
PROMOTION_ENDPOINT = '/api/platform/promotion/plan/list/v:version'
ENUM_ENDPOINT = '/api/platform/kol/enum_config/v1'
NATIVE_FIELDS = ('alias_id','book_id','book_name','alias_name','alias_status','book_status',
                 'task_type','alias_start_time','alias_end_time','alias_post_type')
SCOPE = ('resource_id','binding_version','platform_identity_key','environment_key')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _ref(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('promotion_v2_project_evidence_required')
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def _read(reference):
    if not isinstance(reference,dict) or set(reference)!={'path','sha256'} or _ref(reference['path'])!=reference:
        raise ValueError('promotion_v2_bound_evidence_changed')
    return json.loads(Path(reference['path']).read_text(encoding='utf-8-sig'))


def _save(path,value):
    path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    if not path.is_relative_to(ROOT):raise ValueError('promotion_v2_project_evidence_required')
    data=canonical(value)
    try:
        with path.open('xb') as out:out.write(data)
    except FileExistsError:
        if path.read_bytes()!=data:raise ValueError('promotion_v2_existing_artifact_changed')
    return _ref(path)


def _member(snapshot,row):
    if not isinstance(row,dict) or row not in snapshot.get('rows',[]):
        raise ValueError('promotion_v2_row_not_in_snapshot')


def native_identity(snapshot,row):
    _member(snapshot,row)
    if (snapshot.get('schema')!=SCHEMA or row.get('native_kind')!='promotion_alias'
            or not isinstance(row.get('native_record_id'),str)
            or not re.fullmatch(r'[0-9]{1,24}',row['native_record_id'])
            or not isinstance(snapshot.get('platform_identity_key'),str) or not snapshot['platform_identity_key']):
        raise ValueError('promotion_v2_native_alias_identity_required')
    return dict(platform_identity_key=snapshot['platform_identity_key'],native_kind='promotion_alias',
                native_record_id=row['native_record_id'])


def native_identity_scope(snapshot,row):
    return hashlib.sha256(canonical(native_identity(snapshot,row))).hexdigest()


def authorization_subject(snapshot,row):
    _member(snapshot,row)
    if snapshot.get('schema')=='fanqie_promotion_snapshot/v1':
        return {k:row[k] for k in ('book_id','platform_task_id','alias_id','alias','promotion_path','publish_type')}
    return dict(schema='fanqie_promotion_authorization_subject/v2',identity=native_identity(snapshot,row),
        **{k:row[k] for k in ('book_id','book_name','alias','publish_type','workflow_kind','workflow_label')},
        raw_task_type=row['native_fields']['task_type'],task_type_semantics='unclassified',
        raw_alias_post_type=row['native_fields']['alias_post_type'])


def selection_key(snapshot,row):
    _member(snapshot,row)
    if snapshot.get('schema')=='fanqie_promotion_snapshot/v1':return row['platform_task_id']
    return 'native_alias:'+native_identity_scope(snapshot,row)


def _timestamp(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?',value):
        raise ValueError('promotion_v2_explicit_alias_datetime_required')
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()


def _capture_fields(capture):
    metadata=capture.get('metadata') or {}
    body={k:v for k,v in metadata.items() if k!='sanitized_sha256'}
    if (capture.get('status')!=200 or capture.get('method')!='GET'
            or capture.get('endpoint',{}).get('origin')!='https://kol.fanqieopen.com'
            or metadata.get('native_body_saved') is not False or metadata.get('native_body_sha256') is not None
            or metadata.get('schema')!='fanqie_promotion_sanitized_metadata/v1'
            or metadata.get('extraction_profile')!='fanqie_promotion_observed_native_subset/20261116/v2'
            or hashlib.sha256(canonical(body)).hexdigest()!=metadata.get('sanitized_sha256')
            or metadata.get('statistics',{}).get('truncated') is not False
            or metadata.get('statistics',{}).get('structure_truncated') is not False):
        raise ValueError('promotion_v2_native_observation_invalid')
    size=capture.get('body_size_evidence',{})
    if (size.get('source')!='request.sizes.responseBodySize' or size.get('completion_event')!='requestfinished'
            or any(type(size.get(k)) is not int or not 0<size[k]<=262144 for k in ('response_body_size','decoded_body_bytes'))):
        raise ValueError('promotion_v2_completed_size_evidence_required')
    controls=metadata.get('response_fields',[])
    codes=[x for x in controls if x.get('path')=='$.code']
    totals=[x for x in controls if x.get('path')=='$.data.total']
    if (len(codes)!=1 or codes[0]!=dict(name='code',path='$.code',value=0) or type(codes[0]['value']) is not int
            or len(codes)+len(totals)!=len(controls)
            or capture['endpoint']['path']==PROMOTION_ENDPOINT and (len(totals)!=1 or type(totals[0].get('value')) is not int or totals[0]['value']<0)
            or capture['endpoint']['path']==ENUM_ENDPOINT and totals):
        raise ValueError('promotion_v2_native_success_code_required')
    for record in metadata.get('records',[]):
        fields={}
        for field in record.get('fields',[]):
            key=field.get('name')
            if field.get('path')!=record['native_path']+'.'+str(key) or key in fields:
                raise ValueError('promotion_v2_native_field_path_conflict')
            fields[key]=field['value']
        yield record['native_path'],fields


def _derive(evidence,evidence_ref):
    # The exact values/enum semantics will be accepted only from the observed
    # native fields. This parser intentionally has no numeric status/type map.
    from src.operations_accounts.fanqie_managed_promotion_v1 import validate_snapshot as legacy_validate
    legacy=legacy_validate(_read(evidence['legacy_snapshot']))
    observation=_read(evidence['observation']);subject=evidence['managed_subject']
    from src.platform_adapter.fanqie_promotion_observer_v1 import validate_subject
    validate_subject(subject)
    if (observation.get('schema')!='fanqie_promotion_observer/v1' or observation.get('subject')!=subject
            or any(subject.get(k)!=legacy.get(k) for k in SCOPE)
            or observation.get('page_location')!={'origin':'https://kol.fanqieopen.com','path':'/page/promotion-list'}
            or observation.get('native_requests_issued')!=0 or observation.get('native_body_saved') is not False
            or type(subject.get('generation')) is not int or subject['generation']<1
            or not subject.get('owner_id') or not subject.get('task_id')
            or not 0<=observation.get('observed_at',0)-legacy['observed_at']<=60):
        raise ValueError('promotion_v2_managed_observation_subject_changed')
    natives={};enum_by_value={};enum_by_text={};totals=[];enum_sources={}
    for ci,capture in enumerate(observation.get('captures',[])):
        endpoint=capture.get('endpoint',{}).get('path')
        if endpoint not in (PROMOTION_ENDPOINT,ENUM_ENDPOINT):continue
        records=list(_capture_fields(capture))
        if endpoint==ENUM_ENDPOINT:
            for path,fields in records:
                if not re.fullmatch(r'\$\.data\.kol_alias_post_type\[\d+\]',path):continue
                value,text=fields.get('value'),fields.get('text')
                if type(value) is not int or not isinstance(text,str) or not text:
                    raise ValueError('promotion_v2_exact_enum_pair_required')
                if value in enum_by_value and enum_by_value[value]!=text or text in enum_by_text and enum_by_text[text]!=value:
                    raise ValueError('promotion_v2_enum_conflict')
                enum_by_value[value]=text;enum_by_text[text]=value
                enum_sources.setdefault(value,[]).append(dict(capture_index=ci,record_path=path))
        else:
            controls=capture['metadata']['response_fields']
            totals.extend(f['value'] for f in controls if f.get('path')=='$.data.total' and type(f.get('value')) is int)
            for path,fields in records:
                if not re.fullmatch(r'\$\.data\.promotion_list\[\d+\]',path):continue
                fields={k:v for k,v in fields.items() if k in NATIVE_FIELDS}
                aid=fields.get('alias_id')
                if not isinstance(aid,str) or not re.fullmatch(r'[0-9]{1,24}',aid):
                    raise ValueError('promotion_v2_original_string_alias_id_required')
                if aid in natives and natives[aid]['fields']!=fields:
                    raise ValueError('promotion_v2_native_alias_changed_during_observation')
                natives[aid]=dict(fields=fields,capture_index=ci,record_path=path)
    if not totals or len(set(totals))!=1 or totals[0]<0:
        raise ValueError('promotion_v2_native_total_required')
    complete=(legacy['pagination_complete'] is True and totals[0]==len(natives)==len(legacy['rows']))
    rows=[];used=set();at=legacy['observed_at']
    for di,dom in enumerate(legacy['rows']):
        matches=[n for n in natives.values() if all(n['fields'].get(nk)==dom.get(dk)
            for nk,dk in [('book_id','book_id'),('book_name','book_name'),('alias_name','alias')])]
        typed=[n for n in matches if type(n['fields'].get('alias_post_type')) is int
               and enum_by_value.get(n['fields']['alias_post_type'])==dom.get('publish_type')]
        if typed:matches=typed
        pending=[];native={};entry=None
        if len(matches)==1:
            entry=matches[0];native=entry['fields'];aid=native['alias_id']
            if aid in used:pending.append('native_dom_join_not_unique')
            used.add(aid)
        else:pending.append('native_dom_join_missing_or_ambiguous')
        if not complete:pending.append('native_pagination_incomplete')
        post=native.get('alias_post_type');publish=enum_by_value.get(post) if type(post) is int else None
        if publish is None:pending.append('native_publish_type_enum_missing')
        elif publish!=dom.get('publish_type'):pending.append('native_dom_publish_type_conflict')
        if publish!='AIGC':pending.append('publish_type_not_aigc')
        if type(native.get('task_type')) is not int:pending.append('raw_task_type_missing')
        for key in ('alias_status','book_status'):
            if type(native.get(key)) is not int:pending.append('native_'+key+'_missing')
        # These pairs were directly observed in the exact 7615 native/DOM
        # capture. No value is invented for an unobserved active state.
        for key,known in [('alias_status',{5:'强制失效',4:'审核不通过'}),('book_status',{1:'可用',2:'不可用'})]:
            if native.get(key) in known and known[native[key]]!=dom.get(key):pending.append('native_dom_'+key+'_conflict')
        if dom.get('alias_status')!='生效中':pending.append('actual_dom_alias_not_active')
        if dom.get('book_status')!='可用':pending.append('actual_dom_book_not_usable')
        start,end=native.get('alias_start_time'),native.get('alias_end_time')
        if not start or not end:pending.append('native_alias_dates_missing')
        else:
            try:
                if _timestamp(start)>=_timestamp(end):pending.append('native_alias_dates_invalid')
                elif not _timestamp(start)<=at<_timestamp(end):pending.append('alias_outside_validity')
            except ValueError:pending.append('native_alias_dates_invalid')
            if start!=dom.get('valid_from') or end!=dom.get('valid_until'):pending.append('native_dom_alias_dates_conflict')
        if legacy.get('identity_verified') is not True or legacy.get('challenge') is not False:
            pending.append('managed_identity_not_ready')
        if not legacy.get('table_ready'):pending.append('dom_table_not_ready')
        row=dict(native_kind='promotion_alias',native_record_id=native.get('alias_id'),
            book_id=dom.get('book_id'),book_name=dom.get('book_name'),alias=dom.get('alias'),publish_type=publish,
            workflow_kind='alias_promotion',workflow_label='别名推广',alias_status=dom.get('alias_status'),
            book_status=dom.get('book_status'),valid_from=start or None,valid_until=end or None,
            published_links=dom.get('published_links',[]),fill_status=dom.get('fill_status'),native_fields=native,
            native_identity_evidence=dict(observation=evidence['observation'],capture_index=entry['capture_index'],
                record_path=entry['record_path'],field_name='alias_id') if entry else None,
            enum_evidence=dict(observation=evidence['observation'],sources=enum_sources.get(post,[]),
                native_value=post,text=publish),
            dom_join_evidence=dict(legacy_snapshot=evidence['legacy_snapshot'],row_index=di,
                criteria=['book_id','book_name','alias_name','alias_post_type_via_observed_enum'],unique=len(matches)==1,
                workflow_scope_source='native_alias_id_and_current_keyword_list_context',
                date_semantics='Asia/Shanghai; day-only end uses its start-of-day as conservative cutoff'),
            identity_status='verified' if entry else 'pending',pending_fields=list(dict.fromkeys(pending)),
            status='pending' if pending else 'ready',publishable=not pending)
        if 'fill_status_evidence' in dom:
            from src.platform_adapter.fanqie_fill_status_v1 import normalize_row as normalize_fill_status
            status, proof = normalize_fill_status(dom)
            if status != row['fill_status']:raise ValueError('promotion_v2_fill_status_proof_conflict')
            row['fill_status_evidence'] = proof
        rows.append(row)
    return dict(schema=SCHEMA,normalizer_version=VERSION,
        **{k:legacy[k] for k in (*SCOPE,'observed_at','identity_verified','challenge','table_ready')},
        pagination_complete=complete,evidence_ref=evidence_ref,rows=rows)


def prepare_snapshot(legacy_snapshot_ref,observation_ref,output_directory,*,managed_subject):
    evidence=dict(schema=EVIDENCE_SCHEMA,normalizer_version=VERSION,legacy_snapshot=legacy_snapshot_ref,
                  observation=observation_ref,managed_subject=managed_subject)
    # Derive before writing a successful artifact, including on bad evidence.
    _derive(evidence,None)
    evidence_ref=_save(Path(output_directory)/'NATIVE_ALIAS_EVIDENCE_V2.json',evidence)
    snapshot=_derive(evidence,evidence_ref)
    return _save(Path(output_directory)/'PROMOTION_SNAPSHOT_V2.json',snapshot)


def validate_snapshot(value,*,now=None,require_fresh=False,require_publishable=False):
    if value.get('schema')=='fanqie_promotion_snapshot/v1':
        from src.operations_accounts.fanqie_managed_promotion_v1 import validate_snapshot as legacy_validate
        return legacy_validate(value)
    if value.get('schema')!=SCHEMA or value.get('normalizer_version')!=VERSION:
        raise ValueError('promotion_v2_snapshot_version_unsupported')
    evidence=_read(value['evidence_ref'])
    if evidence.get('schema')!=EVIDENCE_SCHEMA or evidence.get('normalizer_version')!=VERSION:
        raise ValueError('promotion_v2_evidence_version_changed')
    if _derive(evidence,value['evidence_ref'])!=value:raise ValueError('promotion_v2_snapshot_changed')
    now=time.time() if now is None else now
    if require_fresh and not 0<=now-value['observed_at']<=60:raise ValueError('promotion_v2_snapshot_stale')
    if require_publishable and not any(_currently_publishable(value,row,now) for row in value['rows']):
        raise ValueError('promotion_v2_no_publishable_rows')
    return value


def _currently_publishable(snapshot,row,now):
    return (row.get('publishable') is True and row.get('status')=='ready' and not row.get('pending_fields')
        and 0<=now-snapshot['observed_at']<=60
        and _timestamp(row['valid_from'])<=now<_timestamp(row['valid_until']))


def assert_publishable(snapshot,row,*,now=None):
    validate_snapshot(snapshot,now=now,require_fresh=True);_member(snapshot,row)
    if snapshot.get('schema')!=SCHEMA:raise ValueError('promotion_v2_publishable_requires_native_snapshot')
    if not _currently_publishable(snapshot,row,time.time() if now is None else now):
        raise ValueError('promotion_v2_target_not_publishable')
    return row
