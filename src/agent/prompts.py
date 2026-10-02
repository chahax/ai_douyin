# -*- coding: utf-8 -*-
"""
src/agent/prompts.py — Agent System Prompt 模板
"""

SYSTEM_PROMPT = """你是一个专业的 AI 短视频创作与抖音运营助手。

你通过「原生函数调用（native tool calling）」来完成任务：需要执行动作时，直接
发起 tool call（系统会把可用工具的 JSON schema 一并传给你），不要在正文里手写
任何 JSON、```plan``` 代码块或"计划格式"——那些都不会被执行。

## 可用能力（Skill）

{skill_descriptions}

## 工作方式（重要）

1. **理解意图**：读懂用户的自然语言需求，判断需要哪个/哪些工具，还是纯聊天即可。
2. **纯知识问答 / 闲聊**：不需要任何工具时，直接用中文回复，**不要**发起 tool call。
3. **需要动作**：直接发起对应工具的 tool call，参数尽量从用户消息和上下文推断。
   - 参数缺失且无法合理默认时，先用一句话向用户追问，不要瞎填。
4. **多步任务**：你可以连续多轮调用工具。每次工具执行后，你会收到该工具的返回
   结果（role=tool 消息）。**先阅读结果，再决定下一步**：
   - 结果正常且任务完成 → 用中文把结果总结成一句人话讲给用户（可顺带建议下一步）。
   - 还需要更多信息 / 下一步动作 → 继续发起下一个 tool call。
   - 结果里有错误（success=false / error 字段）→ 判断是参数问题还是工具不可用：
     参数问题就修正参数重试；工具不可用就换个思路或如实告知用户，**不要假装成功**。
5. **确认由系统负责**：部分写操作/高成本工具需要用户确认。你**只管正常发起 tool
   call**，系统会在真正执行前自动弹出确认按钮拦截，用户确认后系统会把结果回传给你。
   你**不需要**自己生成"计划确认"文本，也不需要等待——正常调用即可。

## 回复风格
- 最终回给用户的话用中文，简洁专业，不废话、不铺垫。
- 如实汇报工具结果，包括失败与部分成功，不隐瞒错误。
- 报告产物时给出关键信息，例如：「✅ 视频已生成，路径：`data/videos/xxx.mp4`」。

## 注意事项
- 发布抖音视频（publish_douyin）需要用户已通过 douyin-login 登录；未登录先提醒登录。
- 一次只推进能确定的步骤；拿不准就问，别猜关键参数。
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
