"""One deliberate complete direction revision after known, complete content findings."""
from copy import deepcopy
import json
from pathlib import Path
from scripts import run_trend_creative_text_trial_v1 as base
from scripts import creative_resume_dispatch_v3 as control
from scripts import run_creative_resume_v10 as identity
from scripts.prepare_creative_emotion_workflow import write_new
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_trend_bridge import validate_direction

PROJECT = base.PROJECT
ROOT = PROJECT / 'data/production_revisions/legal_trend_text_trial_20261007/round_02'
VERSION = 'evidenced_trend_direction_content_revision/v2'


def revised_wire(packet, facts, feedback, *, now):
    wire = base.build_wire(packet, facts, 'direction', now=now)
    context = json.loads(wire['messages'][1]['content'])
    context['complete_direction_revision_feedback'] = deepcopy(feedback)
    wire['messages'][1]['content'] = json.dumps(context, ensure_ascii=False)
    wire['input_provenance'].update(source_context_sha256=digest(context), feedback_sha256=digest(feedback))
    wire['operator_version'] = VERSION
    return wire


class RevisedTrial(base.Trial):
    def __init__(self):
        super().__init__(ROOT)

    def prepare(self, *unused):
        self.root.mkdir(parents=True, exist_ok=True)
        old = base.Trial()
        rt = old.runtime()
        ledger = control.read(rt.ledger)
        rt.check(ledger)
        if not (self.root / 'ANCHOR.json').exists():
            direction = old.accepted('direction')
            stats = old.summary()
            if stats['new_unknown_token_reservations']:
                raise ValueError('new parent usage unknown; no revision dispatch')
            feedback = {
                'scope': 'intentional complete creative direction revision; not HTTP retry or source backfill',
                'original_direction': direction,
                'original_ordinal': 277,
                'user_goal': '完整原创作品；重点是情绪表达、事件因果和画面叙事；法律是核心。',
                'account_format': '案例拆解',
                'findings': [
                    {'path': 'creative_brief.visual_style', 'quote': direction['creative_brief']['visual_style'],
                     'issue': '口播主干与用户画面叙事主线不一致；已冻结账号允许案例拆解。'},
                    {'path': 'creative_brief.ending', 'quote': direction['creative_brief']['ending'],
                     'issue': '预约咨询CTA不是当前用户要求；结尾应兑现当事人选择及现场可见后果。'},
                    {'path': 'creative_brief.constraints.1', 'quote': direction['creative_brief']['constraints'][1],
                     'issue': '核验依据未建立所有第三十八条情形都必须先书面提示的统一前提。'},
                ],
                'revision_requirements': [
                    '提交完整新方向，proposed_format选择案例拆解；不要返回补丁。',
                    '让劳动者与人事在同一具体事件中形成压力、阻力、主动选择和可见反应；律师口播不能替人物完成选择。',
                    '选一个核验依据足以支持的具体事实条件，不罗列多种不同离职路径；不能把调岗、撤工位自动判为违法。',
                    '观众从压迫和犹疑进入掌握选择的释放；结尾必须发生具体变化，不以咨询CTA或取证操作清单替代戏剧收束。',
                    '不承诺胜诉或固定金额，不虚构律师执业身份，不用一般签字必然失权制造焦虑。',
                    '故事方向不排秒数、坐标、微小道具动作；后续正文仍需用户真实确认方向。',
                ],
                'previous_response_outcome_known': True,
                'automatic_transport_retry': False,
                'human_direction_approval': None,
            }
            inherited = {'calls_started': stats['effective_calls_started'],
                'reported_tokens': stats['effective_reported_tokens'],
                'calls_with_known_usage': ledger['starting_spend']['calls_with_known_usage'] + len(ledger['calls']),
                'unknown_token_reservations': stats['unknown_token_reservations'],
                'pending_ordinals': [70, 160], 'parent_ledger_sha256': control.sha_file(rt.ledger)}
            for name in ('SOURCE_PACKET.json', 'LEGAL_CONTEXT.json', 'CURRENT_TASK_AUTHORIZATION.json'):
                control.write(self.root / name, control.read(old.root / name), True)
            control.write(self.root / 'DIRECTION_CONTENT_FEEDBACK.json', feedback, True)
            control.write(self.root / 'ANCHOR.json', {'schema': VERSION, 'inherited': inherited,
                'models': ledger['model_configs'], 'parent_ledger_sha256': control.sha_file(rt.ledger),
                'automatic_retry': False, 'media_calls_authorized': False}, True)
        return self.runtime().prepare()

    def runtime(self):
        old = base.Trial()
        a = control.read(self.root / 'ANCHOR.json')
        def guard():
            rt = old.runtime()
            rt.check(control.read(rt.ledger))
            if control.sha_file(rt.ledger) != a['parent_ledger_sha256']:
                raise ValueError('parent ledger changed')
        sources = [Path(__file__).resolve()] + [self.root / n for n in (
            'ANCHOR.json', 'SOURCE_PACKET.json', 'LEGAL_CONTEXT.json',
            'CURRENT_TASK_AUTHORIZATION.json', 'DIRECTION_CONTENT_FEEDBACK.json')]
        sources += old.runtime().sources + [old.runtime().ledger, old.root / 'DIRECTION.json']
        return control.ContinuationRuntime(PROJECT, self.root, list(dict.fromkeys(sources)),
            a['inherited'], a['models'], inherited_guard=guard, quota_state=None, shared_lock=identity.SHARED_LOCK)

    def dispatch(self, stage, confirmation_path=None):
        if stage != 'direction':
            return super().dispatch(stage, confirmation_path)
        self.prepare()
        packet, facts, feedback = [control.read(self.root / n) for n in (
            'SOURCE_PACKET.json', 'LEGAL_CONTEXT.json', 'DIRECTION_CONTENT_FEEDBACK.json')]
        wire = revised_wire(packet, facts, feedback, now=control.now())
        control.write(self.root / 'request_previews/direction.json', wire, True)
        def validate(value):
            validate_direction(value, packet)
            if value['account_fit']['proposed_format'] != '案例拆解':
                raise ValueError('confirmed narrative goal requires case-analysis format')
            return {'complete_direction_valid': True, 'human_confirmation_pending': True,
                    'creative_quality_passed': False}
        receipt = self.runtime().dispatch('trend_direction_r1', wire, validate)
        if receipt['status'] == 'contract_valid':
            value = receipt['document_output']
            control.write(self.root / 'DIRECTION.json', value, True)
            write_new(self.root / 'STORY_DIRECTION_FOR_REVIEW.md', base.render_direction(value, packet))
        control.write(self.root / 'STATUS.json', {'latest_stage': stage, 'ordinal': receipt['ordinal'],
            'receipt_status': receipt['status'], 'spend': self.summary(), 'creative_quality_passed': False,
            'director_complete': False, 'performance_complete': False, 'media_calls': 0})
        return receipt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'direction', 'draft', 'review', 'status'])
    parser.add_argument('--confirmation', type=Path)
    args = parser.parse_args()
    t = RevisedTrial()
    if args.stage == 'prepare':
        result = t.prepare()
    elif args.stage == 'status':
        result = t.summary()
    else:
        r = t.dispatch(args.stage, args.confirmation)
        result = {'ordinal': r['ordinal'], 'status': r['status'], 'failure': r.get('failure'), 'spend': t.summary()}
    print(json.dumps(result, ensure_ascii=False), flush=True)
