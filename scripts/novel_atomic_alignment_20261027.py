"""Exact content alignment; punctuation gaps are retained from the candidate."""
from novel_atomic_continue_20261027 import *
import unicodedata
def punctuation_only(s):return all(c.isspace() or unicodedata.category(c).startswith('P') for c in s)
def align(raw,facts):
    value=normalize(raw);index={f['id']:f for f in facts}
    for r in value['rows']:
        text=index[r['fact_id']]['statement'];cursor=0
        for atom in r['atoms']:
            span=atom['span'];pos=text.find(span,cursor)
            if pos<0 or not punctuation_only(text[cursor:pos]):raise ValueError('nonpunctuation_gap_or_changed_atom:'+r['fact_id'])
            atom['span']=text[cursor:pos+len(span)];cursor=pos+len(span)
        if not punctuation_only(text[cursor:]):raise ValueError('nonpunctuation_tail:'+r['fact_id'])
        r['atoms'][-1]['span']+=text[cursor:]
    return value
def main():
    parent=OUT.with_name(OUT.name+'_continued');run=OUT.with_name(OUT.name+'_aligned')
    if run.exists():raise ValueError('no_replay')
    parents=[read(p/'RESULT.json') for p in [OUT,parent]]
    if any(r['pending'] is not None for r in parents):raise ValueError('unknown_parent')
    used=sum(r['calls'] for r in parents);initial=read(OUT/'MATERIAL_0.json');source=read(OUT/'SOURCE.json');ledger=read(OUT/'LEDGER_0.json');cache={};receipts=[]
    for n,p,offset in [('R0_B00',OUT,0),('R0_B01',parent,7)]:
        receipt=read(p/n/'RESPONSE_1.json');c=receipt['native']['choices'][0];tc=c['message']['tool_calls']
        if c['finish_reason']!='tool_calls' or len(tc)!=1 or tc[0]['function']['name']!='submit_result':raise ValueError('native_protocol')
        raw=json.loads(tc[0]['function']['arguments']);value=align(raw,bind(initial)[offset:offset+7]);validate_batch(value,bind(initial)[offset:offset+7],source,ledger);cache[n]=value
        receipts.append({'path':str(p/n/'RESPONSE_1.json'),'sha256':sha(receipt)})
    run.mkdir();dump(run/'ADOPTION.json',{'prior_calls':used,'remaining_calls':11-used,'total_limit_unchanged':11,'receipts':receipts,'initial_sha256':sha(initial),'policy':'顺序匹配模型原样文字，仅把候选中被省略的标点/空白附回跨度；不能补任何字词，包括否定；保留原生及派生视图','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();status='needs_attention';error=None
    def call(name,prompt,payload,output):
        if name in cache:return cache[name]
        if session.calls>=11-used:raise ValueError('cumulative_limit')
        if output is Batch:
            raw=session.call(name,prompt+' 无修改时replacement可省略或null。',payload,OptionalBatch)
            value=align(raw,payload['facts']);dump(run/(name+'_PROGRAM_ALIGNED.json'),value);return value
        return session.call(name,prompt,payload,output)
    try:
        final,ledger,status=drive_atomic(initial,source,ledger,call,lambda n,v:dump(run/(n+'.json'),v));dump(run/'FINAL_MATERIAL.json',final);dump(run/'FINAL_LEDGER.json',ledger)
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':used,'pending':session.pending,'error':error,'primary_acceptance':'pending'})
    print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
