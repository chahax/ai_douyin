"""Resolve ambiguous compression with source-faithful model rewrite, not error voting."""
from novel_independent_review_20261027 import *
PRECISION='''对指定材料做忠实原文的精确改写。这不是要求认定原句错误：即使原句存在合理读法，也尽量避免下游读成更强的心理、因果或群体结论。优先保留原文明确的行为与态度措辞，不把有威信、收起想法概括成所有人内心一致，也不反过来新增所有人内心不同。未明确署名的对白不补名字。保留原条目所有重要信息，包括场景、行为、顾虑及时间；不能手造新事件、删掉难题或套用审核意见。每个指定fact_id输出一个完整replacement（statement/source_ids/mode），无空对象。'''
def main():
    run=RUN.with_name(RUN.name+'_precision');second=RUN.with_name(RUN.name+'_source_first')
    if run.exists():raise ValueError('no_replay')
    states=[read(p/'RESULT.json') for p in [RUN,second]];used=sum(x['calls'] for x in states)
    if used!=6 or any(x['pending'] is not None for x in states):raise ValueError('budget_or_unknown')
    initial=read(second/'FINAL_MATERIAL.json');source=read(OUT/'SOURCE.json');facts=[f for f in bind(initial) if f['id']=='F014']
    run.mkdir();dump(run/'PLAN.json',{'prior_calls':used,'remaining_calls':5,'total_limit_unchanged':11,'prior_repairs_applied':0,'additional_repair_limit':1,'candidate_sha256':sha(initial),'policy':'原句存在可接受读法也允许有据且保留信息的精确化；不冒称已裁决原句必错；非盲测','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();status='needs_attention';error=None
    def call(*args):
        if session.calls>=5:raise ValueError('cumulative_limit')
        return session.call(*args)
    try:
        edits=validate_edits(call('PRECISION_REWRITE',PRECISION,{'complete_source':source,'facts':facts,'candidate_sha256':sha(initial)},Edits),['F014'],source);dump(run/'EDITS.json',edits)
        patches=[{'id':x['fact_id'],'fact_id':x['fact_id'],'replacements':[x['replacement']]} for x in edits['edits']];tasks=content_tasks(patches,initial)
        checks=validate_checks(ground(call('RETENTION',NEW_JUDGE,{'complete_source':source,'checks':tasks,'candidate_sha256':sha(initial)},RefChecks),source,'checks'),tasks,source);dump(run/'RETENTION.json',checks)
        current,changes=apply_patches(initial,patches,tasks,checks);dump(run/'CHANGES.json',changes);dump(run/'FINAL_MATERIAL.json',current)
        class Bounded:
            def call(self,*args):return call(*args)
        final=review_all('FINAL_REVIEW',current,source,Bounded(),run);dump(run/'FINAL_REVIEW.json',final)
        ledger=read(ROOT/'data/corpus_production_trials/20261027_atomic_review_ids/FINAL_LEDGER.json');dump(run/'LEDGER_RECONCILED.json',reconcile(ledger,final,sha(current)))
        status='machine_pass_pending_primary' if all(x['decision']=='supported' for r in final['rows'] for x in r['findings']) else 'needs_revision'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':used,'pending':session.pending,'error':error,'primary_acceptance':'pending'});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
