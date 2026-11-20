"""Pure contracts with explicit fake reviews; no semantic/production claim."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import natural_director_contracts_v10 as contracts
from src.content_factory.novel_logic_contracts_v4 import REVIEW_DIMENSIONS

SOURCE = "Complete original source: a daughter leaves and her parent supports her."
DRAFT = "Complete accepted screenplay: daughter packs, parent answers, both reconcile."
DRAFT_SHA = hashlib.sha256(DRAFT.encode()).hexdigest()
NATURAL = "傍晚渡口，父女隔桌。先拍10秒：女儿看父亲说已准备好，父亲抬眼回应并递票；两人近景反应同时推进。再拍10秒：女儿看票后抬眼，父亲看着她说随时回家；她点头走向门口，回头挥手，他回应。"
BRIEF = {"source_kind": "original", "target_duration_seconds": 20, "max_duration_seconds": 23, "duration_tolerance_seconds": 2}


def materials(payload):
    return json.loads(payload["messages"][-1]["content"])


def extract_native():
    return {"verdict": "pass", "whole_text_reviewed": True, "faithful_to_natural": True,
        "summary": "Explicit fake reviewer assessment for contract testing.",
        "checks": {key: "Specific fake assessment of the complete package." for key in REVIEW_DIMENSIONS},
        "issues": [], "segments": [
            {"segment_id": "A", "duration_seconds": 10, "prompt": "女儿面向父亲，抬眼说已准备好。父亲看着她回应递票；越肩近景看清双方即时反应。", "source_notes": "自然导演前半段，两人完整互动；无需逐字引文。"},
            {"segment_id": "B", "duration_seconds": 10, "prompt": "女儿从票抬眼看父亲。父亲看着她说随时回家；她点头走向门口，回头挥手，他回应。近景及门口中景自然衔接。", "source_notes": "自然导演后半段，完整收束。"}]}


def final_native():
    result = extract_native()
    result.pop("segments")
    result.pop("faithful_to_natural")
    result["all_requests_reviewed"] = True
    return result


def extract(value=None, *, natural=NATURAL, brief=None, request_materials=None):
    actual_brief = BRIEF if brief is None else brief
    req = contracts.build_extract_review_payload(SOURCE, DRAFT, natural, brief=actual_brief)
    return contracts.parse_extract_review(json.dumps(extract_native() if value is None else value, ensure_ascii=False),
        source_binding="source", draft_binding=DRAFT_SHA, materials=materials(req) if request_materials is None else request_materials,
        native_response_ref="a" * 64)


def final(extraction=None, value=None):
    extraction = extract() if extraction is None else extraction
    req = contracts.build_final_review_payload(SOURCE, DRAFT, NATURAL, extraction, brief=BRIEF)
    return contracts.parse_final_review(json.dumps(final_native() if value is None else value), source_binding="source",
        draft_binding=DRAFT_SHA, materials=materials(req), native_response_ref="b" * 64)


def evidence(extraction=None):
    extraction = extract() if extraction is None else extraction
    compiled = contracts.compile_video_requests(extraction)

    def binding(label, digest=None):
        return {"path": "D:/isolated_fake_native/" + label + ".json", "bytes": 123,
            "sha256": digest or hashlib.sha256(label.encode()).hexdigest()}

    return {"verified": True, "source_binding": "source", "draft_binding": DRAFT_SHA,
        "natural_director_sha256": hashlib.sha256(NATURAL.encode()).hexdigest(),
        "extract_native_response_ref": "a" * 64, "final_native_response_ref": "b" * 64,
        "video_requests_sha256": compiled["sha256"], "stages": {
            "natural_director": {"request": binding("natural-request"), "response": binding("natural-response")},
            "extract_review": {"request": binding("extract-request"), "response": binding("extract-response", "a" * 64)},
            "final_review": {"request": binding("final-request"), "response": binding("final-response", "b" * 64)}}}


def file_handoff(folder, *, change_request=None, change_response=None):
    """Complete explicit fake native service files, never an actual paid call."""
    protocol = {"writer": {"provider": "minimax", "model": "MiniMax-M3"},
                "director": {"provider": "deepseek", "model": "deepseek-flash"}}
    stages = {}

    def save(label, obj):
        path = (folder / (label + ".json")).resolve()
        raw = json.dumps(obj, ensure_ascii=False).encode()
        path.write_bytes(raw)
        return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def stage(name, role, ordinal, payload, content):
        from src.content_factory.natural_director_pipeline_v10 import _spec
        actual_messages, actual_parameters = _spec(payload)
        req = {"schema": "native-v10-fixture", "ordinal": ordinal, "stage_key": name + "-1", "stage": name,
            "role": role, "source_binding_id": "source", "draft_binding": DRAFT_SHA,
            "messages": deepcopy(actual_messages), "parameters": deepcopy(actual_parameters)}
        if change_request:
            change_request(name, req)
        req_binding = save(name + "-request", req)
        model = protocol[role]["model"]
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        res = {**{key: req[key] for key in ("schema", "ordinal", "stage_key", "stage", "role")},
            "request_binding": req_binding, "response_text": content, "response_metadata": {
                "role": role, "provider": protocol[role]["provider"], "requested_model": model,
                "response_model": model, "response_id": "native-" + name, "finish_reason": "stop", **usage},
            "response_payload": {"id": "native-" + name, "model": model, "usage": usage,
                "choices": [{"finish_reason": "stop", "message": {"content": content, "tool_calls": []}}]}}
        if change_response:
            change_response(name, res)
        response_binding = save(name + "-response", res)
        stages[name] = {"request": req_binding, "response": response_binding}
        return response_binding

    payload = contracts.build_natural_director_payload(SOURCE, DRAFT, brief=BRIEF, feedback=["Preserve full interaction."])
    stage("natural_director", "writer", 1, payload, NATURAL)
    payload = contracts.build_extract_review_payload(SOURCE, DRAFT, NATURAL, brief=BRIEF)
    content = json.dumps(extract_native(), ensure_ascii=False)
    bound = stage("extract_review", "director", 2, payload, content)
    extraction = contracts.parse_extract_review(content, source_binding="source", draft_binding=DRAFT_SHA,
        materials=materials(payload), native_response_ref=bound["sha256"])
    payload = contracts.build_final_review_payload(SOURCE, DRAFT, NATURAL, extraction, brief=BRIEF)
    content = json.dumps(final_native(), ensure_ascii=False)
    bound = stage("final_review", "director", 3, payload, content)
    reviewed = contracts.parse_final_review(content, source_binding="source", draft_binding=DRAFT_SHA,
        materials=materials(payload), native_response_ref=bound["sha256"])
    compiled = contracts.compile_video_requests(extraction)
    proof = {"verified": True, "protocol": protocol, "stages": stages, "source_binding": "source", "draft_binding": DRAFT_SHA,
        "natural_director_sha256": hashlib.sha256(NATURAL.encode()).hexdigest(), "extract_native_response_ref": extraction["native_response_ref"],
        "final_native_response_ref": reviewed["native_response_ref"], "video_requests_sha256": compiled["sha256"]}
    return contracts.make_handoff(NATURAL, extraction, reviewed, source_binding="source", draft_binding=DRAFT_SHA,
        brief=BRIEF, native_evidence=proof)


def test_minimax_gets_natural_contract_and_concise_diagnostics_only():
    payload = contracts.build_natural_director_payload(SOURCE, DRAFT, brief=BRIEF,
        feedback=["The earlier total was too short; replan full interaction naturally."])
    value = materials(payload)
    assert value["source_text"] == SOURCE and value["accepted_full_draft"] == DRAFT
    assert "diagnostic_feedback" in value
    assert not any(key in value for key in ("output_spec", "previous_director", "segments", "scene_ledger"))
    assert not any(key in payload for key in ("tools", "tool_choice", "response_format"))


def test_minimax_does_not_get_old_json_masquerading_as_feedback():
    with pytest.raises(ValueError, match="Feedback"):
        contracts.build_natural_director_payload(SOURCE, DRAFT, brief=BRIEF, feedback={"segments": [{"duration": 90}]})


@pytest.mark.parametrize("natural", [NATURAL, "No fixed segment heading. ten seconds and ten seconds of actual interaction.", "# 自由排版\n人物与环境\n\n自然段内写明完整互动。"])
def test_no_fixed_heading_or_literal_quote_gate_on_natural_director(natural):
    artifact = extract(natural=natural)
    assert artifact["natural_director_sha256"] == hashlib.sha256(natural.encode()).hexdigest()
    assert artifact["native"]["segments"][0]["source_notes"]


def test_extractor_reads_complete_same_source_writer_natural_and_policy():
    value = materials(contracts.build_extract_review_payload(SOURCE, DRAFT, NATURAL, brief=BRIEF))
    assert (value["source_text"], value["accepted_full_draft"], value["natural_director_text"]) == (SOURCE, DRAFT, NATURAL)
    assert value["quality_policy"] == contracts.quality_policy()
    assert "faithful_to_natural" in value["output_spec"]


def test_only_deepseek_stages_request_official_json_output_without_tools():
    natural = contracts.build_natural_director_payload(SOURCE, DRAFT, brief=BRIEF)
    extraction = contracts.build_extract_review_payload(SOURCE, DRAFT, NATURAL, brief=BRIEF)
    final_payload = contracts.build_final_review_payload(SOURCE, DRAFT, NATURAL, extract(), brief=BRIEF)
    assert "response_format" not in natural["parameters"]
    for payload in (extraction, final_payload):
        assert payload["parameters"]["response_format"] == {"type": "json_object"}
        assert "tools" not in payload and "tool_choice" not in payload


def test_all_segments_compile_actual_sdk_requests_without_local_source_notes():
    artifact = extract()
    compiled = contracts.compile_video_requests(artifact)
    assert len(compiled["requests"]) == 2
    for original, actual in zip(artifact["native"]["segments"], compiled["requests"]):
        assert actual["request"]["content"] == [{"type": "text", "text": original["prompt"]}]
        assert actual["request"]["duration"] == original["duration_seconds"]
        assert original["source_notes"] not in actual["request"]["content"][0]["text"]


@pytest.mark.parametrize("change,code", [
    (lambda v: v.update(faithful_to_natural=False), "REVIEW_COVERAGE"),
    (lambda v: v.update(whole_text_reviewed=False), "REVIEW_COVERAGE"),
    (lambda v: v["checks"].pop(REVIEW_DIMENSIONS[-1]), "REVIEW_DIMENSIONS"),
    (lambda v: v["segments"][0].update(duration_seconds=3), "SERVICE_DURATION"),
    (lambda v: v["segments"][0].update(duration_seconds=15), "TOTAL_DURATION"),
    (lambda v: v["segments"][1].update(segment_id="A"), "SEGMENT_ID_DUPLICATE"),
    (lambda v: v["segments"][0].update(prompt=""), "EXTRACT_SEGMENTS"),
    (lambda v: v.update(issues=[{"severity": "major", "location": "A", "evidence": "Missing response", "suggestion": "Return to director"}]), "REVIEW_UNRESOLVED_CONTENT"),
])
def test_known_extraction_contract_failures_are_not_fixed_to_pass(change, code):
    value = extract_native()
    change(value)
    with pytest.raises(contracts.NaturalDirectorContractError) as caught:
        extract(value)
    assert any(error["code"] == code for error in caught.value.errors)


def test_missing_or_ambiguous_native_revise_is_preserved_without_invented_segments():
    value = extract_native()
    value.update(verdict="revise", faithful_to_natural=False, segments=[], issues=[{
        "severity": "major", "location": "natural director ending", "evidence": "No explicit duration or response provided",
        "suggestion": "MiniMax must rewrite the complete natural director", "responsibility_layer": "director"}])
    artifact = extract(value)
    assert artifact["native"] == value and artifact["verdict"] == "revise" and artifact["segments"] == []
    with pytest.raises(ValueError):
        contracts.compile_video_requests(artifact)


def test_native_verdict_or_prompt_cannot_be_rewritten_after_parsing():
    artifact = extract()
    artifact["segments"][0]["prompt"] = "An assistant rewrote this scene."
    with pytest.raises(ValueError, match="differs"):
        contracts.compile_video_requests(artifact)


@pytest.mark.parametrize("change", [
    lambda m: m.update(accepted_full_draft="partial"),
    lambda m: m.update(source_kind="novel"),
    lambda m: m["quality_policy"].update(sha256="wrong"),
    lambda m: m.pop("output_spec"),
])
def test_extraction_cannot_rebind_different_or_incomplete_native_materials(change):
    req = materials(contracts.build_extract_review_payload(SOURCE, DRAFT, NATURAL, brief=BRIEF))
    change(req)
    with pytest.raises(ValueError):
        extract(request_materials=req)


def test_final_review_contains_complete_natural_and_all_actual_requests():
    artifact = extract()
    req = materials(contracts.build_final_review_payload(SOURCE, DRAFT, NATURAL, artifact, brief=BRIEF))
    assert req["natural_director_text"] == NATURAL
    assert req["extract_review"] == artifact["native"]
    assert req["video_requests"] == contracts.compile_video_requests(artifact)
    assert len(req["video_requests"]["requests"]) == 2


@pytest.mark.parametrize("change", [
    lambda m: m["video_requests"]["requests"].pop(),
    lambda m: m["video_requests"]["requests"][0]["request"].update(duration=15),
    lambda m: m.update(natural_director_text="a different director"),
    lambda m: m["extract_binding"].update(materials_sha256="0" * 64),
])
def test_final_review_for_omitted_changed_or_other_requests_cannot_bind(change):
    artifact = extract()
    req = materials(contracts.build_final_review_payload(SOURCE, DRAFT, NATURAL, artifact, brief=BRIEF))
    change(req)
    with pytest.raises(ValueError):
        contracts.parse_final_review(json.dumps(final_native()), source_binding="source", draft_binding=DRAFT_SHA,
            materials=req, native_response_ref="b" * 64)


def test_final_review_must_explicitly_review_every_request():
    value = final_native()
    value["all_requests_reviewed"] = False
    with pytest.raises(contracts.NaturalDirectorContractError, match="REVIEW_COVERAGE"):
        final(value=value)


def test_handoff_and_dispatch_are_native_bound_and_do_not_authorize_media(tmp_path):
    value = file_handoff(tmp_path)
    validation = contracts.validate_handoff_for_dispatch(value)
    assert validation["request_count"] == 2 and validation["production_dispatch_allowed"] is False
    assert value["human_approved"] is False and value["media_status"] == "not_generated"
    assert value["requires_runtime_file_revalidation"] is True


@pytest.mark.parametrize("change", [
    lambda h: h["video_requests"]["requests"][0]["request"].update(duration=15),
    lambda h: h.update(natural_director_text="assistant changed director"),
    lambda h: h["final_review"].update(verdict="revise"),
    lambda h: h["native_evidence"]["stages"].pop("extract_review"),
    lambda h: h["native_evidence"]["stages"]["extract_review"]["response"].update(sha256="c" * 64),
    lambda h: h["native_evidence"]["stages"]["extract_review"]["response"].update(path="relative.json"),
])
def test_changed_native_evidence_or_actual_handoff_requests_stop(tmp_path, change):
    value = file_handoff(tmp_path)
    change(value)
    with pytest.raises(ValueError):
        contracts.validate_handoff_for_dispatch(value)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '[]', '{"x":[1}', 'reasoning only', ''])
def test_extractor_or_final_native_json_is_never_guessed_or_repaired(text):
    with pytest.raises(ValueError):
        contracts.parse_json(text)


def test_verified_true_and_matching_hashes_without_actual_native_files_cannot_pass():
    extraction = extract()
    fake_evidence = evidence(extraction)
    fake_evidence["protocol"] = {"writer": {"provider": "minimax", "model": "MiniMax-M3"},
        "director": {"provider": "deepseek", "model": "deepseek-flash"}}
    with pytest.raises(ValueError, match="missing or unreadable"):
        contracts.make_handoff(NATURAL, extraction, final(extraction), source_binding="source",
            draft_binding=DRAFT_SHA, brief=BRIEF, native_evidence=fake_evidence)


def test_changed_actual_native_file_stops_even_with_verified_true(tmp_path):
    value = file_handoff(tmp_path)
    path = value["native_evidence"]["stages"]["natural_director"]["response"]["path"]
    from pathlib import Path
    Path(path).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="bytes/hash changed"):
        contracts.validate_handoff_for_dispatch(value)


@pytest.mark.parametrize("stage", ["natural_director", "extract_review", "final_review"])
def test_native_unknown_usage_or_truncation_is_not_proof(tmp_path, stage):
    def change(name, response):
        if name == stage:
            response["response_metadata"].pop("total_tokens")
    with pytest.raises(ValueError, match="known usage"):
        file_handoff(tmp_path, change_response=change)


@pytest.mark.parametrize("stage", ["natural_director", "extract_review", "final_review"])
def test_native_old_prompt_cannot_establish_v10_package(tmp_path, stage):
    def change(name, request):
        if name == stage:
            request["messages"][0]["content"] = "An old prompt without these requirements"
    with pytest.raises(ValueError, match="system prompt"):
        file_handoff(tmp_path, change_request=change)


def test_native_extraction_for_partial_source_cannot_be_rebound_as_full(tmp_path):
    def change(name, request):
        if name == "extract_review":
            value = materials(request)
            value["source_text"] = "partial source"
            request["messages"][-1]["content"] = json.dumps(value)
    with pytest.raises(ValueError, match="same complete"):
        file_handoff(tmp_path, change_request=change)


@pytest.mark.parametrize("change", [
    lambda p: p.update(structured_schema=None),
    lambda p: p.update(thinking="enabled"),
    lambda p: p.update(response_format={"type": "json_schema"}),
    lambda p: p.update(max_tokens=20001),
    lambda p: p.update(unknown_field=True),
])
def test_actual_parameter_normalization_rejects_unverified_fields(change):
    value = {"max_tokens": 12000, "temperature": 0.2}
    change(value)
    with pytest.raises(ValueError):
        contracts.normalize_actual_parameters(value)


def test_file_backed_handoff_uses_real_runtime_actual_parameter_spec(tmp_path):
    value = file_handoff(tmp_path)
    from pathlib import Path
    from src.content_factory.natural_director_pipeline_v10 import _spec
    for stage, bound in value["native_evidence"]["stages"].items():
        request = json.loads(Path(bound["request"]["path"]).read_text(encoding="utf-8"))
        assert request["parameters"]["thinking"] == "disabled"
        assert "structured_schema" not in request["parameters"]
        assert ("response_format" in request["parameters"]) == (stage != "natural_director")
        assert _spec({"messages": request["messages"], "parameters": request["parameters"]}) == (request["messages"], request["parameters"])
    assert contracts.validate_handoff_for_dispatch(value)["status"] == "text_requests_verified"
