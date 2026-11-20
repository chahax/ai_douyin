"""Explicit execution/narrative ownership around unchanged native workflow23.

No native document, source, law or review is repaired here. Only the confirmed
user requirements are projected by exact ID and original wording. Every stage
receives that same projection, including stages whose focused payload omits the
user contract after validating its authority. The original contract stays in the
caller's frozen inputs; reconstruction and hashes make projection auditable.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_goal_context_workflow_v23 as prior

VERSION = "creative_goal_context_workflow/v24"
OWNERSHIP_VERSION = VERSION + "/requirement_ownership_v1"
digest = prior.digest

# Exact confirmed rows, not a keyword classifier or a per-response omission list.
# New or changed requirements need an explicit reviewed ownership rule.
REQUIREMENTS = {
    "UC_COMPLETE_NATIVE": {
        "table": "constraints", "owner": "execution",
        "text": "交付完整可制作正文；内容返修由生成模型提交完整新稿，再全文复审。",
        "source_quote": "内容返修由生成模型提交完整新稿，再全文复审；不要手动回填动作或拼接新旧剧本。",
    },
    "UC_REFERENCE_MECHANISM": {
        "table": "constraints", "owner": "mixed",
        "text": "借鉴参考片的表达机制，参考全文实际进入对应创作请求，不照搬剧情。",
        "source_quote": "使用项目已有的参考片与教学分析，借鉴表达机制，不照搬剧情；确认参考确实进入实际模型请求。",
        "narrative_text": "借鉴参考片的表达机制，不照搬剧情。",
        "execution_text": "参考全文实际进入对应创作请求。",
    },
    "UC_NARRATIVE_ACTION": {
        "table": "constraints", "owner": "narrative",
        "text": "关键行为要传递信息或改变局势；不能靠无叙事作用的操作填时间。",
        "source_quote": "每镜明确新增信息、观察对象、刺激与反应、切镜理由，删除没有叙事作用的操作。",
    },
    "UC_AUTONOMOUS_NATIVE": {
        "table": "constraints", "owner": "execution",
        "text": "修改可复用流程后生成完整新稿，不依赖逐稿人工补动作或固定句数。",
        "source_quote": "应该是你定位问题分析原因然后分析流程为什么出现这种问题然后修改流程然后从新流程跑一份剧本。",
    },
    "UC_CONFIRMED_SUPERMARKET_DIRECTION": {
        "table": "constraints", "owner": "narrative",
        "text": "用户已确认“继续超市老员工方向，强化情绪交锋”。延续超市老员工被劝退、经理也有调任压力、员工坚持公司提出离职要写清、结尾保留她明天的班的故事方向；这不是采用当前未复审正文。",
        "source_quote": "继续超市老员工方向，强化情绪交锋",
    },
    "UG_EMOTION_CAUSAL_VISUAL": {
        "table": "audience_goals", "owner": "narrative",
        "text": "人物感受通过刺激、反应、策略和可见行为推进，事件具有因果。",
        "source_quote": "重点是情绪表达、事件因果和画面叙事，时长可以浮动。",
    },
    "UG_PLAIN_CHARACTER_SPEECH": {
        "table": "audience_goals", "owner": "narrative",
        "text": "对白直白自然，语言体现人物目的和双方立场，避免程序话术替代冲突。",
        "source_quote": "整体方向可以劳动合同不过可以剧情再白一点",
    },
    "UG_OPPONENT_RESPONSE": {
        "table": "audience_goals", "owner": "narrative",
        "text": "刺激会影响人物情绪，对手有自己的立场和回应。",
        "source_quote": "看到是个人原因的时候小林可以情绪扩散一下，人事也可以再公司角度回复",
    },
    "UG_CAUSAL_ENDING": {
        "table": "audience_goals", "owner": "narrative",
        "text": "结尾承接交锋，人物选择得到可观察回应或后果，并有情绪落脚点。",
        "source_quote": "这个结尾是不是太突兀了",
    },
    "UG_INTENSIFIED_EMOTIONAL_EXCHANGE": {
        "table": "audience_goals", "owner": "narrative",
        "text": "强化双方当场相互影响的情绪交锋：人物的目的、感受和对手回应互相推动，具体刺激引起反应与策略变化，压力和让步有现实代价，结尾的可见变化从此前交锋产生。保持人物自己的自然立场，不锁对白、句数或动作。",
        "source_quote": "继续超市老员工方向，强化情绪交锋",
    },
}
CONTRACT_KEYS = {"contract_version", "constraints", "audience_goals", "planning_rules", "division_of_work", "limitations"}
DERIVED_KEYS = {"execution_requirements", "requirement_ownership"}

OWNERSHIP_RULE = (
    "user_goal_contract.constraints和audience_goals是本次叙事要求；其中每个给定origin须由原生claim如实覆盖。"
    "execution_requirements及requirement_ownership记录执行与交付职责，不是剧情事实，不要求角色演出或叙事claim引用。"
    "原用户要求没有取消，执行是否做到由实际完整新稿、全文复审与请求证据核验，投影本身不证明做到。"
)
CHOICE_RULE = (
    "每个beat的claim_refs及ending.claim_refs都必须至少引用一条已声明kind=creative_choice的claim，"
    "明确该处虚构选择的依据；可以复用确实相关的创作选择，不强制每拍新增一条。"
    "用户目标、平台元数据、法律依据或推断不能独自充当虚构事件来源；类型符合仍须同源语义审查支持关系。"
)
LAW_SELECTION_RULE = (
    "完整法律目录是可按实际事件选择的依据，不是剧情覆盖清单；不要求全部登记为claim、逐条引用或各安排一拍。"
    "选择事件实际依赖的法律依据，保留其条件；已选verified_legal仍须单个L编号与给定原文逐字一致。"
)


class OwnershipError(ValueError):
    pass


def _derive_contract(original):
    if type(original) is not dict or set(original) - CONTRACT_KEYS:
        raise OwnershipError("original user contract has unmapped fields or is not an object")
    rows, seen, narrative, execution = [], set(), {key: [] for key in ("constraints", "audience_goals")}, []
    for table in ("constraints", "audience_goals"):
        values = original.get(table)
        if type(values) is not list:
            raise OwnershipError("original " + table + " must be a list")
        for index, row in enumerate(values):
            if type(row) is not dict or set(row) != {"id", "text", "source_quote"}:
                raise OwnershipError("exact native requirement row fields required")
            identifier = row["id"]
            rule = REQUIREMENTS.get(identifier) if type(identifier) is str else None
            if (rule is None or identifier in seen or rule["table"] != table
                    or row["text"] != rule["text"] or row["source_quote"] != rule["source_quote"]):
                raise OwnershipError("unmapped, duplicate or changed requirement: " + str(identifier))
            seen.add(identifier)
            entry = {"id": identifier, "source_table": table, "source_index": index,
                "original_row_sha256": digest(row), "owner": rule["owner"]}
            if rule["owner"] in ("narrative", "mixed"):
                selected = deepcopy(row)
                selected["text"] = rule.get("narrative_text", row["text"])
                narrative[table].append(selected)
            if rule["owner"] in ("execution", "mixed"):
                text = rule.get("execution_text", row["text"])
                execution.append({"id": identifier, "text": text, "source_quote": row["source_quote"],
                    "original_row_sha256": digest(row), "enforcement_owner": "execution_coordinator",
                    "enforcement_proven_by_projection": False})
            rows.append(entry)
    if seen != set(REQUIREMENTS):
        raise OwnershipError("confirmed requirement set incomplete: " + ",".join(sorted(set(REQUIREMENTS) - seen)))
    projected = deepcopy(original)
    projected.update(narrative)
    evidence = {"schema": OWNERSHIP_VERSION, "original_user_goal_contract_sha256": digest(original),
        "narrative_user_goal_contract_sha256": digest(projected), "execution_requirements_sha256": digest(execution),
        "mappings": rows, "exact_catalog_sha256": digest(REQUIREMENTS),
        "original_rows_reconstructible_from_exact_catalog": True,
        "original_contract_modified": False, "native_document_modified": False,
        "execution_compliance_proven": False, "human_approved": False}
    projected.update(execution_requirements=execution, requirement_ownership=evidence)
    return projected


def _original_contract(contract):
    """Verify a previous projection by exact reconstruction, never trust its flag."""
    if type(contract) is not dict or not DERIVED_KEYS <= set(contract):
        raise OwnershipError("partial ownership projection")
    evidence = contract["requirement_ownership"]
    if type(evidence) is not dict or type(evidence.get("mappings")) is not list:
        raise OwnershipError("malformed ownership evidence")
    original = {key: deepcopy(value) for key, value in contract.items() if key not in DERIVED_KEYS}
    for table in ("constraints", "audience_goals"):
        rows = [row for row in evidence["mappings"] if type(row) is dict and row.get("source_table") == table]
        if (any(type(row.get("source_index")) is not int or row.get("id") not in REQUIREMENTS for row in rows)
                or sorted(row["source_index"] for row in rows) != list(range(len(rows)))):
            raise OwnershipError("ownership source rows are not a complete indexed table")
        original[table] = [{"id": row["id"], "text": REQUIREMENTS[row["id"]]["text"],
            "source_quote": REQUIREMENTS[row["id"]]["source_quote"]}
            for row in sorted(rows, key=lambda row: row["source_index"])]
    if _derive_contract(original) != contract:
        raise OwnershipError("ownership projection differs from original requirements or derived hashes")
    return original


def project_inputs(inputs):
    """Return a verified, idempotent projection; never change caller/native data."""
    if type(inputs) is not dict or "user_goal_contract" not in inputs:
        raise OwnershipError("complete original user_goal_contract required")
    result = deepcopy(inputs)
    contract = inputs["user_goal_contract"]
    original = _original_contract(contract) if type(contract) is dict and DERIVED_KEYS & set(contract) else contract
    result["user_goal_contract"] = _derive_contract(original)
    return result


def ownership_evidence(inputs):
    return deepcopy(project_inputs(inputs)["user_goal_contract"]["requirement_ownership"])


def original_user_goal_contract(inputs):
    contract = project_inputs(inputs)["user_goal_contract"]
    return _original_contract(contract)


def _mark(prepared, inputs):
    evidence = ownership_evidence(inputs)
    prepared["manifest"].update(workflow_version=VERSION, requirement_ownership=evidence,
        structured_schema_sha256=digest(prepared["request"]["structured_schema"]),
        original_user_goal_contract_retained_in_local_inputs=True,
        narrative_projection_applied_before_context_build=True)
    prepared["request"]["input_provenance"].update(workflow_version=VERSION,
        requirement_ownership_sha256=digest(evidence),
        original_user_goal_contract_sha256=evidence["original_user_goal_contract_sha256"],
        narrative_user_goal_contract_sha256=evidence["narrative_user_goal_contract_sha256"],
        context_manifest_sha256=digest(prepared["manifest"]))
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    prepared["wire"] = expected_wire_request(prepared["request"])
    prepared["request_sha256"] = digest(prepared["request"])
    return prepared


def origin_ids(inputs):
    return prior.origin_ids(project_inputs(inputs))


def _planning_authority_inputs(inputs):
    return prior._planning_authority_inputs(project_inputs(inputs))


def _fixed_legal_context(inputs):
    return prior._fixed_legal_context(project_inputs(inputs))


def _validate_planning_input(inputs, native_goal):
    return prior._validate_planning_input(project_inputs(inputs), native_goal)


def build_goal_request_schema(inputs):
    schema = prior.build_goal_request_schema(project_inputs(inputs))
    whole = schema["properties"]["whole_plan"]["properties"]
    for refs in (whole["beats"]["items"]["properties"]["claim_refs"], whole["ending"]["properties"]["claim_refs"]):
        refs["description"] = "Must include at least one existing claim whose kind is creative_choice; exact references and semantic support remain locally/reviewer validated."
    schema["properties"]["claims"]["description"] = "Cover every narrative user origin; execution_requirements are coordinator obligations, not narrative claims. Legal origins are optional selections, not an all-law coverage checklist."
    return schema


def prepare_goal_request(inputs, profile):
    result = prior.prepare_goal_request(project_inputs(inputs), profile)
    result["request"]["structured_schema"] = build_goal_request_schema(inputs)
    result["request"]["messages"][0]["content"] += OWNERSHIP_RULE + CHOICE_RULE + LAW_SELECTION_RULE
    return _mark(result, inputs)


def diagnose_goal_document(document, *, inputs):
    return prior.diagnose_goal_document(document, inputs=project_inputs(inputs))


def validate_goal_document(document, *, inputs):
    return prior.validate_goal_document(document, inputs=project_inputs(inputs))


def prepare_goal_source_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_source_audit_request(project_inputs(inputs), profile, native_goal), inputs)


def validate_goal_source_audit(document, native_goal, *, context_sha256, authority_context=None, inputs=None):
    return prior.validate_goal_source_audit(document, native_goal, context_sha256=context_sha256,
        authority_context=authority_context, inputs=project_inputs(inputs) if inputs is not None else None)


def prepare_goal_drama_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_drama_audit_request(project_inputs(inputs), profile, native_goal), inputs)


def prepare_goal_commitment_audit_request(inputs, profile, native_goal):
    return _mark(prior.prepare_goal_commitment_audit_request(project_inputs(inputs), profile, native_goal), inputs)


def validate_goal_audit(bundle, native_goal, *, inputs):
    return prior.validate_goal_audit(bundle, native_goal, inputs=project_inputs(inputs))


def prepare_opening_setup_request(inputs, profile, native_goal):
    return _mark(prior.prepare_opening_setup_request(project_inputs(inputs), profile, native_goal), inputs)


def prepare_script_request(inputs, profile, native_goal, native_goal_audit, *, opening_setup,
                         source_ids, legal_ids, user_constraint_ids):
    return _mark(prior.prepare_script_request(project_inputs(inputs), profile, native_goal, native_goal_audit,
        opening_setup=opening_setup, source_ids=source_ids, legal_ids=legal_ids, user_constraint_ids=user_constraint_ids), inputs)


def prepare_full_review_part_request(inputs, profile, native_script, views, part):
    return _mark(prior.prepare_full_review_part_request(project_inputs(inputs), profile, native_script, views, part), inputs)


# Native schemas and validators below have no user-input projection argument.
# Their exact current source6/setup4/full-review contracts are intentionally reused.
build_goal_audit_bundle = prior.build_goal_audit_bundle
build_goal_source_audit_schema = prior.build_goal_source_audit_schema
build_goal_drama_audit_schema = prior.build_goal_drama_audit_schema
validate_goal_drama_audit = prior.validate_goal_drama_audit
validate_goal_commitment_audit = prior.validate_goal_commitment_audit
validate_script_document = prior.validate_script_document
validate_opening_setup_document = prior.validate_opening_setup_document
compile_native_views = prior.compile_native_views
contexts, citations, windows = prior.contexts, prior.citations, prior.windows
source_audit, drama_contract, commitment_audit = prior.source_audit, prior.drama_contract, prior.commitment_audit
goals, setups, reviews = prior.goals, prior.setups, prior.reviews
audit_contexts, evidence_view, split_reviews = prior.audit_contexts, prior.evidence_view, prior.split_reviews
SOURCE_AUDIT_VERSION, SOURCE_MAX_COMPLETION_TOKENS = prior.SOURCE_AUDIT_VERSION, prior.SOURCE_MAX_COMPLETION_TOKENS
OPENING_SETUP_VERSION, DRAMA_AUDIT_VERSION = prior.OPENING_SETUP_VERSION, prior.DRAMA_AUDIT_VERSION
BUNDLE_VERSION, GOAL_CHECKS, AUTHOR_RULE = prior.BUNDLE_VERSION, prior.GOAL_CHECKS, prior.AUTHOR_RULE
FIXED_LEGAL_SOURCE_RULE, FIXED_LEGAL_SOURCE_RULE_VERSION = prior.FIXED_LEGAL_SOURCE_RULE, prior.FIXED_LEGAL_SOURCE_RULE_VERSION
