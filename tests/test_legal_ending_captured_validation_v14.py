"""Captured v14 review validation must not re-enter an in-flight receipt ledger."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json,socket
import pytest
from jsonschema import ValidationError
from scripts import run_legal_ending_revision_v14 as m

SOURCE=m.PROJECT/m.PARENT

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*a,**k):raise AssertionError('captured validator tests must be offline')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)


def prepare_fixture(tmp_path):
    root=tmp_path/'captured';root.mkdir()
    settings=m.control.read(m.PROJECT/'data/production_revisions/legal_ending_withdrawal_revision_20261011/round_02/SETUP.json')
    m.control.write(root/'SETUP.json',settings)
    for name in ['INPUT.json','ANCHOR.json','WRITER_SCHEMA.json']:
        m.control.write(root/name,m.control.read(SOURCE/name))
    return m.Revision(root),m.control.read(SOURCE/'FULL_MODEL_SCRIPT.json'),m.control.read(SOURCE/'call_430_full_review.json')


def test_actual_review_dispatch_closure_validates_complete430_without_inflight_reentry(monkeypatch,tmp_path):
    op,script,old=prepare_fixture(tmp_path);before=deepcopy(old)
    phase={'inflight':False,'validator_ran':False};calls=[]
    def forbidden(*a,**k):raise AssertionError('in-flight accepted/runtimecheck re-entry')
    def captured_script():
        if phase['inflight']:forbidden()
        return deepcopy(script)
    monkeypatch.setattr(op,'prepare',lambda:None);monkeypatch.setattr(op,'script',captured_script)
    monkeypatch.setattr(op,'accepted',forbidden);monkeypatch.setattr(op,'summary',lambda:{})
    def dispatch(label,request,validator):
        calls.append((label,deepcopy(request)));phase['inflight']=True
        value=validator(deepcopy(old['output']));phase['validator_ran']=True
        assert value['script_sha256']==m.control.digest(script) and value['full_review_complete'] is True
        assert value['creative_quality_passed'] is False
        return {'ordinal':999,'status':'contract_valid','validation':value}
    runtime=SimpleNamespace(dispatch=dispatch,check=forbidden,effective_receipt=forbidden)
    monkeypatch.setattr(op,'runtime',lambda:runtime)
    result=op.dispatch('review')
    assert len(calls)==1 and phase['validator_ran'] is True and result['status']=='contract_valid'
    label,request=calls[0];payload=json.loads(request['messages'][1]['content'])
    assert label=='full_review' and payload['full_current_script']==script
    assert request['structured_schema']==old['request']['structured_schema']
    assert old==before and m.control.read(SOURCE/'call_430_full_review.json')['status']=='contract_rejected'


def test_captured_real_review_schema_still_rejects_type_errors_and_flags_unresolved(monkeypatch,tmp_path):
    op,script,old=prepare_fixture(tmp_path);monkeypatch.setattr(op,'script',lambda:deepcopy(script))
    req,_=op.request('review');direction=m.control.read(op.root/'INPUT.json')['source_direction']
    good=m.Revision.validate_captured('review',deepcopy(old['output']),req,direction,script)
    assert good['script_sha256']==m.control.digest(script)
    for key,value in [('issues',{}),('story_invariants_preserved','true'),('human_spoken_language_feedback_addressed',1)]:
        bad=deepcopy(old['output']);bad[key]=value
        with pytest.raises(ValidationError):m.Revision.validate_captured('review',bad,req,direction,script)
    unresolved=deepcopy(old['output']);unresolved['human_spoken_language_feedback_addressed']=False
    assert m.Revision.validate_captured('review',unresolved,req,direction,script)['needs_revision'] is True
