"""Known tool-name rejection and rejected source-recommendation isolation."""
from pathlib import Path
import argparse,json,sys
PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v8 import ScriptTrial as PriorTrial
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS
from src.content_factory.creative_legal_causal_spine_v2 import build_wire

VERSION='legal_causal_active_sources_trial/v9'
ROOT=PROJECT/'data/production_revisions/legal_trend_text_trial_20261008/round_06'

class ScriptTrial(PriorTrial):
    def __init__(self):self.root=ROOT
    def prepare(self):
        prior=PriorTrial();rt=prior.runtime();ledger=control.read(rt.ledger);rt.check(ledger)
        if not (self.root/'ANCHOR.json').exists():
            r=rt.effective_receipt(ledger['calls'][-1])
            if r['ordinal']!=288 or r['status']!='interface_rejected' or r['failure']['code']!='UNEXPECTED_TOOL_CALL' or type(r['response_metadata']['total_tokens']) is not int:
                raise ValueError('known original unexpected tool and known usage required')
            self.root.mkdir(parents=True,exist_ok=True)
            for n in FIXED_INPUTS:control.write(self.root/n,control.read(prior.root/n),True)
            diagnosis=control.read(prior.root/'DIAGNOSIS.json')
            diagnosis.update(source_interface_ordinal=288,source_receipt_sha256=control.sha_file(rt.root/ledger['calls'][-1]['receipt']),
                verified_rejected_tool_name='tool-name-submit_creative_json',expected_tool_name='submit_creative_json',
                additional_input_cause='original tag_choices story_relevance still requires unadopted stamp-based turn, despite active main brief correction',
                additional_change='isolate original recommendation strings by source hashes; current selected labels remain factual topic provenance; exact tool name and first cause constrained',
                automatic_retry=False,old_response_modified=False)
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
        sources=[Path(__file__).resolve(),PROJECT/'src/content_factory/creative_legal_causal_spine_v2.py',
            self.root/'ANCHOR.json',self.root/'DIAGNOSIS.json']+[self.root/n for n in FIXED_INPUTS]
        sources+=prior.runtime().sources+[prior.runtime().ledger,prior.root/'call_288_legal_spine_r4.json']
        return control.ContinuationRuntime(PROJECT,self.root,list(dict.fromkeys(sources)),a['inherited'],a['models'],
            inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)
    def wire(self,stage,*,script=None,spine=None):
        p,f,g,s,d,c=[control.read(self.root/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json',
            'CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(p,f,g,s,stage,now=control.now(),direction=d,confirmation=c,script=script,spine=spine,
            diagnosis=control.read(self.root/'DIAGNOSIS.json'))

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
