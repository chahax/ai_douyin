from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.narrative_span import target,apply_spans

def test_multiple_exact_spans_leave_all_other_characters_unchanged():
    c={'world':'前😀。错句甲；中间。错句乙！末尾。','other':'不变'}
    ts=[target(c,'a','/world','错句甲'),target(c,'b','/world','错句乙')]
    out=apply_spans(c,ts,[{'id':'b','replacement':'新乙'},{'id':'a','replacement':'新甲'}])
    assert out=={'world':'前😀。新甲；中间。新乙！末尾。','other':'不变'}
    assert c['world']=='前😀。错句甲；中间。错句乙！末尾。'

@pytest.mark.parametrize('case',['stale','overlap','duplicate','wrongid'])
def test_span_corruption_rejected(case):
    c={'world':'abcdef'};ts=[target(c,'a','/world','bcd')];edits=[{'id':'a','replacement':'X'}]
    if case=='stale':c['world']='abcdeg'
    if case=='overlap':ts.append(target(c,'b','/world','cd'));edits.append({'id':'b','replacement':'Y'})
    if case=='duplicate':edits*=2
    if case=='wrongid':edits[0]['id']='other'
    with pytest.raises(ValueError):apply_spans(c,ts,edits)
