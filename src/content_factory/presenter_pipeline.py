import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from src.content_factory.presenter.background_resolver import BackgroundResolver, project_path
from src.content_factory.presenter.models import (
    INPUT_MODE_ARTICLE_DIRECT,
    INPUT_MODE_ARTICLE_EXTRACT,
    INPUT_MODE_KEYWORDS,
    PresenterRequest,
    PresenterResult,
)
from src.content_factory.presenter.presenter_composer import PresenterComposer
from src.content_factory.presenter.script_segmenter import ScriptSegmenter
from src.content_factory.presenter.text_overlay import TextOverlayRenderer
from src.content_factory.tts_engine import TTSEngine
from src.content_factory.video_composer import get_duration
from src.services.generation_service import GenerationRequest, GenerationService
from src.shared.llm_client import llm_client
from src.shared.logger import logger


class PresenterPipeline:
    def __init__(self):
        self.generation_service = GenerationService()
        self.resolver = BackgroundResolver()
        self.overlay_renderer = TextOverlayRenderer()
        self.composer = PresenterComposer()

    def run(self, request: PresenterRequest) -> PresenterResult:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        work_dir = project_path("data/presenter") / stamp
        audio_dir = work_dir / "audio"
        text_dir = work_dir / "text_layers"
        clips_dir = work_dir / "clips"
        final_dir = work_dir / "final"
        for directory in (audio_dir, text_dir, clips_dir, final_dir):
            directory.mkdir(parents=True, exist_ok=True)

        try:
            script = self._resolve_script(request)
            if not script:
                return PresenterResult(False, "脚本为空", work_dir=str(work_dir))

            title = request.title or request.keywords or "数字人主讲"
            segmenter = ScriptSegmenter(max_segments=request.max_segments)
            segments = segmenter.split(script, title=title)
            if not segments:
                return PresenterResult(False, "脚本分段失败", work_dir=str(work_dir))

            character = self.resolver.resolve_character(request.character)

            self._write_text(work_dir / "script.txt", script)
            self._write_json(work_dir / "request.json", asdict(request))

            if request.audio_path:
                segments = segments[:1]
                audio_path = str(project_path(request.audio_path))
                if not Path(audio_path).exists():
                    raise FileNotFoundError(f"指定音频不存在: {audio_path}")
                segments[0].audio_path = audio_path
                segments[0].duration = get_duration(audio_path)
            else:
                self._synthesize_segments(request, segments, audio_dir)

            backgrounds = self.resolver.resolve_segment_backgrounds(
                request.background,
                work_dir,
                segments,
                style=request.background_style,
                switch_seconds=5.0,
                character=request.character,
                use_comfy=request.use_comfy_background,
            )

            for idx, segment in enumerate(segments):
                segment.background_path = backgrounds[idx]
                if idx > 0 and segment.background_path == segments[idx - 1].background_path:
                    segment.background_group = segments[idx - 1].background_group
                else:
                    segment.background_group = 0 if idx == 0 else segments[idx - 1].background_group + 1
                segment.text_layer_path = self.overlay_renderer.render(
                    segment=segment,
                    title=title,
                    output_path=text_dir / f"seg_{segment.index:03d}.png",
                    character_position=request.character_position,
                    character_size=request.character_size,
                )
                segment.clip_path = self.composer.compose_segment(
                    segment=segment,
                    background_path=segment.background_path,
                    character=character,
                    output_path=clips_dir / f"seg_{segment.index:03d}.mp4",
                    character_position=request.character_position,
                    character_size=request.character_size,
                )

            self._write_json(work_dir / "segments.json", [asdict(segment) for segment in segments])

            final_name = f"presenter_{stamp}.mp4"
            final_path = final_dir / final_name
            bgm_path = str(project_path(request.bgm)) if request.bgm else ""
            self.composer.concatenate(segments, final_path, bgm_path=bgm_path)

            output_dir = project_path(request.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            publish_path = output_dir / final_name
            if publish_path != final_path:
                publish_path.write_bytes(final_path.read_bytes())

            return PresenterResult(
                success=True,
                message="数字人主讲视频生成完成",
                video_path=str(publish_path),
                work_dir=str(work_dir),
                segments=segments,
            )
        except Exception as exc:
            logger.exception("Presenter pipeline failed")
            return PresenterResult(False, f"异常: {exc}", work_dir=str(work_dir))

    def run_assets_preview(self, request: PresenterRequest) -> PresenterResult:
        """生成脚本文字、分段音频、背景图和构图元数据，只跳过最终视频合成。"""
        stamp = time.strftime("%Y%m%d_%H%M%S")
        work_dir = project_path("data/presenter_assets") / stamp
        audio_dir = work_dir / "audio"
        backgrounds_dir = work_dir / "backgrounds"
        for directory in (audio_dir, backgrounds_dir):
            directory.mkdir(parents=True, exist_ok=True)

        try:
            script = self._resolve_script(request)
            if not script:
                return PresenterResult(False, "脚本为空", work_dir=str(work_dir))

            title = request.title or request.keywords or "数字人主讲"
            segmenter = ScriptSegmenter(max_segments=request.max_segments)
            segments = segmenter.split(script, title=title)
            if not segments:
                return PresenterResult(False, "脚本分段失败", work_dir=str(work_dir))

            self._write_text(work_dir / "script.txt", script)
            self._write_json(work_dir / "request.json", asdict(request))

            if request.audio_path:
                segments = segments[:1]
                audio_path = str(project_path(request.audio_path))
                if not Path(audio_path).exists():
                    raise FileNotFoundError(f"指定音频不存在: {audio_path}")
                segments[0].audio_path = audio_path
                segments[0].duration = get_duration(audio_path)
            else:
                self._synthesize_segments(request, segments, audio_dir)

            backgrounds = self.resolver.resolve_segment_backgrounds(
                request.background,
                work_dir,
                segments,
                style=request.background_style,
                switch_seconds=5.0,
                character=request.character,
                use_comfy=request.use_comfy_background,
            )
            for idx, segment in enumerate(segments):
                segment.background_path = backgrounds[idx]
                if idx > 0 and segment.background_path == segments[idx - 1].background_path:
                    segment.background_group = segments[idx - 1].background_group
                else:
                    segment.background_group = 0 if idx == 0 else segments[idx - 1].background_group + 1

            self._write_json(work_dir / "segments.json", [asdict(segment) for segment in segments])
            return PresenterResult(
                success=True,
                message="数字人文字和背景图预览生成完成",
                work_dir=str(work_dir),
                segments=segments,
            )
        except Exception as exc:
            logger.exception("Presenter assets preview failed")
            return PresenterResult(False, f"异常: {exc}", work_dir=str(work_dir))

    def _resolve_script(self, request: PresenterRequest) -> str:
        input_mode = request.input_mode or INPUT_MODE_KEYWORDS
        input_text = self._load_input_text(request)

        if input_mode == INPUT_MODE_ARTICLE_DIRECT:
            return self._clean_direct_article(input_text)

        if input_mode == INPUT_MODE_ARTICLE_EXTRACT:
            return self._extract_article_script(input_text, request)

        if input_text and not request.keywords:
            return self._clean_direct_article(input_text)

        gen_request = GenerationRequest(
            topic=request.keywords,
            keywords=request.keywords,
            tts_provider=request.tts_provider,
            voice=request.voice or None,
        )
        script, _source = self.generation_service._resolve_script_content(gen_request)
        return (script or "").strip()

    def _load_input_text(self, request: PresenterRequest) -> str:
        if request.text_file:
            path = project_path(request.text_file)
            if not path.exists():
                raise FileNotFoundError(f"文章文件不存在: {path}")
            return path.read_text(encoding="utf-8").strip()
        return (request.text or "").strip()

    def _clean_direct_article(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.replace("\ufeff", "")
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        cleaned = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"(关注|点赞|评论|转发|收藏|一键三连)[^。！？!?\n]*[。！？!?]?", "", cleaned)
        return cleaned.strip()

    def _extract_article_script(self, text: str, request: PresenterRequest) -> str:
        article = self._clean_direct_article(text)
        if not article:
            return ""
        max_chars = 8000
        if len(article) > max_chars:
            logger.warning(f"文章过长，仅使用前 {max_chars} 字进行提炼。")
            article = article[:max_chars]

        template_path = project_path("docs/prompts/article-to-presenter-script.txt")
        if template_path.exists():
            template = template_path.read_text(encoding="utf-8")
        else:
            template = """请把下面文章提炼成60-90秒中文短视频口播稿。
要求：保留核心观点，开头从具体生活场景切入，不要逐段复述，不要关注点赞引导。
输出JSON：{{"title":"","script_content":"","visual_cues":[],"bgm_suggestion":""}}

标题：{title}
关键词：{keywords}
文章：
{article}
"""

        prompt = (
            template.replace("{title}", request.title or request.keywords or "")
            .replace("{keywords}", request.keywords or request.title or "")
            .replace("{article}", article)
        )
        messages = [
            {"role": "system", "content": "你是短视频口播稿编辑。必须忠于原文核心观点，只输出JSON，不要输出Markdown。"},
            {"role": "user", "content": prompt},
        ]
        response_text = llm_client.chat_completion(messages, temperature=0.45, json_mode=True)
        if not response_text:
            raise RuntimeError("文章提炼失败：LLM 无返回")

        cleaned = response_text.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"文章提炼失败：JSON 解析失败: {exc}") from exc

        script = data.get("script_content") or data.get("content") or data.get("script") or ""
        if isinstance(script, list):
            script = "".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in script)
        script = self._clean_direct_article(str(script))
        if not script:
            raise RuntimeError("文章提炼失败：返回内容缺少 script_content")
        return script

    def _synthesize_segments(self, request: PresenterRequest, segments, audio_dir: Path) -> None:
        tts = TTSEngine(output_dir=str(audio_dir), provider_type=request.tts_provider)
        extension = "wav" if request.tts_provider == "gpt_sovits" else "mp3"

        def try_generate(seg, attempt):
            filename = f"seg_{seg.index:03d}.{extension}"
            return tts.generate_audio(seg.text, filename=filename, voice=request.voice or None)

        for segment in segments:
            audio_path = None
            for attempt in range(1, 4):
                audio_path = try_generate(segment, attempt)
                if audio_path:
                    break
                logger.warning(f"TTS segment {segment.index} attempt {attempt} failed, retrying...")
                time.sleep(2)

            if not audio_path:
                raise RuntimeError(f"TTS 失败: segment {segment.index}")
            segment.audio_path = audio_path
            segment.duration = get_duration(audio_path)
            if segment.duration <= 0:
                raise RuntimeError(f"无法读取 TTS 音频时长: {audio_path}")

    def _write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
