"""Stage projection preserves strategy evidence and rejects missing required direction fields."""
from copy import deepcopy
import json
import pytest
from jsonschema import ValidationError
from scripts.run_trend_creative_text_trial_v1 import build_wire
from src.content_factory.creative_trend_stage_context_v2 import project_case_direction_wire
from src.content_factory.creative_trend_bridge import validate_direction
from test_trend_creative_text_trial_v1 import data
from test_creative_trend_bridge import NOW


def test_business_cta_is_assigned_to_publisher_without_changing_frozen_profile(data):
    packet,direction,facts=data
    before=deepcopy(packet)
    wire=build_wire(packet,facts,'direction',now=NOW)
    original=json.loads(wire['messages'][1]['content'])
    profile=original['account_profile']
    # Explicit simulated operational configuration for this offline test only.
    profile.update(business_goals=['咨询线索'],cta_policy=['整理证据后咨询律师'],domain_config={'require_authority_verification':True},workflow_profile='legal_presenter')
    original['opportunity']['recommended_workflow_profile']='legal_presenter'
    wire['messages'][1]['content']=json.dumps(original,ensure_ascii=False)
    revised=project_case_direction_wire(wire,findings={'required_field_missing':'creative_brief.audience'})
    context=json.loads(revised['messages'][1]['content'])
    assert context['account_strategy_evidence']==profile
    assert context['account_profile']['allowed_formats']==['案例拆解']
    assert 'workflow_profile' not in context['account_profile']
    assert 'recommended_workflow_profile' not in context['opportunity']
    assert context['opportunity_metadata_evidence']['recommended_workflow_profile']=='legal_presenter'
    assert context['stage_assignment']['publisher_later']['cta_policy']==profile['cta_policy']
    assert context['reference_fulltext']==packet['inputs']['reference_fulltext']
    assert context['verified_legal_context']==facts
    assert packet==before and 'account_strategy_evidence' not in json.loads(wire['messages'][1]['content'])
    assert revised['inner_document_schema']==wire['inner_document_schema']


def test_audience_omission_is_rejected_instead_of_backfilled(data):
    packet,direction,facts=data
    broken=deepcopy(direction)
    del broken['creative_brief']['audience']
    with pytest.raises(ValidationError,match='audience'):
        validate_direction(broken,packet)
    assert 'audience' not in broken['creative_brief']
