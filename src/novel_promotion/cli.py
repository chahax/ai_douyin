"""
src/novel_promotion/cli.py — 番茄闭环 P0 CLI 子命令

被 main.py 调用，提供 add_parsers 和 dispatch 两个入口。
"""

import json
import sys
from pathlib import Path

from src.shared.database import SessionLocal
from src.shared.logger import logger


# ── Parser registration ────────────────────────────────────────────────────────


def add_fanqie_closed_loop_parsers(subparsers):
    """Register fanqie-task-* and fanqie-douyin-* subcommands on the given subparsers."""

    # fanqie-task-list
    task_list_parser = subparsers.add_parser("fanqie-task-list", help="List promotion tasks from DB")
    task_list_parser.add_argument("--status", type=str, default="",
                                  help="Filter by status (e.g. manual_intervention, active, bound)")
    task_list_parser.add_argument("--limit", type=int, default=200, help="Max rows")

    # fanqie-task-show
    task_show_parser = subparsers.add_parser("fanqie-task-show", help="Show one task detail by ID or UUID")
    task_show_parser.add_argument("--id", type=int, default=None, help="Task internal ID")
    task_show_parser.add_argument("--uuid", type=str, default="", help="Task UUID")

    # fanqie-task-events
    task_events_parser = subparsers.add_parser("fanqie-task-events", help="Show events for a task")
    task_events_parser.add_argument("--id", type=int, required=True, help="Task internal ID")

    # fanqie-task-reconcile
    task_reconcile_parser = subparsers.add_parser("fanqie-task-reconcile",
                                                  help="Reconcile filesystem tasks with DB")
    task_reconcile_parser.add_argument("--data-root", type=str, default="data/fanqie_promotion",
                                       help="Filesystem root")

    # fanqie-task-import (dry-run + import)
    task_import_parser = subparsers.add_parser("fanqie-task-import",
                                               help="Import old JSON files into DB (idempotent)")
    task_import_parser.add_argument("--dry-run", action="store_true",
                                    help="Preview only, no writes")
    task_import_parser.add_argument("--data-root", type=str, default="data/fanqie_promotion",
                                    help="Filesystem root")
    task_import_parser.add_argument("--book-id-report", action="store_true",
                                    help="Only scan and report book_id formats")

    # fanqie-douyin-migrate
    douyin_migrate_parser = subparsers.add_parser("fanqie-douyin-migrate",
                                                  help="Add account_key to douyin.db:videos")
    douyin_migrate_parser.add_argument("action", choices=["check", "upgrade", "downgrade", "set"],
                                       help="Migration action")
    douyin_migrate_parser.add_argument("--db-path", type=str, default="",
                                       help="Path to douyin.db")
    douyin_migrate_parser.add_argument("--dry-run", action="store_true",
                                       help="Preview upgrade only")
    douyin_migrate_parser.add_argument("--confirm", action="store_true",
                                       help="Confirm destructive downgrade")
    douyin_migrate_parser.add_argument("--video-id", type=str, default="")
    douyin_migrate_parser.add_argument("--account-key", type=str, default="")

    # fanqie-task-sync-douyin
    sync_douyin_parser = subparsers.add_parser("fanqie-task-sync-douyin",
                                               help="Sync douyin video to fanqie publish record")
    sync_douyin_parser.add_argument("--account-key", type=str, required=True,
                                    help="Account key for validation")
    sync_douyin_parser.add_argument("--video-id", type=str, required=True,
                                    help="Douyin video ID to sync")

    # P0-A probe
    p0a_parser = subparsers.add_parser("fanqie-task-p0a-probe",
                                       help="Run P0-A field investigation probe (read-only)")
    p0a_parser.add_argument("--fixture", type=str, default="",
                            help="Path to JSON fixture file for testing")


# ── Command dispatch ───────────────────────────────────────────────────────────


def dispatch_fanqie_closed_loop_commands(args):
    """Dispatch fanqie-task-* and fanqie-douyin-* commands."""

    if args.command == "fanqie-task-list":
        from src.novel_promotion.task_service import TaskService
        status = args.status if args.status else None
        with SessionLocal() as db:
            svc = TaskService(db)
            tasks = svc.list_tasks(status=status)
            if args.limit and len(tasks) > args.limit:
                tasks = tasks[:args.limit]
            result = []
            for t in tasks:
                result.append({
                    "id": t.id,
                    "task_uuid": t.task_uuid,
                    "book_id": t.book_id,
                    "promotion_alias": t.promotion_alias,
                    "status": t.status,
                    "publish_type": t.publish_type,
                    "version": t.version,
                    "created_by": t.created_by,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                })
            print(json.dumps({"count": len(result), "tasks": result}, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-task-show":
        from src.novel_promotion.task_service import TaskService
        with SessionLocal() as db:
            svc = TaskService(db)
            if args.id:
                task = svc.get_task(args.id)
            elif args.uuid:
                task = svc.get_task_by_uuid(args.uuid)
            else:
                logger.error("需要 --id 或 --uuid")
                sys.exit(1)
            if not task:
                logger.error("Task not found")
                sys.exit(1)
            print(json.dumps({
                "id": task.id,
                "task_uuid": task.task_uuid,
                "book_id": task.book_id,
                "platform_task_id": task.platform_task_id,
                "promotion_alias": task.promotion_alias,
                "publish_type": task.publish_type,
                "status": task.status,
                "failure_stage": task.failure_stage,
                "version": task.version,
                "valid_from": task.valid_from.isoformat() if task.valid_from else None,
                "valid_until": task.valid_until.isoformat() if task.valid_until else None,
                "application_snapshot_path": task.application_snapshot_path,
                "last_error": task.last_error,
                "manual_reason": task.manual_reason,
                "created_by": task.created_by,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-task-events":
        from src.novel_promotion.task_service import TaskService
        with SessionLocal() as db:
            svc = TaskService(db)
            events = svc.get_events(args.id)
            result = []
            for e in events:
                result.append({
                    "id": e.id,
                    "event_uuid": e.event_uuid,
                    "event_type": e.event_type,
                    "from_status": e.from_status,
                    "to_status": e.to_status,
                    "actor_type": e.actor_type,
                    "actor_id": e.actor_id,
                    "payload": e.payload_json,
                    "artifact_path": e.artifact_path,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                })
            print(json.dumps({"count": len(result), "events": result}, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-task-reconcile":
        from src.novel_promotion.reconcile_service import ReconcileService
        with SessionLocal() as db:
            svc = ReconcileService(db, data_root=args.data_root)
            report = svc.reconcile()
            result = {
                "summary": report.summary,
                "entries": [
                    {
                        "type": e.type,
                        "source": e.source,
                        "file_status": e.file_status,
                        "db_status": e.db_status,
                        "file_alias": e.file_alias,
                        "db_alias": e.db_alias,
                        "file_book_id": e.file_book_id,
                        "detail": e.detail,
                    }
                    for e in report.entries
                ],
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-task-import":
        from src.novel_promotion.import_service import ImportService
        with SessionLocal() as db:
            svc = ImportService(db, data_root=args.data_root)
            if args.book_id_report:
                report = svc.scan_book_id_formats()
                print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
            elif args.dry_run:
                report = svc.dry_run()
                print(json.dumps({
                    "dry_run": True,
                    "books_created": report.books_created,
                    "books_updated": report.books_updated,
                    "books_skipped": report.books_skipped,
                    "tasks_created": report.tasks_created,
                    "tasks_skipped": report.tasks_skipped,
                    "issues": report.issues,
                }, ensure_ascii=False, indent=2))
            else:
                report = svc.import_all()
                print(json.dumps({
                    "books_created": report.books_created,
                    "books_updated": report.books_updated,
                    "books_skipped": report.books_skipped,
                    "tasks_created": report.tasks_created,
                    "tasks_skipped": report.tasks_skipped,
                    "issues": report.issues,
                }, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-douyin-migrate":
        from src.novel_promotion.douyin_migration import (
            check_account_key, upgrade_account_key, downgrade_account_key,
            update_account_key, _find_db,
        )
        db_path = Path(args.db_path) if args.db_path else _find_db()
        if args.action == "check":
            result = check_account_key(db_path)
        elif args.action == "upgrade":
            result = upgrade_account_key(db_path, dry_run=args.dry_run)
        elif args.action == "downgrade":
            result = downgrade_account_key(db_path, confirm=args.confirm)
        elif args.action == "set":
            result = update_account_key(db_path, args.video_id, args.account_key)
        else:
            logger.error(f"Unknown action: {args.action}")
            sys.exit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-task-sync-douyin":
        from src.novel_promotion.publish_service import NovelPromotionPublishSyncService
        with SessionLocal() as db:
            svc = NovelPromotionPublishSyncService(db)
            result = svc.sync_by_account_and_video_id(
                account_key=args.account_key,
                douyin_video_id=args.video_id,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-task-p0a-probe":
        from src.novel_promotion.p0a_probe import run_probe_from_raw_data
        if args.fixture:
            items = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        else:
            print(json.dumps({
                "note": "P0-A probe requires browser data. Use --fixture to pass test data, "
                        "or run fanqie-promo-list to get live promotion list data.",
                "usage": "python main.py fanqie-task-p0a-probe --fixture tests/fixtures/p0a_sample_list.json",
            }, ensure_ascii=False, indent=2))
            return
        print(run_probe_from_raw_data(items))
        return
