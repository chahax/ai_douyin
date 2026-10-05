"""Versioned fact ownership, cut completion and explicit seating preconditions.

Mechanical checks deliberately do not classify natural-language action/camera
claims. Those sources remain in semantic_comparisons for independent review.
Independent surface v1 preserves slide as a typed operation, never as take/place/hold.
"""
from copy import deepcopy
import json
import hashlib
from scripts import creative_surface_action_core_v1 as legacy
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = 'creative_surface_action_v1'


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def build_action_plan_schema(context):
    schema = legacy.build_action_plan_schema(context)
    schema['properties']['schema']['enum'] = [VERSION]
    nullable_text = {'type': ['string', 'null'], 'minLength': 1}
    for character in context['static_visual_manifest']['characters']:
        state = schema['properties']['initial_state']['properties'][character['id']]
        state['properties']['facing'] = deepcopy(nullable_text)
        state['required'].append('facing')
    schema['properties']['spatial_contract'] = _object({'seats': {'type': 'array', 'items': _object({
        'seat_id': {'type': 'string', 'minLength': 1},
        'access_positions': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'uniqueItems': True},
        'required_facing': deepcopy(nullable_text)})}})
    schema['required'].append('spatial_contract')
    beat = schema['properties']['beats']['items']
    beat['properties']['cut_after_event_id'] = {'type': 'string', 'minLength': 1}
    beat['properties']['completion_condition'] = {'const': 'all_required_events_complete'}
    beat['required'] += ['cut_after_event_id', 'completion_condition']
    group = beat['properties']['groups']['items']
    operation = group['properties']['operations']['items']
    operation['properties']['kind']['enum'].append('face')
    operation['properties']['value'].update(minLength=1, description='move/sit/stand为动作后具体位置；take为手持位置；place为落点；pass为接收人物；gaze/face为目标；affect为表情')
    props = [p['id'] for p in context['static_visual_manifest']['props']]
    elements = [e['id'] for e in context['static_visual_manifest'].get('scene', {}).get('elements', [])]
    character_ids = [c['id'] for c in context['static_visual_manifest']['characters']]
    inherited_operation_constraints = deepcopy(operation.get('allOf', []))
    operation['allOf'] = [
        {'if': {'properties': {'kind': {'enum': ['take', 'place', 'pass']}}, 'required': ['kind']},
         'then': {'properties': {'target': {'enum': props, 'description': '被拿起/放下/交接的移动道具ID，不是桌子等落点'}}}},
        {'if': {'properties': {'kind': {'const': 'sit'}}, 'required': ['kind']},
         'then': {'properties': {'target': {'enum': elements, 'description': '固定可坐物ID；实际可坐性还需空间前提及语义审核'}}}},
        {'if': {'properties': {'kind': {'enum': ['move', 'gaze', 'affect', 'face', 'stand']}}, 'required': ['kind']},
         'then': {'properties': {'target': {'const': ''}}}},
        {'if': {'properties': {'kind': {'const': 'pass'}}, 'required': ['kind']},
         'then': {'properties': {'value': {'enum': character_ids}}}}]

    operation['allOf'].extend(inherited_operation_constraints)

    # Legacy schema reuses one text object. Detach fields before annotating
    # so action instructions do not become dialogue instructions (or ID rules).
    group['properties']['performance'] = deepcopy(group['properties']['performance'])
    beat['properties']['dialogue_performance'] = deepcopy(beat['properties']['dialogue_performance'])
    group['properties']['script_slot']['description'] = '源剧本段落：before在第一句前；during在第一句完整说完后、其余句前（不是说话期间）；after在全部对白后'
    group['properties']['performance']['description'] = '该动作组内表演；during组不得重演已说完对白。物理变化必须写operations，不得删除必要动作以修结构'
    beat['properties']['dialogue_performance']['description'] = '实际对白窗口内嘴部、呼吸、情绪表演；只有此字段承载说话中的表演'
    characters = [c['id'] for c in context['static_visual_manifest']['characters']]
    group['allOf'] = [
        {'if': {'properties': {'kind': {'const': 'hold'}}, 'required': ['kind']},
         'then': {'properties': {'operations': {'const': []}, 'hold_subject': {'enum': characters}}}},
        {'if': {'properties': {'kind': {'const': 'action'}}, 'required': ['kind']},
         'then': {'properties': {'hold_subject': {'const': ''}}}}]
    return schema



class PlanUnavailableError(CreativeContractError):
    """A terminal source/protocol boundary; never route to plan format repair."""
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail['code'] + ': ' + json.dumps(detail, ensure_ascii=False))


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _source_leaves(context):
    leaves = {}
    def visit(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key and '.' not in key:
                    visit(item, path + '.' + key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, path + '.' + str(i))
        elif isinstance(value, str) and value.strip():
            leaves[path] = value
        elif type(value) in (int, float, bool):
            leaves[path] = value
    for root in ('script', 'creative_brief'):
        if isinstance(context.get(root), dict):
            visit(context[root], root)
    return leaves


def build_unavailable_schema(context):
    paths = sorted(_source_leaves(context))
    # No source leaf means no grounded rejection is expressible. The empty enum
    # deliberately makes this branch invalid rather than admitting fake paths.
    return _object({'status': {'const': 'unsupported'},
        'code': {'enum': ['EXPRESSION_UNSUPPORTED', 'REQUIREMENT_CONFLICT']},
        'source_paths': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                         'items': {'type': 'string', 'enum': paths}},
        'reason': {'type': 'string', 'minLength': 1}})


def build_model_response_schema(context):
    """Transport schema only; internal plan validation stays strictly a plan."""
    return {'oneOf': [build_action_plan_schema(context), build_unavailable_schema(context)]}


def reject_unavailable_response(value, payload):
    """Return for normal plans; stop grounded or malformed explicit refusals.

    Hashes are computed from actual bound source, never accepted from the model.
    A grounded refusal is not proof the model's semantic judgment is correct;
    it stops for source/protocol review without rewriting the approved story.
    """
    if not isinstance(value, dict) or not (value.get('status') == 'unsupported'
            or value.get('code') in ('EXPRESSION_UNSUPPORTED', 'REQUIREMENT_CONFLICT')):
        return
    from jsonschema import Draft202012Validator
    source = {key: deepcopy(payload[key]) for key in ('script', 'creative_brief') if key in payload}
    errors = list(Draft202012Validator(build_unavailable_schema(payload)).iter_errors(value))
    if not isinstance(value.get('reason'), str) or not value.get('reason', '').strip():
        errors.append('reason must be nonempty')
    leaves = _source_leaves(payload)
    valid_paths = [path for path in value.get('source_paths', []) if isinstance(path, str) and path in leaves] if isinstance(value.get('source_paths'), list) else []
    detail = {'schema_version': 'plan_unavailable_receipt/v1',
        'code': 'PLAN_UNAVAILABLE_RESPONSE_INVALID' if errors else value['code'],
        'reason_code': 'REQUIRED_EVIDENCE_MISSING' if errors else value['code'],
        'status': 'blocked', 'unknown_disposition': 'blocked',
        'owner_stage': 'source_or_protocol_review', 'repair_owner': 'writer_or_protocol',
        'required_action': '核对源要求与协议能力；修改协议或重新审核简报，不能强制改写为计划',
        'reason': value.get('reason'), 'blocks_handoff': True, 'automatic_retry': False,
        'source_sha256': _digest(source), 'response_sha256': _digest(value),
        'source_refs': [{'path': path, 'value': deepcopy(leaves[path]), 'value_sha256': _digest(leaves[path])} for path in valid_paths],
        'validation_errors': [str(error.message) if hasattr(error, 'message') else str(error) for error in errors],
        'missing_evidence': ['valid script/creative_brief source paths and complete rejection'] if errors else [],
        'semantic_judgment_verified': False}
    raise PlanUnavailableError(detail)


def _unavailable_guidance(context):
    paths = sorted(_source_leaves(context or {}))
    return ('\n表达不兼容/硬需求冲突使用合法替代输出，优先于前面“只返回计划”的要求：'
            '{"status":"unsupported","code":"EXPRESSION_UNSUPPORTED或REQUIREMENT_CONFLICT",'
            '"source_paths":["真实script或creative_brief叶子路径"],"reason":"具体不可兼容的要求及原因"}。'
            '不得输出残缺计划、修改源剧情或编造来源。该响应停止本轮，不能作为已通过。'
            '引用路径从工具schema枚举中选择。当前有效来源数量：' + str(len(paths)))


def build_action_plan_prompt(context=None):
    return legacy.build_action_plan_prompt(context).replace(legacy.VERSION, VERSION) + '''
本版事实归属：initial_state和operations是物理状态唯一来源，performance/dialogue_performance仅补表演；camera仅描述连续拍摄方式，cut_reason仅解释叙事目的，二者不能设置另一个切点。所有自由文字仍须独立语义审核，格式通过不是内容通过。
每拍新增cut_after_event_id，取本拍最后完成的group.id或dialogue_N；completion_condition固定all_required_events_complete。所有计划动作、保持及锁定对白均须完成，程序在原拍时长末切走；不得绑定尚有后续任务的较早事件。
人物initial_state新增facing（身体朝向，不等于gaze；未知用null）。face操作target为空、value为新身体朝向。空间配置spatial_contract={seats:[{seat_id:固定可坐物ID,access_positions:[可坐侧具体位置],required_facing:坐前身体朝向或null}]}。位置与move.value必须使用一致的位置名，不能把椅背后列作可坐侧来迁就操作。坐下开始时，人物position已属于access_positions且facing已等于required_facing。移动、转身与坐下必须分组，前组结束才满足后组前提；缺少空间证据返回unknown，不自动补移动、不猜朝向。配置内容是否忠实剧本和实际布局仍由语义及图片审核。
操作参数必须按kind理解：take/place/pass的target永远是移动道具ID；place.value是落点描述或固定元素ID，不能把道具ID与桌子ID颠倒（如target=P02,value=E01表示把P02放到E01）。take.value是动作后的手持/佩戴位置；pass.value是接收者人物ID。sit.target是固定可坐物ID，sit.value是坐下后的明确位置，不能为空；move/stand.value同样是动作后位置。face.target为空、value为身体朝向（不是视线）。同一组操作在组结束生效，因此先转身再坐下必须拆成前后两组；不能用同组face补sit开始时的朝向。hold表示整个组保持已成立状态，operations严格为空；action的hold_subject严格为空。若保持某人时另一个人发生动作，该组是action，需要的动作后保持另建hold，不允许通过删除剧本必要动作修结构。
本协议不支持关键动作与对白同时发生；若已审剧本明确要求这种并行，必须返回EXPRESSION_UNSUPPORTED交上游，不能改剧情。细微嘴部/呼吸表演仍可伴随对白。
''' + _unavailable_guidance(context)


def _raise(code, path, message, *, unknown=False, missing=None):
    detail = {'code': code, 'path': path, 'status': 'unknown' if unknown else 'failed',
              'unknown_disposition': 'review_required' if unknown else None,
              'reason_code': code, 'owner_stage': 'action_plan',
              'required_action': '补齐来源或针对性复核后重新验证' if unknown else '修复源计划后重新编译与审核',
              'repair_owner': 'action_plan', 'message': message,
              'missing_evidence': missing or [], 'blocks_handoff': True}
    error = CreativeContractError(code + ': ' + json.dumps(detail, ensure_ascii=False))
    error.detail = detail
    raise error


def _validate_shape(plan, script, manifest):
    from jsonschema import Draft202012Validator
    # Preserve the actionable error code while also constraining provider output.
    if isinstance(plan, dict) and isinstance(plan.get('beats'), list):
        for bi, beat in enumerate(plan['beats']):
            for gi, group in enumerate(beat.get('groups', []) if isinstance(beat, dict) and isinstance(beat.get('groups'), list) else []):
                if isinstance(group, dict) and group.get('kind') == 'hold' and isinstance(group.get('operations'), list) and group['operations']:
                    _raise('PLAN_HOLD_HAS_ACTION', f'beats.{bi}.groups.{gi}.operations', '保持组不可包含状态操作')
    errors = list(Draft202012Validator(build_action_plan_schema({'script': script, 'static_visual_manifest': manifest})).iter_errors(plan))
    if errors:
        error = errors[0]
        parts = list(error.absolute_path)
        code = 'PLAN_SCHEMA_INVALID'
        if len(parts) == 7 and parts[0] == 'beats' and parts[2] == 'groups' and parts[4] == 'operations' and parts[6] == 'target':
            op = plan['beats'][parts[1]]['groups'][parts[3]]['operations'][parts[5]]
            if op.get('kind') == 'sit':
                code = 'PLAN_SEAT_ACCESS_INVALID'
        _raise(code, '.'.join(map(str, error.absolute_path)), error.message)
    # Only explicit source annotations can be mechanically classified; prose is
    # preserved for the reviewer, never interpreted through keyword matching.
    for index, beat in enumerate(script['beats']):
        for ri, requirement in enumerate(beat.get('execution_requirements', [])):
            if isinstance(requirement, dict) and requirement.get('kind') == 'simultaneous_dialogue_action':
                reject_unavailable_response({'status': 'unsupported', 'code': 'EXPRESSION_UNSUPPORTED',
                    'source_paths': [f'script.beats.{index}.execution_requirements.{ri}.kind'],
                    'reason': '当前串行契约不能表达源剧本要求的同说同动；请调整协议或重新审核源剧本'}, {'script': script})


def _projection(plan):
    projected = deepcopy(plan)
    projected['schema'] = legacy.VERSION
    projected.pop('spatial_contract')
    for state in projected['initial_state'].values():
        state.pop('facing', None)
    for row in projected['beats']:
        row.pop('cut_after_event_id')
        row.pop('completion_condition')
        for group in row['groups']:
            faces = [op for op in group['operations'] if op['kind'] == 'face']
            group['operations'] = [op for op in group['operations'] if op['kind'] != 'face']
            if faces:
                group['performance'] += '；程序派生身体朝向：' + json.dumps(faces, ensure_ascii=False)
    return projected


def check_sit_preconditions(plan, manifest):
    """Check explicit spatial evidence at group START, not dependent writes in it."""
    seats = {}
    elements = {item['id'] for item in manifest['scene']['elements']}
    for index, seat in enumerate(plan['spatial_contract']['seats']):
        if seat['seat_id'] in seats or seat['seat_id'] not in elements:
            _raise('PLAN_SEAT_ACCESS_INVALID', f'spatial_contract.seats.{index}', '座椅ID重复或不是固定场景元素')
        seats[seat['seat_id']] = seat
    state = deepcopy(plan['initial_state'])
    boundaries, checks = [], []
    for bi, beat in enumerate(plan['beats']):
        start = deepcopy(state)
        for gi, group in enumerate(beat['groups']):
            before = deepcopy(state)
            facing_actors = set()
            for oi, op in enumerate(group['operations']):
                path = f'beats.{bi}.groups.{gi}.operations.{oi}'
                actor, kind = op['actor'], op['kind']
                if kind == 'face':
                    if op['target'] or not op['value'].strip() or actor in facing_actors:
                        _raise('PLAN_FACING_INVALID', path, 'face须空target、非空value，同组不得重复修改人物身体朝向')
                    facing_actors.add(actor)
                    state[actor]['facing'] = op['value']
                elif kind == 'sit':
                    if op['target'] not in elements:
                        _raise('PLAN_SEAT_ACCESS_INVALID', path, '坐下目标未引用固定场景元素')
                    seat = seats.get(op['target'])
                    if seat is None or not seat['access_positions'] or seat['required_facing'] is None or before[actor]['facing'] is None:
                        _raise('PLAN_SEAT_ACCESS_UNKNOWN', path, '缺少可坐侧位置或身体朝向证据', unknown=True,
                               missing=['seat access_positions, required_facing, actor facing'])
                    if before[actor]['position'] not in seat['access_positions'] or before[actor]['facing'] != seat['required_facing']:
                        _raise('PLAN_SEAT_ACCESS_INVALID', path, '坐下开始前尚未到达可坐侧或身体朝向不满足；不能用同组移动/转身充当前提')
                    checks.append({'path': path, 'status': 'passed', 'seat': op['target'],
                                   'position': before[actor]['position'], 'facing': before[actor]['facing']})
                    state[actor]['posture'] = 'sitting'
                    state[actor]['position'] = op['value']
                elif kind in ('move', 'stand'):
                    state[actor]['position'] = op['value']
                    if kind == 'stand':
                        state[actor]['posture'] = 'standing'
                elif kind in ('gaze', 'affect'):
                    state[actor][kind] = op['value']
        boundaries.append({'beat_id': beat['beat_id'], 'start_facing': {c['id']: start[c['id']]['facing'] for c in manifest['characters']},
                           'end_facing': {c['id']: state[c['id']]['facing'] for c in manifest['characters']}})
    return boundaries, checks


def check_group_operation_preconditions(plan, manifest):
    """Read every operation against group START, commit independent writes at END.

    The legacy projector supports sequential operations inside an event. This
    action protocol instead promises simultaneous group-end effects. Never
    collapse an unexpressed take/place chain into a single boundary transition.
    """
    from scripts.creative_surface_state_v1 import _apply_operation
    characters = {c['id'] for c in manifest['characters']}
    props = {p['id'] for p in manifest['props']}
    elements = {e['id'] for e in manifest['scene']['elements']}
    state = deepcopy(plan['initial_state'])
    checks = []
    for bi, beat in enumerate(plan['beats']):
        for gi, group in enumerate(beat['groups']):
            before = deepcopy(state)
            accesses, changes = set(), []
            for oi, operation in enumerate(group['operations']):
                path = f'beats.{bi}.groups.{gi}.operations.{oi}'
                if operation['kind'] == 'face':
                    key = (operation['actor'], 'facing')
                    delta = [{'entity': key[0], 'field': key[1],
                              'from': before[key[0]][key[1]], 'to': operation['value']}]
                    reads = {key}
                else:
                    try:
                        delta, reads, _ = _apply_operation(operation, deepcopy(before),
                            characters, props, elements, path, surface_ids=manifest.get('surface_ids', []))
                    except CreativeContractError as exc:
                        _raise('PLAN_GROUP_PRECONDITION_INVALID', path, str(exc))
                if accesses & reads:
                    _raise('PLAN_GROUP_OPERATION_CONFLICT', path,
                           '同组操作读写同一状态字段；先后动作须由模型拆成独立组，不能合并中间状态')
                accesses |= reads
                changes.extend(delta)
                checks.append({'path': path, 'group_id': group['id'],
                               'preconditions_satisfied_at': 'group_start',
                               'effects_committed_at': 'group_end'})
            for change in changes:
                state[change['entity']][change['field']] = change['to']
    return checks


def check_cut_completion(raw, scheduled, timing, duration, path):
    events = []
    # The scheduler emits groups in source order and dialogue events between them.
    remaining = list(raw['groups'])
    gi = 0
    for event in scheduled['events']:
        if event['script_slot'] == 'dialogue_performance':
            event_id = 'dialogue_' + str(event['dialogue_index'])
        elif gi < len(remaining):
            event_id = remaining[gi]['id']
            gi += 1
        else:
            continue  # compiler-generated tail hold is not a source event
        events.append({'event_id': event_id, 'end': event['end']})
    anchor = next((e for e in events if e['event_id'] == raw['cut_after_event_id']), None)
    if anchor is None:
        _raise('PLAN_CUT_EVENT_UNKNOWN', path + '.cut_after_event_id', '切点锚不存在于本拍')
    unfinished = [e['event_id'] for e in events if e['end'] > anchor['end'] + 1e-8]
    if unfinished:
        _raise('PLAN_CUT_BEFORE_REQUIRED_EVENT', path + '.cut_after_event_id', '切点锚之后仍有必须完成的事件：' + ','.join(unfinished))
    return {'cut_after_event_id': anchor['event_id'], 'completion_condition': raw['completion_condition'],
            'required_events': events, 'completion_seconds': anchor['end'], 'execution_cut_seconds': duration}


def schedule_action_plan(plan, script, manifest):
    _validate_shape(plan, script, manifest)
    for bi, beat in enumerate(plan['beats']):
        for gi, group in enumerate(beat['groups']):
            if group['kind'] == 'hold' and group['operations']:
                _raise('PLAN_HOLD_HAS_ACTION', f'beats.{bi}.groups.{gi}.operations', '保持组不可隐藏任何状态操作，包括身体转向')
    boundaries, spatial_checks = check_sit_preconditions(plan, manifest)
    group_checks = check_group_operation_preconditions(plan, manifest)
    scheduled, report = legacy.schedule_action_plan(_projection(plan), script, manifest)
    report['schema'] = 'surface_action_plan_schedule_report/v1'
    report['source_schema'] = VERSION
    report['semantic_comparisons'] = []
    report['spatial_boundaries'] = boundaries
    report['spatial_checks'] = spatial_checks
    report['group_operation_checks'] = group_checks
    for bi, (raw, row, timing, beat) in enumerate(zip(plan['beats'], scheduled['beats'], report['beats'], script['beats'])):
        cut = check_cut_completion(raw, row, timing, beat['duration_seconds'], f'beats.{bi}')
        timing['cut_contract'] = cut
        # Human rationale stays as evidence; only this compiled clause controls time.
        row['cut_reason'] = (f"程序切点：{cut['execution_cut_seconds']:g}秒，{cut['cut_after_event_id']}完成且全部必需事件已完成。"
                             + '叙事目的（非执行指令）：' + raw['cut_reason'])
        report['semantic_comparisons'].append({'beat_id': raw['beat_id'],
            'operation_sources': [{'path': f'state_plan.beats.{bi}.groups.{gi}.operations', 'value': deepcopy(g['operations'])} for gi, g in enumerate(raw['groups'])],
            'prose_sources': [{'path': f'state_plan.beats.{bi}.{key}', 'value': raw[key]} for key in ('camera', 'cut_reason', 'dialogue_performance', 'composition')]
                + [{'path': f'state_plan.beats.{bi}.groups.{gi}.performance', 'value': g['performance']} for gi, g in enumerate(raw['groups'])],
            'cut_contract': cut, 'spatial_checks': [c for c in spatial_checks if c['path'].startswith(f'beats.{bi}.')],
            'semantic_status': 'not_checked'})
    return scheduled, report


def validate_action_plan(plan, script, manifest):
    schedule_action_plan(plan, script, manifest)


def compile_action_plan(plan, script, manifest):
    from scripts.creative_surface_state_bridge_v1 import compile_state_plan
    from scripts.creative_surface_state_v1 import legacy_visual_manifest
    from src.content_factory.creative_segmented_director import compile_execution_storyboard, validate_execution_contract
    scheduled, report = schedule_action_plan(plan, script, manifest)
    result = compile_state_plan(scheduled, script, manifest)
    names = {c['id']: c['name'] for c in manifest['characters']}
    for shot, boundary, timing in zip(result['shots'], report['spatial_boundaries'], report['beats']):
        for key, side in [('start_state', 'start_facing'), ('end_state', 'end_facing')]:
            state = json.loads(shot[key])
            for entity, facing in boundary[side].items():
                state[f'{entity}({names[entity]})']['facing'] = facing
            shot[key] = json.dumps(state, ensure_ascii=False, sort_keys=True)
        cut = timing['cut_contract']
        shot['visible_performance'] += f"\n唯一执行切点：{cut['execution_cut_seconds']:g}秒；{cut['cut_after_event_id']}及全部必需事件已完成。"
    result = compile_execution_storyboard(result, static_manifest=legacy_visual_manifest(manifest))
    validate_execution_contract(result)
    check_adjacent_state_transition(result)
    return result


def check_adjacent_state_transition(storyboard):
    """Verify compiled boundaries; this is not natural-language gaze checking."""
    shots = storyboard['shots']
    for index in range(1, len(shots)):
        try:
            previous = json.loads(shots[index - 1]['end_state'])
            current = json.loads(shots[index]['start_state'])
        except (TypeError, ValueError, KeyError):
            _raise('PLAN_BOUNDARY_STATE_CONFLICT', f'shots.{index}.start_state', '派生边界缺失或不是结构化状态')
        if previous != current:
            _raise('PLAN_BOUNDARY_STATE_CONFLICT', f'shots.{index}.start_state', '相邻派生首末态不一致')


def field_ownership():
    """Machine-readable P1 ownership; source-map artifacts may embed this."""
    return {
        'schema_version': 'action_field_ownership/v2', 'plan_version': VERSION,
        'owners': [
            {'field_paths': ['initial_state', 'beats.*.groups.*.operations'],
             'authority': 'action_plan', 'derived_fields': ['shots.*.start_state', 'shots.*.end_state']},
            {'field_paths': ['spatial_contract.seats'], 'authority': 'action_plan_spatial_contract',
             'derived_fields': ['scheduling_report.spatial_checks']},
            {'field_paths': ['beats.*.cut_after_event_id', 'beats.*.completion_condition'],
             'authority': 'action_plan_cut_contract', 'derived_fields': ['scheduling_report.beats.*.cut_contract']},
            {'field_paths': ['beats.*.camera', 'beats.*.cut_reason', 'beats.*.dialogue_performance',
                             'beats.*.groups.*.performance'],
             'authority': 'presentation_only', 'constraint': 'cannot_add_physical_facts_or_cut_time',
             'checker_kind': 'semantic', 'runtime_semantic_verification': 'required_not_proven_by_compiler'}]}


def checker_manifest():
    return {'schema_version': 'action_checker_manifest/v2', 'plan_version': VERSION, 'checkers': [
        {'checker': 'check_cut_completion', 'failure_codes': ['PLAN_CUT_BEFORE_REQUIRED_EVENT', 'PLAN_CUT_EVENT_UNKNOWN'],
         'kind': 'deterministic', 'status': 'implemented'},
        {'checker': 'check_sit_preconditions', 'failure_codes': ['PLAN_SEAT_ACCESS_INVALID', 'PLAN_SEAT_ACCESS_UNKNOWN', 'PLAN_FACING_INVALID'],
         'kind': 'deterministic_explicit_evidence_only', 'status': 'implemented'},
        {'checker': 'check_group_operation_preconditions',
         'failure_codes': ['PLAN_GROUP_PRECONDITION_INVALID', 'PLAN_GROUP_OPERATION_CONFLICT'],
         'kind': 'deterministic', 'status': 'implemented'},
        {'checker': 'check_adjacent_state_transition', 'failure_codes': ['PLAN_BOUNDARY_STATE_CONFLICT'],
         'kind': 'deterministic', 'status': 'implemented'},
        {'checker': 'check_gaze_text_consistency', 'failure_codes': ['PLAN_GAZE_TEXT_CONFLICT'],
         'kind': 'semantic', 'status': 'requires_independent_review'},
        {'checker': 'check_camera_cut_consistency', 'failure_codes': ['PLAN_CUT_TEXT_CONFLICT'],
         'kind': 'semantic', 'status': 'requires_independent_review'}]}
