"""Safe API metadata with synthetic responses only; never makes network calls."""
import json
from types import SimpleNamespace

import pytest

from src.shared.llm_providers import openai_compatible_provider as module
from test_script_llm_response import provider_with_response


def response(*, content='{"ok":true}', finish_reason='stop', **fields):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason,
        message=SimpleNamespace(content=content, reasoning_content='DO_NOT_RETAIN_REASONING'))], **fields)


def using_response(value):
    provider, _ = provider_with_response(preserve=True, content='unused')
    provider.client.chat.completions.create = lambda **kwargs: value
    return provider


def test_success_retains_actual_model_id_and_only_supplied_usage_counts():
    value = response(id='completion-actual', model='actual-model-revision', usage=SimpleNamespace(
        prompt_tokens=31, completion_tokens=17, total_tokens=48,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0, audio_tokens=None),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=11, reasoning_text='DO_NOT_RETAIN_REASONING'),
        request_headers='DO_NOT_RETAIN_HEADERS', invalid_tokens=-1, bool_tokens=True, string_tokens='9'))
    provider = using_response(value)
    assert provider.chat_completion([], json_mode=True) == '{"ok":true}'
    assert provider.last_response_metadata == {
        'response_id': 'completion-actual', 'response_model': 'actual-model-revision',
        'finish_reason': 'stop', 'content_processing': 'json_normalization',
        'content_is_raw_http_response': False,
        'usage': {'prompt_tokens': 31, 'completion_tokens': 17, 'total_tokens': 48,
            'prompt_tokens_details': {'cached_tokens': 0},
            'completion_tokens_details': {'reasoning_tokens': 11}},
    }


def test_length_with_unusable_content_keeps_usage_and_does_not_invent_output():
    provider = using_response(response(content=None, finish_reason='length', id='length-response',
        model='actual-m3', usage={'prompt_tokens': 20, 'completion_tokens': 4096,
                                'completion_tokens_details': {'reasoning_tokens': 4096}}))
    assert provider.chat_completion([], json_mode=True) is None
    metadata = provider.last_response_metadata
    assert metadata['finish_reason'] == 'length'
    assert metadata['usage']['completion_tokens'] == 4096
    assert metadata['content_processing'] == 'text_normalization_after_invalid_json'
    assert metadata['content_is_raw_http_response'] is False
    assert 'DO_NOT_RETAIN' not in json.dumps(metadata)


def test_absent_usage_is_not_zero_or_carried_over_from_previous_response():
    provider = using_response(response(id='first', model='actual-first', usage={'total_tokens': 9}))
    provider.chat_completion([], json_mode=True)
    provider.client.chat.completions.create = lambda **kwargs: response()
    assert provider.chat_completion([], json_mode=True) == '{"ok":true}'
    assert provider.last_response_metadata == {
        'finish_reason': 'stop', 'content_processing': 'json_normalization',
        'content_is_raw_http_response': False,
    }


def test_failure_retains_only_safe_fields_exposed_by_sdk_without_logging_body(monkeypatch):
    class SyntheticStatusError(Exception):
        request_id = 'http-request-id'
        status_code = 429
        body = {'id': 'body-response', 'model': 'actual-error-model',
            'usage': {'input_tokens': 27, 'output_tokens': 0},
            'choices': [{'finish_reason': 'length', 'message': {'reasoning_content': 'DO_NOT_RETAIN_REASONING'}}],
            'headers': {'authorization': 'DO_NOT_RETAIN_HEADERS'}}
    provider = using_response(None)
    def fail(**kwargs):
        raise SyntheticStatusError('DO_NOT_LOG_ERROR_BODY')
    provider.client.chat.completions.create = fail
    errors = []
    monkeypatch.setattr(module.logger, 'error', lambda *args: errors.append(args))
    assert provider.chat_completion([], json_mode=True) is None
    metadata = provider.last_response_metadata
    assert metadata['error_type'] == 'SyntheticStatusError'
    assert metadata['request_id'] == 'http-request-id' and metadata['status_code'] == 429
    assert metadata['response_id'] == 'body-response'
    assert metadata['response_model'] == 'actual-error-model'
    assert metadata['usage'] == {'input_tokens': 27, 'output_tokens': 0}
    assert metadata['finish_reason'] == 'length'
    assert 'DO_NOT_' not in json.dumps([metadata, errors])


def test_metadata_survives_a_local_content_processing_failure():
    provider = using_response(SimpleNamespace(id='malformed-choice-response', model='actual-model',
        usage={'total_tokens': 13}, choices=[]))
    assert provider.chat_completion([], json_mode=True) is None
    assert provider.last_response_metadata['error_type'] == 'IndexError'
    assert provider.last_response_metadata['response_id'] == 'malformed-choice-response'
    assert provider.last_response_metadata['usage'] == {'total_tokens': 13}
    assert 'finish_reason' not in provider.last_response_metadata


@pytest.mark.parametrize('json_mode,content,expected,processing', [
    (True, '```json\n{"ok":true}\n```', '{"ok":true}', 'json_normalization'),
    (False, '<think>DO_NOT_RETAIN_REASONING</think>answer', 'answer', 'text_normalization'),
])
def test_output_semantics_unchanged_and_explicitly_not_raw_http(json_mode, content, expected, processing):
    provider = using_response(response(content=content))
    assert provider.chat_completion([], json_mode=json_mode) == expected
    assert provider.last_response_metadata['content_processing'] == processing
    assert provider.last_response_metadata['content_is_raw_http_response'] is False
