import json
import re
from src.shared.llm_client import llm_client
from src.shared.logger import logger

class ScriptGenerator:
    def __init__(self):
        # Load the prompt template
        try:
            with open("docs/prompts/script-generation.txt", "r", encoding="utf-8") as f:
                self.prompt_template = f.read()
        except FileNotFoundError:
            logger.warning("Prompt file not found. Using default prompt.")
            self.prompt_template = """
            角色：短视频爆款文案创作者
            任务：根据提供的人生智慧，撰写一段适合口播的短视频逐字稿。
            输入智慧信息：{wisdom_json}
            文案要求：黄金前3秒（Hook） -> 中间展开（Body） -> 结尾给出可执行建议（不做关注引导）。
            语言风格：口语化，真诚温暖。
            输出JSON格式：{"script_content": "...", "visual_cues": [], "bgm_suggestion": "..."}
            """

    def generate_script(self, wisdom_data: dict, generation_hints: dict = None) -> dict:
        """
        Generates a video script based on extracted wisdom metadata.
        :param wisdom_data: Dictionary containing wisdom metadata (title, core_message, etc.)
        :return: JSON object with script content, visual cues, and BGM suggestion.
        """
        # Prepare data for prompt formatting, handling missing keys gracefully
        format_data = {
            'title': wisdom_data.get('title', ''),
            'core_message': wisdom_data.get('core_message', ''),
            'quote': wisdom_data.get('quote', ''),
            'elaboration': wisdom_data.get('elaboration', ''),
            'actionable': wisdom_data.get('actionable', ''),
            'scene': wisdom_data.get('scene', ''),
            'emotion': wisdom_data.get('emotion', ''),
            # Fallback for prompt template if it uses {wisdom_json} instead of specific fields
            'wisdom_json': json.dumps(wisdom_data, ensure_ascii=False)
        }

        try:
            # Format the prompt using keyword arguments
            # This handles both the specific template and the default fallback template
            prompt = self.prompt_template.format(**format_data)
        except KeyError as e:
            logger.warning(f"Prompt formatting key error: {e}. Using explicit fallback.")
            # Build a clear prompt with explicit key names
            prompt = f"""请根据以下信息生成短视频口播文案。

输入信息：
标题：{wisdom_data.get('title', '')}
核心观点：{wisdom_data.get('core_message', '')}
金句：{wisdom_data.get('quote', '')}
阐述：{wisdom_data.get('elaboration', '')}
行动建议：{wisdom_data.get('actionable', '')}
场景：{wisdom_data.get('scene', '')}
情绪：{wisdom_data.get('emotion', '')}

要求：
- 生成320~520字的口播逐字稿
- 语言口语化，像真人说话
- 不要在结尾添加关注、点赞等号召语

请仅输出以下JSON格式（不要输出其他内容）：
{{"script_content": "完整口播逐字稿", "visual_cues": [], "bgm_suggestion": ""}}"""
        
        hint_lines = []
        if generation_hints:
            keyword_text = generation_hints.get("keywords", "")
            emotion_type = generation_hints.get("emotion_type", "")
            positive_energy_type = generation_hints.get("positive_energy_type", "")
            target_audience = generation_hints.get("target_audience", "")
            if keyword_text:
                hint_lines.append(f"- 必须围绕这些关键词展开：{keyword_text}")
            if emotion_type:
                hint_lines.append(f"- 情绪类型：{emotion_type}")
            if positive_energy_type:
                hint_lines.append(f"- 正能量类型：{positive_energy_type}")
            if target_audience:
                hint_lines.append(f"- 目标人群：{target_audience}")
        if hint_lines:
            prompt = f"{prompt}\n\n## 强制约束\n" + "\n".join(hint_lines)

        messages = [
            {"role": "system", "content": "你是一位拥有百万粉丝的短视频文案专家，擅长将深刻道理转化为通俗易懂的爆款文案。不要在结尾添加关注、点赞、评论、转发等号召语。"},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"Generating script for wisdom: {wisdom_data.get('title')}")
        response_text = llm_client.chat_completion(messages, temperature=0.8, json_mode=True)
        
        if not response_text:
            return None
            
        try:
            # Clean up potential markdown code blocks if present
            cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
            script_data = json.loads(cleaned_text)
            
            # Handle the Mock response case which might return flat wisdom structure instead of script structure
            if "script_content" not in script_data and "core_message" in script_data:
                 # It's a mock wisdom response, let's fake a script for testing pipeline
                 script_data["script_content"] = f"（Mock Script）大家好！今天想和大家分享一个道理：{script_data.get('core_message')}。希望大家都能行动起来！"
            # Handle the case where LLM returns "content" instead of "script_content"
            if "script_content" not in script_data and "content" in script_data:
                script_data["script_content"] = script_data["content"]
            # Handle the case where LLM returns "script" as a list of segments
            if "script_content" not in script_data and isinstance(script_data.get("script"), list):
                # Extract text from each segment and join into one script
                script_list = script_data["script"]
                texts = []
                for seg in script_list:
                    if isinstance(seg, dict) and seg.get("text"):
                        texts.append(seg["text"])
                    elif isinstance(seg, str):
                        texts.append(seg)
                script_data["script_content"] = "".join(texts)
            if isinstance(script_data.get("script_content"), str):
                cleaned_script = script_data["script_content"]
                cleaned_script = re.sub(r"(关注|点赞|评论|转发|收藏|一键三连)[^。！？!?\n]*[。！？!?]?", "", cleaned_script)
                cleaned_script = re.sub(r"\n{3,}", "\n\n", cleaned_script).strip()
                script_data["script_content"] = cleaned_script

            # Validate that we have actual script content
            if not script_data.get("script_content"):
                logger.error(f"LLM returned script without script_content. Response: {response_text[:500]}")
                return None

            logger.info("Script generated successfully.")
            return script_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None

if __name__ == "__main__":
    # Test with dummy wisdom data
    generator = ScriptGenerator()
    test_wisdom = {
        "title": "如何摆脱精神内耗？",
        "core_message": "活在当下，减少对未来的无谓担忧。",
        "quote": "人最宝贵的是生命...当他回首往事的时候，不会因为虚度年华而悔恨。",
        "elaboration": "很多人的痛苦来源于对过去的悔恨和对未来的恐惧，唯独忘记了体验现在。",
        "actionable": "每天花5分钟冥想，专注呼吸。",
        "scene": "深夜独处",
        "emotion": "治愈"
    }
    result = generator.generate_script(test_wisdom)
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))
