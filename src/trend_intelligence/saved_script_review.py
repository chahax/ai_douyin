"""Read-only verification of a saved pair before giving it a current review badge.

Failure never hides a historical script or starts a model call. This verifies the
saved text-review chain, not the sound or visual quality of a generated video.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEMANTIC_REJECTIONS_ROOT = PROJECT_ROOT / 'data/video_analysis/semantic_rejections'


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('保存记录含重复 JSON 字段')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _within(path, root):
    path = Path(path).resolve()
    if root not in path.parents:
        raise ValueError('保存工件路径超出本次输出目录')
    return path


def _read(path):
    return _json(path.read_text(encoding='utf-8'))


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def current_saved_script_review(items, *, allowed_root=None):
    """Return a fresh badge decision; do not trust an item's cached review status.

    UI callers use the project root. ``allowed_root`` is an explicit trusted
    caller boundary for isolated tests/tools, never a field taken from items.
    """
    from . import script_pair

    result = {'status': 'needs_review', 'current_passed': False,
              'reason': '缺少可核验的当前审核记录',
              'schema': script_pair.CURRENT_SCRIPT_REVIEW_SCHEMA,
              'scope': 'saved_script_text_and_evidence_binding; no_media_review'}
    try:
        return {**result, **_verify(items, (Path(allowed_root) if allowed_root else PROJECT_ROOT).resolve())}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as exc:
        # Report the check, never dump script/source contents into a UI error.
        reason = str(exc) if isinstance(exc, ValueError) else '保存工件缺失、不可读取或字段不完整'
        return {**result, 'reason': reason[:350]}


def require_current_saved_script_review(script_json_path, *, allowed_root=None):
    """Resolve a project's original script to its unique pair and require proof.

    A video job must separately compare its locked copy with this original. This
    function does not infer a pair from a copied script or certify custom scripts.
    """
    root = (Path(allowed_root) if allowed_root else PROJECT_ROOT).resolve()
    target = _within(script_json_path, root)
    _require(target.suffix == '.json', '当前审核恢复入口需要原始剧本 JSON 路径')
    matches = []
    for manifest_path in target.parent.glob('*.pair.json'):
        try:
            manifest_path = _within(manifest_path, root)
            manifest = _read(manifest_path)
            bound_paths = [_within(target.parent / manifest[kind]['script_json_path'], target.parent)
                           for kind in ('short', 'long')]
            if target in bound_paths:
                matches.append((manifest_path, manifest))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    _require(len(matches) == 1, '未找到唯一绑定原始剧本的双稿清单，需按当前协议复核')
    manifest_path, manifest = matches[0]
    items = []
    try:
        for kind in ('short', 'long'):
            paths = {key: _within(target.parent / manifest[kind][key], target.parent)
                     for key in ('script_path', 'script_json_path')}
            raw = paths['script_json_path'].read_text(encoding='utf-8')
            script = _json(raw)
            items.append({'kind': kind, 'duration': script['target_duration_seconds'], 'json': raw,
                          'markdown': paths['script_path'].read_text(encoding='utf-8'),
                          'manifest_path': str(manifest_path), **{key: str(path) for key, path in paths.items()}})
        result = current_saved_script_review(items, allowed_root=root)
        _require(result['current_passed'], f"项目双稿需要复核：{result['reason']}")
        return {**result, 'manifest_path': str(manifest_path), 'script_json_path': str(target),
                'script_json_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    except (OSError, TypeError, KeyError) as exc:
        raise ValueError('绑定双稿工件不可读取或字段不完整，需按当前协议复核') from exc


def _verify_review_attempt_chain(report, payload, prompt, trace, attempt, output_root):
    """Replay actual full responses and model quote patches; trust no merged flag."""
    from .script_pair import ScriptReviewRetryState, script_review_binding
    from .review_evidence_patch import TRACE_SCHEMA

    path = _within(trace / f'review_{attempt}_attempt_chain.json', output_root)
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == report.get('format_trace_sha256'),
             '审稿格式修复链文件缺失绑定或已变化')
    chain = _json(raw)
    _require(isinstance(chain, dict) and set(chain) == {
        'schema', 'candidate_sha256', 'evidence_sha256', 'prompt_sha256', 'attempts'}
        and chain['schema'] == TRACE_SCHEMA
        and all(chain.get(key) == value for key, value in script_review_binding(payload).items())
        and chain['prompt_sha256'] == hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        and isinstance(chain['attempts'], list) and len(chain['attempts']) == report['format_attempts'],
        '审稿格式修复链身份、规则或轮次不一致')
    retry = ScriptReviewRetryState(payload, prompt)
    for number, recorded in enumerate(chain['attempts'], 1):
        request_path = _within(trace / f'review_{attempt}_request_{number}.json', output_root)
        request_raw = request_path.read_bytes()
        messages = _json(request_raw)
        _require(_canonical(messages) == _canonical(retry.messages),
                 '审稿修复请求与实际父报告、允许引文路径或当前提示词不一致')
        response_path = _within(trace / f'review_{attempt}_response_{number}.txt', output_root)
        response_raw = response_path.read_bytes()
        _require(bool(response_raw), '审稿修复缺少真实模型响应')
        replayed, effective = retry.consume(response_raw.decode('utf-8'), number)
        replayed.update(request_sha256=hashlib.sha256(request_raw).hexdigest(),
                        response_sha256=hashlib.sha256(response_raw).hexdigest(), merged_report_sha256=None)
        if replayed['mode'] == 'evidence_patch' and effective is not None:
            merged_path = _within(trace / f'review_{attempt}_merged_{number}.json', output_root)
            merged_raw = merged_path.read_bytes()
            _require(_canonical(_json(merged_raw)) == _canonical(effective),
                     '已保存合并报告与原始父报告及模型引文补丁重放不一致')
            replayed['merged_report_sha256'] = hashlib.sha256(merged_raw).hexdigest()
        _require(_canonical(recorded) == _canonical(replayed),
                 '保存报告与真实模型响应不一致：审稿格式修复链、请求、父报告或合并SHA不一致')
        _require(replayed['valid'] is (number == len(chain['attempts'])),
                 '审稿修复必须在首次完整验证完成时结束，最终轮不能仍未通过格式验证')
    _require(retry.report is not None, '审稿格式修复链没有完整的严格验证结果')
    return retry.report


def _verify(items, allowed_root):
    from .pre_video_script import render_script_markdown
    from .script_pair import (CURRENT_SCRIPT_REVIEW_SCHEMA, SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS,
                              PROMPT_PATH, build_script_review_rows, parse_pair,
                              project_source_evidence, validate_saved_script_review_report,
                              validate_script_review_report)

    _require(isinstance(items, (list, tuple)) and len(items) == 2,
             '缺少完整双稿及保存记录，历史内容需按当前协议复核')
    _require([item['kind'] for item in items] == ['short', 'long'], '保存的双稿版本顺序或身份不一致')
    manifests = {item.get('manifest_path') for item in items}
    _require(len(manifests) == 1 and all(isinstance(p, str) and p for p in manifests),
             '缓存没有绑定保存清单，不能沿用当前通过状态')
    manifest_path = _within(next(iter(manifests)), allowed_root)
    _require(manifest_path.name.endswith('.pair.json'), '保存清单文件类型不匹配')
    manifest = _read(manifest_path)
    _require(manifest.get('schema') == 'pre_video_script_pair/v1', '历史清单需按当前协议复核')
    _require(manifest.get('video_generation_submitted') is False, '当前清单不再是停在视频生成前的双稿')
    agent_review = manifest.get('agent_review') or {}
    _require(isinstance(agent_review, dict), '人工/代理退回记录格式不可核验')
    _require(agent_review.get('status') not in {'needs_revision', 'failed', 'rejected', 'withdrawn', 'blocked'},
             '当前稿已被退回，旧模型审核不能继续作为通过依据')
    output_root = manifest_path.parent
    scripts = []
    for item in items:
        kind = item['kind']
        for key in ('script_path', 'script_json_path'):
            path = _within(output_root / manifest[kind][key], output_root)
            _require(item.get(key) == str(path), '缓存绑定的稿件路径与当前清单不一致')
            actual = path.read_text(encoding='utf-8')
            _require(actual == item['markdown' if key == 'script_path' else 'json'],
                     '保存稿或网页缓存已变化，需重新加载并复核')
        script = _json(item['json'])
        _require(script.get('schema') == 'detailed_video_script/v4', '历史稿不具备当前完整分镜字段，需复核')
        _require(script['account_uuid'] == manifest['account_uuid'] and script['format_kind'] == kind,
                 '保存稿账号或版本与清单不一致')
        _require(script['target_duration_seconds'] == item['duration'], '缓存显示时长与稿件不一致')
        scripts.append(script)
    generations = [script['generation'] for script in scripts]
    attempt = generations[0]['accepted_attempt']
    _require(type(attempt) is int and attempt > 0 and all(g['accepted_attempt'] == attempt for g in generations),
             '缺少一致的最终审核轮次')
    trace = _within(generations[0]['trace_dir'], output_root / '_runs')
    _require(all(Path(g['trace_dir']).resolve() == trace for g in generations), '两版稿未绑定同一审核运行')
    report_path = _within(trace / f'review_{attempt}.json', output_root)
    report = _read(report_path)
    for generation in generations:
        accepted = [row for row in generation['reviews'] if row.get('attempt') == attempt]
        _require(len(accepted) == 1 and accepted[0].get('report') == report,
                 '稿内审核与当前磁盘报告不一致，旧审核已失效')
    request_path = _within(trace / f'review_{attempt}_request_1.json', output_root)
    messages = _read(request_path)
    _require(isinstance(messages, list) and len(messages) == 2
             and [row.get('role') for row in messages] == ['system', 'user'], '原始审稿请求缺失或结构无效')
    prompt = PROMPT_PATH.with_name('script_pair_review.md').read_text(encoding='utf-8')
    _require(messages[0]['content'] == prompt
             and report.get('prompt_sha256') == hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
             '审核规则已更新，历史报告需按当前协议复核')
    payload = _json(messages[1]['content'])
    _require(payload.get('review_contract_schema') == CURRENT_SCRIPT_REVIEW_SCHEMA,
             '原始审稿请求未使用当前审核协议，需复核')
    _require(_canonical(build_script_review_rows(scripts)) == _canonical(payload['scripts']),
             '当前稿件与原始送审内容不一致，改稿后旧审核失效')
    full_sources = _read(_within(trace / 'source_evidence.full.json', output_root))
    _require(isinstance(full_sources, list) and len(full_sources) >= 20,
             '缺少原始完整来源批次，不能以聚焦来源替代采样门槛')
    ids = [source['source_id'] for source in full_sources]
    _require(len(set(ids)) == len(ids), '原始来源批次包含重复身份')
    full_hash = _digest(full_sources)
    for generation in generations:
        bound_hash = generation.get('full_source_evidence_sha256') or generation.get('script_reference_selection', {}).get('full_source_evidence_sha256')
        _require(bound_hash == full_hash, '完整来源证据已变化或缺少绑定，历史审核需复核')
    references = [ref for script in scripts for ref in script['generation']['reference_usage']]
    evidence = payload['evidence']
    selection = evidence.get('script_reference_selection')
    review_sources = full_sources
    if selection:
        requested = selection['requested_source_ids']
        actual = {ref['source_id'] for ref in references}
        _require(selection['full_source_evidence_sha256'] == full_hash
                 and len(set(requested)) == len(requested) and set(requested).issubset(ids)
                 and actual and actual.issubset(requested), '聚焦引用与完整来源身份或哈希不一致')
        review_sources = [source for source in full_sources if source['source_id'] in actual]
    _require(_canonical(project_source_evidence(review_sources, reference_usage=references))
             == _canonical(evidence['source_evidence']), '当前完整来源无法重建原送审证据，需重新复核')
    for source in full_sources:
        digest = source.get('media_evidence', {}).get('visual', {}).get('artifact_sha256')
        if isinstance(digest, str) and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
            _require(not (SEMANTIC_REJECTIONS_ROOT / f'{digest}.json').exists(),
                     '原始来源分析已有永久拒绝记录，旧剧本审核需复核')

    # Rebuild the delivered object, including fields not repeated in the review
    # prompt (derived camera/subtitle/video prompt and rendered Markdown).
    baseline = _within(trace / f'draft_{attempt}.json', output_root).read_text(encoding='utf-8')
    identity = SimpleNamespace(**{key: scripts[0][key] for key in ('account_uuid', 'domain_strategy_id', 'strategy_version')})
    rebuilt = parse_pair(baseline, profile=identity, created_at=scripts[0]['created_at'],
                         short_seconds=scripts[0]['target_duration_seconds'],
                         long_seconds=scripts[1]['target_duration_seconds'],
                         generation=copy.deepcopy(generations[0]), source_evidence=full_sources)
    from dataclasses import asdict
    for item, script, expected in zip(items, scripts, rebuilt):
        expected_dict = asdict(expected)
        _require(_canonical({k: v for k, v in script.items() if k != 'generation'})
                 == _canonical({k: v for k, v in expected_dict.items() if k != 'generation'}),
                 '保存稿或派生视频提示词与原始审核草稿不一致，需复核')
        _require(item['markdown'] == render_script_markdown(expected), '展示 Markdown 与当前送审剧本不一致，需复核')

    validated = validate_saved_script_review_report(report, payload)
    _require(validated['passed'] is True, '当前逐镜审核未通过，不能沿用历史通过状态')
    format_attempt = report.get('format_attempts')
    _require(type(format_attempt) is int and 1 <= format_attempt <= SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS,
             '缺少真实审稿响应轮次')
    if 'format_trace_sha256' in report:
        raw_validated = _verify_review_attempt_chain(report, payload, prompt, trace, attempt, output_root)
    else:
        _require(not _within(trace / f'review_{attempt}_attempt_chain.json', output_root).exists(),
                 '已存在审稿修复链但报告缺少绑定，不能降级为旧完整响应验证')
        # Historical current-v2 full-report traces remain readable. A patch
        # response cannot pass this branch as a complete raw review report.
        raw_report = _read(_within(trace / f'review_{attempt}_response_{format_attempt}.txt', output_root))
        raw_validated = validate_script_review_report(raw_report, payload)
    _require(all(report.get(key) == value for key, value in raw_validated.items()),
             '保存报告与真实模型响应不一致，需复核')
    return {'status': 'current_passed', 'current_passed': True, 'reason': '',
            'report_path': str(report_path), 'candidate_sha256': report['candidate_sha256'],
            'evidence_sha256': report['evidence_sha256'], 'full_source_evidence_sha256': full_hash,
            'legal_review_status': 'pending_human_review'}
