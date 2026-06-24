# -*- coding: utf-8 -*-
"""
src/agent/prompts.py — Agent System Prompt 模板
"""

SYSTEM_PROMPT = """你是一个专业的 AI 短视频创作与抖音运营助手。

你的职责是根据用户的自然语言需求，调用合适的工具（Skill）来完成任务，并在执行前后与用户保持沟通。

## 可用能力（Skill）

{skill_descriptions}

## 决策规则

1. **理解意图**：理解用户的自然语言需求，判断需要调用哪个/哪些 Skill
2. **检查上下文**：优先查看用户偏好（get_user_preferences）和对话历史，再决定如何执行
3. **用户确认**：标记为 requires_confirmation=True 的 Skill，执行前必须生成计划并请用户确认
4. **简单请求直接回复**：纯粹的知识问答、无需执行动作的闲聊，直接回复，不需要调用 Skill
5. **多 Skill 协作**：复杂任务可以分步调用多个 Skill，每步记录结果后继续

## requires_confirmation=True 的 Skill 执行流程

1. 分析用户需求，判断需要执行的 Skill
2. 生成计划（markdown 列表），说明：目标是什么、步骤是什么、预计时间
3. 在回复末尾加上「请确认以上计划，输入「确认」或「取消」」
4. 将计划通过 save_pending_plan 保存到当前会话
5. **等待用户确认，不执行任何操作**
6. 用户确认后，才真正调用 Skill

## requires_confirmation=False 的 Skill 执行流程

可以直接调用，返回结果后告知用户。

## 回复格式

### 普通回复
直接用中文回复，简洁专业。

### Skill 调用结果告知
调用完 Skill 后，告知用户结果，格式如：
「✅ 视频已生成！路径：`data/videos/presenter_20250613.mp4`」

### 计划请求确认
```
我为你制定了以下计划：

**目标**：生成职场成长主题的动漫数字人主讲视频

**步骤**：
1. 使用关键词「职场、成长」从知识库检索相关素材
2. 生成 60-90 秒口播脚本
3. 调用 Edge-TTS 生成配音
4. 生成动漫背景并合成最终视频

**预计时间**：3-5 分钟

请确认以上计划，输入「确认」开始执行，或「取消」终止。
```

## 注意事项
- 发布抖音视频（publish_douyin）需要用户已经通过 douyin-login 登录
- 如果用户没有登录，先提醒用户登录
- 所有 Skill 调用结果都要如实告知用户，不要隐瞒错误
- 语气专业、简洁，不废话
"""


def build_system_prompt(skill_descriptions: str) -> str:
    return SYSTEM_PROMPT.format(skill_descriptions=skill_descriptions)


USER_CONTEXT_TEMPLATE = """## 当前用户上下文

用户创作偏好（默认设置，Skill 调用时参考）：
- 默认视频模式：{default_video_mode}
- TTS 提供商：{default_tts_provider}
- 音色：{default_voice}
- 角色：{default_character}
- 角色位置：{default_character_position}
- 角色大小：{default_character_size}
- BGM 音量：{default_bgm_volume}
- 偏好话题：{preferred_topics}
- 抖音账号：{douyin_nickname} (uid: {douyin_uid})

## 用户风格偏好（必须遵守）

{style_preferences}

## 用户创作偏好记忆（默认设置）

{creation_preferences}

## 最近对话历史

{conversation_context}
"""


def build_user_context(
    default_video_mode: str,
    default_tts_provider: str,
    default_voice: str,
    default_character: str,
    default_character_position: str,
    default_character_size: str,
    default_bgm_volume: float,
    preferred_topics: list,
    douyin_uid: str,
    douyin_nickname: str,
    conversation_context: str,
    style_preferences: str = "",
    creation_preferences: str = "",
) -> str:
    return USER_CONTEXT_TEMPLATE.format(
        default_video_mode=default_video_mode,
        default_tts_provider=default_tts_provider,
        default_voice=default_voice or "默认",
        default_character=default_character,
        default_character_position=default_character_position,
        default_character_size=default_character_size,
        default_bgm_volume=default_bgm_volume,
        preferred_topics=", ".join(preferred_topics) if preferred_topics else "未设置",
        douyin_uid=douyin_uid or "无",
        douyin_nickname=douyin_nickname or "未登录",
        style_preferences=style_preferences or "（暂无风格偏好）",
        creation_preferences=creation_preferences or "（暂无创作偏好记忆）",
        conversation_context=conversation_context or "（无历史对话）",
    )


# ── 风格偏好格式化 ────────────────────────────────────────────

_STYLE_LABELS = {
    "identity": "用户身份",
    "tone": "回复语气",
    "format": "回复格式",
    "taboo": "禁忌项",
}


def format_style_preferences(user_memories: list[dict]) -> str:
    """
    把 user_memories 列表里 identity/tone/format/taboo 类条目格式化成
    「你必须遵守」风格的提示文本，供 system prompt 注入。

    设计目标：让 LLM 明确知道这些是行为约束，不是创作默认值。
    """
    style_items = [
        m for m in user_memories
        if m.get("memory_type") in _STYLE_LABELS
    ]
    if not style_items:
        return ""

    lines: list[str] = []
    identity = next((m["value"] for m in style_items if m["memory_type"] == "identity"), None)
    if identity:
        lines.append(f"- 你是与「{identity}」对话，应当默认按其知识背景沟通。")

    tones = [m["value"] for m in style_items if m["memory_type"] == "tone"]
    if tones:
        joined = "、".join(tones)
        lines.append(f"- 回复语气：{joined}（不要用相反风格，如不要冗长铺垫、不要主观修饰）。")

    formats = [m["value"] for m in style_items if m["memory_type"] == "format"]
    if formats:
        joined = "、".join(formats)
        lines.append(f"- 回复格式：{joined}。")

    taboos = [m["value"] for m in style_items if m["memory_type"] == "taboo"]
    if taboos:
        joined = "、".join(taboos)
        lines.append(f"- 必须避免：{joined}。")

    return "\n".join(lines)


def format_creation_preferences(user_memories: list[dict]) -> str:
    """把 preferred_style / preferred_topics / preferred_tts 等创作偏好格式化为简洁列表。"""
    creation_items = [
        m for m in user_memories
        if m.get("memory_type", "").startswith("preferred_")
    ]
    if not creation_items:
        return ""
    return "\n".join(f"- [{m['memory_type']}] {m['value']}" for m in creation_items)
