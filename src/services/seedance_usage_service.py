"""Local usage ledger for Seedance generation reports.

Seedance task responses expose per-task usage but do not expose the account's
remaining free quota through the generation bearer API.  This service therefore
keeps an explicitly labelled local budget/quota estimate from successful task
reports and never presents it as the provider's authoritative balance.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


REPORT_SCHEMA = "seedance_generation_report/v1"


def summarize_seedance_usage(
    report_dir: str | Path,
    *,
    provider: str | None = None,
    account_uuid: str | None = None,
    project_root: Path | None = None,
    monthly_budget_usd: float = 0.0,
    monthly_quota_seconds: float = 0.0,
    usd_per_second_480p: float = 0.2056,
    usd_per_second_720p: float = 0.4621,
) -> dict[str, Any]:
    """Summarize local Seedance reports for dashboard display."""

    if monthly_budget_usd < 0 or monthly_quota_seconds < 0:
        raise ValueError("budget and quota values must not be negative")
    if usd_per_second_480p < 0 or usd_per_second_720p < 0:
        raise ValueError("estimated prices must not be negative")

    directory = Path(report_dir).resolve()
    tasks: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    if directory.exists():
        for path in sorted(directory.glob("*.seedance.json")):
            try:
                report = json.loads(path.read_text(encoding="utf-8-sig"))
                if report.get("schema") != REPORT_SCHEMA:
                    continue
                task = _task_from_report(
                    path,
                    report,
                    usd_per_second_480p=usd_per_second_480p,
                    usd_per_second_720p=usd_per_second_720p,
                )
                from src.services.artifact_account import artifact_account, ROOT
                ownership_record = dict(report)
                if not ownership_record.get('production_manifest') and task.get('video_path'):
                    ownership_record['production_manifest'] = str(Path(task['video_path']).parent / 'production.json')
                task.update(artifact_account(ownership_record, project_root or ROOT))
                if provider is None or task["provider"] == provider:
                    tasks.append(task)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                parse_errors.append({"path": str(path), "error": str(exc)})

    tasks.sort(key=lambda item: item["updated_at"], reverse=True)
    # Mirrored receipts of the same provider task are one charge, not two.
    unique, seen_tasks = [], {}
    for item in tasks:
        identity = (item['provider'], item['task_id']) if item['task_id'] else ('report', item['report_path'])
        if identity not in seen_tasks:
            seen_tasks[identity] = item
            unique.append(item)
        else:
            previous = seen_tasks[identity]
            if (previous.get('account_conflict') or item.get('account_conflict') or
                    (previous.get('account_uuid') and item.get('account_uuid') and previous['account_uuid'] != item['account_uuid'])):
                previous.update(account_uuid='', account_key='', account_conflict=True)
    tasks = unique
    all_tasks = tasks
    if account_uuid is not None:
        tasks = [item for item in tasks if item['account_uuid'] == account_uuid]
    status_counts = Counter(str(item["status"]) for item in tasks)
    current_period = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m")
    successful = [item for item in tasks if item["status"] == "succeeded"]
    period_successful = [
        item for item in successful if str(item["updated_at"]).startswith(current_period)
    ]
    generated_seconds = round(
        sum(float(item["duration_seconds"]) for item in period_successful), 3
    )
    estimated_spend = round(
        sum(float(item["estimated_cost_usd"]) for item in period_successful if item['estimated_cost_usd'] is not None), 4
    )
    remaining_budget = (
        round(max(monthly_budget_usd - estimated_spend, 0.0), 4)
        if monthly_budget_usd > 0
        else None
    )
    remaining_seconds = (
        round(max(monthly_quota_seconds - generated_seconds, 0.0), 3)
        if monthly_quota_seconds > 0
        else None
    )

    return {
        "schema": "seedance_usage_summary/v1",
        "provider": provider,
        "report_dir": str(directory),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "defaults": {
            "ratio": "9:16",
            "resolution": "480p",
        },
        "tasks": tasks,
        "account_uuid": account_uuid,
        "account_totals": account_totals(all_tasks, current_period),
        "summary": {
            "report_count": len(tasks),
            "billing_period": current_period,
            "dry_run_count": status_counts.get("dry-run", 0),
            "submitted_count": status_counts.get("submitted", 0),
            "running_count": status_counts.get("queued", 0)
            + status_counts.get("running", 0),
            "succeeded_count": len(successful),
            "period_succeeded_count": len(period_successful),
            "failed_count": status_counts.get("failed", 0)
            + status_counts.get("cancelled", 0)
            + status_counts.get("expired", 0)
            + status_counts.get('request_rejected',0),
            "generated_seconds": generated_seconds,
            "estimated_spend_usd": None if provider=='ark_api' else estimated_spend,
            "monthly_budget_usd": monthly_budget_usd or None,
            "remaining_budget_usd": remaining_budget,
            "monthly_quota_seconds": monthly_quota_seconds or None,
            "remaining_quota_seconds": remaining_seconds,
            "completion_tokens": (sum(item['completion_tokens'] for item in period_successful if item['completion_tokens'] is not None)
                                  if any(item['completion_tokens'] is not None for item in period_successful) else None),
        },
        "platform_quota": {
            "authoritative_balance_available": False,
            "reason": (
                "The Seedance generation API does not return account-level remaining free quota. "
                "Verify the authoritative balance in the selected provider's billing console."
            ),
        },
        "parse_errors": parse_errors,
    }


def account_totals(tasks: list[dict], period: str) -> list[dict]:
    """Provider-local monthly comparison. Never allocate a shared cash balance."""
    groups = {}
    for task in tasks:
        if not str(task['updated_at']).startswith(period):
            continue
        owner = task.get('account_uuid', '')
        row = groups.setdefault(owner, dict(account_uuid=owner, account_key=task.get('account_key', ''),
                                            task_count=0, succeeded_count=0, generated_seconds=0.,
                                            completion_tokens=None, estimated_cost_usd=None))
        row['task_count'] += 1
        if task['status'] == 'succeeded':
            row['succeeded_count'] += 1
            row['generated_seconds'] += task['duration_seconds']
            if task['completion_tokens'] is not None:
                row['completion_tokens'] = (row['completion_tokens'] or 0) + task['completion_tokens']
            if task['estimated_cost_usd'] is not None:
                row['estimated_cost_usd'] = (row['estimated_cost_usd'] or 0.) + task['estimated_cost_usd']
    return list(groups.values())


def _task_from_report(
    path: Path,
    report: dict[str, Any],
    *,
    usd_per_second_480p: float,
    usd_per_second_720p: float,
) -> dict[str, Any]:
    request = report.get("request") if isinstance(report.get("request"), dict) else {}
    created = report.get("created") if isinstance(report.get("created"), dict) else {}
    final = report.get("final") if isinstance(report.get("final"), dict) else {}

    if final:
        status = str(final.get("status") or "unknown")
    elif created:
        status = "submitted"
    else:
        status = str(report.get('status') or ('submit_outcome_unknown' if report.get('mode')=='submit' else 'dry-run'))

    resolution = str(final.get("resolution") or request.get("resolution") or "480p")
    duration_value = final.get("duration", request.get("duration", 0))
    try:
        duration = max(float(duration_value), 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    rate = (
        usd_per_second_720p if resolution.lower() == "720p" else usd_per_second_480p
    )
    provider=str(report.get('provider') or 'byteplus_api')
    estimated_cost = (None if provider=='ark_api' else
                      round(duration * rate, 4) if status == "succeeded" else 0.0)

    content = request.get("content") if isinstance(request.get("content"), list) else []
    has_video_reference = any(
        isinstance(item, dict) and item.get("type") == "video_url" for item in content
    )
    usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
    updated_epoch = final.get("updated_at") or final.get("created_at") or report.get('updated_at') or report.get('created_at')
    updated_at = _timestamp_text(updated_epoch)

    return {
        "provider": provider,
        "segment_id": str(report.get("segment_id") or path.stem),
        "task_id": str(final.get("id") or created.get("id") or ""),
        "status": status,
        "model": str(final.get("model") or request.get("model") or ""),
        "resolution": resolution,
        "ratio": str(final.get("ratio") or request.get("ratio") or ""),
        "duration_seconds": round(duration, 3),
        "generate_audio": bool(
            final.get("generate_audio", request.get("generate_audio", False))
        ),
        "completion_tokens": int(usage['completion_tokens']) if usage.get('completion_tokens') is not None else None,
        "estimated_cost_usd": estimated_cost,
        "estimate_note": (
            "output-only estimate; reference-video duration is not included"
            if has_video_reference
            else "output-only estimate based on configured rate"
        ),
        "updated_at": updated_at,
        "video_path": str(report.get("video_path") or ""),
        "report_path": str(path),
    }


def _timestamp_text(value: Any) -> str:
    if value is None:
        return '未记录'
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        try:
            moment=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if moment.tzinfo is None:return '未记录'
            return moment.astimezone(timezone(timedelta(hours=8))).isoformat()
        except ValueError:
            return '未记录'
    return datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=8))).isoformat()
