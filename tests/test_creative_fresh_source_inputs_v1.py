"""Pure new-input bridge fixtures, never a real collection or production pass."""
from copy import deepcopy
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_fresh_source_inputs_v1 as inputs_bridge
from src.content_factory import creative_fresh_legal_source_v1 as source
from src.content_factory import creative_goal_source_contract_v4 as goals
from tests.test_creative_fresh_legal_source_v1 import fixture as collection_fixture, NOW

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("input bridge cannot use network/model/browser operations")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    yield
    gc.collect()  # Close synthetic SQLite handles before Windows temp cleanup.


@pytest.fixture
def bundle(tmp_path):
    args, _, _ = collection_fixture(tmp_path)
    prepared = source.prepare_source_bundle(**args)
    root = tmp_path / "source"
    source.write_source_bundle(root, prepared)
    prefs, contract = tmp_path / "preferences.json", tmp_path / "goals.json"
    prefs.write_bytes(source._json_bytes({"max_characters": 2, "whole_film_max_seconds": 180}))
    contract.write_bytes(source._json_bytes(goals.build_user_goal_contract()))
    return root, prefs, contract, prepared


def rewrite(root, name, value):
    """Rebind only synthetic fixture bytes to exercise deeper consistency gates."""
    path = root / name
    path.write_bytes(source._json_bytes(value))
    manifest_path = root / "SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_bytes(source._json_bytes(manifest))


def test_new_bundle_complete_authorities_and_explicit_functional_inputs(bundle):
    root, prefs, contract, original = bundle
    before = {p: p.read_bytes() for p in root.iterdir()}
    result = inputs_bridge.build_inputs(root, prefs, contract, now=NOW)
    current = result["inputs"]
    assert set(current) == set(inputs_bridge.compact.CONTEXT_KEYS) | {"user_goal_contract"}
    assert current["reference_fulltext"] == original["packet"]["inputs"]["reference_fulltext"]
    assert current["verified_legal_context"] == json.loads(original["content"]["VERIFIED_LEGAL_CONTEXT.json"])
    assert current["expression_standards"] == original["packet"]["inputs"]["expression_standards"]
    assert current["user_goal_contract"] == json.loads(contract.read_text(encoding="utf-8"))
    assert len(current["source_packet"]["representative_metadata"]) == 6
    assert current["source_packet"]["source_identity"]["source_packet_semantic_sha256"] == inputs_bridge.digest(original["packet"])
    assert result["evidence"]["source_gate"]["current_source_freshness_verified"]
    assert not result["evidence"]["old_run_inputs_read"]
    assert not result["evidence"]["user_story_direction_alignment_proven"]
    assert not result["evidence"]["creative_quality_passed"]
    assert set(result["source_files"]) == {str(p.resolve()) for p in root.iterdir()} | {str(prefs), str(contract)}
    assert {p: p.read_bytes() for p in root.iterdir()} == before


@pytest.mark.parametrize("name", sorted(inputs_bridge.REQUIRED_ARTIFACTS))
def test_every_original_source_artifact_hash_is_enforced(bundle, name):
    root, *_ = bundle
    path = root / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA changed"):
        inputs_bridge.verify_source_bundle(root, now=NOW)


@pytest.mark.parametrize("fault", ["missing", "untracked", "traversal", "duplicate_json"])
def test_manifest_flat_complete_and_strict_json(bundle, fault):
    root, *_ = bundle
    manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    if fault == "missing": (root / "TAG_GRAPH.json").unlink()
    elif fault == "untracked": (root / "UNBOUND_INPUTS.json").write_text("{}", encoding="utf-8")
    elif fault == "traversal":
        manifest["artifact_sha256"]["../other.json"] = "0" * 64
        (root / "SOURCE_MANIFEST.json").write_bytes(source._json_bytes(manifest))
    else: (root / "SOURCE_MANIFEST.json").write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
    with pytest.raises(ValueError): inputs_bridge.verify_source_bundle(root, now=NOW)


@pytest.mark.parametrize("fault", ["other_account", "profile", "run", "observation_run", "live_uid",
    "identity_after_start", "packet_graph", "selected_core", "sample", "law", "preview"])
def test_semantic_binding_checks_do_not_trust_rehashed_fixture(bundle, fault):
    root, *_ = bundle
    names = {"other_account": "TREND_SOURCE.json", "profile": "TREND_SOURCE.json", "run": "TREND_SOURCE.json",
        "observation_run": "TREND_SOURCE.json", "live_uid": "LIVE_IDENTITY_CHECK.json",
        "identity_after_start": "LIVE_IDENTITY_CHECK.json", "packet_graph": "SOURCE_PACKET.json",
        "selected_core": "SELECTED_CORE.json", "sample": "COLLECTION_RESULT.json",
        "law": "VERIFIED_LEGAL_CONTEXT.json", "preview": "DIRECTION_WIRE_PREVIEW.json"}
    name = names[fault]
    value = json.loads((root / name).read_text(encoding="utf-8"))
    if fault == "other_account": value["account_profile"]["account_key"] = "account02"
    elif fault == "profile": value["account_profile"]["profile_version"] = True
    elif fault == "run": value["collection_run"]["run_id"] = "different-new-batch"
    elif fault == "observation_run": value["observations"][0]["run_id"] = "another-batch"
    elif fault == "live_uid": value["actual_public_id"] = "other-account"
    elif fault == "identity_after_start": value["at_utc"] = NOW
    elif fault == "packet_graph": value["graph_sha256"] = "0" * 64
    elif fault == "selected_core": value["selected_core"]["title"] = "Unsupported unrelated topic"
    elif fault == "sample": value["result"]["sample_gate"]["passed"] = False
    elif fault == "law": value["facts"] = []
    else: value["messages"][1]["content"] = "{}"
    rewrite(root, name, value)
    with pytest.raises(ValueError): inputs_bridge.verify_source_bundle(root, now=NOW)


def test_expiry_not_file_modification_time(bundle):
    root, *_ = bundle
    for path in root.iterdir(): path.touch()
    with pytest.raises(ValueError, match="outside_validity|graph request blocked"):
        inputs_bridge.verify_source_bundle(root, now="2026-10-14T13:10:00Z")


def test_real_historical_bundle_rejected_at_actual_current_time():
    old = PROJECT / "data/production_trials/fresh_legal_full_flow_20261012/round_01/source"
    with pytest.raises(ValueError, match="outside_validity|graph request blocked"):
        inputs_bridge.verify_source_bundle(old, now=datetime.now(timezone.utc).isoformat())


@pytest.mark.parametrize("fault", ["old_inputs", "duplicate_id", "empty_goal", "bool_cast", "missing_timezone"])
def test_explicit_goals_preferences_and_actual_time_contract(bundle, fault):
    root, prefs, contract, _ = bundle
    value = json.loads(contract.read_text(encoding="utf-8"))
    if fault == "old_inputs": value["source_packet"] = {"old": "619"}
    elif fault == "duplicate_id": value["audience_goals"][0]["id"] = value["constraints"][0]["id"]
    elif fault == "empty_goal": value["constraints"][0]["text"] = " "
    elif fault == "bool_cast": prefs.write_bytes(source._json_bytes({"max_characters": True}))
    contract.write_bytes(source._json_bytes(value))
    with pytest.raises(ValueError):
        inputs_bridge.build_inputs(root, prefs, contract, now="2026-10-12T13:10:00" if fault == "missing_timezone" else NOW)


def test_change_during_projection_cannot_be_certified(bundle, monkeypatch):
    root, prefs, contract, _ = bundle
    original = inputs_bridge.compact.compact_context
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        prefs.write_bytes(source._json_bytes({"max_characters": 4}))
        return result
    monkeypatch.setattr(inputs_bridge.compact, "compact_context", changed)
    with pytest.raises(ValueError, match="bytes changed"):
        inputs_bridge.build_inputs(root, prefs, contract, now=NOW)


@pytest.mark.parametrize("status", ["blocked", "partial", "human_required", "outcome_unknown"])
def test_native_or_wrapped_blocked_collection_cannot_be_promoted(bundle, status, tmp_path):
    root, *_ = bundle
    wrapper = json.loads((root / "COLLECTION_RESULT.json").read_text(encoding="utf-8"))
    native = deepcopy(wrapper["result"])
    native["status"] = status
    path = tmp_path / "native-blocked.json"
    path.write_bytes(source._json_bytes(native))
    with pytest.raises(ValueError, match="blocked stays blocked"):
        inputs_bridge.normalize_collection_result(path, original_helper_exit_code=0)
    # The original unwrapped native is not the old frozen source interface.
    with pytest.raises(ValueError): source._collect(native, {"account_key": "account01"})
    wrapper.update(result=native, status="completed", exit_code=0)
    rewrite(root, "COLLECTION_RESULT.json", wrapper)
    with pytest.raises(ValueError): inputs_bridge.verify_source_bundle(root, now=NOW)


@pytest.mark.parametrize("helper_exit", [None, True, 1])
def test_native_status_does_not_invent_actual_helper_exit(bundle, tmp_path, helper_exit):
    root, *_ = bundle
    native = json.loads((root / "COLLECTION_RESULT.json").read_text(encoding="utf-8"))["result"]
    path = tmp_path / "native.json"
    path.write_bytes(source._json_bytes(native))
    with pytest.raises(ValueError, match="helper exit"):
        inputs_bridge.normalize_collection_result(path, original_helper_exit_code=helper_exit)


def test_metadata_pending_native_wrapper_preserves_original_and_explicit_status_mapping(bundle, tmp_path):
    root, prefs, contract, _ = bundle
    wrapper = json.loads((root / "COLLECTION_RESULT.json").read_text(encoding="utf-8"))
    native = deepcopy(wrapper["result"])
    native.update(status="awaiting_media_analysis", stopped_reason="incomplete_source_media_analysis")
    path = tmp_path / "native-helper-result.json"
    original = source._json_bytes(native)
    path.write_bytes(original)
    derived = inputs_bridge.normalize_collection_result(path, original_helper_exit_code=0)
    assert derived["exit_code"] == 1 and derived["status"] == "awaiting_media_analysis"
    assert derived["result"] == native and path.read_bytes() == original
    normalization = derived["normalization"]
    assert normalization["original_helper_exit_code"] == 0 and not normalization["legacy_cli_executed"]
    assert not normalization["exit_code_is_observed_helper_exit"]
    assert normalization["original_video_av_analysis_completed"] is False
    # Create a new synthetic source bundle using the existing frozen exporter.
    second = tmp_path / "second"
    second.mkdir()
    args, _, _ = collection_fixture(second)
    args["collect_result"] = derived
    source.write_source_bundle(second / "source", source.prepare_source_bundle(**args))
    built = inputs_bridge.build_inputs(second / "source", prefs, contract, now=NOW)
    assert str(path) in built["source_files"]
    assert str(inputs_bridge.LEGACY_COLLECTION_CLI) in built["source_files"]
    path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="differs from original"):
        inputs_bridge.verify_source_bundle(second / "source", now=NOW)
