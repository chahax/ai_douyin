"""Return a verified writer draft for bounded revision, preserving native verdicts."""
from pathlib import Path
from . import natural_director_pipeline_v10 as pipeline


def request_revision(run, diagnosis_path):
    run=Path(run).resolve();diagnosis_path=Path(diagnosis_path).resolve()
    core,parent=pipeline.core,pipeline.parent
    with core._lock(run/'.execution.lock'):
        pipeline._source_route(run)
        b,s=parent._verify(run)
        d=core._read(diagnosis_path)
        if (s['stage']!='director_full' or s['pending_call'] is not None
                or s['status'] in parent.TERMINAL or s['reported_tokens'] is None
                or s['calls_started']+2>b['budget']['max_calls']
                or s['revisions_used']>=b['budget']['max_revisions']):
            raise ValueError('只能退回已知完整编剧稿，且须保留一轮编剧与审查预算')
        draft=parent._text(s)
        if (d.get('draft')!=s['active']['writer_full']['file']
                or d.get('source_binding')!=b['source']['binding_id']
                or d.get('decision')!='revise' or d.get('reviewer')!='assistant_editorial_review'
                or not isinstance(d.get('issues'),list) or not d['issues']
                or any(not i.get('quote') or i['quote'] not in draft or not i.get('reason') for i in d['issues'])):
            raise ValueError('退回意见必须绑定原稿和原来源，并提供实际原稿证据')
        gate=parent._value(s,'gate')
        if gate['gate']['decision']!='pass':raise ValueError('原生审核不是已知通过，沿原失败流程处理')
        audit=run/f'EDITORIAL_RETURN_{s["calls_started"]:03}.json'
        if audit.exists():raise ValueError('原退回已记录，不重复执行')
        core._write(audit,{'diagnosis':core._binding(diagnosis_path),'before_checkpoint':core._binding(sorted(run.glob('STATE_*.json'))[-1]),
          'original_native_gate':s['active']['gate'],'reviewer':'assistant_editorial_review',
          'original_native_pass_preserved':True,'budget':b['budget'],'calls_started':s['calls_started']})
        s.update(stage='writer_full',status='needs_full_revision',previous_draft=draft,
          feedback={'editorial_review':d,'original_native_review':parent._value(s,'review_bundle'),
                    'return_evidence':core._binding(audit)})
        parent._save_state(run,s)
        parent._verify(run)
    return pipeline.inspect_source(run)
