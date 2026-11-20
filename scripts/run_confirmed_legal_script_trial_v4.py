"""Explicit confirmed legal-script production on the inherited immutable text ledger."""
from pathlib import Path
import argparse,json,sys
ROOT_PROJECT=Path(__file__).resolve().parents[1]
if str(ROOT_PROJECT) not in sys.path:sys.path.insert(0,str(ROOT_PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts.run_trend_creative_case_trial_v3 import CaseTrial
from scripts import run_creative_resume_v10 as identity
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_confirmed_case_graph_context_v1 import build_wire
from src.content_factory.creative_trend_bridge import validate_complete_story
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2

VERSION='confirmed_legal_script_trial/v4'
DEFAULT_ROOT=ROOT_PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_01'
FIXED_INPUTS=('SOURCE_PACKET.json','DIRECTION.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json',
 'CONTENT_SCOPE.json','HUMAN_DIRECTION_CONFIRMATION.json','CURRENT_TASK_AUTHORIZATION.json')


def render_script(value, status):
    lines=['# '+value['title'],'',status,'',value['premise'],'']
    for b in value['beats']:
        lines += ['## '+b['id']+' '+b['event'],'','触发：'+b['trigger'],'']
        for s in b['steps']:lines += [('**'+s['speaker']+'**：' if s['kind']=='dialogue' else '')+s['text'],'']
    return '\n'.join(lines)


class ScriptTrial:
    def __init__(self,root=DEFAULT_ROOT):
        self.root=Path(root).resolve();self.root.relative_to(ROOT_PROJECT)
    def prepare(self):
        # Inputs are captured from the actual current user instruction before invoking this operator.
        prior=CaseTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        for n in FIXED_INPUTS:
            if not (self.root/n).is_file():raise ValueError('required immutable actual input missing: '+n)
        if not (self.root/'ANCHOR.json').exists():
            stats=prior.summary()
            if stats['new_unknown_token_reservations']:raise ValueError('latest parent usage unresolved')
            if prior.accepted('direction')!=control.read(self.root/'DIRECTION.json'):raise ValueError('original direction changed')
            if control.read(prior.root/'SOURCE_PACKET.json')!=control.read(self.root/'SOURCE_PACKET.json'):raise ValueError('original source packet changed')
            authority=control.read(self.root/'CURRENT_TASK_AUTHORIZATION.json')
            if (authority.get('source')!='current_conversation_user_request' or not authority.get('user_statement')
                or authority.get('automatic_model_retry') is not False or authority.get('media_generation') is not False
                or authority.get('publishing') is not False):raise ValueError('actual text-only continuation authorization required')
            self.wire('draft')
            inherited={'calls_started':stats['effective_calls_started'],'reported_tokens':stats['effective_reported_tokens'],
                'calls_with_known_usage':ledger['starting_spend']['calls_with_known_usage']+len(ledger['calls']),
                'unknown_token_reservations':stats['unknown_token_reservations'],'pending_ordinals':[70,160],
                'parent_ledger_sha256':control.sha_file(rt.ledger)}
            control.write(self.root/'ANCHOR.json',{'schema':VERSION,'inherited':inherited,
                'models':ledger['model_configs'],'parent_ledger_sha256':control.sha_file(rt.ledger),
                'automatic_retry':False,'media_calls_authorized':False},True)
        return self.runtime().prepare()
    def runtime(self):
        prior=CaseTrial();anchor=control.read(self.root/'ANCHOR.json')
        def guard():
            rt=prior.runtime();rt.check(control.read(rt.ledger))
            if control.sha_file(rt.ledger)!=anchor['parent_ledger_sha256']:raise ValueError('parent ledger changed')
        own=[Path(__file__).resolve(),self.root/'ANCHOR.json']+[self.root/n for n in FIXED_INPUTS]
        own += [ROOT_PROJECT/p for p in ('src/content_factory/creative_confirmed_case_graph_context_v1.py',
            'src/content_factory/creative_trend_writer_context_v3.py','src/content_factory/creative_legal_tag_graph_bridge_v1.py',
            'src/trend_intelligence/legal_tag_graph_v1.py')]
        sources=list(dict.fromkeys(own+prior.runtime().sources+[prior.runtime().ledger,prior.root/'DIRECTION.json']))
        return control.ContinuationRuntime(ROOT_PROJECT,self.root,sources,anchor['inherited'],anchor['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def summary(self):
        x=self.runtime().summary();x['unknown_token_reservations']+=control.read(self.root/'ANCHOR.json')['inherited']['unknown_token_reservations']
        x.update(unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160],creative_quality_passed=False)
        return x
    def accepted(self,label):
        rt=self.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        rows=[c for c in ledger['calls'] if c['label']==label]
        if len(rows)!=1:raise ValueError('exact source call required: '+label)
        r=rt.effective_receipt(rows[0])
        if r['status']!='contract_valid':raise ValueError('source outcome rejected or unknown')
        return r
    def wire(self,stage,*,script=None,revision=None):
        packet,facts,graph,scope,direction,confirmation=[control.read(self.root/n) for n in (
            'SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(packet,facts,graph,scope,stage,now=control.now(),direction=direction,
                          confirmation=confirmation,script=script,revision=revision)
    def dispatch(self,stage,revision_number=1):
        self.prepare()
        if revision_number<1:raise ValueError('positive revision number required')
        revision=None;script=None
        if stage=='review':script=self.accepted(f'legal_draft_r{revision_number}')['document_output']
        elif stage=='draft' and revision_number>1:
            olddraft=self.accepted(f'legal_draft_r{revision_number-1}')
            oldreview=self.accepted(f'legal_review_r{revision_number-1}')
            if not oldreview['validation']['needs_revision']:raise ValueError('intentional revision requires genuine current review findings')
            revision={'previous_complete_script':olddraft['document_output'],'review':oldreview['output'],
                'source_draft_ordinal':olddraft['ordinal'],'source_review_ordinal':oldreview['ordinal'],
                'requirement':'按完整正文与已核实复审问题提交完整新稿，再全文复审；不是接口重试、不拼接新旧正文。'}
        elif stage!='draft':raise ValueError('unknown stage')
        wire=self.wire(stage,script=script,revision=revision)
        control.write(self.root/f'request_previews/{stage}_r{revision_number}.json',wire,True)
        direction=control.read(self.root/'DIRECTION.json')
        def validate(v):
            return validate_complete_story(v,direction) if stage=='draft' else validate_complete_review_v2(v,script,direction['emotional_brief'])
        receipt=self.runtime().dispatch(f'legal_{stage}_r{revision_number}',wire,validate)
        if receipt['status']=='contract_valid':
            v=receipt.get('document_output',receipt.get('output'))
            control.write(self.root/f'{stage.upper()}_r{revision_number}.json',v,True)
            if stage=='draft':write_new(self.root/f'FULL_SCRIPT_r{revision_number}.md',render_script(v,'完整模型正文；等待全文复审与用户内容确认。'))
        control.write(self.root/'STATUS.json',{'schema':VERSION,'latest_stage':stage,'revision':revision_number,
            'ordinal':receipt['ordinal'],'receipt_status':receipt['status'],'spend':self.summary(),
            'full_text_review_required':stage=='draft','creative_quality_passed':False,'media_calls':0})
        return receipt


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['prepare','draft','review','status']);ap.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    ap.add_argument('--revision',type=int,default=1);a=ap.parse_args();t=ScriptTrial(a.root)
    if a.stage=='prepare':out=t.prepare()
    elif a.stage=='status':out=t.summary()
    else:
        r=t.dispatch(a.stage,a.revision);out={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'validation':r.get('validation'),'spend':t.summary()}
    print(json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
