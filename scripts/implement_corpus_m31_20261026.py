"""One-shot source migration; never executes a model or edits frozen runs."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
base = root / 'src/content_factory'
qa = root / 'data/qa/corpus_m31_default_20261026'
qa.mkdir(parents=True, exist_ok=True)
old = [base / name for name in ('corpus_production_v6.py', 'corpus_scope_v6.py',
       'corpus_chapter_materials_v6.py', 'corpus_episode_state_v6.py',
       'corpus_production_contract_v6.py', 'minimax_text_trial_client_v1.py')]
for folder in ('data/corpus_production_trials/20261026_v6_real_review',
               'data/corpus_facts_v5_trials/20261026_minimax_m31_flash'):
    old.extend(p for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
with (qa / 'OLD_FILES.json').open('x', encoding='utf-8') as stream:
    json.dump({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in old}, stream, indent=2)

s = (base / 'corpus_production_v6.py').read_text(encoding='utf-8')
s = s.replace('Qwen proposes lightweight source-bound materials, MiniMax reviews and writes from an episode',
              'MiniMax-M3.1-Flash classifies and writes; Qwen independently reviews the episode')
s = s.replace('from .corpus_production_v3 import _source, _cloud_routes, _frozen',
              'from .corpus_production_v3 import _source, _cloud_routes as _legacy_cloud_routes, _frozen\nfrom .minimax_production_client_v1 import MiniMaxProductionClient, MODEL, REQUEST_POLICY')
s = s.replace('corpus_scope_v6', 'corpus_scope_v7')
s = s.replace("VERSION = 'corpus_production/v6-chapter-materials-episode-state'", "VERSION = 'corpus_production/v7-minimax-materials-episode-state'")
s = s.replace("'chapter_materials': 'local', 'material_review': 'writer'", "'chapter_materials': 'writer', 'material_review': 'local'")
start, end = s.index('class StageClients:'), s.index('\ndef _capacity(')
s = s[:start] + '''def _cloud_routes():
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

''' + s[end:]
s = s.replace('local_call_limit', 'materials_call_limit')
s = s.replace("    for chapter_plan in plans:\n", "    materials_route = {'provider': 'minimax', 'model': MODEL, 'context': 131072,\n                       'max_tokens': 16384, 'request_policy': deepcopy(REQUEST_POLICY)}\n    for chapter_plan in plans:\n", 1)
s = s.replace("chapters_api.chapter_schema(chapter_plan, payload)}, route)", "chapters_api.chapter_schema(chapter_plan, payload)}, materials_route)")
s = s.replace('完整逐章正文与来源绑定轻量材料候选供MiniMax核验/框架；', '完整逐章正文供MiniMax-M3.1-Flash分类，材料候选供本机Qwen复核；')
s = s.replace("'stage_routes': STAGES, 'target_seconds'", "'stage_routes': STAGES, 'materials_route': materials_route,\n            'minimax_request_policy': deepcopy(REQUEST_POLICY), 'target_seconds'")
s = s.replace("('local', plan['materials_call_limit'], route)", "('materials', plan['materials_call_limit'], materials_route)")
s = s.replace("'local_route': route, 'stages': STAGES, 'max_tokens': 16000", "'local_route': route, 'stages': STAGES, 'max_tokens': 16384,\n                                         'minimax_request_policy': deepcopy(REQUEST_POLICY)")
s = s.replace("('local', 'cloud')", "('materials', 'cloud')")
s = s.replace("run / 'local'", "run / 'materials'")
s = s.replace("_calls(run, 'local', client)", "_calls(run, 'materials', client)")
s = s.replace('def execute_local(run, client=None):', 'def execute_materials(run, client=None):')
s = s.replace("    client = client or StageClients(plan['local_route'], plan['cloud_models'])\n    lock", "    require_cloud_authorization(run, plan)\n    client = client or StageClients(plan['local_route'], plan['cloud_models'])\n    lock", 1)
s = s.replace("'EXTRACT_MATERIALS_' + chapter_plan['id'], 'local'", "'EXTRACT_MATERIALS_' + chapter_plan['id'], 'writer'")
s = s.replace('all_local_materials_required_before_production', 'all_chapter_materials_required_before_production')
s = s.replace("'corpus_production_v6.py', 'corpus_scope_v7.py'", "'corpus_production_v7.py', 'corpus_scope_v7.py', 'minimax_production_client_v1.py', 'minimax_text_trial_client_v1.py'")
s = s.replace("        def call(name, role, prompt, payload, json_output=True):\n", "        def call(name, role, prompt, payload, json_output=True):\n            # The unchanged v6 content contract is routed to a different model for independent review.\n            if name.startswith('MATERIAL_REVIEW_'):\n                if role != 'writer':\n                    raise ValueError('unexpected_material_review_contract_role')\n                role = STAGES['material_review']\n")
s = s.replace("f'MATERIALS_REPAIR_{cp[\"id\"]}_{attempt}', 'local'", "f'MATERIALS_REPAIR_{cp[\"id\"]}_{attempt}', 'writer'")
s += "\n\ndef execute_local(run, client=None):\n    \"\"\"Legacy command alias; v7's frozen materials route is explicitly cloud MiniMax.\"\"\"\n    return execute_materials(run, client)\n"
with (base / 'corpus_production_v7.py').open('x', encoding='utf-8') as stream:
    stream.write(s)

s = (base / 'corpus_scope_v6.py').read_text(encoding='utf-8')
s = s.replace('corpus_scope/v6.0-experimental', 'corpus_scope/v7-minimax-default')
s = s.replace('corpus_production/v6-chapter-materials-episode-state', 'corpus_production/v7-minimax-materials-episode-state')
s = s.replace('corpus_scope_v6.py', 'corpus_scope_v7.py').replace('corpus_production_v6.py', 'corpus_production_v7.py')
s = s.replace('    "corpus_episode_state_v6.py",', '    "minimax_production_client_v1.py", "minimax_text_trial_client_v1.py",\n    "creative_workflow_roles.py", "natural_director_role_clients_v10.py",\n    "corpus_episode_state_v6.py",')
s = s.replace('whole_v6_production_implementation', 'whole_v7_production_implementation').replace('v6 implementation', 'v7 implementation')
with (base / 'corpus_scope_v7.py').open('x', encoding='utf-8') as stream:
    stream.write(s)
print('Created v7 coordinator/scope; old source and run hashes saved.')
