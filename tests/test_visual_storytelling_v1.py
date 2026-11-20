"""Offline wiring/provenance tests; fake verdicts do not prove creative quality."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from scripts import run_natural_director_v10 as cli
from src.content_factory import visual_storytelling_v1 as visual
from src.content_factory import performance_timing_reference_v2 as timing
from src.content_factory import natural_director_contracts_v10 as contracts
from src.content_factory import novel_agent_roles_v8 as writer

F = runpy.run_path(str(Path(__file__).with_name("test_natural_director_pipeline_v10.py")))
C = F["C"]
pipe, fx = F["pipe"], F["fx"]


def test_policy_is_independent_hashed_and_preserves_user_constraints():
    brief = {"source_kind": "novel", "max_duration_seconds": 90,
             "location_change_authorization": None, "custom": {"keep": [1]}}
    before = deepcopy(brief)
    applied = visual.apply_brief(brief)
    assert brief == before and all(applied[k] == v for k, v in before.items())
    profile = applied[visual.BRIEF_KEY]
    assert len(profile["requirements"]) == 7
    assert profile["sha256"] == contracts.canonical_sha256({k: v for k, v in profile.items() if k != "sha256"})
    assert visual.apply_brief(applied) == applied
    applied[visual.BRIEF_KEY]["requirements"]["opening_information"]["requirement"] = "changed"
    with pytest.raises(ValueError, match="不能覆盖"):
        visual.apply_brief(applied)
    assert visual.profile() != profile
    assert visual.profile()["requirements"]["opening_information"]["requirement"] != "changed"


def test_existing_run_is_not_migrated_or_written(tmp_path):
    run = tmp_path / "old"
    run.mkdir()
    binding = run / "BINDING.json"
    binding.write_text(json.dumps({"brief": timing.apply_brief({})}), encoding="utf-8")
    before = binding.read_bytes()
    calls = []
    runtime = SimpleNamespace(prepare_source=lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValueError, match="原恢复入口"):
        visual.prepare_source(run, runtime=runtime)
    assert not calls and binding.read_bytes() == before


def test_matching_frozen_run_resumes_without_replacing_brief(tmp_path):
    run = tmp_path / "new"
    run.mkdir()
    brief = visual.apply_brief({"source_kind": "novel", "max_duration_seconds": 30})
    binding = run / "BINDING.json"
    binding.write_text(json.dumps({"brief": brief}), encoding="utf-8")
    before = binding.read_bytes()
    calls = []
    runtime = SimpleNamespace(prepare_source=lambda *a, **kw: calls.append(kw))
    visual.prepare_source(run, runtime=runtime)
    assert calls[0]["brief"] == brief and binding.read_bytes() == before
    with pytest.raises(ValueError, match="不能覆盖"):
        visual.prepare_source(run, runtime=runtime, brief={"max_duration_seconds": 60})


CASES = [
    ("family", "novel", "老屋门口，母亲替儿子整理衣领，儿子叫妈并说今晚要走。傍晚阴天，窗边柔光。"),
    ("workplace", "novel", "冷白灯办公室，员工把调岗文件放到经理面前，问生效日期；经理指向日期回应。"),
    ("repair_shop", "novel", "修理铺师徒对着故障灯交谈，徒弟报告温度，师傅停手核对仪表。"),
    ("solitude", "original", "夜间车站，单人听完电话才收起手机，稳定中景呈现决定上车，环境维持冷光。"),
    ("silence", "original", "病房内两人听完检查结果后沉默，视线从报告移向彼此，停顿承载共同决定。"),
]


@pytest.mark.parametrize("name,kind,story", CASES)
def test_five_real_builders_keep_case_source_rules_and_exact_prompts(name, kind, story):
    brief = visual.apply_brief({"source_kind": kind, "max_duration_seconds": 30})
    source = {"text": story, "binding_id": name, "book_id": "book-" + name if kind == "novel" else ""}
    payload = contracts.build_extract_review_payload(story, story, story, brief=brief)
    native = C["extract_native"]()
    native["segments"] = [{"segment_id": "A", "duration_seconds": 8, "prompt": story,
                           "source_notes": "Offline constructed fixture; no model judgment."}]
    extract = contracts.parse_extract_review(json.dumps(native, ensure_ascii=False),
        source_binding=name, draft_binding=hashlib.sha256(story.encode()).hexdigest(),
        materials=C["materials"](payload), native_response_ref="a" * 64)
    final = C["materials"](contracts.build_final_review_payload(story, story, story, extract, brief=brief))
    stages = [writer.build_writer_payload(source, brief=brief),
              writer.build_review_payload(source, story, brief=brief),
              C["materials"](contracts.build_natural_director_payload(story, story, brief=brief)),
              C["materials"](payload), final]
    assert all(s["brief"] == brief for s in stages)
    assert stages[0]["source"] == source and stages[1]["source"] == source
    assert all(s["source_text"] == story for s in stages[2:])
    actual = final["video_requests"]["requests"][0]["request"]
    assert actual["content"][0]["text"] == story
    assert actual["duration"] == 8
    # Altering a rule after extraction cannot be passed off as the reviewed brief.
    altered = deepcopy(brief)
    altered[visual.BRIEF_KEY]["requirements"].pop("motivated_camera_continuity")
    with pytest.raises(ValueError):
        contracts.build_final_review_payload(story, story, story, extract, brief=altered)


@pytest.fixture
def prepared_visual(tmp_path, monkeypatch):
    registry = tmp_path / "canonical"
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", registry)
    monkeypatch.setattr(pipe.parent, "CANONICAL_REGISTRY", registry)
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *a, **kw: [])
    source = tmp_path / "source.txt"
    source.write_text("Original story about choosing and answering.", encoding="utf-8")
    old = tmp_path / "writer"
    authorization = F["auth"](tmp_path, old)
    visual.prepare_source(old, runtime=pipe, authorization_path=authorization,
        source_path=source, source_kind="original", title="Offline visual route",
        brief={"max_duration_seconds": 23})
    client = fx.FakeClients(F["F"]["success_values"]()[:2])
    assert pipe.execute_writer_only(old, clients=client)["writer_ready"]
    run = tmp_path / "natural"
    pipe.prepare(run, parent_run=old, authorization_path=authorization)
    return old, run, client


def test_file_backed_pipeline_binds_same_profile_through_all_five_requests(prepared_visual):
    old, run, writer_client = prepared_visual
    before = F["snapshot"](old)
    client = fx.FakeClients(F["values"]())
    result = pipe.execute(run, clients=client)
    assert result["status"] == "text_ready_for_production", result["blockers"]
    calls = writer_client.calls + client.calls
    assert len(calls) == 5
    for call in calls:
        materials = json.loads(call["messages"][-1]["content"])
        assert materials["brief"][visual.BRIEF_KEY] == visual.profile()
    handoff = pipe.core._read(run / "PRODUCTION_HANDOFF.json")
    pipe.contracts.validate_handoff_for_dispatch(handoff)
    assert F["snapshot"](old) == before
    # Changing compiled video text after native final review must block dispatch.
    request_path = run / "REQUEST_003.json"
    original = request_path.read_bytes()
    request_path.write_bytes(original + b" ")
    assert pipe.inspect(run)["status"] == "evidence_invalid"


def test_source_scene_error_is_returned_to_writer_not_silently_fixed(prepared_visual):
    _, run, _ = prepared_visual
    verdict = C["final_native"]()
    verdict.update(verdict="revise", issues=[{"severity": "major", "location": "opening/location",
        "evidence": "Fixture: source station replaced with a home without brief authorization.",
        "suggestion": "Restore the source scene and rereview the full screenplay.",
        "responsibility_layer": "writer"}])
    client = fx.FakeClients(F["values"]()[:2] + [fx.result(verdict, "director")])
    result = pipe.execute(run, clients=client)
    assert result["status"] == "upstream_writer_revision_required"
    assert len(client.calls) == 3 and not (run / "PRODUCTION_HANDOFF.json").exists()


def test_cli_legacy_source_preparation_does_not_inject_new_rules(tmp_path, monkeypatch, capsys):
    run = tmp_path / "old"
    run.mkdir()
    (run / "BINDING.json").write_text('{"brief":{}}', encoding="utf-8")
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(pipe, "prepare_source", lambda **kw: calls.append(kw) or {"status": "prepared"})
    assert cli.main(["source-prepare", "--source-run-dir", str(run), "--source-path", "source.txt",
                     "--authorization-path", str(auth)]) == 0
    capsys.readouterr()
    assert "brief" not in calls[0]
