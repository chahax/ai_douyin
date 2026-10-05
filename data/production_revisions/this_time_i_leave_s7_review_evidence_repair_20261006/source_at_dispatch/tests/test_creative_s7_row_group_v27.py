from copy import deepcopy
import json
import pytest
from jsonschema import ValidationError
from scripts import run_creative_s7_row_group_v27 as r


def row_case():
    c,_,_=r.physical.make_offline_case()
    raw={'schema':r.SCALAR_FILM,'emotional_arc':'请求到面对边界','causal_chain':'请求引发反应','ending_intent':'责任被接回'}
    for b in c['raw_linear_script']['beats']:raw[b['id']]='原文新增信息|眼与手|前侧固定中景|看清刺激后切反应|呈现边界|双人眼神清楚|无对白'
    return c,raw


def test_complete_rows_preserve_every_authored_scalar_without_rewrite():
    c,raw=row_case();film=r.decode_scalar_film(raw,c)
    for b in film['beats']:
        shot=b['shots'][0]
        assert '|'.join(shot[k] for k in r.FILM_FIELDS)==raw[b['beat_id']]
    assert [ref for b in film['beats'] for s in b['shots'] for ref in s['source_step_refs']]==[x['ref'] for x in r.physical.source_contract.source_catalog(c)]
    bad=deepcopy(raw);bad.pop(c['raw_linear_script']['beats'][0]['id'])
    with pytest.raises(ValidationError):r.decode_scalar_film(bad,c)
    for row in ('信息|对象|摄影|理由|目的|无对白','信息|对象|摄影|理由||构图|无对白','信息|对象|摄影|理由|目的|构图|未知模式'):
        bad=deepcopy(raw);bad[c['raw_linear_script']['beats'][0]['id']]=row
        with pytest.raises(ValueError):r.decode_scalar_film(bad,c)


def test_actual_wire_keeps_original_script_R01_models_and_zero_retry(monkeypatch):
    c=r.previous.context();monkeypatch.setattr(r,'context',lambda:deepcopy(c));monkeypatch.setattr(r,'dispatch',lambda label,request,validator:request)
    wire=r.film_plan();actual=json.loads(wire['messages'][1]['content'])['context']
    assert actual['reference_pack']==c['reference_pack']
    assert actual['raw_linear_script']==c['raw_linear_script']
    assert len(wire['structured_schema']['properties'])==14
    assert wire['model']=='MiniMax-M3' and wire['parameters']=={'max_completion_tokens':4500,'temperature':.4,'thinking':'disabled'}
    assert r.AUTH['automatic_retry'] is False and r.AUTH['media_calls']==0
