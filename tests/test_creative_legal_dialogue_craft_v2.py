"""Regress the actual missing-link response with a prospective simplified contract."""
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import creative_resume_dispatch_v3 as c
from scripts import run_legal_dialogue_refinement_v1_20261009 as first
from src.content_factory.creative_legal_dialogue_craft_v2 import build_wire,craft_schema,expand_review

def fixture():
 p=first.root(1);packet,facts,graph,scope,direction,confirmation=[c.read(p/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 script=c.read(p/'DRAFT.json')
 w=build_wire(packet,facts,graph,scope,'review',now='2026-10-09T09:00:00+00:00',direction=direction,confirmation=confirmation,feedback=c.read(p/'HUMAN_REVISION_REQUEST.json'),previous_script=script,script=script)
 brief=json.loads(w['messages'][1]['content'])['emotional_brief']
 received=c.read(p/'call_342_craft_review_r01.json')['output'];test_value=deepcopy(received)
 # Explicit test fixture rebind, not an edit of the production response or decision.
 test_value['dialogue_craft_review']['schema']='legal_dialogue_craft/v2'
 test_value['emotion_review']['brief_sha256']=c.digest(brief)
 return received,test_value,script,brief,w

def test_actual_missing_field_failure_stays_frozen_but_no_extra_field_required_next_contract():
 received,v,script,brief,w=fixture();original=deepcopy(received)
 _,_,res=expand_review(v,script,brief)
 assert res['needs_revision'] is True and res['professional_review_complete'] is True
 assert received==original
 assert c.read(first.root(1)/'call_342_craft_review_r01.json')['status']=='contract_rejected'
 assert 'issue_ids' not in craft_schema(script,brief)['properties']['dialogue_craft_review']['properties']['criteria']['items']['required']

def test_mandatory_finding_still_needs_complete_review_evidence():
 _,v,script,brief,_=fixture();v['full_text_review']['issues']=[]
 for row in v['emotion_review']['criteria']:row['finding']='satisfied'
 with pytest.raises(ValueError,match='absent from evidence-bound'):expand_review(v,script,brief)

def test_stale_or_extra_fields_are_not_silently_repaired():
 _,v,script,brief,_=fixture();v['dialogue_craft_review']['criteria'][0]['issue_ids']=[]
 with pytest.raises(ValidationError):expand_review(v,script,brief)
 _,v,script,brief,_=fixture();v['dialogue_craft_review']['script_sha256']='0'*64
 with pytest.raises(ValidationError):expand_review(v,script,brief)

def test_review_qualification_keeps_source_stage_separate_from_timing_and_new_stakes():
 _,_,script,brief,w=fixture();ctx=json.loads(w['messages'][1]['content'])
 assert ctx['script']==script
 assert '不要求新增拒签处罚' in ctx['revision_contract']['review_qualification']
 assert '不强制拆成' in ctx['revision_contract']['review_qualification']
 assert w['parameters']['temperature']==.4
