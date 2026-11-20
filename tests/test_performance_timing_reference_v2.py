from copy import deepcopy
import hashlib
import json

import pytest

from scripts import run_performance_timing_natural_director_v2 as cli
from scripts import run_natural_director_v10 as legacy_cli
from src.content_factory import performance_timing_reference_v2 as timing
from src.content_factory import performance_timing_reference_v1 as old_timing
from src.content_factory import natural_director_contracts_v10 as director
from src.content_factory import novel_agent_roles_v8 as writer
from src.content_factory.novel_logic_contracts_v4 import REVIEW_DIMENSIONS


def test_profile_hash_deep_copy_and_distinct_change_extra_windows():
    original = timing.profile()
    body = {key: value for key, value in original.items() if key != "sha256"}
    assert original["sha256"] == hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert original["hard_duration_gate"] is False and original["content_classifier"] is False
    confirmation = original["reaction_reference_seconds"]["key_information_understood_confirmation"]
    assert confirmation["visible_change"] == {"min": 0.3, "max": 0.7}
    assert confirmation["extra_after_dialogue"] == {"min": 0, "max": 0.3, "default": 0}
    changed = timing.profile()
    changed["requirements"]["scope"] = "changed"
    assert timing.profile() == original


@pytest.mark.parametrize("state,slow,fast", [("ordinary_explanation",3.5,4.5), ("brisk_exchange",4,5),
    ("measured_emphasis",3,4), ("smiling_or_teary_fluent",3,4), ("audible_choking",2.5,3.5)])
def test_spoken_chinese_units_rate_reciprocal_and_only_explicit_pause(state, slow, fast):
    text = "我没问这个，票买好了。"
    result = timing.estimate_dialogue(text, state, pause_seconds=0.2)
    assert result["units"] == 9 and result["spoken_text"] == text
    assert result["min_seconds"] == pytest.approx(9 / fast + 0.2)
    assert result["max_seconds"] == pytest.approx(9 / slow + 0.2)
    assert result["count_basis"] == timing.profile()["count_basis"] == "declared_hanzi_reading_proxy_not_audio_measurement"
    assert result["seconds_per_unit"] == pytest.approx({"min": 1 / fast, "max": 1 / slow})
    assert timing.profile()["dialogue_delivery_states"][state]["seconds_per_unit"] == result["seconds_per_unit"]
    plain = timing.estimate_dialogue("我没问这个票买好了", state)
    assert plain["min_seconds"] == pytest.approx(result["min_seconds"] - 0.2)
    assert result["estimation_complete"] and not result["requires_reading_confirmation"]
    assert result["quality_gate"] is False and result["changes_text_or_duration"] is False


@pytest.mark.parametrize("text", ["头3个月", "AI帮我", "三kg", "票价三元/张", "百分之三%", "温度三℃"])
def test_unexpanded_readings_are_partial_and_never_complete_duration(text):
    result = timing.estimate_dialogue(text, "ordinary_explanation")
    assert result["requires_reading_confirmation"] and not result["estimation_complete"]
    assert result["min_seconds"] is None and result["max_seconds"] is None
    assert result["partial_hanzi_seconds"] is not None and result["unexpanded_characters"]


@pytest.mark.parametrize("pause", [True, False, -0.1, float("nan"), float("inf"), "0.2"])
def test_pause_requires_nonnegative_finite_number(pause):
    with pytest.raises(ValueError, match="pause_seconds"):
        timing.estimate_dialogue("票买好了", "brisk_exchange", pause)


def test_tears_or_emotion_name_does_not_automatically_select_choking():
    assert timing.estimate_dialogue("想回来就回来", "smiling_or_teary_fluent")["units_per_second"] == {"min": 3, "max": 4}
    with pytest.raises(ValueError, match="不能按"):
        timing.estimate_dialogue("票买好了", "愧疚")
    result = timing.estimate_dialogue("头三个月，一共三百元", "ordinary_explanation")
    assert result["estimation_complete"]


def test_brief_hard_bounds_preserved_and_old_or_tampered_profile_refused():
    original = dict(min_duration_seconds=105, max_duration_seconds=135, target_duration_seconds=120,
        duration_tolerance_seconds=15, duration_policy="hard_target", custom={"keep": [1]})
    before = deepcopy(original)
    current = timing.apply_brief(original)
    assert all(current[key] == value for key, value in original.items()) and original == before
    assert timing.apply_brief(current) == current
    with pytest.raises(ValueError, match="不能覆盖"):
        timing.apply_brief(old_timing.apply_brief({}))
    current["performance_timing_reference"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="不能覆盖"):
        timing.apply_brief(current)


class Runtime:
    def __init__(self):
        self.calls = []
    def prepare_source(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"status": "prepared"}


def test_new_source_authorization_passthrough_and_old_version_no_writes(tmp_path):
    run, runtime = tmp_path / "new", Runtime()
    kwargs = dict(authorization_path="same-auth", source_path="source.txt", title="New story",
        book_id="book", scope="whole", source_kind="original", catalog_path="catalog.json")
    timing.prepare_source(run, runtime=runtime, brief={"max_duration_seconds": 90}, **kwargs)
    args, actual = runtime.calls[0]
    assert args == (run,) and {key: value for key, value in actual.items() if key != "brief"} == kwargs
    assert actual["brief"]["performance_timing_reference"] == timing.profile()
    assert not run.exists()
    run.mkdir()
    binding = run / "BINDING.json"
    binding.write_text(json.dumps({"brief": old_timing.apply_brief({})}, ensure_ascii=False), encoding="utf-8")
    before = binding.read_bytes()
    with pytest.raises(ValueError, match="原恢复入口"):
        timing.prepare_source(run, runtime=runtime, **kwargs)
    assert len(runtime.calls) == 1 and binding.read_bytes() == before


def materials(payload):
    return json.loads(payload["messages"][-1]["content"])


def test_real_five_stage_builders_consume_identical_v2_profile():
    source = {"text": "The daughter prepares to leave and her father hands her a ticket.", "binding_id": "source"}
    draft, natural = "完整稿：父亲回应并递票。", "S01，7秒：女儿说明准备，父亲回应并递票，意外在推票时显现，票到位且对白结束即收段。"
    brief = timing.apply_brief({"source_kind": "original", "target_duration_seconds": 120})
    extract_payload = director.build_extract_review_payload(source["text"], draft, natural, brief=brief)
    native = dict(verdict="pass", whole_text_reviewed=True, faithful_to_natural=True,
        summary="Offline fake assessment only.", checks={key: "Explicit fake full-content check." for key in REVIEW_DIMENSIONS},
        issues=[], segments=[dict(segment_id="S01", duration_seconds=7,
            prompt="女儿说明已准备好，父亲看她并回应递票；她在票推出时意外地看父亲，票到位且对白结束即收段。",
            source_notes="offline fixture S01")])
    extract = director.parse_extract_review(json.dumps(native, ensure_ascii=False), source_binding="source",
        draft_binding=hashlib.sha256(draft.encode()).hexdigest(), materials=materials(extract_payload), native_response_ref="a" * 64)
    payloads = [writer.build_writer_payload(source, brief=brief), writer.build_review_payload(source, draft, brief=brief),
        materials(director.build_natural_director_payload(source["text"], draft, brief=brief)), materials(extract_payload),
        materials(director.build_final_review_payload(source["text"], draft, natural, extract, brief=brief))]
    assert all(payload["brief"] == brief for payload in payloads)
    assert payloads[-1]["video_requests"]["requests"][0]["request"]["duration"] == 7


def test_cli_new_prepare_checks_original_auth_and_old_execute_stays_unchanged(tmp_path, monkeypatch, capsys):
    auth = tmp_path / "AUTH.json"
    auth.write_text("{}", encoding="utf-8")
    runtime = Runtime()
    monkeypatch.setattr(timing, "_runtime", lambda: runtime)
    args = ["source-prepare", "--source-run-dir", str(tmp_path / "new"), "--source-path", "source.txt",
        "--source-kind", "original", "--authorization-path", str(auth)]
    assert cli.main(args) == 0
    assert runtime.calls[0][1]["authorization_path"] == auth
    assert runtime.calls[0][1]["brief"]["performance_timing_reference"] == timing.profile()
    capsys.readouterr()
    runtime.calls.clear()
    args[args.index(str(auth))] = str(tmp_path / "missing.json")
    assert cli.main(args) == 1 and not runtime.calls
    capsys.readouterr()
    delegated = []
    monkeypatch.setattr(legacy_cli, "main", lambda argv: delegated.append(argv) or 7)
    old = ["execute", "--run-dir", "old"]
    assert cli.main(old) == 7 and delegated == [old]
