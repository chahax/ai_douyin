"""Reuse known specialist receipts and give exact citation feedback once per stage."""
from novel_specialist_review_20261027 import *
def native_value(path):
    receipt=read(path);n=receipt['native'];u=n['usage'];c=n['choices']
    if n['model']!=MODEL or len(c)!=1 or c[0]['finish_reason']!='tool_calls' or u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']:raise ValueError('unknown_or_wrong_native')
    tc=c[0]['message']['tool_calls']
    if len(tc)!=1 or tc[0]['function']['name']!='submit_result':raise ValueError('not_single_native_result')
    return json.loads(tc[0]['function']['arguments']),receipt
def citation_errors(value,source,key):
    known={p['id']:p['text'] for p in source};errors=[]
    for i,p in enumerate(value[key]):
        for j,e in enumerate(p['evidence']):
            if e['source_id'] not in known or e['quote'] not in known[e['source_id']]:
                errors.append({'item_index':i,'evidence_index':j,'provided':e,'actual_text_at_id':known.get(e['source_id']),'exact_quote_matches':[k for k,v in known.items() if e['quote'] in v]})
    return errors
def main(arm):
    parent=BASE/arm;run=BASE/(arm+'_continued');prior=read(parent/'RESULT.json')
    if run.exists() or prior['pending'] is not None:raise ValueError('no_replay_or_unknown')
    if prior['error']!='ValueError:evidence_not_exact':raise ValueError('not_citation_failure')
    source=read(BASE/'SOURCE.json');initial=read(BASE/(arm+'_INITIAL.json'));cached={};bindings=[]
    for path in sorted(parent.glob('R0_*/RESPONSE_1.json')):
        value,receipt=native_value(path);cached[path.parent.name]=value;bindings.append({'stage':path.parent.name,'sha256':sha(receipt),'tokens':receipt['native']['usage']['total_tokens']})
    if len(bindings)!=prior['calls']:raise ValueError('unreconciled_call_count')
    run.mkdir();dump(run/'ADOPTION.json',{'parent':str(parent),'native_bindings':bindings,'initial_sha256':sha(initial),'source_sha256':sha(source),'prior_calls':prior['calls'],'total_engineering_limit':13,'remaining_calls':13-prior['calls'],'additional_repairs_limit_unchanged':2,'note':'原11次工程预留新增最多2次精确引用协议修正，不重置原调用；沿用户MiniMax套餐多轮测试授权，不重复派发旧请求。','pins':pins(),'continuation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();failure=None;status='needs_attention';iterations=0;used=set()
    def dispatch(name,prompt,payload,output):
        if session.calls+prior['calls']>=13:raise ValueError('cumulative_engineering_limit')
        return session.call(name,prompt,payload,output)
    def call(name,prompt,payload,output):
        if name in cached:
            if name in used:raise ValueError('cached_stage_repeated')
            used.add(name);value=cached[name];dump(run/(name+'_ADOPTED_RAW.json'),value)
        else:value=dispatch(name,prompt,payload,output)
        key='patches' if output is Audit else 'checks';errors=citation_errors(value,source,key)
        if errors:
            dump(run/(name+'_CITATION_ERRORS.json'),errors)
            value=dispatch(name+'_PROTOCOL',prompt+' 上次回执有精确引用绑定错误。根据给定实际原段和匹配地址修正证据，返回完整当前审核结果。不得编造引文，仍须核对意见内容，不把候选删空逃避核验。',{**payload,'previous_native_result':value,'citation_errors':errors},output)
        return value
    try:
        final,status,iterations=drive(initial,source,call,lambda n,v:dump(run/(n+'.json'),v));dump(run/'FINAL_MATERIAL.json',final)
    except Exception as exc:failure=type(exc).__name__+':'+str(exc)[:600]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'pending':session.pending,'error':failure,'new_repairs':iterations,'adopted_prior_calls':prior['calls'],'acceptance':'pending_primary_review'})
    print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main(sys.argv[1])
