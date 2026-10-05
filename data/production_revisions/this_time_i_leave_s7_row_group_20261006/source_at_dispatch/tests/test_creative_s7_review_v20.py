from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_review_v20 as r


def raw_receipt(n):
    rec=r.control.read(next(r.old.ROOT.glob(f'call_{n:03}_*.json')))
    return r.source.stage_record_view(rec)['output']


@pytest.mark.parametrize('ordinal',[163,164])
def test_real_missing_comparison_receipts_rejected_by_schema(ordinal):
    ctx=r.script_context();raw=deepcopy(raw_receipt(ordinal));raw['schema']=r.ID_VERSION
    with pytest.raises(ValidationError):Draft202012Validator(r.review_schema(ctx)).validate(raw)


def test_offline_paired_shape_and_stale_id_and_full_scope():
    ctx=r.script_context();raw=deepcopy(raw_receipt(164));raw['schema']=r.ID_VERSION
    # Offline shape fixture ONLY: production review never receives filled references.
    for i,row in enumerate(raw['coverage']):
        for ci,check in enumerate(row[1:]):
            if check[0] in ('pass','fail'):
                for options in r.comparison_groups(ctx,i,ci):
                    if not any(k in options for k in check[2]):check[2].append(options[0])
    Draft202012Validator(r.review_schema(ctx)).validate(raw)
    r.source.review_wire.validate_script_review(r.expand_review(raw,ctx),ctx)
    stale=deepcopy(raw);stale['coverage'][0][1][2][0]='E-stale'
    with pytest.raises(ValidationError):r.expand_review(stale,ctx)
    assert ctx['raw_linear_script']==r.old.latest('draft_s7_r')['output']
    assert ctx['reference_pack']==r.source.original()['reference_pack']
    assert r.AUTH['automatic_retry'] is False
