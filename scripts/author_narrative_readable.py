"""Model-authored editorial screenplay from an actually reviewed outline; no media handoff."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_narrative_workflow import verify_workflow, read_candidate, new_output, now, save
from src.trend_intelligence.narrative_workflow import identity, read, require_review, digest, verify_file


def verify_editorial(run_dir, depth=0):
    folder = Path(run_dir).resolve();run = read(folder/'run.json')
    if depth > 5:raise ValueError('Editorial revision chain too deep')
    if run.get('schema') == 'narrative_editorial_revision/v1':
        from scripts.revise_narrative_readable import apply_replacements
        if (run.get('status') != 'editorial_candidate_pending_actual_review'
                or run.get('model_calls') != 1 or run.get('media_calls') != 0):raise ValueError('Unfinished revision')
        previous_path=verify_file(run['parent_editorial'])
        previous,body=verify_editorial(previous_path.parent,depth+1)
        if run['workflow']!=previous['workflow'] or run['kind']!=previous['kind']:raise ValueError('Mixed revision parent')
        if set(run['artifacts'])!={'request.json','prompt.md','response.json','model_output.json','screenplay.md'}:raise ValueError('Missing edits provenance')
        for name,binding in run['artifacts'].items():
            if verify_file(binding)!=folder/name:raise ValueError('Mixed revision artifact')
        messages=read(folder/'request.json')
        if messages != [{'role':'system','content':(folder/'prompt.md').read_text(encoding='utf-8')},
                {'role':'user','content':json.dumps({'screenplay':body,'feedback':verify_file(run['feedback']).read_text(encoding='utf-8-sig')},ensure_ascii=False)}]:raise ValueError('Revision request changed')
        actual=(folder/'screenplay.md').read_text(encoding='utf-8')
        if actual!=apply_replacements(body,read(folder/'model_output.json')):raise ValueError('Editorial revision differs from actual model edits')
        return run,actual
    if (run.get('schema') != 'narrative_editorial_run/v1'
            or run.get('status') != 'editorial_candidate_pending_actual_review'
            or run.get('model_calls') != 1 or run.get('media_calls') != 0):
        raise ValueError('Completed real editorial candidate required')
    workflow = verify_file(run['workflow'])
    _, context, _ = verify_workflow(workflow)
    parent_path = verify_file(run['parent']['run']);review = verify_file(run['parent']['review'])
    outline = read_candidate(parent_path.parent, workflow, 'outline', context)
    require_review(read(review), 'outline', parent_path.parent/'candidate.json', workflow)
    if set(run['artifacts']) != {'request.json','prompt.md','response.json','screenplay.md'}:
        raise ValueError('Original editorial artifacts missing')
    for name, binding in run['artifacts'].items():
        if verify_file(binding) != folder/name:raise ValueError('Mixed editorial artifacts')
    messages = read(folder/'request.json');payload = json.loads(messages[1]['content'])
    expected = {'requested_kind':run['kind'], 'core':outline['core'], 'characters':outline['characters'],
        'approved_events':outline[run['kind']], 'reference_usage':outline['reference_usage'],
        'constraints':context['constraints'], 'account_positioning':context['account_positioning'],
        'notice':'All sources verified locally. Only expand this approved story; do not add source/legal claims.'}
    if 'feedback' in run:expected['revision_feedback'] = verify_file(run['feedback']).read_text(encoding='utf-8-sig')
    if payload != expected or messages[0] != {'role':'system','content':(folder/'prompt.md').read_text(encoding='utf-8')}:
        raise ValueError('Editorial request does not match reviewed parent')
    if read(folder/'response.json').get('finish_reason') == 'length':raise ValueError('Truncated editorial output')
    return run, (folder/'screenplay.md').read_text(encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workflow', 'outline-run', 'review', 'output-dir', 'kind'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--feedback-file')
    parser.add_argument('--model', choices=('MiniMax-M2.7','MiniMax-M3'), default='MiniMax-M2.7')
    args = parser.parse_args()
    if args.kind not in ('short', 'long'):raise ValueError('Unknown kind')
    out = new_output(args.output_dir)
    run = {'schema': 'narrative_editorial_run/v1', 'status': 'preflight', 'kind': args.kind,
           'started_at_bjt': now(), 'model_calls': 0, 'media_calls': 0,
           'execution_status': 'not_compiled_no_video_handoff', 'artifacts': {}}
    try:
        _, context, gate = verify_workflow(args.workflow)
        outline = read_candidate(args.outline_run, args.workflow, 'outline', context)
        require_review(read(args.review), 'outline', Path(args.outline_run)/'candidate.json', args.workflow)
        run.update(workflow=identity(args.workflow), parent={'run': identity(Path(args.outline_run)/'run.json'),
            'review': identity(args.review)})
        save(out/'source_gate.json', gate)
        prompt = (ROOT/'src/trend_intelligence/prompts/narrative_editorial.md').read_text(encoding='utf-8')
        payload = {'requested_kind': args.kind, 'core': outline['core'], 'characters': outline['characters'],
            'approved_events': outline[args.kind], 'reference_usage': outline['reference_usage'],
            'constraints': context['constraints'], 'account_positioning': context['account_positioning'],
            'notice': 'All sources verified locally. Only expand this approved story; do not add source/legal claims.'}
        if args.feedback_file:
            payload['revision_feedback'] = Path(args.feedback_file).read_text(encoding='utf-8-sig')
            run['feedback'] = identity(args.feedback_file)
        messages = [{'role':'system','content':prompt}, {'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
        save(out/'request.json', messages);(out/'prompt.md').write_text(prompt,encoding='utf-8')
        reservation = Path(args.workflow).resolve().parent/'author_reservations'/(digest(out/'request.json')+'.json')
        with reservation.open('x',encoding='utf-8') as stream:json.dump({'run_dir':str(out),'reserved_at_bjt':now()},stream)
        from src.shared.llm_client import LLMClient
        from src.shared.config import settings
        extra = {'thinking':{'type':'disabled'},'reasoning_split':True} if args.model=='MiniMax-M3' else None
        client = LLMClient(model=args.model, timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                           max_retries=0, max_tokens=16000, extra_body=extra)
        if client.provider_name=='mock':raise ValueError('Real model required')
        run.update(status='running',model=args.model,thinking='disabled' if extra else None,model_calls=1);save(out/'run.json',run)
        try:
            body=client.chat_completion_tracked(messages,caller='narrative_editorial_'+args.kind,
                temperature=.4,json_mode=False,use_cache=False)
        finally:save(out/'response.json',getattr(client.provider,'last_response_metadata',{}))
        (out/'screenplay.md').write_text(body or '',encoding='utf-8')
        if not body or read(out/'response.json').get('finish_reason')=='length':raise ValueError('Missing/truncated editorial body')
        for name in ('request.json','prompt.md','response.json','screenplay.md'):
            run['artifacts'][name]=identity(out/name)
        run['status']='editorial_candidate_pending_actual_review'
    except Exception as exc:
        run.update(status='failed',error=str(exc));raise
    finally:
        run['finished_at_bjt']=now();save(out/'run.json',run)
    print(out)


if __name__=='__main__':main()
