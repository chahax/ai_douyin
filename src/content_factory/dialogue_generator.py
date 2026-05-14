"""
dialogue_generator.py — 双角色对话脚本生成

生成带 speaker 标签的结构化对话，用于 Edge-TTS 双角色语音合成 + SadTalker 口型驱动。

对话规律：B 先描述真实生活场景 → A 引出概念 → B 追问 → A 解释原理
"""

import json
import os
from typing import List, Dict, Optional

from src.shared.llm_client import llm_client
from src.shared.logger import logger


# 角色人格常量（与 SADTALKER_VIDEO_PLAN.md 保持一致）
ROLE_A_PERSONA = {
    "name": "学长",
    "voice": "zh-CN-YunjianNeural",
    "rate": "+5%",
    "traits": ["逻辑清晰", "语速中等", "冷静沉稳", "擅长用例子讲解"],
    "style": "A 是引导者，擅长从实际问题切入，用具体案例帮助理解",
}

ROLE_B_PERSONA = {
    "name": "学弟",
    "voice": "zh-CN-XiaoyiNeural",
    "rate": "+10%",
    "traits": ["普通人视角", "真诚好奇", "语速轻快", "有真实生活感受"],
    "style": "B 从真实生活场景出发，先描述遇到的困惑或经历，再自然引出对原理的追问",
}


class DialogueGenerator:
    def __init__(self):
        self.prompt_template = self._load_prompt()
        self.role_a = ROLE_A_PERSONA
        self.role_b = ROLE_B_PERSONA

    def _load_prompt(self) -> str:
        """加载对话生成 prompt 模板"""
        try:
            prompt_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "docs", "prompts", "dialogue-generation.txt"
            )
            prompt_path = os.path.normpath(prompt_path)
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning("dialogue-generation.txt not found, using fallback prompt")
            return self._fallback_prompt()

    def _fallback_prompt(self) -> str:
        return """你是知识科普对话节目专家，追求真实自然，像两个朋友在聊天。

角色设定：
- 角色A（学长）：逻辑清晰，语速中等，冷静沉稳，擅长用例子讲解。A是引导者，擅长从实际问题切入。
- 角色B（学弟）：普通人视角，真诚好奇，语速轻快，有真实生活感受。B从真实生活场景出发，先描述遇到的困惑，再自然引出对原理的追问。

对话规律：
1. B 先从真实生活场景或具体经历切入（不是直接问概念）
2. A 从 B 描述的场景引出知识点
3. B 追问"为什么"或"什么意思"
4. A 用具体数字或例子解释原理
5. B 联系回自己或举一反三

语言风格：
- B 说的话要像生活中真的在聊天的语气，可以有"诶"、"话说"、"我记得"等
- A 的解释要清晰但不书面，像在认真教导朋友
- 不要使用学术腔或空泛鸡汤
- 禁止出现"关注我"、"点赞"等引导语

对话长度：4-8轮（8-16句），每句话不超过50字

请输出JSON格式：
{{"title": "标题", "summary": "总结", "dialogue": [{"speaker": "A", "text": "..."}, ...]}}
"""

    def generate_dialogue(
        self,
        wisdom_data: dict,
        context: str = "",
        role_a_persona: dict = None,
        role_b_persona: dict = None,
    ) -> dict:
        """
        生成双角色对话脚本。

        Args:
            wisdom_data: 智慧信息字典，包含 title/core_message/quote/elaboration 等字段
            context: RAG 检索到的上下文内容（可选）
            role_a_persona: 角色A的人格设定（默认使用 ROLE_A_PERSONA）
            role_b_persona: 角色B的人格设定（默认使用 ROLE_B_PERSONA）

        Returns:
            {"title": "...", "summary": "...", "dialogue": [{"speaker": "A", "text": "..."}, ...]}
        """
        role_a = role_a_persona or self.role_a
        role_b = role_b_persona or self.role_b

        # 构建 context 内容
        if not context:
            context = self._build_context(wisdom_data)

        # 格式化 prompt
        prompt = self.prompt_template.format(
            role_a_name=role_a["name"],
            role_a_traits="，".join(role_a["traits"]),
            role_a_style=role_a["style"],
            role_b_name=role_b["name"],
            role_b_traits="，".join(role_b["traits"]),
            role_b_style=role_b["style"],
            context=context,
        )

        system_msg = (
            "你是一个知识科普对话节目专家，追求真实自然的对话风格。\n"
            "严格按要求输出JSON格式，不要输出Markdown代码块，不要额外解释。"
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

        logger.info(f"Generating dialogue for topic: {wisdom_data.get('title', 'unknown')}")
        response_text = llm_client.chat_completion(messages, temperature=0.8, json_mode=True)

        if not response_text:
            logger.error("LLM returned empty response for dialogue generation")
            return self._fallback_dialogue(wisdom_data)

        return self._parse_response(response_text, wisdom_data)

    def _build_context(self, wisdom_data: dict) -> str:
        """从 wisdom_data 构建上下文"""
        parts = []
        if wisdom_data.get("title"):
            parts.append(f"主题：{wisdom_data['title']}")
        if wisdom_data.get("core_message"):
            parts.append(f"核心观点：{wisdom_data['core_message']}")
        if wisdom_data.get("quote"):
            parts.append(f"金句：{wisdom_data['quote']}")
        if wisdom_data.get("elaboration"):
            parts.append(f"详细阐述：{wisdom_data['elaboration']}")
        if wisdom_data.get("actionable"):
            parts.append(f"行动建议：{wisdom_data['actionable']}")
        return "\n".join(parts) if parts else wisdom_data.get("core_message", "")

    def _parse_response(self, response_text: str, wisdom_data: dict) -> dict:
        """解析 LLM 响应，提取对话内容"""
        try:
            cleaned = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)

            # 验证必要字段
            if "dialogue" not in data or not isinstance(data.get("dialogue"), list):
                logger.warning(f"Invalid dialogue format, using fallback. Response: {response_text[:200]}")
                return self._fallback_dialogue(wisdom_data)

            # 清理每句对话
            cleaned_dialogue = []
            for item in data["dialogue"]:
                if isinstance(item, dict) and item.get("speaker") and item.get("text"):
                    text = item["text"].strip()
                    # 移除可能的关注引导语
                    text = self._clean_text(text)
                    cleaned_dialogue.append({
                        "speaker": item["speaker"].upper(),
                        "text": text,
                    })

            if not cleaned_dialogue:
                return self._fallback_dialogue(wisdom_data)

            result = {
                "title": data.get("title", wisdom_data.get("title", "智慧对话")),
                "summary": data.get("summary", wisdom_data.get("core_message", "")),
                "dialogue": cleaned_dialogue,
            }
            logger.info(f"Dialogue generated: {len(cleaned_dialogue)} lines")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse dialogue JSON: {e}, response: {response_text[:300]}")
            return self._fallback_dialogue(wisdom_data)

    def _clean_text(self, text: str) -> str:
        """清理对话文本中的引导语和说话人标签"""
        import re
        # 移除说话人标签前缀（如"学长说："、"学弟说："、"A说："等）
        text = re.sub(r"^(学长|学弟|[AB])[说：:\s]+", "", text)
        # 移除关注、点赞等引导语
        patterns = [
            r"(关注我|点赞|评论|转发|收藏|一键三连)[^。！？!?\n]*[。！？!?]?",
            r"请[点关评转]?[赞注论发][^。！？!?\n]*[。！？!?]?",
        ]
        for p in patterns:
            text = re.sub(p, "", text)
        return text.strip()

    def _fallback_dialogue(self, wisdom_data: dict) -> dict:
        """当 LLM 生成失败时，返回默认对话"""
        topic = wisdom_data.get("title", wisdom_data.get("core_message", "人生智慧"))
        core = wisdom_data.get("core_message", "")

        return {
            "title": f"【{topic}】人生智慧对话",
            "summary": core,
            "dialogue": [
                {"speaker": "B", "text": f"诶，我最近在想个事儿，跟{topic}有关。"},
                {"speaker": "A", "text": f"说说看，什么事儿？"},
                {"speaker": "B", "text": f"就是感觉{core[:30]}...但又说不清楚。"},
                {"speaker": "A", "text": f"我懂你，其实这背后有个底层逻辑。"},
                {"speaker": "B", "text": "什么逻辑？"},
                {"speaker": "A", "text": f"{core[:50]}"},
                {"speaker": "B", "text": "哦！我好像有点明白了。"},
                {"speaker": "A", "text": "理解了这个，很多事情就通了。"},
            ],
        }

    def split_by_speaker(self, dialogue_result: dict) -> dict:
        """
        将对话按 speaker 分割为两组，供 Edge-TTS 分别生成音频。

        Returns:
            {"role_a": [texts], "role_b": [texts], "role_a_voice": "...", "role_b_voice": "..."}
        """
        role_a_lines = []
        role_b_lines = []

        for item in dialogue_result.get("dialogue", []):
            speaker = item.get("speaker", "").upper()
            text = item.get("text", "").strip()
            if not text:
                continue
            if speaker == "A":
                role_a_lines.append(text)
            elif speaker == "B":
                role_b_lines.append(text)

        return {
            "role_a": role_a_lines,
            "role_b": role_b_lines,
            "role_a_voice": self.role_a["voice"],
            "role_b_voice": self.role_b["voice"],
            "role_a_rate": self.role_a["rate"],
            "role_b_rate": self.role_b["rate"],
        }


if __name__ == "__main__":
    gen = DialogueGenerator()
    test_wisdom = {
        "title": "复利效应",
        "core_message": "利滚利的威力——时间越长，收益增长越快",
        "quote": "复利是世界上第八大奇迹",
        "elaboration": "普通存款是本金乘利率，复利是利息也计入本金继续生利息",
        "actionable": "尽早开始储蓄，让时间成为你的朋友",
    }
    result = gen.generate_dialogue(test_wisdom)
    print(json.dumps(result, indent=2, ensure_ascii=False))
