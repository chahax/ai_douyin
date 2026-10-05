"""Operator-controlled serial text calls; no automatic dispatch or retries."""
import json,sys,traceback
from scripts import run_creative_resume_v9 as r
sys.stdout.reconfigure(encoding='utf-8')
print(json.dumps({'session':'initial_frozen_verification','provider_calls':0}),flush=True)
r.prepare()
print(json.dumps({'session':'ready','source_checks_remain_enabled':True,'automatic_dispatch':False}),flush=True)
for line in sys.stdin:
    try:
        command=json.loads(line)
        op=command['op']
        if op=='quit':
            print(json.dumps({'session':'closed'}),flush=True);break
        feedback=r.control.read(command['feedback_path']) if command.get('feedback_path') else command.get('feedback')
        if op=='plan':value=r.plan(command['d'],command['index'],command['revision'],feedback)
        elif op=='local':value=r.local(command['d'],command['index'],command['revision'],feedback)
        elif op=='complete':value=r.complete(command['d'])[3];value={k:value.get(k) for k in ('execution_shot_count','total_duration_seconds','performance_checks')}
        elif op=='final-review':value=r.final_review(command['d'],command.get('revision',1))
        elif op=='report':value=r.summary()
        elif op=='finalize':value=r.finalize(command['d'],r.control.read(command['evidence_path']))
        else:raise ValueError('unsupported operation')
        if isinstance(value,dict) and 'ordinal' in value:value={k:value.get(k) for k in ('ordinal','label','status','validation_error','document_output','validation','response_metadata')}
        print('SESSION_RESULT '+json.dumps(value,ensure_ascii=False,separators=(',',':')),flush=True)
    except Exception as exc:
        print('SESSION_ERROR '+json.dumps({'type':type(exc).__name__,'message':str(exc),'automatic_retry':False},ensure_ascii=False),flush=True)
