"""Explicitly expand a never-dispatched source in its original owner and budget."""
from copy import deepcopy
import json
import os
from pathlib import Path
import uuid
from . import natural_director_pipeline_v10 as pipeline

core = pipeline.core
parent = pipeline.parent


def replace_json(path,value):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(temporary,path)


def amend(run, receipt, brief, authorization):
    run=Path(run).resolve(); receipt=Path(receipt).resolve(); authorization=Path(authorization).resolve()
    audit=run/'source_amendment_001'
    auth=core._read(authorization)
    if (auth.get('run_dir')!=str(run) or auth.get('user_statement')!='可以获取多个章节别就1章'
            or auth.get('external_text_services')!=['MiniMax','DeepSeek'] or auth.get('max_text_calls')!=6):
        raise ValueError('缺少本次明确来源扩展及外部文本服务授权')
    with core._lock(run/'.execution.lock'):
        with core._lock(Path(parent.CANONICAL_REGISTRY)/'.registration.lock'):
            b,s=parent._verify(run)
            if (s['status']!='prepared' or s['stage']!='writer_full' or s['calls_started']!=0
                    or s['pending_call'] is not None or s['active'] or s['call_bindings']
                    or any(run.glob('CLAIM_*.json')) or any(run.glob('REQUEST_*.json'))
                    or any(run.glob('RESPONSE_*.json')) or b.get('inherited_consumption')
                    or b['budget']['max_calls']!=auth['max_text_calls'] or audit.exists()):
                raise ValueError('仅原未派发零调用任务可扩展一次；不重置预算或未知请求')
            source,evidence,paths=core._source(None,receipt,None,None,None)
            if (source['book_id']!=b['source']['book_id'] or source['title']!=b['source']['title']
                    or not source['text'].startswith(b['source']['text'].rstrip())
                    or len(paths)<=len(b['original_source_paths'])):
                raise ValueError('仅允许同一本书保留原前缀的新增章节')
            blocks=core._legacy_blocks(source,paths)
            if blocks: raise ValueError('新增来源已有历史阻塞，不能扩展')
            registry=Path(parent.CANONICAL_REGISTRY)
            aliases=parent._aliases(source)
            new_registry=[registry/(a+'.json') for a in aliases]
            old_paths={Path(r['path']) for r in b['registry']}
            for p in new_registry:
                if p.exists() and p not in old_paths:
                    raise ValueError('新增正文已有其他登记，不覆盖')
            # Snapshot every original prepared file and all original aliases.
            audit.mkdir()
            snapshots=[]
            for p in sorted(run.glob('*.json')):
                q=audit/p.name;q.write_bytes(p.read_bytes());snapshots.append(core._binding(q))
            for i,row in enumerate(b['registry']):
                q=audit/f'REGISTRY_{i:02}.json';q.write_bytes(Path(row['path']).read_bytes());snapshots.append(core._binding(q))
            proof={'user_authorization':core._binding(authorization),'original_files':snapshots,
                   'original_source_binding':b['source']['binding_id'],'new_source_binding':source['binding_id'],
                   'original_run':str(run),'original_budget':b['budget'],'calls_before':0,
                   'platform_or_model_request_replayed':False}
            core._write(audit/'AUDIT.json',proof)
            amended=deepcopy(b)
            amended.update(source=source,source_evidence=[*evidence,core._binding(authorization),core._binding(audit/'AUDIT.json'),*snapshots],
                original_source_paths=[str(p) for p in paths],brief=brief,legacy_blockers=blocks)
            claim={'schema':parent.VERSION,'run_dir':str(run),'source_binding_id':source['binding_id'],'story_id':aliases[0]}
            # Keep the old source alias fenced to the same owner as well.
            all_paths=sorted(old_paths|set(new_registry))
            for p in all_paths:replace_json(p,claim)
            amended['registry']=[core._binding(p) for p in all_paths]
            replace_json(run/'SOURCE.json',source)
            amended['source_file']=core._binding(run/'SOURCE.json')
            replace_json(run/'BINDING.json',amended)
            replace_json(run/'BINDING_ANCHOR.json',{'sha256':core._digest(amended)})
            # State, counters, protocol, code bindings, budget and route stay fixed.
            checked,current=parent._verify(run)
            assert checked['budget']==b['budget'] and current==s
            core._write(audit/'COMPLETED.json',{'binding':core._binding(run/'BINDING.json'),'calls_started':0})
    return pipeline.inspect_source(run)
