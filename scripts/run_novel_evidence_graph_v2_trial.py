"""New independent v2 run; explicit adoption of known first batch, no v1 replay."""
from run_novel_evidence_graph_trial import *
from src.content_factory.novel_evidence_protocol_v2 import inline_schema
from src.content_factory.novel_evidence_graph_v1 import Findings,validate_findings,source_catalog

def execute_v2(mode):
    if mode not in ('benchmark','fresh'):raise ValueError('mode')
    run=ROOT/f'data/corpus_production_trials/20261027_langgraph_v2_{mode}'
    if run.exists():raise ValueError('existing_run_no_replay')
    source=read(PILOT/'SOURCE.json');source={'chapters':source['chapters'][:5]}
    old=ROOT/'data/corpus_production_trials/20261027_langgraph_benchmark'
    claims=[];expected=[];initial={'claims':[],'cursor':0,'findings':[]};adoption={}
    if mode=='benchmark':
        if read(old/'STATE.json')['pending'] is not None:raise ValueError('old_pending')
        if digest(source)!=read(old/'PLAN.json')['source_sha256']:raise ValueError('source_changed')
        expected=read(old/'BENCHMARK_EXPECTATIONS_NOT_SENT.json')
        for n,(file,id,ok) in enumerate(CASES,1):
            c=next(e for e in read(PILOT/(file+'.json'))['entries'] if e['id']==id)
            if digest(c)!=expected[n-1]['native_candidate_sha256']:raise ValueError('candidate_changed')
            claims.append({'id':f'T{n:02}','statement':c['statement'],'source_ids':[]})
        first=read(old/'AUDIT_01.json')
        validate_findings(first,claims[:3],source_catalog(source))
        native=read(old/'RESPONSE_001.json')['native'];args=native['choices'][0]['message']['tool_calls'][0]['function']['arguments']
        if json.loads(args)!=first:raise ValueError('native_adoption_mismatch')
        initial={'claims':claims,'cursor':3,'findings':first['findings']}
        adoption={'run':str(old),'adopted_first_batch_sha256':digest(first),'known_failed_batch_sha256':digest(read(old/'AUDIT_02.json')),'old_calls':2,'old_reported_tokens':read(old/'STATE.json')['reported_tokens']}
    plan={'version':'langgraph_evidence/v2','mode':mode,'routes':routes(),'source_sha256':digest(source),'max_calls':8,'context':131072,'engineering_guard_not_purchase_quota':True,'old_unknown_untouched':True,'adoption':adoption,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    run.mkdir()
    for n,v in [('PLAN',plan),('SOURCE',source),('AUTHORIZATION',{'user_statement':'沿当前用户MiniMax套餐开发测试授权，原小说前5章，改协议后继续已知结果；无旧未知重派、无媒体发布。','plan_sha256':digest(plan)}),('BENCHMARK_EXPECTATIONS_NOT_SENT',expected)]:freeze(run/(n+'.json'),v)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)};atomic(run/'STATE.json',state)
    with run_lock(run),SqliteSaver.from_conn_string(str(run/'graph.sqlite')) as saver:
        ledger=Ledger(run,plan,state,NativeClient())
        def caller(name,prompt,payload,schema):
            actual=name
            if mode=='benchmark' and name=='AUDIT_02':
                payload={**payload,'invalid_output':read(old/'AUDIT_02.json'),'validation_error':'atoms必须直接是JSON数组，不是包含item键的对象。只修正格式，所有主张仍须据原文核查。'}
                actual=name+'_EXPLICIT_PROTOCOL_REPAIR'
            prompt+=' 输出数组直接使用[]，不可用item/items对象包裹；输出数据而非Schema。'
            value=ledger.call(actual,'writer',prompt,payload,inline_schema(schema))
            print(actual+' native returned',flush=True)
            return value
        error=None
        try:
            result=build_graph(source,caller,saver,seeded=mode=='benchmark').invoke(initial,{'configurable':{'thread_id':mode},'recursion_limit':30})
            freeze(run/'GRAPH_RESULT.json',result);state['status']='completed_pending_primary_review'
            if expected:
                accepted={c['id'] for c in result['accepted']}
                freeze(run/'BENCHMARK_SCORE.json',[{**x,'actual_supported':x['id'] in accepted,'matches':(x['id'] in accepted)==x['expected_supported']} for x in expected])
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:250]
            if state['pending'] is None:state['status']='needs_attention'
        finally:
            ledger.save();freeze(run/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'semantic_acceptance':'pending_primary_review','old_unknown_untouched':True})
        print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':execute_v2(sys.argv[1])
