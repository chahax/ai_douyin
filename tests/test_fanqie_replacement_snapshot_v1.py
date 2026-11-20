"""Actual immutable evidence rederivation; no network, browser or business DB."""
from copy import deepcopy
import pytest

from src.services import fanqie_replacement_snapshot_v1 as anchor
from src.services import fanqie_promotion_identity_v2 as native
from src.operations_accounts import fanqie_new_publication_backfill_v1 as files

N=files.ROOT/'data/production_trials/fanqie_cleanup_rebind_20261118_v1'
SEED=files.reference(N/'REPLACEMENT_NATIVE_IDENTITY_ACTIVE_OBSERVED.json')


def test_actual_active_anchor_rebuild_is_independent_of_pending_v2_and_freshness(tmp_path):
    seed=files.read(SEED);current=files.read(seed['after_snapshot']);original=deepcopy(current)
    ref=anchor.prepare_snapshot(SEED,seed['after_snapshot'],tmp_path,managed_subject=seed['subject']);snapshot=files.read(ref)
    assert current==original==files.read(seed['after_snapshot'])
    assert len([r for r in current['rows'] if r['alias']==seed['alias'] and r.get('native_record_id') is None])==2
    at=current['observed_at']+1
    assert anchor.validate_snapshot(snapshot,now=at,require_publishable=True)==snapshot
    row=snapshot['rows'][0]
    assert anchor.native_identity(snapshot,row)==seed['native_identity']
    assert row['publishable'] is True and row['pending_fields']==[] and row['alias_status']=='生效中'
    assert row['native_status_anchor']['native_value']==row['native_fields']['alias_status']
    assert anchor.assert_publishable(snapshot,row,now=at)==row
    assert anchor.validate_snapshot(snapshot,now=at+1000)==snapshot  # archival re-read remains stable
    with pytest.raises(ValueError,match='snapshot_stale'):anchor.validate_snapshot(snapshot,now=current['observed_at']+61,require_fresh=True)
    tampered=deepcopy(snapshot);tampered['rows'][0]['native_record_id']='9909342031922872345'
    with pytest.raises(ValueError,match='snapshot_changed'):anchor.validate_snapshot(tampered,now=at)
    wrong=deepcopy(seed['subject']);wrong['task_id']='another-command'
    with pytest.raises(ValueError,match='current_managed_scope_changed'):
        anchor.prepare_snapshot(SEED,seed['after_snapshot'],tmp_path/'wrong',managed_subject=wrong)


def test_actual_pending_dom_does_not_borrow_same_numeric_active_status(tmp_path):
    seed=files.read(SEED);result=files.read(seed['application_result']);pending_ref=result['result']['native_result']['after_snapshot']
    pending=native.validate_snapshot(files.read(pending_ref));subject=files.read(pending['evidence_ref'])['managed_subject']
    ref=anchor.prepare_snapshot(SEED,pending_ref,tmp_path,managed_subject=subject);snapshot=files.read(ref);row=snapshot['rows'][0]
    assert row['native_record_id']==seed['native_identity']['native_record_id'] and row['native_fields']['alias_status']==1
    assert row['alias_status']=='待审核' and row['publishable'] is False and 'current_dom_not_active' in row['pending_fields']
    with pytest.raises(ValueError,match='target_not_publishable'):
        anchor.assert_publishable(snapshot,row,now=snapshot['observed_at']+1)
    forged=deepcopy(snapshot);forged['rows'][0].update(publishable=True,status='ready',pending_fields=[])
    with pytest.raises(ValueError,match='snapshot_changed'):anchor.validate_snapshot(forged)
