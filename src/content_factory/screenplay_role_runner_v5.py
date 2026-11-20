"""Opt-in durable role routing; separate from frozen production campaigns."""
import json
from pathlib import Path
import time
from types import SimpleNamespace
import urllib.request
from urllib.parse import urlsplit
from jsonschema import ValidationError

from .screenplay_roles_v5 import (VERSION, ROLES, SCHEMAS, digest, evidence_from, output_schema,
                                validate_stage, allocate, messages_for, repair_payload)
from src.platform_adapter.fanqie_book_corpus import atomic


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def freeze(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def local_endpoint(endpoint):
    url = urlsplit(endpoint)
    if (url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1')
            or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('loopback_endpoint_required')


def local_routes(model='qwen3.5:9b-q4_K_M', endpoint='http://127.0.0.1:11435'):
    return {role: {'provider': 'ollama', 'model': model, 'endpoint': endpoint,
                   'thinking': model.startswith('qwen3.5') and role in ('source_review', 'review'),
                   'max_tokens': 8192, 'temperature': .3, 'context': 32768, 'seed': 42}
            for role in ROLES}


def hybrid_routes():
    """Candidate routing recipe, not an empirically winning configuration."""
    routes = local_routes()
    for role in ('source_review', 'brief', 'review'):
        routes[role].update(provider='deepseek', model='deepseek-flash', endpoint='', thinking=False)
    routes['integrate'].update(provider='minimax', model='MiniMax-M3', endpoint='', thinking=False)
    return routes


def validate_routes(routes, cloud_authorized=False):
    if set(routes) != set(ROLES):
        raise ValueError('all_task_roles_require_routes')
    for role, route in routes.items():
        if set(route) != {'provider', 'model', 'endpoint', 'thinking', 'max_tokens', 'temperature', 'context', 'seed'}:
            raise ValueError('route_fields_invalid')
        if (not isinstance(route['model'], str) or not route['model'].strip()
                or type(route['thinking']) is not bool or type(route['max_tokens']) is not int
                or not 256 <= route['max_tokens'] <= 16000 or type(route['context']) is not int
                or not 8192 <= route['context'] <= 65536 or type(route['seed']) is not int
                or type(route['temperature']) not in (int, float) or not 0 <= route['temperature'] <= 1):
            raise ValueError('route_parameters_invalid')
        if route['provider'] == 'ollama':
            local_endpoint(route['endpoint'])
        elif route['provider'] in ('minimax', 'deepseek'):
            if not cloud_authorized:
                raise ValueError('cloud_scope_not_authorized')
            if route['endpoint'] or route['thinking']:
                raise ValueError('cloud_uses_verified_project_adapter')
            if (route['provider'] == 'minimax') != (role == 'integrate'):
                raise ValueError('provider_output_mode_not_supported')
        else:
            raise ValueError('unsupported_provider')


class RoleClient:
    def preflight(self, routes):
        pins = {}
        for role, route in routes.items():
            if route['provider'] == 'ollama':
                local_endpoint(route['endpoint'])
                with urllib.request.urlopen(route['endpoint'] + '/api/tags', timeout=10) as response:
                    tags = json.load(response)
                model = next((m for m in tags['models'] if m['name'] == route['model']), None)
                if not model or not model.get('digest'):
                    raise ValueError('local_model_not_installed:' + route['model'])
                pins[role] = {'model': route['model'], 'digest': model['digest']}
            else:
                from .creative_workflow_roles import role_config
                config = role_config('writer' if role == 'integrate' else 'director')
                if config.provider != route['provider'] or config.model != route['model']:
                    raise ValueError('project_provider_differs_from_frozen_route')
                pins[role] = {'model': config.model, 'provider': config.provider}
        return pins

    def call(self, role, route, messages):
        if route['provider'] == 'ollama':
            body = {'model': route['model'], 'messages': messages, 'stream': False, 'keep_alive': 0,
                    'options': {'temperature': route['temperature'], 'num_ctx': route['context'],
                                'num_predict': route['max_tokens'], 'seed': route['seed']}}
            if route['model'].startswith('qwen3.5'):
                body['think'] = route['thinking']
            elif route['thinking']:
                raise ValueError('thinking_mode_not_verified_for_model')
            if role in SCHEMAS:
                body['format'] = output_schema(role, json.loads(messages[-1]['content']))
            request = urllib.request.Request(route['endpoint'] + '/api/chat', data=json.dumps(body).encode(),
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=900) as response:
                native = json.load(response)
            return {'text': native.get('message', {}).get('content', ''), 'native': native,
                    'done': native.get('done') is True and native.get('done_reason') == 'stop',
                    'response_model': native.get('model'), 'input_tokens': native.get('prompt_eval_count'),
                    'output_tokens': native.get('eval_count')}
        from .natural_director_role_clients_v10 import NaturalDirectorRoleClients
        kwargs = {'max_tokens': route['max_tokens'], 'temperature': route['temperature'], 'thinking': 'disabled'}
        if role in SCHEMAS:
            kwargs['response_format'] = {'type': 'json_object'}
        result = NaturalDirectorRoleClients().call('writer' if role == 'integrate' else 'director', messages, **kwargs)
        return {'text': result.text, 'native': result.response_payload, 'done': True,
                'response_model': result.metadata['response_model'],
                'input_tokens': result.metadata['prompt_tokens'], 'output_tokens': result.metadata['completion_tokens']}


def prepare(run, chapters, episode_intent, routes, *, user_statement, target_seconds=90,
            max_calls=18, cloud_authorized=False, provenance=None, client=None):
    run = Path(run)
    if run.exists():
        raise ValueError('existing_run_not_reprepared')
    if not episode_intent.strip() or not user_statement.strip() or type(target_seconds) is not int or not 15 <= target_seconds <= 240:
        raise ValueError('explicit_episode_and_target_required')
    if type(max_calls) is not int or not 6 <= max_calls <= 24:
        raise ValueError('bounded_experiment_scope_required')
    validate_routes(routes, cloud_authorized)
    pins = (client or RoleClient()).preflight(routes)
    source = {'chapters': chapters, 'evidence': evidence_from(chapters), 'episode_intent': episode_intent,
              'target_seconds': target_seconds, 'provenance': provenance or {}}
    plan = {'version': VERSION, 'routes': routes, 'model_pins': pins, 'source_sha256': digest(source),
            'user_statement': user_statement, 'max_calls': max_calls, 'cloud_authorized': cloud_authorized,
            'protocol_repairs_per_stage': 1, 'semantic_revisions': 1, 'media_authorized': False,
            'production_default_changed': False}
    freeze(run / 'SOURCE.json', source); freeze(run / 'PLAN.json', plan)
    atomic(run / 'STATE.json', {'status': 'prepared', 'plan_sha256': digest(plan), 'pending': None,
                              'calls_started': 0, 'input_tokens': 0, 'output_tokens': 0, 'metrics': []})
    return plan


class Experiment:
    def __init__(self, run, client=None):
        self.run = Path(run); self.client = client or RoleClient()
        self.plan = read(self.run / 'PLAN.json'); self.source = read(self.run / 'SOURCE.json'); self.state = read(self.run / 'STATE.json')
        if digest(self.plan) != self.state['plan_sha256'] or digest(self.source) != self.plan['source_sha256']:
            raise ValueError('frozen_inputs_changed')
        validate_routes(self.plan['routes'], self.plan['cloud_authorized'])

    def save(self):
        atomic(self.run / 'STATE.json', self.state)

    def invoke(self, role, artifacts, repair=None):
        if self.state['pending']:
            raise ValueError('pending_original_call_not_replayed')
        if self.state['calls_started'] >= self.plan['max_calls']:
            raise ValueError('experiment_scope_exhausted')
        route = self.plan['routes'][role]
        number = self.state['calls_started'] + 1
        messages = messages_for(role, self.source, artifacts, repair)
        claim = {'number': number, 'role': role, 'route': route, 'messages': messages,
                 'messages_sha256': digest(messages), 'source_sha256': self.plan['source_sha256'],
                 'artifacts': artifacts, 'repair': repair, 'model_pin': self.plan['model_pins'][role]}
        claim['output_schema'] = output_schema(role, json.loads(messages[-1]['content']))
        freeze(self.run / f'CALL_{number:03d}.json', claim)
        self.state.update(status='running', pending=number, calls_started=number); self.save()
        started = time.monotonic()
        try:
            result = self.client.call(role, route, messages)
        except Exception as exc:
            # Native provider refusals/truncations retain their entire receipt.
            payload = getattr(exc, 'response_payload', None)
            freeze(self.run / f'ERROR_{number:03d}.json', {'type': type(exc).__name__, 'native': payload})
            metadata = getattr(exc, 'response_metadata', {}) or {}
            usage = (payload or {}).get('usage', {})
            choices = (payload or {}).get('choices', [])
            known = (metadata.get('response_id') and (payload or {}).get('id') == metadata['response_id']
                     and len(choices) == 1 and choices[0].get('finish_reason') in ('stop', 'length')
                     and choices[0]['finish_reason'] == metadata.get('finish_reason')
                     and all(type(metadata.get(k)) is int and metadata[k] >= 0 and metadata[k] == usage.get(k)
                             for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                     and metadata['total_tokens'] == metadata['prompt_tokens'] + metadata['completion_tokens'])
            if known:
                self.state.update(status='needs_attention', pending=None,
                                  input_tokens=self.state['input_tokens']+metadata['prompt_tokens'],
                                  output_tokens=self.state['output_tokens']+metadata['completion_tokens'])
            else:
                self.state['status'] = 'outcome_unknown'
            self.save()
            raise
        freeze(self.run / f'RESPONSE_{number:03d}.json', result)
        metric = {'call': number, 'role': role, 'provider': route['provider'], 'model': route['model'],
                  'thinking': route['thinking'], 'input_sha256': digest(messages), 'elapsed_seconds': round(time.monotonic()-started, 3),
                  'output_schema_sha256': digest(claim['output_schema']),
                  'input_tokens': result.get('input_tokens'), 'output_tokens': result.get('output_tokens'),
                  'structural_pass': False, 'semantic_pass': None}
        self.state['metrics'].append(metric)
        if any(type(result.get(k)) is not int or result[k] < 0 for k in ('input_tokens', 'output_tokens')):
            self.state['status'] = 'outcome_unknown'; self.save()
            raise ValueError('native_usage_unknown')
        self.state.update(pending=None, input_tokens=self.state['input_tokens']+result['input_tokens'],
                          output_tokens=self.state['output_tokens']+result['output_tokens']); self.save()
        if not result['done'] or not result['text'].strip():
            raise ValueError('known_incomplete_native_response')
        if route['provider'] == 'ollama' and result['response_model'] != route['model']:
            raise ValueError('native_model_mismatch')
        value = result['text'] if role == 'integrate' else json.loads(result['text'])
        freeze(self.run / f'OUTPUT_{number:03d}.json', {'role': role, 'value': value, 'sha256': digest(value)})
        return value, metric

    def stage(self, role, artifacts, feedback=None):
        repair = feedback
        for attempt in range(self.plan['protocol_repairs_per_stage'] + 1):
            # Transport, native envelope, usage, and parse uncertainty are not
            # content repair opportunities. Never loop over invoke failures.
            value, metric = self.invoke(role, artifacts, repair)
            try:
                validate_stage(role, value, self.source, artifacts)
            except (ValueError, ValidationError) as error:
                code = str(error).split('\n')[0][:800]
                metric['rejection'] = code; self.save()
                freeze(self.run / f'REJECT_{metric["call"]:03d}.json', {'role': role, 'reason': code, 'output_sha256': digest(value)})
                if attempt == self.plan['protocol_repairs_per_stage']:
                    raise ValueError('stage_validation_failed:' + role + ':' + code) from None
                repair = repair_payload(role, value, code, artifacts)
                continue
            metric['structural_pass'] = True
            if role == 'review':
                metric['reported_review_pass'] = value['decision'] == 'pass'
            self.save()
            return value

    def source_gate(self, artifacts):
        for revision in range(2):
            review = self.stage('source_review', artifacts)
            freeze(self.run / f'SOURCE_REVIEW_{self.state["calls_started"]:03d}.json', review)
            bad = [row for row in review['checks'] if not row['supported']]
            if review['world_supported'] and not bad:
                freeze(self.run / f'GROUNDED_FACTS_{self.state["calls_started"]:03d}.json', artifacts['facts'])
                return review
            if revision == 1:
                raise ValueError('source_fidelity_repair_limit_reached')
            artifacts['facts'] = self.stage('facts', artifacts,
                {'previous_output': artifacts['facts'], 'source_review': review,
                 'instruction': '对照原文修正不受支持的断言及无关支线；删去不确定细节，不编造证据。返回完整事实表，保留正确内容。'})


def execute(run, client=None):
    experiment = Experiment(run, client)
    state = experiment.state; plan = experiment.plan; root = experiment.run
    if (root / 'APPROVAL_REQUIRED.json').exists():
        raise ValueError('explicit_approval_pending_for_this_cloud_experiment')
    if state['pending'] or state['status'] != 'prepared':
        return state
    if plan['version'] != VERSION:
        raise ValueError('frozen_experiment_version_requires_original_executor')
    lock = root / 'EXECUTION.lock'
    with lock.open('x') as stream:
        stream.write('single role experiment executor')
    artifacts = {}
    try:
        if experiment.client.preflight(plan['routes']) != plan['model_pins']:
            raise ValueError('installed_model_changed')
        for role in ROLES:
            artifacts[role] = experiment.source_gate(artifacts) if role == 'source_review' else experiment.stage(role, artifacts)
            if role == 'outline':
                artifacts['allocated_beats'] = allocate(artifacts[role], experiment.source['target_seconds'])
            freeze(root / f'ACCEPTED_{role}_00.json', {'value': artifacts[role], 'sha256': digest(artifacts[role])})
        if artifacts['review']['decision'] != 'pass':
            # Rebuild from the earliest responsible stage, retaining all old
            # outputs. Later stages are invalidated, never spliced into old work.
            review = artifacts['review']
            earliest = min(ROLES.index(i['owner']) for i in review['issues'])
            feedback = {'issues': review['issues'], 'previous_draft': artifacts['integrate'],
                        'instruction': '只修改当前职责，后续角色将重新运行。'}
            freeze(root / 'INVALIDATION_01.json', {'from_role': ROLES[earliest], 'invalidated': list(ROLES[earliest:]),
                                                'previous_hashes': {k: digest(v) for k, v in artifacts.items()}})
            for role in ROLES[earliest:]:
                artifacts.pop(role, None)
            artifacts.pop('allocated_beats', None)
            if earliest > ROLES.index('outline'):
                artifacts['allocated_beats'] = allocate(artifacts['outline'], experiment.source['target_seconds'])
            for role in ROLES[earliest:]:
                artifacts[role] = (experiment.source_gate(artifacts) if role == 'source_review'
                                   else experiment.stage(role, artifacts, feedback if role == ROLES[earliest] else None))
                if role == 'outline':
                    artifacts['allocated_beats'] = allocate(artifacts[role], experiment.source['target_seconds'])
                freeze(root / f'ACCEPTED_{role}_01.json', {'value': artifacts[role], 'sha256': digest(artifacts[role])})
        passed = artifacts['review']['decision'] == 'pass'
        freeze(root / 'FINAL_ARTIFACTS.json', artifacts)
        if 'integrate' in artifacts:
            with (root / 'SCREENPLAY.md').open('x', encoding='utf8') as stream:
                stream.write(artifacts['integrate'])
        state.update(status='machine_review_passed' if passed else 'needs_attention',
                     quality_acceptance='awaiting_independent_acceptance' if passed else 'not_passed',
                     final_sha256=digest(artifacts), automatic_media_dispatch=False)
    except Exception as exc:
        if not state['pending']:
            state['status'] = 'needs_attention'
        state['reason'] = type(exc).__name__ + ':' + str(exc).split('\n')[0][:800]
        raise
    finally:
        experiment.save()
        freeze(root / 'METRICS.json', {'metrics': state['metrics'], 'quality_acceptance': state.get('quality_acceptance', 'not_passed'),
                                     'ranking': None, 'note': '结构通过率不是内容质量分；不同输入不直接排名。'})
        lock.unlink()
    return state


def benchmark(reference_run, call_number, run, routes, *, user_statement, client=None, cloud_authorized=False):
    reference = Experiment(reference_run, client)
    claim = read(Path(reference_run) / f'CALL_{call_number:03d}.json')
    if claim['source_sha256'] != reference.plan['source_sha256']:
        raise ValueError('benchmark_source_changed')
    if digest(messages_for(claim['role'], reference.source, claim['artifacts'], claim['repair'])) != claim['messages_sha256']:
        raise ValueError('benchmark_inputs_not_identical')
    prepare(run, reference.source['chapters'], reference.source['episode_intent'], routes,
            user_statement=user_statement, target_seconds=reference.source['target_seconds'],
            provenance={'benchmark_of': str(Path(reference_run).resolve()), 'call': call_number}, client=client,
            cloud_authorized=cloud_authorized)
    trial = Experiment(run, client)
    # Ensure the benchmark tests exactly the original stage request, not a
    # model-specific rewritten prompt or another model's previous verdict.
    messages = messages_for(claim['role'], trial.source, claim['artifacts'], claim['repair'])
    if digest(messages) != claim['messages_sha256']:
        raise ValueError('benchmark_inputs_not_identical')
    lock = Path(run) / 'EXECUTION.lock'
    with lock.open('x') as stream:
        stream.write('single benchmark executor')
    try:
        if trial.client.preflight(trial.plan['routes']) != trial.plan['model_pins']:
            raise ValueError('installed_model_changed')
        value, metric = trial.invoke(claim['role'], claim['artifacts'], claim['repair'])
        validate_stage(claim['role'], value, trial.source, claim['artifacts'])
        metric['structural_pass'] = True
        trial.state.update(status='benchmark_complete', quality_acceptance='unscored')
    except Exception as exc:
        if not trial.state['pending']:
            trial.state['status'] = 'needs_attention'
        trial.state['reason'] = type(exc).__name__ + ':' + str(exc).split('\n')[0][:800]
        raise
    finally:
        trial.save()
        freeze(Path(run) / 'METRICS.json', {'metrics': trial.state['metrics'], 'quality_acceptance': 'unscored',
                                          'reference_input_sha256': claim['messages_sha256'], 'ranking': None})
        lock.unlink()
    return trial.state


def report(runs):
    """Compare per task; a protocol pass never turns into a quality score."""
    groups = {}; paired = {}; results = []
    for run in runs:
        # Historical metrics are read-only; a previous version can have fewer
        # roles. Do not apply today's executable routing contract to its report.
        trial = SimpleNamespace(plan=read(Path(run) / 'PLAN.json'), state=read(Path(run) / 'STATE.json'))
        if digest(trial.plan) != trial.state['plan_sha256'] or digest(read(Path(run) / 'SOURCE.json')) != trial.plan['source_sha256']:
            raise ValueError('report_frozen_inputs_changed')
        results.append({'run': str(Path(run).resolve()), 'status': trial.state['status'],
                        'quality_acceptance': trial.state.get('quality_acceptance', 'not_passed'),
                        'calls': trial.state['calls_started']})
        for metric in trial.state['metrics']:
            key = (metric['role'], metric['provider'], metric['model'], metric['thinking'])
            row = groups.setdefault(key, {'role': key[0], 'provider': key[1], 'model': key[2], 'thinking': key[3],
                                         'calls': 0, 'structural_passes': 0, 'elapsed_seconds': 0,
                                         'input_tokens': 0, 'output_tokens': 0, 'semantic_score': None})
            row['calls'] += 1; row['structural_passes'] += int(metric['structural_pass'])
            row['elapsed_seconds'] += metric['elapsed_seconds']
            row['input_tokens'] += metric.get('input_tokens') or 0
            row['output_tokens'] += metric.get('output_tokens') or 0
            evaluation_path = Path(run) / f'INDEPENDENT_EVALUATION_{metric["call"]:03d}.json'
            if evaluation_path.exists():
                evaluation = read(evaluation_path)
                native = read(Path(run) / f'RESPONSE_{metric["call"]:03d}.json')
                if evaluation['response_sha256'] != digest(native) or evaluation['source_sha256'] != trial.plan['source_sha256']:
                    raise ValueError('evaluation_binding_changed')
                row.setdefault('independent_evaluations', []).append({'run': str(Path(run).resolve()), 'call': metric['call'],
                    'semantic_pass': evaluation['semantic_pass'], 'evaluator': evaluation['evaluator'],
                    'finding_count': len(evaluation['findings'])})
            pair = paired.setdefault((metric['role'], metric['input_sha256']), [])
            pair.append({'run': str(Path(run).resolve()), 'call': metric['call'], 'model': metric['model'],
                         'provider': metric['provider'], 'thinking': metric['thinking'],
                         'structural_pass': metric['structural_pass'], 'elapsed_seconds': metric['elapsed_seconds']})
    for row in groups.values():
        row['elapsed_seconds'] = round(row['elapsed_seconds'], 3)
        row['mean_elapsed_seconds'] = round(row['elapsed_seconds'] / row['calls'], 3)
    return {'runs': results, 'by_task_model': list(groups.values()),
            'identical_input_comparisons': [{'role': key[0], 'input_sha256': key[1], 'samples': values}
                                            for key, values in paired.items()
                                            if len({(v['provider'], v['model'], v['thinking']) for v in values}) > 1],
            'ranking': None, 'note': '模型自评与结构合格不能替代独立内容验收；阶段耗时含加载，不同输入不能直接排名。'}


def record_evaluation(run, call_number, evaluation):
    """Append independent observations; never rewrite native model verdicts."""
    trial = Experiment(run)
    response = read(Path(run) / f'RESPONSE_{call_number:03d}.json')
    if evaluation.get('evaluator') not in ('assistant_source_review', 'human_review') or type(evaluation.get('semantic_pass')) is not bool:
        raise ValueError('independent_evaluator_required')
    findings = evaluation.get('findings')
    if not isinstance(findings, list) or (not evaluation['semantic_pass'] and not findings):
        raise ValueError('evaluation_findings_required')
    evidence = {e['id'] for e in trial.source['evidence']}
    for finding in findings:
        if (not isinstance(finding.get('output_quote'), str) or not finding['output_quote']
                or finding['output_quote'] not in response['text'] or not finding.get('reason')
                or not isinstance(finding.get('source_ids'), list) or not set(finding['source_ids']) <= evidence):
            raise ValueError('evaluation_evidence_invalid')
    value = {**evaluation, 'call': call_number, 'source_sha256': trial.plan['source_sha256'],
             'response_sha256': digest(response), 'production_acceptance': False}
    freeze(Path(run) / f'INDEPENDENT_EVALUATION_{call_number:03d}.json', value)
    return value
