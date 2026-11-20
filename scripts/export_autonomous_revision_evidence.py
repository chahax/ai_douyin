"""Verify native calls and every supplied source paragraph for a terminal v3 run."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation.stream_evidence import audit_folder


def export(run):
    state=read(run/'STATE.json');plan=read(run/'PLAN.json');corpus=read(run/'SOURCE.json')
    if not state['trial_ended'] or state['pending'] is not None:raise ValueError('run_not_terminal_known')
    catalog={f"CH{ch['index']}-P{i:03}":text for ch in corpus['chapters'] for i,text in enumerate(ch['text'].split('\n\n'),1)}
    initial=read(run/'INPUT.json');target={x['chapter']:x for x in initial['chapters'] if x['role']=='target'}
    calls=[]
    for folder in sorted(run.glob('native_*')):
        request=read(folder/'REQUEST.json');response=read(folder/'RESPONSE.json');a=request['args']
        payload=json.loads(a['messages'][1]['content']);source=payload.get('source')
        number=int(folder.name.split('_')[-1]);call=read(run/f'CALL_{number:03}.json')
        if source is None:
            assert call['node'].endswith('_address_quotes')
            failure=read(run/(call['node'].removesuffix('_address_quotes')+'_ADDRESS_FAILURE.json'))
            assert digest(payload['candidate'])==failure['candidate_digest']
            assert payload['invalid_addresses']=={f'a{i}':x['quote'] for i,x in enumerate(failure['invalid'])}
        else:
            assert {x['chapter']:x for x in source['chapters'] if x['role']=='target'}==target
            assert all(ch['chapter']<=max(target) for ch in source['chapters'])
            assert all(catalog[p['id']]==p['text'] for ch in source['chapters'] for p in ch['paragraphs'])
        audit=audit_folder(folder);assert audit['completion_evidence']=='known'
        if call['node'].endswith('_review'):
            assert 'review' not in payload and 'relevant_history' not in payload
        calls.append(dict(call=number,node=call['node'],model=a['model'],effort=a.get('reasoning_effort'),
            output_budget=a.get('max_tokens',a.get('max_completion_tokens')),message_roles=[x['role'] for x in a['messages']],
            payload_keys=list(payload),source_digest=digest(source) if source is not None else None,candidate_digest=digest(payload['candidate']) if 'candidate' in payload else None,
            input_scope='source_and_candidate' if source is not None else 'quote_address_only',
            source_exact=True if source is not None else None,targets_complete=True if source is not None else None,future_chapters_excluded=True if source is not None else None,
            usage=response['usage'],finish=response['choices'][0]['finish_reason'],
            elapsed_seconds=read(folder/'METRICS.json')['elapsed_seconds']))
    tokens=sum(x['usage']['total_tokens'] for x in calls)
    assert tokens==state['reported_tokens']-plan['baseline_tokens']
    freeze(run/'REQUEST_AND_USAGE_VERIFICATION.json',dict(calls=calls,new_known_tokens=tokens,
        baseline_calls=plan['baseline_calls'],calls_started=state['calls_started'],
        target_chapters=sorted(target),requires_human_confirmation=state['requires_human_confirmation'],
        source_verified_against_corpus=True))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);export(p.parse_args().run)
