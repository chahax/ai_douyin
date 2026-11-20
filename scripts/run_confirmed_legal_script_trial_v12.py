"""One complete verified-source revision and whole review; flat immutable parent guard."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v11 import ScriptTrial as PriorTrial
from scripts.run_confirmed_legal_script_trial_v4 import ScriptTrial as BaseTrial,FIXED_INPUTS,render_script
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_confirmed_revision_v2 import build_wire
from src.content_factory.creative_complete_review_ids_v1 import expand
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
from src.content_factory.creative_trend_bridge import validate_complete_story
VERSION='legal_complete_fact_revision_trial/v12'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_09'

def verify_files(files):
    for p,h in files.items():
        if control.sha_file(Path(p))!=h:raise ValueError('verified immutable parent changed: '+p)

class ScriptTrial(BaseTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        if not (self.root/'ANCHOR.json').exists():
            prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
            r=prior.accepted('legal_review_r6');d=prior.accepted('legal_draft_r6')
            if r['ordinal']!=295 or not r['validation']['needs_revision']:raise ValueError('valid current full review required')
            receipts=[rt.effective_receipt(c) for c in ledger['calls']]
            if any(type(c['response_metadata']['total_tokens']) is not int for c in receipts):raise ValueError('current parent usage unresolved')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            for n in ['DRAFT_r6.json','REVIEW_r6.json']:control.write(self.root/n,control.read(prior.root/n),True)
            files=list(dict.fromkeys(rt.sources+[rt.ledger,prior.root/'DRAFT_r6.json',prior.root/'REVIEW_r6.json',prior.root/'REVIEW_EVIDENCE_EXPANSION_r6.json']+
                [rt.root/c['receipt'] for c in ledger['calls']]))
            parent_files={str(p):control.sha_file(p) for p in files}
            inherited={'calls_started':ledger['starting_spend']['calls_started']+len(receipts),
                'reported_tokens':ledger['starting_spend']['reported_tokens']+sum(c['response_metadata']['total_tokens'] for c in receipts),
                'calls_with_known_usage':ledger['starting_spend']['calls_with_known_usage']+len(receipts),
                'unknown_token_reservations':ledger['starting_spend']['unknown_token_reservations'],'pending_ordinals':[70,160],
                'parent_ledger_sha256':control.sha_file(rt.ledger)}
            control.write(self.root/'ANCHOR.json',{'schema':VERSION,'inherited':inherited,'models':ledger['model_configs'],
                'parent_ledger_sha256':control.sha_file(rt.ledger),'parent_files':parent_files,
                'parent_guard':'all recursive original guards verified before snapshot; exact source/ledger/receipt hashes checked thereafter',
                'automatic_retry':False,'media_calls_authorized':False},True)
        return self.runtime().prepare()
    def runtime(self):
        a=control.read(self.root/'ANCHOR.json')
        def guard():verify_files(a['parent_files'])
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_confirmed_revision_v2.py',self.root/'ANCHOR.json']
        sources += [self.root/n for n in FIXED_INPUTS+('DRAFT_r6.json','REVIEW_r6.json')]
        sources += [Path(p) for p in a['parent_files']]
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def wire(self,stage,*,script=None,revision=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,revision=revision,
            diagnosis={'source_draft_ordinal':294,'source_review_ordinal':295,'required':'complete revision after valid full-source findings','manual_content_patch':False})
    def dispatch(self,stage):
        self.prepare();script=None;revision=None
        if stage=='draft':revision={'previous_complete_script':control.read(self.root/'DRAFT_r6.json'),'review':control.read(self.root/'REVIEW_r6.json'),
            'source_draft_ordinal':294,'source_review_ordinal':295}
        elif stage=='review':script=self.accepted('legal_draft_r7')['output']
        else:raise ValueError('draft or review required')
        w=self.wire(stage,script=script,revision=revision);control.write(self.root/f'request_previews/{stage}_r7.json',w,True)
        p,f,s,d=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','CONTENT_SCOPE.json','DIRECTION.json')];brief=active_context(p,f,s,d)['emotional_brief']
        def validate(v):return validate_complete_story(v,d) if stage=='draft' else expand(v,script,brief)[2]
        r=self.runtime().dispatch(f'legal_{stage}_r7',w,validate)
        if r['status']=='contract_valid':
            v=r['output']
            if stage=='review':v,receipt,_=expand(v,script,brief);control.write(self.root/'REVIEW_EVIDENCE_EXPANSION_r7.json',receipt,True)
            control.write(self.root/f'{stage.upper()}_r7.json',v,True)
            if stage=='draft':write_new(self.root/'FULL_SCRIPT_r7.md',render_script(v,'完整模型新稿；等待全文复审与用户内容确认。'))
        control.write(self.root/'STATUS.json',{'schema':VERSION,'latest_stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':self.summary(),'creative_quality_passed':False,'media_calls':0})
        return r

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','draft','review','status']);args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':v=t.prepare()
    elif args.stage=='status':v=t.summary()
    else:
        r=t.dispatch(args.stage);v={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(v,ensure_ascii=False),flush=True)
