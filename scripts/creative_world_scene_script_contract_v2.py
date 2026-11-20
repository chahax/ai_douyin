"""Pure wire-schema repair and complete structural screenplay diagnostics.

No creative normalization, service, source mutation or semantic approval.
Frozen world/v28 remain unchanged; callers explicitly inject this contract.
"""
from copy import deepcopy
import re

from jsonschema import Draft202012Validator

from src.content_factory import creative_world_scene_context_v1 as world

VERSION = "creative_world_scene_script_contract/v2"
RELATION_RULE = (
    "Structural relationships are checked locally against the same native goal: scene-context IDs are unique and ordered by first use; "
    "each context links the preceding context ID, first has null/opening and later contexts have nonempty predecessor/non-opening; "
    "each beat's context resolves to that planned beat's scene; ensemble keys equal its scene participants, dialogue speakers participate; "
    "ensemble indexes address current action steps, parallel pairs address current action/dialogue steps and are unique; "
    "returning after another context requires a new occurrence ID. Step document order is not performance time."
)


def _split_array(node):
    """Apply full items independently of prefixItems under draft2020-12."""
    if "items" not in node or "prefixItems" not in node:
        raise ValueError("expected complete item schema and positional prefix constraints")
    full, prefix = node.pop("items"), node.pop("prefixItems")
    node.setdefault("allOf", []).extend([{"items": full}, {"prefixItems": prefix}])


def refine_schema(schema):
    result = deepcopy(schema)
    if result.get("$comment") == VERSION:
        # A version label alone cannot certify an unrepaired original schema.
        try:
            beat_parts = result["properties"]["beats"]["allOf"]
            scene_parts = result["properties"]["scene_contexts"]["allOf"]
            assert "items" not in result["properties"]["beats"] and "prefixItems" not in result["properties"]["beats"]
            assert beat_parts[-2]["items"]["properties"]["steps"]["type"] == "array"
            assert isinstance(beat_parts[-1]["prefixItems"], list)
            assert scene_parts[-2]["items"]["type"] == "object"
            first = scene_parts[-1]["prefixItems"][0]["properties"]
            assert first["previous_context_id"] == {"const": None}
            assert first["story_time"]["properties"]["relation"] == {"const": "opening"}
        except (KeyError, TypeError, IndexError, AssertionError) as exc:
            raise ValueError("refined schema identity lacks its actual full-item constraints") from exc
        Draft202012Validator.check_schema(result)
        return result
    beats = result["properties"]["beats"]
    _split_array(beats)
    scenes = result["properties"]["scene_contexts"]
    if "items" not in scenes or "prefixItems" in scenes:
        raise ValueError("expected original full scene-context item schema without prefixes")
    full = scenes.pop("items")
    first = {"properties": {"previous_context_id": {"const": None},
        "story_time": {"properties": {"relation": {"const": "opening"}}, "required": ["relation"]}},
        "required": ["previous_context_id", "story_time"]}
    later = {"properties": {"previous_context_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "story_time": {"properties": {"relation": {"enum": ["continuous", "later", "earlier", "parallel"]}},
            "required": ["relation"]}}, "required": ["previous_context_id", "story_time"]}
    scenes.setdefault("allOf", []).extend([{"items": full}, {"prefixItems": [first], "items": later}])
    for array in (beats, scenes): array["description"] = (array.get("description", "") + " " + RELATION_RULE).strip()
    result["$comment"] = VERSION
    Draft202012Validator.check_schema(result)
    return result


def _schema(goal, base_schema):
    if base_schema is not None and "contract_version" in base_schema.get("properties", {}):
        original = base_schema
    else:
        original = world.build_script_schema(goal, base_schema=base_schema)
    return refine_schema(original)


def _path(parts):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts) if parts else "/"


def _observed(value):
    # Complete original values stay in the unmodified native document once.
    # Diagnostics describe structural shape rather than echo whole scene/steps.
    if type(value) is dict: return {"json_type": "object", "keys": list(value), "value_retained_in_native_document": True}
    if type(value) is list: return {"json_type": "array", "length": len(value), "value_retained_in_native_document": True}
    if isinstance(value, str) and len(value) > 512:
        return {"json_type": "string", "characters": len(value), "sha256": world.digest(value), "value_retained_in_native_document": True}
    return deepcopy(value)


def diagnose(script, goal, base_schema=None):
    world.validate_goal(goal)
    schema = _schema(goal, base_schema)
    findings = []
    def add(code, path, expected, actual, **details):
        row = {"code": code, "path": path, "expected": deepcopy(expected), "actual": _observed(actual), **details}
        if not any(item["path"] == path and item["expected"] == row["expected"] and item["actual"] == row["actual"] for item in findings):
            findings.append(row)
    for error in sorted(Draft202012Validator(schema).iter_errors(script), key=lambda e: (tuple(map(str, e.absolute_path)), tuple(map(str, e.absolute_schema_path)))):
        if error.validator == "required" and type(error.instance) is dict:
            for key in error.validator_value:
                if key not in error.instance:
                    add("SCRIPT_SCHEMA_REQUIRED", _path([*error.absolute_path, key]), "required field", None,
                        field_present=False, rule="required", schema_path=_path(error.absolute_schema_path))
            continue
        if error.validator == "additionalProperties" and error.validator_value is False and type(error.instance) is dict:
            allowed = error.schema.get("properties", {})
            patterns = error.schema.get("patternProperties", {})
            for key in error.instance:
                if key not in allowed and not any(re.search(pattern, key) for pattern in patterns):
                    add("SCRIPT_SCHEMA_ADDITIONALPROPERTIES", _path([*error.absolute_path, key]), "no undeclared field", error.instance[key],
                        rule="additionalProperties", schema_path=_path(error.absolute_schema_path))
            continue
        add("SCRIPT_SCHEMA_" + error.validator.upper(), _path(error.absolute_path), error.validator_value, error.instance,
            rule=error.validator, schema_path=_path(error.absolute_schema_path))
    if type(script) is dict:
        if script.get("native_goal_sha256") != world.digest(goal):
            add("NATIVE_GOAL_IDENTITY", "/native_goal_sha256", world.digest(goal), script.get("native_goal_sha256"))
        contexts = script.get("scene_contexts")
        beats = script.get("beats")
        if type(contexts) is list and type(beats) is list:
            context_bank, context_index = {}, {}
            for ci, context in enumerate(contexts):
                if type(context) is not dict: continue
                cid = context.get("id")
                if isinstance(cid, str):
                    if cid in context_bank: add("SCENE_CONTEXT_ID_DUPLICATE", f"/scene_contexts/{ci}/id", "unique scene-context ID", cid)
                    else: context_bank[cid], context_index[cid] = context, ci
                previous = contexts[ci-1].get("id") if ci and type(contexts[ci-1]) is dict else None
                if context.get("previous_context_id") != previous:
                    add("SCENE_CONTEXT_PREDECESSOR", f"/scene_contexts/{ci}/previous_context_id", previous, context.get("previous_context_id"))
                relation = context.get("story_time", {}).get("relation") if type(context.get("story_time")) is dict else None
                if (relation == "opening") != (ci == 0):
                    add("SCENE_CONTEXT_OPENING", f"/scene_contexts/{ci}/story_time/relation",
                        "opening" if ci == 0 else ["continuous", "later", "earlier", "parallel"], relation)
            seen, last = [], None
            planned = goal["whole_plan"]["beats"]
            for bi, beat in enumerate(beats):
                if type(beat) is not dict: continue
                if bi < len(planned) and beat.get("id") != planned[bi]["id"]:
                    add("BEAT_ID_ORDER", f"/beats/{bi}/id", planned[bi]["id"], beat.get("id"))
                cid = beat.get("scene_context_id")
                if not isinstance(cid, str) or cid not in context_bank:
                    add("BEAT_CONTEXT_UNKNOWN", f"/beats/{bi}/scene_context_id", list(context_bank), cid)
                    continue
                context, ci = context_bank[cid], context_index[cid]
                if bi < len(planned) and context.get("scene_id") != planned[bi]["scene_id"]:
                    add("BEAT_PLANNED_SCENE_MISMATCH", f"/scene_contexts/{ci}/scene_id", planned[bi]["scene_id"], context.get("scene_id"),
                        related_path=f"/beats/{bi}/scene_context_id", native_goal_path=f"/whole_plan/beats/{bi}/scene_id", beat_id=beat.get("id"))
                if cid not in seen: seen.append(cid)
                elif cid != last:
                    add("SCENE_CONTEXT_RETURN_REUSED", f"/beats/{bi}/scene_context_id", "new occurrence ID after leaving a context", cid)
                last = cid
                ensemble, steps = beat.get("ensemble"), beat.get("steps")
                participants = context.get("present_character_ids")
                if type(ensemble) is not dict or type(participants) is not list or any(not isinstance(x, str) for x in participants): continue
                if set(ensemble) != set(participants):
                    add("ENSEMBLE_PARTICIPANT_COVERAGE", f"/beats/{bi}/ensemble", sorted(set(participants)), sorted(ensemble))
                if type(steps) is not list: continue
                actions = [i for i, step in enumerate(steps) if type(step) is dict and step.get("kind") == "action"]
                dialogues = [i for i, step in enumerate(steps) if type(step) is dict and step.get("kind") == "dialogue"]
                for si in dialogues:
                    if steps[si].get("speaker") not in ensemble:
                        add("DIALOGUE_SPEAKER_NOT_PRESENT", f"/beats/{bi}/steps/{si}/speaker", sorted(ensemble), steps[si].get("speaker"))
                for actor, rows in ensemble.items():
                    if type(rows) is not list: continue
                    for pi, performance in enumerate(rows):
                        indexes = performance.get("action_step_indexes") if type(performance) is dict else None
                        if type(indexes) is not list: continue
                        for ii, index in enumerate(indexes):
                            if type(index) is not int or index not in actions:
                                add("ENSEMBLE_ACTION_INDEX", _path(["beats", bi, "ensemble", actor, pi, "action_step_indexes", ii]), actions, index)
                pairs = set(); parallel = beat.get("parallel_with")
                if type(parallel) is list:
                    for pi, row in enumerate(parallel):
                        if type(row) is not dict: continue
                        a, d = row.get("action_step_index"), row.get("dialogue_step_index")
                        for field, value, choices in (("action_step_index", a, actions), ("dialogue_step_index", d, dialogues)):
                            if type(value) is not int or value not in choices:
                                add("PARALLEL_TYPED_INDEX", f"/beats/{bi}/parallel_with/{pi}/{field}", choices, value)
                        if type(a) is int and type(d) is int:
                            if (a, d) in pairs: add("PARALLEL_PAIR_DUPLICATE", f"/beats/{bi}/parallel_with/{pi}", "unique action/dialogue pair", row)
                            pairs.add((a, d))
            if seen != list(context_bank):
                add("SCENE_CONTEXT_FIRST_USE_ORDER", "/scene_contexts", seen, list(context_bank))
    # Preserve the old validator's remaining structural checks as a backstop;
    # its failure is never turned into a hand-repaired script or semantic pass.
    if not findings:
        try: world.validate_script(script, goal)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            add("EXISTING_STRUCTURAL_CHECK", "/", "all existing world structural checks", type(exc).__name__, message=str(exc)[:512])
    return {"schema": VERSION + "/diagnostic", "valid": not findings, "findings": findings,
        "native_script_sha256": world.digest(script), "native_goal_sha256": world.digest(goal),
        "wire_schema_sha256": world.digest(schema), "native_document_modified": False,
        "schema_check_complete": True, "structural_relationships_checked": True,
        "document_order_is_performance_time": False, "semantic_quality_approved": False, "text_ready_for_director": False}


class ScriptContractError(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = self.detail = deepcopy(diagnostic)
        super().__init__("complete native screenplay structural contract rejected; see diagnostic.findings")


def validate(script, goal, base_schema=None):
    diagnostic = diagnose(script, goal, base_schema)
    if not diagnostic["valid"]: raise ScriptContractError(diagnostic)
    return diagnostic
