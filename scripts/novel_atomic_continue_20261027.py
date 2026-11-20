"""Known receipt adoption; absent no-change proposal is semantically null."""
import novel_atomic_review_20261027 as a
from novel_atomic_review_20261027 import *
class OptionalRow(Row):
    replacement:Fact|None=None
class OptionalBatch(Strict):rows:list[OptionalRow]
def normalize(raw):return OptionalBatch.model_validate(raw).model_dump()
def main():
    run=OUT.with_name(OUT.name+'_continued')
    if run.exists():raise ValueError('no_replay')
    result=read(OUT/'RESULT.json')
    if result['pending'] is not None or result['calls']!=1 or not result['error'].startswith('ValidationError:'):raise ValueError('unexpected_parent')
    receipt=read(OUT/'R0_B00/RESPONSE_1.json');choice=receipt['native']['choices'][0]
    calls=choice['message']['tool_calls']
    if choice['finish_reason']!='tool_calls' or len(calls)!=1 or calls[0]['function']['name']!='submit_result':raise ValueError('unknown_native')
    raw=normalize(json.loads(calls[0]['function']['arguments']))
    initial=read(OUT/'MATERIAL_0.json');source=read(OUT/'SOURCE.json');ledger=read(OUT/'LEDGER_0.json')
    validate_batch(raw,bind(initial)[:7],source,ledger)
    run.mkdir();dump(run/'ADOPTION.json',{'parent':str(OUT),'receipt_sha256':sha(receipt),'initial_sha256':sha(initial),'source_sha256':sha(source),'prior_calls':1,'remaining_calls':10,'total_limit_unchanged':11,'policy':'仅将缺失的无修改proposal解释为null；有错误却无proposal仍拒绝；不改原生回执','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();error=None;status='needs_attention'
    def call(name,prompt,payload,output):
        if name=='R0_B00':return raw
        if session.calls>=10:raise ValueError('cumulative_limit')
        if output is Batch:
            return normalize(session.call(name,prompt+' 无修改时replacement可为null或省略；发现错误仍必须给replacement。',payload,OptionalBatch))
        return session.call(name,prompt,payload,output)
    try:
        final,ledger,status=drive_atomic(initial,source,ledger,call,lambda n,v:dump(run/(n+'.json'),v));dump(run/'FINAL_MATERIAL.json',final);dump(run/'FINAL_LEDGER.json',ledger)
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':1,'pending':session.pending,'error':error,'primary_acceptance':'pending'})
    print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
