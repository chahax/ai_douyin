"""Director contracts: whole-draft boundaries, genuine coverage, and no media claim."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from src.content_factory import novel_director_handoff_v7 as director
from src.content_factory.novel_logic_contracts_v4 import REVIEW_DIMENSIONS, VERSION

SOURCE_TEXT = "Whole acquired source, including its actual ending."
DRAFT_TEXT = "Whole accepted native screenplay, including its actual ending."
DRAFT_BINDING = hashlib.sha256(DRAFT_TEXT.encode("utf-8")).hexdigest()
QA_TEMP = Path(__file__).resolve().parents[1] / "data/qa/novel_full_v7_20261018/director_native_fixtures"


def fact(actor="father", value="table"):
    return {"subject_id": actor, "predicate": "relative_position", "value": value,
            "certainty": "explicit", "evidence_refs": ["scene-1:opening"], "qualifiers": {}}


def ledger():
    return {"header": {"artifact_id": "ledger-1", "schema_version": VERSION,
                        "source_binding": "source-1", "draft_binding": DRAFT_BINDING,
                        "producer_version": "fixture/v1", "parent_artifact_ids": [], "status": "complete"},
            "events": [{"event_id": "E01", "timeline_id": "present", "narrative_layer": "performance",
                        "entities": ["father", "son"], "relation": "new_event", "referent_event_id": None,
                        "before": [fact()], "after": [fact()], "interpretation_status": "explicit",
                        "context": {"scene_id": "room", "location": "scene-1:opening",
                                    "description": "Father asks and son responds at the table."}}]}


def action(actor="father"):
    return {"event_id": "E01", "actor_id": actor, "action": "Stops beside the table and speaks.",
            "expression": "Tense but restrained.", "gaze": "Toward the other speaker.",
            "dialogue": "Wait.", "reaction": "The other person looks up during the sentence.",
            "reaction_window": "A visible breath before and after the sentence."}


def body():
    return {"world_framework": "Contemporary home. Father and son disagree; both remain beside a table.",
            "selected_scope": "Only the acquired first-chapter disagreement and its immediate response.",
            "segments": [{"segment_id": "S01", "timeline_id": "present", "location": "room",
                          "environment": "Table beside the doorway", "present_characters": ["father", "son"],
                          "start_state": [fact(), fact("son")], "end_state": [fact(), fact("son")],
                          "performance": [action(), action("son")], "emotion_focus": "A request is resisted.",
                          "next_cause": "The son answers in this same scene; this scope ends.",
                          "estimated_duration_seconds": 8,
                          "duration_basis": "Two short lines overlap with readable reactions."}],
            "event_coverage": [{"event_id": "E01", "segment_ids": ["S01"], "relation": "new_event"}],
            "asset_requirements": [{"asset_type": "character", "search_tags": ["father", "adult_male"],
                                    "status": "pending", "candidate_id": None, "candidate_version": None}]}


def parse(value=None, **overrides):
    arguments = {"source_binding": "source-1", "draft_binding": DRAFT_BINDING, "text_gate_artifact_id": "gate-1",
                 "scene_ledger": ledger(), "episode_artifact_id": "episode-1"}
    arguments.update(overrides)
    return director.parse_director(json.dumps(body() if value is None else value), **arguments)


def native_review(verdict="pass"):
    result = {"verdict": verdict, "whole_text_reviewed": True, "summary": "All director segments checked.",
              "checks": [{"dimension": dimension, "checked": True,
                          "assessment": "The current scene supports this requirement.", "issues": []}
                         for dimension in REVIEW_DIMENSIONS]}
    if verdict == "revise":
        result["checks"][0]["issues"] = [{"severity": "major", "location": "S01",
                                          "evidence": "Director replaced the father's original motivation.",
                                          "suggestion": "Restore the accepted motivation in the director plan."}]
    return result


def review(plan=None, value=None):
    return director.parse_director_review(json.dumps(native_review() if value is None else value),
                                           source_binding="source-1", draft_binding=DRAFT_BINDING,
                                           director=parse() if plan is None else plan,
                                           native_response_ref="response-1.json")


def handoff(plan=None, checked=None, **overrides):
    plan = parse() if plan is None else plan
    checked = review(plan) if checked is None else checked
    QA_TEMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=QA_TEMP) as folder:
        evidence, proof_checked = native_files(Path(folder), plan, checked)
        arguments = {"source_binding": "source-1", "draft_binding": DRAFT_BINDING, "native_evidence": evidence}
        arguments.update(overrides)
        return director.make_handoff(plan, proof_checked, **arguments)


def native_files(folder, plan=None, checked=None, native_plan_body=None):
    """Explicit fake service receipts exercise evidence checks, never paid calls."""
    plan = parse() if plan is None else plan
    checked = review(plan) if checked is None else checked
    protocol = {"writer": {"provider": "minimax", "model": "MiniMax-M3"},
                "director": {"provider": "deepseek", "model": "deepseek-flash"}}

    def write(name, value):
        path = (folder / name).resolve()
        data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(data)
        return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def request(stage, role, number, payload):
        return {"schema": "fixture-native/v5", "ordinal": number, "stage": stage,
                "stage_key": stage + "-unique", "role": role, "source_binding_id": "source-1",
                "messages": payload["messages"], "parameters": payload["parameters"], "input_bindings": {}}

    def response(req, binding, text):
        role = req["role"]
        model = protocol[role]["model"]
        usage = {"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100}
        metadata = {"role": role, "provider": protocol[role]["provider"], "requested_model": model,
                    "response_model": model, "response_id": "response-" + str(req["ordinal"]),
                    "finish_reason": "stop", **usage}
        return {**{key: req[key] for key in ("schema", "ordinal", "stage", "stage_key", "role")},
                "request_binding": binding, "response_text": text, "response_metadata": metadata,
                "response_payload": {"id": metadata["response_id"], "model": model, "usage": usage,
                    "choices": [{"finish_reason": "stop", "message": {"content": text, "tool_calls": []}}]}}

    director_req = request("director_full", "writer", 1, director.build_director_payload(
        SOURCE_TEXT, DRAFT_TEXT, ledger(), source_binding="source-1", draft_binding=DRAFT_BINDING,
        text_gate_artifact_id="gate-1", episode_artifact_id="episode-1"))
    drq = write("DIRECTOR_REQUEST.json", director_req)
    director_text = json.dumps(native_plan_body if native_plan_body is not None else
        {key: plan[key] for key in ("world_framework", "selected_scope", "segments", "event_coverage", "asset_requirements")})
    drs = write("DIRECTOR_RESPONSE.json", response(director_req, drq, director_text))
    review_req = request("director_review", "director", 2, director.build_director_review_payload(SOURCE_TEXT, DRAFT_TEXT, plan))
    rrq = write("REVIEW_REQUEST.json", review_req)
    review_text = json.dumps({key: checked[key] for key in ("verdict", "whole_text_reviewed", "summary", "checks")})
    rrs = write("REVIEW_RESPONSE.json", response(review_req, rrq, review_text))
    proof_checked = deepcopy(checked)
    if proof_checked.get("native_response_ref") == "response-1.json":
        proof_checked["native_response_ref"] = rrs["sha256"]
    return {"protocol": protocol, "source_text": SOURCE_TEXT, "draft_text": DRAFT_TEXT,
            "director_request_binding": drq, "director_response_binding": drs,
            "review_request_binding": rrq, "review_response_binding": rrs}, proof_checked


def codes(exc):
    return {item["code"] for item in exc.value.errors}


def test_real_consumable_director_contains_all_performers_and_program_bound_parents():
    original = body()
    value = parse(original)
    assert value["header"]["parent_artifact_ids"] == ["gate-1", "ledger-1", "episode-1"]
    assert value["world_framework"] == original["world_framework"]
    assert {item["actor_id"] for item in value["segments"][0]["performance"]} == {"father", "son"}
    assert original == body()


def test_model_echoed_hashes_and_headers_cannot_override_program_binding():
    value = body()
    value.update(header={"draft_binding": "false-model-echo", "status": "passed"}, text_gate_artifact_id="old-gate")
    result = parse(value)
    assert result["header"]["draft_binding"] == DRAFT_BINDING
    assert result["text_gate_artifact_id"] == "gate-1"


def test_one_event_can_continue_across_multiple_segments_without_inventing_new_event():
    value = body()
    second = deepcopy(value["segments"][0])
    second["segment_id"] = "S02"
    value["segments"].append(second)
    value["event_coverage"][0].update(segment_ids=["S01", "S02"], relation="continuation")
    result = parse(value)
    assert len(result["segments"]) == 2
    assert result["event_coverage"][0]["event_id"] == "E01"


def test_missing_a_required_accepted_event_is_detected_even_when_internal_coverage_is_consistent():
    scenes = ledger()
    second = deepcopy(scenes["events"][0])
    second["event_id"] = "E02"
    scenes["events"].append(second)
    with pytest.raises(director.DirectorContractError) as exc:
        parse(scene_ledger=scenes)
    assert "DIRECTOR_EVENT_OMITTED" in codes(exc)


def test_absent_event_cannot_be_invented_in_both_performance_and_coverage_to_bypass_cross_check():
    value = body()
    value["event_coverage"][0]["event_id"] = "fabricated"
    for item in value["segments"][0]["performance"]:
        item["event_id"] = "fabricated"
    with pytest.raises(director.DirectorContractError) as exc:
        parse(value)
    assert {"DIRECTOR_EVENT_OMITTED", "DIRECTOR_EVENT_INVENTED"}.issubset(codes(exc))


@pytest.mark.parametrize("change,expected", [
    (lambda value: value["segments"][0]["performance"].pop(), "DIRECTOR_CHARACTER_COVERAGE"),
    (lambda value: value["segments"][0]["performance"][0].update(actor_id="absent-person"), "DIRECTOR_CHARACTER_COVERAGE"),
    (lambda value: value["segments"][0].update(start_state=[]), "DIRECTOR_STATE_INCOMPLETE"),
    (lambda value: value["segments"][0].update(end_state=[fact()]), "DIRECTOR_STATE_INCOMPLETE"),
    (lambda value: value.update(world_framework=""), "DIRECTOR_FORMAT"),
    (lambda value: value.update(selected_scope=" "), "DIRECTOR_FORMAT"),
    (lambda value: value["segments"][0]["performance"][0].update(gaze=""), "SIDECAR_FORMAT"),
    (lambda value: value["segments"][0].update(estimated_duration_seconds=True), "SIDECAR_FORMAT"),
])
def test_incomplete_performance_and_state_are_rejected_in_director_layer(change, expected):
    value = body()
    change(value)
    with pytest.raises(director.DirectorContractError) as exc:
        parse(value)
    assert expected in codes(exc)


def test_actor_absent_from_event_cannot_be_added_by_adding_them_to_segment_present_list():
    value = body()
    value["segments"][0]["present_characters"].append("stranger")
    value["segments"][0]["performance"].append(action("stranger"))
    value["segments"][0]["start_state"].append(fact("stranger"))
    value["segments"][0]["end_state"].append(fact("stranger"))
    with pytest.raises(director.DirectorContractError) as exc:
        parse(value)
    assert "DIRECTOR_ACTOR_INVENTED" in codes(exc)


def test_summary_layer_does_not_force_duplicate_summary_and_performed_event():
    scenes = ledger()
    summary = deepcopy(scenes["events"][0])
    summary.update(event_id="SUMMARY01", narrative_layer="summary")
    scenes["events"].append(summary)
    assert parse(scene_ledger=scenes)["event_coverage"][0]["event_id"] == "E01"


@pytest.mark.parametrize("bad", ["{", "[]", "null", '{"segments":[],"segments":[]}',
                                  '```json\n{}\n```\nextra', '{"x":NaN}', 'preamble\n{}'])
def test_truncated_or_duplicate_json_is_never_reassembled_into_a_passed_director(bad):
    with pytest.raises(director.DirectorContractError):
        director.parse_director(bad, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                 text_gate_artifact_id="gate-1", episode_artifact_id="episode-1", scene_ledger=ledger())


def test_single_complete_json_fence_is_accepted_without_literal_layout_requirement():
    result = director.parse_director("```json\n" + json.dumps(body()) + "\n```", source_binding="source-1",
                                      draft_binding=DRAFT_BINDING, text_gate_artifact_id="gate-1",
                                      episode_artifact_id="episode-1", scene_ledger=ledger())
    assert result["world_framework"]


@pytest.mark.parametrize("alias", ["T1", "T1_present_ferryhall", "flashback", " present "])
def test_timeline_labels_are_opaque_ids_bound_only_from_known_events(alias):
    native = body()
    native["segments"][0]["timeline_id"] = alias
    original = deepcopy(native)
    result = parse(native)
    assert result["segments"][0]["timeline_id"] == "present"
    assert result["timeline_binding"]["aliases"] == [{"native_timeline_id": alias,
        "canonical_timeline_id": "present", "segment_ids": ["S01"], "event_ids": ["E01"]}]
    assert result["timeline_binding"]["semantic_pass"] is False
    assert result["timeline_binding"]["performance_text_modified"] is False
    assert native == original


def two_timelines(first_alias="T1", second_alias="T2"):
    scenes = ledger()
    past = deepcopy(scenes["events"][0])
    past.update(event_id="E02", timeline_id="past")
    scenes["events"].append(past)
    native = body()
    native["segments"][0]["timeline_id"] = first_alias
    second = deepcopy(native["segments"][0])
    second.update(segment_id="S02", timeline_id=second_alias)
    for row in second["performance"]:
        row["event_id"] = "E02"
    native["segments"].append(second)
    native["event_coverage"].append({"event_id": "E02", "segment_ids": ["S02"], "relation": "new_event"})
    return native, scenes


def test_distinct_native_aliases_bind_to_distinct_known_timelines_without_semantic_guessing():
    native, scenes = two_timelines()
    result = parse(native, scene_ledger=scenes)
    assert [segment["timeline_id"] for segment in result["segments"]] == ["present", "past"]
    assert [(row["native_timeline_id"], row["canonical_timeline_id"]) for row in result["timeline_binding"]["aliases"]] == [
        ("T1", "present"), ("T2", "past")]


def test_same_alias_cannot_be_reused_for_two_different_source_timelines():
    native, scenes = two_timelines("T1", "T1")
    with pytest.raises(director.DirectorContractError) as exc:
        parse(native, scene_ledger=scenes)
    error = next(row for row in exc.value.errors if row["code"] == "DIRECTOR_TIMELINE_ALIAS_CONFLICT")
    context = json.loads(error["message"])
    assert context["segment_id"] == "S02" and context["event_ids"] == ["E02"]
    assert context["native_timeline_id"] == "T1" and context["expected_source_timeline_ids"] == ["past"]
    assert context["prior_canonical_timeline_id"] == "present"


@pytest.mark.parametrize("first_alias,second_alias", [("past", "T2"), ("T1", "present")])
def test_native_label_already_naming_other_known_timeline_is_never_overwritten(first_alias, second_alias):
    native, scenes = two_timelines(first_alias, second_alias)
    with pytest.raises(director.DirectorContractError) as exc:
        parse(native, scene_ledger=scenes)
    error = next(row for row in exc.value.errors if row["code"] == "DIRECTOR_TIMELINE_CANONICAL_CONFLICT")
    context = json.loads(error["message"])
    assert context["native_timeline_id"] in {"present", "past"}
    assert context["expected_source_timeline_ids"] == (["present"] if first_alias == "past" else ["past"])


def test_one_segment_with_events_from_two_source_timelines_is_not_guessed_or_bound():
    native, scenes = two_timelines()
    native["segments"] = native["segments"][:1]
    native["segments"][0]["performance"][1]["event_id"] = "E02"
    native["event_coverage"][1]["segment_ids"] = ["S01"]
    with pytest.raises(director.DirectorContractError) as exc:
        parse(native, scene_ledger=scenes)
    error = next(row for row in exc.value.errors if row["code"] == "DIRECTOR_TIMELINE_MIXED_EVENTS")
    context = json.loads(error["message"])
    assert context == {"segment_id": "S01", "event_ids": ["E01", "E02"],
                       "native_timeline_id": "T1", "expected_source_timeline_ids": ["past", "present"]}


def test_unknown_event_cannot_use_known_events_to_make_partial_timeline_binding():
    native = body()
    native["segments"][0]["timeline_id"] = "T1"
    native["segments"][0]["performance"][1]["event_id"] = "UNKNOWN"
    native["event_coverage"].append({"event_id": "UNKNOWN", "segment_ids": ["S01"], "relation": "unknown"})
    with pytest.raises(director.DirectorContractError) as exc:
        parse(native)
    error = next(row for row in exc.value.errors if row["code"] == "DIRECTOR_EVENT_INVENTED" and row["location"].endswith("timeline_id"))
    context = json.loads(error["message"])
    assert context["unknown_event_ids"] == ["UNKNOWN"] and context["event_ids"] == ["E01", "UNKNOWN"]
    assert context["expected_source_timeline_ids"] == ["present"]


def test_same_alias_can_continue_same_event_across_segments_with_complete_mapping():
    native = body()
    native["segments"][0]["timeline_id"] = "T1"
    second = deepcopy(native["segments"][0])
    second["segment_id"] = "S02"
    native["segments"].append(second)
    native["event_coverage"][0].update(segment_ids=["S01", "S02"], relation="continuation")
    result = parse(native)
    assert result["timeline_binding"]["aliases"][0]["segment_ids"] == ["S01", "S02"]
    assert result["timeline_binding"]["aliases"][0]["event_ids"] == ["E01"]


def test_timeline_binding_preserves_all_other_content_including_240_second_estimate():
    native = body()
    native["segments"][0].update(timeline_id="T1_present_ferryhall", estimated_duration_seconds=240)
    result = parse(native)
    for field in ("world_framework", "selected_scope", "event_coverage", "asset_requirements"):
        assert result[field] == native[field]
    normalized = deepcopy(result["segments"])
    normalized[0]["timeline_id"] = native["segments"][0]["timeline_id"]
    assert normalized == native["segments"]
    assert result["native_director_text_sha256"] == hashlib.sha256(json.dumps(native).encode("utf-8")).hexdigest()


def test_native_file_proof_reproduces_alias_binding_and_preserves_original_receipt(tmp_path):
    native = body()
    native["segments"][0]["timeline_id"] = "T1_present_ferryhall"
    plan = parse(native)
    evidence, checked = native_files(tmp_path, plan, native_plan_body=native)
    response_path = Path(evidence["director_response_binding"]["path"])
    original = response_path.read_bytes()
    result = director.make_handoff(plan, checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                    native_evidence=evidence)
    assert result["status"] == "director_text_ready_for_production"
    assert result["director"]["segments"][0]["timeline_id"] == "present"
    assert result["director"]["timeline_binding"]["aliases"][0]["native_timeline_id"] == "T1_present_ferryhall"
    assert response_path.read_bytes() == original
    raw_text = json.loads(original)["response_payload"]["choices"][0]["message"]["content"]
    assert json.loads(raw_text)["segments"][0]["timeline_id"] == "T1_present_ferryhall"


def test_mapping_metadata_cannot_be_handwritten_after_native_director_receipt(tmp_path):
    native = body()
    native["segments"][0]["timeline_id"] = "T1"
    plan = parse(native)
    plan["timeline_binding"]["aliases"][0]["native_timeline_id"] = "forged-label"
    checked = review(plan)
    evidence, checked = native_files(tmp_path, plan, checked, native_plan_body=native)
    with pytest.raises(director.DirectorContractError) as exc:
        director.make_handoff(plan, checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                native_evidence=evidence)
    assert "DIRECTOR_NATIVE_DERIVATION_MISMATCH" in codes(exc)


def test_id_binding_itself_never_substitutes_for_native_deepseek_pass(tmp_path):
    native = body()
    native["segments"][0]["timeline_id"] = "T1"
    plan = parse(native)
    evidence, checked = native_files(tmp_path, plan, review(plan, native_review("revise")), native_plan_body=native)
    with pytest.raises(director.DirectorContractError) as exc:
        director.make_handoff(plan, checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                native_evidence=evidence)
    assert "DIRECTOR_REVIEW_NOT_PASSED" in codes(exc)


@pytest.mark.parametrize("field,value", [("draft_binding", "stale"), ("source_binding", "wrong-source"), ("status", "invalidated")])
def test_stale_scene_ledger_is_rejected_before_constructing_director_request(field, value):
    scenes = ledger()
    scenes["header"][field] = value
    with pytest.raises(director.DirectorContractError):
        director.build_director_payload("whole source", "accepted whole draft", scenes,
            source_binding="source-1", draft_binding=DRAFT_BINDING, text_gate_artifact_id="gate-1", episode_artifact_id="episode-1")


def test_director_revision_prompt_contains_full_frozen_source_full_accepted_draft_and_full_prior_director():
    previous = parse()
    result = director.build_director_payload("whole source\nEND", "accepted whole draft\nEND", ledger(),
        source_binding="source-1", draft_binding=DRAFT_BINDING, text_gate_artifact_id="gate-1",
        episode_artifact_id="episode-1", previous_director=previous, revision_feedback={"problem": "timing"})
    material = json.loads(result["messages"][1]["content"])
    assert material["source_text"] == "whole source\nEND"
    assert material["accepted_full_draft"] == "accepted whole draft\nEND"
    assert material["previous_director"] == previous
    assert material["revision_feedback"] == {"problem": "timing"}
    assert result["parameters"] == {"max_tokens": 16000, "temperature": 0.2}
    assert "model" not in result and "tools" not in result["parameters"]


def test_review_request_contains_same_full_source_full_draft_and_every_director_segment():
    plan = parse()
    result = director.build_director_review_payload("complete source", "complete draft", plan)
    material = json.loads(result["messages"][1]["content"])
    assert material["source_text"] == "complete source" and material["accepted_full_draft"] == "complete draft"
    assert material["director"] == plan and material["review_schema"]


def test_frozen_user_duration_goal_reaches_both_director_generation_and_independent_review():
    generation = director.build_director_payload("source", "draft", ledger(), source_binding="source-1",
        draft_binding=DRAFT_BINDING, text_gate_artifact_id="gate-1", episode_artifact_id="episode-1", target_duration_seconds=180)
    checking = director.build_director_review_payload("source", "draft", parse(), target_duration_seconds=180)
    assert json.loads(generation["messages"][1]["content"])["target_duration_seconds"] == 180
    assert json.loads(checking["messages"][1]["content"])["target_duration_seconds"] == 180


@pytest.mark.parametrize("value", [True, 0, -1, float("nan"), float("inf"), "180"])
def test_invalid_duration_goal_cannot_be_silently_sent_to_director(value):
    with pytest.raises(ValueError):
        director.build_director_review_payload("source", "draft", parse(), target_duration_seconds=value)


def test_director_asset_choice_request_contains_metadata_but_keeps_local_paths_and_receipts_local():
    candidates = [{"candidate_id": "asset-1", "candidate_version": "v1", "asset_type": "character",
                   "name": "Father", "style": "photoreal", "integrity": "ok", "path": "private-local-file.png",
                   "receipt": {"internal": "local-only"}},
                  {"candidate_id": "broken-asset", "candidate_version": "v1", "integrity": "hash_mismatch"}]
    generation = director.build_director_payload("source", "draft", ledger(), source_binding="source-1",
        draft_binding=DRAFT_BINDING, text_gate_artifact_id="gate-1", episode_artifact_id="episode-1", catalog_candidates=candidates)
    material = json.loads(generation["messages"][1]["content"])
    assert len(material["catalog_candidates"]) == 1
    assert material["catalog_candidates"][0]["candidate_id"] == "asset-1"
    assert "private-local-file" not in generation["messages"][1]["content"]
    assert "receipt" not in material["catalog_candidates"][0]


def test_director_review_records_native_verdict_and_canonical_same_director_binding():
    plan = parse()
    result = review(plan)
    assert result["native_verdict"] == "pass"
    assert result["director_sha256"] == director.artifact_sha256(plan)
    assert result["header"]["parent_artifact_ids"] == [plan["header"]["artifact_id"]]


@pytest.mark.parametrize("change", [
    lambda value: value["checks"].pop(),
    lambda value: value["checks"].__setitem__(0, deepcopy(value["checks"][1])),
    lambda value: value.update(whole_text_reviewed=False),
    lambda value: value["checks"][0].update(assessment=""),
])
def test_director_review_must_cover_all_nine_dimensions_and_whole_scope(change):
    value = native_review()
    change(value)
    with pytest.raises(director.DirectorContractError):
        review(value=value)


def test_native_revise_cannot_be_turned_into_handoff_by_local_validity_or_no_more_budget():
    plan = parse()
    checked = review(plan, native_review("revise"))
    with pytest.raises(director.DirectorContractError) as exc:
        handoff(plan, checked)
    assert "DIRECTOR_REVIEW_NOT_PASSED" in codes(exc)


def test_native_pass_with_major_issue_is_not_releaseable():
    value = native_review("revise")
    value["verdict"] = "pass"
    with pytest.raises(director.DirectorContractError) as exc:
        review(value=value)
    assert "REVIEW_VERDICT_CONFLICT" in codes(exc)


def test_complete_pass_creates_text_handoff_without_media_or_human_approval():
    plan = parse()
    checked = review(plan)
    before = deepcopy((plan, checked))
    result = handoff(plan, checked)
    assert result["status"] == "director_text_ready_for_production"
    assert result["estimated_duration_seconds"] == 8 and result["duration_is_estimate"] is True
    assert result["media_status"] == "not_generated"
    for key in ("human_approved", "assets_bound", "model_capabilities_compiled", "production_dispatch_allowed", "publishing_allowed"):
        assert result[key] is False
    assert (plan, checked) == before


@pytest.mark.parametrize("change", [
    lambda plan, checked: checked["header"].update(draft_binding="other-draft"),
    lambda plan, checked: checked["header"].update(source_binding="other-source"),
    lambda plan, checked: checked["header"].update(status="invalidated"),
    lambda plan, checked: checked["header"].pop("artifact_id"),
    lambda plan, checked: checked.update(director_sha256="0" * 64),
    lambda plan, checked: checked.update(director_artifact_id="other-director"),
    lambda plan, checked: checked.update(native_response_ref=""),
    lambda plan, checked: plan["segments"][0]["performance"][0].update(dialogue="A later local patch, never reviewed."),
])
def test_wrong_review_or_local_patch_after_native_review_cannot_enter_handoff(change):
    plan = parse()
    checked = review(plan)
    change(plan, checked)
    with pytest.raises(director.DirectorContractError):
        handoff(plan, checked)


def test_handoff_requires_runtime_native_evidence_verification_not_only_a_model_pass_string():
    with pytest.raises(director.DirectorContractError) as exc:
        handoff(native_evidence=False)
    assert "DIRECTOR_NATIVE_EVIDENCE_REQUIRED" in codes(exc)


def test_old_public_boolean_keyword_no_longer_constructs_formal_ready_json():
    with pytest.raises(TypeError):
        director.make_handoff(parse(), review(), source_binding="source-1", draft_binding=DRAFT_BINDING,
                                native_evidence_verified=True)


def replace_native(evidence, key, mutate):
    binding = evidence[key]
    path = Path(binding["path"])
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(data)
    evidence[key] = {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if key.endswith("request_binding"):
        response_key = key.replace("request_binding", "response_binding")
        replace_native(evidence, response_key, lambda value: value.update(request_binding=evidence[key]))


@pytest.mark.parametrize("failure", ["missing_file", "changed_file", "unknown_usage", "truncated",
                                     "wrong_model", "wrong_role", "wrong_source", "different_draft",
                                     "different_director", "wrong_request_parent"])
def test_handoff_actually_reads_and_checks_native_files_not_callers_assertions(tmp_path, failure):
    plan = parse()
    evidence, checked = native_files(tmp_path, plan)
    if failure == "missing_file":
        Path(evidence["director_response_binding"]["path"]).unlink()
    elif failure == "changed_file":
        Path(evidence["director_response_binding"]["path"]).write_bytes(b"changed behind the frozen SHA")
    elif failure == "unknown_usage":
        replace_native(evidence, "review_response_binding", lambda value: value["response_metadata"].pop("total_tokens"))
    elif failure == "truncated":
        replace_native(evidence, "review_response_binding", lambda value: value["response_metadata"].update(finish_reason="length"))
    elif failure == "wrong_model":
        replace_native(evidence, "review_response_binding", lambda value: value["response_payload"].update(model="other-model"))
    elif failure == "wrong_role":
        replace_native(evidence, "review_response_binding", lambda value: value.update(role="writer"))
    elif failure in ("wrong_source", "different_draft", "different_director"):
        def changed_input(value):
            materials = json.loads(value["messages"][-1]["content"])
            if failure == "wrong_source":
                materials["source_text"] = "A shorter source pretending to be complete."
            elif failure == "different_draft":
                materials["accepted_full_draft"] = "A different complete accepted draft."
            else:
                materials["director"]["segments"][0]["performance"][0]["dialogue"] = "A different unreviewed director line."
            value["messages"][-1]["content"] = json.dumps(materials)
        replace_native(evidence, "review_request_binding", changed_input)
    elif failure == "wrong_request_parent":
        replace_native(evidence, "review_response_binding", lambda value: value["request_binding"].update(sha256="0" * 64))
    with pytest.raises(director.DirectorContractError):
        director.make_handoff(plan, checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                native_evidence=evidence)


def test_native_response_cannot_back_a_locally_rewritten_same_director_review(tmp_path):
    plan = parse()
    evidence, checked = native_files(tmp_path, plan)
    checked["summary"] = "A local replacement that was never in the original DeepSeek body."
    with pytest.raises(director.DirectorContractError) as exc:
        director.make_handoff(plan, checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                native_evidence=evidence)
    assert "DIRECTOR_NATIVE_DERIVATION_MISMATCH" in codes(exc)


def test_native_four_file_evidence_supports_runtime_frozen_source_and_screenplay_fields(tmp_path):
    plan = parse()
    evidence, checked = native_files(tmp_path, plan)
    evidence["source"] = {"binding_id": "source-1", "text": evidence.pop("source_text")}
    evidence["screenplay"] = evidence.pop("draft_text")
    result = director.make_handoff(plan, checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                    native_evidence=evidence)
    assert result["status"] == "director_text_ready_for_production"
    assert set(result["native_evidence_bindings"]) == {"director_request_binding", "director_response_binding",
                                                       "review_request_binding", "review_response_binding"}


def test_caller_cannot_relabel_different_draft_text_as_the_saved_native_sha(tmp_path):
    evidence, checked = native_files(tmp_path)
    evidence["draft_text"] += "A later local patch."
    with pytest.raises(director.DirectorContractError) as exc:
        director.make_handoff(parse(), checked, source_binding="source-1", draft_binding=DRAFT_BINDING,
                                native_evidence=evidence)
    assert "DIRECTOR_NATIVE_DRAFT_MISMATCH" in codes(exc)


@pytest.mark.parametrize("status", ["invalidated", "incomplete"])
def test_invalidated_director_never_gains_fresh_review_or_handoff_from_otherwise_valid_fields(status):
    plan = parse()
    checked = review(plan)
    plan["header"]["status"] = status
    with pytest.raises(director.DirectorContractError):
        director.build_director_review_payload("source", "draft", plan)
    with pytest.raises(director.DirectorContractError):
        review(plan)
    with pytest.raises(director.DirectorContractError):
        handoff(plan, checked)


def test_per_segment_finite_durations_cannot_overflow_total_handoff_duration():
    value = body()
    value["segments"][0]["estimated_duration_seconds"] = 1e308
    other = deepcopy(value["segments"][0])
    other["segment_id"] = "S02"
    value["segments"].append(other)
    value["event_coverage"][0]["segment_ids"].append("S02")
    plan = parse(value)
    checked = review(plan)
    with pytest.raises(director.DirectorContractError) as exc:
        handoff(plan, checked)
    assert "DIRECTOR_DURATION_OVERFLOW" in codes(exc)


def make_catalog(tmp_path):
    image = tmp_path / "asset.bin"
    image.write_bytes(b"real local fixture bytes")
    expected = hashlib.sha256(image.read_bytes()).hexdigest()
    asset = {"asset_id": "own.father", "version": "v2", "name": "Father", "kind": "character",
             "style": "photoreal", "details": {"aliases": ["dad"], "tags": ["adult_male"]},
             "image": {"path": str(image), "expected_sha256": expected, "integrity": "ok"},
             "current_casting": {"status": "bound"}, "current_media_approval": True}
    path = tmp_path / "CATALOG.json"
    path.write_text(json.dumps({"assets": [asset]}), encoding="utf-8")
    return path, image


def test_asset_discovery_uses_stable_local_identity_actual_hash_and_preserves_catalog(tmp_path):
    path, image = make_catalog(tmp_path)
    before = path.read_bytes()
    result = director.discover_asset_candidates(path.parent, ["adult_male"], asset_type="character")
    assert len(result) == 1
    assert result[0]["candidate_id"] == "own.father" and result[0]["candidate_version"] == "v2"
    assert result[0]["integrity"] == "ok"
    assert result[0]["current_casting_status"] == "unbound" and result[0]["current_media_approval"] is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", ["changed", "missing"])
def test_asset_stale_catalog_integrity_does_not_promote_missing_or_changed_file(tmp_path, failure):
    path, image = make_catalog(tmp_path)
    if failure == "changed":
        image.write_bytes(b"changed")
    else:
        image.unlink()
    result = director.discover_asset_candidates(path, ["father"])
    assert result[0]["integrity"] == ("hash_mismatch" if failure == "changed" else "missing")
    assert result[0]["status"] == "unavailable"


def test_asset_candidate_is_checked_against_current_discovery_not_invented_by_model(tmp_path):
    path, _ = make_catalog(tmp_path)
    candidates = director.discover_asset_candidates(path, ["father"])
    value = body()
    value["asset_requirements"][0].update(status="candidate", candidate_id="own.father", candidate_version="v2")
    assert parse(value, catalog_candidates=candidates)["asset_requirements"][0]["status"] == "candidate"
    with pytest.raises(director.DirectorContractError) as exc:
        parse(value, catalog_candidates=[])
    assert "DIRECTOR_ASSET_CANDIDATE_UNKNOWN" in codes(exc)


def test_verified_scene_candidate_cannot_silently_be_cast_as_character(tmp_path):
    path, _ = make_catalog(tmp_path)
    candidates = director.discover_asset_candidates(path, ["father"])
    candidates[0]["asset_type"] = "scene"
    value = body()
    value["asset_requirements"][0].update(status="candidate", candidate_id="own.father", candidate_version="v2")
    with pytest.raises(director.DirectorContractError) as exc:
        parse(value, catalog_candidates=candidates)
    assert "DIRECTOR_ASSET_CANDIDATE_UNKNOWN" in codes(exc)


@pytest.mark.parametrize("field", ["bound", "human_approved", "media_approved", "production_binding", "api_native_eligibility"])
def test_asset_extension_cannot_smuggle_current_approval(field):
    value = body()
    value["asset_requirements"][0][field] = True
    with pytest.raises(director.DirectorContractError) as exc:
        parse(value)
    assert "DIRECTOR_ASSET_APPROVAL_FORGED" in codes(exc)
