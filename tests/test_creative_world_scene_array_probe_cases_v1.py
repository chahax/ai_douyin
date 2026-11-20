"""Pure 2x2 schema/context diagnostic; no provider or production provenance."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from scripts import creative_world_scene_array_probe_cases_v1 as m

PROFILE = Path(__file__).resolve().parents[1] / "data/qa/creative_world_scene_live_20261015/LIVE_PROFILE_v1.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("pure diagnostic cannot access network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def cases(): return m.build_cases(json.loads(PROFILE.read_text("utf-8-sig")))


def keywords(value):
    if type(value) is dict:
        yield from value
        for child in value.values(): yield from keywords(child)
    elif type(value) is list:
        for child in value: yield from keywords(child)


def test_four_cases_keep_context_messages_and_wire_parameters_exactly_paired():
    profile=json.loads(PROFILE.read_text("utf-8-sig")); before=deepcopy(profile); rows=m.build_cases(profile)
    assert [r["id"] for r in rows]==["compound_clean","direct_clean","compound_bad_previous","direct_bad_previous"]
    for left,right in (rows[:2],rows[2:]):
        assert left["request"]["messages"]==right["request"]["messages"]
        assert {k:v for k,v in left["request"].items() if k!="structured_schema"}=={k:v for k,v in right["request"].items() if k!="structured_schema"}
        lw,rw=(m.clients.expected_wire_request(r["request"]) for r in (left,right))
        ls=lw["tools"][0]["function"].pop("parameters");rs=rw["tools"][0]["function"].pop("parameters")
        assert lw==rw and ls!=rs
        assert left["context_sha256"]==right["context_sha256"] and left["tool_name"]==right["tool_name"]==m.clients.TOOL_NAME
    assert rows[0]["context_sha256"]!=rows[2]["context_sha256"]
    clean=json.loads(rows[0]["request"]["messages"][1]["content"])
    bad=json.loads(rows[2]["request"]["messages"][1]["content"])
    assert clean["toy_source"]==bad["toy_source"] and set(bad)-set(clean)=={"deliberately_invalid_previous_example"}
    assert len(clean["toy_source"]["beats"])==len(clean["toy_source"]["characters"])==2
    assert "reference_fulltext" not in bad and "legal_grounding" not in bad
    assert all(r["diagnostic_only"] and not r["toy_is_production_script"] for r in rows)
    assert profile==before


def test_direct_representation_has_no_compound_keywords_and_preserves_all_field_types():
    compound,direct=cases()[:2]
    assert {"allOf","prefixItems","if","then","propertyNames"}<=set(keywords(compound["expected_output_schema"]))
    assert not {"allOf","prefixItems","if","then","propertyNames","$ref"}&set(keywords(direct["expected_output_schema"]))
    beat=direct["expected_output_schema"]["properties"]["beats"]["items"]
    assert beat["properties"]["steps"]["type"]=="array"
    assert set(beat["properties"]["ensemble"]["properties"])=={"A","B"}
    assert all(v["type"]=="array" for v in beat["properties"]["ensemble"]["properties"].values())
    native=m.synthetic_control_output();before=deepcopy(native)
    for row in cases():
        assert not list(Draft202012Validator(row["expected_output_schema"]).iter_errors(native))
        assert m.validate(native,row)["valid"]
    assert native==before


def test_invalid_previous_is_explicit_synthetic_and_never_normalized_into_a_pass():
    for row in cases()[2:]:
        payload=json.loads(row["request"]["messages"][1]["content"])
        native=payload["deliberately_invalid_previous_example"]["previous_example"]; before=deepcopy(native)
        checked=m.validate(native,row)
        assert not checked["valid"] and not checked["text_ready_for_director"]
        paths={f["path"] for f in checked["findings"]}
        assert {"/count","/previous_run","/labels","/index_grid","/beats/0/steps","/beats/0/ensemble/A","/beats/0/parallel_with"}<=paths
        assert native==before and checked["native_document_modified"] is False


def test_direct_wire_and_local_relationship_gate_reject_reversed_beats_null_strings_integer_strings_and_wrong_indexes():
    row=cases()[1]; native=m.synthetic_control_output()
    native["beats"].reverse();native["scene_contexts"][0]["previous_context_id"]=""
    native["count"]="2";native["index_grid"][0][0]="0"
    native["beats"][0]["steps"][0]["speaker"]="A"
    native["beats"][0]["ensemble"]["A"][0]["action_step_indexes"]=[1,True]
    native["beats"][0]["parallel_with"][0]["action_step_index"]=99
    before=deepcopy(native);checked=m.validate(native,row)
    assert not checked["valid"]
    paths={f["path"] for f in checked["findings"]}
    assert {"/beats/0/id","/beats/1/id","/scene_contexts/0/previous_context_id","/count","/index_grid/0/0", "/beats/0/steps/0/speaker","/beats/0/ensemble/A/0/action_step_indexes/0","/beats/0/ensemble/A/0/action_step_indexes/1","/beats/0/parallel_with/0/action_step_index"}<=paths
    assert native==before


def test_registered_case_identity_and_constants_cannot_be_mutated_or_reshuffled():
    rows=cases(); original=m.synthetic_control_output()
    bad=deepcopy(rows[0]);bad["request"]["messages"][1]["content"]="{}";bad["request_sha256"]=m.digest(bad["request"])
    with pytest.raises(ValueError):m.validate(original,bad)
    bad=deepcopy(rows[0]);bad["request"]["stage"]="goal_plan";bad["request_sha256"]=m.digest(bad["request"])
    with pytest.raises(ValueError):m.validate(original,bad)
    bad=deepcopy(rows[0]);bad["id"]="direct_clean"
    with pytest.raises(ValueError):m.validate(original,bad)
    rows[0]["expected_output_schema"]["properties"]["beats"]["allOf"][0]["items"]["properties"]["id"]["enum"].append("FAKE")
    assert m.ACTORS==["A","B"] and m.BEATS==["B01","B02"]
    assert "FAKE" not in json.dumps(cases())
    profile=json.loads(PROFILE.read_text("utf-8-sig"));profile["writer"]["parameters"]["reasoning_effort"]="max"
    with pytest.raises(ValueError):m.build_cases(profile)


def test_native_integer_controls_reject_float_and_boolean_even_when_json_schema_or_python_equality_accepts_them():
    row=cases()[1];native=m.synthetic_control_output();native["count"]=2.0
    native["index_grid"]=[[0.0,True],[2.0,3.0]];before=deepcopy(native)
    checked=m.validate(native,row)
    paths={f["path"] for f in checked["findings"] if f["code"]=="NATIVE_INTEGER"}
    assert paths=={"/count","/index_grid/0/0","/index_grid/0/1","/index_grid/1/0","/index_grid/1/1"}
    assert not checked["valid"] and native==before
