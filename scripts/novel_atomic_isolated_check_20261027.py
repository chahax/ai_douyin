"""One remaining call: current candidate only, no old diagnostic prose."""
from novel_atomic_ids_20261027 import *
def main():
    parent=OUT.with_name(OUT.name+'_ids');run=OUT.with_name(OUT.name+'_verification')
    if run.exists():raise ValueError('no_replay')
    dirs=[OUT,OUT.with_name(OUT.name+'_continued'),OUT.with_name(OUT.name+'_aligned'),parent]
    states=[read(p/'RESULT.json') for p in dirs];used=sum(x['calls'] for x in states)
    if used!=10 or any(x['pending'] is not None for x in states):raise ValueError('budget_or_unknown')
    source=read(OUT/'SOURCE.json');material=read(parent/'FINAL_MATERIAL.json');facts=[f for f in bind(material) if f['id'] in ('F014','F015')]
    run.mkdir();dump(run/'PLAN.json',{'candidate_sha256':sha(material),'source_sha256':sha(source),'prior_calls':used,'remaining_calls':1,'total_limit':11,'purpose':'独立核验当前两条，不附历史问题措辞，不生成或应用新材料','selection':'F015已出现旧诊断污染；F014上轮助手疑似过度断言的留存问题；不是盲测','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();error=None;status='needs_attention'
    try:
        raw=session.call('CURRENT_ONLY',ID_PROMPT,{'complete_source':source,'facts':facts,'clauses':clauses(facts),'target_chapters':[9,10],'unresolved':[],'candidate_sha256':sha(material)},IdBatch)
        review=validate_batch(materialize(raw,facts),facts,source,[]);dump(run/'REVIEW.json',{'candidate_sha256':sha(material),**review});status='reviewed_not_applied'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':used,'pending':session.pending,'error':error});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
