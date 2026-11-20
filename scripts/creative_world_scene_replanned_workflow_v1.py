"""Pure explicit replanning/writer adapter; original native values stay intact.

Scope, dispatch, loops, receipt authenticity and capacity remain the caller's
responsibility. This module cannot create a claim or call a provider.
"""
from copy import deepcopy
import json

from scripts import creative_world_scene_live_session_v1 as base
from scripts import creative_world_scene_live_session_v2 as prior_feedback
from scripts import creative_world_scene_source_state_audit_v3 as state_audit
from scripts import creative_world_scene_script_contract_v2 as contract
from scripts import creative_world_scene_direct_wire_schema_v1 as direct

VERSION = "creative_world_scene_replanned_workflow/v1"
FEEDBACK_VERSION = VERSION + "/native_replan_feedback"
PLANNING_RULE = (
    "本阶段提交完整新整片规划，负责人物目的、整片情绪与事件因果、刺激与策略变化、可见信息及跨拍必要状态。"
    "逐镜观察窗口、表情节拍、机位、实际时长和执行排时由后续导演/表演阶段负责，不把局部表演细则堆成整片承诺。"
    "保留给定用户功能、世界与合法来源边界；旧规划的creative_choice是未采用的模型实现，可完整重选，"
    "不能因此修改用户/法律来源，也不能把模型自创道具或数量升格为用户硬约束。"
    "失败原生规划、开场和报告是完整诊断证据，各自不等于验收通过；合法引文不证明报告解释正确。"
    "源局部前态按原文保留，不用后一版本倒填旧稿。提交完整原生新计划，再重建四审和开场，不修补旧原生文件。"
)
WRITER_RULE = (
    "本次实际输出约定：kind=action的speaker恒为\"\"，动作执行者写入text；kind=dialogue的speaker填写本拍在场角色ID。"
    "ensemble里每位在场者提交自己的expression；action_step_indexes/P索引指向本拍真实action步骤，"
    "可以挂接同拍别人施加的刺激或共同可见表演，不要求该action由此角色执行。"
    "静默听者的神情、倾听或保持可以挂接同一刺激action，无需为填索引另外摆弄道具。"
    "这不取消当前合同的非空action索引，也不允许助手添加虚假动作；纯零action对白不属于当前合同。"
    "正常语速下说话、动作和表情可以并行，parallel_with仅给出可并行关系，不代表动作已经完成。"
)


def _used_refs(value):
    if type(value) is dict:
        if type(value.get("ref")) is str: yield value["ref"]
        for child in value.values(): yield from _used_refs(child)
    elif type(value) is list:
        for child in value: yield from _used_refs(child)


def seed_feedback(goal, setup, native_audit, decision, *, prepared=None,
                  passed_audits=None, failed_kind="source_state", failed_body=None):
    """One complete failed native report plus functional, fallible diagnostics.

    This pure builder does not establish transport/usage completeness. The
    coordinator must establish a known settled receipt before invoking it.
    """
    structural_failure = failed_kind in ("goal_contract", "opening_setup")
    if (type(goal) is not dict or type(decision) is not dict or
            (native_audit is not None and type(native_audit) is not dict) or
            (native_audit is None and not structural_failure)):
        raise ValueError("complete native planning/report and explicit decision required")
    if decision.get("accepted") is True or decision.get("uncertainties"):
        raise ValueError("passed or unresolved source review cannot seed a known-failure rewrite")
    for document in (native_audit or {}, decision):
        for field in ("goal_sha256", "native_goal_sha256"):
            if field in document and document[field] != base.digest(goal):
                raise ValueError("failed review belongs to another native goal")
    if setup is not None and failed_kind != "opening_setup" and setup.get("goal_sha256") != base.digest(goal):
        raise ValueError("native setup belongs to another goal")
    if failed_body is not None and type(failed_body) is not dict:
        raise ValueError("complete native body required")
    catalog = {}
    if not structural_failure and setup is not None and "whole_plan" in goal:
        catalog = state_audit._catalog({"native_goal_document": goal, "native_opening_setup_document": setup}, goal)
    if prepared is not None and failed_kind in ("source_state", "historical_diagnostic"):
        if "views" in prepared:
            views = prepared["views"]
            if views["goal"] != goal or views["setup"] != setup or views["source_catalog"] != catalog:
                raise ValueError("failed audit source directory is not the exact native goal/setup")
        else:
            payload = json.loads(prepared["request"]["messages"][1]["content"])
            if (payload.get("native_goal_document") != goal or payload.get("native_opening_setup_document") != setup
                    or payload.get("source_catalog") != catalog):
                raise ValueError("historical actual request source directory or native documents changed")
    directory = {ref: deepcopy(catalog[ref]) for ref in dict.fromkeys(_used_refs(native_audit)) if ref in catalog}
    old_projection = None
    if failed_kind in base.workflow.AUDITS and decision.get("valid") is True:
        old_projection = prior_feedback.planning_feedback(goal, {failed_kind: native_audit}, {failed_kind: decision}, failed_kind)
        directory = deepcopy(old_projection["source_directory"])
    findings = []
    for field in ("contract_findings", "findings"):
        for row in decision.get(field, []):
            if row not in findings: findings.append(deepcopy(row))
    feedback = {"schema": FEEDBACK_VERSION, "failed_kind": failed_kind,
        "native_goal_sha256": base.digest(goal), "native_audit_present": native_audit is not None,
        "complete_original_decision_sha256": base.digest(decision),
        "source_directory": directory, "source_directory_role": "exact ref/path mapping into full native source documents below; not extra facts",
        "functional_diagnostics": {"valid": decision.get("valid"), "accepted": False,
            "status": decision.get("status"), "findings": findings, "uncertainties": [],
            "computed_state_findings": deepcopy(decision.get("computed_state_findings", []))},
        "passed_audit_identities": {}, "native_documents_modified": False,
        "diagnostic_is_admission": False,
        "critique_role": "fallible diagnosis, never new user/legal authority; submit a complete new native plan"}
    if native_audit is not None:
        feedback["complete_failed_native_report"] = deepcopy(native_audit)
        feedback["complete_native_report_sha256"] = base.digest(native_audit)
    if setup is not None: feedback["complete_native_opening_setup"] = deepcopy(setup)
    if failed_body is not None: feedback["complete_failed_native_body"] = deepcopy(failed_body)
    passed = passed_audits or {}
    if passed.get("schema") == base.workflow.BUNDLE_VERSION:
        passed = {kind: passed["native_" + kind + "_audit"] for kind in base.workflow.AUDITS}
    for kind, value in passed.items():
        report = value.get("native", value) if type(value) is dict else value
        if type(report) is not dict: raise ValueError("native prior audit lineage must be an object")
        feedback["passed_audit_identities"][kind] = {"native_report_sha256": base.digest(report), "lineage_is_not_current_admission": True}
    return {"previous_complete_document": deepcopy(goal), "revision_diagnostics": feedback}


class ReviewWorkflow(base.ReviewWorkflow):
    """Explicitly injected by the new bounded coordinator, never global patching."""
    seed_feedback = staticmethod(seed_feedback)

    def prepare_goal_request(self, inputs, profile):
        diagnostics = inputs.get("revision_diagnostics")
        if type(diagnostics) is not dict or diagnostics.get("schema") != FEEDBACK_VERSION:
            result = self.base.prepare_goal_request(inputs, profile)
        else:
            if not isinstance(inputs.get("previous_complete_document"), dict):
                raise ValueError("typed replan feedback requires the complete previous native goal")
            if diagnostics.get("native_goal_sha256") != base.digest(inputs["previous_complete_document"]):
                raise ValueError("typed replan feedback goal binding changed")
            clean = {key: deepcopy(value) for key, value in inputs.items()
                if key not in ("previous_complete_document", "revision_diagnostics")}
            result = self.base.prepare_goal_request(clean, profile)
            staged = self.base.legacy.base_requests._context("goal_plan", self.base.prior._planning_authority_inputs(inputs))
            payload = json.loads(result["request"]["messages"][1]["content"])
            for key, value in staged["payload"].items(): payload[key] = deepcopy(value)
            # Keep the existing stage-responsibility contract and verify the
            # same goal-plan budget *after* it and full feedback are combined.
            policy = staged["manifest"]["context_policy"]
            measured = self.base.contexts._measure(payload)
            if measured["characters"] > policy["max_payload_characters"] or measured["utf8_bytes"] > policy["max_payload_utf8_bytes"]:
                raise ValueError("complete replan context exceeds existing goal_plan budget; no native content truncated")
            if self.base.contexts._reference_occurrences(payload, inputs["reference_fulltext"]) != 1:
                raise ValueError("complete R01 must occur once in actual replan payload")
            result["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            result["request"]["input_provenance"]["context_sha256"] = base.digest(payload)
            result["manifest"].update(context_sha256=base.digest(payload), typed_feedback_preserved=True,
                previous_complete_document_sha256=base.digest(inputs["previous_complete_document"]),
                original_revision_diagnostics_sha256=base.digest(diagnostics),
                feedback_compiler_bypassed_for_explicit_native_frame=True,
                replan_stage_projection_manifest=deepcopy(staged["manifest"]))
        result["request"]["messages"][0]["content"] += "\n" + PLANNING_RULE
        result["manifest"]["replanned_workflow_version"] = VERSION
        return self.base._mark(result, inputs)

    def prepare_script_request(self, inputs, profile, goal, audit, *, source_state_audit=None, source_state_prepared=None, **kwargs):
        if source_state_audit is None or source_state_prepared is None:
            raise ValueError("same-source native state audit and complete prepared request required before writer")
        source_decision = self.validate_source_state_audit(source_state_audit, source_state_prepared)
        source_views = source_state_prepared["views"]
        clean = {key: value for key, value in inputs.items() if key not in ("previous_complete_document", "revision_diagnostics")}
        if (source_decision.get("valid") is not True or source_decision.get("accepted") is not True
                or source_decision.get("uncertainties") or source_views["goal"] != goal
                or source_views["setup"] != kwargs.get("opening_setup") or source_views["inputs"] != clean
                or source_state_prepared["coordinator_profile_projection"]["caller_profile"] != profile):
            raise ValueError("same-source accepted state extraction gate required before writer")
        result = super().prepare_script_request(inputs, profile, goal, audit, **kwargs)
        canonical = contract.refine_schema(result["request"]["structured_schema"])
        representation = direct.prepare_schema(goal, canonical_schema=canonical)
        result["request"]["structured_schema"] = representation["schema"]
        result["request"]["messages"][0]["content"] += "\n" + contract.RELATION_RULE + "\n" + WRITER_RULE
        result["manifest"].update(replanned_workflow_version=VERSION, direct_wire_representation=deepcopy(representation["manifest"]),
            canonical_local_schema_sha256=base.digest(canonical), actual_wire_schema_sha256=base.digest(representation["schema"]),
            wire_schema_is_full_local_contract=False, local_contract_uses_default_canonical=True,
            stage_capacity_owner="explicit coordinator shared run scope; no local counter reset")
        binding = {"source_state_audit_version": state_audit.VERSION, "native_source_state_audit_sha256": base.digest(source_state_audit),
            "source_state_context_sha256": source_state_prepared["context_sha256"], "source_state_decision_sha256": base.digest(source_decision),
            "source_state_native_goal_sha256": base.digest(goal), "source_state_native_setup_sha256": base.digest(source_views["setup"])}
        result["manifest"]["source_state_admission_binding"] = binding
        result["request"]["input_provenance"].update(binding)
        return self.base._mark(result, inputs)

    def validate_script_document(self, native, views, production_preferences=None):
        contract.validate(native, views["goal"])
        return self.base.validate_script_document(native, views, production_preferences)

    def prepare_full_review_part_request(self, inputs, profile, native, views, part):
        self.validate_script_document(native, views, inputs["production_preferences"])
        return super().prepare_full_review_part_request(inputs, profile, native, views, part)

    @staticmethod
    def prepare_source_state_audit_request(inputs, profile, goal, setup):
        dedicated = deepcopy(profile)
        dedicated.setdefault("stage_parameters", {}).setdefault("goal_audit", {})["max_completion_tokens"] = 32000
        result = state_audit.prepare(inputs, dedicated, goal, setup)
        result["coordinator_profile_projection"] = {"schema": VERSION + "/source_state_profile_projection",
            "caller_profile": deepcopy(profile), "caller_profile_sha256": base.digest(profile),
            "effective_profile_sha256": base.digest(dedicated), "source_state_only_output_cap_override": 32000,
            "other_stage_profile_modified": False}
        return result

    @staticmethod
    def validate_source_state_audit(native, prepared):
        views = prepared["views"]
        original_profile = prepared["coordinator_profile_projection"]["caller_profile"]
        expected = ReviewWorkflow.prepare_source_state_audit_request(views["inputs"], original_profile, views["goal"], views["setup"])
        if prepared != expected: raise ValueError("source-state substage profile or complete request binding changed")
        pure = {key: value for key, value in prepared.items() if key != "coordinator_profile_projection"}
        return state_audit.validate(native, pure)
