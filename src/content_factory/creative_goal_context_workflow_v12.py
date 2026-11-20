"""Typed review ownership and bounded feedback, preserving frozen workflow v11.

Requests remain preparation only. Declared IDs and real G paths are compiled;
which natural-language actions contain a human voice remains a model judgment.
"""
from __future__ import annotations

from copy import deepcopy
import json
from .creative_goal_context_workflow_v8 import *
from . import creative_goal_context_workflow_v8 as prior
from . import creative_goal_context_workflow_v7 as audit_contexts
from . import creative_goal_drama_audit_contract_v10 as drama_contract
from . import creative_split_full_review_contract_v2 as split_reviews
from . import creative_goal_revision_feedback_v1 as feedback

VERSION = "creative_goal_context_workflow/v12"
SOURCE_AUDIT_VERSION = drama_contract.SOURCE_AUDIT_VERSION
DRAMA_AUDIT_VERSION = drama_contract.DRAMA_AUDIT_VERSION
BUNDLE_VERSION = drama_contract.BUNDLE_VERSION
_validate_planning_input = audit_contexts._validate_planning_input
_planning_authority_inputs = audit_contexts._planning_authority_inputs
CAST_SCOPE_RULE = (
    "实际可辨人声的说话者也属于制作演员范围：电话、对讲机、门外声音须与声明角色身份对应，"
    "不能只数画面内的人或角色数组；提及一个未出声的人不等于其实际参与，设备提示音也不等于人声。"
    "实际操作的关键道具、附带工具和容器须登记，提及或注视物件不自动等于操作。"
)
STAGE_RESPONSIBILITY_VERSION = "creative_planning_stage_responsibility/v2"
STAGE_RESPONSIBILITY_CONTRACT = {
    "schema": STAGE_RESPONSIBILITY_VERSION,
    "stage_owners": {
        "whole_plan": ["人物目的与关系阻力", "刺激、反应、策略变化和事件因果",
            "声明演员及实际可辨人声身份", "登记关键道具、附带工具、容器与场景",
            "已明确写出的状态和末拍/ending不能互相矛盾"],
        "native_opening_setup": ["开场站坐及人物位置按规划已明示initial_state原样提交",
            "道具当前holder、位置、支撑和容器状态", "同一完整规划SHA绑定的原生开场状态"],
        "complete_script_and_local_performance": ["逐拍可执行取放和操作顺序",
            "需要的物件朝向、拍照及具体机位", "对白刺激前中后的可读反应窗口"],
        "same_source_physical_review_and_compile": ["完整起态与正文的必要操作前提",
            "持有、位置、容器及跨拍状态连续", "引用、声明状态和可行时间的确定性条件"],
        "goal_drama_reviewer": ["从规划原句抽取自身scope_observations",
            "与规划全局声明集合比较主体ID", "用closed_scope_findings解释真实未登记、未知或状态矛盾"],
    },
    "planning_decision_policy": {
        "undeclared_actual_actor_voice_or_operated_prop": "fail；身份不确定时unknown，均阻断",
        "explicit_state_contradiction": "fail；不能归为后续待补细节",
        "missing_later_owned_detail_only": "不能单独判规划fail或unknown；后续阶段必须补全并复审",
        "owner_character_id": "只表示归属，不表示当前holder、位置、观看者或使用权限",
        "observation": "提及、注视或看见物件不等于实际操作；只按原句实际行为登记scope_observations",
        "registration_owner": "规划负责全局人物、道具和场景声明；规划没有逐拍scope_observations字段，该观察表由审查者生成",
        "review_self_consistency": "已匹配合法声明ID的观察不能判为未登记；审查漏填或错填观察表须拒绝审查合同，不能要求规划添加审查字段",
        "known_precondition": "确需当前持有或容器状态证据时查完整原生setup及正文；不能用owner代替",
        "immutable_sources": "来源与法律条件、用户目标和已明确初态不能为迁就正文而改写",
    },
    "scope_observation_definitions": {
        "audible_speakers": {"include": "原句中实际可辨人声及其说话者，画外/电话人声同样登记",
            "exclude": "无声签名、拍照、递物及其他默动作；提示音；只被提及而未出声的人",
            "identity_field": "declared_character_id：准确声明ID，未声明或不能确定对应时null"},
        "operated_props": {"include": "原句中被实际物理操作的物件及其声明ID，含取放、写入、开启及容器操作",
            "exclude": "仅提及、看见、注视、面对物件；所有权或背景存在本身",
            "identity_field": "declared_prop_id：准确声明ID，未声明或不能确定对应时null"},
        "evidence": "每项引用自身拍真实G原句；语义抽取由模型负责，Schema不证明分类正确或抽取完整",
    },
}
STAGE_RESPONSIBILITY_RULE = (
    "按stage_responsibility_contract区分阶段责任：规划交代目的、阻力、策略和事件因果，"
    "声明实际演员/人声、关键道具和场景，拒绝未登记操作物件及明示状态矛盾。"
    "开场道具holder、位置和容器状态由原生setup给出；人物已明确initial_state仍须冻结并原样提交。"
    "逐拍取放、操作朝向、具体拍照角度/机位及反应窗口由完整正文和局部表演补全，"
    "必要执行前提与跨拍连续由同源物理全文审查和编译检查。"
    "仅缺这些后续负责细节不能单独判规划fail或unknown，后续仍须补全并复审；"
    "已明确矛盾不能当作待补细节。owner_character_id只表示归属，不等于当前holder、位置、观看者或使用权限，"
    "不同所有者与观察者不能成为旁观失败依据，提及、注视或看见不等于操作。"
    "规划只负责全局声明集合，逐拍scope_observations由审查者抽取；不得把审查观察表漏填归责规划。"
)
GOAL_CHECK_CRITERIA = deepcopy(audit_contexts.GOAL_CHECK_CRITERIA)
GOAL_CHECK_CRITERIA["closed_production_scope"] = (
    "按stage_responsibility_contract核对完整演员/实际人声、关键道具/附带工具/容器和场景登记，"
    "逐拍与ending中已明确写出的状态不得矛盾；未来引入或派生物件须有叙事形成机制。"
    "仅缺已登记道具的开场holder/位置/容器状态或具体操作朝向、拍照角度，不单独判规划fail/unknown；"
    "这些仍由原生setup、完整正文、表演及同源物理全文审查补全核对。"
    "owner仅为归属，不等于当前持有、位置、观看者或使用权限；注视物件不等于操作。"
    "全局合法ID已对应实际观察就不是未登记；规划没有逐拍scope登记字段。"
)
DRAMA_AUDIT_RULE = (
    "只审当前完整未改目标与整片规划的戏剧和制作功能，按goal_check_criteria和stage_responsibility_contract逐项检查实际拍。"
    "核对已声明的在场/离开/返回、物件形成与已明确状态，以及末拍和ending是否一致；"
    "全部背景可见人影和实际可辨人声也计入制作范围，不能只数角色表。"
    "双方目的、阻力、情绪与策略需由具体刺激和回应推动；法律争议开放不替代场内的可见变化。"
    "R01只借表达机制，不照搬情节；用户功能目标不等于指定办理剧情或禁止胜负。"
    "先提交每拍scope_observations，再判closed_production_scope；只观察原句实际可辨说话者和实际被操作物件，"
    "引用当前goal真实G原句及精确声明ID；提及、注视、看见或面对物件不能作为实际操作的当然证据。"
    "未声明对象明确填null并判fail或unknown，不猜对应人物、不把null当闭合pass。"
    "production_scope_catalog只提供完整拍目录和声明集合，不能证明所有实际参与者已经登记。"
    "提交Schema中的全部goal_checks、scope_observations、closed_scope_findings与commitment_checks，不提交来源claim_checks或额外检查。"
    "closed_scope_findings只列真实失败或身份未知：未登记人声/物件须引用自身观察表的精确索引且declared ID为null；"
    "已对应全局合法ID的观察不能列为未登记，不能要求规划补审查者才有的逐拍表。"
    "明确状态矛盾按同一实体ID给出至少两项不同当前C/G原句；先核施事和代词指称，不能把不同人的手混为同一只手。"
    "goal_evidence_catalog提供精确G/C编号和当前原生规划路径，请到native_goal_document读取原句；"
    "每项先做counterexample_analysis，比较前后原句寻找信息未得先回应、未登记操作物件、已明确状态矛盾、"
    "重复一次性操作、无代价的改口和承诺超出实义等反例。未解决反证放counterevidence_refs，不能复述矛盾却pass。"
    "每项选足够且互不重复的真实G/C编号，范围限当前目录；scope_observations仍限自身拍G，不以任意固定引用数代替完整证据。"
    "pass的required_revision为空串且没有未解反证；fail指出完整新规划的功能缺口，不代写替代台词动作。"
    "当前职责内的不确定填unknown，缺后续阶段负责细节按职责合同处理。pass不证明人工审美或视频通过。"
) + CAST_SCOPE_RULE + STAGE_RESPONSIBILITY_RULE
COMMITMENT_REVIEW_RULE = (
    "goal_evidence_catalog包含原whole_plan的G和精确claims.text的C:<claim ID>。"
    "按creative_commitment_usage_catalog逐项提交commitment_checks，比较明示创作承诺与全部使用拍/结尾，"
    "再跨承诺、人物initial_state和其他拍寻找反例；来源支持成立不代表承诺相互兼容。"
    "checked_usages只用该使用位置的真实G，evidence_refs包含自身C；矛盾证据可以来自全片其他C或G。"
    "同一只手的持续占用、单次操作、已经说话后却称尚未开口、原生起态与终态的明示冲突属于规划职责。"
    "先核原文，不把缺具体机位当矛盾，不把owner当holder，不为协调矛盾代写新动作。"
    "无未解反例才pass，发现明确矛盾fail，必要意义无法确定unknown。"
)
SEMANTIC_CONSISTENCY_RULE = (
    "按consistency_evidence_catalog提交beat_intent_checks和每条实际对白的dialogue_role_checks。"
    "target_assertion_only仅是待兑现目标，actual_performed_step才是正文已演出证据；"
    "不得以event/trigger摘要填补正文未发生的诉求、让步促因、关键书面内容或拍序。"
    "逐句读字面命题、指称链、施事/受事及否定作用对象，再与实际说话者的目的比较。"
    "区分直接说话、转述或引用、自语；正常含蓄不自动失败，不能把她/你/我设为禁词。"
    "propositions是审查语法观察，不是替代台词；原文关键分句的quote必须精确，不能把字面‘你’偷换成自己。"
    "物件上‘有一行字’仅证明有字，不能证明规划指定的关键记录内容已写出。"
    "每项比较原始目标与全部实际E，明示倒退或未兑现fail；来自规划/起态的缺陷指向plan，"
    "正文失效指向script，未知阻断，不编写新版正文。"
)


def _add_stage_responsibility(payload, manifest):
    payload["stage_responsibility_contract"] = deepcopy(STAGE_RESPONSIBILITY_CONTRACT)
    measure, policy = contexts._measure(payload), manifest["context_policy"]
    if (measure["characters"] > policy["max_payload_characters"]
            or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]):
        raise ValueError("stage responsibility exceeds explicit context policy; no native source truncated")
    manifest.update(payload_identity=measure,
        stage_responsibility_contract_sha256=digest(payload["stage_responsibility_contract"]))
    manifest["field_manifest"].append({"path": "stage_responsibility_contract", "disposition": "included",
        "reason": "finite stage responsibilities; unchanged native response schema and source authority",
        "projected": contexts._measure(payload["stage_responsibility_contract"])})


def _mark_workflow(result):
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    result["request"]["input_provenance"]["workflow_version"] = VERSION
    result["manifest"]["workflow_version"] = VERSION
    result["request"]["input_provenance"]["context_manifest_sha256"] = digest(result["manifest"])
    result["wire"] = expected_wire_request(result["request"])
    result["request_sha256"] = digest(result["request"])
    return result


def prepare_goal_request(inputs, profile):
    projected_inputs = deepcopy(inputs)
    projection = None
    if "revision_diagnostics" in inputs:
        projection = feedback.project_goal_revision_feedback(inputs["revision_diagnostics"],
            original_diagnostics_path=inputs.get("goal_revision_feedback_evidence_path"))
        projected_inputs["revision_diagnostics"] = projection["projected_diagnostics"]
    # Projection must precede the unchanged context budget check. The full
    # native prior version, legal/user authority and reference are not projected.
    projected_inputs.pop("goal_revision_feedback_evidence_path", None)
    prepared = prior.prepare_goal_request(projected_inputs, profile)
    if projection is not None:
        prepared["manifest"].update(original_input_identity=contexts._measure(inputs),
            revision_feedback_projection=projection["projection_manifest"])
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    _add_stage_responsibility(payload, prepared["manifest"])
    prepared["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False)
    prepared["request"]["messages"][0]["content"] += CAST_SCOPE_RULE + STAGE_RESPONSIBILITY_RULE
    return _mark_workflow(prepared)


def prepare_goal_source_audit_request(inputs, profile, native_goal):
    return _mark_workflow(prior.prepare_goal_source_audit_request(inputs, profile, native_goal))


def _drama_context(inputs, native_goal):
    payload, manifest = audit_contexts._drama_context(inputs, native_goal)
    payload["goal_check_criteria"] = deepcopy(GOAL_CHECK_CRITERIA)
    payload["goal_evidence_catalog"] = drama_contract.build_evidence_manifest(native_goal)
    payload["creative_commitment_usage_catalog"] = drama_contract.build_commitment_usage_catalog(native_goal)
    payload["production_scope_catalog"] = drama_contract.build_production_scope_catalog(native_goal)
    _add_stage_responsibility(payload, manifest)
    measure, policy = contexts._measure(payload), manifest["context_policy"]
    if (measure["characters"] > policy["max_payload_characters"]
            or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]):
        raise ValueError("drama scope context exceeds explicit policy; no native source truncated")
    manifest.update(payload_identity=measure, audit_context_sha256=digest(payload),
                    scope_catalog_native_ids_only=True, scope_observations_are_native_model_output=True)
    manifest["field_manifest"].append({"path": "production_scope_catalog", "disposition": "included",
        "reason": "exact whole-plan beat coverage and declared ID sets; no prose speaker inference",
        "projected": contexts._measure(payload["production_scope_catalog"])})
    for row in manifest["field_manifest"]:
        if row["path"] == "goal_check_criteria":
            row.update(reason="current functional criteria with bounded planning responsibility",
                       projected=contexts._measure(payload["goal_check_criteria"]))
        if row["path"] == "goal_evidence_catalog":
            row.update(reason="exact original G and C paths; complete native source appears once",
                       projected=contexts._measure(payload["goal_evidence_catalog"]))
    manifest["field_manifest"].append({"path": "creative_commitment_usage_catalog", "disposition": "included",
        "reason": "finite explicit claim_refs usage coverage; no relevance inferred from prose",
        "projected": contexts._measure(payload["creative_commitment_usage_catalog"])})
    return payload, manifest


def build_goal_drama_audit_schema(native_goal, *, context_sha256):
    schema = drama_contract.build_drama_schema(native_goal, context_sha256=context_sha256)
    for beat in schema["properties"]["scope_observations"]["properties"].values():
        for table in ("audible_speakers", "operated_props"):
            definition = STAGE_RESPONSIBILITY_CONTRACT["scope_observation_definitions"][table]
            beat["properties"][table]["description"] = definition["include"] + "；不包括" + definition["exclude"]
    return schema


def prepare_goal_drama_audit_request(inputs, profile, native_goal):
    payload, manifest = _drama_context(inputs, native_goal)
    schema = build_goal_drama_audit_schema(native_goal, context_sha256=digest(payload))
    return _mark_workflow(audit_contexts._request(payload, schema, profile,
        DRAMA_AUDIT_RULE + COMMITMENT_REVIEW_RULE, manifest))


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
    """Only a complete current v10-drama/native-source bundle admits the author."""
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
    result = prior.prepare_full_review_part_request(inputs, profile, native_script, views, part)
    payload = json.loads(result["request"]["messages"][1]["content"])
    script = prior.validate_script_document(native_script, views, inputs["production_preferences"])["script"]
    table_contract = split_reviews.part_table_contract(part, script, views["brief"], views["plan"])
    payload["review_table_contract"] = table_contract
    payload["part_coverage_catalog"] = deepcopy(table_contract["coverage"])
    if part == "semantic":
        payload["consistency_evidence_catalog"] = split_reviews.build_consistency_evidence_catalog(
            script, views["plan"], goal_contract=views["goal"])
        result["request"]["messages"][0]["content"] += SEMANTIC_CONSISTENCY_RULE
    measure = contexts._measure(payload)
    policy = result["manifest"]["context_policy"]
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ValueError("consistency full review exceeds explicit context policy; no native source truncated")
    context_sha = digest(payload)
    result["request"]["structured_schema"] = split_reviews.build_part_schema(part, script,
        views["brief"], views["plan"], result["review_legal_context"], context_sha256=context_sha,
        goal_contract=views["goal"], opening_setup=views["opening_setup"])
    result["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False)
    result["manifest"].update(schema=VERSION + "/full_review_part_manifest", payload_identity=measure,
        part_context_sha256=context_sha, native_review_part_version=split_reviews.VERSION)
    for row in result["manifest"]["field_manifest"]:
        if row["path"] in ("review_table_contract", "part_coverage_catalog"):
            row.update(projected=contexts._measure(payload[row["path"]]),
                reason="current finite same-source native consistency coverage")
    if part == "semantic":
        result["manifest"]["field_manifest"].append({"path": "consistency_evidence_catalog", "disposition": "included",
            "reason": "target assertions compared with actual E evidence; model extracts semantic relations",
            "projected": contexts._measure(payload["consistency_evidence_catalog"])})
    result.update(part_context_sha256=context_sha, context_sha256=context_sha)
    result["request"]["input_provenance"].update(part_context_sha256=context_sha,
        native_review_part_version=split_reviews.VERSION)
    return _mark_workflow(result)
