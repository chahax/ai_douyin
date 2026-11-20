"""Plan causality, expand complete script, full review; no media or auto retry."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v7 import ScriptTrial as PriorTrial
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_causal_spine_v1 import build_wire,validate_spine
from src.content_factory.creative_complete_review_ids_v1 import expand
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
from src.content_factory.creative_trend_bridge import validate_complete_story

VERSION='legal_complete_causal_spine_trial/v8'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_05'

class ScriptTrial(PriorTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        if not (self.root/'ANCHOR.json').exists():
            r=prior.accepted('legal_review_r3')
            if r['ordinal']!=287 or not r['validation']['needs_revision']:raise ValueError('current valid full review required')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            diagnosis={'source_draft_ordinal':286,'source_review_ordinal':287,
                'issues':[{k:i[k] for k in ('id','rule','impact')} for i in r['output']['full_text_review']['issues']],
                'verified_input_size':{'full_graph_context_characters':16865,'complete_revision_context_characters':12483},
                'change':'separate short model-authored causal spine from complete new script; compact selected graph metadata for writer, retain frozen full source; no failed-dialogue template in new expansion',
                'original_full_review_retained':True,'model_switch':False,'automatic_retry':False,'manual_content_patch':False}
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
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_causal_spine_v1.py',
            self.root/'ANCHOR.json',self.root/'DIAGNOSIS.json']+[self.root/n for n in FIXED_INPUTS]
        sources+=prior.runtime().sources+[prior.runtime().ledger,prior.root/'DRAFT_r3.json',prior.root/'REVIEW_r3.json']
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def accepted(self,label):
        rt=self.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        rows=[c for c in ledger['calls'] if c['label']==label]
        if len(rows)!=1:raise ValueError('exact current source call required')
        r=rt.effective_receipt(rows[0])
        if r['status']!='contract_valid':raise ValueError('rejected or unknown current source')
        return r
    def wire(self,stage,*,script=None,spine=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json',
            'CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,spine=spine,
            diagnosis=control.read(self.root/'DIAGNOSIS.json'))
    def dispatch(self,stage,revision_number=4):
        self.prepare();script=None;spine=None
        if stage=='draft':spine=self.accepted('legal_spine_r4')['output']
        elif stage=='review':script=self.accepted('legal_draft_r4')['output']
        elif stage!='spine':raise ValueError('unknown stage')
        w=self.wire(stage,script=script,spine=spine)
        control.write(self.root/f'request_previews/{stage}_r4.json',w,True)
        p,f,s,d=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','CONTENT_SCOPE.json','DIRECTION.json')]
        brief=active_context(p,f,s,d)['emotional_brief']
        def validate(v):
            if stage=='spine':return validate_spine(v,d)
            return validate_complete_story(v,d) if stage=='draft' else expand(v,script,brief)[2]
        r=self.runtime().dispatch(f'legal_{stage}_r4',w,validate)
        if r['status']=='contract_valid':
            value=r['output']
            if stage=='review':
                value,receipt,_=expand(value,script,brief);control.write(self.root/'REVIEW_EVIDENCE_EXPANSION_r4.json',receipt,True)
            control.write(self.root/f'{stage.upper()}_r4.json',value,True)
            if stage=='draft':write_new(self.root/'FULL_SCRIPT_r4.md',render_script(value,'完整模型新稿；等待全文复审与用户内容确认。'))
        control.write(self.root/'STATUS.json',{'schema':VERSION,'latest_stage':stage,'ordinal':r['ordinal'],
            'receipt_status':r['status'],'spend':self.summary(),'creative_quality_passed':False,'media_calls':0})
        return r

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','spine','draft','review','status'])
    args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':v=t.prepare()
    elif args.stage=='status':v=t.summary()
    else:
        r=t.dispatch(args.stage);v={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),
            'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(v,ensure_ascii=False),flush=True)
