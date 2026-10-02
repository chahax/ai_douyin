"""Account-scoped smart operations: related research, creator metrics and review report."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.operations_accounts import AccountProfileRepository
from src.operations_accounts.maintenance import AccountMaintenanceService
from src.services.content_performance import (
    METRICS,
    analyze_snapshot,
    latest_snapshots,
    review_prompts,
    snapshot_history,
)
from src.services.database import get_db
from src.trend_intelligence.repository import TrendRepository


SMART_OPERATIONS_DIR = Path("data/smart_operations")
DEFAULT_AUTHORIZATION_REFERENCE = "user-authorized-smart-operations-2026-09-21"

_GENERIC_HASHTAGS = {
    "AI生成", "虚构剧情演绎", "剧情演绎", "法律", "律师", "法律科普",
}
_TOPIC_RULES = (
    (("装修", "合同"), "装修合同"),
    (("退租", "押金"), "租房押金"),
    (("租房", "押金"), "租房押金"),
    (("劳动", "合同"), "劳动合同"),
    (("借款", "欠款"), "债务纠纷"),
    (("离婚", "财产"), "离婚财产"),
    (("交通", "事故"), "交通事故"),
)


def derive_published_topic_keywords(
    account_uuid: str,
    account_key: str,
    *,
    limit: int = 2,
) -> list[str]:
    """Derive focused research topics from recent owned posts, with profile fallback."""
    if not account_uuid or not account_key:
        raise ValueError("智能运营必须绑定具体账号。")
    requested = max(1, min(int(limit), 4))
    with get_db() as db:
        rows = db.execute(
            """SELECT title FROM videos
               WHERE account_uuid = ? OR account_key = ?
               ORDER BY id DESC LIMIT 20""",
            (account_uuid, account_key),
        ).fetchall()

    topics: list[str] = []
    deferred_tags: list[str] = []
    for row in rows:
        title = str(row["title"] or "")
        for required, topic in _TOPIC_RULES:
            if all(term in title for term in required):
                _append_unique(topics, topic)
                break
        tags = re.findall(r"#([^#\s，。！？；:：]{2,16})", title)
        for tag in tags:
            cleaned = tag.strip(" _-*｜|")
            if cleaned and cleaned not in _GENERIC_HASHTAGS:
                _append_unique(deferred_tags, cleaned)
        if len(topics) >= requested:
            return topics[:requested]

    for tag in deferred_tags:
        _append_unique(topics, tag)
        if len(topics) >= requested:
            return topics[:requested]

    profile = AccountProfileRepository().get(account_key)
    for keyword in (*profile.service_scope, *profile.seed_keywords):
        _append_unique(topics, str(keyword or "").strip())
        if len(topics) >= requested:
            break
    return topics[:requested]


def run_smart_operations(
    account_key: str,
    *,
    headless: bool = True,
    authorization_reference: str = DEFAULT_AUTHORIZATION_REFERENCE,
    output_root: str | Path = SMART_OPERATIONS_DIR,
) -> dict[str, object]:
    """Run one read-only operating cycle and persist an evidence-based report."""
    profile = AccountProfileRepository().get(account_key)
    keywords = derive_published_topic_keywords(
        profile.account_uuid,
        profile.account_key,
        limit=2,
    )
    result = AccountMaintenanceService().run(
        account_key,
        "smart-operations",
        authorization_reference=authorization_reference,
        headless=headless,
        research_keywords=keywords,
    )
    report = build_smart_operations_report(profile.account_uuid, account_key, result)
    destination = Path(output_root) / account_key
    destination.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    json_path = destination / f"smart_operations_{run_id}.json"
    md_path = destination / f"smart_operations_{run_id}.md"
    report["report_json"] = str(json_path)
    report["report_markdown"] = str(md_path)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return report


def build_smart_operations_report(account_uuid: str, account_key: str, result) -> dict[str, object]:
    latest = latest_snapshots(account_uuid)
    history = snapshot_history(account_uuid)
    by_video: dict[str, list[dict[str, object]]] = {}
    for row in history:
        by_video.setdefault(str(row["video_id"]), []).append(row)

    performance: list[dict[str, object]] = []
    for row in latest:
        video_history = by_video.get(str(row["video_id"]), [])
        previous = video_history[-2] if len(video_history) >= 2 else None
        retention = next(
            (
                item for item in reversed(video_history)
                if item.get("completion_rate") is not None
                or item.get("bounce_2s_rate") is not None
                or item.get("avg_watch_seconds") is not None
            ),
            None,
        )
        rates, note = analyze_snapshot(row)
        review_row = dict(row)
        if retention:
            for key in ("completion_rate", "bounce_2s_rate", "avg_watch_seconds"):
                if review_row.get(key) is None:
                    review_row[key] = retention.get(key)
        performance.append(
            {
                "video_id": row["video_id"],
                "title": row.get("title") or "",
                "publish_time": row.get("publish_time") or "",
                "latest_collected_at": row.get("collected_at") or "",
                "metrics": {key: row.get(key) for key in METRICS},
                "metric_delta": {
                    key: _delta(row.get(key), previous.get(key) if previous else None)
                    for key in METRICS
                },
                "rates_percent": rates,
                "sample_note": note,
                "last_known_retention": (
                    {
                        "completion_rate": retention.get("completion_rate"),
                        "bounce_2s_rate": retention.get("bounce_2s_rate"),
                        "avg_watch_seconds": retention.get("avg_watch_seconds"),
                        "observed_at": retention.get("collected_at"),
                    }
                    if retention else None
                ),
                "review_prompts": review_prompts(review_row),
            }
        )

    related_records = [dict(item) for item in result.video_records]
    research_source = "live"
    if not related_records:
        related_records = _cached_related_video_records(
            account_uuid,
            list(result.research_keywords),
        )
        research_source = "cached" if related_records else "unavailable"
    related = sorted(
        related_records,
        key=lambda item: (
            float(item.get("relevance_score") or 0),
            float(item.get("visible_metric") or 0),
        ),
        reverse=True,
    )[:20]
    content_patterns = _content_patterns(
        related_records,
        keywords=list(result.research_keywords),
    )
    operating_recommendations = _operating_recommendations(
        performance,
        content_patterns,
    )
    opportunities = []
    for item in TrendRepository().list_opportunities(
        account_uuid=account_uuid, status="candidate", limit=100
    ):
        if result.started_at and item.created_at < result.started_at:
            continue
        opportunities.append(
            {
                "opportunity_id": item.opportunity_id,
                "title": item.title,
                "score": item.opportunity_score,
                "topic_labels": item.topic_labels,
                "recommended_hook_type": item.recommended_hook_type,
                "recommended_presentation": item.recommended_presentation,
                "recommended_pacing": item.recommended_pacing,
                "recommended_duration_seconds": item.recommended_duration_seconds,
                "recommended_publish_window": item.recommended_publish_window,
                "evidence": item.evidence,
                "risks": item.risks,
            }
        )
        if len(opportunities) >= 10:
            break

    report_status = result.status
    if result.published_data_sync_completed and related_records:
        report_status = "completed"
    return {
        "schema": "smart_operations_report/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "account_uuid": account_uuid,
        "account_key": account_key,
        "status": report_status,
        "maintenance_status": result.status,
        "maintenance_run_id": result.run_id,
        "maintenance_log": result.log_path,
        "research_keywords": list(result.research_keywords),
        "backend_sync": {
            "completed": result.published_data_sync_completed,
            "videos": result.synced_videos,
            "comments": result.synced_comments,
            "comment_failures": result.comment_sync_failures,
        },
        "research": {
            "source": research_source,
            "collected_observations": result.collected_count,
            "unique_relevant_videos": (
                result.unique_relevant_videos
                if research_source == "live"
                else len(related_records)
            ),
            "skipped_irrelevant": result.skipped_irrelevant,
            "top_related_videos": related,
            "top_opportunities": opportunities,
            "content_patterns": content_patterns,
        },
        "owned_content_performance": performance,
        "operating_recommendations": operating_recommendations,
        "warnings": list(result.warnings),
        "publication_submitted": False,
        "external_interactions_performed": result.interaction_actions,
    }


def _render_markdown(report: dict[str, object]) -> str:
    backend = report["backend_sync"]
    research = report["research"]
    lines = [
        "# 智能运营日报",
        "",
        f"- 账号：`{report['account_key']}`",
        f"- 状态：`{report['status']}`",
        f"- 关联主题：{'、'.join(report['research_keywords']) or '未提取'}",
        f"- 后台作品：{backend['videos']} 条；评论：{backend['comments']} 条；评论失败：{backend['comment_failures']} 条",
        f"- 关联内容：{research['unique_relevant_videos']} 条（本轮采集观察 {research['collected_observations']} 条；来源 {research['source']}）",
        "",
        "## 已发布作品表现",
        "",
    ]
    for item in report["owned_content_performance"]:
        metrics = item["metrics"]
        rates = item["rates_percent"]
        lines.extend(
            [
                f"### {item['video_id']}",
                "",
                f"- 播放 {metrics['play_count']}，点赞 {metrics['like_count']}，评论 {metrics['comment_count']}，分享 {metrics['share_count']}，收藏 {metrics['collect_count']}",
                f"- 点赞率：{_percent_text(rates.get('like_count'))}；评论率：{_percent_text(rates.get('comment_count'))}；收藏率：{_percent_text(rates.get('collect_count'))}",
                f"- 判断：{item['sample_note']}",
            ]
        )
        for prompt in item["review_prompts"]:
            lines.append(f"- 复盘：{prompt}")
        retention = item.get("last_known_retention")
        if retention:
            lines.append(
                f"- 最近一次留存记录（{retention['observed_at']}）：完播率 {retention['completion_rate']}%，2秒跳出率 {retention['bounce_2s_rate']}%"
            )
        lines.append("")

    lines.extend(["## 关联视频样本", ""])
    for item in research["top_related_videos"][:10]:
        lines.append(
            f"- {item.get('title') or item.get('video_id')}｜相关度 {item.get('relevance_score')}｜页面指标 {item.get('visible_metric_text') or item.get('visible_metric')}｜{item.get('url')}"
        )
    patterns = research.get("content_patterns") or {}
    if patterns:
        lines.extend(["", "## 内容结构观察", ""])
        lines.append(f"- 时长中位数：{patterns['median_duration_seconds']} 秒；60 秒内 {patterns['duration_buckets']['short_60s_or_less']} 条，61–180 秒 {patterns['duration_buckets']['medium_61_to_180s']} 条，180 秒以上 {patterns['duration_buckets']['long_over_180s']} 条")
        if patterns["common_hashtags"]:
            lines.append("- 常见标签：" + "、".join(f"#{item['tag']}（{item['count']}）" for item in patterns["common_hashtags"][:8]))
        if patterns["hook_signals"]:
            lines.append("- 标题结构：" + "、".join(f"{item['label']}（{item['count']}）" for item in patterns["hook_signals"]))
        if patterns.get("topic_coverage"):
            lines.append("- 主题覆盖：" + "、".join(f"{topic}（{count}）" for topic, count in patterns["topic_coverage"].items()))
    lines.extend(["", "## 运营动作", ""])
    for item in report.get("operating_recommendations", []):
        lines.append(f"- **{item['title']}**：{item['action']}（依据：{item['evidence']}）")
    lines.extend(["", "## 下一轮候选", ""])
    for item in research["top_opportunities"][:5]:
        lines.append(
            f"- {item['title']}｜得分 {item['score']:.2f}｜钩子 {item['recommended_hook_type']}｜建议时长 {item['recommended_duration_seconds']} 秒"
        )
    if report["warnings"]:
        lines.extend(["", "## 待处理", ""])
        lines.extend(f"- {item}" for item in report["warnings"])
    lines.extend(["", "本报告只读取和分析数据；没有发布、点赞或评论。", ""])
    return "\n".join(lines)


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _delta(current, previous):
    if current is None or previous is None:
        return None
    return current - previous


def _percent_text(value) -> str:
    return "未知" if value is None else f"{value:.2f}%"


def _content_patterns(
    records: list[dict[str, object]],
    *,
    keywords: list[str] | None = None,
) -> dict[str, object]:
    if not records:
        return {}
    durations = sorted(
        float(item["duration_seconds"])
        for item in records
        if item.get("duration_seconds") is not None
    )
    median = 0.0
    if durations:
        center = len(durations) // 2
        median = (
            durations[center]
            if len(durations) % 2
            else (durations[center - 1] + durations[center]) / 2
        )
    hashtag_counts = Counter(
        str(tag)
        for item in records
        for tag in item.get("hashtags", [])
        if str(tag) not in _GENERIC_HASHTAGS
    )
    hook_patterns = (
        ("清单/数字承诺", re.compile(r"\d+|[三四五六七八九十]条|几句话|几个问题")),
        ("风险警告", re.compile(r"千万|一定要|别乱|避坑|警惕|害怕|吃亏")),
        ("争议/损失", re.compile(r"索赔|扣|赔偿|增项|纠纷|多花|被坑")),
        ("提问", re.compile(r"[？?]|为什么|怎么|如何")),
    )
    hook_counts = Counter()
    for item in records:
        title = str(item.get("title") or "")
        for label, pattern in hook_patterns:
            if pattern.search(title):
                hook_counts[label] += 1
    topic_coverage = {}
    for keyword in keywords or []:
        topic_coverage[keyword] = sum(
            keyword in str(item.get("title") or "")
            or keyword == str(item.get("primary_tag") or "").lstrip("#")
            or keyword in [str(value).lstrip("#") for value in item.get("associated_keywords", [])]
            for item in records
        )
    return {
        "sample_size": len(records),
        "median_duration_seconds": round(median, 1),
        "duration_buckets": {
            "short_60s_or_less": sum(value <= 60 for value in durations),
            "medium_61_to_180s": sum(60 < value <= 180 for value in durations),
            "long_over_180s": sum(value > 180 for value in durations),
            "unknown": len(records) - len(durations),
        },
        "common_hashtags": [
            {"tag": tag, "count": count}
            for tag, count in hashtag_counts.most_common(12)
        ],
        "hook_signals": [
            {"label": label, "count": hook_counts[label]}
            for label, _ in hook_patterns
            if hook_counts[label]
        ],
        "topic_coverage": topic_coverage,
        "metric_semantics": "页面展示数字的语义未确认，仅保留原值，不按点赞量解释。",
    }


def _operating_recommendations(
    performance: list[dict[str, object]],
    patterns: dict[str, object],
) -> list[dict[str, str]]:
    """Turn observed account and sample data into bounded, auditable next actions."""
    recommendations: list[dict[str, str]] = []
    ranked = sorted(
        performance,
        key=lambda item: float(item.get("metrics", {}).get("play_count") or 0),
        reverse=True,
    )
    if len(ranked) >= 2:
        leader = ranked[0]
        trailer = ranked[-1]
        leader_plays = int(leader.get("metrics", {}).get("play_count") or 0)
        trailer_plays = int(trailer.get("metrics", {}).get("play_count") or 0)
        if leader_plays >= max(100, trailer_plays * 2):
            recommendations.append({
                "title": "优先验证高触达选题",
                "action": "下一轮先延展触达更高作品的同类冲突，再保留一个低触达题材作对照；不要只凭两条作品永久定方向。",
                "evidence": f"作品 {leader['video_id']} 播放 {leader_plays}，作品 {trailer['video_id']} 播放 {trailer_plays}",
            })

    weak_openings = []
    for item in performance:
        retention = item.get("last_known_retention") or {}
        bounce = retention.get("bounce_2s_rate")
        completion = retention.get("completion_rate")
        if (bounce is not None and float(bounce) >= 30) or (
            completion is not None and float(completion) < 25
        ):
            weak_openings.append(str(item["video_id"]))
    if weak_openings:
        recommendations.append({
            "title": "先改前两秒",
            "action": "把人物处境、冲突对象或损失结果提前到开场，并在生成前为关键对白保留清楚的表情反应窗口。",
            "evidence": "以下作品出现2秒跳出率不低于30%或完播率低于25%：" + "、".join(weak_openings),
        })

    coverage = patterns.get("topic_coverage") or {}
    if len(coverage) >= 2:
        ordered_coverage = sorted(coverage.items(), key=lambda item: item[1])
        low_topic, low_count = ordered_coverage[0]
        high_topic, high_count = ordered_coverage[-1]
        if high_count >= max(4, low_count * 4):
            recommendations.append({
                "title": "补齐关联样本",
                "action": f"下轮优先采集“{low_topic}”，达到可比较样本量后再比较两个题材。",
                "evidence": f"“{high_topic}”{high_count}条，“{low_topic}”{low_count}条",
            })

    hooks = patterns.get("hook_signals") or []
    if hooks:
        top_hooks = sorted(hooks, key=lambda item: item["count"], reverse=True)[:2]
        recommendations.append({
            "title": "测试标题结构",
            "action": "用一个风险结果和一个具体数字构成标题及开场测试；这里只作为结构参考，不把页面未确认数字当成效果证明。",
            "evidence": "关联样本常见结构为" + "、".join(
                f"{item['label']} {item['count']}条" for item in top_hooks
            ),
        })
    return recommendations


def _cached_related_video_records(
    account_uuid: str,
    keywords: list[str],
    *,
    max_age_hours: int = 72,
    limit: int = 40,
) -> list[dict[str, object]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in TrendRepository().list_observations(
        account_uuid=account_uuid,
        limit=5000,
    ):
        try:
            collected_at = datetime.fromisoformat(item.collected_at.replace("Z", "+00:00"))
            if collected_at.tzinfo is None:
                collected_at = collected_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if collected_at.astimezone(timezone.utc) < cutoff:
            continue
        terms = [item.keyword, *item.root_keywords, *item.relevance_terms]
        if keywords and not any(
            keyword in str(term) or str(term) in keyword
            for keyword in keywords
            for term in terms
            if str(term).strip()
        ):
            continue
        identity = item.video_id or item.item_id
        if not identity or identity in seen:
            continue
        seen.add(identity)
        output.append({
            "item_id": item.item_id,
            "video_id": item.video_id,
            "run_id": item.run_id,
            "primary_tag": item.keyword,
            "collected_at": item.collected_at,
            "title": item.title,
            "author": item.author,
            "hashtags": list(item.hashtags),
            "duration_seconds": item.duration_seconds,
            "associated_keywords": list(dict.fromkeys(terms)),
            "relevance_score": item.relevance_score,
            "visible_metric": item.metric_value,
            "visible_metric_text": item.metric_text,
            "visible_metric_kind": item.metric_kind,
            "source_sort": item.sort_key,
            "published_at": item.published_at,
            "url": item.url,
        })
        if len(output) >= limit:
            break
    return output
