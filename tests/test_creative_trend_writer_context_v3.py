"""Offline downstream readiness; confirmations below are simulated test-only."""
from copy import deepcopy
import json
import pytest
from src.content_factory.creative_trend_writer_context_v3 import build_confirmed_case_wire
from test_trend_creative_text_trial_v1 import data
from test_creative_trend_bridge import confirmation_fixture,NOW


def test_writer_human_corrections_and_full_reference_preserved_as_source(data):
    packet,direction,facts=data
    confirmation=confirmation_fixture(packet,direction)
    confirmation['user_statement']='模拟测试：采用案例，不以没盖章作为违法或胜负依据；不是实际用户批准。'
    before=deepcopy(direction)
    wire=build_confirmed_case_wire(packet,facts,'draft',now=NOW,direction=direction,confirmation=confirmation)
    context=json.loads(wire['messages'][1]['content'])
    assert context['creative_brief']==before['creative_brief']
    assert context['stage_assignment']['confirmed_user_decision']==confirmation
    assert 'workflow_profile' not in context['account_profile']
    assert context['account_strategy_evidence']==packet['inputs']['source']['account_profile']
    assert context['reference_fulltext']==packet['inputs']['reference_fulltext']
    assert direction==before
    step=wire['inner_document_schema']['properties']['beats']['items']['properties']['steps']['items']
    assert step['allOf'][1]['then']['properties']['speaker']['enum']==[c['name'] for c in direction['characters']]


def test_downstream_projection_cannot_turn_absent_user_confirmation_into_approval(data):
    packet,direction,facts=data
    with pytest.raises(ValueError,match='confirmation'):
        build_confirmed_case_wire(packet,facts,'draft',now=NOW,direction=direction,confirmation=None)
