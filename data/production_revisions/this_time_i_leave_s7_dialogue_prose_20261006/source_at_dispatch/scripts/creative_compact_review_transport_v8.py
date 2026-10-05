"""Offline candidate for lossless complete-review transport; no provider client.

Fixed columns reduce repeated JSON keys. They do not reduce review scope,
create evidence, alter conclusions, or grant semantic/media approval.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json

from scripts.creative_script_review_sources_v7 import validate_review_v7
from src.content_factory.creative_review_v3 import CHECKS
from src.content_factory.creative_review_v6 import validate_review_v6
from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = "creative_compact_review_transport/v8"
TOP = {"schema", "context_sha256", "story_preserved", "issues", "suggestions", "calibration_focus", "coverage"}
ISSUE_FIELDS = {"id", "owner", "location", "severity", "rule", "evidence", "contradiction", "impact", "proposal", "evidence_refs"}
STATUSES = {"pass", "fail", "not_applicable"}


class CompactReviewTransportError(CreativeContractError):
    def __init__(self, code: str, message: str):
        super().__init__(code + ": " + message)
        self.code = code


def _fail(code, message):
    raise CompactReviewTransportError(code, message)


def _json(value, *, sort_keys=False):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=sort_keys,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        _fail("COMPACT_JSON_INVALID", "必须为有限数值的完整JSON")


def context_digest(context):
    if not isinstance(context, dict):
        _fail("COMPACT_CONTEXT_INVALID", "context必须为对象")
    return hashlib.sha256(_json(context, sort_keys=True).encode("utf-8")).hexdigest()


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        _fail("COMPACT_TYPE_INVALID", location + "必须为非空字符串")
    return value


def _list(value, location):
    if not isinstance(value, list):
        _fail("COMPACT_TYPE_INVALID", location + "必须为普通数组")
    return value


def _refs(pairs, location):
    result = []
    for index, pair in enumerate(_list(pairs, location)):
        if not isinstance(pair, list) or len(pair) != 2:
            _fail("COMPACT_REFERENCE_SHAPE_INVALID", f"{location}.{index}必须为[path,quote]")
        result.append({"path": _text(pair[0], location + ".path"),
                       "quote": _text(pair[1], location + ".quote")})
    return result


def _rows(context):
    if not isinstance(context, dict):
        _fail("COMPACT_CONTEXT_INVALID", "context必须为对象")
    scope = "shots" if "shots" in context else "script"
    key = "shots" if scope == "shots" else "beats"
    container = context.get(scope)
    if not isinstance(container, dict) or not isinstance(container.get(key), list) or not container[key]:
        _fail("COMPACT_CONTEXT_INVALID", "缺少非空完整script.beats或shots.shots")
    ids = []
    for row in container[key]:
        if not isinstance(row, dict):
            _fail("COMPACT_CONTEXT_INVALID", "正文行必须为对象")
        ids.append(_text(row.get("id"), "context.id"))
    if len(set(ids)) != len(ids):
        _fail("COMPACT_CONTEXT_INVALID", "正文ID必须唯一")
    return ids


def _decode(raw, context):
    expected_ids = _rows(context)
    if not isinstance(raw, dict) or set(raw) != TOP:
        _fail("COMPACT_TOP_INVALID", "顶层字段必须与v8合同完全一致")
    if raw["schema"] != VERSION:
        _fail("COMPACT_VERSION_INVALID", "未知传输版本")
    if raw["context_sha256"] != context_digest(context):
        _fail("COMPACT_CONTEXT_STALE", "输出不属于当前完整context")
    if type(raw["story_preserved"]) is not bool:
        _fail("COMPACT_TYPE_INVALID", "story_preserved必须为bool")
    issues = []
    for index, issue in enumerate(_list(raw["issues"], "issues")):
        if not isinstance(issue, dict) or set(issue) != ISSUE_FIELDS:
            _fail("COMPACT_ISSUE_SHAPE_INVALID", f"issues.{index}字段不完整或有额外字段")
        row = deepcopy(issue)
        for field in ISSUE_FIELDS - {"evidence_refs"}:
            _text(row[field], f"issues.{index}.{field}")
        if row["owner"] not in {"writer", "director"} or row["severity"] not in {"blocking", "major"}:
            _fail("COMPACT_ENUM_INVALID", "issue owner/severity不合法")
        row["evidence_refs"] = _refs(row["evidence_refs"], f"issues.{index}.evidence_refs")
        issues.append(row)
    suggestions = deepcopy(_list(raw["suggestions"], "suggestions"))
    for index, row in enumerate(suggestions):
        if not isinstance(row, dict) or set(row) != {"location", "proposal", "reason"}:
            _fail("COMPACT_SUGGESTION_SHAPE_INVALID", "suggestion字段不完整或有额外字段")
        for field in row:
            _text(row[field], f"suggestions.{index}.{field}")
    focus = deepcopy(_list(raw["calibration_focus"], "calibration_focus"))
    for index, item in enumerate(focus):
        _text(item, f"calibration_focus.{index}")
    compact_rows = _list(raw["coverage"], "coverage")
    if len(compact_rows) != len(expected_ids):
        _fail("COMPACT_COVERAGE_INCOMPLETE", "coverage必须完整覆盖当前全部正文行")
    coverage, actual_ids = [], []
    for row_index, cells in enumerate(compact_rows):
        if not isinstance(cells, list) or len(cells) != 1 + len(CHECKS):
            _fail("COMPACT_ROW_SHAPE_INVALID", "coverage每行必须为ID加固定六项检查")
        beat_id = _text(cells[0], "coverage.id")
        actual_ids.append(beat_id)
        checks = {}
        for offset, name in enumerate(CHECKS, 1):
            check = cells[offset]
            if not isinstance(check, list) or len(check) != 4:
                _fail("COMPACT_CHECK_SHAPE_INVALID", "每项必须为[status,reason,refs,issue_ids]")
            status = _text(check[0], f"coverage.{row_index}.{name}.status")
            if status not in STATUSES:
                _fail("COMPACT_ENUM_INVALID", "未知coverage状态")
            ids = deepcopy(_list(check[3], f"coverage.{row_index}.{name}.issue_ids"))
            for issue_id in ids:
                _text(issue_id, "issue_ids")
            checks[name] = {"status": status, "reason": _text(check[1], "reason"),
                            "evidence_refs": _refs(check[2], "evidence_refs"), "issue_ids": ids}
        coverage.append({"id": beat_id, "checks": checks})
    if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != set(expected_ids):
        _fail("COMPACT_COVERAGE_INCOMPLETE", "coverage行ID不得缺失、重复或属于旧稿")
    return {"story_preserved": raw["story_preserved"], "issues": issues,
            "suggestions": suggestions, "calibration_focus": focus, "coverage": coverage}


def _encode(review, context):
    raw = {"schema": VERSION, "context_sha256": context_digest(context), **deepcopy(review)}
    for issue in raw["issues"]:
        issue["evidence_refs"] = [[ref["path"], ref["quote"]] for ref in issue["evidence_refs"]]
    raw["coverage"] = [[row["id"], *[
        [row["checks"][name]["status"], row["checks"][name]["reason"],
         [[ref["path"], ref["quote"]] for ref in row["checks"][name]["evidence_refs"]],
         deepcopy(row["checks"][name]["issue_ids"])] for name in CHECKS]] for row in review["coverage"]]
    if _decode(raw, context) != review:
        _fail("COMPACT_LOSSY_ENCODING", "传输往返改变了原审核对象")
    return raw


def encode_review(review, context):
    """Production candidate: preserve a v7-valid review exactly; never repair it."""
    validate_review_v7(review, context)
    return _encode(review, context)


def expand_review(raw, context):
    """Production candidate: decode strictly, then enforce the real v7 gate."""
    result = _decode(raw, context)
    validate_review_v7(result, context)
    return result


def accept_response(text, context, *, finish_reason):
    """Reject incomplete responses before parsing; no fallback or partial adoption."""
    if finish_reason == "length":
        _fail("RESPONSE_TRUNCATED", "服务输出已截断，禁止采用partial")
    if finish_reason not in {"stop", "tool_calls"}:
        _fail("COMPACT_RESPONSE_INCOMPLETE", "未确认完整服务响应")
    if not isinstance(text, str):
        _fail("COMPACT_TYPE_INVALID", "响应必须为完整JSON文本")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail("COMPACT_DUPLICATE_KEY", "JSON存在重复字段")
            value[key] = item
        return value
    def invalid_constant(value):
        _fail("COMPACT_JSON_INVALID", "JSON包含非有限数值")
    try:
        raw = json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except json.JSONDecodeError:
        _fail("COMPACT_RESPONSE_JSON_INVALID", "响应不是完整且唯一的JSON对象")
    return expand_review(raw, context)


def replay_legacy_v6(review, context):
    """Explicit offline-only replay; does not weaken expand_review's v7 gate."""
    validate_review_v6(review, context)
    raw = _encode(review, context)
    effective = _decode(raw, context)
    validate_review_v6(effective, context)
    try:
        validate_review_v7(effective, context)
    except CreativeContractError as exc:
        candidate = {"result": "rejected", "error": str(exc)}
    else:
        candidate = {"result": "source_validated", "semantic_approval": False}
    return {"schema": "offline_compact_review_replay/v8", "offline_only": True,
            "network_calls": 0, "raw_transport": raw, "effective_review": effective,
            "exact_roundtrip": effective == review, "original_v6_validation": "passed",
            "candidate_v7_validation": candidate, "automatic_approval": False,
            "real_model_test": False, "provider_token_savings": None}


def build_review_messages(context):
    """Complete script context once; add no catalog or joint-scope prompt."""
    if not isinstance(context, dict) or "shots" in context:
        _fail("COMPACT_SCOPE_UNSUPPORTED", "该候选提示词仅用于完整剧本，不能用于联合分镜审查")
    _rows(context)
    from scripts.review_linear_script_probe_v6 import PROMPT
    expected = {"仅返回JSON": 0, "coverage逐一覆盖": 0, "evidence_refs每项": 0}
    replacements = {
        "仅返回JSON": "仅返回JSON，顶层恰为schema、context_sha256、story_preserved(bool)、issues(array)、suggestions(array)、calibration_focus(array)、coverage(array)。有必修issues则story_preserved=false，否则true。",
        "coverage逐一覆盖": "coverage逐一覆盖全部正文行且各一次。每行固定七列：[id,requirements,timing,continuity,dialogue_timing,first_frame,assets]；每项固定四列：[status,reason,evidence_refs,issue_ids]。status仅pass/fail/not_applicable，reason保留具体理由。fail关联已列issues；其他issue_ids=[]；每issue至少有一个fail关联。禁止省行、省项或补默认结论。",
        "evidence_refs每项": "evidence_refs每项严格为[path,quote]二元数组（issues内也相同）；path输入点分到真实字符串/数字叶子，quote必要逐字片段，不引用数组/对象。每条issue引用当前正文。每个pass/fail至少引用本拍真实正文；有前拍的连续性同时引用前拍真实正文。资产对照不能只引全局ID。缺证据不能标pass或冒称不适用。",
    }
    lines = []
    for line in PROMPT.splitlines():
        for prefix in expected:
            if line.startswith(prefix):
                expected[prefix] += 1
                line = replacements[prefix]
                break
        lines.append(line)
    if any(count != 1 for count in expected.values()):
        _fail("COMPACT_PROMPT_BINDING_CHANGED", "原语义提示词协议段变化，必须显式核对")
    lines.append("schema逐字填写" + _json(VERSION) + "；context_sha256逐字填写" + _json(context_digest(context)) + "。")
    lines.append("输入context必须完整阅读全文；固定列仅为传输表示，不能缩小审核范围。没有证据目录或ID代替原文。")
    _rows(context)
    return [{"role": "system", "content": "\n".join(lines)},
            {"role": "user", "content": _json(context)}]


def build_wire_preview(context, *, model, parameters):
    _text(model, "model")
    if not isinstance(parameters, dict) or type(parameters.get("max_completion_tokens")) is not int or parameters["max_completion_tokens"] <= 0:
        _fail("COMPACT_PARAMETERS_INVALID", "需保留明确正整数输出上限")
    return {"role": "director", "model": model, "messages": build_review_messages(context),
            "structured_schema": None, "parameters": deepcopy(parameters)}


def budget_preview(wire, *, reported_tokens, max_total_tokens=500000, unknown_reservations=0, margin=1024):
    for value in (reported_tokens, max_total_tokens, unknown_reservations, margin):
        if type(value) is not int or value < 0:
            _fail("COMPACT_BUDGET_INVALID", "预算必须为非负整数，不能重置或省略已用额度")
    if not isinstance(wire, dict) or not isinstance(wire.get("parameters"), dict):
        _fail("COMPACT_PARAMETERS_INVALID", "wire必须包含完整parameters对象")
    cap = wire["parameters"].get("max_completion_tokens")
    if type(cap) is not int or cap <= 0:
        _fail("COMPACT_PARAMETERS_INVALID", "需保留明确正整数输出上限")
    # Same conservative count as the frozen driver; these are not measured tokens.
    wire_chars = len(json.dumps(wire, ensure_ascii=False, allow_nan=False))
    reservation = wire_chars + cap + margin
    remaining = max_total_tokens - reported_tokens - unknown_reservations
    return {"schema": "offline_compact_review_budget_preview/v8", "wire_chars": wire_chars,
            "max_output_tokens": cap, "margin": margin, "conservative_reservation": reservation,
            "reported_tokens": reported_tokens, "unknown_reservations": unknown_reservations,
            "remaining_reported_tokens": remaining, "fits_original_budget": reservation <= remaining,
            "method": "wire characters + unchanged output cap + margin",
            "provider_input_token_estimate": None, "provider_output_token_savings": None,
            "network_calls": 0, "dispatched": False, "budget_reset": False}
