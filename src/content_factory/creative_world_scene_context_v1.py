"""Pure world/scene/ensemble extension; no dispatch, state invention or approval.

The old screenplay projection is a private syntax check only. Every actual
writer/source/review payload retains the full new native objects. Frozen
workflows and the unrelated screenplay_world prototype are not modified.
"""
from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from . import creative_goal_source_contract_v4 as goals
from . import creative_autonomous_text_contract_v1 as text_contract
from . import creative_goal_drama_audit_contract_v9 as goal_evidence
from . import creative_legal_speech_scope_v2 as scope
from . import creative_scoped_source_review_v2 as source_review
from . import creative_goal_context_workflow_v24 as ownership

VERSION = "creative_world_scene_context/v1"
GOAL_VERSION = "creative_world_scene_goal/v1"
SCRIPT_VERSION = "creative_world_scene_screenplay/v1"
REVIEW_VERSION = "creative_world_scene_review_extension/v1"
digest = goal_evidence.digest
CORE_KEYS = ("source_packet", "verified_legal_context", "reference_fulltext",
             "expression_standards", "production_preferences", "user_goal_contract")
EXECUTION_RULE = (
    "world_frame是原生剧本前置框架及共享来源，不是角色必须口述的剧情claim。"
    "复用已有角色/场景/claims，不再复制一套人物或事实表；具体新设定仍须真实来源/虚构归属审查。"
    "同类角色/场景/道具/拍与claim的ID不可重复，世界关系与空间连接只能引用本稿已声明的ID。"
    "scene_contexts给每个剧情情境的故事时间、地点、环境差异和前场承接；相同地点可多次出现。"
    "present_character_ids指本情境实际参与演员，不证明第一时点已在屋内；进出仍须正文实际动作。"
    "每拍ensemble恰好覆盖其情境参与者，听者不因不说话而省略。动作只引用本拍action步骤索引；"
    "原生expression写明当前神情，holds允许安静保持/继续原动作，不为填字段新增操作。"
    "parallel_with只声明action与dialogue可并行，不填秒数；steps是文档定位序，不独自证明动作完成的时间序。"
    "场次ID唯一、按首次出现顺序登记；第一场previous_context_id=null且relation=opening，"
    "之后明确链接前一场；本拍所有action索引须存在且kind=action，并行dialogue索引须kind=dialogue。"
    "正文拍ID与顺序必须恰好等于本份whole_plan.beats；每拍关联scene_context的scene_id必须等于该规划拍scene_id。"
    "离开一个情境后再次返回须登记新的context occurrence，不复用旧context ID；parallel_with配对不可重复。"
    "模型提交完整新规划/完整新稿；编译不补世界、神情、入场或状态。"
)


def obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def string(blank=False):
    return {"type": "string", "minLength": 0 if blank else 1, **({} if blank else {"pattern": r"\S"})}


def array(item, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum}


def refs():
    return {"type": "array", "items": string(), "uniqueItems": True}


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def _ids(goal, group):
    return [row["id"] for row in goal["whole_plan"][group]]


def _world_schema():
    return obj({"era_reality": string(), "social_context": string(), "prehistory": string(),
        "relationship_notes": array(obj({"character_ids": refs(), "description": string(), "claim_refs": refs()})),
        "spatial_connections": array(obj({"from_scene_id": string(), "to_scene_id": string(),
            "description": string(), "claim_refs": refs()})), "claim_refs": refs()})


def build_goal_schema(*, base_schema=None, **origin_options):
    schema_options = {key: value for key, value in origin_options.items()
        if key in ("max_characters", "origin_catalog", "preferences")}
    schema = deepcopy(base_schema or goals.build_goal_request_schema(**schema_options))
    _check(schema["properties"]["contract_version"].get("const") == goals.VERSION, "explicit v4 checking schema required")
    schema["properties"]["contract_version"] = {"const": GOAL_VERSION}
    plan = schema["properties"]["whole_plan"]
    plan["properties"]["world_frame"] = _world_schema()
    plan["required"].append("world_frame")
    Draft202012Validator.check_schema(schema)
    return schema


def legacy_goal_checking_projection(goal):
    """Private checking object; never label it a native model response."""
    value = deepcopy(goal)
    value["whole_plan"].pop("world_frame")
    value["contract_version"] = goals.VERSION
    return value


def validate_goal(goal, *, origin_options=None):
    options = origin_options or {}
    Draft202012Validator(build_goal_schema(**options)).validate(goal)
    claims = {row["id"] for row in goal["claims"]}
    actors, scenes = set(_ids(goal, "characters")), set(_ids(goal, "scenes"))
    _check(len(claims) == len(goal["claims"]), "duplicate original claim ID")
    for group in ("characters", "scenes", "props", "beats"):
        _check(len(set(_ids(goal, group))) == len(_ids(goal, group)), "duplicate original " + group + " ID")
    for beat in goal["whole_plan"]["beats"]:
        _check(beat["scene_id"] in scenes and beat["actor_id"] in actors
            and set(beat["claim_refs"]) <= claims, "original beat has unknown actor/scene/claim")
    frame = goal["whole_plan"]["world_frame"]
    _check(set(frame["claim_refs"]) <= claims, "world cites undeclared claim")
    for row in frame["relationship_notes"]:
        _check(bool(row["character_ids"]) and set(row["character_ids"]) <= actors, "world relationship has unknown/empty actor")
        _check(set(row["claim_refs"]) <= claims, "world relationship cites undeclared claim")
    for row in frame["spatial_connections"]:
        _check(row["from_scene_id"] in scenes and row["to_scene_id"] in scenes, "world spatial connection has unknown scene")
        _check(set(row["claim_refs"]) <= claims, "world spatial connection cites undeclared claim")
    if origin_options is not None:
        goals.validate_goal_document(legacy_goal_checking_projection(goal), **options)
    return {"valid": True, "native_goal_sha256": digest(goal), "world_sha256": digest(frame),
        "external_origin_catalog_checked": origin_options is not None,
        "source_semantic_approved": False, "private_projection_is_not_native": True}


def _brief(goal):
    return {"selected_candidate_id": "native_goal:" + digest(goal),
        "characters": [{key: row[key] for key in ("id", "name", "role")} for row in goal["whole_plan"]["characters"]]}


def build_script_schema(goal, *, base_schema=None):
    validate_goal(goal)
    schema = deepcopy(base_schema or text_contract.build_script_schema(_brief(goal)))
    schema["properties"].update(contract_version={"const": SCRIPT_VERSION}, native_goal_sha256={"const": digest(goal)})
    schema["required"] += ["contract_version", "native_goal_sha256", "scene_contexts"]
    scene = obj({"id": string(), "scene_id": {"enum": _ids(goal, "scenes")},
        "story_time": obj({"label": string(), "relation": {"enum": ["opening", "continuous", "later", "earlier", "parallel"]}}),
        "previous_context_id": {"type": ["string", "null"]}, "environment_delta": string(True),
        "present_character_ids": {"type": "array", "items": {"enum": _ids(goal, "characters")}, "minItems": 1, "uniqueItems": True}})
    schema["properties"]["scene_contexts"] = array(scene, 1)
    index = {"type": "integer", "minimum": 0}
    performance = obj({"action_step_indexes": {"type": "array", "items": index, "minItems": 1, "uniqueItems": True},
        "expression": string(), "mode": {"enum": ["holds", "reacts", "acts"]}})
    beat = schema["properties"]["beats"]["items"]
    beat_ids = _ids(goal, "beats")
    schema["properties"]["beats"].update(minItems=len(beat_ids), maxItems=len(beat_ids))
    beat["properties"]["id"] = {"enum": beat_ids}
    beat["properties"].update(scene_context_id=string(), ensemble={"type": "object",
        "propertyNames": {"enum": _ids(goal, "characters")}, "additionalProperties": array(performance, 1), "minProperties": 1},
        parallel_with=array(obj({"action_step_index": index, "dialogue_step_index": index})))
    beat["required"] += ["scene_context_id", "ensemble", "parallel_with"]
    beat["properties"]["parallel_with"]["uniqueItems"] = True
    schema["properties"]["beats"]["prefixItems"] = [
        {"properties": {"id": {"const": beat_id}}} for beat_id in beat_ids]
    Draft202012Validator.check_schema(schema)
    return schema


def legacy_script_checking_projection(script):
    return {"title": script["title"], "premise": script["premise"], "beats": [
        {key: deepcopy(beat[key]) for key in ("id", "event", "trigger", "steps")} for beat in script["beats"]]}


def validate_script(script, goal, *, base_schema=None):
    Draft202012Validator(build_script_schema(goal, base_schema=base_schema)).validate(script)
    text_contract.compile_script(legacy_script_checking_projection(script), _brief(goal))
    expected = [row["id"] for row in goal["whole_plan"]["beats"]]
    _check([b["id"] for b in script["beats"]] == expected, "script must retain complete original beat IDs and order")
    contexts = {row["id"]: row for row in script["scene_contexts"]}
    _check(len(contexts) == len(script["scene_contexts"]), "duplicate scene context ID")
    for i, context in enumerate(script["scene_contexts"]):
        previous = script["scene_contexts"][i-1]["id"] if i else None
        _check(context["previous_context_id"] == previous, "scene context must link the previous original context")
        _check((context["story_time"]["relation"] == "opening") == (i == 0), "opening relation only belongs to first scene context")
    seen_contexts = []
    previous_context = None
    for beat_index, beat in enumerate(script["beats"]):
        cid = beat["scene_context_id"]
        _check(cid in contexts, "unknown scene context")
        _check(contexts[cid]["scene_id"] == goal["whole_plan"]["beats"][beat_index]["scene_id"],
            "scene header must retain the current native planned scene")
        if cid not in seen_contexts:
            seen_contexts.append(cid)
        elif cid != previous_context:
            raise ValueError("returning to a scene requires a new explicit scene-context occurrence")
        previous_context = cid
        _check(set(beat["ensemble"]) == set(contexts[cid]["present_character_ids"]), "ensemble must cover every scene participant, including silent listeners")
        for step in beat["steps"]:
            if step["kind"] == "dialogue":
                _check(step["speaker"] in beat["ensemble"], "speaker is not a scene participant")
        for performances in beat["ensemble"].values():
            for performance in performances:
                for index in performance["action_step_indexes"]:
                    _check(index < len(beat["steps"]) and beat["steps"][index]["kind"] == "action", "ensemble action index must address an actual current action step")
        pairs = set()
        for row in beat["parallel_with"]:
            a, d = row["action_step_index"], row["dialogue_step_index"]
            _check(a < len(beat["steps"]) and d < len(beat["steps"])
                and beat["steps"][a]["kind"] == "action" and beat["steps"][d]["kind"] == "dialogue", "parallel relation requires current action and dialogue steps")
            _check((a, d) not in pairs, "duplicate parallel relation")
            pairs.add((a, d))
    _check(seen_contexts == list(contexts), "scene contexts must be used in first-occurrence order, without unused contexts")
    return {"valid": True, "native_script_sha256": digest(script), "native_goal_sha256": digest(goal),
        "document_order_is_performance_time": False, "semantic_quality_approved": False,
        "text_ready_for_director": False, "missing_fields_filled": False}


def compile_script(script, goal, brief=None):
    """Preserve the complete native object; label deterministic compilation.

    The selected ID is a compile artifact, not an added native response field.
    Native response validation and actual review binding still use ``script``
    supplied to this function, never its compiled result interchangeably.
    """
    validate_script(script, goal)
    actual_brief = _brief(goal) if brief is None else brief
    _check(actual_brief.get("selected_candidate_id") == "native_goal:" + digest(goal),
        "compiled brief must bind the complete native goal, not its private legacy projection")
    _check(set(row["id"] for row in actual_brief["characters"]) == set(_ids(goal, "characters")),
        "compiled brief actor identity differs from native goal")
    projection = legacy_script_checking_projection(script)
    old = text_contract.compile_script(projection, actual_brief)
    compiled = {**deepcopy(script), "selected_candidate_id": old["selected_candidate_id"]}
    return {"script": compiled, "manifest": {"schema": VERSION + "/compiled_screenplay_manifest",
        "native_goal_sha256": digest(goal), "native_script_sha256": digest(script),
        "compiled_script_sha256": digest(compiled), "private_checking_projection_sha256": digest(projection),
        "native_and_compiled_are_distinct": True, "invented_world_actions_or_expression": False,
        "text_ready_for_director": False}}


def _strings(value, prefix):
    if isinstance(value, str) and value:
        yield prefix, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(child, prefix + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, prefix + "." + str(index))


def build_evidence_catalog(goal, script):
    validate_script(script, goal)
    result = {key: {**row, "role": "planning_context_not_performed_event"}
        for key, row in goal_evidence.build_evidence_catalog(goal).items()}
    for ref, row in text_contract.evidence_catalog(legacy_script_checking_projection(script)).items():
        result[ref] = {"document_path": row["path"].replace("script.", "native_script_document.", 1),
            "quote": row["quote"], "role": "actual_step", "kind": row["kind"], "beat_id": row["beat_id"], "speaker": row["speaker"]}
    for ci, context in enumerate(script["scene_contexts"]):
        for field in ("story_time.label", "environment_delta"):
            value = context["story_time"]["label"] if field == "story_time.label" else context[field]
            if value:
                result[f"H:{context['id']}:{field}"] = {"document_path": f"native_script_document.scene_contexts.{ci}.{field}",
                    "quote": value, "role": "scene_context_not_performed_event", "context_id": context["id"]}
    for bi, beat in enumerate(script["beats"]):
        for actor, rows in beat["ensemble"].items():
            for i, row in enumerate(rows):
                result[f"P:{beat['id']}:{actor}:{i}"] = {"document_path": f"native_script_document.beats.{bi}.ensemble.{actor}.{i}.expression",
                    "quote": row["expression"], "role": "native_performance_instruction", "beat_id": beat["id"],
                    "character_id": actor, "action_step_indexes": deepcopy(row["action_step_indexes"])}
    return result


def _request(stage, profile, rule, payload, schema, *, manifest=None, provenance=None):
    role = "writer" if stage in ("goal_plan", "complete_script") else "director"
    parameters = {**deepcopy(profile[role]["parameters"]), **deepcopy(profile.get("stage_parameters", {}).get(stage, {}))}
    request = {"stage": stage, "role": role, "model": profile[role]["model"],
        "messages": [{"role": "system", "content": rule}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
        "parameters": parameters, "structured_schema": schema,
        "input_provenance": {**deepcopy(provenance or {}), "world_scene_contract_version": VERSION, "context_sha256": digest(payload)}}
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    return {"request": request, "request_sha256": digest(request), "wire": expected_wire_request(request),
        "manifest": {"schema": VERSION + "/manifest", "context_sha256": digest(payload), **(manifest or {})},
        "provider_calls": 0, "production_dispatch_eligible": False, "complete_production_chain_connected": False}


def adapt_goal_request(prepared):
    result = deepcopy(prepared)
    request = result["request"]
    _check(request["stage"] == "goal_plan", "whole-plan preparation required; no extra world stage")
    schema = build_goal_schema(base_schema=request["structured_schema"])
    payload = json.loads(request["messages"][1]["content"])
    payload["coordinator_output_contract"] = {"schema": VERSION + "/execution_requirements",
        "world_frame_once": True, "scene_and_ensemble_required": True, "not_character_dialogue_requirement": True}
    output = _request("goal_plan", {"writer": {"model": request["model"], "parameters": request["parameters"]}},
        request["messages"][0]["content"] + "\n" + EXECUTION_RULE, payload, schema,
        manifest={**deepcopy(prepared.get("manifest", {})), "base_request_sha256": digest(request), "new_paid_stage_added": False},
        provenance=request.get("input_provenance"))
    return output


def prepare_writer_request(inputs, profile, goal, *, opening_setup, base_schema=None):
    validate_goal(goal)
    _check(opening_setup.get("goal_sha256") == digest(goal), "opening setup is not bound to the exact new native goal")
    projected = ownership.project_inputs(inputs)
    payload = {key: deepcopy(projected[key]) for key in CORE_KEYS}
    feedback_identity = {}
    for key in ("previous_complete_document", "revision_diagnostics"):
        if key in projected:
            payload[key] = deepcopy(projected[key])
            feedback_identity[key + "_sha256"] = digest(projected[key])
    payload.update(native_goal_document=deepcopy(goal), native_opening_setup_document=deepcopy(opening_setup),
        coordinator_output_contract={"schema": VERSION + "/execution_requirements", "not_character_dialogue_requirement": True})
    reference = projected["reference_fulltext"]
    occurrences = sum(value.count(reference) for _, value in _strings(payload, "payload")) if reference else 0
    _check(occurrences == 1, "writer request must contain the actual complete R01 once")
    return _request("complete_script", profile, ownership.AUTHOR_RULE + "\n" + EXECUTION_RULE, payload,
        build_script_schema(goal, base_schema=base_schema), manifest={"native_goal_sha256": digest(goal), "raw_inputs_sha256": digest(inputs),
            "projected_inputs_sha256": digest(projected), "reference_occurrences": occurrences,
            "preserved_feedback_identity": feedback_identity,
            "inherited_author_rule_sha256": digest(ownership.AUTHOR_RULE),
            "four_native_audits_not_validated_by_this_adapter": True})


def prepare_scope_request(profile, goal):
    validate_goal(goal)
    built = scope.build_scope_context(goal)
    context = built["manifest"]["scope_context_sha256"]
    return _request("goal_audit", profile, scope.SCOPE_RULE, built["payload"],
        scope.build_scope_schema(goal, context_sha256=context), manifest={"native_goal_sha256": digest(goal), "scope_context_sha256": context,
            "world_in_complete_source_frame": True})


def prepare_source_request(profile, goal, native_scope, source_context):
    validate_goal(goal)
    built = source_review.build_review_context(goal, native_scope, source_context)
    context = built["manifest"]["audit_context_sha256"]
    return _request("goal_audit", profile, source_review.REVIEW_RULE, built["payload"],
        source_review.build_review_schema(goal, native_scope, source_context, context_sha256=context),
        manifest={"native_goal_sha256": digest(goal), "source_review_context_sha256": context, "world_in_complete_source_frame": True})


def review_fragment(goal, script):
    catalog = build_evidence_catalog(goal, script)
    targets = {"world": [ref for ref, row in catalog.items() if row["document_path"].startswith("whole_plan.world_frame.")]}
    for context in script["scene_contexts"]:
        targets["scene:" + context["id"]] = [ref for ref in catalog if ref.startswith("H:" + context["id"] + ":")]
    for beat in script["beats"]:
        for actor in beat["ensemble"]:
            targets[f"ensemble:{beat['id']}:{actor}"] = [ref for ref in catalog if ref.startswith(f"P:{beat['id']}:{actor}:")]
    return {"schema": VERSION + "/review_targets", "native_goal_sha256": digest(goal), "native_script_sha256": digest(script),
        "targets": targets, "source_directory": {ref: {key: row[key] for key in ("document_path", "role")} for ref, row in catalog.items()},
        "parallel_relations": {beat["id"]: deepcopy(beat["parallel_with"]) for beat in script["beats"]},
        "document_order_is_performance_time": False, "background_is_actual_event": False}


def augment_semantic_request(prepared, goal, script):
    """Requires an already rebuilt core review bound to the full new objects.

    This does not adapt an old checking projection into a new native review.
    Physical/temporal schema adaptation remains an explicit integration gap.
    """
    result = deepcopy(prepared); request = result["request"]
    payload = json.loads(request["messages"][1]["content"])
    _check(payload.get("review_part") == "semantic" and payload.get("native_goal_document") == goal
        and payload.get("native_script_document") == script, "core semantic request must retain full new native goal and screenplay")
    fragment = review_fragment(goal, script)
    payload["world_scene_review_context"] = fragment
    schema = deepcopy(request["structured_schema"])
    _check("world_scene_checks" not in schema["properties"], "review fragment already attached")
    extension = build_review_extension_schema(goal, script)
    for key in ("world_scene_checks", "world_scene_context_sha256"):
        schema["properties"][key] = extension["properties"][key]
        schema["required"].append(key)
    _check("schema" in schema["properties"], "explicit new core review identity required")
    for key, expected in (("goal_sha256", digest(goal)), ("goal_contract_sha256", digest(goal)),
                          ("script_sha256", digest(script))):
        if key in schema["properties"]:
            _check(schema["properties"][key].get("const") == expected,
                "core semantic identity must bind the actual new native object: " + key)
    schema["properties"]["schema"] = {"const": REVIEW_VERSION}
    if "context_sha256" in schema["properties"]:
        schema["properties"]["context_sha256"] = {"const": digest(payload)}
    rule = request["messages"][0]["content"] + "\n" + EXECUTION_RULE + (
        "world_scene_checks完整覆盖当前targets；每项pass须引用自身相关G/H/P；涉及已发生动作或物件状态时对照实际E，"
        "核时代/空间/故事时间/参与者和前后承接；听者神情动作可以保持，不能只数speaker。"
        "H/G背景不证明事件已演出，P神情不替代法律条件或物件操作；parallel只是可并行，不是已排秒。"
        "fail写完整新稿/新规划的功能缺口，unknown保留；本扩展不替代原全文检查。")
    prepared = _request("full_review", {"director": {"model": request["model"], "parameters": request["parameters"]}},
        rule, payload, schema, manifest={"base_request_sha256": digest(request), "native_goal_sha256": digest(goal),
            "native_script_sha256": digest(script), "review_targets_sha256": digest(fragment), "core_review_validation_not_performed": True,
            "physical_parallel_order_adapter_connected": False}, provenance=request.get("input_provenance"))
    return prepared


def build_review_extension_schema(goal, script):
    fragment = review_fragment(goal, script); catalog = build_evidence_catalog(goal, script)
    rows = {}
    for key, own in fragment["targets"].items():
        row = obj({"status": {"enum": ["pass", "fail", "unknown"]}, "reason": string(),
            "evidence": {"type": "array", "items": {"enum": list(catalog)}, "minItems": 1, "uniqueItems": True},
            "required_revision": {"type": "string"}})
        row["allOf"] = [
            {"if": {"properties": {"status": {"const": "pass"}}}, "then": {"properties": {
                "required_revision": {"const": ""}, "evidence": {"contains": {"enum": own}}}}},
            {"if": {"properties": {"status": {"const": "fail"}}}, "then": {"properties": {"required_revision": string()}}}]
        rows[key] = row
    return obj({"schema": {"const": REVIEW_VERSION}, "world_scene_context_sha256": {"const": digest(fragment)},
        "world_scene_checks": obj(rows)})


def validate_review_extension(document, goal, script):
    fragment = review_fragment(goal, script); catalog = build_evidence_catalog(goal, script)
    projection = {key: document[key] for key in ("schema", "world_scene_context_sha256", "world_scene_checks") if key in document}
    Draft202012Validator(build_review_extension_schema(goal, script)).validate(projection)
    _check(document.get("schema") == REVIEW_VERSION and set(document.get("world_scene_checks", {})) == set(fragment["targets"]),
        "complete new native context review is required")
    failures, unknowns = [], []
    for key, row in document["world_scene_checks"].items():
        _check(set(row) == {"status", "reason", "evidence", "required_revision"} and row["status"] in ("pass", "fail", "unknown")
            and isinstance(row["reason"], str) and row["reason"].strip(), "malformed context review row")
        _check(row["evidence"] and set(row["evidence"]) <= set(catalog), "review cites unknown or absent source")
        if row["status"] == "pass":
            _check(not row["required_revision"] and set(row["evidence"]) & set(fragment["targets"][key]), "pass needs own context evidence and no revision")
        elif row["status"] == "fail":
            _check(bool(row["required_revision"].strip()), "failure requires complete native revision guidance")
            failures.append(key)
        else:
            unknowns.append(key)
    return {"valid": True, "extension_accepted": not failures and not unknowns, "findings": failures, "uncertainties": unknowns,
        "complete_same_source_review": False, "text_ready_for_director": False, "semantic_meaning_proven": False}


def build_segment_context(goal, script, beat_id, snapshot, *, snapshot_kind, expected_snapshot_sha256,
                          snapshot_qualifier=None):
    validate_script(script, goal)
    _check(snapshot_kind in ("native_opening_setup", "accepted_local_performance_end", "approved_service_original_tail"), "unqualified snapshot origin")
    _check(digest(snapshot) == expected_snapshot_sha256, "current snapshot identity changed")
    _check(callable(snapshot_qualifier), "upstream snapshot qualification verifier is required")
    proof = snapshot_qualifier(snapshot, snapshot_kind=snapshot_kind, snapshot_sha256=expected_snapshot_sha256,
        native_goal_sha256=digest(goal), native_script_sha256=digest(script), beat_id=beat_id)
    _check(type(proof) is dict and proof.get("verified") is True and proof.get("snapshot_kind") == snapshot_kind
        and proof.get("snapshot_sha256") == expected_snapshot_sha256 and proof.get("native_goal_sha256") == digest(goal)
        and proof.get("native_script_sha256") == digest(script) and proof.get("beat_id") == beat_id,
        "snapshot qualification rejected or bound to another state")
    index = [beat["id"] for beat in script["beats"]].index(beat_id); beat = script["beats"][index]
    scene = next(row for row in script["scene_contexts"] if row["id"] == beat["scene_context_id"])
    return {"schema": VERSION + "/segment_context", "native_goal_sha256": digest(goal), "native_script_sha256": digest(script),
        "world_frame": deepcopy(goal["whole_plan"]["world_frame"]),
        "characters": deepcopy(goal["whole_plan"]["characters"]), "scenes": deepcopy(goal["whole_plan"]["scenes"]),
        "props": deepcopy(goal["whole_plan"]["props"]), "current_scene_context": deepcopy(scene), "current_beat": deepcopy(beat),
        "snapshot": {"kind": snapshot_kind, "sha256": expected_snapshot_sha256, "value": deepcopy(snapshot), "upstream_proof": deepcopy(proof)},
        "previous_script_event": None if not index else {"beat_id": script["beats"][index-1]["id"], "event": script["beats"][index-1]["event"]},
        "previous_script_event_is_verified_executed": False,
        "upcoming_locked_event": None if index+1 == len(script["beats"]) else {"beat_id": script["beats"][index+1]["id"], "event": script["beats"][index+1]["event"]},
        "upcoming_event_is_already_executed": False, "snapshot_qualification_proven_by_this_function": False,
        "actual_media_request_connected": False, "production_dispatch_eligible": False}


def render_script(script, goal):
    validate_script(script, goal)
    world = goal["whole_plan"]["world_frame"]; actors = {row["id"]: row for row in goal["whole_plan"]["characters"]}
    scenes = {row["id"]: row for row in goal["whole_plan"]["scenes"]}; contexts = {row["id"]: row for row in script["scene_contexts"]}
    lines = ["# " + script["title"], "", "原生完整剧本；机器验收、用户审美与视频人工审核分别记录。", "", "## 世界框架", "",
        world["era_reality"], world["social_context"], world["prehistory"]]
    lines += [row["description"] for row in world["relationship_notes"]]
    lines += [row["description"] for row in world["spatial_connections"]]
    lines += ["", "## 故事前提", "", script["premise"], "", "## 人物", ""]
    for actor in actors.values():
        lines += ["### " + actor["name"], "身份：" + actor["role"]]
        for label, key in (("人物档案", "profile"), ("开场处境", "initial_state"), ("当下目标", "want")):
            value = actor[key]
            shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            lines += [label + "：\n" + shown]
    last = None
    for beat in script["beats"]:
        context = contexts[beat["scene_context_id"]]
        if context["id"] != last:
            source = scenes[context["scene_id"]]
            lines += ["", "## 场次 " + context["id"], "时间：" + context["story_time"]["label"], "地点：" + source["description"],
                "环境：" + source["appearance"] + ("；" + context["environment_delta"] if context["environment_delta"] else ""),
                "参与人物：" + "、".join(actors[c]["name"] for c in context["present_character_ids"]),
                "承接：" + str(context["previous_context_id"]) + " / " + context["story_time"]["relation"]]
            last = context["id"]
        lines += ["", "### " + beat["id"] + " " + beat["event"],
            "当拍情境：" + context["story_time"]["label"] + "｜" + scenes[context["scene_id"]]["description"]
            + "｜在场：" + "、".join(actors[c]["name"] for c in context["present_character_ids"])
            + "｜承接场次：" + (context["previous_context_id"] or "开场"), "刺激：" + beat["trigger"]]
        for i, step in enumerate(beat["steps"]):
            lines += [(actors[step["speaker"]]["name"] + "：" if step["kind"] == "dialogue" else "动作：") + step["text"]]
            for actor, performances in beat["ensemble"].items():
                for performance in performances:
                    if i in performance["action_step_indexes"]:
                        lines += [actors[actor]["name"] + "的神情（" + performance["mode"] + "）：" + performance["expression"]]
        for relation in beat["parallel_with"]:
            lines += [f"并行安排：动作步骤{relation['action_step_index']}与对白步骤{relation['dialogue_step_index']}；实际秒数留导演/局部表演。"]
    return "\n\n".join(lines) + "\n"
