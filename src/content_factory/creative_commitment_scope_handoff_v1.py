"""Carry one complete native commitment report as fallible advisory input.

Original C/G text stays in the complete native goal. The accepted report is
copied once without a second per-claim projection or source directory.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_goal_commitment_audit_v2 as commitments
from . import creative_goal_context_workflow_v26 as workflow

VERSION = "creative_commitment_scope_handoff/v1"
ADVISORY_VERSION = VERSION + "/native_advisory"
SNAPSHOT_VERSION = VERSION + "/bound_snapshot"
FIELD = "commitment_scope_advisory"
digest = commitments.digest
AUTHORITY = "fallible_model_interpretation_not_source_override"
RULE = (
    "commitment_scope_advisory保留当前同源审查者的使用范围解释，是可质疑的模型判断，不是新事实或新创作指令。"
    "原native_goal_document中的C、主体、对象、明确时点/先后和真实原句优先；分类不能免除原文义务或新增口播。"
    "background_consistency核查是否相容，不因关联某拍就要求把全部背景说出口；local_event按原C要求真实演出，不一律限定对白。"
    "cross_beat_relation核对跨拍关系与原文时间限制，不把终态仍成立替换成指定拍内动作已发生；mixed结合原C及原生解释区分，不自行把全C塞同一拍。"
    "全文语义审查可以质疑此前scope解释，须以当前C/G和正文E检查；使用现有fact_checks/paired_checks及原生返修归属，未知仍停止。"
    "这份交接不证明审查解释正确，也不覆盖用户要求、独立法律条件或原规划。"
)


def _verify_original_claims(native_goal, native_commitment):
    catalog = commitments.build_evidence_catalog(native_goal)
    for native in native_commitment["commitment_checks"].values():
        source = catalog[native["claim_ref"]]
        quote = native_goal
        for part in source["document_path"].split("."):
            quote = quote[int(part)] if isinstance(quote, list) else quote[part]
        if type(quote) is not str or quote != source["quote"]:
            raise ValueError("original claim quote must be read back from the exact complete current native goal")


def read_native_advisory(native_goal, native_commitment, *, context_sha256):
    """Read-only accepted-v2 wrapper; grants no authoring or review call."""
    decision = commitments.validate_commitment_audit(native_commitment, native_goal, context_sha256=context_sha256)
    if decision.get("valid") is not True or decision.get("accepted") is not True:
        raise ValueError("failed or unknown commitment interpretation cannot be carried as an accepted advisory")
    _verify_original_claims(native_goal, native_commitment)
    return {"schema": ADVISORY_VERSION, "authority": AUTHORITY,
            "native_commitment_audit": deepcopy(native_commitment)}


def build_snapshot(inputs, profile, native_goal, native_goal_audit):
    """Revalidate the complete actual four-audit bundle, not a passed boolean."""
    decision = workflow.validate_goal_audit(native_goal_audit, native_goal, inputs=inputs)
    if decision.get("valid") is not True or decision.get("accepted") is not True:
        raise ValueError("all four real native audits including paired drama must pass before scope handoff")
    # The complete v26 four-audit validator already checked this report. Keep
    # its reasons/counterproof too; do not replace it with a larger row view.
    native = native_goal_audit["native_commitment_audit"]
    _verify_original_claims(native_goal, native)
    return {"schema": SNAPSHOT_VERSION, "authority": AUTHORITY,
        "native_commitment_audit": deepcopy(native),
        "native_goal_audit_bundle_sha256": digest(native_goal_audit),
        "accepted_paired_snapshot_sha256": digest(decision["accepted_goal_comparison_snapshot"]),
        "profile_sha256": digest(profile)}


def validate_snapshot(snapshot, inputs, profile, native_goal, native_goal_audit):
    expected = build_snapshot(inputs, profile, native_goal, native_goal_audit)
    if digest(snapshot) != digest(expected):
        raise ValueError("scope handoff differs from exact native goal/commitment/paired/four-audit/profile bindings")
    return {"valid": True, "snapshot_sha256": digest(snapshot), "advisory_not_new_authority": True}


def _occurrences(value):
    if isinstance(value, dict):
        return int(value.get("schema") == SNAPSHOT_VERSION) + sum(_occurrences(child) for child in value.values())
    return sum(_occurrences(child) for child in value) if isinstance(value, list) else 0


def _attach_verified(payload, snapshot, native_goal):
    if digest(payload.get("native_goal_document")) != digest(native_goal):
        raise ValueError("actual request must contain the exact complete native goal")
    if digest(payload.get("accepted_goal_comparison_snapshot")) != snapshot["accepted_paired_snapshot_sha256"]:
        raise ValueError("scope advisory must accompany the exact accepted paired snapshot from the same bundle")
    if FIELD in payload or _occurrences(payload):
        raise ValueError("scope advisory must occur once, not in a second field or nested duplicate")
    return {**deepcopy(payload), FIELD: deepcopy(snapshot)}


def attach(payload, snapshot, inputs, profile, native_goal, native_goal_audit):
    # Public untrusted-snapshot attachment verifies the real bundle once.
    expected = build_snapshot(inputs, profile, native_goal, native_goal_audit)
    if digest(snapshot) != digest(expected):
        raise ValueError("scope handoff differs from exact native goal/commitment/paired/four-audit/profile bindings")
    return _attach_verified(payload, expected, native_goal)


def build_and_attach(payload, inputs, profile, native_goal, native_goal_audit):
    # New request compilers need not build then revalidate the same snapshot.
    expected = build_snapshot(inputs, profile, native_goal, native_goal_audit)
    return _attach_verified(payload, expected, native_goal)
