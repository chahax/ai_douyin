import json
import pytest
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger

SCHEMA={'type':'object','properties':{'replacements':{'type':'array','items':{'type':'string'}}},'required':['replacements'],'additionalProperties':False}

def ledger(tmp_path,raw,finish='tool_calls'):
    class Client:
        def call(self,role,messages,schema):
            assert schema==SCHEMA
            assert '不要嵌套result_json' in messages[0]['content']
            return {'id':'known','model':'test','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
                'choices':[{'finish_reason':finish,'message':{'tool_calls':[{'function':{'name':'submit_result','arguments':raw}}]}}]}
    state={'pending':None,'calls_started':134,'reported_tokens':100}
    plan={'max_calls':135,'context':100000,'source_sha256':'s','routes':{'writer':{'model':'test'}},
          'inference':{'writer_max_tokens':1024}}
    return DirectLedger(tmp_path,plan,state,Client())

def test_nested_quotes_and_array_are_native_arguments(tmp_path):
    v={'replacements':['她说：“好。”','array value']}
    run=ledger(tmp_path,json.dumps(v,ensure_ascii=False))
    assert run.call('PATCH','writer','repair',{},SCHEMA)==v
    assert run.state['calls_started']==135 and run.state['reported_tokens']==105
    assert run.state['pending'] is None
    assert (tmp_path/'RESPONSE_135.json').exists()

@pytest.mark.parametrize('raw,finish',[
 ('{"replacements":[],"replacements":["bad"]}','tool_calls'),
 ('{"result_json":"{}"}','tool_calls'),
 ('{"replacements":','tool_calls'),
 ('{"replacements":[]}','length')])
def test_invalid_result_never_accepted_and_usage_retained(tmp_path,raw,finish):
    run=ledger(tmp_path,raw,finish)
    with pytest.raises((ValueError,RuntimeError)):run.call('PATCH','writer','repair',{},SCHEMA)
    assert run.state['pending'] is None and run.state['reported_tokens']==105
    assert not (tmp_path/'PATCH_DIRECT_DECODED.json').exists()
