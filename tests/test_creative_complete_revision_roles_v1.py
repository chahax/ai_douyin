from copy import deepcopy
import json
from pathlib import Path
from src.content_factory.creative_complete_revision_roles_v1 import build_wire
from test_creative_confirmed_case_graph_context_v1 import inputs

def test_full_originals_retained_while_alternatives_separated():
    root=Path(__file__).resolve().parents[1]/'data/production_revisions/legal_trend_text_trial_20261008/round_03'
    script=json.loads((root/'DRAFT_r2.json').read_text(encoding='utf-8'));review=json.loads((root/'REVIEW_r2.json').read_text(encoding='utf-8'))
    revision={'previous_complete_script':script,'review':review};before=deepcopy(revision)
    (p,f,g,s,d,c),now=inputs()
    w=build_wire(p,f,g,s,'draft',now=now,direction=d,confirmation=c,revision=revision,revision_obligations={'test':'source-bound feedback only'})
    ctx=json.loads(w['messages'][1]['content'])
    assert revision==before and ctx['complete_content_revision']==before
    contract=ctx['revision_contract']
    assert contract['must_resolve_issue_ids']==[i['id'] for i in review['full_text_review']['issues']]
    assert contract['advisory_alternatives_must_not_be_accumulated'] and contract['can_rebuild_beats_and_remove_incidental_props_or_extras']
    assert not contract['manual_content_patch'] and ctx['reference_fulltext']==p['inputs']['reference_fulltext']
    assert w['model']=='MiniMax-M3' and w['automatic_retry'] is False
