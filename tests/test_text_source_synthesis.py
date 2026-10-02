import json
import pytest

from src.trend_intelligence.content_analysis.text_synthesis import ConfiguredTextSynthesis


class Client:
    provider_name = "openai_compatible"
    model_name = "configured-test-model"

    def __init__(self, result='{"claims": []}'):
        self.calls = []
        self.result = result

    def chat_completion_tracked(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.result


def test_only_text_is_sent_and_real_response_is_saved(tmp_path):
    client = Client()
    synth = ConfiguredTextSynthesis(tmp_path, client=client)
    assert synth([{"type": "text", "text": "A0001 付款诉求"}]) == {"claims": []}
    messages, options = client.calls[0]
    assert messages[1] == {"role": "user", "content": "A0001 付款诉求"}
    assert options["caller"] == "source_expression_synthesis"
    saved = json.loads((tmp_path / "text_synthesis_response_001.json").read_text(encoding="utf-8"))
    assert saved["answer"] == client.result
    assert saved["media_uploaded"] is False
    assert saved["started_at"] and saved["completed_at"]


@pytest.mark.parametrize("content", [
    [{"type": "image", "image": "frame.jpg"}],
    [{"type": "text", "text": "caption", "audio": "voice.wav"}],
    [{"type": "text", "text": "x" * 64001}],
    [],
])
def test_media_and_unbounded_payloads_stop_before_api(tmp_path, content):
    client = Client()
    with pytest.raises(ValueError):
        ConfiguredTextSynthesis(tmp_path, client=client)(content)
    assert client.calls == []


def test_bad_model_json_is_preserved_not_replaced_with_fake_analysis(tmp_path):
    client = Client("not valid JSON")
    with pytest.raises(ValueError):
        ConfiguredTextSynthesis(tmp_path, client=client)([{"type": "text", "text": "actual evidence"}])
    saved = json.loads((tmp_path / "text_synthesis_response_001.json").read_text(encoding="utf-8"))
    assert saved["answer"] == "not valid JSON"


def test_mock_provider_cannot_claim_real_source_analysis(tmp_path):
    client = Client()
    client.provider_name = "mock"
    with pytest.raises(ValueError):
        ConfiguredTextSynthesis(tmp_path, client=client)


def test_quote_escape_preserves_raw_answer_and_records_repair(tmp_path):
    raw = '{"claims":[{"text":"他说"今天付款"然后离开","evidence_ids":["A0001"]}],"uncertainties":[]}'
    result = ConfiguredTextSynthesis(tmp_path, client=Client(raw))([{"type": "text", "text": "actual evidence"}])
    assert result["claims"][0]["text"] == '他说"今天付款"然后离开'
    saved = json.loads((tmp_path / "text_synthesis_response_001.json").read_text(encoding="utf-8"))
    assert saved["answer"] == raw
    assert saved["syntax_repair"]["original_sha256"] != saved["syntax_repair"]["repaired_sha256"]
