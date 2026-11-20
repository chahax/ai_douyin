"""One explicitly authorized S01 text trial; no media or retry interface."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory import novel_adaptation_pipeline_v1 as io
from src.content_factory import natural_director_contracts_v10 as contracts
from src.content_factory import performance_timing_reference_v2 as timing
from src.content_factory.creative_workflow_roles import role_config
from src.content_factory.natural_director_role_clients_v10 import NaturalDirectorRoleClients
from src.content_factory.novel_plaintext_contracts_v3 import response_evidence

RUN = ROOT / 'data/narrative_pacing_production/20261018_timing_v2_S01'
PARENT = ROOT / 'data/narrative_quality_production/20261018_v10/run'
EDIT = ROOT / 'data/narrative_pacing_revision/20261018_dialogue_v4'
SCOPE = 's01_timing_v2_20261018_single_model_candidate'
PREFIX = '''本次是独立的一次S01单段文本测试。下文“完整/全稿/结尾”指这一个S01的完整互动，不是重出全片。完整原文、旧已通过剧本仅作背景；brief里的编辑候选明确尚未模型验收。本轮创作边界以brief.selected_s01和single_segment_requirements为准，允许这些已声明的地点、起态和压缩对白改编。只输出/整理一个S01，不把后续剧情拍入本段，不套用旧完整片105–135秒。完整v2估时规范是项目参考，逐句核对，不机械按字数判通过。
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def _text(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(value)


def _protocol():
    return {role: {k: getattr(c, k) for k in ('provider', 'model', 'base_url')}
            for role in ('writer', 'director') for c in [role_config(role)]}


def _save_state(status, **extra):
    count = len(list(RUN.glob('REQUEST_*.json')))
    known, unknown = 0, []
    for n in range(1, count + 1):
        p = RUN / f'CALL_LEDGER_{n:03}.json'
        bill = io._read(p).get('reported_tokens') if p.exists() else None
        if bill is None:
            unknown.append(n)
        else:
            known += bill
    result = dict(scope=SCOPE, at=now(), status=status, calls_started=count,
        known_reported_tokens=known, unknown_calls=unknown,
        inherited_calls=17, inherited_reported_tokens=305158,
        cumulative_calls=17 + count, cumulative_known_reported_tokens=305158 + known,
        cumulative_reported_tokens=None if unknown else 305158 + known,
        original_max_calls=20, original_max_total_tokens=500000,
        new_media_calls=0, automatic_retry=False, **extra)
    io._write(RUN / f'STATE_{len(list(RUN.glob("STATE_*.json"))) + 1:05}.json', result)
    return result


def prepare():
    if (RUN / 'BINDING.json').exists():
        raise RuntimeError('本次准备已有记录；只检查或继续已知阶段，不重领范围')
    parent, state = io._read(PARENT / 'BINDING.json'), io._read(PARENT / 'STATE.json')
    assert state['status'] == 'text_ready_for_production' and state['pending_call'] is None
    assert parent['inherited_consumption']['calls_started'] + state['calls_started'] == 17
    assert parent['inherited_consumption']['reported_tokens'] + state['known_reported_tokens'] == 305158
    assert state['reported_tokens'] == state['known_reported_tokens']
    for expected in parent['code_bindings'] + parent['parent_evidence'] + state['call_bindings']:
        io._verify_file(expected)
    assert parent['original_budget']['max_calls'] == 20
    assert parent['original_budget']['max_total_tokens'] == 500000
    protocol = _protocol()
    assert protocol == {role: parent['protocol'][role] for role in ('writer', 'director')}
    selected = io._read(EDIT / 'SEGMENTS.json')['segments'][0]
    brief = timing.apply_brief(dict(source_kind='original', min_duration_seconds=4,
        max_duration_seconds=15, duration_policy='single_segment_content_first',
        single_segment_scope='only S01; not complete-film acceptance',
        preferred_seconds=7, selected_s01=selected,
        editorial_context_status='assistant_editorial_candidate_not_model_accepted',
        editorial_full_context=(EDIT / 'FULL_SCREENPLAY.md').read_text(encoding='utf-8'),
        single_segment_requirements=[
            '独立重排S01；三句对白与说话人、段首段尾不变。其余段只作承接背景，不生成。',
            '先核对白实际读法、发音量、说话状态、声音时长、明确停连和接话间隙，再比较并行动作依赖。',
            '约7秒优先但不机械照抄内部秒表，4至15秒整数由内容决定；若必须延长应说明具体必要内容。',
            '普通神情开镜已成立，动作对白反应自然重叠；刺激先到再反应，最后有效内容完成即收。',
            '可附简短逐句估时，内部分析与给视频模型的纯表演提示分开；后者不写小数硬时点。',
            '女儿26岁成年，父亲约50岁成年；父亲深蓝外套穿在身上、票在内袋。仅两人，无字幕旁白广播配乐。',
            '单连续同侧双人中/中近景可看清三分之二侧脸、相互视线及桌面推票；不望镜头。',
            '不强加慢速愧疚/哽咽；此次S01只需轻微意外，不从中性脸重新酝酿情绪。']))
    RUN.mkdir(parents=True, exist_ok=True)
    auth = dict(scope=SCOPE, user_statement='可以尝试把这个设置给模型重新输出第一段',
        interpretation='一次S01 MiniMax自然文本，最多两次必要DeepSeek整理及实际请求全文审核；仅文本',
        at=now(), max_new_calls=3, max_minimax_candidates=1, max_content_revisions=0,
        inherited_calls=17, inherited_reported_tokens=305158,
        original_max_calls=20, original_max_total_tokens=500000,
        old_campaign_10_round_stop_preserved=True, media_authorized=False, automatic_transport_retry=False)
    io._write(RUN / 'AUTHORIZATION.json', auth)
    paths = [PARENT / n for n in ('BINDING.json', 'STATE.json', 'SOURCE.json', 'SCREENPLAY.md')]
    paths += [EDIT / n for n in ('SEGMENTS.json', 'FULL_SCREENPLAY.md', 'DIALOGUE_TIMING.json')]
    paths += [ROOT / 'docs/PERFORMANCE_TIMING_REFERENCE_V2_20261018.md',
        ROOT / 'docs/S01_TIMING_V2_MODEL_TRIAL_PLAN_20261018.md', Path(__file__),
        Path(timing.__file__), Path(contracts.__file__)]
    paths += [Path(io.__file__), Path(sys.modules[role_config.__module__].__file__),
        Path(sys.modules[response_evidence.__module__].__file__),
        Path(sys.modules[NaturalDirectorRoleClients.__module__].__file__)]
    source = parent['source']
    accepted = (PARENT / 'SCREENPLAY.md').read_text(encoding='utf-8')
    assert hashlib.sha256(accepted.encode('utf-8')).hexdigest() == parent['draft_binding']
    b = dict(scope=SCOPE, source=source, accepted_full_draft=accepted,
        draft_binding=parent['draft_binding'], brief=brief, protocol=protocol,
        authorization=io._binding(RUN / 'AUTHORIZATION.json'), preserved_files=[io._binding(p) for p in paths])
    claim_path = io.CANONICAL_REGISTRY / '_segment_timing_trials/v1' / (source['binding_id'] + '_S01_timing_v2_20261018.json')
    io._write(claim_path, dict(scope=SCOPE, source_binding=source['binding_id'], run_dir=str(RUN),
        authorization=io._binding(RUN / 'AUTHORIZATION.json'), inherited_calls=17, max_new_calls=3))
    b['canonical_claim'] = io._binding(claim_path)
    io._write(RUN / 'BINDING.json', b)
    io._write(RUN / 'BINDING_ANCHOR.json', dict(binding=io._binding(RUN / 'BINDING.json')))
    return _save_state('prepared_not_submitted')


def _verify():
    io._verify_file(io._read(RUN / 'BINDING_ANCHOR.json')['binding'])
    b = io._read(RUN / 'BINDING.json')
    assert b['scope'] == SCOPE
    for item in b['preserved_files'] + [b['authorization'], b['canonical_claim']]:
        io._verify_file(item)
    assert _protocol() == b['protocol']
    return b


def _known(n):
    b = _verify()
    qp, rp = RUN / f'REQUEST_{n:03}.json', RUN / f'RESPONSE_{n:03}.json'
    q, r = io._read(qp), io._read(rp)
    ledger, claim = io._read(RUN / f'CALL_LEDGER_{n:03}.json'), io._read(RUN / f'CLAIM_{n:03}.json')
    assert ledger['request_binding'] == claim['request_binding'] == r['request_binding'] == io._binding(qp)
    assert ledger['response_binding'] == io._binding(rp)
    assert q['binding'] == io._binding(RUN / 'BINDING.json')
    assert q['source_binding'] == b['source']['binding_id'] and q['draft_binding'] == b['draft_binding']
    assert q['scope'] == r['scope'] == SCOPE and q['ordinal'] == r['ordinal'] == ledger['ordinal'] == n
    role = 'writer' if n == 1 else 'director'
    assert q['role'] == r['role'] == role
    errors, bill, body = response_evidence(r, {**b['protocol'][role], 'role': role})
    choices = (r.get('response_payload') or {}).get('choices') or []
    assert len(choices) == 1 and choices[0]['finish_reason'] == 'stop'
    assert not choices[0]['message'].get('tool_calls')
    assert errors == ledger['errors'] == [] and type(bill) is int and bill == ledger['reported_tokens']
    assert body is not None
    return body, io._binding(rp), q


def _dispatch(n, payload, clients=None):
    b = _verify()
    assert n in (1, 2, 3)
    qp, rp = RUN / f'REQUEST_{n:03}.json', RUN / f'RESPONSE_{n:03}.json'
    if qp.exists():
        raise RuntimeError('该阶段已有不可变请求，不重派；已知结果请只读核对原文件')
    if len(list(RUN.glob('REQUEST_*.json'))) != n - 1:
        raise RuntimeError('阶段计数不连续')
    billed = 0
    for ordinal in range(1, n):
        _known(ordinal)
        billed += io._read(RUN / f'CALL_LEDGER_{ordinal:03}.json')['reported_tokens']
    parameters = contracts.normalize_actual_parameters(payload['parameters'])
    size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    reserve = size + parameters['max_tokens'] + 4096
    assert size <= io.MAX_REQUEST_BYTES and 17 + n <= 20 and 305158 + billed + reserve <= 500000
    role = 'writer' if n == 1 else 'director'
    q = dict(scope=SCOPE, ordinal=n, role=role, messages=payload['messages'], parameters=parameters,
        source_binding=b['source']['binding_id'], draft_binding=b['draft_binding'],
        binding=io._binding(RUN / 'BINDING.json'), reservation_tokens=reserve,
        inherited_calls=17, inherited_reported_tokens=305158)
    io._write(qp, q)
    io._write(RUN / f'CLAIM_{n:03}.json', dict(ordinal=n, request_binding=io._binding(qp), automatic_retry=False))
    _save_state('request_dispatched_or_pending', pending_call=n)
    record = dict(scope=SCOPE, ordinal=n, role=role, request_binding=io._binding(qp))
    try:
        result = (clients or NaturalDirectorRoleClients()).call(role, q['messages'], **parameters)
        record.update(response_text=result.text, response_metadata=result.metadata, response_payload=result.response_payload)
    except Exception as exc:
        record.update(error=str(exc), response_text=getattr(exc, 'response_text', None),
            response_metadata=getattr(exc, 'response_metadata', {}), response_payload=getattr(exc, 'response_payload', None))
    io._write(rp, record)
    errors, bill, body = response_evidence(record, {**b['protocol'][role], 'role': role})
    native = record.get('response_payload') or {}
    choices = native.get('choices') or []
    if len(choices) != 1 or choices[0].get('finish_reason') != 'stop' or choices[0].get('message', {}).get('tool_calls'):
        errors.append('Only one explicitly stopped native content choice without tools is usable')
    io._write(RUN / f'CALL_LEDGER_{n:03}.json', dict(ordinal=n, reported_tokens=bill, errors=errors,
        request_binding=io._binding(qp), response_binding=io._binding(rp)))
    _save_state('received_native_result' if not errors else 'stopped_native_evidence_error', pending_call=None, errors=errors)
    if errors or bill is None or body is None:
        raise RuntimeError('原生证据未通过，已保存停止：' + '; '.join(errors))
    return body, io._binding(rp)


def execute_stage(stage):
    with io._lock(RUN / '.execution.lock'):
        b = _verify()
        args = (b['source']['text'], b['accepted_full_draft'])
        if stage == 'writer':
            payload = contracts.build_natural_director_payload(*args, brief=b['brief'], max_tokens=6000)
            payload['messages'][0]['content'] = PREFIX + payload['messages'][0]['content']
            text, receipt = _dispatch(1, payload)
            _text(RUN / 'S01_NATURAL_DIRECTOR.md', text)
            return _save_state('s01_model_candidate_saved', natural_receipt=receipt)
        natural = (RUN / 'S01_NATURAL_DIRECTOR.md').read_text(encoding='utf-8')
        assert natural == _known(1)[0], '自然稿已与原MiniMax正文不同，停止'
        if stage == 'extract':
            payload = contracts.build_extract_review_payload(*args, natural, brief=b['brief'], max_tokens=6000)
            payload['messages'][0]['content'] = PREFIX + payload['messages'][0]['content']
            text, receipt = _dispatch(2, payload)
            materials = json.loads(payload['messages'][-1]['content'])
            value = contracts.parse_extract_review(text, source_binding=b['source']['binding_id'],
                draft_binding=b['draft_binding'], materials=materials, native_response_ref=receipt['sha256'])
            io._write(RUN / 'EXTRACT_REVIEW.json', value)
            if value['verdict'] != 'pass':
                return _save_state('stopped_extract_revise', summary=value['native']['summary'])
            assert len(value['segments']) == 1 and value['segments'][0]['segment_id'] == 'S01'
            requests = contracts.compile_video_requests(value)
            io._write(RUN / 'VIDEO_REQUESTS_PREVIEW.json', requests)
            _text(RUN / 'S01.PROMPT.txt', value['segments'][0]['prompt'])
            return _save_state('s01_extract_pass_final_review_pending')
        if stage != 'final':
            raise ValueError('未知阶段')
        extract = io._read(RUN / 'EXTRACT_REVIEW.json')
        raw, receipt, original_request = _known(2)
        original_materials = json.loads(original_request['messages'][-1]['content'])
        assert original_materials['natural_director_text'] == natural
        assert extract == contracts.parse_extract_review(raw, source_binding=b['source']['binding_id'],
            draft_binding=b['draft_binding'], materials=original_materials, native_response_ref=receipt['sha256'])
        assert len(extract['segments']) == 1 and extract['segments'][0]['segment_id'] == 'S01'
        payload = contracts.build_final_review_payload(*args, natural, extract, brief=b['brief'], max_tokens=6000)
        payload['messages'][0]['content'] = PREFIX + payload['messages'][0]['content']
        text, receipt = _dispatch(3, payload)
        materials = json.loads(payload['messages'][-1]['content'])
        value = contracts.parse_final_review(text, source_binding=b['source']['binding_id'],
            draft_binding=b['draft_binding'], materials=materials, native_response_ref=receipt['sha256'])
        io._write(RUN / 'FINAL_REVIEW.json', value)
        return _save_state('s01_machine_text_reviewed_not_video_generated' if value['verdict'] == 'pass'
            else 'stopped_final_revise', summary=value['native']['summary'])


if __name__ == '__main__':
    try:
        stage = sys.argv[1]
        result = prepare() if stage == 'prepare' else execute_stage(stage)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # Preserve errors locally, without exposing credentials or whole request exceptions.
        if RUN.exists():
            io._write(RUN / f'ERROR_{len(list(RUN.glob("ERROR_*.json"))) + 1:03}.json',
                dict(type=type(exc).__name__, detail=str(exc), automatic_retry=False))
        print(json.dumps(dict(status='stopped', type=type(exc).__name__, detail=str(exc)), ensure_ascii=False))
        raise SystemExit(1)
