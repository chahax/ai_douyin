from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_creative_s7_modular_director_v25 as r


def fixture_components():
    ctx,d,_=r.physical.make_offline_case()
    film=deepcopy(d);film['schema']=r.FILM;film.pop('initial_state');film.pop('spatial_contract')
    for b in film['beats']:
        for s in b['shots']:s.pop('performance_requirements')
    state={'schema':r.STATE,'context_sha256':r.control.digest(ctx),'initial_state':deepcopy(d['initial_state']),'spatial_contract':deepcopy(d['spatial_contract'])}
    source={row['ref']:key for key,row in r.source_ids(ctx).items()}
    windows={'schema':r.WINDOWS,'context_sha256':r.control.digest(ctx),'film_plan_sha256':r.control.digest(film),'shots':[]}
    for s in r.physical._shots(d):
        windows['shots'].append({'shot_id':s['shot_id'],'requirements':[{'subject':q['subject'],'stimulus_id':source[q['stimulus_ref']],'reaction_id':source[q['reaction_ref']],'relation':q['relation'],'duration_class':'2s'} for q in s['performance_requirements']]})
    return ctx,film,state,windows,d


def test_complete_modules_lossless_assembly_and_separation():
    ctx,film,state,windows,original=fixture_components()
    assert 'initial_state' not in r.film_schema(ctx)['properties']
    assert 'performance_requirements' not in r.film_schema(ctx)['properties']['beats']['prefixItems'][0]['properties']['shots']['items']['properties']
    derived=r.assemble_direction(ctx,film,state,windows)
    assert derived['initial_state']==original['initial_state']
    for actual,old in zip(r.physical._shots(derived),r.physical._shots(original)):
        assert actual['source_step_refs']==old['source_step_refs']
        for q,prior in zip(actual['performance_requirements'],old['performance_requirements']):
            assert {k:v for k,v in q.items() if k!='id'}=={k:v for k,v in prior.items() if k!='id'}
    assert ctx['raw_linear_script']==r.physical.make_offline_case()[0]['raw_linear_script']


def test_window_schema_rejects_numeric_token_and_action_during():
    ctx,film,state,windows,_=fixture_components()
    broken=deepcopy(windows);broken['shots'][1]['requirements'][0]['duration_class']=2
    with pytest.raises(ValidationError):r.assemble_direction(ctx,film,state,broken)
    broken=deepcopy(windows);q=broken['shots'][1]['requirements'][0];q.update(stimulus_id=q['reaction_id'],relation='during')
    with pytest.raises(ValidationError):r.assemble_direction(ctx,film,state,broken)
    assert r.AUTH['automatic_retry'] is False


def test_flat_freeze_preserves_ancestor_expected_hash(tmp_path):
    target=tmp_path/'original.json';target.write_text('{"tokens":3177942}',encoding='utf-8');digest=r.control.sha_file(target)
    anchor=tmp_path/'ANCHOR.json';anchor.write_text(json.dumps({'parent_files':{str(target.resolve()):digest}}),encoding='utf-8')
    inherited=r.flatten_parent_evidence({str(anchor.resolve()):r.control.sha_file(anchor)})
    assert inherited[str(target.resolve())]==digest
    target.write_text('{"tokens":0}',encoding='utf-8')
    assert r.control.sha_file(target)!=inherited[str(target.resolve())]


def test_film_request_contains_full_source_and_reference_without_state_generation(monkeypatch):
    ctx=r.previous.context()
    monkeypatch.setattr(r,'context',lambda:deepcopy(ctx))
    monkeypatch.setattr(r,'dispatch',lambda label,request,validator:request)
    req=r.film_plan()
    actual=json.loads(req['messages'][1]['content'])['context']
    assert actual['reference_pack']==ctx['reference_pack']
    assert actual['raw_linear_script']==ctx['raw_linear_script']
    assert req['model']=='MiniMax-M3'
    assert req['inner_document_schema']==r.film_schema(ctx)
    assert req['parameters']['thinking']=='disabled'
    template=json.loads(req['messages'][1]['content'])['complete_shape_template']
    assert len(template['beats'])==len(ctx['raw_linear_script']['beats'])
    Draft202012Validator(r.film_schema(ctx)).validate(template)
    with pytest.raises(RuntimeError,match='placeholder'):r.validate_film(template,ctx)
