"""Offline explicit registration tests; no model or service calls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from scripts import creative_component_registry_v1 as registry
from src.content_factory.creative_workflow_contract import CreativeContractError

ORIGINAL = Path("data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/ORIGINAL_CONTEXT.json")


def sample():
    original = json.loads(ORIGINAL.read_text(encoding="utf-8"))["static_visual_manifest"]
    return original, registry.p03_member_declarations(original)


def build(original, declarations):
    return registry.build_component_manifest(original, declarations, support_surface_ids=["E01", "E02"])


def test_actual_three_members_replace_collection_and_preserve_every_other_asset():
    original, declarations = sample()
    before = deepcopy((original, declarations))
    bundle = build(original, declarations)
    assert (original, declarations) == before
    assert bundle["original_manifest"] == original
    effective = bundle["effective_manifest"]
    assert "P03" not in {p["id"] for p in effective["props"]}
    ids = {p["id"] for p in effective["props"]}
    assert {"P03_Y", "P03_P", "P03_B"} <= ids
    assert {p["id"]: p for p in effective["props"] if p["id"] not in {"P03_Y", "P03_P", "P03_B"}} == {
        p["id"]: p for p in original["props"] if p["id"] != "P03"}
    for key in original:
        if key != "props":
            assert effective[key] == original[key]
    assert effective["surface_ids"] == ["E01", "E02"]
    assert bundle["component_collections"]["P03"]["member_ids"] == ["P03_Y", "P03_P", "P03_B"]
    for prop in effective["props"]:
        if prop["id"].startswith("P03_"):
            assert prop["owner_id"] == "C01"
    assert registry.validate_component_bundle(bundle) == effective
    assert bundle["semantic_approval"] is False
    assert bundle["production_ready"] is False


def test_sha_binds_full_original_declarations_and_effective_manifest():
    original, declarations = sample()
    b = build(original, declarations)
    assert b["original_manifest_sha256"] == registry._digest(original)
    assert b["component_declarations_sha256"] == registry._digest(declarations)
    assert b["effective_manifest_sha256"] == registry._digest(b["effective_manifest"])
    assert b == build(deepcopy(original), deepcopy(declarations))
    assert registry._digest(dict(reversed(list(original.items())))) == b["original_manifest_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda d: d.clear(),
    lambda d: d[0].update(source_prop_id="P99"),
    lambda d: d.append(deepcopy(d[0])),
    lambda d: d[0]["members"].pop(),
    lambda d: d[0].update(members={"item": d[0]["members"]}),
    lambda d: d[0]["members"][1].update(id="P03_Y"),
    lambda d: d[0]["members"][0].update(id="C01"),
    lambda d: d[0]["members"][0].update(owner_id="C02"),
    lambda d: d[0]["members"][0].update(source_evidence=["新发明的纸片"]),
    lambda d: d[0]["members"][0].update(source_evidence=[]),
    lambda d: d[0]["members"][0].pop("source_evidence"),
    lambda d: d[0]["members"][1].update(source_evidence=deepcopy(d[0]["members"][0]["source_evidence"]),
        name=d[0]["members"][0]["name"], appearance=d[0]["members"][0]["appearance"]),
    lambda d: d[0].update(source_count=2),
    lambda d: d[0].update(source_count=True),
    lambda d: d[0].update(source_count_evidence="二张"),
    lambda d: d[0].update(extra="not permitted"),
])
def test_missing_duplicate_changed_owner_unregistered_source_and_false_evidence_rejected(mutation):
    original, declarations = sample()
    mutation(declarations)
    with pytest.raises(CreativeContractError):
        build(original, declarations)


@pytest.mark.parametrize("surfaces", [[], ["E99"], ["E01", "E01"], "E01", [None]])
def test_support_surface_requires_explicit_existing_unique_ids(surfaces):
    original, declarations = sample()
    with pytest.raises(CreativeContractError):
        registry.build_component_manifest(original, declarations, support_surface_ids=surfaces)


@pytest.mark.parametrize("target", ["original_manifest_sha256", "effective_manifest_sha256", "component_collections", "member_source_map"])
def test_trace_or_hash_tampering_rejected(target):
    original, declarations = sample()
    b = build(original, declarations)
    if target.endswith("sha256"):
        b[target] = "0" * 64
    else:
        b[target].clear()
    with pytest.raises(CreativeContractError, match="不一致"):
        registry.validate_component_bundle(b)


def test_validation_return_and_built_bundle_are_independent_copies():
    original, declarations = sample()
    b = build(original, declarations)
    returned = registry.validate_component_bundle(b)
    returned["props"].clear()
    assert b["effective_manifest"]["props"]
    original["props"].clear()
    declarations[0]["members"].clear()
    assert b["original_manifest"]["props"]
    assert b["component_declarations"][0]["members"]


def test_no_raw_script_rewrite_is_part_of_registration():
    context = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    before = deepcopy(context)
    registry.build_p03_registry(context["static_visual_manifest"])
    assert context == before

def test_public_registry_api_and_member_selector_missing_or_duplicate_rejected():
    original, declarations = sample()
    assert registry.build_component_registry(original, declarations, ["E01", "E02"]) == build(original, declarations)
    with pytest.raises(CreativeContractError):
        registry.build_component_registry(original, declarations)
    declarations[0]["members"][1].update(name="浅黄改明细便利贴",
        appearance="正方形小纸片，浅黄底，深灰手写短词（改明细）",
        source_evidence=["浅黄", "改明细"])
    with pytest.raises(CreativeContractError, match="证据重复"):
        build(original, declarations)
