"""Mandatory, evidence-based sampling policy for new video research."""
from dataclasses import asdict, dataclass
from typing import Mapping

MIN_VIDEOS = 20
MIN_VIEWS = 1_000_000
MIN_LIKES = 1_000_000
MIN_PRIMARY_TAGS = 2
POLICY_TEXT = (
    "分析前须满足：同一采集批次至少 20 个不重复视频，覆盖至少 2 个主要标签，"
    "已确认点赞数合计不少于 100 万，或明确播放量合计不少于 100 万。"
    "两种指标分别核算，不混加；主要标签按采集主关键词归类，每个视频只计一次。"
)
VIEW_KINDS = frozenset({"views", "view_count", "play_count", "plays", "浏览量", "播放量"})
LIKE_KINDS = frozenset({"likes", "like_count", "digg_count", "点赞", "喜欢", "likes_user_confirmed"})


def field(row, name, default=None):
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def primary_tag(row):
    explicit = str(field(row, "primary_tag", "") or "").strip().lstrip("#")
    roots = field(row, "root_keywords", []) or []
    return explicit or str((roots[0] if roots else field(row, "keyword", "")) or "").strip().lstrip("#")


@dataclass(frozen=True)
class SampleGateResult:
    run_id: str
    unique_videos: int
    primary_tags: tuple[str, ...]
    total_views: int
    missing_views: int
    reasons: tuple[str, ...]
    total_likes: int = 0
    missing_likes: int = 0
    metric_kind: str = "likes"

    @property
    def total_count(self):
        return self.total_likes if self.metric_kind == "likes" else self.total_views

    @property
    def metric_label(self):
        return "点赞数" if self.metric_kind == "likes" else "播放量"

    @property
    def passed(self):
        return not self.reasons

    @property
    def message(self):
        return "样本门槛已通过" if self.passed else "分析已阻止：" + "；".join(self.reasons)

    def to_dict(self):
        return {"policy_version": "2026-09-07-likes-v2", **asdict(self),
                "total_count": self.total_count, "metric_label": self.metric_label, "passed": self.passed}


class SampleGateError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(result.message)


def evaluate_sample(rows):
    """Deduplicate videos; repeated search hits never multiply tags or views."""
    groups = {}
    run_ids = set()
    for row in rows:
        run_ids.add(str(field(row, "run_id", "") or ""))
        video_id = str(field(row, "video_id", "") or "").strip()
        if video_id:
            groups.setdefault(video_id, []).append(row)
    tags, untagged = set(), 0
    totals, missing = {"likes": 0, "views": 0}, {"likes": 0, "views": 0}
    for entries in groups.values():
        # Stable single assignment even when one video appears under many queries.
        labels = sorted({primary_tag(row) for row in entries if primary_tag(row)})
        if labels:
            tags.add(labels[0])
        else:
            untagged += 1
        for kind, accepted in (("likes", LIKE_KINDS), ("views", VIEW_KINDS)):
            counts = [field(row, "metric_value", field(row, "visible_metric")) for row in entries
                      if field(row, "metric_kind", field(row, "visible_metric_kind")) in accepted]
            valid = [value for value in counts if type(value) is int and value >= 0]
            if valid:
                totals[kind] += min(valid)
            else:
                missing[kind] += 1
    kind = max(totals, key=lambda key: (missing[key] == 0 and totals[key] >= MIN_VIEWS,
                                       -missing[key], totals[key]))
    label = "点赞数" if kind == "likes" else "播放量"
    reasons = []
    if len(run_ids) != 1 or "" in run_ids:
        reasons.append("采集批次缺失或混有不同批次，不能合并凑数")
    if len(groups) < MIN_VIDEOS:
        reasons.append(f"视频 {len(groups)}/{MIN_VIDEOS}，还缺 {MIN_VIDEOS - len(groups)} 个")
    if len(tags) < MIN_PRIMARY_TAGS:
        reasons.append(f"主要标签 {len(tags)}/{MIN_PRIMARY_TAGS}，需要补充不同主要标签")
    if untagged:
        reasons.append(f"{untagged} 个视频未记录主要标签")
    if missing[kind]:
        reasons.append(f"{missing[kind]} 个视频缺少已确认的{label}证据")
    if totals[kind] < MIN_VIEWS:
        reasons.append(f"已确认{label} {totals[kind]:,}/{MIN_VIEWS:,}，还缺 {MIN_VIEWS - totals[kind]:,}")
    return SampleGateResult(next(iter(run_ids)) if len(run_ids) == 1 else "",
                            len(groups), tuple(sorted(tags)), totals['views'], missing['views'], tuple(reasons),
                            totals['likes'], missing['likes'], kind)


def require_sample(rows):
    result = evaluate_sample(rows)
    if not result.passed:
        raise SampleGateError(result)
    return result


def batch_observations(repository, *, account_uuid="", run_id="", limit=100_000):
    """Default to the latest account batch, never silently mix historical runs."""
    if not run_id:
        latest = repository.list_collection_runs(account_uuid=account_uuid, limit=1)
        run_id = str(latest[0]["run_id"]) if latest else ""
    if not run_id:
        return []
    return [row for row in repository.list_observations(
        account_uuid=account_uuid, run_id=run_id, limit=limit
    ) if row.run_id == run_id]
