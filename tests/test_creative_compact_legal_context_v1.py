"""Offline contract tests: original authority first, projection only afterwards."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_compact_legal_context_v1 as compact
from src.content_factory import creative_legal_tag_graph_bridge_v1 as bridge
from src.content_factory.creative_video_trial_contract_v1 import digest
from src.trend_intelligence.legal_tag_graph_v1 import build_graph
from test_creative_trend_bridge import source_fixture, NOW, REFERENCE, STANDARDS


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline projection must not access the network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def inputs():
    source = source_fixture()
    source["account_profile"].update(domain_strategy_id="legal_services",
        allowed_formats=["案例拆解"], seed_keywords=["劳动", "法律"])
    for field in ("collection_run", "opportunity"):
        source[field]["domain_strategy_id"] = "legal_services"
    source["opportunity"]["title"] = "劳动纠纷"
    for index, row in enumerate(source["observations"]):
        row.update(hashtags=["劳动纠纷", "劳动仲裁", "被迫离职"],
            author="模拟作者" + str(index % 5), keyword="劳动纠纷" if index % 2 else "劳动仲裁",
            metric_value=60000 + index)
    # The duplicated video must not become a seventh independent example.
    source["observations"].append(deepcopy(source["observations"][19]))
    reference = REFERENCE.read_text(encoding="utf-8")
    standards = json.loads(STANDARDS.read_text(encoding="utf-8"))
    graph = build_graph(source)
    packet = bridge.build_packet(source, graph, reference, standards, now=NOW, focus_label="劳动纠纷")
    legal = {"schema": "verified_legal_story_context/v1",
        "sources": [{"id": "L", "url": "https://example.invalid/offline-only"}],
        "facts": [{"source_id": "L", "paraphrase": "模拟离线法律边界，不构成生产核验"}],
        "creative_boundaries": ["不保证结果"]}
    preferences = {"max_characters": 2, "max_duration_seconds": 180,
        "prior_story_scope": {"full_prior_script": {"title": "完整旧稿",
            "beats": [{"steps": [{"text": "这份完整旧稿仅作同故事额度隔离。"}]}]},
            "previous_director_candidates": 7}}
    return dict(packet=packet, legal_context=legal, reference_fulltext=reference,
        expression_standards=standards, production_preferences=preferences,
        source_binding_sha256="a" * 64, now=NOW)


def full_payload(inputs):
    result = {"source_packet": deepcopy(inputs["packet"]),
        "verified_legal_context": deepcopy(inputs["legal_context"]),
        "reference_fulltext": inputs["reference_fulltext"],
        "expression_standards": deepcopy(inputs["expression_standards"]),
        "production_preferences": deepcopy(inputs["production_preferences"]),
        "automatic_creative_choice_not_user_approval": True}
    return result


def test_exact_original_selected_evidence_and_fixed_context_preserved(inputs):
    context = compact.compact_context(**inputs)
    packet, projected = inputs["packet"], context["source_packet"]
    assert set(context) == {*compact.CONTEXT_KEYS, "automatic_creative_choice_not_user_approval"}
    assert projected["candidate"] == packet["candidate"]
    assert projected["tag_catalog"] == packet["tag_catalog"]
    selected = [row["edge_id"] for row in packet["candidate"]["related_tags"]]
    original = {row["edge_id"]: row for row in packet["graph"]["edges"]}
    assert projected["selected_relations"] == [original[edge_id] for edge_id in selected]
    assert projected["sample_gate"] == packet["sample_gate"]
    assert projected["source_identity"]["source_packet_semantic_sha256"] == digest(packet)
    assert projected["source_identity"]["source_semantic_sha256"] == packet["source_sha256"]
    assert projected["source_identity"]["graph_semantic_sha256"] == packet["graph_sha256"]
    assert projected["account_profile"] == packet["graph_source"]["account_profile"]
    assert projected["collection_run"] == packet["graph_source"]["collection_run"]
    assert projected["whole_batch_summary"] == packet["graph"]["summary"]
    assert projected["limitations"] == packet["graph"]["limitations"]
    for key in ("reference_fulltext", "expression_standards", "production_preferences"):
        assert context[key] == inputs[key]
    assert context["verified_legal_context"] == inputs["legal_context"]
    assert not {"inputs", "base_packet", "graph", "graph_source", "observations"} & set(projected)
    assert projected["creative_quality_passed"] is False


def test_representative_metadata_bounded_same_batch_distinct_and_exact(inputs):
    result = compact.compact_context(**inputs)["source_packet"]
    rows = result["representative_metadata"]
    assert len(rows) == compact.MAX_REPRESENTATIVE_UNIQUE_VIDEOS == 6
    assert len({row["video_id"] for row in rows}) == 6
    assert [row["video_id"] for row in rows] == ["v19", "v18", "v17", "v16", "v15", "v14"]
    original = inputs["packet"]["graph_source"]["observations"]
    for row in rows:
        source_row = next(item for item in original if digest(item) == row["source_observation_sha256"])
        assert row["run_id"] == inputs["packet"]["graph"]["collection_run_id"]
        assert row["video_id"] in inputs["packet"]["candidate"]["support_video_ids"]
        assert {key: value for key, value in row.items() if key != "source_observation_sha256"} == {
            key: source_row[key] for key in compact.METADATA_FIELDS if key in source_row}
    assert result["sample_gate"]["unique_videos"] == 20
    assert result["sample_gate"]["total_views"] > 1_000_000
    # Projection does not silently evaluate the six examples as the source gate.
    assert sum(row["metric_value"] for row in rows) < 1_000_000


def test_no_mutation_and_returned_objects_are_not_source_aliases(inputs):
    before = digest(inputs)
    context = compact.compact_context(**inputs)
    evidence = compact.projection_evidence(inputs["packet"], context, now=NOW)
    assert digest(inputs) == before
    context["source_packet"]["candidate"]["title"] = "修改返回值"
    context["source_packet"]["selected_relations"][0]["support_video_ids"].clear()
    context["expression_standards"]["criteria"].clear()
    context["verified_legal_context"]["facts"].clear()
    assert digest(inputs) == before
    assert evidence["old_records_modified"] is False and evidence["budget_reset"] is False
    assert (evidence["model_calls"], evidence["collection_calls"], evidence["media_calls"]) == (0, 0, 0)


@pytest.mark.parametrize("fault", ["source", "graph", "catalog", "candidate", "base", "sample_gate", "reference", "standards"])
def test_full_original_authority_tampering_rejected(inputs, fault):
    packet = inputs["packet"]
    if fault == "source": packet["graph_source"]["observations"][0]["run_id"] = "other-run"
    elif fault == "graph": packet["graph"]["edges"][0]["support_video_count"] += 1
    elif fault == "catalog": packet["tag_catalog"][0]["label"] = "伪标签"
    elif fault == "candidate": packet["candidate"]["selected_item_ids"] = ["invented"]
    elif fault == "base": packet["base_packet"]["inputs"]["source"]["observations"][0]["metric_value"] += 1
    elif fault == "sample_gate": packet["sample_gate"]["total_views"] += 1
    elif fault == "reference": packet["inputs"]["reference_fulltext"] = "截断参考"
    else: packet["inputs"]["expression_standards"]["criteria"][0]["check"] = "改标准"
    with pytest.raises((ValueError, KeyError)):
        compact.compact_context(**inputs)


def test_projection_cannot_be_used_as_the_full_source(inputs):
    inputs["packet"] = compact.compact_context(**inputs)["source_packet"]
    with pytest.raises(ValueError, match="original full"):
        compact.compact_context(**inputs)


@pytest.mark.parametrize("now", [None, "2026-10-09T04:00:00+00:00", "2026-10-06T04:00:00+00:00", "2026-10-07T04:00:00"])
def test_freshness_revalidated_on_each_projection(inputs, now):
    inputs["now"] = now
    with pytest.raises(ValueError):
        compact.compact_context(**inputs)


def test_first_validation_is_full_packet_not_the_supplied_small_context(inputs):
    inputs["packet"]["candidate"]["title"] = "篡改源"
    inputs["source_binding_sha256"] = "bad-binding"
    with pytest.raises(ValueError, match="packet or derived selection changed"):
        compact.compact_context(**inputs)


@pytest.mark.parametrize("bad", [None, False, "", "a" * 63, "A" * 64, "a" * 65, "g" * 64])
def test_exact_source_binding_sha_required(inputs, bad):
    inputs["source_binding_sha256"] = bad
    with pytest.raises(ValueError, match="source binding"):
        compact.compact_context(**inputs)


@pytest.mark.parametrize("fault", ["reference_empty", "reference_short", "standards_short", "legal_empty", "legal_schema", "legal_no_sources", "legal_no_facts", "legal_no_boundaries", "preferences_nonobject", "bool_actor_limit", "too_many_actors"])
def test_no_missing_or_shortened_fixed_context(inputs, fault):
    if fault == "reference_empty": inputs["reference_fulltext"] = ""
    elif fault == "reference_short": inputs["reference_fulltext"] = inputs["reference_fulltext"][:10]
    elif fault == "standards_short": inputs["expression_standards"]["criteria"] = inputs["expression_standards"]["criteria"][:1]
    elif fault == "legal_empty": inputs["legal_context"] = {}
    elif fault == "legal_schema": inputs["legal_context"]["schema"] = "not-verified"
    elif fault.startswith("legal_no_"):
        key = "creative_boundaries" if fault == "legal_no_boundaries" else fault.removeprefix("legal_no_")
        inputs["legal_context"][key] = []
    elif fault == "preferences_nonobject": inputs["production_preferences"] = []
    elif fault == "bool_actor_limit": inputs["production_preferences"]["max_characters"] = True
    else: inputs["production_preferences"]["max_characters"] = 5
    with pytest.raises(ValueError):
        compact.compact_context(**inputs)


def test_payload_delta_is_only_source_packet_native_full_documents_unchanged(inputs):
    payload = full_payload(inputs)
    payload.update(brief={"characters": [{"id": "C1", "name": "小江"}], "full": "完整简报"},
        native_theme={"ending": "主题原结尾"}, previous_complete_document={"source_obligations": [
            {"id": "O1", "actor_id": ["", ""], "full_original_failure": "完整失败计划保留"}]},
        revision_requirements=[{"error": "这是原始具体诊断"}],
        full_current_script={"beats": [{"steps": [{"text": "完整正文，不压缩。"}]}]})
    before = digest(payload)
    projected = compact.compact_payload(payload, inputs["source_binding_sha256"], now=NOW)
    assert digest(payload) == before
    assert set(projected) == set(payload)
    assert all(projected[key] == payload[key] for key in payload if key != "source_packet")
    evidence = compact.payload_projection_evidence(payload, projected, inputs["source_binding_sha256"], now=NOW)
    assert evidence["fixed_component_key_occurrences"] == {
        "reference_fulltext": 1, "verified_legal_context": 1, "expression_standards": 1}
    assert evidence["native_documents_preserved_completely"] is True
    assert evidence["original_payload_semantic_sha256"] == before
    assert evidence["projected_payload_semantic_sha256"] == digest(projected)
    assert evidence["reference_fulltext_utf8_sha256"] == hashlib.sha256(inputs["reference_fulltext"].encode("utf-8")).hexdigest()


@pytest.mark.parametrize("fault", ["native_changed", "source_changed", "extra_key", "missing_fixed", "duplicate_reference_key"])
def test_projection_evidence_detects_changes_and_repeated_fixed_inputs(inputs, fault):
    original = full_payload(inputs)
    original["previous_complete_document"] = {"text": "完整原文"}
    if fault == "duplicate_reference_key":
        original["extra"] = {"reference_fulltext": inputs["reference_fulltext"]}
    projected = compact.compact_payload(original, inputs["source_binding_sha256"], now=NOW)
    if fault == "native_changed": projected["previous_complete_document"]["text"] = "擅自缩句"
    elif fault == "source_changed": projected["source_packet"]["sample_gate"]["passed"] = False
    elif fault == "extra_key": projected["extra"] = "不许额外追加"
    elif fault == "missing_fixed": projected.pop("verified_legal_context")
    with pytest.raises(ValueError):
        compact.payload_projection_evidence(original, projected, inputs["source_binding_sha256"], now=NOW)


def test_deterministic_projection_evidence_and_small_input_measurement(inputs):
    first = compact.compact_context(**inputs)
    second = compact.compact_context(**inputs)
    assert first == second
    one = compact.projection_evidence(inputs["packet"], first, now=NOW)
    two = compact.projection_evidence(inputs["packet"], second, now=NOW)
    assert one == two
    assert one["projected_source_packet_size"]["characters"] < one["original_source_packet_size"]["characters"]
    assert one["character_reduction_ratio"] > .5


def test_original_packet_with_a_real_failed_gate_is_not_made_valid_by_six_examples(inputs):
    source = deepcopy(inputs["packet"]["graph_source"])
    for row in source["observations"]:
        row["metric_value"] = 1
    inputs["packet"] = bridge.build_packet(source, build_graph(source), inputs["reference_fulltext"],
        inputs["expression_standards"], now=NOW, focus_label="劳动纠纷")
    assert inputs["packet"]["sample_gate"]["passed"] is False
    with pytest.raises(ValueError, match="sample_gate_failed"):
        compact.compact_context(**inputs)


def test_actual_call_524_readonly_projection_preserves_complete_native_payload():
    root = Path("data/production_trials/fresh_legal_full_flow_20261012/round_01")
    raw = root / "call_evidence/call_524/request_body.raw"
    source_file = root / "source/SOURCE_PACKET.json"
    manifest_file = root / "source/SOURCE_MANIFEST.json"
    receipt_file = root / "call_524_fresh_plan_02.json"
    if not raw.exists():
        pytest.skip("actual frozen receipt not present in this checkout")
    watched = [raw, source_file, manifest_file, receipt_file]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
    request = json.loads(raw.read_bytes())
    original = json.loads(request["messages"][1]["content"])
    packet = json.loads(source_file.read_text(encoding="utf-8-sig"))
    assert original["source_packet"] == packet
    receipt = json.loads(receipt_file.read_bytes())
    binding = receipt["source_binding_sha256"]
    assert binding == receipt["request"]["input_provenance"]["source_binding_sha256"]
    now = packet["prepared_at"]
    projected = compact.compact_payload(original, binding, now=now)
    proof = compact.payload_projection_evidence(original, projected, binding, now=now)
    assert proof["character_reduction_ratio"] > .95
    assert proof["original_source_packet_size"]["characters"] == 1_325_099
    assert proof["source_identity"]["source_binding_sha256"] == binding
    assert len(projected["source_packet"]["candidate"]["support_video_ids"]) == 71
    assert len(projected["source_packet"]["tag_catalog"]) == 7
    assert len(projected["source_packet"]["selected_relations"]) == 6
    assert len(projected["source_packet"]["representative_metadata"]) == 6
    assert projected["source_packet"]["sample_gate"] == packet["sample_gate"]
    assert projected["reference_fulltext"] == (root / "source/R01_FULL.md").read_bytes().decode("utf-8-sig")
    assert original["brief"] == projected["brief"]
    assert original["previous_complete_document"] == projected["previous_complete_document"]
    assert original["revision_requirements"] == projected["revision_requirements"]
    # Demonstrate the actual serialized message boundary, without invoking a provider.
    wire = deepcopy(request)
    wire["messages"][1]["content"] = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    received = json.loads(wire["messages"][1]["content"])
    assert received == projected
    assert received["reference_fulltext"] == original["reference_fulltext"]
    assert wire["messages"][0] == request["messages"][0]
    assert {key: value for key, value in wire.items() if key != "messages"} == {
        key: value for key, value in request.items() if key != "messages"}
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
