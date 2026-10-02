from types import SimpleNamespace

from src.shared.llm_providers.openai_compatible_provider import OpenAICompatibleProvider


def provider_with_response(*, preserve, content, finish_reason='stop'):
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.model = 'synthetic-test-model'
    provider.max_tokens = 32768 if preserve else None
    provider.preserve_invalid_json = preserve
    provider.extra_body = None
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish_reason, message=SimpleNamespace(content=content))])

    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return provider, calls


def test_script_client_retains_partial_response_for_workflow_repair():
    partial = '{"short": {"title": "缺少闭合括号"'
    provider, calls = provider_with_response(preserve=True, content=partial, finish_reason='length')
    assert provider.chat_completion([], json_mode=True) == partial
    assert provider.last_response_metadata == {
        'finish_reason': 'length',
        'content_processing': 'text_normalization_after_invalid_json',
        'content_is_raw_http_response': False,
    }
    assert calls[0]['max_tokens'] == 32768


def test_regular_calls_keep_existing_invalid_json_behavior_and_token_default():
    provider, calls = provider_with_response(preserve=False, content='bad-json')
    assert provider.chat_completion([], json_mode=True) is None
    assert 'max_tokens' not in calls[0]


def test_valid_json_is_normalized_for_both_client_modes():
    for preserve in (False, True):
        provider, _ = provider_with_response(preserve=preserve, content='```json\n{"ok": true}\n```')
        assert provider.chat_completion([], json_mode=True) == '{"ok": true}'


def test_json_followed_by_explanatory_text_keeps_only_the_complete_json_value():
    provider, _ = provider_with_response(
        preserve=False,
        content='Here is the result:\n{"ok": true, "nested": {"value": 1}}\n已按要求生成。',
    )
    assert provider.chat_completion([], json_mode=True) == '{"ok": true, "nested": {"value": 1}}'


def test_multiple_independent_json_values_remain_invalid():
    provider, _ = provider_with_response(
        preserve=False,
        content='{"first": true}\n{"second": true}',
    )
    assert provider.chat_completion([], json_mode=True) is None

def test_optional_model_request_controls_are_forwarded_without_changing_other_calls():
    provider, calls = provider_with_response(preserve=True, content='{"ok": true}')
    provider.extra_body = {'thinking': {'type': 'disabled'}, 'reasoning_split': True}
    assert provider.chat_completion([], json_mode=True) == '{"ok": true}'
    assert calls[0]['extra_body'] == provider.extra_body
    regular, calls = provider_with_response(preserve=False, content='{"ok": true}')
    regular.chat_completion([], json_mode=True)
    assert 'extra_body' not in calls[0]

