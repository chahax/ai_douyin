"""Resource-policy tests with no media/model/process startup."""
from contextlib import contextmanager
from pathlib import Path

from src.trend_intelligence.content_analysis import toolchain as runtime


def test_low_memory_environment_limits_children_without_changing_parent(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "16")
    monkeypatch.setenv("SOURCE_ANALYSIS_LOW_MEMORY", "1")
    service = runtime.LocalContentToolchain()
    assert service.low_memory and service.max_images == 2 and service.cpu_threads == 2
    assert service.frame_interval_seconds == 2
    environment = runtime._subprocess_environment(low_memory=True)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        assert environment[key] == "2"
    assert environment["TOKENIZERS_PARALLELISM"] == "false"
    assert environment["SOURCE_ANALYSIS_LOW_MEMORY"] == "1"
    assert runtime.os.environ["OMP_NUM_THREADS"] == "16"
    assert runtime.LocalContentToolchain(low_memory=False).max_images == 6


def test_low_memory_decoder_is_single_threaded_without_changing_frame_scale():
    class FakeCv2:
        CAP_FFMPEG = 1900
        CAP_PROP_N_THREADS = 70

        def __init__(self):
            self.arguments = None

        def VideoCapture(self, *arguments):
            self.arguments = arguments
            return "capture"

    cv2 = FakeCv2()
    assert runtime._open_video_capture(cv2, Path("source.mp4"), low_memory=True) == "capture"
    assert cv2.arguments == ("source.mp4", 1900, [70, 1])
    runtime._open_video_capture(cv2, Path("source.mp4"), low_memory=False)
    assert cv2.arguments == ("source.mp4",)


def test_low_memory_pipeline_holds_resource_slot_for_all_source_stages(tmp_path, monkeypatch):
    events = []

    @contextmanager
    def slot(path):
        events.append(("acquire", path))
        try:
            yield
        finally:
            events.append(("release", path))

    monkeypatch.setattr(runtime, "_single_local_job", slot)
    service = runtime.LocalContentToolchain(project_root=tmp_path, low_memory=True)
    monkeypatch.setattr(service, "_prepare_request", lambda request: events.append(("whole_source", request)) or "prepared")
    assert service.prepare_request("request") == "prepared"
    assert [event[0] for event in events] == ["acquire", "whole_source", "release"]
    assert events[0][1] == tmp_path / "data/video_analysis/local_low_memory.lock"


def test_low_memory_execution_passes_resource_mode_to_default_runner(monkeypatch):
    service = runtime.LocalContentToolchain(low_memory=True)
    calls = []
    monkeypatch.setattr(service, "_run_command", lambda command, **kwargs: calls.append((command, kwargs)))
    progress = object()
    service._execute(["python", "fake_model.py"], progress)
    assert calls == [(["python", "fake_model.py"], {"progress": progress, "low_memory": True})]
