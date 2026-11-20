"""Offline content-end preparation and real text-payload propagation checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_content_end_natural_director_v1 as cli
from scripts import run_natural_director_v10 as legacy_cli
from src.content_factory import content_end_pacing_v1 as pacing
from src.content_factory import natural_director_contracts_v10 as director
from src.content_factory import novel_agent_roles_v8 as writer
from src.content_factory.novel_logic_contracts_v4 import REVIEW_DIMENSIONS


def test_default_brief_and_policy_are_deep_copies_with_stable_hash():
    original = {"target_duration_seconds": 120, "requirements": ["natural dialogue"]}
    before = deepcopy(original)
    result = pacing.apply_brief(original)
    assert result["duration_policy"] == "content_driven"
    assert result["target_duration_seconds"] == 120 and original == before
    first = pacing.policy()
    body = {key: value for key, value in first.items() if key != "sha256"}
    actual_sha = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert first["sha256"] == actual_sha
    result["requirements"].append("changed")
    result["content_end_pacing"]["requirements"]["content_end"] = "changed"
    assert pacing.policy() == first and original == before
    assert pacing.apply_brief(None)["content_end_pacing"] == first


def test_all_explicit_duration_bounds_and_other_settings_are_preserved():
    original = dict(min_duration_seconds=105, max_duration_seconds=135,
        target_duration_seconds=120, duration_tolerance_seconds=15, duration_policy="hard_target",
        nested={"budget": 20}, media_authorized=False)
    result = pacing.apply_brief(original)
    assert all(result[key] == value for key, value in original.items())
    assert pacing.apply_brief(result) == result
    assert result["content_end_pacing"]["ordinary_tail_padding_seconds"] == 0
    assert "显式target_duration_seconds与duration_tolerance_seconds" in result["content_end_pacing"]["requirements"]["hard_constraints"]


def test_different_or_tampered_existing_policy_is_rejected():
    brief = pacing.apply_brief({})
    brief["content_end_pacing"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="不能覆盖"):
        pacing.apply_brief(brief)


class Runtime:
    def __init__(self):
        self.calls = []
    def prepare_source(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"status": "prepared"}


def test_new_source_delegates_every_original_argument_without_new_authority(tmp_path, monkeypatch):
    runtime = Runtime()
    monkeypatch.setattr(pacing, "_runtime", lambda: runtime)
    kwargs = dict(authorization_path=tmp_path / "AUTH.json", source_path=tmp_path / "source.txt",
        acquisition_receipt=None, title="New story", book_id="book", scope="whole",
        source_kind="original", catalog_path=tmp_path / "catalog.json")
    run = tmp_path / "new"
    assert pacing.prepare_source(run, brief={"max_duration_seconds": 90}, **kwargs)["status"] == "prepared"
    args, received = runtime.calls[0]
    assert args == (run,)
    assert {key: value for key, value in received.items() if key != "brief"} == kwargs
    assert received["brief"]["max_duration_seconds"] == 90
    assert received["brief"]["content_end_pacing"] == pacing.policy()
    assert not run.exists()


def test_old_source_without_new_policy_is_rejected_without_writing(tmp_path):
    run = tmp_path / "old"
    run.mkdir()
    binding = run / "BINDING.json"
    binding.write_text('{"brief":{"target_duration_seconds":120},"budget":{"max_calls":20}}', encoding="utf-8")
    before = {path.name: path.read_bytes() for path in run.iterdir()}
    runtime = Runtime()
    with pytest.raises(ValueError, match="原恢复入口"):
        pacing.prepare_source(run, runtime=runtime, brief={"target_duration_seconds": 120}, authorization_path="same-auth")
    assert not runtime.calls
    assert {path.name: path.read_bytes() for path in run.iterdir()} == before


def test_matching_new_policy_source_can_delegate_its_unchanged_frozen_brief(tmp_path):
    run = tmp_path / "current"
    run.mkdir()
    brief = pacing.apply_brief({"source_kind": "original", "max_duration_seconds": 90})
    path = run / "BINDING.json"
    path.write_text(json.dumps({"brief": brief}, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    runtime = Runtime()
    pacing.prepare_source(run, runtime=runtime, source_kind="original", authorization_path="same-auth")
    assert runtime.calls[0][1]["brief"] == brief and path.read_bytes() == before


def materials(payload):
    return json.loads(payload["messages"][-1]["content"])


def test_actual_writer_review_natural_extract_and_final_receive_same_policy():
    source = {"text": "An original story: a daughter leaves, her parent hands her a ticket.", "binding_id": "source"}
    draft = "完整稿：女儿说已找好房间，父亲回应并递票。"
    natural = "服务段S01，7秒：女儿说明房间找好了，父亲边取票边回应并推票；女儿在票推出时意外地看向父亲，票到位、对白结束即收段。"
    brief = pacing.apply_brief({"source_kind": "original", "target_duration_seconds": 120})
    native = dict(verdict="pass", whole_text_reviewed=True, faithful_to_natural=True,
        summary="Explicit offline fixture assessment, not a model pass.",
        checks={dimension: "Explicit fake complete-content check." for dimension in REVIEW_DIMENSIONS},
        issues=[], segments=[dict(segment_id="S01", duration_seconds=7,
            prompt="女儿看父亲说房间找好了。父亲看着她，取票与回应并行，把票推到她面前；女儿在推票时意外地看向他，票到位且对白结束即收段。",
            source_notes="对应完整自然导演S01；仅离线fixture。")])
    extract_payload = director.build_extract_review_payload(source["text"], draft, natural, brief=brief)
    extract = director.parse_extract_review(json.dumps(native, ensure_ascii=False),
        source_binding="source", draft_binding=hashlib.sha256(draft.encode()).hexdigest(),
        materials=materials(extract_payload), native_response_ref="a" * 64)
    payloads = [writer.build_writer_payload(source, brief=brief),
        writer.build_review_payload(source, draft, brief=brief),
        materials(director.build_natural_director_payload(source["text"], draft, brief=brief)),
        materials(extract_payload),
        materials(director.build_final_review_payload(source["text"], draft, natural, extract, brief=brief))]
    assert all(payload["brief"] == brief for payload in payloads)
    requests = payloads[-1]["video_requests"]["requests"]
    assert requests[0]["duration_seconds"] == 7
    assert requests[0]["request"]["duration"] == 7
    assert requests[0]["request"]["content"][0]["text"] == native["segments"][0]["prompt"]


def test_legacy_explicit_target_tolerance_still_enforces_hard_range():
    brief = pacing.apply_brief(dict(target_duration_seconds=120, duration_tolerance_seconds=15))
    errors = director._segment_errors([dict(segment_id="S01", duration_seconds=7,
        prompt="完整互动", source_notes="offline")], brief)
    assert any(error["code"] == "TOTAL_DURATION" for error in errors)


def test_new_cli_source_prepare_uses_adapter_and_original_auth_check(tmp_path, monkeypatch, capsys):
    authorization = tmp_path / "AUTHORIZATION.json"
    authorization.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli.pacing, "prepare_source", lambda **kwargs: calls.append(kwargs) or {"status": "prepared"})
    argv = ["source-prepare", "--source-run-dir", "new", "--authorization-path", str(authorization),
            "--source-kind", "original", "--source-path", "source.txt"]
    assert cli.main(argv) == 0
    assert calls[0]["authorization_path"] == authorization
    assert calls[0]["source_kind"] == "original" and "brief_json" not in calls[0]
    capsys.readouterr()
    calls.clear()
    argv[argv.index(str(authorization))] = str(tmp_path / "missing.json")
    assert cli.main(argv) == 1 and not calls
    assert json.loads(capsys.readouterr().out)["automatic_media_submit"] is False


@pytest.mark.parametrize("argv", [["execute", "--run-dir", "old"], ["preview", "--run-dir", "old"],
    ["inspect", "--run-dir", "old"], ["source-execute", "--source-run-dir", "source",
        "--run-dir", "old", "--authorization-path", "old-auth.json"]])
def test_existing_commands_delegate_verbatim_without_policy_injection(monkeypatch, argv):
    calls = []
    monkeypatch.setattr(legacy_cli, "main", lambda actual: calls.append(actual) or 7)
    monkeypatch.setattr(pacing, "prepare_source", lambda **kwargs: pytest.fail("old run cannot inject new policy"))
    assert cli.main(argv) == 7 and calls == [argv]


def test_new_cli_does_not_offer_budget_or_media_override():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["source-prepare", "--source-run-dir", "new", "--source-path", "source.txt",
            "--authorization-path", "auth.json", "--submit-video"])
