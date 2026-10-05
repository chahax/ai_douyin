"""Bounded replacements of an existing plan; never approves the merged content."""
from copy import deepcopy
import hashlib
import json
import math
import re
from .creative_workflow_contract import CreativeContractError

PROTECTED = frozenset({"schema", "beat_id", "dialogue", "speaker", "script"})
MAX_PATCHES = 32

def plan_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

def can_patch_plan(value):
    """False means full reconstruction may be necessary, not permission to call it."""
    if not isinstance(value, dict) or not isinstance(value.get("schema"), str) or not value["schema"]:
        return False
    if not isinstance(value.get("initial_state"), dict) or not value["initial_state"]:
        return False
    beats = value.get("beats")
    if not isinstance(beats, list) or not beats:
        return False
    ids = []
    for beat in beats:
        if not isinstance(beat, dict) or not isinstance(beat.get("beat_id"), str) or not beat["beat_id"]:
            return False
        if "events" not in beat and "groups" not in beat:
            return False
        ids.append(beat["beat_id"])
    return len(ids) == len(set(ids))

def can_patch_contract_error(original, error):
    """V2 patches only schema defects, not physical/timing/content decisions."""
    if not can_patch_plan(original):
        return False
    if original.get('schema') == 'whole_film_action_plan_v2':
        return str(error).startswith('PLAN_SCHEMA_INVALID:')
    return True  # Preserve the historical v1 contract-repair route.


def _fail(message):
    raise CreativeContractError("plan_patch: " + message)

def _parts(path):
    if not isinstance(path, str) or not path or any(not p for p in path.split(".")):
        _fail("path必须为非空点分现存字段路径")
    parts = path.split(".")
    if len(parts) < 2 or parts[0] not in ("initial_state", "beats", "spatial_contract"):
        _fail("不得替换整稿或未授权根字段")
    if any(part in PROTECTED for part in parts):
        _fail("不得修改schema、beat_id、源对白或script")
    return parts

def _resolve(root, parts):
    node = root
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdecimal() and str(int(part)) == part and int(part) < len(node):
            node = node[int(part)]
        else:
            _fail("未知path: " + ".".join(parts))
    return node

def _protected_inside(value):
    if isinstance(value, dict):
        return any(k in PROTECTED or _protected_inside(v) for k,v in value.items())
    if isinstance(value, list):
        return any(_protected_inside(v) for v in value)
    return False

def _valid_json(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_valid_json(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k,str) and _valid_json(v) for k,v in value.items())
    return False

def apply_plan_patch(original, response, allowed_paths=None, *, target_schema=None):
    """Apply atomically to a copy. Caller MUST run the complete plan validator."""
    if not can_patch_plan(original):
        _fail("原稿骨架不完整，不能局部修复")
    if not isinstance(response, dict) or set(response) != {"source_sha256", "patches"}:
        _fail("响应只能含source_sha256和patches")
    if response["source_sha256"] != plan_digest(original):
        _fail("source_sha256不匹配原稿")
    patches = response["patches"]
    if not isinstance(patches,list) or not 1 <= len(patches) <= MAX_PATCHES:
        _fail("patches须为1至32个替换项")
    scopes = None if allowed_paths is None else [".".join(_parts(p)) for p in allowed_paths]
    prepared = []
    for patch in patches:
        if not isinstance(patch,dict) or set(patch) != {"path", "value"}:
            _fail("每项只能含path和value")
        parts = _parts(patch["path"])
        path = ".".join(parts)
        if parts[0] == "spatial_contract" and original.get("schema") != "whole_film_action_plan_v2":
            _fail("spatial_contract仅允许action_plan_v2修复")
        if scopes is not None and not any(path == s or path.startswith(s + ".") for s in scopes):
            _fail("path超出允许scope: " + path)
        before = _resolve(original, parts)
        if _protected_inside(before) or _protected_inside(patch["value"]):
            _fail("不得通过祖先替换或新值加入修改受保护字段")
        if not _valid_json(patch["value"]):
            _fail("value不是有限JSON值")
        for prior, _ in prepared:
            if parts == prior or parts[:len(prior)] == prior or prior[:len(parts)] == parts:
                _fail("重复或祖孙重叠patch")
        if original.get("schema") == "whole_film_action_plan_v2":
            from jsonschema import Draft202012Validator
            value_schema = _value_schema(_plan_target_schema(original, target_schema), parts)
            errors = list(Draft202012Validator(value_schema).iter_errors(patch["value"]))
            if errors:
                _fail("PLAN_PATCH_VALUE_SCHEMA: " + path + ": " + errors[0].message)
        prepared.append((parts, deepcopy(patch["value"])))
    merged = deepcopy(original)
    for parts, value in prepared:
        parent = _resolve(merged, parts[:-1])
        parent[int(parts[-1]) if isinstance(parent,list) else parts[-1]] = value
    if original.get("schema") == "whole_film_action_plan_v2" and plan_digest(merged) == plan_digest(original):
        _fail("PLAN_PATCH_NO_CHANGE: 修复未改变任何内容，停止重复请求")
    return merged

def build_patch_request(schema, context, error, original, allowed_paths=None):
    if not can_patch_plan(original):
        _fail("骨架不完整；由调用者按原修复预算决定一次完整重建")
    context = deepcopy(context)
    source_hash = plan_digest(original)
    # Remove only byte-equivalent semantic copies. Distinct prior drafts remain evidence.
    for key in ("plan_patch_base", "previous_draft"):
        if key in context and plan_digest(context[key]) == source_hash:
            del context[key]
    instruction = ("只修复原计划的局部错误，返回JSON：{source_sha256,patches:[{path,value}]}。"
        "source_sha256逐字复制请求根字段；若原阶段payload使用plan_patch_base，则取其对应source_sha256（亦受工具schema枚举绑定），不要自行猜hash。path使用现存字段点分路径，value替换该字段；不支持新增/删除path。"
        "只修改allowed_paths范围(若为null则initial_state/各拍内部)，其余原样保留。"
        "不得替换整稿、整拍或beats，不得修改schema、beat_id、源对白或script。"
        "不重复、不提交祖孙重叠patch，不输出解释或完整计划。最多32项。"
        "duration_seconds必须是JSON数值，例如4或2.5，不能是字符串、[4]或[\"4\"]。"
        "同一拍的动作/保持与插入的对白共享总时长；不要让动作/hold占满拍长后再加对白。"
        "修复后会合并并重新执行完整契约与内容审核，不能以改标签掩盖时间/状态矛盾。")
    return instruction, {"source_sha256": plan_digest(original), "validation_error": str(error),
        "target_schema": deepcopy(schema), "context": deepcopy(context), "original": deepcopy(original),
        "allowed_paths": deepcopy(allowed_paths), "timing_budget": timing_budget(context, original)}


def editable_paths(original, allowed_paths=None):
    """List exact existing mutable paths, omitting protected values and ancestors."""
    if not can_patch_plan(original):
        _fail("原稿骨架不完整，不能生成补丁schema")
    scopes = None if allowed_paths is None else [".".join(_parts(p)) for p in allowed_paths]
    paths = []
    def visit(value, parts):
        path = ".".join(parts)
        if len(parts) >= 2 and not any(p in PROTECTED for p in parts) and not _protected_inside(value):
            if scopes is None or any(path == scope or path.startswith(scope + ".") for scope in scopes):
                paths.append(path)
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in PROTECTED and isinstance(key,str) and key and "." not in key:
                    visit(child, parts + [key])
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, parts + [str(i)])
    roots = ["initial_state", "beats"]
    if original.get("schema") == "whole_film_action_plan_v2" and "spatial_contract" in original:
        roots.append("spatial_contract")
    for root in roots:
        visit(original[root], [root])
    return paths


def build_patch_schema(original, allowed_paths=None, target_schema=None):
    paths = editable_paths(original, allowed_paths)
    if not paths:
        _fail("允许范围内没有可编辑字段")
    if original.get("schema") == "whole_film_action_plan_v2":
        # A groups-array scope is the complete repair unit when an invalid hold
        # may need splitting. Expose that exact replacement rather than every
        # nested leaf; this also avoids repeating nested schemas in the tool.
        if allowed_paths and all(p.startswith('beats.') and p.endswith('.groups') and len(p.split('.')) == 3 for p in allowed_paths):
            paths = [p for p in paths if p in allowed_paths]
        return _typed_patch_schema(original, paths, target_schema)
    return {"type":"object", "additionalProperties":False,
        "properties": {"source_sha256":{"type":"string", "enum":[plan_digest(original)]},
            "patches":{"type":"array", "minItems":1, "maxItems":MAX_PATCHES,
                "items":{"type":"object", "additionalProperties":False,
                    "properties":{"path":{"type":"string", "enum":paths}, "value":{}},
                    "required":["path","value"]}}},
        "required":["source_sha256","patches"]}


def patch_recheck_scope(original, patch, *, target_schema=None):
    """Conservative dependency closure. It is a required scope, never approval."""
    apply_plan_patch(original, patch, target_schema=target_schema)  # Validate the same bound schema.
    first = len(original['beats'])
    roots = set()
    for row in patch['patches']:
        parts = row['path'].split('.')
        roots.add(parts[0])
        first = 0 if parts[0] != 'beats' else min(first, int(parts[1]))
    return {'schema': 'plan_dependency_recheck/v1',
            'source_sha256': plan_digest(original),
            'patch_sha256': plan_digest(patch),
            'changed_paths': [row['path'] for row in patch['patches']],
            'affected_beat_ids': [b['beat_id'] for b in original['beats'][first:]],
            'requires_full_compile': True,
            'requires_semantic_review': True,
            'requires_asset_recheck': bool(roots & {'initial_state', 'spatial_contract'}),
            'semantic_approval': False}



def _plan_target_schema(original, target_schema=None):
    """Use the protocol, never infer the target type from a corrupted old value."""
    if target_schema is not None:
        candidates = target_schema.get('oneOf', [target_schema])
        for candidate in candidates:
            if candidate.get('properties', {}).get('schema', {}).get('enum') == ['whole_film_action_plan_v2']:
                return candidate
        _fail('PLAN_PATCH_TARGET_SCHEMA: missing v2 plan branch')
    from .creative_action_plan_v2 import build_action_plan_schema
    # Entity identities are frozen by the source plan. Full production callers
    # may supply their manifest-bound schema for exact identity validation.
    characters = []
    props = []
    for entity, value in original['initial_state'].items():
        collection = props if isinstance(value, dict) and ('holder' in value or 'location' in value) else characters
        collection.append({'id': entity})
    seat_ids = [s.get('seat_id') for s in original.get('spatial_contract', {}).get('seats', []) if isinstance(s, dict) and isinstance(s.get('seat_id'), str)]
    return build_action_plan_schema({'static_visual_manifest': {'characters': characters, 'props': props, 'scene': {'elements': [{'id': sid} for sid in seat_ids]}},
                                    'script': {'beats': [{'id': b['beat_id']} for b in original['beats']]}})


def _value_schema(schema, parts):
    node = schema
    for part in parts:
        if node.get('type') == 'object' and part in node.get('properties', {}):
            node = node['properties'][part]
        elif node.get('type') == 'array' and part.isdecimal():
            node = node['items']
        else:
            _fail('PLAN_PATCH_TARGET_SCHEMA: no protocol field for ' + '.'.join(parts))
    return deepcopy(node)


def _typed_patch_schema(original, paths, target_schema=None):
    target = _plan_target_schema(original, target_schema)
    groups = {}
    for path in paths:
        value_schema = _value_schema(target, path.split('.'))
        key = plan_digest(value_schema)
        entry = groups.setdefault(key, {'schema': value_schema, 'paths': []})
        entry['paths'].append(path)
    # One branch per distinct value schema, not per path. This preserves exact
    # path/type coupling without replicating nested object schemas for each beat.
    branches = [{'type': 'object', 'additionalProperties': False,
        'properties': {'path': {'type': 'string', 'enum': row['paths']}, 'value': row['schema']},
        'required': ['path', 'value']} for row in groups.values()]
    return {'type': 'object', 'additionalProperties': False,
        'properties': {'source_sha256': {'type': 'string', 'enum': [plan_digest(original)]},
            'patches': {'type': 'array', 'minItems': 1, 'maxItems': MAX_PATCHES,
                        'items': {'oneOf': branches}}},
        'required': ['source_sha256', 'patches']}


def timing_budget(context, original):
    """Expose the scheduler's real shared limits, never retime model content."""
    from .creative_workflow_contract import _speech_units
    groups = {b['beat_id']: b.get('groups', []) for b in original.get('beats', [])}
    rows = []
    for beat in context.get('script', {}).get('beats', []):
        minimum = sum(max(1.0, _speech_units(line['text']) / 5.0) for line in beat.get('dialogue', []))
        natural = sum(max(1.0, _speech_units(line['text']) / 3.5 + 0.3) for line in beat.get('dialogue', []))
        actions = sum(g.get('duration_seconds', 0) for g in groups.get(beat['id'], []) if type(g.get('duration_seconds')) in (int, float))
        rows.append({'beat_id': beat['id'], 'shot_seconds': beat['duration_seconds'],
                     'minimum_dialogue_seconds': round(minimum, 6),
                     'preferred_dialogue_seconds': round(natural, 6),
                     'maximum_action_and_hold_seconds': round(beat['duration_seconds'] - minimum, 6),
                     'current_action_and_hold_seconds': actions})
    return rows


def repair_paths_for_error(original, error):
    """Use affected groups arrays: retain actions, allow reclassification/split."""
    if original.get('schema') != 'whole_film_action_plan_v2':
        return None
    if 'action_plan无法排入' in str(error):
        match = re.search(r'"beat_id"\s*:\s*"([^"\n]+)"', str(error))
        if match:
            paths = [f'beats.{bi}.groups' for bi, beat in enumerate(original['beats']) if beat['beat_id'] == match[1]]
            return paths or None
    if 'PLAN_HOLD_HAS_ACTION' not in str(error):
        return None
    paths = []
    for bi, beat in enumerate(original['beats']):
        for gi, group in enumerate(beat.get('groups', [])):
            if isinstance(group, dict) and group.get('kind') == 'hold' and group.get('operations'):
                path = f'beats.{bi}.groups'
                if path not in paths:
                    paths.append(path)
    return paths or None
