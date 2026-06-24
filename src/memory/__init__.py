"""
src/memory/ — Agent 记忆系统

导出主要类，供其他模块导入使用。
"""

from src.memory.models import UserProfile, ConversationSession, ConversationMessage
from src.memory.manager import MemoryManager, UserPreferences, ChatMessage
from src.memory.problem_memory import (
    MemoryLayerManager,
    ConversationMemory,
    UserMemory,
    ProblemMemory,
    ProblemStatus,
)

__all__ = [
    # 基础记忆系统
    "MemoryManager",
    "UserPreferences",
    "ChatMessage",
    "UserProfile",
    "ConversationSession",
    "ConversationMessage",
    # 分层记忆系统
    "MemoryLayerManager",
    "ConversationMemory",
    "UserMemory",
    "ProblemMemory",
    "ProblemStatus",
]
