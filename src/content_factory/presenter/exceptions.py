# -*- coding: utf-8 -*-
"""
ComfyUI 背景生成异常类（I-2 ComfyUI 容错）。

设计原则：
  - 不影响现有 _create_comfy_background 的 bool 返回接口（向后兼容）
  - 新的 _create_comfy_background_with_retry 入口抛结构化异常
  - 所有异常继承 ComfyBackgroundError 基类，方便上层统一捕获
  - error_class 字段对应 comfy_task_failures 表的 error_class 列

调用方只需：
    try:
        backgrounds = resolver.resolve_grouped_backgrounds(...)
    except ComfyBackgroundError as exc:
        # exc.error_class: "OOM" / "WORKFLOW" / "TIMEOUT" / "UNAVAILABLE"
        # exc.attempts: 重试次数
        # exc.last_stderr_tail: 最近 stderr 输出（OOM 诊断用）
        ...
"""

from typing import List, Optional


class ComfyBackgroundError(Exception):
    """
    所有 ComfyUI 背景生成失败的基类。

    Attributes:
        error_class: 错误分类（用于持久化统计和 UI 展示）
        attempts: 已重试次数
        last_stderr_tail: 最近一次失败的 stderr 摘要（OOM 诊断用）
        failed_presets: 失败的 preset 列表（如果有）
    """

    error_class: str = "UNKNOWN"

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        last_stderr_tail: str = "",
        failed_presets: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_stderr_tail = last_stderr_tail
        self.failed_presets = failed_presets or []


class ComfyOOMError(ComfyBackgroundError):
    """GPU 显存不足（CUDA OOM / HIP OOM / MPS OOM 等）。可重试。"""

    error_class: str = "OOM"


class ComfyWorkflowError(ComfyBackgroundError):
    """工作流 JSON 错误 / checkpoint 缺失 / 节点参数错误。不可重试。"""

    error_class: str = "WORKFLOW"


class ComfyTimeoutError(ComfyBackgroundError):
    """ffmpeg / ComfyUI HTTP 轮询超时。可重试。"""

    error_class: str = "TIMEOUT"


class ComfyBackgroundUnavailableError(ComfyBackgroundError):
    """
    所有重试 + 降级阶梯均失败后抛出。
    pipeline 拿到这个异常做最后决策：
      - strict_background=True → 中止 pipeline
      - strict_background=False → backgrounds=[None]*len(scenes)，继续走 FFmpeg 单色兜底
    """

    error_class: str = "UNAVAILABLE"
