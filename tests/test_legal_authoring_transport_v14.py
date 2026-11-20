from copy import deepcopy
from jsonschema import Draft202012Validator,ValidationError
import pytest
from scripts import creative_resume_dispatch_v3 as c
from src.content_factory.creative_legal_dialogue_craft_v14 import build_wire,compile_writer_script
from scripts import run_legal_dialogue_refinement_v14_20261009 as runner
from types import SimpleNamespace
from pathlib import Path
ROOT=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_12')

def test_simpler_transport_does_not_weaken_local_complete_ordered_acceptance():
 p,f,g,s,d,k=[c.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 full=c.read(ROOT/'PREVIOUS_COMPLETE_SCRIPT.json');raw=deepcopy(full);raw.pop('selected_candidate_id')
 req=build_wire(p,f,g,s,'draft',now='2026-10-09T00:00:00+00:00',direction=d,confirmation=k,feedback=c.read(ROOT/'HUMAN_REVISION_REQUEST.json'),previous_script=full)
 wire=Draft202012Validator(req['structured_schema'])
 assert 'prefixItems' not in req['structured_schema']['properties']['beats']
 assert compile_writer_script(raw,d)==full
 wire.validate(raw)
 from scripts import run_legal_dialogue_refinement_v12_20261009 as parent
 rt=parent.runtime(12);ledger=c.read(rt.ledger);failed=rt.effective_receipt(ledger['calls'][0])['output']
 for invalid in (failed,{**raw,'beats':raw['beats'][:1]}):
  with pytest.raises(ValidationError): wire.validate(invalid)
  with pytest.raises((ValidationError,ValueError)): compile_writer_script(invalid,d)
 for kind in ('repeat','order'):
  bad=deepcopy(raw)
  if kind=='repeat':bad['beats'][1]['id']='B1'
  else:bad['beats'][0],bad['beats'][1]=bad['beats'][1],bad['beats'][0]
  wire.validate(bad)
  with pytest.raises((ValidationError,ValueError)):compile_writer_script(bad,d)

def test_same_label_cannot_dispatch_or_reset_after_known_failure(monkeypatch):
 ledger={'calls':[{'label':'craft_draft_r14','status':'contract_rejected'}],'starting_spend':{'calls_started':357,'reported_tokens':6058336,'unknown_token_reservations':93117}}
 original=deepcopy(ledger)
 monkeypatch.setattr(runner,'prepare',lambda n:None)
 monkeypatch.setattr(runner,'runtime',lambda n:SimpleNamespace(ledger='fixture'))
 monkeypatch.setattr(runner.control,'read',lambda p:ledger)
 monkeypatch.setattr(runner,'wire',lambda *args:pytest.fail('duplicate must not rebuild request'))
 with pytest.raises(ValueError,match='already dispatched'):runner.dispatch(14,'draft')
 assert ledger==original
