"""Independent resumable text stages from a reviewed source/identity/design context.

This opt-in entry does not migrate production defaults. Source-card and design
approval remain upstream gates; final semantic acceptance is a downstream gate.
"""
import argparse,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import stage_session

STAGES=[
 {'name':'author','success_states':['candidate_awaiting_semantic_and_continuity_review'],'artifacts':['CANDIDATE.json','SOURCE.json','PLAN.json']},
 {'name':'presence','success_states':['projection_replayed_awaiting_semantic_coverage_review'],'artifacts':['CANDIDATE.json','PROGRAM_BOUND_PROJECTION.json','PRESENCE_REPLAY.json','SOURCE.json','PLAN.json']},
 {'name':'props','success_states':['combined_replay_awaiting_semantic_review'],'artifacts':['CANDIDATE.json','PRESENCE.json','PROP_PLAN.json','PROP_PROJECTION.json','COMBINED_REPLAY.json','SOURCE.json','PLAN.json']},
 {'name':'review','success_states':['review_awaiting_primary_assessment'],'artifacts':['FINAL_RENDERED_REVIEW_ENVELOPE_DECODED.json','REVIEW_INPUT.json','SOURCE.json','PLAN.json']},
]


def prepare(root,prior,context,design,additional_calls,context_acceptance,author_seed=None):
    if additional_calls<0:raise ValueError('negative_engineering_extension')
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json')
    packet=read(context/'PACKET.json');episode=read(design/'EPISODE.json')
    acceptance=context_acceptance if isinstance(context_acceptance,dict) else read(context_acceptance)
    required={'source':digest(source),'packet':digest(packet),'design':digest(episode['design'])}
    if (acceptance.get('status')!='text_review_accepted' or acceptance.get('semantic_acceptance') is not True
            or any(acceptance.get('artifact_hashes',{}).get(k)!=v for k,v in required.items())):
        raise ValueError('upstream_context_acceptance_missing_or_stale')
    if packet['source_sha256']!=digest(source) or packet.get('semantic_status')!='selected_dependencies_reviewed':
        raise ValueError('source_packet_not_reviewed')
    if not set(episode['design']['target_chapters'])<={c['index'] for c in source['chapters']}:
        raise ValueError('design_chapters_outside_source')
    ceiling=max(plan['max_calls'],state['calls_started']+additional_calls)
    inputs={'source':source,'packet':packet,'episode':episode,
            'context_acceptance':acceptance,'seed_plan':{**plan,'max_calls':ceiling},'seed_state':state,
            'prior':str(prior.resolve()),'prior_state_sha256':digest(state),
            'old_ceiling':plan['max_calls'],'new_ceiling':ceiling,'net_extension':ceiling-plan['max_calls']}
    if author_seed is not None:inputs['adopted_author']=author_seed
    files=[ROOT/'scripts'/f for f in ('run_novel_text_session.py','revise_narrative_adaptation.py',
        'project_narrative_presence.py','project_narrative_props.py','review_rendered_adaptation.py')]
    files+=list((ROOT/'src/content_factory/novel_adaptation').glob('*.py'))
    inputs['implementation']={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    stages=[{**s,'inputs_sha256':digest(inputs)} for s in STAGES]
    if author_seed is not None:
        stages[0]={**stages[0],'success_states':['repaired_candidate_awaiting_independent_review']}
    stage_session.prepare(root,stages,state,ceiling)
    freeze(root/'INPUTS.json',inputs)
    for sub in ('seed','context','design'):(root/sub).mkdir()
    freeze(root/'seed'/'STATE.json',state);freeze(root/'seed'/'SOURCE.json',source)
    freeze(root/'seed'/'PLAN.json',{**plan,'max_calls':ceiling})
    freeze(root/'context'/'PACKET.json',packet);freeze(root/'design'/'EPISODE.json',episode)
    return stage_session.inspect(root)


def prepare_repaired(root,previous,repair,ledger):
    """New session, known repaired author only; preserves the ended session."""
    previous=Path(previous);repair=Path(repair);ledger=Path(ledger)
    prior_state=stage_session.inspect(previous)
    if prior_state.get('status')!='needs_attention' or prior_state.get('failed_stage')!=0:
        raise ValueError('previous_session_not_known_author_failure')
    state=read(repair/'STATE.json');latest=read(ledger/'STATE.json')
    if latest.get('pending') is not None or latest.get('status') in ('outcome_unknown','running','prepared'):
        raise ValueError('latest_ledger_unsettled')
    if state!=latest:raise ValueError('repair_not_latest_ledger')
    if state.get('pending') is not None or state.get('status')!='repaired_candidate_awaiting_independent_review':
        raise ValueError('repair_not_ready')
    if state['calls_started']<prior_state['calls_started'] or state['reported_tokens']<prior_state['reported_tokens']:
        raise ValueError('repair_accounting_regressed')
    inputs=read(previous/'INPUTS.json');old_plan=read(previous/'SESSION.json')
    if any(s['inputs_sha256']!=digest(inputs) for s in old_plan['stages']):raise ValueError('previous_session_inputs_changed')
    source=read(repair/'SOURCE.json')
    if source!=inputs['source']:raise ValueError('repair_source_changed')
    candidate=read(repair/'CANDIDATE.json')
    from src.content_factory.novel_adaptation.narrative_revision import validate
    validate(candidate,source,inputs['packet'],inputs['episode']['design'],240)
    adoption={'candidate':candidate,'source':source,'state':state,'plan':read(repair/'PLAN.json'),
              'repair_directory':str(repair.resolve()),'previous_session':str(previous.resolve()),
              'previous_state_sha256':digest(prior_state),'previous_inputs_sha256':digest(inputs),
              'semantic_acceptance':False}
    return prepare(root,repair,previous/'context',previous/'design',0,inputs['context_acceptance'],adoption)


def step(root):
    inputs=read(root/'INPUTS.json');plan=read(root/'SESSION.json')
    if any(s['inputs_sha256']!=digest(inputs) for s in plan['stages']):raise ValueError('session_inputs_changed')
    for rel,sha in inputs['implementation'].items():
        if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=sha:raise ValueError('session_implementation_changed')
    # Verify frozen source inputs used by subprocess adapters, not just INPUTS.
    for path,value in [('seed/SOURCE.json',inputs['source']),('seed/PLAN.json',inputs['seed_plan']),
                       ('seed/STATE.json',inputs['seed_state']),('context/PACKET.json',inputs['packet']),('design/EPISODE.json',inputs['episode'])]:
        if read(root/path)!=value:raise ValueError('frozen_context_changed')
    def execute(folder,state,session_plan):
        index=state['pending_stage'];name=STAGES[index]['name']
        if name=='author' and 'adopted_author' in inputs:
            adopted=inputs['adopted_author'];folder.mkdir(exist_ok=False)
            for filename,key in [('CANDIDATE.json','candidate'),('SOURCE.json','source'),('PLAN.json','plan'),('STATE.json','state')]:
                freeze(folder/filename,adopted[key])
            freeze(folder/'ADOPTION.json',{k:v for k,v in adopted.items() if k not in ('candidate','source','state','plan')})
            return
        prior=root/'seed' if index==0 else root/state['completed'][-1]['directory']
        args=['--prior',str(prior),'--run',str(folder)]
        if name=='author':
            script='revise_narrative_adaptation.py';args+=['--candidate',str(root/'design'),'--context',str(root/'context'),'--additional-calls','0']
        elif name=='presence':
            script='project_narrative_presence.py';args+=['--context',str(root/'context'),'--design',str(root/'design'),'--program-bind']
        elif name=='props':script='project_narrative_props.py'
        else:
            script='review_rendered_adaptation.py';args+=['--candidate',str(prior),'--narrative','--estimate-timing',
                '--target-chapters',*[str(n) for n in inputs['episode']['design']['target_chapters']]]
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/script),*args],cwd=ROOT,
            capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        freeze(root/f'{index:02}_{name}_PROCESS.json',{'returncode':result.returncode,
            'stdout':result.stdout.decode('utf-8','replace')[-2000:],'stderr':result.stderr.decode('utf-8','replace')[-2000:]})
        if result.returncode:raise RuntimeError('stage_process_failed_preserved_for_reconciliation')
    return stage_session.step(root,{s['name']:execute for s in STAGES})


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','prepare-repaired','step','inspect'])
    p.add_argument('--session',type=Path,required=True)
    for name in ('prior','context','design'):p.add_argument('--'+name,type=Path)
    p.add_argument('--context-acceptance',type=Path)
    p.add_argument('--additional-calls',type=int,default=0)
    p.add_argument('--previous-session',type=Path)
    p.add_argument('--ledger',type=Path)
    a=p.parse_args();root=a.session.resolve();root.relative_to(ROOT/'data')
    if a.command=='prepare':
        if not all((a.prior,a.context,a.design,a.context_acceptance)):p.error('prepare requires prior/context/design/context-acceptance')
        result=prepare(root,a.prior,a.context,a.design,a.additional_calls,a.context_acceptance)
    elif a.command=='prepare-repaired':
        if not all((a.previous_session,a.prior,a.ledger)):p.error('prepare-repaired requires previous-session/prior/ledger')
        result=prepare_repaired(root,a.previous_session,a.prior,a.ledger)
    elif a.command=='step':result=step(root)
    else:result=stage_session.inspect(root)
    print(result['status'])


if __name__=='__main__':main()
