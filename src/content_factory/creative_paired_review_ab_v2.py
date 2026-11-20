"""Pure fixed-corpus A/B diagnostic, not a screenplay or production adapter.

The corpus is identical in both requests. Expectations stay outside wire
messages. A partitions native readings by role; B records each source once
with its role. Neither asks the model to maintain duplicate reference lists.
"""
from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from scripts.creative_call_evidence_v1 import digest
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request

VERSION = "creative_paired_review_ab/v2"
CORPUS_VERSION = VERSION + "/fixed_corpus"
REPRESENTATIONS = ("A", "B")
ROLES = ("support", "unresolved_counter", "transition", "context")
VERDICTS = ("supported", "contradicted", "undetermined")
MODES = ("intention", "conditional_promise", "completed_action", "observed_state",
         "attribution", "open_outcome", "unresolved_reading")
PARAMETERS = {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 16000}
RULE = (
    "这是固定原句小语料诊断，不是完整规划验收。逐case判断question是否由sources支持，不能补写副本、取放或放弃。"
    "supported=有据支持；contradicted=原句明确反驳；undetermined=材料不足或原句无法判读。实际片段允许有据说明相容，不预设必须失败。"
    "每个输入source恰好提交一次原生reading，包含1至3个当前问题必要的语义原子；每个quote必须是该source.text的非空逐字片段。"
    "先区别意图、条件、完成动作与观察状态；说要带走不等于已经带走，近手边不等于手持，明确副本或放弃意图应按原文承认。"
    "open_outcome是原文明示未来结果待定，可与supported并存；unresolved_reading仅指审查者无法确定原句含义，此时case必须undetermined。"
    "角色support为支持question，unresolved_counter为未解反证，transition为明示过渡，context为必读背景；有未解反证不能supported。"
    "state只填写原句明示的规范状态，否则null。holder.character_id=null只表示明确无人持有，不代表未知。"
    "location只登记场景ID，桌沿/手边等细部保留在literal_reading，不能把地点细节当成持有者；signature须区分物件与签署人。"
    "同物件、同时间、相反已完成状态须比较；不同物件或前后有明示过渡不自动矛盾。Schema即结构合同，无其他隐藏集合或状态规则。"
    "只提交指定工具结果，保留不同case各自结论；不宣布法律、完整剧本或创作质量通过。"
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _obj(properties, required=None, **extra):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False, **extra}


def _text(limit=300):
    return {"type": "string", "minLength": 1, "maxLength": limit, "pattern": r"\S"}


def _source(identifier, text, *, path=None):
    return {"id": identifier, "text": text, "native_document_path": path,
            "text_sha256": digest(text)}


def _at(document, path):
    current = document
    for part in path.split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def build_corpus(original_636_receipt):
    """Read actual request text only; prior model output/opinions are excluded."""
    receipt = original_636_receipt
    if receipt.get("ordinal") != 636 or digest(receipt["request"]) != receipt["request_sha256"]:
        raise ValueError("the exact recorded historical636 request identity is required")
    payload = json.loads(receipt["request"]["messages"][1]["content"])
    goal = payload["native_goal_document"]
    beats = goal.get("whole_plan", {}).get("beats", [])
    if len(beats) != 8 or beats[7].get("id") != "B8":
        raise ValueError("fixed historical corpus requires original B8")
    actors = [{"id": row["id"], "label": row["name"]} for row in goal["whole_plan"]["characters"]]
    props = {row["id"]: row["description"] for row in goal["whole_plan"]["props"]}
    scenes = [{"id": row["id"], "label": row["description"]} for row in goal["whole_plan"]["scenes"]]

    def actual(identifier, question, paths, object_ids):
        return {"id": identifier, "origin": "actual_native_quote_subset_not_a_new_plan", "question": question,
            "actors": deepcopy(actors), "objects": [{"id": key, "label": props[key]} for key in object_ids],
            "scenes": deepcopy(scenes), "times": ["source_time", "ending"],
            "sources": [_source("S" + str(i + 1), _at(goal, path), path=path) for i, path in enumerate(paths)]}

    cases = [actual("actual_b8_ending",
        "关于同一份协商解除提议的意图、已发生动作及最终归处，这些原句是否有据相容，无须补写未出现的副本或动作？",
        ["whole_plan.beats.7.response", "whole_plan.beats.7.visible_change", "whole_plan.ending.attempt_result",
         "whole_plan.ending.visible_consequence", "whole_plan.ending.emotional_landing"],
        ["prop_release_proposal", "prop_resign_form", "prop_schedule_confirm", "prop_insurance_print", "prop_apron"]),
        actual("actual_b6_baseline", "这些原句是否明确呈现经理已完成门店签字，而不只是答应以后签？",
        ["whole_plan.beats.5.response", "whole_plan.beats.5.visible_change"], ["prop_schedule_confirm", "prop_schedule"])]

    def synthetic(identifier, question, texts, objects=("paper",)):
        return {"id": identifier, "origin": "explicit_synthetic_control_not_native627",
            "question": question, "actors": [{"id": "a", "label": "甲"}, {"id": "b", "label": "乙"}],
            "objects": [{"id": key, "label": {"paper": "同一份纸质文件", "original": "文件原件", "copy": "文件复印件"}[key]} for key in objects],
            "scenes": [{"id": "room", "label": "同一办公室"}], "times": ["before", "after", "same_final_instant"],
            "sources": [_source("S" + str(i + 1), text) for i, text in enumerate(texts)]}

    cases += [synthetic("near_hand", "仅凭原句，是否能断言甲已经把文件持在手里？", ["文件在甲手边的桌面上。"]),
        synthetic("explicit_copy", "原件留在桌面、甲拿复印件离开，这些原句是否相容？",
            ["桌上明确有文件原件和它的复印件，分开摆放。", "原件留在桌面，甲拿起复印件离开，乙没动原件。"], ("original", "copy")),
        synthetic("abandoned_intention", "甲最后没带走文件，是否与前面的话在已有过渡下相容？",
            ["甲先说：这份文件我带走看。", "乙指出需要留存原件后，甲说：那我不带了。", "甲空手离开，文件一直留在桌面。"]),
        synthetic("opposite_final_state", "这些原句关于同一份文件的同一最终时刻，是否可以同时成立？",
            ["同一最终时刻，唯一的文件原件只由甲单独握在手中，乙没有接触。", "同一最终时刻，唯一的同一文件原件只由乙单独握在手中，甲没有接触。"]),
        synthetic("open_future_outcome", "本场已经取得书面记录、未来法律结果仍未定，这两点是否相容？",
            ["本场结束时，甲已经拿到由乙签署的书面记录。", "将来争议是否解决取决于后续协商与证据，本场不作结论，也不预写任何一方必胜。"])]
    return {"schema": CORPUS_VERSION, "source_receipt_sha256": digest(receipt),
        "native_goal_sha256": digest(goal), "actual_text_modified": False, "cases": cases}


def offline_expectations(corpus):
    """Evaluation metadata only; never an input to either model request."""
    return {case["id"]: {"kind": "non_gold_actual" if case["origin"].startswith("actual") else "synthetic_control",
        "allowed_verdicts": list(VERDICTS) if case["origin"].startswith("actual") else {
            "near_hand": ["undetermined"], "explicit_copy": ["supported"], "abandoned_intention": ["supported"],
            "opposite_final_state": ["contradicted"], "open_future_outcome": ["supported"]}[case["id"]]}
        for case in corpus["cases"]}


def _state_schema(case):
    objects = {"enum": [row["id"] for row in case["objects"]]}
    actors = {"enum": [row["id"] for row in case["actors"]]}
    common = {"object_id": objects, "time_id": {"enum": case["times"]}}
    return {"oneOf": [{"type": "null"},
        _obj({"kind": {"const": "holder"}, **deepcopy(common), "character_id": {"enum": [*actors["enum"], None]}}),
        _obj({"kind": {"const": "location"}, **deepcopy(common), "scene_id": {"enum": [row["id"] for row in case["scenes"]]}}),
        _obj({"kind": {"const": "signature"}, **deepcopy(common), "signer_id": actors,
              "signed": {"type": "boolean"}})]}


def _condition_not_supported(condition):
    return {"if": condition, "then": {"properties": {"verdict": {"enum": ["contradicted", "undetermined"]}}}}


def _nested_properties(path, condition):
    for key in reversed(path):
        condition = {"properties": {key: condition}}
    return condition


def build_schema(corpus, representation, *, context_sha256):
    if representation not in REPRESENTATIONS:
        raise ValueError("A or B representation required")
    records, definitions = {}, {}
    for case in corpus["cases"]:
        key = case["id"]; refs = [source["id"] for source in case["sources"]]
        definitions[key + "_atoms"] = {"type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
            "items": _obj({"quote": _text(300), "literal_reading": _text(220), "mode": {"enum": list(MODES)}, "state": _state_schema(case)})}
        atoms = {"$ref": "#/$defs/" + key + "_atoms"}
        fields = {"verdict": {"enum": list(VERDICTS)}, "comparison": _text(500)}
        conditions = []
        if representation == "A":
            group = _obj({ref: deepcopy(atoms) for ref in refs}, required=[])
            fields["groups"] = _obj({role: deepcopy(group) for role in ROLES}, allOf=[
                {"oneOf": [{"properties": {role: {"required": [ref]}}} for role in ROLES]} for ref in refs])
            conditions.append(_condition_not_supported(_nested_properties(["groups", "unresolved_counter"], {"minProperties": 1})))
            for role in ROLES:
                for ref in refs:
                    condition = {"required": [ref], **_nested_properties([ref],
                        {"contains": _nested_properties(["mode"], {"const": "unresolved_reading"})})}
                    conditions.append({"if": _nested_properties(["groups", role], condition),
                        "then": {"properties": {"verdict": {"const": "undetermined"}}}})
        else:
            fields["readings"] = _obj({ref: _obj({"role": {"enum": list(ROLES)}, "atoms": deepcopy(atoms)}) for ref in refs})
            for ref in refs:
                conditions.append(_condition_not_supported(_nested_properties(["readings", ref, "role"], {"const": "unresolved_counter"})))
                conditions.append({"if": _nested_properties(["readings", ref, "atoms"],
                    {"contains": _nested_properties(["mode"], {"const": "unresolved_reading"})}),
                    "then": {"properties": {"verdict": {"const": "undetermined"}}}})
        records[key] = _obj(fields, allOf=conditions)
    schema = _obj({"schema": {"const": VERSION}, "representation": {"const": representation},
        "corpus_sha256": {"const": digest(corpus)}, "context_sha256": {"const": context_sha256}, "cases": _obj(records)})
    schema["$defs"] = definitions
    Draft202012Validator.check_schema(schema)
    return schema


def _payload(corpus, representation):
    return {"representation": representation, "corpus": deepcopy(corpus)}


def prepare_request(profile, corpus, representation):
    director = profile["director"]
    parameters = director["parameters"]
    cap = profile.get("stage_parameters", {}).get("goal_audit", {}).get("max_completion_tokens", parameters["max_completion_tokens"])
    if (director["model"] != "deepseek-flash" or parameters.get("temperature") != .4
            or parameters.get("thinking") != "disabled" or cap != 16000):
        raise ValueError("fixed same-model comparison requires deepseek-flash")
    payload = _payload(corpus, representation); context = digest(payload)
    schema = build_schema(corpus, representation, context_sha256=context)
    layout = ("A将原生reading按support/unresolved_counter/transition/context四组放置；每source只在一组出现。"
              if representation == "A" else "B每source在readings中出现一次，自带role与atoms；不另写引用数组。")
    request = {"stage": "goal_audit", "role": "director", "model": "deepseek-flash",
        "messages": [{"role": "system", "content": RULE + layout}, {"role": "user", "content": _json(payload)}],
        "parameters": deepcopy(PARAMETERS), "structured_schema": schema,
        "input_provenance": {"schema": VERSION + "/provenance", "representation": representation,
            "corpus_sha256": digest(corpus), "source_receipt_sha256": corpus["source_receipt_sha256"],
            "native_goal_sha256": corpus["native_goal_sha256"], "context_sha256": context,
            "expectations_in_wire": False, "server_schema_guarantee": False}}
    return {"request": request, "request_sha256": digest(request), "wire": expected_wire_request(request),
        "context_sha256": context, "corpus_sha256": digest(corpus), "dispatch_performed": False,
        "sdk_max_retries": 0, "media_authorized": False}


def prepare_experiment(profile, original_636_receipt):
    corpus = build_corpus(original_636_receipt)
    return {"schema": VERSION + "/experiment", "corpus": corpus, "corpus_sha256": digest(corpus),
        "source_receipt_sha256": corpus["source_receipt_sha256"], "native_goal_sha256": corpus["native_goal_sha256"],
        "requests": {rep: prepare_request(profile, corpus, rep) for rep in REPRESENTATIONS},
        "offline_expectations": offline_expectations(corpus), "production_dispatch_eligible": False}


def validate_response(document, corpus, representation, *, context_sha256):
    if context_sha256 != digest(_payload(corpus, representation)):
        raise ValueError("current representation must bind the exact unchanged corpus")
    schema = build_schema(corpus, representation, context_sha256=context_sha256)
    errors = list(Draft202012Validator(schema).iter_errors(document))
    if errors:
        return {"valid": False, "accepted": False, "findings": [{"code": "AB_WIRE_SCHEMA_INVALID",
            "path": "/".join(map(str, error.absolute_path)), "reason": error.message[:800]} for error in errors],
            "creative_quality_passed": False, "native_response_rewritten": False}
    groups, quote_errors = {}, []
    for case in corpus["cases"]:
        native = document["cases"][case["id"]]
        readings = ({ref: {"role": role, "atoms": atoms} for role, rows in native["groups"].items() for ref, atoms in rows.items()}
                    if representation == "A" else native["readings"])
        original = {source["id"]: source["text"] for source in case["sources"]}
        for ref, reading in readings.items():
            for index, atom in enumerate(reading["atoms"]):
                if atom["quote"] not in original[ref]:
                    quote_errors.append({"code": "AB_QUOTE_NOT_IN_OWN_SOURCE", "case": case["id"], "source": ref, "atom_index": index})
        groups[case["id"]] = {role: [ref for ref, reading in readings.items() if reading["role"] == role] for role in ROLES}
    return {"valid": not quote_errors, "accepted": not quote_errors, "diagnostic_contract_only": True,
        "native_response_sha256": digest(document), "context_sha256": context_sha256, "corpus_sha256": digest(corpus),
        "case_verdicts": {key: value["verdict"] for key, value in document["cases"].items()},
        "compiled_reference_groups": groups, "compiled_groups_are_native_response": False,
        "findings": quote_errors, "creative_quality_passed": False, "native_response_rewritten": False,
        "all_cases_settled": all(value["verdict"] != "undetermined" for value in document["cases"].values())}
