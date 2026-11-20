"""Protocol fixtures only; fabricated answers are never semantic gold."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from src.content_factory import creative_paired_review_ab_v2 as ab
from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/production_trials/legal_paired_drama_diagnostic_20261015/round_01/call_636_paired_drama_diagnostic_01.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("fixed-corpus tests cannot contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


@pytest.fixture
def experiment():
    receipt = json.loads(SOURCE.read_text("utf-8"))
    profile = json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return ab.prepare_experiment(profile, receipt)


def make_native(experiment, representation):
    """Entire synthetic response: validates shape, makes no semantic assertion."""
    corpus = experiment["corpus"]
    result = {"schema": ab.VERSION, "representation": representation, "corpus_sha256": ab.digest(corpus),
        "context_sha256": experiment["requests"][representation]["context_sha256"], "cases": {}}
    for case in corpus["cases"]:
        readings = {source["id"]: {"role": "context", "atoms": [{"quote": source["text"][:200],
            "literal_reading": "合成响应仅验证原句身份和结构，不评价该案例语义。", "mode": "attribution", "state": None}]}
            for source in case["sources"]}
        row = {"verdict": "supported", "comparison": "合成结构夹具，不是模型结论或语义金标。"}
        if representation == "A":
            row["groups"] = {role: {ref: reading["atoms"] for ref, reading in readings.items() if reading["role"] == role} for role in ab.ROLES}
        else: row["readings"] = readings
        result["cases"][case["id"]] = row
    return result


def atoms(native, representation, case="near_hand", ref="S1"):
    return native["cases"][case]["groups"]["context"][ref] if representation == "A" else native["cases"][case]["readings"][ref]["atoms"]


def decision(experiment, representation, native):
    return ab.validate_response(native, experiment["corpus"], representation,
        context_sha256=experiment["requests"][representation]["context_sha256"])


def test_fixed_actual_source_unchanged_same_corpus_and_no_gold_or_old_opinions_in_wire(experiment):
    before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    receipt = json.loads(SOURCE.read_text("utf-8")); goal = json.loads(receipt["request"]["messages"][1]["content"])["native_goal_document"]
    corpus = experiment["corpus"]
    assert len(corpus["cases"]) == 7 and experiment["source_receipt_sha256"] == ab.digest(receipt)
    assert experiment["native_goal_sha256"] == ab.digest(goal)
    texts = []
    for rep in ab.REPRESENTATIONS:
        prepared = experiment["requests"][rep]
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        assert payload["corpus"] == corpus and prepared["wire"] == expected_wire_request(prepared["request"])
        assert prepared["request"]["parameters"] == ab.PARAMETERS and prepared["request"]["messages"][0]["content"].startswith(ab.RULE)
        assert prepared["request_sha256"] == ab.digest(prepared["request"])
        assert "offline_expectations" not in prepared["request"]["messages"][1]["content"]
        assert "records_by_target" not in prepared["request"]["messages"][1]["content"]
        texts.append(ab._json(payload["corpus"]))
    assert texts[0] == texts[1] == ab._json(corpus)
    for case in corpus["cases"]:
        for source in case["sources"]:
            assert source["text_sha256"] == ab.digest(source["text"])
            if source["native_document_path"]:
                assert ab._at(goal, source["native_document_path"]) == source["text"]
    assert all(len(row["allowed_verdicts"]) == 3 for row in experiment["offline_expectations"].values() if row["kind"] == "non_gold_actual")
    assert before == hashlib.sha256(SOURCE.read_bytes()).hexdigest()


@pytest.mark.parametrize("rep", ab.REPRESENTATIONS)
def test_synthetic_complete_native_shape_passes_but_not_creative_quality_and_groups_are_derived(experiment, rep):
    native = make_native(experiment, rep); result = decision(experiment, rep, native)
    assert result["valid"] and result["accepted"] and result["diagnostic_contract_only"]
    assert not result["creative_quality_passed"] and not result["compiled_groups_are_native_response"]
    assert result["compiled_reference_groups"]["near_hand"]["context"] == ["S1"]
    assert result["native_response_sha256"] == ab.digest(native)


@pytest.mark.parametrize("rep", ab.REPRESENTATIONS)
@pytest.mark.parametrize("fault", ["missing_source", "extra_source", "extra_native_ref_list", "holder_prose", "location_prose", "signature_prose", "participant", "unsupported_counter", "unresolved_pass"])
def test_every_structural_rejection_is_already_visible_in_actual_wire_schema(experiment, rep, fault):
    native = make_native(experiment, rep); row = native["cases"]["near_hand"]; reading = atoms(native, rep)[0]
    container = row["groups"]["context"] if rep == "A" else row["readings"]
    if fault == "missing_source": container.pop("S1")
    elif fault == "extra_source": container["FOREIGN"] = deepcopy(container["S1"])
    elif fault == "extra_native_ref_list": row["evidence"] = ["S1"]
    elif fault == "holder_prose": reading["state"] = {"kind": "holder", "object_id": "paper", "time_id": "after", "character_id": "她手边"}
    elif fault == "location_prose": reading["state"] = {"kind": "location", "object_id": "paper", "time_id": "after", "scene_id": "桌沿"}
    elif fault == "signature_prose": reading["state"] = {"kind": "signature", "object_id": "paper", "time_id": "after", "signer_id": "a", "signed": "已签字"}
    elif fault == "participant": reading["state"] = {"kind": "holder", "object_id": "paper", "time_id": "after", "character_id": "a", "participant_id": "a"}
    elif fault == "unsupported_counter":
        if rep == "A": row["groups"]["unresolved_counter"]["S1"] = row["groups"]["context"].pop("S1")
        else: row["readings"]["S1"]["role"] = "unresolved_counter"
    else: reading["mode"] = "unresolved_reading"
    schema = experiment["requests"][rep]["wire"]["tools"][0]["function"]["parameters"]
    assert list(Draft202012Validator(schema).iter_errors(native)), fault
    result = decision(experiment, rep, native)
    assert not result["valid"] and all(row["code"] == "AB_WIRE_SCHEMA_INVALID" for row in result["findings"])


def test_A_duplicate_source_in_two_groups_is_rejected_by_wire_oneof_not_hidden_set_logic(experiment):
    native = make_native(experiment, "A"); row = native["cases"]["near_hand"]
    row["groups"]["support"]["S1"] = deepcopy(row["groups"]["context"]["S1"])
    assert not decision(experiment, "A", native)["valid"]


@pytest.mark.parametrize("rep", ab.REPRESENTATIONS)
def test_open_future_is_allowed_with_supported_but_unresolved_reading_needs_undetermined(experiment, rep):
    native = make_native(experiment, rep)
    atoms(native, rep, "open_future_outcome", "S2")[0]["mode"] = "open_outcome"
    assert decision(experiment, rep, native)["valid"]
    atoms(native, rep)[0]["mode"] = "unresolved_reading"
    native["cases"]["near_hand"]["verdict"] = "undetermined"
    result = decision(experiment, rep, native)
    assert result["valid"] and not result["all_cases_settled"]


@pytest.mark.parametrize("rep", ab.REPRESENTATIONS)
def test_quote_identity_is_the_documented_local_check_and_other_representation_or_context_rejects(experiment, rep):
    native = make_native(experiment, rep); atoms(native, rep)[0]["quote"] = "原句没有这段文字"
    assert decision(experiment, rep, native)["findings"][0]["code"] == "AB_QUOTE_NOT_IN_OWN_SOURCE"
    with pytest.raises(ValueError):
        ab.validate_response(native, experiment["corpus"], rep, context_sha256="0" * 64)
    wrong = "B" if rep == "A" else "A"
    assert not decision(experiment, wrong, native)["valid"]


def test_profile_and_source_identity_are_checked_before_preparation():
    receipt = json.loads(SOURCE.read_text("utf-8")); profile = json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    bad = deepcopy(receipt); bad["request"]["messages"][1]["content"] += " "
    with pytest.raises(ValueError): ab.prepare_experiment(profile, bad)
    for key, value in (("temperature", .5), ("thinking", "adaptive")):
        wrong = deepcopy(profile); wrong["director"]["parameters"][key] = value
        with pytest.raises(ValueError): ab.prepare_experiment(wrong, receipt)
