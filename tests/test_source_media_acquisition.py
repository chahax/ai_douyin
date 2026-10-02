import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.trend_intelligence import source_media_acquisition as media
from src.trend_intelligence.source_policy import PolicyStatus, SourcePolicy, SourceProvider


def candidate(number=1):
    video_id = str(7672315755727310080 + number)
    return SimpleNamespace(item_id="douyin:" + video_id, video_id=video_id, run_id="batch",
        url="https://www.douyin.com/video/" + video_id, title="本来源视频", duration_seconds=6.)


def snapshot(item, *, current=None, owner=None, blocked=False, embedded=None, resources=None):
    return {"page_url": item.url, "blocked": blocked,
        "player": {"found": True, "owner_id": item.video_id if owner is None else owner,
                   "current_src": current or f"https://v11-weba.douyinvod.com/{item.video_id}.mp4?signature=private-token"},
        "embedded": embedded or [], "observed_resources": resources or []}


def policy(*, include_detail=True, allowed_fields=None):
    return SourcePolicy(policy_id="authorized-source", provider=SourceProvider.AUTHORIZED_WEB,
        status=PolicyStatus.APPROVED, allowed_hosts=("www.douyin.com",),
        allowed_path_prefixes=("/video", "/aweme/v1/web/aweme/detail") if include_detail else ("/video",),
        allowed_fields=media.MEDIA_FIELDS if allowed_fields is None else frozenset(allowed_fields),
        allowed_purposes=frozenset({"trend_analysis"}), max_pages_per_run=20, daily_page_cap=50,
        authorization_reference_hash="sha256:test-explicit-scope")


class FakeResponse:
    status = 200
    def __init__(self, payload): self.payload = payload
    def json(self): return self.payload
    def body(self): return json.dumps(self.payload).encode()


class FakeRequest:
    def __init__(self):
        self.downloads, self.gets = [], []
        self.detail_payload = None
    def download(self, url, output_path, **kwargs):
        self.downloads.append((url, output_path, kwargs))
        payload = b"\x00\xfffixture-video" + url.encode()
        Path(output_path).write_bytes(payload)
        return {"status": 200, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
                "final_url": url.split("?")[0], "request_url_sha256": hashlib.sha256(url.encode()).hexdigest()}
    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeResponse(self.detail_payload)


class FakePage:
    def __init__(self, session):
        self.session, self.request, self.current = session, FakeRequest(), None
    @property
    def url(self): return (self.current or {}).get("page_url", "")
    def wait_for_timeout(self, milliseconds): pass
    def locator(self, selector): return self
    def evaluate(self, script):
        assert "source-media-acquisition-inspect/v1" in script
        return copy.deepcopy(self.current)


class FakeSession:
    def __init__(self, snapshots):
        self.snapshots, self.opened, self.close_calls = snapshots, [], 0
        self.page = FakePage(self)
    def open_page(self, url):
        self.opened.append(url)
        self.page.current = self.snapshots[url]
        return self.page
    def close(self):
        self.close_calls += 1
        raise AssertionError("service must preserve the existing session")


def service(tmp_path, monkeypatch, session, *, probe=None):
    monkeypatch.setattr(media, "PROJECT_ROOT", tmp_path)
    return media.SourceMediaAcquisitionService(output_root=tmp_path / "data/sources",
        session_factory=lambda: session, probe=probe or (lambda path: {
            "streams": [{"codec_type": "video", "width": 496, "height": 864}], "format": {"duration": "6"}}))


def acquire(runner, items, **kwargs):
    return runner.acquire(items, account_uuid="account:test", collection_run_id="batch",
        policy=kwargs.pop("policy", policy()), **kwargs)


def test_source_download_uses_one_session_and_resume_skips_verified_cache(tmp_path, monkeypatch):
    first, second = candidate(), candidate(2)
    session = FakeSession({item.url: snapshot(item) for item in (first, second)})
    runner = service(tmp_path, monkeypatch, session)
    initial = acquire(runner, [first, second], max_items=1)
    assert initial.status == "partial" and initial.acquired_count == 1
    manifest = json.loads(Path(initial.manifest_path).read_text(encoding="utf-8"))
    assert len(manifest["items"]) == 1 and len(manifest["pending_items"]) == 1
    assert len(manifest["selection"]) == 2
    assert manifest["items"][0]["video"]
    resumed = acquire(runner, [first, second], max_items=1)
    assert resumed.status == "completed" and resumed.cached_count == resumed.acquired_count == 1
    assert resumed.attempted_count == 1
    assert session.opened == [first.url, second.url]
    assert session.close_calls == 0 and resumed.session_left_open
    assert session.page.request.downloads[0][2]["allowed_hosts"] == ["v11-weba.douyinvod.com"]
    assert "private-token" not in json.dumps(resumed.to_dict())
    receipts = list(Path(initial.manifest_path).parent.glob("*.receipt.json"))
    assert "private-token" in receipts[0].read_text(encoding="utf-8")


def test_changed_cached_source_is_refetched_without_overwriting_old_file(tmp_path, monkeypatch):
    item = candidate()
    session = FakeSession({item.url: snapshot(item)})
    runner = service(tmp_path, monkeypatch, session)
    first = acquire(runner, [item])
    original = Path(first.records[0]["video"])
    original.write_bytes(b"changed")
    second = acquire(runner, [item])
    assert second.status == "completed" and second.cached_count == 0
    assert Path(second.records[0]["video"]) != original
    assert original.read_bytes() == b"changed"


@pytest.mark.parametrize("case,status", [("challenge", "human_required"), ("wrong_owner", "identity_unconfirmed"),
    ("blob", "source_unavailable"), ("unknown_owner", "identity_unconfirmed")])
def test_uncertain_identity_or_verification_stops_without_downloading(tmp_path, monkeypatch, case, status):
    first, second = candidate(), candidate(2)
    state = snapshot(first)
    if case == "challenge": state["blocked"] = True
    elif case == "wrong_owner": state["player"]["owner_id"] = second.video_id
    elif case == "blob": state["player"]["current_src"] = "blob:https://www.douyin.com/opaque"
    else: state["player"]["owner_id"] = ""
    session = FakeSession({first.url: state, second.url: snapshot(second)})
    result = acquire(service(tmp_path, monkeypatch, session), [first, second], max_items=2)
    assert result.status == status and result.attempted_count == 1
    assert not session.page.request.downloads and not session.page.request.gets
    assert session.opened == [first.url] and session.close_calls == 0
    assert result.session_left_open


def test_policy_blocks_before_browser_is_opened(tmp_path, monkeypatch):
    item = candidate()
    session = FakeSession({item.url: snapshot(item)})
    result = acquire(service(tmp_path, monkeypatch, session), [item], policy=policy(allowed_fields={"video_id", "url"}))
    assert result.status == "policy_blocked"
    assert not session.opened and not result.session_left_open


def test_bound_json_can_supply_media_for_blob_player_without_guessing_urls():
    item = candidate()
    url = "https://v26-web.douyinvod.com/actual-observed-source.mp4?signature=secret"
    state = snapshot(item, current="blob:https://www.douyin.com/player", owner="", embedded=[
        {"owner_id": candidate(2).video_id, "url": "https://other.example/video.mp4", "field": "video.play_addr"},
        {"owner_id": item.video_id, "url": url, "field": "video.play_addr", "container": "RENDER_DATA", "path": "$.aweme"}])
    found = media.locate_source_media(state, item.video_id)
    assert found["url"] == url and found["identity_kind"] == "embedded_video_owner"


def test_replays_only_observed_detail_request_and_rechecks_returned_video_identity(tmp_path, monkeypatch):
    item = candidate()
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + item.video_id + "&signature=observed-private"
    state = snapshot(item, current="blob:https://www.douyin.com/opaque", resources=[observed])
    session = FakeSession({item.url: state})
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": item.video_id,
        "video": {"play_addr_h264": {"url_list": ["https://v11-weba.douyinvod.com/observed-media.mp4?signature=private"]}}}}
    result = acquire(service(tmp_path, monkeypatch, session), [item])
    assert result.status == "completed"
    assert session.page.request.gets[0][0] == observed
    assert len(session.page.request.gets) == 1
    assert "observed-private" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("breakage", ["not_observed", "wrong_request_id", "wrong_response_id", "policy"])
def test_detail_fallback_does_not_query_guessed_or_mismatched_sources(tmp_path, monkeypatch, breakage):
    item = candidate()
    other = candidate(2)
    target_id = other.video_id if breakage == "wrong_request_id" else item.video_id
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + target_id
    resources = [] if breakage == "not_observed" else [observed]
    state = snapshot(item, current="blob:https://www.douyin.com/opaque", resources=resources)
    session = FakeSession({item.url: state})
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": other.video_id,
        "video": {"play_addr": {"url_list": ["https://v11-weba.douyinvod.com/video.mp4"]}}}}
    result = acquire(service(tmp_path, monkeypatch, session), [item], policy=policy(include_detail=breakage != "policy"))
    assert result.status != "completed"
    assert not session.page.request.downloads
    assert len(session.page.request.gets) == (1 if breakage == "wrong_response_id" else 0)


def test_nonvideo_download_is_not_added_to_manifest(tmp_path, monkeypatch):
    item = candidate()
    session = FakeSession({item.url: snapshot(item)})
    result = acquire(service(tmp_path, monkeypatch, session, probe=lambda path: {
        "streams": [{"codec_type": "audio"}], "format": {"duration": "6"}}), [item])
    assert result.status == "failed"
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["items"] == []
    assert not list(Path(result.manifest_path).parent.glob("*.mp4"))


def test_resume_after_verification_reuses_the_same_page_without_navigation(tmp_path, monkeypatch):
    item = candidate()
    session = FakeSession({item.url: snapshot(item, blocked=True)})
    runner = service(tmp_path, monkeypatch, session)
    assert acquire(runner, [item]).status == "human_required"
    session.page.current = snapshot(item)  # User completed verification in this page.
    result = acquire(runner, [item])
    assert result.status == "completed"
    assert session.opened == [item.url] and session.close_calls == 0


def test_source_duration_from_observed_response_detects_truncated_download(tmp_path, monkeypatch):
    item = candidate()
    item.duration_seconds = None
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + item.video_id
    session = FakeSession({item.url: snapshot(item, current="blob:https://www.douyin.com/player", resources=[observed])})
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": item.video_id,
        "video": {"duration": 91_400, "play_addr_h264": {"url_list": ["https://v11-weba.douyinvod.com/source.mp4"]}}}}
    result = acquire(service(tmp_path, monkeypatch, session), [item])
    assert result.status == "failed" and result.stopped_reason == "下载时长与来源页面记录明显不一致"
    assert not list(Path(result.manifest_path).parent.glob("*.mp4"))


def test_policy_interval_is_respected_between_distinct_source_pages(tmp_path, monkeypatch):
    from dataclasses import replace
    first, second = candidate(), candidate(2)
    session = FakeSession({item.url: snapshot(item) for item in (first, second)})
    runner = service(tmp_path, monkeypatch, session)
    clock, sleeps = [0.], []
    monkeypatch.setattr(media.time, "monotonic", lambda: clock[0])
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(media.time, "sleep", sleep)
    result = acquire(runner, [first, second], max_items=2, policy=replace(policy(), min_interval_seconds=2.))
    assert result.status == "completed" and sum(sleeps) >= 2.


def test_blob_player_waits_for_observed_detail_request_without_reloading(tmp_path, monkeypatch):
    item = candidate()
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + item.video_id
    initial = snapshot(item, current="blob:https://www.douyin.com/player")
    loaded = {**initial, "observed_resources": [observed]}
    session = FakeSession({item.url: initial})
    evaluations = []
    def evaluate(script):
        evaluations.append(script)
        return initial if len(evaluations) < 4 else loaded
    session.page.evaluate = evaluate
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": item.video_id,
        "video": {"duration": 6000, "play_addr_h264": {"url_list": ["https://v11-weba.douyinvod.com/source.mp4"]}}}}
    result = acquire(service(tmp_path, monkeypatch, session), [item])
    assert result.status == "completed" and len(evaluations) == 4
    assert session.opened == [item.url]


def variant_video():
    def address(size, width, height, label):
        return {"data_size": size, "width": width, "height": height,
                "url_list": [f"https://v11-weba.douyinvod.com/{label}.mp4?signature=private"]}
    return {"duration": 1_803_169, "audio": {"present": True},
        "play_addr_h264": address(748_199_679, 1080, 1920, "primary"),
        "download_addr": address(227_769_799, 720, 720, "square"),
        "bit_rate": [
            {"format": "dash", "is_h265": 1, "play_addr": address(68_136_076, 720, 1280, "dash")},
            {"format": "mp4", "is_h265": 1, "gear_name": "720_2_1", "play_addr": address(79_640_035, 720, 1280, "complete720")},
            {"format": "mp4", "is_h265": 1, "play_addr": address(58_558_250, 576, 1024, "complete576")},
        ]}


def test_variant_selection_preserves_complete_mp4_aspect_and_readable_resolution():
    selected = media.select_analysis_variant(variant_video())
    assert "complete720" in selected["url"]
    assert selected["variant"]["format"] == "mp4"
    assert selected["variant"]["data_size"] == 79_640_035
    assert selected["variant"]["width"] == 720 and selected["variant"]["height"] == 1280
    assert selected["requires_audio"]
    assert "signature" not in json.dumps(selected["variant"])
    video = variant_video()
    video["bit_rate"] = video["bit_rate"][:1]
    with pytest.raises(media.AcquisitionStop, match="完整 MP4"):
        media.select_analysis_variant(video)
    with pytest.raises(ValueError, match="时长"):
        media._validate_probe({"streams": [{"codec_type": "video", "width": 720, "height": 1280}],
            "format": {"duration": "1743.169"}}, 1803.169)


def test_observed_detail_selects_bounded_variant_before_large_current_src_get(tmp_path, monkeypatch):
    item = candidate()
    item.duration_seconds = None
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + item.video_id
    session = FakeSession({item.url: snapshot(item, resources=[observed])})
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": item.video_id, "video": variant_video()}}
    probe = lambda path: {"streams": [{"codec_type": "video", "width": 720, "height": 1280},
        {"codec_type": "audio", "duration": "1803.169"}], "format": {"duration": "1803.169"}}
    result = acquire(service(tmp_path, monkeypatch, session, probe=probe), [item])
    assert result.status == "completed"
    assert len(session.page.request.gets) == len(session.page.request.downloads) == 1
    assert "complete720" in session.page.request.downloads[0][0]
    assert result.records[0]["duration_seconds"] == 1803.169
    assert "private" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("audio", [[], [{"codec_type": "audio", "duration": "3"}]])
def test_variant_must_preserve_full_audio_track(tmp_path, monkeypatch, audio):
    item = candidate()
    item.duration_seconds = None
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + item.video_id
    session = FakeSession({item.url: snapshot(item, resources=[observed])})
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": item.video_id, "video": variant_video()}}
    probe = lambda path: {"streams": [{"codec_type": "video", "width": 720, "height": 1280}, *audio],
                          "format": {"duration": "1803.169"}}
    result = acquire(service(tmp_path, monkeypatch, session, probe=probe), [item])
    assert result.status == "failed" and "音" in result.stopped_reason
    assert result.records[-1]["video_id"] == item.video_id
    assert result.records[-1]["stage"] == "media_probe"
    assert not list(Path(result.manifest_path).parent.glob("*.mp4"))


@pytest.mark.parametrize("message,safe", [
    ("binary download HTTP status 403; no output saved", True),
    ("binary request failed (TimeoutError; request_sha256=abcdef1234567890)", True),
    ("binary download declared size is empty or exceeds max_bytes", True),
    ("binary download HTTP status 403; no output saved https://example.com/?signature=private", False),
    ("binary download failed (TimeoutError; url=https://example.com/?signature=private)", False),
])
def test_binary_failure_diagnostics_are_strictly_whitelisted(message, safe):
    assert bool(media.safe_binary_failure(RuntimeError(message))) == safe


def test_failed_download_records_exact_source_stage_and_safe_reason(tmp_path, monkeypatch):
    item = candidate()
    session = FakeSession({item.url: snapshot(item)})
    def denied(*args, **kwargs):
        raise RuntimeError("binary download HTTP status 403; no output saved")
    session.page.request.download = denied
    result = acquire(service(tmp_path, monkeypatch, session), [item])
    assert result.status == "failed" and "HTTP status 403" in result.stopped_reason
    assert result.records[-1] == {"item_id": item.item_id, "video_id": item.video_id,
        "status": "failed", "stage": "media_download", "safe_reason": result.stopped_reason}


def test_size_fallback_fetches_observed_detail_once_and_never_raises_cap(tmp_path, monkeypatch):
    item = candidate()
    observed = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=" + item.video_id
    initial, loaded = snapshot(item), snapshot(item, resources=[observed])
    session = FakeSession({item.url: initial})
    session.page.request.detail_payload = {"aweme_detail": {"aweme_id": item.video_id,
        "video": {"duration": 6000, "play_addr_h264": {"url_list": ["https://v11-weba.douyinvod.com/smaller.mp4"]}}}}
    original_download = session.page.request.download
    attempts = []
    def download(url, path, **kwargs):
        attempts.append(kwargs["max_bytes"])
        if len(attempts) == 1:
            session.page.current = loaded
            raise RuntimeError("binary download declared size is empty or exceeds max_bytes")
        return original_download(url, path, **kwargs)
    session.page.request.download = download
    result = acquire(service(tmp_path, monkeypatch, session), [item])
    assert result.status == "completed"
    assert attempts == [media.MAX_SOURCE_BYTES, media.MAX_SOURCE_BYTES]
    assert len(session.page.request.gets) == 1
