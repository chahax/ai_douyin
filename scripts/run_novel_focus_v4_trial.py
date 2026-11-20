from run_novel_evidence_graph_trial import *
from src.content_factory.novel_focus_review_v4 import build_graph

def execute():
    parent=ROOT/'data/corpus_production_trials/20261027_literal_v3_benchmark'
    run=ROOT/'data/corpus_production_trials/20261027_focus_v4_benchmark'
    if run.exists() or read(parent/'STATE.json')['pending'] is not None:raise ValueError('no_replay')
    source=read(parent/'SOURCE.json');old=findings=read(parent/'GRAPH_RESULT.json')['findings'];expect=read(parent/'EXPECTATIONS_NOT_SENT.json')
    allclaims=[]
    for i in range(1,4):
        request=read(parent/f'CALL_{i:03}.json');payload=json.loads(request['messages'][1]['content']);allclaims+=payload['claims']
    selected=['T02','T03','T08','T07','T06','T09'];claims=[];expected=[]
    for id in selected:
        c=next(x for x in allclaims if x['id']==id)
        c={**c,'source_ids':next(f for f in old if f['claim_id']==id)['source_ids']}
        claims.append(c);expected.append(next(e for e in expect if e['id']==id))
    plan={'version':'focus_review/v4','routes':routes(),'source_sha256':digest(source),'max_calls':6,'context':131072,'claims_sha256':digest(claims),'old_unknown_untouched':True}
    run.mkdir()
    for n,v in [('PLAN',plan),('SOURCE',source),('CLAIMS',claims),('EXPECTATIONS_NOT_SENT',expected),('AUTHORIZATION',{'user_statement':'继续完善，沿原MiniMax小说文本分析授权；旧已知失败新独立核查，未发送旧判定，无旧未知重派。','plan_sha256':digest(plan)})]:freeze(run/(n+'.json'),v)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)};atomic(run/'STATE.json',state);error=None
    with run_lock(run),SqliteSaver.from_conn_string(str(run/'graph.sqlite')) as saver:
        ledger=Ledger(run,plan,state,NativeClient())
        def caller(name,prompt,payload,schema):
            value=ledger.call(name,'writer',prompt,payload,schema);print(name+' native returned',flush=True);return value
        try:
            result=build_graph(source,claims,caller,saver).invoke({'cursor':0,'findings':[]},{'configurable':{'thread_id':'focus'}})
            freeze(run/'GRAPH_RESULT.json',result);state['status']='completed_pending_primary_review'
            actual={f['claim_id']:f['accepted'] for f in result['findings']}
            freeze(run/'SCORE.json',[{**e,'actual_supported':actual[e['id']],'matches':e['expected_supported']==actual[e['id']]} for e in expected])
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:250]
            if state['pending'] is None:state['status']='needs_attention'
        finally:
            ledger.save();freeze(run/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'semantic_acceptance':'pending_primary_review'})
        print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':execute()
