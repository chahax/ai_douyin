"""One-shot controlled 1/3/5 complete-chapter context comparison; no retries."""
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jsonschema import validate
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.story_first_production_v1 import Ledger,NativeClient,routes
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.platform_adapter.fanqie_book_corpus import atomic

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT/'data/corpus_production_trials/20261027_serial_novel_v5_production'
RUN=ROOT/'data/corpus_production_trials/20261027_serial_context_comparison'
QUESTIONS=[
 '第一章开头前三句分别由谁对谁说？无法确定时说明。',
 '“哥哥发传单挣了十块，先给你”中的哥哥指谁，十块钱由谁挣得？',
 '截至第一章，十块钱的提出转交、接受或拒绝、最终去向各有什么证据？',
 '解释“他有些后悔，刚才死活不要二哥的钱，可是他要了，挨打的就是二哥了啊”中各个他及条件、因果关系。',
 '第一章中老大、老二、老六各是谁？哪些是明确命名，哪些只是推断？',
 '第一章苏墨身份、孩子与他的关系、原书未来和当前实际发生的事如何区分？'
]
SCHEMA={'type':'object','properties':{'answers':{'type':'array','minItems':6,'maxItems':6,'items':{'type':'object','properties':{'question_id':{'type':'integer','minimum':1,'maximum':6},'answer':{'type':'string'},'uncertainties':{'type':'string'},'evidence':{'type':'array','minItems':1,'items':{'type':'object','properties':{'chapter':{'type':'integer'},'quote':{'type':'string','minLength':1}},'required':['chapter','quote'],'additionalProperties':False}}},'required':['question_id','answer','uncertainties','evidence'],'additionalProperties':False}}},'required':['answers'],'additionalProperties':False}
PROMPT='你是小说阅读分析员。完整阅读提供的章节，回答六个问题。目标是第一章的理解；后章只帮助辨认身份，不得把后章发生的事件当成第一章已发生。依据原文解释，明确区分事实、推断和未交代事项。每个问题给出简洁解释和精确连续原文引文。不接受任何预设答案。一次submit_result提交全部六个答案。'

def payload(source,n):
 return {'target_chapter':1,'complete_chapters':source['chapters'][:n],'questions':[{'question_id':i+1,'question':q} for i,q in enumerate(QUESTIONS)]}

def check(value,source,n):
 validate(value,SCHEMA)
 assert [a['question_id'] for a in value['answers']]==list(range(1,7))
 texts={c['index']:c['text'] for c in source['chapters'][:n]}
 for a in value['answers']:
  for e in a['evidence']:assert e['chapter'] in texts and e['quote'] in texts[e['chapter']], 'quote_not_in_supplied_chapter'

def prepare():
 assert not RUN.exists()
 state=read(PARENT/'STATE.json');plan=read(PARENT/'PLAN.json');source=read(PARENT/'SOURCE.json');auth=read(PARENT/'AUTHORIZATION.json')
 assert state['pending'] is None and state['status']=='needs_attention'
 assert digest(source)==plan['source_sha256'] and auth['plan_sha256']==digest(plan)
 assert not (PARENT/'BUDGET_TRANSFER.json').exists()
 remaining=plan['max_calls']-state['calls_started'];assert remaining==381
 assert routes()==plan['routes']
 checks=[]
 for n in (1,3,5):
  p=payload(source,n)
  assert len(p['complete_chapters'])==n
  assert p['complete_chapters'][0]==source['chapters'][0]
  size=len(json.dumps([{'role':'system','content':PROMPT},{'role':'user','content':json.dumps({**p,'output_schema':SCHEMA},ensure_ascii=False)}],ensure_ascii=False).encode())+16384+1024
  assert size<131072
  checks.append({'chapters':n,'conservative_bytes_plus_output_reserve':size})
 RUN.mkdir()
 new={'version':'context_comparison/v1','source_sha256':digest(source),'routes':routes(),'max_calls':3,'context':131072,'inherited_calls':19,'original_cap':400,'available_before':381,'prior_semantic_repairs':2,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
 for k,v in [('PLAN',new),('SOURCE',source),('PREFLIGHT',checks),('AUTHORIZATION',{'user_statement':'试试：单章/3章/5章同题对照，沿用原69章外发MiniMax授权，仅3次文本，不生成媒体。','parent_authorization_sha256':digest(auth),'parent':str(PARENT),'plan_sha256':digest(new)})]:freeze(RUN/(k+'.json'),v)
 atomic(RUN/'STATE.json',{'status':'prepared','calls_started':0,'reported_tokens':0,'pending':None,'plan_sha256':digest(new)})
 freeze(PARENT/'BUDGET_TRANSFER.json',{'child':str(RUN),'remaining':remaining,'test_call_cap':3,'user_statement':'用户同意单章/3章/5章对照试验；累计19次，继承剩余381，本次仅3次，不重置语义返修。'})
 print(json.dumps(checks))

def execute():
 with run_lock(RUN):
  plan=read(RUN/'PLAN.json');state=read(RUN/'STATE.json');source=read(RUN/'SOURCE.json')
  assert state['status']=='prepared' and state['pending'] is None
  assert plan['script_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
  assert digest(plan)==state['plan_sha256'] and digest(source)==plan['source_sha256'] and routes()==plan['routes']
  freeze(RUN/'START.json',{'one_shot':True})
  ledger=Ledger(RUN,plan,state,NativeClient());results=[]
  try:
   for n in (1,3,5):
    name=f'CONTEXT_{n:02}'
    value=ledger.call(name,'writer',PROMPT,payload(source,n),SCHEMA)
    try:check(value,source,n);valid=True;error=None
    except Exception as exc:valid=False;error=type(exc).__name__+':'+str(exc)[:200]
    results.append({'chapters':n,'format_and_quotes_pass':valid,'error':error})
    print(json.dumps(results[-1]),flush=True)
   state['status']='completed_pending_primary_review'
  except Exception as exc:
   if state['pending'] is None:state['status']='needs_attention'
   results.append({'error':type(exc).__name__+':'+str(exc)[:200]})
  finally:
   ledger.save();freeze(RUN/'RESULT.json',{'results':results,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'cumulative_calls':19+state['calls_started'],'remaining_original_budget':381-state['calls_started'],'semantic_acceptance':'pending_primary_review','not_full_pipeline':True})
  print(json.dumps(read(RUN/'RESULT.json')),flush=True)

if __name__=='__main__':
 {'prepare':prepare,'execute':execute}[sys.argv[1]]()
