"""Use the seven unspent calls for source-first extraction and targeted comparison."""
from novel_independent_review_20261027 import *
class Observation(Strict):
    source_ids:list[str]=Field(min_length=1)
    explicit_information:str
    unspecified_information:str
class Observations(Strict):observations:list[Observation]=Field(min_length=1)
SOURCE_PROMPT='''只阅读原文，对指定原段提取明确说了什么、什么没有明说。上下文用于辨认指代，不用常识补姓名、内心、事件。直接引语没有明示说话人就说明未明示，不能按说话顺序猜某个孩子。区分叙述者交代、人物说过、人物内心。保留有威信、接受安排、沉默、内心赞同之间的区别。输出来源ID，explicit_information和unspecified_information。这里不提供候选，不评价任何候选。'''
COMPARE_PROMPT=PROMPT_CURRENT+'''
本次对每一项（包括想判supported的项）都做反例检验：原文保持全部为真时，候选这一项是否仍可能不成立？能则给出最小的相容解释并判insufficient；不能则明确解释原文哪项排除了替代。alternative_consistent_with_source不许留空。不是捏造新事件或质疑原文，而是检验候选是否加了未确定的主体/心理/因果。附带observations只是另一次模型提取，可能出错，必须回到原文核对；不可当权威证据。'''
def main():
    run=RUN.with_name(RUN.name+'_source_first')
    if run.exists():raise ValueError('no_replay')
    state=read(RUN/'RESULT.json')
    if state['pending'] is not None or state['calls']!=4:raise ValueError('unexpected_parent')
    initial=read(RUN/'FINAL_MATERIAL.json');source=read(OUT/'SOURCE.json');facts=[f for f in bind(initial) if f['id'] in ('F014','F015')]
    focus=[p['id'] for p in source if p['chapter']==9 and 131<=int(p['id'].split('P')[1])<=163]
    run.mkdir();dump(run/'PLAN.json',{'prior_calls':4,'remaining_calls':7,'total_limit_unchanged':11,'additional_repair_round_limit':1,'candidate_sha256':sha(initial),'source_sha256':sha(source),'scope':'已知F014与已修正F015的定向对照；本轮留出结果不用于改提示','implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();current=initial;status='needs_attention';error=None
    def call(name,prompt,payload,output):
        if session.calls>=7:raise ValueError('cumulative_limit')
        return session.call(name,prompt,payload,output)
    try:
        obs=Observations.model_validate(call('SOURCE_ONLY',SOURCE_PROMPT,{'complete_source':source,'focus_source_ids':focus},Observations)).model_dump()
        known={p['id'] for p in source}
        if any(not set(x['source_ids'])<=known for x in obs['observations']):raise ValueError('unknown_source')
        dump(run/'OBSERVATIONS.json',obs)
        raw=call('COMPARE',COMPARE_PROMPT,{**payload_for(source,facts),'observations':obs},CurrentReview);rv=validate_review(raw,facts,source)
        if any(not x['alternative_consistent_with_source'].strip() for r in rv['rows'] for x in r['findings']):raise ValueError('missing_counterexample_check')
        dump(run/'COMPARE.json',rv);bad=[r for r in rv['rows'] if any(x['decision']!='supported' for x in r['findings'])]
        if bad:
            wanted={r['fact_id'] for r in bad};original=[f for f in facts if f['id'] in wanted]
            edits=validate_edits(call('REPAIR',PROMPT_EDIT,{'complete_source':source,'facts':original,'review':bad,'candidate_sha256':sha(initial)},Edits),wanted,source);dump(run/'EDITS.json',edits)
            patches=[{'id':x['fact_id'],'fact_id':x['fact_id'],'replacements':[x['replacement']]} for x in edits['edits']];tasks=content_tasks(patches,initial)
            checks=validate_checks(ground(call('RETENTION',NEW_JUDGE,{'complete_source':source,'checks':tasks,'candidate_sha256':sha(initial)},RefChecks),source,'checks'),tasks,source);dump(run/'RETENTION.json',checks)
            current,changes=apply_patches(initial,patches,tasks,checks);dump(run/'CHANGES.json',changes);dump(run/'MATERIAL_1.json',current)
            class Bounded:
                def call(self,*args):return call(*args)
            final=review_all('FINAL_REVIEW',current,source,Bounded(),run)
        else:final=read(RUN/'FINAL_REVIEW.json')
        dump(run/'FINAL_MATERIAL.json',current);dump(run/'FINAL_REVIEW.json',final)
        ledger=read(ROOT/'data/corpus_production_trials/20261027_atomic_review_ids/FINAL_LEDGER.json');dump(run/'LEDGER_RECONCILED.json',reconcile(ledger,final,sha(current)))
        status='machine_pass_pending_primary' if all(x['decision']=='supported' for r in final['rows'] for x in r['findings']) else 'needs_revision'
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:700]
    session.save();dump(run/'RESULT.json',{'status':status,'calls':session.calls,'tokens':session.tokens,'prior_calls':4,'pending':session.pending,'error':error,'primary_acceptance':'pending'});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
