"""Full causal rewrite after verified inconsistent alternative accumulation."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v6 import ScriptTrial as PriorTrial
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS
from src.content_factory.creative_complete_revision_roles_v1 import build_wire
from src.content_factory.creative_story_emotion import digest

VERSION='legal_complete_causal_revision/v7'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_04'

class ScriptTrial(PriorTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        if not (self.root/'ANCHOR.json').exists():
            r=prior.accepted('legal_review_r2');d=prior.accepted('legal_draft_r2')
            if r['ordinal']!=285 or not r['validation']['needs_revision'] or type(r['response_metadata']['total_tokens']) is not int:
                raise ValueError('known full review findings required')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            control.write(self.root/'DRAFT_r2.json',d['output'],True)
            control.write(self.root/'REVIEW_r2.json',r['output'],True)
            s=d['output'];paths=['script.beats.5.steps.0.text','script.beats.6.steps.0.text','script.beats.7.steps.0.text','script.beats.2.steps.0.text']
            refs=[]
            for path in paths:
                x=path.split('.');refs.append({'path':path,'quote':s['beats'][int(x[2])]['steps'][int(x[4])]['text']})
            findings={'schema':'source_bound_operator_findings/v1','source_script_sha256':digest(s),'source_ordinal':284,
                'evidence_refs':refs,'findings':[
                    '不带走与装包带走互斥，返修需选择一种处置并贯穿正文，不同时实现两种建议。',
                    '桌上美式后来被持有，正文未写拿取；同事与另一罐咖啡仍超出双人关系并未兑现触发。可删除无叙事作用的分支，不必靠补微操作保留它们。',
                    '工位与延后结算是审查的备选加压，不是用户必选情节；新稿应自行选择与核对真实原因直接有关的阻力及后果，不逐项升级后再逐项撤回。',
                    '核对公司是否要求自己离开是主线，调岗/章/工资条并非逐项必修道具。事件描述与实际steps必须是同一件事。'],
                'new_plot_or_dialogue_written_by_operator':False,'raw_review_modified':False}
            control.write(self.root/'REVISION_OBLIGATIONS.json',findings,True)
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
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_complete_revision_roles_v1.py',
            self.root/'ANCHOR.json',self.root/'REVISION_OBLIGATIONS.json',self.root/'DRAFT_r2.json',self.root/'REVIEW_r2.json']+[self.root/n for n in FIXED_INPUTS]
        sources+=prior.runtime().sources+[prior.runtime().ledger,prior.root/'DRAFT_r2.json',prior.root/'REVIEW_r2.json']
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def accepted(self,label):
        if label in ('legal_draft_r2','legal_review_r2'):return PriorTrial().accepted(label)
        return super().accepted(label)
    def wire(self,stage,*,script=None,revision=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json',
            'CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,revision=revision,
            revision_obligations=control.read(self.root/'REVISION_OBLIGATIONS.json'))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('stage',choices=['prepare','draft','review','status']);a.add_argument('--revision',type=int,default=3)
    args=a.parse_args();t=ScriptTrial()
    if args.stage=='prepare':v=t.prepare()
    elif args.stage=='status':v=t.summary()
    else:
        r=t.dispatch(args.stage,args.revision);v={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),
            'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(v,ensure_ascii=False),flush=True)
