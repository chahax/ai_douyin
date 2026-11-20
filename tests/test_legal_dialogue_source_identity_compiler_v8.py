"""Identity compilation never repairs old responses or edits creative content."""
from copy import deepcopy
from pathlib import Path
import pytest
from jsonschema import ValidationError
from scripts import creative_resume_dispatch_v3 as c
from src.content_factory.creative_legal_dialogue_craft_v8 import compile_writer_script,build_wire
ROOT=Path('data/production_revisions/legal_dialogue_refinement_20261009/round_07')
def source():return c.read(ROOT/'call_350_craft_draft_r07.json'),c.read(ROOT/'DIRECTION.json')

def test_old_wrong_id_response_is_not_silently_repaired():
 r,d=source();before=deepcopy(r)
 with pytest.raises(ValidationError):compile_writer_script(r['output'],d)
 assert r==before and r['status']=='contract_rejected'

def test_prospective_content_fixture_binds_identity_without_editing_a_character():
 r,d=source();raw={k:deepcopy(v) for k,v in r['output'].items() if k!='selected_candidate_id'} # new-protocol test fixture only
 before=deepcopy(raw);out=compile_writer_script(raw,d)
 assert raw==before
 assert {k:v for k,v in out.items() if k!='selected_candidate_id'}==before
 assert out['selected_candidate_id']=='direction:'+c.digest(d)[:24]
 assert out['beats'] is not raw['beats']

def test_complete_writer_schema_and_review_context_remain_bound():
 r,d=source();v=[c.read(ROOT/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','HUMAN_DIRECTION_CONFIRMATION.json')]
 w=build_wire(*v[:4],'draft',now='2026-10-09T13:00:00+00:00',direction=d,confirmation=v[4],feedback=c.read(ROOT/'HUMAN_REVISION_REQUEST.json'),previous_script=r['output'])
 assert set(w['structured_schema']['required'])=={'title','premise','beats'}
 assert 'selected_candidate_id' not in w['structured_schema']['properties']
 assert w['structured_schema']['additionalProperties'] is False
 assert w['parameters']=={'max_completion_tokens':6500,'temperature':.4,'thinking':'disabled'}
