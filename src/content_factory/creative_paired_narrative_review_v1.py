"""Pure, source-bound narrative comparison fragments for existing review calls.

No provider, runtime, grant, lexical classifier or legacy-report conversion.
Literal meanings and entity mappings remain native model judgments. Validation
proves source/coverage/internal contracts, never natural-language correctness.
"""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from . import creative_goal_drama_audit_contract_v11 as goal_evidence
from . import creative_split_full_review_contract_v4 as script_evidence

VERSION = "creative_paired_narrative_review/v1"
SNAPSHOT_VERSION = VERSION + "/accepted_snapshot"
MODES = ("intention", "conditional_promise", "completed_action", "observed_state",
         "attribution", "uncertain")
RULE = (
    "paired_checks逐个回答当前每拍及ending唯一target，不另写可互相矛盾的同义总评。"
    "先按原句读清施事、对象、意图/条件/完成动作/观察终态，再比较response、visible_change、ending及实际steps。"
    "说要做不等于已经完成；中间留桌不等于最终留下；明确受阻、放弃或不同对象可相容，须引用原有过渡。"
    "不得在literal_reading中暗改原句施事或补写动作。引用当前ref的逐字片段，不跨稿取证。"
    "同句多对象仅列当前比较必需的1至6条语义原子，不逐词穷举；一个target仍只有一个结论。"
    "evidence含支持与已经解释的前后文；counterevidence仅含未解决反证，存在时不能pass。"
    "目标改变不必然矛盾，比较新刺激、代价和新增结果；不能只因出现交换一词就认定动因充分。"
    "状态只写原文可支持的对象/参与人/时点；不确定填uncertain及unknown，不猜法律效力。"
    "语义由审查模型判断，程序不证明中文解释、法律或创作质量。")


digest = goal_evidence.digest


def _sha(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("lowercase SHA-256 identity required")


def _obj(properties, *, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def _text(limit=240):
    return {"type": "string", "minLength": 1, "maxLength": limit, "pattern": r"\S"}


def _ids(goal, table):
    ids = [row["id"] for row in goal["whole_plan"][table]]
    if (not ids or any(type(value) is not str or not value.strip() for value in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("unique nonempty declared " + table + " required")
    return ids


def _index(catalog):
    # One path-only directory; complete source hashes stay in the manifest.
    return {ref: {"document_path": row["document_path"]} for ref, row in catalog.items()}


def build_targets(native_goal):
    catalog = goal_evidence.build_evidence_catalog(native_goal)
    ids = _ids(native_goal, "beats")
    actors = _ids(native_goal, "characters")
    _ids(native_goal, "props"); _ids(native_goal, "scenes")
    by_path = {row["document_path"]: ref for ref, row in catalog.items()}
    ending = [ref for ref, row in catalog.items()
              if row["document_path"].startswith("whole_plan.ending.")]
    if len(ending) < 2:
        raise ValueError("complete original ending fields required")
    targets = {}
    for i, beat_id in enumerate(ids):
        if native_goal["whole_plan"]["beats"][i]["actor_id"] not in actors:
            raise ValueError("comparison target actor must be declared in this native goal")
        prefix = f"whole_plan.beats.{i}."
        own = [ref for ref, row in catalog.items() if row["document_path"].startswith(prefix)]
        anchors = [by_path[prefix + field] for field in
                   ("response", "visible_change", "strategy.before", "strategy.after")]
        targets["beat:" + beat_id] = {"beat_id": beat_id,
            "declared_actor_id": native_goal["whole_plan"]["beats"][i]["actor_id"],
            "required_reading_refs": anchors, "own_source_refs": own}
    targets["ending"] = {"beat_id": None, "declared_actor_id": None,
        "required_reading_refs": ending, "own_source_refs": ending}
    return {"schema": VERSION + "/targets", "goal_sha256": digest(native_goal),
            "source_index": _index(catalog), "targets": targets,
            "semantic_mapping_programmatically_inferred": False}


def _frame(goal, *, script=None, snapshot=None, compiled_script=None, request_same_source_sha256=None):
    targets = build_targets(goal)
    catalog = deepcopy(goal_evidence.build_evidence_catalog(goal))
    if script is None:
        kind = "goal"
        original = {"native_goal_document": goal}
    else:
        kind = "script"
        own = script_evidence.build_consistency_evidence_catalog(
            script, goal["whole_plan"], goal_contract=goal)
        actual, asserted = own["actual_steps"], own["target_assertions"]
        for ref, row in {**actual, **asserted}.items():
            catalog[ref] = {"document_path": row["document_path"], "quote": row["quote"]}
        for beat_id in _ids(goal, "beats"):
            step_refs = [ref for ref, row in actual.items() if row["beat_id"] == beat_id]
            target_refs = [ref for ref, row in asserted.items() if row["beat_id"] == beat_id]
            if not step_refs or len(target_refs) != 2:
                raise ValueError("each native script beat requires real steps and event/trigger assertions")
            target = targets["targets"]["beat:" + beat_id]
            target.update(required_reading_refs=[*target_refs, *step_refs],
                own_source_refs=[*target_refs, *step_refs])
        targets["targets"]["ending"]["required_reading_refs"].append(next(reversed(actual)))
        targets["source_index"] = _index(catalog)
        original = {"native_goal_document": goal, "native_script_document": script}
        if compiled_script is not None:
            original["full_current_script"] = compiled_script
        if request_same_source_sha256 is not None:
            if type(request_same_source_sha256) is not dict or "script_sha256" not in request_same_source_sha256:
                raise ValueError("actual same-source header object with compiled script identity required")
            for value in request_same_source_sha256.values(): _sha(value)
            if compiled_script is not None and digest(compiled_script) != request_same_source_sha256["script_sha256"]:
                raise ValueError("compiled object differs from actual semantic request script header")
            original["same_source_sha256"] = deepcopy(request_same_source_sha256)
    task = {"schema": VERSION, "frame_kind": kind, "goal_sha256": digest(goal),
            "input_sha256": digest(original), "comparison_targets": targets}
    delta = {"paired_narrative_comparison": task}
    if snapshot is not None:
        delta["accepted_goal_comparison_snapshot"] = deepcopy(snapshot)
    context = digest({**deepcopy(original), "payload_delta": delta})
    return {"payload_delta": delta, "manifest": {"schema": VERSION + "/context",
        "frame_kind": kind, "goal_sha256": digest(goal), "input_sha256": digest(original),
        "context_sha256": context, "catalog_sha256": digest(catalog),
        "native_script_sha256": digest(script) if script is not None else None,
        "compiled_script_sha256": digest(compiled_script) if compiled_script is not None else None,
        "request_same_source_sha256": deepcopy(request_same_source_sha256),
        "compiled_object_supplied": compiled_script is not None,
        "original_text_modified": False, "original_fulltext_copies_in_delta": 0},
        "_catalog": catalog, "_targets": targets["targets"]}


def build_goal_delta(native_goal):
    frame = _frame(native_goal)
    return {key: frame[key] for key in ("payload_delta", "manifest")}


def build_script_targets(script, native_goal):
    """Structural replay only; this does not authorize a body/review request."""
    return deepcopy(_frame(native_goal, script=script)["payload_delta"]
                    ["paired_narrative_comparison"]["comparison_targets"])


def _check_context(frame, context_sha256):
    _sha(context_sha256)
    if context_sha256 != frame["manifest"]["context_sha256"]:
        raise ValueError("comparison context differs from current lossless originals and actual delta")


def _schema(frame, goal, context_sha256):
    _check_context(frame, context_sha256)
    actors, objects = _ids(goal, "characters"), _ids(goal, "props")
    nullable_actor = {"enum": [*actors, None]}
    state = _obj({"dimension": {"enum": ["holder", "location", "signature"]},
        "phase": {"enum": ["before", "after", "ending"]},
        "participant_id": nullable_actor, "value": _text(100)})
    reading = _obj({"quote": _text(240), "mode": {"enum": list(MODES)},
        "actor_id": nullable_actor, "object_id": {"enum": [*objects, None]},
        "literal_reading": _text(200), "state": {"oneOf": [{"type": "null"}, state]}})
    rows = {}
    for target_id, target in frame["_targets"].items():
        refs = list(frame["_catalog"])
        evidence = {"type": "array", "items": {"$ref": "#/$defs/paired_ref"}, "uniqueItems": True,
                    "maxItems": len(refs)}
        rows[target_id] = _obj({"status": {"enum": ["pass", "fail", "unknown"]},
            "readings": {"type": "object", "propertyNames": {"$ref": "#/$defs/paired_ref"},
                "additionalProperties": {"$ref": "#/$defs/paired_reading"},
                "required": target["required_reading_refs"], "maxProperties": len(refs)},
            "evidence": {**deepcopy(evidence), "minItems": 2},
            "counterevidence": deepcopy(evidence), "transition_evidence": deepcopy(evidence),
            "comparison": _text(360), "required_revision": {"type": "string", "maxLength": 360}})
    manifest = frame["manifest"]
    schema = _obj({"schema": {"const": VERSION}, "frame_kind": {"const": manifest["frame_kind"]},
        "goal_sha256": {"const": manifest["goal_sha256"]},
        "input_sha256": {"const": manifest["input_sha256"]},
        "context_sha256": {"const": context_sha256}, "records_by_target": _obj(rows)})
    schema["$defs"] = {"paired_reading": {"type": "array", "items": reading,
        "minItems": 1, "maxItems": 6, "uniqueItems": True},
        "paired_ref": {"enum": list(frame["_catalog"])}}
    Draft202012Validator.check_schema(schema)
    return schema


def build_goal_schema(native_goal, *, context_sha256):
    return _schema(_frame(native_goal), native_goal, context_sha256)


def add_to_schema(base_schema, paired_schema, *, native_version):
    """New explicit outer protocol, not a forged prior native document.

    The local $defs are merged to keep JSON-pointer refs correct when nested.
    """
    if type(native_version) is not str or not native_version.strip():
        raise ValueError("new explicit native outer version required")
    result, fragment = deepcopy(base_schema), deepcopy(paired_schema)
    definitions = fragment.pop("$defs", {})
    for key, value in definitions.items():
        if key in result.get("$defs", {}) and result["$defs"][key] != value:
            raise ValueError("comparison schema definition collision")
        result.setdefault("$defs", {})[key] = value
    if "paired_checks" in result["properties"]:
        raise ValueError("paired comparison is already present")
    old = result["properties"]["schema"].get("const")
    if old == native_version:
        raise ValueError("new outer version must be distinct")
    result["properties"]["schema"] = {"const": native_version}
    result["properties"]["paired_checks"] = fragment
    result["required"].append("paired_checks")
    Draft202012Validator.check_schema(result)
    return result


def _validate(document, frame, goal, context_sha256):
    Draft202012Validator(_schema(frame, goal, context_sha256)).validate(document)
    findings, uncertainties, end_states = [], [], {}
    for target_id, record in document["records_by_target"].items():
        status = record["status"]
        if status == "pass" and (record["counterevidence"] or record["required_revision"]):
            raise ValueError("pass cannot hide unresolved counterevidence or a required revision")
        if status == "fail" and not record["required_revision"].strip():
            raise ValueError("fail requires complete native revision guidance")
        accounted = set(record["evidence"] + record["counterevidence"] + record["transition_evidence"])
        if accounted != set(record["readings"]):
            raise ValueError("each native reading and cited support/transition needs the same local quote binding")
        for ref, atoms in record["readings"].items():
            for reading in atoms:
                if reading["quote"] not in frame["_catalog"][ref]["quote"]:
                    raise ValueError("comparison quote differs from exact original source")
                if status != "unknown" and reading["mode"] == "uncertain":
                    raise ValueError("unresolved literal reading requires unknown, not a settled pass/fail")
                state = reading["state"]
                if state is None:
                    continue
                if reading["object_id"] is None:
                    raise ValueError("explicit object state requires a declared object")
                dimension, value = state["dimension"], state["value"]
                if dimension in ("holder", "location") and state["participant_id"] is not None:
                    raise ValueError("holder/location is one object state; participant must be null")
                if dimension == "holder" and value not in _ids(goal, "characters"):
                    raise ValueError("holder state must use a declared character ID")
                if dimension == "location" and value not in _ids(goal, "scenes"):
                    raise ValueError("location state must use a declared scene ID")
                if dimension == "signature" and (value not in ("signed", "unsigned") or state["participant_id"] is None):
                    raise ValueError("signature state needs an explicit signer and signed/unsigned value")
                # Only native completed/observed states at the same final
                # instant are compared. Intentions are never outcomes.
                if state["phase"] == "ending" and reading["mode"] in ("completed_action", "observed_state"):
                    key = (reading["object_id"], dimension, state["participant_id"])
                    end_states.setdefault(key, []).append((value, status))
        row = {"target_id": target_id, "reason": record["comparison"],
               "required_revision": record["required_revision"]}
        if status == "fail": findings.append(row)
        if status == "unknown": uncertainties.append(row)
    if not findings and not uncertainties:
        for values in end_states.values():
            if len({value for value, _ in values}) > 1:
                raise ValueError("all-pass comparison contains incompatible explicitly declared final states")
    return {"valid": True, "accepted": not findings and not uncertainties,
        "findings": findings, "uncertainties": uncertainties,
        "native_comparison_sha256": digest(document),
        "goal_sha256": digest(goal), "context_sha256": context_sha256,
        "semantic_meaning_programmatically_verified": False, "human_approved": False}


def validate_goal(document, native_goal, *, context_sha256):
    return _validate(document, _frame(native_goal), native_goal, context_sha256)


def compile_snapshot(document, native_goal, *, context_sha256, bundle_sha256):
    _sha(bundle_sha256)
    if validate_goal(document, native_goal, context_sha256=context_sha256)["accepted"] is not True:
        raise ValueError("unaccepted comparison cannot enter a body or full review")
    records = deepcopy(document["records_by_target"])
    for record in records.values():
        for atoms in record["readings"].values():
            for reading in atoms: reading.pop("quote")
    return {"schema": SNAPSHOT_VERSION, "goal_sha256": digest(native_goal),
        "goal_context_sha256": context_sha256, "native_comparison_sha256": digest(document),
        "bundle_sha256": bundle_sha256, "records_by_target": records,
        "semantic_meaning_programmatically_verified": False, "human_approved": False}


def validate_snapshot(snapshot, native_goal, *, native_comparison, context_sha256, bundle_sha256):
    expected = compile_snapshot(native_comparison, native_goal,
        context_sha256=context_sha256, bundle_sha256=bundle_sha256)
    if snapshot != expected:
        raise ValueError("snapshot differs from exact accepted native comparison/goal/context/bundle")
    return {"valid": True, "snapshot_sha256": digest(snapshot), "accepted": True}


def attach_snapshot(payload, snapshot, native_goal, *, native_comparison, context_sha256, bundle_sha256):
    validate_snapshot(snapshot, native_goal, native_comparison=native_comparison,
        context_sha256=context_sha256, bundle_sha256=bundle_sha256)
    if payload.get("native_goal_document") != native_goal:
        raise ValueError("actual body payload must contain the unmodified same native goal")
    if "accepted_goal_comparison_snapshot" in payload:
        raise ValueError("comparison snapshot must occur once")
    return {**deepcopy(payload), "accepted_goal_comparison_snapshot": deepcopy(snapshot)}


def _script_frame(script, goal, snapshot, *, native_comparison, goal_context_sha256, bundle_sha256, compiled_script=None, request_same_source_sha256=None):
    validate_snapshot(snapshot, goal, native_comparison=native_comparison,
        context_sha256=goal_context_sha256, bundle_sha256=bundle_sha256)
    return _frame(goal, script=script, snapshot=snapshot, compiled_script=compiled_script,
                  request_same_source_sha256=request_same_source_sha256)


def build_script_delta(script, native_goal, snapshot, *, native_comparison, goal_context_sha256, bundle_sha256, compiled_script=None, request_same_source_sha256=None):
    frame = _script_frame(script, native_goal, snapshot, native_comparison=native_comparison,
        goal_context_sha256=goal_context_sha256, bundle_sha256=bundle_sha256, compiled_script=compiled_script,
        request_same_source_sha256=request_same_source_sha256)
    return {key: frame[key] for key in ("payload_delta", "manifest")}


def build_script_schema(script, native_goal, snapshot, *, native_comparison, goal_context_sha256, bundle_sha256, context_sha256, compiled_script=None, request_same_source_sha256=None):
    frame = _script_frame(script, native_goal, snapshot, native_comparison=native_comparison,
        goal_context_sha256=goal_context_sha256, bundle_sha256=bundle_sha256, compiled_script=compiled_script,
        request_same_source_sha256=request_same_source_sha256)
    return _schema(frame, native_goal, context_sha256)


def validate_script(document, script, native_goal, snapshot, *, native_comparison, goal_context_sha256, bundle_sha256, context_sha256, compiled_script=None, request_same_source_sha256=None):
    frame = _script_frame(script, native_goal, snapshot, native_comparison=native_comparison,
        goal_context_sha256=goal_context_sha256, bundle_sha256=bundle_sha256, compiled_script=compiled_script,
        request_same_source_sha256=request_same_source_sha256)
    return _validate(document, frame, native_goal, context_sha256)


def attach_script_delta(payload, script, native_goal, snapshot, *, native_comparison,
                        goal_context_sha256, bundle_sha256, compiled_script=None):
    """Bind actual request objects; raw tool and compiled identities stay distinct."""
    if payload.get("native_goal_document") != native_goal or payload.get("native_script_document") != script:
        raise ValueError("actual semantic payload differs from exact native goal/script")
    actual_compiled = payload.get("full_current_script")
    if actual_compiled is not None and compiled_script is not None and actual_compiled != compiled_script:
        raise ValueError("provided compiled object differs from actual payload")
    built = build_script_delta(script, native_goal, snapshot, native_comparison=native_comparison,
        goal_context_sha256=goal_context_sha256, bundle_sha256=bundle_sha256,
        compiled_script=compiled_script if compiled_script is not None else actual_compiled,
        request_same_source_sha256=payload.get("same_source_sha256"))
    if any(key in payload for key in built["payload_delta"]):
        raise ValueError("comparison input must occur once")
    return {"payload": {**deepcopy(payload), **built["payload_delta"]}, "manifest": built["manifest"]}
