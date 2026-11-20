"""Two isolated, fallible semantic stages with exact native/source identities.

No model calls or content rewriting.  Deterministic slot checks are conditional
on the model's extraction/classification; they are not natural-language proof.
"""
from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator, ValidationError

from scripts import creative_world_scene_derived_context_script_v1 as source
from scripts import creative_world_scene_replanned_workflow_v3 as workflow

VERSION = "creative_isolated_event_entailment/v1"
EVENTS_VERSION = VERSION + "/observable_events"
ENTAILMENT_VERSION = VERSION + "/claim_comparison"
LEDGER_VERSION = VERSION + "/compiled_ledger"
digest = source.digest
FORCES = ("inquiry", "request", "inform", "offer", "promise", "acceptance", "refusal", "other", "unknown")
KINDS = ("speech", "action", "state")
ROLES = ("event_claim", "context", "goal", "open_future", "mental_performance", "unknown")
ENDING_FIELDS = ("attempt_result", "visible_consequence", "emotional_landing", "open_legal_question")

EVENT_RULE = (
    "只提取actual_steps中实际可观察的言语/动作/状态，不评价剧情质量、不补写事件。"
    "本阶段刻意不提供规划、premise/event/trigger概要、法律、R01或旧审查，不能据想象补全。"
    "逐E覆盖；recorded有events，no_observable_event为空并说明，读不清用unknown。"
    "每event.source_quote必须是自身E.text非空逐字片段。speech必须有actor_id和speech_force，非speech的speech_force=null。"
    "言语actor_id是实际说话者，不能拿动作方替代别人已说的话；"
    "dialogue步骤除明确disposition=unknown外至少记录一项该speaker已说出的speech，occurrence=occurred。action中明确的原话也可记录speech。"
    "speech_force描述语用行为而非标点句式，间接问句也可能是在请求；不能把追问/告知自动升级为要求/承诺。"
    "content_medium指要求/承诺内容的书面或口头形式，不是开口说话的声道；deadline仅明确期限原文，未指定用null。"
    "occurrence描述该言语行为/操作本身是否发生，content_phase另描述所谈内容的时态。承诺现在已说出而未来履行开放可以同时成立。"
    "proposition简短忠实；背景不编成已完成操作。未知槽保unknown，不装作一致。"
    "事件ID由本地按Eref#events数组索引派生，不另填ID。temporal_relations只列原文/故事时间有据的已发生先后，"
    "before_event/after_event使用上述派生ID，evidence引Eref及逐字短quote，reason说明关系依据。"
    "步骤文档序不自动等于完成先后；可并行/同时不提供完成边，无足够依据就不造边。边端点必须occurred，不能重复边或成环。"
    "不输出overall pass。逐字引用和全E覆盖不证明语义提取穷尽或正确。"
)
COMPARE_RULE = (
    "比较source_fields全部字段与已冻结compiled_event_ledger，不能改ledger，不用概要反向补实际事件。"
    "每个F必须source_segments，source_text按序逐字拼接恰好还原该F.text，包括全部并列分句与标点；"
    "按事实原子拆分，不用其中可演子句代证同字段其它已说/已答应/已完成的断言。拆分与分类仍是你的语义责任。"
    "role区分event_claim/context/goal/open_future/mental_performance/unknown。背景、目标、内心与神情不强迫新增对白/操作；"
    "没有达成目标不当然失败。已承诺是当前已发生的言语行为，承诺未来是否履行另看content_phase，不得把前者改称开放未来而免审。"
    "event_claim必须填写expected并引用匹配event_refs；expected为该原子声称的kind/actor/语用force/命题/必要medium/deadline/发生轴/内容时态。"
    "同一原子的actor、言语行为、命题与必要条件必须同时有据，不能只因同拍或同主题便蕴含；询问来源、要求落纸、告知、承诺各自区分。"
    "间接请求按语用判断不按疑问标点。仅你判为必要的非null槽才强制匹配，未规定medium/deadline用null。"
    "context/goal/open_future/mental_performance的expected=null，event_refs可空，verdict=not_required；unknown须verdict=unknown。"
    "event_claim verdict仅entailed/not_entailed/unknown；缺实际支持给not_entailed并解释，不伪造缺失台词。"
    "temporal_requirement=none不声明先后；before要求prior_event_refs是刺激先因、event_refs是反应，且ledger有据先后可达。"
    "无足够时序依据用unknown，不把E索引当物理完成证明。intent不等于occurred。"
    "reason只写简短逐原子比较；revision_target仅none/script/plan，明确内容缺口才script，必须改源规划才plan。"
    "原生verdict/target不会被程序改写；可证类型槽矛盾另列computed_slot_findings阻断，unknown优先停止。"
    "deadline是自然语言，程序只核必要期限在同一候选event非null存在，是否等义由你判断，不按字串不同宣称语义矛盾。"
    "不输出overall pass。程序不能证明你没有把事件错误分类成背景，也不能证明自然语言蕴含正确。"
)


def _obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def _text(blank=False, maximum=400):
    return {"type": "string", "minLength": 0 if blank else 1, "maxLength": maximum}


def _arr(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


def _nullable(rule): return {"anyOf": [rule, {"type": "null"}]}


def _source(inputs, raw, views):
    workflow.base.workflow._verify_views(inputs, views)
    return source.compile_document(raw, views["goal"], views["brief"])


def _steps(script):
    return {f"E:{beat['id']}:{i}": {"beat_id": beat["id"], "step_index": i,
        "scene_context_id": beat["scene_context_id"], **deepcopy(step)}
        for beat in script["beats"] for i, step in enumerate(beat["steps"])}


def _actors(goal):
    return [{"id": c["id"], "name": c["name"]} for c in goal["whole_plan"]["characters"]]


def _fields(goal, script):
    fields = {}
    def add(alias, path, role, beat_id, text):
        if type(text) is not str or not text.strip(): raise ValueError("nonempty narrative source field required")
        fields[f"F{len(fields)+1:04d}"] = {"source": alias, "path": path, "role": role, "beat_id": beat_id, "text": text}
    for i, beat in enumerate(goal["whole_plan"]["beats"]):
        for field in ("goal", "stimulus", "response", "strategy.after", "visible_change"):
            parts = field.split("."); text = beat
            for part in parts: text = text[part]
            add("goal", f"/whole_plan/beats/{i}/" + "/".join(parts), field, beat["id"], text)
    for i, beat in enumerate(script["beats"]):
        for field in ("event", "trigger"):
            add("script", f"/beats/{i}/{field}", field, beat["id"], beat[field])
    add("script", "/premise", "premise", "whole", script["premise"])
    for field in ENDING_FIELDS:
        add("goal", "/whole_plan/ending/" + field, "ending." + field, "ending", goal["whole_plan"]["ending"][field])
    return fields


def _slots(actor_ids):
    result = _obj({"kind": {"enum": list(KINDS)}, "actor_id": _nullable({"enum": actor_ids}),
        "speech_force": _nullable({"enum": list(FORCES)}), "proposition": _text(),
        "content_medium": _nullable({"enum": ["written", "oral", "unspecified", "unknown"]}),
        "deadline": _nullable(_text(maximum=100)),
        "occurrence": {"enum": ["occurred", "intended", "conditional", "unknown"]},
        "content_phase": {"enum": ["past", "current", "future", "open", "unspecified", "unknown"]}})
    result["allOf"] = [
        {"if": {"properties": {"kind": {"const": "speech"}}}, "then": {"properties": {
            "actor_id": {"enum": actor_ids}, "speech_force": {"enum": list(FORCES)}}}},
        {"if": {"properties": {"kind": {"enum": ["action", "state"]}}}, "then": {"properties": {
            "speech_force": {"type": "null"}}}}]
    return result


def _headers(version, context, descriptor):
    return {"schema": {"const": version}, "context_sha256": {"const": context},
        "origin_native_script_sha256": {"const": descriptor["native_script_sha256"]}}


def _event_schema(payload, descriptor):
    slots = _slots([a["id"] for a in payload["actors"]])
    event = _obj({**slots["properties"], "source_quote": _text(maximum=500)})
    event["allOf"] = deepcopy(slots["allOf"])
    row = _obj({"disposition": {"enum": ["recorded", "no_observable_event", "unknown"]},
        "reason": _text(), "events": _arr({"$ref": "#/$defs/event"})})
    row["allOf"] = [
        {"if": {"properties": {"disposition": {"const": "recorded"}}}, "then": {"properties": {"events": {"minItems": 1}}}},
        {"if": {"properties": {"disposition": {"const": "no_observable_event"}}}, "then": {"properties": {"events": {"maxItems": 0}}}}]
    event_ref = {"type": "string", "pattern": "^(?:" + "|".join(re.escape(e) for e in payload["actual_steps"]) + r")#[0-9]+$"}
    relation = _obj({"before_event": event_ref, "after_event": deepcopy(event_ref), "reason": _text(),
        "evidence": _arr(_obj({"step_ref": {"enum": list(payload["actual_steps"])}, "quote": _text(maximum=240)}), 1)})
    result = _obj({**_headers(EVENTS_VERSION, digest(payload), descriptor),
        "steps": _obj({ref: {"$ref": "#/$defs/step"} for ref in payload["actual_steps"]}),
        "temporal_relations": _arr(relation)})
    result["$defs"] = {"event": event, "step": row}
    return result


def _comparison_schema(payload, descriptor):
    refs = list(payload["compiled_event_ledger"]["events"])
    ref_rule = {"enum": refs} if refs else {"type": "string", "maxLength": 0}
    segment = _obj({"source_text": _text(maximum=2500), "role": {"enum": list(ROLES)},
        "expected": _nullable({"$ref": "#/$defs/slots"}), "event_refs": _arr(ref_rule),
        "verdict": {"enum": ["entailed", "not_entailed", "not_required", "unknown"]},
        "temporal_requirement": {"enum": ["none", "before", "unknown"]},
        "prior_event_refs": _arr(deepcopy(ref_rule)), "reason": _text()})
    segment["allOf"] = [
        {"if": {"properties": {"role": {"const": "event_claim"}}}, "then": {"properties": {
            "expected": {"$ref": "#/$defs/slots"}, "verdict": {"enum": ["entailed", "not_entailed", "unknown"]}}}},
        {"if": {"properties": {"role": {"enum": ["context", "goal", "open_future", "mental_performance"]}}}, "then": {
            "properties": {"expected": {"type": "null"}, "verdict": {"const": "not_required"},
                "temporal_requirement": {"const": "none"}, "prior_event_refs": {"maxItems": 0}}}},
        {"if": {"properties": {"role": {"const": "unknown"}}}, "then": {"properties": {"verdict": {"const": "unknown"}}}},
        {"if": {"properties": {"verdict": {"const": "entailed"}}}, "then": {"properties": {"event_refs": {"minItems": 1}}}},
        {"if": {"properties": {"temporal_requirement": {"const": "before"}}}, "then": {"properties": {
            "event_refs": {"minItems": 1}, "prior_event_refs": {"minItems": 1}}}}]
    result = _obj({**_headers(ENTAILMENT_VERSION, digest(payload), descriptor),
        "compiled_ledger_sha256": {"const": digest(payload["compiled_event_ledger"])},
        "fields": _obj({ref: {"$ref": "#/$defs/field"} for ref in payload["source_fields"]}),
        "revision_target": {"enum": ["none", "script", "plan"]}})
    result["$defs"] = {"slots": _slots([a["id"] for a in payload["actors"]]), "segment": segment,
        "field": _obj({"source_segments": _arr({"$ref": "#/$defs/segment"}, 1)})}
    return result


def _request(inputs, profile, raw, views, payload, schema, rule, stage, descriptor):
    measure = workflow.base.workflow.contexts._measure(payload)
    policy = workflow.base.workflow.contexts.prior._policy("full_review", inputs)
    if measure["characters"] > policy["max_payload_characters"] or measure["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
        raise ValueError("isolated review context exceeds existing full_review policy; no truncation")
    Draft202012Validator.check_schema(schema)
    result = source.world._request("full_review", profile, rule, payload, schema,
        manifest={"schema": VERSION + "/manifest", "isolated_stage": stage, "context_policy": policy,
            "payload_identity": measure, "source_descriptor": descriptor, "original_inputs_sha256": digest(inputs),
            "intentional_evidence_isolation": True, "reference_occurrences": 0,
            "reference_presence_requirement": "not sent in these isolated diagnostic stages; retained by creative and full reviews",
            "withheld_context": ["R01", "legal_authority", "platform_samples", "old_reviews", "manual_expected_answers"],
            "no_manual_expected_findings_in_request": True, "semantic_meaning_programmatically_verified": False},
        provenance={"isolated_event_entailment_version": VERSION, "isolated_stage": stage,
            "origin_native_script_sha256": descriptor["native_script_sha256"]})
    result.update(context_sha256=digest(payload), source_descriptor=deepcopy(descriptor),
        views={"inputs": deepcopy(inputs), "profile": deepcopy(profile), "native_script": deepcopy(raw), "compiler_views": deepcopy(views)},
        dispatch_performed=False, sdk_max_retries=0, server_schema_guarantee=False)
    return result


def prepare_events(inputs, profile, raw, views):
    compiled = _source(inputs, raw, views)
    script = compiled["derived_script"]
    payload = {"schema": VERSION + "/events_context", "actors": _actors(views["goal"]),
        "scene_locators": [{"id": c["id"], "scene_id": c["scene_id"], "story_time": c["story_time"]} for c in script["scene_contexts"]],
        "actual_steps": _steps(script)}
    result = _request(inputs, profile, raw, views, payload, _event_schema(payload, compiled["source_descriptor"]),
        EVENT_RULE, "actual_events", compiled["source_descriptor"])
    result["manifest"]["withheld_context"] += ["goal", "setup", "premise", "beat_event_trigger", "ensemble"]
    result["views"]["actual_steps"] = deepcopy(payload["actual_steps"])
    return result


def _invalid(exc, phase):
    if isinstance(exc, ValidationError):
        reason = "closed schema constraint: " + str(exc.validator)
        path = "/" + "/".join(map(str, exc.absolute_path))
    else: reason, path = str(exc), ""
    return {"valid": False, "accepted": False, "ledger_usable": False, "status": "halt_isolated_contract",
        "findings": [{"code": "ISOLATED_CONTRACT_INVALID", "reason": reason, "path": path}],
        "uncertainties": [], "isolated_stage": phase, "isolated_event_entailment_version": VERSION}


def _unknown_slots(event):
    return any(event[k] == "unknown" for k in ("speech_force", "content_medium", "occurrence", "content_phase"))


def _check_slots(event):
    if event["kind"] != "speech" and event["speech_force"] is not None:
        raise ValueError("non-speech event cannot claim a speech force")
    if event["kind"] == "speech" and (event["speech_force"] is None or event["actor_id"] is None):
        raise ValueError("speech actor and force required (or explicit unknown force)")


def _closure(events, relations):
    graph = {ref: set() for ref in events}
    pairs = set()
    for row in relations:
        a, b = row["before_event"], row["after_event"]
        if a not in graph or b not in graph or a == b: raise ValueError("temporal relation endpoints must be different compiled events")
        if (a, b) in pairs: raise ValueError("duplicate temporal event edge")
        pairs.add((a, b))
        if any(events[ref]["occurrence"] != "occurred" for ref in (a, b)):
            raise ValueError("completed-before evidence cannot promote intended or unknown event")
        graph[a].add(b)
    closure = {}
    for start in graph:
        reached, pending = set(), list(graph[start])
        while pending:
            node = pending.pop()
            if node == start: raise ValueError("temporal event relation cycle")
            if node not in reached: reached.add(node); pending.extend(graph[node] - reached)
        closure[start] = reached
    return closure


def validate_events(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"]):
            raise ValueError("observable event source/request identity differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        steps = v["actual_steps"]; events, uncertainties = {}, []
        for ref, row in native["steps"].items():
            step = steps[ref]
            if row["disposition"] == "unknown": uncertainties.append({"step_ref": ref, "reason": row["reason"]})
            spoken = []
            for index, event in enumerate(row["events"]):
                _check_slots(event)
                if not event["source_quote"].strip() or event["source_quote"] not in step["text"]:
                    raise ValueError("observable quote must be exact within its own actual E.text")
                if event["kind"] == "speech": spoken.append(event)
                event_id = f"{ref}#{index}"
                events[event_id] = {"step_ref": ref, "beat_id": step["beat_id"], "step_index": step["step_index"], **deepcopy(event)}
                if _unknown_slots(event): uncertainties.append({"event_ref": event_id, "reason": "native extraction has unknown typed slot"})
            if step["kind"] == "dialogue" and row["disposition"] != "unknown" and not any(e["actor_id"] == step["speaker"] and e["occurrence"] == "occurred" for e in spoken):
                raise ValueError("dialogue must include its original speaker's occurred speech act")
            if step["kind"] == "dialogue" and any(e["actor_id"] != step["speaker"] for e in spoken):
                raise ValueError("dialogue extraction cannot substitute another speaker")
        for row in native["temporal_relations"]:
            for proof in row["evidence"]:
                if not proof["quote"].strip() or proof["quote"] not in steps[proof["step_ref"]]["text"]:
                    raise ValueError("temporal quote must refer to its designated actual E.text")
        _closure(events, native["temporal_relations"])
        ledger = {"schema_version": LEDGER_VERSION, "native_events_sha256": digest(native),
            "native_script_sha256": prepared["source_descriptor"]["native_script_sha256"],
            "events": events, "source_steps": deepcopy(steps), "temporal_relations": deepcopy(native["temporal_relations"]),
            "step_coverage": {ref: row["disposition"] for ref, row in native["steps"].items()},
            "extraction_is_fallible_model_interpretation": True, "document_order_is_completed_time": False}
        return {"valid": True, "accepted": not uncertainties, "ledger_usable": not uncertainties,
            "status": "halt_observable_events_unknown" if uncertainties else "observable_ledger_usable_not_content_approval",
            "findings": [], "uncertainties": uncertainties, "compiled_ledger": ledger,
            "compiled_ledger_sha256": digest(ledger), "native_report_sha256": digest(native),
            "source_descriptor": deepcopy(prepared["source_descriptor"]), "context_sha256": prepared["context_sha256"],
            "isolated_event_entailment_version": VERSION, "semantic_meaning_programmatically_verified": False}
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc, "actual_events")


def prepare_entailment(inputs, profile, raw, views, events_native, events_prepared):
    expected_prepared = prepare_events(inputs, profile, raw, views)
    if events_prepared != expected_prepared: raise ValueError("comparison extractor source differs")
    decision = validate_events(events_native, events_prepared)
    if not decision["valid"] or not decision["ledger_usable"]: raise ValueError("comparison requires a fully usable native observable ledger")
    compiled = _source(inputs, raw, views)
    fields = _fields(views["goal"], compiled["derived_script"])
    payload = {"schema": VERSION + "/comparison_context", "actors": _actors(views["goal"]),
        "source_fields": fields, "compiled_event_ledger": decision["compiled_ledger"]}
    result = _request(inputs, profile, raw, views, payload, _comparison_schema(payload, compiled["source_descriptor"]),
        COMPARE_RULE, "event_entailment", compiled["source_descriptor"])
    result["views"].update(source_fields=deepcopy(fields), events_native=deepcopy(events_native), events_prepared=deepcopy(events_prepared))
    return result


def validate_entailment(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], v["events_native"], v["events_prepared"]):
            raise ValueError("claim comparison source/request identity differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        ledger = payload["compiled_event_ledger"]; events = ledger["events"]
        reach = _closure(events, ledger["temporal_relations"])
        findings, computed, uncertainties = [], [], []
        for ref, row in native["fields"].items():
            segments = row["source_segments"]
            if "".join(s["source_text"] for s in segments) != v["source_fields"][ref]["text"]:
                raise ValueError("source_segments must exactly concatenate the entire designated F.text: " + ref)
            for index, segment in enumerate(segments):
                location = {"field_ref": ref, "segment_index": index}
                if segment["role"] == "unknown" or segment["verdict"] == "unknown" or segment["temporal_requirement"] == "unknown":
                    uncertainties.append({**location, "reason": segment["reason"]})
                if segment["verdict"] == "not_entailed": findings.append({**location, "finding": deepcopy(segment), "target": native["revision_target"]})
                expected = segment["expected"]
                if expected is None: continue
                _check_slots(expected)
                if _unknown_slots(expected): uncertainties.append({**location, "reason": "native expected atom has unknown slot"})
                if segment["verdict"] != "entailed": continue
                candidates = [events[r] for r in segment["event_refs"]]
                necessary = ["kind", "occurrence"] + [k for k in ("actor_id", "speech_force") if expected[k] is not None]
                if expected["content_medium"] not in (None, "unspecified"): necessary.append("content_medium")
                # One coherent event must satisfy the atom's simultaneous typed
                # slots; unrelated records cannot each supply a different slot.
                if not any(all(event[k] == expected[k] for k in necessary) and
                           (expected["deadline"] is None or event["deadline"] is not None) for event in candidates):
                    computed.append({**location, "code": "TYPED_EVENT_SLOTS_NOT_SUPPORTED", "expected_slots": {k: expected[k] for k in necessary},
                        "deadline_presence_required": expected["deadline"] is not None,
                        "actual_event_refs": deepcopy(segment["event_refs"]), "native_verdict": segment["verdict"], "target": "script"})
                if segment["temporal_requirement"] == "before":
                    if not all(b in reach[a] for a in segment["prior_event_refs"] for b in segment["event_refs"]):
                        uncertainties.append({**location, "reason": "required completed-before relation lacks ledger evidence; no index-order inference"})
        if bool(findings) != (native["revision_target"] != "none"):
            raise ValueError("native revision_target must match its definite not_entailed atoms")
        all_findings = findings + computed
        target = native["revision_target"] if native["revision_target"] != "none" else "script" if computed else "none"
        return {"valid": True, "accepted": not all_findings and not uncertainties,
            "status": "halt_event_entailment_unknown" if uncertainties else "needs_new_goal_plan" if target == "plan" else "needs_whole_revision" if all_findings else "event_entailment_passed",
            "findings": all_findings, "computed_slot_findings": computed, "uncertainties": uncertainties,
            "revision_target": target, "native_revision_target": native["revision_target"],
            "requires_new_goal_plan": target == "plan", "native_report_sha256": digest(native),
            "compiled_ledger_sha256": digest(ledger), "source_descriptor": deepcopy(prepared["source_descriptor"]),
            "context_sha256": prepared["context_sha256"], "isolated_event_entailment_version": VERSION,
            "native_verdict_values_rewritten": False, "semantic_meaning_programmatically_verified": False, "human_quality_approved": False}
    except (ValidationError, ValueError, KeyError, TypeError) as exc: return _invalid(exc, "event_entailment")


def build_review_packet(events_native, events_prepared, comparison_native, comparison_prepared):
    event_decision = validate_events(events_native, events_prepared)
    decision = validate_entailment(comparison_native, comparison_prepared)
    if not event_decision["ledger_usable"] or not decision["valid"]:
        raise ValueError("review packet requires contract-valid same-source extraction and comparison")
    if comparison_prepared["views"]["events_native"] != events_native or comparison_prepared["views"]["events_prepared"] != events_prepared:
        raise ValueError("repair feedback ledger identity differs")
    used = {item["field_ref"] for item in decision["findings"]}
    directory = comparison_prepared["views"]["source_fields"]
    return {"schema": VERSION + "/review_packet", "native_observable_events_report": deepcopy(events_native),
        "native_claim_comparison_report": deepcopy(comparison_native), "verified_compiled_event_ledger": deepcopy(event_decision["compiled_ledger"]),
        "used_source_fields": {ref: {k: value for k, value in directory[ref].items() if k != "text"} for ref in directory if ref in used},
        "functional_decision": {k: deepcopy(decision[k]) for k in ("status", "revision_target", "native_revision_target", "computed_slot_findings", "uncertainties", "native_report_sha256", "compiled_ledger_sha256")},
        "source_descriptor": deepcopy(comparison_prepared["source_descriptor"]), "native_reports_rewritten": False}


def build_repair_feedback(events_native, events_prepared, comparison_native, comparison_prepared):
    decision = validate_entailment(comparison_native, comparison_prepared)
    if not decision["valid"] or decision["accepted"] or decision["uncertainties"] or decision["requires_new_goal_plan"]:
        raise ValueError("repair feedback requires a definite valid same-source script failure")
    packet = build_review_packet(events_native, events_prepared, comparison_native, comparison_prepared)
    packet["schema"] = VERSION + "/repair_feedback"
    return packet
