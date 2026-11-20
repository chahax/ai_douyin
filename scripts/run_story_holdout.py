"""Source-only unseen-chapter probe of the direct prose writer, with cumulative ledger."""
import argparse, sys, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest
from scripts.run_story_text_trial import execute
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger

def prepare(run, prior, source_path, target, ceiling, context_start=1):
    old=read(prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('prepared','running','outcome_unknown'):
        raise ValueError('prior_unsettled')
    full=read(source_path)
    if target not in [c['index'] for c in full['chapters']]:raise ValueError('target_missing')
    if not 1<=context_start<=target:raise ValueError('invalid_context_start')
    source={**full,'chapters':[c for c in full['chapters'] if context_start<=c['index']<=target]}
    plan=read(prior/'PLAN.json'); previous=plan['max_calls']
    if ceiling<previous or ceiling<=old['calls_started']:raise ValueError('invalid_window')
    plan.update(max_calls=ceiling,baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],
                source_sha256=digest(source),chapter_indices=[c['index'] for c in source['chapters']],
                version='direct_prose_source_holdout_v1',user_statement='用户继续测试；同书已授权MiniMax文本，新章直写及最多两轮局部修复，无媒体发布。')
    paths=['scripts/run_story_holdout.py','scripts/run_story_text_trial.py',
           'src/content_factory/novel_adaptation/story_text.py',
           'src/content_factory/novel_adaptation/protocol_direct.py']
    plan['implementation_pin']={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    packet={'source_sha256':digest(source),'entities':[],'facts':[],
            'semantic_status':'source_only_unreviewed','note':'No reused chapter2 identities or manually supplied plot answers.'}
    run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',source),('PACKET',packet),('TARGETS',[target]),
        ('CONFIG',{'use_reviewed_materials':False,'scope_guard':True,'direct_story':True}),
        ('EVALUATION_PLAN',{'target':target,'variant':'source_only_direct_prose','max_semantic_repairs':2,
            'full_source_sha256':digest(full),'context_start':context_start,'no_future_chapters':True,'not_whole_pipeline_acceptance':True,
            'criteria':['source meaning and uncertainty','speaker knowledge','time and location continuity','complete target events'],
            'development_holdout_only':True}),
        ('LINEAGE',{'prior':str(prior.resolve()),'prior_state_sha256':digest(old),
            'previous_ceiling':previous,'new_ceiling':ceiling,'net_extension':ceiling-previous,
            'authorization':'User: 继续测试啊; existing same-book MiniMax text authorization'})]:
        freeze(run/(name+'.json'),value)
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],
           'baseline_tokens':old['reported_tokens']}
    DirectLedger(run,plan,state,None).save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute'])
    for k in ('run','prior','source'):p.add_argument('--'+k,type=Path,required=k=='run')
    p.add_argument('--target',type=int);p.add_argument('--ceiling',type=int);p.add_argument('--context-start',type=int,default=1);a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.source,a.target,a.ceiling,a.context_start)
    else:execute(a.run)
