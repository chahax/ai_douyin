"""One remaining audit call; lossless exact-quote spans, failed quotes retained."""
from trial_serial_understanding_20261027 import *
from copy import deepcopy
PILOT=RUN
AUDIT_RUN=ROOT/'data/corpus_production_trials/20261027_serial_understanding_audit'

def compact(materials,source):
 texts={c['index']:c['text'] for c in source['chapters'][:5]};out=deepcopy(materials);count=0
 for m in out:
  for e in m['entries']:
   for ref in e['evidence']:
    text=texts[ref['chapter']];quote=ref['quote'];start=text.find(quote)
    if start>=0:
     ref.pop('quote');ref['source_span']=[start,start+len(quote)];count+=1
    else:ref['quote_not_exact']=True
 rebuilt=deepcopy(out)
 for m in rebuilt:
  for e in m['entries']:
   for ref in e['evidence']:
    if 'source_span' in ref:
     a,b=ref.pop('source_span');ref['quote']=texts[ref['chapter']][a:b]
    ref.pop('quote_not_exact',None)
 if rebuilt!=materials:raise ValueError('not_lossless')
 return out,count

def main():
 if AUDIT_RUN.exists():raise ValueError('no_replay')
 ps=read(PILOT/'STATE.json');pp=read(PILOT/'PLAN.json');source=read(PILOT/'SOURCE.json');r=read(PILOT/'RESULT.json')
 if ps['pending'] is not None or ps['calls_started']!=6 or ps['status']!='needs_attention' or (PILOT/'BUDGET_TRANSFER.json').exists():raise ValueError('parent_not_ready')
 if digest(source)!=pp['source_sha256'] or digest(pp)!=ps['plan_sha256'] or routes()!=pp['routes']:raise ValueError('parent_changed')
 ms=[read(PILOT/f'MATERIAL_{n:02}.json') for n in range(1,6)]
 packed,count=compact(ms,source)
 payload={'complete_chapters':[{'index':c['index'],'title':c['title'],'text':c['text']} for c in source['chapters'][:5]],'materials':[{'chapter':n+1,'candidate':m,'original_candidate_sha256':digest(ms[n])} for n,m in enumerate(packed)],'evidence_encoding':'source_span是对应完整章text的Python Unicode字符[start,end)位置，程序已经逐字可逆核验。quote_not_exact表示原模型引文无法匹配，保留原样，不能视作有效证据。','contract_checks':read(PILOT/'CHECKS.json')}
 prompt=POLICY+REVIEW
 messages=[{'role':'system','content':prompt+' 只调用submit_result提交结果。'},{'role':'user','content':json.dumps({**payload,'output_schema':AUDIT},ensure_ascii=False)}]
 size=len(json.dumps(messages,ensure_ascii=False).encode())+16384+1024
 if size>131072:raise ValueError('still_over_capacity')
 p={'version':'understanding_audit/v1','routes':routes(),'source_sha256':digest(source),'max_calls':1,'context':131072,'inherited_calls':28,'available_before':372,'original_cap':400,'prior_semantic_repairs':2,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
 AUDIT_RUN.mkdir()
 for name,value in [('PLAN',p),('SOURCE',source),('INPUT',payload),('PREFLIGHT',{'lossless_roundtrip':True,'replaced_exact_quotes':count,'bytes_plus_reserve':size}),('AUTHORIZATION',{'user_statement':'原前5章7次小样的第7次审核；首次在HTTP前容量拒绝，压缩重复引文后新独立一次审核，无原任务重跑。','parent_authorization_sha256':digest(read(PILOT/'AUTHORIZATION.json')),'plan_sha256':digest(p)})]:freeze(AUDIT_RUN/(name+'.json'),value)
 freeze(PILOT/'BUDGET_TRANSFER.json',{'child':str(AUDIT_RUN),'remaining':372,'test_call_cap':1,'inherited_calls':28,'user_statement':'同一已授权7次小样剩余1次，不重置总预算及语义返修。'})
 state={'status':'prepared','pending':None,'calls_started':0,'reported_tokens':0,'plan_sha256':digest(p)};atomic(AUDIT_RUN/'STATE.json',state)
 print('lossless_quotes',count,'capacity',size,flush=True)
 with run_lock(AUDIT_RUN):
  freeze(AUDIT_RUN/'START.json',{'one_shot':True});ledger=Ledger(AUDIT_RUN,p,state,NativeClient());error=None
  try:
   value=ledger.call('RECONCILE','writer',prompt,payload,AUDIT)
   check(value,source,AUDIT,materials=ms);state['status']='completed_pending_primary_review'
  except Exception as exc:
   error=type(exc).__name__+':'+str(exc)[:240]
   if state['pending'] is None:state['status']='needs_attention'
  finally:
   ledger.save();freeze(AUDIT_RUN/'RESULT.json',{'error':error,'calls':state['calls_started'],'reported_tokens':state['reported_tokens'],'pending':state['pending'],'cumulative_calls':28+state['calls_started'],'remaining_original_budget':372-state['calls_started'],'semantic_acceptance':'pending_primary_review'})
  print(json.dumps(read(AUDIT_RUN/'RESULT.json')),flush=True)
if __name__=='__main__':main()
