"""Native fake receipts prove transport bindings, not creative or video quality."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import narrative_quality_v1 as quality
from src.content_factory import novel_agent_roles_v8 as roles
from src.content_factory import novel_director_handoff_v8 as director
from src.content_factory.novel_logic_contracts_v4 import REVIEW_DIMENSIONS, VERSION

SOURCE = "Complete source seed: a parent and child disagree, then understand."
DRAFT = "Complete native screenplay including its actual ending."
DRAFT_SHA = hashlib.sha256(DRAFT.encode()).hexdigest()


def fact(actor="parent"):
    return {"subject_id": actor, "predicate": "position", "value": "beside table",
            "certainty": "explicit", "evidence_refs": ["scene-1"], "qualifiers": {}}


def ledger():
    return {"header": {"artifact_id": "ledger", "schema_version": VERSION,
        "source_binding": "source", "draft_binding": DRAFT_SHA, "producer_version": "fixture",
        "parent_artifact_ids": [], "status": "complete"}, "events": [{"event_id": "E1",
        "timeline_id": "present", "narrative_layer": "performance", "entities": ["parent", "child"],
        "relation": "new_event", "referent_event_id": None, "before": [fact()], "after": [fact()],
        "interpretation_status": "explicit", "context": {"scene_id": "room", "location": "table",
        "description": "Parent asks; child replies without looking away."}}]}


def person(actor):
    return {"actor_id": actor, "action": actor + " turns toward the other person",
            "expression": actor + " looks tense", "gaze_target": "the other speaker's eyes",
            "gaze_change": "from paper to the other speaker", "head_body_orientation": "body beside table, head turned toward partner",
            "dialogue": "Wait." if actor == "parent" else "I have a plan.",
            "response": actor + " registers the partner's answer",
            "camera_visibility": actor + " face readable in reverse close-up"}


def body():
    people = [person("parent"), person("child")]
    actions = [{"event_id": "E1", "actor_id": p["actor_id"], "action": p["action"],
        "expression": p["expression"], "gaze": p["gaze_target"], "dialogue": p["dialogue"],
        "reaction": p["response"], "reaction_window": "during the partner's sentence"} for p in people]
    return {"world_framework": "Contemporary family room, two adults beside the table.",
        "selected_scope": "A complete disagreement and mutual response.", "segments": [{
        "segment_id": "S1", "timeline_id": "present", "location": "family room", "environment": "warm evening light",
        "time_context": "Present evening, immediately after the parent spots the travel bag",
        "present_characters": ["parent", "child"], "start_state": [fact(), fact("child")],
        "end_state": [fact(), fact("child")], "performance": actions, "emotion_focus": "a decision becomes understood",
        "next_cause": "both now understand the plan", "estimated_duration_seconds": 8,
        "duration_basis": "natural short exchange with simultaneous responses", "beats": [{
        "beat_id": "B1", "start_seconds": 0, "end_seconds": 8, "event_ids": ["E1"],
        "stimulus": "a travel bag appears beside the table", "camera": "two-shot into reverse close-up",
        "information_change": "the parent learns the child has a plan", "participants": people}]}],
        "event_coverage": [{"event_id": "E1", "segment_ids": ["S1"], "relation": "new_event"}],
        "asset_requirements": []}


def parse(value=None, **overrides):
    args = {"source_binding": "source", "draft_binding": DRAFT_SHA, "text_gate_artifact_id": "gate",
            "scene_ledger": ledger(), "episode_artifact_id": "episode", "source_kind": "original",
            "target_duration_seconds": 8, "brief": {"target_duration_seconds": 8, "max_duration_seconds": 9}}
    args.update(overrides)
    return director.parse_director(json.dumps(body() if value is None else value), **args)


def native_review():
    return {"verdict": "pass", "whole_text_reviewed": True, "summary": "Fake reviewer read the whole package.",
        "responsibility_layer": "none",
        "checks": [{"dimension": key, "checked": True, "assessment": "Concrete fake fixture assessment.", "issues": []}
                   for key in REVIEW_DIMENSIONS]}


def native_files(folder, *, mutate_review_request=None):
    plan = parse()
    protocol = {"writer": {"provider": "minimax", "model": "MiniMax-M3"},
                "director": {"provider": "deepseek", "model": "deepseek-flash"}}

    def write(name, value):
        path = (folder / name).resolve()
        data = json.dumps(value, ensure_ascii=False).encode()
        path.write_bytes(data)
        return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def req(stage, role, ordinal, payload):
        return {"schema": "native-fixture", "stage": stage, "stage_key": stage + "1", "role": role,
                "ordinal": ordinal, "source_binding_id": "source", **payload}

    def response(request, binding, text):
        role = request["role"]
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        model = protocol[role]["model"]
        return {**{key: request[key] for key in ("schema", "stage", "stage_key", "role", "ordinal")},
            "request_binding": binding, "response_text": text,
            "response_metadata": {"role": role, "provider": protocol[role]["provider"], "requested_model": model,
                "response_model": model, "response_id": "r1", "finish_reason": "stop", **usage},
            "response_payload": {"id": "r1", "model": model, "usage": usage,
                "choices": [{"finish_reason": "stop", "message": {"content": text, "tool_calls": []}}]}}

    payload = director.build_director_payload(SOURCE, DRAFT, ledger(), source_binding="source",
        draft_binding=DRAFT_SHA, text_gate_artifact_id="gate", episode_artifact_id="episode",
        target_duration_seconds=8, source_kind="original", brief=plan["brief"])
    request = req("director_full", "writer", 1, payload)
    drq = write("drq.json", request)
    drs = write("drs.json", response(request, drq, json.dumps(body())))
    payload = director.build_director_review_payload(SOURCE, DRAFT, plan, target_duration_seconds=8)
    if mutate_review_request:
        payload = mutate_review_request(payload)
    request = req("director_review", "director", 2, payload)
    rrq = write("rrq.json", request)
    rrs = write("rrs.json", response(request, rrq, json.dumps(native_review())))
    review = director.parse_director_review(json.dumps(native_review()), source_binding="source",
        draft_binding=DRAFT_SHA, director=plan, native_response_ref=rrs["sha256"])
    evidence = {"protocol": protocol, "source_text": SOURCE, "draft_text": DRAFT,
        "director_request_binding": drq, "director_response_binding": drs,
        "review_request_binding": rrq, "review_response_binding": rrs}
    return plan, review, evidence


def test_shared_policy_is_detached_and_hashed():
    first = quality.quality_policy()
    first["requirements"]["interaction"] = "changed"
    assert first != quality.quality_policy()
    with pytest.raises(ValueError):
        quality.validate_quality_policy(first)


@pytest.mark.parametrize("kind", ["novel", "original"])
def test_writer_and_review_materials_share_frozen_policy(kind):
    source = {"binding_id": "source", "text": SOURCE}
    brief = {"source_kind": kind, "target_duration_seconds": 8, "location": "青岚河"}
    writer = roles.build_writer_payload(source, brief=brief)
    review = roles.build_review_payload(source, DRAFT, brief=brief)
    assert writer["quality_policy"] == review["quality_policy"] == quality.quality_policy()
    assert writer["source_kind"] == review["source_kind"] == kind
    assert writer["brief"] == review["brief"] == brief


def test_native_extra_field_is_preserved_and_not_silently_dropped():
    value = body()
    value["native_creative_note"] = "This original note remains available to the reviewer."
    assert parse(value)["native_creative_note"] == value["native_creative_note"]


def test_compiler_preserves_both_actors_beats_and_all_segments_without_json_evidence():
    value = body()
    second = deepcopy(value["segments"][0])
    second["segment_id"] = "S2"
    value["segments"].append(second)
    value["event_coverage"][0]["segment_ids"].append("S2")
    plan = parse(value, target_duration_seconds=16, brief={"max_duration_seconds": 16})
    compiled = director.compile_video_requests(plan)
    assert len(compiled["requests"]) == 2
    assert [r["duration_seconds"] for r in compiled["requests"]] == [8, 8]
    for item in compiled["requests"]:
        prompt = item["prompt"]
        assert "parent registers" in prompt and "child registers" in prompt
        assert "head turned toward partner" in prompt and "reverse close-up" in prompt
        assert prompt.count("Wait.") == prompt.count("I have a plan.") == 1
        assert "gaze_target" not in prompt and "evidence_refs" not in prompt and "subject_id" not in prompt
        assert item["request"]["content"] == [{"type": "text", "text": prompt}]


@pytest.mark.parametrize("change,code", [
    (lambda b: b["segments"][0].pop("beats"), "DIRECTOR_BEATS_REQUIRED"),
    (lambda b: b["segments"][0]["beats"][0].update(start_seconds=1), "DIRECTOR_BEAT_TIME"),
    (lambda b: b["segments"][0]["beats"][0]["participants"].pop(), "DIRECTOR_BEAT_ACTOR_COVERAGE"),
    (lambda b: b["segments"][0]["beats"][0].update(event_ids=["unknown"]), "DIRECTOR_BEAT_EVENT_COVERAGE"),
    (lambda b: b["segments"][0].update(estimated_duration_seconds=28), "DIRECTOR_SERVICE_DURATION"),
])
def test_mechanical_omissions_and_capability_errors_stop_before_review(change, code):
    value = body()
    change(value)
    with pytest.raises(director.DirectorContractError) as caught:
        parse(value)
    assert any(error["code"] == code for error in caught.value.errors)


def test_reasonable_silence_and_averted_gaze_are_not_automatically_rejected():
    value = body()
    for row in value["segments"][0]["beats"][0]["participants"]:
        row.update(dialogue="", gaze_target="the acceptance letter", gaze_change="averts to protect composure",
                   response="silently realizes the other person already knows")
    value["segments"][0]["beats"][0]["information_change"] = "Their shared silence reveals acceptance."
    assert director.compile_video_requests(parse(value))["requests"]


def test_frozen_total_duration_bounds_are_enforced():
    with pytest.raises(director.DirectorContractError, match="DIRECTOR_TOTAL_DURATION"):
        parse(brief={"max_duration_seconds": 7})


def test_whole_package_review_contains_exact_all_final_requests():
    plan = parse()
    payload = director.build_director_review_payload(SOURCE, DRAFT, plan, target_duration_seconds=8)
    materials = json.loads(payload["messages"][-1]["content"])
    assert materials["video_requests"] == director.compile_video_requests(plan)
    assert materials["quality_policy"] == quality.quality_policy()


def test_native_evidence_handoff_and_dispatch_rebuild_same_requests(tmp_path):
    plan, review, evidence = native_files(tmp_path)
    handoff = director.make_handoff(plan, review, source_binding="source", draft_binding=DRAFT_SHA,
                                   native_evidence=evidence)
    assert handoff["model_capabilities_compiled"] is True
    assert director.validate_handoff_for_dispatch(handoff)["request_count"] == 1
    assert handoff["production_dispatch_allowed"] is False
    handoff["video_requests"]["requests"][0]["request"]["duration"] = 15
    with pytest.raises(director.DirectorContractError, match="REVIEW_DISPATCH_REQUEST_MISMATCH"):
        director.validate_handoff_for_dispatch(handoff)


def test_saved_review_that_omitted_final_requests_cannot_make_handoff(tmp_path):
    def omit(payload):
        content = json.loads(payload["messages"][-1]["content"])
        content.pop("video_requests")
        payload["messages"][-1]["content"] = json.dumps(content)
        return payload
    plan, review, evidence = native_files(tmp_path, mutate_review_request=omit)
    with pytest.raises(director.DirectorContractError, match="DIRECTOR_NATIVE_REVIEW_INPUT_MISMATCH"):
        director.make_handoff(plan, review, source_binding="source", draft_binding=DRAFT_SHA,
                              native_evidence=evidence)


def test_changed_system_prompt_cannot_be_claimed_as_v8_review(tmp_path):
    def change(payload):
        payload["messages"][0]["content"] = "Old JSON-only review"
        return payload
    plan, review, evidence = native_files(tmp_path, mutate_review_request=change)
    with pytest.raises(director.DirectorContractError, match="DIRECTOR_NATIVE_PROMPT_MISMATCH"):
        director.make_handoff(plan, review, source_binding="source", draft_binding=DRAFT_SHA,
                              native_evidence=evidence)


def roles_native_files(folder, *, change_materials=None, change_response=None):
    source = {"binding_id": "source", "text": SOURCE}
    materials = roles.build_review_payload(source, DRAFT, brief={"source_kind": "original", "target_duration_seconds": 8})
    if change_materials:
        change_materials(materials)
    request = {"schema": "native-fixture", "source_binding_id": "source", "role": "director",
        "stage": "review_full", "stage_key": "review-1", "ordinal": 1, "messages": [
        {"role": "system", "content": roles.REVIEW_PROMPT}, {"role": "user", "content": json.dumps(materials)}]}
    scene_ledger = ledger()
    scene_ledger.pop("header")
    raw = {"scene_ledger": scene_ledger, "full_review": {"native_verdict": "pass",
        "whole_text_reviewed": True, "source_complete": True, "draft_complete": True,
        "checks": [{"dimension": key, "checked": True, "assessment": "Fixture whole-text assessment", "issue_ids": []}
            for key in REVIEW_DIMENSIONS], "issues": []}, "adjudication": {"new_issues": [], "dispositions": []}}
    text = json.dumps(raw)

    def save(name, obj):
        path = (folder / name).resolve()
        data = json.dumps(obj).encode()
        path.write_bytes(data)
        return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    request_binding = save("roles-request.json", request)
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    response = {**{key: request[key] for key in ("schema", "stage", "stage_key", "role", "ordinal")},
        "request_binding": request_binding, "response_text": text, "response_metadata": {
        "provider": "deepseek", "role": "director", "requested_model": "deepseek-flash",
        "response_model": "deepseek-flash", "response_id": "roles-r1", "finish_reason": "stop", **usage},
        "response_payload": {"id": "roles-r1", "model": "deepseek-flash", "usage": usage,
        "choices": [{"finish_reason": "stop", "message": {"content": text}}]}}
    if change_response:
        change_response(response)
    response_binding = save("roles-response.json", response)
    review = roles.parse_review_bundle(text, source_binding="source", draft_binding=DRAFT_SHA,
        native_response_ref=response_binding["sha256"], artifact_prefix="roles-1")["review"]
    return dict(request=request, response=response, source=source, screenplay=DRAFT,
        protocol={"director": {"provider": "deepseek", "model": "deepseek-flash"}}, review=review,
        request_binding=request_binding, response_binding=response_binding)


def test_v8_roles_native_evidence_reproduces_same_policy_and_original_brief(tmp_path):
    proof = roles.verify_review_evidence(**roles_native_files(tmp_path))
    assert proof["quality_policy_sha256"] == quality.quality_policy()["sha256"]
    assert proof["native_verdict"] == "pass"


@pytest.mark.parametrize("change", [
    lambda value: value.pop("quality_policy"),
    lambda value: value.update(source_kind="novel"),
    lambda value: value.update(screenplay="partial draft"),
    lambda value: value["output_spec"].clear(),
])
def test_v8_roles_native_evidence_rejects_missing_policy_kind_fulltext_or_spec(tmp_path, change):
    data = roles_native_files(tmp_path, change_materials=change)
    with pytest.raises(ValueError):
        roles.verify_review_evidence(**data)


@pytest.mark.parametrize("change", [
    lambda value: value["response_metadata"].pop("total_tokens"),
    lambda value: value["response_metadata"].update(finish_reason="length"),
    lambda value: value.update(ordinal=2),
])
def test_v8_roles_native_evidence_stops_unknown_usage_truncation_or_wrong_request(tmp_path, change):
    data = roles_native_files(tmp_path, change_response=change)
    with pytest.raises(ValueError):
        roles.verify_review_evidence(**data)


@pytest.mark.parametrize("layer", ["writer", "director", "compiler"])
def test_review_keeps_native_responsibility_layer_for_runtime_routing(layer):
    raw = native_review()
    raw.update(verdict="revise", responsibility_layer=layer)
    raw["checks"][0]["issues"] = [{"severity": "major", "location": "S1",
        "evidence": "Concrete fixture substantive issue", "suggestion": "Repair in the stated layer"}]
    parsed = director.parse_director_review(json.dumps(raw), source_binding="source", draft_binding=DRAFT_SHA,
        director=parse(), native_response_ref="fake-native-file")
    assert parsed["responsibility_layer"] == layer and parsed["native_verdict"] == "revise"
