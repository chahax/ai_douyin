"""Source-only claims frozen before comparison with a fallible actual ledger.

Pure contracts and compilation only.  Native payloads contain domain values;
source identities and deterministic claim IDs belong to local envelopes.
"""
from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator, ValidationError
from scripts import creative_isolated_event_entailment_v3 as facts

base = facts.prior.base
VERSION = "creative_isolated_source_claims/v1"
CLAIMS_VERSION, COMPARISON_VERSION = VERSION + "/source_claims_payload", VERSION + "/claims_comparison_payload"
digest = facts.digest

SOURCE_RULE = (
    "本阶段只读source_fields与逐字source_units，不提供actual_steps/ledger/旧审查；独立提取源自己宣称的事实，不迁就一份实际表演。"
    "units数组按source_unit_order逐项返回{parts:[...]},每项text按序逐字拼接必须还原对应完整unit.text，项数必须相等。标点分片仅定位，不保证语义原子；并列义项分开，不能保留一句原文却只抽其中好证明的子句。"
    "speech/action/state表示该片宣称的事件；context区分背景、目标意图、心理解读、未来结果。背景和未实现目标不强迫新增操作或口播。"
    "force表示言语施为类型，需结合原文命题及交际功能判断，不由句末标点单独判定。"
    "required_content_form仅指所要求/承诺内容形式，未指定=unspecified；deadline未指定填空字符串。"
    "occurrence是言语/动作的发生轴，content_phase是内容时态，两者独立；概括叙述与直接引语均按其事实断言状态提取，不能仅因内容涉及未来便改成背景或意图。"
    "未知义项用unknown并说明；每片的原文就是待证声明，不另改写一份较弱proposition。只能使用actors里的身份；非人物状态可actor_ids空。"
    "temporal_requirement区分none、信息已可供本拍反应的available_before_response、原文明确要求完成的completed_before_response、unknown。"
    "stimulus/trigger的当前speech/action通常要求信息可达，不要求整句说完或整个动作结束，不能为比较强写完成先后。"
    "不填本地版本/hash/claimID，不输出质量pass；分类、拆分、语义仍是模型判断，完整字符覆盖不是语义正确证明。"
)
COMPARE_RULE = (
    "比较已冻结source_claims与actual_ledger；不能修改源claims的原文、角色、force、形式或发生轴，不能用源概要补实际事件。"
    "checks数组按compiled_claim_order逐项整体比较全部义项，项数必须相等；不回填ID。主体、施为类型、命题、必要内容形式与期限分别核证，同主题或同场景不代表同一义项已经获得支持。"
    "当前说出的承诺与未来履行两轴分开；背景、意图和开放结果已由源阶段另列，不强迫兑现。"
    "support/counterevidence/response_refs使用typed step_ref/event_index，选实际ledger事件，不自行维护派生ID。"
    "response_refs选本拍反应；信息可达与整句/动作完成不同，available_before或during允许自然重叠，temporal_evidence引刺激与反应的原steps短句。"
    "只有冻结claim明确completed_before_response才要求原证据完成图路径；不能靠E文档序补先后。无足够依据ordering=unknown，明确相反ordering=violated。"
    "state可由动作呈现，不能仅因action/state标签不同否认可观察状态。"
    "actual_ledger仍是可出错的提取，actual_steps与原边quote保留；发现提取/先后解释与原文冲突，facts=uncertain并说明，停止而不拿它当无误真值。"
    "支持须同一speech同时匹配actor/force及必要内容形式；deadline具体语义交你判断，不用自然语言字符串不等当机械矛盾。"
    "supported不可有未解决counterevidence；missing/contradicted为明确缺口，unknown或facts uncertain停止。reason只短述关键差别。"
    "revision_target仅none/script/plan，只有明确内容失败才script，源本身必须改才plan；不输出overall pass。"
)


def _obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _arr(items): return {"type": "array", "items": items}
def _enum(values): return {"type": "string", "enum": list(values)}
def _string(): return {"type": "string"}


def _units(fields):
    """Stable strong-punctuation ranges; never a natural-language atomizer."""
    units = {}
    for field_ref, field in fields.items():
        pieces = [m.group(0) for m in re.finditer(r"[^。；！？\n]*(?:[。；！？\n]|$)", field["text"]) if m.group(0)]
        if "".join(pieces) != field["text"]: raise ValueError("source unit compilation lost characters")
        offset = 0
        for text in pieces:
            units[f"S{len(units)+1:04d}"] = {"field_ref": field_ref, "start": offset, "end": offset + len(text), **deepcopy(field), "text": text}
            offset += len(text)
    return units


def _claims_schema(payload):
    actors = [a["id"] for a in payload["actors"]]
    common = {"text": _string(), "occurrence": _enum(("occurred", "intended", "conditional", "unknown")),
        "content_phase": _enum(("past", "current", "future", "open", "unspecified", "unknown")),
        "temporal_requirement": _enum(("none", "available_before_response", "completed_before_response", "unknown"))}
    speech = _obj({"tag": _enum(("speech",)), **common, "actor_id": _enum(actors),
        "force": _enum(base.FORCES), "required_content_form": _enum(("written", "oral", "unspecified", "unknown")), "deadline": _string()})
    alternatives = [speech]
    for tag in ("action", "state"):
        alternatives.append(_obj({"tag": _enum((tag,)), **common, "actor_ids": _arr(_enum(actors))}))
    alternatives += [_obj({"tag": _enum(("context",)), "text": _string(), "mode": _enum(("background", "goal", "mental", "open_future"))}),
        _obj({"tag": _enum(("unknown",)), "text": _string(), "reason": _string()})]
    schema = _obj({"units": _arr(_obj({"parts": _arr({"$ref": "#/$defs/part"})}))})
    schema["$defs"] = {"part": {"anyOf": alternatives}}
    return schema


def _request(inputs, profile, raw, views, payload, schema, rule, kind, descriptor):
    actual = deepcopy(profile)
    actual.setdefault("stage_parameters", {}).setdefault("full_review", {})["max_completion_tokens"] = 16000
    result = base._request(inputs, actual, raw, views, payload, schema, rule, kind, descriptor)
    result["views"]["profile"] = deepcopy(profile)
    result["request"]["input_provenance"].update(isolated_source_claims_version=VERSION, stage_kind=kind)
    result["manifest"].update(schema=VERSION + "/manifest", stage_kind=kind,
        native_protocol_version=VERSION, source_character_coverage_is_semantic_proof=False,
        profile_projection={"original_profile_sha256": digest(profile), "actual_profile_sha256": digest(actual),
            "changed": "stage_parameters.full_review.max_completion_tokens:16000"})
    # The fixed new selector is part of the logical request before freeze/claim.
    from scripts import creative_isolated_claims_strict_role_clients_v1 as strict
    result["request"] = strict.bind_request(result["request"])
    result["manifest"]["strict_protocol_binding_sha256"] = digest(result["request"]["input_provenance"]["source_protocol_binding"])
    result.update(wire=strict.expected_wire_request(result["request"]), request_sha256=digest(result["request"]))
    return result


def prepare_claims(inputs, profile, raw, views):
    compiled = base._source(inputs, raw, views)
    fields = base._fields(views["goal"], compiled["derived_script"]); units = _units(fields)
    payload = {"actors": base._actors(views["goal"]), "source_fields": fields, "source_unit_order": list(units),
        "source_units": {ref: {k: deepcopy(value) for k, value in unit.items() if k in ("field_ref", "start", "end", "text")} for ref, unit in units.items()}}
    # Full field text appears once; units are exact slices, not a second source authority.
    payload["source_fields"] = {ref: {k: deepcopy(value) for k, value in field.items() if k != "text"} for ref, field in fields.items()}
    result = _request(inputs, profile, raw, views, payload, _claims_schema(payload), SOURCE_RULE, "source_claims", compiled["source_descriptor"])
    result["views"].update(source_fields=fields, source_units=units)
    result["manifest"].update(withheld_context=["actual_steps", "actual_ledger", "R01", "legal_authority", "old_reviews", "manual_expected_answers"],
        source_field_count=len(fields), source_character_count=sum(len(f["text"]) for f in fields.values()), source_unit_count=len(units),
        source_only_isolation=True)
    return result


def _invalid(exc, stage):
    result = base._invalid(exc, stage)
    result.update(isolated_source_claims_version=VERSION, claims_usable=False)
    return result


def _envelope(native, prepared):
    return {"schema": VERSION + "/local_source_envelope", "native_report_sha256": digest(native),
        "actual_request_sha256": prepared["request_sha256"], "actual_context_sha256": prepared["context_sha256"],
        "source_descriptor": deepcopy(prepared["source_descriptor"]), "compiled_object_is_model_native": False,
        "native_domain_rewritten": False}


def validate_claims(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_claims(v["inputs"], v["profile"], v["native_script"], v["compiler_views"]): raise ValueError("source-only request or authority differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        claims, contexts, uncertainties = {}, {}, []
        if len(native["units"]) != len(v["source_units"]): raise ValueError("native units must exactly cover source_unit_order")
        for ref, native_unit in zip(v["source_units"], native["units"]):
            parts = native_unit["parts"]
            unit = v["source_units"][ref]
            if not parts or any(not p["text"] for p in parts) or "".join(p["text"] for p in parts) != unit["text"]:
                raise ValueError("unit parts must preserve all exact source characters: " + ref)
            offset = unit["start"]
            for index, part in enumerate(parts):
                cid = f"{ref}#{index}"
                row = {"unit_ref": ref, "part_index": index, "field_ref": unit["field_ref"], "source": unit["source"],
                    "path": unit["path"], "role": unit["role"], "beat_id": unit["beat_id"],
                    "start": offset, "end": offset + len(part["text"]), **deepcopy(part)}
                offset = row["end"]
                if part["tag"] == "context": contexts[cid] = row
                elif part["tag"] == "unknown": uncertainties.append({"claim_ref": cid, "reason": part["reason"]})
                else:
                    if part["tag"] != "speech" and len(set(part["actor_ids"])) != len(part["actor_ids"]): raise ValueError("duplicate source actor")
                    claims[cid] = row
                    if any(part.get(k) == "unknown" for k in ("occurrence", "content_phase", "force", "required_content_form", "temporal_requirement")):
                        uncertainties.append({"claim_ref": cid, "reason": "source assertion unknown slot"})
                    if unit["role"] in ("stimulus", "trigger") and part["tag"] in ("speech", "action") and part["occurrence"] == "occurred" and part["temporal_requirement"] == "none":
                        uncertainties.append({"claim_ref": cid, "reason": "current causal source claim has no declared information-availability interpretation"})
        if not claims and not uncertainties: raise ValueError("complete narrative requires at least one observable source claim; all-context cannot pass")
        compiled = {"schema": VERSION + "/compiled_claims", "native_claims_sha256": digest(native),
            "source_descriptor": deepcopy(prepared["source_descriptor"]), "claims": claims, "claim_order": list(claims), "contexts": contexts,
            "source_field_sha256": digest(v["source_fields"]), "source_units_sha256": digest(v["source_units"]),
            "exact_character_coverage": True, "classification_is_fallible_model_interpretation": True}
        return {"valid": True, "accepted": not uncertainties, "claims_usable": not uncertainties,
            "status": "halt_source_claims_unknown" if uncertainties else "source_claims_frozen_not_content_approval",
            "findings": [], "uncertainties": uncertainties, "compiled_claims": compiled, "compiled_claims_sha256": digest(compiled),
            "native_report_sha256": digest(native), "local_source_envelope": _envelope(native, prepared),
            "semantic_meaning_programmatically_verified": False}
    except (ValidationError, ValueError, TypeError, KeyError) as exc: return _invalid(exc, "source_claims")


def _comparison_schema(payload):
    refs = list(payload["actual_ledger"]["source_steps"])
    endpoint = _obj({"step_ref": _enum(refs), "event_index": {"type": "integer"}})
    row = _obj({"verdict": _enum(("supported", "missing", "contradicted", "unknown")),
        "support": _arr({"$ref": "#/$defs/endpoint"}), "counterevidence": _arr({"$ref": "#/$defs/endpoint"}),
        "response_refs": _arr({"$ref": "#/$defs/endpoint"}), "ordering": _enum(("not_required", "available_before", "during", "completed_before", "violated", "unknown")),
        "temporal_evidence": _arr(_obj({"step_ref": _enum(refs), "quote": _string()})),
        "facts": _enum(("clear", "uncertain")), "reason": _string()})
    schema = _obj({"checks": _arr({"$ref": "#/$defs/check"}),
        "revision_target": _enum(("none", "script", "plan"))})
    schema["$defs"] = {"endpoint": endpoint, "check": row}
    return schema


def prepare_comparison(inputs, profile, raw, views, claims_native, claims_prepared, events_native, events_prepared):
    if claims_prepared != prepare_claims(inputs, profile, raw, views): raise ValueError("claims request source differs")
    if events_prepared != facts.prepare_events(inputs, profile, raw, views): raise ValueError("actual ledger request source differs")
    cd, ed = validate_claims(claims_native, claims_prepared), facts.validate_events(events_native, events_prepared)
    if not cd["valid"] or not cd["claims_usable"] or not ed["valid"] or not ed["ledger_usable"]: raise ValueError("complete usable same-source claims and actual ledger required")
    payload = {"source_claims": cd["compiled_claims"], "compiled_claim_order": cd["compiled_claims"]["claim_order"], "actual_ledger": ed["compiled_ledger"]}
    result = _request(inputs, profile, raw, views, payload, _comparison_schema(payload), COMPARE_RULE, "claims_comparison", claims_prepared["source_descriptor"])
    result["views"].update(claims_native=deepcopy(claims_native), claims_prepared=deepcopy(claims_prepared),
        events_native=deepcopy(events_native), events_prepared=deepcopy(events_prepared))
    result["manifest"].update(frozen_source_claims_sha256=cd["compiled_claims_sha256"],
        actual_ledger_sha256=ed["compiled_ledger_sha256"], source_claims_cannot_be_reclassified_in_response=True)
    return result


def _refs(items, ledger):
    refs = []
    for endpoint in items:
        index = endpoint["event_index"]; ref = f"{endpoint['step_ref']}#{index}"
        if type(index) is not int or index < 0 or ref not in ledger["events"]: raise ValueError("typed actual endpoint out of bounds")
        refs.append(ref)
    if len(set(refs)) != len(refs): raise ValueError("duplicate actual endpoint")
    return refs


def validate_comparison(native, prepared):
    try:
        v = prepared["views"]
        if prepared != prepare_comparison(v["inputs"], v["profile"], v["native_script"], v["compiler_views"],
                v["claims_native"], v["claims_prepared"], v["events_native"], v["events_prepared"]): raise ValueError("comparison source/request differs")
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(native)
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        claims, ledger = payload["source_claims"], payload["actual_ledger"]
        reach = facts._closure(ledger["events"], ledger["temporal_relations"])
        findings, computed, uncertainties = [], [], []
        if len(native["checks"]) != len(claims["claim_order"]): raise ValueError("native checks must exactly cover frozen compiled_claim_order")
        for cid, row in zip(claims["claim_order"], native["checks"]):
            claim = claims["claims"][cid]; support, counter, response = (_refs(row[k], ledger) for k in ("support", "counterevidence", "response_refs"))
            loc = {"claim_ref": cid, "field_ref": claim["field_ref"], "unit_ref": claim["unit_ref"], "part_index": claim["part_index"]}
            for proof in row["temporal_evidence"]:
                if not proof["quote"].strip() or proof["quote"] not in ledger["source_steps"][proof["step_ref"]]["text"]: raise ValueError("temporal evidence quote differs from actual step")
            if not row["reason"].strip(): raise ValueError("short comparison reason required")
            if row["verdict"] == "unknown" or row["facts"] == "uncertain" or row["ordering"] == "unknown": uncertainties.append({**loc, "reason": row["reason"]})
            if row["verdict"] in ("missing", "contradicted"): findings.append({**loc, "finding": deepcopy(row), "target": native["revision_target"]})
            if row["verdict"] != "supported": continue
            if not support: raise ValueError("supported claim requires actual event evidence")
            if counter: uncertainties.append({**loc, "reason": "supported claim retains unresolved counterevidence"})
            candidates = [ledger["events"][r] for r in support]
            if claim["tag"] == "speech":
                fits = any(e["kind"] == "speech" and e["actor_id"] == claim["actor_id"] and e["speech_force"] == claim["force"]
                    and e["occurrence"] == claim["occurrence"] and (claim["required_content_form"] == "unspecified" or e["required_content_form"] == claim["required_content_form"])
                    and (not claim["deadline"] or e["deadline"] is not None) for e in candidates)
            else:
                fits = all(any(e["actor_id"] == actor and e["kind"] != "speech" and e["occurrence"] == claim["occurrence"] for e in candidates) for actor in claim["actor_ids"])
                if not claim["actor_ids"]: fits = any(e["kind"] != "speech" and e["occurrence"] == claim["occurrence"] for e in candidates)
            if not fits: computed.append({**loc, "code": "FROZEN_CLAIM_SLOTS_UNSUPPORTED", "native_verdict": row["verdict"], "target": "script"})
            requirement = claim["temporal_requirement"]
            causal = requirement in ("available_before_response", "completed_before_response")
            if causal and row["ordering"] == "not_required": uncertainties.append({**loc, "reason": "frozen causal source claim needs relation to this beat response"})
            if row["ordering"] == "violated": computed.append({**loc, "code": "FROZEN_CAUSAL_ORDER_VIOLATED", "target": "script"})
            if causal or row["ordering"] in ("available_before", "during", "completed_before"):
                if not response or any(ledger["events"][r]["beat_id"] != claim["beat_id"] for r in response):
                    uncertainties.append({**loc, "reason": "causal response must be identified in the claimed beat"})
                proof_steps = {proof["step_ref"] for proof in row["temporal_evidence"]}
                if not {ledger["events"][r]["step_ref"] for r in support + response}.issubset(proof_steps):
                    uncertainties.append({**loc, "reason": "stimulus and response need their actual step quotes"})
                if requirement == "completed_before_response" and row["ordering"] != "completed_before":
                    uncertainties.append({**loc, "reason": "source explicitly requires completion; information availability alone does not prove it"})
                if row["ordering"] == "completed_before" and not all(b in reach[a] for a in support for b in response):
                    uncertainties.append({**loc, "reason": "no evidenced completed-before path; document order not substituted"})
        if bool(findings) != (native["revision_target"] != "none"): raise ValueError("native target and explicit missing/contradicted claims disagree")
        target = native["revision_target"] if native["revision_target"] != "none" else "script" if computed else "none"
        return {"valid": True, "accepted": not findings and not computed and not uncertainties,
            "status": "halt_claims_comparison_unknown" if uncertainties else "needs_new_goal_plan" if target == "plan" else "needs_whole_revision" if findings or computed else "claims_comparison_passed",
            "findings": findings + computed, "computed_slot_findings": computed, "uncertainties": uncertainties,
            "revision_target": target, "native_revision_target": native["revision_target"], "requires_new_goal_plan": target == "plan",
            "native_report_sha256": digest(native), "compiled_claims_sha256": digest(claims), "compiled_ledger_sha256": digest(ledger),
            "local_source_envelope": _envelope(native, prepared), "native_verdict_values_rewritten": False,
            "semantic_meaning_programmatically_verified": False}
    except (ValidationError, ValueError, TypeError, KeyError) as exc: return _invalid(exc, "claims_comparison")


def build_review_packet(claims_native, claims_prepared, events_native, events_prepared, comparison_native, comparison_prepared):
    cd, ed = validate_claims(claims_native, claims_prepared), facts.validate_events(events_native, events_prepared)
    decision = validate_comparison(comparison_native, comparison_prepared)
    if not cd.get("claims_usable") or not ed.get("ledger_usable") or not decision["valid"]: raise ValueError("complete valid same-source native reports required")
    v = comparison_prepared["views"]
    if any(v[key] != value for key, value in (("claims_native", claims_native), ("claims_prepared", claims_prepared), ("events_native", events_native), ("events_prepared", events_prepared))): raise ValueError("packet source identities differ")
    return {"schema": VERSION + "/review_packet", "native_source_claims_report": deepcopy(claims_native),
        "native_observable_events_report": deepcopy(events_native), "native_claim_comparison_report": deepcopy(comparison_native),
        "verified_compiled_source_claims": cd["compiled_claims"], "verified_compiled_event_ledger": ed["compiled_ledger"],
        "functional_decision": deepcopy(decision), "source_descriptor": deepcopy(comparison_prepared["source_descriptor"]),
        "local_source_envelopes": {"claims": cd["local_source_envelope"], "events": ed["local_source_envelope"], "comparison": decision["local_source_envelope"]},
        "native_reports_rewritten": False}


def build_repair_feedback(*args):
    decision = validate_comparison(args[4], args[5])
    if not decision["valid"] or decision["accepted"] or decision["uncertainties"] or decision["requires_new_goal_plan"]: raise ValueError("only definite valid fixed-source script failure admits writer")
    packet = build_review_packet(*args); packet["schema"] = VERSION + "/repair_feedback"
    return packet
