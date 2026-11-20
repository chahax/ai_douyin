from types import SimpleNamespace

import httpx

from scripts.audit_creative_provider_environment_v1 import query_deepseek_models, sanitize_models


def config(base="https://api.deepseek.com/v1"):
    return SimpleNamespace(provider="deepseek", model="deepseek-flash", base_url=base,
                           api_key="test-secret-do-not-persist")


def test_only_one_get_and_public_model_metadata_are_saved():
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url), request.content))
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash", "name": "Flash",
                                "max_output_tokens": 42, "api_key": "never-save"}],
                                        "access_token": "never-save"})

    result = query_deepseek_models(config(), lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert calls == [("GET", "https://api.deepseek.com/v1/models", b"")]
    assert result["configured_model_listed"] is True
    assert result["generation_request_sent"] is False
    assert "test-secret" not in str(result) and "never-save" not in str(result)


def test_unverified_origin_never_receives_credentials():
    def forbidden():
        raise AssertionError("must not construct client")

    for base in ("https://other.example/v1", "http://api.deepseek.com/v1",
                 "https://api.deepseek.com/beta", "https://api.deepseek.com/v1?token=x",
                 "https://api.deepseek.com@other.example/v1"):
        assert query_deepseek_models(config(base), forbidden)["request_sent"] is False


def test_http_failure_does_not_persist_reflected_key_or_error_body():
    def handler(request):
        return httpx.Response(400, text=request.headers["authorization"])

    result = query_deepseek_models(config(), lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert result["http_status"] == 400
    assert "test-secret" not in str(result)
    assert "models" not in result


def test_malformed_200_is_not_model_discovery_success_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"id": "deepseek-flash"}})

    result = query_deepseek_models(config(), lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert result["status"] == "directory_result_unavailable"
    assert len(calls) == 1


def test_absent_configured_model_is_not_assumed_supported():
    result = query_deepseek_models(config(), lambda: httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "different"}]}))))
    assert result["configured_model_listed"] is False
    assert result["configured_model_metadata"] is None


def test_private_top_level_fields_are_excluded_from_directory():
    assert sanitize_models({"data": [{"id": "m", "name": "M", "private": "secret"}],
                            "account_id": "private-account"}) == [{"id": "m", "name": "M"}]
