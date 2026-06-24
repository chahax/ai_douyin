"""
src/agent/ — AI Agent 调度层

核心组件：
  agent.py      — Agent 主类，chat() 接口
  registry.py   — Skill 注册表
  prompts.py   — System Prompt 模板
"""

from src.agent.agent import Agent, AgentResponse, ExecutionPlan, ConfirmStatus
from src.agent.registry import SkillRegistry, Skill

__all__ = [
    "Agent",
    "AgentResponse",
    "ExecutionPlan",
    "ConfirmStatus",
    "SkillRegistry",
    "Skill",
]
