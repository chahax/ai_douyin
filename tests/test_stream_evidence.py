from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.stream_evidence import audit

def data():
    usage={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}
    rows=[{'id':'a','model':'m','choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'name':'submit_result','arguments':'{"x":'}}]}}]},
          {'id':'a','model':'m','choices':[{'index':0,'finish_reason':'tool_calls','delta':{'tool_calls':[{'index':0,'function':{'arguments':'1}'}}]}}]},
          {'id':'a','model':'m','choices':[],'usage':usage}]
    receipt={'id':'a','model':'m','usage':usage,'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'function':{'name':'submit_result','arguments':'{"x":1}'}}]}}]}
    return rows,receipt

def test_usage_after_finish_and_complete_arguments_are_supported():
    rows,r=data();before=deepcopy((rows,r));result=audit(rows,r)
    assert result['completion_evidence']=='known'
    assert not result['semantic_acceptance'] and not result['may_retry']
    assert (rows,r)==before

@pytest.mark.parametrize('failure',['finish','usage','identity','arguments','model','bad_total'])
def test_missing_or_contradictory_evidence_remains_unknown(failure):
    rows,r=data()
    if failure=='finish':rows[1]['choices'][0].pop('finish_reason');r['choices'][0]['finish_reason']=None
    if failure=='usage':rows[-1].pop('usage');r['usage']=None
    if failure=='identity':rows[1]['id']='other'
    if failure=='model':rows[1]['model']='other'
    if failure=='arguments':r['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{}'
    if failure=='bad_total':r['usage']['total_tokens']=6
    assert audit(rows,r)['completion_evidence']=='unknown'

def test_known_length_is_not_confused_with_unknown_or_content_acceptance():
    rows,r=data();rows[1]['choices'][0]['finish_reason']='length';r['choices'][0]['finish_reason']='length'
    result=audit(rows,r)
    assert result['completion_evidence']=='known' and not result['semantic_acceptance']
