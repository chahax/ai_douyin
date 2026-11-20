"""The content revision is complete, bound and preserves the transport contract."""
from copy import deepcopy
import json
from scripts.run_trend_creative_direction_revision_v2 import revised_wire
from test_trend_creative_text_trial_v1 import data
from test_creative_trend_bridge import NOW


def test_complete_revision_feedback_enters_wire_without_patching_original(data):
    packet, direction, facts = data
    before = deepcopy(direction)
    feedback = {'original_direction': direction, 'findings': [{'path': 'creative_brief.ending',
                  'quote': direction['creative_brief']['ending'], 'issue': 'offline simulated finding'}],
                'account_format': '案例拆解', 'human_direction_approval': None}
    wire = revised_wire(packet, facts, feedback, now=NOW)
    context = json.loads(wire['messages'][1]['content'])
    assert context['complete_direction_revision_feedback'] == feedback
    assert direction == before and context['reference_fulltext'] == packet['inputs']['reference_fulltext']
    assert context['verified_legal_context'] == facts
    assert wire['inner_document_schema']['properties']['schema']['const'] == 'trend_story_direction/v1'
    assert wire['parameters']['max_completion_tokens'] == 6000
    assert context['complete_direction_revision_feedback']['human_direction_approval'] is None
