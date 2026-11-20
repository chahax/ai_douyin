"""Four pure, tiny interface cases; no story adoption, SDK, claim or repair.

The experiment compares a representation bundle, not an individual keyword.
Every original response is validated unchanged. A bad previous example is
deliberately synthetic diagnostic material, never an accepted screenplay.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from scripts.creative_call_evidence_v1 import digest
from scripts import creative_m31_flash_role_clients_v1 as clients

VERSION = "creative_world_scene_array_probe_cases/v1"
OUTPUT_VERSION = "creative_array_probe_output/v1"
ACTORS = ["A", "B"]
BEATS = ["B01", "B02"]
PARAMETERS = {"temperature": .4, "thinking": "adaptive", "reasoning_effort": "medium", "max_completion_tokens": 16000}
REPRESENTATIONS = ("current_compound", "direct_common_items")
CONTEXT_VARIANTS = ("clean", "bad_previous")

SYSTEM = (
    "这是一个很小的原生工具参数类型诊断，不是剧本制作。只调用指定工具提交完整JSON对象。"
    "按工具Schema填写原生JSON类型：数组直接写[]，整数不加引号，null不能省略；不要用item对象包装。"
    "根据同一份toy_source写两拍、两人、一个柜台和一个红盒的简单场面。"
    "拍序必须B01、B02，场次序CX1、CX2；首场previous_context_id为null且relation为opening，"
    "第二场previous_context_id为CX1且relation为continuous。两拍均在S1，分别引用CX1、CX2，两人均在场。"
    "steps包含至少一个action和一个dialogue；action的speaker为空字符串，dialogue的speaker为A或B。"
    "ensemble的A和B各自对应表演数组，action_step_indexes只引用本拍实际action的零基整数索引；"
    "parallel_with只引用本拍实际action/dialogue的零基整数索引，不能重复关系。"
    "count固定为整数2；previous_run必须显式null；labels和index_grid逐值保留toy_source。"
    "如出现故意错误previous_example，它只用于测试错误历史上下文的影响，不能照抄它的类型错误。"
)


def _object(properties, required=None):
    return {"type": "object", "properties": properties,
        "required": list(properties) if required is None else list(required), "additionalProperties": False}


def _array(items, **limits):
    return {"type": "array", "items": items, **limits}


def build_output_schema(representation):
    if representation not in REPRESENTATIONS: raise ValueError("unknown diagnostic representation")
    compound = representation == "current_compound"
    integer = {"type": "integer", "minimum": 0}
    nonempty = {"type": "string", "minLength": 1}
    step = _object({"kind": {"enum": ["action", "dialogue"]},
        "speaker": {"type": "string", "enum": ["", *ACTORS]}, "text": deepcopy(nonempty)})
    if compound:
        step["allOf"] = [
            {"if": {"properties": {"kind": {"const": "action"}}}, "then": {"properties": {"speaker": {"const": ""}}}},
            {"if": {"properties": {"kind": {"const": "dialogue"}}}, "then": {"properties": {"speaker": {"enum": ACTORS}}}}]
    performance = _object({"action_step_indexes": _array(deepcopy(integer), minItems=1, uniqueItems=True),
        "expression": deepcopy(nonempty), "mode": {"enum": ["holds", "reacts", "acts"]}})
    performances = _array(performance, minItems=1)
    if compound:
        ensemble = {"type": "object", "propertyNames": {"enum": ACTORS},
            "additionalProperties": deepcopy(performances), "required": ACTORS, "minProperties": 2, "maxProperties": 2}
    else:
        ensemble = _object({actor: deepcopy(performances) for actor in ACTORS})
    beat = _object({"id": {"type": "string", "enum": BEATS}, "scene_id": {"const": "S1"},
        "scene_context_id": {"type": "string", "enum": ["CX1", "CX2"]},
        "steps": _array(step, minItems=2), "ensemble": ensemble,
        "parallel_with": _array(_object({"action_step_index": deepcopy(integer), "dialogue_step_index": deepcopy(integer)}), minItems=1, uniqueItems=True)})
    beats = {"type": "array", "minItems": 2, "maxItems": 2}
    if compound:
        beats["allOf"] = [{"items": beat}, {"prefixItems": [
            {"properties": {"id": {"const": bid}}} for bid in BEATS]}]
    else: beats["items"] = beat
    context = _object({"id": {"type": "string", "enum": ["CX1", "CX2"]}, "scene_id": {"const": "S1"},
        "previous_context_id": {"type": ["string", "null"]},
        "story_time": _object({"relation": {"enum": ["opening", "continuous"]}}),
        "present_character_ids": _array({"type": "string", "enum": ACTORS}, minItems=2, maxItems=2, uniqueItems=True)})
    contexts = {"type": "array", "minItems": 2, "maxItems": 2}
    if compound:
        contexts["allOf"] = [{"items": context}, {"prefixItems": [{"properties": {
            "previous_context_id": {"const": None}, "story_time": {"properties": {"relation": {"const": "opening"}}}}}],
            "items": {"properties": {"previous_context_id": {"const": "CX1"},
                "story_time": {"properties": {"relation": {"const": "continuous"}}}}}}]
    else: contexts["items"] = context
    schema = _object({"schema": {"const": OUTPUT_VERSION}, "title": deepcopy(nonempty),
        "count": {"type": "integer", "const": 2}, "previous_run": {"type": "null"},
        "labels": _array(deepcopy(nonempty), minItems=2, maxItems=2),
        "index_grid": _array(_array(deepcopy(integer), minItems=2, maxItems=2), minItems=2, maxItems=2),
        "scene_contexts": contexts, "beats": beats})
    Draft202012Validator.check_schema(schema)
    return deepcopy(schema)


def synthetic_control_output():
    """A labelled synthetic control for offline validation, not model output."""
    beats = []
    for i, bid in enumerate(BEATS):
        beats.append({"id": bid, "scene_id": "S1", "scene_context_id": f"CX{i+1}",
            "steps": [{"kind": "action", "speaker": "", "text": "A把红盒放在柜台上。" if i == 0 else "B把红盒移到柜台右侧。"},
                {"kind": "dialogue", "speaker": "B" if i == 0 else "A", "text": "先放这儿。" if i == 0 else "好，就放右边。"}],
            "ensemble": {actor: [{"action_step_indexes": [0], "expression": "看着红盒，神情自然。", "mode": "acts" if actor == ("A" if i == 0 else "B") else "reacts"}] for actor in ACTORS},
            "parallel_with": [{"action_step_index": 0, "dialogue_step_index": 1}]})
    return {"schema": OUTPUT_VERSION, "title": "柜台上的红盒", "count": 2, "previous_run": None,
        "labels": ["red", "counter"], "index_grid": [[0, 1], [2, 3]],
        "scene_contexts": [{"id": f"CX{i+1}", "scene_id": "S1", "previous_context_id": None if i == 0 else "CX1",
            "story_time": {"relation": "opening" if i == 0 else "continuous"}, "present_character_ids": ACTORS.copy()} for i in range(2)], "beats": beats}


def _payload(context_variant):
    source = {"purpose": "synthetic JSON tool-argument type diagnostic only; never a screenplay candidate",
        "characters": [{"id": "A", "role": "放盒子的人"}, {"id": "B", "role": "接话的人"}],
        "scene": {"id": "S1", "description": "普通房间的一张柜台；只有A、B和一个红盒。"},
        "beats": [{"id": "B01", "scene_context_id": "CX1", "event": "A放下红盒，B同时接话。"},
            {"id": "B02", "scene_context_id": "CX2", "event": "B把红盒移向柜台右侧，A同时接话。"}],
        "count": 2, "previous_run": None, "labels": ["red", "counter"], "index_grid": [[0, 1], [2, 3]]}
    value = {"toy_source": source}
    if context_variant == "bad_previous":
        bad = synthetic_control_output()
        bad["count"] = "2"; bad.pop("previous_run")
        bad["labels"] = {"item": bad["labels"]}; bad["index_grid"] = {"item": [{"item": ["0", "1"]}, {"item": ["2", "3"]}]}
        bad["scene_contexts"][0]["previous_context_id"] = ""
        for scene in bad["scene_contexts"]: scene["present_character_ids"] = {"item": scene["present_character_ids"]}
        for beat in bad["beats"]:
            beat["steps"] = {"item": beat["steps"]}; beat["parallel_with"] = {"item": beat["parallel_with"]}
            for actor in ACTORS:
                row = beat["ensemble"][actor][0]; row["action_step_indexes"] = {"item": ["0"]}
                beat["ensemble"][actor] = row
        value["deliberately_invalid_previous_example"] = {"warning": "故意构造的错误类型示例，不是原生服务回执或已采用正文；必须重写完整正确对象，不能修补或照抄。", "previous_example": bad}
    elif context_variant != "clean": raise ValueError("unknown context variant")
    return value


def build_cases(profile):
    writer = profile.get("writer", {})
    if (writer.get("model") != clients.WRITER_MODEL or writer.get("base_url") != clients.WRITER_BASE_URL
            or writer.get("parameters") != PARAMETERS):
        raise ValueError("exact current M3.1 writer profile and parameters required")
    cases = []
    for variant in CONTEXT_VARIANTS:
        payload = _payload(variant)
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]
        for representation in REPRESENTATIONS:
            schema = build_output_schema(representation)
            request = {"role": "writer", "stage": "complete_script", "model": clients.WRITER_MODEL,
                "messages": deepcopy(messages), "parameters": deepcopy(PARAMETERS), "structured_schema": schema}
            clients.expected_wire_request(request)
            label = ("compound" if representation == "current_compound" else "direct") + "_" + variant
            case = {"id": label, "schema": VERSION + "/case", "representation": representation, "tool_name": clients.TOOL_NAME,
                "context_variant": variant, "context_sha256": digest(payload), "messages_sha256": digest(messages),
                "schema_sha256": digest(schema), "request": request, "request_sha256": digest(request),
                "expected_output_schema": deepcopy(schema), "diagnostic_only": True, "toy_is_production_script": False,
                "native_output_must_remain_unchanged": True, "comparison_attribution": "representation_bundle_not_individual_keyword"}
            cases.append(case)
    return cases


def _pointer(parts):
    return "/" + "/".join(str(x).replace("~", "~0").replace("/", "~1") for x in parts) if parts else "/"


def validate(native, case):
    """Check the exact native object; never fill, unwrap or normalize values."""
    if (case.get("schema") != VERSION + "/case" or case.get("representation") not in REPRESENTATIONS
            or case.get("context_variant") not in CONTEXT_VARIANTS or case.get("diagnostic_only") is not True
            or digest(case["request"]) != case.get("request_sha256")
            or case["request"]["structured_schema"] != case.get("expected_output_schema")
            or digest(case["expected_output_schema"]) != case.get("schema_sha256")):
        raise ValueError("exact registered diagnostic case identity required")
    schema = build_output_schema(case["representation"])
    payload = _payload(case["context_variant"])
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]
    expected_request = {"role": "writer", "stage": "complete_script", "model": clients.WRITER_MODEL,
        "messages": messages, "parameters": deepcopy(PARAMETERS), "structured_schema": schema}
    expected_id = ("compound" if case["representation"] == "current_compound" else "direct") + "_" + case["context_variant"]
    if (schema != case["expected_output_schema"] or case["request"]["messages"] != messages
            or case["request"] != expected_request or case.get("id") != expected_id or case.get("tool_name") != clients.TOOL_NAME
            or digest(payload) != case.get("context_sha256") or digest(messages) != case.get("messages_sha256")):
        raise ValueError("diagnostic schema/source/context identity differs")
    clients.expected_wire_request(case["request"])
    findings = []
    def add(code, path, expected, actual):
        row = {"code": code, "path": path, "expected": deepcopy(expected), "actual": deepcopy(actual)}
        if row not in findings: findings.append(row)
    for error in Draft202012Validator(schema).iter_errors(native):
        if error.validator == "required" and type(error.instance) is dict:
            for key in error.validator_value:
                if key not in error.instance: add("SCHEMA_REQUIRED", _pointer([*error.absolute_path, key]), "required field", None)
        else: add("SCHEMA_" + error.validator.upper(), _pointer(error.absolute_path), error.validator_value, error.instance)
    if type(native) is dict:
        if type(native.get("count")) is not int or native.get("count") != 2:
            add("NATIVE_INTEGER", "/count", "JSON integer 2, excluding float and boolean", native.get("count"))
        grid = native.get("index_grid")
        if type(grid) is list:
            for i,row in enumerate(grid):
                if type(row) is list:
                    for j,value in enumerate(row):
                        if type(value) is not int:
                            add("NATIVE_INTEGER", f"/index_grid/{i}/{j}", "JSON integer, excluding float and boolean", value)
        for name in ("labels", "index_grid"):
            if native.get(name) != payload["toy_source"][name]: add("EXACT_SOURCE_VALUE", "/"+name, payload["toy_source"][name], native.get(name))
        beats, contexts = native.get("beats"), native.get("scene_contexts")
        if type(contexts) is list:
            for i,c in enumerate(contexts):
                if type(c) is not dict: continue
                if i < 2:
                    expected = {"id": f"CX{i+1}", "scene_id": "S1", "previous_context_id": None if i == 0 else "CX1"}
                    for key,value in expected.items():
                        if c.get(key) != value or key not in c: add("CONTEXT_SOURCE_BINDING", f"/scene_contexts/{i}/{key}", value, c.get(key))
                    relation = c.get("story_time", {}).get("relation") if type(c.get("story_time")) is dict else None
                    if relation != ("opening" if i == 0 else "continuous"): add("CONTEXT_RELATION", f"/scene_contexts/{i}/story_time/relation", "opening" if i == 0 else "continuous", relation)
                    people = c.get("present_character_ids")
                    if type(people) is list and all(type(person) is str for person in people) and set(people) != set(ACTORS): add("PARTICIPANT_COVERAGE", f"/scene_contexts/{i}/present_character_ids", ACTORS, people)
        if type(beats) is list:
            for i,b in enumerate(beats):
                if type(b) is not dict: continue
                if i < 2:
                    for key,value in {"id":BEATS[i],"scene_id":"S1","scene_context_id":f"CX{i+1}"}.items():
                        if b.get(key) != value: add("BEAT_SOURCE_BINDING", f"/beats/{i}/{key}", value, b.get(key))
                ensemble,steps = b.get("ensemble"),b.get("steps")
                if type(ensemble) is dict and set(ensemble) != set(ACTORS): add("ENSEMBLE_COVERAGE", f"/beats/{i}/ensemble", ACTORS, list(ensemble))
                if type(steps) is not list: continue
                actions=[j for j,s in enumerate(steps) if type(s) is dict and s.get("kind")=="action"]
                dialogue=[j for j,s in enumerate(steps) if type(s) is dict and s.get("kind")=="dialogue"]
                if not actions: add("ACTION_REQUIRED", f"/beats/{i}/steps", "at least one actual action", actions)
                if not dialogue: add("DIALOGUE_REQUIRED", f"/beats/{i}/steps", "at least one actual dialogue", dialogue)
                for j,s in enumerate(steps):
                    if type(s) is not dict: continue
                    expected="" if s.get("kind")=="action" else ACTORS
                    if s.get("kind")=="action" and s.get("speaker")!="" or s.get("kind")=="dialogue" and s.get("speaker") not in ACTORS:
                        add("STEP_SPEAKER", f"/beats/{i}/steps/{j}/speaker", expected, s.get("speaker"))
                if type(ensemble) is dict:
                    for actor,rows in ensemble.items():
                        if type(rows) is not list: continue
                        for j,row in enumerate(rows):
                            indexes=row.get("action_step_indexes") if type(row) is dict else None
                            if type(indexes) is list:
                                for k,index in enumerate(indexes):
                                    if type(index) is not int or index not in actions: add("ACTION_INDEX", f"/beats/{i}/ensemble/{actor}/{j}/action_step_indexes/{k}", actions, index)
                if type(b.get("parallel_with")) is list:
                    for j,row in enumerate(b["parallel_with"]):
                        if type(row) is not dict: continue
                        for key,choices in (("action_step_index",actions),("dialogue_step_index",dialogue)):
                            index=row.get(key)
                            if type(index) is not int or index not in choices: add("PARALLEL_INDEX", f"/beats/{i}/parallel_with/{j}/{key}", choices, index)
    return {"schema": VERSION + "/validation", "valid": not findings, "findings": findings,
        "case_id": case["id"], "request_sha256": case["request_sha256"], "native_output_sha256": digest(native),
        "native_document_modified": False, "diagnostic_only": True, "text_ready_for_director": False,
        "creative_quality_passed": False, "provider_calls": 0}
