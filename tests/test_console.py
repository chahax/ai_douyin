"""Focused tests for safe JSON output on Windows GBK consoles."""

from __future__ import annotations

import io
import json
import sys

import pytest

from src.shared.console import safe_print_json


class _FakeStdout:
    """Strict GBK stdout that rejects characters outside its repertoire."""

    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        value.encode("gbk")
        self.parts.append(value)
        return len(value)

    def flush(self) -> None:
        pass

    def text(self) -> str:
        return "".join(self.parts)


def test_gbk_fallback_is_ascii_and_round_trips_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    data = {"book_name": "测试➕小说", "emoji": "📚"}

    safe_print_json(data)

    output = fake.text().rstrip("\n")
    output.encode("ascii")
    assert json.loads(output) == data


def test_gbk_safe_text_uses_human_readable_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    data = {"book_name": "测试小说", "chapters": 10}

    safe_print_json(data)

    output = fake.text().rstrip("\n")
    assert "测试小说" in output
    assert json.loads(output) == data


def test_output_ends_with_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    safe_print_json([1, 2, 3])
    assert fake.text().endswith("\n")


def test_forwards_json_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    safe_print_json({"z": 1, "a": 2}, sort_keys=True)
    assert list(json.loads(fake.text()).keys()) == ["a", "z"]
