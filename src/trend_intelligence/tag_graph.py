"""Pure helpers for extracting and scoring run-scoped hashtag relationships."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from statistics import median
from typing import Iterable

from .models import TrendObservation, TrendTagRelation, TrendTagTrafficSnapshot


HASHTAG_PATTERN = re.compile(r"[#＃]([0-9A-Za-z_\u3400-\u9fff]{1,40})")
GENERIC_EXPANSION_TAGS = frozenset(
    {"douyin", "抖音", "热门", "热点", "上热门", "推荐", "知识", "分享"}
)


def normalize_hashtag(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = normalized.lstrip("#").strip().rstrip(".,，。!！?？:：;；")
    if normalized.isascii():
        normalized = normalized.casefold()
    if not normalized or len(normalized) > 40:
        return ""
    return normalized


def extract_hashtags(*texts: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in HASHTAG_PATTERN.finditer(text or ""):
            tag = normalize_hashtag(match.group(1))
            if tag and tag not in seen:
                seen.add(tag)
                output.append(tag)
    return output


def build_keyword_tag_relations(
    observations: Iterable[TrendObservation],
    *,
    max_tags_per_keyword: int,
    max_total_tags: int,
) -> tuple[list[TrendTagRelation], dict[str, list[str]]]:
    rows_by_root: dict[str, list[TrendObservation]] = defaultdict(list)
    for row in observations:
        roots = row.root_keywords or [row.keyword]
        for root in roots:
            if root:
                rows_by_root[root].append(row)

    relations: list[TrendTagRelation] = []
    selected_roots_by_tag: dict[str, list[str]] = defaultdict(list)
    remaining = max(0, int(max_total_tags))
    per_root_limit = max(0, int(max_tags_per_keyword))

    for root, rows in rows_by_root.items():
        unique_source_items = {row.item_id for row in rows}
        tag_rows: dict[str, list[TrendObservation]] = defaultdict(list)
        for row in rows:
            for tag in row.hashtags:
                normalized = normalize_hashtag(tag)
                if normalized:
                    tag_rows[normalized].append(row)

        root_relations: list[TrendTagRelation] = []
        for tag, matched_rows in tag_rows.items():
            unique_rows = _best_rows_by_item(matched_rows)
            support = len(unique_rows)
            source_count = len(unique_source_items)
            reciprocal = sum(
                _reciprocal_rank(row.rank) for row in unique_rows.values()
            )
            root_affinity = _text_affinity(root, tag)
            relation = TrendTagRelation(
                root_keyword=root,
                source_kind="keyword",
                source_value=root,
                target_tag=tag,
                relation_kind="keyword_hashtag",
                support_video_count=support,
                source_video_count=source_count,
                unique_authors=len(
                    {row.author for row in unique_rows.values() if row.author}
                ),
                sort_coverage=len({row.sort_key for row in matched_rows}),
                weight=round(support / max(1, source_count), 4),
                relationship_score=round(
                    100
                    * (
                        0.5 * support / max(1, source_count)
                        + 0.3 * reciprocal / max(1, support)
                        + 0.2 * root_affinity
                    ),
                    2,
                ),
                visible_metric_max=_max_metric(unique_rows),
                supporting_item_ids=sorted(unique_rows),
            )
            root_relations.append(relation)

        root_relations.sort(
            key=lambda item: (
                -item.support_video_count,
                -item.relationship_score,
                -item.sort_coverage,
                -(item.visible_metric_max or 0),
                item.target_tag,
            )
        )
        chosen = 0
        for relation in root_relations:
            normalized_root = normalize_hashtag(root)
            is_new_tag = relation.target_tag not in selected_roots_by_tag
            can_expand = (
                (remaining > 0 or not is_new_tag)
                and chosen < per_root_limit
                and relation.target_tag != normalized_root
                and relation.target_tag not in GENERIC_EXPANSION_TAGS
            )
            if can_expand:
                relation.expanded = True
                if root not in selected_roots_by_tag[relation.target_tag]:
                    selected_roots_by_tag[relation.target_tag].append(root)
                chosen += 1
                if is_new_tag:
                    remaining -= 1
            relations.append(relation)

    return relations, dict(selected_roots_by_tag)


def build_tag_cooccurrence_relations(
    observations_by_tag: dict[str, list[TrendObservation]],
    roots_by_tag: dict[str, list[str]],
) -> list[TrendTagRelation]:
    output: list[TrendTagRelation] = []
    for source_tag, rows in observations_by_tag.items():
        unique_source_items = {row.item_id for row in rows}
        for root in roots_by_tag.get(source_tag, []):
            co_rows: dict[str, list[TrendObservation]] = defaultdict(list)
            for row in rows:
                for target_tag in row.hashtags:
                    normalized = normalize_hashtag(target_tag)
                    if normalized and normalized != source_tag:
                        co_rows[normalized].append(row)
            for target_tag, matched_rows in co_rows.items():
                unique_rows = _best_rows_by_item(matched_rows)
                support = len(unique_rows)
                source_count = len(unique_source_items)
                reciprocal = sum(
                    _reciprocal_rank(row.rank) for row in unique_rows.values()
                )
                output.append(
                    TrendTagRelation(
                        root_keyword=root,
                        source_kind="tag",
                        source_value=source_tag,
                        target_tag=target_tag,
                        relation_kind="video_cooccurrence",
                        support_video_count=support,
                        source_video_count=source_count,
                        unique_authors=len(
                            {
                                row.author
                                for row in unique_rows.values()
                                if row.author
                            }
                        ),
                        sort_coverage=len({row.sort_key for row in matched_rows}),
                        weight=round(support / max(1, source_count), 4),
                        relationship_score=round(
                            100
                            * (
                                0.6 * support / max(1, source_count)
                                + 0.4 * reciprocal / max(1, support)
                            ),
                            2,
                        ),
                        visible_metric_max=_max_metric(unique_rows),
                        supporting_item_ids=sorted(unique_rows),
                    )
                )
    return sorted(
        output,
        key=lambda item: (
            item.root_keyword,
            item.source_value,
            -item.relationship_score,
            item.target_tag,
        ),
    )


def build_tag_traffic_snapshots(
    observations_by_tag: dict[str, list[TrendObservation]],
    roots_by_tag: dict[str, list[str]],
    *,
    limit_per_sort: int,
) -> list[TrendTagTrafficSnapshot]:
    output: list[TrendTagTrafficSnapshot] = []
    safe_limit = max(1, int(limit_per_sort))
    for tag, rows in observations_by_tag.items():
        by_sort: dict[tuple[str, str], list[TrendObservation]] = defaultdict(list)
        for row in rows:
            by_sort[(row.sort_key, row.sort_label)].append(row)
        for root in roots_by_tag.get(tag, []):
            for (sort_key, sort_label), sort_rows in by_sort.items():
                best_by_item = _best_rows_by_item(sort_rows)
                unique_rows = sorted(
                    best_by_item.values(),
                    key=lambda row: (row.rank, -(row.metric_value or 0), row.item_id),
                )
                ranks = [max(1, row.rank) for row in unique_rows]
                reciprocal = sum(_reciprocal_rank(rank) for rank in ranks)
                metrics = [
                    row.metric_value
                    for row in unique_rows
                    if row.metric_value is not None
                ]
                metric_max = max(metrics) if metrics else None
                metric_score = (
                    min(1.0, math.log10(metric_max + 1) / 8)
                    if metric_max is not None
                    else 0.0
                )
                breadth_score = min(1.0, len(unique_rows) / safe_limit)
                reciprocal_score = reciprocal / max(1, len(unique_rows))
                best_rank = min(ranks, default=0)
                best_rank_score = (
                    max(0.0, 1.0 - (best_rank - 1) / safe_limit)
                    if best_rank
                    else 0.0
                )
                output.append(
                    TrendTagTrafficSnapshot(
                        root_keyword=root,
                        tag=tag,
                        sort_key=sort_key,
                        sort_label=sort_label,
                        unique_video_count=len(unique_rows),
                        best_rank=best_rank,
                        reciprocal_rank_score=round(reciprocal, 4),
                        sample_score=round(
                            100
                            * (
                                0.3 * breadth_score
                                + 0.3 * reciprocal_score
                                + 0.3 * metric_score
                                + 0.1 * best_rank_score
                            ),
                            2,
                        ),
                        visible_metric_max=metric_max,
                        visible_metric_median=(
                            round(float(median(metrics)), 2) if metrics else None
                        ),
                        top_item_ids=[row.item_id for row in unique_rows[:5]],
                    )
                )
    return sorted(
        output,
        key=lambda item: (
            item.root_keyword,
            item.tag,
            -item.sample_score,
            item.sort_key,
        ),
    )


def _best_rows_by_item(
    rows: Iterable[TrendObservation],
) -> dict[str, TrendObservation]:
    output: dict[str, TrendObservation] = {}
    for row in rows:
        current = output.get(row.item_id)
        if current is None or (row.rank, -(row.metric_value or 0)) < (
            current.rank,
            -(current.metric_value or 0),
        ):
            output[row.item_id] = row
    return output


def _max_metric(rows: dict[str, TrendObservation]) -> int | None:
    values = [row.metric_value for row in rows.values() if row.metric_value is not None]
    return max(values) if values else None


def _reciprocal_rank(rank: int) -> float:
    return 1 / math.log2(max(1, rank) + 1)


def _text_affinity(left: str, right: str) -> float:
    normalized_left = normalize_hashtag(left)
    normalized_right = normalize_hashtag(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 1.0
    left_chars = {char for char in normalized_left if char.strip()}
    right_chars = {char for char in normalized_right if char.strip()}
    return len(left_chars & right_chars) / max(1, len(left_chars))
