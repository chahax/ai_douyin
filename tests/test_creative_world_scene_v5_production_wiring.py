"""New fixed selectors/adapters only; synthetic proof and MockTransport, no GPU.

No real text adoption or content quality is asserted by these fixtures. Native
production contracts, installed SDK/raw/SQL verification and graph rebuilding
are exercised independently of their synthetic source-verifier replacement.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
import pytest
from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
from scripts import creative_world_scene_production_probe_v2 as production
from scripts import creative_world_scene_media_probe_v3 as media
from scripts import run_creative_world_scene_video_submit_v2 as submit
from tests.test_creative_world_scene_production_probe_v1 import (
    parent_fixture, whole_direction, first_performance, review_document)
from tests.test_creative_world_scene_media_probe_v1 import case
from tests.test_creative_world_scene_media_probe_v2 import encoded_case
from tests.test_creative_world_scene_video_submit_v1 import factory, put


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("no real network or GPU in wiring tests")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(production.base.clients.text, "role_config", lambda role: SimpleNamespace(
        model="MiniMax-M3.1-Flash-Preview" if role == "writer" else "deepseek-flash", api_key="offline-test-key",
        base_url="https://api.minimax.cn/v1" if role == "writer" else "https://api.deepseek.com/v1"))


@pytest.mark.parametrize("version", [5, 6, 7])
def test_fixed_v5_selector_executes_original_verifier_and_never_uses_ready_flag(tmp_path, monkeypatch, version):
    proof = parent_fixture(tmp_path); root = Path(proof["root"])
    put(root / "STATE.json", {"schema": f"creative_world_scene_live_session/v{version}/state", "status": "text_ready_for_director"})
    calls = []
    monkeypatch.setattr(registry, f"_verify_v{version}", lambda r: (calls.append(str(r)) or deepcopy(proof)))
    for other in ({5, 6, 7} - {version}):
        monkeypatch.setattr(registry, f"_verify_v{other}", lambda r: (_ for _ in ()).throw(AssertionError("wrong native version")))
    def old_is_not_v5(*a): raise AssertionError("v5 must not fall back to legacy selector")
    monkeypatch.setattr(registry.legacy, "verify_text_handoff", old_is_not_v5)
    checked = registry.verify_text_handoff(root)
    assert calls == [str(root)] and checked["verifier_entry"]["native_verifier_always_executed"]
    assert str(Path(registry.__file__).resolve()) in checked["source_files"]
    proof["accepted"] = False
    with pytest.raises(ValueError, match="complete native proof"): registry.verify_text_handoff(root)
    put(root / "STATE.json", {"schema": "unregistered/state", "status": "text_ready_for_director"})
    with pytest.raises(ValueError, match="unsupported"): registry.verify_text_handoff(root)
    assert len(calls) == 2


@pytest.mark.parametrize("derived_native", [False, True])
def test_new_production_entry_installed_sdk_native_handoff_and_frozen_selector(tmp_path, monkeypatch, derived_native):
    base = production.base; parent = parent_fixture(tmp_path); material = base.load_material(parent)
    if derived_native:
        from tests.test_creative_world_scene_v7_production_source import derived_fixture
        parent = derived_fixture(parent); material = production.load_material(parent)
    monkeypatch.setattr(registry, "verify_text_handoff", lambda r: deepcopy(parent))
    # All exclusive offline claims stay under this synthetic test directory.
    original_paths = base.policy.successor_paths
    monkeypatch.setattr(base.policy, "successor_paths", lambda project, p, h: original_paths(tmp_path, p, h))
    counter = base.CountedExecution(tmp_path / "counter"); base.write(tmp_path / "counter/AUTH.json", {"OFFLINE": True}, True)
    counter.initialize(tmp_path / "counter/AUTH.json"); counter.begin_round("round21", "synthetic fixed-registry wiring")
    cfg = production.Config(str(tmp_path / "production"), parent["root"], "offline-v5-production", str(tmp_path / "AUTH.json"),
        str(tmp_path / "counter"), "round21", dispatch_lock_path=str(tmp_path / "dispatch.lock"))
    holder, sent = {}, []
    def builder(request):
        def handler(outgoing):
            label = holder["s"].pending_intent["label"]; sent.append(label)
            direction = whole_direction(material); performance = first_performance(material, direction)
            value = direction if label.startswith("whole_direction") else performance if label.startswith("first_performance") else review_document(
                production.review_request(material, material["values"]["profile"], direction, performance))
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline-tool", "type": "function",
                "function": {"name": base.clients.text.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
            return httpx.Response(200, json={"id": "offline-" + label, "model": request["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}})
        return base.clients.make_client_factory(request, http_client_factory=lambda **kw: httpx.Client(
            transport=httpx.MockTransport(handler), verify=False, **kw))
    s = production.Session(cfg, client_factory_builder=builder); holder["s"] = s
    preview = s.preview(); base.write(cfg.authorization_path, s.authorization_template(preview), True); s.prepare()
    assert base.read(s.root / "PRODUCTION_FREEZE.json")["files"][str(Path(registry.__file__).resolve())] == base.sha(registry.__file__)
    assert s.run()["status"] == "first_segment_ready_for_media"
    assert sent == ["whole_direction_01", "first_performance_01", "first_production_review_01"]
    proof = production.verify_first_segment_handoff(s.root)
    assert proof["valid"] and proof["entry_binding"] == production.entry_binding()
    assert proof["spend"]["effective_calls_started"] == parent["inherited"]["calls_started"] + 3
    assert proof["schema"] == base.VERSION + "/verified_first_segment"
    auth = base.read(cfg.authorization_path); auth["entry_binding"]["fixed_registry_version"] = "wrong"
    base.write(cfg.authorization_path, auth)
    with pytest.raises(ValueError, match="frozen original source|fixed v2"): production.verify_first_segment_handoff(s.root)
    assert len(sent) == 3


def _fixed_media(case, monkeypatch):
    cfg, text, prod, snap = encoded_case(case)
    # Preserve existing asset bytes, but no shared story ledger/template writes.
    tmp = Path(cfg.output_root).parent
    ledger = media.base.read(cfg.ledger_path); ledger["story_id"] = prod["story_id"]
    ledger.update(failure_limit=10, failures_used=1, known_rejections=1, technical_failures=0,
        observed_local_video_submissions=2, not_a_new_story_reset=True, old_receipts_and_unknowns_retained=True)
    put(tmp / "ledger.json", ledger); cfg = replace(cfg, ledger_path=str(tmp / "ledger.json"))
    prod["entry_binding"] = production.entry_binding()
    text["source_files"] = {text["handoff_path"]: text["handoff_sha256"]}
    monkeypatch.setattr(registry, "verify_text_handoff", lambda r: deepcopy(text))
    monkeypatch.setattr(production, "verify_first_segment_handoff", lambda r, **kw: deepcopy(prod))
    monkeypatch.setattr(media.base, "inspect_service", lambda: deepcopy(snap))
    return cfg, text, prod


def test_fixed_media_prepares_rebuilds_and_rejects_altered_new_entry(case, monkeypatch):
    cfg, text, prod = _fixed_media(case, monkeypatch)
    prepared = media.prepare(cfg); verified = media.verify_prepared(cfg.output_root)
    assert prepared["media_submissions"] == 0 and not prepared["media_claim_created"]
    assert verified["production_verified"]["entry_binding"] == production.entry_binding()
    assert verified["base_prepared"]["synthetic"] is False  # fixed real symbols were replaced only in this synthetic test
    assert verified["graph"]["condition"]["inputs"]["prompt"] == prod["actual_video_prompt"]
    assert all(str(Path(p).resolve()) in verified["source_files"] for p in (media.__file__, production.__file__, registry.__file__))
    entry = media.base.read(Path(cfg.output_root) / "MEDIA_ENTRY_V3.json"); entry["fixed_text_registry_version"] = "wrong"
    put(Path(cfg.output_root) / "MEDIA_ENTRY_V3.json", entry)
    with pytest.raises(ValueError, match="fixed media entry"): media.verify_prepared(cfg.output_root)
    assert not (Path(cfg.output_root) / "RUN_CLAIM.json").exists()


def test_media_has_no_offline_injection_and_rejects_nonfixed_production(case, monkeypatch):
    cfg, text, prod = _fixed_media(case, monkeypatch)
    with pytest.raises(TypeError): media.prepare(cfg, offline_test=True)
    prod["entry_binding"]["fixed_registry_version"] = "legacy"
    with pytest.raises(ValueError, match="fixed-entry"): media.prepare(cfg)
    assert not Path(cfg.output_root).exists()


def test_fixed_submit_cli_preserves_global_one_video_claim_across_new_roots(factory, monkeypatch):
    build, calls, _, _ = factory
    first, *_ = build("first-new"); second, *_ = build("second-new", production_sha="d" * 64)
    # The original submitter fixture keeps all claims/network under a temporary
    # project. Only this fixed function symbol is replaced, not a CLI option.
    monkeypatch.setattr(submit, "__file__", submit.base.__file__)
    monkeypatch.setattr(media, "verify_prepared", lambda root: deepcopy(first.verifier(root)))
    def new_session(old):
        result = submit.submitter(old.config, client=old.client, counter=old.counter,
            project=old.project, metadata_probe=old.metadata_probe)
        put(old.config.authorization_path, result.authorization_template()); return result
    a, b = new_session(first), new_session(second)
    assert submit.AUTHORIZATION_ID == submit.base.AUTHORIZATION_ID == "world_scene_live_20261015_one_video_user_authorization_v1"
    assert str(Path(submit.__file__).resolve()) in a.preview()["source_files"]
    assert not calls
    a.submit()
    with pytest.raises(ValueError, match="already claimed"): b.submit()
    assert sum(method == "POST" for method, _ in calls) == 1
    assert not (b.root / "RUN_CLAIM.json").exists()
    with pytest.raises(ValueError, match="fixed media"): submit.submitter(first.config, verifier=lambda r: {"accepted": True})
