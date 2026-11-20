"""Offline checks of complete-source ending revision, freeze and dispatch boundaries."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from scripts import creative_resume_dispatch_v3 as c
from scripts import run_legal_dialogue_refinement_v9_20261009 as runner
from src.content_factory.creative_legal_dialogue_craft_v9 import build_wire,compile_writer_script
ROOT=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_08')
def wire(stage='draft'):
 p,f,g,s,d,k=[c.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 full=c.read(ROOT/'DELIVERABLE/FULL_SCRIPT.json')
 req=build_wire(p,f,g,s,stage,now='2026-10-09T00:00:00+00:00',direction=d,confirmation=k,feedback={'user_statement':'继续修改你审查'},previous_script=full,script=full if stage=='review' else None)
 return req,full,d

def test_current_complete_source_reference_and_hashes_are_real_inputs():
 req,full,d=wire();a=json.loads(req['messages'][1]['content']);ctx=json.loads(req['messages'][-1]['content'])
 old=c.read(ROOT/'request_previews/draft.json');old_a=json.loads(old['messages'][1]['content'])
 assert a['reference_fulltext']==old_a['reference_fulltext']
 assert a['writer_expression_criteria']==old_a['writer_expression_criteria']
 assert ctx['current_complete_revision_source']['previous_valid_complete_script']==full
 assert req['input_provenance']['source_context_sha256']==c.digest(ctx)
 assert req['input_provenance']['archival_context_sha256']==c.digest(a)
 assert req['input_provenance']['messages_sha256']==c.digest(req['messages'])
 assert req['input_provenance']['current_revision_targets_sha256']==c.digest(ctx['current_complete_revision_targets'])
 assert 'ending_closure' in ctx['current_complete_revision_targets']
 assert req['parameters']==old['parameters']
 raw={k:deepcopy(v) for k,v in full.items() if k!='selected_candidate_id'}
 assert compile_writer_script(raw,d)==full
 assert set(req['structured_schema']['required'])=={'title','premise','beats'}

def test_full_review_keeps_original_schema_and_current_script():
 req,full,d=wire('review');ctx=json.loads(req['messages'][-1]['content'])
 assert ctx['script']==full
 assert 'ending_closure' in ctx['current_complete_revision_targets']
 assert 'current_complete_revision_source' not in ctx
 assert set(req['structured_schema']['required'])=={'full_text_review','emotion_review','dialogue_craft_review'}
 assert req['structured_schema']['properties']['dialogue_craft_review']['properties']['script_sha256']=={'const':c.digest(full)}
 assert req['input_provenance']['current_valid_complete_script_in_writer_messages'] is False

def test_used_stage_never_reaches_provider_or_resets_ledger(monkeypatch):
 ledger={'calls':[{'label':'craft_draft_r09','ordinal':353,'status':'outcome_unknown'}],'starting_spend':{'calls_started':352,'reported_tokens':5991883,'unknown_token_reservations':93117}}
 before=deepcopy(ledger)
 monkeypatch.setattr(runner,'prepare',lambda n:None)
 monkeypatch.setattr(runner,'runtime',lambda n:SimpleNamespace(ledger='fixture'))
 monkeypatch.setattr(runner.control,'read',lambda path:ledger)
 monkeypatch.setattr(runner,'wire',lambda *args:pytest.fail('repeat may not rebuild wire or dispatch'))
 with pytest.raises(ValueError,match='already dispatched'):runner.dispatch(9,'draft')
 assert ledger==before
