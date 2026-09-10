"""Relevant-video playback and guarded interaction helpers for Douyin."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Iterable, Mapping

from src.platform_adapter.douyin_identity import has_visible_douyin_challenge


_VIDEO_ID_PATTERN = re.compile(r"/video/(\d{8,})")
_ADVERTISING_PATTERNS = (
    re.compile(r"(?:微信|微\s*信|vx|v信|加v|加微|私信|主页联系|联系我)", re.I),
    re.compile(r"(?:qq|QQ群|进群|群聊|代理|招商|加盟|返利|免费咨询)", re.I),
    re.compile(r"(?:https?://|www\.|[a-z0-9-]+\.(?:com|cn|net))", re.I),
    re.compile(r"(?:1[3-9]\d{9}|\d{5,}号)", re.I),
)
_EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2764\uFE0F]"
)


@dataclass(slots=True)
class PlaybackOptions:
    max_videos: int = 20
    per_video_seconds: int = 90
    total_minutes: int = 20
    min_relevance_score: float = 60.0
    auto_like: bool = False
    auto_comment: bool = False
    base_like_ratio: float = 0.25
    base_comment_ratio: float = 0.05
    decision_seed: str = ""
    verified_playbacks_before: int = 0
    likes_before: int = 0
    comments_before: int = 0
    # Optional emergency per-run ceilings kept for backwards-compatible callers.
    # Zero means the daily ratio budget is the only limit.
    max_likes: int = 0
    max_comments: int = 0

    def validate(self) -> None:
        if not 1 <= int(self.max_videos) <= 20:
            raise ValueError("播放视频数必须在 1 到 20 之间。")
        if not 5 <= int(self.per_video_seconds) <= 300:
            raise ValueError("单条播放上限必须在 5 到 300 秒之间。")
        if not 1 <= int(self.total_minutes) <= 60:
            raise ValueError("总播放时长必须在 1 到 60 分钟之间。")
        if not 0 <= float(self.min_relevance_score) <= 100:
            raise ValueError("相关度阈值必须在 0 到 100 之间。")
        if not 0 <= float(self.base_like_ratio) <= 1:
            raise ValueError("基础点赞比例必须在 0 到 1 之间。")
        if not 0 <= float(self.base_comment_ratio) <= 1:
            raise ValueError("基础评论比例必须在 0 到 1 之间。")
        if not 0 <= int(self.max_likes) <= 20:
            raise ValueError("单次点赞安全上限必须在 0 到 20 之间。")
        if not 0 <= int(self.max_comments) <= 20:
            raise ValueError("单次评论安全上限必须在 0 到 20 之间。")
        if min(
            int(self.verified_playbacks_before),
            int(self.likes_before),
            int(self.comments_before),
        ) < 0:
            raise ValueError("历史播放和互动计数不能小于 0。")


@dataclass(slots=True)
class PlaybackItemResult:
    video_id: str
    title: str
    author: str
    url: str
    relevance_score: float
    planned_watch_seconds: int = 0
    watch_plan_factor: float = 1.0
    watch_plan_basis: str = "content_quality"
    start_current_time: float = 0.0
    end_current_time: float = 0.0
    actual_watch_seconds: float = 0.0
    duration_seconds: float = 0.0
    completion_ratio: float = 0.0
    playback_verified: bool = False
    observed_like_count: int | None = None
    observed_view_count: int | None = None
    observed_like_rate: float | None = None
    like_signal_kind: str = "unavailable"
    like_performance_score: float = 0.0
    like_probability: float = 0.0
    like_decision_value: float | None = None
    like_decision_reason: str = "disabled"
    liked: bool = False
    like_status: str = "disabled"
    liked_at: str = ""
    comment_probability: float = 0.0
    comment_decision_value: float | None = None
    comment_decision_reason: str = "disabled"
    comment_family: str = ""
    comment_text: str = ""
    comment_sent: bool = False
    comment_status: str = "disabled"
    commented_at: str = ""
    error: str = ""


@dataclass(slots=True)
class PlaybackRunResult:
    status: str = "completed"
    items: list[PlaybackItemResult] = field(default_factory=list)
    verified_videos: int = 0
    actual_watch_seconds: float = 0.0
    likes_performed: int = 0
    comments_sent: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SafeCommentDecision:
    allowed: bool
    text: str = ""
    family: str = ""
    reason: str = ""


class SafeCommentPolicy:
    """Build a short original comment from an observed comment style family."""

    _TEMPLATES = {
        "legal_services": {
            "emoji": ("讲得很清楚，学到了👏", "这个提醒很有必要👍"),
            "question": ("这个问题确实值得关注，感谢讲解。", "又学到一个容易忽略的法律点。"),
            "agreement": ("讲得很清楚，学到了。", "案例讲解得很明白，感谢普法。"),
            "general": ("这个法律提醒很实用，收藏学习。", "感谢分享，关键点讲得很清楚。"),
        },
        "novel_promotion": {
            "emoji": ("这个节奏太抓人了👏", "期待后续🔥"),
            "question": ("这个伏笔后面会怎么收？", "接下来是不是还有反转？"),
            "agreement": ("这个设定确实很有吸引力。", "节奏很顺，继续追。"),
            "general": ("开头很抓人，期待下一段。", "人物冲突一下就立住了。"),
        },
    }

    def build(
        self,
        *,
        domain_strategy_id: str,
        video_title: str,
        visible_comments: Iterable[str],
        recent_account_comments: Iterable[str] = (),
    ) -> SafeCommentDecision:
        observed = [
            _normalize_comment(item)
            for item in visible_comments
            if _normalize_comment(item)
            and not is_advertising_comment(item)
        ]
        family = _comment_family(observed)
        templates = self._TEMPLATES.get(
            domain_strategy_id,
            self._TEMPLATES["legal_services"],
        )
        candidates = list(templates.get(family, templates["general"]))
        if not candidates:
            return SafeCommentDecision(False, family=family, reason="no_approved_template")
        seed = hashlib.sha256(
            f"{domain_strategy_id}|{video_title}|{family}".encode("utf-8")
        ).digest()[0]
        candidates = candidates[seed % len(candidates) :] + candidates[: seed % len(candidates)]
        comparison_pool = [*observed, *(_normalize_comment(item) for item in recent_account_comments)]
        for candidate in candidates:
            if is_advertising_comment(candidate):
                continue
            if any(comment_similarity(candidate, other) >= 0.82 for other in comparison_pool if other):
                continue
            return SafeCommentDecision(True, text=candidate, family=family, reason="approved_original_variant")
        return SafeCommentDecision(
            False,
            family=family,
            reason="duplicate_or_unsafe_comment",
        )


class DouyinRelevantPlaybackController:
    """Play analyzed video candidates and optionally perform guarded interactions."""

    def __init__(self, session, *, comment_policy: SafeCommentPolicy | None = None):
        self.session = session
        self.comment_policy = comment_policy or SafeCommentPolicy()

    def run(
        self,
        candidates: Iterable[dict[str, object]],
        options: PlaybackOptions,
        *,
        domain_strategy_id: str,
        recent_account_comments: Iterable[str] = (),
        blocked_comment_authors: Iterable[str] = (),
    ) -> PlaybackRunResult:
        options.validate()
        result = PlaybackRunResult()
        deadline = time.monotonic() + int(options.total_minutes) * 60
        likes_remaining = int(options.max_likes) if options.auto_like else 0
        comments_remaining = int(options.max_comments) if options.auto_comment else 0
        blocked_authors = {str(item or "").strip() for item in blocked_comment_authors}
        recent_comments = [str(item or "").strip() for item in recent_account_comments]

        prepared_candidates = enrich_candidate_engagement_signals(
            list(candidates)[: int(options.max_videos)]
        )
        for index, candidate in enumerate(prepared_candidates):
            remaining_wall_seconds = int(deadline - time.monotonic())
            if remaining_wall_seconds < 2:
                result.warnings.append("达到本次总播放时长上限。")
                break
            planned_seconds, watch_factor = _content_weighted_watch_plan(
                candidate,
                per_video_cap=int(options.per_video_seconds),
                remaining_wall_seconds=remaining_wall_seconds,
            )
            item = self._play_candidate(
                candidate,
                planned_seconds=planned_seconds,
            )
            item.watch_plan_factor = watch_factor
            result.items.append(item)
            if not item.playback_verified:
                continue
            result.verified_videos += 1
            result.actual_watch_seconds += item.actual_watch_seconds

            item.like_probability = _interaction_probability(
                base_ratio=options.base_like_ratio,
                performance_score=item.like_performance_score,
                relevance_score=item.relevance_score,
                action="like",
            )
            if options.auto_like:
                item.like_decision_value = _stable_decision_value(
                    options.decision_seed,
                    item.video_id,
                    "like",
                    index,
                )
                live_like_target = _rounded_ratio_target(
                    int(options.verified_playbacks_before) + result.verified_videos,
                    options.base_like_ratio,
                )
                live_like_allowance = live_like_target - int(options.likes_before) - result.likes_performed
                if likes_remaining <= 0 or live_like_allowance <= 0:
                    item.like_status = "ratio_budget_exhausted"
                    item.like_decision_reason = "live_daily_ratio_budget_exhausted"
                elif item.like_decision_value > item.like_probability:
                    item.like_status = "probability_skipped"
                    item.like_decision_reason = "adaptive_probability_not_met"
                else:
                    item.like_decision_reason = "adaptive_probability_met"
                    performed, status = self._like_current_video()
                    item.liked = performed
                    item.like_status = status
                    if performed:
                        item.liked_at = _utc_now()
                        likes_remaining -= 1
                        result.likes_performed += 1

            if not options.auto_comment:
                continue
            item.comment_probability = _interaction_probability(
                base_ratio=options.base_comment_ratio,
                performance_score=item.like_performance_score,
                relevance_score=item.relevance_score,
                action="comment",
            )
            item.comment_decision_value = _stable_decision_value(
                options.decision_seed,
                item.video_id,
                "comment",
                index,
            )
            if comments_remaining <= 0:
                item.comment_status = "quota_exhausted"
                item.comment_decision_reason = "daily_ratio_budget_exhausted"
                continue
            live_comment_target = _rounded_ratio_target(
                int(options.verified_playbacks_before) + result.verified_videos,
                options.base_comment_ratio,
            )
            live_comment_allowance = (
                live_comment_target
                - int(options.comments_before)
                - result.comments_sent
            )
            if live_comment_allowance <= 0:
                item.comment_status = "ratio_budget_exhausted"
                item.comment_decision_reason = "live_daily_ratio_budget_exhausted"
                continue
            if item.comment_decision_value > item.comment_probability:
                item.comment_status = "probability_skipped"
                item.comment_decision_reason = "adaptive_probability_not_met"
                continue
            if item.author.strip() and item.author.strip() in blocked_authors:
                item.comment_status = "author_daily_limit"
                item.comment_decision_reason = "author_daily_limit"
                continue
            item.comment_decision_reason = "adaptive_probability_met"
            visible_comments = self._open_and_read_comments()
            decision = self.comment_policy.build(
                domain_strategy_id=domain_strategy_id,
                video_title=item.title,
                visible_comments=visible_comments,
                recent_account_comments=recent_comments,
            )
            item.comment_family = decision.family
            item.comment_text = decision.text
            if not decision.allowed:
                item.comment_status = decision.reason
                continue
            sent = self._submit_comment(decision.text)
            item.comment_sent = sent
            item.comment_status = "sent" if sent else "submit_failed"
            if sent:
                item.commented_at = _utc_now()
                comments_remaining -= 1
                result.comments_sent += 1
                recent_comments.append(decision.text)
                if item.author.strip():
                    blocked_authors.add(item.author.strip())

        if not result.items:
            result.status = "partial"
            result.warnings.append("没有可播放的高相关候选视频。")
        elif result.verified_videos == 0:
            result.status = "partial"
            result.warnings.append("没有视频通过真实播放进度校验。")
        result.actual_watch_seconds = round(result.actual_watch_seconds, 2)
        return result

    def _play_candidate(
        self,
        candidate: dict[str, object],
        *,
        planned_seconds: int,
    ) -> PlaybackItemResult:
        video_id = str(candidate.get("video_id") or "").strip()
        url = str(candidate.get("url") or "").strip()
        item = PlaybackItemResult(
            video_id=video_id,
            title=str(candidate.get("title") or ""),
            author=str(candidate.get("author") or ""),
            url=url,
            relevance_score=float(candidate.get("relevance_score") or 0),
            planned_watch_seconds=max(1, int(planned_seconds)),
            observed_like_count=_optional_int(candidate.get("observed_like_count")),
            observed_view_count=_optional_int(candidate.get("observed_view_count")),
            observed_like_rate=_optional_float(candidate.get("observed_like_rate")),
            like_signal_kind=str(candidate.get("like_signal_kind") or "unavailable"),
            like_performance_score=float(
                candidate.get("like_performance_score") or 0
            ),
        )
        try:
            page = self.session.open_page(url)
            page.wait_for_timeout(1800)
            if has_visible_douyin_challenge(page) or _page_looks_blocked(page):
                item.error = "登录页、验证码或安全验证阻止播放。"
                return item
            actual_id = _current_video_id(page)
            if actual_id and actual_id != video_id:
                item.error = f"视频身份不匹配：期望 {video_id}，实际 {actual_id}。"
                return item
            start = _video_state(page)
            if not start.get("found"):
                item.error = "页面未找到可播放视频。"
                return item
            item.start_current_time = float(start.get("current_time") or 0)
            item.duration_seconds = float(start.get("duration") or 0)
            if item.duration_seconds > 0:
                item.planned_watch_seconds = max(
                    1,
                    min(item.planned_watch_seconds, int(item.duration_seconds)),
                )
            _ensure_video_playing(page)
            cumulative = 0.0
            previous = item.start_current_time
            playback_deadline = time.monotonic() + item.planned_watch_seconds + 5
            while time.monotonic() < playback_deadline:
                page.wait_for_timeout(1000)
                state = _video_state(page)
                if not state.get("found"):
                    break
                current = float(state.get("current_time") or 0)
                duration = float(state.get("duration") or item.duration_seconds or 0)
                if current >= previous:
                    cumulative += current - previous
                elif duration > 0 and previous >= duration - 1.5:
                    cumulative += max(0.0, duration - previous) + current
                previous = current
                item.end_current_time = current
                if cumulative >= item.planned_watch_seconds - 0.75:
                    break
                if state.get("paused") and not state.get("ended"):
                    _ensure_video_playing(page)
            item.actual_watch_seconds = round(max(0.0, cumulative), 2)
            item.completion_ratio = (
                round(min(1.0, item.actual_watch_seconds / item.duration_seconds), 4)
                if item.duration_seconds > 0
                else 0.0
            )
            required = max(1.0, item.planned_watch_seconds * 0.75)
            item.playback_verified = item.actual_watch_seconds >= required
            if not item.playback_verified:
                item.error = (
                    f"实际播放 {item.actual_watch_seconds:.1f}s，"
                    f"低于校验要求 {required:.1f}s。"
                )
        except Exception as exc:
            item.error = f"{type(exc).__name__}: {exc}"
        return item

    def _like_current_video(self) -> tuple[bool, str]:
        current_page = _SessionPage(self.session)
        marker = current_page.locator("").evaluate(_MARK_LIKE_TARGET_JS) or {}
        if not marker.get("found"):
            return False, "like_button_missing"
        if marker.get("already_liked"):
            return False, "already_liked"
        try:
            current_page.locator('[data-account-playback-like="1"]').click()
            current_page.wait_for_timeout(700)
            return True, "clicked"
        except Exception as exc:
            return False, f"click_failed:{type(exc).__name__}"

    def _open_and_read_comments(self) -> list[str]:
        page = _SessionPage(self.session)
        marked = bool(page.locator("").evaluate(_MARK_COMMENT_TARGET_JS))
        if marked:
            try:
                page.locator('[data-account-playback-comment="1"]').click()
                page.wait_for_timeout(1200)
            except Exception:
                return []
        try:
            values = page.locator("").evaluate(_READ_VISIBLE_COMMENTS_JS) or []
        except Exception:
            return []
        return [str(item or "").strip() for item in values if str(item or "").strip()][:30]

    def _submit_comment(self, content: str) -> bool:
        if not content or is_advertising_comment(content):
            return False
        page = _SessionPage(self.session)
        marker = page.locator("").evaluate(_MARK_COMMENT_EDITOR_JS) or {}
        if not marker.get("found"):
            return False
        editor = page.locator('[data-account-playback-comment-editor="1"]')
        try:
            editor.click()
            editor.fill(content)
        except Exception:
            try:
                editor.click()
                editor.type(content)
            except Exception:
                return False
        submit_marked = bool(page.locator("").evaluate(_MARK_COMMENT_SUBMIT_JS))
        if not submit_marked:
            return False
        try:
            page.locator('[data-account-playback-comment-submit="1"]').click()
            page.wait_for_timeout(1200)
        except Exception:
            return False
        verification = page.locator("").evaluate(
            """() => {
              const editor = document.querySelector('[data-account-playback-comment-editor="1"]');
              const value = editor ? (editor.value || editor.innerText || '').trim() : '';
              return value.length === 0;
            }"""
        )
        return bool(verification)

class _SessionPage:
    """Address the currently open page without navigating it."""

    def __init__(self, session):
        from src.platform_adapter.browser_session import Page

        self._page = Page(session)

    def __getattr__(self, name):
        return getattr(self._page, name)


def enrich_candidate_engagement_signals(
    candidates: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach auditable like-performance signals without inventing a like rate."""
    prepared: list[dict[str, object]] = []
    signal_rows: list[tuple[str, float | None]] = []
    for source in candidates:
        candidate = dict(source)
        metrics = candidate.get("displayed_metrics")
        nested = metrics if isinstance(metrics, Mapping) else {}
        like_count = _first_metric(
            candidate,
            nested,
            ("like_count", "likes", "digg_count", "observed_like_count"),
        )
        view_count = _first_metric(
            candidate,
            nested,
            ("view_count", "views", "play_count", "observed_view_count"),
        )
        visible_metric = _optional_float(candidate.get("visible_metric"))
        if like_count is not None and view_count and view_count > 0:
            signal_kind = "observed_like_rate"
            comparison_value = max(0.0, like_count / view_count)
            candidate["observed_like_rate"] = round(comparison_value, 6)
        elif like_count is not None:
            signal_kind = "relative_like_count"
            comparison_value = float(max(0, like_count))
            candidate["observed_like_rate"] = None
        elif visible_metric is not None:
            sort_key = str(candidate.get("source_sort") or candidate.get("sort_key") or "")
            signal_kind = (
                "relative_displayed_metric_most_liked"
                if sort_key == "most_liked"
                else "relative_displayed_metric"
            )
            comparison_value = max(0.0, visible_metric)
            candidate["observed_like_rate"] = None
        else:
            signal_kind = "unavailable"
            comparison_value = None
            candidate["observed_like_rate"] = None
        candidate["observed_like_count"] = like_count
        candidate["observed_view_count"] = view_count
        candidate["like_signal_kind"] = signal_kind
        prepared.append(candidate)
        signal_rows.append((signal_kind, comparison_value))

    groups: dict[str, list[float]] = {}
    for kind, value in signal_rows:
        if value is not None:
            groups.setdefault(kind, []).append(value)
    for candidate, (kind, value) in zip(prepared, signal_rows):
        if value is None:
            score = 0.25
        else:
            peer_values = groups[kind]
            percentile = _midrank_percentile(value, peer_values)
            if kind == "observed_like_rate":
                # Ten percent is a strong short-video like rate; retain the
                # within-batch rank while still respecting the absolute rate.
                absolute_score = min(1.0, value / 0.10)
                score = (percentile + absolute_score) / 2
            else:
                score = percentile
        candidate["like_performance_score"] = round(_clamp(score, 0.0, 1.0), 4)
    return prepared


def _first_metric(
    top_level: Mapping[str, object],
    nested: Mapping[str, object],
    keys: tuple[str, ...],
) -> int | None:
    for source in (top_level, nested):
        for key in keys:
            value = _optional_int(source.get(key))
            if value is not None:
                return value
    return None


def _midrank_percentile(value: float, values: list[float]) -> float:
    if len(values) <= 1:
        return 0.5
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return (below + max(0, equal - 1) / 2) / (len(values) - 1)


def _interaction_probability(
    *,
    base_ratio: float,
    performance_score: float,
    relevance_score: float,
    action: str,
) -> float:
    if base_ratio <= 0:
        return 0.0
    performance_multiplier = 0.45 + 1.10 * _clamp(performance_score, 0.0, 1.0)
    relevance_multiplier = 0.70 + 0.30 * _clamp(relevance_score / 100, 0.0, 1.0)
    ceiling = 0.95 if action == "like" else 0.35
    return round(
        _clamp(base_ratio * performance_multiplier * relevance_multiplier, 0.0, ceiling),
        4,
    )


def _content_weighted_watch_plan(
    candidate: Mapping[str, object],
    *,
    per_video_cap: int,
    remaining_wall_seconds: int,
) -> tuple[int, float]:
    relevance = _clamp(float(candidate.get("relevance_score") or 0) / 100, 0.0, 1.0)
    performance = _clamp(
        float(candidate.get("like_performance_score") or 0),
        0.0,
        1.0,
    )
    content_quality = 0.65 * relevance + 0.35 * performance
    factor = _clamp(0.50 + 0.50 * content_quality, 0.50, 1.0)
    planned = int(round(max(1, per_video_cap) * factor))
    if per_video_cap >= 5 and remaining_wall_seconds >= 5:
        planned = max(5, planned)
    planned = max(1, min(planned, per_video_cap, remaining_wall_seconds))
    return planned, round(factor, 4)


def _stable_decision_value(seed: str, video_id: str, action: str, index: int) -> float:
    material = f"{seed or _utc_now()}|{video_id}|{action}|{index}"
    value = int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")
    return round(value / ((1 << 64) - 1), 6)


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _rounded_ratio_target(sample_count: int, ratio: float) -> int:
    return max(0, int(max(0, sample_count) * _clamp(ratio, 0.0, 1.0) + 0.5))


def is_advertising_comment(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    return any(pattern.search(normalized) for pattern in _ADVERTISING_PATTERNS)


def comment_similarity(left: str, right: str) -> float:
    a = _normalize_comment(left)
    b = _normalize_comment(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _normalize_comment(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _comment_family(comments: list[str]) -> str:
    if not comments:
        return "general"
    emoji_heavy = sum(
        1 for item in comments if len(_EMOJI_PATTERN.findall(item)) >= max(1, len(item) // 3)
    )
    if emoji_heavy / len(comments) >= 0.35:
        return "emoji"
    questions = sum(1 for item in comments if "?" in item or "？" in item)
    if questions / len(comments) >= 0.35:
        return "question"
    agreement = sum(
        1
        for item in comments
        if any(term in item for term in ("确实", "支持", "说得对", "学到了", "有道理"))
    )
    return "agreement" if agreement / len(comments) >= 0.25 else "general"


def _current_video_id(page) -> str:
    match = _VIDEO_ID_PATTERN.search(str(page.url or ""))
    if match:
        return match.group(1)
    value = page.locator("").evaluate(
        """() => {
          const node = document.querySelector('[data-e2e-vid], [data-video-id]');
          return node ? (node.getAttribute('data-e2e-vid') || node.getAttribute('data-video-id') || '') : '';
        }"""
    )
    return str(value or "")


def _page_looks_blocked(page) -> bool:
    return bool(
        page.locator("").evaluate(
            r"""() => {
              const text = document.body ? document.body.innerText : '';
              const url = location.href || '';
              return /\/login(?:[/?#]|$)/.test(url)
                || /扫码登录|账号异常|访问异常|风控/.test(text);
            }"""
        )
    )


def _video_state(page) -> dict[str, object]:
    return dict(
        page.locator("").evaluate(
            """() => {
              const visible = element => {
                if (!element) return false;
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && style.opacity !== '0' && rect.width > 8 && rect.height > 8;
              };
              const video = Array.from(document.querySelectorAll('video')).find(visible);
              if (!video) return {found: false};
              return {
                found: true,
                current_time: Number(video.currentTime || 0),
                duration: Number.isFinite(video.duration) ? Number(video.duration) : 0,
                paused: Boolean(video.paused),
                ended: Boolean(video.ended),
                ready_state: Number(video.readyState || 0)
              };
            }"""
        )
        or {}
    )


def _ensure_video_playing(page) -> bool:
    return bool(
        page.locator("").evaluate(
            """() => {
              const video = Array.from(document.querySelectorAll('video')).find(element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                  && rect.width > 8 && rect.height > 8;
              });
              if (!video) return false;
              video.muted = true;
              video.play().catch(() => {});
              return true;
            }"""
        )
    )


_MARK_LIKE_TARGET_JS = """() => {
  document.querySelectorAll('[data-account-playback-like]').forEach(node => node.removeAttribute('data-account-playback-like'));
  const visible = node => {
    if (!node) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 8 && rect.height > 8;
  };
  const selectors = [
    '[data-e2e="like-icon"]', '[data-e2e="video-like"]',
    '[aria-label*="点赞"]', '[aria-label*="喜欢"]'
  ];
  let target = selectors.map(selector => Array.from(document.querySelectorAll(selector)).find(visible)).find(Boolean);
  if (!target) {
    const rows = Array.from(document.querySelectorAll('.FzsqcKBH p')).filter(visible);
    target = rows[0] || null;
  }
  if (!target) return {found: false};
  target = target.closest('button, [role="button"], p, div') || target;
  const state = `${target.getAttribute('aria-pressed') || ''} ${target.getAttribute('data-state') || ''} ${target.className || ''}`;
  const alreadyLiked = /true|active|selected|liked/i.test(state);
  target.setAttribute('data-account-playback-like', '1');
  return {found: true, already_liked: alreadyLiked};
}"""


_MARK_COMMENT_TARGET_JS = """() => {
  document.querySelectorAll('[data-account-playback-comment]').forEach(node => node.removeAttribute('data-account-playback-comment'));
  const visible = node => {
    if (!node) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 8 && rect.height > 8;
  };
  if (document.querySelector('[data-e2e="comment-list"], #videoSideCard, #relatedVideoCard')) return true;
  const selectors = ['[data-e2e="comment-icon"]', '[aria-label*="评论"]'];
  let target = selectors.map(selector => Array.from(document.querySelectorAll(selector)).find(visible)).find(Boolean);
  if (!target) {
    const rows = Array.from(document.querySelectorAll('.FzsqcKBH p')).filter(visible);
    target = rows[1] || null;
  }
  if (!target) return false;
  target = target.closest('button, [role="button"], p, div') || target;
  target.setAttribute('data-account-playback-comment', '1');
  return true;
}"""


_READ_VISIBLE_COMMENTS_JS = """() => {
  const selectors = [
    '[data-e2e="comment-item"] .WFJiGxr7',
    '[data-e2e="comment-item"] [data-e2e="comment-content"]',
    '[data-e2e="comment-item"]'
  ];
  for (const selector of selectors) {
    const values = Array.from(document.querySelectorAll(selector))
      .filter(node => node.offsetParent !== null)
      .map(node => (node.innerText || '').trim())
      .filter(Boolean);
    if (values.length) return values.slice(0, 30);
  }
  return [];
}"""


_MARK_COMMENT_EDITOR_JS = """() => {
  document.querySelectorAll('[data-account-playback-comment-editor]').forEach(node => node.removeAttribute('data-account-playback-comment-editor'));
  const visible = node => {
    if (!node) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 80 && rect.height > 18;
  };
  const selectors = [
    '[data-e2e="comment-input"] [contenteditable="true"]',
    '[data-e2e="comment-input"] textarea',
    '.comment-input-container [contenteditable="true"]',
    'div[contenteditable="true"][aria-label*="评论"]',
    'div[contenteditable="true"][data-placeholder*="评论"]'
  ];
  const editor = selectors.map(selector => Array.from(document.querySelectorAll(selector)).find(visible)).find(Boolean);
  if (!editor) return {found: false};
  editor.setAttribute('data-account-playback-comment-editor', '1');
  return {found: true, tag: editor.tagName};
}"""


_MARK_COMMENT_SUBMIT_JS = """() => {
  document.querySelectorAll('[data-account-playback-comment-submit]').forEach(node => node.removeAttribute('data-account-playback-comment-submit'));
  const visible = node => {
    if (!node) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 8 && rect.height > 8;
  };
  const editor = document.querySelector('[data-account-playback-comment-editor="1"]');
  const root = editor ? (editor.closest('[data-e2e="comment-input"], .comment-input-container') || editor.parentElement?.parentElement) : document;
  const candidates = Array.from((root || document).querySelectorAll('button, [role="button"]')).filter(visible);
  const submit = candidates.find(node => /发送|发布/.test((node.innerText || node.getAttribute('aria-label') || '').trim()))
    || Array.from(document.querySelectorAll('[data-e2e="comment-submit"]')).find(visible);
  if (!submit) return false;
  submit.setAttribute('data-account-playback-comment-submit', '1');
  return true;
}"""
