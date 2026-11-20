"""Explicit M3.1 image-input extension; unchanged SDK single-send evidence.

Only selected independent still images are supported here, never video review.
Official schema checked20261015: /docs/api-reference/text-openai-api.
"""
import base64
from copy import deepcopy
import hashlib
import json

from scripts import creative_m31_flash_role_clients_v1 as text
from scripts.creative_resume_dispatch_v3 import digest

VERSION = "creative_world_scene_multimodal_clients/v1"
OFFICIAL = "https://platform.minimax.cn/docs/api-reference/text-openai-api"
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _projection(request):
    value = deepcopy(request)
    images = []
    for mi, message in enumerate(value.get("messages", [])):
        content = message.get("content")
        if isinstance(content, str):
            continue
        if request.get("role") != "writer" or message.get("role") != "user" or type(content) is not list or not content:
            raise ValueError("only writer user-message selected still images are supported")
        for ci, part in enumerate(content):
            if type(part) is not dict:
                raise ValueError("typed image/text part required")
            if part.get("type") == "text" and set(part) == {"type", "text"} and isinstance(part["text"], str):
                continue
            if part.get("type") != "image_url" or set(part) != {"type", "image_url"}:
                raise ValueError("selected still image input required; no video input")
            image = part["image_url"]
            if type(image) is not dict or set(image) - {"url", "detail"} or image.get("detail", "default") not in ("low", "default", "high"):
                raise ValueError("official image_url fields required")
            url = image.get("url")
            if not isinstance(url, str) or not url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
                raise ValueError("original selected image bytes required as explicit base64")
            raw = base64.b64decode(url.split(",", 1)[1], validate=True)
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("official per-image10MiB bound exceeded")
            mime = url.split(";", 1)[0][5:]
            valid = ((mime == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n"))
                or (mime == "image/jpeg" and raw.startswith(b"\xff\xd8\xff"))
                or (mime == "image/webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"))
            if not valid:
                raise ValueError("selected image MIME differs from original file bytes")
            images.append({"message_index": mi, "content_index": ci, "bytes": len(raw),
                "mime": mime, "sha256": hashlib.sha256(raw).hexdigest()})
        message["content"] = "[independent selected still images; validation-only text projection]"
    return value, images


def expected_wire_request(request):
    checking, _ = _projection(request)
    wire = text.expected_wire_request(checking)
    wire["messages"] = deepcopy(request["messages"])
    if len(json.dumps(wire, ensure_ascii=False).encode("utf-8")) > text.MAX_BODY_BYTES:
        raise ValueError("official64MB request bound exceeded")
    return wire


class MultimodalRoleClients(text.M31FlashRoleClients):
    def __init__(self, *, expected_request, **kwargs):
        checking, self.image_inventory = _projection(expected_request)
        wire = expected_wire_request(expected_request)
        super().__init__(expected_request=checking, **kwargs)
        self._request = deepcopy(expected_request)
        self._request_sha256 = digest(expected_request)
        self._wire, self._wire_sha256 = wire, digest(wire)

    def call(self, *args, **kwargs):
        evidence = kwargs.get("evidence")
        if evidence is not None:
            evidence.record("selected_still_image_input", {"schema": VERSION, "official_reference": OFFICIAL,
                "logical_request_sha256": self._request_sha256, "images": deepcopy(self.image_inventory),
                "video_input_used": False, "sdk_max_retries": 0, "server_schema_guarantee": False})
        return super().call(*args, **kwargs)


def make_client_factory(request, **kwargs):
    frozen = deepcopy(request)
    return lambda: MultimodalRoleClients(expected_request=frozen, **kwargs)
