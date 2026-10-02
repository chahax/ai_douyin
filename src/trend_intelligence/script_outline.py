"""Model-authored event planning before the full storyboard workflow."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

PROMPT_PATH = Path(__file__).parent / 'prompts/script_outline.md'


def build_outline_messages(workflow_messages, feedback, previous=None, *, reference_source_ids=()):
    if not isinstance(workflow_messages, list) or len(workflow_messages) != 2:
        raise ValueError('需要本项目保存的双剧本工作流请求')
    payload = json.loads(workflow_messages[1]['content'])
    sources = payload.get('source_evidence', [])
    ids = [s.get('source_id') for s in sources]
    if (len(ids) < 20 or any(not isinstance(sid, str) or not sid.strip() for sid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('提纲仍需至少20个独立来源')
    if any(s.get('independent_review', {}).get('decision') not in ('passed', 'passed_with_limits') for s in sources):
        raise ValueError('提纲只使用本轮已独立复核的来源请求')
    for source in sources:
        review, media = source['independent_review'], source.get('media_evidence', {})
        if (review.get('blocked_for_script_generation') is True
                or any(not isinstance(review.get(k), str) or not re.fullmatch(r'[a-f0-9]{64}', review[k])
                       for k in ('review_sha256', 'artifact_sha256', 'source_video_sha256'))
                or review['source_video_sha256'] != media.get('source_video_sha256')
                or review['artifact_sha256'] != media.get('visual', {}).get('artifact_sha256')):
            raise ValueError('来源审核身份与媒体证据不匹配或被阻塞')
    evidence = {k: copy.deepcopy(payload[k]) for k in ('source_evidence', 'expression_patterns',
        'account_positioning', 'short_seconds', 'long_seconds', 'expression_direction', 'production_constraints') if k in payload}
    if reference_source_ids:
        selected = list(reference_source_ids)
        if len(set(selected)) != len(selected) or any(sid not in ids for sid in selected):
            raise ValueError('提纲实际参考来源须来自这20条且不重复')
        evidence['source_overview'] = [{
            'source_id': s['source_id'], 'metric_kind': s.get('metric_kind'), 'metric_value': s.get('metric_value'),
            'core_message': copy.deepcopy(s.get('expression_analysis', {}).get('core_message')),
            'expression_modes': copy.deepcopy(s.get('expression_analysis', {}).get('expression_modes')),
            'emotion_analysis': copy.deepcopy(s.get('emotion_analysis', {'status': 'not_analyzed'})),
            'independent_review': copy.deepcopy(s['independent_review'])} for s in sources]
        evidence['source_evidence'] = [copy.deepcopy(s) for s in sources if s['source_id'] in selected]
        evidence['planning_evidence_scope'] = {
            'reviewed_source_count': len(sources), 'reference_source_ids': selected,
            'notice': '20条已分析来源及完整高值对照仍保留概览；本提纲只允许引用选定来源的完整现有证据。其他来源概览不是可引用原句，不省略所选源的任何证据。完整20源请求已另存并通过workflow_request_sha256追溯。'}
    if previous is not None:
        evidence['previous_outline'] = previous
    # Keep the current revision instructions after the rejected candidate.
    evidence['current_editor_feedback'] = feedback
    return [{'role': 'system', 'content': PROMPT_PATH.read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)}]


def validate_outline(outline, messages):
    payload = json.loads(messages[1]['content'])
    required = {'core_message', 'characters', 'short', 'long', 'reference_usage', 'legal_boundaries'}
    if not isinstance(outline, dict) or set(outline) != required:
        raise ValueError('提纲顶层须完整且仅含规定字段')
    for key in ('core_message', 'legal_boundaries'):
        if not isinstance(outline[key], str) or not outline[key].strip():
            raise ValueError(f'{key}须为非空文字')
    roles = outline['characters']
    if not isinstance(roles, list) or len(roles) != 2 or any(not isinstance(r, dict) for r in roles):
        raise ValueError('提纲须定义两个角色')
    names = [r.get('name') for r in roles]
    if len(set(names)) != 2 or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError('人物名须明确且不同')
    for role in roles:
        if set(role) != {'name', 'identity', 'wants', 'reason_not_immediately_agree'} or any(
                not isinstance(v, str) or not v.strip() for v in role.values()):
            raise ValueError('角色字段须完整且仅含规定文字')
    for kind, limits in (('short', (6, 9, 4, 15)), ('long', (16, 22, 3, 20))):
        version = outline[kind]
        if not isinstance(version, dict) or set(version) != {'title','goal','obstacle','stakes','ending','events'}:
            raise ValueError(f'{kind}版本字段无效')
        for key in ('title', 'goal', 'obstacle', 'stakes', 'ending'):
            if not isinstance(version.get(key), str) or not version[key].strip():
                raise ValueError(f'{kind}.{key}缺失')
        events = version.get('events')
        if not isinstance(events, list) or not limits[0] <= len(events) <= limits[1]:
            raise ValueError(f'{kind}事件数量须为{limits[0]}—{limits[1]}')
        for i, event in enumerate(events, 1):
            if not isinstance(event, dict) or event.get('event_id') != f'E{i:02d}':
                raise ValueError(f'{kind}事件编号须连续')
            if set(event) != {'event_id','duration_seconds','visible_action','changed_state','opponent_reaction','spoken_intent'}:
                raise ValueError('事件含未定义字段')
            duration = event.get('duration_seconds')
            if type(duration) is not int or not limits[2] <= duration <= limits[3]:
                raise ValueError(f'{kind}.{event.get("event_id")}时长无效')
            for key in ('visible_action', 'changed_state', 'opponent_reaction', 'spoken_intent'):
                if not isinstance(event.get(key), str) or not event[key].strip():
                    raise ValueError(f'{kind}.{event["event_id"]}.{key}缺失')
            if not any(event['spoken_intent'].startswith(n + '：') or event['spoken_intent'].startswith(n + ':') for n in names):
                raise ValueError('话语意图须以唯一已定义角色姓名和冒号开头')
            if sum(event['spoken_intent'].count(n + '：') + event['spoken_intent'].count(n + ':') for n in names) != 1:
                raise ValueError('事件只能指定一位说话人')
        if sum(e['duration_seconds'] for e in events) != payload[f'{kind}_seconds']:
            raise ValueError(f'{kind}事件总时长不匹配')
    sources = {s['source_id']: {e['id'] for e in s.get('expression_analysis', {}).get('evidence', [])}
               for s in payload['source_evidence']}
    refs = outline['reference_usage']
    if not isinstance(refs, list) or not refs:
        raise ValueError('实际来源引用不能为空')
    for ref in refs:
        if not isinstance(ref, dict) or ref.get('source_id') not in sources:
            raise ValueError('引用来源不存在')
        if set(ref) != {'source_id','evidence_ids','borrowed_expression','original_adaptation'}:
            raise ValueError('来源引用含未定义字段')
        ids = ref.get('evidence_ids')
        if (not isinstance(ids, list) or not ids or any(not isinstance(e,str) or e not in sources[ref['source_id']] for e in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('引用证据不存在')
        for key in ('borrowed_expression', 'original_adaptation'):
            if not isinstance(ref.get(key), str) or not ref[key].strip():
                raise ValueError('借鉴与原创改编必须分别说明')
    return outline


def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
