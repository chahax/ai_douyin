# -*- coding: utf-8 -*-
"""
src/agent/skill_decorator.py — Skill 装饰器 + 显式参数 schema

把"Python 函数即 Skill"做到位：装饰器在注册时拿到每个参数的
类型/默认值/描述，LLM 看到的是结构化 schema，不再是
`inspect.signature` 拼出来的字符串。

设计原则：
  - 向后兼容：现有 SKILLS 列表继续工作，新 Skill 用 @skill 注册
  - 渐进迁移：单个 Skill 可独立从老列表搬到装饰器
  - 失败兜底：未识别 key 走 __absorb__ 槽（**kwargs 兼容）
"""

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ParamType(str, Enum):
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"
    DICT = "dict"
    CHOICE = "choice"
    ANY = "any"


# Python 类型 → ParamType 的映射
_PY_TYPE_MAP = {
    str: ParamType.STRING,
    int: ParamType.INT,
    float: ParamType.FLOAT,
    bool: ParamType.BOOL,
    list: ParamType.LIST,
    dict: ParamType.DICT,
}


@dataclass
class SkillParam:
    """单个参数的 schema。"""

    name: str
    type: ParamType = ParamType.STRING
    required: bool = False
    default: Any = None
    description: str = ""
    choices: list = field(default_factory=list)        # 仅 CHOICE 用
    min_value: float | None = None                      # 仅 INT / FLOAT
    max_value: float | None = None

    def is_absorber(self) -> bool:
        """这个参数是 **kwargs 兜底（吸收所有未知 key）。"""
        return self.name == "kwargs" and self.type == ParamType.ANY


@dataclass
class Skill:
    """Skill 注册信息。"""

    name: str
    description: str
    func: Callable
    params: list[SkillParam] = field(default_factory=list)
    requires_confirmation: bool = True
    category: str = "general"                            # UI 分组：创作/发布/养号/系统/记忆
    examples: list[str] = field(default_factory=list)     # LLM 参考用法


# 装饰器注册的 Skills（追加在 SKILLS 列表之后）
_SKILLS: list[Skill] = []


def _py_to_param_type(py_type: Any) -> ParamType:
    """把 Python 类型注解映射到 ParamType。无法识别时回退到 STRING。"""
    if py_type in _PY_TYPE_MAP:
        return _PY_TYPE_MAP[py_type]
    origin = getattr(py_type, "__origin__", None)
    if origin in (list, tuple):
        return ParamType.LIST
    if origin is dict:
        return ParamType.DICT
    return ParamType.STRING


def _derive_from_signature(fn: Callable) -> list[SkillParam]:
    """从函数签名推导参数 schema（兼容 **kwargs 的老 Skill）。"""
    sig = inspect.signature(fn)
    params: list[SkillParam] = []
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            # *args — 极少见，跳过
            continue
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            # **kwargs — 插入一个吸收器
            params.append(
                SkillParam(
                    name="kwargs",
                    type=ParamType.ANY,
                    required=False,
                    default="__absorb__",
                    description="additional options (absorbed)",
                )
            )
            continue
        py_type = (
            p.annotation
            if p.annotation is not inspect.Parameter.empty
            else str
        )
        param_type = _py_to_param_type(py_type)
        required = p.default is inspect.Parameter.empty
        default = None if required else p.default
        params.append(
            SkillParam(
                name=p.name,
                type=param_type,
                required=required,
                default=default,
                description="",  # 装饰器注册的 Skill 应显式提供
            )
        )
    return params


def skill(
    name: str,
    description: str,
    *,
    requires_confirmation: bool = True,
    category: str = "general",
    examples: list[str] | None = None,
    params: list[SkillParam] | None = None,
):
    """
    装饰器：注册一个 Skill。

    用法：

        @skill(
            "rag_search",
            "从知识库检索相关段落",
            requires_confirmation=False,
            category="记忆",
            examples=['{"query": "人生哲学", "top_k": 3}'],
            params=[
                SkillParam("query", ParamType.STRING, required=True, description="查询文本"),
                SkillParam("top_k", ParamType.INT, default=3, description="返回条数"),
            ],
        )
        def _search_knowledge(query: str, top_k: int = 3) -> dict:
            ...
    """
    resolved_examples = examples or []

    def wrap(fn: Callable) -> Callable:
        resolved_params = params if params is not None else _derive_from_signature(fn)
        _SKILLS.append(
            Skill(
                name=name,
                description=description,
                func=fn,
                params=resolved_params,
                requires_confirmation=requires_confirmation,
                category=category,
                examples=resolved_examples,
            )
        )
        return fn

    return wrap


def get_registered_skills() -> list[Skill]:
    """返回所有通过 @skill 装饰器注册的 Skill（拷贝）。"""
    return list(_SKILLS)


def clear_registered_skills() -> None:
    """测试用：清空装饰器注册表。"""
    _SKILLS.clear()
