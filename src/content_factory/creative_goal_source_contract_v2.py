"""Native whole-story goals with typed provenance; no semantic or quality verdict.

This independent contract does not edit a frozen brief or infer actions from prose.
Its validator verifies structure, declared provenance and referential integrity.
Whether a claim was classified honestly, an emotion is readable or a consequence
is dramatically effective belongs to a separate evidence-bearing goal review.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable
from typing import Any

from jsonschema import Draft202012Validator


VERSION = "creative_goal_source_v2"
CLAIM_KINDS = (
    "user_constraint", "user_audience_goal", "platform_metadata",
    "verified_legal", "creative_choice", "inference",
)
GOAL_PLANNING_RULE = """提交完整的新目标与整片计划，不修改或拼接旧冻结简报。
用户约束、用户观感目标、平台元数据、已核实法律、虚构创作选择和未核实推断分开登记。
热度与标签仅说明选题信号，不证明法律、原视频剧情或观众的真实感受；创作选择不能冒充来源事实。
规划具体人物诉求、关系阻力、刺激如何引起反应、话轮策略如何推进和可观察的场内结果。
法律争议可以保持开放，不能把法律结果未定等同于本场没有选择、回应或后果。
不预写唯一结尾，不强制金钱胜诉、口号、道歉、爽文或额外角色；不使用禁词表替代话轮功能。
整片规划负责因果与情绪；完整正文负责有目的的对白和关键行为；局部表演负责反应窗口、动作前提及共享状态；
确定性编译负责引用、状态与时间。整片计划不填逐秒动作、机位或所有朝向。
来源分类与戏剧功能需要独立同源语义复审，字段齐全或本地合同通过不能作为创作质量通过。"""


class GoalContractError(ValueError):
    """A machine-contract failure, with a stable class for offline routing."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _text() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "pattern": r"\S"}


def _id() -> dict[str, Any]:
    return {"type": "string", "minLength": 1,
            "pattern": r"^[A-Za-z][A-Za-z0-9_.:-]*$"}


def _refs(*, minimum: int = 0, maximum: int = 24) -> dict[str, Any]:
    return {"type": "array", "items": _id(), "minItems": minimum,
            "maxItems": maximum, "uniqueItems": True}


def _origin_refs() -> dict[str, Any]:
    # Real catalog IDs include names such as tag:劳动争议. Internal entity IDs
    # remain portable ASCII, but external authority IDs retain their exact text.
    return {"type": "array", "items": _text(), "minItems": 0,
            "maxItems": 24, "uniqueItems": True}


def _rows(item: dict[str, Any], minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "array", "items": item, "minItems": minimum,
            "maxItems": maximum}


def build_goal_request_schema() -> dict[str, Any]:
    """The exact outgoing and incoming native goal schema, returned independently."""
    nullable_id = {"anyOf": [_id(), {"type": "null"}]}
    nullable_text = {"anyOf": [_text(), {"type": "null"}]}
    claims = _obj({
        "id": _id(), "kind": {"type": "string", "enum": list(CLAIM_KINDS)},
        "text": _text(), "origin_ids": _origin_refs(), "basis_claim_refs": _refs(),
    })
    # Honest typing still requires semantic review; these conditions prevent a
    # declared creative choice from being promoted mechanically to an authority.
    claims["allOf"] = [
        {"if": {"properties": {"kind": {"enum": list(CLAIM_KINDS[:4])}}},
         "then": {"properties": {"origin_ids": {"minItems": 1},
                                    "basis_claim_refs": {"maxItems": 0}}}},
        {"if": {"properties": {"kind": {"enum": ["creative_choice", "inference"]}}},
         "then": {"properties": {"origin_ids": {"maxItems": 0}}}},
        {"if": {"properties": {"kind": {"const": "inference"}}},
         "then": {"properties": {"basis_claim_refs": {"minItems": 1}}}},
    ]
    character = _obj({
        "id": _id(), "name": _text(), "role": _text(),
        "profile": _obj({"gender_presentation": _text(), "age_presentation": _text(),
                          "appearance": _text(), "wardrobe": _text()}),
        "want": _text(), "pressure": _text(),
        "initial_state": _obj({"scene_id": _id(), "posture": _text(), "location": _text()}),
    })
    scene = _obj({"id": _id(), "description": _text(), "appearance": _text()})
    prop = _obj({
        "id": _id(), "description": _text(), "initial_state": _text(),
        "holder_character_id": nullable_id, "owner_character_id": nullable_id,
        "support": {"anyOf": [_obj({"entity_type": {"enum": ["scene", "prop", "actor"]}, "entity_id": _id()}),
                              {"type": "null"}]},
        "orientation": nullable_text,
    })
    beat = _obj({
        "id": _id(), "scene_id": _id(), "actor_id": _id(),
        "goal": _text(), "resistance": _text(), "stimulus": _text(),
        "response": _text(),
        "strategy": _obj({"before": _text(), "after": _text(),
                           "effect": {"enum": ["establishes", "maintains", "changes", "abandons"]}}),
        "visible_change": _text(), "claim_refs": _refs(minimum=1),
    })
    plan = _obj({
        "premise": _text(),
        "audience_path": _obj({"starting_feeling": _text(), "target_shift": _text(),
                               "emotional_landing": _text(), "claim_refs": _refs(minimum=1)}),
        "characters": _rows(character, 1, 4), "scenes": _rows(scene, 1, 4),
        "props": _rows(prop, 0, 24), "beats": _rows(beat, 2, 16),
        "ending": _obj({"attempt_result": _text(), "visible_consequence": _text(),
                        "emotional_landing": _text(), "open_legal_question": _text(),
                        "evidence_beat_ids": _refs(minimum=1), "claim_refs": _refs(minimum=1)}),
    })
    schema = _obj({"contract_version": {"const": VERSION},
                   "claims": _rows(claims, 1, 96), "whole_plan": plan})
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def _external_ids(values: Iterable[str], label: str) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", f"{label} must be an ID collection")
    values = list(values)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", f"{label} contains a blank or non-string ID")
    if len(values) != len(set(values)):
        raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", f"{label} repeats an ID")
    return set(values)


def _index(rows: list[dict[str, Any]], path: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["id"] in result:
            raise GoalContractError("GOAL_DUPLICATE_ID", f"{path}: {row['id']}")
        result[row["id"]] = row
    return result


def _require_refs(refs: Iterable[str], ids: set[str], path: str) -> None:
    missing = set(refs) - ids
    if missing:
        raise GoalContractError("GOAL_REFERENCE_UNKNOWN", f"{path}: {sorted(missing)}")


def _reject_cycles(edges: dict[str, list[str]], path: str) -> None:
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(item: str) -> None:
        if item in visiting:
            raise GoalContractError("GOAL_REFERENCE_CYCLE", f"{path}: {item}")
        if item in done:
            return
        visiting.add(item)
        for parent in edges.get(item, []):
            visit(parent)
        visiting.remove(item)
        done.add(item)

    for item in edges:
        visit(item)


def validate_goal_document(document: dict[str, Any], *, source_ids: Iterable[str],
                           legal_ids: Iterable[str], user_constraint_ids: Iterable[str]) -> dict[str, Any]:
    """Validate a complete native plan without repairing it; return a deep copy.

    user_constraint_ids is the union of selected hard-constraint and audience-goal
    origin IDs. Each selected origin must be represented, not every platform row.
    A null owner means unspecified ownership; a null holder means not held by a
    character at the declared start. Neither is inferred from the other.
    """
    schema = build_goal_request_schema()
    errors = sorted(Draft202012Validator(schema).iter_errors(document),
                    key=lambda error: "/".join(map(str, error.absolute_path)))
    if errors:
        error = errors[0]
        path = "/".join(map(str, error.absolute_path)) or "$"
        raise GoalContractError("GOAL_SCHEMA_INVALID", f"{path}: {error.message}")
    catalogs = {
        "platform_metadata": _external_ids(source_ids, "source_ids"),
        "verified_legal": _external_ids(legal_ids, "legal_ids"),
        "user_constraint": _external_ids(user_constraint_ids, "user_constraint_ids"),
    }
    catalogs["user_audience_goal"] = catalogs["user_constraint"]
    groups = [catalogs["platform_metadata"], catalogs["verified_legal"], catalogs["user_constraint"]]
    if any(groups[a] & groups[b] for a in range(len(groups)) for b in range(a + 1, len(groups))):
        raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", "authority namespaces overlap")
    claims = _index(document["claims"], "claims")
    claim_ids = set(claims)
    covered_user: set[str] = set()
    for claim in claims.values():
        kind = claim["kind"]
        if kind in catalogs:
            unknown = set(claim["origin_ids"]) - catalogs[kind]
            if unknown:
                raise GoalContractError("GOAL_ORIGIN_CLASS_MISMATCH", f"{claim['id']} {kind}: {sorted(unknown)}")
            if kind in ("user_constraint", "user_audience_goal"):
                covered_user.update(claim["origin_ids"])
        _require_refs(claim["basis_claim_refs"], claim_ids, f"claims/{claim['id']}/basis_claim_refs")
    missing_user = catalogs["user_constraint"] - covered_user
    if missing_user:
        raise GoalContractError("GOAL_USER_REQUIREMENT_UNCOVERED", str(sorted(missing_user)))
    _reject_cycles({item: claim["basis_claim_refs"] for item, claim in claims.items()}, "claims")

    plan = document["whole_plan"]
    characters = _index(plan["characters"], "whole_plan/characters")
    scenes = _index(plan["scenes"], "whole_plan/scenes")
    props = _index(plan["props"], "whole_plan/props")
    beats = _index(plan["beats"], "whole_plan/beats")
    # Identity namespaces remain separate but cannot collide where a typed prop
    # support or later source compiler would otherwise be ambiguous.
    entity_groups = [set(characters), set(scenes), set(props)]
    if any(entity_groups[a] & entity_groups[b] for a in range(3) for b in range(a + 1, 3)):
        raise GoalContractError("GOAL_ENTITY_ID_COLLISION", "character, scene and prop IDs overlap")
    for actor in characters.values():
        _require_refs([actor["initial_state"]["scene_id"]], set(scenes), f"characters/{actor['id']}/initial_state")
    for prop in props.values():
        for key in ("holder_character_id", "owner_character_id"):
            if prop[key] is not None:
                _require_refs([prop[key]], set(characters), f"props/{prop['id']}/{key}")
        support = prop["support"]
        if support is not None:
            support_ids = {"scene": set(scenes), "prop": set(props), "actor": set(characters)}
            _require_refs([support["entity_id"]], support_ids[support["entity_type"]],
                          f"props/{prop['id']}/support")
            if prop["holder_character_id"] is not None and support != {
                    "entity_type": "actor", "entity_id": prop["holder_character_id"]}:
                raise GoalContractError("GOAL_INITIAL_HOLDER_SUPPORT_CONFLICT", f"prop {prop['id']}")
    _reject_cycles({item: [prop["support"]["entity_id"]]
                   if prop["support"] is not None and prop["support"]["entity_type"] == "prop" else []
                    for item, prop in props.items()}, "prop_support")
    for beat in beats.values():
        _require_refs([beat["scene_id"]], set(scenes), f"beats/{beat['id']}/scene_id")
        _require_refs([beat["actor_id"]], set(characters), f"beats/{beat['id']}/actor_id")
        _require_refs(beat["claim_refs"], claim_ids, f"beats/{beat['id']}/claim_refs")
        if not any(claims[ref]["kind"] == "creative_choice" for ref in beat["claim_refs"]):
            raise GoalContractError("GOAL_DRAMATIC_CHOICE_UNTRACED", f"beat {beat['id']} needs a declared creative choice")
    if not any(beat["strategy"]["effect"] in ("changes", "abandons") for beat in beats.values()):
        raise GoalContractError("GOAL_STRATEGY_SHIFT_MISSING", "whole plan declares no strategy change")
    audience = plan["audience_path"]
    _require_refs(audience["claim_refs"], claim_ids, "audience_path/claim_refs")
    if not any(claims[ref]["kind"] == "user_audience_goal" for ref in audience["claim_refs"]):
        raise GoalContractError("GOAL_AUDIENCE_UNTRACED", "audience path needs a user audience goal")
    ending = plan["ending"]
    _require_refs(ending["claim_refs"], claim_ids, "ending/claim_refs")
    _require_refs(ending["evidence_beat_ids"], set(beats), "ending/evidence_beat_ids")
    if plan["beats"][-1]["id"] not in ending["evidence_beat_ids"]:
        raise GoalContractError("GOAL_ENDING_UNTRACED", "final beat is absent from the ending evidence")
    if not any(claims[ref]["kind"] == "creative_choice" for ref in ending["claim_refs"]):
        raise GoalContractError("GOAL_DRAMATIC_CHOICE_UNTRACED", "ending needs a declared creative choice")
    return deepcopy(document)


def build_user_goal_contract() -> dict[str, Any]:
    """Map established user requirements, not an assistant-authored story draft."""
    return {
        "contract_version": VERSION + "/user_goals",
        "constraints": [
            {"id": "UC_COMPLETE_NATIVE", "text": "交付完整可制作正文；内容返修由生成模型提交完整新稿，再全文复审。",
             "source_quote": "内容返修由生成模型提交完整新稿，再全文复审；不要手动回填动作或拼接新旧剧本。"},
            {"id": "UC_REFERENCE_MECHANISM", "text": "借鉴参考片的表达机制，参考全文实际进入对应创作请求，不照搬剧情。",
             "source_quote": "使用项目已有的参考片与教学分析，借鉴表达机制，不照搬剧情；确认参考确实进入实际模型请求。"},
            {"id": "UC_NARRATIVE_ACTION", "text": "关键行为要传递信息或改变局势；不能靠无叙事作用的操作填时间。",
             "source_quote": "每镜明确新增信息、观察对象、刺激与反应、切镜理由，删除没有叙事作用的操作。"},
            {"id": "UC_AUTONOMOUS_NATIVE", "text": "修改可复用流程后生成完整新稿，不依赖逐稿人工补动作或固定句数。",
             "source_quote": "应该是你定位问题分析原因然后分析流程为什么出现这种问题然后修改流程然后从新流程跑一份剧本。"},
        ],
        "audience_goals": [
            {"id": "UG_EMOTION_CAUSAL_VISUAL", "text": "人物感受通过刺激、反应、策略和可见行为推进，事件具有因果。",
             "source_quote": "重点是情绪表达、事件因果和画面叙事，时长可以浮动。"},
            {"id": "UG_PLAIN_CHARACTER_SPEECH", "text": "对白直白自然，语言体现人物目的和双方立场，避免程序话术替代冲突。",
             "source_quote": "整体方向可以劳动合同不过可以剧情再白一点"},
            {"id": "UG_OPPONENT_RESPONSE", "text": "刺激会影响人物情绪，对手有自己的立场和回应。",
             "source_quote": "看到是个人原因的时候小林可以情绪扩散一下，人事也可以再公司角度回复"},
            {"id": "UG_CAUSAL_ENDING", "text": "结尾承接交锋，人物选择得到可观察回应或后果，并有情绪落脚点。",
             "source_quote": "这个结尾是不是太突兀了"},
        ],
        "planning_rules": [
            {"id": "RG_TYPED_ORIGIN", "text": "平台热度、法律事实和虚构选择分层；未知不能冒充核实。"},
            {"id": "RG_LOCAL_VS_LEGAL_RESULT", "text": "法律结论可以开放，本场仍需可观察的选择、回应或后果；不强制赔偿、胜诉或唯一结尾。"},
            {"id": "RG_FUNCTION_NOT_WORD_BAN", "text": "检查话轮和行为的作用，不用禁词、口号或固定情绪代替戏剧功能。"},
        ],
        "division_of_work": {
            "whole_plan": "人物诉求、阻力、情绪路径、策略、事件因果和场内结果。",
            "complete_script": "有目的的对白和关键行为；必要起态与行为前提保持一致。",
            "local_performance": "逐镜反应窗口、表演与共享状态；使用实际已选素材。",
            "deterministic_compile": "引用与状态前提、可行时间、下游失效范围。",
        },
        "limitations": [
            "这是用户要求映射，不是采用的故事稿、模型原生目标或用户对新稿的审美批准。",
            "本地合同只能检验结构与引用，来源语义和戏剧效果需同源全文审查；审查仍不能证明实际视频通过。",
        ],
    }
