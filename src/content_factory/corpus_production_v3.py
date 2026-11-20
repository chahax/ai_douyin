"""Extractive local corpus preparation followed by explicitly scoped cloud creation.

Old runs and models are never resumed through this coordinator. Local extraction
keeps original passages; cloud writers receive a selected event's full source.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import threading

from src.platform_adapter.fanqie_book_corpus import atomic
from .corpus_screenplay_v1 import read, freeze, digest, cumulative_history, dialogue_stats
from .corpus_local_analysis_v2 import preflight, LocalAnalysisClient
from .corpus_parallel_calls_v2 import ParallelCalls
from .corpus_analysis_parallel_v2 import _phase, AnalysisStopped
from .natural_director_role_clients_v10 import NaturalDirectorRoleClients
from .visual_storytelling_v1 import profile


VERSION = 'corpus_production/v3-extractive'


def _cloud_routes():
    from .creative_workflow_roles import role_config
    return {role: {'provider': role_config(role).provider, 'model': role_config(role).model,
                   'base_url': role_config(role).base_url.rstrip('/')}
            for role in ('writer', 'director')}


class PinnedCloudClient:
    def __init__(self, expected):
        self.expected = expected
        self.client = NaturalDirectorRoleClients()

    def call(self, role, messages, **kwargs):
        if _cloud_routes() != self.expected:
            raise ValueError('cloud_provider_or_model_changed')
        return self.client.call(role, messages, **kwargs)


def _source(manifest_path):
    manifest = read(manifest_path)
    if manifest.get('status') != 'accessible_catalogue_complete':
        raise ValueError('all_accessible_acquisition_required')
    chapters = []
    for item in manifest['chapters']:
        chapter = read(item['path'])
        if (chapter['book_id'] != manifest['book_id'] or chapter['sha256'] != item['sha256']
                or hashlib.sha256(chapter['text'].encode()).hexdigest() != item['sha256']):
            raise ValueError('source_changed')
        chapters.append(chapter)
    if not chapters or len({c['index'] for c in chapters}) != len(chapters):
        raise ValueError('source_chapters_invalid')
    return {'manifest': manifest, 'chapters': sorted(chapters, key=lambda c: c['index'])}


def prepare(manifest_path, run, *, user_statement, previous_status, local_route=None,
            workers=2, group_chars=10000, target_seconds=90, cloud_call_limit=24):
    from . import corpus_materials_v3 as materials
    run = Path(run).resolve()
    if run.exists():
        raise ValueError('existing_run_must_not_be_reprepared')
    if not isinstance(user_statement, str) or not user_statement.strip():
        raise ValueError('current_user_scope_required')
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers_out_of_range')
    if type(cloud_call_limit) is not int or not 1 <= cloud_call_limit <= 24:
        raise ValueError('cloud_call_limit_out_of_range')
    source = _source(manifest_path)
    history = cumulative_history(previous_status, read(previous_status))
    route = preflight(local_route or {'provider': 'ollama', 'model': 'qwen3.5:9b-q4_K_M',
                                     'endpoint': 'http://127.0.0.1:11435', 'context': 65536,
                                     'max_tokens': 8192})
    groups = materials.plan_groups(source['chapters'], max_chars=group_chars)
    for group in groups:
        payload = materials.group_payload(source['chapters'], group, source['manifest']['book_name'])
        payload['output_schema'] = materials.group_schema(group, payload)
        capacity = len(materials.CLASSIFY_PROMPT.encode()) + len(json.dumps(payload, ensure_ascii=False).encode()) + route['max_tokens'] + 1024
        if capacity > route['context']:
            raise ValueError('local_group_input_exceeds_frozen_context:' + group['id'])
    cloud_models = _cloud_routes()
    authorization = {'user_statement': user_statement,
        'book_id': source['manifest']['book_id'], 'book_name': source['manifest']['book_name'],
        'source_chapters': [c['index'] for c in source['chapters']], 'source_sha256': digest(source),
        'destinations': cloud_models, 'cloud_call_limit': cloud_call_limit,
        'cloud_token_limit': 2500000, 'media_authorized': False,
        'source_material_sent': f"全部{len(source['chapters'])}章派生分类索引及精选原文；选段及相邻章节完整正文；新设定与剧本",
        'stages': {'local': 'Qwen仅原文分类与选择', 'director': '世界框架、选段、来源审核、设计审核、事实与全文计时审核',
                   'writer': 'MiniMax自然视觉设定、完整剧本及必要修订'},
        'supersedes_old_experiment': False, 'old_approval_records_untouched': True}
    plan = {'version': VERSION, 'materials_version': materials.VERSION,
            'source_sha256': digest(source), 'user_statement': user_statement,
            'source_chapters': [c['index'] for c in source['chapters']], 'groups': groups,
            'workers': workers, 'local_route': route, 'cloud_models': cloud_models,
            'local_call_limit': 2 * len(groups), 'local_token_limit': 1500000,
            'cloud_call_limit': cloud_call_limit, 'cloud_token_limit': 2500000,
            'inherited_consumption': history, 'previous_status_path': str(Path(previous_status).resolve()),
            'authorization_sha256': digest(authorization),
            'previous_status_sha256': digest(read(previous_status)), 'target_seconds': target_seconds,
            'visual_storytelling': profile(), 'media_authorized': False,
            'cloud_scope': '原书全部已获取章节的分类索引、精选原文及选段完整章节；DeepSeek整理/审核，MiniMax视觉设定/自然剧本。',
            'automatic_transport_retry': False}
    run.mkdir(parents=True)
    freeze(run / 'SOURCE.json', source)
    freeze(run / 'PLAN.json', plan)
    freeze(run / 'AUTHORIZATION.json', authorization)
    for phase, max_calls, tokens, selected_route in (
            ('local', plan['local_call_limit'], plan['local_token_limit'], route),
            ('cloud', cloud_call_limit, plan['cloud_token_limit'],
             {'provider': 'role_pinned', 'models': cloud_models, 'max_tokens': 16000,
              'stages': authorization['stages']})):
        phase_plan = {'source_sha256': plan['source_sha256'], 'new_call_limit': max_calls,
                      'new_token_limit': tokens, 'analysis_route': selected_route,
                      'inherited_consumption': history, 'parent_plan_sha256': digest(plan)}
        freeze(run / phase / 'PLAN.json', phase_plan)
        atomic(run / phase / 'STATE.json', {'status': 'prepared', 'stage': phase,
            'calls_started': 0, 'reported_tokens': 0, 'pending': None, 'pending_calls': {},
            'plan_sha256': digest(phase_plan)})
    atomic(run / 'STATE.json', {'status': 'prepared', 'plan_sha256': digest(plan),
                               'pending': None, 'calls_started': 0, 'reported_tokens': 0})
    return plan


def _open(run):
    from . import corpus_materials_v3 as materials
    run = Path(run).resolve()
    plan, source, state = read(run / 'PLAN.json'), read(run / 'SOURCE.json'), read(run / 'STATE.json')
    if (plan.get('version') != VERSION or plan['materials_version'] != materials.VERSION
            or digest(plan) != state['plan_sha256'] or digest(source) != plan['source_sha256']
            or digest(read(run / 'AUTHORIZATION.json')) != plan['authorization_sha256']):
        raise ValueError('frozen_production_plan_or_source_changed')
    for phase in ('local', 'cloud'):
        phase_plan, phase_state = read(run / phase / 'PLAN.json'), read(run / phase / 'STATE.json')
        if (phase_plan['parent_plan_sha256'] != digest(plan)
                or phase_state['plan_sha256'] != digest(phase_plan)):
            raise ValueError('frozen_phase_plan_changed')
    return run, plan, source, state


def _save_parent(run, plan, state, status, **extra):
    phases = {p: read(run / p / 'STATE.json') for p in ('local', 'cloud')}
    pending = [item for s in phases.values() for item in (s.get('pending') or [])]
    count = sum(s['calls_started'] for s in phases.values())
    tokens = sum(s['reported_tokens'] for s in phases.values())
    state.update(status=status, calls_started=count, reported_tokens=tokens, pending=pending or None,
        total_calls_with_history=plan['inherited_consumption']['calls_started'] + count,
        total_tokens_with_history=plan['inherited_consumption']['reported_tokens'] + tokens, **extra)
    atomic(run / 'STATE.json', state)
    return state


def _calls(run, phase, client):
    folder = run / phase
    return ParallelCalls(folder, read(folder / 'PLAN.json'), read(folder / 'STATE.json'),
                         client, read, freeze, digest)


def _frozen(path, value):
    if path.exists():
        if digest(read(path)) != digest(value):
            raise ValueError('frozen_production_artifact_changed:' + path.name)
    else:
        freeze(path, value)


def prepare_cloud(run):
    """Freeze the expanded evidence and implementation before any external call."""
    from .corpus_evidence_pack_v3 import expand_core
    from . import corpus_production_contract_v3 as contract
    from .screenplay_revision_v4 import policy as revision_policy
    run, plan, source, state = _open(run)
    if state['status'] != 'materials_ready':
        raise ValueError('all_local_materials_required_before_cloud')
    binding, index, base_pack = (read(run / name) for name in
        ('MATERIALS_BINDING.json', 'MATERIALS_INDEX.json', 'CLOUD_SOURCE_PACK.json'))
    if (binding['source_sha256'] != plan['source_sha256'] or binding['index_sha256'] != digest(index)
            or binding['cloud_pack_sha256'] != digest(base_pack)):
        raise ValueError('source_materials_binding_changed')
    expansion_args = {}
    if binding.get('core_adoption_sha256'):
        adoption = read(run / 'CORE_MATERIAL_ADOPTION.json')
        if digest(adoption) != binding['core_adoption_sha256']:
            raise ValueError('core_material_adoption_changed')
        expansion_args = {
            'original_priority_ids': [pid for group in adoption['groups']
                                      for pid in group['original_priority_passage_ids']],
            'priority_provenance': {'adoption_sha256': digest(adoption),
                                    'policy_version': adoption['policy_version'],
                                    'source_sha256': plan['source_sha256']}}
    pack, metadata = expand_core(index, base_pack, **expansion_args)
    module_names = ('corpus_production_v3.py', 'corpus_production_contract_v3.py',
        'corpus_evidence_pack_v3.py', 'screenplay_revision_v4.py', 'screenplay_revision_v3.py',
        'screenplay_review_cycle_v2.py', 'corpus_parallel_calls_v2.py',
        'natural_director_role_clients_v10.py', 'creative_workflow_roles.py')
    pin = {'parent_plan_sha256': digest(plan), 'contract_version': getattr(contract, 'VERSION', None),
           'revision_policy': revision_policy(), 'source_files': {
               name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
               for name in module_names}}
    _frozen(run / 'CLOUD_IMPLEMENTATION_PIN.json', pin)
    _frozen(run / 'CLOUD_EVIDENCE_PACK.json', pack)
    _frozen(run / 'CLOUD_EVIDENCE_BINDING.json', {'parent_plan_sha256': digest(plan),
        'source_sha256': plan['source_sha256'], 'base_pack_sha256': digest(base_pack),
        'expanded_pack_sha256': digest(pack), 'implementation_sha256': digest(pin),
        'expansion': metadata})
    return pack


def adopt_core_materials(run):
    run = Path(run).resolve()
    lock = run / 'EXECUTION.lock'
    with lock.open('x') as handle:
        handle.write('local completed-classification adoption only')
    try:
        return _adopt_core_materials(run)
    finally:
        lock.unlink()


def _adopt_core_materials(run):
    """Use completed classifications under the explicit all-core evidence policy.

    This makes no provider call and does not change the original failed local
    ledger. Priority selection errors cannot erase correctly classified source.
    """
    from . import corpus_materials_v3 as materials
    from .corpus_evidence_pack_v3 import validate_core_classification, CLASSIFICATION_POLICY_VERSION
    run, plan, source, state = _open(run)
    if state['status'] == 'materials_ready' and (run / 'CORE_MATERIAL_ADOPTION.json').exists():
        return state
    local = read(run / 'local' / 'STATE.json')
    cloud = read(run / 'cloud' / 'STATE.json')
    if (state['status'] != 'needs_attention' or local.get('pending') or local.get('pending_calls')
            or local['status'] != 'needs_attention' or cloud.get('pending') or cloud['calls_started']):
        raise ValueError('completed_local_classifications_required_for_core_adoption')
    phase_plan = read(run / 'local' / 'PLAN.json')
    receipts = {}
    for claim_path in sorted((run / 'local').glob('CALL_*.json')):
        claim = read(claim_path)
        ordinal = int(claim_path.stem.split('_')[1])
        response_name = f'RESPONSE_{ordinal:03d}.json'
        response = read(run / 'local' / response_name)
        meta, native = response['metadata'], response['response_payload']
        if (meta.get('finish_reason') != 'stop' or native.get('done') is not True
                or native.get('done_reason') != 'stop' or native.get('model') != plan['local_route']['model']
                or any(type(meta.get(k)) is not int or meta[k] < 0 for k in
                       ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                or meta['prompt_tokens'] != native.get('prompt_eval_count')
                or meta['completion_tokens'] != native.get('eval_count')
                or meta['total_tokens'] != meta['prompt_tokens'] + meta['completion_tokens']):
            raise ValueError('native_completion_required_for_core_adoption')
        request = {k: v for k, v in claim.items() if k not in ('reserved_tokens', 'admitted_at')}
        call_binding = read(run / 'local' / 'CALL_BINDINGS' / (claim['name'] + '.json'))
        artifact = read(run / 'local' / (claim['name'] + '.json'))
        if (call_binding['request_sha256'] != digest(request)
                or call_binding['artifact_sha256'] != digest(artifact)
                or call_binding['response_file'] != response_name
                or json.loads(response['text']) != artifact
                or native.get('message', {}).get('content') != response['text']
                or claim['source_sha256'] != plan['source_sha256']
                or claim['analysis_route'] != phase_plan['analysis_route']
                or claim['role'] != 'director' or claim['json_output'] is not True
                or claim['messages'][0]['content'] != materials.CLASSIFY_PROMPT):
            raise ValueError('original_classification_receipt_changed')
        if claim['name'] in receipts:
            raise ValueError('duplicate_classification_receipt')
        receipts[claim['name']] = (artifact, claim, response)
    if (len(receipts) != local['calls_started'] or
            sum(v[2]['metadata']['total_tokens'] for v in receipts.values()) != local['reported_tokens']):
        raise ValueError('classification_usage_not_reconciled')
    validated, derived_groups, audits = [], [], []
    for group in plan['groups']:
        directory = run / 'local' / 'groups' / group['id']
        payload = materials.group_payload(source['chapters'], group, source['manifest']['book_name'])
        schema = materials.group_schema(group, payload)
        expected = {'name': 'MATERIALS_' + group['id'], 'prompt_sha256': materials.digest(materials.CLASSIFY_PROMPT),
                    'payload_sha256': materials.digest(payload), 'schema_sha256': materials.digest(schema), 'upstream': {}}
        if read(directory / 'BINDING.json') != expected:
            raise ValueError('original_group_binding_changed')
        accepted = read(directory / 'ACCEPTED.json') if (directory / 'ACCEPTED.json').exists() else None
        output_name = accepted['output_file'] if accepted else 'REPAIR.json'
        raw = read(directory / output_name)
        call_name = expected['name'] + ('_REPAIR' if output_name == 'REPAIR.json' else '')
        if call_name not in receipts or raw != receipts[call_name][0]:
            raise ValueError('classification_group_receipt_missing')
        request_payload = json.loads(receipts[call_name][1]['messages'][1]['content'])
        if any(request_payload.get(k) != v for k, v in {**payload, 'output_schema': schema}.items()):
            raise ValueError('classification_group_request_changed')
        if accepted and (accepted['binding_sha256'] != materials.digest(expected) or accepted['output_sha256'] != materials.digest(raw)
                or accepted['validated_sha256'] != materials.digest(materials.validate(raw, source['chapters'], group))):
            raise ValueError('original_accepted_group_changed')
        value, derived, audit = validate_core_classification(raw, source['chapters'], group)
        validated.append(value)
        derived_groups.append(derived)
        audits.append({**audit, 'group_id': group['id'], 'original_call_name': call_name,
                       'original_group_state': read(directory / 'STATE.json')})
    index = materials.materials_index(validated, source['chapters'], groups=derived_groups,
                                      book_name=source['manifest']['book_name'])
    pack = materials.cloud_input(index)
    adoption = {'policy_version': CLASSIFICATION_POLICY_VERSION, 'parent_plan_sha256': digest(plan),
                'source_sha256': plan['source_sha256'], 'old_root_state': deepcopy(state),
                'old_local_state': local, 'groups': audits, 'new_model_calls': 0,
                'original_failures_unchanged': True,
                'effective_selection': 'deterministic_all_classified_core_original_passages',
                'materials_index_sha256': digest(index), 'cloud_pack_sha256': digest(pack)}
    _frozen(run / 'CORE_MATERIAL_ADOPTION.json', adoption)
    _frozen(run / 'MATERIALS_INDEX.json', index)
    _frozen(run / 'CLOUD_SOURCE_PACK.json', pack)
    _frozen(run / 'MATERIALS_BINDING.json', {'source_sha256': plan['source_sha256'],
        'index_sha256': digest(index), 'cloud_pack_sha256': digest(pack),
        'core_adoption_sha256': digest(adoption)})
    return _save_parent(run, plan, state, 'materials_ready', source_chapters=len(source['chapters']),
        supplemental_material_policy=CLASSIFICATION_POLICY_VERSION,
        original_local_outcome='needs_attention', content_acceptance=False,
        completed_groups=[g['id'] for g in plan['groups']])


def execute_local(run, client=None):
    from . import corpus_materials_v3 as materials
    run, plan, source, state = _open(run)
    if state['status'] in {'materials_ready', 'reviewed_draft_ready'}:
        return state
    phase_state = read(run / 'local' / 'STATE.json')
    if phase_state.get('pending') or phase_state['status'] in {'needs_attention', 'outcome_unknown'}:
        return state
    client = client or LocalAnalysisClient(plan['local_route'])
    lock = run / 'EXECUTION.lock'
    with lock.open('x') as f:
        f.write('single production coordinator')
    call = _calls(run, 'local', client)
    stopped = threading.Event()
    try:
        def one(group):
            payload = materials.group_payload(source['chapters'], group, source['manifest']['book_name'])
            return _phase(run / 'local', run / 'local' / 'groups' / group['id'],
                          'MATERIALS_' + group['id'], 'director', materials.CLASSIFY_PROMPT,
                          payload, materials.group_schema(group, payload),
                          lambda value: materials.validate(value, source['chapters'], group),
                          call, stop_event=stopped)
        values, failures = {}, []
        for group in plan['groups']:
            if (run / 'local' / 'groups' / group['id'] / 'ACCEPTED.json').exists():
                values[group['id']] = one(group)
        queue = iter([g for g in plan['groups'] if g['id'] not in values])
        with ThreadPoolExecutor(max_workers=plan['workers'], thread_name_prefix='source-materials') as pool:
            active = {}
            def fill():
                while len(active) < plan['workers'] and not stopped.is_set():
                    group = next(queue, None)
                    if group is None:
                        break
                    active[pool.submit(one, group)] = group
            fill()
            while active:
                finished, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in finished:
                    group = active.pop(future)
                    try:
                        values[group['id']] = future.result()
                    except Exception as exc:
                        stopped.set()
                        failures.append({'group_id': group['id'], 'error': type(exc).__name__ + ':' + str(exc)[:300]})
                # On Windows an open read handle can block the ledger's atomic
                # replace. Snapshot the shared ledger under its writer lock.
                with call.lock:
                    _save_parent(run, plan, state, 'classifying', completed_groups=sorted(values), failures=failures)
                fill()
        if failures:
            raise AnalysisStopped('local_materials_incomplete')
        analyses = [values[group['id']] for group in plan['groups']]
        index = materials.materials_index(analyses, source['chapters'], groups=plan['groups'],
                                         book_name=source['manifest']['book_name'])
        pack = materials.cloud_input(index)
        _frozen(run / 'MATERIALS_INDEX.json', index)
        _frozen(run / 'CLOUD_SOURCE_PACK.json', pack)
        _frozen(run / 'MATERIALS_BINDING.json', {'source_sha256': plan['source_sha256'],
            'index_sha256': digest(index), 'cloud_pack_sha256': digest(pack)})
        call.state['status'] = 'completed'
        call.save()
        return _save_parent(run, plan, state, 'materials_ready', completed_groups=sorted(values),
                            source_chapters=len(source['chapters']), content_acceptance=False)
    except Exception as exc:
        if not call.state.get('pending'):
            call.state.update(status='needs_attention', reason=type(exc).__name__ + ':' + str(exc))
            call.save()
        _save_parent(run, plan, state, 'needs_attention', reason=type(exc).__name__ + ':' + str(exc))
        raise
    finally:
        lock.unlink()


def execute_cloud(run, client=None):
    """Production text only; the current scope is frozen in AUTHORIZATION.json."""
    from . import corpus_production_contract_v3 as contract
    from .screenplay_revision_v4 import run_cycle, policy as revision_policy
    run, plan, source, state = _open(run)
    if state['status'] == 'reviewed_draft_ready':
        return state
    if (run / 'APPROVAL_REQUIRED.json').exists():
        raise ValueError('cloud_execution_requires_approval_disposition')
    if state['status'] != 'materials_ready':
        raise ValueError('all_local_materials_required_before_cloud')
    phase_state = read(run / 'cloud' / 'STATE.json')
    if phase_state.get('pending') or phase_state['status'] in {'needs_attention', 'outcome_unknown'}:
        return state
    pack = prepare_cloud(run)
    client = client or PinnedCloudClient(plan['cloud_models'])
    lock = run / 'EXECUTION.lock'
    with lock.open('x') as f:
        f.write('single production coordinator')
    call = _calls(run, 'cloud', client)
    try:
        # Cloud stages are implemented against the contract in a separate module
        # so the local source preparation cannot accidentally invoke a writer.
        result = contract.run_production(call, source, pack, plan,
            revision_cycle=run_cycle, revision_policy=revision_policy(), stats=dialogue_stats,
            record=lambda name, value: _frozen(run / 'cloud' / (name + '.json'), value),
            remaining_calls=lambda: plan['cloud_call_limit'] - call.state['calls_started'])
        draft, review_binding = result['draft'], result['binding']
        target = run / '剧本_新版全章分类生产.md'
        if target.exists() and target.read_text(encoding='utf-8') != draft:
            raise ValueError('delivered_draft_changed')
        if not target.exists():
            with target.open('x', encoding='utf-8') as f:
                f.write(draft)
        _frozen(run / 'REVIEW_BINDING.json', review_binding)
        call.state['status'] = 'completed'
        call.save()
        return _save_parent(run, plan, state, 'reviewed_draft_ready',
                            selected_chapters=result['selected_chapters'], media_generated=False,
                            content_acceptance='machine_review_passed_awaiting_independent_review')
    except Exception as exc:
        if not call.state.get('pending'):
            call.state.update(status='needs_attention', reason=type(exc).__name__ + ':' + str(exc))
            call.save()
        _save_parent(run, plan, state, 'needs_attention', reason=type(exc).__name__ + ':' + str(exc))
        raise
    finally:
        lock.unlink()
