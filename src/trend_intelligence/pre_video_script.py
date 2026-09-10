"""Mine high-traffic overlap and expand it into a model-ready shot script.

The public artifact is deliberately script-only. Source videos, relative
traffic selection and overlap evidence are retained in a separate audit file.
Source-media analysis must cover the selected batch before script generation.
Titles are retrieval metadata; the writer receives observed audiovisual
expression and its evidence, not an invented substitute for unseen videos.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from src.operations_accounts import AccountProfile, AccountProfileRepository
from src.trend_intelligence.models import (
    ContentOpportunity,
    TrendObservation,
    VideoContentAnalysis,
)
from src.trend_intelligence.repository import TrendRepository
from .sample_gate import batch_observations, require_sample, primary_tag, MIN_VIDEOS
from .media_evidence import (media_readiness, batch_media_readiness,
    SourceMediaGateError, build_expression_patterns)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAFE_VIDEO_TYPE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

LEGAL_SCOPE_ALIASES = {
    "婚姻家事": ("婚姻", "离婚", "夫妻", "抚养", "亲生", "公婆", "小三", "孩子"),
    "劳动争议": ("劳动", "工资", "加班", "工伤", "辞退", "旷工", "解除合同", "老板", "员工"),
    "合同纠纷": ("合同", "违约", "合作方", "履行", "定金"),
    "债权债务": ("债权", "债务", "欠款", "借款", "还款", "欠钱", "借钱"),
    "交通事故": ("交通事故", "车祸", "事故责任", "交通赔偿", "撞车"),
}

NARRATIVE_DEVICE_TERMS = {
    "具体人物关系": ("夫妻", "孩子", "父母", "亲戚", "老板", "员工", "邻居", "合作方", "朋友"),
    "数字或期限制造风险感": ("万", "元", "年", "天", "小时", "一千", "一万", "二十"),
    "意外后果或反转": ("却", "没想到", "竟", "居然", "反而", "才发现", "转头", "结果"),
    "证据或材料揭示": ("证据", "聊天", "转账", "合同", "通知", "记录", "报告", "账单"),
    "冲突事实先行": ("被骗", "辞退", "旷工", "欠钱", "受伤", "离婚", "销户", "起诉", "赔偿"),
}

MEDIA_DIMENSION_TERMS = {
    "scene": {
        "办公室/咨询室": ("办公室", "咨询室", "律所"),
        "家庭室内": ("客厅", "卧室", "家中", "餐桌"),
        "工作场所": ("工位", "公司", "工厂", "店内"),
        "街头/户外": ("街头", "街道", "路边", "户外"),
    },
    "character": {
        "当事人与专业人士": ("当事人", "律师", "咨询者"),
        "家庭关系人物": ("夫妻", "父亲", "母亲", "孩子", "老人"),
        "劳动关系人物": ("老板", "员工", "劳动者", "主管"),
    },
    "action": {
        "展示关键材料": ("展示", "递出", "推向", "翻开", "举起", "拿出"),
        "查看手机或文件": ("手机", "文件", "报告", "合同", "聊天记录"),
        "面对面对话": ("对话", "交谈", "咨询", "询问"),
    },
    "emotion": {
        "震惊/错愕": ("震惊", "错愕", "愣住"),
        "焦虑/慌张": ("焦虑", "慌张", "不安", "紧张"),
        "克制/冷静": ("克制", "冷静", "平静", "沉稳"),
        "愤怒/委屈": ("愤怒", "生气", "委屈", "不甘"),
    },
    "language": {
        "问题式对白": ("？", "吗", "怎么办", "能不能", "怎么"),
        "短句结论式表达": ("先", "再", "不一定", "关键", "证据"),
    },
}

STYLE = "现实主义电影质感的竖屏剧情短片，克制表演，自然光，真实皮肤和材质"
NEGATIVE_CONSTRAINTS = (
    "不要多人脸融合、身份漂移、服装变化、多余肢体、手指畸形、道具穿模、"
    "动作循环、瞬移、表情突变、背景闪烁、画面抖动、口型与声音不同步、"
    "音频爆音、重复对白、额外文字、水印或平台标志。禁止旁白、解说配音和内心独白。"
)


@dataclass(frozen=True, slots=True)
class PreVideoScriptRequest:
    account_key: str
    recent_video_types: tuple[str, ...]
    window_days: int | None = None
    min_relevance: float = 50.0
    max_source_videos: int = 20
    high_traffic_percentile: float = 0.70
    variant_id: str = "A"
    output_dir: str = "data/pre_video_scripts"
    short_seconds: int = 45
    long_seconds: int = 180
    collection_run_id: str = ""
    editor_feedback: str = ""
    initial_draft_path: str = ""
    revision_feedback: str = ""
    initial_revision_path: str = ""
    baseline_draft_path: str = ""
    continuous_short: bool = False
    review_only: bool = False
    script_reference_source_ids: tuple[str, ...] = ()
    staged_screenplay_bundle_path: str = ''

    def __post_init__(self) -> None:
        account_key = str(self.account_key or "").strip()
        if not account_key:
            raise ValueError("account_key is required")
        normalized = tuple(
            dict.fromkeys(str(value or "").strip().lower() for value in self.recent_video_types)
        )
        if not normalized or any(not SAFE_VIDEO_TYPE.fullmatch(value) for value in normalized):
            raise ValueError("recent_video_types must contain valid analysis type IDs")
        if self.window_days is not None and not 1 <= int(self.window_days) <= 30:
            raise ValueError("window_days must be between 1 and 30")
        if not 0 <= float(self.min_relevance) <= 100:
            raise ValueError("min_relevance must be between 0 and 100")
        if not MIN_VIDEOS <= int(self.max_source_videos) <= 100:
            raise ValueError("max_source_videos must be between 20 and 100")
        if not 0.5 <= float(self.high_traffic_percentile) <= 0.9:
            raise ValueError("high_traffic_percentile must be between 0.5 and 0.9")
        if self.variant_id not in {"A", "B"}:
            raise ValueError("variant_id must be A or B")
        if not 30 <= self.short_seconds <= 120 or not 120 <= self.long_seconds <= 600 or self.long_seconds <= self.short_seconds:
            raise ValueError("短版须为 30—120 秒，长版须为 120—600 秒且长于短版")
        object.__setattr__(self, "account_key", account_key)
        object.__setattr__(self, "recent_video_types", normalized)
        from .script_pair import _reference_source_ids
        object.__setattr__(self, "script_reference_source_ids",
                           _reference_source_ids(self.script_reference_source_ids))
        if not isinstance(self.staged_screenplay_bundle_path, str):
            raise ValueError('staged_screenplay_bundle_path 必须是路径字符串')
        if self.staged_screenplay_bundle_path:
            if any((self.initial_draft_path, self.baseline_draft_path, self.initial_revision_path,
                    self.revision_feedback)):
                raise ValueError('分阶段剧本包不能混用 baseline/resume/revision 参数')
            if (self.short_seconds, self.long_seconds) != (45, 180):
                raise ValueError('分阶段剧本包仅支持45秒短版与180秒长版')


@dataclass(frozen=True, slots=True)
class OverlapTrait:
    dimension: str
    value: str
    support_video_count: int
    cohort_video_count: int
    unique_author_count: int
    weighted_support: float
    evidence_level: str
    source_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CharacterSpec:
    name: str
    identity: str
    appearance: str
    wardrobe: str
    performance_arc: str


@dataclass(frozen=True, slots=True)
class DetailedScriptShot:
    shot_id: str
    start_seconds: float
    end_seconds: float
    scene: str
    participants: tuple[str, ...]
    blocking: str
    action: str
    emotion_and_performance: str
    camera: str
    dialogue_speaker: str
    dialogue: str
    subtitle: str
    audio: str
    narrative_purpose: str
    continuity: str
    model_prompt_zh: str
    composition: str = ""
    lighting: str = ""
    shot_size: str = ""
    camera_angle: str = ""
    camera_movement: str = ""
    start_frame: str = ""
    end_frame: str = ""
    transition: str = ""
    dialogue_mode: str = "in_scene"


@dataclass(frozen=True, slots=True)
class DetailedVideoScript:
    schema: str
    script_id: str
    account_uuid: str
    domain_strategy_id: str
    strategy_version: str
    variant_id: str
    title: str
    status: str
    target_duration_seconds: float
    aspect_ratio: str
    style: str
    premise: str
    characters: tuple[CharacterSpec, ...]
    shots: tuple[DetailedScriptShot, ...]
    global_continuity: tuple[str, ...]
    negative_constraints: str
    legal_review_note: str
    created_at: str
    format_kind: str = ""
    core_message: str = ""
    dramatic_question: str = ""
    resolution: str = ""
    closing_line: str = ""
    story_beats: tuple[dict, ...] = ()
    generation: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreVideoScriptArtifact:
    script: DetailedVideoScript
    script_path: str
    script_json_path: str
    audit_path: str


@dataclass(frozen=True, slots=True)
class PreVideoScriptPairArtifact:
    short: PreVideoScriptArtifact
    long: PreVideoScriptArtifact
    manifest_path: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    observation: TrendObservation
    analysis: VideoContentAnalysis
    published_at: datetime | None
    relevance: float
    age_hours: float | None
    weight: float


@dataclass(frozen=True, slots=True)
class _OverlapProfile:
    traits: tuple[OverlapTrait, ...]
    media_observed_video_count: int
    dimension_coverage: dict[str, float]
    focus: str
    focus_evidence_level: str
    high_traffic_metric_threshold: int


class PreVideoScriptService:
    def __init__(
        self,
        *,
        repository: TrendRepository | None = None,
        profile_repository: AccountProfileRepository | None = None,
        script_client=None,
        review_client=None,
    ) -> None:
        self.repository = repository or TrendRepository()
        self.profile_repository = profile_repository or AccountProfileRepository()
        self.script_client = script_client
        self.review_client = review_client

    def recent_video_type_counts(
        self,
        account_key: str,
        *,
        window_days: int | None = None,
        min_relevance: float = 50.0,
        collection_run_id: str = "",
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Return input choices ordered by evidence weight, not a result report."""
        profile = self.profile_repository.get(account_key)
        analyses = self.repository.list_content_analyses(
            account_uuid=profile.account_uuid,
            limit=100_000,
        )
        video_types = tuple(
            dict.fromkeys(
                item.presentation_type
                for item in analyses
                if item.profile_version == profile.profile_version
                and item.presentation_type
            )
        )
        if not video_types:
            return {}
        candidates = self._recent_candidates(
            profile,
            PreVideoScriptRequest(
                account_key=account_key,
                recent_video_types=video_types,
                window_days=window_days,
                min_relevance=min_relevance,
                collection_run_id=collection_run_id,
            ),
            (now or datetime.now(timezone.utc)).astimezone(timezone.utc),
        )
        counts: dict[str, int] = defaultdict(int)
        weights: dict[str, float] = defaultdict(float)
        for candidate in candidates:
            video_type = candidate.analysis.presentation_type
            counts[video_type] += 1
            weights[video_type] += candidate.weight
        return dict(sorted(counts.items(), key=lambda item: weights[item[0]], reverse=True))

    def source_media_readiness(self, request, *, now=None, verify_artifacts=False):
        """Read-only preflight with exactly the same source selection as generate."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        profile = self.profile_repository.get(request.account_key)
        candidates = self._recent_candidates(profile, request, current)
        cohort = self._high_traffic_cohort(candidates, request)
        sample = require_sample([item.observation for item in cohort])
        result = batch_media_readiness([item.analysis for item in cohort], verify_artifacts=verify_artifacts)
        result.update(sample_gate=sample.to_dict(),
            selected_item_ids=[item.observation.item_id for item in cohort])
        return result

    def generate(
        self,
        request: PreVideoScriptRequest,
        *,
        now: datetime | None = None,
    ) -> PreVideoScriptPairArtifact:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        profile = self.profile_repository.get(request.account_key)
        if profile.domain_strategy_id != "legal_services":
            raise ValueError("详细镜头扩张当前仅接入法律账号；小说账号需使用独立剧情扩张策略")
        candidates = self._recent_candidates(profile, request, current)
        if not candidates:
            types = ", ".join(request.recent_video_types)
            raise ValueError(
                f"当前批次及时间筛选范围没有类型为 {types} 且相关度达标的视频"
            )

        cohort = self._high_traffic_cohort(candidates, request)
        require_sample([item.observation for item in cohort])
        media_gate = batch_media_readiness([item.analysis for item in cohort])
        if not media_gate['ready']:
            output_dir = self._resolve_output_dir(request)
            output_dir.mkdir(parents=True, exist_ok=True)
            gate_path = output_dir / f'source_media_gate_{uuid.uuid4().hex}.json'
            report = dict(media_gate, account_key=request.account_key,
                collection_run_id=cohort[0].observation.run_id, checked_at=current.isoformat(),
                video_generation_submitted=False, script_generation_submitted=False,
                sources=[{'item_id':c.observation.item_id,'video_id':c.observation.video_id,
                    'url':c.observation.url,'title':c.observation.title} for c in cohort])
            self._atomic_write(gate_path, json.dumps(report, ensure_ascii=False, indent=2))
            media_gate['report_path'] = str(gate_path)
            raise SourceMediaGateError(media_gate)
        overlap = self._mine_overlap(profile, cohort)
        fingerprint = self._fingerprint(profile, request, overlap, cohort)
        created_at = current.isoformat()
        opportunity = self._build_opportunity(
            profile, request, overlap, cohort, fingerprint, created_at
        )
        from .script_pair import generate_script_pair
        for saved_draft in (request.initial_draft_path, request.baseline_draft_path):
            if not saved_draft:
                continue
            draft_path = Path(saved_draft).resolve()
            if (self._resolve_output_dir(request) / '_runs').resolve() not in draft_path.parents:
                raise ValueError('只能续审本项目工作流保存的原始模型草稿')
        client, review_client = self.script_client, self.review_client
        if client is None:
            from src.shared.llm_client import LLMClient
            from src.shared.config import settings
            script_model = settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
            extra_body = None
            if settings.SCRIPT_LLM_THINKING and not request.staged_screenplay_bundle_path:
                if (script_model.lower() != 'minimax-m3'
                        or settings.SCRIPT_LLM_THINKING not in ('disabled', 'adaptive')):
                    raise ValueError('SCRIPT_LLM_THINKING 仅适用于 MiniMax-M3，值为 disabled 或 adaptive')
                extra_body = {'thinking': {'type': settings.SCRIPT_LLM_THINKING}, 'reasoning_split': True}
            client = LLMClient(timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0,
                               max_tokens=settings.SCRIPT_LLM_MAX_TOKENS, preserve_invalid_json=True,
                               model=settings.SCRIPT_LLM_MODEL or None, extra_body=extra_body)
            if review_client is None and settings.SCRIPT_REVIEW_LLM_MODEL:
                review_client = LLMClient(timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0,
                    max_tokens=settings.SCRIPT_LLM_MAX_TOKENS, preserve_invalid_json=True,
                    model=settings.SCRIPT_REVIEW_LLM_MODEL)
        # Both complete scripts must validate before any output is written.
        scripts = generate_script_pair(client, profile, cohort, overlap, created_at=created_at,
                                       short_seconds=request.short_seconds, long_seconds=request.long_seconds,
                                       editor_feedback=request.editor_feedback,
                                       initial_draft_path=request.initial_draft_path,
                                       revision_feedback=request.revision_feedback,
                                       initial_revision_path=request.initial_revision_path,
                                       baseline_draft_path=request.baseline_draft_path,
                                       continuous_short=request.continuous_short,
                                       review_client=review_client,
                                       review_only=request.review_only,
                                        script_reference_source_ids=request.script_reference_source_ids,
                                        staged_screenplay_bundle_path=request.staged_screenplay_bundle_path,
                                        trace_dir=self._resolve_output_dir(request) / '_runs' / uuid.uuid4().hex)
        self.repository.save_opportunity(opportunity)
        artifacts = tuple(self._write_artifacts(request, profile, opportunity, overlap, script, cohort)
                          for script in scripts)
        manifest_path = Path(artifacts[0].script_path).with_suffix('.pair.json')
        review_path = manifest_path.with_suffix('.review.md')
        self._atomic_write(review_path, render_script_pair_markdown(scripts))
        self._atomic_write(manifest_path, json.dumps({
            'schema': 'pre_video_script_pair/v1', 'created_at': created_at,
            'account_uuid': profile.account_uuid, 'core_message': scripts[0].core_message,
            'review_path': str(review_path),
            'short': {'script_path': artifacts[0].script_path, 'script_json_path': artifacts[0].script_json_path,
                      'audit_path': artifacts[0].audit_path},
            'long': {'script_path': artifacts[1].script_path, 'script_json_path': artifacts[1].script_json_path,
                     'audit_path': artifacts[1].audit_path},
            'paused_at': 'before_video_generation', 'video_generation_submitted': False,
        }, ensure_ascii=False, indent=2))
        return PreVideoScriptPairArtifact(artifacts[0], artifacts[1], str(manifest_path))

    def _recent_candidates(
        self,
        profile: AccountProfile,
        request: PreVideoScriptRequest,
        now: datetime,
    ) -> list[_Candidate]:
        analyses: dict[str, VideoContentAnalysis] = {}
        for analysis in self.repository.list_content_analyses(
            account_uuid=profile.account_uuid,
            limit=100_000,
        ):
            if analysis.profile_version == profile.profile_version:
                existing = analyses.get(analysis.item_id)
                if existing is None or (media_readiness(analysis, verify_artifacts=False)['ready']
                        and not media_readiness(existing, verify_artifacts=False)['ready']):
                    analyses[analysis.item_id] = analysis

        cutoff = now - timedelta(days=request.window_days) if request.window_days is not None else None
        output: list[_Candidate] = []
        seen: set[str] = set()
        for observation in batch_observations(self.repository,
            account_uuid=profile.account_uuid,
            run_id=request.collection_run_id,
            limit=100_000,
        ):
            if observation.video_id in seen:
                continue
            seen.add(observation.video_id)
            analysis = analyses.get(observation.item_id)
            published_at = self._parse_datetime(observation.published_at)
            if analysis is None:
                continue
            if cutoff is not None and (published_at is None or not cutoff <= published_at <= now + timedelta(hours=1)):
                continue
            if analysis.presentation_type not in request.recent_video_types:
                continue
            relevance = (
                analysis.relevance.score
                if analysis.relevance is not None
                else float(observation.relevance_score or 0.0)
            )
            if relevance < request.min_relevance:
                continue
            visible_metric = max(0, int(observation.metric_value or 0))
            if visible_metric <= 0:
                continue
            age_hours = max(0.0, (now - published_at).total_seconds() / 3600) if published_at else None
            freshness = max(0.2, 1.0 - age_hours / (request.window_days * 24)) if request.window_days is not None else 1.0
            weight = math.log10(visible_metric + 10) * (relevance / 100) * freshness
            output.append(
                _Candidate(
                    observation,
                    analysis,
                    published_at,
                    relevance,
                    age_hours,
                    weight,
                )
            )
        return output

    @staticmethod
    def _high_traffic_cohort(
        candidates: list[_Candidate], request: PreVideoScriptRequest
    ) -> list[_Candidate]:
        require_sample([item.observation for item in candidates])
        ranked = sorted(
            candidates,
            # The same displayed count is more useful when it was accumulated
            # recently and has stronger account relevance. Raw counts remain in
            # the audit, but cohort membership uses this time-aware score.
            key=lambda item: (item.weight, int(item.observation.metric_value or 0)),
            reverse=True,
        )
        top_share = 1.0 - request.high_traffic_percentile
        cohort_size = max(MIN_VIDEOS, math.ceil(len(ranked) * top_share))
        cohort_size = min(len(ranked), request.max_source_videos, cohort_size)
        return ranked[:cohort_size]

    def _mine_overlap(
        self, profile: AccountProfile, cohort: list[_Candidate]
    ) -> _OverlapProfile:
        buckets: dict[tuple[str, str, str], list[_Candidate]] = defaultdict(list)
        media_dimension_hits: dict[str, set[str]] = defaultdict(set)
        for candidate in cohort:
            for dimension, value, level in self._candidate_traits(profile, candidate):
                key = (dimension, value, level)
                if all(
                    existing.observation.item_id != candidate.observation.item_id
                    for existing in buckets[key]
                ):
                    buckets[key].append(candidate)
                if level == "observed_media":
                    media_dimension_hits[dimension].add(candidate.observation.item_id)

        # Two independent videos are a real overlap for a small top cohort;
        # larger cohorts scale the support floor to avoid accidental matches.
        minimum_support = max(2, math.ceil(len(cohort) * 0.25))
        total_weight = sum(item.weight for item in cohort) or 1.0
        traits: list[OverlapTrait] = []
        for (dimension, value, level), items in buckets.items():
            authors = {
                item.observation.author.strip()
                for item in items
                if item.observation.author.strip()
            }
            if len(items) < minimum_support:
                continue
            if authors and len(authors) < 2 and len(cohort) > 2:
                continue
            traits.append(
                OverlapTrait(
                    dimension=dimension,
                    value=value,
                    support_video_count=len(items),
                    cohort_video_count=len(cohort),
                    unique_author_count=len(authors),
                    weighted_support=round(
                        sum(item.weight for item in items) / total_weight, 4
                    ),
                    evidence_level=level,
                    source_item_ids=tuple(
                        item.observation.item_id for item in items
                    ),
                )
            )
        traits.sort(
            key=lambda item: (
                item.evidence_level == "observed_media",
                item.weighted_support,
                item.support_video_count,
            ),
            reverse=True,
        )

        focus_traits = [item for item in traits if item.dimension == "topic_scope"]
        if focus_traits:
            focus = max(focus_traits, key=lambda item: item.weighted_support).value
            focus_level = "high_traffic_overlap"
        else:
            focus = self._weighted_legal_focus(profile, cohort)
            focus_level = "highest_weighted_topic_seed"
        media_count = sum(
            1
            for item in cohort
            if media_readiness(item.analysis, verify_artifacts=False)['ready']
        )
        coverage = {
            dimension: round(
                len(media_dimension_hits.get(dimension, set())) / len(cohort), 4
            )
            for dimension in ("scene", "character", "action", "emotion", "language")
        }
        return _OverlapProfile(
            traits=tuple(traits),
            media_observed_video_count=media_count,
            dimension_coverage=coverage,
            focus=focus,
            focus_evidence_level=focus_level,
            high_traffic_metric_threshold=min(
                int(item.observation.metric_value or 0) for item in cohort
            ),
        )

    def _candidate_traits(
        self, profile: AccountProfile, candidate: _Candidate
    ) -> Iterable[tuple[str, str, str]]:
        observation = candidate.observation
        analysis = candidate.analysis
        corpus = " ".join(
            (
                observation.title,
                *observation.hashtags,
                *observation.relevance_terms,
                *analysis.topic_labels,
            )
        )
        for scope in profile.service_scope or LEGAL_SCOPE_ALIASES:
            aliases = LEGAL_SCOPE_ALIASES.get(scope, (scope,))
            if any(alias and alias in corpus for alias in aliases):
                yield "topic_scope", scope, "observed_metadata"
        if analysis.hook_type and analysis.hook_type != "unknown":
            yield "hook", analysis.hook_type, "observed_metadata"
        if analysis.pacing and analysis.pacing != "unknown":
            yield "pacing", analysis.pacing, "observed_metadata"
        content_text = " ".join(
            (
                observation.title,
                analysis.content_summary,
                analysis.transcript_summary,
                analysis.visual_summary,
            )
        )
        for intent in analysis.user_intents:
            # Metadata providers install generic domain intents. They are only
            # market evidence when the analysed content actually expresses one.
            if intent and intent in content_text:
                yield "user_intent", intent, "observed_metadata"
        for value, terms in NARRATIVE_DEVICE_TERMS.items():
            if any(term in observation.title for term in terms):
                yield "narrative_device", value, "observed_metadata"

        if not media_readiness(analysis, verify_artifacts=False)['ready']:
            return
        expression = analysis.expression_analysis
        for item in expression['expression_modes']:
            yield 'expression_mode', item['mode'], 'observed_media'
        if expression.get('conflict', {}).get('status') == 'observed':
            yield 'narrative_device', '人物目标与阻碍推动冲突', 'observed_media'
        visual_text = ' '.join(e['text'] for e in expression['evidence'] if e['channel']=='visual')
        spoken_text = ' '.join(e['text'] for e in expression['evidence'] if e['channel']=='asr')
        for dimension, values in MEDIA_DIMENSION_TERMS.items():
            media_text = spoken_text if dimension == 'language' else visual_text
            for value, terms in values.items():
                if any(term in media_text for term in terms):
                    yield dimension, value, "observed_media"

    @staticmethod
    def _weighted_legal_focus(
        profile: AccountProfile, cohort: list[_Candidate]
    ) -> str:
        configured = list(
            profile.domain_config.get("practice_areas") or profile.service_scope
        )
        totals: dict[str, float] = defaultdict(float)
        for candidate in cohort:
            corpus = " ".join(
                (
                    candidate.observation.title,
                    *candidate.observation.hashtags,
                    *candidate.analysis.topic_labels,
                )
            )
            for scope in configured:
                aliases = LEGAL_SCOPE_ALIASES.get(scope, (scope,))
                if any(alias in corpus for alias in aliases):
                    totals[scope] += candidate.weight
        return (
            max(totals, key=totals.get)
            if totals
            else (configured[0] if configured else "法律问题")
        )

    @staticmethod
    def _build_opportunity(
        profile: AccountProfile,
        request: PreVideoScriptRequest,
        overlap: _OverlapProfile,
        cohort: list[_Candidate],
        fingerprint: str,
        created_at: str,
    ) -> ContentOpportunity:
        def dominant(dimension: str, default: str) -> str:
            matches = [item for item in overlap.traits if item.dimension == dimension]
            return (
                max(matches, key=lambda item: item.weighted_support).value
                if matches
                else default
            )

        return ContentOpportunity(
            opportunity_id=f"opportunity:overlap:{fingerprint[:20]}",
            account_uuid=profile.account_uuid,
            account_key=profile.account_key,
            profile_version=profile.profile_version,
            domain_strategy_id=profile.domain_strategy_id,
            strategy_version=profile.strategy_version,
            cluster_id=f"high-traffic-overlap:{fingerprint[:20]}",
            brief_id="",
            title=overlap.focus,
            status="candidate",
            opportunity_score=round(
                100
                * max(
                    (item.weighted_support for item in overlap.traits),
                    default=0,
                ),
                2,
            ),
            score_breakdown={
                "high_traffic_cohort_size": float(len(cohort)),
                "overlap_trait_count": float(len(overlap.traits)),
                "average_relevance": round(
                    sum(item.relevance for item in cohort) / len(cohort), 2
                ),
                "media_observed_coverage": round(
                    overlap.media_observed_video_count / len(cohort), 4
                ),
            },
            selected_item_ids=[item.observation.item_id for item in cohort],
            recommended_presentation=request.recent_video_types[0],
            recommended_hook_type=dominant("hook", "conflict"),
            recommended_pacing=dominant("pacing", "balanced"),
            recommended_duration_seconds=15.0,
            recommended_publish_window=(
                profile.publishing_windows[0]
                if profile.publishing_windows
                else "待测试"
            ),
            recommended_workflow_profile="legal_overlap_expansion_v2",
            topic_labels=[overlap.focus],
            user_intents=[
                item.value
                for item in overlap.traits
                if item.dimension == "user_intent"
            ][:10],
            evidence=[
                f"近期类型：{', '.join(request.recent_video_types)}",
                f"时间校正后的高展示指标样本 {len(cohort)} 条；组内最小页面展示值 {overlap.high_traffic_metric_threshold}",
                f"重合特征 {len(overlap.traits)} 项；媒体级分析覆盖 {overlap.media_observed_video_count}/{len(cohort)}",
            ],
            risks=[
                "页面展示指标不等同于平台官方播放量。",
                "未取得视频画面/转写的维度不得标记为样本观察结果。",
                "热门内容只提供抽象结构，不作为法律依据或可复制表达。",
            ],
            valid_from=created_at,
            valid_until=(
                datetime.fromisoformat(created_at) + timedelta(hours=24)
            ).isoformat(),
            created_at=created_at,
        )

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _fingerprint(
        profile: AccountProfile,
        request: PreVideoScriptRequest,
        overlap: _OverlapProfile,
        cohort: list[_Candidate],
    ) -> str:
        payload = {
            "schema": "high_traffic_overlap_to_detailed_script/v3-media-expression",
            "account_uuid": profile.account_uuid,
            "profile_version": profile.profile_version,
            "video_types": request.recent_video_types,
            "window_days": request.window_days,
            "min_relevance": request.min_relevance,
            "high_traffic_percentile": request.high_traffic_percentile,
            "focus": overlap.focus,
            "traits": [
                (item.dimension, item.value, item.source_item_ids)
                for item in overlap.traits
            ],
            "sources": [{'item_id':item.observation.item_id,
                         'analysis_id':item.analysis.analysis_id,
                         'input_fingerprint':item.analysis.input_fingerprint,
                         'expression_analysis':item.analysis.expression_analysis,
                         'media_evidence':item.analysis.media_evidence} for item in cohort],
        }
        if request.script_reference_source_ids:
            payload['script_reference_source_ids'] = request.script_reference_source_ids
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _resolve_output_dir(request):
        output_dir = (PROJECT_ROOT / request.output_dir).resolve()
        allowed_root = (PROJECT_ROOT / 'data').resolve()
        if output_dir != allowed_root and allowed_root not in output_dir.parents:
            raise ValueError('pre-video output_dir must stay inside project data directory')
        return output_dir

    def _write_artifacts(
        self,
        request: PreVideoScriptRequest,
        profile: AccountProfile,
        opportunity: ContentOpportunity,
        overlap: _OverlapProfile,
        script: DetailedVideoScript,
        cohort: list[_Candidate],
    ) -> PreVideoScriptArtifact:
        output_dir = self._resolve_output_dir(request)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = script.script_id.replace(":", "_")
        script_path = output_dir / f"{stem}.md"
        script_json_path = output_dir / f"{stem}.json"
        audit_path = output_dir / f"{stem}.audit.json"
        markdown = render_script_markdown(script)
        self._atomic_write(script_path, markdown)
        self._atomic_write(
            script_json_path,
            json.dumps(asdict(script), ensure_ascii=False, indent=2) + "\n",
        )
        audit = {
            "schema": "pre_video_script_audit/v3",
            "pipeline": [
                "recent_time_and_account_relevance_filter",
                "relative_high_traffic_cohort",
                "verified_source_media_expression_gate",
                "within_batch_high_metric_expression_comparison",
                "cross_video_and_author_overlap_mining",
                "prompt_based_short_long_original_scripts",
                "detailed_shot_script",
            ],
            "account_key": profile.account_key,
            "account_uuid": profile.account_uuid,
            "profile_version": profile.profile_version,
            "recent_video_types": list(request.recent_video_types),
            "window_days": request.window_days,
            "min_relevance": request.min_relevance,
            "high_traffic_percentile": request.high_traffic_percentile,
            "selection": {
                "sample_gate": require_sample([item.observation for item in cohort]).to_dict(),
                "cohort_video_count": len(cohort),
                "minimum_visible_metric_in_cohort": overlap.high_traffic_metric_threshold,
                "ranking_formula": "log10(visible_metric+10) * (relevance / 100) * freshness",
                "score_meaning": "采样优先级，不是剧本创作参考贡献；不将其归一化展示为参考占比。",
                "time_filter": "published_at" if request.window_days is not None else "same_collection_batch",
                "freshness_when_no_time_filter": 1.0,
                "metric_confirmations": (self.repository.list_metric_confirmations(run_id=cohort[0].observation.run_id, account_uuid=profile.account_uuid)
                                         if hasattr(self.repository, "list_metric_confirmations") else []),
                "metric_kind": sorted(
                    {item.observation.metric_kind for item in cohort}
                ),
            },
            "generation": script.generation,
            "media_readiness": batch_media_readiness([c.analysis for c in cohort], verify_artifacts=False),
            "expression_patterns": build_expression_patterns(cohort),
            "reference_usage": script.generation.get('reference_usage', []),
            "expression_plan": script.generation.get('expression_plan', {}),
            "format_kind": script.format_kind,
            "story_contract": {'core_message': script.core_message, 'dramatic_question': script.dramatic_question,
                               'resolution': script.resolution, 'closing_line': script.closing_line},
            "overlap_profile": {
                "focus": overlap.focus,
                "focus_evidence_level": overlap.focus_evidence_level,
                "traits": [asdict(item) for item in overlap.traits],
                "media_observed_video_count": overlap.media_observed_video_count,
                "dimension_coverage": overlap.dimension_coverage,
            },
            "creative_expansion": {
                "observed_anchor_dimensions": sorted(
                    {item.dimension for item in overlap.traits}
                ),
                "original_dimensions": [
                    "scene",
                    "character_appearance",
                    "blocking",
                    "action",
                    "emotion_and_performance",
                    "dialogue",
                    "camera",
                    "audio",
                    "continuity",
                ],
                "rule": "表达方法须基于逐视频音画证据；具体剧情、人物和对白原创改编，使用关系逐项记录，不计算虚构贡献比例。",
            },
            "opportunity": asdict(opportunity),
            "source_videos": [
                {
                    "item_id": item.observation.item_id,
                    "video_id": item.observation.video_id,
                    "url": item.observation.url,
                    "run_id": item.observation.run_id,
                    "primary_tag": primary_tag(item.observation),
                    "title": item.observation.title,
                    "author": item.observation.author,
                    "published_at": item.observation.published_at,
                    "collected_at": item.observation.collected_at,
                    "analyzed_at": item.analysis.created_at,
                    "analysis_provider": item.analysis.provider_id,
                    "media_access_mode": item.analysis.media_access_mode,
                    "presentation_type": item.analysis.presentation_type,
                    "hook_type": item.analysis.hook_type,
                    "visible_metric": item.observation.metric_value,
                    "metric_kind": item.observation.metric_kind,
                    "age_hours_at_selection": round(item.age_hours, 3) if item.age_hours is not None else None,
                    "relevance": round(item.relevance, 2),
                    "time_relevance_traffic_score": round(item.weight, 6),
                    "analysis_id": item.analysis.analysis_id,
                    "expression_analysis": item.analysis.expression_analysis,
                    "media_evidence": item.analysis.media_evidence,
                }
                for item in cohort
            ],
            "script_id": script.script_id,
            "script_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        }
        self._atomic_write(
            audit_path,
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        )
        return PreVideoScriptArtifact(
            script=script,
            script_path=str(script_path),
            script_json_path=str(script_json_path),
            audit_path=str(audit_path),
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class LegalOverlapExpansionStrategy:
    """Expand abstract overlap into an original, model-ready legal short."""

    def build(
        self,
        profile: AccountProfile,
        overlap: _OverlapProfile,
        cohort: list[_Candidate],
        *,
        fingerprint: str,
        variant_id: str,
        created_at: str,
    ) -> DetailedVideoScript:
        scenario = _choose_legal_scenario(overlap.focus, cohort, variant_id)
        characters = tuple(CharacterSpec(**item) for item in scenario["characters"])
        global_continuity = (
            "三个镜头锁定同一角色的年龄、脸型、发型、服装、配饰和体型。",
            "关键文件或手机在相邻镜头保持外观、朝向与持有关系一致。",
            "每个片段只完成一个连续动作，结束姿态必须能承接下一镜头。",
            "对白均为自然普通话；字幕逐字一致、简体中文、画面下方居中且稳定。",
        )
        shots = tuple(
            _build_detailed_shot(
                item,
                characters=characters,
                global_continuity=global_continuity,
            )
            for item in scenario["shots"]
        )
        return DetailedVideoScript(
            schema="detailed_video_script/v2",
            script_id=f"detailed-script:{fingerprint[:24]}",
            account_uuid=profile.account_uuid,
            domain_strategy_id=profile.domain_strategy_id,
            strategy_version=profile.strategy_version,
            variant_id=variant_id,
            title=scenario["title"],
            status="draft_pending_legal_review",
            target_duration_seconds=15.0,
            aspect_ratio="9:16",
            style=STYLE,
            premise=scenario["premise"],
            characters=characters,
            shots=shots,
            global_continuity=global_continuity,
            negative_constraints=NEGATIVE_CONSTRAINTS,
            legal_review_note=(
                "这是剧情化普法脚本，不构成个案法律意见；发布前需按当日有效规范核验"
                "事实前提、适用地域、程序和时限。"
            ),
            created_at=created_at,
        )


def _choose_legal_scenario(
    focus: str, cohort: list[_Candidate], variant_id: str
) -> dict[str, object]:
    corpus = " ".join(item.observation.title for item in cohort)
    if focus == "劳动争议":
        key = "dismissal_absence"
    elif focus == "婚姻家事" and any(term in corpus for term in ("亲生", "亲子")):
        key = "parentage_evidence"
    elif focus == "婚姻家事":
        key = "marital_debt"
    elif focus == "债权债务" and any(term in corpus for term in ("去世", "逝者", "遗产")):
        key = "estate_debt"
    elif focus == "债权债务":
        key = "loan_evidence"
    elif focus == "合同纠纷":
        key = "contract_delivery"
    elif focus == "交通事故":
        key = "traffic_evidence"
    else:
        key = "general_evidence"
    return _LEGAL_SCENARIOS[key][variant_id]


def _build_detailed_shot(
    item: dict[str, object],
    *,
    characters: tuple[CharacterSpec, ...],
    global_continuity: tuple[str, ...],
) -> DetailedScriptShot:
    participants = tuple(str(value) for value in item["participants"])
    role_lock = "；".join(
        f"{character.name}：{character.appearance}，{character.wardrobe}"
        for character in characters
        if character.name in participants
    )
    dialogue = str(item["dialogue"])
    speaker = str(item["dialogue_speaker"])
    duration = float(item["end_seconds"]) - float(item["start_seconds"])
    mode = str(item.get('dialogue_mode', 'in_scene'))
    visual_fields = {key: str(item.get(key, '')) for key in (
        'composition', 'lighting', 'shot_size', 'camera_angle', 'camera_movement',
        'start_frame', 'end_frame', 'transition')}
    camera = ('；'.join(visual_fields[key] for key in ('shot_size', 'camera_angle', 'camera_movement'))
              if visual_fields['shot_size'] else str(item['camera']))
    if mode == 'none':
        speech = '本镜无对白、无人声，不生成字幕；只保留所列环境声和动作声。'
    else:
        speech = (f"{speaker}用符合当前情绪的普通话完整说出：“{dialogue}”。"
                  + ('声音只从场内设备传出，入画人物不代说、不对口型。' if mode == 'device'
                     else '说话人入画并同步准确口型，其他人物不代说。')
                  + f"画面下方同步显示清晰稳定的简体中文字幕：“{dialogue}”。")
    prompt = (
        f"{STYLE}，9:16，时长约{duration:.2f}秒。{item['scene']}。"
        f"构图：{visual_fields['composition']}。光线：{visual_fields['lighting']}。"
        f"首帧：{visual_fields['start_frame']}。"
        f"人物锁定：{role_lock}。{item['blocking']}。{item['action']}。"
        f"{item['emotion_and_performance']}。摄影：{camera}。{speech}{item['audio']}。"
        f"尾帧：{visual_fields['end_frame']}。剪辑衔接（在本镜之外执行）：{visual_fields['transition']}。"
        f"连续性要求：{item['continuity']}；{global_continuity[0]}"
        "只生成一个连续镜头，允许人物完成顺接或同时发生的简洁动作链；不在片段内部切镜、不变焦、不改变景别。"
        "禁止旁白、解说配音、内心独白及未列出的声音。"
        "本段画面、人物动作、所列对白和环境声音由视频模型一次生成。"
    )
    return DetailedScriptShot(
        shot_id=str(item["shot_id"]),
        start_seconds=float(item["start_seconds"]),
        end_seconds=float(item["end_seconds"]),
        scene=str(item["scene"]),
        participants=participants,
        blocking=str(item["blocking"]),
        action=str(item["action"]),
        emotion_and_performance=str(item["emotion_and_performance"]),
        camera=camera,
        dialogue_speaker=speaker,
        dialogue=dialogue,
        subtitle=dialogue,
        audio=str(item["audio"]),
        narrative_purpose=str(item["narrative_purpose"]),
        continuity=str(item["continuity"]),
        model_prompt_zh=prompt,
        dialogue_mode=mode,
        **visual_fields,
    )


def _scenario(
    title: str,
    premise: str,
    *,
    client_identity: str,
    client_appearance: str,
    client_wardrobe: str,
    client_arc: str,
    scenes: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return {
        "title": title,
        "premise": premise,
        "characters": (
            {
                "name": "当事人",
                "identity": client_identity,
                "appearance": client_appearance,
                "wardrobe": client_wardrobe,
                "performance_arc": client_arc,
            },
            {
                "name": "律师",
                "identity": "三十多岁的执业律师，负责拆解事实和证据，不承诺结果",
                "appearance": "黑色短发、神情专注、面部自然真实",
                "wardrobe": "深灰西装、白衬衫、无夸张配饰",
                "performance_arc": "始终沉稳克制，先倾听，再用材料把焦虑转化为可执行步骤",
            },
        ),
        "shots": scenes,
    }


def _shot(
    shot_id: str,
    start: float,
    end: float,
    *,
    scene: str,
    participants: tuple[str, ...],
    blocking: str,
    action: str,
    emotion: str,
    camera: str,
    speaker: str,
    dialogue: str,
    audio: str,
    purpose: str,
    continuity: str,
) -> dict[str, object]:
    return {
        "shot_id": shot_id,
        "start_seconds": start,
        "end_seconds": end,
        "scene": scene,
        "participants": participants,
        "blocking": blocking,
        "action": action,
        "emotion_and_performance": emotion,
        "camera": camera,
        "dialogue_speaker": speaker,
        "dialogue": dialogue,
        "audio": audio,
        "narrative_purpose": purpose,
        "continuity": continuity,
    }


_COMMON_CLIENT = {
    "client_identity": "三十多岁的普通上班族，带着刚发生纠纷后的疲惫感",
    "client_appearance": "短黑发、眼下轻微疲态、真实皮肤纹理",
    "client_wardrobe": "深蓝通勤外套、浅灰内搭，手持黑色手机和牛皮纸文件袋",
    "client_arc": "开场压着愤怒和慌乱，中段认真追随材料，结尾恢复克制并准备行动",
}


def _three_shot_scenario(
    *,
    title: str,
    premise: str,
    first_scene: str,
    first_action: str,
    first_emotion: str,
    first_dialogue: str,
    evidence_action: str,
    second_dialogue: str,
    third_action: str,
    third_dialogue: str,
    variant: str,
) -> dict[str, object]:
    if variant == "B":
        scenes = (
            _shot(
                "S01",
                0,
                5,
                scene="白天的律师事务所咨询室，木质桌面，侧窗自然光，案件材料仍装在牛皮纸文件袋中",
                participants=("当事人", "律师"),
                blocking="当事人坐左侧、律师坐右侧，文件袋位于两人之间，手机屏幕朝下",
                action=evidence_action,
                emotion="当事人仍急于得到答案；律师不看镜头，先用平稳动作建立材料顺序",
                camera="固定双人中景，略微俯拍桌面，证据动作和两人表情同时可见",
                speaker="律师",
                dialogue=second_dialogue,
                audio="保留纸张展开和签字笔轻触桌面的声音，不添加背景音乐",
                purpose="直接用可见的证据动作进入问题，避免抽象口播开场",
                continuity="结尾材料按既定方向展开，手机与文件袋保留在桌面原位",
            ),
            _shot(
                "S02",
                5,
                10,
                scene="同一律师事务所咨询室，同一桌面和侧窗光线，材料已按事实顺序排开",
                participants=("当事人", "律师"),
                blocking="律师右手停在证据缺口旁，当事人身体前倾并沿笔尖查看时间线",
                action=third_action,
                emotion="律师克制严谨，在限制条件处放慢语速；当事人的急切转为专注",
                camera="固定桌面与人物半身同框的中近景，不切反打、不改变景别",
                speaker="律师",
                dialogue=third_dialogue,
                audio="保留轻微翻页声和自然室内底噪，不添加背景音乐",
                purpose="给出带事实边界的判断方法，不承诺个案结果",
                continuity="人物、座位、服装、材料方向和光线延续上一镜头",
            ),
            _shot(
                "S03",
                10,
                15,
                scene="同一律师事务所咨询室，材料已被分组，牛皮纸文件袋重新打开",
                participants=("当事人", "律师"),
                blocking="当事人位于左侧整理材料，律师在右侧抬眼确认，签字笔留在桌面中央",
                action="当事人把散乱材料按时间顺序收进文件袋，最后把手机中的原始记录停在导出页面",
                emotion="当事人肩膀逐渐放松，语气从追问转为确认行动；律师轻微点头但不露夸张笑容",
                camera="固定双人中景，焦点落在完成整理的双手和克制表情，不推拉变焦",
                speaker="当事人",
                dialogue="我先固定证据，再做个案判断。",
                audio="保留纸张收拢和手机轻触桌面的声音，台词后留半秒室内声",
                purpose="把法律信息收束为当事人的下一步行动",
                continuity="所有关键道具、服装、座位和光向与前两镜头完全一致",
            ),
        )
        return _scenario(title, premise, scenes=scenes, **_COMMON_CLIENT)

    scenes = (
        _shot(
            "S01",
            0,
            5,
            scene=first_scene,
            participants=("当事人",),
            blocking="当事人位于画面中央，手机在胸口高度，文件袋夹在左臂",
            action=first_action,
            emotion=first_emotion,
            camera="固定中近景，视线与镜头略错开，背景浅景深，冲突物件始终清晰",
            speaker="当事人",
            dialogue=first_dialogue,
            audio="保留现场低频环境声和一次手机轻振，不添加背景音乐",
            purpose="第一秒给出具体人物关系和反常后果，建立继续观看的问题",
            continuity="结尾让手机与文件袋停在胸前，下一镜头沿用同一物件",
        ),
        _shot(
            "S02",
            5,
            10,
            scene="白天的律师事务所咨询室，木质桌面，侧窗自然光，桌上只有案件材料和一支黑色签字笔",
            participants=("当事人", "律师"),
            blocking="当事人坐左侧、律师坐右侧，两人隔桌呈稳定对角线，材料位于画面中心",
            action=evidence_action,
            emotion="当事人眉头仍紧但注意力落到材料；律师语速平稳、目光落在证据而非镜头上，动作有明确停顿",
            camera="固定双人中景，略微俯拍桌面但不改变景别，不切换反打",
            speaker="律师",
            dialogue=second_dialogue,
            audio="保留安静室内底噪、纸张摩擦和签字笔轻触桌面的声音，不添加背景音乐",
            purpose="把抽象法律问题转成观众能看见的证据动作",
            continuity="沿用上一镜头的黑色手机和牛皮纸文件袋，材料展开方向保持一致",
        ),
        _shot(
            "S03",
            10,
            15,
            scene="同一律师事务所咨询室，同一桌面和侧窗光线，证据已按三组整齐排开",
            participants=("当事人", "律师"),
            blocking="律师右手停在最后一组材料旁，当事人双手放松并正视材料",
            action=third_action,
            emotion="律师克制严谨，在关键限定词处略放慢；当事人从急于追问转为理解，肩膀逐渐放松，不露夸张笑容",
            camera="固定桌面与人物半身同框的中近景，焦点从材料自然落到两人表情，不推拉变焦",
            speaker="律师",
            dialogue=third_dialogue,
            audio="保留轻微翻页声，台词结束后留半秒自然室内声，不添加背景音乐",
            purpose="给出边界清楚的行动结论，并保留个案核验要求",
            continuity="两人服装、座位、光向与上一镜头完全一致，结尾稳定停在整理后的材料上",
        ),
    )
    return _scenario(title, premise, scenes=scenes, **_COMMON_CLIENT)


def _variants(**kwargs: str) -> dict[str, dict[str, object]]:
    return {
        variant: _three_shot_scenario(variant=variant, **kwargs)
        for variant in ("A", "B")
    }


_LEGAL_SCENARIOS = {
    "dismissal_absence": _variants(
        title="老板让我走，转头又按旷工解除？｜15秒剧情化普法",
        premise="员工收到模糊的离开指令后被按旷工处理，律师引导其分开固定通知、考勤和沟通证据。",
        first_scene="傍晚的空办公室，冷白顶灯只亮一排，工位电脑已熄屏，玻璃门外有人影离开",
        first_action="当事人快步停在工位旁，举起刚弹出解除消息的手机，另一只手捏紧文件袋后缓慢松开",
        first_emotion="眉心紧锁、呼吸略急，声音压着委屈和愤怒；说到“旷工”时短暂看向熄灭的工位",
        first_dialogue="老板让我走，转头又说我旷工。",
        evidence_action="律师把解除通知、考勤页和聊天记录三份材料依次推到桌面中央，当事人立即俯身看向日期",
        second_dialogue="先留通知、考勤和沟通记录。",
        third_action="律师用签字笔依次点过指令来源、离岗日期和解除理由，当事人把手机放到材料旁",
        third_dialogue="再核对解除理由和时限，别急着签。",
    ),
    "parentage_evidence": _variants(
        title="养了二十年才发现亲子疑问？｜15秒剧情化普法",
        premise="当事人带着亲子关系材料咨询，律师先区分身份事实、支出记录和对方陈述，再提示个案核验。",
        first_scene="雨后的夜晚客厅，窗外城市光影模糊，餐桌上压着一份未完全展开的检测材料",
        first_action="当事人坐在桌边反复捏住报告一角，终于把报告推到灯下，指尖仍轻微发抖",
        first_emotion="眼神发直、下颌绷紧，悲伤和难以置信被压在低声里；说完后不看镜头，只盯着报告",
        first_dialogue="养了二十年，现在才发现亲子疑问。",
        evidence_action="律师没有触碰结论页，只把身份材料、支出流水和双方沟通记录分成三组，当事人跟着移动视线",
        second_dialogue="先核实关系、支出和双方陈述。",
        third_action="律师合上未经核验的报告，把三组材料摆成时间线，当事人缓慢点头并收回颤抖的手",
        third_dialogue="能否主张，要结合证据和具体事实。",
    ),
    "marital_debt": _variants(
        title="配偶突然留下大额欠款，要一起还吗？｜15秒剧情化普法",
        premise="当事人收到陌生催款后咨询，律师用签名、资金用途和沟通记录拆解共同债务判断所需事实。",
        first_scene="深夜家中玄关，暖灯下堆着刚取回的快递，手机突然弹出大额欠款提醒",
        first_action="当事人停下脱外套的动作，举起手机反复确认姓名和金额，随后立刻锁屏",
        first_emotion="先错愕后警惕，眼睛睁大但不尖叫；说到“一起还”时声音明显放低",
        first_dialogue="他背着我借的钱，我也要一起还吗？",
        evidence_action="律师把签字页、资金流向和家庭支出记录排成三列，当事人把催款手机放在第一列旁",
        second_dialogue="先查签名、用途和共同意思。",
        third_action="律师将未经确认的催款单翻面，指向保全聊天与流水的清单，当事人开始逐项拍照留存",
        third_dialogue="超出日常需要，更要核对证据。",
    ),
    "estate_debt": _variants(
        title="亲人去世后，债务就由家人承担吗？｜15秒剧情化普法",
        premise="家属收到催款，律师将个人债务、遗产清单和继承范围分开核对。",
        first_scene="安静的白天客厅，遗物纸箱尚未封口，手机在茶几上持续显示陌生催款来电",
        first_action="当事人按掉来电，把催款短信和遗物清单并排放下，手在纸箱边停住",
        first_emotion="疲惫、迟疑又警觉，声音低沉；提到“家人承担”时抬眼寻求确认",
        first_dialogue="人去世了，欠款就得家人还吗？",
        evidence_action="律师把债务材料与遗产清单分开放置，再用签字笔圈出继承范围，当事人不再触碰催款短信",
        second_dialogue="先看债务性质，再核对遗产范围。",
        third_action="律师把个人承诺书推回当事人一侧但保持未签状态，当事人收起笔并拍下材料目录",
        third_dialogue="别急着个人承诺，先固定材料。",
    ),
    "loan_evidence": _variants(
        title="只有转账记录，欠款还能追回吗？｜15秒剧情化普法",
        premise="出借人只保存了转账截图，律师引导补齐借款合意、交付和催款链条。",
        first_scene="夜晚餐桌，手机停在一笔大额转账记录上，聊天窗口里迟迟没有回复",
        first_action="当事人连续滑动聊天记录又停回转账页，把空白借条压在手机旁",
        first_emotion="焦虑中带懊恼，嘴角紧绷；说到“只有转账”时声音变轻",
        first_dialogue="只有转账记录，欠款还能追回吗？",
        evidence_action="律师把借款聊天、转账凭证和催款记录依次对齐，在缺口处放下一张空白提示卡",
        second_dialogue="先补借款合意、交付和催款链。",
        third_action="律师用笔沿时间线缓慢移动并停在证据缺口，当事人按顺序导出原始记录",
        third_dialogue="证据要成链，再核对主体和期限。",
    ),
    "contract_delivery": _variants(
        title="合同写了，履行记录却断了？｜15秒剧情化普法",
        premise="合同双方对履行结果发生争议，律师将合同原件、交付、付款与往来沟通组成证据链。",
        first_scene="白天仓库门口，卷帘门半开，未签收的货箱与手机中的催款消息同时入画",
        first_action="当事人蹲下查看货箱标签，站起后把未签字的送货单举到手机旁进行比对",
        first_emotion="困惑转为警觉，动作克制但迅速；说到“算交付”时目光落在空白签收栏",
        first_dialogue="货到了门口，就一定算交付了吗？",
        evidence_action="律师将合同原件、签收页、付款记录和沟通内容按发生顺序铺开，当事人指向空白签收栏",
        second_dialogue="先对合同、交付、付款和沟通。",
        third_action="律师把争议条款与实际履行记录上下对齐，当事人拍下完整页而不是只截一句话",
        third_dialogue="违约判断，要回到约定和证据。",
    ),
    "traffic_evidence": _variants(
        title="事故现场一挪车，证据就没了吗？｜15秒剧情化普法",
        premise="事故当事人在现场慌乱挪车，律师引导核对现场影像、认定材料、病历和费用凭证。",
        first_scene="阴天城市路口，两辆车已停到安全区域，地面仍有刹车痕和散落的小碎片",
        first_action="当事人举着手机来回比对现场照片和当前位置，手指停在一张模糊照片上",
        first_emotion="呼吸偏快、担心证据丢失，但努力回忆；说到“挪车”时回头看向路口",
        first_dialogue="事故后挪了车，证据就没了吗？",
        evidence_action="律师把现场影像、认定材料、病历和票据分四组排开，当事人逐项确认拍摄时间",
        second_dialogue="先留现场、认定、病历和票据。",
        third_action="律师用时间线连接事故、就诊和费用节点，当事人补拍票据全貌并收进透明文件袋",
        third_dialogue="再核责任与损失，别漏时间线。",
    ),
    "general_evidence": _variants(
        title="一句“肯定能赢”，为什么不能信？｜15秒剧情化普法",
        premise="当事人带着网络上的确定性结论咨询，律师把主体、时间、事实和材料逐项拆开。",
        first_scene="夜晚地铁站出口，当事人停在灯箱旁，手机里是一条醒目的确定性法律结论",
        first_action="当事人放大手机上的结论，又切回自己保存的零散材料，神情逐渐迟疑",
        first_emotion="先被结论鼓动，随后意识到事实不完整；语气从笃定转为疑问",
        first_dialogue="网上都说肯定能赢，真的一样吗？",
        evidence_action="律师把主体、时间、事实和材料四张无字色块卡片依次排开，当事人逐项放上自己的材料",
        second_dialogue="先核主体、时间、事实和材料。",
        third_action="律师收起网络截图，只保留原始材料和时间线，当事人在清单上勾出待补项目",
        third_dialogue="规则不能脱离事实，个案要核验。",
    ),
}


def render_script_markdown(script: DetailedVideoScript, *, include_model_prompts: bool = True) -> str:
    """Render the rich script only; omit traffic ranking and source evidence."""
    lines = [
        f"# {script.title}",
        "",
        f"成片规格：{script.style}；{script.aspect_ratio}；总时长约 {script.target_duration_seconds:g} 秒。",
        "",
        f"剧情前提：{script.premise}",
        "",
        *([f"核心观点：{script.core_message}", "", f"开场问题：{script.dramatic_question}", "",
           f"本片结局：{script.resolution}", "", f"收尾台词：{script.closing_line}", ""] if script.core_message else []),
        "## 人物定妆与表演弧线",
        "",
    ]
    for character in script.characters:
        lines.extend(
            [
                f"### {character.name}",
                "",
                f"人物身份：{character.identity}",
                "",
                f"外形与服装：{character.appearance}；{character.wardrobe}",
                "",
                f"情绪与表演：{character.performance_arc}",
                "",
            ]
        )
    lines.extend(["## 完整分镜", "", "声音规则：无旁白、无解说配音、无内心独白；通过场内人物动作与对白推进。", ""])
    for shot in script.shots:
        lines.extend(
            [
                f"### {shot.shot_id}｜{shot.start_seconds:g}—{shot.end_seconds:g} 秒",
                "",
                f"剧情作用：{shot.narrative_purpose}",
                "",
                f"场景：{shot.scene}",
                "",
                f"画面结构／构图：{shot.composition or '历史稿未提供'}",
                "",
                f"光线：{shot.lighting or '历史稿未提供'}",
                "",
                f"景别／机位／运镜：{shot.camera}",
                "",
                f"站位与视线：{shot.blocking}",
                "",
                f"首帧：{shot.start_frame or '历史稿未提供'}",
                "",
                f"动作：{shot.action}",
                "",
                f"表演：{shot.emotion_and_performance}",
                "",
                f"对白｜{shot.dialogue_speaker}：{shot.dialogue}" if shot.dialogue else "对白：无（静默动作镜头）",
                "",
                f"声音：{shot.audio}",
                "",
                f"尾帧：{shot.end_frame or '历史稿未提供'}",
                "",
                f"剪辑衔接：{shot.transition or '历史稿未提供'}",
                "",
                f"连续性：{shot.continuity}",
                "",
            ]
        )
        if include_model_prompts:
            lines.extend(["<details><summary>本镜视频提示词（仅存稿，尚未提交）</summary>",
                          "", shot.model_prompt_zh, "", "</details>", ""])
    lines.extend(
        [
            "## 全片连续性约束",
            "",
            *(f"- {item}" for item in script.global_continuity),
            "",
            f"负面约束：{script.negative_constraints}",
            "",
            f"审核提示：{script.legal_review_note}",
            "",
        ]
    )
    return "\n".join(lines)


def render_script_pair_markdown(scripts) -> str:
    """Persist the same complete storyboard for CLI review and browser display."""
    lines = ['# 双剧本分镜审核稿', '', '由项目编剧模型生成；停在生成视频之前，等待用户审核。', '']
    for script in scripts:
        label = '短视频' if script.format_kind == 'short' else '长视频'
        lines.extend([f'## {label} · {script.target_duration_seconds:g} 秒', '',
                      render_script_markdown(script, include_model_prompts=False), '', '---', ''])
    return '\n'.join(lines)
