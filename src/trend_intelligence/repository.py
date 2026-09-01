"""SQLite persistence for trend analysis and operation feedback."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from src.shared.config import settings

from .models import (
    AccountContentRelevance,
    ContentAnalysisBatchResult,
    ContentEvidence,
    ContentOpportunity,
    ContentSegment,
    PublishedContentContext,
    OpportunityScript,
    ScriptBeat,
    TrendBrief,
    TrendCluster,
    TrendObservation,
    TrendTagRelation,
    TrendTagTrafficSnapshot,
    VideoMetricSnapshot,
    VideoContentAnalysis,
    utc_now_iso,
)
from .collection.planner import AccountCollectionPlan


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "trend_intelligence.db"
TREND_SCHEMA_VERSION = 5


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trend_collection_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    keywords_json TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    account_uuid TEXT NOT NULL DEFAULT '',
    profile_version INTEGER NOT NULL DEFAULT 0,
    domain_strategy_id TEXT NOT NULL DEFAULT '',
    strategy_version TEXT NOT NULL DEFAULT '',
    plan_id TEXT NOT NULL DEFAULT '',
    batch_id TEXT NOT NULL DEFAULT '',
    wave_kind TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trend_collection_plans (
    plan_id TEXT PRIMARY KEY,
    account_uuid TEXT NOT NULL,
    account_key TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    domain_strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    wave_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_content_analyses (
    analysis_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    video_id TEXT NOT NULL DEFAULT '',
    account_uuid TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    provider_id TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    presentation_type TEXT NOT NULL DEFAULT 'unknown',
    relevance_score REAL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_content_analysis_batches (
    batch_id TEXT PRIMARY KEY,
    implementation_id TEXT NOT NULL,
    account_uuid TEXT NOT NULL,
    requested_count INTEGER NOT NULL,
    completed_count INTEGER NOT NULL,
    degraded_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    cached_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_content_opportunities (
    opportunity_id TEXT PRIMARY KEY,
    account_uuid TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    domain_strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    cluster_id TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL NOT NULL,
    valid_until TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_opportunity_scripts (
    script_id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    account_uuid TEXT NOT NULL,
    domain_strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (opportunity_id) REFERENCES trend_content_opportunities(opportunity_id)
);

CREATE TABLE IF NOT EXISTS trend_items (
    item_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'douyin',
    video_id TEXT,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    published_at_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trend_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    sort_label TEXT NOT NULL,
    rank INTEGER NOT NULL,
    metric_text TEXT NOT NULL DEFAULT '',
    metric_value INTEGER,
    metric_kind TEXT NOT NULL DEFAULT 'displayed_unknown',
    collected_at TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    published_at_text TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    query_kind TEXT NOT NULL DEFAULT 'keyword',
    query_value TEXT NOT NULL DEFAULT '',
    query_depth INTEGER NOT NULL DEFAULT 0,
    root_keywords_json TEXT NOT NULL DEFAULT '[]',
    hashtags_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(run_id, item_id, keyword, sort_key),
    FOREIGN KEY (run_id) REFERENCES trend_collection_runs(run_id),
    FOREIGN KEY (item_id) REFERENCES trend_items(item_id)
);

CREATE TABLE IF NOT EXISTS trend_tags (
    tag TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_observation_tags (
    run_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    query_value TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    tag TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id, query_value, sort_key, tag),
    FOREIGN KEY (run_id) REFERENCES trend_collection_runs(run_id),
    FOREIGN KEY (item_id) REFERENCES trend_items(item_id),
    FOREIGN KEY (tag) REFERENCES trend_tags(tag)
);

CREATE TABLE IF NOT EXISTS trend_tag_relations (
    run_id TEXT NOT NULL,
    root_keyword TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_value TEXT NOT NULL,
    target_tag TEXT NOT NULL,
    relation_kind TEXT NOT NULL,
    support_video_count INTEGER NOT NULL,
    source_video_count INTEGER NOT NULL,
    unique_authors INTEGER NOT NULL,
    sort_coverage INTEGER NOT NULL,
    weight REAL NOT NULL,
    relationship_score REAL NOT NULL,
    visible_metric_max INTEGER,
    expanded INTEGER NOT NULL DEFAULT 0,
    supporting_item_ids_json TEXT NOT NULL DEFAULT '[]',
    collected_at TEXT NOT NULL,
    PRIMARY KEY (
        run_id, root_keyword, source_kind, source_value,
        target_tag, relation_kind
    ),
    FOREIGN KEY (run_id) REFERENCES trend_collection_runs(run_id),
    FOREIGN KEY (target_tag) REFERENCES trend_tags(tag)
);

CREATE TABLE IF NOT EXISTS trend_tag_traffic_snapshots (
    run_id TEXT NOT NULL,
    root_keyword TEXT NOT NULL,
    tag TEXT NOT NULL,
    sort_key TEXT NOT NULL,
    sort_label TEXT NOT NULL,
    unique_video_count INTEGER NOT NULL,
    best_rank INTEGER NOT NULL,
    reciprocal_rank_score REAL NOT NULL,
    sample_score REAL NOT NULL,
    visible_metric_max INTEGER,
    visible_metric_median REAL,
    top_item_ids_json TEXT NOT NULL DEFAULT '[]',
    metric_kind TEXT NOT NULL DEFAULT 'displayed_unknown',
    score_kind TEXT NOT NULL DEFAULT 'sample_traffic_proxy',
    collected_at TEXT NOT NULL,
    PRIMARY KEY (run_id, root_keyword, tag, sort_key),
    FOREIGN KEY (run_id) REFERENCES trend_collection_runs(run_id),
    FOREIGN KEY (tag) REFERENCES trend_tags(tag)
);

CREATE TABLE IF NOT EXISTS trend_clusters (
    cluster_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    score REAL NOT NULL,
    score_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_briefs (
    brief_id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL NOT NULL,
    score_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS published_content_context (
    local_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL DEFAULT '',
    brief_id TEXT NOT NULL DEFAULT '',
    cluster_id TEXT NOT NULL DEFAULT '',
    script_version TEXT NOT NULL DEFAULT 'v1',
    workflow_profile TEXT NOT NULL DEFAULT '',
    hook_type TEXT NOT NULL DEFAULT '',
    content_format TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    published_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL DEFAULT '',
    local_id TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL,
    publish_time TEXT NOT NULL DEFAULT '',
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    shares INTEGER NOT NULL DEFAULT 0,
    collects INTEGER NOT NULL DEFAULT 0,
    UNIQUE(video_id, local_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_trend_observations_item
    ON trend_observations(item_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_trend_briefs_status
    ON trend_briefs(status, score DESC);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_identity
    ON video_metric_snapshots(local_id, video_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_observation_tags_tag
    ON trend_observation_tags(tag, captured_at);
CREATE INDEX IF NOT EXISTS idx_tag_relations_source
    ON trend_tag_relations(source_kind, source_value, collected_at);
CREATE INDEX IF NOT EXISTS idx_tag_relations_target
    ON trend_tag_relations(target_tag, collected_at);
CREATE INDEX IF NOT EXISTS idx_tag_traffic_timeline
    ON trend_tag_traffic_snapshots(tag, sort_key, collected_at);
CREATE INDEX IF NOT EXISTS idx_collection_plans_account
    ON trend_collection_plans(account_uuid, created_at);
CREATE INDEX IF NOT EXISTS idx_content_analysis_account
    ON trend_content_analyses(account_uuid, profile_version, created_at);
CREATE INDEX IF NOT EXISTS idx_content_analysis_item
    ON trend_content_analyses(item_id, account_uuid, created_at);
CREATE INDEX IF NOT EXISTS idx_opportunity_account_score
    ON trend_content_opportunities(account_uuid, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_validity
    ON trend_content_opportunities(valid_until, status);
CREATE INDEX IF NOT EXISTS idx_opportunity_scripts
    ON trend_opportunity_scripts(opportunity_id, status);
"""


class TrendRepository:
    def __init__(self, db_path: str | Path | None = None):
        configured = (
            db_path
            or os.getenv("TREND_DB_PATH")
            or getattr(settings, "TREND_DB_PATH", "")
            or DEFAULT_DB_PATH
        )
        self.db_path = Path(configured).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            self._ensure_observation_columns(conn)
            self._ensure_item_columns(conn)
            self._ensure_collection_run_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trend_observations_query "
                "ON trend_observations(query_kind, query_value, collected_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_collection_runs_account "
                "ON trend_collection_runs(account_uuid, finished_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_collection_runs_plan "
                "ON trend_collection_runs(plan_id, batch_id)"
            )
            conn.execute(f"PRAGMA user_version = {TREND_SCHEMA_VERSION}")

    @staticmethod
    def _ensure_observation_columns(conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(trend_observations)").fetchall()
        }
        additions = {
            "query_kind": "TEXT NOT NULL DEFAULT 'keyword'",
            "query_value": "TEXT NOT NULL DEFAULT ''",
            "query_depth": "INTEGER NOT NULL DEFAULT 0",
            "root_keywords_json": "TEXT NOT NULL DEFAULT '[]'",
            "hashtags_json": "TEXT NOT NULL DEFAULT '[]'",
            "metric_kind": "TEXT NOT NULL DEFAULT 'displayed_unknown'",
            "published_at": "TEXT NOT NULL DEFAULT ''",
            "published_at_text": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE trend_observations ADD COLUMN {name} {definition}"
                )

    @staticmethod
    def _ensure_item_columns(conn: sqlite3.Connection) -> None:
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(trend_items)")
        }
        for name, definition in {
            "published_at": "TEXT NOT NULL DEFAULT ''",
            "published_at_text": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE trend_items ADD COLUMN {name} {definition}")

    @staticmethod
    def _ensure_collection_run_columns(conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(trend_collection_runs)")
        }
        additions = {
            "account_uuid": "TEXT NOT NULL DEFAULT ''",
            "profile_version": "INTEGER NOT NULL DEFAULT 0",
            "domain_strategy_id": "TEXT NOT NULL DEFAULT ''",
            "strategy_version": "TEXT NOT NULL DEFAULT ''",
            "plan_id": "TEXT NOT NULL DEFAULT ''",
            "batch_id": "TEXT NOT NULL DEFAULT ''",
            "wave_kind": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE trend_collection_runs ADD COLUMN {name} {definition}"
                )

    def save_collection_plan(self, plan: AccountCollectionPlan) -> None:
        payload = json.dumps(plan.to_dict(), ensure_ascii=False)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trend_collection_plans (
                    plan_id, account_uuid, account_key, profile_version,
                    domain_strategy_id, strategy_version, wave_kind, status,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    plan.plan_id,
                    plan.account_uuid,
                    plan.account_key,
                    plan.profile_version,
                    plan.domain_strategy_id,
                    plan.strategy_version,
                    plan.wave_kind,
                    payload,
                    plan.created_at,
                    utc_now_iso(),
                ),
            )

    def update_collection_plan_status(self, plan_id: str, status: str) -> bool:
        if status not in {"planned", "running", "partial", "completed", "failed"}:
            raise ValueError("invalid collection plan status")
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE trend_collection_plans
                SET status = ?, updated_at = ?
                WHERE plan_id = ?
                """,
                (status, utc_now_iso(), plan_id),
            )
        return cursor.rowcount > 0

    def list_collection_plans(
        self, *, account_uuid: str = "", limit: int = 100
    ) -> list[dict[str, object]]:
        query = "SELECT payload_json, status, updated_at FROM trend_collection_plans"
        params: list[object] = []
        if account_uuid:
            query += " WHERE account_uuid = ?"
            params.append(account_uuid)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        output: list[dict[str, object]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["status"] = row["status"]
            payload["updated_at"] = row["updated_at"]
            output.append(payload)
        return output

    def list_collection_runs(
        self, *, plan_id: str = "", account_uuid: str = "", limit: int = 1000
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM trend_collection_runs"
        clauses: list[str] = []
        params: list[object] = []
        if plan_id:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if account_uuid:
            clauses.append("account_uuid = ?")
            params.append(account_uuid)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY finished_at DESC, started_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 10_000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def save_collection(
        self,
        observations: list[TrendObservation],
        *,
        provider: str,
        keywords: list[str],
        warnings: list[str] | None = None,
        tag_relations: list[TrendTagRelation] | None = None,
        tag_traffic_snapshots: list[TrendTagTrafficSnapshot] | None = None,
        account_uuid: str = "",
        profile_version: int = 0,
        domain_strategy_id: str = "",
        strategy_version: str = "",
        plan_id: str = "",
        batch_id: str = "",
        wave_kind: str = "",
    ) -> str:
        run_id = uuid.uuid4().hex
        started_at = min(
            (item.collected_at for item in observations),
            default=utc_now_iso(),
        )
        finished_at = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trend_collection_runs (
                    run_id, provider, keywords_json, status, item_count,
                    warnings_json, started_at, finished_at, account_uuid,
                    profile_version, domain_strategy_id, strategy_version,
                    plan_id, batch_id, wave_kind
                ) VALUES (?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    provider,
                    json.dumps(keywords, ensure_ascii=False),
                    len(observations),
                    json.dumps(warnings or [], ensure_ascii=False),
                    started_at,
                    finished_at,
                    account_uuid,
                    max(0, int(profile_version)),
                    domain_strategy_id,
                    strategy_version,
                    plan_id,
                    batch_id,
                    wave_kind,
                ),
            )
            for item in observations:
                item.run_id = run_id
                conn.execute(
                    """
                    INSERT INTO trend_items (
                        item_id, platform, video_id, url, title, author,
                        first_seen_at, last_seen_at, published_at,
                        published_at_text
                    ) VALUES (?, 'douyin', ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        video_id = COALESCE(excluded.video_id, trend_items.video_id),
                        url = excluded.url,
                        title = excluded.title,
                        author = excluded.author,
                        last_seen_at = excluded.last_seen_at,
                        published_at = CASE
                            WHEN excluded.published_at != '' THEN excluded.published_at
                            ELSE trend_items.published_at
                        END,
                        published_at_text = CASE
                            WHEN excluded.published_at_text != '' THEN excluded.published_at_text
                            ELSE trend_items.published_at_text
                        END
                    """,
                    (
                        item.item_id,
                        item.video_id or None,
                        item.url,
                        item.title,
                        item.author,
                        item.collected_at,
                        item.collected_at,
                        item.published_at,
                        item.published_at_text,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO trend_observations (
                        run_id, item_id, keyword, sort_key, sort_label, rank,
                        metric_text, metric_value, collected_at, raw_text,
                        metric_kind, published_at, published_at_text,
                        query_kind, query_value, query_depth,
                        root_keywords_json, hashtags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, item_id, keyword, sort_key) DO UPDATE SET
                        sort_label = excluded.sort_label,
                        rank = excluded.rank,
                        metric_text = excluded.metric_text,
                        metric_value = excluded.metric_value,
                        collected_at = excluded.collected_at,
                        raw_text = excluded.raw_text,
                        metric_kind = excluded.metric_kind,
                        published_at = excluded.published_at,
                        published_at_text = excluded.published_at_text,
                        query_kind = excluded.query_kind,
                        query_value = excluded.query_value,
                        query_depth = excluded.query_depth,
                        root_keywords_json = excluded.root_keywords_json,
                        hashtags_json = excluded.hashtags_json
                    """,
                    (
                        run_id,
                        item.item_id,
                        item.keyword,
                        item.sort_key,
                        item.sort_label,
                        item.rank,
                        item.metric_text,
                        item.metric_value,
                        item.collected_at,
                        item.raw_text,
                        item.metric_kind,
                        item.published_at,
                        item.published_at_text,
                        item.query_kind,
                        item.query_value or item.keyword,
                        max(0, item.query_depth),
                        json.dumps(item.root_keywords, ensure_ascii=False),
                        json.dumps(item.hashtags, ensure_ascii=False),
                    ),
                )
                for ordinal, tag in enumerate(item.hashtags, start=1):
                    self._upsert_tag(conn, tag, item.collected_at)
                    conn.execute(
                        """
                        INSERT INTO trend_observation_tags (
                            run_id, item_id, query_value, sort_key,
                            tag, ordinal, captured_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(
                            run_id, item_id, query_value, sort_key, tag
                        ) DO UPDATE SET
                            ordinal = excluded.ordinal,
                            captured_at = excluded.captured_at
                        """,
                        (
                            run_id,
                            item.item_id,
                            item.query_value or item.keyword,
                            item.sort_key,
                            tag,
                            ordinal,
                            item.collected_at,
                        ),
                    )
            for relation in tag_relations or []:
                relation.run_id = run_id
                self._upsert_tag(conn, relation.target_tag, relation.collected_at)
                if relation.source_kind == "tag":
                    self._upsert_tag(
                        conn, relation.source_value, relation.collected_at
                    )
                conn.execute(
                    """
                    INSERT INTO trend_tag_relations (
                        run_id, root_keyword, source_kind, source_value,
                        target_tag, relation_kind, support_video_count,
                        source_video_count, unique_authors, sort_coverage,
                        weight, relationship_score, visible_metric_max,
                        expanded, supporting_item_ids_json, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(
                        run_id, root_keyword, source_kind, source_value,
                        target_tag, relation_kind
                    ) DO UPDATE SET
                        support_video_count = excluded.support_video_count,
                        source_video_count = excluded.source_video_count,
                        unique_authors = excluded.unique_authors,
                        sort_coverage = excluded.sort_coverage,
                        weight = excluded.weight,
                        relationship_score = excluded.relationship_score,
                        visible_metric_max = excluded.visible_metric_max,
                        expanded = excluded.expanded,
                        supporting_item_ids_json = excluded.supporting_item_ids_json,
                        collected_at = excluded.collected_at
                    """,
                    (
                        run_id,
                        relation.root_keyword,
                        relation.source_kind,
                        relation.source_value,
                        relation.target_tag,
                        relation.relation_kind,
                        relation.support_video_count,
                        relation.source_video_count,
                        relation.unique_authors,
                        relation.sort_coverage,
                        relation.weight,
                        relation.relationship_score,
                        relation.visible_metric_max,
                        int(relation.expanded),
                        json.dumps(
                            relation.supporting_item_ids, ensure_ascii=False
                        ),
                        relation.collected_at,
                    ),
                )
            for snapshot in tag_traffic_snapshots or []:
                snapshot.run_id = run_id
                self._upsert_tag(conn, snapshot.tag, snapshot.collected_at)
                conn.execute(
                    """
                    INSERT INTO trend_tag_traffic_snapshots (
                        run_id, root_keyword, tag, sort_key, sort_label,
                        unique_video_count, best_rank, reciprocal_rank_score,
                        sample_score, visible_metric_max, visible_metric_median,
                        top_item_ids_json, metric_kind, score_kind, collected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, root_keyword, tag, sort_key) DO UPDATE SET
                        sort_label = excluded.sort_label,
                        unique_video_count = excluded.unique_video_count,
                        best_rank = excluded.best_rank,
                        reciprocal_rank_score = excluded.reciprocal_rank_score,
                        sample_score = excluded.sample_score,
                        visible_metric_max = excluded.visible_metric_max,
                        visible_metric_median = excluded.visible_metric_median,
                        top_item_ids_json = excluded.top_item_ids_json,
                        metric_kind = excluded.metric_kind,
                        score_kind = excluded.score_kind,
                        collected_at = excluded.collected_at
                    """,
                    (
                        run_id,
                        snapshot.root_keyword,
                        snapshot.tag,
                        snapshot.sort_key,
                        snapshot.sort_label,
                        snapshot.unique_video_count,
                        snapshot.best_rank,
                        snapshot.reciprocal_rank_score,
                        snapshot.sample_score,
                        snapshot.visible_metric_max,
                        snapshot.visible_metric_median,
                        json.dumps(snapshot.top_item_ids, ensure_ascii=False),
                        snapshot.metric_kind,
                        snapshot.score_kind,
                        snapshot.collected_at,
                    ),
                )
        return run_id

    @staticmethod
    def _upsert_tag(
        conn: sqlite3.Connection,
        tag: str,
        captured_at: str,
    ) -> None:
        if not tag:
            return
        conn.execute(
            """
            INSERT INTO trend_tags (
                tag, display_name, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(tag) DO UPDATE SET
                display_name = excluded.display_name,
                last_seen_at = excluded.last_seen_at
            """,
            (tag, tag, captured_at, captured_at),
        )

    def list_observations(self, limit: int = 2000) -> list[TrendObservation]:
        safe_limit = max(1, min(int(limit), 100_000))
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT i.item_id, i.video_id, i.url, i.title, i.author,
                       o.run_id,
                       o.keyword, o.sort_key, o.sort_label, o.rank,
                       o.metric_text, o.metric_value, o.collected_at, o.raw_text,
                       o.metric_kind, o.published_at, o.published_at_text,
                       o.query_kind, o.query_value, o.query_depth,
                       o.root_keywords_json, o.hashtags_json
                FROM trend_observations o
                JOIN trend_items i ON i.item_id = o.item_id
                ORDER BY o.collected_at DESC, o.rank ASC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            TrendObservation(
                item_id=row["item_id"],
                video_id=row["video_id"] or "",
                url=row["url"],
                title=row["title"],
                author=row["author"],
                keyword=row["keyword"],
                sort_key=row["sort_key"],
                sort_label=row["sort_label"],
                rank=row["rank"],
                run_id=row["run_id"],
                metric_text=row["metric_text"],
                metric_value=row["metric_value"],
                metric_kind=row["metric_kind"],
                collected_at=row["collected_at"],
                published_at=row["published_at"],
                published_at_text=row["published_at_text"],
                raw_text=row["raw_text"],
                query_kind=row["query_kind"],
                query_value=row["query_value"] or row["keyword"],
                query_depth=row["query_depth"],
                root_keywords=_json_string_list(row["root_keywords_json"]),
                hashtags=_json_string_list(row["hashtags_json"]),
            )
            for row in rows
        ]

    def latest_collection_run_id(self) -> str:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT run_id
                FROM trend_collection_runs
                ORDER BY finished_at DESC, started_at DESC
                LIMIT 1
                """
            ).fetchone()
        return row["run_id"] if row else ""

    def list_tag_relations(
        self,
        *,
        run_id: str = "",
        limit: int = 1000,
    ) -> list[TrendTagRelation]:
        query = "SELECT * FROM trend_tag_relations"
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY relationship_score DESC, collected_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100_000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            TrendTagRelation(
                root_keyword=row["root_keyword"],
                source_kind=row["source_kind"],
                source_value=row["source_value"],
                target_tag=row["target_tag"],
                relation_kind=row["relation_kind"],
                support_video_count=row["support_video_count"],
                source_video_count=row["source_video_count"],
                unique_authors=row["unique_authors"],
                sort_coverage=row["sort_coverage"],
                weight=row["weight"],
                relationship_score=row["relationship_score"],
                visible_metric_max=row["visible_metric_max"],
                expanded=bool(row["expanded"]),
                supporting_item_ids=_json_string_list(
                    row["supporting_item_ids_json"]
                ),
                run_id=row["run_id"],
                collected_at=row["collected_at"],
            )
            for row in rows
        ]

    def list_tag_traffic_snapshots(
        self,
        *,
        run_id: str = "",
        limit: int = 1000,
    ) -> list[TrendTagTrafficSnapshot]:
        query = "SELECT * FROM trend_tag_traffic_snapshots"
        params: list[object] = []
        if run_id:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY sample_score DESC, collected_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100_000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            TrendTagTrafficSnapshot(
                root_keyword=row["root_keyword"],
                tag=row["tag"],
                sort_key=row["sort_key"],
                sort_label=row["sort_label"],
                unique_video_count=row["unique_video_count"],
                best_rank=row["best_rank"],
                reciprocal_rank_score=row["reciprocal_rank_score"],
                sample_score=row["sample_score"],
                visible_metric_max=row["visible_metric_max"],
                visible_metric_median=row["visible_metric_median"],
                top_item_ids=_json_string_list(row["top_item_ids_json"]),
                metric_kind=row["metric_kind"],
                score_kind=row["score_kind"],
                run_id=row["run_id"],
                collected_at=row["collected_at"],
            )
            for row in rows
        ]

    def save_content_analysis(self, analysis: VideoContentAnalysis) -> None:
        now = utc_now_iso()
        relevance_score = (
            analysis.relevance.score if analysis.relevance is not None else None
        )
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trend_content_analyses (
                    analysis_id, item_id, video_id, account_uuid,
                    profile_version, provider_id, provider_version,
                    input_fingerprint, status, presentation_type,
                    relevance_score, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(analysis_id) DO UPDATE SET
                    status = excluded.status,
                    presentation_type = excluded.presentation_type,
                    relevance_score = excluded.relevance_score,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    analysis.analysis_id,
                    analysis.item_id,
                    analysis.video_id,
                    analysis.account_uuid,
                    analysis.profile_version,
                    analysis.provider_id,
                    analysis.provider_version,
                    analysis.input_fingerprint,
                    analysis.status,
                    analysis.presentation_type,
                    relevance_score,
                    json.dumps(asdict(analysis), ensure_ascii=False),
                    analysis.created_at,
                    now,
                ),
            )

    def get_content_analysis(
        self, analysis_id: str
    ) -> VideoContentAnalysis | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM trend_content_analyses WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            return None
        return _content_analysis_from_dict(json.loads(row["payload_json"]))

    def list_content_analyses(
        self,
        *,
        account_uuid: str = "",
        item_id: str = "",
        limit: int = 1000,
    ) -> list[VideoContentAnalysis]:
        query = "SELECT payload_json FROM trend_content_analyses"
        clauses: list[str] = []
        params: list[object] = []
        if account_uuid:
            clauses.append("account_uuid = ?")
            params.append(account_uuid)
        if item_id:
            clauses.append("item_id = ?")
            params.append(item_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100_000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            _content_analysis_from_dict(json.loads(row["payload_json"]))
            for row in rows
        ]

    def save_content_analysis_batch(
        self, result: ContentAnalysisBatchResult
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trend_content_analysis_batches (
                    batch_id, implementation_id, account_uuid,
                    requested_count, completed_count, degraded_count,
                    failed_count, cached_count, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.batch_id,
                    result.implementation_id,
                    result.account_uuid,
                    result.requested_count,
                    result.completed_count,
                    result.degraded_count,
                    result.failed_count,
                    result.cached_count,
                    json.dumps(asdict(result), ensure_ascii=False),
                    result.created_at,
                ),
            )

    def save_opportunity(self, opportunity: ContentOpportunity) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trend_content_opportunities (
                    opportunity_id, account_uuid, profile_version,
                    domain_strategy_id, strategy_version, cluster_id,
                    status, score, valid_until, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(opportunity_id) DO UPDATE SET
                    status = excluded.status,
                    score = excluded.score,
                    valid_until = excluded.valid_until,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    opportunity.opportunity_id,
                    opportunity.account_uuid,
                    opportunity.profile_version,
                    opportunity.domain_strategy_id,
                    opportunity.strategy_version,
                    opportunity.cluster_id,
                    opportunity.status,
                    opportunity.opportunity_score,
                    opportunity.valid_until,
                    json.dumps(asdict(opportunity), ensure_ascii=False),
                    opportunity.created_at,
                    now,
                ),
            )

    def get_opportunity(self, opportunity_id: str) -> ContentOpportunity | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json, status
                FROM trend_content_opportunities
                WHERE opportunity_id = ?
                """,
                (opportunity_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["status"] = row["status"]
        return ContentOpportunity(**payload)

    def list_opportunities(
        self,
        *,
        account_uuid: str = "",
        status: str | None = None,
        limit: int = 500,
    ) -> list[ContentOpportunity]:
        query = "SELECT payload_json, status FROM trend_content_opportunities"
        clauses: list[str] = []
        params: list[object] = []
        if account_uuid:
            clauses.append("account_uuid = ?")
            params.append(account_uuid)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY score DESC LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        output: list[ContentOpportunity] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["status"] = row["status"]
            output.append(ContentOpportunity(**payload))
        return output

    def update_opportunity_status(self, opportunity_id: str, status: str) -> bool:
        if status not in {"candidate", "approved", "rejected", "used", "expired"}:
            raise ValueError("invalid opportunity status")
        return self._update_payload_status(
            table="trend_content_opportunities",
            id_column="opportunity_id",
            identity=opportunity_id,
            status=status,
        )

    def save_opportunity_script(self, script: OpportunityScript) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trend_opportunity_scripts (
                    script_id, opportunity_id, account_uuid,
                    domain_strategy_id, strategy_version, variant_id,
                    status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(script_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    script.script_id,
                    script.opportunity_id,
                    script.account_uuid,
                    script.domain_strategy_id,
                    script.strategy_version,
                    script.variant_id,
                    script.status,
                    json.dumps(asdict(script), ensure_ascii=False),
                    script.created_at,
                    now,
                ),
            )

    def list_opportunity_scripts(
        self,
        *,
        opportunity_id: str = "",
        status: str | None = None,
        limit: int = 500,
    ) -> list[OpportunityScript]:
        query = "SELECT payload_json, status FROM trend_opportunity_scripts"
        clauses: list[str] = []
        params: list[object] = []
        if opportunity_id:
            clauses.append("opportunity_id = ?")
            params.append(opportunity_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, variant_id LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        output: list[OpportunityScript] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["status"] = row["status"]
            payload["beats"] = [
                ScriptBeat(**item) for item in payload.get("beats", [])
            ]
            output.append(OpportunityScript(**payload))
        return output

    def update_opportunity_script_status(self, script_id: str, status: str) -> bool:
        if status not in {"draft", "approved", "rejected", "used"}:
            raise ValueError("invalid opportunity script status")
        return self._update_payload_status(
            table="trend_opportunity_scripts",
            id_column="script_id",
            identity=script_id,
            status=status,
        )

    def _update_payload_status(
        self,
        *,
        table: str,
        id_column: str,
        identity: str,
        status: str,
    ) -> bool:
        allowed = {
            ("trend_content_opportunities", "opportunity_id"),
            ("trend_opportunity_scripts", "script_id"),
        }
        if (table, id_column) not in allowed:
            raise ValueError("unsupported status table")
        with self.connection() as conn:
            row = conn.execute(
                f"SELECT payload_json FROM {table} WHERE {id_column} = ?",
                (identity,),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(row["payload_json"])
            payload["status"] = status
            cursor = conn.execute(
                f"UPDATE {table} SET status = ?, payload_json = ?, updated_at = ? "
                f"WHERE {id_column} = ?",
                (
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    utc_now_iso(),
                    identity,
                ),
            )
        return cursor.rowcount > 0

    def save_analysis(
        self,
        clusters: list[TrendCluster],
        briefs: list[TrendBrief],
    ) -> None:
        with self.connection() as conn:
            for cluster in clusters:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trend_clusters (
                        cluster_id, title, score, score_kind, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cluster.cluster_id,
                        cluster.title,
                        cluster.selection_score,
                        cluster.score_kind,
                        json.dumps(asdict(cluster), ensure_ascii=False),
                        cluster.created_at,
                    ),
                )
            for brief in briefs:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trend_briefs (
                        brief_id, cluster_id, title, status, score,
                        score_kind, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        brief.brief_id,
                        brief.cluster_id,
                        brief.title,
                        brief.status,
                        brief.score,
                        brief.score_kind,
                        json.dumps(asdict(brief), ensure_ascii=False),
                        brief.created_at,
                    ),
                )

    def list_clusters(self, limit: int = 100) -> list[TrendCluster]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM trend_clusters ORDER BY score DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [TrendCluster(**json.loads(row["payload_json"])) for row in rows]

    def list_briefs(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TrendBrief]:
        query = "SELECT payload_json, status FROM trend_briefs"
        params: list[object] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY score DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        briefs: list[TrendBrief] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["status"] = row["status"]
            briefs.append(TrendBrief(**payload))
        return briefs

    def get_brief(self, brief_id: str) -> TrendBrief | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM trend_briefs WHERE brief_id = ?",
                (brief_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["status"] = row["status"]
        return TrendBrief(**payload)

    def update_brief_status(self, brief_id: str, status: str) -> bool:
        if status not in {"draft", "approved", "rejected", "used"}:
            raise ValueError("invalid brief status")
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM trend_briefs WHERE brief_id = ?",
                (brief_id,),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(row["payload_json"])
            payload["status"] = status
            cursor = conn.execute(
                "UPDATE trend_briefs SET status = ?, payload_json = ? WHERE brief_id = ?",
                (status, json.dumps(payload, ensure_ascii=False), brief_id),
            )
            return cursor.rowcount > 0

    def link_published_content(self, context: PublishedContentContext) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO published_content_context (
                    local_id, video_id, brief_id, cluster_id, script_version,
                    workflow_profile, hook_type, content_format, duration_seconds,
                    published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(local_id) DO UPDATE SET
                    video_id = CASE
                        WHEN excluded.video_id != '' THEN excluded.video_id
                        ELSE published_content_context.video_id
                    END,
                    brief_id = excluded.brief_id,
                    cluster_id = excluded.cluster_id,
                    script_version = excluded.script_version,
                    workflow_profile = excluded.workflow_profile,
                    hook_type = excluded.hook_type,
                    content_format = excluded.content_format,
                    duration_seconds = excluded.duration_seconds,
                    published_at = excluded.published_at,
                    updated_at = excluded.updated_at
                """,
                (
                    context.local_id,
                    context.video_id,
                    context.brief_id,
                    context.cluster_id,
                    context.script_version,
                    context.workflow_profile,
                    context.hook_type,
                    context.content_format,
                    context.duration_seconds,
                    context.published_at,
                    now,
                    now,
                ),
            )

    def attach_video_id(self, local_id: str, video_id: str) -> bool:
        if not local_id or not video_id:
            return False
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE published_content_context
                SET video_id = ?, updated_at = ?
                WHERE local_id = ?
                """,
                (video_id, utc_now_iso(), local_id),
            )
            return cursor.rowcount > 0

    def record_video_snapshot(self, snapshot: VideoMetricSnapshot) -> None:
        if not snapshot.video_id and not snapshot.local_id:
            raise ValueError("snapshot requires video_id or local_id")
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO video_metric_snapshots (
                    video_id, local_id, captured_at, publish_time,
                    views, likes, comments, shares, collects
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.video_id,
                    snapshot.local_id,
                    snapshot.captured_at,
                    snapshot.publish_time,
                    max(0, snapshot.views),
                    max(0, snapshot.likes),
                    max(0, snapshot.comments),
                    max(0, snapshot.shares),
                    max(0, snapshot.collects),
                ),
            )

    def list_contexts(self) -> list[PublishedContentContext]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM published_content_context ORDER BY created_at DESC"
            ).fetchall()
        return [
            PublishedContentContext(
                local_id=row["local_id"],
                video_id=row["video_id"],
                brief_id=row["brief_id"],
                cluster_id=row["cluster_id"],
                script_version=row["script_version"],
                workflow_profile=row["workflow_profile"],
                hook_type=row["hook_type"],
                content_format=row["content_format"],
                duration_seconds=row["duration_seconds"],
                published_at=row["published_at"],
            )
            for row in rows
        ]

    def list_video_snapshots(
        self,
        *,
        video_id: str = "",
        local_id: str = "",
    ) -> list[VideoMetricSnapshot]:
        if not video_id and not local_id:
            query = "SELECT * FROM video_metric_snapshots ORDER BY captured_at"
            params: tuple[object, ...] = ()
        else:
            query = (
                "SELECT * FROM video_metric_snapshots "
                "WHERE (? != '' AND video_id = ?) OR (? != '' AND local_id = ?) "
                "ORDER BY captured_at"
            )
            params = (video_id, video_id, local_id, local_id)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            VideoMetricSnapshot(
                video_id=row["video_id"],
                local_id=row["local_id"],
                captured_at=row["captured_at"],
                publish_time=row["publish_time"],
                views=row["views"],
                likes=row["likes"],
                comments=row["comments"],
                shares=row["shares"],
                collects=row["collects"],
            )
            for row in rows
        ]

    def summary(self) -> dict[str, int]:
        with self.connection() as conn:
            return {
                "runs": conn.execute(
                    "SELECT COUNT(*) FROM trend_collection_runs"
                ).fetchone()[0],
                "items": conn.execute("SELECT COUNT(*) FROM trend_items").fetchone()[0],
                "briefs": conn.execute("SELECT COUNT(*) FROM trend_briefs").fetchone()[0],
                "approved": conn.execute(
                    "SELECT COUNT(*) FROM trend_briefs WHERE status = 'approved'"
                ).fetchone()[0],
                "snapshots": conn.execute(
                    "SELECT COUNT(*) FROM video_metric_snapshots"
                ).fetchone()[0],
                "plans": conn.execute(
                    "SELECT COUNT(*) FROM trend_collection_plans"
                ).fetchone()[0],
                "content_analyses": conn.execute(
                    "SELECT COUNT(*) FROM trend_content_analyses"
                ).fetchone()[0],
                "opportunities": conn.execute(
                    "SELECT COUNT(*) FROM trend_content_opportunities"
                ).fetchone()[0],
                "opportunity_scripts": conn.execute(
                    "SELECT COUNT(*) FROM trend_opportunity_scripts"
                ).fetchone()[0],
            }


def _json_string_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item)]


def _content_analysis_from_dict(payload: dict[str, object]) -> VideoContentAnalysis:
    data = dict(payload)
    data["segments"] = [
        ContentSegment(**item) for item in data.get("segments", [])
    ]
    data["evidence"] = [
        ContentEvidence(**item) for item in data.get("evidence", [])
    ]
    relevance = data.get("relevance")
    if isinstance(relevance, dict):
        relevance_data = dict(relevance)
        relevance_data["evidence"] = [
            ContentEvidence(**item)
            for item in relevance_data.get("evidence", [])
        ]
        data["relevance"] = AccountContentRelevance(**relevance_data)
    return VideoContentAnalysis(**data)
