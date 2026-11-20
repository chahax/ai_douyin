import json
from copy import deepcopy
from pathlib import Path
import pytest
from src.content_factory.creative_legal_review_qualification_v1 import build_wire,validate
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
from test_creative_confirmed_case_graph_context_v1 import inputs

ROOT=Path(__file__).resolve().parents[1]/'data/production_revisions/legal_trend_text_trial_20261008/round_10'

def fixture():
    script=json.loads((ROOT/'DRAFT_r8.json').read_text(encoding='utf-8'));prior=json.loads((ROOT/'REVIEW_r8.json').read_text(encoding='utf-8'))
    raw=json.loads((ROOT/'call_299_legal_review_r8.json').read_text(encoding='utf-8'))['output']
    raw['prior_issue_assessments']=[{'prior_issue_id':i['id'],'disposition':'upheld_must_fix','current_issue_id':i['id'],
        'reason':'offline synthetic source-bound assessment, not adopted production judgment','evidence_refs':deepcopy(i['evidence_refs'])} for i in raw['full_text_review']['issues']]
    (p,f,g,s,d,c),now=inputs();brief=active_context(p,f,s,d)['emotional_brief']
    return script,prior,raw,brief

def test_original_conclusions_and_raw_unmodified_no_auto_approval():
    script,prior,raw,brief=fixture();before=deepcopy(raw)
    effective,receipt,result=validate(raw,script,brief,prior)
    assert raw==before and result['needs_revision'] and result['automatic_semantic_approval'] is False
    assert effective['full_text_review']['issues'][0]['impact']==prior['full_text_review']['issues'][0]['impact']
    assert len(receipt['expanded_prior_issue_assessments'])==len(prior['full_text_review']['issues'])

@pytest.mark.parametrize('change',['omitted','duplicate','upheld_missing','optional_bound','stale','mixed_ref'])
def test_reclassification_and_source_errors_rejected(change):
    script,prior,raw,brief=fixture()
    if change=='omitted':raw['prior_issue_assessments'].pop()
    elif change=='duplicate':raw['prior_issue_assessments'][1]['prior_issue_id']=raw['prior_issue_assessments'][0]['prior_issue_id']
    elif change=='upheld_missing':raw['prior_issue_assessments'][0]['current_issue_id']='missing'
    elif change=='optional_bound':raw['prior_issue_assessments'][0]['disposition']='optional_improvement'
    elif change=='stale':script['beats'][0]['steps'][0]['text']+=' changed'
    else:raw['prior_issue_assessments'][0]['evidence_refs'][0]['quote']='invented'
    with pytest.raises(Exception):validate(raw,script,brief,prior)

def test_wire_entire_current_script_prior_review_reference_and_scope_retained():
    script,prior,raw,brief=fixture();(p,f,g,s,d,c),now=inputs();original=deepcopy(prior)
    w=build_wire(p,f,g,s,'review',now=now,direction=d,confirmation=c,script=script,prior_review=prior)
    x=json.loads(w['messages'][1]['content'])
    assert prior==original and x['script']==script and x['prior_full_review_for_qualification']==original
    assert x['reference_fulltext']==p['inputs']['reference_fulltext'] and x['confirmation']==c
    assert 'prior_issue_assessments' in w['structured_schema']['required'] and x['review_acceptance_contract']['must_fix']
