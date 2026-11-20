"""Diagnosed exact-citation transport continuation; full model revisions only."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v5 import ScriptTrial as PriorTrial
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_complete_review_ids_v1 import build_wire,expand
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
from src.content_factory.creative_trend_bridge import validate_complete_story

VERSION='legal_complete_script_source_review/v6'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_03'

class ScriptTrial(PriorTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        if not (self.root/'ANCHOR.json').exists():
            last=rt.effective_receipt(ledger['calls'][-1])
            if (last['ordinal']!=282 or last['status']!='contract_rejected' or last['failure']['code']!='review quote differs from the actual source'
                or not last['response_metadata']['response_body_complete'] or type(last['response_metadata']['total_tokens']) is not int):
                raise ValueError('known complete citation failure and usage required')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            control.write(self.root/'DRAFT_r1.json',prior.accepted('legal_draft_r1')['output'],True)
            diagnosis={'source_ordinal':282,'source_receipt_sha256':control.sha_file(rt.root/ledger['calls'][-1]['receipt']),
                'service_result_known':True,'http_status':200,'response_body_complete':True,
                'interface_cause':'one exact source quote omitted opening sentence in script.beats.0.steps.0.text',
                'change':'reuse context-bound source IDs, deterministic exact-leaf expansion; original review and conclusions preserved',
                'model_switch':False,'automatic_retry':False,'manual_content_patch':False}
            control.write(self.root/'DIAGNOSIS.json',diagnosis,True)
            stats=prior.summary()
            inherited={'calls_started':stats['effective_calls_started'],'reported_tokens':stats['effective_reported_tokens'],
                'calls_with_known_usage':ledger['starting_spend']['calls_with_known_usage']+len(ledger['calls']),
                'unknown_token_reservations':stats['unknown_token_reservations'],'pending_ordinals':[70,160],
                'parent_ledger_sha256':control.sha_file(rt.ledger)}
            control.write(self.root/'ANCHOR.json',{'schema':VERSION,'inherited':inherited,'models':ledger['model_configs'],
                'parent_ledger_sha256':control.sha_file(rt.ledger),'automatic_retry':False,'media_calls_authorized':False},True)
        return self.runtime().prepare()
    def runtime(self):
        prior=PriorTrial();a=control.read(self.root/'ANCHOR.json')
        def guard():
            rt=prior.runtime();rt.check(control.read(rt.ledger))
            if control.sha_file(rt.ledger)!=a['parent_ledger_sha256']:raise ValueError('parent ledger changed')
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_complete_review_ids_v1.py',
            PROJECT/'src/content_factory/creative_review_evidence_ids.py',PROJECT/'src/content_factory/creative_emotion_review_v2.py',
            self.root/'ANCHOR.json',self.root/'DIAGNOSIS.json',self.root/'DRAFT_r1.json']+[self.root/n for n in FIXED_INPUTS]
        sources+=prior.runtime().sources+[prior.runtime().ledger,prior.root/'DRAFT_r1.json',prior.root/'call_282_legal_review_r1.json']
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def accepted(self,label):
        if label=='legal_draft_r1':return PriorTrial().accepted(label)
        r=super().accepted(label)
        if label.startswith('legal_review_'):
            r=dict(r);r['output']=control.read(self.root/(label.replace('legal_review_','REVIEW_')+'.json'))
        return r
    def wire(self,stage,*,script=None,revision=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json',
            'CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,revision=revision,
            diagnosis=control.read(self.root/'DIAGNOSIS.json'))
    def dispatch(self,stage,revision_number=1):
        self.prepare();script=None;revision=None
        if stage=='review':script=self.accepted(f'legal_draft_r{revision_number}')['output']
        elif stage=='draft' and revision_number>1:
            d=self.accepted(f'legal_draft_r{revision_number-1}');r=self.accepted(f'legal_review_r{revision_number-1}')
            if not r['validation']['needs_revision']:raise ValueError('actual accepted full review findings required')
            revision={'previous_complete_script':d['output'],'review':r['output'],
                'source_draft_ordinal':d['ordinal'],'source_review_ordinal':r['ordinal'],
                'requirement':'依完整正文与真实审查问题提交完整新稿，再全文复审，不返回补丁，不拼接。'}
        else:raise ValueError('review existing full draft first')
        w=self.wire(stage,script=script,revision=revision)
        control.write(self.root/f'request_previews/{stage}_r{revision_number}.json',w,True)
        p,f,s,d=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','CONTENT_SCOPE.json','DIRECTION.json')]
        brief=active_context(p,f,s,d)['emotional_brief']
        def validate(v):return validate_complete_story(v,d) if stage=='draft' else expand(v,script,brief)[2]
        r=self.runtime().dispatch(f'legal_{stage}_r{revision_number}',w,validate)
        if r['status']=='contract_valid':
            value=r['output']
            if stage=='review':
                value,receipt,_=expand(value,script,brief)
                control.write(self.root/f'REVIEW_EVIDENCE_EXPANSION_r{revision_number}.json',receipt,True)
            control.write(self.root/f'{stage.upper()}_r{revision_number}.json',value,True)
            if stage=='draft':write_new(self.root/f'FULL_SCRIPT_r{revision_number}.md',render_script(value,'完整模型新稿；等待全文复审与用户内容确认。'))
        control.write(self.root/'STATUS.json',{'schema':VERSION,'latest_stage':stage,'revision':revision_number,
            'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':self.summary(),'creative_quality_passed':False,
            'full_text_review_required':stage=='draft','media_calls':0})
        return r

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','draft','review','status']);a.add_argument('--revision',type=int,default=1)
    args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':v=t.prepare()
    elif args.stage=='status':v=t.summary()
    else:
        r=t.dispatch(args.stage,args.revision);v={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),
            'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(v,ensure_ascii=False),flush=True)
