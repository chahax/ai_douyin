"""Read-only continuation of an already dispatched original comment."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def run_settlement(ctx,payload,session):
    from .publication_comment_settlement_control import get_verified_settlement_inputs
    from .publication_comment_settlement import verify_only
    from .publication_reconciliation import _active_ai_source
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    inputs=get_verified_settlement_inputs(payload)
    scope=inputs['manifest'];prepared=inputs['prepared']
    if not re.fullmatch(r'[a-f0-9]{32}',ctx.task_id):raise ValueError('invalid settlement task')
    if ctx.resource.account_uuid!=scope['account_uuid'] or ctx.resource.account_key!=scope['account_key']:
        raise ValueError('settlement account differs')
    out=ROOT/'data/publication_reconciliations'/ctx.task_id
    out.mkdir(parents=True,exist_ok=True)
    adapter=DouyinAdapter(session=session,runtime_context=ctx.resource.context)
    frozen={'account_uuid':scope['account_uuid'],'account_key':scope['account_key'],
        'authorization':inputs['original_command']['payload']['authorization'],
        'comment':inputs['comment_text'],'title':prepared['title'],'hashtags':prepared['hashtags'],
        'publish_evidence':inputs['source_evidence']['result']['publish_evidence'],
        'original_comment_command_id':scope['original_comment_command_id'],
        'source_unknown_receipt':scope['source_unknown_receipt'],'source_claim':scope['source_claim']}
    ctx.check_dispatch()
    comment=verify_only(adapter,frozen,scope['post_id'],evidence_dir=out)
    evidence=dict(comment.get('publish_evidence') or {})
    evidence.update(ai_active_source_verified=_active_ai_source(inputs['journal_rows']),
        ai_active_source='original_frozen_pre_submit_journal',
        ai_label_origin='unknown; display does not identify creator-selected origin')
    complete=(comment.get('status')=='matching_comment_already_visible' and comment.get('exact_visible') is True
        and comment.get('new_submission') is False and evidence.get('review_status')=='clear'
        and all(evidence.get(k) is True for k in ('post_verified','ai_declaration_verified',
            'fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified')))
    status='verified_published' if complete else 'human_required' if comment.get('status')=='human_required' else 'verification_pending'
    result={'status':status,'publish_evidence':evidence,'comment':comment}
    native={'schema':'publication_reconciliation_evidence/20261019/v1','account_uuid':scope['account_uuid'],
        'original_command_id':scope['original_command_id'],'reconciliation_command_id':ctx.task_id,'result':result}
    target=out/'evidence.json'
    with target.open('x',encoding='utf-8')as handle:json.dump(native,handle,ensure_ascii=False,indent=2)
    return dict(result,evidence_ref={'path':str(target.resolve()),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
