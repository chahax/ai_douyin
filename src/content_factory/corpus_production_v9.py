"""Light chapter materials and episode-state production with preserved native receipts.

This coordinator creates new runs only. It never adopts old failed classifications
or changes a frozen v3 plan. MiniMax-M3.1-Flash classifies and writes; Qwen independently reviews the episode
state snapshot, and DeepSeek only performs final content/timing reviews.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import threading

from src.platform_adapter.fanqie_book_corpus import atomic
from .corpus_screenplay_v1 import read, freeze, digest, cumulative_history, dialogue_stats
from .corpus_local_analysis_v2 import preflight, LocalAnalysisClient, LocalInputRejected
from .corpus_parallel_calls_v2 import ParallelCalls
from .corpus_analysis_parallel_v2 import _phase, AnalysisStopped
from .corpus_production_v3 import _source, _cloud_routes as _legacy_cloud_routes, _frozen
from .minimax_production_client_v1 import MiniMaxProductionClient, MODEL, REQUEST_POLICY
from .natural_director_role_clients_v10 import NaturalDirectorRoleClients
from .visual_storytelling_v1 import profile
from . import corpus_temporal_policy_v1 as temporal
from . import corpus_reference_view_v1 as references
from .corpus_scope_v9 import implementation_pin, validate_implementation_pin, require_cloud_authorization

VERSION = 'corpus_production/v9-temporal-source-addresses'
STAGES = {
    'chapter_materials': 'writer', 'material_review': 'local',
    'framework': 'writer', 'framework_review': 'local',
    'episode_snapshot': 'writer', 'snapshot_review': 'local',
    'visual_design': 'writer', 'design_review': 'local',
    'fact_contract': 'writer', 'screenplay': 'writer',
    'root_cause': 'local', 'final_content': 'director', 'final_timing': 'director',
}


def _cloud_routes():
    routes = deepcopy(_legacy_cloud_routes())
    if routes['writer']['provider'] != 'minimax':
        raise LocalInputRejected('minimax_provider_required')
    routes['writer']['model'] = MODEL
    return routes


class StageClients:
    """Pinned new-task MiniMax route; legacy frozen runs retain their own clients."""
    def __init__(self, local_route, cloud_models, *, local_client=None,
                 cloud_client=None, minimax_client=None):
        self.local_route, self.cloud_models = deepcopy(local_route), deepcopy(cloud_models)
        self.local_client, self.cloud_client = local_client, cloud_client
        self.minimax_client = minimax_client

    def call(self, role, messages, **kwargs):
        if role == 'local':
            if kwargs.get('response_format') != {'type': 'json_object'}:
                raise LocalInputRejected('local_stage_requires_json')
            options = {**kwargs, 'max_tokens': self.local_route['max_tokens']}
            if self.local_client is None:
                try:
                    self.local_client = LocalAnalysisClient(self.local_route)
                except Exception as exc:
                    raise LocalInputRejected('local_preflight_failed_before_inference:' + type(exc).__name__) from exc
            return self.local_client.call('director', messages, **options)
        if role not in ('writer', 'director'):
            raise LocalInputRejected('unknown_production_role')
        if _cloud_routes() != self.cloud_models:
            raise LocalInputRejected('cloud_provider_or_model_changed')
        if role == 'writer':
            if self.minimax_client is None:
                self.minimax_client = MiniMaxProductionClient()
            return self.minimax_client.call(role, messages, **kwargs)
        if self.cloud_client is None:
            self.cloud_client = NaturalDirectorRoleClients()
        return self.cloud_client.call(role, messages, **kwargs)


def _capacity(prompt, payload, route):
    estimate = len(prompt.encode('utf-8')) + len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    if estimate + route['max_tokens'] + 1024 > route['context']:
        raise LocalInputRejected('whole_chapter_exceeds_context_no_truncation')


def prepare(manifest_path, run, *, user_statement, previous_status, local_route=None,
            workers=2, context_neighbors=1, target_seconds=90, production_call_limit=None,
            root_repair_limit=2, materials_call_limit=None):
    from . import corpus_chapter_materials_v6 as chapters_api
    run = Path(run).resolve()
    if run.exists():
        raise ValueError('existing_run_must_not_be_reprepared')
    if not isinstance(user_statement, str) or not user_statement.strip():
        raise ValueError('current_user_scope_required')
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers_out_of_range')
    if type(target_seconds) not in (int, float) or not 0 < target_seconds <= 600:
        raise ValueError('target_seconds_invalid')
    if type(root_repair_limit) is not int or not 0 <= root_repair_limit <= 2:
        raise ValueError('root_repair_limit_invalid')
    source = _source(manifest_path)
    history = cumulative_history(previous_status, read(previous_status))
    route = preflight(local_route or {'provider': 'ollama', 'model': 'qwen3.5:9b-q4_K_M',
                                     'endpoint': 'http://127.0.0.1:11435', 'context': 65536,
                                     'max_tokens': 8192})
    plans = chapters_api.plan_chapters(source['chapters'], context_neighbors=context_neighbors)
    if materials_call_limit is None:
        materials_call_limit = 2 * len(plans)
    if type(materials_call_limit) is not int or not len(plans) <= materials_call_limit <= 2 * len(plans):
        raise ValueError('materials_call_limit_out_of_range')
    materials_route = {'provider': 'minimax', 'model': MODEL, 'context': 131072,
                       'max_tokens': 16384, 'request_policy': deepcopy(REQUEST_POLICY)}
    for chapter_plan in plans:
        payload = references.chapter_payload(source['chapters'], chapter_plan, source['manifest']['book_name'])
        _capacity(temporal.extraction_prompt(chapters_api.EXTRACT_PROMPT),
                  {**payload, 'output_schema': temporal.extraction_schema(chapters_api.chapter_schema(chapter_plan, payload))}, materials_route)
    if production_call_limit is None:
        # Structural upper bound for bounded per-chapter checks plus two root
        # repairs. This is a new-run plan, not an extension of any old budget.
        production_call_limit = 6 * len(plans) + 64
    if type(production_call_limit) is not int or production_call_limit < 1:
        raise ValueError('production_call_limit_invalid')
    models = _cloud_routes()
    scope = {'user_statement': user_statement, 'book_id': source['manifest']['book_id'],
             'source_sha256': digest(source), 'source_chapters': [c['index'] for c in source['chapters']],
             'destinations': models, 'stages': STAGES,
             'source_material': '完整逐章正文供MiniMax-M3.1-Flash分类，材料候选供本机Qwen复核；本集状态快照、选段及必要原文证据供设计/编剧和DeepSeek最终内容与时长审核。',
             'media_authorized': False, 'actual_provider_billing': 'not_verified',
             'prior_approval_records_superseded': False}
    plan = {'version': VERSION, 'materials_version': chapters_api.VERSION,
            'local_implementation_pin': implementation_pin(),
            'source_sha256': digest(source), 'source_chapters': scope['source_chapters'],
            'chapters': plans, 'workers': workers, 'local_route': route, 'cloud_models': models,
            'stage_routes': STAGES, 'materials_route': materials_route,
            'minimax_request_policy': deepcopy(REQUEST_POLICY),
            'reference_view_version': references.VERSION, 'temporal_policy_version': temporal.VERSION, 'temporal_policy_sha256': digest(temporal.RULES), 'target_seconds': target_seconds, 'root_repair_limit': root_repair_limit,
            'materials_call_limit': materials_call_limit, 'production_call_limit': production_call_limit,
            'inherited_consumption': history, 'previous_status_path': str(Path(previous_status).resolve()),
            'previous_status_sha256': digest(read(previous_status)), 'authorization_sha256': digest(scope),
            'visual_storytelling': profile(), 'automatic_transport_retry': False, 'media_authorized': False}
    run.mkdir(parents=True)
    freeze(run / 'SOURCE.json', source)
    freeze(run / 'PLAN.json', plan)
    freeze(run / 'AUTHORIZATION.json', scope)
    for phase, limit, selected in (
        ('materials', plan['materials_call_limit'], materials_route),
        ('cloud', production_call_limit, {'provider': 'stage_pinned', 'models': models,
                                         'local_route': route, 'stages': STAGES, 'max_tokens': 16384,
                                         'minimax_request_policy': deepcopy(REQUEST_POLICY)})):
        phase_plan = {'source_sha256': plan['source_sha256'], 'new_call_limit': limit,
                      'new_token_limit': max(1500000, limit * 100000), 'analysis_route': selected,
                      'inherited_consumption': history, 'parent_plan_sha256': digest(plan)}
        freeze(run / phase / 'PLAN.json', phase_plan)
        atomic(run / phase / 'STATE.json', {'status': 'prepared', 'stage': phase, 'calls_started': 0,
               'reported_tokens': 0, 'pending': None, 'pending_calls': {}, 'plan_sha256': digest(phase_plan)})
    atomic(run / 'STATE.json', {'status': 'prepared', 'plan_sha256': digest(plan),
                               'pending': None, 'calls_started': 0, 'reported_tokens': 0})
    return plan


def _open(run):
    from . import corpus_chapter_materials_v6 as chapters_api
    run = Path(run).resolve()
    plan, source, state = (read(run / name) for name in ('PLAN.json', 'SOURCE.json', 'STATE.json'))
    if (plan.get('version') != VERSION or plan['materials_version'] != chapters_api.VERSION
            or digest(plan) != state['plan_sha256'] or digest(source) != plan['source_sha256']
            or digest(read(run / 'AUTHORIZATION.json')) != plan['authorization_sha256']
            or plan['stage_routes'] != STAGES
            or plan.get('reference_view_version') != references.VERSION
            or plan.get('temporal_policy_version') != temporal.VERSION
            or plan.get('temporal_policy_sha256') != digest(temporal.RULES)):
        raise ValueError('frozen_production_plan_or_source_changed')
    validate_implementation_pin(plan.get('local_implementation_pin'))
    for phase in ('materials', 'cloud'):
        pp, ps = read(run / phase / 'PLAN.json'), read(run / phase / 'STATE.json')
        if pp['parent_plan_sha256'] != digest(plan) or ps['plan_sha256'] != digest(pp):
            raise ValueError('frozen_phase_plan_changed')
    return run, plan, source, state


def _save(run, plan, state, status, **extra):
    phases = [read(run / phase / 'STATE.json') for phase in ('materials', 'cloud')]
    count = sum(s['calls_started'] for s in phases)
    tokens = sum(s['reported_tokens'] for s in phases)
    pending = [p for s in phases for p in (s.get('pending') or [])]
    state.update(status=status, calls_started=count, reported_tokens=tokens, pending=pending or None,
                 total_calls_with_history=plan['inherited_consumption']['calls_started'] + count,
                 total_tokens_with_history=plan['inherited_consumption']['reported_tokens'] + tokens, **extra)
    atomic(run / 'STATE.json', state)
    return state


def _preserve_production_state(run, plan, state, downstream):
    if downstream.get('pending'):
        status = 'outcome_unknown' if downstream['status'] == 'outcome_unknown' else 'waiting_existing'
        return _save(run, plan, state, status, stage=downstream.get('stage'),
                     reason='original_production_request_has_no_consumed_result')
    if downstream['status'] in {'needs_attention', 'outcome_unknown'}:
        return _save(run, plan, state, downstream['status'], stage=downstream.get('stage'),
                     reason=downstream.get('reason') or state.get('reason') or 'production_requires_attention')
    return state


def _calls(run, phase, client):
    folder = run / phase
    return ParallelCalls(folder, read(folder / 'PLAN.json'), read(folder / 'STATE.json'),
                         client, read, freeze, digest)


def execute_materials(run, client=None):
    from . import corpus_chapter_materials_v6 as api
    run, plan, source, state = _open(run)
    downstream = read(run / 'cloud' / 'STATE.json')
    if (downstream.get('calls_started', 0) or downstream.get('pending')
            or downstream['status'] in {'needs_attention', 'outcome_unknown'}):
        # Once production starts, cached local completion cannot overwrite its
        # failure/unknown outcome with an earlier materials_ready status.
        return _preserve_production_state(run, plan, state, downstream)
    if state['status'] in {'materials_ready', 'reviewed_draft_ready'}:
        return state
    ps = read(run / 'materials' / 'STATE.json')
    if ps.get('pending') or ps['status'] in {'needs_attention', 'outcome_unknown'}:
        return _preserve_production_state(run, plan, state, ps)
    require_cloud_authorization(run, plan)
    client = client or StageClients(plan['local_route'], plan['cloud_models'])
    lock = run / 'EXECUTION.lock'
    with lock.open('x') as handle:
        handle.write('whole-chapter production coordinator')
    call = _calls(run, 'materials', client)
    stopped = threading.Event()
    try:
        def one(chapter_plan):
            payload = references.chapter_payload(source['chapters'], chapter_plan, source['manifest']['book_name'])
            return _phase(run / 'materials', run / 'materials' / 'chapters' / chapter_plan['id'],
                          'EXTRACT_MATERIALS_' + chapter_plan['id'], 'writer', temporal.extraction_prompt(api.EXTRACT_PROMPT),
                          payload, temporal.extraction_schema(api.chapter_schema(chapter_plan, payload)),
                          lambda value: references.validate(value, source['chapters'], chapter_plan),
                          call, stop_event=stopped)
        values, failures = {}, []
        for cp in plan['chapters']:
            if (run / 'materials' / 'chapters' / cp['id'] / 'ACCEPTED.json').exists():
                values[cp['id']] = one(cp)
        queue = iter([cp for cp in plan['chapters'] if cp['id'] not in values])
        with ThreadPoolExecutor(max_workers=plan['workers'], thread_name_prefix='whole-chapter') as pool:
            active = {}
            def fill():
                while len(active) < plan['workers'] and not stopped.is_set():
                    cp = next(queue, None)
                    if cp is None:
                        break
                    active[pool.submit(one, cp)] = cp
            fill()
            while active:
                finished, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in finished:
                    cp = active.pop(future)
                    try:
                        values[cp['id']] = future.result()
                    except Exception as exc:
                        stopped.set()
                        failures.append({'chapter_id': cp['id'], 'error': type(exc).__name__ + ':' + str(exc)[:300]})
                with call.lock:
                    _save(run, plan, state, 'extracting_materials', completed_chapters=sorted(values), failures=failures)
                fill()
        if failures:
            raise AnalysisStopped('whole_chapter_materials_incomplete')
        analyses = [values[cp['id']] for cp in plan['chapters']]
        index = api.facts_catalog(analyses, source['chapters'], plans=plan['chapters'], book_name=source['manifest']['book_name'])
        pack = api.cloud_input(index)
        for name, value in (('CHAPTER_MATERIALS.json', analyses), ('MATERIAL_CATALOG.json', index), ('CLOUD_SOURCE_PACK.json', pack)):
            _frozen(run / name, value)
        _frozen(run / 'MATERIALS_BINDING.json', {'source_sha256': plan['source_sha256'],
                'chapters_sha256': digest(analyses), 'index_sha256': digest(index), 'cloud_pack_sha256': digest(pack)})
        call.state['status'] = 'completed'
        call.save()
        return _save(run, plan, state, 'materials_ready', completed_chapters=sorted(values), content_acceptance=False)
    except Exception as exc:
        if not call.state.get('pending'):
            call.state.update(status='needs_attention', reason=type(exc).__name__ + ':' + str(exc))
            call.save()
        _preserve_production_state(run, plan, state, call.state)
        raise
    finally:
        lock.unlink()


def prepare_cloud(run):
    from . import corpus_production_contract_v6 as contract
    run, plan, source, state = _open(run)
    if state['status'] != 'materials_ready':
        raise ValueError('all_chapter_materials_required_before_production')
    binding, analyses, index, pack = (read(run / name) for name in
        ('MATERIALS_BINDING.json', 'CHAPTER_MATERIALS.json', 'MATERIAL_CATALOG.json', 'CLOUD_SOURCE_PACK.json'))
    if (binding['source_sha256'] != plan['source_sha256'] or binding['chapters_sha256'] != digest(analyses)
            or binding['index_sha256'] != digest(index) or binding['cloud_pack_sha256'] != digest(pack)):
        raise ValueError('source_materials_binding_changed')
    names = ('corpus_production_v9.py', 'corpus_scope_v9.py', 'corpus_reference_view_v1.py', 'corpus_temporal_policy_v1.py', 'minimax_production_client_v1.py', 'minimax_text_trial_client_v1.py', 'corpus_chapter_materials_v6.py', 'corpus_episode_state_v6.py',
             'corpus_production_contract_v6.py', 'corpus_production_v4.py',
             'corpus_chapters_v4.py', 'corpus_production_contract_v4.py',
             'corpus_production_v3.py', 'corpus_production_contract_v3.py', 'corpus_materials_v3.py',
             'corpus_analysis_parallel_v2.py', 'corpus_parallel_calls_v2.py', 'corpus_local_analysis_v2.py',
             'screenplay_revision_v4.py', 'screenplay_revision_v3.py', 'screenplay_review_cycle_v2.py',
             'natural_director_role_clients_v10.py', 'creative_workflow_roles.py')
    pin = {'parent_plan_sha256': digest(plan), 'contract_version': contract.VERSION,
           'source_files': {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in names}}
    _frozen(run / 'CLOUD_IMPLEMENTATION_PIN.json', pin)
    _frozen(run / 'CLOUD_EVIDENCE_BINDING.json', {'parent_plan_sha256': digest(plan),
            'source_sha256': plan['source_sha256'], 'expanded_pack_sha256': digest(pack), 'implementation_sha256': digest(pin)})
    return pack


def execute_cloud(run, client=None):
    from . import corpus_chapter_materials_v6 as api
    from . import corpus_production_contract_v6 as contract
    run, plan, source, state = _open(run)
    if state['status'] == 'reviewed_draft_ready':
        return state
    # A denial is an execution fact, not removable by switching pipeline versions.
    if (run / 'APPROVAL_REQUIRED.json').exists():
        raise ValueError('cloud_execution_requires_approval_disposition')
    ps = read(run / 'cloud' / 'STATE.json')
    if ps.get('pending') or ps['status'] in {'needs_attention', 'outcome_unknown'}:
        return _preserve_production_state(run, plan, state, ps)
    if state['status'] != 'materials_ready':
        raise ValueError('all_chapter_materials_required_before_production')
    require_cloud_authorization(run, plan)
    pack = prepare_cloud(run)
    client = client or StageClients(plan['local_route'], plan['cloud_models'])
    lock = run / 'EXECUTION.lock'
    with lock.open('x') as handle:
        handle.write('whole-chapter production coordinator')
    ledger = _calls(run, 'cloud', client)
    analyses = read(run / 'CHAPTER_MATERIALS.json')
    try:
        def call(name, role, prompt, payload, json_output=True):
            # The unchanged v6 content contract is routed to a different model for independent review.
            if name.startswith('MATERIAL_REVIEW_'):
                if role != 'writer':
                    raise ValueError('unexpected_material_review_contract_role')
                role = STAGES['material_review']
                prompt = temporal.review_prompt(prompt)
            elif not name.startswith('MATERIALS_REPAIR_'):
                prompt = temporal.downstream_prompt(prompt)
            if role == 'director' and not name.startswith(('FINAL_CONTENT_', 'FINAL_TIMING_')):
                raise ValueError('deepseek_reserved_for_final_review')
            if role == 'local':
                _capacity(prompt, payload, plan['local_route'])
            return ledger(name, role, prompt, payload, json_output)

        def repair_materials(chapter_index, issues, attempt):
            nonlocal analyses
            cp = next(p for p in plan['chapters'] if p['chapter_index'] == chapter_index)
            payload = {**references.chapter_payload(source['chapters'], cp, source['manifest']['book_name']),
                       'required_material_corrections': deepcopy(issues)}
            updated = _phase(run / 'cloud', run / 'cloud' / 'material_repairs' / f'{cp["id"]}_{attempt}',
                             f'MATERIALS_REPAIR_{cp["id"]}_{attempt}', 'writer', temporal.extraction_prompt(api.EXTRACT_PROMPT),
                             payload, temporal.extraction_schema(api.chapter_schema(cp, payload)),
                             lambda raw: references.validate(raw, source['chapters'], cp), call)
            analyses = [updated if item['chapter_index'] == chapter_index else item for item in analyses]
            index = api.facts_catalog(analyses, source['chapters'], plans=plan['chapters'], book_name=source['manifest']['book_name'])
            revised = api.cloud_input(index)
            _frozen(run / 'cloud' / f'MATERIAL_REVISION_{cp["id"]}_{attempt}.json',
                    {'chapter_index': chapter_index, 'issues': issues, 'chapter_materials': analyses, 'pack': revised})
            return {'pack': revised, 'chapter_materials': deepcopy(analyses)}

        result = contract.run_production(call, source, pack, plan, stats=dialogue_stats,
                  chapter_materials=analyses, repair_materials=repair_materials,
                  record=lambda name, value: _frozen(run / 'cloud' / (name + '.json'), value),
                  remaining_calls=lambda: plan['production_call_limit'] - ledger.state['calls_started'])
        draft = result['draft']
        target = run / '剧本_章节材料与本集状态.md'
        if target.exists() and target.read_text(encoding='utf-8') != draft:
            raise ValueError('delivered_draft_changed')
        if not target.exists():
            with target.open('x', encoding='utf-8') as stream:
                stream.write(draft)
        _frozen(run / 'REVIEW_BINDING.json', result['binding'])
        ledger.state['status'] = 'completed'
        ledger.save()
        return _save(run, plan, state, 'reviewed_draft_ready', selected_chapters=result['selected_chapters'],
                     media_generated=False, content_acceptance='machine_review_passed_awaiting_independent_review')
    except Exception as exc:
        if not ledger.state.get('pending'):
            ledger.state.update(status='needs_attention', reason=type(exc).__name__ + ':' + str(exc))
            ledger.save()
        _preserve_production_state(run, plan, state, ledger.state)
        raise
    finally:
        lock.unlink()


def execute_local(run, client=None):
    """Legacy command alias; v9's frozen materials route is explicitly cloud MiniMax."""
    return execute_materials(run, client)
