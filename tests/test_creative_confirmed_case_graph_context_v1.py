"""The current genuine user confirmation cannot be substituted by graph metadata."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import pytest
from src.content_factory.creative_confirmed_case_graph_context_v1 import build_wire
from src.content_factory.creative_trend_bridge import _time

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/production_revisions/legal_trend_text_trial_20261008/round_01'


def inputs():
    values=[json.loads((RUN/n).read_text(encoding='utf-8-sig')) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json',
        'GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
    now=(_time(values[-1]['confirmed_at'])+timedelta(seconds=1)).isoformat()
    return values,now


def test_current_confirmed_case_and_supplemental_graph_reach_existing_wire():
    (packet,facts,graph,scope,direction,confirmation),now=inputs()
    before=deepcopy(direction)
    wire=build_wire(packet,facts,graph,scope,'draft',now=now,direction=direction,confirmation=confirmation)
    ctx=json.loads(wire['messages'][1]['content'])
    assert direction==before and ctx['source_direction']==direction
    assert ctx['confirmed_current_story_scope']==scope
    assert ctx['confirmation']==confirmation
    assert ctx['supplemental_tag_graph_evidence']['collection_run_id']==packet['inputs']['source']['collection_run']['run_id']
    assert ctx['reference_fulltext']==packet['inputs']['reference_fulltext']
    assert wire['model']=='MiniMax-M3' and wire['parameters']['thinking']=='disabled'
    assert ctx['stage_assignment']['publisher_later']['workflow_profile']=='legal_presenter'
    assert 'workflow_profile' not in ctx['account_profile']


@pytest.mark.parametrize('fault',['different_batch','wrong_graph_confirmation','changed_scope','unapproved'])
def test_invalid_confirmation_or_graph_blocks_before_any_client(fault):
    (p,f,g,s,d,c),now=inputs()
    if fault=='different_batch':p['inputs']['source']['collection_run']['run_id']='other'
    elif fault=='wrong_graph_confirmation':c['supplemental_graph_packet_sha256']='wrong'
    elif fault=='changed_scope':s['story_conflict']='未经确认的新剧情'
    else:c['decision']='pending'
    with pytest.raises(ValueError):build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c)
