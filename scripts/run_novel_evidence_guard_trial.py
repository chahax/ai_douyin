from run_novel_evidence_graph_trial import *
from src.content_factory.novel_evidence_guards_v1 import build_guards

def execute():
    parent=ROOT/'data/corpus_production_trials/20261027_langgraph_v2_fresh'
    run=ROOT/'data/corpus_production_trials/20261027_langgraph_guards'
    if run.exists() or read(parent/'STATE.json')['pending'] is not None:raise ValueError('no_replay')
    full=read(parent/'SOURCE.json');source={'chapters':full['chapters'][:1]};claims=read(parent/'EXTRACT.json')['claims']
    plan={'version':'langgraph_guards/v1','routes':routes(),'source_sha256':digest(source),'claims_sha256':digest(claims),'max_calls':2,'context':131072,'old_unknown_untouched':True}
    run.mkdir()
    for n,v in [('PLAN',plan),('SOURCE',source),('CLAIMS',claims),('AUTHORIZATION',{'user_statement':'沿当前MiniMax套餐与小说开发测试授权，两个独立语义门核查原生新材料；无媒体发布、无未知重派。','plan_sha256':digest(plan)})]:freeze(run/(n+'.json'),v)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)};atomic(run/'STATE.json',state)
    error=None
    with run_lock(run),SqliteSaver.from_conn_string(str(run/'graph.sqlite')) as saver:
        ledger=Ledger(run,plan,state,NativeClient())
        def caller(name,prompt,payload,schema):
            value=ledger.call(name,'writer',prompt,payload,schema);print(name+' native returned',flush=True);return value
        try:
            result=build_guards(source,claims,caller,saver).invoke({}, {'configurable':{'thread_id':'guards'}})
            freeze(run/'GRAPH_RESULT.json',result);state['status']='completed_pending_primary_review'
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:250]
            if state['pending'] is None:state['status']='needs_attention'
        finally:
            ledger.save();freeze(run/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'semantic_acceptance':'pending_primary_review'})
        print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':execute()
