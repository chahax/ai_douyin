from run_novel_evidence_graph_trial import *
from src.content_factory.novel_blind_source_v5 import build_graph
def execute():
    parent=ROOT/'data/corpus_production_trials/20261027_focus_v4_benchmark'
    run=ROOT/'data/corpus_production_trials/20261027_blind_v5_benchmark'
    if run.exists() or read(parent/'STATE.json')['pending'] is not None:raise ValueError('no_replay')
    source=read(parent/'SOURCE.json');allclaims=read(parent/'CLAIMS.json');expected=read(parent/'EXPECTATIONS_NOT_SENT.json')
    selected=['T03','T02','T07','T06'];claims=[next(c for c in allclaims if c['id']==i) for i in selected];expected=[e for e in expected if e['id'] in selected]
    plan={'version':'blind_source/v5','routes':routes(),'source_sha256':digest(source),'claims_sha256':digest(claims),'max_calls':8,'context':131072,'old_unknown_untouched':True}
    run.mkdir()
    for n,v in [('PLAN',plan),('SOURCE',source),('CLAIMS',claims),('EXPECTATIONS_NOT_SENT',expected),('AUTHORIZATION',{'user_statement':'继续完善，沿同一小说和MiniMax授权，先盲读原文再判断候选的小样，不重派旧未知、不生成媒体。','plan_sha256':digest(plan)})]:freeze(run/(n+'.json'),v)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)};atomic(run/'STATE.json',state);error=None
    with run_lock(run),SqliteSaver.from_conn_string(str(run/'graph.sqlite')) as saver:
        ledger=Ledger(run,plan,state,NativeClient())
        def caller(name,prompt,payload,schema):
            value=ledger.call(name,'writer',prompt,payload,schema);print(name+' native returned',flush=True);return value
        try:
            result=build_graph(source,claims,caller,saver).invoke({'cursor':0,'findings':[]},{'configurable':{'thread_id':'blind'}})
            freeze(run/'GRAPH_RESULT.json',result);state['status']='completed_pending_primary_review'
            actual={f['claim_id']:f['accepted'] for f in result['findings']};freeze(run/'SCORE.json',[{**e,'actual_supported':actual[e['id']],'matches':e['expected_supported']==actual[e['id']]} for e in expected])
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:250]
            if state['pending'] is None:state['status']='needs_attention'
        finally:
            ledger.save();freeze(run/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'semantic_acceptance':'pending_primary_review'})
        print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':execute()
