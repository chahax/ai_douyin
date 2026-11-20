"""Frozen-source regression for professional semantic review and source-safe dispatch inputs."""
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import creative_resume_dispatch_v3 as c
from scripts import run_legal_conflict_feedback_revision_v8_20261009 as parent
from src.content_factory.creative_legal_dialogue_craft_v1 import build_wire,craft_schema,expand_review,validate_script,STANDARDS

def request(stage='draft'):
 p,f,g,s,d,confirm=[c.read(parent.ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 script=c.read(parent.ROOT/'DRAFT_r8.json')
 feedback={'user_statement':'专业术语持续优化','prior_user_statements':['原反馈完整原话'],'media_authorized':False}
 return build_wire(p,f,g,s,stage,now='2026-10-09T09:00:00+00:00',direction=d,confirmation=confirm,feedback=feedback,previous_script=script,previous_review=c.read(parent.ROOT/'REVIEW_r8.json'),script=script if stage=='review' else None)

def review_fixture():
 w=request('review');ctx=json.loads(w['messages'][1]['content']);script=ctx['script']
 raw=deepcopy(c.read(parent.ROOT/'call_340_conflict_review_r8.json')['output'])
 raw['emotion_review']['brief_sha256']=c.digest(ctx['emotional_brief'])
 ref=raw['emotion_review']['criteria'][0]['evidence_refs'][0]
 raw['dialogue_craft_review']={'schema':'legal_dialogue_craft/v1','script_sha256':c.digest(script),'standards_sha256':c.digest(STANDARDS),'creative_quality_passed':False,'criteria':[{'criterion':k,'finding':'satisfied','reason':'离线形状夹具，不是生产语义判断','evidence_refs':[deepcopy(ref)],'issue_ids':[]} for k in STANDARDS]}
 return raw,script,ctx['emotional_brief']

def test_actual_full_reference_old_source_and_human_statement_retained_with_one_active_contract():
 w=request();ctx=json.loads(w['messages'][1]['content'])
 assert ctx['reference_fulltext']==c.read(parent.ROOT/'SOURCE_PACKET.json')['inputs']['reference_fulltext']
 assert ctx['complete_revision_source']['previous_complete_script']==c.read(parent.ROOT/'DRAFT_r8.json')
 assert ctx['writer_expression_criteria'] and ctx['human_revision_request']['prior_user_statements']
 assert 'revision_contract' not in ctx['human_revision_request']
 assert 'revision_contract' not in ctx['complete_revision_source']
 assert '7–10' not in json.dumps(ctx['revision_contract'],ensure_ascii=False)
 assert w['parameters']['temperature']==.4 and w['parameters']['thinking']=='disabled'
 assert 'not_human_adoption' in ctx['complete_revision_source']['current_editorial_diagnosis'][0]['kind']

def test_actual_old_long_line_is_not_rejected_by_character_count_as_semantic_quality():
 old=c.read(parent.ROOT/'PREVIOUS_COMPLETE_SCRIPT.json');before=deepcopy(old)
 assert any(len(s['text'])>40 for b in old['beats'] for s in b['steps'] if s['kind']=='dialogue')
 validate_script(old);assert old==before

def test_review_schema_source_and_standards_bound_and_all_fields_consumed():
 raw,script,brief=review_fixture();before=deepcopy(raw)
 Draft202012Validator.check_schema(craft_schema(script,brief))
 effective,evidence,result=expand_review(raw,script,brief)
 assert raw==before and len(effective['dialogue_craft_review']['criteria'])==7
 assert result['creative_quality_passed'] is False and result['conclusions_modified'] is False
 assert result['professional_review_complete'] is True
 assert effective['dialogue_craft_review']['criteria'][0]['finding']=='satisfied'
 assert 'path' in effective['dialogue_craft_review']['criteria'][0]['evidence_refs'][0]

def test_mandatory_professional_issue_cannot_disappear_from_complete_review():
 raw,script,brief=review_fixture();raw['dialogue_craft_review']['criteria'][0]['finding']='needs_revision'
 with pytest.raises(ValueError,match='absent from full-text'):expand_review(raw,script,brief)

def test_stale_source_or_standard_hash_not_rebound():
 raw,script,brief=review_fixture();raw['dialogue_craft_review']['script_sha256']='0'*64
 with pytest.raises(ValidationError):expand_review(raw,script,brief)
 raw,script,brief=review_fixture();raw['dialogue_craft_review']['standards_sha256']='0'*64
 with pytest.raises(ValidationError):expand_review(raw,script,brief)

def test_duplicate_criteria_or_extra_field_cannot_be_accepted():
 raw,script,brief=review_fixture();raw['dialogue_craft_review']['criteria'][-1]['criterion']='oral_register'
 with pytest.raises(ValueError,match='duplicated'):expand_review(raw,script,brief)
 raw,script,brief=review_fixture();raw['suggestions_note']='do not silently strip me'
 with pytest.raises(ValidationError):expand_review(raw,script,brief)

def test_uncertainty_does_not_become_quality_pass():
 raw,script,brief=review_fixture();raw['dialogue_craft_review']['criteria'][0]['finding']='uncertain'
 _,_,result=expand_review(raw,script,brief)
 assert result['needs_revision'] is True and result['professional_uncertainty'] is True
 assert result['creative_quality_passed'] is False
