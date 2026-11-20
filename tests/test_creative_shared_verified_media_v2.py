"""Focused original-lineage adapter tests; synthetic text only, zero network."""
from copy import deepcopy
import json
import socket
from types import SimpleNamespace

import pytest

from scripts import run_creative_shared_verified_media_v2 as verified
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig, ARK_BASE_URL
from tests.test_creative_complete_production_pipeline_v1 import complete_fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs): raise AssertionError("verified media tests are offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    p = verified.production
    monkeypatch.setattr(p, "ROOT", tmp_path / "text")
    monkeypatch.setattr(p, "OUT", tmp_path / "media")
    root = p.ROOT; root.mkdir()
    script, old_manifest, initial, old_direction, old_perfs = complete_fixture()
    context = json.loads(next(r["text"] for r in old_manifest["provenance_catalog"] if r["source_id"] == "frozen_source_context"))
    casting = {a["id"]: {key: value["value"] for key, value in a["profile"].items()} for a in old_manifest["actors"]}
    x = {"brief": context, "casting": casting, "environment": "离线同一会议室",
        "prop_appearance": {"paper": "白色A4纸"}, "reference_fulltext": "R01离线完整参考夹具",
        "provider_evidence": {"text": "离线能力夹具：文生视频与首帧生视频"},
        "production_preferences": {"language": "普通话", "no_subtitles": True}}
    scope = {"max_new_video_submissions": 1, "budget_reset": False, "batch_authorized": False}
    manifest = p.build_manifest(script, x)
    initial = p.pipeline.build_initial_state(context, manifest)
    direction = p.pipeline.compile_direction(old_direction["native"], script, manifest)
    perfs, completed, state = [], [], initial
    for segment, previous in zip(direction["segments"], old_perfs):
        perf = p.pipeline.compile_performance(previous["native"], script, manifest, segment, state, completed)
        perfs.append(perf); state = perf["planned_ending_state"]; completed += segment["source_refs"]
    complete = p.pipeline.compile_complete(direction, perfs, script, manifest, initial)
    projection = p.shared.compile_segment_context(manifest, script, p.bootstrap_dynamic_state(manifest, x),
        perfs[0]["source_refs"], bootstrap=True)
    prompt = p.pipeline.render_prompt(perfs[0], script, manifest, projection)
    planned = [p.pipeline.render_prompt(row, script, manifest) for row in perfs]
    def review(checks):
        return {"checks": [{"check": key, "status": "pass", "source_refs": list(p.source.catalog(script)),
            "reason": "离线模拟全文审查，不代表真实创作通过"} for key in checks],
            "revision_requirements": [], "review_limitations": ["媒体仍待人工审核，声线未绑定。"]}
    source_review, whole_review = review(p.SCRIPT_CHECKS), review(p.PRODUCTION_CHECKS)
    source_input = {"brief": context, "full_script": script, "script_sha256": p.control.digest(script),
        "source_catalog": p.source.catalog(script), "reference_fulltext": x["reference_fulltext"], "casting": casting}
    whole_input = {"brief": context, "full_current_script": script, "source_catalog": p.source.catalog(script),
        "shared_manifest": manifest, "whole_direction": direction, "complete_compilation": complete,
        "all_local_performances": perfs, "all_planned_video_prompts": planned,
        "opening_actual_video_prompt": prompt, "opening_shared_projection": projection,
        "reference_fulltext": x["reference_fulltext"], "scope": scope}
    ledger = {"calls": []}
    def receipt(ordinal, role, value, user, label, schema=None, rejected=False):
        request = {"role": role, "messages": [{"role": "user", "content": json.dumps(user, ensure_ascii=False)}]}
        if role == "writer":
            schema = schema or {"type": "object"}
            request.update(output_transport=p.transport.VERSION, inner_document_schema=schema)
            request["messages"] = p.transport.build_messages(request["messages"], schema)
            text = p.transport.encode_envelope(value, schema)
            output = json.loads(text)
        else: text = json.dumps(value, ensure_ascii=False); output = value
        result = {"ordinal": ordinal, "label": label,
            "status": "contract_rejected" if rejected else "contract_valid", "request": request,
            "request_sha256": p.control.digest(request), "response_text": text, "output": output,
            "response_metadata": {"response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": 20}}
        if role == "writer": result["document_output"] = value
        if rejected:
            result.update(failure={"category": "validation"}, validation_error="离线明确完整导演来源范围错误")
        path = root / ("call_" + str(ordinal) + ".json"); p.control.write(path, result)
        ledger["calls"].append({"ordinal": ordinal, "label": label, "receipt": path.name})
        return result
    receipt(512, "writer", script, {"offline_writer": True}, "full_script_0")
    receipt(513, "director", source_review, source_input, "full_script_review_0")
    direction_input = {"full_current_script": script, "source_catalog": p.source.catalog(script),
        "shared_manifest": manifest, "planned_initial_state": initial,
        "reference_fulltext": x["reference_fulltext"], "production_preferences": x["production_preferences"]}
    direction_schema = p.pipeline.whole_direction_schema(script, manifest)
    rejected_native = deepcopy(direction["native"])
    rejected_native["segments"][0]["end_source_ref"] = list(p.source.catalog(script))[-1]
    failed = receipt(514, "writer", rejected_native, direction_input, "whole_direction_r0", direction_schema, True)
    revised_input = deepcopy(direction_input)
    revised_input["previous_complete_rejected_versions"] = [{"ordinal": 514,
        "complete_rejected_native": rejected_native, "validation_error": failed["validation_error"],
        "adopted": False, "reported_tokens": 20}]
    receipt(515, "writer", direction["native"], revised_input, "whole_direction_r1", direction_schema)
    state, completed = initial, []
    for ordinal, segment, perf in zip([516, 517], direction["segments"], perfs):
        refs = segment["source_refs"]
        perf_input = {"current_direction": segment, "current_sources": {ref: p.source.catalog(script)[ref] for ref in refs},
            "completed_stimulus_catalog": {ref: p.source.catalog(script)[ref] for ref in completed},
            "shared_manifest": manifest, "planned_initial_state": state, "completed_source_refs": completed,
            "reference_fulltext": x["reference_fulltext"], "production_preferences": x["production_preferences"],
            "actual_future_tail_not_created": True, "planned_state_is_not_pixel_approval": True}
        receipt(ordinal, "writer", perf["native"], perf_input, "performance_" + segment["segment_id"].lower() + "_r0",
            p.pipeline.performance_schema(script, manifest, segment, state, completed))
        state = perf["planned_ending_state"]; completed = completed + refs
        p.control.write(root / "performances" / (segment["segment_id"] + ".json"), perf)
    receipt(518, "director", whole_review, whole_input, "whole_production_review")
    adopted = {"script": script, "script_sha256": p.control.digest(script), "machine_text_review_passed": True,
        "actual_media_quality_passed": False, "user_adopted": False, "writer_ordinal": 512, "review_ordinal": 513}
    h = {"source_writer_ordinal": 512, "source_review_ordinal": 513, "production_review_ordinal": 518,
        "script_sha256": p.control.digest(script), "global_manifest_sha256": p.control.digest(manifest),
        "complete_compilation_sha256": p.control.digest(complete), "text_full_review_passed": True,
        "new_media_authorized": 1, "review_limitations": whole_review["review_limitations"]}
    for name, value in {"INPUT.json": x, "USER_SCOPE.json": scope, "ADOPTED_SOURCE.json": adopted,
        "VIDEO_HANDOFF.json": h, "SHARED_MANIFEST.json": manifest, "WHOLE_DIRECTION.json": direction,
        "PLANNED_INITIAL_STATE.json": initial,
        "COMPLETE_PRODUCTION_COMPILED.json": complete, "BOOTSTRAP_CONTEXT.json": projection,
        "FINAL_PROMPTS.json": {"all_planned_prompts": planned, "opening_actual_prompt": prompt}, "CALL_LEDGER.json": ledger}.items():
        p.control.write(root / name, value)
    runtime = SimpleNamespace(ledger=root / "CALL_LEDGER.json", check=lambda _: None,
        effective_receipt=lambda row: p.control.read(root / row["receipt"]))
    monkeypatch.setattr(p, "runtime", lambda: runtime)
    return SimpleNamespace(root=root, p=p, prompt=prompt, runtime=runtime)


def test_original_native_and_all_reviewed_inputs_bound_without_creative_or_media_approval(prepared):
    proof = verified.verify_bindings()
    assert [r["ordinal"] for r in proof["original_receipt_bindings"]] == [512, 513, 515, 516, 517, 518]
    assert proof["source_native_unchanged"] is True and proof["all_actual_review_inputs_equal"] is True
    assert proof["all_adopted_direction_and_performance_natives_equal"] is True
    assert proof["media_quality_verified"] is False and proof["human_approved"] is False
    assert proof["video_request_modified"] is False


@pytest.mark.parametrize("defect", ["native_substitution", "production_prompt", "unknown_usage", "unknown_review"])
def test_self_consistent_files_cannot_replace_original_native_or_review(prepared, defect):
    p, root = prepared.p, prepared.root
    if defect == "native_substitution":
        adopted = p.control.read(root / "ADOPTED_SOURCE.json")
        adopted["script"]["title"] = "被本地替换的正文"
        adopted["script_sha256"] = p.control.digest(adopted["script"])
        h = p.control.read(root / "VIDEO_HANDOFF.json"); h["script_sha256"] = adopted["script_sha256"]
        p.control.write(root / "ADOPTED_SOURCE.json", adopted); p.control.write(root / "VIDEO_HANDOFF.json", h)
    else:
        path = root / "call_518.json"; r = p.control.read(path)
        if defect == "production_prompt":
            x = json.loads(r["request"]["messages"][0]["content"])
            x["opening_actual_video_prompt"] = "遗漏共用人物档案的另一提示词"
            r["request"]["messages"][0]["content"] = json.dumps(x, ensure_ascii=False)
            r["request_sha256"] = p.control.digest(r["request"])
        elif defect == "unknown_usage": r["response_metadata"]["total_tokens"] = None
        else:
            r["output"]["checks"][0]["status"] = "unknown"
            r["output"]["revision_requirements"] = ["离线模拟未知，不能交付"]
            r["response_text"] = json.dumps(r["output"], ensure_ascii=False)
        p.control.write(path, r)
    with pytest.raises(ValueError): verified.verify_bindings()


@pytest.mark.parametrize("stage", ["direction", "performance"])
def test_self_consistent_local_production_and_whole_review_cannot_replace_original_stage(prepared, stage):
    p, root = prepared.p, prepared.root
    script = p.control.read(root / "ADOPTED_SOURCE.json")["script"]
    manifest = p.control.read(root / "SHARED_MANIFEST.json")
    old = p.control.read(root / "COMPLETE_PRODUCTION_COMPILED.json")
    raw_direction = deepcopy(old["direction"]["native"])
    if stage == "direction": raw_direction["whole_observation"] = "本地另写的整体观察对象"
    direction = p.pipeline.compile_direction(raw_direction, script, manifest)
    state, completed, perfs = old["initial_state"], [], []
    for index, (segment, original) in enumerate(zip(direction["segments"], old["performances"])):
        raw = deepcopy(original["native"])
        if stage == "performance" and index == 0: raw["continuous_performance"] = "本地另写的连贯表演，仍保持当前人物与来源。"
        compiled = p.pipeline.compile_performance(raw, script, manifest, segment, state, completed)
        perfs.append(compiled); state = compiled["planned_ending_state"]; completed = completed + segment["source_refs"]
        p.control.write(root / "performances" / (segment["segment_id"] + ".json"), compiled)
    complete = p.pipeline.compile_complete(direction, perfs, script, manifest, old["initial_state"])
    projection = p.control.read(root / "BOOTSTRAP_CONTEXT.json")
    planned = [p.pipeline.render_prompt(perf, script, manifest) for perf in perfs]
    prompt = p.pipeline.render_prompt(perfs[0], script, manifest, projection)
    p.control.write(root / "WHOLE_DIRECTION.json", direction)
    p.control.write(root / "COMPLETE_PRODUCTION_COMPILED.json", complete)
    p.control.write(root / "FINAL_PROMPTS.json", {"all_planned_prompts": planned, "opening_actual_prompt": prompt})
    handoff = p.control.read(root / "VIDEO_HANDOFF.json")
    handoff["complete_compilation_sha256"] = p.control.digest(complete)
    p.control.write(root / "VIDEO_HANDOFF.json", handoff)
    path = root / "call_518.json"; receipt = p.control.read(path)
    user = json.loads(receipt["request"]["messages"][0]["content"])
    user.update(whole_direction=direction, complete_compilation=complete, all_local_performances=perfs,
        all_planned_video_prompts=planned, opening_actual_video_prompt=prompt)
    receipt["request"]["messages"][0]["content"] = json.dumps(user, ensure_ascii=False)
    receipt["request_sha256"] = p.control.digest(receipt["request"])
    p.control.write(path, receipt)
    # All local compiler checks and the full reviewed input agree, but original
    # model stage receipts remain untouched: this must still block dispatch.
    with pytest.raises(ValueError, match="original model native output"):
        verified.verify_bindings()


@pytest.mark.parametrize("defect", ["wrong_state_prefix", "failed_then_transport_unknown", "two_valid_natives"])
def test_stage_input_and_bounded_revision_lineage_cannot_be_replaced(prepared, defect):
    p, root = prepared.p, prepared.root
    if defect == "wrong_state_prefix":
        path = root / "call_517.json"; receipt = p.control.read(path)
        user = json.loads(receipt["request"]["messages"][0]["content"])
        user["completed_source_refs"] = []
        receipt["request"]["messages"][0]["content"] = json.dumps(user, ensure_ascii=False)
        receipt["request_sha256"] = p.control.digest(receipt["request"])
    else:
        path = root / "call_514.json"; receipt = p.control.read(path)
        if defect == "failed_then_transport_unknown":
            receipt["status"] = "interface_rejected"; receipt["failure"]["category"] = "interface"
        else: receipt["status"] = "contract_valid"
    p.control.write(path, receipt)
    with pytest.raises(ValueError): verified.verify_bindings()


def test_verified_prepare_submit_keep_exact_request_and_unknown_original_id_is_not_resubmitted(prepared, monkeypatch):
    p = prepared.p; calls, reservations = [], []
    class FakeClient:
        def __init__(self, config): self.config = config
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def build_task_payload(self, *args, **kwargs): return SeedanceClient.build_task_payload(self, *args, **kwargs)
        def create_task(self, request): calls.append(deepcopy(request)); raise TimeoutError("offline unknown submission")
        def get_task(self, task_id): raise AssertionError("no original ID; must not query or redispatch")
    monkeypatch.setattr(p, "SeedanceClient", FakeClient)
    monkeypatch.setattr(p.SeedanceConfig, "from_env", lambda *a, **k: SeedanceConfig(
        api_key="offline", base_url=ARK_BASE_URL, model=p.MODEL, provider="ark_api"))
    monkeypatch.setattr(p, "reserve_media_attempt", lambda *args: reservations.append(deepcopy(args[1])))
    old_make_plan = p.make_plan
    original_plan = old_make_plan()
    assert verified.media("media_prepare")["new_paid_calls"] == 0
    plan = p.control.read(p.OUT / "PLAN.json")
    assert plan["prompt"] == original_plan["prompt"] == prepared.prompt
    assert plan["logical_task_id"] == p.LOGICAL and plan["source_run"] is None
    assert plan["budget_reset"] is False and plan["new_submissions"] == 1
    assert plan["references"] == [] and plan["input_mode"] == "text_to_video_bootstrap"
    preview = p.control.read(p.OUT / "REQUEST.preview.json")
    assert preview["content"] == [{"type": "text", "text": prepared.prompt}]
    assert any(path.endswith("run_creative_shared_verified_media_v2.py") for path in plan["sources"])
    with pytest.raises(TimeoutError): verified.media("media_submit")
    with pytest.raises(ValueError, match="never redispatch"): verified.media("media_submit")
    with pytest.raises(ValueError, match="unknown"): verified.media("media_query")
    assert calls == [preview] and len(reservations) == 1
    assert p.make_plan == old_make_plan
