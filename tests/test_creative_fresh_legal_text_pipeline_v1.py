"""Offline fresh-source routing fixtures, not creative quality judgments."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_fresh_legal_text_pipeline_v1 as fresh
from src.content_factory import creative_autonomous_text_contract_v6 as contract
from src.content_factory import creative_shared_production_contract_v1 as shared
from tests.test_creative_legal_tag_graph_bridge_v1 import bundle, NOW
from tests.test_creative_autonomous_text_pipeline_v1 import plan_for


BINDING = "a" * 64
PROVIDER = {"text": "Offline fixture provider declaration; not live service acceptance.",
    "provider_id": "ark_api", "model": "doubao-seedance-2-0-mini-260428", "status": "verified",
    "identity_reference_mode": "text_to_video_bootstrap", "allowed_reference_modes": ["text_to_video_bootstrap", "first_frame"],
    "allows_actor_asset_mapping": None, "reason": "fixture only; no image, voice or user approval"}


def inputs():
    _, _, packet, legal, _ = bundle()
    return {"packet": packet, "legal_context": legal,
        "reference_fulltext": packet["inputs"]["reference_fulltext"],
        "expression_standards": packet["inputs"]["expression_standards"],
        "production_preferences": {"max_characters": 2, "max_duration_seconds": 180},
        "provider_evidence": PROVIDER, "source_binding_sha256": BINDING, "now": NOW}


def theme_for(packet):
    profile = {"gender_presentation": "女性", "age_presentation": "三十岁", "appearance": "黑色短发", "wardrobe": "灰色衬衫"}
    return {"schema": fresh.VERSION + "/theme", "candidate_id": packet["candidate"]["candidate_id"],
        "title": "一张工资明细", "theme": "解释扣款", "relationships": "员工与人事当面交涉", "audience_feeling": "疑惑后坚持保留明细", "style": "写实", "turn": "对方尚不能解释", "ending": "员工留下自己的明细",
        "tag_choices": [{"tag_id": packet["tag_catalog"][0]["tag_id"], "story_relevance": "测试用议题引用，不是语义金标"}],
        "characters": [{"id": "worker", "name": "阿宁", "role": "员工", "profile": profile},
            {"id": "hr", "name": "陈姐", "role": "人事", "profile": deepcopy(profile)}],
        "actors": [{"id": "company", "name": "公司"}],
        "scenes": [{"id": "room", "description": "办公室", "appearance": "一张桌子、两把椅子"}],
        "facts": [{"id": "salary", "text": "阿宁拿到明细，提出询问。", "kind": "fictional_event"},
            {"id": "retain", "text": "阿宁保留明细，没有当场确认扣款。", "kind": "fictional_event"}],
        "initial_state": {"scene_id": "room", "character_states": [
            {"id": aid, "expected_state": "坐在桌边", "pose": "坐在桌边", "posture": "坐着", "location": "桌边", "gaze": None, "emotion": None, "knowledge": None}
            for aid in ("worker", "hr")], "prop_states": [
            {"id": "table", "expected_state": "桌子在房间地面", "holder_character_id": None, "anchor": "地面", "facing": None,
                "orientation": None, "support": {"entity_type": "scene", "entity_id": "room"}, "appearance": "灰色桌子", "owner_character_id": None},
            {"id": "slip", "expected_state": "面朝上放在桌子靠阿宁的一边，没人持有", "holder_character_id": None, "anchor": "桌边", "facing": "面朝上",
                "orientation": "面朝上", "support": {"entity_type": "prop", "entity_id": "table"}, "appearance": "白色A4明细", "owner_character_id": None}]}}


def raw_script():
    return {"title": "一张工资明细", "premise": "员工询问工资明细中的扣款，留下自己的明细等待答复。", "beats": [
        {"id": "B1", "trigger": "看到明细", "event": "阿宁询问扣款", "steps": [
            {"kind": "dialogue", "speaker": "worker", "text": "这里少了一千块，能解释一下吗？"}]},
        {"id": "B2", "trigger": "阿宁询问", "event": "人事说尚不知道", "steps": [
            {"kind": "dialogue", "speaker": "hr", "text": "这笔扣款我得去问，先把单子给我。"}]},
        {"id": "B3", "trigger": "对方要取回明细", "event": "阿宁保留明细", "steps": [
            {"kind": "dialogue", "speaker": "worker", "text": "单子我留着，给你拍一张。"},
            {"kind": "action", "speaker": "", "text": "阿宁把明细留在面前，没有递过去；陈姐停下伸出的手。"}]}]}


def plan_for_fresh(brief):
    script = contract.compile_script(raw_script(), brief)
    value = plan_for(script, brief)
    value["source_obligations"] = [{"id": "SO" + str(i + 1), "fact_id": row["id"], "mode": "state",
        "description": row["text"], "actor_id": "", "required_kind": "either", "allowed_speech_functions": contract.FUNCTIONS}
        for i, row in enumerate(brief["facts"])]
    value["source_order"] = []
    value["initial_conditions"] = [{"entity_type": kind, "entity_id": row["id"], "relation": "unspecified",
        "anchor_type": "unspecified", "anchor_id": "", "orientation": "unspecified"}
        for kind, key in (("character", "character_states"), ("prop", "prop_states")) for row in brief["initial_state"][key]]
    contract.validate_plan(value, brief)
    return value


def review_for(script, brief, plan, legal):
    entries = contract.evidence_catalog(script)
    common = {"status": "pass", "source_refs": [next(iter(entries))], "reason": "明确模拟语义输入，只验证路由，非质量金标。", "required_revision": ""}
    def rows(key, ids): return [{key: item, **deepcopy(common)} for item in ids]
    return {"script_sha256": fresh.digest(script), "brief_sha256": fresh.digest(brief), "plan_sha256": fresh.digest(plan), "legal_context_sha256": fresh.digest(legal),
        **({"prior_story_relation": {"prior_scope_sha256": fresh.digest(brief["prior_story_scope"]), "relation": "new_story",
            "reason": "模拟不同核心事件，只测试门禁，不是语义金标。", "current_evidence": [{"source_ref": next(iter(entries)), "quote": entries[next(iter(entries))]["quote"]}]}}
            if brief.get("prior_story_scope") else {}),
        "plan_support": rows("plan_item_id", fresh.plan_review_ids(plan)),
        "fact_checks": rows("fact_id", [row["id"] for row in brief["facts"]]),
        "initial_checks": rows("initial_id", [kind + ":" + row["id"] for kind, key in (("character", "character_states"), ("prop", "prop_states")) for row in brief["initial_state"][key]]),
        "observed_prop_initial": [{"prop_id": row["id"], "holder_character_id": row["holder_character_id"], "support": deepcopy(row["support"]), "orientation": row["orientation"], **deepcopy(common)} for row in brief["initial_state"]["prop_states"]],
        "literal_events": [{"source_ref": ref, "kind": row["kind"], "speaker": row["speaker"], "speech_functions": ["action"] if row["kind"] == "action" else ["question"] if ref == "E0001" else ["request"] if ref == "E0002" else ["refusal"]} for ref, row in entries.items()],
        "obligations": [{"obligation_id": row["id"], "status": "pass", "occurrence_evidence": [], "reason": common["reason"], "required_revision": ""} for row in plan["source_obligations"]],
        "order_checks": [], "dialogue_checks": rows("dialogue_ref", [ref for ref, row in entries.items() if row["kind"] == "dialogue"]),
        "criteria": rows("criterion", list(fresh.CRITERIA)), "ending_checks": rows("field", ["attempt_result", "visible_consequence", "open_problem"]),
        "legal_claims": [], "review_limitations": ["纯离线路由夹具，未判断真实内容"]}


class Service:
    def __init__(self, case, modifications=None):
        self.case = case
        self.modifications = modifications or {}
        self.calls = []
        self.states = []

    def persist(self, state):
        self.states.append(deepcopy(state))

    def invoke(self, label, request, validate):
        assert self.states[-1]["events"][-1]["event"] == "claim"
        assert self.states[-1]["events"][-1]["request_sha256"] == fresh.digest(request)
        self.calls.append(deepcopy(request))
        payload = json.loads(request["messages"][1]["content"])
        phase = request["input_provenance"]["phase"]
        if phase == "theme": output = theme_for(self.case["packet"])
        elif phase == "plan": output = plan_for_fresh(payload["brief"])
        elif phase == "draft": output = raw_script()
        else: output = review_for(payload["full_current_script"], payload["brief"], payload["full_scene_plan"], self.case["legal_context"])
        modifier = self.modifications.get(label)
        if modifier is not None:
            output = modifier(output)
        status, failure = "contract_valid", None
        try:
            validate(output)
        except (ValueError, ValidationError) as exc:
            status = "contract_rejected"
            failure = {"category": "validation", "code": str(exc), "response_received": True}
        result = {"ordinal": 520 + len(self.calls), "label": label, "request": deepcopy(request),
            "request_sha256": fresh.digest(request), "source_binding_sha256": BINDING, "status": status,
            "output": output, "response_metadata": {"http_status_code": 200, "response_body_complete": True,
                "finish_reason": "tool_calls", "total_tokens": 100, "raw_body_sha256": "b" * 64},
            "response_text": json.dumps(output, ensure_ascii=False), "response_payload": {"fixture": True},
            "call_evidence": {"identity_sha256": "c" * 64}}
        if failure: result["failure"] = failure
        receipt_modifier = self.modifications.get("receipt:" + label)
        if receipt_modifier is not None: result = receipt_modifier(result)
        return result


def execute(modifications=None, **options):
    case = inputs()
    service = Service(case, modifications)
    pipeline = fresh.FreshLegalTextPipeline(invoke=service.invoke, persist_state=service.persist, **options)
    result = pipeline.run(**case)
    return result, service


def test_fresh_complete_flow_minimum_four_calls_and_current_source_package():
    result, service = execute()
    assert result["status"] == "text_ready_for_director"
    assert len(service.calls) == 4
    assert [q["role"] for q in service.calls] == ["writer", "writer", "writer", "director"]
    assert result["versions"] == {"theme": 1, "plan": 1, "draft": 1}
    assert result["source_review_binding"]["writer_ordinal"] == 523
    assert result["source_review_binding"]["review_ordinal"] == 524
    assert result["source_review_binding"]["script_sha256"] == fresh.digest(result["script"])
    assert result["script"]["selected_candidate_id"].startswith("fresh:")
    assert not result["creative_quality_passed"] and not result["human_quality_approved"] and not result["old_budget_reset"]
    assert result["manifest"]["actors"][0]["asset_binding"]["status"] == "unknown"
    assert all(row["voice"]["status"] == "unbound" for row in result["manifest"]["actors"])
    assert all(json.loads(request["messages"][1]["content"])["reference_fulltext"] == inputs()["reference_fulltext"] for request in service.calls)
    props = {row["id"]: row for row in result["shared_dynamic_initial"]["props"]}
    assert props["slip"]["support"]["value"] == {"entity_type": "prop", "entity_id": "table"}
    assert result["manifest"]["props"][0]["owner"]["status"] == "unknown"
    assert fresh.render_script(result["script"], result["brief"]).startswith("# 一张工资明细")


@pytest.mark.parametrize("relation,expected", [("same_story", "halt_same_story_prior_allowance_exhausted"),
    ("unknown", "halt_prior_story_relation_unknown"), ("new_story", "text_ready_for_director")])
def test_prior_story_scope_cannot_reset_exhausted_allowance(relation, expected):
    case = inputs()
    case["production_preferences"]["prior_story_scope"] = {"prior_script_sha256": "f" * 64,
        "full_prior_script": {"title": "旧稿", "premise": "旧故事"}, "director_used": 7, "director_limit": 7, "director_remaining": 0}
    def change(value):
        value["prior_story_relation"]["relation"] = relation
        return value
    service = Service(case, {"fresh_full_review_01": change})
    result = fresh.FreshLegalTextPipeline(invoke=service.invoke, persist_state=service.persist).run(**case)
    assert result["status"] == expected and len(service.calls) == 4
    assert result["brief"]["prior_story_scope"] == case["production_preferences"]["prior_story_scope"]
    assert result["old_budget_reset"] is False
    if relation != "new_story":
        assert "production_package" not in result and "source_review_binding" not in result


@pytest.mark.parametrize("fault", ["missing", "scope_sha", "quote", "blank_reason", "blank_quote"])
def test_prior_story_relation_needs_same_scope_and_real_body_evidence(fault):
    case = inputs()
    case["production_preferences"]["prior_story_scope"] = {"full_prior_script": {"title": "旧稿"}, "director_remaining": 0}
    brief = fresh.compile_brief(theme_for(case["packet"]), case["packet"], case["legal_context"], case["production_preferences"], BINDING)
    plan = contract.compile_plan(plan_for_fresh(brief), brief)
    script = contract.compile_script(raw_script(), brief)
    value = review_for(script, brief, plan, case["legal_context"])
    if fault == "missing": value.pop("prior_story_relation")
    elif fault == "scope_sha": value["prior_story_relation"]["prior_scope_sha256"] = "a" * 64
    elif fault == "blank_reason": value["prior_story_relation"]["reason"] = " "
    elif fault == "blank_quote": value["prior_story_relation"]["current_evidence"][0]["quote"] = " "
    else: value["prior_story_relation"]["current_evidence"][0]["quote"] = "正文没有这句话"
    with pytest.raises((ValueError, ValidationError)):
        fresh.validate_review(value, script, brief, plan, case["legal_context"])


def fail_dialogue(review):
    review["dialogue_checks"][0].update(status="fail", required_revision="完整新稿修复首句语病。")
    return review


def test_known_complete_full_review_failure_generates_complete_new_script_and_new_review():
    result, service = execute({"fresh_full_review_01": fail_dialogue})
    assert result["status"] == "text_ready_for_director" and len(service.calls) == 6
    assert result["versions"]["draft"] == 2
    revised = json.loads(service.calls[4]["messages"][1]["content"])
    assert revised["previous_complete_document"] == contract.compile_script(raw_script(), result["brief"])
    assert revised["revision_requirements"][0]["finding"]["dialogue_ref"] == "E0001"
    assert result["source_review_binding"]["review_ordinal"] == 526


def test_plan_semantic_fail_rebuilds_complete_plan_and_body_without_reset_counts():
    def reject(review):
        review["plan_support"][0].update(status="fail", required_revision="完整计划纠正义务。")
        return review
    result, service = execute({"fresh_full_review_01": reject})
    assert result["status"] == "text_ready_for_director"
    assert result["versions"] == {"theme": 1, "plan": 2, "draft": 2}
    assert len(service.calls) == 7
    assert "previous_complete_document" in json.loads(service.calls[4]["messages"][1]["content"])


def test_three_complete_drafts_exhaust_without_extra_review_or_count_reset():
    result, service = execute({"fresh_full_review_0" + str(i): fail_dialogue for i in range(1, 4)})
    assert result["status"] == "creative_stalled"
    assert result["versions"]["draft"] == 3 and len(service.calls) == 8


@pytest.mark.parametrize("field,value", [("total_tokens", None), ("total_tokens", -1), ("response_body_complete", False),
    ("finish_reason", "length"), ("http_status_code", 500)])
def test_unknown_usage_or_incomplete_result_never_redispatches(field, value):
    def change(receipt):
        receipt["response_metadata"][field] = value
        return receipt
    result, service = execute({"receipt:fresh_theme_01": change})
    assert result["status"] == "halt_result_or_usage_unknown" and len(service.calls) == 1


@pytest.mark.parametrize("field", ["request_sha256", "source_binding_sha256"])
def test_wrong_actual_receipt_identity_stops_before_next_model(field):
    def change(receipt):
        receipt[field] = "f" * 64
        return receipt
    result, service = execute({"receipt:fresh_theme_01": change})
    assert result["status"] == "halt_result_or_usage_unknown" and len(service.calls) == 1


def test_complete_schema_error_can_revise_theme_with_full_native_old_document():
    def bad(value):
        value["characters"][0]["profile"].pop("wardrobe")
        return value
    result, service = execute({"fresh_theme_01": bad})
    assert result["status"] == "text_ready_for_director" and result["versions"]["theme"] == 2
    assert json.loads(service.calls[1]["messages"][1]["content"])["previous_complete_document"]["characters"][0]["profile"].get("wardrobe") is None


def missing_tool(receipt):
    receipt["status"] = "response_rejected"
    receipt["failure"] = {"code": "REQUIRED_TOOL_MISSING", "category": "interface", "response_received": True}
    receipt["response_metadata"]["finish_reason"] = "stop"
    return receipt


def format_auth():
    return {"authorized": True, "source_binding_sha256": BINDING, "evidence_ref": "fixture-explicit-user-scope", "evidence_sha256": "d" * 64}


def test_missing_tool_has_no_recovery_without_current_source_authorization():
    result, service = execute({"receipt:fresh_theme_01": missing_tool})
    assert result["status"] == "halt_required_tool_missing" and len(service.calls) == 1


def test_single_format_recovery_is_claimed_before_invoke_and_not_old_body_conversion():
    result, service = execute({"receipt:fresh_theme_01": missing_tool}, format_recovery_authorization=format_auth())
    assert result["status"] == "text_ready_for_director" and len(service.calls) == 5
    claim = result["format_recovery_claims"]["theme"]
    assert claim["original_ordinal"] == 521
    assert result["source_review_binding"]["writer_ordinal"] == 524
    assert service.calls[1]["input_provenance"]["single_format_recovery_of"] == 521


def test_format_recovery_again_missing_stops_and_does_not_recover_twice():
    mods = {"receipt:fresh_theme_01": missing_tool, "receipt:fresh_theme_01_format_recovery": missing_tool}
    result, service = execute(mods, format_recovery_authorization=format_auth())
    assert result["status"] == "halt_format_recovery_failed" and len(service.calls) == 2


def test_review_unknown_wins_over_explicit_fail_and_does_not_generate_revision():
    def uncertain(review):
        fail_dialogue(review)
        review["ending_checks"][-1].update(status="unknown", reason="无法判断来源开放问题。")
        return review
    result, service = execute({"fresh_full_review_01": uncertain})
    assert result["status"] == "halt_review_uncertain" and len(service.calls) == 4


@pytest.mark.parametrize("fault", ["speaker", "kind", "missing_dialogue", "duplicate_fact", "bad_legal_quote", "fake_legal_support", "event_only_support"])
def test_complete_review_protocol_does_not_accept_forged_or_incomplete_evidence(fault):
    case = inputs()
    theme = theme_for(case["packet"])
    brief = fresh.compile_brief(theme, case["packet"], case["legal_context"], case["production_preferences"], BINDING)
    plan = contract.compile_plan(plan_for_fresh(brief), brief)
    script = contract.compile_script(raw_script(), brief)
    if fault == "event_only_support":
        plan["source_obligations"][0].update(mode="event", required_kind="dialogue", actor_id="worker", allowed_speech_functions=["question"])
    review = review_for(script, brief, plan, case["legal_context"])
    if fault == "speaker": review["literal_events"][0]["speaker"] = "hr"
    elif fault == "kind": review["literal_events"][0]["kind"] = "action"
    elif fault == "missing_dialogue": review["dialogue_checks"].pop()
    elif fault == "duplicate_fact": review["fact_checks"][1] = deepcopy(review["fact_checks"][0])
    elif fault in ("bad_legal_quote", "fake_legal_support"):
        review["legal_claims"] = [{"source_ref": "E0001", "quote": "不存在的结论" if fault == "bad_legal_quote" else script["beats"][0]["steps"][0]["text"], "legal_fact_refs": [], "status": "pass", "reason": "模拟伪依据", "required_revision": ""}]
    with pytest.raises((ValueError, ValidationError)):
        fresh.validate_review(review, script, brief, plan, case["legal_context"])


def test_current_prop_support_unknown_is_preserved_and_not_inferred_from_scene():
    case = inputs(); theme = theme_for(case["packet"])
    theme["initial_state"]["prop_states"][1].update(support=None, orientation=None)
    brief = fresh.compile_brief(theme, case["packet"], case["legal_context"], case["production_preferences"], BINDING)
    script = contract.compile_script(raw_script(), brief)
    package = fresh.build_production_package(theme, brief, script, PROVIDER)
    prop = package["shared_dynamic_initial"]["props"][1]
    assert prop["support"]["status"] == "unknown" and prop["support"]["value"] is None
    assert prop["orientation"]["status"] == "unknown"  # expected prose says face-up, still not guessed


def test_prop_support_cycle_and_foreign_actor_are_refused():
    case = inputs(); theme = theme_for(case["packet"])
    theme["initial_state"]["prop_states"][0]["support"] = {"entity_type": "prop", "entity_id": "slip"}
    with pytest.raises(ValueError, match="cycle"):
        fresh.validate_theme(theme, case["packet"], 2)
    theme = theme_for(case["packet"])
    theme["initial_state"]["prop_states"][1]["holder_character_id"] = "third_person"
    with pytest.raises(ValueError, match="undeclared"):
        fresh.validate_theme(theme, case["packet"], 2)


def test_resume_claimed_execution_cannot_restart_model_calls():
    case = inputs(); service = Service(case)
    prior = {"schema": fresh.VERSION + "/state", "source_binding_sha256": BINDING, "events": [{"event": "claim"}], "versions": {"draft": 2}}
    result = fresh.FreshLegalTextPipeline(invoke=service.invoke, persist_state=service.persist).run(**case, resume_state=prior)
    assert result["status"] == "halt_existing_execution_reconcile_original" and not service.calls
    assert result["versions"]["draft"] == 2


def test_changed_reference_or_stale_packet_blocks_before_claim():
    case = inputs(); service = Service(case)
    case["reference_fulltext"] = "changed"
    with pytest.raises(ValueError, match="R01"):
        fresh.FreshLegalTextPipeline(invoke=service.invoke, persist_state=service.persist).run(**case)
    assert not service.calls and not service.states
    case = inputs(); case["now"] = "2026-10-12T23:00:00Z"
    with pytest.raises(ValueError):
        fresh.FreshLegalTextPipeline(invoke=service.invoke, persist_state=service.persist).run(**case)


def test_unknown_model_or_unbounded_versions_are_refused():
    for options in ({"models": {"writer": "other", "director": "deepseek-flash"}}, {"max_full_drafts": 4}, {"max_full_plans": 0}):
        with pytest.raises(ValueError):
            fresh.FreshLegalTextPipeline(invoke=lambda *_: None, persist_state=lambda *_: None, **options)
