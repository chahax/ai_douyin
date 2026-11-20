"""Thread-safe, durable calls for new corpus plans; legacy ledgers stay intact."""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from src.platform_adapter.fanqie_book_corpus import atomic


class ParallelCalls:
    def __init__(self, run, plan, state, client, read, freeze, digest):
        self.run, self.plan, self.state, self.client = Path(run), plan, state, client
        self.read, self.freeze, self.digest = read, freeze, digest
        self.lock = threading.RLock()
        self.stopped = False

    def save(self):
        pending = self.state.setdefault('pending_calls', {})
        self.state['pending'] = sorted(pending) or None
        atomic(self.run / 'STATE.json', self.state)

    def __call__(self, name, role, prompt, context, json_output=True):
        messages = [{'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}]
        artifact = self.run / (name + ('.json' if json_output else '.md'))
        binding = self.run / 'CALL_BINDINGS' / (name + '.json')
        request = {'name': name, 'role': role, 'messages': messages,
                   'source_sha256': self.plan['source_sha256'],
                   'analysis_route': self.plan.get('analysis_route'), 'json_output': json_output}
        max_tokens = self.plan.get('analysis_route', {}).get('max_tokens', 16000)
        # Conservatively reserve UTF-8 request bytes plus maximum output for
        # each in-flight call. Completion replaces the reservation with usage.
        reservation = len(json.dumps(messages, ensure_ascii=False).encode()) + max_tokens + 1024
        with self.lock:
            if artifact.exists():
                b = self.read(binding)
                value = self.read(artifact) if json_output else artifact.read_text(encoding='utf-8')
                if b['request_sha256'] != self.digest(request) or b['artifact_sha256'] != self.digest(value):
                    raise ValueError('cached_call_binding_changed')
                return value
            if self.stopped or self.state.get('status') == 'outcome_unknown':
                raise RuntimeError('parallel_dispatch_stopped')
            pending = self.state.setdefault('pending_calls', {})
            if any(item['name'] == name for item in pending.values()):
                raise RuntimeError('same_model_call_already_pending')
            if (self.state['calls_started'] >= self.plan['new_call_limit']
                    or self.state['reported_tokens'] + sum(x['reserved_tokens'] for x in pending.values())
                    + reservation > self.plan['new_token_limit']):
                raise ValueError('new_scope_budget_exhausted')
            ordinal = self.state['calls_started'] + 1
            claim = self.run / f'CALL_{ordinal:03d}.json'
            self.freeze(claim, {**request, 'reserved_tokens': reservation,
                                'admitted_at': datetime.now(timezone.utc).isoformat()})
            pending[str(claim)] = {'name': name, 'ordinal': ordinal, 'reserved_tokens': reservation}
            self.state.update(status='running', stage=name, calls_started=ordinal)
            self.save()
        kwargs = {'max_tokens': max_tokens, 'temperature': .2 if json_output else .5, 'thinking': 'disabled'}
        if json_output:
            kwargs['response_format'] = {'type': 'json_object'}
        started=time.monotonic()
        try:
            result = self.client.call(role, messages, **kwargs)
        except Exception as exc:
            with self.lock:
                from .corpus_local_analysis_v2 import LocalInputRejected
                meta = getattr(exc, 'response_metadata', None) or {}
                native = getattr(exc, 'response_payload', None) or {}
                self.freeze(self.run / f'ERROR_{ordinal:03d}.json', {
                    'type': type(exc).__name__, 'metadata': meta, 'response_payload': native,
                    'dispatch_state': 'not_sent' if isinstance(exc, LocalInputRejected) else 'unknown_or_sent'})
                if isinstance(exc, LocalInputRejected):
                    self.state['pending_calls'].pop(str(claim))
                    if self.state.get('status') != 'outcome_unknown':
                        self.state['status'] = 'needs_attention'
                    self.stopped = True
                    self.save()
                    raise
                usage = native.get('usage') or {}
                choices = native.get('choices') or []
                known = (meta.get('response_id') and native.get('id') == meta['response_id']
                         and len(choices) == 1 and choices[0].get('finish_reason') == meta.get('finish_reason')
                         and meta.get('finish_reason') in ('stop', 'length')
                         and all(type(meta.get(k)) is int and meta[k] >= 0 and usage.get(k) == meta[k]
                                 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                         and meta['total_tokens'] == meta['prompt_tokens'] + meta['completion_tokens'])
                if known:
                    self.state['reported_tokens'] += meta['total_tokens']
                    self.state['pending_calls'].pop(str(claim))
                    if self.state.get('status') != 'outcome_unknown':
                        self.state['status'] = 'needs_attention'
                else:
                    self.state['status'] = 'outcome_unknown'
                self.stopped = True
                self.save()
            raise
        with self.lock:
            self.freeze(self.run / f'RESPONSE_{ordinal:03d}.json', {
                'text': result.text, 'metadata': result.metadata, 'response_payload': result.response_payload,
                'received_at': datetime.now(timezone.utc).isoformat(), 'elapsed_seconds': round(time.monotonic()-started,3)})
            total = result.metadata.get('total_tokens')
            valid_usage = (all(type(result.metadata.get(k)) is int and result.metadata[k] >= 0
                               for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
                           and total == result.metadata['prompt_tokens'] + result.metadata['completion_tokens'])
            if not valid_usage:
                self.state['status'] = 'outcome_unknown'
                self.stopped = True
                self.save()
                raise ValueError('native_usage_unknown')
            if result.metadata.get('finish_reason') not in ('stop', 'length'):
                self.state['status'] = 'outcome_unknown'
                self.stopped = True
                self.save()
                raise RuntimeError('native_completion_unknown')
            self.state['reported_tokens'] += total
            self.state['pending_calls'].pop(str(claim))
            if total > reservation or result.metadata.get('finish_reason') != 'stop':
                self.stopped = True
                if self.state.get('status') != 'outcome_unknown':
                    self.state['status'] = 'needs_attention'
                self.save()
                raise RuntimeError('native_response_not_completed_or_reservation_exceeded')
            self.save()
            if json_output:
                try:
                    value = json.loads(result.text)
                except json.JSONDecodeError:
                    value = {'parse_error': 'invalid_json', 'native_text': result.text}
                self.freeze(artifact, value)
            else:
                from .corpus_screenplay_v1 import visible_script
                value = visible_script(result.text)
                with artifact.open('x', encoding='utf-8') as stream:
                    stream.write(value)
            self.freeze(binding, {'request_sha256': self.digest(request), 'artifact_sha256': self.digest(value),
                                  'response_file': f'RESPONSE_{ordinal:03d}.json'})
            return value
