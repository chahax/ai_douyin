import json
from copy import deepcopy
from pathlib import Path
from test_creative_confirmed_case_graph_context_v1 import inputs
from src.content_factory.creative_legal_complete_revision_v3 import build_wire

def test_full_revision_and_failed_spine_keep_originals_without_plot_patch():
    root=Path(__file__).resolve().parents[1]/'data/production_revisions/legal_trend_text_trial_20261008/round_06'
    script=json.loads((root/'DRAFT_r4.json').read_text(encoding='utf-8'));review=json.loads((root/'REVIEW_r4.json').read_text(encoding='utf-8'));spine=json.loads((root/'SPINE_r4.json').read_text(encoding='utf-8'))
    revision={'previous_complete_script':script,'review':review};before=deepcopy(revision)
    (p,f,g,s,d,c),now=inputs()
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c,spine=spine,revision=revision,operator_findings={'test':'source-bound'})
    x=json.loads(w['messages'][1]['content']);assert revision==before and x['complete_content_revision']==before
    assert not x['revision_contract']['manual_content_patch'] and x['current_model_authored_causal_spine']==spine
    assert x['reference_fulltext']==p['inputs']['reference_fulltext'] and all('story_relevance' not in i for i in x['tag_choices'])
    w=build_wire(p,f,g,s,'review',now=now,direction=d,confirmation=c,script=script)
    x=json.loads(w['messages'][1]['content']);assert x['script']==script and x['review_calibration']['confirmed_case_outcome_unresolved']
    assert x['review_calibration']['two_characters_only'] and 'complete_content_revision' not in x
