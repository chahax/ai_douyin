"""Independent audit-scope repair, preserving frozen native workflow v8.

Requests remain preparation only. Declared IDs and real G paths are compiled;
which natural-language actions contain a human voice remains a model judgment.
"""
from __future__ import annotations

from copy import deepcopy
from .creative_goal_context_workflow_v8 import *
from . import creative_goal_context_workflow_v8 as prior
from . import creative_goal_context_workflow_v7 as audit_contexts
from . import creative_goal_drama_audit_contract_v8 as drama_contract

VERSION = "creative_goal_context_workflow/v9"
SOURCE_AUDIT_VERSION = drama_contract.SOURCE_AUDIT_VERSION
DRAMA_AUDIT_VERSION = drama_contract.DRAMA_AUDIT_VERSION
BUNDLE_VERSION = drama_contract.BUNDLE_VERSION
_validate_planning_input = audit_contexts._validate_planning_input
_planning_authority_inputs = audit_contexts._planning_authority_inputs
CAST_SCOPE_RULE = (
    "实际可辨人声的说话者也属于制作演员范围：电话、对讲机、门外声音须与声明角色身份对应，"
    "不能只数画面内的人或角色数组；提及一个未出声的人不等于其实际参与，设备提示音也不等于人声。"
    "已核实反例是一份两人规划只声明员工和班长，却用对讲机中主管的完整催问促成班长写字，"
    "设备只在腰间服装描述出现又被当成桌上物件；须检验此类声音身份、物件登记和跨拍前提，"
    "不要求保留该设备、说话内容或固定替代情节。"
)
DRAMA_AUDIT_RULE = audit_contexts.DRAMA_AUDIT_RULE.replace(
    "每项选足够且不超过8个G编号，不重复抄路径和引文。",
    "每项选足够且互不重复的真实G编号，范围限当前目录，不以任意固定引用数代替完整证据。"
) + CAST_SCOPE_RULE + (
    "先提交每拍scope_observations，再判closed_production_scope；"
    "逐项观察实际可辨说话者和实际被操作物件，引用当前goal真实G原句及精确声明ID，"
    "未声明对象明确填null并判fail或unknown，不猜对应人物、不把null当闭合pass。"
    "production_scope_catalog只提供完整拍目录和声明集合，不能当作所有实际参与者已经登记的证明。"
)


def _mark_workflow(result):
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result["request"]["input_provenance"]["workflow_version"] = VERSION
    result["manifest"]["workflow_version"] = VERSION
    result["request"]["input_provenance"]["context_manifest_sha256"] = digest(result["manifest"])
    result["wire"] = expected_wire_request(result["request"])
    result["request_sha256"] = digest(result["request"])
    return result


def prepare_goal_request(inputs, profile):
    prepared = prior.prepare_goal_request(inputs, profile)
    prepared["request"]["messages"][0]["content"] += CAST_SCOPE_RULE
    return _mark_workflow(prepared)


def prepare_goal_source_audit_request(inputs, profile, native_goal):
    return _mark_workflow(prior.prepare_goal_source_audit_request(inputs, profile, native_goal))


def _drama_context(inputs, native_goal):
    payload, manifest = audit_contexts._drama_context(inputs, native_goal)
    payload["production_scope_catalog"] = drama_contract.build_production_scope_catalog(native_goal)
    measure, policy = contexts._measure(payload), manifest["context_policy"]
    if (measure["characters"] > policy["max_payload_characters"]
            or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]):
        raise ValueError("drama scope context exceeds explicit policy; no native source truncated")
    manifest.update(payload_identity=measure, audit_context_sha256=digest(payload),
                    scope_catalog_native_ids_only=True, scope_observations_are_native_model_output=True)
    manifest["field_manifest"].append({"path": "production_scope_catalog", "disposition": "included",
        "reason": "exact whole-plan beat coverage and declared ID sets; no prose speaker inference",
        "projected": contexts._measure(payload["production_scope_catalog"])})
    return payload, manifest


def build_goal_drama_audit_schema(native_goal, *, context_sha256):
    return drama_contract.build_drama_schema(native_goal, context_sha256=context_sha256)


def prepare_goal_drama_audit_request(inputs, profile, native_goal):
    payload, manifest = _drama_context(inputs, native_goal)
    schema = build_goal_drama_audit_schema(native_goal, context_sha256=digest(payload))
    return _mark_workflow(audit_contexts._request(payload, schema, profile, DRAMA_AUDIT_RULE, manifest))


def validate_goal_drama_audit(document, native_goal, *, context_sha256):
    return drama_contract.validate_drama(document, native_goal, context_sha256=context_sha256)


def build_goal_audit_bundle(native_source_audit, native_drama_audit):
    return drama_contract.build_bundle(native_source_audit, native_drama_audit)


def validate_goal_audit(bundle, native_goal, *, inputs):
    source_payload, _ = audit_contexts._source_context(inputs, native_goal)
    drama_payload, _ = _drama_context(inputs, native_goal)
    return drama_contract.validate_bundle(bundle, native_goal,
        source_context_sha256=digest(source_payload), drama_context_sha256=digest(drama_payload))


def prepare_opening_setup_request(inputs, profile, native_goal):
    return _mark_workflow(prior.prepare_opening_setup_request(inputs, profile, native_goal))


def prepare_script_request(inputs, profile, native_goal, native_goal_audit, *, opening_setup,
                           source_ids, legal_ids, user_constraint_ids):
    """Only a complete current v8-drama/native-source bundle admits the author."""
    actual_ids = origin_ids(audit_contexts._planning_authority_inputs(inputs))
    provided = {"source_ids": source_ids, "legal_ids": legal_ids, "user_constraint_ids": user_constraint_ids}
    if any(set(provided[key]) != set(actual_ids[key]) for key in actual_ids):
        raise ValueError("origin IDs differ from actual supplied source/legal/user context")
    audit_contexts._validate_planning_input(inputs, native_goal)
    views = compile_native_views(native_goal, opening_setup, **provided)
    audit = validate_goal_audit(native_goal_audit, views["goal"], inputs=inputs)
    if not audit["accepted"]:
        raise ValueError("both current native source and drama audits must pass; no author request prepared")
    maximum = inputs["production_preferences"].get("max_characters")
    if type(maximum) is not int or maximum < 1 or len(views["brief"]["characters"]) > maximum:
        raise ValueError("native whole plan violates explicit on-screen cast preference")
    payload_inputs = {**audit_contexts._planning_authority_inputs(inputs), "native_goal_document": views["goal"],
        "brief": views["brief"], "creative_scene_plan": views["plan"]}
    built = audit_contexts.prior._context("complete_script", payload_inputs)
    built["payload"]["native_opening_setup_document"] = deepcopy(views["opening_setup"])
    audit_contexts._append_native_setup_manifest(built["manifest"], built["payload"], views["opening_setup"])
    built["manifest"]["fact_projection"] = deepcopy(views["fact_projection"])
    built["manifest"]["native_goal_audit_bundle_version"] = BUNDLE_VERSION
    schema = windows.build_script_schema(views["brief"])
    beat_ids = [row["id"] for row in views["plan"]["beats"]]
    schema["properties"]["beats"]["minItems"] = len(beat_ids)
    schema["properties"]["beats"]["maxItems"] = len(beat_ids)
    schema["properties"]["beats"]["items"]["properties"]["id"] = {"enum": beat_ids}
    result = audit_contexts.prior._request("complete_script", built["payload"], schema,
        "writer", profile, AUTHOR_RULE, built["manifest"])
    result["views"] = views
    result["goal_audit_sha256"] = digest(native_goal_audit)
    result["request"]["input_provenance"].update(goal_audit_sha256=digest(native_goal_audit),
        native_source_audit_sha256=digest(native_goal_audit["native_source_audit"]),
        native_drama_audit_sha256=digest(native_goal_audit["native_drama_audit"]),
        native_goal_audit_bundle_version=BUNDLE_VERSION,
        native_opening_setup_sha256=digest(views["opening_setup"]), native_goal_sha256=digest(native_goal))
    result["native_opening_setup_sha256"] = digest(views["opening_setup"])
    return _mark_workflow(result)


def prepare_full_review_part_request(inputs, profile, native_script, views, part):
    return _mark_workflow(prior.prepare_full_review_part_request(inputs, profile, native_script, views, part))
