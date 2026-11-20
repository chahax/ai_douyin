"""Central, privacy-conscious local ledger for paid model API calls.

The generation workflows keep detailed immutable receipts beside their media.
This ledger adds one searchable index across those receipts and records new
Seedance/Seedream calls at the client boundary.  It deliberately stores hashes
and small request/response summaries, never API keys, prompts, data URLs, or
signed output URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "data" / "provider_calls.sqlite3"
LEDGER_SCHEMA = "provider_call_ledger/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_json(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def summarize_request(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return useful request facts without persisting prompt/reference content."""
    source = payload if isinstance(payload, dict) else {}
    body = source.get("body") if isinstance(source.get("body"), dict) else source
    content = body.get("content") if isinstance(body.get("content"), list) else []
    texts: list[str] = []
    content_types: list[str] = []
    reference_roles: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type:
            content_types.append(item_type)
        role = str(item.get("role") or "")
        if role:
            reference_roles.append(role)
        if item_type == "text" and isinstance(item.get("text"), str):
            texts.append(item["text"])
    if isinstance(body.get("prompt"), str):
        texts.append(body["prompt"])
    prompt = "\n".join(texts)
    result: dict[str, Any] = {}
    for key in (
        "model", "duration", "resolution", "ratio", "size", "generate_audio",
        "watermark", "return_last_frame", "seed", "task_type", "output_format",
    ):
        if key in body and isinstance(body[key], (str, int, float, bool)):
            result[key] = body[key]
    result.update({
        "content_types": content_types,
        "reference_roles": reference_roles,
        "reference_count": sum(1 for value in content_types if value != "text"),
        "prompt_characters": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else "",
        "has_callback": bool(body.get("callback_url")),
    })
    return result


def summarize_response(response: dict[str, Any] | None) -> dict[str, Any]:
    """Strip provider responses down to non-secret accounting metadata."""
    source = response if isinstance(response, dict) else {}
    result: dict[str, Any] = {}
    for key in (
        "id", "status", "model", "duration", "resolution", "ratio",
        "generate_audio", "created_at", "updated_at", "seed", "credit_count",
    ):
        value = source.get(key)
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
    usage = source.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {
            str(key): value
            for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    return result


class ProviderCallLedger:
    """Small SQLite ledger with idempotent task/receipt upserts."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = os.getenv("PROVIDER_CALL_LEDGER_PATH", "").strip()
        self.path = Path(path or configured or DEFAULT_LEDGER_PATH).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_calls (
                    call_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL DEFAULT '',
                    request_metadata_json TEXT NOT NULL DEFAULT '{}',
                    response_metadata_json TEXT NOT NULL DEFAULT '{}',
                    source_path TEXT NOT NULL DEFAULT '',
                    http_status INTEGER,
                    error_type TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_task
                    ON provider_calls(provider, task_id) WHERE task_id <> '';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_source
                    ON provider_calls(provider, source_path) WHERE source_path <> '';
                CREATE INDEX IF NOT EXISTS ix_provider_calls_updated
                    ON provider_calls(updated_at DESC);
                CREATE INDEX IF NOT EXISTS ix_provider_calls_status
                    ON provider_calls(provider, operation, status);
                """
            )

    def begin_call(
        self,
        *,
        provider: str,
        operation: str,
        model: str,
        request: dict[str, Any],
        source_path: str | Path | None = None,
        created_at: str | None = None,
    ) -> str:
        call_id = uuid.uuid4().hex
        source = str(Path(source_path).resolve()) if source_path else ""
        timestamp = created_at or _now()
        metadata = summarize_request(request)
        with self._connect() as connection:
            if source:
                existing = connection.execute(
                    "SELECT call_id FROM provider_calls WHERE provider=? AND source_path=?",
                    (provider, source),
                ).fetchone()
                if existing:
                    call_id = str(existing["call_id"])
            connection.execute(
                """
                INSERT INTO provider_calls (
                    call_id, provider, operation, model, status, request_sha256,
                    request_metadata_json, source_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'submitting', ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    operation=excluded.operation,
                    model=excluded.model,
                    status='submitting',
                    request_sha256=excluded.request_sha256,
                    request_metadata_json=excluded.request_metadata_json,
                    source_path=excluded.source_path,
                    updated_at=excluded.updated_at
                """,
                (
                    call_id, provider, operation, model, _sha_json(request),
                    _json(metadata), source, timestamp, timestamp,
                ),
            )
        return call_id

    def mark_submitted(
        self,
        call_id: str,
        *,
        task_id: str = "",
        status: str = "submitted",
        response: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE provider_calls
                SET task_id=?, status=?, response_metadata_json=?, http_status=?,
                    error_type='', error_code='', error_message='', updated_at=?
                WHERE call_id=?
                """,
                (
                    task_id, status, _json(summarize_response(response)),
                    http_status, _now(), call_id,
                ),
            )

    def update_task(
        self,
        *,
        provider: str,
        task_id: str,
        status: str,
        response: dict[str, Any] | None = None,
    ) -> None:
        if not task_id:
            return
        with self._connect() as connection:
            row = connection.execute(
                "SELECT call_id FROM provider_calls WHERE provider=? AND task_id=?",
                (provider, task_id),
            ).fetchone()
            if row:
                connection.execute(
                    """
                    UPDATE provider_calls
                    SET status=?, response_metadata_json=?, updated_at=?
                    WHERE call_id=?
                    """,
                    (status, _json(summarize_response(response)), _now(), row["call_id"]),
                )
            else:
                timestamp = _now()
                connection.execute(
                    """
                    INSERT INTO provider_calls (
                        call_id, provider, operation, task_id, status,
                        response_metadata_json, created_at, updated_at
                    ) VALUES (?, ?, 'video_generation', ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex, provider, task_id, status,
                        _json(summarize_response(response)), timestamp, timestamp,
                    ),
                )

    def mark_failed(
        self,
        call_id: str,
        exc: BaseException,
        *,
        status: str = "submit_outcome_unknown",
        http_status: int | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE provider_calls
                SET status=?, http_status=?, error_type=?, error_code=?,
                    error_message=?, updated_at=?
                WHERE call_id=?
                """,
                (
                    status,
                    http_status,
                    type(exc).__name__,
                    str(error_code or ""),
                    str(exc)[:1000],
                    _now(),
                    call_id,
                ),
            )

    def upsert_receipt(self, path: str | Path, receipt: dict[str, Any]) -> bool:
        record = _record_from_receipt(Path(path), receipt)
        if record is None:
            return False
        source = str(Path(path).resolve())
        with self._connect() as connection:
            existing = None
            if record["task_id"]:
                existing = connection.execute(
                    "SELECT call_id FROM provider_calls WHERE provider=? AND task_id=?",
                    (record["provider"], record["task_id"]),
                ).fetchone()
            if not existing:
                existing = connection.execute(
                    "SELECT call_id FROM provider_calls WHERE provider=? AND source_path=?",
                    (record["provider"], source),
                ).fetchone()
            call_id = str(existing["call_id"]) if existing else uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO provider_calls (
                    call_id, provider, operation, model, task_id, status,
                    request_sha256, request_metadata_json, response_metadata_json,
                    source_path, http_status, error_type, error_code, error_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_id) DO UPDATE SET
                    operation=excluded.operation,
                    model=excluded.model,
                    task_id=excluded.task_id,
                    status=excluded.status,
                    request_sha256=excluded.request_sha256,
                    request_metadata_json=excluded.request_metadata_json,
                    response_metadata_json=excluded.response_metadata_json,
                    source_path=excluded.source_path,
                    http_status=excluded.http_status,
                    error_type=excluded.error_type,
                    error_code=excluded.error_code,
                    error_message=excluded.error_message,
                    updated_at=excluded.updated_at
                """,
                (
                    call_id, record["provider"], record["operation"], record["model"],
                    record["task_id"], record["status"], record["request_sha256"],
                    _json(record["request_metadata"]), _json(record["response_metadata"]),
                    source, record["http_status"], record["error_type"],
                    record["error_code"], record["error_message"],
                    record["created_at"], record["updated_at"],
                ),
            )
        return True

    def list_calls(
        self,
        *,
        provider: str | None = None,
        operation: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        for key, value in (("provider", provider), ("operation", operation), ("status", status)):
            if value:
                clauses.append(f"{key}=?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(int(limit), 5000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM provider_calls{where} ORDER BY updated_at DESC LIMIT ?",
                values,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["request_metadata"] = json.loads(item.pop("request_metadata_json"))
            item["response_metadata"] = json.loads(item.pop("response_metadata_json"))
            result.append(item)
        return result

    def summary(self) -> dict[str, Any]:
        rows = self.list_calls(limit=5000)
        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        total_tokens = 0
        for row in rows:
            key = (row["provider"], row["operation"], row["model"], row["status"])
            item = grouped.setdefault(key, {
                "provider": key[0], "operation": key[1], "model": key[2],
                "status": key[3], "count": 0, "tokens": 0,
            })
            item["count"] += 1
            usage = row["response_metadata"].get("usage", {})
            tokens = (
                _integer(usage.get("total_tokens"))
                or _integer(usage.get("completion_tokens"))
                or _integer(usage.get("output_tokens"))
                or 0
            )
            item["tokens"] += tokens
            total_tokens += tokens
        return {
            "schema": LEDGER_SCHEMA,
            "database": str(self.path),
            "generated_at": _now(),
            "total_calls": len(rows),
            "total_logged_tokens": total_tokens,
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "groups": sorted(
                grouped.values(),
                key=lambda item: (
                    item["provider"], item["operation"], item["model"], item["status"]
                ),
            ),
        }

    def export_json(self, path: str | Path) -> Path:
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema": LEDGER_SCHEMA,
            "generated_at": _now(),
            "summary": self.summary(),
            "calls": self.list_calls(limit=5000),
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination


def backfill_receipts(
    ledger: ProviderCallLedger,
    roots: Iterable[str | Path],
) -> dict[str, Any]:
    candidates: set[Path] = set()
    # Legacy Dreamina CLI receipts used names such as S01.json rather than a
    # receipt suffix.  Scan JSON comprehensively and let _record_from_receipt()
    # accept only actual Seedance/Seedream attempts.
    patterns = ("*.json",)
    for root_value in roots:
        root = Path(root_value).resolve()
        if not root.exists():
            continue
        for pattern in patterns:
            candidates.update(root.rglob(pattern))
    imported = skipped = 0
    errors: list[dict[str, str]] = []
    for path in sorted(candidates):
        try:
            if "review" in path.name.lower():
                skipped += 1
                continue
            receipt = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(receipt, dict) and ledger.upsert_receipt(path, receipt):
                imported += 1
            else:
                skipped += 1
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {
        "scanned": len(candidates),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def _record_from_receipt(path: Path, receipt: dict[str, Any]) -> dict[str, Any] | None:
    if receipt.get("mode") == "dry-run":
        return None
    schema = str(receipt.get("schema") or "")
    looks_like_receipt = (
        "receipt" in schema
        or "generation_report" in schema
        or "receipt" in path.name
        or path.name.endswith(".seedance.json")
        or (
            receipt.get("provider") == "dreamina_cli"
            and bool(receipt.get("submit_id"))
        )
    )
    if not looks_like_receipt:
        return None
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    if not request and path.name == "opening.ark_image.json":
        request_path = path.parent / "request.json"
        if request_path.is_file():
            raw = json.loads(request_path.read_text(encoding="utf-8-sig"))
            request = raw.get("body") if isinstance(raw, dict) and isinstance(raw.get("body"), dict) else raw
    if not request and isinstance(receipt.get("prompt"), str):
        request = {
            "model": receipt.get("model"),
            "duration": receipt.get("duration"),
            "resolution": receipt.get("resolution"),
            "ratio": receipt.get("ratio") or receipt.get("aspect"),
            "content": [{"type": "text", "text": receipt["prompt"]}],
        }
    final = receipt.get("final") if isinstance(receipt.get("final"), dict) else {}
    created = receipt.get("created") if isinstance(receipt.get("created"), dict) else {}
    request_body = request.get("body") if isinstance(request.get("body"), dict) else {}
    model = str(
        final.get("model")
        or request.get("model")
        or request_body.get("model")
        or ""
    )
    model = model or str(receipt.get("model") or "")
    if model.lower() == "seedance2.5":
        model = "dreamina-seedance-2-5-260628"
    lowered = model.lower()
    if "seedance" not in lowered and "seedream" not in lowered:
        return None
    task_id = str(
        final.get("id")
        or created.get("id")
        or receipt.get("task_id")
        or receipt.get("submit_id")
        or ""
    )
    api_calls = _integer(receipt.get("api_calls")) or 0
    status = str(final.get("status") or receipt.get("status") or "unknown")
    is_video = "seedance" in lowered
    is_image = "seedream" in lowered
    if is_image and api_calls <= 0:
        return None
    if is_video and not (
        task_id
        or api_calls > 0
        or status in {
            "rejected_pre_generation",
            "request_rejected",
            "submit_outcome_unknown",
        }
    ):
        return None
    provider = str(receipt.get("provider") or ("ark_api" if model.startswith("doubao-") else "byteplus_api"))
    operation = "video_generation" if is_video else "image_generation"
    response = (
        final
        or (
            receipt.get("latest_response")
            if isinstance(receipt.get("latest_response"), dict)
            else {}
        )
        or (
            receipt.get("failure_response")
            if isinstance(receipt.get("failure_response"), dict)
            else {}
        )
        or receipt
    )
    response_metadata = summarize_response(response)
    cost_credits = _integer(receipt.get("cost_credits"))
    if cost_credits is not None:
        response_metadata["cost_credits"] = cost_credits
    created_at = str(
        receipt.get("submitted_at")
        or receipt.get("caller_started_at")
        or receipt.get("created_at")
        or receipt.get("prepared_at")
        or _now()
    )
    updated_at = str(
        receipt.get("completed_at")
        or receipt.get("finished_at")
        or receipt.get("response_received_at")
        or final.get("updated_at")
        or created_at
    )
    return {
        "provider": provider,
        "operation": operation,
        "model": model,
        "task_id": task_id,
        "status": status,
        "request_sha256": str(receipt.get("request_sha256") or _sha_json(request)),
        "request_metadata": summarize_request(request),
        "response_metadata": response_metadata,
        "http_status": _integer(receipt.get("http_status")),
        "error_type": str(receipt.get("error_type") or ""),
        "error_code": str(receipt.get("error_code") or ""),
        "error_message": str(receipt.get("error") or receipt.get("error_message") or "")[:1000],
        "created_at": created_at,
        "updated_at": updated_at,
    }
