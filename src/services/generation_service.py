import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from src.content_factory.audio_mixer import AudioMixer
from src.content_factory.dialogue_generator import DialogueGenerator
from src.content_factory.script_generator import ScriptGenerator
from src.content_factory.tts_engine import TTSEngine
from src.shared.config import settings
from src.shared.logger import logger
from src.shared.output_manager import finalize_output


@dataclass
class GenerationRequest:
    book: Optional[str] = None
    topic: Optional[str] = None
    text: Optional[str] = None
    tts_provider: str = "edge"
    voice: Optional[str] = None
    bgm: Optional[str] = None
    bgm_volume: float = 0.2
    no_merge: bool = False
    keywords: str = ""
    emotion_type: str = ""
    positive_energy_type: str = ""
    target_audience: str = ""
    output_dir: Optional[str] = None
    keep_temp: bool = False


@dataclass
class QuickGenerationRequest:
    prompt: Optional[str] = None
    text: Optional[str] = None
    tts_provider: str = "edge"
    voice: Optional[str] = None
    count: int = 1
    bgm: Optional[str] = None
    bgm_volume: float = 0.2
    output_dir: Optional[str] = None
    keep_temp: bool = False
    no_merge: bool = False
    keywords: str = ""
    emotion_type: str = ""
    positive_energy_type: str = ""
    target_audience: str = ""


@dataclass
class KnowledgeImportRequest:
    books_dir: str


@dataclass
class DialogueGenerationRequest:
    topic: str = ""
    keywords: str = ""
    use_rag: bool = True
    emotion_type: str = ""
    positive_energy_type: str = ""
    target_audience: str = ""
    tts_provider: str = "edge"  # 双角色默认用 Edge-TTS
    bgm: Optional[str] = None
    bgm_volume: float = 0.2
    output_dir: Optional[str] = None


@dataclass
class GenerationResult:
    audio_paths: List[str]
    script_content: str
    source_mode: str
    topic_label: str = ""
    archived_paths: List[str] = field(default_factory=list)


class GenerationService:
    def __init__(self):
        self.default_bgm_path = settings.DEFAULT_BGM_PATH
        self.default_books_dir = settings.BOOKS_DIR
        self.default_chroma_dir = settings.CHROMA_PERSIST_DIR

    def build_generation_request_from_namespace(self, args) -> GenerationRequest:
        return GenerationRequest(
            book=getattr(args, "book", None),
            topic=getattr(args, "topic", None),
            text=getattr(args, "text", None),
            tts_provider=getattr(args, "tts_provider", "edge"),
            voice=getattr(args, "voice", None),
            bgm=getattr(args, "bgm", None),
            bgm_volume=getattr(args, "bgm_volume", 0.2),
            no_merge=getattr(args, "no_merge", False),
            keywords=getattr(args, "keywords", ""),
            emotion_type=getattr(args, "emotion_type", ""),
            positive_energy_type=getattr(args, "positive_energy_type", ""),
            target_audience=getattr(args, "target_audience", ""),
            output_dir=getattr(args, "output_dir", None),
            keep_temp=getattr(args, "keep_temp", False),
        )

    def build_quick_request_from_namespace(self, args) -> QuickGenerationRequest:
        return QuickGenerationRequest(
            prompt=getattr(args, "prompt", None),
            text=getattr(args, "text", None),
            tts_provider=getattr(args, "tts_provider", "edge"),
            voice=getattr(args, "voice", None),
            count=getattr(args, "count", 1),
            bgm=getattr(args, "bgm", None),
            bgm_volume=getattr(args, "bgm_volume", 0.2),
            output_dir=getattr(args, "output_dir", None),
            keep_temp=getattr(args, "keep_temp", False),
            no_merge=getattr(args, "no_merge", False),
            keywords=getattr(args, "keywords", ""),
            emotion_type=getattr(args, "emotion_type", ""),
            positive_energy_type=getattr(args, "positive_energy_type", ""),
            target_audience=getattr(args, "target_audience", ""),
        )

    def generate_from_text(self, text: str, **kwargs) -> Optional[GenerationResult]:
        request = GenerationRequest(text=text, **kwargs)
        return self.generate_from_request(request)

    def generate_from_topic(self, topic: str, **kwargs) -> Optional[GenerationResult]:
        request = GenerationRequest(topic=topic, **kwargs)
        return self.generate_from_request(request)

    def run_batch_generation(self, request: GenerationRequest, count: int = 1) -> List[GenerationResult]:
        results: List[GenerationResult] = []
        total = max(1, count)

        for index in range(total):
            logger.info(f"--- Generating Audio {index + 1}/{total} ---")
            result = self.generate_from_request(request)
            if result:
                results.append(result)

        return results

    def generate_from_request(self, request: GenerationRequest) -> Optional[GenerationResult]:
        logger.info("=== Starting Video Generation Pipeline ===")

        script_content, source_mode = self._resolve_script_content(request)
        if not script_content:
            return None

        audio_paths = self._synthesize_audio(request, script_content)
        if not audio_paths:
            logger.error("Pipeline failed at TTS stage.")
            return None

        if request.bgm:
            logger.info(f"[Step 5] Mixing BGM: {request.bgm}")
            audio_paths = self._mix_background_music(audio_paths, request.bgm, request.bgm_volume)

        logger.info(f"Pipeline Success! Audio saved to: {audio_paths}")
        return GenerationResult(
            audio_paths=audio_paths,
            script_content=script_content,
            source_mode=source_mode,
            topic_label=self._determine_topic_label(request),
        )

    def run_quick_request(self, request: QuickGenerationRequest) -> List[str]:
        if not request.text and not request.prompt and not request.keywords:
            raise ValueError("quick generation requires prompt, keywords, or text")

        final_paths: List[str] = []
        total = max(1, request.count)

        for index in range(total):
            logger.info(f"--- Quick Generating {index + 1}/{total} ---")

            single_request = GenerationRequest(
                topic=request.prompt or request.keywords,
                text=request.text,
                tts_provider=request.tts_provider,
                voice=request.voice,
                bgm=self._resolve_bgm_path(request.bgm),
                bgm_volume=request.bgm_volume,
                no_merge=request.no_merge,
                keywords=request.keywords,
                emotion_type=request.emotion_type,
                positive_energy_type=request.positive_energy_type,
                target_audience=request.target_audience,
                output_dir=request.output_dir,
                keep_temp=request.keep_temp,
            )

            result = self.generate_from_request(single_request)
            if not result:
                logger.error("Quick pipeline failed to generate audio.")
                continue

            base_topic = self._determine_quick_topic_label(request)
            archived_paths = self._archive_outputs(
                audio_paths=result.audio_paths,
                output_dir=request.output_dir,
                topic=base_topic,
                provider=request.tts_provider,
                keep_temp=request.keep_temp,
            )
            result.archived_paths = archived_paths
            final_paths.extend(archived_paths)

        return final_paths

    def import_knowledge_base(self, request: KnowledgeImportRequest) -> bool:
        from src.rag_engine.knowledge_importer import KnowledgeImporter

        books_dir = os.path.abspath(request.books_dir or self.default_books_dir)
        if not os.path.exists(books_dir):
            logger.error(f"Books directory not found: {books_dir}")
            return False

        importer = KnowledgeImporter(persist_dir=self.default_chroma_dir)
        importer.import_books(books_dir)
        logger.info(f"Knowledge import completed for: {books_dir}")
        return True

    def run_dialogue_generation(self, request: DialogueGenerationRequest) -> dict:
        """
        生成双角色对话：RAG检索 → 对话脚本 → TTS音频分割 → 返回结构化结果

        Returns:
            {
                "dialogue": [{"speaker": "A/B", "text": "..."}, ...],
                "title": "...",
                "summary": "...",
                "role_a_audio": [...],
                "role_b_audio": [...],
            }
        """
        logger.info("=== Starting Dual-Character Dialogue Pipeline ===")

        # Step 1: RAG 检索
        wisdom_data = {}
        context = ""
        if request.topic and request.use_rag:
            logger.info(f"[Step 1] RAG Mode: Searching wisdom for '{request.topic}'...")
            from src.rag_engine.wisdom_retriever import WisdomRetriever
            from src.content_factory.wisdom_extractor_rag import WisdomExtractorRAG

            retriever = WisdomRetriever()
            chunks = retriever.search_wisdom(request.topic, top_k=3)
            if chunks:
                rag_extractor = WisdomExtractorRAG()
                wisdom_data = rag_extractor.extract_wisdom(request.topic, chunks)
                context = "\n".join([c.get("content", "") for c in chunks])

        if not wisdom_data:
            logger.warning("No RAG results, using topic as search")
            wisdom_data = {
                "title": request.topic or request.keywords,
                "core_message": request.topic or request.keywords,
                "quote": "",
                "elaboration": "",
                "actionable": "",
            }

        # Step 2: 生成对话脚本
        logger.info("[Step 2] Generating dialogue script...")
        dialogue_gen = DialogueGenerator()
        dialogue_result = dialogue_gen.generate_dialogue(wisdom_data, context=context)

        # Step 3: 分割并生成 TTS 音频
        logger.info("[Step 3] Splitting dialogue and generating TTS audio...")
        split = dialogue_gen.split_by_speaker(dialogue_result)

        tts = TTSEngine(provider_type=request.tts_provider)

        role_a_audios = []
        for i, text in enumerate(split["role_a"]):
            filename = f"role_a_{i}_{int(time.time() * 1000)}.wav"
            path = tts.generate_audio(
                text=text,
                filename=filename,
                voice=split["role_a_voice"],
                rate=split["role_a_rate"],
            )
            if path:
                role_a_audios.append(path)

        role_b_audios = []
        for i, text in enumerate(split["role_b"]):
            filename = f"role_b_{i}_{int(time.time() * 1000)}.wav"
            path = tts.generate_audio(
                text=text,
                filename=filename,
                voice=split["role_b_voice"],
                rate=split["role_b_rate"],
            )
            if path:
                role_b_audios.append(path)

        logger.info(f"Role A: {len(role_a_audios)} audio files | Role B: {len(role_b_audios)} audio files")

        # Step 4: BGM 混音（可选）
        bgm_path = self._resolve_bgm_path(request.bgm)
        if bgm_path and role_a_audios and role_b_audios:
            logger.info("[Step 4] Mixing BGM...")
            mixer = AudioMixer()
            # 合并所有音频后再混 BGM
            # 这里简化处理，混第一段即可
            role_a_audios = [
                mixer.mix_audio(p, bgm_path, f"{os.path.splitext(p)[0]}_mixed.mp3", request.bgm_volume)
                or p for p in role_a_audios
            ]

        logger.info("Dialogue pipeline completed!")
        return {
            "dialogue": dialogue_result.get("dialogue", []),
            "title": dialogue_result.get("title", ""),
            "summary": dialogue_result.get("summary", ""),
            "role_a_audio": role_a_audios,
            "role_b_audio": role_b_audios,
            "role_a_voice": split["role_a_voice"],
            "role_b_voice": split["role_b_voice"],
        }

    # Backward-compatible wrappers for existing scripts.
    def generate_audio_pipeline(self, args):
        request = self.build_generation_request_from_namespace(args)
        result = self.generate_from_request(request)
        if not result:
            return None
        if len(result.audio_paths) == 1:
            return result.audio_paths[0]
        return result.audio_paths

    def run_quick_pipeline(self, args):
        request = self.build_quick_request_from_namespace(args)
        return self.run_quick_request(request)

    def _resolve_script_content(self, request: GenerationRequest):
        script_content = ""

        if request.text:
            logger.info("[Step 0] Direct Text Mode Activated")
            return request.text, "direct_text"

        wisdom = None

        if request.topic:
            logger.info(f"[Step 1] RAG Mode: Searching wisdom for topic '{request.topic}'...")
            from src.rag_engine.wisdom_retriever import WisdomRetriever

            try:
                retriever = WisdomRetriever()
                chunks = retriever.search_wisdom(request.topic, top_k=3)
            except Exception as exc:
                logger.warning(f"RAG retriever unavailable, falling back to random extraction with keyword hints: {exc}")
                chunks = []

            if not chunks:
                logger.warning("No relevant chunks found. Falling back to keyword-only wisdom.")
                wisdom = self._build_keyword_wisdom(request)
            else:
                logger.info(f"[Step 2] RAG Mode: Extracting wisdom from {len(chunks)} chunks...")
                from src.content_factory.wisdom_extractor_rag import WisdomExtractorRAG

                rag_extractor = WisdomExtractorRAG()
                wisdom = rag_extractor.extract_wisdom(request.topic, chunks)

        if not wisdom:
            logger.info("[Step 1] Random Mode: Reading Book...")
            from src.content_factory.book_processor import BookProcessor
            from src.content_factory.wisdom_extractor import WisdomExtractor

            book_proc = BookProcessor()
            chunk = book_proc.read_random_chunk(book_name=request.book)

            if not chunk:
                logger.error("Failed to read book chunk.")
                return None, "failed"

            logger.info(f"Book: {chunk['book_name']}")
            logger.info("[Step 2] Random Mode: Extracting Wisdom...")
            extractor = WisdomExtractor()
            wisdom = extractor.extract_wisdom(chunk["content"])

        if not wisdom:
            logger.error("Failed to extract wisdom.")
            return None, "failed"

        logger.info(f"Wisdom Title: {wisdom.get('title')}")
        logger.info("[Step 3] Generating Script...")
        script_gen = ScriptGenerator()
        script_data = script_gen.generate_script(wisdom, generation_hints=self._build_generation_hints(request))

        if not script_data:
            logger.error("Failed to generate script.")
            return None, "failed"

        script_content = script_data.get("script_content", "")
        logger.info("Script generated.")
        return script_content, "rag" if request.topic else "random_book"

    def resolve_script(self, topic: str = "", keywords: str = "", tts_provider: str = "edge", voice: Optional[str] = None) -> str:
        """公开接口：通过 RAG + LLM 生成脚本文本。"""
        request = GenerationRequest(
            topic=topic,
            keywords=keywords,
            tts_provider=tts_provider,
            voice=voice,
        )
        script, _source = self._resolve_script_content(request)
        return (script or "").strip()

    def _build_generation_hints(self, request: GenerationRequest):
        return {
            "keywords": request.keywords,
            "emotion_type": request.emotion_type,
            "positive_energy_type": request.positive_energy_type,
            "target_audience": request.target_audience,
        }

    def _build_keyword_wisdom(self, request: GenerationRequest) -> dict:
        keyword_text = request.keywords or request.topic or "人生智慧"
        return {
            "title": keyword_text,
            "core_message": f"围绕{keyword_text}，用具体生活场景说明边界、选择和行动方法。",
            "quote": "",
            "elaboration": f"不要引用随机书籍内容，直接围绕用户关键词{keyword_text}展开，先给真实生活痛点，再说明原因和解决方法。",
            "actionable": "给出今天就能执行的三个小动作，要求具体、可验证、低门槛。",
            "scene": "日常生活和工作场景",
            "emotion": request.emotion_type or "冷静、清醒、有安全感",
        }

    def _synthesize_audio(self, request: GenerationRequest, script_content: str) -> List[str]:
        logger.info("[Step 4] Synthesizing Audio...")
        tts = TTSEngine(provider_type=request.tts_provider)
        extension = "wav" if request.tts_provider == "gpt_sovits" else "mp3"
        audio_filename = f"output_{int(time.time() * 1000)}.{extension}"

        tts_kwargs = {}
        if request.no_merge:
            tts_kwargs["no_merge"] = True

        audio_output = tts.generate_audio(
            text=script_content,
            filename=audio_filename,
            voice=request.voice,
            **tts_kwargs,
        )
        return self._normalize_audio_paths(audio_output)

    def _mix_background_music(self, audio_paths: List[str], bgm_path: str, bgm_volume: float) -> List[str]:
        mixer = AudioMixer()
        mixed_paths: List[str] = []

        for path in audio_paths:
            mixed_path = f"{os.path.splitext(path)[0]}_mixed.mp3"
            final_path = mixer.mix_audio(path, bgm_path, mixed_path, bgm_volume=bgm_volume)
            if final_path:
                mixed_paths.append(final_path)
            else:
                logger.warning(f"BGM mixing failed for {path}, using original.")
                mixed_paths.append(path)

        return mixed_paths

    def _archive_outputs(self, audio_paths: List[str], output_dir: Optional[str], topic: str, provider: str, keep_temp: bool) -> List[str]:
        final_paths: List[str] = []

        for index, path in enumerate(audio_paths):
            topic_label = topic if len(audio_paths) == 1 else f"{topic}_{index + 1}"
            archived_path = finalize_output(
                source_path=path,
                output_dir=output_dir,
                topic=topic_label,
                provider=provider,
                keep_temp=keep_temp,
            )
            if archived_path:
                final_paths.append(archived_path)
                logger.info(f"Archived output {index + 1}: {archived_path}")

        return final_paths

    def _normalize_audio_paths(self, audio_output) -> List[str]:
        if not audio_output:
            return []
        if isinstance(audio_output, list):
            return audio_output
        return [audio_output]

    def _resolve_bgm_path(self, bgm_value: Optional[str]) -> Optional[str]:
        if bgm_value:
            return bgm_value
        if os.path.exists(self.default_bgm_path):
            return self.default_bgm_path
        return None

    def _determine_quick_topic_label(self, request: QuickGenerationRequest) -> str:
        if request.prompt:
            return request.prompt
        if request.keywords:
            return request.keywords
        if request.text:
            return request.text[:10]
        return "unknown"

    def _determine_topic_label(self, request: GenerationRequest) -> str:
        if request.topic:
            return request.topic
        if request.keywords:
            return request.keywords
        if request.text:
            return request.text[:10]
        if request.book:
            return request.book
        return "unknown"
