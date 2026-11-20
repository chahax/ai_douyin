"""Chapter facts, episode state snapshots and accountable screenplay production.

This module is an offline orchestration contract.  The caller owns durable model
requests, provider credentials, approvals, budget admission and unknown outcomes.
Model semantic opinions are recorded separately from structural evidence checks.
"""
from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator

from . import corpus_production_contract_v3 as previous
from .screenplay_revision_v3 import (CONTRACT, REBUILD, source_sha,
                                     validate_contract, locate_contract_evidence,
                                     draft_quote_anchors)
from .screenplay_revision_v4 import segments, speech_constraints, TIMING, validate_timing
from .screenplay_review_cycle_v2 import REVIEW, text_sha, validate_review


VERSION = "corpus_production_contract/v5-chapter-facts-episode-state"
LAYERS = ("world", "character", "location", "event", "staging", "dialogue_timing")
STAGES = ("materials", "framework", "snapshot", "design", "facts", "screenplay")
CATEGORIES = ("world", "character", "location", "event")
CHECKS = previous.CHECKS


class ProductionRejected(ValueError):
    """Known, completed review rejection; never an unknown transport outcome."""
    def __init__(self, stage, issues, reason="production_review_rejected"):
        super().__init__(reason + ":" + stage)
        self.stage, self.issues = stage, deepcopy(issues)


def policy():
    return {"version": VERSION, "material_repairs_per_chapter": 1,
            "root_repair_limit": 2, "protocol_repairs": 1,
            "deepseek_scope": "final_content_and_timing_only"}


def minimum_calls(chapter_count, include_materials=True):
    if type(chapter_count) is not int or chapter_count < 1:
        raise ValueError("chapter_count_invalid")
    # Snapshot evidence may refer to earlier complete chapters. Reserve the
    # maximum independent snapshot and design reviews before source review.
    result = {"writer": (chapter_count if include_materials else 0) + 5,
              "local": chapter_count + 1 + 2 * chapter_count, "director": 2}
    return {**result, "total": sum(result.values())}


def digest(value):
    return previous.digest(value)


def _obj(**properties):
    return {"type": "object", "properties": deepcopy(properties),
            "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1}


def _array(items, minimum=0):
    return {"type": "array", "items": deepcopy(items), "minItems": minimum}


def _schema(raw, schema):
    errors = list(Draft202012Validator(schema).iter_errors(raw))
    if errors:
        raise ValueError("v5_schema_invalid:" + ".".join(map(str, errors[0].path)) + ":" + errors[0].message)


def _source_evidence_schema(chapters):
    if not chapters:
        return {"type": "array", "maxItems": 0, "items": False}
    return _array(_obj(chapter_index={"enum": [c["index"] for c in chapters]},
                       quote={"type": "string", "minLength": 4, "maxLength": 1200}))


def _evidence(refs, chapters, required=False):
    if required and not refs:
        raise ValueError("v5_source_evidence_required")
    lookup = {c["index"]: c["text"] for c in chapters}
    bound = []
    for row in refs:
        quote, text = row["quote"], lookup.get(row["chapter_index"], "")
        at = text.find(quote)
        if at < 0:
            raise ValueError("v5_original_quote_mismatch")
        if text.find(quote, at + 1) >= 0:
            raise ValueError("v5_original_quote_ambiguous")
        bound.append({**deepcopy(row), "start_offset": at, "end_offset": at + len(quote)})
    return bound


def review_schema(artifact, chapters, *, checks=CHECKS, checked_ids=()):
    return _obj(reviewed_artifact_sha256={"const": digest(artifact)},
                checked_chapter_indices={"type": "array", "items": {"enum": [c["index"] for c in chapters]},
                                         "uniqueItems": True, "minItems": len(chapters), "maxItems": len(chapters)},
                checked_ids={"type": "array", "items": {"enum": list(checked_ids)},
                             "uniqueItems": True, "minItems": len(checked_ids), "maxItems": len(checked_ids)},
                decision={"enum": ["pass", "revise"]},
                checks=_obj(**{key: {"enum": ["pass", "fail"]} for key in checks}),
                issues=_array(_obj(check={"enum": list(checks)}, layer={"enum": list(LAYERS)},
                                   location=TEXT, reason=TEXT, required_change=TEXT,
                                   source_evidence=_source_evidence_schema(chapters))), summary=TEXT)


def validate_stage_review(raw, artifact, chapters, *, checks=CHECKS, checked_ids=()):
    _schema(raw, review_schema(artifact, chapters, checks=checks, checked_ids=checked_ids))
    failed = {key for key, status in raw["checks"].items() if status == "fail"}
    if failed != {item["check"] for item in raw["issues"]}:
        raise ValueError("v5_review_checks_disagree")
    if (raw["decision"] == "pass") != (not raw["issues"]):
        raise ValueError("v5_review_decision_disagree")
    bindings = [_evidence(item["source_evidence"], chapters,
                          item["layer"] in CATEGORIES) for item in raw["issues"]]
    return {"native_review": deepcopy(raw), "source_bindings": bindings,
            "artifact_sha256": digest(artifact), "downstream_ready": raw["decision"] == "pass",
            "semantic_status": "model_opinion_" + raw["decision"]}


MATERIAL_REVIEW_REQUIREMENTS = """逐条检查候选是否足以构建后续状态快照：原文明示的身份关系、所在地点、持有或转移物品、获知变化，即使已经写进 statement，也必须准确登记对应实体及 typed state_changes。statement 提到但 state_changes 漏记、实体类型错误（如地名被当人物）均需 revise，分别定位 state_changes/entity_mentions，引用本章原句说明缺什么。不要因 facts/coverage 非空或每段有记录就通过；也不要机械要求每章必须存在所有状态种类。这里只审核有原文支持的实际遗漏，不自行替模型补写候选。"""

LOCAL_FRAMEWORK_REVIEW = """你是本机 Qwen 独立来源核对员。阅读完整本章、邻章以及本次断言实际引用的其他完整章节，对 framework_claims 中分配给本次的全部原子断言逐一核对。每个断言只分配一次，origin_chapter 是其引用最早章；其他引用章节也全部提供。只审核这些断言，不要求本章单独包含跨章事实；检查世界规则、人物别名和关系、地点层级、事件前因和时间状态。尤其区分亲子/继子、物品来源、计划/发生、内心/对白和未来知情状态。checked_ids 覆盖输入 required_claim_ids，问题必须定位字段并有实际正文引文。只返回 schema，不改稿，不因上游来自 MiniMax 或已通过材料审而默认通过。"""

CONSISTENCY_REVIEW = """你是本机 Qwen 跨章框架一致性审核员。输入是已逐章对照原文核查的紧凑框架，并非全部原文。仅检查跨章框架自身矛盾：同一人的别名或关系互斥、人物状态的时间冲突、地点包含矛盾、事件前因后果互斥。问题必须引用框架中两处具体字段及原样内容，解释矛盾；不能据缺失原文宣称原文没有某事实，也不新增事实。没有矛盾则 pass。完整框架本身如超过容量，由调用层停止，不得截断后冒称完整审核。"""

LOCAL_DESIGN_REVIEW = """你是本机 Qwen 独立视觉设计验收员。对照 selected_original_chapters 的完整正文、已核对的世界/人物/地点/本集事件，以及视觉设计全文，核对实际时点人物关系、空间、道具、知情状态与创意补足边界。检查世界背景、统一画风、大环境到小环境、人物互动、初末状态、开场可见信息是否具体。家具服装光线等明确标注的合理创意不算来源错误。所有来源问题须给4至1200字连续唯一原句；纯表演缺项可空原文证据但必须定位设计。返回 schema，只审核不修稿。"""

SNAPSHOT_REVIEW = """你是本机 Qwen 本集状态快照独立验收员。完整阅读给定本章正文及 episode_snapshot、本集事实证据和场景计划。逐项核对开场时点的在场人物、关系、所在位置、道具持有、知情与情绪状态、场景之间的事实变化；必须区分已成立状态、将来事件、回忆、内心、计划、猜测。所有场景引用已声明状态，状态变化有本集事件支持，不允许把全书后期关系或物品偷带到开场。
本次按完整章分开核对来源，其他章事实由其他调用核对，不能因本章未提及就宣称其他章事实不存在；仍须通读完整快照检查内部连续性。episode_selection_brief 是已审选段内的开端、推进、转折、结尾及其原段，核对快照与场景是否实际承接这个事件，不能另换故事。创意服装/陈设可补足但不能修改来源事实。指出问题给原文连续唯一引文与责任类别，纯场景规划缺项可以无原文证据但须定位。返回给定schema，只审核，不改快照或剧本。"""

WRITER = REBUILD + """
依据经过独立核对的新框架、视觉设计、本集事实表和完整原文写一份完整新稿。世界观与人物关系写在正文前。每场交代时间、地点、环境、实际人物、进入状态与前后衔接。每段写具体动作、双方神情视线、说听反应、镜头和连续道具状态。只呈现需要的正向内容。
所有段落用“### 【0—12秒】”连续秒数标题；每句对白单独一行，角色名：“实际台词”；非对白不用双引号。场景元数据置于该场首秒段之前。动作省略须明确剪辑与新镜头初态。按自然语速每秒最多5语音单位计对白，另留必要停顿与串行动作；勿用全片平均掩盖某段超时。
收到责任修订时修完整稿；框架或设计改变后重新构建整稿，不保留已失效的旧剧情状态。旧稿只作错误定位，不是必须沿用的模板。"""
WRITER += """
本路线以 episode_state_plan 的本集快照与 beats 作为当前状态来源，episode_selection_brief 保留已审事件开端、推进、转折、结尾及选段来源，不另换故事。绝不能用未提供的全书后文补当前关系或物品。按 beats 顺序写场景；每个beat在它的第一段秒数标题之前单独写两行：scene_id: 原beat.id；state_ids: 该beat的before/after快照全部state_ids的去重并集，用英文逗号分隔。每个beat出现一次，状态编号不可虚构或漏写。全稿末秒不得超过target_seconds；每场的全部秒段时长合计不得超过对应beat.duration_seconds。场景里的具体动作和镜头把计划的前后状态变化实际表现出来；编号只是来源地址，不能代替表演内容。"""


def _completed_checked(call, name, role, prompt, payload, schema, validator):
    context = {**payload, "output_schema": _request_schema(schema)}
    native = call(name, role, prompt, context)
    try:
        return validator(native)
    except ValueError as error:
        # call() is outside try: an uncertain execution is never retried here.
        repaired = call(name + "_PROTOCOL_REPAIR", role,
                        prompt + "\n修正已完成返回的格式/范围/引用错误，重新给出完整结论，不可隐藏真实问题。",
                        {**context, "previous_invalid_output": native, "validation_error": str(error)})
        return validator(repaired)


def _request_schema(schema):
    """Large source-ID enums are validated locally, not duplicated in prompts."""
    if isinstance(schema, list):
        return [_request_schema(row) for row in schema]
    if not isinstance(schema, dict):
        return schema
    if isinstance(schema.get("enum"), list) and len(schema["enum"]) > 100 and all(isinstance(x, str) for x in schema["enum"]):
        return {**{key: _request_schema(value) for key, value in schema.items() if key != "enum"},
                "type": "string", "minLength": 1,
                "description": "Use an exact source ID from the supplied directory; locally validated."}
    return {key: _request_schema(value) for key, value in schema.items()}


def framework_source_payload(source, pack):
    """One complete original per chapter plus compact source-ID offsets."""
    previous._source(pack, source["chapters"])
    def paragraph_ids(refs):
        return list(dict.fromkeys(row["paragraph_id"] for row in refs))
    candidates = []
    for accepted in pack.get("chapter_facts", []):
        entities = [{**{key: deepcopy(row[key]) for key in ("id", "kind", "name")},
                     "source_paragraph_ids": paragraph_ids(row["source_refs"])} for row in accepted["entities"]]
        facts = []
        for row in accepted["facts"]:
            changes = [{**{key: deepcopy(change[key]) for key in ("kind", "subject_id", "object_id", "predicate", "before_value", "after_value", "change_type")},
                        "source_paragraph_ids": paragraph_ids(change["source_refs"])} for change in row["state_changes"]]
            facts.append({**{key: deepcopy(row[key]) for key in ("id", "categories", "statement", "entity_ids", "modality", "event_time", "narrative_anchor_passage_id")},
                          "source_paragraph_ids": paragraph_ids(row["source_refs"]), "state_changes": changes})
        candidates.append({"chapter_id": accepted["chapter_id"], "chapter_index": accepted["chapter_index"],
                           "candidate_sha256": digest(accepted), "entities": entities, "facts": facts,
                           "covered_natural_paragraphs": len(accepted["coverage"])})
    return {"book_name": source.get("book_name", pack.get("book_name", "")),
            "source_pack_sha256": digest(pack),
            "source_contexts": [{"chapter_index": row["index"], "title": row["title"], "text": row["text"]}
                                for row in source["chapters"]],
            "passage_directory": {"columns": ["id", "chapter_index", "start_offset", "end_offset"],
                                  "rows": [[row[key] for key in ("id", "chapter_index", "start_offset", "end_offset")]
                                           for row in pack["selected_core_passages"]]},
            "source_index_rule": "passage_directory 是自然段位置目录，全文在 source_contexts 每章仅一份；按 columns 读取各行并按字符位置找原句。所有原段均保留，不按重要度删除。",
            "chapter_coverage": [{"chapter_index": row["chapter_index"]} for row in pack["chapter_coverage"]],
            "chapter_fact_candidates": candidates,
            "fact_input_rule": "这些是Qwen逐章提取且经MiniMax逐章核验的事实及状态变化，仍需对照原文。关系/当前或回忆计划/成立区间以事实证据核对，不把后文状态提前。"}


def _materials_payload(source, accepted):
    from . import corpus_chapter_facts_v5 as chapter_contract
    chapters = source["chapters"]
    plan = accepted["chapter_plan"]
    raw = chapter_contract.raw_candidate(accepted)
    canonical = chapter_contract.validate(raw, chapters, plan)
    if canonical != accepted:
        raise ValueError("v5_material_binding_changed")
    payload = chapter_contract.review_payload(accepted, chapters, plan)
    return payload


def _review_one_material(call, source, accepted, name):
    from . import corpus_chapter_facts_v5 as chapter_contract
    payload = _materials_payload(source, accepted)
    native = _completed_checked(call, name, "writer", chapter_contract.REVIEW_PROMPT + "\n" + MATERIAL_REVIEW_REQUIREMENTS, payload,
                                chapter_contract.review_schema(payload),
                                lambda raw: chapter_contract.validate_review(raw, payload))
    return {"native_review": native, "candidate_sha256": payload["candidate_sha256"],
            "downstream_ready": native["decision"] == "pass",
            "semantic_status": "model_opinion_" + native["decision"]}


def review_materials(call, source, chapter_materials, *, record=lambda *_: None, attempt=0):
    expected = [row["index"] for row in source["chapters"]]
    actual = [row["chapter_index"] for row in chapter_materials]
    if actual != expected:
        raise ValueError("v5_material_chapter_coverage_mismatch")
    reviews, issues = [], []
    for accepted in chapter_materials:
        result = _review_one_material(call, source, accepted,
                                      f"MATERIAL_REVIEW_{attempt:02}_CH{accepted['chapter_index']:03}")
        row = {"chapter_index": accepted["chapter_index"], **result}
        record(f"MATERIAL_REVIEW_BOUND_{attempt:02}_CH{accepted['chapter_index']:03}", row)
        reviews.append(row)
        issues.extend({**issue, "chapter_index": accepted["chapter_index"], "responsible_stage": "materials"}
                      for issue in result["native_review"]["issues"])
    return {"decision": "revise" if issues else "pass", "reviews": reviews, "issues": issues,
            "materials_sha256": digest(chapter_materials), "source_sha256": digest(source)}


def _framework_claims(framework, pack, chapter_index):
    lookup = {row["id"]: row["chapter_index"] for row in pack["selected_core_passages"]}
    claims = []
    def add(identifier, value):
        refs = sorted({lookup[pid] for pid in value["source_passage_ids"]})
        if min(refs) == chapter_index:
            claims.append({"id": identifier, "value": deepcopy(value),
                           "origin_chapter": chapter_index, "source_chapter_indices": refs})
    for category in ("world", "characters", "locations", "mainline"):
        for index, row in enumerate(framework[category]):
            if category == "characters":
                add(f"characters.{index}.identity", {key: value for key, value in row.items() if key != "relationships"})
                for n, relation in enumerate(row["relationships"]):
                    add(f"characters.{index}.relationships.{n}", {"character_id": row["id"], **relation})
            else:
                add(f"{category}.{index}", row)
    add("episode_arc", framework["episode_arc"])
    return claims


def framework_schema(pack):
    schema = previous.framework_schema(pack)
    schema["properties"]["mainline"]["items"]["properties"]["chapter_indices"]["maxItems"] = 1
    return schema


def validate_framework(raw, pack, chapters):
    _schema(raw, framework_schema(pack))
    return previous.validate_framework(raw, pack, chapters)


def episode_selection_brief(framework, pack, source):
    """Project only the reviewed episode arc and its exact selected sources."""
    passages, _, _ = previous._source(pack, source["chapters"])
    selected = framework["selected_chapter_indices"]
    ids = framework["episode_arc"]["source_passage_ids"]
    if not ids or any(pid not in passages or passages[pid]["chapter_index"] not in selected for pid in ids):
        raise ValueError("v5_episode_arc_source_outside_selection")
    return {"selected_chapter_indices": deepcopy(selected),
            "episode_arc": deepcopy(framework["episode_arc"]),
            "source_passages": [deepcopy(passages[pid]) for pid in dict.fromkeys(ids)],
            "framework_sha256": digest(framework), "source_pack_sha256": digest(pack)}


def _stage_corrections(corrections, stage, selected=()):
    """Resolved upstream reports stay in audit records, not creative inputs."""
    scoped = [deepcopy(row) for row in corrections if row.get("responsible_stage") == stage]
    if selected and any(ref["chapter_index"] > max(selected) for row in scoped for ref in row.get("source_evidence", [])):
        raise ValueError("v5_episode_correction_future_source")
    return scoped


def _pointer(value, path):
    current = value
    for part in path.split(".") if path else []:
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, ValueError, TypeError):
            raise ValueError("v5_artifact_field_missing:" + path) from None
    return current


def _text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def consistency_schema(framework):
    anchor = _obj(field_path=TEXT, quote={"type": "string", "minLength": 4})
    return _obj(reviewed_artifact_sha256={"const": digest(framework)}, decision={"enum": ["pass", "revise"]},
                issues=_array(_obj(layer={"enum": list(CATEGORIES)}, reason=TEXT, required_change=TEXT,
                                   artifact_evidence={"type": "array", "items": anchor, "minItems": 2})), summary=TEXT)


def validate_consistency(raw, framework):
    _schema(raw, consistency_schema(framework))
    if (raw["decision"] == "pass") != (not raw["issues"]):
        raise ValueError("v5_consistency_decision_disagree")
    for issue in raw["issues"]:
        if len({row["field_path"] for row in issue["artifact_evidence"]}) < 2:
            raise ValueError("v5_consistency_needs_distinct_fields")
        for evidence in issue["artifact_evidence"]:
            if evidence["quote"] not in _text(_pointer(framework, evidence["field_path"])):
                raise ValueError("v5_consistency_evidence_mismatch")
    return deepcopy(raw)


def review_framework(call, source, pack, framework, *, record=lambda *_: None, attempt=0):
    chapters = source["chapters"]
    issues, reviews = [], []
    for chapter in chapters:
        wanted = {chapter["index"]-1, chapter["index"], chapter["index"]+1}
        claims = _framework_claims(framework, pack, chapter["index"])
        wanted.update(index for claim in claims for index in claim["source_chapter_indices"])
        originals = [row for row in chapters if row["index"] in wanted]
        artifact = {"framework_sha256": digest(framework), "chapter_index": chapter["index"], "claims": claims}
        ids = [row["id"] for row in claims]
        result = _completed_checked(call, f"FRAMEWORK_LOCAL_{attempt:02}_CH{chapter['index']:03}", "local",
                                    LOCAL_FRAMEWORK_REVIEW,
                                    {"core_chapter_index": chapter["index"], "complete_original_chapters": originals,
                                     "framework_claims": artifact, "required_claim_ids": ids,
                                     "reviewed_artifact_sha256": digest(artifact)},
                                    review_schema(artifact, originals, checked_ids=ids),
                                    lambda raw: validate_stage_review(raw, artifact, originals, checked_ids=ids))
        record(f"FRAMEWORK_LOCAL_BOUND_{attempt:02}_CH{chapter['index']:03}", result)
        reviews.append(result)
        issues.extend({**item, "responsible_stage": "framework"} for item in result["native_review"]["issues"])
    if issues:
        return {"decision": "revise", "issues": issues, "reviews": reviews}
    consistency = _completed_checked(call, f"FRAMEWORK_CONSISTENCY_{attempt:02}", "local", CONSISTENCY_REVIEW,
                                     {"framework": framework, "reviewed_artifact_sha256": digest(framework),
                                      "per_chapter_review_bindings": [row["artifact_sha256"] for row in reviews]},
                                     consistency_schema(framework), lambda raw: validate_consistency(raw, framework))
    record(f"FRAMEWORK_CONSISTENCY_BOUND_{attempt:02}", consistency)
    return {"decision": consistency["decision"], "issues": [dict(row, responsible_stage="framework")
                                                              for row in consistency["issues"]],
            "reviews": reviews, "consistency": consistency, "artifact_sha256": digest(framework)}


def review_design(call, context, framework, pack, design, *, record, attempt):
    reviews, issues = [], []
    for chapter in context["selected_original_chapters"]:
        originals = [chapter]
        local_context = {key: value for key, value in context.items()
                         if key not in ("selected_original_chapters",)}
        local_context.update(selected_original_chapters=originals,
                             visual_world_design=design, reviewed_artifact_sha256=digest(design),
                             source_scope="One complete chapter for source checks; the complete design is supplied. Other chapters have separate checks.")
        result = _completed_checked(call, f"DESIGN_LOCAL_{attempt:02}_CH{chapter['index']:03}", "local",
                                    LOCAL_DESIGN_REVIEW +
                                    "\n本次只核对与给定完整章有关的来源断言；其他章节事实不能因本章没有而判错，其他章另行审核。完整设计的画风/空间/表演缺项仍可检查；跨章来源不够时说明待其他章核对，不能编造证据。",
                                    local_context, review_schema(design, originals),
                                    lambda raw: validate_stage_review(raw, design, originals))
        record(f"DESIGN_LOCAL_BOUND_{attempt:02}_CH{chapter['index']:03}", result)
        reviews.append(result)
        issues.extend(result["native_review"]["issues"])
    return {"downstream_ready": not issues, "reviews": reviews, "issues": issues,
            "design_sha256": digest(design),
            "source_chapter_indices": [row["index"] for row in context["selected_original_chapters"]]}


def review_snapshot(call, context, snapshot, *, record, attempt):
    reviews, issues = [], []
    for chapter in context["selected_original_chapters"]:
        originals = [chapter]
        local_context = {key: value for key, value in context.items() if key != "selected_original_chapters"}
        local_context.update(selected_original_chapters=originals, episode_snapshot=snapshot,
                             reviewed_artifact_sha256=digest(snapshot),
                             source_scope="One complete episode chapter; the full bounded episode snapshot is supplied.")
        result = _completed_checked(call, f"SNAPSHOT_LOCAL_{attempt:02}_CH{chapter['index']:03}", "local", SNAPSHOT_REVIEW,
                                    local_context, review_schema(snapshot, originals),
                                    lambda raw: validate_stage_review(raw, snapshot, originals))
        record(f"SNAPSHOT_LOCAL_BOUND_{attempt:02}_CH{chapter['index']:03}", result)
        reviews.append(result)
        issues.extend(result["native_review"]["issues"])
    return {"downstream_ready": not issues, "reviews": reviews, "issues": issues,
            "snapshot_sha256": digest(snapshot),
            "source_chapter_indices": [row["index"] for row in context["selected_original_chapters"]]}


ROOT_CAUSE = """你是本机 Qwen 流程责任诊断员，不修改剧本。final_issues 是已完成的审核或程序计时问题，仍需对照 source_original_chapters 与各层实际产物逐一定位原因。逐项选择责任层 world/character/location/event/staging/dialogue_timing，再选择真正产生错误的负责阶段 materials/framework/snapshot/design/facts/screenplay。materials是章节事实及变化，snapshot是本集开场状态和场景状态计划。不要按问题关键词固定路由：例如人物错可以是材料错、框架错、本集快照把未来关系提前，也可能前面正确而编剧写错。只修最早实际有错的产物；上游正确时不能要求全局重做。
每项必须说明 cause、required_change，并给 responsible_stage 同名产物的 SHA、真实 field_path 与该字段的原样 quote；已有错误用 evidence_kind=present，确有遗漏用 omission 且 quote 为空、field_path 必须是实际存在的集合/字段，解释原文哪项应出现却遗漏。世界/人物/地点/事件责任必须提供完整原文连续唯一引文；表演和计时可用当前产物与程序测量证据。materials 阶段还须给具体 chapter_index，其他阶段 chapter_index=0。覆盖每个 final_issue_index，不能漏掉不易解释的问题，不能把没有根据的建议升级为根因。返回 schema，程序核对证据定位，但你的语义归因仍是待记录的模型判断。"""


def diagnosis_schema(issues, artifacts, chapters):
    anchor = _obj(artifact_name={"enum": list(artifacts)}, artifact_sha256=TEXT,
                  field_path={"type": "string"}, evidence_kind={"enum": ["present", "omission"]},
                  quote={"type": "string"})
    return _obj(reviewed_issues_sha256={"const": digest(issues)},
                decision={"enum": ["diagnosed", "insufficient_evidence"]}, reason=TEXT,
                diagnoses={"type": "array", "minItems": 0, "maxItems": len(issues),
                           "items": _obj(final_issue_index={"enum": list(range(len(issues)))},
                                         layer={"enum": list(LAYERS)}, responsible_stage={"enum": list(STAGES)},
                                         chapter_index={"enum": [0, *[c["index"] for c in chapters]]},
                                         cause=TEXT, required_change=TEXT,
                                         source_evidence=_source_evidence_schema(chapters),
                                         artifact_evidence=_array(anchor, 1))})


def validate_diagnosis(raw, issues, artifacts, chapters):
    _schema(raw, diagnosis_schema(issues, artifacts, chapters))
    rows = raw["diagnoses"]
    if raw["decision"] == "insufficient_evidence":
        if rows:
            raise ValueError("v5_uncertain_root_must_not_route")
        return {"responsible_stage": None, "diagnoses": [], "issues_sha256": digest(issues),
                "semantic_status": "insufficient_evidence", "reason": raw["reason"]}
    if sorted(row["final_issue_index"] for row in rows) != list(range(len(issues))):
        raise ValueError("v5_root_issue_coverage_invalid")
    for row in rows:
        _evidence(row["source_evidence"], chapters, row["layer"] in CATEGORIES)
        if row["responsible_stage"] == "materials":
            if row["chapter_index"] not in {chapter["index"] for chapter in chapters}:
                raise ValueError("v5_material_root_chapter_missing")
            prefix = f"CH{row['chapter_index']:03}"
            target_refs = [ref for ref in row["artifact_evidence"] if ref["artifact_name"] == "materials"]
            if not target_refs or any(ref["field_path"] != prefix and not ref["field_path"].startswith(prefix + ".")
                                      for ref in target_refs):
                raise ValueError("v5_material_root_chapter_evidence_mismatch")
        elif row["chapter_index"] != 0:
            raise ValueError("v5_nonmaterial_root_chapter_unexpected")
        if row["responsible_stage"] not in {ref["artifact_name"] for ref in row["artifact_evidence"]}:
            raise ValueError("v5_root_responsible_artifact_missing")
        for ref in row["artifact_evidence"]:
            artifact = artifacts[ref["artifact_name"]]
            if ref["artifact_sha256"] != digest(artifact):
                raise ValueError("v5_root_artifact_sha_mismatch")
            value = _pointer(artifact, ref["field_path"])
            if ref["evidence_kind"] == "present":
                if len(ref["quote"]) < 4 or ref["quote"] not in _text(value):
                    raise ValueError("v5_root_artifact_quote_mismatch")
            elif ref["quote"] or not isinstance(value, (dict, list, str)):
                raise ValueError("v5_root_omission_scope_invalid")
    stage = min((row["responsible_stage"] for row in rows), key=STAGES.index)
    return {"responsible_stage": stage, "diagnoses": deepcopy(rows),
            "issues_sha256": digest(issues), "semantic_status": "model_root_cause_opinion"}


def invalidated_stages(stage):
    if stage not in STAGES:
        raise ValueError("v5_root_stage_unknown")
    return [*STAGES[STAGES.index(stage):], "final_content", "final_timing"]


def _material_artifacts(chapter_materials):
    return {f"CH{row['chapter_index']:03}": {key: deepcopy(row[key])
            for key in ("chapter_index", "chapter_id", "source_digest", "entities", "facts", "coverage")}
            for row in chapter_materials}


def _episode_framework_view(framework, pack, chapters, design=""):
    """Project for local episode checks; preserve original paths and full hash."""
    indices = {row["index"] for row in chapters}
    passages = {row["id"]: row["chapter_index"] for row in pack["selected_core_passages"]}
    text = "\n".join(row["text"] for row in chapters) + "\n" + design
    fields = []
    selected_locations = set()
    for category in ("world", "characters", "locations", "mainline"):
        for index, row in enumerate(framework[category]):
            cited_here = bool({passages[pid] for pid in row["source_passage_ids"]} & indices)
            named_here = bool(row.get("name") and row["name"] in text)
            include = category == "world" or cited_here or named_here
            if include:
                fields.append({"field_path": f"{category}.{index}", "value": deepcopy(row)})
                if category == "locations":
                    selected_locations.add(row["id"])
    # A selected location needs all explicitly declared parent spaces as well.
    lookup = {row["id"]: (index, row) for index, row in enumerate(framework["locations"])}
    for identifier in list(selected_locations):
        parent = lookup[identifier][1]["parent_id"]
        while parent:
            index, row = lookup[parent]
            if parent not in selected_locations:
                fields.append({"field_path": f"locations.{index}", "value": deepcopy(row)})
                selected_locations.add(parent)
            parent = row["parent_id"]
    for key in ("selected_chapter_indices", "selection_reason", "episode_arc", "limitations"):
        fields.append({"field_path": key, "value": deepcopy(framework[key])})
    return {"full_artifact_sha256": digest(framework), "scope": "episode_projection_not_full_corpus_review",
            "source_chapter_indices": sorted(indices), "fields": fields}


def _diagnosis_views(artifacts, pack, chapters):
    indices = {row["index"] for row in chapters}
    views = {}
    for name, artifact in artifacts.items():
        if name == "framework":
            views[name] = _episode_framework_view(artifact, pack, chapters, artifacts.get("design", ""))
        elif name == "materials":
            views[name] = {"full_artifact_sha256": digest(artifact), "fields": [
                {"field_path": key, "value": deepcopy(row)} for key, row in artifact.items()
                if row["chapter_index"] in indices]}
        else:
            views[name] = {"full_artifact_sha256": digest(artifact), "fields": [{"field_path": "", "value": artifact}]}
    return views


def diagnose_issues(call, issues, artifacts, pack, context, measured, *, record, attempt, local_route=None):
    """One issue per local call, with its complete implicated original chapters.

    Cross-chapter evidence stays together.  If the bound request does not fit,
    stop before dispatch rather than drawing a conclusion from partial chapters.
    """
    all_originals = context["selected_original_chapters"]
    selected = set(context["episode_brief"]["chapter_indices"])
    results = []
    for index, issue in enumerate(issues):
        cited = {row["chapter_index"] for row in issue.get("source_evidence", [])}
        # Program timing evidence can be diagnosed from the actual script and
        # numeric audit; it does not license making source-fact assertions.
        timing_only = not cited and issue.get("check") == "dialogue_timing"
        wanted = cited if cited else (set() if timing_only else selected)
        originals = [row for row in all_originals if row["index"] in wanted]
        if (not originals and not timing_only) or not wanted <= {row["index"] for row in originals}:
            raise ValueError("v5_root_source_scope_missing")
        current = [issue]
        payload = {"final_issues": current, "original_final_issue_index": index,
                   "reviewed_issues_sha256": digest(current),
                   "artifact_views": _diagnosis_views(artifacts, pack, originals),
                   "artifact_hashes": {key: digest(value) for key, value in artifacts.items()},
                   "source_original_chapters": originals,
                   "source_scope": "Complete implicated chapters together; timing-only diagnostics have no source and cannot assert source facts.",
                   "measured_segments": [{key: value for key, value in row.items() if key not in ("text", "evidence")}
                                         for row in measured]}
        prompt = ROOT_CAUSE + "\n本次只诊断一个问题，实际引用的完整章一起提供；artifact_views仅提供有关字段，field_path是完整原产物路径，SHA取artifact_hashes。不要将投影里没有显示的字段判为完整产物遗漏。证据足够才diagnosed；需要未给章节或无法归因则decision=insufficient_evidence、diagnoses=[]并说明，禁止猜根因。纯计时如无原文，不得归因世界/人物/地点/事件事实错误。"
        schema = diagnosis_schema(current, artifacts, originals)
        route = local_route or {"context": 65536, "max_tokens": 8192}
        byte_bound = len(prompt.encode("utf-8")) + len(json.dumps({**payload, "output_schema": _request_schema(schema)}, ensure_ascii=False).encode("utf-8"))
        capacity = {"input_utf8_byte_bound": byte_bound, "output_tokens": route["max_tokens"],
                    "context": route["context"], "complete_source_chapters": [row["index"] for row in originals]}
        record(f"ROOT_CAUSE_CAPACITY_{attempt:02}_ISSUE{index:03}", capacity)
        if byte_bound + route["max_tokens"] + 1024 > route["context"]:
            raise ProductionRejected("root_cause", [issue], "root_cause_complete_evidence_exceeds_capacity")
        result = _completed_checked(call, f"ROOT_CAUSE_{attempt:02}_ISSUE{index:03}", "local", prompt,
                                    payload, schema, lambda raw: validate_diagnosis(raw, current, artifacts, originals))
        record(f"ROOT_CAUSE_BOUND_{attempt:02}_ISSUE{index:03}", result)
        if result["responsible_stage"] is None:
            raise ProductionRejected("root_cause", [issue], "root_cause_evidence_insufficient")
        results.append({**result["diagnoses"][0], "final_issue_index": index})
    stage = min((row["responsible_stage"] for row in results), key=STAGES.index)
    return {"responsible_stage": stage, "diagnoses": results, "issues_sha256": digest(issues),
            "semantic_status": "model_root_cause_opinion"}


def _validate_material_pack(source, pack, chapter_materials):
    from . import corpus_chapter_facts_v5 as chapter_contract
    index = chapter_contract.facts_catalog(chapter_materials, source["chapters"],
                                           book_name=pack.get("book_name", ""))
    if chapter_contract.cloud_input(index) != pack:
        raise ValueError("v5_pack_materials_binding_mismatch")


def _episode_context(source, library, snapshot, design, target_seconds, visual, selection_brief):
    from . import corpus_episode_state_v5 as episode_contract
    context = episode_contract.build_episode_context(snapshot, library, source["chapters"])
    # The global framework and full chapter-fact catalog never enter a writer
    # request after this point.  The episode module owns temporal projection.
    originals = [*context["selected_original_chapters"], *context.pop("required_evidence_chapters", [])]
    originals.sort(key=lambda row: row["index"])
    if len({row["index"] for row in originals}) != len(originals):
        raise ValueError("v5_episode_original_chapters_duplicate")
    raw = snapshot["snapshot"]
    if selection_brief["selected_chapter_indices"] != raw["selected_chapter_indices"]:
        raise ValueError("v5_episode_selection_brief_scope_changed")
    context = {**context, "selected_original_chapters": originals,
               "episode_selection_brief": deepcopy(selection_brief),
               "episode_brief": {"chapter_indices": raw["selected_chapter_indices"],
                                 "opening_snapshot_id": raw["opening_snapshot_id"], "ending_snapshot_id": raw["ending_snapshot_id"],
                                 "beats": [{key: row[key] for key in ("id", "purpose", "dialogue_goal", "duration_seconds")}
                                           for row in raw["beats"]],
                                 "temporal_rule": "Only this episode's referenced state and event evidence; never import future whole-book state."},
               "target_seconds": target_seconds, "visual_world_design": design,
               "visual_storytelling": deepcopy(visual), "accepted_episode_snapshot_sha256": digest(snapshot)}
    if context.get("global_bible", {}).get("mainline"):
        raise ValueError("v5_episode_context_leaks_global_mainline")
    return context


def validate_scene_state_refs(draft, validated_snapshot):
    """Bind each natural-script scene to its planned before/after state IDs."""
    raw = validated_snapshot["snapshot"]
    snapshots = {row["id"]: row for row in raw["snapshots"]}
    headings = list(re.finditer(r"(?m)^\s*scene_id\s*[:：]\s*([^\s,]+)\s*$", draft))
    if [match[1] for match in headings] != [row["id"] for row in raw["beats"]]:
        raise ValueError("v5_script_scene_plan_coverage_mismatch")
    bindings = []
    for index, (heading, beat) in enumerate(zip(headings, raw["beats"])):
        body = draft[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(draft)]
        matches = re.findall(r"(?m)^\s*state_ids\s*[:：]\s*([^\n]+)\s*$", body)
        if len(matches) != 1:
            raise ValueError("v5_script_state_marker_missing_or_duplicate")
        ids = [value.strip() for value in matches[0].split(",")]
        expected = set(snapshots[beat["before_snapshot_id"]]["state_ids"]) | set(snapshots[beat["after_snapshot_id"]]["state_ids"])
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ValueError("v5_script_state_plan_binding_mismatch")
        if not re.search(r"(?m)^[#*【\[ \t]*\d+(?:\.\d+)?\s*[—–\-~～至]\s*\d+(?:\.\d+)?\s*秒", body):
            raise ValueError("v5_script_scene_timing_missing")
        bindings.append({"scene_id": beat["id"], "state_ids": sorted(expected),
                         "before_snapshot_id": beat["before_snapshot_id"], "after_snapshot_id": beat["after_snapshot_id"]})
    return {"snapshot_sha256": digest(validated_snapshot), "draft_sha256": text_sha(draft), "scene_bindings": bindings,
            "semantic_state_realization": "requires_full_content_review"}


def validate_script_timing(draft, validated_snapshot, target_seconds):
    """Enforce the requested whole duration and every planned scene budget."""
    measured = segments(draft)
    if type(target_seconds) not in (int, float) or not 0 < target_seconds < float("inf"):
        raise ValueError("v5_script_target_seconds_invalid")
    if measured[-1]["end"] > target_seconds:
        raise ValueError("v5_script_total_duration_exceeds_target")
    raw = validated_snapshot["snapshot"]
    headings = list(re.finditer(r"(?m)^\s*scene_id\s*[:：]\s*([^\s,]+)\s*$", draft))
    if [match[1] for match in headings] != [row["id"] for row in raw["beats"]]:
        raise ValueError("v5_script_scene_plan_coverage_mismatch")
    assigned, scenes = 0, []
    for index, (heading, beat) in enumerate(zip(headings, raw["beats"])):
        body = draft[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(draft)]
        spans = re.findall(r"(?m)^[#*【\[ \t]*(\d+(?:\.\d+)?)\s*[—–\-~～至]\s*(\d+(?:\.\d+)?)\s*秒[^\n]*$", body)
        duration = sum(float(end) - float(start) for start, end in spans)
        assigned += len(spans)
        if not spans or duration > beat["duration_seconds"]:
            raise ValueError("v5_script_scene_duration_exceeds_plan:" + beat["id"])
        scenes.append({"scene_id": beat["id"], "duration_seconds": duration, "planned_seconds": beat["duration_seconds"]})
    if assigned != len(measured):
        raise ValueError("v5_script_time_segment_outside_scene")
    return {"draft_sha256": text_sha(draft), "target_seconds": target_seconds,
            "duration_seconds": measured[-1]["end"], "scenes": scenes,
            "semantic_timing_acceptance": False}


def _final_reviews(call, context, draft, stats, record, attempt):
    measured = segments(draft)
    early = speech_constraints(measured)
    record(f"SPEECH_PREFLIGHT_{attempt:02}", {"draft_sha256": text_sha(draft),
                                            "blocking_issues": early,
                                            "segments": [{k: v for k, v in row.items() if k not in ("text", "evidence")}
                                                         for row in measured]})
    if early:
        return {"issues": early, "program_preflight": True, "measured": measured}
    chapters = context["selected_original_chapters"]
    payload = {**context, "screenplay": draft, "reviewed_draft_sha256": text_sha(draft),
               "required_reviewed_chapter_indices": [c["index"] for c in chapters],
               "measured_segments": measured, "measured_dialogue": stats(draft)}

    def review(name, prompt, timing=False):
        def valid(raw):
            validate_review(raw, draft, chapters, draft_quote_validator=draft_quote_anchors)
            if timing:
                validate_timing(raw, draft, measured)
            return raw
        native = call(name, "director", prompt, payload)
        try:
            return valid(native)
        except ValueError as error:
            repaired = call(name + "_PROTOCOL_REPAIR", "director", prompt +
                            "\n修正完整报告的证据或协议错误，不能隐藏真实问题。",
                            {**payload, "previous_invalid_review": native, "validation_error": str(error)})
            return valid(repaired)

    content = review(f"FINAL_CONTENT_{attempt:02}", REVIEW +
                     "\n同时按 episode_state_plan 逐场核对实际正文是否表现 before/after 状态与动作依赖，是否完成 episode_selection_brief 的已审事件开端、推进、转折、结尾。scene_id/state_ids 仅证明引用地址，不代表人物真的完成了进出场、物品转移或获知；不能只看元数据就通过。完整原文及当前稿是事实与表演判断依据，回忆/计划/未发生后文不得变成当前状态。")
    temporal = review(f"FINAL_TIMING_{attempt:02}", TIMING, True)
    constraints = validate_timing(temporal, draft, measured)
    record(f"FINAL_TIMING_CONSTRAINTS_{attempt:02}", {"draft_sha256": text_sha(draft), **constraints})
    issues = [*content["blocking_issues"], *temporal["blocking_issues"], *constraints["blocking_issues"]]
    return {"issues": issues, "content": content, "timing": temporal,
            "constraints": constraints, "measured": measured}


def run_production(call, source, pack, plan, *, stats, record, remaining_calls,
                   chapter_materials, repair_materials=None):
    """Run the new route; all retries are finite, evidence-bound known results.

    ``repair_materials(index, issues, attempt)`` is the caller's audited local
    chapter-fact repair.  It must return ``pack`` and full ``chapter_materials``;
    every changed chapter is independently reviewed again before downstream work.
    No provider call is performed by this module except through ``call``.
    """
    from . import corpus_chapter_facts_v5 as chapter_contract
    from . import corpus_episode_state_v5 as episode_contract
    previous._source(pack, source["chapters"])
    _validate_material_pack(source, pack, chapter_materials)
    limit = plan.get("root_repair_limit", policy()["root_repair_limit"])
    if type(limit) is not int or not 0 <= limit <= policy()["root_repair_limit"]:
        raise ValueError("v5_root_repair_limit_invalid")
    minimum = minimum_calls(len(source["chapters"]))
    if remaining_calls() < minimum["total"]:
        raise ValueError("insufficient_capacity_for_complete_production_stage")
    record("MINIMUM_EXECUTION_REQUIREMENT", minimum)
    material_attempts, material_reviews = {}, {}

    def verify_materials(indices=None, generation=0):
        nonlocal pack, chapter_materials
        rows = chapter_materials
        if indices is None:
            selected = {row["chapter_index"] for row in rows}
        else:
            selected = set(indices)
        # review_materials requires complete source coverage.  Each selected
        # chapter uses the same single-chapter verifier, without replaying others.
        for row in rows:
            index = row["chapter_index"]
            if index not in selected:
                continue
            while True:
                attempt = material_attempts.get(index, 0)
                result = _review_one_material(call, source, row,
                                              f"MATERIAL_REVIEW_{generation:02}_CH{index:03}_A{attempt}")
                record(f"MATERIAL_BOUND_{generation:02}_CH{index:03}_A{attempt}", result)
                if result["downstream_ready"]:
                    material_reviews[index] = {"material_sha256": digest(row), **result}
                    break
                issues = result["native_review"]["issues"]
                if repair_materials is None or attempt >= policy()["material_repairs_per_chapter"]:
                    raise ProductionRejected("materials", issues, "material_semantic_revision_limit_reached")
                repaired = repair_materials(index, issues, attempt + 1)
                next_pack, next_materials = repaired["pack"], repaired["chapter_materials"]
                previous._source(next_pack, source["chapters"])
                _validate_material_pack(source, next_pack, next_materials)
                before = {item["chapter_index"]: item for item in chapter_materials}
                after = {item["chapter_index"]: item for item in next_materials}
                if set(before) != set(after) or any(before[key] != after[key] for key in before if key != index):
                    raise ValueError("v5_material_repair_changed_unrelated_chapter")
                pack, chapter_materials = next_pack, next_materials
                material_attempts[index] = attempt + 1
                row = after[index]

    if [row["chapter_index"] for row in chapter_materials] != [row["index"] for row in source["chapters"]]:
        raise ValueError("v5_material_chapter_coverage_mismatch")
    verify_materials()
    record("MATERIALS_ACCEPTED", {"source_pack_sha256": digest(pack),
                                 "materials_sha256": digest(chapter_materials), "reviews": material_reviews})
    artifacts = {"materials": _material_artifacts(chapter_materials)}
    library = chapter_contract.facts_catalog(chapter_materials, source["chapters"], book_name=pack.get("book_name", ""))
    framework = snapshot = design = facts = draft = selection_brief = None
    framework_review = snapshot_review = design_review = None
    stage, corrections = "framework", []
    invalidations = []
    for generation in range(limit + 1):
        if stage == "materials":
            if repair_materials is None:
                raise ProductionRejected(stage, corrections, "material_repair_callback_missing")
            targets = sorted({row["chapter_index"] for row in corrections if row["responsible_stage"] == "materials"})
            for index in targets:
                attempt = material_attempts.get(index, 0)
                if attempt >= policy()["material_repairs_per_chapter"]:
                    raise ProductionRejected(stage, corrections, "material_semantic_revision_limit_reached")
                result = repair_materials(index, [row for row in corrections if row["chapter_index"] == index], attempt + 1)
                before = {row["chapter_index"]: row for row in chapter_materials}
                after = {row["chapter_index"]: row for row in result["chapter_materials"]}
                if set(before) != set(after) or any(before[key] != after[key] for key in before if key != index):
                    raise ValueError("v5_material_repair_changed_unrelated_chapter")
                previous._source(result["pack"], source["chapters"])
                _validate_material_pack(source, result["pack"], result["chapter_materials"])
                pack, chapter_materials = result["pack"], result["chapter_materials"]
                material_attempts[index] = attempt + 1
            verify_materials(targets, generation)
            artifacts["materials"] = _material_artifacts(chapter_materials)
            library = chapter_contract.facts_catalog(chapter_materials, source["chapters"], book_name=pack.get("book_name", ""))
            stage = "framework"
        if stage == "framework":
            if remaining_calls() < minimum_calls(len(source["chapters"]), include_materials=False)["total"]:
                raise ValueError("insufficient_capacity_for_complete_production_stage")
            scope, details = previous.source_scope(pack, source["chapters"])
            payload = {**framework_source_payload(source, pack), "target_seconds": plan.get("target_seconds", 90),
                       "source_scope": scope, "source_scope_details": details,
                       "required_source_corrections": _stage_corrections(corrections, "framework")}
            validated = _completed_checked(call, f"FRAMEWORK_{generation:02}", "writer", previous.FRAMEWORK_PROMPT +
                                           "\n本路线 mainline 每项只对应一个完整章节，逐章覆盖，不合并多个章节到同一条。passage_directory 的 columns/rows 是自然段ID/章/位置目录，完整原文在source_contexts。chapter_fact_candidates是逐章事实和状态变化及证据，已经MiniMax逐章审过，仍需亲自对原文核查；不要把modality非actual或event_time非当前的状态当已经成立。按目录引用，不假定目录内重复存有text。",
                                           payload, framework_schema(pack),
                                           lambda raw: validate_framework(raw, pack, source["chapters"]))
            framework = previous.framework_raw(validated)
            artifacts["framework"] = framework
            record(f"FRAMEWORK_{generation:02}_BOUND", validated)
            framework_review = review_framework(call, source, pack, framework, record=record, attempt=generation)
            if framework_review["decision"] != "pass":
                corrections = framework_review["issues"]
                if generation == limit:
                    raise ProductionRejected("framework", corrections, "framework_semantic_revision_limit_reached")
                invalidation = {"generation": generation, "responsible_stage": "framework",
                                "invalidated": invalidated_stages("framework"), "issues": corrections,
                                "artifact_sha256": digest(framework)}
                invalidations.append(invalidation); record(f"INVALIDATION_{generation:02}", invalidation)
                stage = "framework"
                continue
            selection_brief = episode_selection_brief(framework, pack, source)
            record(f"EPISODE_SELECTION_BRIEF_{generation:02}", selection_brief)
            stage = "snapshot"
        if stage == "snapshot":
            selected = framework["selected_chapter_indices"]
            payload = episode_contract.episode_payload(library, source["chapters"], selected,
                                                        target_seconds=plan.get("target_seconds", 90))
            payload = {**payload, "episode_selection_brief": deepcopy(selection_brief),
                       "required_snapshot_corrections": _stage_corrections(corrections, "snapshot", selected),
                       "accepted_chapter_review_bindings": {str(key): digest(value) for key, value in material_reviews.items()}}
            snapshot = _completed_checked(call, f"EPISODE_SNAPSHOT_{generation:02}", "writer", episode_contract.EPISODE_PROMPT +
                                          "\nepisode_selection_brief 是已审的本集事件开端、推进、转折、结尾及选段原文依据；状态和场景计划须落实该事件，不另换故事。",
                                          payload, episode_contract.episode_schema(library, selected, target_seconds=plan.get("target_seconds", 90)),
                                          lambda raw: episode_contract.validate_episode(raw, library, source["chapters"], selected,
                                                                                       target_seconds=plan.get("target_seconds", 90)))
            artifacts["snapshot"] = snapshot
            record(f"EPISODE_SNAPSHOT_BOUND_{generation:02}", snapshot)
            snapshot_context = _episode_context(source, library, snapshot, "pending", plan.get("target_seconds", 90),
                                                 plan.get("visual_storytelling", {}), selection_brief)
            snapshot_context.pop("visual_world_design")
            snapshot_review = review_snapshot(call, snapshot_context, snapshot, record=record, attempt=generation)
            record(f"SNAPSHOT_LOCAL_BOUND_{generation:02}", snapshot_review)
            if not snapshot_review["downstream_ready"]:
                if generation == limit:
                    raise ProductionRejected("snapshot", snapshot_review["issues"], "snapshot_semantic_revision_limit_reached")
                diagnosed = diagnose_issues(call, snapshot_review["issues"], artifacts, pack, snapshot_context, [],
                                            record=record, attempt=generation, local_route=plan.get("local_route"))
                stage, corrections = diagnosed["responsible_stage"], diagnosed["diagnoses"]
                invalidation = {"generation": generation, "responsible_stage": stage,
                                "invalidated": invalidated_stages(stage), "issues": corrections,
                                "artifact_sha256": digest(snapshot)}
                invalidations.append(invalidation); record(f"INVALIDATION_{generation:02}", invalidation)
                for key in invalidated_stages(stage):
                    if key != "materials":
                        artifacts.pop(key, None)
                continue
            stage = "design"
        if stage == "design":
            context = _episode_context(source, library, snapshot, "pending", plan.get("target_seconds", 90),
                                       plan.get("visual_storytelling", {}), selection_brief)
            context.pop("visual_world_design")
            design = call(f"VISUAL_DESIGN_{generation:02}", "writer", previous.VISUAL_DESIGN_PROMPT.replace(
                          "global_bible、episode_brief及selected_original_chapters", "episode_state_plan、episode_source_facts、episode_brief及selected_original_chapters") +
                          "\n本路线只使用本集快照及投影事实，不提供全书后续主线；按每个beat已绑定的初末状态设计环境、动作和人物，不能改写关系、知情、持物和出入场状态。",
                          {**context, "required_design_corrections": _stage_corrections(corrections, "design", framework["selected_chapter_indices"])}, False)
            if not isinstance(design, str) or not design.strip():
                raise ValueError("visual_design_empty")
            artifacts["design"] = design
            design_review = review_design(call, context, framework, pack, design, record=record, attempt=generation)
            record(f"DESIGN_LOCAL_BOUND_{generation:02}", design_review)
            if not design_review["downstream_ready"]:
                current_issues = design_review["issues"]
                if generation == limit:
                    raise ProductionRejected("design", current_issues, "design_semantic_revision_limit_reached")
                diagnosed = diagnose_issues(call, current_issues, artifacts, pack, context, [],
                                            record=record, attempt=generation, local_route=plan.get("local_route"))
                stage, corrections = diagnosed["responsible_stage"], diagnosed["diagnoses"]
                invalidation = {"generation": generation, "responsible_stage": stage,
                                "invalidated": invalidated_stages(stage), "issues": corrections,
                                "artifact_sha256": digest(design)}
                invalidations.append(invalidation); record(f"INVALIDATION_{generation:02}", invalidation)
                for key in invalidated_stages(stage):
                    if key != "materials":
                        artifacts.pop(key, None)
                continue
            stage = "facts"
        context = _episode_context(source, library, snapshot, design, plan.get("target_seconds", 90),
                                   plan.get("visual_storytelling", {}), selection_brief)
        if stage == "facts":
            originals = context["selected_original_chapters"]
            # Compact fact structure is checked against original text; it is
            # reviewed semantically with the entire script at the final stage.
            fact_payload = {"selected_original_chapters": originals, "source_sha256": source_sha(originals),
                            "episode_brief": context["episode_brief"], "episode_state_plan": context["episode_state_plan"],
                            "episode_selection_brief": context["episode_selection_brief"],
                            "required_fact_corrections": _stage_corrections(corrections, "facts", framework["selected_chapter_indices"])}
            native_facts = call(f"FACTS_{generation:02}", "writer", CONTRACT, fact_payload)
            try:
                facts = validate_contract(locate_contract_evidence(native_facts, originals), originals)
            except ValueError as error:
                repaired = call(f"FACTS_{generation:02}_PROTOCOL_REPAIR", "writer", CONTRACT +
                                "\n修正已完成事实表的结构或原文引用错误，返回完整事实表，不能隐去真实问题。",
                                {**fact_payload, "previous_invalid_output": native_facts, "validation_error": str(error)})
                facts = validate_contract(locate_contract_evidence(repaired, originals), originals)
            artifacts["facts"] = facts
            record(f"FACTS_BOUND_{generation:02}", facts)
            stage = "screenplay"
        if stage != "screenplay":
            raise ValueError("v5_invalid_repair_stage")
        if remaining_calls() < 3:
            raise ValueError("insufficient_capacity_for_writer_and_final_reviews")
        context["source_fact_contract"] = facts
        writer_payload = {**context, "required_revisions": _stage_corrections(corrections, "screenplay", framework["selected_chapter_indices"])}
        draft = call(f"SCREENPLAY_{generation:02}", "writer", WRITER, writer_payload, False)
        def valid_draft(value):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("screenplay_empty")
            validate_scene_state_refs(value, snapshot)
            validate_script_timing(value, snapshot, plan.get("target_seconds", 90))
            return value
        try:
            draft = valid_draft(draft)
        except ValueError as error:
            revised = call(f"SCREENPLAY_{generation:02}_PROTOCOL_REPAIR", "writer", WRITER +
                           "\n已完成稿的结构或时长未通过程序核对，请按诊断返回一份完整合规稿，不只返回补丁；全稿及各场不能超预算。",
                           {**writer_payload, "previous_invalid_output": draft, "validation_error": str(error)}, False)
            draft = valid_draft(revised)
        record(f"SCRIPT_STATE_BINDING_{generation:02}", validate_scene_state_refs(draft, snapshot))
        record(f"SCRIPT_TIMING_BINDING_{generation:02}", validate_script_timing(draft, snapshot, plan.get("target_seconds", 90)))
        artifacts["screenplay"] = draft
        final = _final_reviews(call, context, draft, stats, record, generation)
        record(f"FINAL_REVIEW_BOUND_{generation:02}", {"draft_sha256": text_sha(draft),
                                                       "issues": final["issues"],
                                                       "content": final.get("content"), "timing": final.get("timing")})
        if not final["issues"]:
            return {"draft": draft, "selected_chapters": framework["selected_chapter_indices"],
                    "binding": {"version": VERSION, "draft_sha256": text_sha(draft),
                                "source_sha256": digest(source), "source_pack_sha256": digest(pack),
                                "artifact_hashes": {name: digest(value) for name, value in artifacts.items()},
                                "chapter_fact_reviews_sha256": digest(material_reviews),
                                "framework_review_sha256": digest(framework_review),
                                "snapshot_review_sha256": digest(snapshot_review),
                                "design_review_sha256": digest(design_review),
                                "final_content_sha256": digest(final["content"]),
                                "final_timing_sha256": digest(final["timing"]),
                                "root_repairs": generation, "invalidations": invalidations,
                                "semantic_status": "machine_review_passed_awaiting_independent_review",
                                "media_acceptance": False}}
        if generation == limit:
            raise ProductionRejected("final", final["issues"], "root_repair_limit_reached")
        diagnosis = diagnose_issues(call, final["issues"], artifacts, pack, context, final["measured"],
                                    record=record, attempt=generation, local_route=plan.get("local_route"))
        record(f"ROOT_CAUSE_BOUND_{generation:02}", diagnosis)
        stage, corrections = diagnosis["responsible_stage"], diagnosis["diagnoses"]
        invalidation = {"generation": generation, "responsible_stage": stage,
                        "invalidated": invalidated_stages(stage),
                        "invalidated_artifact_hashes": {key: digest(value) for key, value in artifacts.items()
                                                       if key in invalidated_stages(stage)},
                        "diagnosis_sha256": digest(diagnosis)}
        invalidations.append(invalidation); record(f"INVALIDATION_{generation:02}", invalidation)
        for key in invalidated_stages(stage):
            if key != "materials":
                artifacts.pop(key, None)
    raise ValueError("v5_unreachable_production_state")

