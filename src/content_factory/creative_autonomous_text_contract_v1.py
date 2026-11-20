"""Reusable autonomous text contracts; semantic decisions do not edit model prose.

The brief owns facts, allowed people and scenes. Models own the plan and whole
script. The compiler adds only source identity. Evidence is restricted to actual
performed steps, never internal summaries. This module has no service calls.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from jsonschema import Draft202012Validator

VERSION = "creative_autonomous_text_contract/v1"
CRITERIA = {
    "role_clarity": "言语施事、受事、说话人与指代清楚，不能混淆谁要求谁做什么。",
    "turn_responsiveness": "回应能作用于前面压力；有意回避、反问、沉默或动作回答均可成立。",
    "dramatic_progression": "人物尝试、阻力和策略变化在实际正文中兑现，不以摘要替代演出。",
    "ending_payoff": "结尾选择和可见结果接住前面的交锋；允许动作收束和仍未解决的争议。",
    "spoken_register": "话语符合人物与当面关系，诉求能听懂；正常公务口语不按词禁处理。",
    "factual_physical": "事实、人物、场景和物件动作前提一致；不得新增无来源的事实来补因果。",
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _obj(properties):
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


def _text():
    return {"type": "string", "minLength": 1}


def _ids(brief, plural, alternate):
    if alternate in brief:
        rows = brief[alternate]
    else:
        rows = brief.get(plural, [])
        if not isinstance(rows, list):
            raise ValueError(plural + " must be an array")
        rows = [r.get("id") if isinstance(r, dict) else r for r in rows]
    if not isinstance(rows, list) or any(not isinstance(x, str) or not x.strip() for x in rows):
        raise ValueError(plural + " IDs must be nonempty strings")
    if len(rows) != len(set(rows)):
        raise ValueError(plural + " IDs must be unique")
    return rows


def _characters(brief):
    result = _ids(brief, "characters", "character_ids")
    if not result:
        raise ValueError("at least one allowed character is required")
    return result


def _facts(brief):
    return _ids(brief, "facts", "fact_ids")


def _actors(brief):
    # A company can be the subject of a spoken proposition without becoming a
    # third on-screen person. The brief must explicitly declare that subject.
    return list(dict.fromkeys(_characters(brief) + _ids(brief, "actors", "actor_ids")))


def _source_id(brief):
    value = brief.get("selected_candidate_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("brief.selected_candidate_id is required")
    return value


def _array_refs(ids, minimum=1):
    result = {"type": "array", "uniqueItems": True, "minItems": minimum,
              "items": {"type": "string", "enum": ids} if ids else False}
    if not ids:
        result["maxItems"] = 0
    return result


def build_plan_schema(brief):
    people = _characters(brief)
    _source_id(brief)
    goal = _obj({"character_id": {"enum": people}, "objective": _text(), "obstacle": _text()})
    beat = _obj({
        "id": _text(), "trigger": _text(), "attempt": _text(),
        "acting_character_id": {"enum": people},
        "target_character_id": {"enum": people + [""]},
        "state_change": _text(), "fact_refs": _array_refs(_facts(brief), 0),
    })
    return _obj({
        "title": _text(), "dramatic_question": _text(), "audience_arc": _text(),
        "character_goals": {"type": "array", "minItems": len(people),
                            "maxItems": len(people), "items": goal},
        "beats": {"type": "array", "minItems": 1, "items": beat},
        "ending": _obj({"attempt_result": _text(), "visible_consequence": _text(),
                        "open_problem": _text()}),
    })


def build_script_schema(brief):
    people = _characters(brief)
    _source_id(brief)
    step = _obj({"kind": {"enum": ["action", "dialogue"]},
                 "speaker": {"type": "string"}, "text": _text()})
    step["allOf"] = [
        {"if": {"properties": {"kind": {"const": "dialogue"}}},
         "then": {"properties": {"speaker": {"enum": people}}}},
        {"if": {"properties": {"kind": {"const": "action"}}},
         "then": {"properties": {"speaker": {"const": ""}}}},
    ]
    beat = _obj({"id": _text(), "event": _text(), "trigger": _text(),
                 "steps": {"type": "array", "minItems": 1, "items": step}})
    return _obj({"title": _text(), "premise": _text(),
                 "beats": {"type": "array", "minItems": 1, "items": beat}})


def _validate_schema(schema, value, label):
    errors = sorted(Draft202012Validator(schema).iter_errors(value),
                    key=lambda e: tuple(str(p) for p in e.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(p) for p in error.absolute_path) or "root"
        raise ValueError(label + "." + path + ": " + error.message)


def _unique_beats(beats):
    ids = [b["id"] for b in beats]
    if len(ids) != len(set(ids)):
        raise ValueError("beat IDs must be unique")


def validate_plan(value, brief):
    _validate_schema(build_plan_schema(brief), value, "plan")
    _unique_beats(value["beats"])
    if {g["character_id"] for g in value["character_goals"]} != set(_characters(brief)):
        raise ValueError("plan.character_goals must cover every allowed character exactly once")
    return {"source_hash": _digest(value), "brief_sha256": _digest(brief),
            "complete": True, "beat_count": len(value["beats"]),
            "semantic_quality_approved": False}


def compile_script(raw, brief):
    _validate_schema(build_script_schema(brief), raw, "script")
    _unique_beats(raw["beats"])
    result = deepcopy(raw)
    result["selected_candidate_id"] = _source_id(brief)
    return result


def evidence_catalog(script):
    """Stable E IDs for each actual step text, including actions and dialogue."""
    result = {}
    for bi, beat in enumerate(script["beats"]):
        for si, step in enumerate(beat["steps"]):
            ref = "E" + str(len(result) + 1).zfill(4)
            result[ref] = {"path": f"script.beats.{bi}.steps.{si}.text",
                           "quote": step["text"], "kind": step["kind"],
                           "speaker": step["speaker"], "beat_id": beat["id"]}
    return result


def build_review_schema(script, brief):
    entries = evidence_catalog(script)
    refs = _array_refs(list(entries))
    dialogue_ids = [k for k, v in entries.items() if v["kind"] == "dialogue"]
    criterion = _obj({
        "criterion": {"enum": list(CRITERIA)}, "status": {"enum": ["pass", "fail", "unknown"]},
        "explanation": _text(), "evidence_refs": deepcopy(refs),
        "required_revision": {"type": "string"},
    })
    reading = _obj({
        "source_ref": {"enum": dialogue_ids} if dialogue_ids else False,
        "interpreted_actor": {"enum": _actors(brief) + ["unspecified"]},
        "interpreted_action": _text(), "interpreted_object": _text(),
        "clarity": {"enum": ["clear", "ambiguous", "unknown"]},
        "register": {"enum": ["conversational", "stilted", "unknown"]},
        "function": {"enum": ["responsive", "redundant", "unknown"]},
    })
    issue = _obj({"code": _text(), "evidence_refs": deepcopy(refs),
                  "problem": _text(), "required_revision": _text()})
    suggestion = _obj({"code": _text(), "evidence_refs": deepcopy(refs), "assessment": _text()})
    return _obj({
        "script_sha256": {"const": _digest(script)},
        "criteria": {"type": "array", "minItems": len(CRITERIA),
                     "maxItems": len(CRITERIA), "items": criterion},
        "dialogue_readings": {"type": "array", "minItems": len(dialogue_ids),
                              "maxItems": len(dialogue_ids), "items": reading},
        "issues": {"type": "array", "items": issue},
        "suggestions": {"type": "array", "items": suggestion},
    })


def validate_review(value, script, brief):
    body = {k: deepcopy(v) for k, v in script.items() if k != "selected_candidate_id"}
    if compile_script(body, brief) != script:
        raise ValueError("review script differs from compiler-bound complete source")
    _validate_schema(build_review_schema(script, brief), value, "review")
    keys = [r["criterion"] for r in value["criteria"]]
    if len(keys) != len(set(keys)) or set(keys) != set(CRITERIA):
        raise ValueError("review.criteria must cover all six criteria exactly once")
    entries = evidence_catalog(script)
    expected = {k for k, row in entries.items() if row["kind"] == "dialogue"}
    actual = [row["source_ref"] for row in value["dialogue_readings"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("review.dialogue_readings must cover every dialogue exactly once")
    return {"source_hash": _digest(value), "script_sha256": _digest(script),
            "brief_sha256": _digest(brief), "complete": True,
            "criteria_count": len(keys), "dialogue_count": len(actual),
            "performed_step_evidence_only": True, "semantic_quality_approved": False}


def decide_review(review, script, brief):
    """Route explicit semantic readings, even when the model leaves issues empty."""
    validation = validate_review(review, script, brief)
    entries = evidence_catalog(script)
    requirements, uncertainties = [], []

    def add(target, code, refs, problem, revision):
        evidence = [{"ref_id": ref, "path": entries[ref]["path"],
                     "quote": entries[ref]["quote"]} for ref in refs]
        target.append({"code": code, "evidence_refs": evidence,
                       "evidence_text": "\n".join(row["quote"] for row in evidence),
                       "problem": problem, "required_revision": revision})

    for row in review["criteria"]:
        if row["status"] == "fail":
            add(requirements, "CRITERION_" + row["criterion"].upper(), row["evidence_refs"],
                row["explanation"], row["required_revision"] or
                "完整重写并修复该功能缺陷：" + CRITERIA[row["criterion"]])
        elif row["status"] == "unknown":
            add(uncertainties, "UNCERTAIN_" + row["criterion"].upper(), row["evidence_refs"],
                row["explanation"], row["required_revision"] or "核实该项，不能将未知写为通过。")
    for row in review["dialogue_readings"]:
        ref = row["source_ref"]
        actual = entries[ref]["quote"]
        meaning = ("审查解读施事=" + row["interpreted_actor"] + "，行动=" +
                   row["interpreted_action"] + "，对象=" + row["interpreted_object"])
        for field in ("clarity", "register", "function"):
            if row[field] == "unknown":
                add(uncertainties, "DIALOGUE_" + field.upper() + "_UNKNOWN", [ref],
                    meaning + "；该项无法确定。", "核实当前完整上下文中的实际含义和作用。")
        if row["clarity"] == "ambiguous":
            add(requirements, "DIALOGUE_AMBIGUOUS", [ref], meaning + "；施事、对象或指代有歧义。",
                "由生成模型提交完整新稿，明确谁要求谁做什么，不把作者解释写入人物对白。")
        if row["register"] == "stilted":
            add(requirements, "DIALOGUE_STILTED", [ref], "当面措辞生硬：" + actual,
                "完整新稿中按人物身份、关系与当前诉求重组织这条话语，不只替换同义词或依赖词禁。")
        if row["function"] == "redundant":
            add(requirements, "DIALOGUE_REDUNDANT", [ref], "当前话轮没有改变前面压力或行动：" + actual,
                "完整新稿中删除无功能重复或改变人物尝试；允许回应不同压力时复现同一事实。")
    for issue in review["issues"]:
        add(requirements, issue["code"], issue["evidence_refs"], issue["problem"], issue["required_revision"])

    # Preserve distinct diagnoses while suppressing exact duplicate payloads.
    unique = {}
    for requirement in requirements:
        unique.setdefault(_digest(requirement), requirement)
    requirements = list(unique.values())
    status = ("halt_review_uncertain" if uncertainties else
              "needs_whole_revision" if requirements else "text_ready_for_director")
    return {"status": status, "script_sha256": _digest(script),
            "review_sha256": _digest(review), "validation": validation,
            "revision_requirements": requirements, "uncertainties": uncertainties,
            "human_quality_approved": False, "human_approved": False,
            "creative_quality_passed": False, "automatic_media_submit": False,
            "decision_basis": "explicit_same_source_semantic_review_not_human_adoption"}
