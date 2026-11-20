"""Regress evidence preservation and current-context isolation using real sources."""
from pathlib import Path
import json
from scripts import creative_resume_dispatch_v3 as c
from src.content_factory.creative_legal_dialogue_craft_v4 import build_wire,CONTRACT,EMOTIONAL_BRIEF,STANDARDS,craft_schema
ROOT=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_03')
def fixture(stage):
 values=[c.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 script=c.read(ROOT/'DRAFT.json');feedback=c.read(ROOT/'HUMAN_REVISION_REQUEST.json')
 wire=build_wire(*values[:4],stage,now='2026-10-09T10:00:00+00:00',direction=values[4],confirmation=values[5],feedback=feedback,previous_script=script,script=script if stage=='review' else None)
 return wire,script,feedback

def test_complete_real_sources_preserved_once_and_frozen_source_unchanged():
 before=c.sha_file(ROOT/'DRAFT.json');w,script,feedback=fixture('draft')
 archive=json.loads(w['messages'][1]['content']);current=json.loads(w['messages'][2]['content'])
 old=json.loads(c.read(ROOT/'request_previews/draft.json')['messages'][1]['content'])
 assert archive['previous_complete_script']==script
 assert archive['actual_human_feedback']==feedback
 assert archive['reference_fulltext']==old['reference_fulltext']
 assert archive['writer_expression_criteria']==old['writer_expression_criteria']
 assert 'previous_complete_script' not in current and 'actual_human_feedback' not in current
 assert 'creative_brief' not in archive['original_source_context']
 assert c.sha_file(ROOT/'DRAFT.json')==before

def test_current_assignment_has_no_old_bad_sentence_examples_or_stale_hashes():
 w,_,_=fixture('draft');a=json.loads(w['messages'][1]['content']);ctx=json.loads(w['messages'][2]['content']);pr=w['input_provenance']
 assert ctx['revision_contract']==CONTRACT and ctx['emotional_brief']==EMOTIONAL_BRIEF
 for phrase in ('要走的是公司','让我走的不是我','替他们签','没碰过笔的纸和笔','核对动作','曾在同一办公区共事','344说'):
  assert phrase not in w['messages'][-1]['content'] and phrase not in w['messages'][0]['content']
 assert pr['source_context_sha256']==c.digest(ctx)
 assert pr['archival_context_sha256']==c.digest(a)
 assert pr['messages_sha256']==c.digest(w['messages'])
 assert pr['active_emotional_brief_sha256']==c.digest(ctx['emotional_brief'])
 assert pr['revision_contract_sha256']==c.digest(ctx['revision_contract'])
 assert 'active_creative_brief_sha256' not in pr
 assert w['parameters']=={'max_completion_tokens':6500,'temperature':.4,'thinking':'disabled'}
 assert [m['role'] for m in w['messages']]==['system','user','user']
 assert w['model']=='MiniMax-M3' and w['automatic_retry'] is False

def test_review_remains_bound_to_complete_current_script_and_current_brief():
 w,script,_=fixture('review');ctx=json.loads(w['messages'][-1]['content'])
 assert ctx['script']==script
 assert w['structured_schema']==craft_schema(script,EMOTIONAL_BRIEF)
 assert w['structured_schema']['properties']['emotion_review']['properties']['brief_sha256']['const']==c.digest(EMOTIONAL_BRIEF)
 assert w['model']=='deepseek-flash'
 assert len(ctx['dialogue_craft_standards'])==7
