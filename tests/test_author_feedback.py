import json
from copy import deepcopy
import pytest
from test_narrative_revision_contract import SOURCE,PACKET,DESIGN,VALUE
from src.content_factory.novel_adaptation.author_feedback import rejected_feedback
from src.content_factory.novel_adaptation.author_feedback import reuse_feedback


def test_reuse_only_preserves_feedback_for_exact_source_and_design_context():
    old={'complete_source':['chapter'],'target_chapters':[2],'identities':['a'],'places':['room'],
         'scene_order':['s'],'scene_objectives':['talk'],'editorial_brief':{'maximum_seconds':240},
         'repair_feedback':{'accepted':False,'native_receipt_sha256':'bound','rejected_candidate':{'title':'original'}}}
    current={k:v for k,v in old.items() if k!='repair_feedback'}
    result=reuse_feedback(old,current)
    assert result==old['repair_feedback'] and result is not old['repair_feedback']
    for key in current:
        changed=deepcopy(current);changed[key]='different'
        with pytest.raises(ValueError,match='context_changed'):reuse_feedback(old,changed)

def inputs():
    draft=deepcopy(VALUE);draft['scenes'][0]['segments'][0]['seconds']=45
    return ({'native':{'id':'known','model':'test','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
        'choices':[{'finish_reason':'stop','message':{'content':json.dumps(draft),'tool_calls':[]}}]}},
        {'status':'needs_attention','pending':None},{'routes':{'writer':{'model':'test'}}})

def test_failed_draft_is_feedback_not_acceptance_or_mutation():
    r,s,p=inputs();before=deepcopy(r)
    result=rejected_feedback(r,s,p,SOURCE,PACKET,DESIGN,30)
    assert result['accepted'] is False and r==before
    assert result['structural_diagnosis']['issues'][0]['code']=='editorial_duration_limit_exceeded'

@pytest.mark.parametrize('failure',['pending','length','usage','model','duplicate'])
def test_uncertain_truncated_or_ambiguous_receipts_cannot_be_reused(failure):
    r,s,p=inputs();n=r['native']
    if failure=='pending':s['pending']=1
    if failure=='length':n['choices'][0]['finish_reason']='length'
    if failure=='usage':n['usage']['total_tokens']=0
    if failure=='model':n['model']='other'
    if failure=='duplicate':n['choices'][0]['message']['content']='{"title":"a","title":"b"}'
    with pytest.raises(ValueError):rejected_feedback(r,s,p,SOURCE,PACKET,DESIGN,30)
