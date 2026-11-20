"""Returned-tail content type must survive a misleading local suffix."""
import base64
from src.content_factory.creative_segment_execution import frame_mime, reference

def test_service_jpeg_saved_as_png_is_sent_as_jpeg_without_changing_bytes(tmp_path):
    frame=tmp_path/"service_tail.png"
    raw=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"+b"opaque-provider-payload"
    frame.write_bytes(raw)
    url=reference(frame).to_content()["image_url"]["url"]
    assert frame_mime(frame)=="image/jpeg"
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",",1)[1])==raw
    assert frame.read_bytes()==raw

def test_png_saved_as_jpeg_is_sent_as_png(tmp_path):
    frame=tmp_path/"service_tail.jpg"
    raw=b"\x89PNG\r\n\x1a\n"+b"opaque-provider-payload"
    frame.write_bytes(raw)
    url=reference(frame).to_content()["image_url"]["url"]
    assert frame_mime(frame)=="image/png"
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",",1)[1])==raw

