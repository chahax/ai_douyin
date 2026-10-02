"""Synthetic model output for tests; never used as a production fallback."""
import copy
import json


def fixture_source_evidence():
    return [{'source_id': 'labor-0', 'analysis_id': 'analysis:labor-0',
             'expression_analysis': {'evidence': [
                 {'id': 'visual-1', 'channel': 'visual', 'start_seconds': 0, 'end_seconds': 2,
                  'text': '测试合成观察：人物把两张实物单据并排展示编号差异。'}]}}]


def pair_payload():
    data = {'core_message': '先核对账单编号和付款记录，避免把重复通知当成两笔欠款。'}
    roles = ('setup', 'conflict', 'escalation', 'turn', 'resolution', 'closure')
    for kind, count, seconds in [('short', 6, 60), ('long', 12, 180)]:
        ending = '编号和付款记录对上了，这封重复通知已经核对清楚。'
        data[kind] = {
            'title': '同一笔账单，为什么又来了', 'premise': f'{kind}：当事人收到重复账单并逐步核对清楚。',
            'dramatic_question': '为什么已付款还收到催款通知？',
            'resolution': '当事人当场核对编号，确认通知对应已经付款的同一笔账单。',
            'closing_line': ending, 'legal_review_note': '仅为虚构的事实核对情境，等待人工审核。',
            'expression_plan': {
                'presentation_mode': 'prop_demonstration',
                'account_fit': '以具体账单核对帮助遇到重复催款的普通人理解事实。',
                'source_pattern_rationale': '借鉴测试来源实物并排对照机制；指标只作观察关联。',
                'protagonist': '当事人', 'goal': '避免为已经支付的账单再次付款。',
                'obstacle': '第二张通知与记忆中的付款事实相矛盾。', 'stakes': '再次操作可能重复支付。',
                'action_chain': [
                    {'shot_ids': ['S01', 'S02'], 'visible_action': '按下付款前被重复通知编号打断，摊开旧记录。',
                     'state_change': '从准备付款变成停下核对两个实物。'},
                    {'shot_ids': [f'S{count//2+1:02d}'], 'visible_action': '把两张单据编号对齐，再与付款记录逐项比照。',
                     'state_change': '从看似两笔欠款变成发现对应同一笔已付账单。'}],
                'turn': {'shot_ids': [f'S{count//2+1:02d}'], 'visible_trigger': '编号与付款记录完整对应。',
                         'result': '停止重复付款操作，改为归档重复通知。'},
                'ending': {'shot_ids': [f'S{count:02d}'], 'visible_result': '关闭重复付款页面并归档通知。',
                           'core_answer': '眼前第二张通知对应已经支付的同一账单。'}},
            'reference_usage': [{'source_id': 'labor-0', 'evidence_ids': ['visual-1'],
                                 'borrowed_expression': '借鉴实物并排对照让差异可见的表达方法。',
                                 'adaptation': '原创改为重复账单和已付款记录的核对行动。',
                                 'shot_ids': ['S01', f'S{count//2+1:02d}']}],
            'characters': [{'name': '当事人', 'identity': '普通职员', 'appearance': '短发',
                            'wardrobe': '深蓝外套', 'performance_arc': '从焦虑到确认事实后平静'}],
            'story_beats': [{'role': role, 'because': '承接前一项核对结果', 'change': f'核对进展到{role}',
                             'shot_ids': [f'S{j+1:02d}' for j in range(i*count//6, (i+1)*count//6)]}
                            for i, role in enumerate(roles)],
            'shots': [{'shot_id': f'S{i+1:02d}', 'start_seconds': i*seconds/count,
                       'end_seconds': (i+1)*seconds/count, 'scene': '咨询室桌前',
                       'participants': ['当事人'], 'blocking': '坐在桌左侧',
                       'action': '将通知与付款记录并排核对，最后把重复通知归入已核对文件夹。',
                       'emotion_and_performance': '眉头逐渐放松', 'camera': '固定中景',
                       'composition': '当事人在左侧中景，桌面账单在前景，后景为文件柜，下方留字幕空间',
                       'lighting': '左侧窗户散射日光为主光，柔和中性，右侧白墙反射补光',
                       'shot_size': '中景', 'camera_angle': '桌对面平视', 'camera_movement': '固定',
                       'start_frame': '当事人左手按住通知，付款记录在桌面右侧',
                       'end_frame': '当事人将已核对的通知放回桌面左侧',
                       'transition': '在放下通知时切到下一镜，末镜停留后结束',
                       'dialogue_mode': 'in_scene',
                       'dialogue_speaker': '当事人', 'dialogue': ending if i == count-1 else f'{kind}：第{i+1}项记录可以和账单逐一核对。',
                       'audio': '纸张轻响，句后停顿', 'narrative_purpose': '推进事实核对',
                       'continuity': '通知保持在桌面同一位置'} for i in range(count)]}
    return data


def enrich_review_report(report, payload):
    """Complete synthetic protocol fields without certifying real script semantics.

    Existing fields, including deliberately invalid test values, are preserved.
    The caller's report is not mutated; negative checks and issues remain intact.
    """
    result = copy.deepcopy(report)
    result.setdefault('candidate_sha256', payload['candidate_sha256'])
    result.setdefault('evidence_sha256', payload['evidence_sha256'])
    shot_audit, result_audit, character_audit, conflict_audit = [], [], [], []
    for script in payload['scripts']:
        kind = script['format_kind']
        for shot in script['shots']:
            citation = {'script': kind, 'shot_id': shot['shot_id'],
                        'field': 'action', 'quote': shot['action']}
            shot_audit.append({
                'script': kind, 'shot_id': shot['shot_id'], 'decision': 'passed',
                'action_evidence': [citation],
                'continuity_note': '测试用实际字段核对，不作真实语义认证',
                'voice_note': '仅核对测试剧本指令，未听音',
                'dialogue_action_note': '合成字段关联，不代表语义核准',
                'cross_field_evidence': {key: shot[key] for key in
                    ('dialogue', 'audio', 'emotion_and_performance', 'blocking', 'camera_angle',
                     'composition', 'start_frame', 'end_frame')},
                'cross_checks': {key: 'passed' for key in ('dialogue_action', 'voice_performance', 'spatial')},
            })
        last = script['shots'][-1]
        for target in ('resolution', 'ending'):
            result_audit.append({
                'script': kind, 'target': target, 'decision': 'passed',
                'action_evidence': [{'script': kind, 'shot_id': last['shot_id'],
                                     'field': 'action', 'quote': last['action']}],
                'explanation': '合成测试证据；非生产通过标准',
            })
        for character in script['characters']:
            name = character['name']
            spoken = [s for s in script['shots'] if s['dialogue_speaker'] == name and s['dialogue']]
            visible = [s for s in script['shots'] if name in s['participants']]
            character_audit.append({'script': kind, 'character_name': name, 'decision': 'passed',
                'spoken_shot_ids': [s['shot_id'] for s in spoken],
                'performance_arc_quote': character['performance_arc'],
                'dialogue_quotes': {s['shot_id']: s['dialogue'] for s in spoken},
                'voice_quote': spoken[0]['audio'] if spoken else '',
                'performance_quotes': {s['shot_id']: s['emotion_and_performance'] for s in visible[:1] + visible[-1:]},
                'assessment': '合成角色全对白及首末表演覆盖；不证明真实语义通过'})
        groups = {}
        for group, roles in {'opening': ('setup',), 'dispute': ('conflict', 'escalation'),
                             'turn': ('turn',), 'ending': ('resolution', 'closure')}.items():
            ids = {sid for beat in script['story_beats'] if beat['role'] in roles for sid in beat['shot_ids']}
            actual = [s for s in script['shots'] if s['shot_id'] in ids]
            refs = [{'script': kind, 'shot_id': actual[0]['shot_id'], 'field': 'action', 'quote': actual[0]['action']}]
            spoken = next((s for s in actual if s['dialogue']), None)
            if spoken:
                refs.append({'script': kind, 'shot_id': spoken['shot_id'], 'field': 'dialogue', 'quote': spoken['dialogue']})
            groups[group] = refs
        conflict_audit.append({'script': kind, 'decision': 'passed',
            **{key: '合成测试判断；非实际审核' for key in
               ('conflict_object', 'disputed_property', 'positions', 'turn', 'closure_scope')}, 'evidence': groups})
    result.setdefault('shot_audit', shot_audit)
    result.setdefault('result_audit', result_audit)
    result.setdefault('character_audit', character_audit)
    result.setdefault('conflict_audit', conflict_audit)
    return result


class FixtureClient:
    provider_name = 'test_fixture'
    model_name = 'synthetic_script_pair'

    def __init__(self, responses=None):
        self.responses = responses or [json.dumps(pair_payload(), ensure_ascii=False)]
        self.calls = []

    def chat_completion_tracked(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        if kwargs.get('caller') == 'pre_video_script_review':
            from src.trend_intelligence.script_pair import REVIEW_CHECKS
            # The final user message may be a format-retry instruction. Bind to
            # the original review payload, not to that instruction's text.
            payload = json.loads(next(message['content'] for message in messages
                                      if message['role'] == 'user'))
            report = {'checks': {key: True for key in REVIEW_CHECKS},
                      'issues': [], 'summary': 'Synthetic fixture passes.'}
            return json.dumps(enrich_review_report(report, payload), ensure_ascii=False)
        drafts = sum(call[1].get('caller') == 'pre_video_script_pair' for call in self.calls)
        response = self.responses[min(drafts-1, len(self.responses)-1)]
        # Bind only synthetic fixture references to each test's actual selected input IDs.
        # Production code never fills in missing model-authored attribution.
        data = json.loads(response)
        if isinstance(data, dict) and {'short', 'long'} <= set(data):
            payload = json.loads(messages[-1]['content'])
            sources = payload.get('source_evidence', [])
            known = {s['source_id'] for s in sources}
            if sources:
                for kind in ('short', 'long'):
                    for ref in data[kind].get('reference_usage', []):
                        if ref['source_id'] == 'labor-0' and ref['source_id'] not in known:
                            ref['source_id'] = sources[0]['source_id']
                            ref['evidence_ids'] = [sources[0]['expression_analysis']['evidence'][0]['id']]
            return json.dumps(data, ensure_ascii=False)
        return response
