"""Scoped offline427 quote-only intake and same-whole review; all clients blocked."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json,socket
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_legal_saved_response_review_v12 as m


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('saved427 tests are offline only')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)
    monkeypatch.setattr(m.control,'CreativeRoleClients',denied)


def configured(tmp_path):
    root=tmp_path/'quote_intake';m.init(root);return root,m.control.read(root/'SETUP.json')


def test_original427_only_quote_equivalence_preserves_whole_raw_and_all_other_contracts(tmp_path):
    root,settings=configured(tmp_path)
    ledger,old,raw,compiled,schema,assessment=m.inspect_saved_source(settings)
    before=deepcopy(raw);original_schema=old['request']['structured_schema'];schema_before=deepcopy(original_schema)
    assert old['status']=='contract_rejected' and assessment['original_status']=='contract_rejected'
    assert assessment['status']=='locally_contract_assessed_pending_full_review'
    assert old['response_metadata']['total_tokens']==7120 and old['response_metadata']['finish_reason']=='tool_calls'
    assert old['request_sha256']==m.SOURCE_REQUEST_SHA and m.control.digest(raw)==m.SOURCE_OUTPUT_SHA
    assert raw['beats'][0]['steps'][4]['text']==m.EQUIVALENT_QUOTE
    with pytest.raises(ValidationError):Draft202012Validator(original_schema).validate(raw)
    clean=deepcopy(compiled);clean.pop('selected_candidate_id');assert clean==raw
    assert m.quote_equivalent_schema(original_schema)==schema and original_schema==schema_before
    assert m.validate_whole_output(raw,schema,m.control.read(m.PROJECT/m.SOURCE_DIRECTORY/'INPUT.json')['source_direction'])[1]['creative_quality_passed'] is False
    cases=[]
    bad=deepcopy(raw);bad['beats'][0]['steps'][0]['text']='公司没有让你离开。';cases.append(bad)
    bad=deepcopy(raw);bad['beats'][3]['steps'][0]['text']='周姐放下文件夹。';cases.append(bad)
    bad=deepcopy(raw);bad['beats'][1]['steps'].append(deepcopy(bad['beats'][1]['steps'][-1]));cases.append(bad)
    bad=deepcopy(raw);bad['beats'][2]['steps'].pop();cases.append(bad)
    bad=deepcopy(raw);bad['beats'].pop();cases.append(bad)
    bad=deepcopy(raw);bad['beats'][1]['steps']='not array';cases.append(bad)
    direction=m.control.read(m.PROJECT/m.SOURCE_DIRECTORY/'INPUT.json')['source_direction']
    for bad in cases:
        with pytest.raises(ValidationError):m.validate_whole_output(bad,schema,direction)
    bad=deepcopy(raw);bad['beats'][1]['steps'][1]['text']='系统要求你签。'
    with pytest.raises(ValueError,match='current facts'):m.validate_whole_output(bad,schema,direction)
    assert raw==before and not (root/'CALL_LEDGER.json').exists()


def test_prepare_inherits_known_rejection_and_review_only_actual_whole_source_then_finish_gates(monkeypatch,tmp_path):
    root,settings=configured(tmp_path);source=m.PROJECT/m.SOURCE_DIRECTORY
    old_receipt_sha=m.control.sha_file(source/m.SOURCE_RECEIPT);old_ledger_sha=m.control.sha_file(source/'CALL_LEDGER.json')
    old_body_sha=m.control.sha_file(source/'call_evidence/call_427/response_body.raw')
    op=m.Revision(root)
    monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None))
    monkeypatch.setattr(op,'summary',lambda:{'effective_calls_started':427,'effective_reported_tokens':6750566,'unknown_token_reservations':93117})
    op.prepare();a=m.control.read(root/'ANCHOR.json');x=m.control.read(root/'INPUT.json')
    assert a['inherited']['calls_started']==427 and a['inherited']['reported_tokens']==6750566
    assert a['inherited']['unknown_token_reservations']==93117 and a['inherited']['pending_ordinals']==[70,160]
    assert a['budget_reset'] is False and a['writer_dispatch_allowed'] is False and a['automatic_retry'] is False
    d=op.accepted('complete_draft')
    assert d['status']!='contract_valid' and d['original_status']=='contract_rejected'
    assert d['output']==m.control.read(source/m.SOURCE_RECEIPT)['output']==m.control.read(root/'RAW_MODEL_SCRIPT.json')
    assert x['previous_full_review']==m.control.read(source/'INPUT.json')['previous_full_review']
    assert x['draft_to_replace_not_facts']==m.control.read(source/'INPUT.json')['draft_to_replace_not_facts']
    assert x['saved_response_intake_source']['original_receipt_status']=='contract_rejected'
    calls=[]
    def dispatch(label,req,validator):calls.append((label,deepcopy(req),validator));return {'ordinal':428,'status':'outcome_unknown'}
    fake_runtime=SimpleNamespace(prepare=lambda:None,dispatch=dispatch)
    monkeypatch.setattr(op,'runtime',lambda:fake_runtime)
    with pytest.raises(ValueError,match='writer dispatch prohibited'):op.dispatch('draft')
    result=op.dispatch('review');assert result['status']=='outcome_unknown' and len(calls)==1
    label,req,validator=calls[0];body=json.loads(req['messages'][1]['content'])
    script=m.control.read(root/'FULL_MODEL_SCRIPT.json')
    assert label=='full_review' and req['model']==a['models']['director']['model']=='deepseek-flash'
    assert body['full_current_script']==script and body['reference_fulltext']==x['reference_fulltext']
    assert body['source_catalog']==m.prior.baseline.evidence(script)
    assert body['saved_response_intake_source']==x['saved_response_intake_source']
    assert body['full_current_script']['beats'][0]['steps'][4]['text']==m.EQUIVALENT_QUOTE
    m.control.write(root/'CALL_LEDGER.json',{'calls':[{'label':'full_review'}]})
    fake_runtime.ledger=root/'CALL_LEDGER.json';fake_runtime.check=lambda l:None
    fake_runtime.effective_receipt=lambda row:{'status':'outcome_unknown'}
    with pytest.raises(ValueError,match='invalid or unknown'):op.accepted('full_review')
    review={'ordinal':428,'status':'contract_valid','output':{'offline_fixture_only':True},'validation':{'script_sha256':m.control.digest(script),'needs_revision':False}}
    fake_runtime.effective_receipt=lambda row:deepcopy(review)
    gate={'script_sha256':m.control.digest(script),'text_candidate_qualified':False,'unresolved_mandatory_findings':1}
    m.control.write(root/'INDEPENDENT_EDITORIAL_GATE.json',gate)
    with pytest.raises(ValueError,match='unresolved'):op.finish()
    gate.update(text_candidate_qualified=True,unresolved_mandatory_findings=[])
    m.control.write(root/'INDEPENDENT_EDITORIAL_GATE.json',gate)
    review['validation']['script_sha256']='different-source'
    with pytest.raises(ValueError,match='unresolved'):op.finish()
    review['validation']['script_sha256']=m.control.digest(script)
    op.finish();handoff=m.control.read(root/'REVIEWED_CANDIDATE/HANDOFF.json')
    assert handoff['human_quality_approved'] is False and handoff['video_calls']==0
    assert handoff['original_draft_receipt_status']=='contract_rejected'
    assert handoff['status']=='complete_reviewed_text_awaiting_human_content_confirmation'
    assert m.control.read(root/'REVIEWED_CANDIDATE/RAW_MODEL_SCRIPT.json')==d['output']
    assert m.control.sha_file(source/m.SOURCE_RECEIPT)==old_receipt_sha and m.control.sha_file(source/'CALL_LEDGER.json')==old_ledger_sha
    assert m.control.sha_file(source/'call_evidence/call_427/response_body.raw')==old_body_sha
