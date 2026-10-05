from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_director_v22 as r


def test_native_shape_retains_model_and_full_schema():
    ctx=r.context();messages=r.physical.build_direction_messages(ctx);schema=r.direction_schema(ctx)
    req=r.direction_wire(messages,schema,8000,{'full_reference_pack_in_messages':True})
    assert 'output_transport' not in req and 'inner_document_schema' not in req
    assert req['structured_schema']==schema
    assert req['model']==r.source.legacy.role_config('writer').model=='MiniMax-M3'
    assert json.loads(req['messages'][1]['content'])['context']==ctx
    assert req['parameters']=={'max_completion_tokens':8000,'temperature':.4,'thinking':'disabled'}


def test_real167_missing_fields_rejected_and_reaction_cannot_cross_beat():
    ctx=r.context();rec=r.control.read(r.previous.ROOT/'call_167_direction_s7_r1.json')
    raw=json.loads(rec['output']['payload_json'])
    with pytest.raises(ValidationError):Draft202012Validator(r.direction_schema(ctx)).validate(raw)
    row=r.direction_schema(ctx)['properties']['beats']['prefixItems'][4]
    shot=raw['beats'][4]['shots'][0]
    scoped=row['properties']['shots']['items']['properties']['performance_requirements']['items']['allOf'][1]
    with pytest.raises(ValidationError):Draft202012Validator(scoped).validate(shot['performance_requirements'][0])
    assert r.AUTH['automatic_retry'] is False
