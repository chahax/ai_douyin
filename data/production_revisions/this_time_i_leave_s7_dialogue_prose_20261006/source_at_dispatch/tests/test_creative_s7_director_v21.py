from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_director_v21 as r


def test_actual166_action_during_rejected_in_schema():
    ctx=r.context();rec=r.control.read(r.previous.ROOT/'call_166_direction_s7_r1.json');raw=r.source.stage_record_view(rec)['output']
    with pytest.raises(ValidationError):Draft202012Validator(r.direction_schema(ctx)).validate(raw)


def test_serial_source_windows_accept_valid_case_reject_self_action():
    ctx,d,_=r.physical.make_offline_case()
    Draft202012Validator(r.direction_schema(ctx)).validate(d)
    item=r.direction_schema(ctx)['properties']['beats']['items']['properties']['shots']['items']['properties']['performance_requirements']['items']
    refs=[row['ref'] for row in r.physical.source_contract.source_catalog(ctx)]
    good={'id':'R','subject':'C01','stimulus_ref':refs[1],'reaction_ref':refs[2],'relation':'after','minimum_seconds':2}
    Draft202012Validator(item).validate(good)
    bad=deepcopy(good);bad.update(stimulus_ref=refs[2],reaction_ref=refs[2])
    with pytest.raises(ValidationError):Draft202012Validator(item).validate(bad)
    spoken=deepcopy(good);spoken.update(stimulus_ref=refs[1],reaction_ref=refs[1],relation='during')
    Draft202012Validator(item).validate(spoken)
    assert r.AUTH['automatic_retry'] is False
