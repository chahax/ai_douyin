"""Same model/wire, durable raw HTTP evidence before content parsing. No retries."""
from __future__ import annotations
from copy import deepcopy
import json
import math
from src.content_factory.creative_workflow_roles import RoleResult, role_config, _response_model_matches
from src.content_factory.creative_response_contract import fault, exception_failure as legacy_exception_failure
from src.shared.config import settings

VERSION = 'creative_evidenced_role_clients/v1'
TOOL_NAME = 'submit_creative_json'
SAFE_HEADERS = ('x-request-id', 'request-id', 'x-trace-id', 'trace-id', 'content-type', 'date')

class EvidenceCallError(RuntimeError):
    def __init__(self, code, *, started, received=False, outcome_known=False, metadata=None, payload=None, text=None, cause_type=None):
        super().__init__(code)
        self.code = code
        self.provider_dispatch_started = started
        self.response_received = received
        self.provider_outcome_known = outcome_known
        self.response_metadata = deepcopy(metadata) if metadata is not None else None
        self.response_payload = deepcopy(payload)
        self.response_text = text
        self.status_code = (metadata or {}).get('http_status_code')
        self.request_id = (metadata or {}).get('http_request_id')
        self.cause_type = cause_type


def evidence_exception_failure(exc):
    if not isinstance(exc, EvidenceCallError):
        result = legacy_exception_failure(exc)
        result['provider_outcome_known'] = result['response_received']
        return result
    code = exc.code if exc.provider_outcome_known else 'OUTCOME_UNKNOWN'
    if exc.provider_dispatch_started is False:
        code = 'BLOCKED_BEFORE_DISPATCH'
    action = 'diagnose_original_received_response' if exc.provider_outcome_known else 'reconcile_original_request'
    result = fault(code, 'interface' if exc.provider_dispatch_started else 'control', action, received=exc.response_received)
    result.update(provider_outcome_known=exc.provider_outcome_known, cause_code=exc.code,
                  http_status_code=exc.status_code, http_request_id=exc.request_id,
                  cause_type=exc.cause_type)
    return result


def http_metadata(status, headers, *, extra_request_id=None):
    safe = {name: str(headers.get(name))[:256] for name in SAFE_HEADERS if headers.get(name)}
    request_id = safe.get('x-request-id') or safe.get('request-id') or extra_request_id
    return {'http_status_code': status if type(status) is int else None,
            'http_request_id': request_id if isinstance(request_id, str) else None,
            'safe_response_headers': safe}


def strict_envelope(raw):
    def pairs(items):
        value = {}
        for key, child in items:
            if key in value:
                raise ValueError('duplicate response field')
            value[key] = child
        return value
    def nonfinite(value):
        raise ValueError('nonfinite response field')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError('response object required')
    def finite(item):
        if isinstance(item,float) and not math.isfinite(item):raise ValueError('nonfinite response number')
        if isinstance(item,dict):
            for child in item.values():finite(child)
        elif isinstance(item,list):
            for child in item:finite(child)
    finite(value)
    return value


def parse_saved_response(raw, manifest, role, model, thinking, structured_schema, evidence):
    """Can also be called for local recovery. Never imports or constructs an SDK."""
    metadata = {**deepcopy(manifest['http_metadata']), 'role': role,
        'provider': 'minimax' if role == 'writer' else 'deepseek', 'requested_model': model,
        'response_model': '', 'response_id': '', 'finish_reason': '',
        'thinking_mode': thinking or 'provider_default', 'output_mode': 'unusable_response',
        'transport_version': VERSION, 'strict_mode': False, 'server_schema_guarantee': False,
        'response_body_complete': True, 'raw_body_sha256': manifest['original_sha256']}
    payload = None
    text = None
    def record(phase, details):
        try:
            evidence.record(phase, details)
        except Exception as exc:
            raise EvidenceCallError('RESPONSE_PHASE_SAVE_FAILED',started=True,received=True,
                outcome_known=True,metadata=metadata,payload=payload,text=text,cause_type=type(exc).__name__) from None
    def reject(code):
        metadata['response_fault_code'] = code
        record('response_rejected', {'code': code, 'metadata': metadata})
        raise EvidenceCallError(code, started=True, received=True, outcome_known=True,
                                metadata=metadata, payload=payload, text=text)
    try:
        payload = strict_envelope(raw)
    except (ValueError, UnicodeError):
        reject('HTTP_ERROR_RESPONSE' if (metadata['http_status_code'] or 0) >= 400 else 'RESPONSE_ENVELOPE_INVALID')
    for key, field in (('response_id', 'id'), ('response_model', 'model'), ('provider_trace_id', 'trace_id')):
        value = payload.get(field)
        if isinstance(value, str):
            metadata[key] = value
    usage = payload.get('usage')
    if isinstance(usage, dict):
        for field in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            value = usage.get(field)
            if type(value) is int and value >= 0:
                metadata[field] = value
        metadata['usage_source'] = 'original_provider_response'
    base = payload.get('base_resp')
    if isinstance(base, dict):
        metadata['provider_status_code'] = base.get('status_code')
    record('response_metadata_saved', {'metadata': metadata})
    if manifest['credential_redacted']:
        reject('RESPONSE_CREDENTIAL_REDACTED')
    if (metadata['http_status_code'] or 0) >= 400:
        reject('HTTP_ERROR_RESPONSE')
    if base is not None and (not isinstance(base, dict) or type(base.get('status_code')) is not int):
        reject('PROVIDER_STATUS_INVALID')
    if isinstance(base, dict) and base['status_code'] != 0:
        reject('PROVIDER_ERROR_RESPONSE')
    choices = payload.get('choices')
    if not isinstance(choices, list):
        reject('MALFORMED_RESPONSE_ENVELOPE')
    if not choices:
        reject('NO_RESPONSE_CHOICES')
    if len(choices) != 1 or not isinstance(choices[0], dict):
        reject('UNEXPECTED_RESPONSE_CHOICES')
    choice = choices[0]
    metadata['finish_reason'] = choice.get('finish_reason') if isinstance(choice.get('finish_reason'), str) else ''
    # Truncation is diagnosed before tool absence or malformed tool details.
    if metadata['finish_reason'] == 'length':
        reject('RESPONSE_TRUNCATED')
    if not _response_model_matches(role, model, metadata['response_model']):
        reject('MODEL_MISMATCH')
    if metadata['finish_reason'] not in ('stop', 'tool_calls'):
        reject('RESPONSE_NOT_COMPLETED')
    message = choice.get('message')
    if not isinstance(message, dict):
        reject('MALFORMED_RESPONSE_ENVELOPE')
    tools = message.get('tool_calls')
    if tools is None:tools=[]
    if not isinstance(tools, list):
        reject('UNEXPECTED_TOOL_CALL')
    if structured_schema is not None:
        if not tools:
            reject('REQUIRED_TOOL_MISSING')
        if len(tools) != 1 or not isinstance(tools[0], dict):
            reject('UNEXPECTED_TOOL_CALL')
        function = tools[0].get('function')
        if not isinstance(function, dict) or function.get('name') != TOOL_NAME or tools[0].get('type') != 'function':
            reject('UNEXPECTED_TOOL_CALL')
        text = function.get('arguments')
        metadata['output_mode'] = 'tool_call'
    else:
        text = message.get('content')
        metadata['output_mode'] = 'content'
    if not isinstance(text, str) or not text.strip():
        reject('EMPTY_RESPONSE')
    record('result_ready', {'metadata': metadata})
    return RoleResult(text=text, metadata=metadata, response_payload=payload)


class EvidencedRoleClients:
    def call(self, role, messages, *, max_tokens=12000, temperature=.4, thinking=None,
             structured_schema=None, writer_model=None, evidence=None):
        if evidence is None or role not in ('writer', 'director') or writer_model not in (None, 'MiniMax-M3'):
            raise EvidenceCallError('INVALID_EVIDENCE_PREFLIGHT', started=False, outcome_known=True)
        if type(max_tokens) is not int or not 0 < max_tokens <= 32000 or type(temperature) not in (int, float) or temperature != .4:
            raise EvidenceCallError('INVALID_REQUEST_PARAMETERS', started=False, outcome_known=True)
        if thinking not in (None, 'disabled', 'adaptive') or (role == 'director' and thinking == 'adaptive') or (role == 'director' and writer_model is not None):
            raise EvidenceCallError('UNVERIFIED_MODEL_MODE', started=False, outcome_known=True)
        if role == 'director' and (not isinstance(structured_schema, dict) or not structured_schema):
            raise EvidenceCallError('REVIEW_SCHEMA_REQUIRED', started=False, outcome_known=True)
        started = False
        received = False
        metadata = None
        client = None
        try:
            from openai import OpenAI
            config = role_config(role)
            evidence.register_secrets(config.api_key)
            client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                            timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0)
            parameters = {'model': config.model, 'messages': deepcopy(messages), 'temperature': temperature,
                          'max_completion_tokens' if role == 'writer' else 'max_tokens': max_tokens}
            if thinking in ('disabled', 'adaptive'):
                parameters['extra_body'] = {'thinking': {'type': thinking}}
                if thinking == 'adaptive':
                    parameters['extra_body']['reasoning_split'] = True
            if structured_schema is not None:
                description = '提交本阶段完整结构化创作结果' if role == 'writer' else '提交本阶段完整文本审核结果，保留所有结论及真实证据'
                parameters['tools'] = [{'type': 'function', 'function': {'name': TOOL_NAME,
                    'description': description, 'parameters': deepcopy(structured_schema)}}]
                parameters['tool_choice'] = {'type': 'function', 'function': {'name': TOOL_NAME}}
            evidence.record('client_configured', {'role': role, 'model': config.model,
                'base_url': config.base_url, 'timeout_seconds': settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                'max_retries': 0, 'server_stream_requested': False})
            evidence.record('dispatch_attempt_started', {'meaning': 'SDK method about to be called; not a server acknowledgement'})
            started = True
            # This only defers local body parsing; it does NOT send stream=True.
            with client.chat.completions.with_streaming_response.create(**parameters) as response:
                received = True
                metadata = http_metadata(response.status_code, response.headers)
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                evidence.record('http_headers_received', metadata)
                raw = response.read()
                protected, manifest = evidence.save_body(raw, metadata)
            return parse_saved_response(protected, manifest, role, config.model, thinking, structured_schema, evidence)
        except EvidenceCallError:
            raise
        except Exception as exc:
            response = getattr(exc, 'response', None)
            status = getattr(exc, 'status_code', None)
            # SDK HTTP error replies are response evidence, not transport silence.
            if response is not None and type(status) is int:
                received = True
                metadata = http_metadata(status, response.headers, extra_request_id=getattr(exc, 'request_id', None))
                metadata = json.loads(evidence.protect(json.dumps(metadata).encode())[0])
                try:
                    evidence.record('http_error_headers_received', metadata)
                except Exception as storage_exc:
                    raise EvidenceCallError('HTTP_ERROR_EVIDENCE_SAVE_FAILED',started=started,received=True,
                        outcome_known=True,metadata=metadata,cause_type=type(storage_exc).__name__) from None
                try:
                    raw = response.read()
                except Exception:
                    raise EvidenceCallError('HTTP_ERROR_BODY_UNAVAILABLE', started=started, received=True,
                        outcome_known=True, metadata=metadata, cause_type=type(exc).__name__) from None
                try:
                    protected, manifest = evidence.save_body(raw, metadata)
                except Exception as storage_exc:
                    raise EvidenceCallError('HTTP_ERROR_EVIDENCE_SAVE_FAILED',started=started,received=True,
                        outcome_known=True,metadata=metadata,cause_type=type(storage_exc).__name__) from None
                return parse_saved_response(protected, manifest, role, config.model, thinking, structured_schema, evidence)
            code = 'RESPONSE_CAPTURE_INTERRUPTED' if received else ('TRANSPORT_EXCEPTION' if started else 'CLIENT_PREFLIGHT_FAILED')
            try:
                evidence.record('call_interrupted', {'code': code, 'cause_type': type(exc).__name__,
                                                  'headers_received': received})
            except Exception:
                pass  # Preserve the original structured exception if the journal also fails.
            raise EvidenceCallError(code, started=started, received=received,
                outcome_known=not started, metadata=metadata, cause_type=type(exc).__name__) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    # Cleanup must not replace the original response or exception.
                    pass
