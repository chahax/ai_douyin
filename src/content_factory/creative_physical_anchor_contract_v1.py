"""Candidate source/observation contract with independent physical role axes.

This module is not installed in any frozen production runtime. It accepts no
legacy anchor aliases and makes no geometric or semantic inference from prose.
Models extract source constraints and before-action observations independently;
the local gate compares only explicit, matching dimensions and references.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v1 as base
from . import creative_autonomous_text_contract_v2 as sources

VERSION = "creative_physical_anchor_contract/v1"
DIMENSIONS = ("scene", "support", "container", "holder", "spatial_reference", "orientation", "visibility")
VALUES = {
    "scene": ["located_in"], "support": ["on_surface", "unsupported"],
    "container": ["inside", "outside"], "holder": ["held_by", "no_holder"],
    "spatial_reference": ["in_front_of", "beside", "same_side_as", "opposite"],
    "orientation": ["face_up", "face_down", "upright", "sideways"],
    "visibility": ["visible", "occluded", "partially_occluded"],
}
SOURCE_RULE = (
    "只读冻结brief，逐初态实体分别解析七维物理约束：所在scene、承载support、容器container、"
    "当前持有holder、空间参照spatial_reference、朝向orientation、遮挡visibility。"
    "人物面前/物件旁属于空间参照，不表示人物持物，也不替代所在场景或承载表面；桌面不是人物。"
    "所在场景不能证明位于该场景任意表面；同一场景里的桌面与地面仍不同。"
    "只有来源明确限定才known，无法判断unknown；来源确实没有限定该维度可unconstrained，"
    "不能把已经给出的限定遗漏为unconstrained。每known引用source_catalog对应真实原片段。"
    "holder_character_id=null只表明当前无人持有，不表明所有权、空间参照或容器位置。"
    "不从旧稿推源约束，不发明新实体或新起态，不把结尾状态当初态。按Schema完整简明提交。")
ACTUAL_RULE = (
    "只读完整实际正文与实体标识，还原第一步动作之前的物理状态，七维独立填写。"
    "不读或复制源期望；人物面前/纸旁不是holder或scene。每个known引用真实steps并说明时间依据："
    "earliest是首步直接陈述的初态，reconstructed_before_first_action是首步动作前提明确证明的此前状态，"
    "例如首步从容器取出可证明此前在容器内；late_only只是较晚时刻，不能当最初状态已知满足。"
    "移开遮挡物露出东西不能被描述成此前一直无遮挡；物件在后续出现不能自动回填最初位置。"
    "无法还原用unknown，不用源故事或摘要脑补。保持scene/support/container/holder/"
    "spatial_reference/orientation/visibility角色分离，不改正文。按Schema完整简明提交。")


def _digest(value):
    return base._digest(value)


def source_catalog(brief):
    result = {"initial_scene": str(brief.get("initial_state", {}).get("scene_id", ""))}
    result.update({"initial:" + kind + ":" + entity: text for (kind, entity), text in sources._states(brief).items()})
    result.update({"fact:" + key: text for key, text in sources._facts(brief).items()})
    result.update({"scene:" + row["id"]: row.get("description", "") for row in brief.get("scenes", [])})
    for row in brief.get("initial_state", {}).get("prop_states", []):
        if "holder_character_id" in row:
            result["holder:prop:" + row["id"]] = "holder_character_id=" + (
                "null" if row["holder_character_id"] is None else str(row["holder_character_id"]))
    return result


def _references(brief):
    states = sources._states(brief)
    return {"scene": base._ids(brief, "scenes", "scene_ids"),
        "scene_surface": base._ids(brief, "scenes", "scene_ids"),
        "prop": list(dict.fromkeys(base._ids(brief, "props", "prop_ids") +
                                   [entity for kind, entity in states if kind == "prop"])),
        "character": base._characters(brief), "none": [""], "unspecified": [""]}


def _atom(dimension, brief, actual=False, entries=None):
    kinds = {"scene": ["scene"], "support": ["scene_surface", "prop", "none"],
        "container": ["prop", "none"], "holder": ["character", "none"],
        "spatial_reference": ["character", "prop"], "orientation": ["none"], "visibility": ["none"]}[dimension]
    properties = {"knowledge": {"enum": ["known", "unknown"] + ([] if actual else ["unconstrained"])},
        "value": {"enum": VALUES[dimension] + ["unspecified"]},
        "reference_type": {"enum": kinds + ["unspecified"]}, "reference_id": {"type": "string"},
        "explanation": base._text()}
    if dimension == "support":
        properties["surface_kind"] = {"enum": ["table", "floor", "seat", "shelf", "wall", "other", "unspecified"],
            "description": "承载表面类型，独立于所在scene和人物空间参照；other不能由程序确定具体表面是否同一。"}
    if actual:
        refs = list(entries)
        properties.update(evidence_refs=base._array_refs(refs, 0), temporal_basis={
            "enum": ["earliest", "reconstructed_before_first_action", "later_only", "unknown"],
            "description": "首步证据才能直接或据动作前提还原最初状态；late_only只证明较晚时刻。"})
    else:
        properties["source_refs"] = {"type": "array", "uniqueItems": True, "items": base._obj({
            "source_id": {"enum": list(source_catalog(brief))}, "quote": base._text()})}
    row = base._obj(properties)
    row["allOf"] = []
    for kind in kinds + ["unspecified"]:
        row["allOf"].append({"if": {"properties": {"reference_type": {"const": kind}}},
            "then": {"properties": {"reference_id": {"enum": _references(brief)[kind]}}}})
    known = {"value": {"enum": VALUES[dimension]},
        "evidence_refs" if actual else "source_refs": {"minItems": 1}}
    row["allOf"].append({"if": {"properties": {"knowledge": {"const": "known"}}}, "then": {"properties": known}})
    if actual and entries:
        row["allOf"].append({"if": {"properties": {"knowledge": {"const": "known"},
            "temporal_basis": {"enum": ["earliest", "reconstructed_before_first_action"]}}},
            "then": {"properties": {"evidence_refs": {"contains": {"const": next(iter(entries))}}}}})
    elif not actual:
        row["allOf"].append({"if": {"properties": {"knowledge": {"const": "unconstrained"}}},
            "then": {"properties": {"value": {"const": "unspecified"},
                "reference_type": {"const": "unspecified"}, "reference_id": {"const": ""}}}})
    reference_roles = {"located_in": ["scene"], "on_surface": ["scene_surface", "prop"],
        "unsupported": ["none"], "inside": ["prop"], "outside": ["prop", "none"],
        "held_by": ["character"], "no_holder": ["none"],
        **{value: ["character", "prop"] for value in VALUES["spatial_reference"]},
        **{value: ["none"] for value in VALUES["orientation"] + VALUES["visibility"]}}
    for value in VALUES[dimension]:
        row["allOf"].append({"if": {"properties": {"value": {"const": value}, "knowledge": {"const": "known"}}},
            "then": {"properties": {"reference_type": {"enum": reference_roles[value]}}}})
    return row


def _schema(brief, script=None):
    actual = script is not None
    entries = base.evidence_catalog(script) if actual else None
    states = sources._states(brief)
    variants = [base._obj({"entity_type": {"const": kind}, "entity_id": {"const": entity},
        "dimensions": base._obj({dimension: _atom(dimension, brief, actual, entries) for dimension in DIMENSIONS})})
        for kind, entity in states]
    return base._obj({"brief_sha256": {"const": _digest(brief)},
        "script_sha256" if actual else "source_catalog_sha256": {
            "const": _digest(script) if actual else _digest(source_catalog(brief))},
        "states": {"type": "array", "minItems": len(states), "maxItems": len(states),
            "items": {"oneOf": variants} if variants else False,
            "description": "每初态实体恰一次；七个role独立，未知不作为满足，unconstrained只用于源确未限定的维度。"}})


def build_source_schema(brief):
    return _schema(brief)


def build_actual_schema(script, brief):
    return _schema(brief, script)


def _validate(value, brief, script=None):
    actual = script is not None
    base._validate_schema(_schema(brief, script), value, "actual_physics" if actual else "source_physics")
    if actual and base.compile_script({key: deepcopy(item) for key, item in script.items()
                                      if key != "selected_candidate_id"}, brief) != script:
        raise ValueError("actual physical extraction must bind an unchanged compiler-bound script")
    keys = [(row["entity_type"], row["entity_id"]) for row in value["states"]]
    if len(keys) != len(set(keys)) or set(keys) != set(sources._states(brief)):
        raise ValueError("physical states must cover each original initial entity exactly once")
    if not actual:
        catalog = source_catalog(brief)
        for row in value["states"]:
            for atom in row["dimensions"].values():
                for ref in atom["source_refs"]:
                    if not ref["quote"].strip() or ref["quote"] not in catalog[ref["source_id"]]:
                        raise ValueError("physical source quote must be a true fragment of its bound frozen source")
    return {"complete": True, "source_hash": _digest(value), "brief_sha256": _digest(brief),
        "script_sha256": _digest(script) if actual else None, "native_text_changed": False,
        "semantic_extraction_model_owned": True, "legacy_anchor_aliases_accepted": False}


def validate_source(value, brief):
    return _validate(value, brief)


def validate_actual(value, script, brief):
    return _validate(value, brief, script)


def decide(source, actual, script, brief):
    sv, av = validate_source(source, brief), validate_actual(actual, script, brief)
    observed = {(row["entity_type"], row["entity_id"]): row for row in actual["states"]}
    requirements, uncertainties, unconstrained = [], [], []
    for expected in source["states"]:
        entity = expected["entity_type"], expected["entity_id"]
        for dimension, target in expected["dimensions"].items():
            row = observed[entity]["dimensions"][dimension]
            item = {"entity_type": entity[0], "entity_id": entity[1], "dimension": dimension,
                "source_atom": deepcopy(target), "actual_atom": deepcopy(row),
                "code": "PHYSICAL_" + entity[0].upper() + "_" + entity[1] + "_" + dimension.upper()}
            if target["knowledge"] == "unconstrained":
                unconstrained.append(item)
                continue
            fields = ["value", "reference_type", "reference_id"] + (["surface_kind"] if dimension == "support" else [])
            unknown = (target["knowledge"] == "unknown" or row["knowledge"] == "unknown" or
                       row["temporal_basis"] in ("later_only", "unknown") or
                       (dimension == "support" and target["reference_type"] == row["reference_type"] == "scene_surface"
                        and (target["surface_kind"] in ("other", "unspecified") or
                             row["surface_kind"] in ("other", "unspecified"))))
            if unknown:
                item["problem"] = "必要物理维度或最初状态证据未知，不能由另一role或较晚状态补齐。"
                uncertainties.append(item)
            elif any(target[key] != row[key] for key in fields):
                item["mismatched_fields"] = [key for key in fields if target[key] != row[key]]
                item["problem"] = "同一物理维度存在明确不相容值。"
                item["required_revision"] = "冻结源不变，由生成模型提交完整新稿兑现明确物理约束；不改元数据迁就当前稿。"
                requirements.append(item)
    source_unknown = any(item["source_atom"]["knowledge"] == "unknown" for item in uncertainties)
    return {"status": "needs_whole_revision" if requirements else "halt_source_uncertain" if source_unknown else
            "halt_physical_uncertain" if uncertainties else "source_constrained_physics_ready",
        "validation": {"source": sv, "actual": av}, "revision_requirements": requirements,
        "uncertainties": uncertainties, "unconstrained_dimensions_not_certified": unconstrained,
        "source_sha256": _digest(source), "actual_sha256": _digest(actual), "script_sha256": _digest(script),
        "brief_sha256": _digest(brief), "native_text_changed": False, "legacy_initial_state_approved": False,
        "other_text_or_scene_gates_replaced": False, "human_quality_approved": False,
        "creative_quality_passed": False, "automatic_media_submit": False}
