from run_novel_evidence_graph_trial import *
from src.content_factory.novel_literal_review_v3 import build_graph

def execute(mode):
    if mode not in ['benchmark','fresh']:raise ValueError('mode')
    run=ROOT/f'data/corpus_production_trials/20261027_literal_v3_{mode}'
    if run.exists():raise ValueError('no_replay')
    source=read(PILOT/'SOURCE.json');source={'chapters':source['chapters'][:5 if mode=='benchmark' else 1]}
    cases=[('MATERIAL_02','T17',True),('MATERIAL_03','E3-03',False),('MATERIAL_04','T04-E03',False),('BACKGROUND','C03',False),('MATERIAL_04','T04-E09',True),('MATERIAL_05','C5_03',True)]
    claims=[];expected=[]
    if mode=='benchmark':
        for n,(file,id,ok) in enumerate(cases,1):
            c=next(x for x in read(PILOT/(file+'.json'))['entries'] if x['id']==id)
            claims.append({'id':f'T{n:02}','statement':c['statement'],'time_scope':c['time_scope'],'source_ids':[]})
            expected.append({'id':f'T{n:02}','expected_supported':ok,'origin':file,'original_id':id,'candidate_sha256':digest(c)})
        prev=ROOT/'data/corpus_production_trials/20261027_langgraph_v2_fresh'
        for id,scope,ok in [('C09','current',True),('C07','unknown',False),('C04','original_novel_future',True)]:
            c=next(x for x in read(prev/'EXTRACT.json')['claims'] if x['id']==id);newid=f'T{len(claims)+1:02}'
            claims.append({**c,'id':newid,'time_scope':scope});expected.append({'id':newid,'expected_supported':ok,'origin':str(prev),'original_id':id,'candidate_sha256':digest(c),'scope_annotation_for_test':scope})
    module=ROOT/'src/content_factory/novel_literal_review_v3.py'
    plan={'version':'literal_review/v3','mode':mode,'routes':routes(),'source_sha256':digest(source),'max_calls':3 if mode=='benchmark' else 30,'context':131072,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'module_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),'engineering_guard_not_purchase_quota':True,'old_unknown_untouched':True}
    run.mkdir()
    for n,v in [('PLAN',plan),('SOURCE',source),('EXPECTATIONS_NOT_SENT',expected),('AUTHORIZATION',{'user_statement':'继续完善；沿原MiniMax套餐及小说文本分析测试授权。','plan_sha256':digest(plan),'no_media':True})]:freeze(run/(n+'.json'),v)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)};atomic(run/'STATE.json',state)
    error=None
    with run_lock(run),SqliteSaver.from_conn_string(str(run/'graph.sqlite')) as saver:
        ledger=Ledger(run,plan,state,NativeClient())
        def caller(name,prompt,payload,schema):
            value=ledger.call(name,'writer',prompt,payload,schema);print(name+' native returned',flush=True);return value
        try:
            result=build_graph(source,caller,saver,seeded=mode=='benchmark').invoke({'claims':claims,'cursor':0,'findings':[]},{'configurable':{'thread_id':mode},'recursion_limit':70})
            freeze(run/'GRAPH_RESULT.json',result);state['status']='completed_pending_primary_review'
            if expected:
                verdicts={f['claim_id']:f['verdict']=='supported' for f in result['findings']}
                freeze(run/'SCORE.json',[{**e,'actual_supported':verdicts[e['id']],'matches':verdicts[e['id']]==e['expected_supported']} for e in expected])
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:250]
            if state['pending'] is None:state['status']='needs_attention'
        finally:
            ledger.save();freeze(run/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'semantic_acceptance':'pending_primary_review'})
        print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':execute(sys.argv[1])
