"""Source-bound case direction after a known complete required-field rejection."""
from pathlib import Path
import json
from scripts import run_trend_creative_text_trial_v1 as base
from scripts.run_trend_creative_direction_revision_v2 import RevisedTrial as PriorTrial
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_trend_bridge import validate_direction
from src.content_factory.creative_trend_stage_context_v2 import project_case_direction_wire

PROJECT = base.PROJECT
ROOT = PROJECT / 'data/production_revisions/legal_trend_text_trial_20261007/round_03'
VERSION = 'case_direction_stage_projection/v3'


class CaseTrial(base.Trial):
    def __init__(self):
        super().__init__(ROOT)

    def prepare(self, *unused):
        self.root.mkdir(parents=True, exist_ok=True)
        old = PriorTrial()
        rt = old.runtime()
        ledger = control.read(rt.ledger)
        rt.check(ledger)
        if not (self.root / 'ANCHOR.json').exists():
            r = rt.effective_receipt(ledger['calls'][-1])
            if (r['ordinal'] != 278 or r['status'] != 'contract_rejected'
                    or r['failure']['code'] != 'JSON_DOCUMENT_INNER_SCHEMA_REJECTED'
                    or r['validation_error']['detail']['path'] != 'creative_brief'
                    or 'audience' not in r['validation_error']['message']
                    or not r['response_metadata']['response_body_complete']
                    or type(r['response_metadata']['total_tokens']) is not int):
                raise ValueError('exact known complete audience-field rejection required')
            stats = old.summary()
            inherited = {'calls_started': stats['effective_calls_started'],
                'reported_tokens': stats['effective_reported_tokens'],
                'calls_with_known_usage': ledger['starting_spend']['calls_with_known_usage'] + len(ledger['calls']),
                'unknown_token_reservations': stats['unknown_token_reservations'],
                'pending_ordinals': [70,160], 'parent_ledger_sha256': control.sha_file(rt.ledger)}
            for name in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','CURRENT_TASK_AUTHORIZATION.json'):
                control.write(self.root / name, control.read(old.root / name), True)
            findings = {'source_ordinal': 278, 'source_receipt_sha256': control.sha_file(rt.root / ledger['calls'][-1]['receipt']),
                'required_field_missing': 'creative_brief.audience',
                'content_findings': ['运营口播配置覆盖了当前画面叙事目标，需要按阶段投影账号职责。',
                    '此前仍添加真人律师与未经核验的统一前置条件；新提案不继承这些条件。'],
                'scope': 'complete new case direction after explicit diagnosis; not automatic transport retry',
                'human_direction_approval': None}
            control.write(self.root / 'KNOWN_FINDINGS.json', findings, True)
            control.write(self.root / 'ANCHOR.json', {'schema':VERSION,'inherited':inherited,
                'models':ledger['model_configs'],'parent_ledger_sha256':control.sha_file(rt.ledger),
                'automatic_retry':False,'media_calls_authorized':False}, True)
        return self.runtime().prepare()

    def runtime(self):
        old = PriorTrial()
        a = control.read(self.root / 'ANCHOR.json')
        def guard():
            rt = old.runtime()
            rt.check(control.read(rt.ledger))
            if control.sha_file(rt.ledger) != a['parent_ledger_sha256']:
                raise ValueError('parent ledger changed')
        sources = [Path(__file__).resolve(), PROJECT / 'src/content_factory/creative_trend_stage_context_v2.py']
        sources += [self.root / n for n in ('ANCHOR.json','SOURCE_PACKET.json','LEGAL_CONTEXT.json',
                                          'CURRENT_TASK_AUTHORIZATION.json','KNOWN_FINDINGS.json')]
        sources += old.runtime().sources + [old.runtime().ledger]
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)

    def dispatch(self, stage, confirmation_path=None):
        if stage != 'direction':
            return super().dispatch(stage,confirmation_path)
        self.prepare()
        packet,facts,findings = [control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','KNOWN_FINDINGS.json')]
        wire = project_case_direction_wire(base.build_wire(packet,facts,'direction',now=control.now()),findings=findings)
        wire['operator_version'] = VERSION
        control.write(self.root / 'request_previews/direction.json',wire,True)
        def validate(value):
            validate_direction(value,packet)
            if value['account_fit']['proposed_format'] != '案例拆解' or len(value['characters']) != 2:
                raise ValueError('this narrative case requires two characters and case-analysis format')
            return {'complete_direction_valid':True,'human_confirmation_pending':True,'creative_quality_passed':False}
        r = self.runtime().dispatch('trend_direction_r1',wire,validate)
        if r['status'] == 'contract_valid':
            control.write(self.root/'DIRECTION.json',r['document_output'],True)
            write_new(self.root/'STORY_DIRECTION_FOR_REVIEW.md',base.render_direction(r['document_output'],packet))
        control.write(self.root/'STATUS.json',{'latest_stage':stage,'ordinal':r['ordinal'],'receipt_status':r['status'],
            'spend':self.summary(),'creative_quality_passed':False,'director_complete':False,
            'performance_complete':False,'media_calls':0})
        return r


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','direction','draft','review','status'])
    parser.add_argument('--confirmation',type=Path)
    args=parser.parse_args();t=CaseTrial()
    if args.stage=='prepare': result=t.prepare()
    elif args.stage=='status': result=t.summary()
    else:
        r=t.dispatch(args.stage,args.confirmation)
        result={'ordinal':r['ordinal'],'status':r['status'],'failure':r.get('failure'),'spend':t.summary()}
    print(json.dumps(result,ensure_ascii=False),flush=True)
