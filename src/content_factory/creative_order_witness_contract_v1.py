"""Isolated source-order candidate. No dispatch, production mutation or new draft.

The source model chooses the quantifier from frozen facts without seeing a
script. An actual witness groups native occurrences into episodes and links
responses. Every native occurrence remains covered: a later convenient pair
cannot erase an earlier response. Native speech-function conflicts stay unknown.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v1 as base
from . import creative_autonomous_text_contract_v2 as sources

VERSION = "creative_order_witness_contract/v1"
MODES = ("first_transition", "paired_response", "all_occurrences", "unknown")
SOURCE_RULE = (
    "只看冻结brief及源顺序，不看正文或旧审查。逐边依据原fact全文判断要求的先后量词："
    "first_transition表示第一次进入策略或行动阶段必须先于该阶段回应，允许阶段内继续交锋；"
    "paired_response表示回应须有已发生且相关的刺激，不要求全部刺激都先于全部回应；"
    "只有来源要求所有前项完成后才开始任何后项时使用all_occurrences。不得只因source_order"
    "叫先后就默认all_occurrences，不强迫一次对话完成整项。无法区分填unknown。"
    "source_quote按Schema回传完整冻结fact，不改来源、不开新剧情、不代写对白。")
WITNESS_RULE = (
    "只核对同一完整正文、原生literal_events与obligation_evidence、已知源边语义。"
    "用原生发生引用及原生span构成episode，所有before和after引用均须覆盖，不删早回应"
    "来凑后来一对；response_links按实际接话关系填写responds_to/independent/unknown。"
    "不能自行补充原审查缺失的request/refusal功能：原生义务说pass却其literal_events"
    "没有要求的行事功能时填unknown，保留矛盾。陈述式间接请求需要原生语用分类证据。"
    "first_transition验证最早已证实转入及随后回应；paired_response验证每个回应的已发生"
    "刺激；all_occurrences才比较全部发生窗口。不得以同一原文重叠子句冒充严格先后。"
    "fail给完整新正文目标，unknown如实保留，不改原审查、正文或源语义。")


def _digest(value):
    return base._digest(value)


def _source_inputs(plan, brief):
    facts = sources._facts(brief)
    obligations = {row["id"]: row for row in plan["source_obligations"]}
    if len(obligations) != len(plan["source_obligations"]):
        raise ValueError("source obligation IDs must be unique")
    edges = {}
    for row in plan["source_order"]:
        before, after = row["before_id"], row["after_id"]
        if before not in obligations or after not in obligations or before == after:
            raise ValueError("source edge needs two original obligations")
        key = before + "_BEFORE_" + after
        if key in edges or row["fact_id"] not in facts:
            raise ValueError("source edge identity or frozen fact invalid")
        quote = row.get("source_quote", facts[row["fact_id"]])
        if not quote.strip() or quote not in facts[row["fact_id"]]:
            raise ValueError("source edge must retain an unchanged frozen fact quote")
        edges[key] = {**deepcopy(row), "edge_id": key,
                      "source_quote": facts[row["fact_id"]]}
    return facts, obligations, edges


def _exact_table(variants, identities, description):
    identities = list(identities)
    result = {"type": "array", "minItems": len(identities), "maxItems": len(identities),
        "items": {"oneOf": variants} if variants else False, "description": description}
    if identities:
        result["allOf"] = [{"contains": {"required": ["edge_id"], "properties": {"edge_id": {"const": key}}},
                           "minContains": 1, "maxContains": 1} for key in identities]
    return result


def build_source_order_semantics_schema(plan, brief):
    _, _, edges = _source_inputs(plan, brief)
    variants = [base._obj({"edge_id": {"const": key},
        "before_id": {"const": edge["before_id"]}, "after_id": {"const": edge["after_id"]},
        "fact_id": {"const": edge["fact_id"]}, "source_quote": {"const": edge["source_quote"]},
        "mode": {"enum": list(MODES)}, "explanation": base._text()}) for key, edge in edges.items()]
    return base._obj({"plan_sha256": {"const": _digest(plan)}, "brief_sha256": {"const": _digest(brief)},
        "edges": _exact_table(variants, edges, "逐冻结源边独立判断量词，unknown不能进入实际见证验收。")})


def source_order_semantics_payload(plan, brief):
    """The source classifier receives no creative beats, actual body or review."""
    _, obligations, edges = _source_inputs(plan, brief)
    return {"brief": deepcopy(brief), "source_edges": [
        {**deepcopy(edge), "before_obligation": deepcopy(obligations[edge["before_id"]]),
         "after_obligation": deepcopy(obligations[edge["after_id"]])} for edge in edges.values()],
        "provenance": {"source_only": True, "plan_sha256": _digest(plan), "brief_sha256": _digest(brief),
            "actual_script_or_review_in_payload": False, "candidate_only": True}}


def validate_source_order_semantics(value, plan, brief):
    base._validate_schema(build_source_order_semantics_schema(plan, brief), value, "source_order_semantics")
    return {"complete": True, "plan_sha256": _digest(plan), "brief_sha256": _digest(brief),
        "source_semantics_sha256": _digest(value), "source_only_contract": True,
        "native_source_changed": False, "candidate_only": True}


def decide_source_order_semantics(value, plan, brief):
    validation = validate_source_order_semantics(value, plan, brief)
    unknown = [deepcopy(row) for row in value["edges"] if row["mode"] == "unknown"]
    return {"status": "halt_source_uncertain" if unknown else "source_order_semantics_ready",
        "validation": validation, "uncertainties": unknown, "candidate_only": True,
        "human_quality_approved": False, "production_applied": False}


def _actual_inputs(source, audit, script, plan, brief):
    if decide_source_order_semantics(source, plan, brief)["status"] != "source_order_semantics_ready":
        raise ValueError("known source-only edge semantics required before actual witness")
    _, obligations, edges = _source_inputs(plan, brief)
    entries = base.evidence_catalog(script)
    if audit["script_sha256"] != _digest(script) or audit["plan_sha256"] != _digest(plan):
        raise ValueError("native audit and actual witness must bind the unchanged script and plan")
    events = {row["source_ref"]: row for row in audit["literal_events"]}
    if len(events) != len(audit["literal_events"]) or set(events) != set(entries):
        raise ValueError("native literal classifier must cover every original step exactly once")
    for ref, event in events.items():
        if event["kind"] != entries[ref]["kind"] or event["speaker"] != entries[ref]["speaker"]:
            raise ValueError("native event kind/speaker differs from its original step")
        if not isinstance(event.get("speech_functions"), list) or not event["speech_functions"]:
            raise ValueError("native speech-function array required; do not synthesize it")
    proofs = {row["obligation_id"]: row for row in audit["obligation_evidence"]}
    if len(proofs) != len(audit["obligation_evidence"]) or set(proofs) != set(obligations):
        raise ValueError("native obligation evidence must remain complete")
    quotes = {}
    for key, proof in proofs.items():
        if proof["status"] not in ("pass", "fail", "unknown"):
            raise ValueError("native proof status must remain pass/fail/unknown")
        refs = proof["occurrence_refs"]
        if len(refs) != len(set(refs)) or any(ref not in entries for ref in refs):
            raise ValueError("native occurrence reference is duplicated or not an original step")
        spans = {row["ref_id"]: row["quote"] for row in proof.get("occurrence_spans", [])}
        if len(spans) != len(proof.get("occurrence_spans", [])) or not set(spans).issubset(refs):
            raise ValueError("native spans must bind original occurrence references")
        quotes[key] = {}
        for ref in refs:
            quote = spans.get(ref, entries[ref]["quote"])
            if not quote or entries[ref]["quote"].count(quote) != 1:
                raise ValueError("native occurrence span must identify one unchanged original position")
            quotes[key][ref] = quote
    return obligations, edges, entries, events, proofs, quotes


def _occurrences(quotes):
    return {"type": "array", "uniqueItems": True, "maxItems": len(quotes),
        "items": {"oneOf": [base._obj({"ref_id": {"const": ref}, "quote": {"const": quote}})
                              for ref, quote in quotes.items()]} if quotes else False,
        "description": "仅原生发生引用及原生span；无span时使用完整原步骤，不裁掉早回应。"}


def _episode_schema(before, after):
    links = {"type": "array", "maxItems": len(after), "items": base._obj({
        "before_ref_id": {"enum": list(before) or [""]},
        "after_ref_id": {"enum": list(after)} if after else False,
        "relation": {"enum": ["responds_to", "independent", "unknown"]}, "explanation": base._text()})}
    episode = base._obj({"before_occurrences": _occurrences(before),
        "after_occurrences": _occurrences(after), "response_links": links})
    # Each link is publicly constrained to this episode, not an arbitrary later pair.
    episode["allOf"] = []
    for key, refs, field in (("before_ref_id", before, "before_occurrences"),
                             ("after_ref_id", after, "after_occurrences")):
        for ref in refs:
            episode["allOf"].append({"if": {"properties": {"response_links": {"contains": {
                "properties": {key: {"const": ref}}, "required": [key]}}}},
                "then": {"properties": {field: {"contains": {
                    "properties": {"ref_id": {"const": ref}}, "required": ["ref_id"]}}}}})
    for ref in after:
        episode["allOf"].append({"if": {"properties": {"after_occurrences": {"contains": {
            "properties": {"ref_id": {"const": ref}}, "required": ["ref_id"]}}}},
            "then": {"properties": {"response_links": {"contains": {
                "properties": {"after_ref_id": {"const": ref}}, "required": ["after_ref_id"]},
                "minContains": 1, "maxContains": 1}}}})
    if not episode["allOf"]:
        episode.pop("allOf")
    return episode


def build_occurrence_episode_witness_schema(source, audit, script, plan, brief):
    _, edges, _, _, proofs, quotes = _actual_inputs(source, audit, script, plan, brief)
    variants = []
    for key, edge in edges.items():
        before, after = quotes[edge["before_id"]], quotes[edge["after_id"]]
        episodes = {"type": "array", "maxItems": max(1, len(before) + len(after)),
                    "items": _episode_schema(before, after), "allOf": []}
        for field, refs in (("before_occurrences", before), ("after_occurrences", after)):
            for ref in refs:
                episodes["allOf"].append({"contains": {"properties": {field: {"contains": {
                    "properties": {"ref_id": {"const": ref}}, "required": ["ref_id"]}}},
                    "required": [field]}, "minContains": 1, "maxContains": 1})
        if not episodes["allOf"]:
            episodes.pop("allOf")
        row = base._obj({"edge_id": {"const": key}, "status": {"enum": ["pass", "fail", "unknown"]},
            "explanation": base._text(), "episodes": episodes, "required_revision": {"type": "string"}})
        row["allOf"] = [{"if": {"properties": {"status": {"const": "fail"}}},
            "then": {"properties": {"required_revision": {"pattern": r"\S"}}}}]
        variants.append(row)
    return base._obj({"plan_sha256": {"const": _digest(plan)}, "brief_sha256": {"const": _digest(brief)},
        "script_sha256": {"const": _digest(script)}, "native_audit_sha256": {"const": _digest(audit)},
        "source_semantics_sha256": {"const": _digest(source)},
        "edges": _exact_table(variants, edges, "每项原生发生一次覆盖；不能删除早回应或本地补行事功能。")})


def occurrence_episode_witness_payload(source, audit, script, plan, brief):
    _actual_inputs(source, audit, script, plan, brief)
    return {"brief": deepcopy(brief), "source_semantics": deepcopy(source),
        "source_obligations": deepcopy(plan["source_obligations"]),
        "full_current_script": deepcopy(script), "evidence_catalog": base.evidence_catalog(script),
        "native_literal_events": deepcopy(audit["literal_events"]),
        "native_obligation_evidence": deepcopy(audit["obligation_evidence"]),
        "provenance": {"script_sha256": _digest(script), "plan_sha256": _digest(plan),
            "brief_sha256": _digest(brief), "native_audit_sha256": _digest(audit),
            "source_semantics_sha256": _digest(source), "native_classification_changed": False,
            "test_expectations_in_payload": False, "candidate_only": True}}


def validate_occurrence_episode_witness(value, source, audit, script, plan, brief):
    base._validate_schema(build_occurrence_episode_witness_schema(source, audit, script, plan, brief),
                          value, "occurrence_episode_witness")
    return {"complete": True, "witness_sha256": _digest(value), "script_sha256": _digest(script),
        "native_audit_sha256": _digest(audit), "source_semantics_sha256": _digest(source),
        "native_classification_changed": False, "all_native_occurrences_covered": True,
        "candidate_only": True}


def _mismatches(obligation, event):
    fields = []
    if obligation["required_kind"] != "either" and obligation["required_kind"] != event["kind"]:
        fields.append("kind")
    if obligation["actor_id"] and obligation["actor_id"] != event["actual_actor"]:
        fields.append("actor")
    if event["kind"] == "dialogue" and obligation["actor_id"] and obligation["actor_id"] != event["speaker"]:
        fields.append("speaker")
    if obligation["allowed_speech_functions"][0] not in event["speech_functions"]:
        fields.append("speech_function")
    return fields


def decide_occurrence_episode_witness(value, source, audit, script, plan, brief):
    validation = validate_occurrence_episode_witness(value, source, audit, script, plan, brief)
    obligations, edges, entries, events, proofs, quotes = _actual_inputs(source, audit, script, plan, brief)
    modes = {row["edge_id"]: row["mode"] for row in source["edges"]}
    positions = {ref: index for index, ref in enumerate(entries)}
    requirements, uncertainties, report = [], [], []

    def add(target, edge_id, code, problem, refs, native_status, revision=""):
        target.append({"code": code + "_" + edge_id, "edge_id": edge_id, "problem": problem,
            "native_status": native_status, "required_revision": revision,
            "evidence_refs": [{"ref_id": ref, **deepcopy(entries[ref])} for ref in dict.fromkeys(refs)]})

    def window(key, ref):
        original, quote = entries[ref]["quote"], quotes[key][ref]
        start = original.index(quote)
        return (positions[ref], start), (positions[ref], start + len(quote))

    for row in value["edges"]:
        edge_id = row["edge_id"]; edge = edges[edge_id]; mode = modes[edge_id]
        left_key, right_key = edge["before_id"], edge["after_id"]
        left, right = list(quotes[left_key]), list(quotes[right_key])
        refs = left + right; conflicts = []
        for key in (left_key, right_key):
            proof = proofs[key]
            if proof["status"] == "fail":
                add(requirements, edge_id, "NATIVE_SOURCE_FAILURE", proof["explanation"],
                    proof["occurrence_refs"], proof["status"], "由生成模型完整返修正文，冻结来源不变。")
            elif proof["status"] == "unknown" or not proof["occurrence_refs"]:
                add(uncertainties, edge_id, "NATIVE_SOURCE_UNKNOWN", "原生发生证据未知或缺失，不能由程序补齐。",
                    proof["occurrence_refs"], proof["status"])
            for ref in proof["occurrence_refs"]:
                mismatch = _mismatches(obligations[key], events[ref])
                if mismatch:
                    conflicts.append({"obligation_id": key, "ref_id": ref, "mismatch_fields": mismatch})
        if conflicts:
            add(uncertainties, edge_id, "NATIVE_CLASSIFIER_CONFLICT",
                "原生义务发生与原生行事功能/施事分类不一致；需要同源原生分类澄清，不能本地补request或删除早回应。",
                [item["ref_id"] for item in conflicts], row["status"])
        if row["status"] == "fail":
            add(requirements, edge_id, "MODEL_ORDER_FAILURE", row["explanation"], refs,
                row["status"], row["required_revision"])
        elif row["status"] == "unknown":
            add(uncertainties, edge_id, "MODEL_ORDER_UNKNOWN", row["explanation"], refs, row["status"])
        links = [link for episode in row["episodes"] for link in episode["response_links"]]
        if mode in ("first_transition", "paired_response") and not conflicts and left and right:
            if mode == "first_transition":
                first_end = min(window(left_key, ref) for ref in left)[1]
                early = [ref for ref in right if window(right_key, ref)[0] < first_end]
                if early:
                    add(requirements, edge_id, "EARLY_RESPONSE", "已有原生回应发生在首次已证实转入之前；不能选后来一对放过。",
                        left + early, row["status"], "完整返修实际刺激与回应的顺序，不能改原分类或删证据。")
            for link in links:
                a, b = link["before_ref_id"], link["after_ref_id"]
                if link["relation"] == "unknown":
                    add(uncertainties, edge_id, "RESPONSE_LINK_UNKNOWN", link["explanation"], [a, b], row["status"])
                elif link["relation"] != "responds_to" or window(left_key, a)[1] > window(right_key, b)[0]:
                    add(requirements, edge_id, "RESPONSE_LINK_FAILURE",
                        "原生回应未关联一个此前已发生的源刺激，不能靠任意存在一对兑现因果。", [a, b],
                        row["status"], "完整返修实际因果接话；保留冻结来源与全部原生证据。")
        elif mode == "all_occurrences":
            known_left = [ref for ref in left if not _mismatches(obligations[left_key], events[ref])]
            known_right = [ref for ref in right if not _mismatches(obligations[right_key], events[ref])]
            if known_left and known_right and max(window(left_key, ref)[1] for ref in known_left) > min(
                    window(right_key, ref)[0] for ref in known_right):
                add(requirements, edge_id, "ALL_OCCURRENCES_ORDER_FAILURE",
                    "来源原生语义明确要求全体先后，实际已证实窗口有重叠或逆序。", known_left + known_right,
                    row["status"], "由生成模型完整返修正文，兑现原生全体先后要求。")
        report.append({"edge_id": edge_id, "source_mode": mode, "before_refs": left, "after_refs": right,
            "native_classifier_conflicts": conflicts, "native_witness_status": row["status"]})
    return {"status": "needs_whole_revision" if requirements else "halt_review_uncertain" if uncertainties else "order_witness_ready",
        "validation": validation, "revision_requirements": requirements, "uncertainties": uncertainties,
        "edge_evidence": report, "source_semantics_sha256": _digest(source), "native_audit_changed": False,
        "native_witness_changed": False, "candidate_only": True, "production_applied": False,
        "creative_quality_passed": False, "human_quality_approved": False}
