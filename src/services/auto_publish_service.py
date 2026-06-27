"""
auto_publish_service.py — 一键自动发布服务

完整流水线：
  1. 接收关键字/主题
  2. 本地模型生成脚本（RAG + LLM）
  3. TTS 生成配音
  4. 混 BGM
  5. 视频合成（stream_loop 循环拼接）
  6. 浏览器自动化发布
  7. 发布结果写入数据库
"""

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.content_factory.video_composer import compose_dual_character_sequence_video, compose_video, get_duration
from src.content_factory.presenter_pipeline import PresenterPipeline
from src.content_factory.presenter.models import PresenterRequest
from src.platform_adapter.browser_session import BrowserSession, build_default_browser_session_config
from src.platform_adapter.douyin_adapter import DouyinAdapter
from src.platform_adapter.models import PublishRequest, VideoItem, VideoStatus
from src.services.generation_service import DialogueGenerationRequest, GenerationService, QuickGenerationRequest
from src.services.video_service import save_video, update_video_rag_context
from src.shared.logger import logger


DEFAULT_TEMPLATE_VIDEO = "data/videos/template.mp4"  # 用户自备并放到 data/videos/ 下；不存在时模板视频模式会在合成阶段失败
DEFAULT_BGM_VOLUME = 0.2
VIDEO_MODE_SINGLE_TEMPLATE = "single_template"
VIDEO_MODE_DUAL_FRAMEPACK_ACTIVE = "dual_framepack_active"
VIDEO_MODE_PRESENTER_ANIME = "presenter_anime"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DUAL_BACKGROUND = "data/videos/bg_comfy_green_loop_motion.mp4"
DEFAULT_DUAL_ROLE_A_SEQUENCE = "data/framepack/frames_looped/na1_idle_v1/%06d.png"
DEFAULT_DUAL_ROLE_B_SEQUENCE = "data/framepack/frames_looped/n3_idle_v1/%06d.png"


@dataclass
class AutoPublishRequest:
    """自动发布请求"""
    keywords: str = ""              # 关键字（触发 RAG 生成脚本）
    title: str = ""                # 视频标题（空则自动生成）
    description: str = ""           # 视频描述
    hashtags: List[str] = ""        # 话题标签（可以是逗号分隔字符串或列表）
    template_video: str = ""        # 模板视频路径
    bgm: str = ""                  # BGM 路径（空则用默认）
    bgm_volume: float = DEFAULT_BGM_VOLUME
    tts_provider: str = "edge"     # edge / gpt_sovits，后台默认用 edge 作为稳定兜底
    voice: str = ""                # 声音ID/参考音频
    video_mode: str = VIDEO_MODE_PRESENTER_ANIME  # presenter_anime / dual_framepack_active / single_template
    publish_headless: bool = True   # 自动发布默认后台运行浏览器
    output_dir: str = "data/videos"  # 输出目录
    interactive: bool = False       # 交互模式（每步暂停）
    auto_hashtags: bool = True     # 自动生成话题标签
    visibility: str = "public"     # 可见性：public / private / friends


@dataclass
class AutoPublishResult:
    """自动发布结果"""
    success: bool
    message: str
    video_path: str = ""           # 生成的视频路径
    post_id: str = ""              # 抖音视频ID
    publish_url: str = ""          # 抖音视频链接
    db_video_id: str = ""          # 数据库记录ID


class AutoPublishService:
    """自动发布服务"""

    def __init__(self):
        self.gen_service = GenerationService()
        self.adapter: Optional[DouyinAdapter] = None

    def publish(self, request: AutoPublishRequest) -> AutoPublishResult:
        """
        执行一键自动发布。

        完整流水线：生成 → 合成 → 发布 → 落库
        """
        try:
            # Step 1: 生成内容
            logger.info("=" * 50)
            logger.info("[Step 1/6] 开始生成内容...")
            content = self._generate_content(request)
            if not content:
                return AutoPublishResult(
                    success=False,
                    message=(
                        "内容生成失败：通常是配音阶段失败。"
                        "Edge-TTS 需要联网；GPT-SoVITS 需要本地 torch/GPT-SoVITS 环境完整。"
                        "请展开“最近发布日志”查看具体错误。"
                    ),
                )
            logger.info(f"[OK] 内容生成成功: {content}")

            # Step 2: 视频合成
            logger.info("=" * 50)
            logger.info("[Step 2/6] 开始合成视频...")
            video_path = self._compose_video(request, content)
            if not video_path:
                return AutoPublishResult(success=False, message="视频合成失败")
            logger.info(f"[OK] 视频合成成功: {video_path}")

            # Step 3: 初始化发布适配器
            logger.info("=" * 50)
            logger.info("[Step 3/6] 初始化浏览器...")
            self._init_adapter(request)
            if not self._ensure_authenticated():
                return AutoPublishResult(success=False, message="未检测到登录态，请先运行 python main.py douyin-login")

            # Step 4: 写入数据库（pending状态），发布失败时标记为 failed
            logger.info("=" * 50)
            logger.info("[Step 4/6] 保存到数据库（pending）...")
            db_video_id = self._save_to_database(
                request=request,
                video_path=video_path,
            )
            logger.info(f"[OK] 已写入数据库: local_id={db_video_id}, status=PENDING")

            # Step 5: 发布视频
            logger.info("=" * 50)
            logger.info("[Step 5/6] 开始发布视频...")
            try:
                post_id, publish_url = self._publish_video(request, video_path)
                logger.info(f"[OK] 发布成功: post_id={post_id}, url={publish_url}")
            except Exception as exc:
                # 发布失败，回滚数据库状态为 failed
                logger.warning(f"发布失败，回滚数据库状态: {exc}")
                from src.services.video_service import update_video_status_by_local
                update_video_status_by_local(db_video_id, "failed")
                raise

            # Step 6: RAG 检索 + 写入 rag_context
            logger.info("=" * 50)
            logger.info("[Step 6/6] 更新 RAG 上下文...")
            rag_text = ""
            try:
                from src.rag_engine.wisdom_retriever import WisdomRetriever
                retriever = WisdomRetriever()
                chunks = retriever.search_wisdom(request.keywords or request.title, top_k=3)
                if chunks:
                    rag_text = "\n".join(self._chunk_to_text(c) for c in chunks)
                    logger.info(f"[RAG] 检索到 {len(chunks)} 条知识片段")
            except Exception as exc:
                logger.warning(f"[RAG] 检索失败，跳过: {exc}")

            if rag_text and db_video_id:
                update_video_rag_context(db_video_id, rag_text)

            # 完成
            logger.info("=" * 50)
            logger.info("发布流程完成！")
            logger.info(f"  视频文件: {video_path}")
            logger.info(f"  本地ID: {db_video_id}")
            logger.info(f"  抖音ID: （sync 后补上）")

            return AutoPublishResult(
                success=True,
                message="发布已提交，等待抖音审核/同步",
                video_path=video_path,
                post_id=post_id,
                publish_url=publish_url,
                db_video_id=db_video_id,
            )

        except Exception as exc:
            logger.exception("自动发布流程异常")
            return AutoPublishResult(success=False, message=f"异常: {exc}")
        finally:
            self._close_adapter()

    # ─── 分步实现 ────────────────────────────────────────

    @staticmethod
    def _chunk_to_text(chunk) -> str:
        """兼容 LangChain Document 和旧版 dict 结构。"""
        if hasattr(chunk, "page_content"):
            return chunk.page_content or ""
        if isinstance(chunk, dict):
            return chunk.get("content", "") or chunk.get("page_content", "") or str(chunk)
        return str(chunk)

    def _generate_content(self, request: AutoPublishRequest) -> dict:
        """Step 1: 生成音频内容"""
        if request.video_mode == VIDEO_MODE_DUAL_FRAMEPACK_ACTIVE:
            return self._generate_dual_dialogue_content(request)

        if request.video_mode == VIDEO_MODE_PRESENTER_ANIME:
            script = self.gen_service.resolve_script(
                topic=request.keywords,
                keywords=request.keywords,
                tts_provider=request.tts_provider or "edge",
                voice=request.voice or None,
            )
            return {"mode": VIDEO_MODE_PRESENTER_ANIME, "script": script}

        # 解析 hashtags（支持字符串或列表）
        hashtags = request.hashtags
        if isinstance(hashtags, str):
            hashtags = [h.strip() for h in hashtags.split(",") if h.strip()]

        quick_req = QuickGenerationRequest(
            keywords=request.keywords,
            prompt=request.keywords,
            tts_provider=request.tts_provider or "edge",
            voice=request.voice or None,
            bgm=request.bgm or self.gen_service.default_bgm_path,
            bgm_volume=request.bgm_volume,
            output_dir=request.output_dir,
            keep_temp=False,
        )

        paths = self.gen_service.run_quick_request(quick_req)
        if not paths:
            return {}
        return {
            "mode": VIDEO_MODE_SINGLE_TEMPLATE,
            "audio_path": paths[0],
        }

    def _generate_dual_dialogue_content(self, request: AutoPublishRequest) -> dict:
        """生成双角色对话音频，并返回主动说话时间轴。"""
        dialogue_req = DialogueGenerationRequest(
            topic=request.keywords or request.title,
            keywords=request.keywords,
            use_rag=False,
            tts_provider=request.tts_provider or "edge",
            bgm=None,
            bgm_volume=request.bgm_volume,
            output_dir=request.output_dir,
        )
        result = self.gen_service.run_dialogue_generation(dialogue_req)

        role_a_sources = self._existing_audio_files(result.get("role_a_audio", []))
        role_b_sources = self._existing_audio_files(result.get("role_b_audio", []))
        if not role_a_sources or not role_b_sources:
            logger.error(
                "双角色音频生成失败: role_a=%s, role_b=%s",
                len(role_a_sources),
                len(role_b_sources),
            )
            return {}

        output_dir = self._project_path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        role_a_audio = self._concat_audio_files(role_a_sources, output_dir / f"role_a_dual_{stamp}.wav")
        role_b_audio = self._concat_audio_files(role_b_sources, output_dir / f"role_b_dual_{stamp}.wav")
        if not role_a_audio or not role_b_audio:
            return {}

        role_a_duration = get_duration(role_a_audio)
        role_b_duration = get_duration(role_b_audio)
        if role_a_duration <= 0 or role_b_duration <= 0:
            logger.error("双角色合并音频时长异常: A=%.3f, B=%.3f", role_a_duration, role_b_duration)
            return {}

        if not request.title and result.get("title"):
            request.title = result["title"]

        return {
            "mode": VIDEO_MODE_DUAL_FRAMEPACK_ACTIVE,
            "role_a_audio": role_a_audio,
            "role_b_audio": role_b_audio,
            "active_speaker_timeline": [
                ("A", 0, role_a_duration),
                ("B", role_a_duration, role_a_duration + role_b_duration),
            ],
            "dialogue_title": result.get("title", ""),
            "dialogue_summary": result.get("summary", ""),
        }

    def _compose_video(self, request: AutoPublishRequest, content: dict) -> str:
        """Step 2: 合成视频"""
        if request.video_mode == VIDEO_MODE_DUAL_FRAMEPACK_ACTIVE:
            return self._compose_dual_framepack_active_video(request, content)

        if request.video_mode == VIDEO_MODE_PRESENTER_ANIME:
            return self._compose_presenter_anime_video(request, content)

        audio_path = content.get("audio_path", "")
        if not audio_path:
            return ""

        template = request.template_video or DEFAULT_TEMPLATE_VIDEO
        if not os.path.exists(template):
            raise FileNotFoundError(f"模板视频不存在: {template}")

        output_dir = request.output_dir
        os.makedirs(output_dir, exist_ok=True)

        video_path = compose_video(
            video_clip_path=template,
            audio_path=audio_path,
            output_dir=output_dir,
        )
        return video_path

    def _compose_dual_framepack_active_video(self, request: AutoPublishRequest, content: dict) -> str:
        """合成正式版双角色主动说话视频。"""
        background_path = self._project_path(DEFAULT_DUAL_BACKGROUND)
        role_a_sequence = self._project_path(DEFAULT_DUAL_ROLE_A_SEQUENCE)
        role_b_sequence = self._project_path(DEFAULT_DUAL_ROLE_B_SEQUENCE)

        required_paths = {
            "背景视频": background_path,
            "角色A帧": role_a_sequence.parent / "000001.png",
            "角色B帧": role_b_sequence.parent / "000001.png",
        }
        missing = [f"{label}: {path}" for label, path in required_paths.items() if not path.exists()]
        if missing:
            raise FileNotFoundError("双角色素材缺失: " + "；".join(missing))

        output_name = f"dual_active_{int(time.time() * 1000)}"
        video_path = compose_dual_character_sequence_video(
            background_path=str(background_path),
            role_a_sequence=str(role_a_sequence),
            role_b_sequence=str(role_b_sequence),
            audio_a_path=content["role_a_audio"],
            audio_b_path=content["role_b_audio"],
            bgm_path=request.bgm or None,
            output_dir=str(self._project_path(request.output_dir)),
            output_name=output_name,
            portrait=True,
            role_a_x=0,
            role_a_y=480,
            role_b_x=540,
            role_b_y=480,
            crf=23,
            active_speaker_timeline=content.get("active_speaker_timeline"),
        )
        return video_path

    def _compose_presenter_anime_video(self, request: AutoPublishRequest, content: dict) -> str:
        """合成动漫数字人主讲视频（PresenterPipeline）。"""
        presenter = PresenterPipeline()
        # 优先使用 Sonic 生成的狐狸口型视频（video_chroma 绿幕）
        character_path = (
            "data/ip_characters/_incoming/sonic_test/fox_planner_576_mouthboost_upscale1080_sharp.mp4"
        )
        presenter_req = PresenterRequest(
            keywords=request.keywords or "",
            text=content.get("script", ""),
            title=request.title or request.keywords or "数字人主讲",
            voice=request.voice or "",
            tts_provider=request.tts_provider or "edge",
            character=character_path,
            character_position="right_bottom",
            character_size="medium",
            background="",
            background_style="anime",
            bgm=request.bgm or "",
            output_dir=request.output_dir or "data/videos",
            audio_path="",
            max_segments=16,
        )
        result = presenter.run(presenter_req)
        if not result.success:
            raise RuntimeError(f"动漫数字人视频生成失败: {result.message}")
        return result.video_path

    @staticmethod
    def _existing_audio_files(paths: List[str]) -> List[str]:
        return [str(Path(path)) for path in paths if path and Path(path).exists() and Path(path).stat().st_size > 0]

    @staticmethod
    def _concat_audio_files(paths: List[str], output_path: Path) -> str:
        """用 FFmpeg 重新编码拼接多段角色音频。"""
        if not paths:
            return ""
        if len(paths) == 1:
            return paths[0]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs = []
        labels = []
        for idx, path in enumerate(paths):
            inputs.extend(["-i", path])
            labels.append(f"[{idx}:a]")
        filter_complex = "".join(labels) + f"concat=n={len(paths)}:v=0:a=1[outa]"
        cmd = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outa]",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=300)
        if result.returncode != 0:
            logger.error("角色音频拼接失败: %s", result.stderr[-1000:])
            return ""
        return str(output_path)

    @staticmethod
    def _project_path(path: str) -> Path:
        value = Path(path)
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value

    def _init_adapter(self, request: AutoPublishRequest) -> None:
        """Step 3: 初始化浏览器适配器"""
        session_config = build_default_browser_session_config()
        session_config.headless = bool(request.publish_headless) and not request.interactive
        logger.info(
            "发布浏览器模式: "
            f"{'后台无头' if session_config.headless else '调试可见窗口'} "
            f"(publish_headless={request.publish_headless}, interactive={request.interactive})"
        )
        self.adapter = DouyinAdapter(session=BrowserSession(session_config))

    def _ensure_authenticated(self) -> bool:
        """确保已登录"""
        if self.adapter is None:
            return False
        user_data = self.adapter.session.config.user_data_dir
        from pathlib import Path
        return Path(user_data).exists()

    def _publish_video(self, request: AutoPublishRequest, video_path: str) -> tuple[str, str]:
        """Step 4: 发布视频"""
        if self.adapter is None:
            raise RuntimeError("适配器未初始化")

        # 解析 hashtags
        hashtags = request.hashtags
        if isinstance(hashtags, str):
            hashtags = [h.strip().lstrip("#") for h in hashtags.split(",") if h.strip()]

        # 标题：优先用用户输入的，空则用关键词兜底（UI 提示"空则自动生成"）
        video_title = request.title.strip() if request.title else request.keywords or "自动生成"

        publish_req = PublishRequest(
            video_path=video_path,
            title=video_title,
            description=request.description,
            hashtags=hashtags,
            visibility=getattr(request, "visibility", "public"),
        )

        result = self.adapter.publish_video(publish_req, interactive=request.interactive)

        if not result.success:
            raise RuntimeError(f"发布失败: {result.message}")

        return result.post_id, result.publish_url

    def _save_to_database(
        self,
        request: AutoPublishRequest,
        video_path: str,
    ) -> str:
        """Step 5: 保存到数据库，status=PENDING，等待 sync 后补上 video_id"""
        hashtags = request.hashtags
        if isinstance(hashtags, str):
            hashtags = [h.strip() for h in hashtags.split(",") if h.strip()]

        # 生成描述（包含话题标签）
        description = request.description
        if hashtags and request.auto_hashtags:
            tag_text = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
            description = f"{description} {tag_text}".strip()

        # 发布时 video_id 未知，生成 local_id 用于后续 sync 匹配
        # 标题：与 _publish_video 保持一致（优先用户输入，空则关键词兜底）
        video_title = request.title.strip() if request.title else request.keywords or "自动生成"
        local_id = uuid.uuid4().hex

        video = VideoItem(
            local_id=local_id,
            video_id=None,
            title=video_title,
            description=description,
            status=VideoStatus.PENDING,
            publish_time=datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            cover_url=None,
            stats=None,
        )

        save_video(video)
        logger.info(f"[OK] 已保存到数据库: local_id={local_id}, status=PENDING")
        return local_id

    def _close_adapter(self) -> None:
        """关闭适配器"""
        if self.adapter:
            try:
                self.adapter.close()
            except Exception as exc:
                logger.debug(f"关闭 adapter 失败: {exc}")
            self.adapter = None
