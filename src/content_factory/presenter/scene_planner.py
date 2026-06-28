import json
from pathlib import Path

from src.shared.config import settings
from src.shared.llm_client import llm_client
from src.shared.logger import logger


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ScenePlanner:
    def __init__(self):
        self.prompt_path = PROJECT_ROOT / "docs" / "prompts" / "background-scene-analysis.txt"
        self.library_dir = PROJECT_ROOT / settings.BACKGROUND_SCENE_LIBRARY_DIR
        self._templates: list[dict] | None = None

    def plan(self, text: str, cue: str = "", character: str = "") -> tuple[str, dict]:
        templates = self._load_scene_library()
        analysis = self._analyze_text(text, templates)
        template, score = self._select_template(analysis, templates, text)
        if not template:
            return "", {}
        prompt = self._build_prompt(analysis, template)
        plan = {
            "source": "scene_planner",
            "domain": analysis.get("domain", ""),
            "category": analysis.get("category", ""),
            "subject": analysis.get("subject", ""),
            "action": analysis.get("action", ""),
            "risk_points": analysis.get("risk_points", []),
            "scene_intent": analysis.get("scene_intent", ""),
            "scene_template_id": analysis.get("scene_template_id", ""),
            "forbidden_visuals": analysis.get("forbidden_visuals", []),
            "emotion": analysis.get("emotion", ""),
            "confidence": analysis.get("confidence", 0),
            "reason": analysis.get("reason", ""),
            "matched_template_id": template.get("id", ""),
            "matched_template_score": score,
            "template_visual_prompt": template.get("visual_prompt", ""),
            "template_negative_rules": template.get("negative_rules", []),
            "cue": cue,
            "include_ip": False,
        }
        return prompt, plan

    def _analyze_text(self, text: str, templates: list[dict]) -> dict:
        fallback = self._fallback_analysis(text)
        if not settings.BACKGROUND_SCENE_PLANNER_USE_LLM:
            return fallback
        try:
            template = self.prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Background scene analysis prompt not found. Using fallback analysis.")
            return fallback

        prompt = template.replace("{text}", (text or "").strip()[:900])
        prompt = prompt.replace("{scene_templates}", self._format_template_choices(templates))
        messages = [
            {"role": "system", "content": "你是短视频背景场景分类器。必须只输出合法JSON。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = llm_client.chat_completion_tracked(
                messages, caller="scene_plan", temperature=0.2, json_mode=True,
            )
            if not response:
                return fallback
            cleaned = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                return fallback
            merged = {**fallback, **data}
            return self._validate_analysis(merged, fallback, text, templates)
        except Exception as exc:
            logger.warning(f"Background scene analysis failed. Using fallback analysis: {exc}")
            return fallback

    def _validate_analysis(self, analysis: dict, fallback: dict, text: str, templates: list[dict]) -> dict:
        valid_ids = {str(item.get("id")) for item in templates if item.get("id")}
        scene_template_id = str(analysis.get("scene_template_id") or "")
        confidence = self._safe_float(analysis.get("confidence"), 0.0)
        fallback_id = str(fallback.get("scene_template_id") or "")
        if scene_template_id not in valid_ids or confidence < 0.65:
            if scene_template_id:
                logger.info(
                    f"ScenePlanner rejected LLM scene id, using fallback: id={scene_template_id}, confidence={confidence}"
                )
            analysis["scene_template_id"] = fallback_id
            analysis["confidence"] = 0.0
            analysis["domain"] = fallback.get("domain", analysis.get("domain", ""))
            analysis["category"] = fallback.get("category", analysis.get("category", ""))
            analysis["subject"] = fallback.get("subject", analysis.get("subject", ""))
            analysis["action"] = fallback.get("action", analysis.get("action", ""))

        fallback_category = fallback.get("category") or ""
        category = analysis.get("category") or ""
        if fallback_category != "general_life_advice" and category != fallback_category:
            logger.info(
                f"ScenePlanner category conflict, using fallback category: llm={category}, fallback={fallback_category}"
            )
            analysis["domain"] = fallback.get("domain", analysis.get("domain", ""))
            analysis["category"] = fallback_category
            analysis["subject"] = fallback.get("subject", analysis.get("subject", ""))
            analysis["action"] = fallback.get("action", analysis.get("action", ""))
            analysis["scene_template_id"] = fallback_id
        if not analysis.get("category"):
            analysis["category"] = fallback_category
        if not analysis.get("domain"):
            analysis["domain"] = fallback.get("domain", "general")
        if not isinstance(analysis.get("risk_points"), list):
            analysis["risk_points"] = fallback.get("risk_points", [])
        if not isinstance(analysis.get("forbidden_visuals"), list):
            analysis["forbidden_visuals"] = fallback.get("forbidden_visuals", [])
        return analysis

    def _format_template_choices(self, templates: list[dict]) -> str:
        lines = []
        for item in templates:
            lines.append(
                f"- id: {item.get('id')} | category: {', '.join(item.get('category', []))} | "
                f"applies_to: {', '.join(item.get('applies_to', [])[:10])} | notes: {item.get('notes', '')}"
            )
        return "\n".join(lines)

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fallback_analysis(self, text: str) -> dict:
        value = text or ""
        category = "general_life_advice"
        domain = "general"
        subject = "日常生活场景"
        action = "表达一个生活判断"
        keywords: list[str] = []
        scene_template_id = "general_transition_city_morning"

        rules = (
            ("social_security_coverage", "social_law", "社会保障覆盖", "面对社会保障覆盖不足的问题", "social_security_umbrella_bench", ("社会保障", "社保", "保障", "覆盖不足", "保险", "养老", "医疗")),
            ("responsibility_boundary", "labor_law", "公司和劳动者", "划清管理和责任边界", "responsibility_boundary_line", ("责任", "边界", "指派", "管理", "考勤", "派单", "规章制度", "实际控制", "责任界定")),
            ("platform_worker_rights", "labor_law", "平台劳动者", "面对劳动权益和责任边界困惑", "platform_worker_sidewalk_helmet", ("外卖", "骑手", "网约车", "司机", "主播", "平台", "新业态", "灵活就业", "用工")),
            ("labor_injury", "labor_law", "劳动者", "面对工作中受伤和责任承担", "labor_safety_workshop", ("工伤", "受伤", "事故", "伤害")),
            ("contract_risk", "labor_law", "签约双方", "面对合同和实际管理不一致", "contract_risk_closed_folder", ("合作协议", "劳动合同", "签字", "条款", "外包", "承包", "协议", "合同")),
            ("evidence_preservation", "legal", "维权当事人", "保存证据和记录", "evidence_phone_envelope", ("聊天记录", "转账", "录音", "截图", "订单", "打卡", "证据", "保存")),
            ("legal_process", "legal", "当事人", "进入法律或仲裁流程", "legal_process_plain_steps", ("法院", "仲裁", "起诉", "调解", "判决", "维权", "赔偿", "纠纷")),
            ("income_wage", "labor_law", "劳动者", "关注收入结算和工资报酬", "income_wage_closed_wallet", ("工资", "报酬", "提成", "结算", "拖欠", "加班费", "收入")),
            ("general_transition", "social_law", "社会变化", "解释新模式带来的问题", "general_transition_city_morning", ("近年来", "随着", "这种模式", "背后", "问题", "变化", "模式")),
        )
        for item_category, item_domain, item_subject, item_action, item_template_id, triggers in rules:
            matched = [word for word in triggers if word in value]
            if matched:
                category = item_category
                domain = item_domain
                subject = item_subject
                action = item_action
                scene_template_id = item_template_id
                keywords = matched
                break

        return {
            "domain": domain,
            "category": category,
            "subject": subject,
            "action": action,
            "scene_template_id": scene_template_id,
            "risk_points": [],
            "scene_intent": action,
            "forbidden_visuals": ["readable text", "signboard", "certificate", "wall art", "open document"],
            "emotion": "serious_but_gentle" if domain in {"labor_law", "legal", "social_law"} else "calm_reflective",
            "confidence": 0.0,
            "reason": f"本地关键词匹配: {', '.join(keywords)}" if keywords else "本地默认场景",
        }

    def _load_scene_library(self) -> list[dict]:
        if self._templates is not None:
            return self._templates
        templates: list[dict] = []
        if not self.library_dir.exists():
            logger.warning(f"Background scene library not found: {self.library_dir}")
            self._templates = []
            return self._templates
        for path in sorted(self.library_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    templates.extend(item for item in data if isinstance(item, dict))
            except Exception as exc:
                logger.warning(f"Failed to load scene library {path}: {exc}")
        self._templates = templates
        return templates

    def _select_template(self, analysis: dict, templates: list[dict], text: str) -> tuple[dict | None, int]:
        scene_template_id = str(analysis.get("scene_template_id") or "")
        if scene_template_id:
            for template in templates:
                if template.get("id") == scene_template_id:
                    return template, 100
        return self._match_template(analysis, templates, text)

    def _match_template(self, analysis: dict, templates: list[dict], text: str) -> tuple[dict | None, int]:
        best: dict | None = None
        best_score = -1
        domain = str(analysis.get("domain") or "")
        category = str(analysis.get("category") or "")
        combined_text = f"{text} {analysis.get('subject', '')} {analysis.get('action', '')} {analysis.get('scene_intent', '')}".lower()

        for template in templates:
            score = 0
            if domain and domain in template.get("domain", []):
                score += 4
            if category and category in template.get("category", []):
                score += 5
            for word in template.get("applies_to", []):
                if str(word).lower() in combined_text:
                    score += 2
            if score > best_score:
                best = template
                best_score = score
        if best_score <= 0:
            for template in templates:
                if "general_transition" in template.get("category", []):
                    return template, 0
        return best, best_score

    def _build_prompt(self, analysis: dict, template: dict) -> str:
        negative_rules = ", ".join(str(item) for item in template.get("negative_rules", []))
        forbidden = ", ".join(f"avoid {item}" for item in analysis.get("forbidden_visuals", []) if item)
        parts = [
            template.get("style") or "vertical 9:16 anime illustration, clean modern slice-of-life scene, soft cel shading",
            "high quality soft cel shading",
            "gentle cinematic lighting",
            str(template.get("visual_prompt") or ""),
            f"safe action: {template.get('safe_action', '')}",
            "clear narrative action, no camera close-up, no realistic photo style",
            template.get("safe_area") or "lower 35 percent clean and empty, especially lower right",
            "open empty lower 35 percent reserved for subtitles and presenter overlay",
            "lower right area clean and uncluttered",
            negative_rules,
            forbidden,
            "no written text, no Chinese characters, no English letters, no numbers, no readable or unreadable characters",
            "no glyph-like marks, no pseudo text, no fake writing, no scribbles, no decorative strokes that resemble letters",
            "no logo, no watermark, no speech bubble, no interface",
            "no close-up face, no large human figure, no near back-view person",
        ]
        return ", ".join(part for part in parts if part)
