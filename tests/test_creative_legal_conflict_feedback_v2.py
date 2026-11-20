"""Regression for the actual stale-brief request fault, using frozen source only."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from scripts import run_legal_conflict_feedback_revision_v2_20261009 as run
from scripts import creative_resume_dispatch_v3 as c
from src.content_factory.creative_legal_conflict_feedback_v2 import validate_current_script
BASE=run.PROJECT/'data/production_revisions/legal_conflict_feedback_20261009/round_01'
def test_actual_old_review_bound_the_stale_brief():
 old=c.read(BASE/'request_previews/review_r1.json');ctx=json.loads(old['messages'][1]['content'])
 assert old['structured_schema']['properties']['emotion_review']['properties']['brief_sha256']['const']!=c.digest(ctx['emotional_brief'])
def test_rebuilt_review_schema_binds_actual_complete_source_and_new_brief():
 source=c.read(BASE/'DRAFT_r1.json');original=deepcopy(source)
 req=run.wire('review',source);ctx=json.loads(req['messages'][1]['content']);emotion=req['structured_schema']['properties']['emotion_review']['properties']
 Draft202012Validator.check_schema(req['structured_schema'])
 assert emotion['brief_sha256']['const']==c.digest(ctx['emotional_brief'])
 assert emotion['script_sha256']['const']==c.digest(source)
 assert req['input_provenance']['active_emotional_brief_sha256']==c.digest(ctx['emotional_brief'])
 assert ctx['script']==source==original
 assert ctx['reference_fulltext']==c.read(run.ROOT/'SOURCE_PACKET.json')['inputs']['reference_fulltext']
def test_old_brief_cannot_pass_the_new_contract():
 source=c.read(BASE/'DRAFT_r1.json');req=run.wire('review',source)
 old=c.read(sorted(BASE.glob('call_331_*.json'))[0])['output']
 with pytest.raises(ValidationError):Draft202012Validator(req['structured_schema']).validate(old)
def test_received_bad_company_reply_is_rejected_without_changing_source():
 source=c.read(BASE/'DRAFT_r1.json');original=deepcopy(source)
 with pytest.raises(ValueError,match='wage/social-insurance'):validate_current_script(source)
 assert source==original
def test_model_roles_and_ledger_remain_inherited_after_local_fix():
 summary=run.summary();a=c.read(run.ROOT/'ANCHOR.json')
 assert a['inherited']['calls_started']==331 and a['inherited']['reported_tokens']==5703351
 assert summary['effective_calls_started']>=331 and summary['effective_reported_tokens']>=5703351
 assert summary['unknown_token_reservations']==93117
 assert a['models']==c.read(BASE/'ANCHOR.json')['models']
 assert a['automatic_retry'] is False and a['media_authorized'] is False and a['budget_reset'] is False


def test_current_feedback_gate_does_not_ban_natural_signing_words():
 from scripts import run_legal_conflict_feedback_revision_v3_20261009 as current
 from src.content_factory.creative_legal_conflict_feedback_v3 import validate_exact_wording
 source=c.read(current.ROOT/'PREVIOUS_COMPLETE_SCRIPT.json');original=deepcopy(source)
 assert any('先把字签了' in s['text'] for b in source['beats'] for s in b['steps'])
 validate_exact_wording(source)
 assert source==original

def test_current_review_schema_still_binds_actual_emotional_brief():
 from scripts import run_legal_conflict_feedback_revision_v3_20261009 as current
 source=c.read(current.ROOT/'PREVIOUS_COMPLETE_SCRIPT.json')
 req=current.wire('review',source);ctx=json.loads(req['messages'][1]['content'])
 assert req['structured_schema']['properties']['emotion_review']['properties']['brief_sha256']['const']==c.digest(ctx['emotional_brief'])
 assert ctx['script']==source

def test_latest_tool_schema_rejects_the_received_long_speech_without_trimming_it():
 from scripts import run_legal_conflict_feedback_revision_v8_20261009 as current
 source=c.read(current.ROOT/'PREVIOUS_COMPLETE_SCRIPT.json');original=deepcopy(source)
 req=current.wire('draft')
 for b in [req['structured_schema']['properties']['beats']['items']]+req['structured_schema']['properties']['beats']['prefixItems']:
  branches=b['properties']['steps']['items']['allOf']
  speech=[x['then']['properties']['text'] for x in branches if x['if']['properties']['kind']['const']=='dialogue'][0]
  assert speech['maxLength']==40
 with pytest.raises(ValidationError):Draft202012Validator(req['structured_schema']).validate(source)
 assert source==original

def test_latest_actual_request_retains_reference_and_source_but_not_unusable_review_prose():
 from scripts import run_legal_conflict_feedback_revision_v8_20261009 as current
 req=current.wire('draft');ctx=json.loads(req['messages'][1]['content'])
 assert ctx['reference_fulltext']==c.read(current.ROOT/'SOURCE_PACKET.json')['inputs']['reference_fulltext']
 assert ctx['complete_revision_source']['previous_complete_script']==c.read(current.ROOT/'PREVIOUS_COMPLETE_SCRIPT.json')
 assert 'current_complete_review' not in ctx['complete_revision_source']
 assert req['parameters']['temperature']==.4 and req['parameters']['thinking']=='disabled'
 assert c.read(current.ROOT/'ANCHOR.json')['inherited']['calls_started']==338
 assert c.read(current.ROOT/'ANCHOR.json')['inherited']['reported_tokens']==5811942

def test_latest_review_still_binds_the_exact_active_brief():
 from scripts import run_legal_conflict_feedback_revision_v8_20261009 as current
 source=c.read(current.ROOT/'PREVIOUS_COMPLETE_SCRIPT.json')
 req=current.wire('review',source);ctx=json.loads(req['messages'][1]['content'])
 assert req['structured_schema']['properties']['emotion_review']['properties']['brief_sha256']['const']==c.digest(ctx['emotional_brief'])
 assert req['structured_schema']['properties']['full_text_review']['additionalProperties'] is False

