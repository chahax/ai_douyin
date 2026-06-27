# -*- coding: utf-8 -*-
"""
Tests for src/agent/skill_decorator.py and the refactored SkillRegistry.

Covers:
  - @skill decorator registration
  - override on name collision
  - validate_params: missing / wrong type / out-of-range / unknown / choice
  - **kwargs absorber behavior (老 SKILLS 兼容)
  - get_skill_descriptions grouping by category
  - the 22 legacy Skills still work
"""

import pytest

from src.agent.skill_decorator import (
    ParamType,
    Skill,
    SkillParam,
    clear_registered_skills,
    get_registered_skills,
    skill,
)
from src.agent.registry import (
    SkillRegistry,
    validate_params,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_decorator_registry():
    """每个测试前清空装饰器注册表，避免污染。"""
    clear_registered_skills()
    yield
    clear_registered_skills()


def _make_skill(
    *,
    name="echo",
    requires_confirmation=True,
    params=None,
    category="general",
    func=None,
):
    if func is None:
        func = lambda **kw: {"ok": True, "kw": kw}  # noqa: E731
    return Skill(
        name=name,
        description="test",
        func=func,
        params=params or [],
        requires_confirmation=requires_confirmation,
        category=category,
    )


# ---------------------------------------------------------------------------
# @skill decorator
# ---------------------------------------------------------------------------


class TestSkillDecorator:
    def test_register_basic(self):
        @skill("test_a", "first test", requires_confirmation=False)
        def f():
            return {"ok": True}

        reg = get_registered_skills()
        assert len(reg) == 1
        assert reg[0].name == "test_a"
        assert reg[0].description == "first test"
        assert reg[0].requires_confirmation is False

    def test_register_with_explicit_params(self):
        @skill(
            "test_b",
            "second test",
            requires_confirmation=True,
            category="测试",
            examples=['{"x": 1}'],
            params=[
                SkillParam("x", ParamType.INT, required=True, description="X value"),
                SkillParam("y", ParamType.STRING, default="hi"),
            ],
        )
        def f(x: int, y: str = "hi") -> dict:
            return {"x": x, "y": y}

        reg = get_registered_skills()
        assert len(reg) == 1
        s = reg[0]
        assert s.category == "测试"
        assert s.examples == ['{"x": 1}']
        assert len(s.params) == 2
        assert s.params[0].required is True
        assert s.params[1].default == "hi"

    def test_auto_derive_params_from_signature(self):
        @skill("test_c", "auto schema", requires_confirmation=False)
        def f(name: str, count: int = 5, **kwargs) -> dict:
            return {}

        s = get_registered_skills()[0]
        names = [p.name for p in s.params]
        assert "name" in names
        assert "count" in names
        assert "kwargs" in names  # **kwargs -> absorber
        name_p = next(p for p in s.params if p.name == "name")
        assert name_p.required is True
        assert name_p.type == ParamType.STRING
        kwargs_p = next(p for p in s.params if p.name == "kwargs")
        assert kwargs_p.is_absorber() is True

    def test_decorator_preserves_function(self):
        @skill("test_d", "preserve", requires_confirmation=False)
        def original():
            return 42

        # 装饰器返回原函数，调用应该不受影响
        assert original() == 42


# ---------------------------------------------------------------------------
# validate_params
# ---------------------------------------------------------------------------


class TestValidateParams:
    def test_missing_required(self):
        s = _make_skill(
            params=[SkillParam("query", ParamType.STRING, required=True)],
        )
        ok, err, code = validate_params(s, {})
        assert ok is False
        assert code == "PARAM_MISSING"
        assert "query" in err

    def test_wrong_type_string(self):
        s = _make_skill(
            params=[SkillParam("name", ParamType.STRING, required=True)],
        )
        ok, err, code = validate_params(s, {"name": 123})
        assert ok is False
        assert code == "PARAM_TYPE"

    def test_wrong_type_int(self):
        s = _make_skill(
            params=[SkillParam("count", ParamType.INT, required=True)],
        )
        ok, err, code = validate_params(s, {"count": "five"})
        assert ok is False
        assert code == "PARAM_TYPE"

    def test_wrong_type_bool(self):
        s = _make_skill(
            params=[SkillParam("flag", ParamType.BOOL, required=True)],
        )
        ok, err, code = validate_params(s, {"flag": "true"})  # 字符串不是 bool
        assert ok is False
        assert code == "PARAM_TYPE"

    def test_out_of_range_min(self):
        s = _make_skill(
            params=[
                SkillParam("n", ParamType.INT, required=True, min_value=1),
            ],
        )
        ok, err, code = validate_params(s, {"n": 0})
        assert ok is False
        assert code == "PARAM_RANGE"

    def test_out_of_range_max(self):
        s = _make_skill(
            params=[
                SkillParam("n", ParamType.INT, required=True, max_value=10),
            ],
        )
        ok, err, code = validate_params(s, {"n": 11})
        assert ok is False
        assert code == "PARAM_RANGE"

    def test_choice_violation(self):
        s = _make_skill(
            params=[
                SkillParam(
                    "mode",
                    ParamType.CHOICE,
                    required=True,
                    choices=["a", "b", "c"],
                ),
            ],
        )
        ok, err, code = validate_params(s, {"mode": "z"})
        assert ok is False
        assert code == "PARAM_CHOICE"

    def test_choice_ok(self):
        s = _make_skill(
            params=[
                SkillParam(
                    "mode",
                    ParamType.CHOICE,
                    required=True,
                    choices=["a", "b"],
                ),
            ],
        )
        ok, _, _ = validate_params(s, {"mode": "a"})
        assert ok is True

    def test_unknown_param_no_absorber(self):
        s = _make_skill(
            params=[SkillParam("x", ParamType.INT, required=True)],
        )
        ok, err, code = validate_params(s, {"x": 1, "y": 2})
        assert ok is False
        assert code == "PARAM_UNKNOWN"
        assert "y" in err

    def test_unknown_param_with_absorber(self):
        s = _make_skill(
            params=[
                SkillParam("x", ParamType.INT, required=True),
                SkillParam("kwargs", ParamType.ANY),  # absorber
            ],
        )
        ok, _, _ = validate_params(s, {"x": 1, "y": 2, "z": "anything"})
        assert ok is True

    def test_optional_param_missing_ok(self):
        s = _make_skill(
            params=[
                SkillParam("opt", ParamType.STRING, required=False, default="d"),
            ],
        )
        ok, _, _ = validate_params(s, {})
        assert ok is True


# ---------------------------------------------------------------------------
# SkillRegistry merging + legacy SKILLS
# ---------------------------------------------------------------------------


class TestSkillRegistry:
    def test_legacy_skills_loaded(self):
        r = SkillRegistry()
        # 22 个老 SKILLS 都应可用
        names = [s.name for s in r.list_all()]
        assert "rag_search" in names
        assert "publish_douyin" in names
        assert "investigate_problems" in names
        assert len(names) == 22

    def test_legacy_skill_auto_derives_params(self):
        r = SkillRegistry()
        s = r.get("rag_search")
        assert s is not None
        # 老 SKILLS 列表的 Skill 没有显式 params，registry 应自动 derive
        param_names = {p.name for p in s.params}
        assert "query" in param_names
        assert "top_k" in param_names
        # **kwargs -> absorber
        assert "kwargs" in param_names

    def test_decorator_overrides_legacy(self):
        @skill(
            "rag_search",
            "OVERRIDDEN",
            requires_confirmation=False,
            category="测试",
        )
        def f(**kwargs):
            return {"overridden": True}

        r = SkillRegistry()
        s = r.get("rag_search")
        assert s.description == "OVERRIDDEN"
        assert s.category == "测试"

    def test_decorator_adds_new_skill(self):
        @skill("brand_new", "new", requires_confirmation=False)
        def f():
            return {"ok": True}

        r = SkillRegistry()
        names = [s.name for s in r.list_all()]
        assert "brand_new" in names
        assert len(names) == 23  # 22 legacy + 1 new

    def test_call_validates_params(self):
        r = SkillRegistry()
        # 缺必需 query
        res = r.call("rag_search", {})
        assert res["success"] is False
        assert res["code"] == "PARAM_MISSING"

    def test_call_unknown_skill(self):
        r = SkillRegistry()
        res = r.call("nonexistent_skill", {})
        assert res["success"] is False
        assert "未知 Skill" in res["error"]

    def test_call_with_absorber_passes_through(self):
        r = SkillRegistry()
        # 实际调 rag_search 因为没有 embedding model 会失败，
        # 但校验应放行（不应报 PARAM_UNKNOWN）
        res = r.call("rag_search", {"query": "x", "extra_field": 1})
        # 不应含 PARAM_UNKNOWN code
        assert res.get("code") != "PARAM_UNKNOWN"


# ---------------------------------------------------------------------------
# get_skill_descriptions
# ---------------------------------------------------------------------------


class TestGetSkillDescriptions:
    def test_groups_by_category(self):
        r = SkillRegistry()
        desc = r.get_skill_descriptions()
        # 默认 category="general" 的都在一起
        assert "## general" in desc

    def test_includes_required_optional_markers(self):
        r = SkillRegistry()
        desc = r.get_skill_descriptions()
        # rag_search 有 query 必填 + top_k 可选
        assert "**rag_search**" in desc
        assert "query: <string>" in desc
        assert "top_k" in desc

    def test_includes_confirmation_flag(self):
        r = SkillRegistry()
        desc = r.get_skill_descriptions()
        # 写操作需要确认
        assert "需要确认" in desc
        # 读操作无需确认
        assert "无需确认" in desc
