"""Focused same-source enacted-event audit; semantic findings are model judgments.

The program validates categories, exact quotes, source identity and complete
coverage. It cannot prove that event extraction or absence detection is correct.
"""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError

from scripts import creative_world_scene_derived_context_script_v1 as source
from scripts import creative_world_scene_replanned_workflow_v3 as workflow
from scripts import creative_world_scene_source_state_audit_v4 as authority

VERSION = "creative_enacted_causality_audit/v1"
CHECKS = ("pursuit_and_resistance", "stimulus_reaction_causality", "commitments_and_results", "ending_enactment", "world_and_story_time")
READINGS = ("enacted", "not_enacted", "intended", "background", "open_outcome", "unknown")
digest = source.digest
RULE = (
    "只审当前完整正文的事件/因果兑现，不改稿。goal=native_goal_document，setup=native_opening_setup_document，"
    "script=native_script_document；source_directory的path从对应对象内部根开始。正文为明确派生的canonical-source，"
    "review_source_derivation另绑定真实provider-native，不将编译字段视为表演。"
    "assertions目录是原规划、初态、正文premise/event/trigger、场次及神情等语境断言；actual_steps目录仅实际action/dialogue.text。"
    "完整读全片逐步比较：人物具体追求和反抗、刺激与反应、声称已谈成/已承诺/已完成的事与结尾是否有实际步骤。"
    "概要、event、trigger、意图和后文总结不能证明某人已说、已答应或动作已完成；这种enacted证据只能填actual_steps中的逐字片段。"
    "已作承诺是当下说过的言语行为；承诺所指未来履行仍可intended/open_outcome，不要求未来已兑现。"
    "ensemble可支撑神情和情绪表演，不为证明它新增action；它不能替代说过、答应或操作完成的实际steps。"
    "没有找到时reading=not_enacted、status=fail，指出相关断言，声明检索全片实际steps并解释缺口；不伪造缺失对白。"
    "未来目标、条件、开放结果可仍是intended/open_outcome，不强迫所有意图兑现；世界背景、人物档案和前史可由框架成立，不强迫角色口述。"
    "步号/文档位置不能独自证明时间先后，按实际动作语言与场次故事时间判因果；不明确才unknown。"
    "每拍及ending各有一行比较，覆盖本目标全部相关断言，不因举一条引用就当全拍完成；全片五项职责另给简洁结论。"
    "每行assertion_evidence须自身目录来源；enacted须真实actual_evidence；非world全片pass也须实际步骤。"
    "status=pass无required_revision；fail写明确整稿修订建议；reading=unknown必须status=unknown。"
    "searched_actual_scope=all_current_steps是审查者声明已检索目录全文，不是程序证明穷尽。"
    "revision_target仅none/script/plan，明确fail才给script或plan；源规划本身须重建才plan。unknown始终停。"
    "不输出overall pass，不以概要流畅替代实际交锋；所有语义判断均可能出错，引用合法不证明解释正确。"
)


def _obj(fields): return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}
def _text(blank=False, maximum=600): return {"type": "string", "minLength": 0 if blank else 1, "maxLength": maximum}
def _array(item, minimum=0): return {"type": "array", "items": item, "minItems": minimum, "uniqueItems": True}


def _leaves(value, path=()):
    if type(value) is str and value.strip(): yield path, value
    elif type(value) is dict:
        for key, child in value.items(): yield from _leaves(child, (*path, key))
    elif type(value) is list:
        for index, child in enumerate(value): yield from _leaves(child, (*path, index))


def _pointer(parts): return "/" + "/".join(str(v).replace("~", "~0").replace("/", "~1") for v in parts)


def _read(document, pointer):
    value = document
    for part in pointer.split("/")[1:]:
        token = part.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if type(value) is list else value[token]
    return value


def _directory(goal, setup, script):
    assertions, steps = {}, {}
    beat_ids = [beat["id"] for beat in script["beats"]]
    targets = {identifier: [] for identifier in [*beat_ids, "ending"]}
    for alias, document in (("goal", goal), ("setup", setup), ("script", script)):
        for path, text in _leaves(document):
            leaf = str(path[-1])
            if leaf in ("id", "schema", "contract_version", "speaker", "kind", "mode", "relation") or leaf.endswith(("_id", "_sha256")):
                continue
            if any(str(part).endswith(("_ids", "_refs")) for part in path): continue
            actual = alias == "script" and len(path) == 5 and path[0] == "beats" and path[2] == "steps" and path[4] == "text"
            if actual:
                bi, si = path[1], path[3]
                ref = f"E:{script['beats'][bi]['id']}:{si}"
                steps[ref] = {"source": alias, "path": _pointer(path), "beat_id": beat_ids[bi],
                    "kind": script["beats"][bi]["steps"][si]["kind"], "role": "actual_step"}
                continue
            # The script itself is sent once. A directory indexes narrative
            # assertions, never copies the complete step/actor-ID arrays.
            if alias == "script" and (path[0] not in ("premise", "beats", "scene_contexts") or
                    path[0] == "beats" and len(path) >= 3 and path[2] not in ("event", "trigger", "ensemble")):
                continue
            ref = f"A{len(assertions)+1:04d}"
            row = {"source": alias, "path": _pointer(path), "role": "context_assertion_not_enacted_proof"}
            if alias == "goal" and len(path) >= 4 and path[:2] == ("whole_plan", "beats"):
                row["beat_id"] = beat_ids[path[2]]; targets[row["beat_id"]].append(ref)
            elif alias == "script" and len(path) >= 3 and path[0] == "beats":
                row["beat_id"] = beat_ids[path[1]]; targets[row["beat_id"]].append(ref)
            elif alias == "goal" and path[:2] == ("whole_plan", "ending"):
                targets["ending"].append(ref)
            assertions[ref] = row
    if not all(targets.values()) or not steps: raise ValueError("complete beat/ending assertion targets and actual steps required")
    return {"assertions": assertions, "actual_steps": steps, "target_assertion_refs": targets}


def _schema(context, descriptor, setup, directory):
    proof = lambda refs: _obj({"ref": {"enum": list(refs)}, "quote": _text(maximum=240)})
    assertion = _array({"$ref": "#/$defs/assertion_proof"}, 1)
    actual = _array({"$ref": "#/$defs/actual_proof"})
    def row():
        result = _obj({"status": {"enum": ["pass", "fail", "unknown"]}, "reading": {"enum": list(READINGS)},
            "comparison": _text(maximum=800), "assertion_evidence": deepcopy(assertion), "actual_evidence": deepcopy(actual),
            "searched_actual_scope": {"const": "all_current_steps"}, "required_revision": _text(True)})
        result["allOf"] = [
            {"if": {"properties": {"status": {"const": "pass"}}}, "then": {"properties": {"required_revision": {"const": ""}}}},
            {"if": {"properties": {"status": {"const": "fail"}}}, "then": {"properties": {"required_revision": _text()}}},
            {"if": {"properties": {"reading": {"const": "not_enacted"}}}, "then": {"properties": {"status": {"const": "fail"}}}},
            {"if": {"properties": {"reading": {"const": "unknown"}}}, "then": {"properties": {"status": {"const": "unknown"}}}},
            {"if": {"properties": {"reading": {"const": "enacted"}}}, "then": {"properties": {"actual_evidence": {"minItems": 1}}}}]
        return result
    def own_row(own):
        return {"allOf": [{"$ref": "#/$defs/row"}, {"properties": {"assertion_evidence": {
            "contains": {"properties": {"ref": {"enum": own}}, "required": ["ref"]}}}}]}
    result = _obj({"schema": {"const": VERSION}, "context_sha256": {"const": context},
        "native_script_sha256": {"const": descriptor["native_script_sha256"]},
        "derived_script_sha256": {"const": descriptor["derived_script_sha256"]},
        "compiled_script_sha256": {"const": descriptor["compiled_script_sha256"]},
        "native_goal_sha256": {"const": descriptor["native_goal_sha256"]}, "native_setup_sha256": {"const": digest(setup)},
        "beat_reviews": _obj({identifier: own_row(own) for identifier, own in directory["target_assertion_refs"].items()}),
        "checks": _obj({key: {"$ref": "#/$defs/row" if key == "world_and_story_time" else "#/$defs/actual_check"} for key in CHECKS}),
        "revision_target": {"enum": ["none", "script", "plan"]}})
    result["$defs"] = {"assertion_proof": proof(directory["assertions"]), "actual_proof": proof(directory["actual_steps"]),
        "row": row(), "actual_check": {"allOf": [{"$ref": "#/$defs/row"},
            {"if": {"properties": {"status": {"const": "pass"}}},
             "then": {"properties": {"actual_evidence": {"minItems": 1}}}}]}}
    return result


def prepare(inputs, profile, native, views):
    workflow.base.workflow._verify_views(inputs, views)
    compiled = source.compile_document(native, views["goal"], views["brief"])
    payload, authority_manifest = authority.prior._payload(inputs, views["goal"], views["opening_setup"])
    packet = payload["authority_inputs"].pop("source_packet")
    payload.update(native_script_document=deepcopy(compiled["derived_script"]), review_source_derivation=compiled["source_descriptor"])
    directory = _directory(views["goal"], views["opening_setup"], compiled["derived_script"])
    payload["source_directory"] = directory
    context = digest(payload); schema = _schema(context, compiled["source_descriptor"], views["opening_setup"], directory)
    Draft202012Validator.check_schema(schema)
    policy = workflow.base.workflow.contexts.prior._policy("full_review", inputs)
    measure = workflow.base.workflow.contexts._measure(payload)
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ValueError("focused full-source audit exceeds existing context policy; no text truncated")
    result = source.world._request("full_review", profile, RULE, payload, schema,
        manifest={"schema": VERSION + "/manifest", "context_policy": policy, "payload_identity": measure,
            "authority_projection_manifest": authority_manifest, "omitted_source_packet_sha256": digest(packet),
            "original_inputs_sha256": digest(inputs), "source_descriptor": compiled["source_descriptor"],
            "no_manual_expected_findings_in_request": True, "semantic_completeness_programmatically_proven": False})
    result.update(context_sha256=context, source_descriptor=compiled["source_descriptor"],
        views={"inputs": deepcopy(inputs), "profile": deepcopy(profile), "native_script": deepcopy(native),
            "compiler_views": deepcopy(views), "source_directory": directory},
        dispatch_performed=False, sdk_max_retries=0, server_schema_guarantee=False)
    result["request"]["input_provenance"]["enacted_causality_audit_version"] = VERSION
    return workflow.base.workflow._mark(result, inputs)


def validate(native, prepared):
    try:
        views = prepared["views"]
        if prepared != prepare(views["inputs"], views["profile"], views["native_script"], views["compiler_views"]):
            raise ValueError("focused audit complete source/request identity differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        documents = {"goal": payload["native_goal_document"], "setup": payload["native_opening_setup_document"], "script": payload["native_script_document"]}
        directory = views["source_directory"]
        findings, uncertainties = [], []
        for table in ("beat_reviews", "checks"):
            for identifier, row in native[table].items():
                for key, group in (("assertion_evidence", "assertions"), ("actual_evidence", "actual_steps")):
                    for proof in row[key]:
                        location = directory[group][proof["ref"]]
                        if not proof["quote"].strip() or proof["quote"] not in _read(documents[location["source"]], location["path"]):
                            raise ValueError("focused audit quote differs from the actual designated source field")
                item = {"table": table, "item_id": identifier, "finding": deepcopy(row), "target": native["revision_target"]}
                if row["status"] == "fail": findings.append(item)
                elif row["status"] == "unknown": uncertainties.append(item)
        if bool(findings) != (native["revision_target"] != "none"):
            raise ValueError("focused native revision_target must match definite failures")
        return {"valid": True, "accepted": not findings and not uncertainties,
            "status": "halt_enacted_causality_unknown" if uncertainties else "needs_whole_revision" if findings else "enacted_causality_passed",
            "findings": findings, "uncertainties": uncertainties, "revision_target": native["revision_target"],
            "requires_new_goal_plan": native["revision_target"] == "plan", "native_report_sha256": digest(native),
            "source_descriptor": deepcopy(prepared["source_descriptor"]), "context_sha256": prepared["context_sha256"],
            "enacted_causality_audit_version": VERSION, "semantic_meaning_programmatically_verified": False,
            "human_quality_approved": False}
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        reason = exc.message if isinstance(exc, ValidationError) else str(exc)
        return {"valid": False, "accepted": False, "status": "halt_enacted_causality_contract",
            "findings": [{"code": "ENACTED_CAUSALITY_CONTRACT_INVALID", "reason": reason,
                "path": "/" + "/".join(map(str, exc.absolute_path)) if isinstance(exc, ValidationError) else ""}],
            "uncertainties": [], "enacted_causality_audit_version": VERSION}
