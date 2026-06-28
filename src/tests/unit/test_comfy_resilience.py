# -*- coding: utf-8 -*-
"""
Tests for I-2 ComfyUI 容错（src/content_factory/presenter/exceptions.py +
background_resolver.py 的 retry / OOM / stderr 部分 + comfy_failure_model）。

覆盖：
  - 4 个异常类的 error_class 字段
  - OOM 检测（关键字 + 自定义）
  - GPU 显存采样（无 nvidia-smi 也不崩）
  - 重试阶梯（max_retries 环境变量）
  - COMFYUI_FORCE_OOM 触发 3 次重试 → 抛 ComfyBackgroundUnavailableError
  - ComfyWorkflowError 不重试
  - strict_background 决策（True → 中止 / False → None 背景继续）
  - record_failure 写库失败不掩盖原始错误
"""

import os
from unittest.mock import patch

import pytest

from src.content_factory.presenter.exceptions import (
    ComfyBackgroundError,
    ComfyBackgroundUnavailableError,
    ComfyOOMError,
    ComfyTimeoutError,
    ComfyWorkflowError,
)
from src.content_factory.presenter.background_resolver import (
    DEFAULT_OOM_PATTERNS,
    RETRY_PRESETS,
    detect_oom_in_stderr,
    get_max_retries,
    get_oom_patterns,
)
from src.content_factory.presenter.models import PresenterRequest, PresenterResult


# ---------------------------------------------------------------------------
# 异常类
# ---------------------------------------------------------------------------


class TestExceptionClasses:
    """4 个异常类及其 error_class 字段。"""

    def test_base_class_error_class(self):
        assert ComfyBackgroundError.error_class == "UNKNOWN"

    def test_oom_error_class(self):
        assert ComfyOOMError.error_class == "OOM"
        assert issubclass(ComfyOOMError, ComfyBackgroundError)

    def test_workflow_error_class(self):
        assert ComfyWorkflowError.error_class == "WORKFLOW"
        assert issubclass(ComfyWorkflowError, ComfyBackgroundError)

    def test_timeout_error_class(self):
        assert ComfyTimeoutError.error_class == "TIMEOUT"
        assert issubclass(ComfyTimeoutError, ComfyBackgroundError)

    def test_unavailable_error_class(self):
        assert ComfyBackgroundUnavailableError.error_class == "UNAVAILABLE"
        assert issubclass(ComfyBackgroundUnavailableError, ComfyBackgroundError)

    def test_exception_carries_attempts_and_stderr(self):
        exc = ComfyBackgroundUnavailableError(
            "all failed", attempts=3, last_stderr_tail="CUDA OOM..."
        )
        assert exc.attempts == 3
        assert "CUDA OOM" in exc.last_stderr_tail
        assert str(exc) == "all failed"


# ---------------------------------------------------------------------------
# OOM 检测
# ---------------------------------------------------------------------------


class TestOOMDetection:
    def test_detects_default_cuda_oom(self):
        assert detect_oom_in_stderr("RuntimeError: CUDA out of memory. Tried to allocate 2GB")

    def test_detects_pytorch_oof_message(self):
        assert detect_oom_in_stderr("torch.cuda.OutOfMemoryError: CUDA out of memory.")

    def test_ignores_normal_errors(self):
        assert not detect_oom_in_stderr("RuntimeError: CUDA error: device-side assert triggered")
        assert not detect_oom_in_stderr("")

    def test_custom_pattern_from_env(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_OOM_PATTERNS", "MY_CUSTOM_OOM,ANOTHER_PATTERN")
        patterns = get_oom_patterns()
        assert "MY_CUSTOM_OOM" in patterns
        assert "ANOTHER_PATTERN" in patterns
        # And these new patterns are detected
        assert detect_oom_in_stderr("got MY_CUSTOM_OOM here")
        assert detect_oom_in_stderr("and ANOTHER_PATTERN too")

    def test_apple_mps_oom_detected(self):
        assert detect_oom_in_stderr("MPS backend out of memory")

    def test_amd_roc_oom_detected(self):
        assert detect_oom_in_stderr("hipMalloc returned nullptr")


# ---------------------------------------------------------------------------
# 重试配置
# ---------------------------------------------------------------------------


class TestRetryConfig:
    def test_default_max_retries_is_3(self, monkeypatch):
        monkeypatch.delenv("COMFYUI_MAX_RETRIES", raising=False)
        assert get_max_retries() == 3

    def test_env_override_to_2(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_MAX_RETRIES", "2")
        assert get_max_retries() == 2

    def test_env_override_to_5(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_MAX_RETRIES", "5")
        assert get_max_retries() == 5

    def test_invalid_env_falls_back_to_3(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_MAX_RETRIES", "not-a-number")
        assert get_max_retries() == 3

    def test_zero_or_negative_clamped_to_1(self, monkeypatch):
        monkeypatch.setenv("COMFYUI_MAX_RETRIES", "0")
        assert get_max_retries() == 1
        monkeypatch.setenv("COMFYUI_MAX_RETRIES", "-5")
        assert get_max_retries() == 1

    def test_three_presets_configured(self):
        """RETRY_PRESETS 阶梯：默认 → 降 steps → 降分辨率"""
        assert len(RETRY_PRESETS) == 3
        # Step count non-increasing
        assert RETRY_PRESETS[0].steps >= RETRY_PRESETS[1].steps >= RETRY_PRESETS[2].steps
        # Width non-increasing
        assert RETRY_PRESETS[0].width >= RETRY_PRESETS[1].width >= RETRY_PRESETS[2].width


# ---------------------------------------------------------------------------
# GPU 显存采样（无 nvidia-smi 也不崩）
# ---------------------------------------------------------------------------


class TestGPUMemorySampling:
    def test_handles_missing_nvidia_smi_gracefully(self):
        from src.content_factory.presenter.background_resolver import sample_gpu_memory
        with patch("subprocess.run", side_effect=FileNotFoundError):
            used, total = sample_gpu_memory()
        assert used is None
        assert total is None

    def test_parses_nvidia_smi_csv_output(self):
        from src.content_factory.presenter.background_resolver import sample_gpu_memory
        fake = type("R", (), {
            "returncode": 0,
            "stdout": "1024, 16303\n",
        })()
        with patch("subprocess.run", return_value=fake):
            used, total = sample_gpu_memory()
        assert used == 1024
        assert total == 16303


# ---------------------------------------------------------------------------
# retry 行为（用 monkeypatch 替换 _create_comfy_background）
# ---------------------------------------------------------------------------


class TestRetryEscalation:
    """3 次重试 → 抛 ComfyBackgroundUnavailableError。"""

    def test_force_oom_triggers_three_retries(self, monkeypatch, tmp_path):
        """COMFYUI_FORCE_OOM=1 时 _create_comfy_background_with_retry 抛 ComfyBackgroundUnavailableError,
        attempts=3, error_class=UNAVAILABLE。"""
        monkeypatch.setenv("COMFYUI_FORCE_OOM", "1")
        from src.content_factory.presenter.background_resolver import BackgroundResolver
        resolver = BackgroundResolver()

        with pytest.raises(ComfyBackgroundUnavailableError) as exc_info:
            resolver._create_comfy_background_with_retry(
                prompt="test",
                output_path=tmp_path / "out.png",
                seed=42,
            )
        # COMFYUI_FORCE_OOM 在 retry 循环内部触发，共 3 次尝试
        assert exc_info.value.attempts == 3
        assert exc_info.value.error_class == "UNAVAILABLE"

    def test_workflow_error_not_retried(self, monkeypatch, tmp_path):
        """ComfyWorkflowError（工作流 JSON 错）应立即抛，不重试。"""
        from src.content_factory.presenter.background_resolver import BackgroundResolver
        resolver = BackgroundResolver()

        call_count = [0]
        def fake_inner(*args, **kwargs):
            call_count[0] += 1
            raise ComfyWorkflowError("invalid JSON in node '5'", attempts=1)
        resolver._create_comfy_background = fake_inner

        with pytest.raises(ComfyWorkflowError):
            resolver._create_comfy_background_with_retry(
                prompt="test",
                output_path=tmp_path / "out.png",
                seed=42,
            )
        # 1 次（不重试）
        assert call_count[0] == 1

    def test_success_on_first_try_no_retry(self, monkeypatch, tmp_path):
        monkeypatch.delenv("COMFYUI_FORCE_OOM", raising=False)
        from src.content_factory.presenter.background_resolver import BackgroundResolver
        resolver = BackgroundResolver()

        call_count = [0]
        def fake_inner(*args, **kwargs):
            call_count[0] += 1
            return True
        resolver._create_comfy_background = fake_inner

        output = tmp_path / "out.png"
        result_path = resolver._create_comfy_background_with_retry(
            prompt="test", output_path=output, seed=42,
        )
        assert call_count[0] == 1
        assert result_path == output


# ---------------------------------------------------------------------------
# strict_background 决策
# ---------------------------------------------------------------------------


class TestStrictBackgroundDecision:
    def test_default_strict_background_is_false(self):
        """默认 False：ComfyUI 不可用走 None 背景继续。"""
        req = PresenterRequest(input_mode="article_direct", text="test")
        assert req.strict_background is False

    def test_strict_background_field_can_be_set(self):
        req = PresenterRequest(input_mode="article_direct", text="test", strict_background=True)
        assert req.strict_background is True

    def test_error_class_field_default_empty(self):
        """PresenterResult 默认 error_class="" 表示无错。"""
        res = PresenterResult(success=True, message="ok")
        assert res.error_class == ""

    def test_error_class_field_can_be_set(self):
        res = PresenterResult(success=False, message="x", error_class="OOM")
        assert res.error_class == "OOM"


# ---------------------------------------------------------------------------
# record_failure 不掩盖原始错误
# ---------------------------------------------------------------------------


class TestRecordFailure:
    def test_record_failure_db_error_returns_negative(self, monkeypatch):
        """写库失败不应抛异常，应返回 -1。"""
        # record_failure 内 from import SessionLocal，所以 patch 源模块
        from src.shared import database as db_mod
        class FakeSessCtx:
            def __enter__(self): raise RuntimeError("DB down")
            def __exit__(self, *a): return False
        def fake_session_local():
            return FakeSessCtx()
        monkeypatch.setattr(db_mod, "SessionLocal", fake_session_local)
        from src.content_factory.presenter import comfy_failure_model
        result = comfy_failure_model.record_failure(
            task_name="x", error_class="OOM", error_message="test",
        )
        assert result == -1  # 不抛异常，返回 -1
