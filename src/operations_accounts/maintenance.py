"""Read-only account health and operations maintenance workflows."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Literal

from src.platform_adapter.models import CommentQuery
from src.platform_adapter.douyin_playback import (
    DouyinRelevantPlaybackController,
    PlaybackOptions,
    enrich_candidate_engagement_signals,
)
from src.trend_intelligence.providers import (
    DouyinWebTrendProvider,
    TrendCollectionRequest,
    estimate_douyin_planned_pages,
)
from src.trend_intelligence.research_workflow import AccountVideoResearchWorkflow
from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourceProvider,
)

from .repository import AccountRuntimeUnavailable
from .runtime import AccountRuntimeError, AccountRuntimeService


MaintenanceMode = Literal["daily", "pre-publish", "playback", "post-publish"]
MAINTENANCE_LOG_DIR = Path("data/account_maintenance")
_COLLECTED_FIELDS = frozenset(
    {
        "video_id",
        "url",
        "title",
        "author",
        "keyword",
        "sort",
        "rank",
        "displayed_metrics",
        "published_at",
        "hashtags",
        "duration_seconds",
        "relevance_score",
        "tag_relationships",
        "tag_traffic_snapshots",
    }
)


@dataclass(slots=True)
class AccountMaintenanceResult:
    run_id: str
    account_key: str
    account_uuid: str = ""
    mode: MaintenanceMode = "daily"
    status: str = "running"
    login_healthy: bool = False
    identity: str = ""
    collected_count: int = 0
    unique_relevant_videos: int = 0
    skipped_irrelevant: int = 0
    synced_videos: int = 0
    synced_comments: int = 0
    published_data_sync_completed: bool = False
    interaction_actions: int = 0
    playback_candidates: int = 0
    playback_verified_videos: int = 0
    actual_watch_seconds: float = 0.0
    likes_performed: int = 0
    comments_sent: int = 0
    playback_items: list[dict[str, object]] = field(default_factory=list)
    interaction_policy: dict[str, object] = field(default_factory=dict)
    success_criteria: dict[str, bool] = field(default_factory=dict)
    video_records: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""
    started_at: str = ""
    finished_at: str = ""
    log_path: str = ""


class _MaintenanceRunFailed(RuntimeError):
    pass


class AccountMaintenanceService:
    """Run bound-account health, research, playback and owned-data sync."""

    MODE_LIMITS = {
        # Maintenance modes can be composed in one operations session. A fixed
        # account-wide delay made a read-only health check block later playback,
        # so maintenance now relies on the mutex and circuit breaker instead.
        "daily": (20, 0),
        "pre-publish": (20, 0),
        "playback": (3, 0),
        "post-publish": (20, 0),
    }

    def __init__(
        self,
        *,
        runtime: AccountRuntimeService | None = None,
        research_factory: Callable[[], AccountVideoResearchWorkflow] | None = None,
        adapter_factory: Callable[..., object] | None = None,
        playback_factory: Callable[..., object] | None = None,
        log_dir: str | Path = MAINTENANCE_LOG_DIR,
    ) -> None:
        self.runtime = runtime or AccountRuntimeService()
        self.research_factory = research_factory or AccountVideoResearchWorkflow
        self.adapter_factory = adapter_factory
        self.playback_factory = playback_factory
        self.log_dir = Path(log_dir)

    def run(
        self,
        account_key: str,
        mode: MaintenanceMode,
        *,
        authorization_reference: str = "",
        headless: bool = True,
        playback_options: PlaybackOptions | None = None,
    ) -> AccountMaintenanceResult:
        if mode not in self.MODE_LIMITS:
            raise ValueError(f"不支持的账号维护模式：{mode}")
        result = AccountMaintenanceResult(
            run_id=f"maintenance:{uuid.uuid4().hex}",
            account_key=account_key,
            mode=mode,
            started_at=_utc_now(),
        )
        try:
            context = self.runtime.resolve(account_key)
            result.account_uuid = context.account_uuid
            result.identity = context.identity_label
            daily_limit, cooldown_seconds = self.MODE_LIMITS[mode]
            with self.runtime.operation_lease(
                context,
                operation=f"maintenance:{mode}",
                daily_limit=daily_limit,
                cooldown_seconds=cooldown_seconds,
            ):
                identity_session = context.create_browser_session(headless=headless)
                try:
                    check = self.runtime.verify_identity(
                        context,
                        session=identity_session,
                    )
                finally:
                    identity_session.stop()
                result.login_healthy = check.healthy
                if not check.healthy:
                    result.message = check.message
                    raise _MaintenanceRunFailed(check.message)
                if mode in {"daily", "pre-publish", "playback"}:
                    self._run_research(
                        result,
                        context,
                        authorization_reference=authorization_reference,
                        headless=headless,
                    )
                    if mode == "playback":
                        self._run_playback(
                            result,
                            context,
                            options=playback_options or PlaybackOptions(),
                            headless=headless,
                            authorization_reference=authorization_reference,
                        )
                else:
                    self._run_post_publish(result, context, headless=headless)
                self._evaluate_success(result)
                if result.status != "completed":
                    raise _MaintenanceRunFailed(result.message)
        except (AccountRuntimeError, AccountRuntimeUnavailable, _MaintenanceRunFailed) as exc:
            if result.status == "running":
                result.status = "blocked"
            result.message = result.message or str(exc)
            if str(exc) and str(exc) not in result.warnings:
                result.warnings.append(str(exc))
        except Exception as exc:
            result.status = "failed"
            result.message = f"{type(exc).__name__}: {exc}"
            result.warnings.append(result.message)
        finally:
            result.interaction_actions = result.likes_performed + result.comments_sent
            result.finished_at = _utc_now()
            self._write_log(result)
        return result

    def _run_research(
        self,
        result: AccountMaintenanceResult,
        context,
        *,
        authorization_reference: str,
        headless: bool,
    ) -> None:
        if not authorization_reference.strip():
            result.message = "相关内容调研需要填写授权说明或工单编号。"
            raise _MaintenanceRunFailed(result.message)
        keywords = context.profile.seed_keywords[:2]
        if not keywords:
            result.message = "账号策略没有种子关键词，无法进行相关内容调研。"
            raise _MaintenanceRunFailed(result.message)
        pre_publish = result.mode == "pre-publish"
        playback_mode = result.mode == "playback"
        request = TrendCollectionRequest(
            keywords=keywords,
            limit_per_sort=15 if playback_mode else (12 if pre_publish else 6),
            sorts=("comprehensive", "most_liked", "latest")
            if pre_publish or playback_mode
            else ("comprehensive", "latest"),
            headless=headless,
            web_crawler_enabled=True,
            expand_related_tags=pre_publish or playback_mode,
            max_related_tags_per_keyword=2 if pre_publish or playback_mode else 0,
            max_total_related_tags=4 if pre_publish or playback_mode else 0,
        )
        policy = _maintenance_policy(
            authorization_reference,
            planned_pages=estimate_douyin_planned_pages(request),
        )
        research = self.research_factory().run(
            context.profile,
            DouyinWebTrendProvider.for_account(context.account_key),
            request,
            policy=policy,
            max_content_candidates=80 if playback_mode else (40 if pre_publish else 16),
        )
        result.collected_count = research.collected_observations
        result.unique_relevant_videos = research.unique_videos
        result.video_records = research.video_records
        result.warnings.extend(research.warnings)
        for warning in research.warnings:
            if warning.startswith("账号相关度预检："):
                import re

                match = re.search(r"跳过\s*(\d+)\s*条", warning)
                if match:
                    result.skipped_irrelevant = int(match.group(1))
        if research.status not in {"completed", "partial"}:
            result.message = research.stopped_reason or "相关内容调研没有完成。"
            raise _MaintenanceRunFailed(result.message)
        if pre_publish:
            self._sync_owned_feedback(
                result,
                context,
                headless=headless,
                required=False,
            )

    def _run_playback(
        self,
        result: AccountMaintenanceResult,
        context,
        *,
        options: PlaybackOptions,
        headless: bool,
        authorization_reference: str,
    ) -> None:
        options.validate()
        usage = self._interaction_usage(context.account_key)
        candidates = enrich_candidate_engagement_signals(
            _select_playback_candidates(
                result.video_records,
                min_relevance_score=options.min_relevance_score,
                max_videos=options.max_videos,
                exclude_video_ids=usage["recent_played_video_ids"],
            )
        )
        result.playback_candidates = len(candidates)
        if not candidates:
            result.message = (
                f"没有达到相关度阈值 {options.min_relevance_score:g} 的播放候选。"
            )
            raise _MaintenanceRunFailed(result.message)

        ratio_plan = _build_dynamic_interaction_plan(
            candidates,
            verified_playbacks_today=int(usage["verified_playbacks_today"]),
            likes_today=int(usage["likes_today"]),
            comments_today=int(usage["comments_today"]),
            base_like_ratio=options.base_like_ratio,
            base_comment_ratio=options.base_comment_ratio,
        )
        like_budget = int(ratio_plan["remaining_like_budget"]) if options.auto_like else 0
        comment_budget = (
            int(ratio_plan["remaining_comment_budget"])
            if options.auto_comment
            else 0
        )
        if options.max_likes > 0:
            like_budget = min(like_budget, int(options.max_likes))
        if options.max_comments > 0:
            comment_budget = min(comment_budget, int(options.max_comments))
        # A short playback run cannot safely satisfy the 30-minute interval twice.
        comment_budget = min(comment_budget, 1)
        last_comment_at = _parse_utc(usage["last_comment_at"])
        if (
            comment_budget > 0
            and last_comment_at is not None
            and datetime.now(timezone.utc) - last_comment_at < timedelta(minutes=30)
        ):
            comment_budget = 0
            result.warnings.append("自动评论仍在 30 分钟冷却期，本次只执行播放/点赞。")

        effective_options = PlaybackOptions(
            max_videos=options.max_videos,
            per_video_seconds=options.per_video_seconds,
            total_minutes=options.total_minutes,
            min_relevance_score=options.min_relevance_score,
            auto_like=options.auto_like and like_budget > 0,
            auto_comment=options.auto_comment and comment_budget > 0,
            base_like_ratio=float(ratio_plan["adaptive_like_ratio"]),
            base_comment_ratio=float(ratio_plan["adaptive_comment_ratio"]),
            decision_seed=result.run_id,
            verified_playbacks_before=int(usage["verified_playbacks_today"]),
            likes_before=int(usage["likes_today"]),
            comments_before=int(usage["comments_today"]),
            max_likes=like_budget,
            max_comments=comment_budget,
        )
        result.interaction_policy = {
            "bound_public_uid": context.binding.public_uid,
            "authorization_reference_hash": "sha256:" + hashlib.sha256(
                authorization_reference.strip().encode("utf-8")
            ).hexdigest(),
            "requested_auto_like": bool(options.auto_like),
            "requested_auto_comment": bool(options.auto_comment),
            "budget_mode": "dynamic_daily_ratio",
            "verified_playbacks_today_before_run": usage["verified_playbacks_today"],
            "projected_verified_playbacks": ratio_plan["projected_verified_playbacks"],
            "base_like_ratio": round(float(options.base_like_ratio), 4),
            "adaptive_like_ratio": ratio_plan["adaptive_like_ratio"],
            "base_comment_ratio": round(float(options.base_comment_ratio), 4),
            "adaptive_comment_ratio": ratio_plan["adaptive_comment_ratio"],
            "candidate_quality_score": ratio_plan["candidate_quality_score"],
            "daily_like_target": ratio_plan["daily_like_target"],
            "daily_comment_target": ratio_plan["daily_comment_target"],
            "likes_today_before_run": usage["likes_today"],
            "comments_today_before_run": usage["comments_today"],
            "like_signal_counts": ratio_plan["like_signal_counts"],
            "recent_played_videos_excluded": len(usage["recent_played_video_ids"]),
            "recent_playback_lookback_days": 7,
            "same_author_comment_daily_cap": 1,
            "comment_cooldown_seconds": 1800,
            "optional_like_run_ceiling": int(options.max_likes),
            "optional_comment_run_ceiling": int(options.max_comments),
            "effective_like_budget": like_budget,
            "effective_comment_budget": comment_budget,
            "advertising_filter": True,
            "comment_similarity_threshold": 0.82,
        }
        if options.auto_like and like_budget == 0:
            result.warnings.append("当前动态点赞比例预算为 0，本次不会点赞。")
        if options.auto_comment and comment_budget == 0:
            result.warnings.append("当前动态评论比例预算或冷却额度为 0，本次不会评论。")
        session = context.create_browser_session(headless=headless)
        try:
            playback_identity = self.runtime.verify_identity(context, session=session)
            if not playback_identity.healthy:
                result.message = playback_identity.message
                raise _MaintenanceRunFailed(playback_identity.message)
            controller = (
                self.playback_factory(session)
                if self.playback_factory is not None
                else DouyinRelevantPlaybackController(session)
            )
            playback = controller.run(
                candidates,
                effective_options,
                domain_strategy_id=context.profile.domain_strategy_id,
                recent_account_comments=usage["recent_comments"],
                blocked_comment_authors=usage["commented_authors_today"],
            )
        finally:
            session.stop()
        result.playback_verified_videos = playback.verified_videos
        result.actual_watch_seconds = playback.actual_watch_seconds
        result.likes_performed = playback.likes_performed
        result.comments_sent = playback.comments_sent
        result.playback_items = [asdict(item) for item in playback.items]
        realized_playbacks = (
            int(usage["verified_playbacks_today"]) + playback.verified_videos
        )
        realized_like_target = _rounded_ratio_target(
            realized_playbacks,
            float(ratio_plan["adaptive_like_ratio"]),
        )
        realized_comment_target = _rounded_ratio_target(
            realized_playbacks,
            float(ratio_plan["adaptive_comment_ratio"]),
        )
        result.interaction_policy.update(
            {
                "realized_verified_playbacks": realized_playbacks,
                "realized_daily_like_target": realized_like_target,
                "realized_daily_comment_target": realized_comment_target,
                "realized_like_budget": min(
                    like_budget,
                    max(0, realized_like_target - int(usage["likes_today"])),
                ),
                "realized_comment_budget": min(
                    comment_budget,
                    max(
                        0,
                        realized_comment_target - int(usage["comments_today"]),
                    ),
                ),
            }
        )
        result.warnings.extend(playback.warnings)
        if playback.status != "completed" or playback.verified_videos < 1:
            result.message = "相关视频播放未通过真实进度校验。"
            raise _MaintenanceRunFailed(result.message)

    def _interaction_usage(self, account_key: str) -> dict[str, object]:
        account_dir = self.log_dir / account_key
        today = datetime.now(timezone.utc).date()
        likes_today = 0
        comments_today = 0
        verified_playbacks_today = 0
        recent_played_video_ids: set[str] = set()
        commented_authors_today: set[str] = set()
        recent_comments: list[str] = []
        last_comment_at = ""
        if not account_dir.exists():
            return {
                "likes_today": 0,
                "comments_today": 0,
                "verified_playbacks_today": 0,
                "recent_played_video_ids": [],
                "commented_authors_today": [],
                "recent_comments": [],
                "last_comment_at": "",
            }
        paths = sorted(
            account_dir.glob("maintenance_*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:100]
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            finished_at = str(payload.get("finished_at") or "")
            finished = _parse_utc(finished_at)
            is_today = bool(finished and finished.date() == today)
            is_recent = bool(
                finished
                and datetime.now(timezone.utc) - finished <= timedelta(days=7)
            )
            if is_today:
                likes_today += int(payload.get("likes_performed") or 0)
                comments_today += int(payload.get("comments_sent") or 0)
                verified_playbacks_today += int(
                    payload.get("playback_verified_videos") or 0
                )
            for item in payload.get("playback_items") or []:
                if not isinstance(item, dict):
                    continue
                if is_recent and item.get("playback_verified"):
                    video_id = str(item.get("video_id") or "").strip()
                    if video_id:
                        recent_played_video_ids.add(video_id)
                if not item.get("comment_sent"):
                    continue
                text = str(item.get("comment_text") or "").strip()
                if text and text not in recent_comments:
                    recent_comments.append(text)
                if is_today:
                    author = str(item.get("author") or "").strip()
                    if author:
                        commented_authors_today.add(author)
                    if finished_at and (not last_comment_at or finished_at > last_comment_at):
                        last_comment_at = finished_at
        return {
            "likes_today": likes_today,
            "comments_today": comments_today,
            "verified_playbacks_today": verified_playbacks_today,
            "recent_played_video_ids": sorted(recent_played_video_ids),
            "commented_authors_today": sorted(commented_authors_today),
            "recent_comments": recent_comments[:50],
            "last_comment_at": last_comment_at,
        }

    def _run_post_publish(self, result: AccountMaintenanceResult, context, *, headless: bool) -> None:
        self._sync_owned_feedback(
            result,
            context,
            headless=headless,
            required=True,
        )

    def _sync_owned_feedback(
        self,
        result: AccountMaintenanceResult,
        context,
        *,
        headless: bool,
        required: bool,
    ) -> None:
        if self.adapter_factory is None:
            from src.platform_adapter.douyin_adapter import DouyinAdapter

            adapter = DouyinAdapter.for_account(context.account_key, headless=headless)
        else:
            adapter = self.adapter_factory(context.account_key, headless=headless)
        try:
            sync = adapter.sync_videos(page_limit=3)
            if not sync.success:
                message = sync.message or "作品数据同步失败。"
                if required:
                    result.message = message
                    raise _MaintenanceRunFailed(message)
                result.warnings.append(f"自有作品用户反馈暂未同步：{message}")
                return
            result.published_data_sync_completed = True
            result.synced_videos = len(sync.videos)
            for video in sync.videos[:30]:
                if not video.video_id:
                    continue
                comments = adapter.fetch_comments(CommentQuery(post_id=video.video_id))
                if comments.success:
                    result.synced_comments += len(comments.comments)
        finally:
            adapter.close()

    @staticmethod
    def _evaluate_success(result: AccountMaintenanceResult) -> None:
        criteria = {"login_healthy": result.login_healthy}
        if result.mode in {"daily", "pre-publish", "playback"}:
            criteria["relevant_distinct_content_collected"] = (
                result.unique_relevant_videos > 0
            )
        else:
            criteria["published_data_synced"] = (
                result.published_data_sync_completed
            )
        if result.mode == "playback":
            criteria["verified_playback_completed"] = result.playback_verified_videos > 0
            like_budget = int(result.interaction_policy.get("realized_like_budget") or 0)
            comment_budget = int(
                result.interaction_policy.get("realized_comment_budget") or 0
            )
            criteria["interaction_policy_respected"] = (
                result.likes_performed <= like_budget
                and result.comments_sent <= comment_budget
            )
        else:
            criteria["external_interactions_zero"] = result.interaction_actions == 0
        result.success_criteria = criteria
        result.status = "completed" if all(criteria.values()) else "partial"
        result.message = (
            "账号健康与运营维护完成。"
            if result.status == "completed"
            else "账号维护只完成了部分成功标准。"
        )

    def _write_log(self, result: AccountMaintenanceResult) -> None:
        account_dir = self.log_dir / result.account_key
        account_dir.mkdir(parents=True, exist_ok=True)
        safe_run_id = result.run_id.replace(":", "_")
        path = account_dir / f"{safe_run_id}.json"
        result.log_path = str(path)
        path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _maintenance_policy(reference: str, *, planned_pages: int) -> SourcePolicy:
    reference_hash = "sha256:" + hashlib.sha256(
        reference.strip().encode("utf-8")
    ).hexdigest()
    cap = max(1, min(30, int(planned_pages)))
    return SourcePolicy(
        policy_id=f"account-maintenance-{datetime.now(timezone.utc).date().isoformat()}",
        provider=SourceProvider.AUTHORIZED_WEB,
        status=PolicyStatus.APPROVED,
        allowed_hosts=("www.douyin.com",),
        allowed_path_prefixes=("/search",),
        allowed_fields=_COLLECTED_FIELDS,
        allowed_purposes=frozenset({"trend_analysis"}),
        min_interval_seconds=1,
        max_pages_per_run=cap,
        daily_page_cap=90,
        raw_retention_days=0,
        authorization_reference_hash=reference_hash,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _select_playback_candidates(
    records: list[dict[str, object]],
    *,
    min_relevance_score: float,
    max_videos: int,
    exclude_video_ids: Iterable[str] = (),
) -> list[dict[str, object]]:
    excluded = {str(item or "").strip() for item in (exclude_video_ids or [])}
    unique: dict[str, dict[str, object]] = {}
    for record in records:
        video_id = str(record.get("video_id") or "").strip()
        url = str(record.get("url") or "").strip()
        relevance = float(record.get("relevance_score") or 0)
        if (
            not video_id
            or video_id in excluded
            or "/video/" not in url
            or relevance < min_relevance_score
        ):
            continue
        current = unique.get(video_id)
        if current is None or relevance > float(current.get("relevance_score") or 0):
            unique[video_id] = dict(record)
    ranked = sorted(
        unique.values(),
        key=lambda item: (
            float(item.get("relevance_score") or 0),
            int(item.get("visible_metric") or 0),
        ),
        reverse=True,
    )
    return ranked[: max(1, int(max_videos))]


def _build_dynamic_interaction_plan(
    candidates: list[dict[str, object]],
    *,
    verified_playbacks_today: int,
    likes_today: int,
    comments_today: int,
    base_like_ratio: float,
    base_comment_ratio: float,
) -> dict[str, object]:
    performance_scores = [
        _clamp(float(item.get("like_performance_score") or 0), 0.0, 1.0)
        for item in candidates
    ]
    relevance_scores = [
        _clamp(float(item.get("relevance_score") or 0) / 100, 0.0, 1.0)
        for item in candidates
    ]
    performance_quality = (
        sum(performance_scores) / len(performance_scores)
        if performance_scores
        else 0.25
    )
    relevance_quality = (
        sum(relevance_scores) / len(relevance_scores)
        if relevance_scores
        else 0.0
    )
    candidate_quality = 0.65 * performance_quality + 0.35 * relevance_quality
    quality_multiplier = 0.65 + 0.70 * candidate_quality
    adaptive_like_ratio = _clamp(
        float(base_like_ratio) * quality_multiplier,
        0.0,
        0.80,
    )
    adaptive_comment_ratio = _clamp(
        float(base_comment_ratio) * quality_multiplier,
        0.0,
        0.20,
    )
    projected_verified = max(0, int(verified_playbacks_today)) + len(candidates)
    daily_like_target = _rounded_ratio_target(projected_verified, adaptive_like_ratio)
    daily_comment_target = _rounded_ratio_target(
        projected_verified,
        adaptive_comment_ratio,
    )
    signal_counts: dict[str, int] = {}
    for item in candidates:
        kind = str(item.get("like_signal_kind") or "unavailable")
        signal_counts[kind] = signal_counts.get(kind, 0) + 1
    return {
        "projected_verified_playbacks": projected_verified,
        "candidate_quality_score": round(candidate_quality, 4),
        "adaptive_like_ratio": round(adaptive_like_ratio, 4),
        "adaptive_comment_ratio": round(adaptive_comment_ratio, 4),
        "daily_like_target": daily_like_target,
        "daily_comment_target": daily_comment_target,
        "remaining_like_budget": max(0, daily_like_target - max(0, int(likes_today))),
        "remaining_comment_budget": max(
            0,
            daily_comment_target - max(0, int(comments_today)),
        ),
        "like_signal_counts": signal_counts,
    }


def _rounded_ratio_target(sample_count: int, ratio: float) -> int:
    return max(0, int(max(0, sample_count) * _clamp(ratio, 0.0, 1.0) + 0.5))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
