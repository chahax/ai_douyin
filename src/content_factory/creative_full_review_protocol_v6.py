"""Native world/scene full review with evidence-based partial temporal order.

Two existing review calls, no dispatch. Private legacy views check unchanged
fields only; native v6 identities always bind the full new source documents.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError

from . import creative_full_review_protocol_v5 as previous
from . import creative_partial_order_review_v1 as partial
from . import creative_world_scene_context_v1 as world

VERSION = "creative_full_review_part/v6"
BUNDLE_VERSION = "creative_full_review_bundle/v6"
ADAPTER_VERSION = "creative_full_review_protocol/v6"
digest = previous.digest
PART_TABLES = previous.PART_TABLES
SOURCE_HEADERS = previous.SOURCE_HEADERS
OPENING_VERSION = "creative_world_scene_opening_setup/v1"

TEMPORAL_RULE = (
    "steps/E编号仅定位原文，不证明时间先后。temporal_relations只报告原文有据的最少关系："
    "completed_before_start表示前动作完成才开始后步骤；overlaps表示原文支持实际重叠。"
    "每条证据仅填两端实际E的逐字片段；G/H/P只阅读上下文，不填temporal证据。不能凭编号、排版或parallel_with推先后/重叠。"
    "关系不可自连、重复、成环，完成先后不能与重叠矛盾；两个审查包无需重复同一边集。"
    "前提只认精确setup状态或本包有据完成祖先E；并行许可、情境在场名单、神情不证明动作完成。"
    "同物同状态原子的未排明写入不能同时pass；唯有before=after=同一已核setup值的纯保持可相容。"
    "无足够证明应unknown/fail，不回退初态猜测。"
    "strict order的所有before引文均须在所有after引文之前；同E仅能用不重叠原文片段证明。"
    "逐句stimulus/reaction须本包有据先后或原文实际重叠；无刺激可明确null，不伪造反应。"
)
SEMANTIC_RULE = previous.SEMANTIC_RULE + TEMPORAL_RULE + (
    "新world_scene_checks恰好覆盖world/每场/每个在场角色神情；背景不要求角色口播，保持/聆听也可表演。"
    "H是故事时间/环境，P是神情指令，G/C是规划；都不能替代实际E中的执行、物件转移或法律事实。"
    "narrative_consistency_checks每拍及结尾比较同物件跨拍内容/持有/去向、意图与已做、初态与末态、"
    "策略改变的刺激与后果，并与该拍原规划及结尾逐字来源比较；开放未来结果用open_outcome，"
    "读不懂才用unresolved_reading且不得pass。readings是唯一引用记录，键定位完整原文，"
    "role为support/unresolved_counter/transition/context；未解反证不得pass。source_directory绑定规范原文路径。"
    "本版本evidence_catalog指source_directory中actual_step条目，路径不重复展开；T按consistency目录定位。"
    "pass须含自身规划目标及本拍实际E，不能只因引用存在就声称语义成立。"
)
PHYSICAL_RULE = previous.COMMON_RULE + TEMPORAL_RULE + (
    "仅物理职责，不带法律/参考/世界语义审查上下文。使用source_refs及typed preconditions/state_changes。"
    "holder_character_id仅人物ID/null，support_entity_id仅已声明实体ID/null，open仅bool/null，"
    "presence仅present/absent/unknown/null；location/posture仅原文支持的字符串/null。"
    "条件/变化entity须属于本行subjects，同atom不得重复；变化quote必须来自自身E。"
    "未证明前提established_by=null、actual_value=null、quote为空并判unknown/fail；pass不得这样填。"
    "所有权不等于持有，靠手边不等于在手里；取物前需存在/容器已开等真实必要前提。"
    "initial_checks覆盖该实体所有因果上最早的实际使用，后续动作不能倒填setup。"
)


def _error(code, reason, path=""):
    return {**previous._error(code, reason, path), "full_review_protocol_version": ADAPTER_VERSION,
        "native_version": VERSION, "source_order_used": False}


def _sources(script, goal, setup, brief):
    world.validate_goal(goal)
    raw = deepcopy(script)
    selected = raw.pop("selected_candidate_id", None)
    world.validate_script(raw, goal)
    compiled = world.compile_script(raw, goal, brief)["script"]
    if selected is None or compiled != script:
        raise ValueError("compiled new screenplay must round-trip exactly from raw native plus selected_candidate_id")
    if setup.get("schema") != OPENING_VERSION or setup.get("goal_sha256") != digest(goal):
        raise ValueError("native world opening setup identity differs from full world goal")
    old_goal = world.legacy_goal_checking_projection(goal)
    old_setup = deepcopy(setup)
    from . import creative_opening_setup_contract_v4 as opening
    old_setup.update(schema=opening.VERSION, goal_sha256=digest(old_goal))
    opening.validate(old_setup, old_goal)
    old_script = world.legacy_script_checking_projection(raw)
    old_script["selected_candidate_id"] = script["selected_candidate_id"]
    return raw, old_script, old_goal, old_setup


def build_review_context(goal, script):
    raw = deepcopy(script); raw.pop("selected_candidate_id", None)
    fragment = world.review_fragment(goal, raw)
    wire_fragment = {key: deepcopy(value) for key, value in fragment.items() if key not in ("source_directory", "parallel_relations")}
    wire_fragment.update(source_directory_ref="source_directory", parallel_permissions_ref="temporal_relation_catalog.parallel_permissions",
        canonical_context_sha256=digest(fragment))
    catalog = world.build_evidence_catalog(goal, raw)
    targets = {}
    for beat in raw["beats"]:
        paths = ["whole_plan.beats." + str(i) + "." for i, planned in enumerate(goal["whole_plan"]["beats"])
                 if planned["id"] == beat["id"]]
        targets[beat["id"]] = {"goal_refs": [ref for ref, row in catalog.items()
            if any(row["document_path"] == path + field for path in paths for field in ("response", "strategy", "visible_change"))],
            "actual_refs": [ref for ref, row in catalog.items() if row.get("role") == "actual_step" and row["beat_id"] == beat["id"]]}
    targets["ending"] = {"goal_refs": [ref for ref, row in catalog.items()
        if row["document_path"] in ("whole_plan.ending." + field for field in ("attempt_result", "visible_consequence", "emotional_landing", "open_legal_question"))],
        "actual_refs": targets[raw["beats"][-1]["id"]]["actual_refs"]}
    return {"world_scene_review_context": wire_fragment, "narrative_targets": targets,
        "source_directory": {ref: {key: row[key] for key in ("document_path", "role")} for ref, row in catalog.items()},
        "temporal_relation_catalog": {"step_refs": [ref for ref, row in catalog.items() if row.get("kind") in ("action", "dialogue")],
            "parallel_permissions": fragment["parallel_relations"], "document_index_proves_time": False,
            "parallel_permission_proves_completion_or_overlap": False}}


def _obj(fields): return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
def _text(blank=False, maximum=240): return {"type": "string", "minLength": 0 if blank else 1, "maxLength": maximum}


def _prior_scope(brief, supplied):
    retained = brief.get("prior_story_scope")
    if supplied is not None and retained is not None and supplied != retained:
        raise ValueError("explicit prior-story authority differs from retained brief scope")
    scope = supplied if supplied is not None else retained
    if scope is not None and (not isinstance(scope, dict) or not isinstance(scope.get("full_prior_script"), dict)
            or scope.get("prior_script_sha256") != digest(scope["full_prior_script"])):
        raise ValueError("prior-story scope requires the exact retained full story and matching native SHA")
    return scope


def _temporal_schema(catalog):
    refs = [ref for ref, row in catalog.items() if row.get("kind") in ("action", "dialogue")]
    proof = _obj({"source_ref": {"enum": refs}, "quote": _text(maximum=500)})
    return {"type": "array", "uniqueItems": True, "items": _obj({
        "relation": {"enum": ["completed_before_start", "overlaps"]}, "from_ref": {"enum": refs},
        "to_ref": {"enum": refs}, "evidence": {"type": "array", "minItems": 2, "uniqueItems": True, "items": proof},
        "reason": _text()})}


def _narrative_schema(context, catalog):
    reading = _obj({"role": {"enum": ["support", "unresolved_counter", "transition", "context"]},
        "mode": {"enum": ["intention", "conditional_promise", "completed_action", "observed_state", "attribution", "open_outcome", "unresolved_reading"]},
        "literal_reading": _text()})
    rows = {}
    for identifier, target in context["narrative_targets"].items():
        row = _obj({"status": {"enum": ["pass", "fail", "unknown"]}, "comparison": _text(maximum=500),
            "readings": {"type": "object", "propertyNames": {"enum": list(catalog)}, "additionalProperties": deepcopy(reading), "minProperties": 1},
            "required_revision": _text(True)})
        required_goals = {ref: {"$ref": "#/$defs/v6_reading"} for ref in target["goal_refs"]}
        # Required goals are exact references, never a repeated source quote.
        row["properties"]["readings"]["properties"] = required_goals
        row["properties"]["readings"]["required"] = list(required_goals)
        row["allOf"] = [
            {"if": {"properties": {"status": {"const": "pass"}}}, "then": {"properties": {
                "required_revision": {"const": ""}, "readings": {"additionalProperties": {"properties": {
                    "role": {"not": {"const": "unresolved_counter"}}, "mode": {"not": {"const": "unresolved_reading"}}}}}}}},
            {"if": {"properties": {"status": {"const": "fail"}}}, "then": {"properties": {"required_revision": _text()}}},
            {"if": {"properties": {"readings": {"not": {"additionalProperties": {"properties": {
                "mode": {"not": {"const": "unresolved_reading"}}}}}}}},
             "then": {"properties": {"status": {"const": "unknown"}}}},
            {"if": {"properties": {"status": {"const": "pass"}}}, "then": {"properties": {"readings": {"anyOf": [
                {"required": [ref], "properties": {ref: {"properties": {"role": {"enum": ["support", "transition"]}}}}}
                for ref in target["actual_refs"]]}}}}]
        rows[identifier] = row
    return _obj(rows), reading


def _adjust_temporal_fields(node, all_refs, action_refs, initial_refs, actors, entities):
    if isinstance(node, list):
        for value in node: _adjust_temporal_fields(value, all_refs, action_refs, initial_refs, actors, entities)
    elif isinstance(node, dict):
        fields = node.get("properties", {})
        if "stimulus_ref" in fields: fields["stimulus_ref"] = {"enum": [None, *all_refs]}
        if "reaction_refs" in fields: fields["reaction_refs"] = {"type": "array", "items": {"enum": all_refs}, "uniqueItems": True, "maxItems": len(all_refs)}
        if "established_by" in fields and "actual_value" in fields and "quote" in fields:
            fields["established_by"] = {"enum": [None, *initial_refs, *action_refs]}
            fields["quote"] = _text(True, 500)
            node.setdefault("allOf", []).append({"if": {"properties": {"established_by": {"type": "null"}}},
                "then": {"properties": {"actual_value": {"type": "null"}, "quote": {"const": ""}}},
                "else": {"properties": {"quote": _text(maximum=500)}}})
        if "state_key" in fields and any(key in fields for key in ("expected_value", "actual_value", "before", "after")):
            values = [key for key in ("expected_value", "actual_value", "before", "after") if key in fields]
            for key, spec in (("holder_character_id", {"enum": [None, *actors]}),
                              ("support_entity_id", {"enum": [None, *entities]}),
                              ("open", {"type": ["boolean", "null"]}),
                              ("presence", {"enum": [None, "present", "absent", "unknown"]}),
                              ("location", {"type": ["string", "null"]}), ("posture", {"type": ["string", "null"]})):
                node.setdefault("allOf", []).append({"if": {"properties": {"state_key": {"const": key}}},
                    "then": {"properties": {field: deepcopy(spec) for field in values}}})
            node["allOf"].append({"if": {"properties": {"entity_id": {"enum": actors}}},
                "then": {"properties": {"state_key": {"enum": ["posture", "location"]}}},
                "else": {"properties": {"state_key": {"not": {"const": "posture"}}}}})
        if "subjects" in fields and "preconditions" in fields:
            node.setdefault("allOf", []).append({"if": {"properties": {"status": {"const": "pass"}}},
                "then": {"properties": {"preconditions": {"items": {"properties": {"established_by": {"not": {"type": "null"}}}}}}}})
        for value in list(node.values()): _adjust_temporal_fields(value, all_refs, action_refs, initial_refs, actors, entities)


def build_part_schema(part, script, brief, plan, legal_context, *, context_sha256, goal_contract=None, opening_setup=None, prior_story_scope=None):
    raw, old_script, old_goal, old_setup = _sources(script, goal_contract, opening_setup, brief)
    scope = _prior_scope(brief, prior_story_scope)
    checking_brief = {**deepcopy(brief), **({"prior_story_scope": deepcopy(scope)} if scope and part == "semantic" else {})}
    schema = previous.build_part_schema(part, old_script, checking_brief, plan, legal_context, context_sha256=context_sha256,
        goal_contract=old_goal, opening_setup=old_setup)
    fields = schema["properties"]
    fields.update(schema={"const": VERSION}, script_sha256={"const": digest(script)}, native_script_sha256={"const": digest(raw)},
        brief_sha256={"const": digest(brief)}, goal_contract_sha256={"const": digest(goal_contract)}, opening_setup_sha256={"const": digest(opening_setup)})
    catalog = world.build_evidence_catalog(goal_contract, raw)
    refs = [ref for ref, row in catalog.items() if row.get("kind") in ("action", "dialogue")]
    initials = previous.checks.reviews.base.initial_evidence_catalog(brief, old_setup)
    _adjust_temporal_fields(schema, refs, [ref for ref in refs if catalog[ref]["kind"] == "action"], list(initials),
        brief["constraints"]["allowed_character_ids"],
        [row["id"] for group in ("character_states", "prop_states") for row in brief["initial_state"][group]] + [row["id"] for row in brief["scenes"]])
    fields["temporal_relations"] = _temporal_schema(catalog)
    if part == "semantic":
        fields["prior_story_scope_sha256"] = {"const": digest(scope) if scope else None}
        extension = world.build_review_extension_schema(goal_contract, raw)
        for key in ("world_scene_checks", "world_scene_context_sha256"): fields[key] = deepcopy(extension["properties"][key])
        context = build_review_context(goal_contract, raw)
        fields["narrative_consistency_checks"], reading = _narrative_schema(context, catalog)
        schema.setdefault("$defs", {})["v6_reading"] = reading
        issues = fields["unresolved_issues"]
        for table in ("world_scene_checks", "narrative_consistency_checks"):
            ids = list(fields[table]["properties"])
            issues["items"]["allOf"][0]["oneOf"].append({"properties": {"table": {"const": table}, "item_id": {"enum": ids}}, "required": ["table", "item_id"]})
            issues["maxItems"] += len(ids)
    schema["required"] = list(fields)
    # Intern repeated standard JSON-Schema fragments without losing existing
    # definitions. This changes representation, never admissible responses.
    definitions = deepcopy(schema.get("$defs", {}))
    compact = previous.checks.reviews.base.base._compact_schema(schema)
    generated = compact.get("$defs", {})
    if set(definitions) & set(generated):
        raise ValueError("new schema definition identity collision")
    compact["$defs"] = {**definitions, **generated}
    schema = compact
    Draft202012Validator.check_schema(schema)
    return schema


def _checked_projection(document, part, old_script):
    value = previous._checking_projection(document, part, old_script)
    for field in ("native_script_sha256", "temporal_relations", "world_scene_checks", "world_scene_context_sha256", "narrative_consistency_checks"):
        value.pop(field, None)
    if part == "semantic":
        value["unresolved_issues"] = [row for row in value["unresolved_issues"]
            if row["table"] not in ("world_scene_checks", "narrative_consistency_checks")]
    return value


def validate_part(document, part, script, brief, plan, legal_context, *, context_sha256, goal_contract=None, opening_setup=None, prior_story_scope=None):
    try:
        raw, old_script, old_goal, old_setup = _sources(script, goal_contract, opening_setup, brief)
        Draft202012Validator(build_part_schema(part, script, brief, plan, legal_context, context_sha256=context_sha256,
            goal_contract=goal_contract, opening_setup=opening_setup, prior_story_scope=prior_story_scope)).validate(document)
        catalog = world.build_evidence_catalog(goal_contract, raw)
        temporal = partial.temporal_proof(document["temporal_relations"], catalog)
        projection = _checked_projection(document, part, old_script)
        expanded = previous.checks._expand_semantic(projection, old_script, plan, goal_contract=old_goal) if part == "semantic" else projection
        partial._part_evidence(expanded, part, old_script, brief, plan, goal_contract=old_goal, opening_setup=old_setup, temporal=temporal)
        if part == "semantic":
            world.validate_review_extension({"schema": world.REVIEW_VERSION, **{key: document[key]
                for key in ("world_scene_checks", "world_scene_context_sha256")}}, goal_contract, raw)
            for row in document["narrative_consistency_checks"].values():
                if any(item["mode"] == "unresolved_reading" for item in row["readings"].values()) and row["status"] != "unknown":
                    raise ValueError("unresolved native reading requires unknown, not a definite content failure")
                if row["status"] == "pass" and any(item["role"] == "unresolved_counter" or item["mode"] == "unresolved_reading" for item in row["readings"].values()):
                    raise ValueError("passing narrative comparison cannot hide an unresolved counterproof/reading")
            pointers = set()
            for issue in document["unresolved_issues"]:
                pointer = issue["table"], issue["item_id"]
                if pointer in pointers or document[issue["table"]][issue["item_id"]]["status"] != issue["status"]:
                    raise ValueError("unresolved issue must bind one existing same-status native target")
                pointers.add(pointer)
        findings, uncertainties = [], []
        for table in (*PART_TABLES[part], *(["world_scene_checks", "narrative_consistency_checks"] if part == "semantic" else [])):
            if table not in document or table in ("literal_events", "review_limitations", "unresolved_issues", "prior_story_relation"): continue
            rows = document[table]
            for identifier, row in rows.items() if isinstance(rows, dict) else enumerate(rows):
                item = {"table": table, "item_id": identifier, "part": part, "target": document["revision_target"], "finding": deepcopy(row)}
                if row["status"] == "fail": findings.append(item)
                elif row["status"] == "unknown": uncertainties.append(item)
        target = document["revision_target"]
        if bool(findings) != (target != "none") or any(row["table"] == "plan_support" for row in findings) and target != "plan":
            raise ValueError("native revision_target must match definite failures; plan_support failure requires plan")
        status = "halt_review_uncertain" if uncertainties else "needs_whole_revision" if findings else "review_part_passed"
        scope = _prior_scope(brief, prior_story_scope)
        if part == "semantic" and scope:
            relation = document["prior_story_relation"]["relation"]
            if previous.checks.reviews.base.base.prior.story_body_digest(script) == previous.checks.reviews.base.base.prior.story_body_digest(scope["full_prior_script"]) or relation == "same_story": status = "halt_same_story_prior_allowance_exhausted"
            elif relation == "unknown": status = "halt_prior_story_relation_unknown"
        prior_halt = status.startswith(("halt_same_story", "halt_prior_story"))
        return {"valid": True, "accepted": status == "review_part_passed", "status": status, "part": part,
            "findings": findings, "uncertainties": uncertainties, "revision_target": target,
            "requires_new_goal_plan": target == "plan" and not prior_halt, "revision_dispatch_blocked": prior_halt,
            "full_review_protocol_version": ADAPTER_VERSION, "split_review_contract_version": VERSION, "native_version": VERSION,
            "native_part_sha256": digest(document), "native_script_sha256": digest(raw), "compiled_script_sha256": digest(script),
            "native_prior_story_scope_sha256": digest(scope) if scope and part == "semantic" else None,
            "original_native_source_sha256": {key: document[key] for key in SOURCE_HEADERS}, "native_context_sha256": context_sha256,
            "compiler_validation_projection_sha256": digest(expanded), "compiler_projection_is_native_review": False,
            "native_response_rewritten": False, "source_order_used": False, "semantic_meaning_programmatically_verified": False,
            "semantic_review_is_model_judgement": True, "temporal_proof_semantics_programmatically_verified": False,
            "complete_same_source_full_review": False, "human_quality_approved": False, "creative_quality_passed": False, "old_budget_reset": False}
    except ValidationError as exc:
        return _error("FULL_REVIEW_V6_SCHEMA_INVALID", exc.message, "/".join(map(str, exc.absolute_path)))
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return _error("FULL_REVIEW_V6_EVIDENCE_INVALID", str(exc))


def build_review_bundle(native_semantic_review, native_physical_review):
    return {"schema": BUNDLE_VERSION, "native_semantic_review": deepcopy(native_semantic_review), "native_physical_review": deepcopy(native_physical_review)}


def validate_bundle(bundle, script, brief, plan, legal_context, *, semantic_context_sha256, physical_context_sha256, goal_contract=None, opening_setup=None, prior_story_scope=None):
    if not isinstance(bundle, dict) or set(bundle) != {"schema", "native_semantic_review", "native_physical_review"} or bundle.get("schema") != BUNDLE_VERSION or semantic_context_sha256 == physical_context_sha256:
        return _error("FULL_REVIEW_V6_BUNDLE_INVALID", "two complete new native parts with distinct contexts required")
    contexts = {"semantic": semantic_context_sha256, "physical": physical_context_sha256}
    parts = {part: bundle["native_" + part + "_review"] for part in PART_TABLES}
    results = {part: validate_part(parts[part], part, script, brief, plan, legal_context, context_sha256=contexts[part], goal_contract=goal_contract, opening_setup=opening_setup, prior_story_scope=prior_story_scope) for part in PART_TABLES}
    identity = {"part_results": results, "full_review_protocol_version": ADAPTER_VERSION, "split_review_bundle_version": BUNDLE_VERSION,
        "native_bundle_sha256": digest(bundle), "native_part_sha256": {part: digest(value) for part, value in parts.items()},
        "native_response_rewritten": False, "compiler_projection_is_native_review": False, "old_budget_reset": False,
        "human_quality_approved": False, "creative_quality_passed": False, "source_order_used": False,
        "review_origin": "two_native_same_source_v6_parts", "native_single_full_review": False}
    if not all(row["valid"] for row in results.values()):
        return {**_error("FULL_REVIEW_V6_PART_INVALID", "one or both complete native parts rejected"), **identity, "status": "halt_split_review_contract"}
    try:
        raw = deepcopy(script); raw.pop("selected_candidate_id")
        # Equal native edges are retained once for checking only. Each actual
        # report and its edge provenance remain unchanged in the native bundle.
        relations, relation_keys = [], set()
        for part in PART_TABLES:
            for relation in parts[part]["temporal_relations"]:
                left, right = relation["from_ref"], relation["to_ref"]
                key = (relation["relation"], left, right) if relation["relation"] == "completed_before_start" else (relation["relation"], *sorted((left, right)))
                if key not in relation_keys:
                    relation_keys.add(key); relations.append(deepcopy(relation))
        merged = partial.temporal_proof(relations, world.build_evidence_catalog(goal_contract, raw))
        _, old_script, old_goal, old_setup = _sources(script, goal_contract, opening_setup, brief)
        # New compatible facts from the other part can alter an old frontier.
        # Recheck the unchanged judgments against the union; never promote an
        # unknown part using a relation it did not itself establish.
        for part in PART_TABLES:
            projection = _checked_projection(parts[part], part, old_script)
            expanded = previous.checks._expand_semantic(projection, old_script, plan, goal_contract=old_goal) if part == "semantic" else projection
            partial._part_evidence(expanded, part, old_script, brief, plan, goal_contract=old_goal, opening_setup=old_setup, temporal=merged)
    except (ValueError, KeyError, TypeError) as exc:
        return {**_error("FULL_REVIEW_V6_TEMPORAL_BUNDLE_INVALID", str(exc)), **identity, "status": "halt_split_review_contract"}
    findings = [item for row in results.values() for item in row["findings"]]
    uncertainties = [item for row in results.values() for item in row["uncertainties"]]
    prior = next((row["status"] for row in results.values() if row.get("revision_dispatch_blocked")), None)
    new_goal = any(row["requires_new_goal_plan"] for row in results.values())
    status = prior or ("halt_review_uncertain" if uncertainties else "halt_full_review_requires_new_complete_goal" if new_goal else "needs_whole_revision" if findings else "text_ready_for_director")
    return {**identity, "valid": True, "accepted": status == "text_ready_for_director", "status": status,
        "findings": findings, "uncertainties": uncertainties, "requires_new_goal_plan": new_goal and not prior,
        "revision_dispatch_blocked": bool(prior), "complete_same_source_full_review": True,
        "derived_temporal_relation_sha256": digest({part: parts[part]["temporal_relations"] for part in PART_TABLES}),
        "derived_completed_before": sorted([list(pair) for pair in merged["before"]]),
        "temporal_relation_native_sources": {part: digest(parts[part]["temporal_relations"]) for part in PART_TABLES},
        "semantic_meaning_programmatically_verified": False, "semantic_review_is_model_judgement": True}


def prepare_full_review_part_request(inputs, profile, native_script, views, part):
    from . import creative_goal_context_workflow_v25 as legacy
    from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
    compiled, goal, setup = views["compiled_script"], views["goal"], views["opening_setup"]
    raw, old_script, old_goal, old_setup = _sources(compiled, goal, setup, views["brief"])
    if native_script != raw: raise ValueError("actual native script differs from the exact compiled source")
    full = legacy._fixed_legal_context(inputs)
    legal = full["verified_legal_context"]
    context = build_review_context(goal, raw)
    source_sha = {"script_sha256": digest(compiled), "brief_sha256": digest(views["brief"]), "plan_sha256": digest(views["plan"]),
        "legal_context_sha256": digest(legal), "goal_contract_sha256": digest(goal), "opening_setup_sha256": digest(setup)}
    initials = previous.checks.reviews.base.initial_evidence_catalog(views["brief"], old_setup)
    table_contract = previous.part_table_contract(part, old_script, views["brief"], views["plan"])
    prior_scope = deepcopy(_prior_scope(views["brief"], inputs["production_preferences"].get("prior_story_scope")))
    if part == "semantic":
        if prior_scope and "prior_story_relation" not in table_contract["required_tables"]:
            table_contract["required_tables"].append("prior_story_relation")
        table_contract = deepcopy(table_contract)
        table_contract["required_tables"] += ["world_scene_checks", "narrative_consistency_checks"]
        table_contract["coverage"].update(world_scene_checks=list(world.review_fragment(goal, raw)["targets"]),
            narrative_consistency_checks=list(context["narrative_targets"]))
    payload = {"review_part": part, "native_goal_document": deepcopy(goal), "native_opening_setup_document": deepcopy(setup),
        "native_script_document": deepcopy(raw), "same_source_sha256": source_sha, "native_script_sha256": digest(raw),
        "initial_state_refs": {key: {field: row[field] for field in ("entity_id", "origin", "path")} for key, row in initials.items()},
        "review_table_contract": table_contract,
        "production_preferences": deepcopy(legacy.contexts.build_stage_context("complete_script", {
            **legacy._planning_authority_inputs(inputs), "native_goal_document": goal,
            "brief": views["brief"], "creative_scene_plan": views["plan"]})["payload"]["production_preferences"]),
        "temporal_relation_catalog": context["temporal_relation_catalog"]}
    if part == "semantic":
        payload.update(verified_legal_context=deepcopy(legal), reference_fulltext=deepcopy(full["reference_fulltext"]),
            expression_standards=deepcopy(full["expression_standards"]), user_goal_contract=deepcopy(full["user_goal_contract"]),
            fact_projection=deepcopy(views["fact_projection"]), **context)
        if prior_scope:
            payload["prior_story_scope"] = prior_scope
        consistency = previous.build_consistency_evidence_catalog(old_script, views["plan"], goal_contract=old_goal)
        consistency.pop("actual_steps")
        for row in consistency["target_assertions"].values(): row.pop("quote")
        payload["consistency_evidence_catalog"] = consistency
    else:
        # Physical evidence E paths only; no H/P/semantic legal context.
        payload["source_directory"] = {ref: row for ref, row in context["source_directory"].items() if ref.startswith("E")}
    context_sha = digest(payload)
    policy = legacy.contexts.prior._policy("full_review", inputs)
    measure = legacy.contexts._measure(payload)
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ValueError("new full review exceeds existing explicit context policy; no source is truncated")
    schema = build_part_schema(part, compiled, views["brief"], views["plan"], legal, context_sha256=context_sha, goal_contract=goal, opening_setup=setup, prior_story_scope=prior_scope)
    manifest = {"schema": ADAPTER_VERSION + "/request_manifest", "stage": "full_review", "part": part,
        "part_context_sha256": context_sha, "native_script_sha256": digest(raw), "compiled_script_sha256": digest(compiled),
        "prior_story_scope_sha256": digest(prior_scope) if prior_scope and part == "semantic" else None,
        "same_source_sha256": source_sha, "structured_schema_sha256": digest(schema), "source_text_omitted_or_truncated": False,
        "native_values_rewritten": False, "compiler_fulltext_duplicates_omitted": ["brief", "creative_scene_plan", "full_current_script"],
        "source_order_used": False, "dispatch_performed": False, "server_schema_guarantee": False,
        "context_policy": policy, "payload_identity": measure,
        "phase_projection": {"production_preferences.prior_story_scope.full_prior_script": "omitted from preferences; exact source explicitly included only in semantic prior_story_scope",
            "world_scene_review_context.source_directory": "uses one top-level source_directory with exact canonical context SHA",
            "new_cross_beat_comparison": "one concise comparison per beat/ending; old event/trigger and dialogue duties remain in their original tables"},
        "payload_characters": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        "schema_characters": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))}
    prepared = world._request("full_review", profile, SEMANTIC_RULE if part == "semantic" else PHYSICAL_RULE, payload, schema, manifest=manifest)
    prepared.update(part=part, part_context_sha256=context_sha, context_sha256=context_sha, review_legal_context=deepcopy(legal),
        native_script_sha256=digest(raw), compiled_script_sha256=digest(compiled), same_source_sha256=source_sha,
        sdk_max_retries=0, server_schema_guarantee=False, dispatch_performed=False, full_review_protocol_version=ADAPTER_VERSION)
    prepared["request"]["input_provenance"].update(review_part=part, part_context_sha256=context_sha,
        native_goal_sha256=digest(goal), native_opening_setup_sha256=digest(setup), native_review_part_version=VERSION)
    prepared.update(wire=expected_wire_request(prepared["request"]), request_sha256=digest(prepared["request"]))
    return prepared
