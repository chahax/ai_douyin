"""Regression for visible first facts and unchanged provenance/dispatch protections."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json,pytest
from scripts import creative_resume_dispatch_v3 as c
from scripts import run_legal_dialogue_refinement_v12_20261009 as runner
from src.content_factory.creative_legal_dialogue_craft_v12 import build_wire
ROOT=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_11')
def request(stage):
 p,f,g,s,d,k=[c.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 full=c.read(ROOT/'DELIVERABLE/FULL_SCRIPT.json')
 fb={'user_statement':'这次就先到这\n这个没有前因','opening_feedback':{'quoted_opening':full['beats'][0]['steps'][1]['text'],'user_statement':'这个没有前因'}}
 before=deepcopy(fb)
 req=build_wire(p,f,g,s,stage,now='2026-10-09T00:00:00+00:00',direction=d,confirmation=k,feedback=fb,previous_script=full,script=full if stage=='review' else None)
 assert fb==before
 return req,full

def test_source_projection_cannot_reinstate_failed_opening_as_a_template():
 req,full=request('draft');ctx=json.loads(req['messages'][-1]['content']);a=json.loads(req['messages'][1]['content'])
 src=ctx['current_complete_revision_source']
 assert src['previous_last_two_beats']==full['beats'][2:]
 assert 'previous_first_three_beats' not in src and 'previous_valid_complete_script' not in src
 assert 'quoted_opening' not in a['actual_human_feedback']['opening_feedback']
 assert set(req['structured_schema']['required'])=={'title','premise','beats'}
 assert req['input_provenance']['source_script_sha256']==c.digest(full)
 assert req['input_provenance']['messages_sha256']==c.digest(req['messages'])
 assert req['input_provenance']['user_feedback_sha256']==c.digest(a['actual_human_feedback'])
 old=c.read(ROOT/'request_previews/review.json');old_a=json.loads(old['messages'][1]['content'])
 assert a['reference_fulltext']==old_a['reference_fulltext'] and a['writer_expression_criteria']==old_a['writer_expression_criteria']
 assert '本次旧B4正文' not in req['messages'][0]['content'] and '主要返修结尾' not in req['messages'][0]['content']


def test_full_review_uses_visible_fact_rule_and_complete_current_source():
 req,full=request('review');ctx=json.loads(req['messages'][-1]['content'])
 assert ctx['script']==full
 assert 'opening_information' in ctx['current_complete_revision_targets']
 assert 'previous_last_two_beats' not in ctx
 assert 'premise/event/trigger' in ctx['revision_contract']['review_qualification']
 assert req['structured_schema']['properties']['dialogue_craft_review']['properties']['script_sha256']=={'const':c.digest(full)}
 assert set(req['structured_schema']['required'])=={'full_text_review','emotion_review','dialogue_craft_review'}


def test_repeated_unknown_stage_never_reaches_request_or_provider(monkeypatch):
 ledger={'calls':[{'label':'craft_draft_r12','status':'outcome_unknown'}],'starting_spend':{'calls_started':356,'reported_tokens':6047025,'unknown_token_reservations':93117}}
 before=deepcopy(ledger)
 monkeypatch.setattr(runner,'prepare',lambda n:None)
 monkeypatch.setattr(runner,'runtime',lambda n:SimpleNamespace(ledger='fixture'))
 monkeypatch.setattr(runner.control,'read',lambda p:ledger)
 monkeypatch.setattr(runner,'wire',lambda *args:pytest.fail('must not build a repeated request'))
 with pytest.raises(ValueError,match='already dispatched'):runner.dispatch(12,'draft')
 assert ledger==before
