"""Explicit Fanqie acquisition bridge; no promotion, media or credential copying."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def _chapters(rows, *, parent: Path, confined_to: Path | None = None) -> list[dict]:
    result = []
    for row in rows:
        if not isinstance(row, dict) or not (row.get("file") or row.get("path")):
            raise ValueError("章节缺少实际文件路径")
        path = Path(row.get("file") or row["path"])
        if path.is_absolute():
            path = path.resolve()
        elif path.parts and path.parts[0].casefold() == "data":
            path = (ROOT / path).resolve()
            if not path.is_relative_to((ROOT / "data").resolve()):
                raise ValueError("原生项目相对章节路径越出 data 目录")
        else:
            path = (parent / path).resolve()
        if confined_to is not None and not path.is_relative_to(confined_to):
            raise ValueError("采集服务返回了工作区之外的章节")
        raw = path.read_bytes()
        body = raw.decode("utf-8-sig").strip()
        title = str(row.get("title", "")).strip()
        if title and body.splitlines() and body.splitlines()[0].strip() == title:
            body = "\n".join(body.splitlines()[1:]).strip()
        if not body or row.get("char_count") == 0:
            raise ValueError("章节正文为空")
        if str(path) in {item["path"] for item in result}:
            raise ValueError("章节文件重复")
        result.append({**row, "path": str(path), "file": str(path),
                       "sha256": hashlib.sha256(raw).hexdigest()})
    if not result:
        raise ValueError("没有可用的实际章节正文")
    return result


def _saved(source: dict, rows: list[dict], requested: int | None) -> dict:
    return {"schema": "novel_adaptation_acquisition/v1", "status": "source_saved",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {**source, "chapters": rows},
            "scope": {"requested_chapters": requested, "acquired_chapters": len(rows),
                      "chapter_titles": [r.get("title", Path(r["path"]).stem) for r in rows],
                      "scope_note": "仅已保存章节；不能据此声称取得或分析整本小说"},
            "automatic_media_submit": False}


def fetch_source(output_dir, *, book_name: str, chapters: int = 1, book_id: str = "",
                 service_factory=None) -> dict:
    """One explicit acquisition attempt in a new directory, with immutable receipt."""
    if not book_name.strip() or type(chapters) is not int or not 1 <= chapters <= 100:
        raise ValueError("请填写书名，采集章节数须为 1–100 的整数")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    _write(output / "REQUEST.json", {"book_name": book_name.strip(), "book_id": book_id,
           "chapters": chapters, "headless": False, "automatic_media_submit": False})
    try:
        if service_factory is None:
            from src.platform_adapter.fanqie_promotion import FanqiePromotionService
            service_factory = FanqiePromotionService
        service = service_factory(root_dir=output / "source_cache")
        result = service.fetch_book(book_name.strip(), chapters=chapters, headless=False,
                                    book_id=book_id)
        value = asdict(result) if is_dataclass(result) else dict(result)
        rows = _chapters(value.get("chapters", []), parent=Path.cwd(), confined_to=output)
        receipt = _saved(value, rows, chapters)
    except Exception as exc:
        receipt = {"schema": "novel_adaptation_acquisition/v1", "status": "acquisition_failed",
                   "error": f"{type(exc).__name__}: {exc}",
                   "next_action": "处理登录、验证或采集错误后，由用户明确发起新的采集；本次不自动重试",
                   "automatic_retry": False, "automatic_media_submit": False}
    _write(output / "RECEIPT.json", receipt)
    return {**receipt, "receipt_path": str(output / "RECEIPT.json")}


def import_saved_book(metadata_path, output_dir) -> dict:
    """Reference existing native chapter files without altering their metadata."""
    metadata = Path(metadata_path).resolve()
    metadata_raw = metadata.read_bytes()
    value = json.loads(metadata_raw.decode("utf-8-sig"))
    chapter_dir = metadata.parent / "chapters"
    rows = value.get("fetch_log") or [{"path": str(p), "title": p.stem}
                                      for p in sorted(chapter_dir.glob("*.txt"))]
    chapters = _chapters(rows, parent=metadata.parent)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = _saved({"book_name": value.get("book_name", metadata.parent.name),
                      "book_id": str(value.get("book_id", "")),
                      "metadata_path": str(metadata),
                      "metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
                      "chapters_dir": str(chapter_dir)}, chapters, None)
    receipt["method"] = "existing_native_chapter_files"
    _write(output / "RECEIPT.json", receipt)
    return {**receipt, "receipt_path": str(output / "RECEIPT.json")}


def discover_sources(roots) -> list[dict]:
    """Read-only inventory, including failed receipts as visible evidence."""
    results, seen = [], set()
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            continue
        paths = list(root.rglob("meta.json")) + list(root.rglob("RECEIPT.json"))
        paths += list(root.rglob("ACQUISITION_RESULT*.json"))
        for path in sorted(paths):
            if path in seen:
                continue
            seen.add(path)
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                if path.name == "meta.json":
                    if not list((path.parent / "chapters").glob("*.txt")):
                        continue
                    source, kind, status = value, "metadata", "saved_chapter_files"
                else:
                    source, kind, status = value.get("source", {}), "receipt", value.get("status", "unknown")
                results.append({"path": str(path), "kind": kind, "status": status,
                                "title": source.get("book_name", path.parent.name),
                                "book_id": str(source.get("book_id", ""))})
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return results
