"""Read-only grouping of production attempts and assemblies by recorded identity."""
from datetime import datetime, timezone
import json
from pathlib import Path


def read_record(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def recorded_time(record: dict) -> datetime:
    for field in ('finished_at_bjt', 'completed_at', 'created_at', 'started_at_bjt'):
        try:
            stamp = datetime.fromisoformat(str(record.get(field, '')).replace('Z', '+00:00'))
            if stamp.tzinfo is not None:
                return stamp
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def project_key(record: dict, path: Path) -> str:
    series = record.get('campaign_series_id') or record.get('series_id')
    if series and record.get('campaign_path'):
        return str(record.get('account_uuid') or '') + '::' + str(record['campaign_path']) + '::' + str(series)
    return str(record.get('account_uuid') or record.get('account_key') or '') + '::' + str(record.get('script_sha256') or record.get('source_script') or path)


def task_review_context(task: dict, root: Path) -> dict:
    """Expose recorded evidence only, never infer quality from API status."""
    value = task.get('video_path')
    empty = dict(project='未关联项目', decision='pending', quality='未找到独立审核记录')
    if not value:
        return empty
    video = (root / value).resolve()
    if not video.is_relative_to((root / 'data').resolve()):
        return empty
    manifest = read_record(video.parent / 'production.json')
    review = read_record(video.with_suffix('.quality_review.json'))
    decision = review.get('decision', 'pending')
    label = {'passed': '记录通过', 'failed': '记录未通过',
             'passed_with_previously_accepted_limitations': '记录通过（含已接受局限）'}.get(decision, '待核对')
    return dict(project=manifest.get('title') or video.parent.name,
                series=manifest.get('campaign_series_id', ''), attempt=video.parent.name,
                decision=decision, quality=label if review else empty['quality'])


def list_projects(root: Path, account_uuid: str | None = None) -> list[dict]:
    base = root / 'data/video_generation'
    groups = {}
    for name, kind in (('production.json', 'attempts'), ('assembly.json', 'assemblies')):
        for path in sorted(base.rglob(name)):
            if not path.resolve().is_relative_to(base.resolve()):
                continue
            record = read_record(path)
            if not record or (kind == 'attempts' and not isinstance(record.get('shots'), list)):
                continue
            if kind == 'assemblies' and not record.get('video'):
                continue
            from src.services.artifact_account import artifact_account
            owner = artifact_account(record, root)
            if kind == 'assemblies' and not owner['account_uuid']:
                inputs = record.get('inputs') or []
                input_owners = [artifact_account({'production_manifest': str(Path(i['run_dir']) / 'production.json')}, root)
                                for i in inputs if isinstance(i, dict) and i.get('run_dir')]
                if input_owners and len(input_owners) == len(inputs) and len({o['account_uuid'] for o in input_owners}) == 1:
                    owner = input_owners[0]
            record.update(owner)
            if account_uuid is not None and owner['account_uuid'] != account_uuid:
                continue
            key = project_key(record, path)
            group = groups.setdefault(key, dict(key=key, title=record.get('title') or path.parent.name,
                                               account_uuid=owner['account_uuid'], account_key=owner.get('account_key', ''),
                                               attempts=[], assemblies=[], recorded_at=recorded_time(record)))
            group[kind].append(path)
            group['recorded_at'] = max(group['recorded_at'], recorded_time(record))
    for group in groups.values():
        for kind in ('attempts', 'assemblies'):
            group[kind].sort(key=lambda p: recorded_time(read_record(p)), reverse=True)
    return sorted(groups.values(), key=lambda g: g['recorded_at'], reverse=True)
