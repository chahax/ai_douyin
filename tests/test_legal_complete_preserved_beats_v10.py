"""One offline actual-request check: native420 B1/B4 const, complete model output."""
from copy import deepcopy
from types import SimpleNamespace
import json
import socket
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_legal_complete_revision_v10 as m


def test_v10_actual_request_preserves_native420_whole_beats_and_demands_complete_new_output(monkeypatch,tmp_path):
    def denied(*a,**k):raise AssertionError('offline preserved-beat contract check')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
    production=m.PROJECT/'data/production_revisions/legal_spoken_dialogue_revision_20261010/round_11'
    settings=m.control.read(production/'SETUP.json')
    root=tmp_path/'v10';root.mkdir()
    (root/'SETUP.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
    original=m.control.read;stored={}
    monkeypatch.setattr(m.control,'write',lambda path,value,*args:stored.update({str(path):deepcopy(value)}))
    monkeypatch.setattr(m.control,'read',lambda path:deepcopy(stored[str(path)]) if str(path) in stored else original(path))
    op=m.Revision(root)
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None))
    monkeypatch.setattr(op,'summary',lambda:{})
    op.prepare()
    x=stored[str(root/'INPUT.json')];anchor=stored[str(root/'ANCHOR.json')]
    parent=m.PROJECT/settings['parent_text_directory'];ledger=original(parent/'CALL_LEDGER.json')
    receipts=[original(parent/r['receipt']) for r in ledger['calls']]
    assert anchor['inherited']['calls_started']==ledger['starting_spend']['calls_started']+len(receipts)
    assert anchor['inherited']['reported_tokens']==ledger['starting_spend']['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts)
    assert anchor['inherited']['unknown_token_reservations']==93117 and anchor['budget_reset'] is False
    assert anchor['automatic_retry'] is False and anchor['media_authorized'] is False
    preserved=m.PROJECT/settings['preserved_source_directory']/settings['preserved_source_receipt']
    native=original(preserved);raw=deepcopy(native['output']);before=deepcopy(raw)
    assert native['ordinal']==420 and native['status']=='contract_valid'
    fixed=[b for b in raw['beats'] if b['id'] in ['B1','B4']]
    calls=[]
    def dispatch(label,request,validator):
        calls.append((label,deepcopy(request),validator));return {'ordinal':999,'status':'contract_rejected'}
    monkeypatch.setattr(op,'prepare',lambda:None)
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(dispatch=dispatch))
    op.dispatch('draft')
    assert len(calls)==1
    label,request,validator=calls[0]
    body=json.loads(request['messages'][1]['content'])
    assert label=='complete_draft' and request['model']=='MiniMax-M3'
    assert body['unchanged_beats_from_single_full_model_source']['source_ordinal']==420
    assert body['unchanged_beats_from_single_full_model_source']['beats']==fixed
    assert body['reference_fulltext']==x['reference_fulltext']
    assert 'draft_to_replace_not_facts' not in body and 'previous_full_review' not in body
    conditions=request['structured_schema']['properties']['beats']['items']['allOf']
    assert len(conditions)==2 and [c['then']['const'] for c in conditions]==fixed
    assert [c['if']['properties']['id']['const'] for c in conditions]==['B1','B4']
    assert all(c['if']['required']==['id'] for c in conditions)
    Draft202012Validator.check_schema(request['structured_schema'])
    assert validator(raw)['creative_text_changed_locally'] is False and raw==before
    changed=deepcopy(raw)
    first=next(s for s in changed['beats'][0]['steps'] if s['kind']=='dialogue')
    first['text']='公司没有让你离开。'
    with pytest.raises(ValidationError):validator(changed)
    missing=deepcopy(raw);missing['beats'].pop(2)
    with pytest.raises(ValidationError):validator(missing)
    middle=deepcopy(raw)
    for b in middle['beats']:
        if b['id'] in ['B2','B3']:
            d=next(q for q in b['steps'] if q['kind']=='dialogue')
            d['text']='离线模拟中间对白重新创作。'
    assert validator(middle)['full_model_script'] is True
    assert [b for b in middle['beats'] if b['id'] in ['B1','B4']]==fixed
    assert raw==before
    assert request['input_provenance']['creative_text_changed_locally'] is False
    assert str(preserved) not in stored and not (root/'FULL_MODEL_SCRIPT.json').exists()
