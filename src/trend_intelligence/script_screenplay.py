"""Validate model-authored story text and project it into the existing storyboard.

This module makes no model calls and grants no editorial approval. The caller
must retain/hash the original screenplay and bind its independent review before
compilation. A compilation freezes story text; it cannot establish that a new
photography description is semantically faithful or physically executable.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from .script_pair import BEAT_ROLES, CAMERA_MOVEMENTS, SHOT_SIZES, _has_narration


SCHEMA = 'script_screenplay/v1'
PRODUCTION_SCHEMA_V2 = 'screenplay_production/v2'
STORY_REVIEW_SCHEMA = 'screenplay_editorial_review/v2'
INTERPRETATION_FIELDS = {'presentation_mode', 'account_fit', 'source_pattern_rationale', 'protagonist'}
STORY_REVIEW_CHECKS = frozenset({'core_and_scope', 'conflict_and_turn', 'ending_complete',
                               'prop_continuity', 'speaker_and_no_narration', 'pace_and_duration',
                               'source_fidelity', 'legal_boundaries', 'version_value',
                               'dialogue_action_alignment', 'conflict_focus',
                               'character_delivery_grounded', 'spatial_alignment'})
CHARACTER_FIELDS = {'name', 'identity', 'appearance', 'wardrobe', 'voice', 'performance_arc'}
VERSION_FIELDS = {'title', 'premise', 'dramatic_question', 'goal', 'obstacle', 'stakes',
                  'resolution', 'legal_review_note', 'scene', 'spatial_layout', 'props',
                  'initial_state', 'shots', 'reference_usage'}
SHOT_FIELDS = {'shot_id', 'duration_seconds', 'beat', 'dialogue_speaker', 'dialogue',
               'action', 'end_state'}
REFERENCE_FIELDS = {'source_id', 'evidence_ids', 'borrowed_expression', 'adaptation', 'shot_ids'}
SCENE_DESIGN_FIELDS = {'composition', 'lighting', 'shot_size', 'camera_angle',
                       'camera_movement', 'blocking'}
CAMERA_FIELDS = ('shot_size', 'camera_angle', 'camera_movement')
PHOTOGRAPHY_SHOT_FIELDS = {'shot_id', 'composition', *CAMERA_FIELDS,
                          'emotion_and_performance', 'transition'}
PLAN_FIELDS = {'presentation_mode', 'account_fit', 'source_pattern_rationale', 'protagonist',
               'goal', 'obstacle', 'stakes', 'action_chain', 'turn', 'ending'}


def verify_story_review(screenplay_raw, report, *, workflow_sha, source_sha):
    """Check the saved independent-review protocol; never create an approval."""
    if (not isinstance(screenplay_raw, bytes)
            or not isinstance(report, dict) or report.get('schema') != STORY_REVIEW_SCHEMA
            or report.get('decision') != 'passed'
            or report.get('blocked_for_script_generation') is True
            or report.get('candidate_sha256') != hashlib.sha256(screenplay_raw).hexdigest()
            or report.get('workflow_request_sha256') != workflow_sha
            or report.get('source_evidence_sha256') != source_sha
            or report.get('unresolved_issues') != []
            or not isinstance(report.get('checks'), dict) or set(report['checks']) != STORY_REVIEW_CHECKS
            or any(value is not True for value in report['checks'].values())
            or not isinstance(report.get('shot_reviews'), list) or not report['shot_reviews']
            or any(not isinstance(row, dict) for row in report['shot_reviews'])
            or not isinstance(report.get('result_review'), dict) or not report['result_review']):
        raise ValueError('展开须有绑定当前故事、来源和原工作流的实际通过审核，缺失/退回/旧SHA不得沿用')
    # Keep byte identity and reject ambiguous objects even for direct callers.
    from .production_revision import parse_unique_json
    story = parse_unique_json(screenplay_raw)
    ids = [s['shot_id'] for s in story['version']['shots']]
    if [s.get('shot_id') for s in report['shot_reviews']] != ids:
        raise ValueError('故事审核必须按顺序完整覆盖所有镜头')
    for item, shot in zip(report['shot_reviews'], story['version']['shots']):
        if (item.get('decision') != 'passed' or not isinstance(item.get('action_quote'), str)
                or not item['action_quote'].strip() or item['action_quote'] not in shot['action']
                or not isinstance(item.get('finding'), str) or not item['finding'].strip()):
            raise ValueError('逐镜审核必须有当前动作原文和实际检查结论')
        # Full dialogue is intentional: a selective quote can omit the clause
        # that contradicts an action or changes the object under dispute.
        if (not isinstance(shot.get('dialogue'), str)
                or item.get('dialogue_quote') != shot['dialogue']
                or any(not isinstance(item.get(key), str) or not item[key].strip()
                       for key in ('dialogue_action_finding', 'conflict_focus_finding',
                                   'spatial_finding'))):
            raise ValueError('逐镜审核须保留完整对白并分别核对对白动作、争议焦点与人物空间；静默不能补造对白')
    result = report['result_review']
    actual = next((s for s in story['version']['shots'] if s['shot_id'] == result.get('shot_id')), None)
    if (result.get('decision') != 'passed' or not actual
            or not isinstance(result.get('action_quote'), str) or not result['action_quote'].strip()
            or result['action_quote'] not in actual['action']
            or not isinstance(result.get('finding'), str) or not result['finding'].strip()):
        raise ValueError('结果审核必须引用实际完成动作并有检查说明')
    _verify_story_cross_field_review(story, report)


def _verify_story_cross_field_review(story, report):
    """Require explicit cross-field coverage; this does not infer semantics."""
    version = story['version']
    scope = report.get('focus_review')
    spoken = [s for s in version['shots'] if s.get('dialogue', '').strip()]
    if (not isinstance(scope, dict) or scope.get('decision') != 'passed'
            or any(not isinstance(value, str) or not value.strip() or scope.get(key) != value
                   for key, value in (('core_quote', story.get('core_message')),
                                      ('question_quote', version.get('dramatic_question')),
                                      ('goal_quote', version.get('goal'))))
            or scope.get('spoken_shot_ids') != [s['shot_id'] for s in spoken]
            or not isinstance(scope.get('finding'), str) or not scope['finding'].strip()):
        raise ValueError('焦点审核须覆盖当前核心、问题、目标与全部实际对白，不能只概括金额或责任为同一件事')
    spatial = report.get('spatial_review')
    layout = version.get('spatial_layout')
    if (not isinstance(spatial, dict) or spatial.get('decision') != 'passed'
            or not isinstance(layout, str) or not layout.strip()
            or spatial.get('layout_quote') != layout
            or not isinstance(spatial.get('finding'), str) or not spatial['finding'].strip()):
        raise ValueError('空间审核须保留完整固定座位/视线轴原文并与各镜人物状态对照')
    characters = story.get('characters')
    rows = report.get('character_reviews')
    if (not isinstance(characters, list) or not characters or not isinstance(rows, list)
            or len(rows) != len(characters)
            or any(not isinstance(row, dict) for row in rows)
            or [row.get('name') for row in rows] != [c['name'] for c in characters]):
        raise ValueError('人物表现审核须按顺序覆盖全部实际角色')
    for row, character in zip(rows, characters):
        expected = [{'shot_id': s['shot_id'], 'quote': s['dialogue']} for s in spoken
                    if s['dialogue_speaker'] == character['name']]
        if (row.get('decision') != 'passed'
                or row.get('voice_quote') != character.get('voice')
                or row.get('performance_arc_quote') != character.get('performance_arc')
                or any(not isinstance(character.get(key), str) or not character[key].strip()
                       for key in ('voice', 'performance_arc'))
                or row.get('dialogue_quotes') != expected
                or not isinstance(row.get('finding'), str) or not row['finding'].strip()):
            raise ValueError('人物表现审核须对照完整声线/表现设定及其全部实际对白；不能以问号计数或其他角色台词代替')


def _fields(value, expected, label, *, optional=()):
    if (not isinstance(value, dict) or not expected <= set(value)
            or set(value) - expected - set(optional)):
        raise ValueError(f'{label}: fields must be exactly {sorted(expected)}'
                         + (f' with optional {sorted(optional)}' if optional else ''))


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label}: nonempty text required')
    return value


def _ids(value, available, label, *, allow_empty=False):
    if (not isinstance(value, list) or (not value and not allow_empty)
            or any(not isinstance(v, str) or v not in available for v in value)
            or len(value) != len(set(value))):
        raise ValueError(f'{label}: unknown, missing or duplicate IDs')
    return value


def _state(state, names, prop_ids, label):
    _fields(state, {'people', 'props'}, label)
    _fields(state['people'], set(names), label + '.people')
    _fields(state['props'], set(prop_ids), label + '.props')
    for category in ('people', 'props'):
        for key, value in state[category].items():
            _text(value, f'{label}.{category}.{key}')


def _definitions(characters, props):
    if not isinstance(characters, list) or len(characters) != 2:
        raise ValueError('characters: exactly two characters required')
    names = []
    for character in characters:
        _fields(character, CHARACTER_FIELDS, 'character')
        for key, value in character.items():
            _text(value, 'character.' + key)
        if any(_has_narration(character[k]) for k in ('name', 'identity', 'voice')):
            raise ValueError('character: narration roles/voices are forbidden')
        names.append(character['name'])
    if len(set(names)) != 2:
        raise ValueError('characters: duplicate names')
    if not isinstance(props, list):
        raise ValueError('props: list required')
    prop_ids = []
    for prop in props:
        _fields(prop, {'id', 'name'}, 'prop')
        _text(prop['id'], 'prop.id')
        _text(prop['name'], 'prop.name')
        prop_ids.append(prop['id'])
    if len(set(prop_ids)) != len(prop_ids):
        raise ValueError('props: duplicate IDs')
    return names, prop_ids


def _structure(data, kind, duration):
    if kind not in ('short', 'long'):
        raise ValueError('kind must be short or long')
    target = 45 if kind == 'short' else 180
    if type(duration) is not int or duration != target:
        raise ValueError(f'{kind}: duration must be {target} integer seconds')
    _fields(data, {'schema', 'core_message', 'characters', 'version'}, 'screenplay')
    if data['schema'] != SCHEMA:
        raise ValueError(f'screenplay.schema must be {SCHEMA}')
    _text(data['core_message'], 'core_message')
    version = data['version']
    _fields(version, VERSION_FIELDS, 'version')
    for key in VERSION_FIELDS - {'props', 'initial_state', 'shots', 'reference_usage'}:
        _text(version[key], 'version.' + key)
    names, prop_ids = _definitions(data['characters'], version['props'])
    _state(version['initial_state'], names, prop_ids, 'initial_state')
    low, high, minimum, maximum = (6, 9, 4, 15) if kind == 'short' else (9, 30, 3, 20)
    shots = version['shots']
    if not isinstance(shots, list) or not low <= len(shots) <= high:
        raise ValueError(f'{kind}: shot count must be {low}--{high}')
    beats, seconds, spoken = [], 0, 0
    for index, shot in enumerate(shots, 1):
        label = f'{kind}.S{index:02d}'
        _fields(shot, SHOT_FIELDS, label)
        if shot['shot_id'] != f'S{index:02d}':
            raise ValueError(f'{label}: shot IDs must be consecutive')
        length = shot['duration_seconds']
        if type(length) is not int or not minimum <= length <= maximum:
            raise ValueError(f'{label}: duration must be integer {minimum}--{maximum}')
        if shot['beat'] not in BEAT_ROLES:
            raise ValueError(f'{label}: unknown beat')
        beats.append(shot['beat'])
        speaker, dialogue = shot['dialogue_speaker'], shot['dialogue']
        if not isinstance(speaker, str) or not isinstance(dialogue, str):
            raise ValueError(f'{label}: speaker and dialogue must be text')
        if speaker == '' and dialogue == '':
            pass
        elif speaker not in names or not dialogue.strip():
            raise ValueError(f'{label}: use one defined speaker or two empty strings')
        if len(dialogue) > length * 5:
            raise ValueError(f'{label}: dialogue exceeds 5 characters per second')
        _text(shot['action'], label + '.action')
        if _has_narration(shot['action']):
            raise ValueError(f'{label}: narration is forbidden')
        _state(shot['end_state'], names, prop_ids, label + '.end_state')
        seconds += length
        spoken += len(dialogue)
    groups = [beat for i, beat in enumerate(beats) if i == 0 or beat != beats[i - 1]]
    if tuple(groups) != BEAT_ROLES:
        raise ValueError('beats: six roles must cover shots in contiguous ordered groups')
    if seconds != duration:
        raise ValueError(f'{kind}: total duration must be {duration}')
    if spoken > duration * 4:
        raise ValueError(f'{kind}: total dialogue exceeds 4 characters per second')
    # The final storyboard schema requires a nonempty closing_line equal to the
    # final dialogue. Silence is allowed in earlier shots, not a hidden late fix.
    ending = shots[-1]['dialogue']
    if not ending.strip() or ending.rstrip().endswith(('？', '?', '…', '...')) or any(
            word in ending for word in ('未完待续', '下集', '下期', '后续揭晓', '关注看后续')):
        raise ValueError('final dialogue must be a nonempty, closed ending')
    refs = version['reference_usage']
    if not isinstance(refs, list) or not refs:
        raise ValueError('reference_usage: nonempty list required')
    shot_ids = [shot['shot_id'] for shot in shots]
    for ref in refs:
        _fields(ref, REFERENCE_FIELDS, 'reference_usage')
        for field in ('source_id', 'borrowed_expression', 'adaptation'):
            _text(ref[field], 'reference_usage.' + field)
        ids = ref['evidence_ids']
        if (not isinstance(ids, list) or not ids or any(not isinstance(eid, str) or not eid for eid in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('reference_usage: evidence IDs must be nonempty and unique')
        _ids(ref['shot_ids'], shot_ids, 'reference_usage.shot_ids')
    return version, names, prop_ids


def validate_screenplay(data, kind, duration, source_evidence, reference_source_ids=()):
    """Validate one actual story without modifying it or granting semantic approval.

    ``source_evidence`` contains detailed source records, not overview summaries.
    The full 20-source/independent-review gate belongs to the calling workflow.
    State values are model-authored prose: staticness, action/state causality,
    legal accuracy and hidden extra dialogue still require independent review.
    """
    version, _, _ = _structure(data, kind, duration)
    if not isinstance(source_evidence, list) or not source_evidence:
        raise ValueError('source_evidence: detailed source list required')
    sources = {}
    for source in source_evidence:
        if not isinstance(source, dict):
            raise ValueError('source_evidence: each source must be an object')
        sid = _text(source.get('source_id'), 'source.source_id')
        if sid in sources:
            raise ValueError('source_evidence: duplicate source ID')
        sources[sid] = source
    if not isinstance(reference_source_ids, (list, tuple)):
        raise ValueError('reference_source_ids: list or tuple required')
    selected = _ids(list(reference_source_ids), sources, 'reference_source_ids', allow_empty=True)
    for ref in version['reference_usage']:
        sid = ref['source_id']
        if sid not in sources or (selected and sid not in selected):
            raise ValueError('reference_usage: source not in the detailed reference selection')
        source = sources[sid]
        analysis = source.get('expression_analysis')
        items = analysis.get('evidence') if isinstance(analysis, dict) else None
        if not isinstance(items, list) or not items:
            raise ValueError('reference_usage: source overview is not original evidence')
        evidence = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('source evidence: each record must be an object')
            eid = _text(item.get('id'), 'source evidence ID')
            if eid in evidence:
                raise ValueError('source evidence: duplicate ID')
            evidence[eid] = item
        _ids(ref['evidence_ids'], evidence, 'reference_usage.evidence_ids')
        media = source.get('media_evidence', {})
        source_duration = media.get('duration_seconds') if isinstance(media, dict) else None
        for eid in ref['evidence_ids']:
            item = evidence[eid]
            start, end = item.get('start_seconds'), item.get('end_seconds')
            if (item.get('channel') not in ('visual', 'asr')
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
                    or start < 0 or end < start
                    or (type(source_duration) in (int, float) and end > source_duration + .25)):
                raise ValueError('source evidence: invalid channel or time range')
            _text(item.get('text'), 'source evidence text')
    return data


def render_state(state, characters, props):
    """Render all original state strings in character/prop definition order."""
    names, prop_ids = _definitions(characters, props)
    _state(state, names, prop_ids, 'state')
    people = [f'{name}：{state["people"][name]}' for name in names]
    objects = [f'{prop["id"]}（{prop["name"]}）：{state["props"][prop["id"]]}' for prop in props]
    return '；'.join(people + objects)


def _camera(row, label):
    for field in CAMERA_FIELDS:
        _text(row[field], label + '.' + field)
    if row['shot_size'] not in SHOT_SIZES or row['camera_movement'] not in CAMERA_MOVEMENTS:
        raise ValueError(f'{label}: invalid shot size or camera movement')
    # An explicit fixed-lens instruction is not a zoom operation. Keep this
    # exemption narrow so a positive movement elsewhere is still rejected.
    camera_description = row['camera_angle'].replace('不变焦', '')
    if re.search(r'正反打|切到|切至|切镜|转场|拉近|拉远|变焦', camera_description):
        raise ValueError(f'{label}: camera_angle must describe one camera position')


def _expression(production, version, names):
    ids = [s['shot_id'] for s in version['shots']]
    beats = production['story_beats']
    if not isinstance(beats, list) or len(beats) != len(BEAT_ROLES):
        raise ValueError('story_beats: six ordered rows required')
    for role, row in zip(BEAT_ROLES, beats):
        _fields(row, {'role', 'because', 'change', 'shot_ids'}, 'story_beats')
        expected = [s['shot_id'] for s in version['shots'] if s['beat'] == role]
        if row['role'] != role or row['shot_ids'] != expected:
            raise ValueError('story_beats: cannot change frozen beat assignments')
        _text(row['because'], 'story_beats.because')
        _text(row['change'], 'story_beats.change')
    plan = production['expression_plan']
    _fields(plan, PLAN_FIELDS, 'expression_plan')
    for field in PLAN_FIELDS - {'action_chain', 'turn', 'ending'}:
        _text(plan[field], 'expression_plan.' + field)
    if plan['protagonist'] not in names:
        raise ValueError('expression_plan: protagonist must be a defined name')
    for field in ('goal', 'obstacle', 'stakes'):
        if plan[field] != version[field]:
            raise ValueError(f'expression_plan.{field}: cannot change frozen story text')
    chain = plan['action_chain']
    if not isinstance(chain, list) or len(chain) < 2:
        raise ValueError('expression_plan.action_chain: at least two rows required')
    changes = []
    for row in chain:
        _fields(row, {'shot_ids', 'visible_action', 'state_change'}, 'action_chain')
        _ids(row['shot_ids'], ids, 'action_chain.shot_ids')
        _text(row['visible_action'], 'action_chain.visible_action')
        changes.append(_text(row['state_change'], 'action_chain.state_change'))
    if len(set(changes)) != len(changes):
        raise ValueError('action_chain: duplicate state_change')
    for key, fields, required in (
            ('turn', {'visible_trigger', 'result'}, {s['shot_id'] for s in version['shots'] if s['beat'] == 'turn'}),
            ('ending', {'visible_result', 'core_answer'}, {ids[-1]})):
        part = plan[key]
        _fields(part, {'shot_ids', *fields}, 'expression_plan.' + key)
        _ids(part['shot_ids'], ids, 'expression_plan.' + key + '.shot_ids')
        if not set(part['shot_ids']) & required:
            raise ValueError(f'expression_plan.{key}: wrong frozen beat/ending shot')
        for field in fields:
            _text(part[field], f'expression_plan.{key}.{field}')


def _project_story_expression(data, interpretation):
    """Project literal reviewed facts; do not author a new explanation of them."""
    version = data['version']
    groups = [[shot for shot in version['shots'] if shot['beat'] == role] for role in BEAT_ROLES]
    actions = lambda group: '\n'.join(shot['action'] for shot in group)
    end = lambda group: render_state(group[-1]['end_state'], data['characters'], version['props'])
    chain, beats = [], []
    previous = None
    for role, group in zip(BEAT_ROLES, groups):
        original_actions = actions(group)
        ids = [shot['shot_id'] for shot in group]
        chain.append({'shot_ids': ids, 'visible_action': original_actions,
                      # Merely labeling an unchanged end pose as a new change is
                      # misleading. Include its literal action context as well;
                      # the editor still judges whether this advances the story.
                      'state_change': '动作：' + original_actions + '\n末态：' + end(group)})
        because = (version['premise'] if previous is None
                   else previous['dialogue'] or previous['action'])
        beats.append({'role': role, 'because': because, 'change': original_actions, 'shot_ids': ids})
        previous = group[-1]
    turn = groups[BEAT_ROLES.index('turn')]
    final = version['shots'][-1]
    plan = {**copy.deepcopy(interpretation),
            **{field: version[field] for field in ('goal', 'obstacle', 'stakes')},
            'action_chain': chain,
            'turn': {'shot_ids': [shot['shot_id'] for shot in turn],
                     'visible_trigger': actions(turn), 'result': end(turn)},
            'ending': {'shot_ids': [final['shot_id']],
                       'visible_result': '动作：' + final['action'] + '\n末态：' + end([final]),
                       'core_answer': version['resolution']}}
    return plan, beats


def _expand_production_v2(data, production, kind):
    """Turn limited photography data into the legacy compiler's internal shape."""
    _fields(production, {'schema', 'scene_design', 'shots', 'interpretation'}, 'production.v2')
    if production['schema'] != PRODUCTION_SCHEMA_V2:
        raise ValueError(f'production.schema must be {PRODUCTION_SCHEMA_V2}')
    version = data['version']
    design = production['scene_design']
    _fields(design, SCENE_DESIGN_FIELDS - {'blocking'}, 'production.v2.scene_design')
    for key, value in design.items():
        _text(value, 'production.v2.scene_design.' + key)
    _camera(design, 'production.v2.scene_design')
    if kind == 'short' and design['camera_movement'] != '固定':
        raise ValueError('short: shared camera must be fixed')
    interpretation = production['interpretation']
    _fields(interpretation, INTERPRETATION_FIELDS, 'production.v2.interpretation')
    for key, value in interpretation.items():
        _text(value, 'production.v2.interpretation.' + key)
    if interpretation['protagonist'] not in [c['name'] for c in data['characters']]:
        raise ValueError('production.v2.interpretation: protagonist must be a defined name')
    photography = production['shots']
    if not isinstance(photography, list) or len(photography) != len(version['shots']):
        raise ValueError('production.v2.shots: must cover exactly the frozen shots')
    rows = []
    for index, (story, camera) in enumerate(zip(version['shots'], photography)):
        optional = {'participants'} | (set(CAMERA_FIELDS) if kind == 'long' else set())
        _fields(camera, {'shot_id', 'composition', 'emotion_and_performance'},
                'production.v2.shot', optional=optional)
        if camera['shot_id'] != story['shot_id']:
            raise ValueError('production.v2.shots: reordering or renaming frozen shots is forbidden')
        for field in ('composition', 'emotion_and_performance'):
            _text(camera[field], 'production.v2.shot.' + field)
        final_state = render_state(story['end_state'], data['characters'], version['props'])
        transition = ('本镜结束状态直接作为下一镜开始状态：' + final_state
                      if index < len(photography) - 1 else
                      '在本镜既定时长内完成末态后自然结束，不追加静止时长：' + final_state)
        row = {**copy.deepcopy(camera), 'transition': transition}
        for field in CAMERA_FIELDS:
            row[field] = copy.deepcopy(camera[field] if field in camera else design[field])
        rows.append(row)
    plan, beats = _project_story_expression(data, interpretation)
    return {'scene_design': {**copy.deepcopy(design), 'blocking': version['spatial_layout']},
            'shots': rows, 'expression_plan': plan, 'story_beats': beats}


def compile_screenplay(data, production, kind):
    """Return one existing-schema version, preserving every mapped story string.

    External evidence and review/hash authorization must be checked by the
    caller. Original ``data`` remains the canonical complete story artifact.
    Production cannot supply actions, dialogue, state, scene or reference_usage.
    Long-shot participants may be a nonempty subset (the existing pair schema
    requires at least one visible character even for a silent shot).
    Short shots always contain both characters. Version 2 photography permits
    no per-short-shot camera, blocking, transition, action, plan or beat fields;
    those are derived solely from the shared design and reviewed story. The
    original unversioned production shape is retained for existing artifacts.
    """
    version, names, _ = _structure(data, kind, 45 if kind == 'short' else 180)
    if isinstance(production, dict) and 'schema' in production:
        production = _expand_production_v2(data, production, kind)
    _fields(production, {'scene_design', 'shots', 'expression_plan', 'story_beats'}, 'production')
    design = production['scene_design']
    _fields(design, SCENE_DESIGN_FIELDS, 'scene_design')
    for key, value in design.items():
        _text(value, 'scene_design.' + key)
    _camera(design, 'scene_design')
    if design['blocking'] != version['spatial_layout']:
        raise ValueError('scene_design.blocking: must equal frozen spatial_layout')
    if kind == 'short' and design['camera_movement'] != '固定':
        raise ValueError('short: shared camera must be fixed')
    photography = production['shots']
    if not isinstance(photography, list) or len(photography) != len(version['shots']):
        raise ValueError('production.shots: must cover exactly the frozen shots')
    _expression(production, version, names)
    output = {key: copy.deepcopy(version[key]) for key in
              ('title', 'premise', 'dramatic_question', 'resolution', 'legal_review_note', 'reference_usage')}
    output['closing_line'] = version['shots'][-1]['dialogue']
    output['characters'] = [{k: v for k, v in character.items() if k != 'voice'}
                            for character in copy.deepcopy(data['characters'])]
    output['expression_plan'] = copy.deepcopy(production['expression_plan'])
    output['story_beats'] = copy.deepcopy(production['story_beats'])
    output['shots'] = []
    voices = {c['name']: c['voice'] for c in data['characters']}
    previous = render_state(version['initial_state'], data['characters'], version['props'])
    cursor = 0
    for story, camera in zip(version['shots'], photography):
        required = PHOTOGRAPHY_SHOT_FIELDS
        optional = {'participants'}
        if kind == 'short':
            required = PHOTOGRAPHY_SHOT_FIELDS - set(CAMERA_FIELDS)
            optional |= set(CAMERA_FIELDS)
        _fields(camera, required, 'production.shot', optional=optional)
        if camera['shot_id'] != story['shot_id']:
            raise ValueError('production.shots: reordering or renaming frozen shots is forbidden')
        for field in ('composition', 'emotion_and_performance', 'transition'):
            _text(camera[field], 'production.shot.' + field)
        if _has_narration(camera['emotion_and_performance']):
            raise ValueError('production: narration is forbidden')
        if kind == 'short':
            for field in CAMERA_FIELDS:
                if field in camera and camera[field] not in (design[field], '同S01', '同 S01'):
                    raise ValueError(f'short.{story["shot_id"]}.{field}: conflicts with shared camera')
            settings = {field: design[field] for field in CAMERA_FIELDS}
        else:
            _camera(camera, 'production.shot')
            settings = {field: camera[field] for field in CAMERA_FIELDS}
        participants = copy.deepcopy(camera.get('participants', names))
        _ids(participants, names, 'production.shot.participants')
        if kind == 'short' and set(participants) != set(names):
            raise ValueError('short: both characters must remain in frame')
        speaker = story['dialogue_speaker']
        if speaker and speaker not in participants:
            raise ValueError('production: speaking character must be in frame')
        following = render_state(story['end_state'], data['characters'], version['props'])
        audio = (f'场内对白；说话人：{speaker}；声线：{voices[speaker]}。'
                 if speaker else '本镜无人说话。')
        output['shots'].append({
            'shot_id': story['shot_id'], 'start_seconds': cursor,
            'end_seconds': cursor + story['duration_seconds'],
            'scene': version['scene'], 'participants': participants,
            'composition': design['composition'] + '；本镜构图：' + camera['composition'],
            'lighting': design['lighting'], **settings,
            'blocking': version['spatial_layout'], 'start_frame': previous,
            'action': story['action'], 'end_frame': following,
            'emotion_and_performance': camera['emotion_and_performance'],
            'dialogue_mode': 'in_scene' if speaker else 'none',
            'dialogue_speaker': speaker, 'dialogue': story['dialogue'], 'audio': audio,
            'transition': camera['transition'], 'narrative_purpose': story['beat'],
            'continuity': '开始状态：' + previous + '；结束状态：' + following,
        })
        cursor += story['duration_seconds']
        previous = following
    return output
