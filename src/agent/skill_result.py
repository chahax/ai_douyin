# -*- coding: utf-8 -*-
"""
src/agent/skill_result.py — Skill 标准返回 envelope

设计原则（Harness Engineering Layer 4: 反馈与监控）：
  - 所有 Skill 必须返回 SkillResult（或被 Registry 自动 coerce）
  - 10 种标准 error code（机读）
  - LLM 看到的是统一 shape，便于分支判断
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


# 标准 error code（详见 docs/SKILL_SPEC.md §4.3.2）
SKILL_ERROR_CODES = (
    "ok",                     # 成功
    "validation_error",       # 输入参数错误（不可重试）
    "not_found",              # 资源不存在（不可重试）
    "auth_required",          # 需要登录/认证（不可重试）
    "paywall",                # 付费墙/内容受限（不可重试）
    "cancelled",              # 用户取消（不可重试）
    "timeout",                # 执行超时（可重试）
    "rate_limited",           # 频率限制（可重试）
    "skill_error",            # 内部异常（默认不可重试）
    "max_retries_exceeded",   # 重试耗尽（不可重试）
)


# 每个 code 的默认 retryable 行为
DEFAULT_RETRYABLE = {
    "ok": False,
    "validation_error": False,
    "not_found": False,
    "auth_required": False,
    "paywall": False,
    "cancelled": False,
    "timeout": True,
    "rate_limited": True,
    "skill_error": False,
    "max_retries_exceeded": False,
}


@dataclass
class SkillResult:
    """Skill 调用的标准返回 envelope。

    字段：
      success     bool      是否成功
      code        str       机器可读状态码（SKILL_ERROR_CODES 之一）
      message     str       人类可读消息（中文，1 句话）
      data        dict      成功时的载荷（按每个 Skill 的 schema 填）
      error       dict      失败时的错误详情
                            { type, message, retryable, details }
      skill       str       Skill 名字（registry.call 自动填）
      duration_ms int       耗时（registry.call 自动填）
      attempts    int       实际尝试次数（registry.call 自动填，含 retry）
    """

    success: bool
    code: str = "ok"
    message: str = ""
    data: dict = field(default_factory=dict)
    error: dict = field(default_factory=dict)
    skill: str = ""
    duration_ms: int = 0
    attempts: int = 1

    def to_dict(self) -> dict:
        """转 dict。LLM 调 Skill 收到的是这个 shape。"""
        return asdict(self)

    @classmethod
    def ok(
        cls,
        data: dict | None = None,
        message: str = "",
        **kw,
    ) -> "SkillResult":
        """成功路径工厂。"""
        return cls(success=True, code="ok", message=message, data=data or {}, **kw)

    @classmethod
    def err(
        cls,
        code: str,
        message: str,
        error: dict | None = None,
        **kw,
    ) -> "SkillResult":
        """失败路径工厂。code 必须是 SKILL_ERROR_CODES 之一。"""
        if code not in SKILL_ERROR_CODES:
            code = "skill_error"
        return cls(
            success=False,
            code=code,
            message=message,
            error=error or {},
            **kw,
        )

    @property
    def is_retryable(self) -> bool:
        """该 result 是否可重试（基于 code）。"""
        return DEFAULT_RETRYABLE.get(self.code, False)


def coerce_to_skill_result(name: str, raw: object) -> SkillResult:
    """把 Skill 函数的原始返回值归一化到 SkillResult。

    兼容 3 种老格式：
      1. SkillResult  → 直接返回（但补 skill name）
      2. dict  → 根据 success 字段判断
      3. 其它   → 包成 SkillResult.ok(data={"value": raw})
    """
    if isinstance(raw, SkillResult):
        if not raw.skill:
            raw.skill = name
        return raw

    if isinstance(raw, dict):
        success = bool(raw.get("success", False))
        if success:
            # 成功：data 字段 = 除标准字段外的所有字段
            standard = {"success", "code", "message", "data", "error"}
            has_data_field = "data" in raw and isinstance(raw["data"], dict)
            data = raw["data"] if has_data_field else {
                k: v for k, v in raw.items() if k not in standard
            }
            return SkillResult(
                success=True,
                code=raw.get("code", "ok"),
                message=raw.get("message", ""),
                data=data,
                skill=name,
            )
        else:
            # 失败
            return SkillResult(
                success=False,
                code=raw.get("code", "skill_error") or "skill_error",
                message=raw.get("error") or raw.get("message", "Skill 失败"),
                error={
                    "type": "LegacyError",
                    "message": raw.get("error") or raw.get("message", ""),
                    "retryable": False,
                    "details": raw,
                },
                skill=name,
            )

    # 其它（int / str / list / None）：当作 data 包装
    return SkillResult(success=True, code="ok", data={"value": raw}, skill=name)
