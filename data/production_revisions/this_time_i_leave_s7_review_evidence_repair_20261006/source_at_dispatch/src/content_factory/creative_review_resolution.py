"""Explicit evidence-bound assistant resolution; never fabricates an approval."""
from copy import deepcopy
from .creative_review_gate import digest
from .creative_workflow_contract import CreativeContractError
from .creative_review_packet import build_packet, validate_review, review_disposition, iter_source_map


def apply_resolution(raw, context, resolution):
    packet = build_packet(context)
    disposition = review_disposition(raw, packet)
    def fail(message):
        raise CreativeContractError('FOCUSED_RESOLUTION: ' + message)
    if disposition['disposition'] == 'blocked':
        fail('来源/表达/硬约束阻断不能人工覆盖，必须修复上游')
    if not disposition['requires_resolution']:
        fail('不存在待复核unknown，不允许借复核改写已有结论')
    if not isinstance(resolution,dict) or resolution.get('schema') != 'focused_review_resolution/v1':
        fail('复核回执版本错误')
    if (resolution.get('context_sha256') != packet['context_sha256']
            or resolution.get('raw_review_sha256') != digest(raw)):
        fail('复核回执不是当前上下文和原审核')
    if resolution.get('reviewed_by') != 'assistant' or resolution.get('reviewed_full_text') is not True:
        fail('必须由助手实际阅读全文并记录依据')
    rows = resolution.get('resolutions')
    required = {c['check_id'] for c in raw['checks'] if c['status']=='unknown'}
    if (not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows)
            or len(rows)!=len(required) or {r.get('check_id') for r in rows} != required):
        fail('必须逐项解决全部待复核检查，不允许覆盖已知结论')
    result=deepcopy(raw)
    definitions={c['check_id']:c for c in packet['checks']}
    by_id={r['check_id']:r for r in rows}
    for check in result['checks']:
        if check['check_id'] not in by_id: continue
        row=by_id[check['check_id']]
        if row.get('status') not in ('passed','failed') or not isinstance(row.get('reason'),str) or not row['reason'].strip():
            fail('复核必须明确结论和实际依据')
        refs=row.get('evidence_ids')
        prefixes=definitions[check['check_id']]['source_prefixes']
        if (not isinstance(refs,list) or not refs or any(not isinstance(r,str) or r not in packet['sources'] for r in refs)
                or not all(any(sid==r and any(p==pre or p.startswith(pre+'.') for pre in prefixes)
                               for p,sid in iter_source_map(packet)) for r in refs)):
            fail('复核依据必须属于该检查的真实来源')
        check.update(status=row['status'],reason=row['reason'],issue_ids=deepcopy(row.get('issue_ids',[])),unknown=None)
    additions=resolution.get('additional_issues')
    if not isinstance(additions,list): fail('additional_issues必须显式给出')
    result['issues'].extend(deepcopy(additions))
    validate_review(result,packet)
    return result
