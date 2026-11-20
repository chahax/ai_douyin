"""Read-only model evidence rendering; writes only derived evidence in ended runs."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest


def export(run):
    state=read(run/'STATE.json');plan=read(run/'PLAN.json')
    if not state['trial_ended'] or state['pending'] is not None:raise ValueError('run_not_ended_known')
    calls=[]
    for folder in sorted(run.glob('native_*')):
        request=read(folder/'REQUEST.json');response=read(folder/'RESPONSE.json')
        a=request['args'];payload=json.loads(a['messages'][1]['content'])
        num=int(folder.name.split('_')[-1]);call=read(run/f'CALL_{num:03}.json')
        calls.append(dict(call=num,node=call['node'],model=a['model'],effort=a.get('reasoning_effort'),
            output_budget=a.get('max_tokens',a.get('max_completion_tokens')),message_roles=[x['role'] for x in a['messages']],
            payload_keys=list(payload),source_digest=digest(payload['source']),
            candidate_digest=digest(payload['candidate']) if 'candidate' in payload else None,
            usage=response['usage'],finish=response['choices'][0]['finish_reason'],
            elapsed_seconds=read(folder/'METRICS.json')['elapsed_seconds'],capacity=call['capacity']))
    usage=sum(x['usage']['total_tokens'] for x in calls)
    assert usage==state['reported_tokens']-plan['baseline_tokens']
    assert all(x['source_digest']==plan['source_digest'] for x in calls)
    freeze(run/'REQUEST_AND_USAGE_VERIFICATION.json',dict(calls=calls,new_known_tokens=usage,
        baseline_calls=plan['baseline_calls'],calls_started=state['calls_started'],
        source_scope=[dict(chapter=x['chapter'],role=x['role'],paragraphs=len(x['paragraphs'])) for x in read(run/'INPUT.json')['chapters']]))
    for path in sorted(run.glob('round_*_review.json')):
        review=read(path);lines=['# 模型整稿审核（原返回字段阅读版）','',review['summary'],'']
        for row in review['issues']:
            lines.extend([f"## {row['id']} · {row['severity']} · {row['subject']}",'',row['claim'],'',row['reason'],'',
                          '原文：'+', '.join(row['source_ids']),''])
            for scope in row['scopes']:lines.extend(['> '+scope['quote'].replace('\n','\n> '),'','边界：'+scope['boundary'],''])
        path.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();export(a.run)
