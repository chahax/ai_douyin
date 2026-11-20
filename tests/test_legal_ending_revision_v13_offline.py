"""Scoped offline ending request and explicit old/new finalization boundary checks."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json,socket
import pytest
from jsonschema import ValidationError
from scripts import run_legal_ending_revision_v13 as m
from scripts import finish_legal_ending_candidate_v1 as strict

ROOT=m.PROJECT/'data/production_revisions/legal_ending_withdrawal_revision_20261011/round_01'

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('ending checks must stay offline')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)


def temp_operator(tmp_path,monkeypatch,name='ending'):
    root=tmp_path/name;root.mkdir();m.control.write(root/'SETUP.json',m.control.read(ROOT/'SETUP.json'))
    op=m.Revision(root);monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(prepare=lambda:None));monkeypatch.setattr(op,'summary',lambda:{})
    op.prepare();return op


def fixtures(op):
    raw=m.control.read(op.root/'PRESERVED_SINGLE_SOURCE.json')
    script=m.prior.compile_writer_script(raw,m.control.read(op.root/'INPUT.json')['source_direction']);sha=m.control.digest(script)
    d={'ordinal':429,'status':'contract_valid','label':'complete_draft','response_metadata':{'total_tokens':1},'output':raw,'validation':{'script_sha256':sha,'local_current_fact_findings':[]}}
    r={'ordinal':430,'status':'contract_valid','label':'full_review','response_metadata':{'total_tokens':1},'output':{'issues':[],'story_invariants_preserved':True,'human_spoken_language_feedback_addressed':True},'validation':{'script_sha256':sha,'needs_revision':False}}
    gate={'script_sha256':sha,'draft_ordinal':429,'review_ordinal':430,'text_candidate_qualified':True,'unresolved_mandatory_findings':[],'checks':{'complete_same_source':True}}
    return raw,script,d,r,gate


def test_actual_mock_draft_reference_feedback_fixed_source_compile_and_inheritance(monkeypatch,tmp_path):
    op=temp_operator(tmp_path,monkeypatch);raw,_,_,_,_=fixtures(op);before=deepcopy(raw)
    a=m.control.read(op.root/'ANCHOR.json');x=m.control.read(op.root/'INPUT.json');calls=[]
    def dispatch(label,request,validator):calls.append((label,deepcopy(request),validator));return {'ordinal':999,'status':'contract_rejected'}
    monkeypatch.setattr(op,'prepare',lambda:None);monkeypatch.setattr(op,'runtime',lambda:SimpleNamespace(dispatch=dispatch))
    op.dispatch('draft');assert len(calls)==1
    label,request,validator=calls[0]
    assert request==m.control.read(ROOT/'request_previews/draft.json') and label=='complete_draft'
    body=json.loads(request['messages'][1]['content'])
    assert body['reference_fulltext']==x['reference_fulltext'] and body['feedback']['user_statement']==op.settings['user_statement']
    assert '那先走了' in body['feedback']['user_statement']
    assert body['unchanged_beats_from_single_full_model_source']['beats']==raw['beats'][:3]
    assert body['unchanged_beats_from_single_full_model_source']['source_ordinal']==427
    assert body['source_provenance']['raw427_original_status']=='contract_rejected'
    assert [q['if']['properties']['id']['const'] for q in request['structured_schema']['properties']['beats']['items']['allOf']]==['B1','B2','B3']
    assert validator(raw)['creative_quality_passed'] is False and raw==before
    for index in range(3):
        bad=deepcopy(raw);bad['beats'][index]['steps'][0]['text']+='改'
        with pytest.raises(ValidationError):validator(bad)
    for index in [0,1]:
        alt=deepcopy(raw);beat=alt['beats'][index]
        for row in beat['steps']:row['text']=row['text'].replace('"个人原因"','“个人原因”')
        beat['trigger']=beat['trigger'].replace('"个人原因"','“个人原因”')
        assert validator(alt)['creative_text_changed_locally'] is False
    bad=deepcopy(raw);bad['beats'][3]['steps']='wrong type'
    with pytest.raises(ValidationError):validator(bad)
    assert a['inherited']['calls_started']==428 and a['inherited']['reported_tokens']==6765003
    assert a['inherited']['unknown_token_reservations']==93117 and a['inherited']['pending_ordinals']==[70,160]
    assert a['budget_reset'] is False and a['automatic_retry'] is False
    assert not (op.root/'FULL_MODEL_SCRIPT.json').exists()


def test_old_finish_gaps_are_reproducible_without_altering_frozen_operator(monkeypatch,tmp_path):
    for name,wrong_sha,bad_types in [('old_sha_gap',True,False),('old_type_gap',False,True)]:
        op=temp_operator(tmp_path,monkeypatch,name);raw,s,d,r,g=fixtures(op)
        if wrong_sha:r['validation']['script_sha256']='another_script'
        if bad_types:g.update(text_candidate_qualified='false',unresolved_mandatory_findings=None)
        m.control.write(op.root/'INDEPENDENT_EDITORIAL_GATE.json',g)
        monkeypatch.setattr(op,'script',lambda s=deepcopy(s):deepcopy(s))
        monkeypatch.setattr(op,'accepted',lambda label,d=deepcopy(d),r=deepcopy(r):deepcopy(d if label=='complete_draft' else r))
        op.finish()
        assert m.control.read(op.root/'REVIEWED_CANDIDATE/HANDOFF.json')['human_quality_approved'] is False


def test_new_finisher_blocks_source_types_unknown_and_legacy_acceptance_blocks_unknown(monkeypatch,tmp_path):
    op=temp_operator(tmp_path,monkeypatch);raw,s,d,r,g=fixtures(op)
    good=strict.validate_finalization(s,d,r,g)
    assert good['typed_review_and_gate_checked'] is True and good['human_quality_approved'] is False
    cases=[]
    badr=deepcopy(r);badr['validation']['script_sha256']='another_script';cases.append((d,badr,g))
    badg=deepcopy(g);badg['text_candidate_qualified']='false';cases.append((d,r,badg))
    for value in [None,False]:
        badg=deepcopy(g);badg['unresolved_mandatory_findings']=value;cases.append((d,r,badg))
    for label in ['draft','review']:
        badd=deepcopy(d);badr=deepcopy(r);(badd if label=='draft' else badr)['status']='outcome_unknown';cases.append((badd,badr,g))
    badr=deepcopy(r);badr['response_metadata']['total_tokens']=None;cases.append((d,badr,g))
    for dd,rr,gg in cases:
        with pytest.raises(ValueError):strict.validate_finalization(s,dd,rr,gg)
    m.control.write(op.root/'CALL_LEDGER.json',{'calls':[{'label':'complete_draft'}]})
    fake=SimpleNamespace(ledger=op.root/'CALL_LEDGER.json',check=lambda l:None,effective_receipt=lambda row:{'status':'outcome_unknown'})
    monkeypatch.setattr(op,'runtime',lambda:fake)
    with pytest.raises(ValueError,match='invalid or unknown'):op.finish()
