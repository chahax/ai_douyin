from copy import deepcopy
import hashlib
import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from scripts import creative_world_scene_multimodal_clients_v1 as module
from scripts.creative_call_evidence_v1 import CallEvidenceJournal, digest
from test_creative_m31_flash_role_clients_v1 import logical, reply, call

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPXcAAAAASUVORK5CYII="


def request():
    value = logical()
    value["messages"].append({"role": "user", "content": [
        {"type": "text", "text": "image1=场景；image2=角色A"},
        {"type": "image_url", "image_url": {"url": PNG, "detail": "default"}},
        {"type": "image_url", "image_url": {"url": PNG, "detail": "low"}}]})
    return value


@pytest.mark.parametrize("fault", [None, "timeout"])
def test_actual_sdk_original_image_order_bytes_and_single_send(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(module.text, "role_config", lambda role: SimpleNamespace(
        model="MiniMax-M3", api_key="offline-image-key", base_url="https://api.minimaxi.com/v1"))
    native, sent = request(), []
    saved = deepcopy(native)
    journal = CallEvidenceJournal(tmp_path / "call", {"ordinal": 1, "label": "selected_images",
        "request_sha256": digest(native), "source_binding_sha256": "offline-source", "role": "writer", "model": native["model"]})
    def handler(outgoing):
        sent.append(outgoing.read())
        assert json.loads(sent[0]) == module.expected_wire_request(native)
        assert (journal.root / "request_body.raw").read_bytes() == sent[0]
        if fault:
            raise httpx.ReadTimeout("mock unknown result", request=outgoing)
        return httpx.Response(200, content=reply())
    client = module.MultimodalRoleClients(expected_request=native,
        http_client_factory=lambda **kw: httpx.Client(transport=httpx.MockTransport(handler), **kw))
    if fault:
        with pytest.raises(module.text.EvidenceCallError) as caught:
            call(client, native, journal)
        assert caught.value.provider_outcome_known is False
    else:
        call(client, native, journal)
        proof = json.loads((journal.root / "M31_WIRE_PREFLIGHT.json").read_text(encoding="utf-8"))
        assert proof["actual_request_body_sha256"] == hashlib.sha256(sent[0]).hexdigest()
        assert proof["SDK_max_retries"] == 0
    assert native == saved and len(sent) == 1
    with pytest.raises(module.text.EvidenceCallError):
        call(client, native, journal)
    assert len(sent) == 1


@pytest.mark.parametrize("mutation", ["video", "mime", "role", "url"])
def test_unsupported_media_and_false_mime_fail_before_sdk(mutation):
    native = request()
    image = native["messages"][-1]["content"][-1]
    if mutation == "video": image["type"] = "video_url"
    elif mutation == "mime": image["image_url"]["url"] = PNG.replace("image/png", "image/jpeg")
    elif mutation == "role": native["messages"][-1]["role"] = "system"
    else: image["image_url"]["url"] = "https://unverified.example/image.png"
    with pytest.raises(ValueError): module.expected_wire_request(native)
