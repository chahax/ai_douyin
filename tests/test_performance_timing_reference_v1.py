from copy import deepcopy
import hashlib
import json

import pytest

from scripts import run_performance_timing_natural_director_v1 as cli
from scripts import run_natural_director_v10 as legacy_cli
from src.content_factory import performance_timing_reference_v1 as timing
from src.content_factory import natural_director_contracts_v10 as director
from src.content_factory import novel_agent_roles_v8 as writer
from src.content_factory.novel_logic_contracts_v4 import REVIEW_DIMENSIONS


def test_profile_is_independent_hashed_reference_and_preserves_hard_bounds():
    value = timing.profile()
    body = {key: item for key, item in value.items() if key != "sha256"}
    assert value["sha256"] == hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert value["content_classifier"] is False and value["hard_duration_gate"] is False
    assert value["action_reference_seconds"]["ordinary_expression_already_present"]["max"] == 0
    original = dict(min_duration_seconds=105, max_duration_seconds=135, target_duration_seconds=120,
        duration_tolerance_seconds=15, duration_policy="hard_target", custom={"keep": [1]})
    before = deepcopy(original)
    result = timing.apply_brief(original)
    assert all(result[key] == item for key, item in original.items()) and original == before
    assert timing.apply_brief(result) == result
    result["performance_timing_reference"]["requirements"]["scope"] = "changed"
    result["custom"]["keep"].append(2)
    assert timing.profile() == value and original == before


def test_tampered_profile_is_rejected():
    brief = timing.apply_brief(None)
    brief["performance_timing_reference"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="不能覆盖"):
        timing.apply_brief(brief)


class Runtime:
    def __init__(self):
        self.calls = []
    def prepare_source(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"status": "prepared"}


@pytest.mark.parametrize("brief", [{}, timing.pacing.apply_brief({})])
def test_old_source_cannot_be_patched_and_bytes_remain_unchanged(tmp_path, brief):
    run = tmp_path / "old"
    run.mkdir()
    path = run / "BINDING.json"
    path.write_text(json.dumps({"brief": brief}, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    runtime = Runtime()
    with pytest.raises(ValueError, match="原恢复入口"):
        timing.prepare_source(run, runtime=runtime, authorization_path="original-auth")
    assert not runtime.calls and path.read_bytes() == before


def test_new_source_and_matching_profile_preserve_original_arguments(tmp_path):
    run, runtime = tmp_path / "new", Runtime()
    kwargs = dict(authorization_path="same-auth", source_path="source.txt", acquisition_receipt=None,
        title="New story", book_id="book", scope="whole", source_kind="original", catalog_path="catalog.json")
    brief = dict(max_duration_seconds=90, target_duration_seconds=120)
    timing.prepare_source(run, runtime=runtime, brief=brief, **kwargs)
    args, actual = runtime.calls[0]
    assert args == (run,)
    assert {key: item for key, item in actual.items() if key != "brief"} == kwargs
    assert actual["brief"] == timing.apply_brief(brief) and not run.exists()
    run.mkdir()
    binding = run / "BINDING.json"
    binding.write_text(json.dumps({"brief": actual["brief"]}, ensure_ascii=False), encoding="utf-8")
    before = binding.read_bytes()
    timing.prepare_source(run, runtime=runtime, **kwargs)
    assert runtime.calls[1][1]["brief"] == actual["brief"] and binding.read_bytes() == before


def materials(payload):
    return json.loads(payload["messages"][-1]["content"])


def test_actual_five_stage_builders_receive_identical_complete_profiles():
    source = {"text": "A daughter prepares to leave; her father supports her and hands over a ticket.", "binding_id": "source"}
    draft, natural = "完整稿：女儿说明准备，父亲递票支持。", "S01，7秒：女儿看父亲说明准备，父亲递票并回应，听者意外并行显现，票到位且对白结束即收段。"
    brief = timing.apply_brief({"source_kind": "original", "target_duration_seconds": 120})
    extract_payload = director.build_extract_review_payload(source["text"], draft, natural, brief=brief)
    native = dict(verdict="pass", whole_text_reviewed=True, faithful_to_natural=True,
        summary="Explicit offline fake assessment; not real model acceptance.",
        checks={key: "Explicit fake full-content check." for key in REVIEW_DIMENSIONS}, issues=[],
        segments=[dict(segment_id="S01", duration_seconds=7,
            prompt="女儿看父亲说已准备好，父亲同时递票并回应；女儿在递票时意外地看向他，票到位且对白结束即收段。",
            source_notes="offline fake S01")])
    extract = director.parse_extract_review(json.dumps(native, ensure_ascii=False), source_binding="source",
        draft_binding=hashlib.sha256(draft.encode()).hexdigest(), materials=materials(extract_payload), native_response_ref="a" * 64)
    payloads = [writer.build_writer_payload(source, brief=brief), writer.build_review_payload(source, draft, brief=brief),
        materials(director.build_natural_director_payload(source["text"], draft, brief=brief)), materials(extract_payload),
        materials(director.build_final_review_payload(source["text"], draft, natural, extract, brief=brief))]
    assert all(payload["brief"] == brief for payload in payloads)
    assert all(payload["brief"]["performance_timing_reference"] == timing.profile() for payload in payloads)
    request = payloads[-1]["video_requests"]["requests"][0]
    assert request["duration_seconds"] == 7 and request["request"]["duration"] == 7
    assert request["request"]["content"][0]["text"] == native["segments"][0]["prompt"]


def test_cli_new_prepare_uses_adapter_and_original_auth_gate(tmp_path, monkeypatch, capsys):
    authorization = tmp_path / "AUTHORIZATION.json"
    authorization.write_text("{}", encoding="utf-8")
    runtime = Runtime()
    monkeypatch.setattr(timing, "_runtime", lambda: runtime)
    argv = ["source-prepare", "--source-run-dir", str(tmp_path / "new"), "--source-path", "source.txt",
        "--source-kind", "original", "--authorization-path", str(authorization)]
    assert cli.main(argv) == 0
    assert runtime.calls[0][1]["authorization_path"] == authorization
    assert runtime.calls[0][1]["brief"]["performance_timing_reference"] == timing.profile()
    capsys.readouterr()
    runtime.calls.clear()
    argv[argv.index(str(authorization))] = str(tmp_path / "missing.json")
    assert cli.main(argv) == 1 and not runtime.calls
    assert json.loads(capsys.readouterr().out)["automatic_media_submit"] is False


@pytest.mark.parametrize("argv", [["execute", "--run-dir", "old"], ["inspect", "--run-dir", "old"],
    ["preview", "--run-dir", "old"], ["source-execute", "--source-run-dir", "old-source", "--run-dir", "old",
        "--authorization-path", "old-auth.json"]])
def test_legacy_commands_delegate_unchanged_without_profile_injection(monkeypatch, argv):
    calls = []
    monkeypatch.setattr(legacy_cli, "main", lambda actual: calls.append(actual) or 7)
    monkeypatch.setattr(timing, "prepare_source", lambda **kwargs: pytest.fail("cannot migrate old run"))
    assert cli.main(argv) == 7 and calls == [argv]
