"""Durable natural direction -> faithful extraction -> exact-request review.

Old v9 native proofs are read only. Extra campaign rounds never reset spending.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path

from . import novel_agent_pipeline_v9 as parent
from . import natural_director_contracts_v10 as contracts
from . import natural_director_role_clients_v10 as client_module

CreativeRoleClients = client_module.NaturalDirectorRoleClients

core = parent.core
VERSION = 'natural_director_pipeline/v10'
CANONICAL_REGISTRY = parent.CANONICAL_REGISTRY
STAGES = ('natural_director', 'extract_review', 'final_review')
TERMINAL = {'needs_attention', 'round_limit_exhausted', 'budget_exhausted', 'text_ready_for_production', 'upstream_writer_revision_required'}


def _codes():
    paths = {Path(__file__).resolve(), Path(contracts.__file__).resolve(), Path(client_module.__file__).resolve()}
    paths.update(Path(row['path']) for row in parent._code_bindings())
    return [core._binding(p) for p in sorted(paths)]


def _auth(path, parent_run):
    file = core._binding(Path(path).resolve()); value = core._read(file['path'])
    limits = value.get('old_total_limits', {})
    campaign_file = value.get('campaign_authorization', {})
    core._verify_file(campaign_file)
    campaign = core._read(campaign_file['path'])
    if (Path(value.get('parent_run', '')).resolve() != Path(parent_run).resolve()
            or type(value.get('max_rounds')) is not int or not 1 <= value['max_rounds'] <= 10
            or value.get('review_interval_rounds') != 5 or value.get('max_calls_per_round') != 3
            or value.get('new_media_authorized') is not False or value.get('automatic_transport_retry') is not False
            or type(limits.get('calls')) is not int or not 1 <= limits['calls'] <= 20
            or type(limits.get('reported_tokens')) is not int or not 1 <= limits['reported_tokens'] <= 500000
            or campaign.get('max_rounds') != 10 or campaign.get('review_interval_rounds') != 5
            or campaign.get('max_calls_per_round') != 3 or campaign.get('media_authorized') is not False
            or campaign.get('automatic_transport_retry') is not False
            or Path(campaign_file['path']).parent.resolve() != Path(value.get('campaign_dir', '')).resolve()
            or not value.get('user_statement')):
        raise ValueError('专属自然导演授权、共享campaign或原总预算非法')
    return file, value


def _audit(parent_run):
    run = Path(parent_run).resolve(); b, s = parent._verify(run)
    writer_only = (s['status'] in {'running', 'prepared'} and s['stage'] == 'director_full'
        and not any(core._read(p)['stage'] == 'director_full' for p in run.glob('REQUEST_*.json')))
    if (not (writer_only or (s['status'] == 'director_revision_exhausted' and s['stage'] == 'director_full'))
            or s.get('pending_call') is not None or s.get('reported_tokens') is None):
        raise ValueError('只接受v9已知导演耗尽或writer-only全文通过，未知/截断父链停止')
    if any((run / name).exists() for name in ('.execution.lock', '.graph_driver.lock')):
        raise ValueError('父运行仍在执行')
    gate = parent._evaluate_review(run, b, s, parent._value(s, 'review_bundle'), s['active']['review_bundle']['receipt'])
    if gate['gate']['decision'] != 'pass':
        raise ValueError('父同源原生全文审查未通过')
    inherited = b.get('inherited_consumption', {'calls_started': 0, 'reported_tokens': 0})
    consumption = {'calls_started': inherited['calls_started'] + s['calls_started'],
                   'reported_tokens': inherited['reported_tokens'] + s['known_reported_tokens']}
    original = (b.get('known_director_continuation') or b.get('quality_revision') or {}).get('original_budget', b['budget'])
    files = {run / 'BINDING.json', run / 'BINDING_ANCHOR.json', run / 'state.json'}
    for pattern in ('STATE_*.json', 'CLAIM_*.json', 'REQUEST_*.json', 'RESPONSE_*.json', 'CALL_LEDGER_*.json'):
        files.update(run.glob(pattern))
    files.update(Path(row['file']['path']) for row in s['active'].values())
    return {'binding': b, 'state': s, 'consumption': consumption, 'original_budget': original,
        'files': [core._binding(p) for p in sorted(files)], 'checkpoint': core._binding(sorted(run.glob('STATE_*.json'))[-1]),
        'screenplay': parent._text(s), 'feedback': [
            f"{e.get('code')}: {e.get('location')}: {e.get('message')}" for e in
            (s.get('director_feedback') or {}).get('content_contract_errors', [])]}


def _claim(run, audit):
    draft = audit['state']['active']['writer_full']['file']['sha256']
    identity = core._digest({'source': audit['binding']['source']['binding_id'], 'draft': draft, 'policy': contracts.quality_policy()})
    path = Path(CANONICAL_REGISTRY).resolve() / '_natural_director_continuations' / 'v10' / (identity + '.json')
    return path, {'schema': VERSION, 'run_dir': str(run), 'parent_run': audit['binding']['run_dir'],
        'source_binding_id': audit['binding']['source']['binding_id'], 'draft_sha256': draft,
        'parent_checkpoint': audit['checkpoint'], 'inherited_consumption': audit['consumption'], 'quality_policy': contracts.quality_policy()}


def _unique(run, claim):
    for p in (Path(CANONICAL_REGISTRY).resolve() / '_natural_director_continuations').glob('*/*.json'):
        other = core._read(p)
        if (other.get('source_binding_id') == claim['source_binding_id'] and other.get('draft_sha256') == claim['draft_sha256']
                and Path(other.get('run_dir', '')).resolve() != run):
            raise RuntimeError('同源完整稿已有跨版本唯一自然导演owner，不能重领轮数')


def _budget(audit, auth):
    old, used, limits = audit['original_budget'], audit['consumption'], auth['old_total_limits']
    return {'max_calls': min(old['max_calls'], limits['calls']) - used['calls_started'],
        'max_total_tokens': min(old['max_total_tokens'], limits['reported_tokens']) - used['reported_tokens'],
        'max_rounds': auth['max_rounds'], 'review_interval_rounds': 5, 'max_calls_per_round': 3}


def prepare(run_dir, *, parent_run, authorization_path):
    run = Path(run_dir).resolve(); audit = _audit(parent_run); auth_file, auth = _auth(authorization_path, parent_run)
    campaign = Path(auth['campaign_dir']).resolve()
    with core._lock(campaign / '.round.lock'):
        snapshots = sorted(campaign.glob('CAMPAIGN_STATE_*.json'))
        if not snapshots:
            if list(campaign.glob('ROUND_*_CLAIM.json')) or (campaign / 'CAMPAIGN_ANCHOR.json').exists():
                raise ValueError('共享campaign历史缺失，不初始化或清零')
            core._write(campaign / 'CAMPAIGN_STATE_00001.json', {'schema': VERSION, 'claims': [], 'previous': None})
            core._write(campaign / 'CAMPAIGN_ANCHOR.json', core._binding(campaign / 'CAMPAIGN_STATE_00001.json'))
        _campaign_claims(campaign)
    if all((run / n).exists() for n in ('BINDING.json', 'BINDING_ANCHOR.json', 'state.json')):
        with core._lock(run / '.execution.lock') as owner:
            _recover(run); b, _ = _verify(run)
            if b['parent_run'] != str(Path(parent_run).resolve()) or b['authorization_file'] != auth_file:
                raise ValueError('恢复不能改变父链或授权')
            return inspect(run, _lock_owner=owner)
    budget = _budget(audit, auth)
    if min(budget['max_calls'], budget['max_total_tokens']) < 1:
        raise ValueError('原故事总预算已耗尽')
    claim_path, claim = _claim(run, audit)
    with core._lock(Path(CANONICAL_REGISTRY).resolve() / '.registration.lock'):
        _unique(run, claim)
        if _audit(parent_run) != audit:
            raise ValueError('父链在准备中变化')
        if claim_path.exists() and core._read(claim_path) != claim:
            raise RuntimeError('已有唯一自然导演claim')
        partial = list(run.iterdir()) if run.exists() else []
        if partial and not claim_path.exists():
            raise ValueError('非空目录无同owner准备claim')
        if not claim_path.exists():
            core._write(claim_path, claim)
        run.mkdir(parents=True, exist_ok=True)
        text = audit['screenplay']; source = audit['binding']['source']
        b = {'schema': VERSION, 'run_dir': str(run), 'parent_run': str(Path(parent_run).resolve()),
            'parent_checkpoint': audit['checkpoint'], 'parent_evidence': audit['files'], 'authorization_file': auth_file,
            'authorization': auth, 'source': source, 'source_file': parent._prepared_json_binding(run / 'SOURCE.json', source),
            'screenplay_file': {'path': str(run / 'SCREENPLAY.md'), 'sha256': core._sha(text.encode()), 'bytes': len(text.encode())},
            'draft_binding': audit['state']['active']['writer_full']['file']['sha256'], 'brief': deepcopy(audit['binding']['brief']),
            'protocol': audit['binding']['protocol'], 'quality_policy': contracts.quality_policy(), 'code_bindings': _codes(),
            'registry': [*audit['binding']['registry'], core._binding(claim_path)], 'inherited_consumption': audit['consumption'],
            'inherited_stage_counters': {k: v for k, v in audit['state'].items() if k.endswith('_used')},
            'original_budget': audit['original_budget'], 'budget': budget, 'initial_feedback': audit['feedback']}
        s = {'schema': VERSION, 'status': 'prepared', 'stage': 'natural_director', 'rounds_started': 0,
            'calls_started': 0, 'known_reported_tokens': 0, 'reported_tokens': 0, 'pending_call': None,
            'pending_request_binding': None, 'call_bindings': [], 'active': {}, 'round_results': [], 'feedback': audit['feedback']}
        expected = {'SOURCE.json': source, 'BINDING.json': b, 'BINDING_ANCHOR.json': {'sha256': core._digest(b)},
                    'STATE_00001.json': s, 'state.json': s}
        for p in partial:
            wanted = b['screenplay_file'] if p.name == 'SCREENPLAY.md' else parent._prepared_json_binding(p, expected[p.name]) if p.name in expected else None
            if not p.is_file() or wanted is None or core._binding(p) != wanted:
                raise ValueError('已有准备文件不符，不覆盖：' + str(p))
        if not (run / 'SCREENPLAY.md').exists():
            parent._ensure_text(run / 'SCREENPLAY.md', text)
        for n, value in expected.items():
            if not (run / n).exists():
                core._write(run / n, value)
    return inspect(run)


def _text(b):
    return Path(b['screenplay_file']['path']).read_text(encoding='utf-8')


def _value(inputs, stage):
    row = inputs[stage]; core._verify_file(row['file']); p = Path(row['file']['path'])
    return p.read_text(encoding='utf-8') if stage == 'natural_director' else core._read(p)


def _payload(b, stage, inputs, feedback):
    args, kw = (b['source']['text'], _text(b)), {'brief': b['brief'], 'policy': b['quality_policy']}
    if stage == 'natural_director':
        return contracts.build_natural_director_payload(*args, **kw, feedback=feedback)
    text = _value(inputs, 'natural_director')
    if stage == 'extract_review':
        return contracts.build_extract_review_payload(*args, text, **kw)
    return contracts.build_final_review_payload(*args, text, _value(inputs, 'extract_review'), **kw)


def _spec(payload):
    return payload['messages'], contracts.normalize_actual_parameters(payload['parameters'])


def _campaign_claims(campaign):
    rows = []
    for n, path in enumerate(sorted(campaign.glob('ROUND_*_CLAIM.json')), 1):
        claim = core._read(path); core._verify_file(claim['request_binding']); request = core._read(claim['request_binding']['path'])
        if (path.name != f'ROUND_{n:03}_CLAIM.json' or request.get('stage') != 'natural_director'
                or request.get('round') != claim.get('local_round')
                or request.get('source_binding_id') != claim.get('source_binding')
                or Path(claim['request_binding']['path']).parent.resolve() != Path(claim.get('run_dir', '')).resolve()):
            raise ValueError('共享campaign实际轮claim身份不符')
        rows.append((path, claim))
    if len(rows) > 10:
        raise ValueError('共享campaign轮数超限')
    snapshots = sorted(campaign.glob('CAMPAIGN_STATE_*.json'))
    if not snapshots:
        raise ValueError('共享campaign缺不可变检查点，不能重领')
    core._verify_file(core._read(campaign / 'CAMPAIGN_ANCHOR.json'))
    for n, path in enumerate(snapshots, 1):
        value = core._read(path)
        if (path.name != f'CAMPAIGN_STATE_{n:05}.json' or len(value.get('claims', [])) != n - 1
                or value.get('previous') != (core._binding(snapshots[n-2]) if n > 1 else None)):
            raise ValueError('共享campaign不可变账本链不完整')
        for row in value['claims']:
            core._verify_file(row)
    if core._read(snapshots[-1])['claims'] != [core._binding(p) for p, _ in rows]:
        raise ValueError('共享campaign轮claim丢失或新增未决，不降低计数')
    expected = {claim['request_binding']['path'] for _, claim in rows}
    owners = {claim['run_dir'] for _, claim in rows}
    for registration in (Path(CANONICAL_REGISTRY).resolve() / '_natural_director_continuations').glob('*/*.json'):
        owner = Path(core._read(registration)['run_dir']); binding_file = owner / 'BINDING.json'
        if binding_file.exists() and Path(core._read(binding_file).get('authorization', {}).get('campaign_dir', '')).resolve() == campaign.resolve():
            owners.add(str(owner))
        elif not binding_file.exists() and list(owner.glob('REQUEST_*.json')):
            raise ValueError('已注册自然owner请求存在但冻结缺失，不回退共享轮数')
    for owner in owners:
        actual = {str(p.resolve()) for p in Path(owner).glob('REQUEST_*.json') if core._read(p).get('stage') == 'natural_director'}
        if not actual.issubset(expected):
            raise ValueError('实际自然请求缺共享轮claim，不重领')
    return rows


def _review_evidence(campaign):
    claims = _campaign_claims(campaign)
    if len(claims) < 5:
        raise ValueError('尚未完成第一批5轮')
    evidence = []
    for path, claim in claims[:5]:
        run = Path(claim['run_dir']); binding = core._read(run / 'BINDING.json')
        state = core._read(run / 'state.json'); conclusion = run / f"ROUND_{claim['local_round']:03}.json"
        if not conclusion.exists():
            if state.get('status') != 'text_ready_for_production' or state.get('rounds_started') != claim['local_round']:
                raise ValueError('5轮中仍有未完成、未知或未决结果，不放行第6轮')
            conclusion = run / 'OUTPUT_MANIFEST.json'
        result = core._read(conclusion); refs = result.get('artifacts', result.get('stages', {}))
        native_rows = []
        for artifact in refs.values():
            receipt = artifact['receipt']; core._verify_file(receipt); response = core._read(receipt['path'])
            core._verify_file(response['request_binding'])
            errors, tokens, _ = parent._response_evidence(response, binding)
            if errors or tokens is None:
                raise ValueError('复盘原生结论的结束或用量未知')
            native_rows.append({'request': response['request_binding'], 'response': receipt, 'reported_tokens': tokens})
        if not native_rows:
            raise ValueError('复盘缺原生完整结论')
        evidence.append({'claim': core._binding(path), 'conclusion': core._binding(conclusion),
            'source_binding': claim['source_binding'], 'local_round': claim['local_round'],
            'source_budget': binding['budget'], 'inherited_consumption': binding['inherited_consumption'], 'native_results': native_rows})
    return evidence


def record_campaign_review(campaign_dir, *, findings):
    if not isinstance(findings, str) or not findings.strip():
        raise ValueError('复盘需具体结论')
    campaign = Path(campaign_dir).resolve()
    with core._lock(campaign / '.round.lock'):
        value = {'schema': 'natural_director_campaign_review/v10', 'rounds_reviewed': 5,
            'evidence': _review_evidence(campaign), 'findings': findings, 'decision': 'continue_within_original_budgets',
            'media_authorized': False}
        path = campaign / 'REVIEW_005.json'; core._ensure(path, value)
        return core._binding(path)


def _valid_campaign_review(campaign):
    path = campaign / 'REVIEW_005.json'
    if not path.is_file():
        return False
    value = core._read(path)
    if (value.get('schema') != 'natural_director_campaign_review/v10' or value.get('rounds_reviewed') != 5
            or value.get('evidence') != _review_evidence(campaign) or not value.get('findings')
            or value.get('decision') != 'continue_within_original_budgets' or value.get('media_authorized') is not False):
        raise ValueError('第一批复盘不完整或未绑定5轮实际原生结论')
    return True


def _verify(run, *, state_override=None):
    run = Path(run).resolve(); b = core._read(run / 'BINDING.json'); s = core._read(run / 'state.json') if state_override is None else state_override
    snapshots = sorted(run.glob('STATE_*.json'))
    if (b.get('schema') != VERSION or b.get('run_dir') != str(run)
            or core._read(run / 'BINDING_ANCHOR.json').get('sha256') != core._digest(b)
            or not snapshots or core._read(snapshots[-1]) != s):
        raise ValueError('冻结身份或不可变检查点不符')
    for row in [b['authorization_file'], b['source_file'], b['screenplay_file'], *b['parent_evidence'], *b['code_bindings'], *b['registry']]:
        core._verify_file(row)
    audit = _audit(b['parent_run']); path, claim = _claim(run, audit); _unique(run, claim)
    af, auth = _auth(b['authorization_file']['path'], b['parent_run'])
    if (core._read(path) != claim or core._binding(path) not in b['registry'] or audit['consumption'] != b['inherited_consumption']
            or audit['checkpoint'] != b['parent_checkpoint'] or b['source'] != audit['binding']['source']
            or _text(b) != audit['screenplay'] or b['brief'] != audit['binding']['brief']
            or b['protocol'] != core._protocol() or b['quality_policy'] != contracts.quality_policy()
            or b['budget'] != _budget(audit, auth) or af != b['authorization_file'] or auth != b['authorization']):
        raise ValueError('父原生链、原稿、授权、协议或继承预算变化')
    requests = sorted(run.glob('REQUEST_*.json')); adopted = {r['path'] for r in s['call_bindings']}; known, rounds, counts = 0, 0, {}
    with core._lock(Path(b['authorization']['campaign_dir']) / '.round.lock'):
        shared = _campaign_claims(Path(b['authorization']['campaign_dir']))
        shared_requests = {row['request_binding']['path'] for _, row in shared}
    if len(requests) != s['calls_started'] or len(list(run.glob('CLAIM_*.json'))) != len(requests):
        raise ValueError('调用claim/请求与检查点不符；未知请求不重派')
    for n, p in enumerate(requests, 1):
        q, c = core._read(p), core._read(run / f'CLAIM_{n:03}.json')
        if (q.get('ordinal') != n or q.get('stage') not in STAGES or q.get('role') != ('writer' if q['stage'] == 'natural_director' else 'director')
                or q.get('source_binding_id') != b['source']['binding_id'] or q.get('draft_binding') != b['draft_binding']
                or c.get('request_binding') != core._binding(p)):
            raise ValueError('实际请求与唯一claim身份不符')
        rounds += q['stage'] == 'natural_director'; counts[rounds] = counts.get(rounds, 0) + 1
        if q['stage'] == 'natural_director' and str(p.resolve()) not in shared_requests:
            raise ValueError('本运行实际自然请求缺共享轮claim')
        if q.get('round') != rounds:
            raise ValueError('轮数与实际派发不符')
        m, params = _spec(_payload(b, q['stage'], q['input_bindings'], q.get('feedback')))
        if m != q['messages'] or params != q['parameters']:
            raise ValueError('原生完整请求不能按冻结合同重现')
        rp, lp = run / f'RESPONSE_{n:03}.json', run / f'CALL_LEDGER_{n:03}.json'
        if rp.exists():
            r = core._read(rp)
            if r.get('request_binding') != core._binding(p) or any(r.get(k) != q.get(k) for k in ('ordinal', 'stage', 'role', 'round')):
                raise ValueError('原生响应与原请求不符')
            _, tokens, _ = parent._response_evidence(r, b)
            if str(rp.resolve()) in adopted and tokens is not None:
                known += tokens
        if lp.exists() and (core._read(lp).get('request_binding') != core._binding(p) or not rp.exists()
                            or core._read(lp).get('response_binding') != core._binding(rp)):
            raise ValueError('实际账本与原生响应不符')
    for row in [*s['call_bindings'], *s['round_results']]:
        core._verify_file(row)
    if (known != s['known_reported_tokens'] or s['reported_tokens'] not in (None, known) or rounds != s['rounds_started']
            or any(v > 3 for v in counts.values()) or rounds > b['budget']['max_rounds']
            or len(requests) > b['budget']['max_calls'] or known > b['budget']['max_total_tokens']):
        raise ValueError('实际轮数、用量或原总预算不符')
    if s['pending_call'] is not None:
        if s['pending_request_binding'] != core._binding(run / f"REQUEST_{s['pending_call']:03}.json"):
            raise ValueError('未决请求身份变化')
    elif len(s['call_bindings']) != 3 * len(requests):
        raise ValueError('原生响应或用量账本缺失')
    for row in s['active'].values():
        core._verify_file(row['file']); core._verify_file(row['receipt'])
    return b, s


def _save(run, s):
    core._save_state(run, deepcopy(s))


def _recover(run):
    snapshots = sorted(run.glob('STATE_*.json'))
    if not snapshots:
        return
    latest = core._read(snapshots[-1])
    if core._read(run / 'state.json') == latest:
        return
    _verify(run, state_override=latest)
    p = run / ('.verified-projection-' + core._digest(latest)); data = json.dumps(latest, ensure_ascii=False, indent=2, allow_nan=False).encode()
    if not p.exists():
        with p.open('xb') as stream:
            stream.write(data)
    if p.read_bytes() != data:
        raise ValueError('恢复临时文件不符')
    p.replace(run / 'state.json')


def recover_projection(run_dir):
    run = Path(run_dir).resolve()
    with core._lock(run / '.execution.lock') as owner:
        _recover(run); _verify(run)
        return inspect(run, _lock_owner=owner)


def _adopt(run, b, s, n):
    qp, rp = run / f'REQUEST_{n:03}.json', run / f'RESPONSE_{n:03}.json'; q, r = core._read(qp), core._read(rp)
    if r.get('request_binding') != core._binding(qp):
        raise ValueError('原生响应与原请求身份不符')
    errors, tokens, text = parent._response_evidence(r, b); lp = run / f'CALL_LEDGER_{n:03}.json'
    core._ensure(lp, {'schema': VERSION, 'ordinal': n, 'round': q['round'], 'request_binding': core._binding(qp),
        'response_binding': core._binding(rp), 'reported_tokens': tokens, 'usage_known': tokens is not None, 'errors': errors})
    existing = {row['path'] for row in s['call_bindings']}
    if str(rp.resolve()) not in existing and tokens is not None:
        s['known_reported_tokens'] += tokens
    for p in (qp, rp, lp):
        if str(p.resolve()) not in existing:
            s['call_bindings'].append(core._binding(p))
    s['reported_tokens'] = s['known_reported_tokens'] if tokens is not None else None
    if errors:
        s.update(status='needs_attention', halt_reason='；'.join(errors))
    else:
        s.update(status='running', pending_call=None, pending_request_binding=None)
    _save(run, s)
    if errors:
        raise RuntimeError(s['halt_reason'])
    return text, core._binding(rp)


def _dispatch(run, b, s, clients):
    _verify(run); stage = s['stage']; m, p = _spec(_payload(b, stage, s['active'], s['feedback']))
    if s['calls_started']:
        last = core._read(run / f"REQUEST_{s['calls_started']:03}.json")
        if (last['stage'] == stage and last['round'] == s['rounds_started'] and last['input_bindings'] == s['active']
                and last['messages'] == m and last['parameters'] == p):
            if not (run / f"RESPONSE_{last['ordinal']:03}.json").exists():
                raise RuntimeError('已有在途原请求结果未知，不重派')
            return _adopt(run, b, s, last['ordinal'])
    key = core._digest({'stage': stage, 'round': s['rounds_started'] + (stage == 'natural_director'), 'messages': m, 'inputs': s['active']})
    for path in sorted(run.glob('REQUEST_*.json')):
        q = core._read(path)
        if q['stage_key'] == key:
            if not (run / f"RESPONSE_{q['ordinal']:03}.json").exists():
                raise RuntimeError('原请求结果未知，不重派')
            return _adopt(run, b, s, q['ordinal'])
    if s['pending_call'] is not None or s['status'] in TERMINAL:
        raise RuntimeError('存在未决请求或运行已停止')
    size = len(json.dumps({'messages': m, 'parameters': p}, ensure_ascii=False).encode()); reserve = size + p['max_tokens'] + 4096
    if s['calls_started'] >= b['budget']['max_calls'] or size > core.MAX_REQUEST_BYTES or s['known_reported_tokens'] + reserve > b['budget']['max_total_tokens']:
        s.update(status='budget_exhausted', halt_reason='原总调用或完整请求预留不足，额外轮数不扩预算'); _save(run, s)
        return None, None
    campaign = Path(b['authorization']['campaign_dir']).resolve()
    with core._lock(campaign / '.round.lock'):
        campaign_claims = _campaign_claims(campaign)
        if stage == 'natural_director':
            if len(campaign_claims) >= 10 or s['rounds_started'] >= b['budget']['max_rounds']:
                s.update(status='round_limit_exhausted', halt_reason='共享campaign两批5轮已耗尽'); _save(run, s)
                return None, None
            if len(campaign_claims) >= 5 and not _valid_campaign_review(campaign):
                s.update(status='campaign_review_required'); _save(run, s)
                return None, None
        n = s['calls_started'] + 1; rnd = s['rounds_started'] + (stage == 'natural_director'); qp = run / f'REQUEST_{n:03}.json'
        q = {'schema': VERSION, 'ordinal': n, 'round': rnd, 'stage': stage, 'stage_key': key,
            'role': 'writer' if stage == 'natural_director' else 'director', 'source_binding_id': b['source']['binding_id'],
            'draft_binding': b['draft_binding'], 'messages': m, 'parameters': p, 'input_bindings': deepcopy(s['active']),
            'feedback': deepcopy(s['feedback']), 'reservation_tokens': reserve}
        core._write(qp, q); core._write(run / f'CLAIM_{n:03}.json', {'schema': VERSION, 'ordinal': n, 'stage_key': key, 'request_binding': core._binding(qp)})
        if stage == 'natural_director':
            core._write(campaign / f'ROUND_{len(campaign_claims)+1:03}_CLAIM.json', {'schema': VERSION,
                'source_binding': b['source']['binding_id'], 'parent_run': b['parent_run'], 'run_dir': str(run), 'local_round': rnd, 'request_binding': core._binding(qp)})
            snapshots = sorted(campaign.glob('CAMPAIGN_STATE_*.json'))
            core._write(campaign / f'CAMPAIGN_STATE_{len(snapshots)+1:05}.json', {'schema': VERSION,
                'claims': [core._binding(path) for path in sorted(campaign.glob('ROUND_*_CLAIM.json'))],
                'previous': core._binding(snapshots[-1])})
        s.update(calls_started=n, rounds_started=rnd, pending_call=n, pending_request_binding=core._binding(qp), status='running'); _save(run, s)
    r = {k: q[k] for k in ('schema', 'ordinal', 'round', 'stage', 'stage_key', 'role')}; r['request_binding'] = core._binding(qp)
    try:
        result = clients.call(q['role'], m, **p)
        r.update(response_text=result.text, response_metadata=result.metadata, response_payload=result.response_payload)
    except Exception as exc:
        r.update(error=str(exc), response_text=getattr(exc, 'response_text', None), response_metadata=getattr(exc, 'response_metadata', {}), response_payload=getattr(exc, 'response_payload', None))
    core._write(run / f'RESPONSE_{n:03}.json', r)
    return _adopt(run, b, s, n)


def _store(run, s, stage, name, value, receipt):
    path = run / name
    if stage == 'natural_director':
        parent._ensure_text(path, value)
    else:
        core._ensure(path, value)
    s['active'][stage] = {'file': core._binding(path), 'receipt': receipt}


def _parse(b, stage, text, request, receipt):
    parser = contracts.parse_extract_review if stage == 'extract_review' else contracts.parse_final_review
    return parser(text, source_binding=b['source']['binding_id'], draft_binding=b['draft_binding'],
        materials=parent.roles.parse_json(request['messages'][-1]['content']), native_response_ref=receipt['sha256'],
        artifact_id=f"{stage}-{request['ordinal']:03}")


def _bundle(b, s):
    evidence = {'verified': True, 'source_binding': b['source']['binding_id'], 'draft_binding': b['draft_binding'],
                'protocol': b['protocol'], 'stages': {}}
    for stage in STAGES:
        row = s['active'][stage]; core._verify_file(row['file']); core._verify_file(row['receipt'])
        response = core._read(row['receipt']['path']); qf = response['request_binding']; core._verify_file(qf)
        q = core._read(qf['path']); errors, tokens, text = parent._response_evidence(response, b)
        m, p = _spec(_payload(b, stage, q['input_bindings'], q.get('feedback')))
        if errors or tokens is None or q['stage'] != stage or q['messages'] != m or q['parameters'] != p:
            raise ValueError('最终整包原生身份、完整输入、用量或结束不符')
        expected = text if stage == 'natural_director' else _parse(b, stage, text, q, row['receipt'])
        if _value(s['active'], stage) != expected:
            raise ValueError('最终交接不是同一原生响应派生')
        evidence['stages'][stage] = {'request': qf, 'response': row['receipt']}
    natural, extract, final = (_value(s['active'], key) for key in STAGES)
    compiled = contracts.compile_video_requests(extract)
    evidence.update(natural_director_sha256=core._sha(natural.encode()),
        extract_native_response_ref=s['active']['extract_review']['receipt']['sha256'],
        final_native_response_ref=s['active']['final_review']['receipt']['sha256'], video_requests_sha256=compiled['sha256'])
    handoff = contracts.make_handoff(natural, extract, final, source_binding=b['source']['binding_id'],
        draft_binding=b['draft_binding'], brief=b['brief'], native_evidence=evidence)
    return handoff, compiled


def _complete(run, b, s):
    handoff, compiled = _bundle(b, s); contracts.validate_handoff_for_dispatch(handoff)
    core._ensure(run / 'PRODUCTION_HANDOFF.json', handoff); core._ensure(run / 'VIDEO_REQUESTS.json', compiled)
    parent._ensure_text(run / 'NATURAL_DIRECTOR.md', _value(s['active'], 'natural_director'))
    manifest = {'schema': VERSION, 'status': 'text_ready_for_production', 'source_binding': b['source']['binding_id'],
        'draft_binding': b['draft_binding'], 'stages': s['active'], 'files': [core._binding(run / name) for name in
        ('SCREENPLAY.md', 'NATURAL_DIRECTOR.md', 'PRODUCTION_HANDOFF.json', 'VIDEO_REQUESTS.json')],
        'human_approved': False, 'automatic_media_submit': False, 'media_generated': False}
    core._ensure(run / 'OUTPUT_MANIFEST.json', manifest)
    s.update(status='text_ready_for_production', stage='complete', output_manifest=core._binding(run / 'OUTPUT_MANIFEST.json')); _save(run, s)


def _failed(run, s, value):
    n = s['rounds_started']; path = run / f'ROUND_{n:03}.json'
    core._ensure(path, {'schema': VERSION, 'round': n, 'status': 'content_revision_required',
        'stage': s['stage'], 'native_result': value, 'artifacts': deepcopy(s['active'])})
    row = core._binding(path)
    if row not in s['round_results']:
        s['round_results'].append(row)
    native = value.get('native', value)
    s.update(stage='natural_director', active={}, feedback=[native['summary']] + [
        f"{e.get('severity')} at {e.get('location')}: {e.get('evidence')}；{e.get('suggestion')}"
        for e in native.get('issues', [])])
    if any(e.get('responsibility_layer') == 'writer' and e.get('severity') in {'major', 'blocking'} for e in native.get('issues', [])):
        s.update(status='upstream_writer_revision_required', halt_reason='原生审查确认完整稿上游问题，自然导演无权改写，保存本轮并停止')


def execute(run_dir, *, clients=None, max_steps=None):
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError('max_steps必须为正整数')
    run = Path(run_dir).resolve()
    with core._lock(run / '.execution.lock') as owner:
        _recover(run); b, s = _verify(run)
        if s['status'] in TERMINAL:
            return inspect(run, _lock_owner=owner)
        clients = clients or CreativeRoleClients(); count = 0
        try:
            while s['status'] not in TERMINAL:
                if s['stage'] == 'complete':
                    _complete(run, b, s); break
                stage = s['stage']; text, receipt = _dispatch(run, b, s, clients)
                if receipt is None:
                    break
                q = core._read(core._read(receipt['path'])['request_binding']['path']); n = q['ordinal']
                if stage == 'natural_director':
                    s['active'] = {}; _store(run, s, stage, f'NATURAL_DIRECTOR_{n:03}.md', text, receipt)
                    s.update(stage='extract_review')
                else:
                    try:
                        value = _parse(b, stage, text, q, receipt)
                    except contracts.NaturalDirectorContractError as exc:
                        allowed = {'SERVICE_DURATION', 'TOTAL_DURATION', 'SEGMENT_ID_DUPLICATE', 'EXTRACT_SEGMENTS', 'REVIEW_UNRESOLVED_CONTENT'}
                        if not exc.errors or any(e['code'] not in allowed for e in exc.errors):
                            raise
                        original = contracts.parse_json(text)
                        value = {'schema': VERSION + '/known-content-rejection', 'native_text': text, 'original_native': original,
                            'native': {'summary': '完整原生结果已知，程序发现实质内容合同问题；原判词保留在original_native。',
                                'issues': [*original.get('issues', []), *[{'severity': 'major', 'location': e['location'],
                                    'evidence': e['code'] + ': ' + e['message'], 'suggestion': '提交完整新自然导演并全文复审。'} for e in exc.errors]]}}
                        _store(run, s, stage, f'REJECTED_{stage.upper()}_{n:03}.json', value, receipt)
                        _failed(run, s, value); _save(run, s); count += 1
                        if max_steps is not None and count >= max_steps:
                            break
                        continue
                    _store(run, s, stage, f'{stage.upper()}_{n:03}.json', value, receipt)
                    if value.get('verdict') != 'pass':
                        _failed(run, s, value)
                    elif stage == 'extract_review':
                        contracts.compile_video_requests(value); s.update(stage='final_review')
                    else:
                        s.update(stage='complete')
                _save(run, s); count += 1
                if max_steps is not None and count >= max_steps:
                    if s['stage'] == 'complete':
                        _complete(run, b, s)
                    break
        except Exception as exc:
            disk = core._read(run / 'state.json'); disk.update(status='needs_attention', halt_reason=str(exc)); _save(run, disk)
            raise
        return inspect(run, _lock_owner=owner)


def inspect(run_dir, *, _lock_owner=None):
    run = Path(run_dir).resolve()
    if not (run / 'BINDING.json').exists():
        return {'schema': VERSION, 'run_dir': str(run), 'status': 'unprepared', 'dispatch_blocked': True,
                'blockers': ['任务未准备'], 'artifacts': {}, 'human_approved': False, 'automatic_media_submit': False}
    b, s = core._read(run / 'BINDING.json'), core._read(run / 'state.json'); status, blockers, artifacts, recovery = s['status'], [], {}, False
    try:
        _verify(run)
        if status == 'text_ready_for_production':
            core._verify_file(s['output_manifest']); manifest = core._read(s['output_manifest']['path'])
            for row in manifest['files']:
                core._verify_file(row)
            handoff, compiled = _bundle(b, s)
            if (core._read(run / 'PRODUCTION_HANDOFF.json') != handoff or core._read(run / 'VIDEO_REQUESTS.json') != compiled
                    or manifest['stages'] != s['active']):
                raise ValueError('最终交接不是全部实际原生回执的完整派生')
            artifacts = {Path(row['path']).name: row['path'] for row in manifest['files']}
    except Exception as exc:
        status = 'evidence_invalid'; blockers.append(str(exc)); snapshots = sorted(run.glob('STATE_*.json'))
        if snapshots:
            try:
                latest = core._read(snapshots[-1]); _verify(run, state_override=latest); recovery = latest != s
            except Exception:
                pass
    if s.get('pending_call') is not None:
        blockers.append('存在未决原请求，不重派')
    if s.get('halt_reason'):
        blockers.append(s['halt_reason'])
    if (run / '.execution.lock').exists() and core._read(run / '.execution.lock').get('owner') != _lock_owner:
        blockers.append('执行锁存在')
    inherited = b['inherited_consumption']
    return {'schema': VERSION, 'run_dir': str(run), 'status': status, 'stage': s['stage'], 'state': s,
        'rounds_started': s['rounds_started'], 'calls_started': s['calls_started'], 'known_reported_tokens': s['known_reported_tokens'],
        'reported_tokens': s['reported_tokens'], 'pending_call': s['pending_call'], 'inherited_consumption': inherited,
        'combined_calls_started': inherited['calls_started'] + s['calls_started'],
        'combined_known_reported_tokens': inherited['reported_tokens'] + s['known_reported_tokens'],
        'projection_recovery_available': recovery, 'blockers': blockers,
        'dispatch_blocked': bool(blockers) or status in TERMINAL, 'artifacts': artifacts,
        'human_approved': False, 'automatic_media_submit': False, 'media_generated': False}


def preview(run_dir):
    view = inspect(run_dir)
    if view['status'] == 'unprepared':
        return view
    b = core._read(Path(run_dir) / 'BINDING.json'); s = view['state']; preflight = None
    if not view['dispatch_blocked']:
        m, p = _spec(_payload(b, s['stage'], s['active'], s['feedback']))
        size = len(json.dumps({'messages': m, 'parameters': p}, ensure_ascii=False).encode()); reserve = size + p['max_tokens'] + 4096
        preflight = {'stage': s['stage'], 'input_bytes': size, 'max_output_tokens': p['max_tokens'], 'reservation_tokens': reserve,
            'reservation_fits': s['known_reported_tokens'] + reserve <= b['budget']['max_total_tokens'], 'read_only': True, 'dispatch_authorized': False}
    return {**view, 'budget': b['budget'], 'next_request_preflight': preflight,
        'remaining_calls': max(0, b['budget']['max_calls'] - s['calls_started']),
        'remaining_known_tokens': max(0, b['budget']['max_total_tokens'] - s['known_reported_tokens'])}


def prepare_source(source_run_dir, *, authorization_path, source_path=None, acquisition_receipt=None,
                   title=None, book_id=None, scope=None, source_kind='novel', brief=None, catalog_path=None):
    """New default source route freezes v9 writer logic, never its JSON director."""
    run = Path(source_run_dir).resolve(); af, auth = _auth(authorization_path, run)
    view = parent.prepare(run, source_path=source_path, acquisition_receipt=acquisition_receipt, title=title,
        book_id=book_id, scope=scope, source_kind=source_kind, brief=brief, catalog_path=catalog_path,
        max_calls=auth['old_total_limits']['calls'], max_total_tokens=auth['old_total_limits']['reported_tokens'])
    route = {'schema': VERSION, 'source_run': str(run), 'authorization_file': af, 'code_bindings': _codes(),
             'allowed_stages': ['writer_full', 'review_full', 'clarify_full'], 'heavy_json_director_allowed': False}
    core._ensure(run / 'WRITER_ONLY_ROUTE.json', route)
    core._ensure(run / 'WRITER_ONLY_ROUTE_ANCHOR.json', {'sha256': core._digest(route)})
    return inspect_source(run)


def _source_route(run):
    route = core._read(run / 'WRITER_ONLY_ROUTE.json')
    if (route.get('schema') != VERSION or route.get('source_run') != str(run)
            or route.get('allowed_stages') != ['writer_full', 'review_full', 'clarify_full']
            or route.get('heavy_json_director_allowed') is not False
            or core._read(run / 'WRITER_ONLY_ROUTE_ANCHOR.json').get('sha256') != core._digest(route)):
        raise ValueError('writer-only专属路线或派发范围不符')
    for row in [route['authorization_file'], *route['code_bindings']]:
        core._verify_file(row)
    _auth(route['authorization_file']['path'], run)
    return route


def inspect_source(source_run_dir):
    run = Path(source_run_dir).resolve(); view = parent.inspect(run)
    if view['status'] == 'unprepared':
        return view
    try:
        route = _source_route(run)
    except Exception as exc:
        return {**view, 'status': 'evidence_invalid', 'dispatch_blocked': True,
                'blockers': [*view['blockers'], str(exc)], 'writer_only': True}
    return {**view, 'writer_only': True, 'writer_only_route': route,
        'writer_ready': view.get('stage') == 'director_full' and not view.get('pending_call') and not view['blockers']}


def preview_source(source_run_dir):
    return inspect_source(source_run_dir)


def execute_writer_only(source_run_dir, *, clients=None, max_steps=None):
    """Stage admission is inside the same native lock, before any request claim."""
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError('max_steps必须为正整数')
    run = Path(source_run_dir).resolve(); clients = clients or parent.CreativeRoleClients(); count = 0
    with core._lock(run / '.execution.lock'):
        _source_route(run); parent._recover_state_projection(run); b, s = parent._verify(run)
        try:
            while s['status'] not in parent.TERMINAL and s['stage'] in {'writer_full', 'review_full', 'clarify_full'}:
                _source_route(run); stage = s['stage']
                payload = parent._build_stage_payload(b, s)
                text, receipt = parent._dispatch(run, b, s, stage, payload, clients)
                number = core._read(receipt['path'])['ordinal']
                if stage == 'writer_full':
                    s['active'] = {}; parent._store(run, s, stage, f'DRAFT_{number:03}.md', text, receipt, text=True)
                    s.update(stage='review_full', previous_draft=None, feedback=None, draft_clarifications_used=0,
                        previous_bundle=None, director_previous=None, director_feedback=None, director_rejected_receipt=None)
                else:
                    bundle = parent.roles.parse_review_bundle(text, source_binding=b['source']['binding_id'],
                        draft_binding=s['active']['writer_full']['file']['sha256'], native_response_ref=receipt['sha256'],
                        artifact_prefix=f'review-{number:03}', required_issues=payload.get('required_issues'))
                    parent._store(run, s, 'review_bundle', f'REVIEW_BUNDLE_{number:03}.json', bundle, receipt)
                    for key, label in (('scene_ledger', 'SCENE_LEDGER'), ('review', 'REVIEW'), ('adjudication', 'ADJUDICATION')):
                        parent._store(run, s, key, f'{label}_{number:03}.json', bundle[key], receipt)
                    gate = parent._evaluate_review(run, b, s, bundle, receipt)
                    parent._store(run, s, 'gate', f'GATE_{number:03}.json', gate)
                    decision = gate['gate']
                    if decision['decision'] == 'pass':
                        parent._store(run, s, 'episode', f'EPISODE_{number:03}.json', parent._episode(b, bundle))
                        tags = list(dict.fromkeys([entity for e in bundle['scene_ledger']['events'] for entity in e['entities']]))
                        candidates = parent.director.discover_asset_candidates(b['catalog_snapshot']['path'], tags)
                        parent._store(run, s, 'asset_candidates', f'ASSET_CANDIDATES_{number:03}.json',
                            {'schema': parent.VERSION, 'catalog': b['catalog_snapshot'], 'search_tags': tags,
                             'candidates': candidates, 'current_casting_status': 'unbound'})
                        s.update(stage='director_full')
                    elif decision['next_action'] == 'revise_full_draft':
                        s.update(stage='writer_full', previous_draft=parent._text(s), feedback={'review': bundle, 'gate': gate}, status='needs_full_revision')
                    elif decision['next_action'] in {'clarify_same_draft', 'full_review_same_draft'}:
                        s.update(stage='clarify_full')
                    else:
                        s.update(status='content_revision_exhausted', halt_reason=';'.join(decision['stop_reasons']))
                parent._save_state(run, s); count += 1
                if max_steps is not None and count >= max_steps:
                    break
        except Exception as exc:
            disk = core._read(run / 'state.json'); disk.update(status='needs_attention', halt_reason=str(exc)); parent._save_state(run, disk)
            raise
    return inspect_source(run)


def execute_source(source_run_dir, *, run_dir, authorization_path, clients=None, max_steps=None):
    view = execute_writer_only(source_run_dir, clients=clients, max_steps=max_steps)
    if not view.get('writer_ready'):
        return view
    route = _source_route(Path(source_run_dir).resolve())
    if core._binding(Path(authorization_path).resolve()) != route['authorization_file']:
        raise ValueError('source与自然导演必须使用同一专属授权')
    prepare(run_dir, parent_run=source_run_dir, authorization_path=authorization_path)
    return execute(run_dir, clients=clients, max_steps=max_steps)
