"""Export existing trend evidence read-only, and prepare offline creative inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.content_factory.creative_trend_bridge import (
    build_packet, build_direction_preview, build_writer_preview, render_selection_review)
from src.content_factory.creative_story_emotion import digest


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_bundle(output, values):
    """Preflight all outputs; identical replay is harmless, changed evidence is refused."""
    output = Path(output)
    raw = {name: (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n")
           for name, value in values.items()}
    for name, value in raw.items():
        target = output / name
        if target.exists() and target.read_text(encoding="utf-8-sig") != value:
            raise ValueError("different output already exists: " + str(target))
    output.mkdir(parents=True, exist_ok=True)
    for name, value in raw.items():
        target = output / name
        if not target.exists():
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(value)


def export_source(trend_db, profile_db, opportunity_id, run_id, *, tag_scope, max_sample_age_hours):
    """No repository constructors: SQLite mode=ro prevents migrations and writes."""
    paths = [Path(trend_db).resolve(), Path(profile_db).resolve()]
    before = {str(p): file_sha(p) for p in paths}
    with sqlite3.connect(paths[0].as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        stored = conn.execute("SELECT payload_json FROM trend_content_opportunities WHERE opportunity_id=?",
                              (opportunity_id,)).fetchone()
        run = conn.execute("SELECT run_id,provider,status,started_at,finished_at,account_uuid,profile_version,"
            "domain_strategy_id,strategy_version FROM trend_collection_runs WHERE run_id=?", (run_id,)).fetchone()
        if not stored or not run:
            raise ValueError("exact opportunity and collection run required")
        op = json.loads(stored[0])
        if op.get("opportunity_id") != opportunity_id:
            raise ValueError("stored opportunity identity mismatch")
        rows = [dict(r) for r in conn.execute(
            "SELECT o.run_id,o.item_id,i.video_id,i.url,i.title,i.author,o.keyword,o.root_keywords_json,"
            "o.hashtags_json,o.metric_kind,o.metric_value,o.metric_text,o.collected_at,"
            "o.sort_key,o.sort_label,o.rank,o.query_kind,o.query_value,o.query_depth "
            "FROM trend_observations o JOIN trend_items i ON i.item_id=o.item_id "
            "WHERE o.run_id=? ORDER BY o.id", (run_id,))]
    with sqlite3.connect(paths[1].as_uri() + "?mode=ro", uri=True) as conn:
        profile = conn.execute("SELECT profile_json FROM account_strategy_versions WHERE account_uuid=? AND profile_version=?",
                              (op["account_uuid"], op["profile_version"])).fetchone()
        if not profile:
            raise ValueError("exact frozen account strategy version required")
        profile = json.loads(profile[0])
    for row in rows:
        row["root_keywords"] = json.loads(row.pop("root_keywords_json"))
        row["hashtags"] = json.loads(row.pop("hashtags_json"))
    if any(file_sha(p) != h for p, h in ((Path(k), v) for k, v in before.items())):
        raise ValueError("database changed during read-only export")
    return {"account_profile": profile, "collection_run": dict(run), "opportunity": op,
        "observations": rows, "selection_policy": {"tag_scope": tag_scope,
                                                    "max_sample_age_hours": max_sample_age_hours}}, before


def prepare(source_path, reference_path, standards_path, *, now):
    inputs = [Path(p).resolve() for p in (source_path, reference_path, standards_path)]
    before = {str(p): file_sha(p) for p in inputs}
    packet = build_packet(read(inputs[0]), inputs[1].read_text(encoding="utf-8-sig"), read(inputs[2]), now=now)
    if any(file_sha(Path(p)) != h for p, h in before.items()):
        raise ValueError("source changed during preparation")
    values = {"SOURCE_PACKET.json": packet, "TOPIC_SELECTION_REVIEW.md": render_selection_review(packet)}
    if not packet["blockers"]:
        values["STORY_DIRECTION_REQUEST_NOT_SUBMITTED.json"] = build_direction_preview(packet, now=now)
    values["EVIDENCE.json"] = {"schema": "trend_creative_offline_evidence/v1", "source_file_sha256": before,
        "packet_sha256": digest(packet), "blockers": packet["blockers"], "model_calls": 0,
        "media_calls": 0, "publishing_calls": 0, "frozen_records_modified": False,
        "old_budget_reset": False, "creative_quality_passed": False}
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description="Trend tags to complete creative inputs; offline only")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-source", help="read existing SQLite evidence; never collect")
    export.add_argument("--trend-db", type=Path, default=ROOT / "data/trend_intelligence.db")
    export.add_argument("--profile-db", type=Path, default=ROOT / "data/douyin.db")
    export.add_argument("--opportunity-id", required=True)
    export.add_argument("--run-id", required=True)
    export.add_argument("--tag-scope", choices=("pending", "account_positioning", "site_wide"), default="pending")
    export.add_argument("--max-sample-age-hours", type=int, default=72)
    export.add_argument("--output", type=Path, required=True)
    prep = commands.add_parser("prepare", help="freeze source and produce topic review/request preview")
    prep.add_argument("--source", type=Path, required=True)
    prep.add_argument("--reference-fulltext", type=Path, required=True)
    prep.add_argument("--standards", type=Path, required=True)
    writer = commands.add_parser("writer-preview", help="requires actual exact-source user direction confirmation")
    writer.add_argument("--packet", type=Path, required=True)
    writer.add_argument("--direction", type=Path, required=True)
    writer.add_argument("--confirmation", type=Path, required=True)
    for command in (prep, writer):
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--now", default=None, help="timezone-aware ISO time; default current UTC")
    args = parser.parse_args(argv)
    if args.command == "export-source":
        source, hashes = export_source(args.trend_db, args.profile_db, args.opportunity_id, args.run_id,
            tag_scope=args.tag_scope, max_sample_age_hours=args.max_sample_age_hours)
        values = {"TREND_SOURCE.json": source, "EXPORT_EVIDENCE.json": {"database_sha256": hashes,
                  "mode": "sqlite_read_only", "new_collection_calls": 0}}
    else:
        now = args.now or datetime.now(timezone.utc).isoformat()
        if args.command == "prepare":
            values = prepare(args.source, args.reference_fulltext, args.standards, now=now)
        else:
            packet, direction, confirmation = [read(p) for p in (args.packet, args.direction, args.confirmation)]
            preview = build_writer_preview(packet, direction, confirmation, now=now)
            values = {"CREATIVE_BRIEF.json": direction["creative_brief"],
                "EMOTIONAL_BRIEF.json": direction["emotional_brief"], "CHARACTERS.json": direction["characters"],
                "COMPLETE_STORY_REQUEST_NOT_SUBMITTED.json": preview,
                "EVIDENCE.json": {"packet_sha256": digest(packet), "direction_sha256": digest(direction),
                    "confirmation_sha256": digest(confirmation), "preview_sha256": digest(preview),
                    "model_calls": 0, "media_calls": 0, "creative_quality_passed": False, "old_budget_reset": False}}
    write_bundle(args.output, values)
    print(json.dumps({"output": str(args.output.resolve()), "files": list(values), "model_calls": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
