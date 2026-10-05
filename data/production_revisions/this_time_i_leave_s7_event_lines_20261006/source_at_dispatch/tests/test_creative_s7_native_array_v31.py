from copy import deepcopy
import json
import pytest
from jsonschema import ValidationError
from scripts import run_creative_s7_native_array_v31 as r

def case():
    c=deepcopy(r.previous.context());raw={'schema':r.SCALAR_FILM,'emotional_arc':'选择自己','causal_chain':'明确拒绝后接回责任','ending_intent':'她赴约他工作'}
    for b in c['raw_linear_script']['beats']:raw[b['id']]=['新增信息及目的','源观察重点',r.frame_catalog.ALLOWED[b['id']][0],'信息充分后切下一反应']
    return c,raw

def test_exact_authored_array_and_fixed_frame_provenance():
    c,raw=case();d=r.decode_scalar_film(raw,c)
    for b in d['beats']:
        s=b['shots'][0];v=raw[b['beat_id']];frame=r.frame_catalog.FRAMES[v[2]]
        assert s['purpose']==s['new_information']==v[0] and s['observation_object']==v[1] and s['cut_reason']==v[3]
        assert s['camera']==frame['camera'] and s['composition']==frame['composition']
    assert [x['dialogue_mode'] for b in d['beats'] for x in b['shots']]==['无对白','画内对白','画外对白','无对白','画内对白','无对白','无对白','无对白','无对白','无对白']

def test_wrong_length_multiple_choices_extra_notes_and_row_string_rejected():
    c,raw=case()
    bads=[]
    for val in ('文本|观察|fang_face|理由',['信息','观察','dual_front','fang_face','理由'],['信息','观察','dual_front','理由'],['信息','观察','fang_face']):
        bad=deepcopy(raw);bad['B05']=val;bads.append(bad)
    bad=deepcopy(raw);bad['B02补充']=['信息','观察','dual_front','理由'];bads.append(bad)
    for bad in bads:
        with pytest.raises(ValidationError):r.decode_scalar_film(bad,c)

def test_focused_wire_full_script_R01_and_no_old_feedback(monkeypatch):
    c,raw=case();monkeypatch.setattr(r,'context',lambda:deepcopy(c));monkeypatch.setattr(r,'dispatch',lambda label,request,validator:request)
    req=r.film_plan();packet=json.loads(req['messages'][1]['content'])['read_only_creative_source']
    assert packet['reference_pack']==c['reference_pack'] and packet['raw_linear_script']==c['raw_linear_script']
    assert 'user_content_feedback' not in packet and 'component_registry' not in packet
    assert req['structured_schema']['properties']['B05']['prefixItems'][2]['enum']==['fang_face']
    assert req['model']=='MiniMax-M3' and r.AUTH['automatic_retry'] is False and r.AUTH['media_calls']==0
