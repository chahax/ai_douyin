"""Continue only after reconciling every known receipt; append-only local state."""
from novel_multiround_20261027 import *
class AppendSession(Session):
    def __init__(self,run):super().__init__(run);self.snapshot=0
    def save(self):
        self.snapshot+=1;dump(self.run/f'STATE_{self.snapshot:03}.json',{'calls':self.count,'tokens':self.tokens,'pending':self.pending,'error':self.error})
def main():
    parent=BASE/'baseline';run=BASE/'baseline_continued'
    if run.exists():raise ValueError('no_replay')
    source=read(BASE/'SOURCE.json');initial=read(parent/'MATERIAL_0.json');review=read(parent/'BOUND_REVIEW_0.json')['review'];known=[]
    for stage in ('ANALYZE','REVIEW_0','JUDGE_0'):
        receipt=read(parent/stage/'RESPONSE_1.json');native=receipt['native'];leaf=read(parent/stage/'STATE.json')
        u=native['usage'];choice=native['choices'][0]
        if leaf['pending'] is not None or native['model']!=MODEL or choice['finish_reason']!='tool_calls' or u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']:raise ValueError('receipt_not_reconciled')
        known.append({'stage':stage,'native_sha256':sha(receipt),'tokens':u['total_tokens']})
    calls=native['choices'][0]['message']['tool_calls']
    if len(calls)!=1 or calls[0]['function']['name']!='submit_result':raise ValueError('not_single_submission')
    judge=json.loads(calls[0]['function']['arguments'])
    validate_review(review,initial,source);validate_rulings(judge,[{'id':f'I{i:03}',**x} for i,x in enumerate(review['issues'],1)],source)
    run.mkdir();dump(run/'RECONCILIATION.json',{'parent':str(parent),'parent_state_preserved':read(parent/'STATE.json'),'known_receipts':known,'actual_prior_calls':3,'actual_prior_pending':None,'failure':'Windows os.replace STATE.tmp -> STATE.json PermissionError; model receipts known, no retransmission','remaining_calls':5,'adopted_initial_sha256':sha(initial),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=AppendSession(run);session.save();failure=None;outcome=None;reused=set()
    def call(name,prompt,payload,output):
        if name in ('REVIEW_0','JUDGE_0'):
            if name in reused:raise ValueError('repeated_cached_stage')
            reused.add(name);return review if name=='REVIEW_0' else judge
        if session.count>=5:raise ValueError('remaining_budget_exhausted')
        return session.call(name,prompt,payload,output)
    try:
        outcome=drive(source,call,lambda n,v:dump(run/(n+'.json'),v),initial);dump(run/'FINAL_MATERIAL.json',outcome['material'])
    except Exception as exc:failure=type(exc).__name__+':'+str(exc)[:600]
    session.save();dump(run/'RESULT.json',{'status':outcome['status'] if outcome else 'needs_attention','rounds':outcome['rounds'] if outcome else None,'calls':session.count,'tokens':session.tokens,'pending':session.pending,'error':failure,'acceptance':'pending_primary_review'})
    print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
