"""General syntax projection and content diagnostics, no live service calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from src.content_factory import novel_director_handoff_v9 as director
from src.content_factory import novel_director_handoff_v8 as previous

H = runpy.run_path(str(Path(__file__).with_name("test_narrative_quality_v8.py")))


def kwargs():
    return {"source_binding": "source", "draft_binding": H["DRAFT_SHA"], "text_gate_artifact_id": "gate",
        "scene_ledger": H["ledger"](), "episode_artifact_id": "episode", "source_kind": "original",
        "target_duration_seconds": 8, "brief": {"target_duration_seconds": 8, "max_duration_seconds": 9}}


def parse(value=None, **changes):
    args = kwargs()
    args.update(changes)
    return director.parse_director(json.dumps(H["body"]() if value is None else value), **args)


@pytest.mark.parametrize("raw", [
    '{"a":[{"x":"name","n":1}}',
    '```json\n{"outer":[{"a":[{"text":"数组 ] 在字符串里","x":false}}, {"a":[{"text":"other","x":null}}]}\n```',
])
def test_only_missing_array_closers_are_inserted_without_changing_native_values(raw):
    projected = director.project_native_json(raw)
    proof = projected["native_projection"]
    assert proof["insertions"] and proof["content_modified"] is False
    assert proof["value_tokens_preserved"] is True
    assert director._value_tokens(director._body_and_offset(raw)[0]) == director._value_tokens(projected["normalized_json"])
    rebuilt = raw
    for edit in reversed(proof["insertions"]):
        pos = edit["native_codepoint_offset"]
        rebuilt = rebuilt[:pos] + edit["text"] + rebuilt[pos:]
    assert director._parse_object(rebuilt) == projected["native_object"]


@pytest.mark.parametrize("raw", [
    '{"a":"unfinished}', '{"a":[1,2', '{"a":1 "b":2}', '{"a":}',
    '{"a":[{"text":"hello"}', '{"a":[{"x":1,"x":2}}}',
    '{"a": NaN}', '{"a":[1 2]}', '{"a":1',
])
def test_ambiguous_or_non_array_syntax_is_never_guessed(raw):
    with pytest.raises((director.DirectorContractError, ValueError)):
        director.project_native_json(raw)


def test_projection_bound_stops_instead_of_unlimited_repair():
    with pytest.raises(director.DirectorContractError):
        director.project_native_json('{"a":[{"b":[{"c":1}}}', max_insertions=1)


def test_empty_redundant_reaction_uses_existing_same_actor_beat_without_content_addition():
    value = H["body"]()
    value["segments"][0]["performance"][0]["reaction"] = ""
    with pytest.raises(previous.DirectorContractError):
        previous.parse_director(json.dumps(value), **kwargs())
    parsed = parse(value)
    assert parsed["segments"][0]["performance"][0]["reaction"] == ""
    assert parsed["redundant_field_coverage"][0]["content_added"] is False
    assert parsed["redundant_field_coverage"][0]["covered_by"] == ["$.segments[0].beats[0].participants[0].response"]


def test_empty_reaction_is_not_forgiven_by_another_actor_or_empty_response():
    value = H["body"]()
    value["segments"][0]["performance"][0]["reaction"] = ""
    value["segments"][0]["beats"][0]["participants"][0]["response"] = ""
    with pytest.raises(director.DirectorContractError):
        parse(value)


def test_content_errors_aggregate_timing_overlap_and_event_coverage_without_fixing_them():
    value = H["body"]()
    value["segments"][0]["performance"][0]["reaction"] = ""
    value["segments"][0]["beats"][0]["start_seconds"] = 1
    value["event_coverage"][0]["segment_ids"].append("does-not-exist")
    result = director.diagnose_known_director(json.dumps(value), **{**kwargs(), "brief": {"min_duration_seconds": 10}})
    assert result["status"] == "content_revision_required"
    codes = {error["code"] for error in result["errors"]}
    assert {"DIRECTOR_BEAT_TIME", "DIRECTOR_TOTAL_DURATION", "DIRECTOR_EVENT_COVERAGE_MISMATCH"} <= codes
    assert result["native_object"] == value
    assert result["native_projection"]["content_modified"] is False


def test_unknown_event_is_rejected_and_not_silently_rebound():
    value = H["body"]()
    value["event_coverage"][0]["event_id"] = "not-in-source"
    result = director.diagnose_known_director(json.dumps(value), **kwargs())
    assert result["status"] == "content_revision_required"
    assert any(error["code"] == "DIRECTOR_EVENT_INVENTED" for error in result["errors"])


def test_compiler_uses_beats_as_single_authority_and_never_inserts_native_evidence():
    value = H["body"]()
    value["segments"][0]["performance"][0]["action"] = "INDEX ONLY: should not be extra motion"
    value["segments"][0]["performance"][0]["dialogue"] = "INDEX SHOULD NOT SPEAK"
    parsed = parse(value)
    prompt = director.compile_video_requests(parsed)["requests"][0]["prompt"]
    assert "INDEX ONLY" not in prompt and "INDEX SHOULD NOT SPEAK" not in prompt
    assert prompt.count("Wait.") == prompt.count("I have a plan.") == 1
    assert "parent registers" in prompt and "child registers" in prompt
    assert "native_projection" not in prompt and "evidence_refs" not in prompt
    review = director.build_director_review_payload(H["SOURCE"], H["DRAFT"], parsed, target_duration_seconds=8)
    material = json.loads(review["messages"][-1]["content"])
    assert material["director"]["native_director_text"] == json.dumps(value)
    assert material["director"]["native_projection"] == parsed["native_projection"]


def native_files(folder, *, parent_v8=False, projected_syntax=False, omit_projection=False):
    value = H["body"]()
    text = json.dumps(value)
    if projected_syntax:
        text = text.replace('"participants": [', '"participants": [', 1)
        # Remove exactly the array closing bracket between participants and beat.
        marker = text.rfind(']}]}]')
        if marker < 0:
            # Locate it structurally from the final participant object.
            ending = text.index('"event_coverage"')
            position = text.rfind(']', 0, ending)
            # The last ] closes segments; the preceding closes beats, and the
            # preceding one closes participants. Remove the beats closer.
            position = text.rfind(']', 0, position)
            text = text[:position] + text[position + 1:]
        else:
            text = text[:marker] + text[marker + 1:]
    plan = director.parse_director(text, **kwargs())
    protocol = {"writer": {"provider": "minimax", "model": "MiniMax-M3"},
        "director": {"provider": "deepseek", "model": "deepseek-flash"}}

    def save(name, obj):
        path = (folder / name).resolve()
        raw = json.dumps(obj, ensure_ascii=False).encode()
        path.write_bytes(raw)
        return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def request(stage, role, ordinal, payload):
        return {"schema": "v9-native-fixture", "stage": stage, "stage_key": stage + "-1",
            "role": role, "ordinal": ordinal, "source_binding_id": "source", **payload}

    def response(req, binding, content):
        model = protocol[req["role"]]["model"]
        usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        return {**{key: req[key] for key in ("schema", "stage", "stage_key", "role", "ordinal")},
            "request_binding": binding, "response_text": content, "response_metadata": {
                "role": req["role"], "provider": protocol[req["role"]]["provider"],
                "requested_model": model, "response_model": model, "response_id": "r1", "finish_reason": "stop", **usage},
            "response_payload": {"id": "r1", "model": model, "usage": usage,
                "choices": [{"finish_reason": "stop", "message": {"content": content, "tool_calls": []}}]}}

    builder = previous if parent_v8 else director
    payload = builder.build_director_payload(H["SOURCE"], H["DRAFT"], H["ledger"](),
        **{key: value for key, value in kwargs().items() if key != "scene_ledger"})
    dr = request("director_full", "writer", 1, payload)
    drq = save("drq.json", dr)
    drs = save("drs.json", response(dr, drq, text))
    payload = director.build_director_review_payload(H["SOURCE"], H["DRAFT"], plan, target_duration_seconds=8)
    if omit_projection:
        materials = json.loads(payload["messages"][-1]["content"])
        materials["director"].pop("native_projection")
        payload["messages"][-1]["content"] = json.dumps(materials)
    rr = request("director_review", "director", 2, payload)
    rrq = save("rrq.json", rr)
    rrs = save("rrs.json", response(rr, rrq, json.dumps(H["native_review"]())))
    review = director.parse_director_review(json.dumps(H["native_review"]()), source_binding="source",
        draft_binding=H["DRAFT_SHA"], director=plan, native_response_ref=rrs["sha256"])
    evidence = {"protocol": protocol, "source_text": H["SOURCE"], "draft_text": H["DRAFT"],
        "director_request_binding": drq, "director_response_binding": drs,
        "review_request_binding": rrq, "review_response_binding": rrs}
    return plan, review, evidence


@pytest.mark.parametrize("parent_v8", [False, True])
def test_native_v8_or_v9_director_can_be_reaudited_by_exact_v9_package(tmp_path, parent_v8):
    plan, review, evidence = native_files(tmp_path, parent_v8=parent_v8)
    handoff = director.make_handoff(plan, review, source_binding="source", draft_binding=H["DRAFT_SHA"], native_evidence=evidence)
    assert director.validate_handoff_for_dispatch(handoff)["request_count"] == 1


def test_v9_review_that_did_not_receive_original_projection_cannot_pass_handoff(tmp_path):
    plan, review, evidence = native_files(tmp_path, parent_v8=True, omit_projection=True)
    with pytest.raises(director.DirectorContractError):
        director.make_handoff(plan, review, source_binding="source", draft_binding=H["DRAFT_SHA"], native_evidence=evidence)


def test_projected_old_native_syntax_is_reproduced_from_original_files_and_reaudited(tmp_path):
    plan, review, evidence = native_files(tmp_path, parent_v8=True, projected_syntax=True)
    assert plan["native_projection"]["insertions"]
    handoff = director.make_handoff(plan, review, source_binding="source", draft_binding=H["DRAFT_SHA"], native_evidence=evidence)
    assert director.validate_handoff_for_dispatch(handoff)["request_count"] == 1


def test_changed_projection_or_raw_native_text_is_not_accepted():
    parsed = parse()
    parsed["native_projection"]["content_modified"] = True
    with pytest.raises(director.DirectorContractError, match="DIRECTOR_NATIVE_PROJECTION"):
        director.compile_video_requests(parsed)
