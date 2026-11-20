"""Native identity contracts over actual validators, no browser or network."""
from copy import deepcopy
import json
import time

import pytest

from src.services import fanqie_promotion_identity_v2 as v
from src.operations_accounts import fanqie_managed_promotion_v1 as old
from src.platform_adapter.fanqie_promotion_observer_v1 import sanitize_metadata


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(v.canonical(value));return v._ref(path)


def make_case(tmp_path,*,native_updates=None,dom_updates=None,extra_native=None,extra_dom=None,enum_items=None,identity='uid:synthetic',at=None):
    at=time.time() if at is None else at
    subject=dict(resource_id='fanqie:synthetic',binding_version='v1',platform_identity_key=identity,environment_key='env',
                 owner_id='owner',generation=1,task_id='task')
    native=dict(alias_id='1234567890123456789',book_id='1234567890123456780',book_name='准确书名',alias_name='准确推广词',
        task_type=1,alias_post_type=29,alias_status=3,book_status=1,
        alias_start_time='2026-01-01',alias_end_time='2027-01-01')
    native.update(native_updates or {})
    dom=dict(book_id='1234567890123456780',book_name='准确书名',alias='准确推广词',publish_type='AIGC',
        alias_status='生效中',book_status='可用',valid_from='2026-01-01',valid_until='2027-01-01',published_links=[],fill_status='未填写')
    dom.update(dom_updates or {})
    source={k:subject[k] for k in v.SCOPE};source.update(observed_at=at,identity_verified=True,challenge=False)
    raw=dict(items=[dom]+(extra_dom or []),table_ready=True,loading=False,pagination_complete=True)
    ev=save(tmp_path/'DOM.json',dict(schema='fanqie_promotion_DOM_evidence/v1',normalizer_version='v1.1',raw=raw,subject=source))
    legacy=old.normalise_snapshot(raw,**source,evidence_ref=ev)
    legacy_ref=save(tmp_path/'LEGACY.json',legacy)
    records=[native]+(extra_native or [])
    def capture(endpoint,body):
        return dict(status=200,method='GET',endpoint=dict(origin='https://kol.fanqieopen.com',path=endpoint),
                    metadata=sanitize_metadata(body,endpoint_path=endpoint),body_size_evidence=dict(
                        source='request.sizes.responseBodySize',completion_event='requestfinished',response_body_size=4000,decoded_body_bytes=4000))
    observation=dict(schema='fanqie_promotion_observer/v1',subject=subject,
        page_location=dict(origin='https://kol.fanqieopen.com',path='/page/promotion-list'),
        native_requests_issued=0,native_body_saved=False,observed_at=at+1,
        captures=[capture(v.PROMOTION_ENDPOINT,dict(code=0,data=dict(total=len(records),promotion_list=records))),
                  capture(v.ENUM_ENDPOINT,dict(code=0,data=dict(kol_alias_post_type=enum_items or [dict(text='AIGC',value=29)])))])
    obs_ref=save(tmp_path/'OBSERVATION.json',observation)
    return dict(legacy=legacy,legacy_ref=legacy_ref,observation=observation,observation_ref=obs_ref,subject=subject,at=at)


def prepare(case,tmp_path):
    ref=v.prepare_snapshot(case['legacy_ref'],case['observation_ref'],tmp_path/'output',managed_subject=case['subject'])
    return v._read(ref)


def test_native_alias_is_only_identity_and_dynamic_enum_not_hardcoded(tmp_path):
    case=make_case(tmp_path);snap=prepare(case,tmp_path);row=snap['rows'][0]
    assert v.validate_snapshot(snap)==snap and row['publishable'] and row['publish_type']=='AIGC'
    assert 'platform_task_id' not in row and 'alias_id' not in row
    assert v.native_identity(snap,row)==dict(platform_identity_key='uid:synthetic',native_kind='promotion_alias',native_record_id='1234567890123456789')
    assert v.selection_key(snap,row)=='native_alias:'+v.native_identity_scope(snap,row)
    assert v.assert_publishable(snap,row,now=case['at']+2)==row


def test_legacy_subject_and_rebuild_unchanged(tmp_path):
    case=make_case(tmp_path)
    legacy=case['legacy'];row=legacy['rows'][0]
    assert v.validate_snapshot(legacy)==legacy
    assert v.authorization_subject(legacy,row)=={k:row[k] for k in ('book_id','platform_task_id','alias_id','alias','promotion_path','publish_type')}


def test_raw_mode_change_invalidates_authorization_and_account_scope_isolated(tmp_path):
    a=make_case(tmp_path/'a');b=make_case(tmp_path/'b',native_updates=dict(task_type=7));c=make_case(tmp_path/'c',identity='uid:other')
    sa=prepare(a,tmp_path/'a');sb=prepare(b,tmp_path/'b');sc=prepare(c,tmp_path/'c')
    assert v.native_identity_scope(sa,sa['rows'][0])==v.native_identity_scope(sb,sb['rows'][0])
    assert v.authorization_subject(sa,sa['rows'][0])!=v.authorization_subject(sb,sb['rows'][0])
    assert v.native_identity_scope(sa,sa['rows'][0])!=v.native_identity_scope(sc,sc['rows'][0])
    assert v.authorization_subject(sa,sa['rows'][0])['task_type_semantics']=='unclassified'


@pytest.mark.parametrize('native,dom,reason',[
    ({'alias_start_time':'','alias_end_time':''},{},'native_alias_dates_missing'),
    ({'alias_status':5},{},'native_dom_alias_status_conflict'),
    ({'alias_post_type':9},{},'native_publish_type_enum_missing'),
    ({},{'publish_type':'真人出镜'},'native_dom_publish_type_conflict'),
    ({},{'alias_status':'强制失效'},'actual_dom_alias_not_active'),
    ({},{'valid_until':'2028-01-01'},'native_dom_alias_dates_conflict')])
def test_missing_conflicting_or_inactive_never_ready(tmp_path,native,dom,reason):
    case=make_case(tmp_path,native_updates=native,dom_updates=dom);snap=prepare(case,tmp_path);row=snap['rows'][0]
    assert not row['publishable'] and reason in row['pending_fields']
    with pytest.raises(ValueError):v.assert_publishable(snap,row,now=case['at']+1)


def test_duplicate_alias_and_book_not_joined_by_order(tmp_path):
    extra=dict(alias_id='2234567890123456789',book_id='1234567890123456780',book_name='准确书名',alias_name='准确推广词',
        task_type=1,alias_post_type=29,alias_status=3,book_status=1,alias_start_time='2026-01-01',alias_end_time='2027-01-01')
    case=make_case(tmp_path,extra_native=[extra]);snap=prepare(case,tmp_path)
    assert snap['rows'][0]['native_record_id'] is None and 'native_dom_join_missing_or_ambiguous' in snap['rows'][0]['pending_fields']


def test_same_book_keyword_two_types_uniquely_join_by_real_enum(tmp_path):
    extra=dict(alias_id='2234567890123456789',book_id='1234567890123456780',book_name='准确书名',alias_name='准确推广词',
        task_type=1,alias_post_type=9,alias_status=3,book_status=1,alias_start_time='2026-01-01',alias_end_time='2027-01-01')
    case=make_case(tmp_path,extra_native=[extra],enum_items=[dict(text='AIGC',value=29),dict(text='真人出镜',value=9)])
    snap=prepare(case,tmp_path);row=snap['rows'][0]
    assert row['native_record_id']=='1234567890123456789' and row['identity_status']=='verified'
    assert 'alias_post_type_via_observed_enum' in row['dom_join_evidence']['criteria']


def test_expired_static_snapshot_still_rebuilds_but_cutoff_blocks_fresh_use(tmp_path):
    end=v._timestamp('2026-11-16')
    case=make_case(tmp_path,at=end-20,native_updates=dict(alias_end_time='2026-11-16'),dom_updates=dict(valid_until='2026-11-16'))
    snap=prepare(case,tmp_path);row=snap['rows'][0]
    assert row['publishable'] and v.validate_snapshot(snap,now=end+10)==snap
    with pytest.raises(ValueError,match='target_not_publishable'):v.assert_publishable(snap,row,now=end+10)


def test_conflicting_enum_and_nonstring_id_rejected(tmp_path):
    case=make_case(tmp_path/'a',enum_items=[dict(text='AIGC',value=29),dict(text='真人出镜',value=29)])
    with pytest.raises(ValueError,match='enum_conflict'):prepare(case,tmp_path/'a')
    case=make_case(tmp_path/'b',native_updates=dict(alias_id=1234567890123456789))
    with pytest.raises(ValueError,match='original_string_alias_id'):prepare(case,tmp_path/'b')


def test_stale_and_changed_bound_native_evidence_cannot_publish(tmp_path):
    case=make_case(tmp_path);snap=prepare(case,tmp_path)
    with pytest.raises(ValueError,match='stale'):v.assert_publishable(snap,snap['rows'][0],now=case['at']+61)
    save(tmp_path/'OBSERVATION.json',dict(case['observation'],observed_at=case['at']+2))
    with pytest.raises(ValueError,match='bound_evidence_changed'):v.validate_snapshot(snap)


def test_actual_exact_value_receipt_offline_all_five_remain_pending(tmp_path):
    folder=v.ROOT/'data/fanqie_account_control/commands/7615ae93b01140d7aa96e5aba9f7ed50'
    observation=v._ref(folder/'observer_diagnostic/OBSERVATION.json')
    legacy=v._ref(folder/'PROMOTION_SNAPSHOT.json')
    subject=v._read(observation)['subject']
    ref=v.prepare_snapshot(legacy,observation,tmp_path/'actual_offline',managed_subject=subject)
    snap=v.validate_snapshot(v._read(ref))
    assert len(snap['rows'])==5 and all(not row['publishable'] for row in snap['rows'])
    assert all(row['native_record_id'] and row['identity_status']=='verified' for row in snap['rows'])
    assert all('platform_task_id' not in row for row in snap['rows'])


@pytest.mark.parametrize('variant',['profile','duplicate_code','conflicting_total','size_bool','size_source'])
def test_native_capture_control_and_size_evidence_cannot_be_forged(tmp_path,variant):
    case=make_case(tmp_path);obs=case['observation'];cap=obs['captures'][0];metadata=cap['metadata']
    if variant=='profile':metadata['extraction_profile']='unverified-profile'
    if variant=='duplicate_code':metadata['response_fields'].append(dict(name='code',path='$.code',value=99))
    if variant=='conflicting_total':metadata['response_fields'].append(dict(name='total',path='$.data.total',value=8))
    if variant=='size_bool':cap['body_size_evidence']['decoded_body_bytes']=True
    if variant=='size_source':cap['body_size_evidence']['source']='unverified-size'
    metadata['sanitized_sha256']=__import__('hashlib').sha256(v.canonical({k:x for k,x in metadata.items() if k!='sanitized_sha256'})).hexdigest()
    case['observation_ref']=save(tmp_path/'OBSERVATION.json',obs)
    with pytest.raises(ValueError):prepare(case,tmp_path)


def test_workspace_complete_target_survives_unrelated_unjoinable_row(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace
    native=dict(alias_id='2234567890123456789',book_id='2234567890123456780',book_name='其他书',alias_name='不同推广词',
        task_type=1,alias_post_type=29,alias_status=3,book_status=1,alias_start_time='2026-01-01',alias_end_time='2027-01-01')
    dom=dict(book_id='2234567890123456780',book_name='其他书',alias='未关联推广词',publish_type='AIGC',
        alias_status='生效中',book_status='可用',valid_from='2026-01-01',valid_until='2027-01-01',published_links=[],fill_status='未填写')
    case=make_case(tmp_path,extra_native=[native],extra_dom=[dom]);snap=prepare(case,tmp_path)
    assert snap['rows'][0]['publishable'] and snap['rows'][1]['native_record_id'] is None
    workspace=PromotionWorkspace(tmp_path/'ledger.db',accounts=SimpleNamespace())
    snapshot_ref=v._ref(tmp_path/'output/PROMOTION_SNAPSHOT_V2.json')
    monkeypatch.setattr(workspace,'latest_snapshot',lambda resource:snapshot_ref)
    monkeypatch.setattr(workspace,'_resource_binding',lambda resource:{'resource_id':resource})
    key=v.selection_key(snap,snap['rows'][0])
    _,target,_=workspace._promotion('resource',promotion_key=key)
    assert target['native_record_id']=='1234567890123456789'
    with pytest.raises(ValueError,match='不能伪作平台任务ID'):workspace._promotion('resource',platform_task_id=key)
