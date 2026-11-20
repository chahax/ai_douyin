"""Read-only native receipts and exact patch/continuity binding verification."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,digest,freeze
from src.content_factory.novel_adaptation import continuity_cards_v5 as cards,prose_patch
from src.content_factory.novel_adaptation.stream_evidence import audit_folder

def audit(run):
    state=read(run/'STATE.json');plan=read(run/'PLAN.json')
    if not state['trial_ended'] or state['pending'] is not None:raise ValueError('not_terminal_known')
    calls=[];patches=[];chapters=[];reading=[]
    roots=[Path(x) for x in plan.get('prior_roots',[])]+[run]
    children=[p for root in roots for p in sorted(root.glob('chapter_*'))]
    for child in children:
        if not child.is_dir():continue
        for p in child.glob('CALL_*.json'):
            n=int(p.stem.split('_')[1]);call=read(p);receipt=read(child/f'RESPONSE_{n:03}.json')
            if audit_folder(child/f'native_{n:03}')['completion_evidence']!='known':raise ValueError('missing_native_terminal')
            payload=json.loads(call['messages'][1]['content'])
            native=read(child/f'native_{n:03}/REQUEST.json')['args']
            if native['messages']!=call['messages']:raise ValueError('native_messages_differ')
            calls.append(dict(number=n,node=call['node'],role=call['role'],usage=receipt.get('usage'),
                model=receipt.get('model'),requested_model=native.get('model'),reasoning_effort=native.get('reasoning_effort'),
                requested_output_tokens=native.get('max_completion_tokens',native.get('max_tokens')),
                finish=receipt['choices'][0]['finish_reason'],continuity_present='continuity' in payload))
            if child.name.endswith('_script'):
                b=read(child/'CONTINUITY.json');cards.validate_bundle(b)
                if payload.get('continuity')!=b:raise ValueError('node_missing_or_different_continuity')
                if call['role']=='director' and any(k in payload for k in ['review','relevant_history','confirmed_issues']):raise ValueError('independent_review_contaminated')
        for p in child.glob('cycle_*_SPANS.json'):
            prefix=p.name.removesuffix('_SPANS.json');pp=child/(prefix+'_patch.json')
            if not pp.exists():continue
            before=(child/(prefix+'_BEFORE.md')).read_text(encoding='utf-8');after=(child/(prefix+'_AFTER.md')).read_text(encoding='utf-8')
            if prose_patch.apply(before,read(p),read(pp))!=after:raise ValueError('patch_replay_mismatch')
            patches.append(dict(run=str(child),cycle=prefix,after_digest=digest(after)))
        p=child/'SCREENPLAY.md'
        if p.exists():
            text=p.read_text(encoding='utf-8')
            if digest(text)!=read(child/'CANDIDATE_BINDING.json')['candidate_digest']:raise ValueError('candidate_changed')
            s=read(child/'STATE.json');ch=int(child.name.split('_')[1])
            chapters.append(dict(chapter=ch,status=s['status'],candidate_digest=digest(text),characters=len(text),script=str(p.resolve())))
            reading.append(f'# 第{ch}章\n\n'+text)
    calls.sort(key=lambda x:x['number'])
    baseline_calls=plan.get('trial_baseline_calls',plan['baseline_calls'])
    baseline_tokens=plan.get('trial_baseline_tokens',plan['baseline_tokens'])
    if [x['number'] for x in calls]!=list(range(baseline_calls+1,state['calls_started']+1)):raise ValueError('call_sequence_gap')
    tokens=sum(x['usage']['total_tokens'] for x in calls)
    if tokens!=state['reported_tokens']-baseline_tokens:raise ValueError('usage_mismatch')
    previous=None
    for ch in range(1,4):
        p=run/f'COMMIT_{ch:03}.json'
        if not p.exists():continue
        co=read(p);b=co['bundle'];cards.validate_bundle(b)
        if b['parent_digest']!=previous:raise ValueError('commit_chain_broken')
        if digest(dict(bundle=b,handoff=co['handoff']))!=co['commit_digest']:raise ValueError('commit_digest_changed')
        previous=co['commit_digest']
    # Latest chapter candidate wins only in the reading export; every older
    # candidate and its failure remain in the native verification records.
    final_chapters={x['chapter']:x for x in chapters}
    reading=[f"# 第{ch}章\n\n"+Path(row['script']).read_text(encoding='utf-8') for ch,row in sorted(final_chapters.items())]
    result=dict(status=state['status'],baseline_calls=baseline_calls,final_calls=state['calls_started'],new_calls=len(calls),
        new_tokens=tokens,final_tokens=state['reported_tokens'],calls=calls,patches=patches,chapters=chapters,
        no_new_unknown=True,all_script_nodes_same_bundle=True,independent_reviews_without_old_opinions=True)
    freeze(run/'REQUEST_AND_USAGE_VERIFICATION.json',result)
    (run/'SCREENPLAYS_READING.md').write_text('# 跨章共享资料 v5 前三章生产测试稿\n\n原生生成及局部补丁结果，验收意见见 PRIMARY_REVIEW；不代表视频成片验收。\n\n'+'\n\n---\n\n'.join(reading),encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ('calls','patches','chapters')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();print(json.dumps(audit(a.run),ensure_ascii=False))
