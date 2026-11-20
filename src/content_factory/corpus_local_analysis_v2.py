"""Loopback-only adapter for analysis testing, with pinned model identity."""
import json
import urllib.request
from types import SimpleNamespace

from .screenplay_role_runner_v5 import local_endpoint


class LocalInputRejected(ValueError):
    dispatched = False


def preflight(route):
    route = dict(route)
    local_endpoint(route['endpoint'])
    if route.get('provider') != 'ollama' or not route.get('model'):
        raise ValueError('local_analysis_route_invalid')
    route.setdefault('max_tokens', 8192)
    route.setdefault('context', 32768)
    if type(route['max_tokens']) is not int or not 512 <= route['max_tokens'] <= 16000:
        raise ValueError('local_analysis_output_limit_invalid')
    if type(route['context']) is not int or not 8192 <= route['context'] <= 65536:
        raise ValueError('local_analysis_context_invalid')
    with urllib.request.urlopen(route['endpoint'] + '/api/tags', timeout=10) as response:
        tags = json.load(response)
    model = next((m for m in tags['models'] if m['name'] == route['model']), None)
    if not model or not model.get('digest'):
        raise ValueError('local_analysis_model_missing')
    if route.get('digest') and route['digest'] != model['digest']:
        raise ValueError('local_analysis_model_changed')
    route['digest'] = model['digest']
    return route


class LocalAnalysisClient:
    def __init__(self, route):
        self.route = preflight(route)

    def call(self, role, messages, **kwargs):
        if role != 'director' or kwargs.get('response_format') != {'type': 'json_object'}:
            raise ValueError('local_adapter_analysis_only')
        payload = json.loads(messages[-1]['content'])
        # Byte count is intentionally conservative for a byte-level tokenizer;
        # reject oversized prompts before HTTP instead of accepting truncation.
        if sum(len(m['content'].encode('utf-8')) for m in messages) + kwargs['max_tokens'] + 1024 > self.route['context']:
            raise LocalInputRejected('local_analysis_context_capacity_requires_smaller_groups_or_larger_context')
        body = {'model': self.route['model'], 'messages': messages, 'stream': False,
                'keep_alive': 0, 'format': payload.get('output_schema', 'json'),
                'options': {'num_ctx': self.route['context'], 'num_predict': kwargs['max_tokens'],
                            'temperature': .1, 'seed': 42}}
        if self.route['model'].startswith('qwen3.5'):
            body['think'] = False
        request = urllib.request.Request(self.route['endpoint'] + '/api/chat',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=900) as response:
            native = json.load(response)
        meta = {'provider': 'ollama', 'requested_model': self.route['model'],
                'response_model': native.get('model'), 'model_digest': self.route['digest'],
                'finish_reason': native.get('done_reason') if native.get('done') is True else 'unknown',
                'prompt_tokens': native.get('prompt_eval_count'), 'completion_tokens': native.get('eval_count')}
        if all(type(meta[k]) is int and meta[k] >= 0 for k in ('prompt_tokens', 'completion_tokens')):
            meta['total_tokens'] = meta['prompt_tokens'] + meta['completion_tokens']
        if native.get('model') != self.route['model']:
            meta['finish_reason'] = 'model_mismatch'
        return SimpleNamespace(text=native.get('message', {}).get('content', ''),
                               metadata=meta, response_payload=native)
