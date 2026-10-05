from copy import deepcopy
from pathlib import Path
import pytest
from scripts import run_creative_content_revision_v18 as r


def test_only_complete_known_529_can_continue_with_billing_unresolved():
    original=r.control.read(r.parent.ROOT/'call_160_draft_s7_r2.json')
    value=r.validate_closed_overload(original)
    assert value['closed_error_outcome'] and value['billing_still_unknown'] and value['no_zero_usage_assumed']
    for change in [{'status':'outcome_unknown'},{'response_metadata':{'http_status_code':529,'response_body_complete':False}},{'failure':{'provider_outcome_known':False,'response_received':True}},{'response_payload':{'type':'error','error':{'type':'authentication_error'},'request_id':'x'}}]:
        wrong=deepcopy(original);wrong.update(change)
        with pytest.raises(RuntimeError,match='never bypass unknown outcome'):r.validate_closed_overload(wrong)


def test_frozen_original_error_is_not_rewritten_to_zero():
    raw=r.control.read(r.parent.ROOT/'call_160_draft_s7_r2.json')
    assert 'total_tokens' not in raw['response_metadata']
    assert raw['token_reservation']==29107
    assert r.AUTH['automatic_retry'] is False and r.AUTH['max_replacement_drafts']==1
    assert r.parent.summary()['unknown_token_reservations']==93117
