"""Isolated LangGraph trial with native immutable ledger and SQLite checkpoints."""
import os
os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'
import sys,hashlib,json,importlib.metadata
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[1]/'.venv/Lib/site-packages'))
from src.content_factory.novel_evidence_graph_v1 import build_graph
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.story_first_production_v1 import Ledger,NativeClient,routes
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.platform_adapter.fanqie_book_corpus import atomic
from langgraph.checkpoint.sqlite import SqliteSaver
ROOT=Path(__file__).resolve().parents[1]
PILOT=ROOT/'data/corpus_production_trials/20261027_serial_understanding_pilot'
CASES=[('BACKGROUND','C03',False),('BACKGROUND','C05',True),('BACKGROUND','C08',False),('BACKGROUND','W04',True),('MATERIAL_01','C1-21',False),('MATERIAL_01','C1-11',True),('MATERIAL_02','T01',False),('MATERIAL_02','T17',True),('MATERIAL_03','E3-03',False),('MATERIAL_03','E3-06',True),('MATERIAL_04','T04-E03',False),('MATERIAL_04','T04-E09',True),('MATERIAL_05','C5_03',True),('MATERIAL_05','C5_11',False),('MATERIAL_05','C5_18',True)]

def main(mode):
    if mode not in ('benchmark','fresh'):raise ValueError('mode')
    run=ROOT/f'data/corpus_production_trials/20261027_langgraph_{mode}'
    if run.exists():raise ValueError('ended_or_existing_no_replay')
    source=read(PILOT/'SOURCE.json');source={'chapters':source['chapters'][:5]}
    claims=[];expected=[]
    if mode=='benchmark':
        for n,(file,id,ok) in enumerate(CASES,1):
            candidate=next(e for e in read(PILOT/(file+'.json'))['entries'] if e['id']==id)
            claims.append({'id':f'T{n:02}','statement':candidate['statement'],'source_ids':[]})
            expected.append({'id':f'T{n:02}','expected_supported':ok,'origin':file,'original_id':id,'native_candidate_sha256':digest(candidate)})
    pins={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'src/content_factory/novel_evidence_graph_v1.py']}
    plan={'version':'langgraph_evidence/v1','mode':mode,'routes':routes(),'source_sha256':digest(source),'max_calls':5 if mode=='benchmark' else 7,'context':131072,'implementation_pin':pins,'engineering_guard_not_purchase_quota':True,'original_audit_pending_untouched':True,'versions':{x:importlib.metadata.version(x) for x in ['langgraph','langgraph-checkpoint-sqlite','pydantic','openai']}}
    run.mkdir()
    for n,v in [('PLAN',plan),('SOURCE',source),('AUTHORIZATION',{'user_statement':'minimax你可以随便造我弄的套餐形式，你可以用开源的agent框架套只要能让它更好的分析小说生产剧本就好，这个框架不行就换一个','scope':'原授权小说前5章MiniMax分析核查实验，无媒体发布；旧未知审核不重派','plan_sha256':digest(plan)}),('BENCHMARK_EXPECTATIONS_NOT_SENT',expected)]:freeze(run/(n+'.json'),v)
    state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(plan)};atomic(run/'STATE.json',state)
    with run_lock(run),SqliteSaver.from_conn_string(str(run/'graph.sqlite')) as saver:
        ledger=Ledger(run,plan,state,NativeClient())
        def caller(name,prompt,payload,schema):
            result=ledger.call(name,'writer',prompt,payload,schema)
            print(name+' native returned',flush=True)
            return result
        graph=build_graph(source,caller,saver,seeded=mode=='benchmark')
        freeze(run/'GRAPH.json',{'mermaid':graph.get_graph().draw_mermaid()})
        error=None
        try:
            result=graph.invoke({'claims':claims,'cursor':0,'findings':[]},{'configurable':{'thread_id':mode},'recursion_limit':30})
            freeze(run/'GRAPH_RESULT.json',result);state['status']='completed_pending_primary_review'
            if expected:
                accepted={x['id'] for x in result['accepted']}
                evaluation=[{**x,'actual_supported':x['id'] in accepted,'matches':(x['id'] in accepted)==x['expected_supported']} for x in expected]
                freeze(run/'BENCHMARK_SCORE.json',evaluation)
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:250]
            if state['pending'] is None:state['status']='needs_attention'
        finally:
            ledger.save();freeze(run/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'semantic_acceptance':'pending_primary_review','unknown_old_audit_untouched':True})
        print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main(sys.argv[1])
