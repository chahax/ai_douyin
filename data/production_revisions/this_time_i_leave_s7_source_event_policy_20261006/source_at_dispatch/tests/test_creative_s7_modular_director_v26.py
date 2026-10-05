from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_modular_director_v26 as r


def scalar_fixture():
    ctx,original,_=r.physical.make_offline_case()
    raw={'schema':r.SCALAR_FILM,'emotional_arc':'从请求到面对边界','causal_chain':'请求引发反应，随后自己拿笔。','ending_intent':'边界被接住'}
    for beat in ctx['raw_linear_script']['beats']:
        for field in r.FILM_FIELDS:raw[beat['id']+'_'+field]='无对白' if field=='dialogue_mode' else '依据原文可读地观察'
    film=r.decode_scalar_film(raw,ctx)
    st={'schema':r.SCALAR_STATE}
    for entity,values in original['initial_state'].items():
        for key,value in values.items():st[entity+'_'+key]=value
    for sid in r.seat_ids(ctx):st[sid+'_access_positions']='NONE';st[sid+'_required_facing']='NONE'
    state=r.decode_scalar_state(st,ctx)
    win={'schema':r.SCALAR_WINDOWS}
    for shot in [s for b in film['beats'] for s in b['shots']]:
        for slot in (1,2):win[shot['shot_id']+'_w'+str(slot)]='NONE'
    return ctx,raw,film,st,state,win


def test_scalar_only_film_and_source_coverage_without_json_rewrite():
    ctx,raw,film,_,_,_=scalar_fixture()
    assert all(isinstance(v,str) for v in raw.values())
    assert all(x.get('type')!='array' for x in r.scalar_film_schema(ctx)['properties'].values())
    assert [ref for b in film['beats'] for s in b['shots'] for ref in s['source_step_refs']]==[v['ref'] for v in r.physical.source_contract.source_catalog(ctx)]
    for b in film['beats']:
        assert len(b['shots'])==1 and b['shots'][0]['camera']==raw[b['beat_id']+'_camera']
    broken=deepcopy(raw);broken.pop(next(k for k in raw if k.endswith('_purpose')))
    with pytest.raises(ValidationError):r.decode_scalar_film(broken,ctx)


def test_scalar_state_exact_values_and_window_mapping():
    ctx,raw,film,st,state,win=scalar_fixture()
    for entity,values in state['initial_state'].items():
        for key,value in values.items():assert value==st[entity+'_'+key]
    windows=r.decode_scalar_windows(win,ctx,film);d=r.assemble_direction(ctx,film,state,windows)
    assert d['initial_state']==state['initial_state']
    assert all(not s['performance_requirements'] for s in r.physical._shots(d))
    # Ordinary action self-during is rejected, without coercing source IDs or values.
    shot=r.physical._shots(d)[0];own=next(k for k,v in r.source_ids(ctx).items() if v['ref'] in shot['source_step_refs'] and v['kind']=='action')
    broken=deepcopy(win);broken[shot['shot_id']+'_w1']='C01,'+own+','+own+',during,2s'
    with pytest.raises(ValidationError):r.decode_scalar_windows(broken,ctx,film)


def test_scalar_film_wire_contains_complete_s7_and_R01(monkeypatch):
    ctx=r.previous.context();monkeypatch.setattr(r,'context',lambda:deepcopy(ctx));monkeypatch.setattr(r,'dispatch',lambda label,request,validator:request)
    req=r.film_plan();actual=json.loads(req['messages'][1]['content'])['context']
    assert actual['reference_pack']==ctx['reference_pack'] and actual['raw_linear_script']==ctx['raw_linear_script']
    assert req['model']=='MiniMax-M3' and 'inner_document_schema' not in req
    assert req['parameters']=={'max_completion_tokens':6000,'temperature':.4,'thinking':'disabled'}
    assert r.AUTH['automatic_retry'] is False
