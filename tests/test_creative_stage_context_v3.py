"""Pure context/provenance verification; no credentials, claims or network."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_goal_source_contract_v2 as user_goals
from src.content_factory import creative_stage_context_v2 as old
from src.content_factory import creative_stage_context_v3 as context
from tests.test_creative_stage_context_v2 import inputs as v2_inputs


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("pure context cannot use sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def inputs(v2_inputs):
    result = deepcopy(v2_inputs)
    result["user_goal_contract"] = user_goals.build_user_goal_contract()
    result["verified_legal_context"].update(
        applicability_scope={"jurisdiction": "大陆一般劳动关系", "excluded": ["特殊用工", "个案金额"]},
        scope="以劳动关系及具体事实、证据为条件，不对未知用工关系推定结果",
        creative_boundaries=["不把拒签说成一定胜诉。",
            "虚构事件中的当事人先保留真实书面事实、核对解除性质；不伪造证据、不删除劳动者的具体过错。",
            "请求获得支持取决于事实、证据和法律条件，结尾不以口号代替实际后果。"])
    return result


def get_path(value, path):
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def quotes(value):
    if isinstance(value, dict):
        return [(key, child) for key, child in value.items() if key == "source_quote"] + [
            item for key, child in value.items() if key != "source_quote" for item in quotes(child)]
    if isinstance(value, list):
        return [item for child in value for item in quotes(child)]
    return []


@pytest.mark.parametrize("stage", context.STAGES)
def test_functional_user_goals_and_legal_full_values_survive_every_stage(inputs, stage):
    original = deepcopy(inputs)
    result = context.build_stage_context(stage, inputs)
    payload = result["payload"]
    assert inputs == original
    assert not quotes(payload["user_goal_contract"])
    for table in ("constraints", "audience_goals", "planning_rules"):
        assert [row["text"] for row in payload["user_goal_contract"][table]] == [row["text"] for row in original["user_goal_contract"][table]]
    for key, value in original["verified_legal_context"].items():
        if key != "creative_boundaries":
            assert payload["verified_legal_context"][key] == value
    assert payload["reference_fulltext"] == original["reference_fulltext"]
    assert result["manifest"]["reference_proof"]["payload_occurrences"] == 1


def test_historical_case_quote_moves_to_complete_local_provenance(inputs):
    result = context.build_stage_context("goal_plan", inputs)
    payload, manifest = result["payload"], result["manifest"]
    historical = inputs["user_goal_contract"]["audience_goals"][2]["source_quote"]
    assert historical not in json.dumps(payload, ensure_ascii=False)
    assert "个人原因" not in json.dumps(payload["user_goal_contract"], ensure_ascii=False)
    records = [row for row in manifest["provenance_manifest"]["transformations"] if row["category"] == "historical_user_quote"]
    assert len(records) == 8
    for row in records:
        actual = get_path(inputs, row["source_path"])
        assert row["original_text"] == actual
        assert row["original_identity"]["utf8_sha256"] == hashlib.sha256(actual.encode()).hexdigest()
        assert row["projected_path"] is None
    assert manifest["provenance_manifest"]["enters_provider_messages"] is False


def test_optional_fixed_strategy_is_not_injected_as_mandatory_legal_step(inputs):
    result = context.build_stage_context("goal_plan", inputs)
    law = result["payload"]["verified_legal_context"]
    assert law["creative_boundaries"][1] == "不伪造证据、不删除劳动者的具体过错。"
    assert "当事人先保留真实书面事实、核对解除性质" not in json.dumps(law, ensure_ascii=False)
    original = inputs["verified_legal_context"]["creative_boundaries"][1]
    row = next(row for row in result["manifest"]["provenance_manifest"]["transformations"] if row["source_path"] == "verified_legal_context.creative_boundaries.1")
    assert row["original_text"] == original
    assert row["optional_strategy"]["authority"] == "optional_creative_strategy_not_mandatory_legal_step"
    assert row["projected_text"] == law["creative_boundaries"][1]
    assert row["projected_identity"]["utf8_sha256"] == hashlib.sha256(row["projected_text"].encode()).hexdigest()


def test_unknown_boundary_is_preserved_complete_instead_of_guessed_as_advice(inputs):
    original = "劳动关系认定需事实证据，先取证的要求不当然适用于所有用工；不得删条件。"
    inputs["verified_legal_context"]["creative_boundaries"].append(original)
    result = context.build_stage_context("goal_plan", inputs)
    assert result["payload"]["verified_legal_context"]["creative_boundaries"][-1] == original
    row = result["manifest"]["provenance_manifest"]["transformations"][-1]
    assert row["disposition"] == "retained_unchanged"


def test_optional_strategy_only_omission_tracks_shifted_remaining_paths(inputs):
    inputs["verified_legal_context"]["creative_boundaries"] = ["当事人先保留真实书面事实、核对解除性质。", "未依法缴纳时按法定条件请求。"]
    result = context.build_stage_context("goal_plan", inputs)
    assert result["payload"]["verified_legal_context"]["creative_boundaries"] == ["未依法缴纳时按法定条件请求。"]
    rows = [row for row in result["manifest"]["provenance_manifest"]["transformations"] if row["category"] == "legal_context_boundary"]
    assert rows[0]["projected_path"] is None
    assert rows[1]["projected_path"] == "verified_legal_context.creative_boundaries.0"


def test_platform_alias_catalog_has_exact_original_id_path_and_text(inputs):
    result = context.build_stage_context("goal_plan", inputs)
    catalog = result["payload"]["origin_catalog"]
    entries = catalog["platform_metadata"]
    assert list(entries) == ["S" + str(index).zfill(3) for index in range(1, 7)]
    assert [entry["original_id"] for entry in entries.values()] == sorted(entry["original_id"] for entry in entries.values())
    for alias, entry in entries.items():
        actual = get_path(result["payload"], entry["path"])
        assert entry["original_id"] in [actual.get(key) for key in ("tag_id", "edge_id", "family_id", "item_id", "candidate_id")]
        if entry["text_path"] is not None:
            assert entry["text"] == get_path(result["payload"], entry["text_path"])
        assert context.resolve_origin_alias(catalog, alias)["original_id"] == entry["original_id"]


def test_aliases_stable_by_original_id_when_source_tables_are_reordered(inputs):
    first = context.build_stage_context("goal_plan", inputs)["payload"]["origin_catalog"]["platform_metadata"]
    changed = deepcopy(inputs)
    changed["source_packet"]["tag_catalog"].reverse()
    second = context.build_stage_context("goal_plan", changed)["payload"]["origin_catalog"]["platform_metadata"]
    assert {alias: row["original_id"] for alias, row in first.items()} == {alias: row["original_id"] for alias, row in second.items()}
    assert any(first[alias]["path"] != second[alias]["path"] for alias in first)


@pytest.mark.parametrize("alias", ["S01", "s001", " S001", "S001 ", "edge:1", "tag:labor", "S999", 1, None])
def test_unknown_or_approximate_alias_is_rejected_without_correction(inputs, alias):
    catalog = context.build_stage_context("goal_plan", inputs)["payload"]["origin_catalog"]
    with pytest.raises(context.ContextError, match="exact"):
        context.resolve_origin_alias(catalog, alias)


def test_readable_legal_and_user_ids_keep_their_actual_authority_groups(inputs):
    catalog = context.build_stage_context("goal_plan", inputs)["payload"]["origin_catalog"]
    ids = context.alias_origin_ids(catalog)
    assert ids["legal_ids"] == ["L001"]
    assert ids["user_constraint_ids"] == [row["id"] for table in ("constraints", "audience_goals") for row in inputs["user_goal_contract"][table]]
    assert context.resolve_origin_alias(catalog, "L001")["path"] == "verified_legal_context.facts.0"
    assert context.resolve_origin_alias(catalog, "UG_OPPONENT_RESPONSE")["authority"] == "user_audience_goal"
    assert all(key.startswith("S") for key in ids["source_ids"])


def test_alias_local_mapping_keeps_original_source_row_identity(inputs):
    result = context.build_stage_context("goal_plan", inputs)
    for row in result["manifest"]["provenance_manifest"]["platform_alias_mappings"]:
        original = get_path(inputs, row["original_source_path"])
        assert row["original_source_identity"] == context._measure(original)
        assert row["original_id"] in [original.get(key) for key in ("tag_id", "edge_id", "family_id", "item_id", "candidate_id")]


@pytest.mark.parametrize("group,field,value", [("platform_metadata", "authority", "verified_legal_with_conditions"), ("verified_legal", "original_id", ""), ("user", "path", None)])
def test_catalog_authority_or_identity_corruption_is_not_accepted(inputs, group, field, value):
    catalog = context.build_stage_context("goal_plan", inputs)["payload"]["origin_catalog"]
    catalog[group][next(iter(catalog[group]))][field] = value
    with pytest.raises(context.ContextError):
        context.alias_origin_ids(catalog)


def test_duplicate_origin_between_platform_groups_is_rejected(inputs):
    inputs["source_packet"]["selected_relations"][0]["edge_id"] = "tag:labor"
    with pytest.raises(context.ContextError, match="overlap"):
        context.build_stage_context("goal_plan", inputs)


def test_duplicate_user_origin_is_rejected(inputs):
    inputs["user_goal_contract"]["audience_goals"][0]["id"] = inputs["user_goal_contract"]["constraints"][0]["id"]
    with pytest.raises(context.ContextError, match="ambiguous"):
        context.build_stage_context("goal_plan", inputs)


def test_complete_current_script_is_not_sanitized_or_abbreviated(inputs):
    inputs["full_current_script"]["beats"][0]["steps"][0]["source_quote"] = "当前原生正文的字段必须完整保留"
    result = context.build_stage_context("full_review", inputs)
    assert result["payload"]["full_current_script"] == inputs["full_current_script"]
    assert result["manifest"]["full_current_script_sha256"] == context._digest(inputs["full_current_script"])
    assert result["manifest"]["full_current_script_unchanged"] is True


def test_complete_previous_native_revision_survives_without_manual_alias_rewrite(inputs):
    previous = {"claims": [{"origin_ids": ["S999"], "text": "完整失败原生稿不能手改引用"}]}
    inputs.update(previous_complete_document=previous, revision_diagnostics={"code": "GOAL_SOURCE_UNKNOWN"})
    result = context.build_stage_context("goal_plan", inputs)
    assert result["payload"]["previous_complete_document"] == previous
    assert result["manifest"]["native_aliases_rewritten"] is False


def test_final_alias_context_rechecks_explicit_budget_and_reports_real_bytes(inputs):
    first = context.build_stage_context("goal_plan", inputs)
    actual = first["manifest"]["payload_identity"]
    assert actual == context._measure(first["payload"])
    inputs["context_policy"] = {"max_payload_characters": actual["characters"] - 1, "max_payload_utf8_bytes": actual["utf8_bytes"] + 100}
    with pytest.raises(context.ContextError, match="no content truncated"):
        context.build_stage_context("goal_plan", inputs)


def test_nested_reference_repetition_is_still_rejected(inputs):
    inputs["creative_scene_plan"]["reference_copy"] = inputs["reference_fulltext"]
    with pytest.raises(context.ContextError, match="exactly once"):
        context.build_stage_context("complete_script", inputs)


def test_unknown_input_not_silently_dropped(inputs):
    inputs["secret_extra_goal"] = "未分类"
    with pytest.raises(context.ContextError, match="unmapped"):
        context.build_stage_context("goal_plan", inputs)


@pytest.mark.parametrize("field", ["text", "id"])
def test_missing_functional_user_goal_stops_instead_of_reconstructing_from_quote(inputs, field):
    inputs["user_goal_contract"]["audience_goals"][0].pop(field)
    with pytest.raises(context.ContextError):
        context.build_stage_context("goal_plan", inputs)


def test_nontext_historical_quote_stops_instead_of_silent_omission(inputs):
    inputs["user_goal_contract"]["audience_goals"][0]["source_quote"] = {"ambiguous": True}
    with pytest.raises(context.ContextError, match="original text"):
        context.build_stage_context("goal_plan", inputs)


@pytest.mark.parametrize("field", ["facts", "sources"])
def test_missing_complete_legal_source_rows_are_rejected(inputs, field):
    inputs["verified_legal_context"][field] = []
    with pytest.raises(context.ContextError, match="complete"):
        context.build_stage_context("goal_plan", inputs)


def test_legal_boundary_unknown_structured_type_is_rejected(inputs):
    inputs["verified_legal_context"]["creative_boundaries"] = [{"unknown": "condition"}]
    with pytest.raises(context.ContextError, match="original text"):
        context.build_stage_context("goal_plan", inputs)


def test_actual_frozen_production_inputs_preserve_law_reference_and_history_before_after():
    root = Path(__file__).resolve().parents[1]
    path = root / "data/production_trials/goal_context_text_production_20261013/round_01/INPUTS.json"
    if not path.exists():
        pytest.skip("actual frozen production source unavailable")
    original_bytes = path.read_bytes()
    inputs = json.loads(original_bytes)
    before = old.build_stage_context("goal_plan", inputs)
    result = context.build_stage_context("goal_plan", inputs)
    for key, value in inputs["verified_legal_context"].items():
        if key != "creative_boundaries":
            assert result["payload"]["verified_legal_context"][key] == before["payload"]["verified_legal_context"][key] == value
    assert len(result["payload"]["reference_fulltext"]) == 2313
    assert result["manifest"]["reference_proof"]["payload_occurrences"] == 1
    assert len(result["payload"]["source_packet"]["representative_metadata"]) == 6
    assert result["payload"]["source_packet"]["candidate"]["selected_item_ids"] == before["payload"]["source_packet"]["candidate"]["selected_item_ids"]
    assert "source_quote" not in json.dumps(result["payload"]["user_goal_contract"], ensure_ascii=False)
    assert path.read_bytes() == original_bytes
    assert not result["manifest"]["allowance_reset"] and not result["manifest"]["dispatch_performed"]
    assert result["manifest"]["actual_provider_tokens"] is None
