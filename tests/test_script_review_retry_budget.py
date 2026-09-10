"""Separate full-report/quote-patch budgets; all responses are offline fixtures."""
import json
from pathlib import Path

import pytest

from src.trend_intelligence import script_pair as gate
from src.trend_intelligence import saved_script_review as saved
from src.trend_intelligence.review_evidence_patch import PATCH_SCHEMA
from test_script_review_evidence_revision import PatchReviewer, review_with_trace


class TwoFullTwoPatchReviewer(PatchReviewer):
    def __init__(self):
        super().__init__(('invented', 'valid'), malformed_full=1)

    def chat_completion_tracked(self, messages, **kwargs):
        response = super().chat_completion_tracked(messages, **kwargs)
        payload = json.loads(next(m['content'] for m in messages if m['role'] == 'user'))
        if (kwargs.get('caller') == 'pre_video_script_review'
                and payload.get('schema') != PATCH_SCHEMA and self.full_count == 2):
            report = json.loads(response)
            report['shot_audit'][0]['cross_field_evidence']['audio'] += '第二份完整报告的抄录错字'
            return json.dumps(report, ensure_ascii=False)
        return response


def test_full_reports_stop_after_three_without_a_fourth_call(tmp_path):
    client = PatchReviewer(malformed_full=99)
    with pytest.raises(RuntimeError, match='审稿结果格式无效'):
        review_with_trace(client, tmp_path)
    assert gate.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS == 3
    assert len(client.calls) == client.full_count == 3 and client.patch_count == 0
    assert not (tmp_path / 'review_1_request_4.json').exists()


def test_two_full_reports_plus_two_patches_can_pass_and_restore_saved_gate(tmp_path):
    from test_saved_script_review_current import isolated_service
    from test_pre_video_script import NOW
    from src.trend_intelligence.pre_video_script import PreVideoScriptRequest
    from src.web.trend_dashboard import _load_saved_script_pair
    client = TwoFullTwoPatchReviewer()
    pair = isolated_service(client, tmp_path).generate(PreVideoScriptRequest(
        account_key='account01', short_seconds=60, recent_video_types=('mixed',),
        output_dir=str(tmp_path)), now=NOW)
    trace = Path(pair.short.script.generation['trace_dir'])
    report = json.loads((trace / 'review_1.json').read_bytes())
    chain = json.loads((trace / 'review_1_attempt_chain.json').read_bytes())
    assert report['passed'] and report['format_attempts'] == 4
    assert [row['mode'] for row in chain['attempts']] == [
        'full_report', 'full_report', 'evidence_patch', 'evidence_patch']
    assert client.full_count == client.patch_count == 2 and len(client.calls) == 5  # One author.
    assert gate.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS == 3
    assert gate.SCRIPT_REVIEW_MAX_EVIDENCE_PATCH_ATTEMPTS == 2
    assert gate.SCRIPT_REVIEW_MAX_TOTAL_ATTEMPTS == 5
    items = _load_saved_script_pair(pair.short.script.account_uuid, tmp_path)
    before = len(client.calls)
    status = saved.current_saved_script_review(items, allowed_root=tmp_path)
    assert status['current_passed'], status
    assert len(client.calls) == before


def test_two_failed_patches_cannot_consume_a_third_patch(tmp_path):
    client = PatchReviewer(('invented',))
    with pytest.raises(RuntimeError, match='审稿结果格式无效'):
        review_with_trace(client, tmp_path)
    assert client.full_count == 1 and client.patch_count == 2 and len(client.calls) == 3
    assert not (tmp_path / 'review_1_request_4.json').exists()
    chain = json.loads((tmp_path / 'review_1_attempt_chain.json').read_bytes())
    assert [row['mode'] for row in chain['attempts']] == ['full_report', 'evidence_patch', 'evidence_patch']
    assert all(not row['valid'] for row in chain['attempts'])


def test_saved_replay_rejects_three_patches_even_when_total_is_below_five(tmp_path, monkeypatch):
    client = PatchReviewer(('invented', 'invented', 'valid'))
    # Deliberately create an over-budget synthetic trace to exercise saved replay.
    # This temporary bypass exists only in the fixture, never in production code.
    with monkeypatch.context() as fixture_only:
        fixture_only.setattr(gate.ScriptReviewRetryState, 'assert_can_call', lambda self, attempt: None)
        report = review_with_trace(client, tmp_path)
    assert report['passed'] and report['format_attempts'] == 4
    assert client.full_count == 1 and client.patch_count == 3
    original_messages = client.calls[0][0]
    payload = json.loads(original_messages[1]['content'])
    with pytest.raises(ValueError):
        saved._verify_review_attempt_chain(report, payload, original_messages[0]['content'],
                                           tmp_path, 1, tmp_path)
