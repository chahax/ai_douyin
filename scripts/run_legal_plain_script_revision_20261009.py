"""Explicit complete plain-language revision, full review and readable delivery; no media."""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import sys
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_legal_director_performance_v20 as parent
from scripts import run_creative_resume_v10 as identity
from scripts.run_confirmed_legal_script_trial_v4 import FIXED_INPUTS, render_script
from scripts.run_confirmed_legal_script_trial_v13 import verify_files
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_legal_plain_revision_v1 import build_wire, validate_plain_dialogue
from src.content_factory.creative_trend_bridge import validate_complete_story
from src.content_factory.creative_complete_review_ids_v1 import expand

ROOT = PROJECT / 'data/production_revisions/legal_plain_revision_20261009/round_01'
SCRIPT_SOURCE = PROJECT / 'data/production_revisions/legal_trend_text_trial_20261008/round_11'
MEDIA = PROJECT / 'data/video_generation/legal_trend_20261008/remaining_batch_v1'
FEEDBACK = {
    'schema': 'legal_plain_script_human_revision_request/v1',
    'source': 'current_conversation_user_statement',
    'user_statement': '最后几秒是直接是有持续两个人走出办公室，整体方向可以劳动合同不过可以剧情再白一点没必要再\n“省心”“*心”“对不上不签”，“核对”这种',
    'prior_feedback': '重复催签句、重复戴工牌、2分30秒场景不一致、疑似第三人；取消字幕。',
    'observed_ending': '用户报告成片最后两人都走出办公室；原文本是周姐独自离开，小林留坐。',
    'assistant_media_inspected': False,
    'video_sha256': '0697880b62b93d617e128c0edd07afbbeb4d7058eaf01a78da483c8f438549ee',
    'adopted_old_script_sha256': 'febb8a7c9d186bc3addc0080e02413a67532bab079486decb15423c66de1d7de',
    'requested_scope': 'retain employment departure conflict; complete simpler script and full textual review',
    'human_adoption_of_new_text': None,
    'media_dispatch_in_this_revision': False,
    'automatic_retry': False,
    'old_budget_reset': False
}

def prepare():
    if not (ROOT / 'ANCHOR.json').exists():
        rt = parent.runtime()
        ledger = control.read(rt.ledger)
        rt.check(ledger)
        receipts = [rt.effective_receipt(c) for c in ledger['calls']]
        if any(type(r['response_metadata'].get('total_tokens')) is not int for r in receipts):
            raise ValueError('latest parent usage unresolved')
        for name in FIXED_INPUTS:
            control.write(ROOT / name, control.read(SCRIPT_SOURCE / name), True)
        control.write(ROOT / 'HUMAN_REVISION_REQUEST.json', FEEDBACK, True)
        control.write(MEDIA / 'human_feedback_20261009/PLAIN_LANGUAGE_AND_ENDING_FEEDBACK.json', FEEDBACK, True)
        control.write(ROOT / 'ORIGINAL_ADOPTED_SCRIPT.json', control.read(SCRIPT_SOURCE / 'DRAFT_r8.json'), True)
        files = list(dict.fromkeys(rt.sources + [rt.ledger] + [rt.root / c['receipt'] for c in ledger['calls']]
            + [SCRIPT_SOURCE / n for n in FIXED_INPUTS] + [SCRIPT_SOURCE / 'DRAFT_r8.json', MEDIA / 'human_feedback_20261009/USER_FEEDBACK.json']))
        inherited = deepcopy(ledger['starting_spend'])
        inherited.update(calls_started=inherited['calls_started'] + len(receipts),
            reported_tokens=inherited['reported_tokens'] + sum(r['response_metadata']['total_tokens'] for r in receipts),
            calls_with_known_usage=inherited['calls_with_known_usage'] + len(receipts), parent_ledger_sha256=control.sha_file(rt.ledger))
        if inherited['calls_started'] != 311 or inherited['reported_tokens'] != 5335773:
            raise ValueError('unexpected latest lineage; reconcile before paid dispatch')
        control.write(ROOT / 'ANCHOR.json', {'schema': 'legal_plain_script_operator/v1', 'inherited': inherited,
            'models': ledger['model_configs'], 'parent_files': {str(p): control.sha_file(p) for p in files},
            'automatic_retry': False, 'media_authorized': False, 'publishing': False}, True)
    return runtime().prepare()

def runtime():
    anchor = control.read(ROOT / 'ANCHOR.json')
    def guard():
        verify_files(anchor['parent_files'])
        if control.read(ROOT / 'HUMAN_REVISION_REQUEST.json') != FEEDBACK:
            raise ValueError('actual human revision request changed')
    own = [Path(__file__).resolve(), PROJECT / 'src/content_factory/creative_legal_plain_revision_v1.py',
        ROOT / 'ANCHOR.json', ROOT / 'HUMAN_REVISION_REQUEST.json', ROOT / 'ORIGINAL_ADOPTED_SCRIPT.json'] + [ROOT / n for n in FIXED_INPUTS]
    return control.ContinuationRuntime(PROJECT, ROOT, list(dict.fromkeys(own + [Path(p) for p in anchor['parent_files']])),
        anchor['inherited'], anchor['models'], inherited_guard=guard, quota_state=None, shared_lock=identity.SHARED_LOCK)

def summary():
    result = runtime().summary()
    result['unknown_token_reservations'] += control.read(ROOT / 'ANCHOR.json')['inherited']['unknown_token_reservations']
    result.update(unknown_outcome_ordinals=[70], unknown_usage_ordinals=[70, 160])
    return result

def accepted(label):
    rt = runtime()
    ledger = control.read(rt.ledger)
    rt.check(ledger)
    rows = [row for row in ledger['calls'] if row['label'] == label]
    if len(rows) != 1:
        raise ValueError('exact source call required: ' + label)
    receipt = rt.effective_receipt(rows[0])
    if receipt['status'] != 'contract_valid':
        raise ValueError('source rejected or unknown: ' + label)
    return receipt

def wire(stage, *, script=None, revision=None):
    values = [control.read(ROOT / n) for n in ('SOURCE_PACKET.json', 'LEGAL_CONTEXT.json', 'GRAPH_PACKET.json',
        'CONTENT_SCOPE.json', 'DIRECTION.json', 'HUMAN_DIRECTION_CONFIRMATION.json')]
    packet, facts, graph, scope, direction, confirmation = values
    return build_wire(packet, facts, graph, scope, stage, now=control.now(), direction=direction,
        confirmation=confirmation, feedback=FEEDBACK, script=script, revision=revision)

def preflight():
    prepare()
    req = wire('draft')
    context = json.loads(req['messages'][1]['content'])
    original = control.read(ROOT / 'SOURCE_PACKET.json')['inputs']['reference_fulltext']
    if context['reference_fulltext'] != original or not original:
        raise ValueError('full actual reference missing')
    if req['model'] != 'MiniMax-M3' or req['parameters']['thinking'] != 'disabled':
        raise ValueError('unverified writer configuration')
    record = {'status': 'offline_input_binding_verified', 'spend': summary(),
        'actual_reference_sha256': control.digest(original), 'full_reference_in_actual_messages': True,
        'writer_criteria_count': len(context['writer_expression_criteria']), 'human_request_bound': context['human_revision_request'] == FEEDBACK,
        'review_required': True, 'model_calls': 0, 'media_calls': 0, 'creative_quality_passed': False}
    control.write(ROOT / 'OFFLINE_PREFLIGHT.json', record, True)
    return record

def dispatch(stage, number):
    prepare()
    script = None
    revision = None
    if stage == 'review':
        script = accepted(f'plain_draft_r{number}')['output']
    elif number > 1:
        draft = accepted(f'plain_draft_r{number-1}')
        review = accepted(f'plain_review_r{number-1}')
        if not review['validation']['needs_revision']:
            raise ValueError('genuine complete review findings required for new revision')
        effective, _, _ = expand(review['output'], draft['output'], json.loads(review['request']['messages'][1]['content'])['emotional_brief'])
        revision = {'previous_complete_script': draft['output'], 'complete_review': effective,
            'draft_ordinal': draft['ordinal'], 'review_ordinal': review['ordinal']}
    req = wire(stage, script=script, revision=revision)
    # Use the exact frozen request when resuming a stage; timestamps must not cause duplicate dispatch.
    path = ROOT / f'request_previews/{stage}_r{number}.json'
    if path.exists():
        frozen = control.read(path)
        comparison = deepcopy(req)
        # The gate ran with current time; request context itself contains no dynamic dispatch timestamp.
        if frozen != comparison:
            raise ValueError('existing request differs; reconcile original stage')
        req = frozen
    else:
        control.write(path, req, True)
    context = json.loads(req['messages'][1]['content'])
    brief = context['emotional_brief']
    direction = control.read(ROOT / 'DIRECTION.json')
    def validate(value):
        if stage == 'draft':
            return {**validate_complete_story(value, direction), **validate_plain_dialogue(value)}
        return expand(value, script, brief)[2]
    receipt = runtime().dispatch(f'plain_{stage}_r{number}', req, validate)
    if receipt['status'] == 'contract_valid':
        result = receipt['output']
        if stage == 'review':
            result, evidence, _ = expand(result, script, brief)
            control.write(ROOT / f'REVIEW_EVIDENCE_r{number}.json', evidence, True)
        control.write(ROOT / f'{stage.upper()}_r{number}.json', result, True)
        if stage == 'draft':
            write_new(ROOT / f'FULL_SCRIPT_r{number}.md', render_script(result, '完整MiniMax新稿；等待全文复审与用户内容确认。'))
    control.write(ROOT / 'STATUS.json', {'stage': stage, 'revision': number, 'ordinal': receipt['ordinal'],
        'receipt_status': receipt['status'], 'spend': summary(), 'media_calls': 0, 'human_new_script_adopted': None})
    return {'ordinal': receipt['ordinal'], 'status': receipt['status'], 'failure': receipt.get('failure'),
        'validation_error': receipt.get('validation_error'), 'validation': receipt.get('validation'), 'spend': summary()}

def finish(number):
    draft = accepted(f'plain_draft_r{number}')
    review = accepted(f'plain_review_r{number}')
    if review['validation']['needs_revision'] or review['validation']['emotion_checkpoint'] != 'ready_for_director':
        raise ValueError('unresolved current full review')
    script = draft['output']
    out = ROOT / f'DELIVERABLE_r{number}'
    control.write(out / 'FULL_SCRIPT.json', script, True)
    control.write(out / 'FULL_TEXT_REVIEW.json', control.read(ROOT / f'REVIEW_r{number}.json'), True)
    write_new(out / 'FULL_SCRIPT.md', render_script(script, '完整新稿已完成DeepSeek全文复审；等待用户采用。尚未生成新视频。'))
    speeches = [s['text'] for b in script['beats'] for s in b['steps'] if s['kind'] == 'dialogue']
    control.write(out / 'HANDOFF.json', {'status': 'complete_reviewed_text_awaiting_human_adoption',
        'script_sha256': control.digest(script), 'draft_ordinal': draft['ordinal'], 'review_ordinal': review['ordinal'],
        'issues': 0, 'beat_count': len(script['beats']), 'speech_count': len(speeches),
        'spoken_characters': sum(len(s) for s in speeches), 'human_new_script_adopted': None,
        'director_and_performance_recompile_required': True, 'reuse_old_timing': False,
        'media_calls': 0, 'creative_quality_passed': False, 'spend': summary()}, True)
    return {'delivery': str(out), 'spend': summary()}

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'preflight', 'draft', 'review', 'finish', 'status'])
    parser.add_argument('--revision', type=int, default=1)
    args = parser.parse_args()
    if args.revision < 1:
        raise ValueError('positive revision required')
    result = prepare() if args.stage == 'prepare' else preflight() if args.stage == 'preflight' else summary() if args.stage == 'status' else finish(args.revision) if args.stage == 'finish' else dispatch(args.stage, args.revision)
    print(json.dumps(result, ensure_ascii=False), flush=True)
