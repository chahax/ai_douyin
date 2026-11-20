"""Full repair of actual missing facts, then calibrated whole-text review."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v10 import ScriptTrial as PriorTrial
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS,render_script
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_confirmed_facts_v1 import build_wire
from src.content_factory.creative_complete_review_ids_v1 import expand
from src.content_factory.creative_confirmed_case_active_scope_v2 import active_context
from src.content_factory.creative_trend_bridge import validate_complete_story
from src.content_factory.creative_story_emotion import digest
VERSION='legal_confirmed_facts_complete_trial/v11'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_08'

class ScriptTrial(PriorTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        if not (self.root/'ANCHOR.json').exists():
            r=prior.accepted('legal_review_r5');d=prior.accepted('legal_draft_r5');r=dict(r);r['output']=control.read(prior.root/'REVIEW_r5.json')
            if r['ordinal']!=293 or not r['validation']['needs_revision']:raise ValueError('valid current full review findings required')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            effective=control.read(prior.root/'REVIEW_r5.json')
            for n,v in [('DRAFT_r5.json',d['output']),('REVIEW_r5.json',effective)]:control.write(self.root/n,v,True)
            s=d['output']
            findings={'source_script_sha256':digest(s),'source_ordinal':292,'source_review_ordinal':293,
                'source_review_sha256':digest(effective),'findings':[
                    '原稿把公司要求结束劳动关系改成调岗，未兑现已确认核心。',
                    '咖啡同时留在会议室和工位，未交代从桌到工位；仍新增未确认同事台词。',
                    '此前完整事件链和反复返修仍锚定失败场景，此次只用确认事实重写完整正文，不继承失败场景模板。'],
                'accepted_full_review_issue_ids':[i['id'] for i in effective['full_text_review']['issues']],
                'manual_content_patch':False,'complete_original_review_retained':True}
            control.write(self.root/'OPERATOR_FINDINGS.json',findings,True)
            stats=prior.summary();inherited={'calls_started':stats['effective_calls_started'],'reported_tokens':stats['effective_reported_tokens'],
                'calls_with_known_usage':ledger['starting_spend']['calls_with_known_usage']+len(ledger['calls']),
                'unknown_token_reservations':stats['unknown_token_reservations'],'pending_ordinals':[70,160],'parent_ledger_sha256':control.sha_file(rt.ledger)}
            control.write(self.root/'ANCHOR.json',{'schema':VERSION,'inherited':inherited,'models':ledger['model_configs'],
                'parent_ledger_sha256':control.sha_file(rt.ledger),'automatic_retry':False,'media_calls_authorized':False},True)
        return self.runtime().prepare()
    def runtime(self):
        prior=PriorTrial();a=control.read(self.root/'ANCHOR.json')
        def guard():
            rt=prior.runtime();rt.check(control.read(rt.ledger))
            if control.sha_file(rt.ledger)!=a['parent_ledger_sha256']:raise ValueError('parent ledger changed')
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_confirmed_facts_v1.py',self.root/'ANCHOR.json',self.root/'OPERATOR_FINDINGS.json']
        sources += [self.root/n for n in FIXED_INPUTS+('DRAFT_r5.json','REVIEW_r5.json')]
        sources += prior.runtime().sources+[prior.runtime().ledger,prior.root/'DRAFT_r5.json',prior.root/'REVIEW_r5.json']
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def wire(self,stage,*,script=None,revision=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,
            diagnosis=control.read(self.root/'OPERATOR_FINDINGS.json'))
    def dispatch(self,stage,revision_number=6):
        self.prepare();script=None;revision=None
        if stage=='draft':
            revision={'previous_complete_script':control.read(self.root/'DRAFT_r5.json'),'review':control.read(self.root/'REVIEW_r5.json'),
                'source_draft_ordinal':292,'source_review_ordinal':293,'requirement':'完整新稿，全文复审，原文保留不手改'}
        elif stage=='review':script=self.accepted('legal_draft_r6')['output']
        else:raise ValueError('draft or review required')
        w=self.wire(stage,script=script,revision=revision);control.write(self.root/f'request_previews/{stage}_r6.json',w,True)
        p,f,s,d=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','CONTENT_SCOPE.json','DIRECTION.json')]
        brief=active_context(p,f,s,d)['emotional_brief']
        def validate(v):return validate_complete_story(v,d) if stage=='draft' else expand(v,script,brief)[2]
        r=self.runtime().dispatch(f'legal_{stage}_r6',w,validate)
        if r['status']=='contract_valid':
            v=r['output']
            if stage=='review':v,receipt,_=expand(v,script,brief);control.write(self.root/'REVIEW_EVIDENCE_EXPANSION_r6.json',receipt,True)
            control.write(self.root/f'{stage.upper()}_r6.json',v,True)
            if stage=='draft':write_new(self.root/'FULL_SCRIPT_r6.md',render_script(v,'完整模型新稿；等待全文复审与用户内容确认。'))
        control.write(self.root/'STATUS.json',{'schema':VERSION,'latest_stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':self.summary(),'creative_quality_passed':False,'media_calls':0})
        return r

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','draft','review','status']);args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':v=t.prepare()
    elif args.stage=='status':v=t.summary()
    else:
        r=t.dispatch(args.stage);v={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(v,ensure_ascii=False),flush=True)
