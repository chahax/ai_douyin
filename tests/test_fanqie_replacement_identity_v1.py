"""Actual immutable application evidence, CPU-only; no database or browser."""
from copy import deepcopy
import pytest

from src.services import fanqie_replacement_identity_v1 as identity
from src.operations_accounts import fanqie_new_publication_backfill_v1 as files

RESULT=files.ROOT/'data/fanqie_account_control/commands/da6385b07e0c41eeaa823049df495f0e/CLEANUP_REBIND_RESULT.json'


def test_actual_same_keyword_pending_record_has_exact_native_id_not_publishability(tmp_path):
    original=RESULT.read_bytes();ref=files.reference(RESULT);receipt=identity.derive(ref)
    assert receipt['native_identity']==dict(platform_identity_key='uid:2521598930983028',native_kind='promotion_alias',native_record_id='7709342031922872345')
    assert receipt['old_native_identity']['native_record_id']=='7708816622072381502'
    assert receipt['dom_status']=='待审核' and receipt['native_status_raw']==1 and receipt['native_status_text_inferred'] is False
    assert receipt['publish_type']=='AIGC' and receipt['post_type_evidence']['native_value']==6
    assert receipt['publishable'] is receipt['backfill_allowed'] is False and receipt['order_used_as_identity'] is False
    saved=identity.prepare_receipt(ref,tmp_path/'IDENTITY.json');assert files.read(saved)==receipt and RESULT.read_bytes()==original


def test_reordered_native_and_dom_rows_keep_identity_and_ambiguous_delta_rejects():
    result=files.read(files.reference(RESULT));request=files.read(result['request']);value=result['result']['native_result']
    preflight=files.read(files.read(value['claim'])['preflight']);before=identity._evidence(preflight['native_snapshot']);after=identity._evidence(value['after_snapshot'])
    first=identity._resolve(before,after,request)
    before=deepcopy(before);after=deepcopy(after);before['records']=dict(reversed(list(before['records'].items())));after['records']=dict(reversed(list(after['records'].items())))
    before['legacy']['rows'].reverse();after['legacy']['rows'].reverse()
    second=identity._resolve(before,after,request)
    assert first[0]==second[0]=='7709342031922872345' and first[2]['alias_status']==second[2]['alias_status']=='待审核'
    extra=dict(after['records'][first[0]],alias_id='9909342031922872345');after['records'][extra['alias_id']]=extra
    with pytest.raises(ValueError,match='exactly_one_new_native_record_required'):identity._resolve(before,after,request)
