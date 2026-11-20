import json
from copy import deepcopy
from src.content_factory.novel_adaptation.pipeline import extract_cards
from src.content_factory.novel_adaptation import contracts as c


def test_four_tasks_are_isolated_and_patch_does_not_rewrite_other_entities(tmp_path):
    source={'chapters':[{'index':1,'text':'苏墨在屋里。\n叶南在屋里。'}]}
    good={'entities':[{'id':'su','kind':'character','display_name':'原主苏墨',
        'source_ids':['CH1-P001']},
        {'id':'nan','kind':'character','display_name':'叶南',
         'source_ids':['CH1-P002']}]}
    seen=[]
    class Client:
        def call(self,role,messages,schema):
            p=json.loads(messages[1]['content']);seen.append(p)
            if 'allowed_records' in p:
                assert len(p['allowed_records'])==1
                assert p['allowed_records'][0]['record']['id']=='su'
                assert 'before_sha256' not in p['allowed_records'][0]
                assert 'before_sha256' not in schema['properties']['patches']['items']['properties']
                out={'patches':[{'id':'su','replacement':good['entities'][0]}]}
            elif p['task_kind']=='identity':
                out=deepcopy(good);out['entities'][0]['source_ids']=['CH999-P001']
            else:
                assert 'current_analysis' not in p and 'facts' not in p
                out={'facts':[{'id':p['task_kind']+'_1','entity_ids':['su'],
                    'statement':'苏墨在屋里','temporal_scope':'current','certainty':'explicit',
                    'source_ids':['CH1-P001']}]}
            return {'id':'test','model':'MiniMax-M3.1-Flash',
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2},
                'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[
                    {'function':{'name':'submit_result','arguments':json.dumps(out)}}]}}]}
    plan={'inference':{'writer_max_tokens':65536,'writer_effort':'xhigh'},
        'routes':{'writer':{'model':'MiniMax-M3.1-Flash'}},'max_calls':8,
        'context':131072,'source_sha256':c.digest(source)}
    out=extract_cards(tmp_path,source,plan,Client())
    assert out['identity']==good
    assert len(seen)==5
    result=json.loads((tmp_path/'RESULT.json').read_text('utf-8'))
    assert result['state']['status']=='cards_ready_awaiting_semantic_review'
    assert result['semantic_accepted'] is False
    assert result['state']['calls_started']==5
    assert result['state']['pending'] is None
