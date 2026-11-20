"""Offline transport tests; fixtures are never accepted production reviews."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory.creative_complete_review_ids_v1 import catalog,expand,build_wire
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
from test_creative_confirmed_case_graph_context_v1 import inputs

ROOT=Path(__file__).resolve().parents[1]/'data/production_revisions/legal_trend_text_trial_20261008/round_02'

def fixture():
    script=json.loads((ROOT/'DRAFT_r1.json').read_text(encoding='utf-8'))
    raw=json.loads((ROOT/'call_282_legal_review_r1.json').read_text(encoding='utf-8'))['output']
    bypath={v['path']:k for k,v in catalog(script)['entries'].items()}
    for section in [raw['full_text_review']['issues'],raw['emotion_review']['criteria']]:
        for row in section:row['evidence_refs']=[{'ref_id':bypath[x['path']]} for x in row['evidence_refs']]
    (p,f,g,s,d,c),now=inputs();brief=active_context(p,f,s,d)['emotional_brief']
    return script,raw,brief

def test_exact_leaf_expansion_keeps_every_finding_and_raw():
    script,raw,brief=fixture();before=deepcopy(raw)
    effective,receipt,validation=expand(raw,script,brief)
    assert raw==before and validation['needs_revision'] and validation['full_review_complete']
    assert effective['full_text_review']['suggestions']==raw['full_text_review']['suggestions']
    for x,y in zip(raw['full_text_review']['issues'],effective['full_text_review']['issues']):
        assert {k:v for k,v in x.items() if k!='evidence_refs'}=={k:v for k,v in y.items() if k!='evidence_refs'}
    assert effective['emotion_review']['criteria'][0]['evidence_refs'][0]['quote']==script['beats'][0]['steps'][0]['text']
    assert receipt['automatic_approval'] is False and validation['creative_quality_passed'] is False

@pytest.mark.parametrize('change',['unknown','stale_script','mixed','missing','brief_hash','emotion_issues_omitted'])
def test_invalid_reference_or_bound_source_never_accepted(change):
    script,raw,brief=fixture()
    if change=='unknown':raw['full_text_review']['issues'][0]['evidence_refs'][0]['ref_id']='EUNKNOWN-0001'
    elif change=='stale_script':script['beats'][0]['steps'][0]['text']+=' changed'
    elif change=='mixed':raw['full_text_review']['issues'][0]['evidence_refs'][0]['quote']='invented'
    elif change=='missing':raw['full_text_review']['issues'][0]['evidence_refs']=[]
    elif change=='brief_hash':brief=deepcopy(brief);brief['release']+=' changed'
    else:raw['full_text_review']['issues']=[]
    with pytest.raises(Exception):expand(raw,script,brief)

def test_wire_retains_full_script_reference_scope_and_original_hash():
    script,raw,brief=fixture();(p,f,g,s,d,c),now=inputs()
    w=build_wire(p,f,g,s,'review',now=now,direction=d,confirmation=c,script=script)
    ctx=json.loads(w['messages'][1]['content'])
    assert ctx['script']==script and ctx['reference_fulltext']==p['inputs']['reference_fulltext']
    assert ctx['emotional_brief']==brief and ctx['supplemental_tag_graph_evidence']['candidate']['support_video_count']==14
    assert ctx['original_direction_provenance']['original_direction_sha256']==c['direction_sha256']
    assert set(ctx['source_evidence_directory'])==set(catalog(script)['entries'])
    assert w['model']==json.loads((ROOT/'request_previews/review_r1.json').read_text(encoding='utf-8'))['model'] and w['automatic_retry'] is False
