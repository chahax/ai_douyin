"""Whole-source re-review of actual same draft; preserve original objections and ledger."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v13 import ScriptTrial as PriorTrial,verify_files
from scripts.run_confirmed_legal_script_trial_v4 import ScriptTrial as BaseTrial,FIXED_INPUTS
from src.content_factory.creative_legal_review_qualification_v1 import build_wire,validate
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
VERSION='legal_full_review_qualification_trial/v14'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_11'

class ScriptTrial(BaseTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        if not (self.root/'ANCHOR.json').exists():
            prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
            r=prior.accepted('legal_review_r8');d=prior.accepted('legal_draft_r8')
            if r['ordinal']!=299 or not r['validation']['needs_revision']:raise ValueError('actual original full review required')
            receipts=[rt.effective_receipt(c) for c in ledger['calls']]
            if any(type(r['response_metadata']['total_tokens']) is not int for r in receipts):raise ValueError('parent usage unresolved')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS+('DRAFT_r8.json','REVIEW_r8.json'):control.write(self.root/n,control.read(prior.root/n),True)
            files=list(dict.fromkeys(rt.sources+[rt.ledger,prior.root/'DRAFT_r8.json',prior.root/'REVIEW_r8.json',prior.root/'REVIEW_EVIDENCE_EXPANSION_r8.json']+[rt.root/c['receipt'] for c in ledger['calls']]))
            inherited={'calls_started':ledger['starting_spend']['calls_started']+len(receipts),'reported_tokens':ledger['starting_spend']['reported_tokens']+sum(r['response_metadata']['total_tokens'] for r in receipts),
                'calls_with_known_usage':ledger['starting_spend']['calls_with_known_usage']+len(receipts),'unknown_token_reservations':ledger['starting_spend']['unknown_token_reservations'],
                'pending_ordinals':[70,160],'parent_ledger_sha256':control.sha_file(rt.ledger)}
            control.write(self.root/'ANCHOR.json',{'schema':VERSION,'inherited':inherited,'models':ledger['model_configs'],
                'parent_files':{str(p):control.sha_file(p) for p in files},'automatic_retry':False,'media_calls_authorized':False},True)
        return self.runtime().prepare()
    def runtime(self):
        a=control.read(self.root/'ANCHOR.json')
        def guard():verify_files(a['parent_files'])
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_review_qualification_v1.py',self.root/'ANCHOR.json']+[self.root/n for n in FIXED_INPUTS+('DRAFT_r8.json','REVIEW_r8.json')]+[Path(p) for p in a['parent_files']]
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def dispatch(self):
        self.prepare();script=control.read(self.root/'DRAFT_r8.json');prior=control.read(self.root/'REVIEW_r8.json')
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        brief=active_context(p,f,s,d)['emotional_brief'];wire=build_wire(p,f,g,s,'review',now=control.now(),direction=d,confirmation=c,script=script,prior_review=prior)
        control.write(self.root/'request_previews/review_qualification_r8.json',wire,True)
        r=self.runtime().dispatch('legal_review_qualification_r8',wire,lambda v:validate(v,script,brief,prior)[2])
        if r['status']=='contract_valid':
            effective,receipt,result=validate(r['output'],script,brief,prior)
            control.write(self.root/'REVIEW_QUALIFIED_r8.json',effective,True);control.write(self.root/'REVIEW_QUALIFICATION_EXPANSION_r8.json',receipt,True)
        control.write(self.root/'STATUS.json',{'schema':VERSION,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':self.summary(),'creative_quality_passed':False,'media_calls':0})
        return r
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','review','status']);args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':v=t.prepare()
    elif args.stage=='status':v=t.summary()
    else:
        r=t.dispatch();v={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(v,ensure_ascii=False),flush=True)
