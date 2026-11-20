"""Account opportunity to full novel creation; preparation never calls providers."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.operations_accounts.repository import AccountProfileRepository, DEFAULT_DB_PATH as ACCOUNT_DB  # noqa: E402
from src.trend_intelligence.repository import TrendRepository, DEFAULT_DB_PATH as TREND_DB  # noqa: E402

CONTEXT_FILE = "ENTRY_CONTEXT.json"


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _opportunity_source(opportunity) -> dict:
    payload = asdict(opportunity)
    payload.pop("status", None)  # Approval can change; the underlying source cannot.
    return payload


def load_current(account_db, trend_db, account_key, opportunity_id):
    """Load active records, including the separate account disable switch."""
    account_db, trend_db = Path(account_db).resolve(), Path(trend_db).resolve()
    if not account_db.is_file() or not trend_db.is_file():
        raise ValueError("账号或机会数据库不存在；不能建立空库代替真实来源")
    accounts = AccountProfileRepository(account_db)
    trends = TrendRepository(trend_db)
    profile = accounts.get(account_key)
    with accounts.connection() as conn:
        row = conn.execute("SELECT status FROM douyin_accounts WHERE account_uuid = ?",
                           (profile.account_uuid,)).fetchone()
    if row is None or row["status"] != "active" or profile.status != "active":
        raise ValueError("账号已暂停或禁用，不能启动小说创作")
    opportunity = trends.get_opportunity(opportunity_id)
    if opportunity is None:
        raise ValueError("账号机会不存在")
    return profile, opportunity


def _context(profile, opportunity, account_db, trend_db) -> dict:
    return {"schema": "account_novel_entry_context/v1",
            "account_db": str(Path(account_db).resolve()),
            "trend_db": str(Path(trend_db).resolve()),
            "account_key": profile.account_key, "account_uuid": profile.account_uuid,
            "opportunity_id": opportunity.opportunity_id,
            "profile_sha256": _digest(asdict(profile)),
            "opportunity_source_sha256": _digest(_opportunity_source(opportunity))}


def _freeze_context(run_dir: Path, context: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / CONTEXT_FILE
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(context, handle, ensure_ascii=False, indent=2)
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf-8")) != context:
            raise ValueError("原任务账号、机会或数据库绑定已改变；不能覆盖或换来源恢复")


def _bind_entry_context(run_dir: Path) -> None:
    """Finalize entry provenance once, before any creative execution exists."""
    from src.content_factory.creative_workflow_inputs import file_binding, verify_binding
    binding_path = run_dir / "BINDING.json"
    if not binding_path.exists():
        return
    lock = run_dir / ".account_novel_entry_binding.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write("entry provenance finalization")
    except FileExistsError:
        raise RuntimeError("入口绑定正在准备，先核对原任务") from None
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        marker_path = run_dir / ".account_novel_preparation.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        def binding_digest(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if marker.get("binding_sha256") != binding_digest(binding):
            raise ValueError("原任务绑定hash锚不符，不能补写入口来源")
        context_path = run_dir / CONTEXT_FILE
        prior = binding["files"].get("entry_context")
        if prior:
            if prior.get("path") != str(context_path.resolve()):
                raise ValueError("原任务数据库绑定路径不一致")
            verify_binding(prior)
            return
        if (run_dir / "creative").exists():
            raise ValueError("任务已经进入创作，不能新增或改写入口来源绑定")
        binding["files"]["entry_context"] = file_binding(context_path)
        binding["code_bindings"].append(file_binding(Path(__file__)))
        temporary = run_dir / ".ENTRY_BINDING.pending.json"
        temporary.write_text(json.dumps(binding, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(binding_path)
        marker["binding_sha256"] = binding_digest(binding)
        marker_temporary = run_dir / ".ENTRY_MARKER.pending.json"
        marker_temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
        marker_temporary.replace(marker_path)
    finally:
        lock.unlink()


def prepare_from_repositories(*, account_key, opportunity_id, run_dir,
                              account_db=ACCOUNT_DB, trend_db=TREND_DB,
                              books_root=None, catalog=None, target_book_id=None):
    from src.content_factory.account_novel_selection_v1 import discover_books
    from src.content_factory.account_novel_creation_v1 import prepare_account_novel_run
    profile, opportunity = load_current(account_db, trend_db, account_key, opportunity_id)
    context = _context(profile, opportunity, account_db, trend_db)
    run_dir = Path(run_dir).resolve()
    # Existing entry provenance is immutable; first preparation owns its directory.
    if (run_dir / CONTEXT_FILE).exists():
        _freeze_context(run_dir, context)
    if catalog is not None:
        catalog_path = Path(catalog).resolve()
        candidates = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        if not isinstance(candidates, list):
            raise ValueError("候选清单必须是JSON数组")
        # Catalog paths are relative to the catalog, never the worker's cwd.
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("候选清单每一项必须是JSON对象")
            for name in ("metadata_path", "material_path"):
                if candidate.get(name):
                    if not isinstance(candidate[name], str):
                        raise ValueError(f"候选{name}必须是文件路径字符串")
                    path = Path(candidate[name])
                    candidate[name] = str((catalog_path.parent / path).resolve())
    else:
        candidates = discover_books(Path(books_root or ROOT / "data/fanqie_promotion/books"))
    result = prepare_account_novel_run(profile, opportunity, candidates, run_dir,
                                      target_book_id=target_book_id)
    _freeze_context(run_dir, context)
    _bind_entry_context(run_dir)
    return result


def validate_current_context(run_dir):
    from src.content_factory.account_novel_selection_v1 import select_target_novel
    from src.content_factory.creative_workflow_inputs import verify_binding
    run_dir = Path(run_dir).resolve()
    binding = json.loads((run_dir / "BINDING.json").read_text(encoding="utf-8"))
    context_binding = binding.get("files", {}).get("entry_context")
    if not context_binding or context_binding.get("path") != str(run_dir / CONTEXT_FILE):
        raise ValueError("入口数据库来源尚未冻结，不能执行")
    verify_binding(context_binding)
    context = json.loads((run_dir / CONTEXT_FILE).read_text(encoding="utf-8"))
    if context.get("schema") != "account_novel_entry_context/v1":
        raise ValueError("缺少有效账号机会数据库绑定")
    profile, opportunity = load_current(context["account_db"], context["trend_db"],
                                       context["account_key"], context["opportunity_id"])
    if _context(profile, opportunity, context["account_db"], context["trend_db"]) != context:
        raise ValueError("当前账号策略或机会来源已变化，停止派发")
    selection = json.loads((run_dir / "SELECTION.json").read_text(encoding="utf-8"))
    if selection.get("account") != asdict(profile):
        raise ValueError("冻结账号快照与数据库绑定不一致")
    frozen_opportunity = dict(selection.get("opportunity") or {})
    frozen_opportunity.pop("status", None)
    if frozen_opportunity != _opportunity_source(opportunity):
        raise ValueError("冻结机会快照与数据库绑定不一致")
    # Run the shared domain/identity/freshness/status gate even for resume.
    select_target_novel(profile, opportunity, [])
    return profile, opportunity


def execute_from_repositories(run_dir, *, runner=None):
    from src.content_factory.account_novel_creation_v1 import execute_account_novel_run
    validate_current_context(run_dir)
    return execute_account_novel_run(
        Path(run_dir), runner=runner, validator=lambda: validate_current_context(run_dir))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="本地选书、冻结来源与准备简报，不调用模型")
    prepare.add_argument("--account-key", required=True)
    prepare.add_argument("--opportunity-id", required=True)
    prepare.add_argument("--books-root", type=Path, default=ROOT / "data/fanqie_promotion/books")
    prepare.add_argument("--catalog", type=Path)
    prepare.add_argument("--target-book-id")
    prepare.add_argument("--account-db", type=Path, default=ACCOUNT_DB)
    prepare.add_argument("--trend-db", type=Path, default=TREND_DB)
    prepare.add_argument("--run-dir", type=Path, required=True)
    for name in ("preview", "inspect", "execute"):
        command = commands.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            kwargs = vars(args).copy()
            kwargs.pop("command")
            result = prepare_from_repositories(**kwargs)
        elif args.command == "execute":
            result = execute_from_repositories(args.run_dir)
        else:
            from src.content_factory.account_novel_creation_v1 import (
                preview_account_novel_run, inspect_account_novel_run)
            function = preview_account_novel_run if args.command == "preview" else inspect_account_novel_run
            result = function(args.run_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.command in {"inspect", "preview"}:
            return 0
        successful = {"prepared"} if args.command == "prepare" else {
            "machine_text_complete", "awaiting_text_review", "text_ready_for_director", "completed"}
        return 0 if result.get("status") in successful else 2
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc),
                          "automatic_media_submit": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
