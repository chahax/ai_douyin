"""Only historical failed dialogue exposure changes; complete review remains mandatory."""
import json
from pathlib import Path
from scripts import creative_resume_dispatch_v3 as c
from src.content_factory.creative_legal_dialogue_craft_v4 import build_wire as before
from src.content_factory.creative_legal_dialogue_craft_v5 import build_wire
ROOT=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_04')
def fixture(stage):
 v=[c.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 s=c.read(ROOT/'DRAFT.json');kw=dict(now='2026-10-09T11:00:00+00:00',direction=v[4],confirmation=v[5],feedback=c.read(ROOT/'HUMAN_REVISION_REQUEST.json'),previous_script=s,script=s if stage=='review' else None)
 return before(*v[:4],stage,**kw),build_wire(*v[:4],stage,**kw),s

def test_writer_change_is_archival_dialogue_exposure_only():
 old,new,s=fixture('draft');a=json.loads(new['messages'][1]['content']);oa=json.loads(old['messages'][1]['content'])
 assert new['messages'][0]==old['messages'][0] and new['messages'][-1]==old['messages'][-1]
 assert new['model']==old['model'] and new['parameters']==old['parameters'] and new['structured_schema']==old['structured_schema']
 assert 'previous_complete_script' not in a and a['previous_script_identity']['sha256']==c.digest(s)
 for k in ('reference_fulltext','writer_expression_criteria','actual_human_feedback','original_source_context'):assert a[k]==oa[k]
 assert new['input_provenance']['archival_context_sha256']==c.digest(a)
 assert new['input_provenance']['messages_sha256']==c.digest(new['messages'])
 assert new['input_provenance']['historical_failed_script_in_actual_messages'] is False
 assert c.read(ROOT/'DRAFT.json')==s

def test_review_still_receives_complete_current_source():
 old,new,s=fixture('review');ctx=json.loads(new['messages'][-1]['content'])
 assert ctx['script']==s and new['messages'][-1]==old['messages'][-1]
 assert new['structured_schema']==old['structured_schema']
 assert new['model']=='deepseek-flash' and new['automatic_retry'] is False
