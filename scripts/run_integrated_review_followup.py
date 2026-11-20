"""Continue a completed independent review with an adjudicated local patch.

The old run is immutable. Human/primary adjudication is explicit, not an
automatic semantic acceptance or a replay of a completed request.
"""
import argparse
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_integrated_revision_trial as runner
from src.content_factory.novel_adaptation import integrated_revision as n
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest


def prepare(run, prior, handoff_path):
    old = read(prior / 'STATE.json')
    if old['pending'] is not None or not old.get('trial_ended'):
        raise ValueError('prior_not_terminal')
    if old['status'] != 'needs_revision':
        raise ValueError('prior_not_reviewed_needs_revision')
    candidate = (prior / 'SCREENPLAY.md').read_text(encoding='utf-8')
    report = (prior / 'DEEPSEEK_REVIEW.md').read_text(encoding='utf-8')
    packet = read(prior / 'INPUT.json')
    choices = read(prior / 'PRODUCTION_CHOICES.json')
    binding = read(prior / 'FINAL_REVIEW_BINDING.json')
    expected = dict(candidate_digest=digest(candidate), source_digest=digest(packet),
                    review_digest=digest(report))
    if any(binding.get(k) != v for k, v in expected.items()):
        raise ValueError('prior_review_binding_mismatch')
    handoff = read(handoff_path)
    if handoff.get('prior_binding') != expected:
        raise ValueError('handoff_binding_mismatch')
    review = handoff['structured_review']
    decisions = handoff['adjudication']
    diagnostics = n.diagnose(packet, candidate, review)
    n.span_plan(candidate, review, diagnostics, decisions)
    mapping = handoff['report_dispositions']
    refs = [i for row in mapping for i in row['issue_indices']]
    if sorted(refs) != list(range(len(review['issues']))):
        raise ValueError('report_issue_mapping_incomplete')
    if any(not row.get('report_quote') or report.count(row['report_quote']) != 1
           or row.get('decision') not in ('accept', 'defer', 'reject')
           or not row.get('reason') for row in mapping):
        raise ValueError('report_mapping_invalid')
    plan = deepcopy(read(prior / 'PLAN.json'))
    plan.update(version='integrated_review_followup_v1', baseline_calls=old['calls_started'],
                baseline_tokens=old['reported_tokens'], max_calls=old['calls_started'] + 2,
                candidate_digest=digest(candidate), input_digest=digest(packet),
                choices_digest=digest(choices), imported_review_digest=digest(review),
                parent_review_binding=expected, handoff_digest=digest(handoff))
    paths = [Path(p) for p in plan['implementation_pin']]
    paths.append(Path(__file__).resolve())
    plan['implementation_pin'] = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    run.mkdir(exist_ok=False)
    for p in paths:
        (run / ('SNAPSHOT_' + p.name)).write_bytes(p.read_bytes())
    for name, value in [('INPUT', packet), ('SOURCE', read(prior / 'SOURCE.json')),
                        ('PRODUCTION_CHOICES', choices), ('PLAN', plan),
                        ('REVIEW_HANDOFF', handoff), ('review', review),
                        ('REVIEW_DIAGNOSTICS', diagnostics), ('DECISIONS', decisions)]:
        freeze(run / (name + '.json'), value)
    (run / 'ORIGINAL.md').write_text(candidate, encoding='utf-8')
    (run / 'PARENT_DEEPSEEK_REVIEW.md').write_text(report, encoding='utf-8')
    freeze(run / 'AUTHORIZATION.json', {
        'user': '按流程吧deepseek的问题交给minimax修复看看',
        'scope': '沿用同19前情20/21目标原文；MiniMax局部修复一次、DeepSeek独立复核一次；仅文本',
        'prior': str(prior), 'prior_state_sha256': hashlib.sha256((prior / 'STATE.json').read_bytes()).hexdigest(),
        'adjudicator': 'primary_assistant', 'automatic_semantic_adjudication': False})
    state = dict(status='awaiting_issue_adjudication', pending=None,
                 calls_started=old['calls_started'], reported_tokens=old['reported_tokens'],
                 retained_unknowns=old.get('retained_unknowns', []), reported_usage_complete=False,
                 trial_ended=False, completed_stages=[], imported_review=True)
    runner.Ledger(run, plan, state, None).save()


def execute(run, stage):
    plan = read(run / 'PLAN.json')
    handoff = read(run / 'REVIEW_HANDOFF.json')
    if digest(handoff) != plan['handoff_digest']:
        raise ValueError('changed_handoff')
    if digest(read(run / 'review.json')) != plan['imported_review_digest']:
        raise ValueError('changed_imported_review')
    if read(run / 'DECISIONS.json') != handoff['adjudication']:
        raise ValueError('changed_adjudication')
    if digest((run / 'PARENT_DEEPSEEK_REVIEW.md').read_text(encoding='utf-8')) != plan['parent_review_binding']['review_digest']:
        raise ValueError('changed_parent_report')
    runner.execute(run, stage, run / 'DECISIONS.json' if stage == 'repair' else None)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['prepare', 'repair', 'final'])
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--prior', type=Path)
    p.add_argument('--handoff', type=Path)
    a = p.parse_args()
    if a.command == 'prepare':
        prepare(a.run, a.prior, a.handoff)
    else:
        execute(a.run, a.command)
