"""Bounded, separately audited review of the user's requested assistant revision.

Does not resume the stopped corpus campaign, write its artifacts, or call media.
Each review round is dispatched at most once; received/unknown failures stop.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.corpus_screenplay_v1 import dialogue_stats
from src.content_factory.natural_director_role_clients_v10 import NaturalDirectorRoleClients

RUN = ROOT / 'data/novel_platform_trials/20261025_six_children_assistant_revision'
PRIOR = ROOT / 'data/novel_platform_trials/20261025_six_children_full_corpus'
BOOK = ROOT / 'data/fanqie_account_control/books/7302660145530539062'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open('x', encoding='utf-8') as out:
        json.dump(data, out, ensure_ascii=False, indent=2)


def prepare():
    if (RUN / 'AUTHORIZATION.json').exists():
        return
    previous = read(PRIOR / 'STATE.json')
    if previous['pending'] is not None:
        raise ValueError('previous_pending_requires_resolution')
    save(RUN / 'AUTHORIZATION.json', {
        'user_statement': '你审查修改在跑在审查',
        'scope': 'assistant revision, independent DeepSeek full review, assistant adjudication',
        'operational_bound': 'at most two review calls; second only for a changed complete draft after a known first review',
        'max_new_calls': 2, 'media_authorized': False,
        'inherited_calls': 18, 'inherited_reported_tokens': 550714,
        'prior_run_state_sha256': sha(PRIOR / 'STATE.json'),
        'prior_files': {str(p.relative_to(PRIOR)): sha(p) for p in PRIOR.rglob('*') if p.is_file()},
        'created_at': datetime.now(timezone.utc).isoformat(),
    })


def execute(round_number):
    if (RUN / 'FINAL_STATUS.json').exists():
        raise ValueError('review_scope_closed_no_further_dispatch')
    prepare()
    auth = read(RUN / 'AUTHORIZATION.json')
    if round_number not in (1, 2):
        raise ValueError('review_round_out_of_scope')
    draft = RUN / f'SCREENPLAY_V{round_number}.md'
    if round_number == 2:
        if not (RUN / 'REVIEW_01.json').exists() or sha(draft) == sha(RUN / 'SCREENPLAY_V1.md'):
            raise ValueError('second_review_requires_received_first_review_and_changed_draft')
    for name, value in auth['prior_files'].items():
        if sha(PRIOR / name) != value:
            raise ValueError('prior_evidence_changed')
    chapter_rows = []
    for number in range(3, 8):
        path = BOOK / 'chapters' / f'{number:05d}.json'
        chapter = read(path)
        if hashlib.sha256(chapter['text'].encode()).hexdigest() != chapter['sha256']:
            raise ValueError('source_text_sha_mismatch')
        chapter_rows.append(chapter)
    # Verify this is the same source scope already used for DeepSeek REVIEW_REVISION.
    old_call = read(PRIOR / 'CALL_012.json')
    old_context = json.loads(next(m['content'] for m in old_call['messages'] if m['role'] == 'user'))
    old_chapters = old_context['selected_original_chapters']
    if [(c['index'], c['sha256'], c['text']) for c in chapter_rows] != [(c['index'], c['sha256'], c['text']) for c in old_chapters]:
        raise ValueError('source_scope_differs_from_previous_authorized_deepseek_review')
    text = draft.read_text(encoding='utf-8')
    instruction = '''你是独立的小说改编全文审查员，只审查，不代写。逐字阅读给定的第3—7章原文和完整新稿。
本集主事件在第6—7章，第5章是零花钱前因，第3—4章用于核对关系和此前行为。不要把摘要或旧审核当原文。
审核标准：因果完整、人物关系和当下知情程度一致、物品流转及进出场连续、情绪有触发、动作可拍、信息清楚且快速推进、对白及必要串行动作能在各段自然完成。
允许重新措辞、压缩、动机成立的表演和美术设计。非逐字照搬、删去非核心原文细节不自动构成缺陷。区分明确矛盾与仅可选优化，不能为了提出意见制造问题，也不能因修订稿而放宽。
逐段核算时长：不能只用全片对白字数或6字/秒就判通过，按自然中文约每秒4—5字并考虑迟疑、切换、录像证据可读时间、串行走动及可以并行的动作。过载或信息空转要具体说明。
按JSON输出：{decision:"pass"或"revise",reviewed_source_chapters:[3,4,5,6,7],whole_draft_reviewed:true,checks:{source_causality:"pass/fail",character_relationships:"pass/fail",opening_information:"pass/fail",environment:"pass/fail",emotion_and_gaze:"pass/fail",parallel_action_dialogue:"pass/fail",camera_continuity:"pass/fail",dialogue_timing:"pass/fail"},blocking_issues:[{location,category,source_chapter,source_quote,draft_quote,reason,minimal_fix}],non_blocking_notes:[{location,reason,suggestion}],segment_timing:[{range,verdict,reason}],summary}。
来源类硬伤必须附可核对的原文原句与章节；纯拍摄或节奏问题source_chapter可null。引用不得杜撰。合理改编或审美偏好仅放non_blocking_notes；没有硬伤则blocking_issues为空、decision为pass。若确有硬伤必须revise，不能写“合理无需修改”却放进硬伤。
输出只是本轮文本审核，不代表成片质量、真实配音时长或推广任务验收。'''
    messages = [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': json.dumps({
        'book_name': '你敢惹我？我有六个反派儿子',
        'source_chapters': chapter_rows, 'screenplay': text,
        'screenplay_sha256': sha(draft), 'measured_dialogue': dialogue_stats(text),
    }, ensure_ascii=False)}]
    ordinal = f'{round_number:02d}'
    # Exclusive durable claim: a second invocation cannot dispatch this round.
    save(RUN / f'CALL_{ordinal}.json', {
        'role': 'director', 'provider': 'DeepSeek', 'messages': messages,
        'screenplay_sha256': sha(draft), 'source_chapter_sha256': {str(c['index']): c['sha256'] for c in chapter_rows},
        'parameters': {'max_tokens': 7000, 'temperature': 0.1, 'thinking': 'disabled', 'response_format': {'type': 'json_object'}},
    })
    try:
        result = NaturalDirectorRoleClients().call('director', messages, max_tokens=7000,
            temperature=0.1, thinking='disabled', response_format={'type': 'json_object'})
    except Exception as exc:
        payload = getattr(exc, 'response_payload', None)
        save(RUN / f'ERROR_{ordinal}.json', {'type': type(exc).__name__,
            'metadata': getattr(exc, 'response_metadata', None), 'response_payload': payload,
            'status': 'received_rejected' if payload is not None else 'outcome_unknown',
            'retry_permitted': False})
        raise
    save(RUN / f'RESPONSE_{ordinal}.json', {'text': result.text, 'metadata': result.metadata,
        'response_payload': result.response_payload})
    value = json.loads(result.text)
    save(RUN / f'REVIEW_{ordinal}.json', value)
    checks = value.get('checks', {})
    required = {'source_causality', 'character_relationships', 'opening_information', 'environment',
                'emotion_and_gaze', 'parallel_action_dialogue', 'camera_continuity', 'dialogue_timing'}
    passed = (value.get('decision') == 'pass' and value.get('whole_draft_reviewed') is True
              and value.get('reviewed_source_chapters') == [3,4,5,6,7]
              and value.get('blocking_issues') == [] and set(checks) == required
              and all(v == 'pass' for v in checks.values()))
    receipt = {'status': 'model_pass_awaiting_assistant_review' if passed else 'model_revision_or_schema_review_required',
        'screenplay_sha256': sha(draft), 'model': result.metadata, 'media_calls': 0,
        'round': round_number, 'prior_evidence_unchanged': all(sha(PRIOR / n) == h for n, h in auth['prior_files'].items())}
    save(RUN / f'RECEIPT_{ordinal}.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', type=int, choices=(1,2), required=True)
    args = parser.parse_args()
    execute(args.round)
