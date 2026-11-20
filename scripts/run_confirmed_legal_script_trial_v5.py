"""Diagnosed complete-script repair; new source binding, same models, no HTTP retries."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v4 import ScriptTrial as PriorTrial,FIXED_INPUTS,render_script
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_confirmed_case_active_scope_v2 import build_wire,active_context
from src.content_factory.creative_trend_bridge import validate_complete_story
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2

VERSION='legal_complete_script_diagnosed_repair/v5'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_02'


class ScriptTrial(PriorTrial):
    def __init__(self):super().__init__(ROOT)
    def prepare(self):
        prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        if not (self.root/'ANCHOR.json').exists():
            last=rt.effective_receipt(ledger['calls'][-1])
            if (last['ordinal']!=280 or last['status']!='interface_rejected' or
                last['failure']['code']!='JSON_DOCUMENT_INNER_INVALID_JSON' or
                not last['response_metadata']['response_body_complete'] or type(last['response_metadata']['total_tokens']) is not int):
                raise ValueError('known complete original JSON rejection and usage required')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            diagnosis={'source_ordinal':280,'source_receipt_sha256':control.sha_file(rt.root/ledger['calls'][-1]['receipt']),
                'service_result_known':True,'http_status':200,'finish_reason':'tool_calls',
                'response_body_complete':True,'interface_cause':'inner payload_json contains an extra closing brace at character738',
                'content_cause':'unadopted stamp-based turn remained in active brief; prior output copied it instead of applying supplemental findings',
                'change':'project current accepted scope into active brief; keep original direction on disk; use native typed tool JSON without nested payload_json string',
                'model_switch':False,'automatic_retry':False,'old_document_patched':False}
            control.write(self.root/'DIAGNOSIS.json',diagnosis,True)
            self.wire('draft')
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
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_confirmed_case_active_scope_v2.py',
            self.root/'ANCHOR.json',self.root/'DIAGNOSIS.json']+[self.root/n for n in FIXED_INPUTS]
        sources += prior.runtime().sources+[prior.runtime().ledger]
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def wire(self,stage,*,script=None,revision=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json',
            'CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,revision=revision,
                          diagnosis=control.read(self.root/'DIAGNOSIS.json'))
    def dispatch(self,stage,revision_number=1):
        self.prepare();script=None;revision=None
        if stage=='review':script=self.accepted(f'legal_draft_r{revision_number}')['output']
        elif stage=='draft' and revision_number>1:
            prior_draft=self.accepted(f'legal_draft_r{revision_number-1}')
            prior_review=self.accepted(f'legal_review_r{revision_number-1}')
            if not prior_review['validation']['needs_revision']:raise ValueError('current real review findings required')
            revision={'previous_complete_script':prior_draft['output'],'review':prior_review['output'],
                'source_draft_ordinal':prior_draft['ordinal'],'source_review_ordinal':prior_review['ordinal'],
                'requirement':'依据完整正文和真实必修问题提交完整新稿，再全文复审；不返回补丁、不拼接。'}
        elif stage!='draft':raise ValueError('unknown stage')
        wire=self.wire(stage,script=script,revision=revision)
        control.write(self.root/f'request_previews/{stage}_r{revision_number}.json',wire,True)
        p,f,s,d=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','CONTENT_SCOPE.json','DIRECTION.json')]
        brief=active_context(p,f,s,d)['emotional_brief']
        def validate(v):return validate_complete_story(v,d) if stage=='draft' else validate_complete_review_v2(v,script,brief)
        r=self.runtime().dispatch(f'legal_{stage}_r{revision_number}',wire,validate)
        if r['status']=='contract_valid':
            control.write(self.root/f'{stage.upper()}_r{revision_number}.json',r['output'],True)
            if stage=='draft':write_new(self.root/f'FULL_SCRIPT_r{revision_number}.md',render_script(r['output'],'完整模型正文；等待全文复审及用户内容确认。'))
        control.write(self.root/'STATUS.json',{'schema':VERSION,'latest_stage':stage,'revision':revision_number,
            'ordinal':r['ordinal'],'receipt_status':r['status'],'spend':self.summary(),'creative_quality_passed':False,
            'full_text_review_required':stage=='draft','media_calls':0})
        return r


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','draft','review','status']);a.add_argument('--revision',type=int,default=1)
    args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':result=t.prepare()
    elif args.stage=='status':result=t.summary()
    else:
        r=t.dispatch(args.stage,args.revision);result={'ordinal':r['ordinal'],'status':r['status'],
            'failure':r.get('failure'),'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(result,ensure_ascii=False),flush=True)
