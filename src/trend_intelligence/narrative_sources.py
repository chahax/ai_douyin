"""Revalidate a frozen research cohort before the narrative-impact workflow.

Saved author requests omit local paths and collection identifiers. They are not
enough to establish the sample gate on their own: reopen the exact database
observations, analysis versions, local media and independently written reviews.
This module does not author a script, approve analysis claims, or submit media.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

from .media_evidence import batch_media_readiness
from .repository import TrendRepository
from .sample_gate import MIN_VIDEOS, primary_tag, require_sample
from .script_pair import _full_source_evidence, _source_json


def _payload(workflow_messages):
    if (not isinstance(workflow_messages, list) or len(workflow_messages) != 2
            or any(not isinstance(row, dict) for row in workflow_messages)
            or [row.get('role') for row in workflow_messages] != ['system', 'user']
            or not isinstance(workflow_messages[1].get('content'), str)):
        raise ValueError('source gate requires the original two-message workflow')
    payload = json.loads(workflow_messages[1]['content'])
    sources = payload.get('source_evidence') if isinstance(payload, dict) else None
    if (not isinstance(sources, list) or len(sources) < MIN_VIDEOS
            or any(not isinstance(source, dict) for source in sources)):
        raise ValueError('source gate requires at least 20 complete frozen sources')
    ids = [source.get('source_id') for source in sources]
    if (any(not isinstance(sid, str) or not sid.strip() for sid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('frozen source IDs must be nonempty and unique')
    for source in sources:
        if any(not isinstance(source.get(key), str) or not source[key].strip()
               for key in ('analysis_id', 'collected_at')):
            raise ValueError('frozen source requires exact analysis_id and collected_at')
        if (not isinstance(source.get('expression_analysis'), dict)
                or not isinstance(source.get('media_evidence'), dict)
                or not isinstance(source.get('independent_review'), dict)):
            raise ValueError('frozen source lacks complete media, expression or review evidence')
        if source.get('evidence_projection'):
            raise ValueError('restore full source evidence before narrative source verification')
    return sources


def _matching_observation(observation, source, analysis):
    # Do not replace a historic metric with a newer observation or infer its
    # meaning from a bare number. Timestamp identity also binds the cohort.
    return (observation.item_id == source['source_id']
            and observation.video_id == analysis.video_id
            and observation.collected_at == source['collected_at']
            and observation.metric_kind == source.get('metric_kind')
            and observation.metric_value == source.get('metric_value')
            and observation.published_at == source.get('published_at', ''))


def verify_workflow_sources(workflow_messages, *, repository=None):
    """Return JSON-serializable proof or raise before any author model call.

    ``workflow_messages`` must already contain the restored, hash-bound full
    source array. ``repository`` supports the project's list_content_analyses
    and list_observations methods and can be injected for isolated tests.
    Existing media verification may persist a previously observed rejection;
    it never upgrades an unreviewed artifact to passed.
    """
    sources = _payload(workflow_messages)
    repo = repository if repository is not None else TrendRepository()
    available = repo.list_content_analyses(limit=100_000)
    analyses = []
    for source in sources:
        matches = [analysis for analysis in available
                   if analysis.analysis_id == source['analysis_id']]
        if (len(matches) != 1 or matches[0].item_id != source['source_id']
                or not matches[0].video_id):
            raise ValueError(f"{source['source_id']}: exact frozen analysis version is unavailable")
        analysis = matches[0]
        if (analysis.expression_analysis != source['expression_analysis']
                or analysis.media_access_mode != source.get('media_access_mode')):
            raise ValueError(f"{source['source_id']}: frozen analysis content differs from database")
        analyses.append(analysis)
    accounts = {analysis.account_uuid for analysis in analyses}
    if len(accounts) != 1 or '' in accounts:
        raise ValueError('frozen source analyses must belong to one explicit account')
    account_uuid = next(iter(accounts))
    observations = repo.list_observations(account_uuid=account_uuid, limit=100_000)
    matches_by_source = []
    for source, analysis in zip(sources, analyses):
        matches = [row for row in observations if _matching_observation(row, source, analysis)]
        if not matches:
            raise ValueError(f"{source['source_id']}: original metric/time observation is unavailable or changed")
        matches_by_source.append(matches)
    common_runs = set.intersection(*({row.run_id for row in matches} for matches in matches_by_source))
    if len(common_runs) != 1 or '' in common_runs:
        raise ValueError('frozen sources do not resolve to one unambiguous common collection batch')
    run_id = next(iter(common_runs))
    batch_rows = [row for matches in matches_by_source for row in matches if row.run_id == run_id]
    sample = require_sample(batch_rows)
    if sample.unique_videos != len(sources):
        raise ValueError('different frozen source IDs cannot reuse one video')
    media_gate = batch_media_readiness(analyses, required_count=MIN_VIDEOS,
        expected_item_ids=[source['source_id'] for source in sources], verify_artifacts=True)
    if not media_gate['ready']:
        raise ValueError('current frozen-source media gate failed: '
                         + json.dumps(media_gate, ensure_ascii=False))
    cohort = [SimpleNamespace(observation=next(row for row in matches if row.run_id == run_id),
                              analysis=analysis)
              for matches, analysis in zip(matches_by_source, analyses)]
    live = _full_source_evidence(cohort)
    bindings = []
    for source, current, analysis in zip(sources, live, analyses):
        review = current['independent_review']
        frozen_review = source['independent_review']
        if (review.get('decision') not in ('passed', 'passed_with_limits')
                or frozen_review.get('blocked_for_script_generation') is True
                or review.get('blocked_for_script_generation') is True
                or any(review.get(key) != frozen_review.get(key) for key in
                       ('decision', 'review_sha256', 'artifact_sha256', 'source_video_sha256'))
                or not review.get('review_sha256')):
            raise ValueError(f"{source['source_id']}: independent review is stale, rejected or unavailable")
        if (current['media_evidence'] != source['media_evidence']
                or current['expression_analysis'] != source['expression_analysis']):
            raise ValueError(f"{source['source_id']}: current media/evidence differs from the frozen request")
        tags = sorted({primary_tag(row) for row in batch_rows if row.item_id == source['source_id']
                       and primary_tag(row)})
        bindings.append({'source_id': source['source_id'], 'analysis_id': analysis.analysis_id,
            'video_id': analysis.video_id, 'run_id': run_id, 'primary_tag': tags[0] if tags else '',
            'collected_at': source['collected_at'], 'published_at': source.get('published_at', ''),
            'metric_kind': source.get('metric_kind'), 'metric_value': source.get('metric_value'),
            'source_video_sha256': review['source_video_sha256'],
            'visual_artifact_sha256': review['artifact_sha256'], 'review_sha256': review['review_sha256'],
            'review_decision': review['decision']})
    return {'schema': 'narrative_source_gate/v1', 'status': 'verified',
        'checked_at_bjt': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'source_count': len(sources), 'account_uuid': account_uuid, 'collection_run_id': run_id,
        'source_evidence_sha256': hashlib.sha256(_source_json(sources).encode('utf-8')).hexdigest(),
        'sample_gate': sample.to_dict(), 'media_gate': media_gate, 'source_bindings': bindings,
        'scope': 'Exact historic observations and analyses, current file hashes and bound independent reviews; '
                 'this does not establish acoustic emotion, causality, or full-video human review.',
        'model_calls': 0, 'media_generation': False, 'automatic_editorial_approval': False}
