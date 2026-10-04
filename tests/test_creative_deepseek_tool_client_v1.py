"""Mock-SDK boundary tests; no network or real credentials are read."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS

import openai
import pytest

from scripts import creative_deepseek_tool_client_v1 as tool_client
from src.content_factory.creative_workflow_roles import RoleConfig, RoleResult, RoleResponseError
from src.content_factory.creative_response_contract import exception_failure

SECRET = 'offline-credential-fixture-do-not-report'
SCHEMA = {'type': 'object', 'properties': {'whole_review': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['whole_review'], 'additionalProperties': False}
MESSAGES = [{'role': 'system', 'content': '完整全文审查协议'}, {'role': 'user', 'content': '完整剧本与参考原文'}]


def response(*, finish='tool_calls', names=None, text='{"whole_review":["保留原失败结论"]}', content=None, model='deepseek-flash', choices=True):
    names = [tool_client.TOOL_NAME] if names is None else names
    tools = [NS(id=f'tool_{i}', type='function', function=NS(name=name, arguments=text)) for i, name in enumerate(names)]
    return NS(id='response-fixture-001', model=model,
              choices=[NS(finish_reason=finish, message=NS(content=content, reasoning_content='完整服务分析回执', tool_calls=tools))] if choices else [],
              usage=NS(prompt_tokens=21, completion_tokens=13, total_tokens=34))


def sdk_mock(monkeypatch, result=None, create_error=None, constructor_error=None):
    initialized, requests, configured = [], [], []
    def config(role):
        configured.append(role)
        return RoleConfig('deepseek', 'deepseek-flash', 'https://standard-endpoint.invalid', SECRET)
    def create(**parameters):
        requests.append(deepcopy(parameters))
        if create_error is not None: raise create_error
        return result
    def factory(**parameters):
        initialized.append(deepcopy(parameters))
        if constructor_error is not None: raise constructor_error
        return NS(chat=NS(completions=NS(create=create)))
    monkeypatch.setattr(tool_client, 'role_config', config)
    monkeypatch.setattr(openai, 'OpenAI', factory)
    return initialized, requests, configured


def call(**kwargs):
    parameters = {'max_tokens': 16000, 'temperature': 0.4, 'thinking': 'disabled', 'structured_schema': SCHEMA}
    parameters.update(kwargs)
    return tool_client.CreativeDeepSeekToolClients().call('director', MESSAGES, **parameters)


def test_deepseek_wire_uses_same_endpoint_forced_tool_and_schema_not_strict(capsys, monkeypatch):
    initialized, requests, configured = sdk_mock(monkeypatch, response(content='ignore even valid body content'))
    before = deepcopy((MESSAGES, SCHEMA))
    result = call()
    assert configured == ['director'] and len(initialized) == len(requests) == 1
    assert initialized[0]['base_url'] == 'https://standard-endpoint.invalid'
    assert initialized[0]['max_retries'] == 0 and initialized[0]['api_key'] == SECRET
    parameters = requests[0]
    assert parameters['model'] == 'deepseek-flash'
    assert parameters['messages'] == MESSAGES
    assert parameters['max_tokens'] == 16000 and 'max_completion_tokens' not in parameters
    assert parameters['temperature'] == 0.4 and parameters['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert parameters['tool_choice'] == {'type': 'function', 'function': {'name': 'submit_creative_json'}}
    function = parameters['tools'][0]['function']
    assert function['parameters'] == SCHEMA and function['name'] == 'submit_creative_json'
    assert 'strict' not in function and 'response_format' not in parameters
    assert result.text == '{"whole_review":["保留原失败结论"]}'
    assert result.metadata['output_mode'] == 'tool_call'
    assert result.metadata['strict_mode'] is False and result.metadata['server_schema_guarantee'] is False
    assert result.metadata['total_tokens'] == 34
    assert result.response_payload['choices'][0]['message']['reasoning_content'] == '完整服务分析回执'
    assert SECRET not in json.dumps({'metadata': result.metadata, 'payload': result.response_payload}, ensure_ascii=False)
    assert capsys.readouterr().out == ''
    assert (MESSAGES, SCHEMA) == before


@pytest.mark.parametrize('model', ['deepseek-flash', 'deepseek-v4.1-flash', 'deepseek-v4_1-flash'])
def test_director_retains_frozen_response_alias_match(monkeypatch, model):
    sdk_mock(monkeypatch, response(model=model))
    assert call().metadata['response_model'] == model


@pytest.mark.parametrize('defect,code', [('length_no_tool', 'RESPONSE_TRUNCATED'), ('length_correct_tool', 'RESPONSE_TRUNCATED'),
    ('body_only', 'REQUIRED_TOOL_MISSING'), ('wrong_name', 'UNEXPECTED_TOOL_CALL'), ('two_tools', 'UNEXPECTED_TOOL_CALL'),
    ('no_choices', 'NO_RESPONSE_CHOICES'), ('wrong_model', 'MODEL_MISMATCH'), ('unknown_finish', 'RESPONSE_NOT_COMPLETED'),
    ('empty_args', 'EMPTY_RESPONSE'), ('object_args', 'EMPTY_RESPONSE'), ('missing_function', 'UNEXPECTED_TOOL_CALL')])
def test_rejected_response_keeps_original_billing_snapshot_and_never_body_fallback(monkeypatch, defect, code):
    result = response()
    if defect == 'length_no_tool': result = response(finish='length', names=[], content='{"partial":true}')
    elif defect == 'length_correct_tool': result = response(finish='length')
    elif defect == 'body_only': result = response(finish='stop', names=[], content='{"whole_review":["body fallback forbidden"]}')
    elif defect == 'wrong_name': result = response(names=['other_tool'])
    elif defect == 'two_tools': result = response(names=[tool_client.TOOL_NAME, tool_client.TOOL_NAME])
    elif defect == 'no_choices': result = response(choices=False)
    elif defect == 'wrong_model': result = response(model='unexpected-model')
    elif defect == 'unknown_finish': result = response(finish='aborted')
    elif defect == 'empty_args': result = response(text=' ')
    elif defect == 'object_args': result = response(text={'not': 'text'})
    else: result.choices[0].message.tool_calls = [NS(id='malformed', type='function')]
    initialized, requests, _ = sdk_mock(monkeypatch, result)
    with pytest.raises(RoleResponseError) as caught:
        call()
    error = caught.value
    assert error.response_metadata['response_fault_code'] == code
    assert error.response_metadata['total_tokens'] == 34
    assert error.response_payload['usage'] == {'prompt_tokens': 21, 'completion_tokens': 13, 'total_tokens': 34}
    assert len(requests) == len(initialized) == 1
    assert exception_failure(error)['response_received'] is True
    assert SECRET not in str(error)


@pytest.mark.parametrize('thinking', [None, 'disabled'])
def test_tool_choice_always_has_explicit_nonthinking_mode(monkeypatch, thinking):
    _, requests, _ = sdk_mock(monkeypatch, response())
    result = call(thinking=thinking)
    assert requests[0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert result.metadata['thinking_mode'] == 'disabled'


@pytest.mark.parametrize('kwargs', [{'structured_schema': None}, {'structured_schema': {}}, {'structured_schema': []},
    {'thinking': 'adaptive'}, {'thinking': 'enabled'}, {'temperature': 0.7}, {'temperature': True},
    {'max_tokens': True}, {'max_tokens': 0}, {'max_tokens': 32001}, {'writer_model': 'MiniMax-M3'}])
def test_invalid_experimental_parameters_stop_before_config_or_sdk(monkeypatch, kwargs):
    initialized, requests, configured = sdk_mock(monkeypatch, response())
    with pytest.raises(tool_client.DeepSeekToolPreflightError) as caught:
        call(**kwargs)
    assert caught.value.provider_dispatch_started is False
    assert exception_failure(caught.value)['code'] == 'BLOCKED_BEFORE_DISPATCH'
    assert initialized == requests == configured == []


@pytest.mark.parametrize('during_constructor', [False, True])
def test_api_exception_redacts_request_credentials_and_preserves_unknown_dispatch_state(monkeypatch, during_constructor):
    class SDKFailure(RuntimeError):
        status_code = 503
        request_id = 'safe-request-id'
    original = SDKFailure('SDK dumped request key=' + SECRET + ' with full request body')
    initialized, requests, _ = sdk_mock(monkeypatch, create_error=None if during_constructor else original,
                                        constructor_error=original if during_constructor else None)
    with pytest.raises(RuntimeError) as caught:
        call()
    error = caught.value
    assert SECRET not in str(error) and 'full request body' not in str(error)
    assert '503' in str(error) and 'safe-request-id' in str(error)
    assert error.provider_dispatch_started is (not during_constructor)
    assert not hasattr(error, 'response_metadata')
    assert exception_failure(error)['code'] == ('BLOCKED_BEFORE_DISPATCH' if during_constructor else 'OUTCOME_UNKNOWN')
    assert len(initialized) == 1 and len(requests) == (0 if during_constructor else 1)


def test_writer_delegate_preserves_original_arguments_and_uses_no_director_config(monkeypatch):
    captured = []
    original_result = RoleResult('original-writer-response', {'provider': 'minimax', 'unchanged': True})
    class WriterDelegate:
        def call(self, *args, **kwargs):
            captured.append((args, kwargs))
            return original_result
    monkeypatch.setattr(tool_client, 'FrozenCreativeRoleClients', WriterDelegate)
    monkeypatch.setattr(tool_client, 'role_config', lambda role: pytest.fail('director config must not be read'))
    result = tool_client.CreativeDeepSeekToolClients().call('writer', MESSAGES, max_tokens=8000, temperature=1,
        thinking='adaptive', structured_schema=SCHEMA, writer_model='MiniMax-M2.7')
    assert result is original_result
    assert captured == [(('writer', MESSAGES), {'max_tokens': 8000, 'temperature': 1, 'thinking': 'adaptive',
                                              'structured_schema': SCHEMA, 'writer_model': 'MiniMax-M2.7'})]


def test_transport_does_not_claim_model_arguments_are_valid_json_or_review(monkeypatch):
    sdk_mock(monkeypatch, response(text='invalid-json-but-complete-tool-string'))
    result = call()
    assert result.text == 'invalid-json-but-complete-tool-string'
    assert result.metadata['server_schema_guarantee'] is False
    assert result.metadata['output_mode'] == 'tool_call'
    # Operator strict_json, tool schema and final v7 evidence validation remain required.
