"""Natural writer and native same-source review contracts with shared quality.

The v6 lossless state projection is deliberately retained; old modules and
native decisions are never edited or silently migrated.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import novel_agent_roles_v5 as base
from . import novel_agent_roles_v6 as projection
from . import novel_plaintext_contracts_v3 as native_contracts
from .narrative_quality_v1 import quality_policy, source_kind, validate_quality_policy

VERSION = "novel_agent_roles/v8"
WRITER_PROMPT = base.WRITER_PROMPT + """
本次为全流程质量v8。完整消费quality_policy，交付完整原生自然文本，不交指定工具或双份JSON。
先交代世界框架和创作规划，再写完整可演出剧本。观众必须从实际动作对白理解当下目标、冲突及关系变化；不能只在背景中解释。
所有在场者都有动作、神情、具体视线对象及转移、头身朝向和听者反应；重要神情由近景/特写/越肩等可见方式承载。
自然语速下压缩重复信息与无效停顿，先保留完整来回互动，再按brief冻结总时长组织情节；不硬套15秒或一条台词一段。
动作与对白、听者反应自然重叠，不靠堆动作加速。合理沉默和避视有具体表达功能，不强求互看或不断说话。
source_kind=novel时忠于已取得正文主线、人物关系和动机；source_kind=original时source是创作种子/约束，允许依brief完整原创人物、事件和结局，不把原创扩写误当小说事实越界。两者都遵守冻结brief与质量要求。
"""
REVIEW_PROMPT = projection.REVIEW_PROMPT + """
本次全流程质量v8：逐项消费quality_policy。仅字段齐全不代表信息或表演合格。
审核实际正片是否迅速可理解、有持续的信息/判断/关系变化；所有在场者是否回应、看向具体对象、头身朝向是否合理，摄影是否看得清关键反应；时长是否来自完整自然互动，不能单句拉长或无效静候。
合理沉默、避视、画外音及单人场景可以成立，判断其上下文表达价值，不用字数、固定秒数或固定动作数替代判断。
source_kind=original时source是原创种子，brief允许的原创人物事件不是无据改编；仍审核主线因果与冻结创作约束。source_kind=novel时遵守已取得原文。
将实质问题记入原生九维review及adjudication；不得因为排版要求整稿返修。
"""
REVIEW_OUTPUT_SPEC = deepcopy(projection.REVIEW_OUTPUT_SPEC)
parse_json = base.parse_json
historical_candidates_from_payload = base.historical_candidates_from_payload
evaluate_review_bundle = base.evaluate_review_bundle


def build_writer_payload(source, *, previous_draft=None, feedback=None, brief=None):
    result = base.build_writer_payload(source, previous_draft=previous_draft,
                                      feedback=feedback, brief=brief)
    result.update(quality_policy=quality_policy(), source_kind=source_kind(source, brief))
    return result


def build_review_payload(source, screenplay, *, previous_bundle=None, candidate_issues=None, brief=None):
    result = projection.build_review_payload(source, screenplay, previous_bundle=previous_bundle,
                                             candidate_issues=candidate_issues, brief=brief)
    result.update(quality_policy=quality_policy(), source_kind=source_kind(source, brief))
    return result


def parse_review_bundle(text, *, source_binding, draft_binding, native_response_ref,
                        artifact_prefix, required_issues=None):
    result = projection.parse_review_bundle(text, source_binding=source_binding,
        draft_binding=draft_binding, native_response_ref=native_response_ref,
        artifact_prefix=artifact_prefix, required_issues=required_issues)
    for artifact in result.values():
        artifact["header"]["producer_version"] = VERSION
        artifact["quality_policy"] = quality_policy()
    return result


def verify_review_evidence(request, response, *, source, screenplay, protocol, review,
                           request_binding=None, response_binding=None):
    if base._verify_bound_file(request_binding) != request or base._verify_bound_file(response_binding) != response:
        raise ValueError("Supplied records differ from immutable files")
    if response.get("request_binding") != request_binding:
        raise ValueError("Native response targets another request")
    errors, tokens, text = native_contracts.response_evidence(response, {**protocol["director"], "role": "director"})
    if errors or tokens is None or response.get("role") != "director":
        raise ValueError("Native review envelope incomplete: " + json.dumps(errors))
    if response.get("stage") != request.get("stage") or request.get("role") != "director":
        raise ValueError("Native review stage/role mismatch")
    if (request.get("source_binding_id") != source.get("binding_id")
            or any(response.get(key) != request.get(key) for key in ("schema", "stage", "stage_key", "ordinal"))):
        raise ValueError("Native review request identity differs from frozen source or response")
    if response["response_metadata"].get("finish_reason") != "stop":
        raise ValueError("Native review did not end with stop")
    messages = request.get("messages")
    if (not isinstance(messages, list) or len(messages) != 2
            or messages[0] != {"role": "system", "content": REVIEW_PROMPT}
            or messages[-1].get("role") != "user"):
        raise ValueError("Complete v8 review prompt missing or changed")
    materials = parse_json(messages[-1]["content"])
    if materials.get("source") != source or materials.get("screenplay") != screenplay:
        raise ValueError("DeepSeek was not sent complete same source and draft")
    validate_quality_policy(materials.get("quality_policy"))
    if materials.get("source_kind") != source_kind(source, materials.get("brief")):
        raise ValueError("Review source_kind differs from frozen brief")
    expected_materials = build_review_payload(source, screenplay,
        previous_bundle=materials.get("previous_bundle"), candidate_issues=materials.get("scene_candidates"),
        brief=materials.get("brief"))
    if expected_materials != materials:
        raise ValueError("Review payload cannot be reconstructed under the frozen v8 policy")
    source_binding = source["binding_id"]
    draft_binding = hashlib.sha256(screenplay.encode("utf-8")).hexdigest()
    artifact_id = review.get("header", {}).get("artifact_id", "")
    if not artifact_id.endswith("/review"):
        raise ValueError("Review artifact identity invalid")
    derived = parse_review_bundle(text, source_binding=source_binding, draft_binding=draft_binding,
        native_response_ref=response_binding["sha256"], artifact_prefix=artifact_id.removesuffix("/review"),
        required_issues=materials.get("required_issues"))
    if derived["review"] != review:
        raise ValueError("Review differs from native output")
    return {"status": "complete", "usage_known": True, "finish_reason": "stop",
            "identity_verified": True, "files_verified": True, "whole_text_verified": True,
            "review_payload_verified": True, "native_provider": "deepseek",
            "quality_policy_sha256": quality_policy()["sha256"],
            "source_binding": source_binding, "draft_binding": draft_binding,
            "native_response_ref": response_binding["sha256"], "native_verdict": review["native_verdict"],
            "review_artifact_id": artifact_id}
