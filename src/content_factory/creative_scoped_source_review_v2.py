"""All-claim provenance and scoped legal verification after native speech scope.

Reuses citation/schema atoms and the existing relation policy, never fabricates
a source6 report or reclassifies its native input. No provider or filesystem use.
"""
from __future__ import annotations

from copy import deepcopy
from jsonschema import Draft202012Validator

from . import creative_legal_speech_scope_v2 as scope
from . import creative_goal_legal_usage_source_audit_v6 as legal
from . import creative_goal_evidence_view_v1 as views

VERSION = "creative_scoped_source_review/v2"
digest = legal.digest
SOURCE_KEYS = {"source_packet", "verified_legal_context", "user_goal_contract", "origin_catalog"}

REVIEW_RULE = (
    "本阶段审核全部原生C的来源支持，以及前一完整原生scope报告实际识别的法律命题的依据与条件。"
    "完整native_goal_evidence_view、scope_projection和当前全部来源/用户/法律原文同源；scope短码只是一份原生语义判断，不是语义真值。"
    "claim_checks完整覆盖所有C，核对真实origin支持、用户要求、平台仅元数据、虚构归属和inference的真实前提，不以自引C原句等于来源支持。"
    "legal_observations逐一覆盖scope_projection.legal_assertions所有位置；每条usage的quote、assertion_scope、interpretation"
    "必须逐字保持该scope断言的quote、assertion_scope、proposition，reason解释核验依据，不重新定义被审命题；"
    "核原权威、适用条件、general_rule与case_application，不能因同主题就支持，也不能因为是虚构或角色请求而豁免其真实法律前提。"
    "普通事实可能在未来法律评价中有用，不等于本句已断言法律效果；不要要求作者为所有事实先说明法律效力。"
    "外部法律不覆盖、个案条件未展示或法律关系未知，如实保留not_covered/application_not_demonstrated/unknown阻断，不换成文本U。"
    "若原句真实两可、scope漏掉或误解实际法律命题，提交scope_challenges并指明当前ref、精确quote和具体候选命题；"
    "不得静默改变scope短码、以可能关联法律为由重判，或直接代写新稿。挑战应先范围复核，不能据此本地通过或自动重写创作。"
    "actual_case_conditions仅用当前actual_event_refs精确原句，ref证明位置不证明事件已完成；未来承诺不是条件已成立。"
    "actually_corrected仍需已知错误、独立权威和另一当前G真实纠正，不能结论自证、引用自身或用争议未决代替。"
    "用指定完整原生合同提交；本地结构与关系路由不证明法律理解、语义或创作质量。"
)


class ScopedSourceContractError(ValueError):
    pass


def _authority(source_context):
    if type(source_context) is not dict or set(source_context) != SOURCE_KEYS:
        raise ScopedSourceContractError("complete source_packet/legal/user/origin context required")
    if any(type(source_context[key]) is not dict for key in SOURCE_KEYS):
        raise ScopedSourceContractError("complete source context objects required")
    return {key: deepcopy(source_context[key]) for key in ("verified_legal_context", "origin_catalog")}


def build_review_context(native_goal, native_scope, source_context):
    authority = _authority(source_context)
    authorities = legal.build_authority_catalog(authority)
    for claim in native_goal["claims"]:
        if claim["kind"] == "verified_legal":
            refs = claim.get("origin_ids", [])
            if (type(refs) is not list or len(refs) != 1 or refs[0] not in authorities
                    or claim["text"] != authorities[refs[0]]["fact"]["paraphrase"]):
                raise ScopedSourceContractError("verified_legal must preserve one exact original fact and its origin")
    projection = scope.authority_projection(native_scope, native_goal)
    view = views.build_lossless_goal_evidence_view(native_goal)
    if views.reconstruct_goal(view) != native_goal:
        raise ScopedSourceContractError("scoped source context differs from complete native goal")
    payload = {**deepcopy(source_context), "native_goal_evidence_view": view,
        "native_goal_sha256": digest(native_goal), "scope_projection": projection,
        "actual_event_refs": list(legal.build_actual_context_catalog(native_goal))}
    return {"payload": payload, "manifest": {"schema": VERSION + "/context_manifest",
        "native_goal_sha256": digest(native_goal), "scope_native_sha256": digest(native_scope),
        "source_context_sha256": digest(source_context), "authority_context_sha256": digest(authority),
        "audit_context_sha256": digest(payload), "all_native_claims_provenance_required": True,
        "scope_source_ref_count": len(projection["act_by_ref"]),
        "legal_source_ref_count": len(projection["legal_assertions"]),
        "scope_native_modified": False, "semantic_truth_deterministically_proven": False,
        "model_calls": 0, "media_calls": 0}}


def build_review_schema(native_goal, native_scope, source_context, *, context_sha256):
    built = build_review_context(native_goal, native_scope, source_context)
    if context_sha256 != built["manifest"]["audit_context_sha256"]:
        raise ScopedSourceContractError("current scoped source context identity required")
    original_atoms = legal.build_source_schema(native_goal, _authority(source_context), context_sha256=context_sha256)
    catalog = legal.build_evidence_catalog(native_goal)
    refs = list(built["payload"]["scope_projection"]["legal_assertions"])
    obj, text = scope._object, scope._text
    observation = obj({"source_ref": {"enum": refs} if refs else False,
        "usages": {"type": "array", "items": {"$ref": "#/$defs/legal_assertion"}, "minItems": 1,
                   "maxItems": legal.MAX_USAGES_PER_SOURCE, "uniqueItems": True}})
    challenge = obj({"source_ref": {"enum": list(catalog)}, "quote": text(),
        "kind": {"enum": ["missed_legal_proposition", "misread_scoped_assertion", "textual_ambiguity"]},
        "candidate_proposition": text(400), "reason": text(400)})
    schema = obj({"schema": {"const": VERSION}, "native_goal_sha256": {"const": digest(native_goal)},
        "scope_native_sha256": {"const": digest(native_scope)}, "audit_context_sha256": {"const": context_sha256},
        "authority_context_sha256": {"const": built["manifest"]["authority_context_sha256"]},
        "claim_checks": deepcopy(original_atoms["properties"]["claim_checks"]),
        "legal_observations": {"type": "array", "items": observation, "minItems": len(refs), "maxItems": len(refs)},
        "scope_challenges": {"type": "array", "items": challenge, "maxItems": len(catalog)}})
    definitions = deepcopy(original_atoms["$defs"])
    # This field copies A's bounded native proposition; it is not a new B interpretation.
    definitions["legal_assertion"]["properties"]["interpretation"]["maxLength"] = 400
    definitions["legal_assertion"]["properties"]["interpretation"]["description"] = (
        "Exact scope_projection.legal_assertions[source_ref].proposition; do not reinterpret it here.")
    definitions["legal_assertion"]["properties"]["assertion_scope"]["description"] = (
        "Exact original scoped assertion_scope; disagreement requires scope_challenges, never silent downgrade.")
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": definitions})
    Draft202012Validator.check_schema(schema)
    return schema


def validate_review(document, native_goal, native_scope, source_context, *, context_sha256):
    built = build_review_context(native_goal, native_scope, source_context)
    schema = build_review_schema(native_goal, native_scope, source_context, context_sha256=context_sha256)
    Draft202012Validator(schema).validate(document)
    catalog = legal.build_evidence_catalog(native_goal)
    actual = legal.build_actual_context_catalog(native_goal)
    authority = _authority(source_context)
    origins = legal.exact._origin_directory(authority)
    authorities = legal.build_authority_catalog(authority)
    expected = built["payload"]["scope_projection"]["legal_assertions"]
    refs = [row["source_ref"] for row in document["legal_observations"]]
    if len(set(refs)) != len(refs) or set(refs) != set(expected):
        raise ScopedSourceContractError("legal observations must cover all and only native scoped L refs")
    findings, unknowns, challenges, citations, gates = [], [], [], {}, {}
    for index, claim in enumerate(native_goal["claims"]):
        identifier = claim["id"]
        origin_refs = claim.get("origin_ids", [])
        if (type(origin_refs) is not list or any(type(key) is not str for key in origin_refs)
                or len(set(origin_refs)) != len(origin_refs) or any(key not in origins for key in origin_refs)):
            raise ScopedSourceContractError("native claim origin directory mismatch: " + identifier)
        row = document["claim_checks"][identifier]
        item = {"kind": "provenance", "claim_id": identifier, **deepcopy(row),
            "native_claim": deepcopy(claim), "origin_citations": [{"origin_ref": ref, **deepcopy(origins[ref])} for ref in origin_refs]}
        if row["status"] == "fail": findings.append(item)
        elif row["status"] == "unknown": unknowns.append(item)
    for offset, observation in enumerate(document["legal_observations"]):
        ref = observation["source_ref"]
        citations[ref], gates[ref] = [], []
        for index, row in enumerate(observation["usages"]):
            path = f"/legal_observations/{offset}/usages/{index}"
            if (row["quote"] != expected[ref]["quote"] or row["quote"] not in catalog[ref]["quote"]
                    or row["assertion_scope"] != expected[ref]["assertion_scope"]
                    or row["interpretation"] != expected[ref]["proposition"]):
                raise ScopedSourceContractError("preserve the exact native scoped quote/proposition/assertion scope; challenge rather than silently change: " + ref)
            actual_evidence = legal.prior._compile_role_evidence(row["actual_case_conditions"], actual,
                "event_ref", path + "/actual_case_conditions")
            gate = legal.relation_policy._gate(row, ref,
                [{"source_ref": item["event_ref"], "quote": item["quote"]} for item in actual_evidence], path)
            compiled = {"source_ref": ref, "native_usage": deepcopy(row), "gate": gate,
                "authority_citations": [deepcopy(authorities[key]) for key in row["authority_refs"]],
                "actual_case_conditions": actual_evidence}
            citations[ref].append(compiled)
            gates[ref].append(gate)
            if gate == "fail": findings.append(compiled)
            elif gate == "unknown": unknowns.append(compiled)
    seen = set()
    for challenge in document["scope_challenges"]:
        ref, quote = challenge["source_ref"], challenge["quote"]
        identity = (ref, quote, challenge["kind"])
        if quote not in catalog[ref]["quote"] or identity in seen:
            raise ScopedSourceContractError("scope challenge requires its own current nonduplicate quote")
        seen.add(identity)
        challenges.append(deepcopy(challenge))
    route = ("scope_recheck_required" if challenges else "halt_external_source_or_legal_unknown" if unknowns
        else "complete_new_native_content_revision" if findings else "native_source_review_accepted")
    return {"schema": VERSION + "/decision", "valid": True, "accepted": not findings and not unknowns and not challenges,
        "findings": findings, "uncertainties": unknowns, "scope_challenges": challenges, "route": route,
        "native_goal_sha256": digest(native_goal), "scope_native_sha256": digest(native_scope),
        "native_review_sha256": digest(document), "audit_context_sha256": context_sha256,
        "authority_context_sha256": digest(authority), "all_native_claim_checks_covered": True,
        "scoped_legal_refs_covered": True, "legal_usage_citations": citations, "usage_gates": gates,
        "scope_native_modified": False, "native_review_modified": False,
        "semantic_truth_deterministically_proven": False, "creative_quality_passed": False, "human_quality_approved": False}
