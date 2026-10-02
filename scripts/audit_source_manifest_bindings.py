"""Read-only manifest/media/review/database audit; writes only the requested report."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def beijing(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('recorded timestamp has no timezone')
    return stamp.astimezone(timezone(timedelta(hours=8))).isoformat()


def audit(manifest_path, db_path, pending_ids):
    started = datetime.now(timezone.utc)
    manifest_path, db_path = manifest_path.resolve(), db_path.resolve()
    manifest_hash = sha(manifest_path)
    manifest = read(manifest_path)
    errors, items = [], []
    connection = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    connection.execute('BEGIN')
    run_row = connection.execute('SELECT * FROM trend_collection_runs WHERE run_id=?',
                                 (manifest['collection_run_id'],)).fetchone()
    run = dict(run_row) if run_row else {}
    if run.get('account_uuid') != manifest['account_uuid'] or run.get('status') != 'completed':
        errors.append('Collection run account/status binding mismatch')
    confirmations = [dict(row) for row in connection.execute(
        'SELECT * FROM trend_metric_confirmations WHERE run_id=? AND account_uuid=?',
        (manifest['collection_run_id'], manifest['account_uuid']))]
    confirmed = {}
    for record in confirmations:
        if record['metric_kind'] == 'likes_user_confirmed':
            for observation in json.loads(record['observations_json']):
                confirmed[observation['id']] = observation
    for ordinal, item in enumerate(manifest['items'], 1):
        row = {'ordinal': ordinal, 'item_id': item['item_id'], 'video_id': item['video_id'],
               'checks': {}, 'errors': []}
        checks = row['checks']
        try:
            video, receipt_path, qwen_path = (Path(item[key]).resolve()
                                               for key in ('video', 'acquisition_receipt', 'qwen'))
            source_hash, receipt_hash, qwen_hash = sha(video), sha(receipt_path), sha(qwen_path)
            receipt, qwen = read(receipt_path), read(qwen_path)
            row['source'] = {'path': str(video), 'sha256': source_hash, 'bytes': video.stat().st_size}
            row['receipt'] = {'path': str(receipt_path), 'sha256': receipt_hash,
                              'download_completed_at_beijing': beijing(receipt['download_completed_at'])}
            checks['item_video_identity'] = item['item_id'] == 'douyin:' + item['video_id']
            checks['source_sha_matches_manifest'] = source_hash == item['source_video_sha256']
            checks['receipt_sha_matches_manifest'] = receipt_hash == item['acquisition_receipt_sha256']
            checks['receipt_identity'] = all(receipt.get(key) == expected for key, expected in {
                'schema': 'source_media_receipt/v1', 'account_uuid': manifest['account_uuid'],
                'collection_run_id': manifest['collection_run_id'], 'item_id': item['item_id'],
                'video_id': item['video_id'], 'source_page_url': item['source_url'],
                'source_video_sha256': source_hash, 'identity_confirmed': True}.items())
            checks['receipt_local_video'] = Path(receipt['video']).resolve() == video
            observed = receipt.get('observed_source', {})
            checks['receipt_observed_owner'] = (observed.get('owner_id') == item['video_id']
                and observed.get('detail_response_subset', {}).get('aweme_id') == item['video_id'])
            checks['receipt_download_bytes_sha'] = (receipt['download']['sha256'] == source_hash
                and receipt['download']['size'] == video.stat().st_size)
            checks['qwen_source_identity'] = (qwen.get('schema') == 'local_qwen_frame_analysis/v2'
                and qwen.get('source_video_sha256') == source_hash)
            frame_path, transcript_path = Path(qwen['frame_manifest_path']).resolve(), Path(item['transcript']).resolve()
            checks['frame_manifest_sha'] = sha(frame_path) == qwen['frame_manifest_sha256']
            checks['frame_manifest_source_sha'] = read(frame_path).get('source_video_sha256') == source_hash
            checks['transcript_sha'] = sha(transcript_path) == qwen['transcript_sha256']
            row['qwen'] = {'path': str(qwen_path), 'sha256': qwen_hash,
                            'created_at_beijing': beijing(qwen['created_at']),
                            'frame_manifest_path': str(frame_path), 'transcript_path': str(transcript_path)}
            review_path = qwen_path.with_name('semantic_review.json')
            review = read(review_path) if review_path.is_file() else {}
            bound = (review.get('schema') == 'source_expression_semantic_review/v1'
                and review.get('artifact_sha256') == qwen_hash
                and Path(review.get('artifact_path') or '.').resolve() == qwen_path
                and review.get('source_video_sha256') == source_hash
                and review.get('source_video_id') == item['video_id'])
            marker_path = ROOT / 'data/video_analysis/semantic_rejections' / (qwen_hash + '.json')
            marker = read(marker_path) if marker_path.exists() else None
            row['review'] = {'path': str(review_path), 'sha256': sha(review_path) if review else None,
                'binding_matches': bound, 'decision': review.get('decision'),
                'blocked_for_script_generation': review.get('blocked_for_script_generation'),
                'reviewed_at_beijing': beijing(review['reviewed_at']) if review.get('reviewed_at') else None}
            row['permanent_rejection'] = {'exists': marker is not None,
                'path': str(marker_path) if marker is not None else None,
                'sha256': sha(marker_path) if marker is not None else None,
                'marker_binding_valid': (marker.get('artifact_sha256') == qwen_hash and marker.get('decision') == 'failed') if marker else None}
            accepted = bound and review.get('decision') in {'passed', 'passed_with_limits'} and review.get('blocked_for_script_generation') is False and marker is None
            if item['video_id'] in pending_ids and not accepted:
                row['semantic_state'] = 'pending_final_candidate_binding'
                row['pending_notice'] = 'Current manifest still references the prior candidate; its recorded rejection is retained. No approval transferred from a newer unbound candidate.'
            else:
                row['semantic_state'] = 'accepted_with_recorded_limits' if accepted else 'binding_or_review_error'
                checks['review_source_artifact_binding'] = bound
                checks['review_allows_script_use'] = accepted
            observations = [dict(r) for r in connection.execute(
                'SELECT id,run_id,item_id,keyword,metric_text,metric_value,metric_kind,collected_at FROM trend_observations WHERE run_id=? AND item_id=?',
                (manifest['collection_run_id'], item['item_id']))]
            metrics = {(r['metric_kind'], r['metric_value'], r['metric_text']) for r in observations}
            checks['same_run_observation_exists'] = bool(observations)
            checks['duplicate_observations_agree'] = len(metrics) == 1
            checks['user_confirmed_likes'] = bool(observations) and all(r['metric_kind'] == 'likes_user_confirmed'
                and r['id'] in confirmed and all(confirmed[r['id']].get(k) == r[k]
                    for k in ('item_id', 'metric_text', 'metric_value', 'collected_at')) for r in observations)
            row['metrics'] = {'observations': [{**r, 'collected_at_beijing': beijing(r['collected_at'])} for r in observations],
                'deduplicated_value': observations[0]['metric_value'] if len(metrics) == 1 else None,
                'deduplication_rule': 'Count each source item once; duplicate rows must agree exactly in metric kind/value/text.'}
            row['errors'].extend(key for key, value in checks.items() if value is False)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['errors'].append(type(exc).__name__ + ': ' + str(exc))
        items.append(row)
    connection.close()
    duplicate_fields = {}
    for key in ('item_id', 'video_id'):
        duplicate_fields[key] = [key for key, count in Counter(item[key] for item in manifest['items']).items() if count > 1]
    duplicate_fields['source_video_sha256'] = [key for key, count in Counter(item.get('source', {}).get('sha256') for item in items).items() if count > 1]
    if any(duplicate_fields.values()): errors.append('Duplicate source identity or source bytes in selected cohort')
    selection_equal = [(s['item_id'], s['video_id']) for s in manifest['selection']] == [(s['item_id'], s['video_id']) for s in manifest['items']]
    if not selection_equal: errors.append('Selection differs from active item list')
    stable = sha(manifest_path) == manifest_hash
    if not stable: errors.append('Manifest changed during audit; rerun required')
    errors.extend({'ordinal': row['ordinal'], 'errors': row['errors']} for row in items if row['errors'])
    total = sum(row.get('metrics', {}).get('deduplicated_value') or 0 for row in items)
    times = sorted(r['collected_at'] for row in items for r in row.get('metrics', {}).get('observations', []))
    return {'schema': 'final_manifest_binding_audit/v1', 'audit_started_at': started.isoformat(),
        'audit_completed_at': datetime.now(timezone.utc).isoformat(), 'display_timezone': 'Asia/Shanghai (UTC+8)',
        'manifest': {'path': str(manifest_path), 'sha256': manifest_hash, 'unchanged_during_audit': stable},
        'database': {'path': str(db_path), 'access': 'SQLite mode=ro, query_only transaction snapshot'},
        'account_uuid': manifest['account_uuid'], 'collection_run_id': manifest['collection_run_id'],
        'collection_run': {key: run.get(key) for key in ('status', 'account_uuid', 'item_count', 'started_at', 'finished_at', 'keywords_json')},
        'selection_matches_active_items': selection_equal, 'source_count': len(items), 'duplicate_sources': duplicate_fields,
        'accepted_bound_count': sum(r.get('semantic_state') == 'accepted_with_recorded_limits' for r in items),
        'pending_final_binding_ids': [r['video_id'] for r in items if r.get('semantic_state') == 'pending_final_candidate_binding'],
        'deduplicated_likes_sum': total, 'minimum_20_sources_met': len(items) >= 20,
        'minimum_one_million_likes_met': total >= 1_000_000,
        'collection_window_beijing': [beijing(times[0]), beijing(times[-1])] if times else [],
        'metric_confirmations': [{key: c[key] for key in ('confirmation_id', 'metric_kind', 'confirmed_at', 'statement')} for c in confirmations],
        'status': 'binding_errors' if errors else 'pending_final_binding' if any(r.get('semantic_state') == 'pending_final_candidate_binding' for r in items) else 'all_bound_and_reviewed',
        'errors': errors, 'items': items,
        'scope': ['Bindings and recorded decisions only; no new semantic, acoustic or visual review.',
                  'No manifest, candidate, database, rejection registry or model settings changed.',
                  'No model calls, media uploads, script generation or video generation.',
                  'Completion times read from actual recorded timestamps; filesystem mtime is not used.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/trend_intelligence.db')
    parser.add_argument('--pending-video-id', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.manifest, args.database, set(args.pending_video_id))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        prior = read(args.output)
        suffix = datetime.fromisoformat(prior['audit_started_at']).strftime('%Y%m%dT%H%M%S%fZ')
        history = args.output.with_name(args.output.stem + '.' + suffix + '.json')
        if history.exists() and history.read_bytes() != args.output.read_bytes():
            raise ValueError('audit history collision')
        history.write_bytes(args.output.read_bytes())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'source_count', 'accepted_bound_count', 'pending_final_binding_ids', 'deduplicated_likes_sum', 'errors')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
