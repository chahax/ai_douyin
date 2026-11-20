"""Versioned lossless native-state projection; no inferred physical facts.

V5 required every scene-state entry to be a typed fact, despite its prompt's
natural state descriptions. V6 also preserves native strings as *unknown*,
nonphysical descriptions. Existing native files/verdicts remain byte-identical.
No paid formatting recovery or writer rewrite is involved in this projection.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import novel_agent_roles_v5 as base
from . import novel_plaintext_contracts_v3 as native_contracts

VERSION = "novel_agent_roles/v6"
WRITER_PROMPT = base.WRITER_PROMPT
REVIEW_PROMPT = base.REVIEW_PROMPT + """
状态表示补充：before/after优先用output_spec中嵌套的事实对象。只能确切抽取的状态才explicit。
若自然语言状态不能可靠拆为事实，可直接保留该原生字符串；程序将它标为unknown的文字描述，
不猜角色、位置、姿态或持有者，不把它拿去做确定性物理冲突判定。不要为填事实字段编造状态。
这不会替代对完整原文和整稿的九维语义审查；重大与可能重大的问题仍须逐项报告、核实。
"""
REVIEW_OUTPUT_SPEC = deepcopy(base.REVIEW_OUTPUT_SPEC)
REVIEW_OUTPUT_SPEC["scene_ledger"]["events"][0]["before"] = [{
    "subject_id": "角色稳定ID", "predicate": "presence", "value": True,
    "certainty": "explicit", "evidence_refs": ["S1段首确切在场"], "qualifiers": {"scope": "physical"}}]
REVIEW_OUTPUT_SPEC["scene_ledger"]["events"][0]["after"] = ["不能可靠拆解时，保留原生自然语言状态"]
parse_json = base.parse_json
build_writer_payload = base.build_writer_payload
historical_candidates_from_payload = base.historical_candidates_from_payload
evaluate_review_bundle = base.evaluate_review_bundle


def build_review_payload(source, screenplay, *, previous_bundle=None, candidate_issues=None, brief=None):
    payload = base.build_review_payload(source, screenplay, previous_bundle=previous_bundle,
                                        candidate_issues=candidate_issues, brief=brief)
    payload["output_spec"] = deepcopy(REVIEW_OUTPUT_SPEC)
    return payload


def parse_review_bundle(text, *, source_binding, draft_binding, native_response_ref,
                        artifact_prefix, required_issues=None):
    raw = parse_json(text)
    normalized = deepcopy(raw)
    ledger = normalized.get("scene_ledger")
    projected_paths = []
    if isinstance(ledger, dict) and isinstance(ledger.get("events"), list):
        for event_index, event in enumerate(ledger["events"]):
            if not isinstance(event, dict):
                continue
            for phase in ("before", "after"):
                values = event.get(phase)
                if not isinstance(values, list):
                    continue
                for index, value in enumerate(values):
                    if not isinstance(value, str):
                        continue
                    if not value.strip():
                        raise ValueError("Empty native scene-state description")
                    location = f"$.scene_ledger.events[{event_index}].{phase}[{index}]"
                    values[index] = {
                        "subject_id": "event:" + str(event.get("event_id", event_index)),
                        "predicate": "native_state_description", "value": value, "certainty": "unknown",
                        "evidence_refs": [native_response_ref + ":" + location],
                        "qualifiers": {"scope": "native_description", "representation": "lossless_text",
                                       "not_physical_fact": True},
                    }
                    projected_paths.append(location)
    bundle = base.parse_review_bundle(json.dumps(normalized, ensure_ascii=False, allow_nan=False),
        source_binding=source_binding, draft_binding=draft_binding, native_response_ref=native_response_ref,
        artifact_prefix=artifact_prefix, required_issues=required_issues)
    for artifact in bundle.values():
        artifact["header"]["producer_version"] = VERSION
    bundle["scene_ledger"]["state_projection"] = {
        "version": VERSION, "native_response_ref": native_response_ref,
        "text_description_paths": projected_paths,
        "physical_facts_inferred": False,
        "meaning": "Native strings retained verbatim as unknown nonphysical descriptions; typed facts retain original certainty.",
    }
    return bundle


def verify_review_evidence(request, response, *, source, screenplay, protocol, review,
                           request_binding=None, response_binding=None):
    """Reproduce v6 projections from the same immutable native files and input."""
    if base._verify_bound_file(request_binding) != request or base._verify_bound_file(response_binding) != response:
        raise ValueError("Supplied records differ from their immutable files")
    if response.get("request_binding") != request_binding:
        raise ValueError("Native response targets another request")
    errors, tokens, native_text = native_contracts.response_evidence(
        response, {**protocol["director"], "role": "director"})
    if errors or tokens is None or response.get("role") != "director":
        raise ValueError("Native review envelope not complete: " + json.dumps(errors))
    if response.get("stage") != request.get("stage") or request.get("role") != "director":
        raise ValueError("Native review stage/role mismatch")
    if response["response_metadata"].get("finish_reason") != "stop":
        raise ValueError("Native text review did not end with stop")
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Complete frozen review request missing")
    payload = parse_json(messages[-1]["content"])
    if payload.get("source") != source or payload.get("screenplay") != screenplay:
        raise ValueError("DeepSeek was not sent the complete same source and draft")
    source_binding = source["binding_id"]
    draft_binding = hashlib.sha256(screenplay.encode("utf-8")).hexdigest()
    artifact_id = review.get("header", {}).get("artifact_id", "")
    if not artifact_id.endswith("/review"):
        raise ValueError("Program review artifact ID invalid")
    derived = parse_review_bundle(native_text, source_binding=source_binding, draft_binding=draft_binding,
        native_response_ref=response_binding["sha256"], artifact_prefix=artifact_id.removesuffix("/review"),
        required_issues=payload.get("required_issues"))
    if derived["review"] != review:
        raise ValueError("Review verdict/content differs from native output")
    return {"status": "complete", "usage_known": True, "finish_reason": "stop",
            "identity_verified": True, "files_verified": True, "whole_text_verified": True,
            "review_payload_verified": True, "native_provider": "deepseek",
            "source_binding": source_binding, "draft_binding": draft_binding,
            "native_response_ref": response_binding["sha256"], "native_verdict": review["native_verdict"],
            "review_artifact_id": artifact_id}
