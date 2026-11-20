"""Provider/canonical identity and actual request/graph adaptation, synthetic only."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import socket

import pytest
from scripts import creative_world_scene_production_source_v1 as source
from scripts import creative_world_scene_production_probe_v2 as production
from scripts import creative_world_scene_media_probe_v3 as media
from scripts import creative_world_scene_text_handoff_verifier_v2 as registry
from tests.test_creative_world_scene_production_probe_v1 import parent_fixture, whole_direction, first_performance, review_document
from tests.test_creative_world_scene_media_probe_v1 import case, write
from tests.test_creative_world_scene_media_probe_v2 import encoded_case


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("no real service or GPU in source adapter tests")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def derived_fixture(proof):
    """Create a new synthetic v2 native, never convert an actual failed body."""
    raw = source.legacy.read(proof["paths"]["raw_script"]); goal = source.legacy.read(proof["paths"]["goal"])
    raw["contract_version"] = source.derived.NATIVE_VERSION
    for context in raw["scene_contexts"]: context.pop("previous_context_id")
    compiled = source.derived.compile_document(raw, goal); root = Path(proof["paths"]["raw_script"]).parent
    for key, value in (("raw_script", raw), ("derived_script", compiled["derived_script"]),
            ("compiled_script", compiled["script"]), ("source_descriptor", compiled["source_descriptor"])):
        path = Path(proof["paths"].get(key, root / (key + ".json")))
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8"); proof["paths"][key] = str(path)
    proof["source_descriptor"] = deepcopy(compiled["source_descriptor"])
    proof["identity"].update({k: compiled["source_descriptor"][k] for k in (
        "native_script_sha256", "derived_script_sha256", "compiled_script_sha256")})
    proof.setdefault("source_files", {}).update(source.legacy._hashes(proof["paths"].values()))
    return proof


def test_real_source_loader_keeps_provider_native_and_binds_all_three_actual_requests(tmp_path):
    proof = derived_fixture(parent_fixture(tmp_path)); original = deepcopy(proof)
    with pytest.raises(Exception): source.legacy.load_material(proof)  # old raw contract cannot silently accept v2
    material = source.load_material(proof)
    assert material["verified"] == original and material["values"]["raw_script"] == source.legacy.read(proof["paths"]["raw_script"])
    assert material["verified"]["paths"]["raw_script"] != material["verified"]["paths"]["derived_script"]
    assert all("previous_context_id" not in c for c in material["values"]["raw_script"]["scene_contexts"])
    direction = whole_direction(material); performance = first_performance(material, direction); profile = material["values"]["profile"]
    prepared = [production.direction_request(material, profile), production.performance_request(material, profile, direction),
        production.review_request(material, profile, direction, performance)]
    for request in prepared:
        actual = json.loads(request["request"]["messages"][1]["content"])
        assert actual == request["payload"]
        binding = actual.get("script_source_binding", actual.get("context", {}).get("script_source_binding"))
        assert binding["source_descriptor"] == proof["source_descriptor"]
        assert request["request"]["input_provenance"]["provider_native_script_sha256"] == proof["identity"]["native_script_sha256"]
        assert binding["actual_full_current_script_sha256"] == proof["identity"]["compiled_script_sha256"]
    reviewed = prepared[-1]
    assert source.legacy.validate_review(review_document(reviewed), reviewed)["accepted"]
    assert reviewed["context_sha256"] == source.legacy.digest(reviewed["review_context"])
    assert reviewed["request"]["structured_schema"]["properties"]["context_sha256"] == {"const": reviewed["context_sha256"]}
    assert any(row["path"].startswith("script_source_binding.source_descriptor.") for row in reviewed["evidence_catalog"].values())
    assert material["verified"] == original and proof == original
    altered = deepcopy(proof); altered["source_descriptor"]["native_script_sha256"] = altered["identity"]["derived_script_sha256"]
    with pytest.raises(ValueError, match="exactly rebuild"): source.verify_documents(altered)


def test_media_v7_uses_canonical_catalog_but_keeps_true_raw_identity_and_rejects_change(case, monkeypatch):
    cfg, text, prod, snapshot = encoded_case(case); text = derived_fixture(text)
    prod.update(**text["identity"], source_descriptor=deepcopy(text["source_descriptor"]), entry_binding=production.entry_binding())
    tmp = Path(cfg.output_root).parent; ledger = media.base.read(cfg.ledger_path)
    ledger.update(story_id=prod["story_id"], failure_limit=10, failures_used=1, known_rejections=1, technical_failures=0,
        observed_local_video_submissions=2, not_a_new_story_reset=True, old_receipts_and_unknowns_retained=True)
    write(tmp / "ledger.json", ledger); cfg = replace(cfg, ledger_path=str(tmp / "ledger.json"))
    monkeypatch.setattr(registry, "verify_text_handoff", lambda r: deepcopy(text))
    monkeypatch.setattr(production, "verify_first_segment_handoff", lambda r, **kw: deepcopy(prod))
    monkeypatch.setattr(media.base, "inspect_service", lambda: deepcopy(snapshot))
    media.prepare(cfg); checked = media.verify_prepared(cfg.output_root)
    assert checked["base_prepared"]["native_identity"]["native_script_sha256"] == source.legacy.digest(source.legacy.read(text["paths"]["raw_script"]))
    assert checked["production_verified"]["source_descriptor"] == text["source_descriptor"]
    assert "derived_script" in checked["base_prepared"]["source_paths"]
    assert checked["graph"]["condition"]["inputs"]["prompt"] == prod["actual_video_prompt"]
    derived_path = Path(text["paths"]["derived_script"]); changed = media.base.read(derived_path)
    changed["scene_contexts"][0]["previous_context_id"] = "not-the-compiled-link"
    derived_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly rebuild"): media.verify_prepared(cfg.output_root)
    assert not (Path(cfg.output_root) / "RUN_CLAIM.json").exists()
