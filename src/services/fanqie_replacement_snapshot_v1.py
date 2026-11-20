"""Opt-in anchor-resolved snapshot for the one evidenced replacement alias.

This is a new schema. It does not rewrite generic snapshot/v2 or its pending
rows. Static reconstruction uses observed_at; live TTL/date admission is separate.
"""
import time
from pathlib import Path

from . import fanqie_promotion_identity_v2 as native
from . import fanqie_replacement_identity_v1 as identity
from src.operations_accounts import fanqie_new_publication_backfill_v1 as files

SCHEMA='fanqie_replacement_anchor_snapshot/v1'
EVIDENCE_SCHEMA='fanqie_replacement_anchor_evidence/v1'
VERSION='replacement_anchor_v1'
SOURCES=(Path(__file__).resolve(),Path(identity.__file__).resolve())


def need(ok,code):
    if not ok:raise ValueError('replacement_anchor_'+code)


def validate_identity_observation(ref):
    value=files.read(ref)
    need(value.get('schema')==identity.SCHEMA and value.get('identity_verified') is True,'identity_observation_required')
    rebuilt=identity.derive(value['application_result'],current_snapshot_ref=value['after_snapshot'] if value.get('readonly_command') is not None else None,
                            readonly_command_ref=value.get('readonly_command'))
    need(rebuilt==value,'identity_observation_changed')
    return value


def _derive(evidence,evidence_ref):
    need(evidence.get('schema')==EVIDENCE_SCHEMA and evidence.get('normalizer_version')==VERSION,'evidence_version_changed')
    seed=validate_identity_observation(evidence['identity_observation']);result=files.read(seed['application_result']);request=files.read(result['request'])
    claim=files.read(result['result']['native_result']['claim']);preflight=files.read(claim['preflight'])
    before=identity._evidence(preflight['native_snapshot']);current=identity._evidence(evidence['current_snapshot']);subject=evidence['managed_subject']
    need(current['evidence']['managed_subject']==subject and type(subject.get('generation')) is int and subject['generation']>0
         and isinstance(subject.get('owner_id'),str) and subject['owner_id'] and isinstance(subject.get('task_id'),str) and subject['task_id']
         and all(subject.get(k)==current['snapshot'].get(k)==seed['subject'].get(k)==request[k] for k in native.SCOPE),'current_managed_scope_changed')
    new_id,new,dom,old_id,_=identity._resolve(before,current,request)
    need(new_id==seed['native_identity']['native_record_id'] and old_id==request['replaces_native_identity']['native_record_id'],'different_replacement_identity')
    # Native active-state meaning is anchored in this same account/book's
    # independently observed pre-deletion active record, never guessed from 1.
    deletion=files.read(request['cleanup_reconciliation']);active=native.validate_snapshot(files.read(deletion['before_snapshot']))
    active_rows=[r for r in active['rows'] if r.get('identity_status')=='verified' and r.get('native_record_id')==old_id]
    need(len(active_rows)==1 and all(active_rows[0].get(k)==request[k] for k in ('book_id','book_name','alias','publish_type'))
         and active_rows[0].get('alias_status')=='生效中' and active_rows[0].get('book_status')=='可用'
         and active_rows[0].get('publish_type')=='AIGC' and all(active.get(k)==request[k] for k in native.SCOPE),'observed_active_status_anchor_required')
    active_fields=active_rows[0]['native_fields'];at=current['snapshot']['observed_at'];pending=[]
    if dom.get('alias_status')!='生效中':pending.append('current_dom_not_active')
    if new.get('alias_status')!=active_fields.get('alias_status') or type(new.get('alias_status')) is not int:pending.append('native_status_does_not_match_observed_active_anchor')
    if dom.get('book_status')!='可用' or new.get('book_status')!=active_fields.get('book_status'):pending.append('current_book_not_usable')
    if type(new.get('task_type')) is not int:pending.append('raw_task_type_missing')
    start,end=new.get('alias_start_time'),new.get('alias_end_time')
    try:
        if not native._timestamp(start)<=at<native._timestamp(end):pending.append('native_dates_not_current')
    except (ValueError,TypeError):pending.append('native_dates_missing_or_invalid')
    if dom.get('valid_from')!=start or dom.get('valid_until')!=end:pending.append('current_dom_native_dates_conflict')
    row=dict(native_kind='promotion_alias',native_record_id=new_id,identity_status='verified',book_id=request['book_id'],book_name=request['book_name'],
        alias=request['alias'],publish_type='AIGC',workflow_kind='alias_promotion',workflow_label='别名推广',task_type_semantics='unclassified',
        native_fields=new,alias_status=dom.get('alias_status'),book_status=dom.get('book_status'),valid_from=start,valid_until=end,
        fill_status=dom.get('fill_status'),published_links=dom.get('published_links',[]),pending_fields=pending,status='pending' if pending else 'ready',publishable=not pending,
        identity_join_criteria=seed['join_criteria'],native_status_anchor=dict(snapshot=deletion['before_snapshot'],native_record_id=old_id,native_value=active_fields['alias_status'],dom_text='生效中'),
        post_type_evidence=dict(observation=current['evidence']['observation'],native_value=new['alias_post_type'],text=current['enums'][new['alias_post_type']]))
    if 'fill_status_evidence' in dom:row['fill_status_evidence']=dom['fill_status_evidence']
    return dict(schema=SCHEMA,normalizer_version=VERSION,evidence_ref=evidence_ref,**{k:subject[k] for k in native.SCOPE},observed_at=at,
        identity_verified=True,challenge=False,table_ready=True,pagination_complete=True,source_row_count=len(current['legacy']['rows']),target_row_count=1,
        managed_subject=subject,rows=[row],default_snapshot_unchanged=True)


def prepare_snapshot(identity_observation_ref,current_snapshot_ref,output_directory,*,managed_subject):
    evidence=dict(schema=EVIDENCE_SCHEMA,normalizer_version=VERSION,identity_observation=identity_observation_ref,current_snapshot=current_snapshot_ref,managed_subject=managed_subject)
    _derive(evidence,None)
    folder=Path(output_directory);ref=files.once(folder/'REPLACEMENT_ANCHOR_EVIDENCE.json',evidence)
    return files.once(folder/'REPLACEMENT_ANCHOR_SNAPSHOT.json',_derive(evidence,ref))


def validate_snapshot(snapshot,*,now=None,require_fresh=False,require_publishable=False):
    need(snapshot.get('schema')==SCHEMA and snapshot.get('normalizer_version')==VERSION,'snapshot_version_changed')
    need(_derive(files.read(snapshot['evidence_ref']),snapshot['evidence_ref'])==snapshot,'snapshot_changed')
    now=time.time() if now is None else now
    if require_fresh or require_publishable:need(0<=now-snapshot['observed_at']<=60,'snapshot_stale')
    if require_publishable:
        row=snapshot['rows'][0];need(row['publishable'] is True and not row['pending_fields'] and row['alias_status']=='生效中'
            and native._timestamp(row['valid_from'])<=now<native._timestamp(row['valid_until']),'target_not_publishable')
    return snapshot


def native_identity(snapshot,row):
    need(snapshot.get('schema')==SCHEMA and row in snapshot.get('rows',[]) and row.get('identity_status')=='verified','identity_row_required')
    return dict(platform_identity_key=snapshot['platform_identity_key'],native_kind='promotion_alias',native_record_id=row['native_record_id'])


def assert_publishable(snapshot,row,*,now=None):
    validate_snapshot(snapshot,now=now,require_publishable=True);need(row in snapshot['rows'],'row_not_in_snapshot');return row
