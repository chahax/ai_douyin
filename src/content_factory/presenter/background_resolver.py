import json
from pathlib import Path

from PIL import Image, ImageDraw

from src.content_factory.presenter.models import CharacterAsset, PresenterSegment
from src.shared.llm_client import llm_client
from src.shared.config import settings
from src.shared.logger import logger


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def project_path(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return PROJECT_ROOT / value


class BackgroundResolver:
    DEFAULT_BACKGROUNDS = (
        "data/videos/bg_comfy_green_loop_motion.mp4",
        "data/videos/bg_loop.mp4",
        "data/videos/bg_healing.jpg",
        "data/bg_t0.png",
    )

    CHARACTER_CANDIDATES = {
        "na1": (
            ("data/framepack/frames_looped/na1_idle_v1/%06d.png", "sequence"),
            ("data/png/composite_na1.png", "static"),
            ("data/png/na1_nobg.png", "static"),
        ),
        "n3": (
            ("data/framepack/frames_looped/n3_idle_v1/%06d.png", "sequence"),
            ("data/png/composite_n3.png", "static"),
            ("data/png/n3_nobg.png", "static"),
        ),
    }

    def resolve_background(self, requested: str, work_dir: Path, style: str = "anime") -> str:
        if requested:
            candidate = project_path(requested)
            if candidate.exists():
                return str(candidate)

        normalized_style = (style or "anime").strip().lower()
        if normalized_style == "anime":
            fallback = work_dir / "background_anime.png"
            self._create_anime_background(fallback)
            return str(fallback)

        for path in self.DEFAULT_BACKGROUNDS:
            candidate = project_path(path)
            if candidate.exists():
                return str(candidate)

        fallback = work_dir / "background_gradient.png"
        self._create_gradient(fallback)
        return str(fallback)

    def resolve_segment_backgrounds(
        self,
        requested: str,
        work_dir: Path,
        segments: list[PresenterSegment],
        style: str = "anime",
        switch_seconds: float = 5.0,
        character: str = "",
        use_comfy: bool = True,
    ) -> list[str]:
        if requested:
            background = self.resolve_background(requested, work_dir, style=style)
            return [background for _ in segments]

        normalized_style = (style or "anime").strip().lower()
        if normalized_style != "anime":
            background = self.resolve_background("", work_dir, style=style)
            return [background for _ in segments]

        backgrounds_dir = work_dir / "backgrounds"
        backgrounds_dir.mkdir(parents=True, exist_ok=True)

        paths: list[str] = []
        segment_index = 0
        current_group = 0
        while segment_index < len(segments):
            group_segments: list[PresenterSegment] = []
            group_elapsed = 0.0
            while segment_index < len(segments) and (not group_segments or group_elapsed < switch_seconds):
                segment = segments[segment_index]
                group_segments.append(segment)
                group_elapsed += max(segment.duration or switch_seconds, 0.1)
                segment_index += 1

            group_text = " ".join(segment.text for segment in group_segments)
            cue = self._build_group_cue(group_segments, group_text)
            background_path = backgrounds_dir / f"bg_{current_group:03d}.png"
            prompt, plan = self.build_background_prompt_with_plan(group_text, cue=cue, character=character)

            generated = False
            if use_comfy:
                generated = self._create_comfy_background(
                    prompt,
                    background_path,
                    seed=260600 + current_group,
                )
            if not generated:
                self._create_anime_background(
                    background_path,
                    seed_index=current_group,
                    cue=cue,
                    scene_text=group_text,
                )

            for segment in group_segments:
                segment.background_group = current_group
                segment.background_prompt = prompt
                segment.background_action = plan["action"]
                segment.background_subject = plan["subject"]
                segment.background_include_ip = plan["include_ip"]
                segment.background_plan = plan
                paths.append(str(background_path))
            current_group += 1
        return paths

    def build_background_prompt(self, text: str, cue: str = "", character: str = "") -> str:
        prompt, _plan = self.build_background_prompt_with_plan(text, cue=cue, character=character)
        return prompt

    def build_background_prompt_with_plan(self, text: str, cue: str = "", character: str = "") -> tuple[str, dict]:
        llm_plan = self._build_llm_background_plan(text)
        if llm_plan:
            prompt = self._plan_to_comfy_prompt(llm_plan)
            return prompt, {
                "action": llm_plan.get("scene_type") or llm_plan.get("content_type") or "llm_plan",
                "subject": llm_plan.get("core_metaphor") or llm_plan.get("content_type") or "llm generated background",
                "include_ip": False,
                "source": "llm",
                "llm_plan": llm_plan,
                "cue": cue,
            }

        plan = self._visual_plan(text)
        ip_subject = self._ip_subject(character)
        subject = ip_subject if plan["include_ip"] else plan["subject"]
        actor_clause = ""
        if plan["include_ip"]:
            actor_clause = (
                f"{ip_subject}, tiny decorative mascot prop about 8 percent of image height, "
                f"placed on the desk or in the middle distance, {plan['actor_action']}, "
                "the environment is the main subject, no living full-size character, "
                "not a portrait, not a close-up, not in the lower right presenter area, "
            )

        prompt = (
            "vertical 9:16 anime illustration, clean modern slice-of-life scene, "
            "high quality soft cel shading, gentle cinematic lighting, "
            f"{actor_clause}{plan['visual']}, "
            "clear narrative action, no camera close-up, no realistic photo style, "
            "no indoor wall, no wall art, no framed pictures, no wall decorations, no hanging plaque, no calligraphy, "
            "no signboard, no plaque, no certificate, no menu board, no poster board, "
            "avoid open document pages, avoid forms, avoid receipts, avoid sheets filled with details, "
            "all paper, cards, notebooks, folders, screens, walls, and signs are completely blank and plain, "
            "no glyph-like marks, no pseudo text, no fake writing, no scribbles, no decorative strokes that resemble letters, "
            "open empty lower 35 percent reserved for subtitles and presenter overlay, "
            "no written text, no Chinese characters, no English letters, no numbers, no readable or unreadable characters, "
            "no signs, no road signs, no posters, no book titles, no labels, no logo, "
            "no watermark, no speech bubble, no interface"
        )
        plan = {
            **plan,
            "subject": subject,
            "source": "rules",
            "llm_plan": {},
            "cue": cue,
        }
        return prompt, plan

    def _build_llm_background_plan(self, text: str) -> dict:
        template_path = PROJECT_ROOT / "docs" / "prompts" / "background-plan-generation.txt"
        try:
            template = template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Background plan prompt file not found. Falling back to rule-based background plan.")
            return {}

        prompt = template.replace("{text}", (text or "").strip()[:900])
        messages = [
            {"role": "system", "content": "你是专业短视频动漫背景分镜导演。必须只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = llm_client.chat_completion(messages, temperature=0.35, json_mode=True)
            if not response:
                return {}
            cleaned = response.replace("```json", "").replace("```", "").strip()
            plan = json.loads(cleaned)
        except Exception as exc:
            logger.warning(f"LLM background plan failed, fallback to rules: {exc}")
            return {}

        if not self._is_valid_llm_plan(plan):
            logger.warning("LLM background plan missing required fields, fallback to rules.")
            return {}
        return plan

    def _is_valid_llm_plan(self, plan: dict) -> bool:
        if not isinstance(plan, dict):
            return False
        required = ("content_type", "scene_type", "composition", "main_visual_prompt", "symbolic_objects")
        if any(not plan.get(key) for key in required):
            return False
        composition = plan.get("composition")
        if not isinstance(composition, dict):
            return False
        if not isinstance(plan.get("symbolic_objects"), list):
            return False
        english_fields = [
            plan.get("content_type", ""),
            plan.get("scene_type", ""),
            plan.get("emotion", ""),
            plan.get("main_visual_prompt", ""),
            plan.get("color_palette", ""),
            plan.get("lighting", ""),
            composition.get("foreground", ""),
            composition.get("midground", ""),
            composition.get("background", ""),
            composition.get("focal_point", ""),
            composition.get("camera_angle", ""),
            *[str(item) for item in plan.get("symbolic_objects", [])],
        ]
        if any(self._contains_cjk(value) for value in english_fields):
            return False
        forbidden_marks = ("《", "》", "“", "”", "book title", "readable title")
        joined = " ".join(str(value).lower() for value in english_fields)
        if any(mark.lower() in joined for mark in forbidden_marks):
            return False
        return True

    def _contains_cjk(self, value: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))

    def _plan_to_comfy_prompt(self, plan: dict) -> str:
        composition = plan.get("composition") or {}
        symbolic_objects = ", ".join(str(item) for item in (plan.get("symbolic_objects") or [])[:6])
        parts = [
            "vertical 9:16 anime illustration",
            "clean modern slice-of-life scene",
            "high quality soft cel shading",
            "professional storyboarding composition",
            "gentle cinematic lighting",
            str(plan.get("main_visual_prompt") or "").strip(),
            f"foreground: {composition.get('foreground', '')}",
            f"midground: {composition.get('midground', '')}",
            f"background: {composition.get('background', '')}",
            f"focal point: {composition.get('focal_point', '')}",
            f"camera angle: {composition.get('camera_angle', 'medium wide shot')}",
            f"symbolic objects: {symbolic_objects}",
            f"color palette: {plan.get('color_palette', 'warm clean soft colors')}",
            f"lighting: {plan.get('lighting', 'soft warm light with gentle shadows')}",
            "all paper, cards, notebooks, folders, screens, walls, and signs are completely blank and plain",
            "no glyph-like marks, no pseudo text, no fake writing, no scribbles, no decorative strokes that resemble letters",
            "open empty lower 35 percent reserved for subtitles and presenter overlay",
            "lower right area clean and uncluttered",
            "plain clean surfaces",
            "no written text, no Chinese characters, no English letters, no numbers, no readable or unreadable characters",
            "no signs, no posters, no book titles, no labels, no logo",
            "no watermark, no speech bubble, no interface",
            "no close-up face, no large portrait, no realistic photo style",
        ]
        return ", ".join(part for part in parts if part and not part.endswith(": "))

    def _build_group_cue(self, segments: list[PresenterSegment], group_text: str) -> str:
        keywords: list[str] = []
        for segment in segments:
            keywords.extend(segment.keywords[:2])
        compact = "、".join(dict.fromkeys(word for word in keywords if word))
        return compact or group_text[:24]

    def _visual_plan(self, text: str) -> dict:
        normalized = text or ""
        rules = (
            {
                "action": "choose",
                "subject": "decision making",
                "triggers": ("选择", "选A", "选错", "决定", "纠结", "正确的选择"),
                "include_ip": True,
                "actor_action": "thoughtfully comparing two blank colored option cards on a desk",
                "visual": "a tidy workspace with two blank colored option cards, a warm desk lamp, and soft morning light, visual metaphor for making a choice",
            },
            {
                "action": "hesitate",
                "subject": "fear of failure",
                "triggers": ("担心", "害怕", "失败", "不敢", "迟迟", "犹豫"),
                "include_ip": True,
                "actor_action": "pausing before a softly lit open doorway with one foot ready to step forward",
                "visual": "a calm room opening into warm light, a blank doorway and gentle floor shadows, visual metaphor for hesitation before action",
            },
            {
                "action": "trust_self",
                "subject": "self trust",
                "triggers": ("相信自己", "信任自己", "内心", "光芒", "接纳"),
                "include_ip": True,
                "actor_action": "looking at a soft glowing reflection in a clean oval mirror",
                "visual": "a quiet study room with an oval mirror, soft inner glow, blank wall, and warm afternoon light",
            },
            {
                "action": "follow",
                "subject": "inner direction",
                "triggers": ("跟随", "指引", "前行", "方向", "导向"),
                "include_ip": True,
                "actor_action": "walking toward a gentle ribbon of light across a clean room",
                "visual": "a simple interior with a warm ribbon of light leading forward, symbolic but grounded, no roads and no arrows",
            },
            {
                "action": "explore_practice",
                "subject": "exploration and practice",
                "triggers": ("探索", "实践", "找到", "道路", "迈出"),
                "include_ip": True,
                "actor_action": "testing a small handmade prototype beside neatly arranged tools",
                "visual": "a cozy maker desk with simple tools, blank paper shapes, and small prototype parts, visual metaphor for learning by doing",
            },
            {
                "action": "record",
                "subject": "daily journaling",
                "triggers": ("记录", "日记", "小事", "自豪"),
                "include_ip": True,
                "actor_action": "writing in a blank notebook with a pen",
                "visual": "a wooden desk with an open blank notebook, pen, tea cup, and soft window light, no readable writing",
            },
            {
                "action": "reflect_adjust",
                "subject": "reflection and planning",
                "triggers": ("反思", "调整", "目标", "计划"),
                "include_ip": True,
                "actor_action": "arranging blank colored planning cards on a table",
                "visual": "a clean planning desk with blank colored cards, simple calendar shapes without numbers, and a warm lamp",
            },
            {
                "action": "legal_rules",
                "subject": "rules evidence and boundaries",
                "triggers": ("规则", "法律", "合同", "证据", "权益", "责任", "纠纷", "维权", "条款", "借钱", "口头承诺", "签字", "转账"),
                "include_ip": False,
                "actor_action": "",
                "visual": "a simple peaceful anime landscape with a quiet garden path, a low wooden fence marking a clear boundary, a small open gate, smooth stepping stones, calm grass, and soft morning light, visual metaphor for rules, boundaries, safe choices, and a clear process, no indoor room, no wall, no desk, no paper, no document, no book, no signboard, no plaque, no poster, no framed object, no human face",
            },
            {
                "action": "conflict_relationship",
                "subject": "conflict and communication",
                "triggers": ("矛盾", "冲突", "误会", "争执", "分歧", "意见不合", "沟通", "对立"),
                "include_ip": False,
                "actor_action": "",
                "visual": "a calm conversation table with two cups placed apart, two empty chairs facing each other, separated warm and cool light on the tabletop, visual metaphor for conflict, distance, and the possibility of communication",
            },
            {
                "action": "connect",
                "subject": "mutual growth",
                "triggers": ("朋友", "导师", "互相", "启发", "共同成长", "分享"),
                "include_ip": True,
                "actor_action": "sharing tea with a simple friendly silhouette across the table",
                "visual": "a cozy cafe table with two cups, warm window light, and floating abstract idea shapes, no menu and no text",
            },
            {
                "action": "grow",
                "subject": "personal growth",
                "triggers": ("成长", "成为最好的自己", "进步"),
                "include_ip": True,
                "actor_action": "watering a small green plant beside a bright window",
                "visual": "a bright windowsill with a small plant growing in a pot, soft sunlight, calm hopeful mood",
            },
            {
                "action": "think",
                "subject": "philosophical thinking",
                "triggers": ("为什么", "原因", "问题", "怎么", "怎样"),
                "include_ip": False,
                "actor_action": "",
                "visual": "a quiet study corner with a lamp, blank notebook, tea cup, and abstract soft light particles, reflective mood",
            },
        )
        for rule in rules:
            if any(trigger in normalized for trigger in rule["triggers"]):
                return rule

        return {
            "action": "explain",
            "subject": "life philosophy",
            "include_ip": False,
            "actor_action": "",
            "visual": "a warm philosophical presentation background with symbolic blank objects, soft room depth, clean empty space",
        }

    def _ip_subject(self, character: str) -> str:
        raw = (character or "").lower()
        if "fox" in raw or "狐狸" in raw:
            return "a small orange fox mentor mascot figurine inspired by the project original IP, teal vest, cute anime design"
        if "owl" in raw or "猫头鹰" in raw:
            return "a small owl teacher mascot figurine inspired by the project original IP, tiny glasses, cute anime design"
        if "wolf" in raw or "狼" in raw:
            return "a small wolf tech lead mascot figurine inspired by the project original IP, calm cute anime design"
        if "bear" in raw or "熊" in raw:
            return "a small bear product manager mascot figurine inspired by the project original IP, gentle cute anime design"
        return "a small friendly anime mentor mascot figurine inspired by the project original IP"

    def resolve_character(self, character: str) -> CharacterAsset:
        raw = (character or "na1").strip()
        explicit = project_path(raw)
        if explicit.exists():
            if explicit.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
                return CharacterAsset(path=str(explicit), kind="video_chroma")
            return CharacterAsset(path=str(explicit), kind="static")

        for path, kind in self.CHARACTER_CANDIDATES.get(raw, self.CHARACTER_CANDIDATES["na1"]):
            if kind == "sequence":
                first_frame = project_path(path.replace("%06d", "000001"))
                if first_frame.exists():
                    return CharacterAsset(path=str(project_path(path)), kind=kind)
            else:
                candidate = project_path(path)
                if candidate.exists():
                    return CharacterAsset(path=str(candidate), kind=kind)

        raise FileNotFoundError(f"未找到数字人素材: {character}")

    def _create_gradient(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 1080, 1920
        image = Image.new("RGB", (width, height), "#18304f")
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / height
            r = int(24 + 30 * ratio)
            g = int(48 + 65 * ratio)
            b = int(79 + 45 * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        image.save(output_path)

    def _create_anime_background(self, output_path: Path, seed_index: int = 0, cue: str = "", scene_text: str = "") -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 1080, 1920
        palettes = [
            ("#bfe6ff", "#eaf6ff", "#f4e7ca", "#9fc5dd"),
            ("#ffd7c2", "#fff2da", "#e7f0dc", "#d7a7a0"),
            ("#d8e7ff", "#f3f7ff", "#e4e0ff", "#9aa7d8"),
            ("#ccebd8", "#f7f1d8", "#e7d8bd", "#86b99d"),
        ]
        base, light, floor, city = palettes[seed_index % len(palettes)]
        image = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(image)

        # Soft anime sky gradient.
        for y in range(height):
            ratio = y / height
            if ratio < 0.58:
                t = ratio / 0.58
                start = Image.new("RGB", (1, 1), base).getpixel((0, 0))
                end = Image.new("RGB", (1, 1), light).getpixel((0, 0))
            else:
                t = (ratio - 0.58) / 0.42
                start = Image.new("RGB", (1, 1), light).getpixel((0, 0))
                end = Image.new("RGB", (1, 1), floor).getpixel((0, 0))
            r = int(start[0] + (end[0] - start[0]) * t)
            g = int(start[1] + (end[1] - start[1]) * t)
            b = int(start[2] + (end[2] - start[2]) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Distant city silhouettes in a clean anime palette.
        horizon = 1180
        city_colors = [city, "#8ab4d4", "#78a6c9", "#c9b4d8"]
        buildings = [
            (40, 980, 180, horizon), (210, 900, 330, horizon), (380, 1020, 500, horizon),
            (550, 930, 690, horizon), (730, 1010, 840, horizon), (880, 880, 1020, horizon),
        ]
        for idx, rect in enumerate(buildings):
            draw.rectangle(rect, fill=city_colors[idx % len(city_colors)])
            x0, y0, x1, y1 = rect
            for wx in range(x0 + 22, x1 - 20, 36):
                for wy in range(y0 + 34, min(y1 - 40, y0 + 220), 52):
                    draw.rounded_rectangle((wx, wy, wx + 14, wy + 22), radius=3, fill="#eaf7ff")

        # Foreground floor with a slight perspective feel.
        draw.polygon([(0, 1320), (1080, 1230), (1080, 1920), (0, 1920)], fill=floor)
        for i in range(9):
            y = 1320 + i * 78
            draw.line([(0, y), (1080, y - 90)], fill="#dfcda9", width=3)
        for x in range(-280, 1300, 210):
            draw.line([(x, 1920), (x + 410, 1230)], fill="#e6d5b5", width=3)

        self._draw_scene_symbols(draw, self._visual_plan(scene_text)["action"], width, height)

        image.save(output_path)

    def _scene_type(self, text: str) -> str:
        text = text or ""
        if any(word in text for word in ("方向", "选择", "导向", "走这条路", "哪里走")):
            return "path"
        if any(word in text for word in ("信任自己", "内心", "自己", "接纳")):
            return "mirror"
        if any(word in text for word in ("日记", "记录", "想法", "进步")):
            return "journal"
        if any(word in text for word in ("挑战", "成功", "项目", "超出预期")):
            return "mountain"
        if any(word in text for word in ("朋友", "分享", "支持", "目标")):
            return "friends"
        if any(word in text for word in ("学习", "实践", "复习", "知识")):
            return "study"
        return "default"

    def _create_comfy_background(self, prompt: str, output_path: Path, seed: int = 260600) -> bool:
        """调用 ComfyUI (127.0.0.1:8190) 生成动漫背景图。自动启动/关闭 ComfyUI。"""
        import json
        import socket
        import subprocess
        import time
        import urllib.request
        import urllib.parse

        host = settings.COMFYUI_HOST or "127.0.0.1"
        port = int(settings.COMFYUI_PORT or 8190)
        comfy_path = settings.COMFYUI_MAIN_PATH or r"D:\IT\AI_vido\ComfyUI\main.py"
        comfy_main = Path(comfy_path)
        comfy_marker = str(comfy_main).replace("/", "\\").lower()

        def is_port_open(host: str, port: int) -> bool:
            try:
                with socket.create_connection((host, port), timeout=3):
                    return True
            except (socket.timeout, OSError):
                return False

        def wait_for_comfy(max_wait: int = 60) -> bool:
            for _ in range(max_wait):
                if is_comfyui_ready():
                    return True
                time.sleep(2)
            return False

        def is_comfyui_ready() -> bool:
            if not is_port_open(host, port):
                return False
            try:
                with urllib.request.urlopen(f"http://{host}:{port}/system_stats", timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return isinstance(data, dict) and ("system" in data or "devices" in data)
            except Exception:
                return False

        def stop_comfyui_process_by_port() -> None:
            ps_command = (
                f"$conns = Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue; "
                "$conns | ForEach-Object { "
                "$pid = $_.OwningProcess; "
                "$proc = Get-CimInstance Win32_Process -Filter \"ProcessId = $pid\" -ErrorAction SilentlyContinue; "
                f"if ($proc -and $proc.CommandLine -and $proc.CommandLine.Replace('/', '\\').ToLower().Contains('{comfy_marker}')) "
                "{ Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } "
                "}"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_command],
                timeout=15,
                capture_output=True,
            )

        def stop_started_comfy(process: subprocess.Popen | None) -> None:
            if not we_started:
                return
            print("[ComfyUI] 生成流程结束，正在关闭本次启动的 ComfyUI...")
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception as exc:
                        print(f"[ComfyUI] 按 PID 关闭失败: {exc}")

            # 兜底：只清理命令行匹配 ComfyUI main.py 且仍监听当前端口的进程。
            try:
                stop_comfyui_process_by_port()
            except Exception as exc:
                print(f"[ComfyUI] 端口兜底关闭失败: {exc}")

        # 检查 ComfyUI 是否已运行
        we_started = False
        comfy_process = None
        if is_port_open(host, port) and not is_comfyui_ready():
            print(f"[ComfyUI] {host}:{port} 已被非 ComfyUI 服务占用，跳过 ComfyUI 背景生成。")
            return False

        if not is_port_open(host, port):
            print("[ComfyUI] 未运行，正在启动...")
            try:
                comfy_process = subprocess.Popen(
                    ["python", comfy_path, "--enable-cors", "--listen", host, "--port", str(port)],
                    cwd=str(comfy_main.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                we_started = True
            except Exception as e:
                print(f"[ComfyUI] 启动失败: {e}")
                return False

            print("[ComfyUI] 等待服务就绪...")
            if not wait_for_comfy(60):
                print("[ComfyUI] 启动超时")
                stop_started_comfy(comfy_process)
                return False
            print("[ComfyUI] 已就绪")

        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-schnell-fp8.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {
                "text": "text, readable text, unreadable text, pseudo text, fake writing, glyphs, symbols, "
                        "Chinese characters, English letters, numbers, scribbles, decorative strokes, "
                        "sign, poster, frame, logo, watermark, label, book title, document text, "
                        "forms, receipts, paper full of details, filled document pages, wall plaque, hanging plaque, "
                        "calligraphy, certificate, menu board, poster board, framed writing, "
                        "close-up portrait, large animal, extra head, malformed face",
                "clip": ["1", 1]
            }},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1344, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": 4, "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]
            }},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ai_douyin_bg", "images": ["6", 0]}},
        }

        try:
            import uuid
            cid = str(uuid.uuid4())
            data = json.dumps({"prompt": workflow, "client_id": cid}).encode("utf-8")
            req = urllib.request.Request(
                f"http://{host}:{port}/prompt",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=20)
            pid = json.loads(resp.read())["prompt_id"]

            for _ in range(240):
                time.sleep(1)
                hist = json.loads(urllib.request.urlopen(f"http://{host}:{port}/history/{pid}", timeout=10).read())
                if pid in hist:
                    break
            else:
                return False

            item = hist[pid]
            if item.get("status", {}).get("status_str") != "success":
                return False

            images = []
            for node in item.get("outputs", {}).values():
                images.extend(node.get("images", []))
            if not images:
                return False

            img = images[0]
            qs = urllib.parse.urlencode({
                "filename": img["filename"],
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            })
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(
                urllib.request.urlopen(f"http://{host}:{port}/view?{qs}", timeout=30).read()
            )
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False
        finally:
            stop_started_comfy(comfy_process)

    def _draw_scene_symbols(self, draw: ImageDraw.ImageDraw, scene: str, width: int, height: int) -> None:
        top = 350
        if scene in {"choose", "path"}:
            draw.rounded_rectangle((250, 620, 830, 900), radius=28, fill="#f8ecd5", outline="#ba9264", width=8)
            draw.rounded_rectangle((315, 680, 505, 835), radius=18, fill="#dceeff", outline="#6e9dc5", width=6)
            draw.rounded_rectangle((575, 680, 765, 835), radius=18, fill="#ffe2d7", outline="#cf8975", width=6)
            draw.ellipse((500, 505, 580, 585), fill="#ffe7cf", outline="#9b7062", width=5)
        elif scene in {"hesitate", "follow"}:
            draw.rounded_rectangle((380, 440, 700, 920), radius=26, fill="#fff8dc", outline="#b98d5e", width=10)
            draw.rectangle((430, 510, 650, 920), fill="#ffd98f")
            draw.polygon([(470, 1180), (610, 1180), (680, 920), (400, 920)], fill="#fff1bf")
            draw.ellipse((500, 760, 580, 840), fill="#ffd9c8", outline="#9b7062", width=5)
        elif scene in {"trust_self", "mirror"}:
            draw.rounded_rectangle((365, top, 715, 820), radius=42, fill="#edf8ff", outline="#7aa7c7", width=10)
            draw.ellipse((492, 560, 588, 656), fill="#ffd8c7", outline="#995f56", width=5)
            draw.arc((470, 640, 610, 720), 20, 160, fill="#995f56", width=5)
        elif scene in {"record", "journal"}:
            draw.rounded_rectangle((270, 680, 810, 960), radius=24, fill="#fff9e8", outline="#be9d6a", width=8)
            draw.line((540, 690, 540, 950), fill="#e1c99d", width=5)
            for y in range(735, 900, 42):
                draw.line((310, y, 505, y), fill="#cfb98e", width=4)
                draw.line((575, y, 770, y), fill="#cfb98e", width=4)
            draw.line((720, 620, 820, 760), fill="#4b5363", width=12)
        elif scene in {"explore_practice", "mountain", "study"}:
            draw.rounded_rectangle((260, 720, 820, 940), radius=24, fill="#f3dfbd", outline="#9e774f", width=8)
            draw.ellipse((380, 620, 470, 710), fill="#ffd9c8", outline="#9b7062", width=5)
            draw.rectangle((500, 650, 710, 790), fill="#d7e8ff", outline="#6f95bd", width=5)
            draw.line((320, 860, 760, 860), fill="#745139", width=8)
            draw.ellipse((720, 710, 790, 780), fill="#ccebd8", outline="#6d9a76", width=5)
        elif scene in {"reflect_adjust"}:
            draw.rounded_rectangle((250, 620, 830, 940), radius=28, fill="#fff6df", outline="#be9d6a", width=8)
            colors = ["#dceeff", "#ffe2d7", "#e5f4d5", "#eee1ff"]
            for idx, (x, y) in enumerate(((330, 690), (555, 690), (330, 805), (555, 805))):
                draw.rounded_rectangle((x, y, x + 170, y + 82), radius=14, fill=colors[idx], outline="#aa9c88", width=4)
        elif scene in {"connect", "friends"}:
            draw.ellipse((340, 760, 455, 875), fill="#fff0d5", outline="#b08b5e", width=6)
            draw.ellipse((625, 760, 740, 875), fill="#fff0d5", outline="#b08b5e", width=6)
            draw.rounded_rectangle((410, 520, 670, 640), radius=34, fill="#ffffff", outline="#94bad4", width=5)
            draw.polygon([(500, 640), (460, 710), (560, 640)], fill="#ffffff", outline="#94bad4")
        elif scene == "grow":
            draw.rounded_rectangle((455, 805, 625, 980), radius=18, fill="#c68d5f", outline="#875d40", width=6)
            draw.line((540, 805, 540, 610), fill="#5e9b62", width=12)
            draw.ellipse((430, 650, 545, 755), fill="#8acb88", outline="#5e9b62", width=5)
            draw.ellipse((535, 610, 660, 730), fill="#9bdd98", outline="#5e9b62", width=5)
