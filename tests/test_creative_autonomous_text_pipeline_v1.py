"""Autonomous text routing tests; fixtures are contract cases, not quality golds.

No service, legal recommendation, product-performance claim, or media inspection.
"""
from copy import deepcopy

import pytest

from src.content_factory import creative_autonomous_text_contract_v1 as contract


def case(topic="legal"):
    if topic == "legal":
        people = [{"id": "worker", "name": "小林"}, {"id": "hr", "name": "周姐"}]
        raw = {"title": "一张未签的表", "premise": "公司要求员工离开，员工不愿签个人原因申请，人事收回材料。", "beats": [
            {"id": "notice", "event": "人事说明公司的决定", "trigger": "两人在会议室坐下", "steps": [
                {"kind": "dialogue", "speaker": "hr", "text": "公司让我通知你，这次要你离开。"},
                {"kind": "action", "speaker": "", "text": "周姐把已经填写个人原因的申请和笔送到小林面前。"}]},
            {"id": "question", "event": "小林质问材料上的原因", "trigger": "小林看清原因栏", "steps": [
                {"kind": "dialogue", "speaker": "worker", "text": "明明是公司要我走，为什么写我自己辞职？"},
                {"kind": "dialogue", "speaker": "hr", "text": "公司想按这张表办，麻烦你签一下。"}]},
            {"id": "refusal", "event": "小林拒签", "trigger": "周姐再次提出签名", "steps": [
                {"kind": "dialogue", "speaker": "worker", "text": "这不是我的意思，我不签。"}]},
            {"id": "withdrawal", "event": "周姐撤回未签材料", "trigger": "小林拒绝签字", "steps": [
                {"kind": "action", "speaker": "", "text": "周姐没有再递笔，取回未签的表和笔，放进文件夹，独自出门。小林仍坐在原位。"}]}]}
        facts = [{"id": "company_decision", "text": "公司要求小林离开，小林没有提出辞职。"}, {"id": "unsigned", "text": "原因栏已填个人原因，签名仍空白。"}]
        actors = [{"id": "company", "name": "公司", "on_screen": False}]
    elif topic == "family":
        people = [{"id": "child", "name": "女儿"}, {"id": "parent", "name": "母亲"}]
        raw = {"title": "门口的伞", "premise": "女儿不想被送，母亲换成把伞交给她，女儿接下后独自出门。", "beats": [
            {"id": "offer", "event": "母亲提出陪女儿出门", "trigger": "女儿准备出门", "steps": [{"kind": "dialogue", "speaker": "parent", "text": "外面下雨，我送你到车站吧。"}]},
            {"id": "boundary", "event": "女儿拒绝陪送", "trigger": "母亲拿起外套", "steps": [{"kind": "dialogue", "speaker": "child", "text": "我想自己走，伞借我就行。"}]},
            {"id": "umbrella", "event": "母亲改为交伞", "trigger": "女儿说明需要", "steps": [{"kind": "action", "speaker": "", "text": "母亲放下外套，把伞递给女儿。女儿接住伞，独自出门；母亲留在门内。"}]}]}
        facts = [{"id": "rain", "text": "门外下雨，家中有一把伞。"}]
        actors = []
    elif topic == "product":
        people = [{"id": "owner", "name": "使用者"}]
        raw = {"title": "桌边的灯", "premise": "使用者整理空出来的书桌，将一盏灯放在书旁，打开后坐下。", "beats": [
            {"id": "space", "event": "使用者给书和灯留出桌面", "trigger": "书桌摆满杂物", "steps": [{"kind": "action", "speaker": "", "text": "使用者把散放的纸收进抽屉，在空出的桌面放好书和台灯。"}]},
            {"id": "reading", "event": "使用者打开灯开始阅读", "trigger": "书和灯放好", "steps": [{"kind": "action", "speaker": "", "text": "使用者按下台灯开关，坐下翻开书。光落在书页上。"}]}]}
        facts = [{"id": "lamp", "text": "书桌上有一本书和一盏可开关的台灯；不约定任何性能。"}]
        actors = []
    else:
        raise AssertionError(topic)
    brief = {"selected_candidate_id": "fixture_" + topic, "characters": people, "actors": actors, "facts": facts}
    return brief, raw, contract.compile_script(raw, brief)


def review_for(script, brief):
    catalog = contract.evidence_catalog(script)
    refs = list(catalog)
    rows = []
    for ref, item in catalog.items():
        if item["kind"] != "dialogue":
            continue
        rows.append({"source_ref": ref, "interpreted_actor": item["speaker"], "interpreted_action": "提出当前要求或回应", "interpreted_object": "对方与当前事项", "clarity": "clear", "register": "conversational", "function": "responsive"})
    return {"script_sha256": contract._digest(script), "criteria": [
        {"criterion": name, "status": "pass", "explanation": "当前实际步骤已兑现该项；本夹具只测路由，不代表审美金标。", "evidence_refs": [refs[-1]], "required_revision": ""}
        for name in contract.CRITERIA], "dialogue_readings": rows, "issues": [], "suggestions": []}


def plan_for(script, brief):
    people = [p["id"] for p in brief["characters"]]
    return {"title": script["title"], "dramatic_question": "人物当前尝试能否得到回应", "audience_arc": "从提出需要到看到当前选择的结果", "character_goals": [
        {"character_id": person, "objective": "处理当前事项", "obstacle": "对方需要或空间限制"} for person in people], "beats": [
        {"id": beat["id"], "trigger": beat["trigger"], "attempt": beat["event"], "acting_character_id": people[0], "target_character_id": people[-1] if len(people) > 1 else "", "state_change": "当前尝试产生下一步", "fact_refs": [f["id"] for f in brief["facts"]]}
        for beat in script["beats"]], "ending": {"attempt_result": "当前事项得到明确选择", "visible_consequence": script["beats"][-1]["steps"][-1]["text"], "open_problem": "未声称关系或争议永久解决"}}


@pytest.mark.parametrize("topic,count", [("legal", 4), ("family", 3), ("product", 2)])
def test_variable_topics_and_beats_have_one_contract_without_dialogue_counts(topic, count):
    brief, raw, script = case(topic)
    before = deepcopy(raw)
    assert contract.validate_plan(plan_for(script, brief), brief)["beat_count"] == count
    assert contract.compile_script(raw, brief) == script
    assert raw == before
    assert {k: v for k, v in script.items() if k != "selected_candidate_id"} == raw
    decision = contract.decide_review(review_for(script, brief), script, brief)
    assert decision["status"] == "text_ready_for_director"
    assert decision["human_approved"] is False
    assert decision["creative_quality_passed"] is False
    assert decision["automatic_media_submit"] is False


def test_ambiguous_subject_triggers_whole_revision_even_with_empty_issues_and_pass_rows():
    brief, _, script = case()
    review = review_for(script, brief)
    review["dialogue_readings"][-1]["clarity"] = "ambiguous"
    assert review["issues"] == [] and all(r["status"] == "pass" for r in review["criteria"])
    decision = contract.decide_review(review, script, brief)
    assert decision["status"] == "needs_whole_revision"
    finding = next(r for r in decision["revision_requirements"] if r["code"] == "DIALOGUE_AMBIGUOUS")
    assert finding["evidence_refs"][0]["quote"] == script["beats"][2]["steps"][0]["text"]
    assert "完整新稿" in finding["required_revision"]


@pytest.mark.parametrize("field,value,code", [("register", "stilted", "DIALOGUE_STILTED"), ("function", "redundant", "DIALOGUE_REDUNDANT")])
def test_stilted_or_redundant_feedback_is_not_hidden_in_suggestions(field, value, code):
    brief, _, script = case()
    review = review_for(script, brief)
    review["dialogue_readings"][0][field] = value
    decision = contract.decide_review(review, script, brief)
    assert decision["status"] == "needs_whole_revision"
    assert code in [r["code"] for r in decision["revision_requirements"]]


def test_missing_criterion_cannot_pass():
    brief, _, script = case()
    review = review_for(script, brief)
    review["criteria"].pop()
    with pytest.raises(ValueError):
        contract.decide_review(review, script, brief)


def test_duplicate_criterion_cannot_replace_a_missing_one():
    brief, _, script = case()
    review = review_for(script, brief)
    review["criteria"][-1]["criterion"] = review["criteria"][0]["criterion"]
    with pytest.raises(ValueError, match="exactly once"):
        contract.decide_review(review, script, brief)


@pytest.mark.parametrize("criterion", list(contract.CRITERIA))
def test_each_unknown_criterion_halts_instead_of_passing_or_dispatching_repair(criterion):
    brief, _, script = case()
    review = review_for(script, brief)
    next(r for r in review["criteria"] if r["criterion"] == criterion)["status"] = "unknown"
    decision = contract.decide_review(review, script, brief)
    assert decision["status"] == "halt_review_uncertain"
    assert decision["uncertainties"]


@pytest.mark.parametrize("field", ["clarity", "register", "function"])
def test_unknown_dialogue_reading_halts(field):
    brief, _, script = case()
    review = review_for(script, brief)
    review["dialogue_readings"][0][field] = "unknown"
    assert contract.decide_review(review, script, brief)["status"] == "halt_review_uncertain"


def test_every_dialogue_needs_its_own_reading():
    brief, _, script = case()
    review = review_for(script, brief)
    review["dialogue_readings"].pop()
    with pytest.raises(ValueError):
        contract.decide_review(review, script, brief)


def test_fabricated_reference_is_blocked():
    brief, _, script = case()
    review = review_for(script, brief)
    review["criteria"][0]["evidence_refs"] = ["E9999"]
    with pytest.raises(ValueError):
        contract.decide_review(review, script, brief)


def test_review_of_another_whole_script_is_blocked():
    brief, _, script = case()
    review = review_for(script, brief)
    other = deepcopy(script)
    other["beats"][0]["steps"][0]["text"] = "另一个完整稿的发言。"
    with pytest.raises(ValueError):
        contract.decide_review(review, other, brief)


def test_evidence_catalog_cannot_use_premise_or_event_as_performed_result():
    brief, _, script = case()
    entries = contract.evidence_catalog(script)
    assert entries and all(".steps." in row["path"] for row in entries.values())
    assert script["premise"] not in [r["quote"] for r in entries.values()]
    review = review_for(script, brief)
    review["criteria"][0]["evidence_refs"] = ["script.premise"]
    with pytest.raises(ValueError):
        contract.decide_review(review, script, brief)


def test_leaving_without_interaction_result_enters_whole_revision():
    brief, raw, _ = case()
    raw["beats"][-1]["steps"][-1]["text"] = "周姐说了一声先走了，然后独自出门，小林仍坐在原位。"
    script = contract.compile_script(raw, brief)
    review = review_for(script, brief)
    ending = next(r for r in review["criteria"] if r["criterion"] == "ending_payoff")
    ending.update(status="fail", explanation="离场没有体现未取得签名后如何处理眼前材料。", required_revision="整稿明确这次索签受阻造成的当前行动结果，允许动作兑现。")
    decision = contract.decide_review(review, script, brief)
    assert decision["status"] == "needs_whole_revision"
    assert "CRITERION_ENDING_PAYOFF" in [r["code"] for r in decision["revision_requirements"]]


def test_action_can_deliver_ending_without_any_ending_dialogue():
    brief, _, script = case()
    assert all(s["kind"] == "action" for s in script["beats"][-1]["steps"])
    assert contract.decide_review(review_for(script, brief), script, brief)["status"] == "text_ready_for_director"


def test_declared_offscreen_subject_is_allowed_but_not_as_dialogue_speaker():
    brief, raw, script = case()
    review = review_for(script, brief)
    review["dialogue_readings"][0]["interpreted_actor"] = "company"
    assert contract.decide_review(review, script, brief)["status"] == "text_ready_for_director"
    raw["beats"][0]["steps"][0]["speaker"] = "company"
    with pytest.raises(ValueError):
        contract.compile_script(raw, brief)


def test_unknown_has_priority_over_known_content_failure():
    brief, _, script = case()
    review = review_for(script, brief)
    review["criteria"][0]["status"] = "unknown"
    review["dialogue_readings"][0]["clarity"] = "ambiguous"
    decision = contract.decide_review(review, script, brief)
    assert decision["status"] == "halt_review_uncertain"
    assert decision["revision_requirements"] and decision["uncertainties"]


@pytest.fixture
def pipeline_workspace(monkeypatch):
    """Isolated real-runtime receipts under the workspace, never old records."""
    import json
    import tempfile
    from pathlib import Path
    from scripts import run_autonomous_text_pipeline_v1 as runner
    qa = runner.PROJECT / "data" / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autonomous_text_mock_", dir=qa) as name:
        workspace = Path(name).resolve()
        assert workspace.is_relative_to(qa.resolve())
        parent, root = workspace / "parent", workspace / "run"
        parent.mkdir(); root.mkdir()
        base = {"calls_started": 433, "reported_tokens": 6803210, "calls_with_known_usage": 431,
                "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]}
        models = {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-v4-flash"}}
        ledger = {"source_manifest": {}, "calls": [], "starting_spend": base, "model_configs": models}
        (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
        setup = {"parent_text_directory": parent.relative_to(runner.PROJECT).as_posix(), "max_full_drafts": 3}
        (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
        brief, raw, script = case()
        input_value = {"brief": brief, "reference_fulltext": {"R01": "参考表达机制：请求受阻后改变行动，而不是重复主题。"},
                       "user_goal": "完整文本主链自行审查和整稿修订，无人工决策文件"}
        (root / "INPUT.json").write_text(json.dumps(input_value, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(runner.identity, "SHARED_LOCK", workspace / "shared.lock")
        yield runner, root, parent, brief, raw, script


class MockTextService:
    def __init__(self, brief, raw, *, failure=None, unknown_at=None, usage_unknown_at=None, repeated_failure=False):
        self.brief, self.raw = deepcopy(brief), deepcopy(raw)
        self.failure, self.unknown_at, self.usage_unknown_at = failure, unknown_at, usage_unknown_at
        self.repeated_failure = repeated_failure
        self.requests = []
        self.drafts = 0
        self.reviews = 0

    def call(self, role, messages, **kwargs):
        import json
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        self.requests.append({"role": role, "messages": deepcopy(messages), "payload": payload, "schema": deepcopy(kwargs["structured_schema"])})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_TIMEOUT_AFTER_SEND", started=True, received=False, outcome_known=False)
        if "full_current_script" in payload:
            self.reviews += 1
            script = payload["full_current_script"]
            output = review_for(script, self.brief)
            if self.failure and (self.reviews == 1 or self.repeated_failure):
                if self.failure == "unknown":
                    output["criteria"][0]["status"] = "unknown"
                elif self.failure == "missing_criterion":
                    output["criteria"].pop()
                elif self.failure == "fake_reference":
                    output["criteria"][0]["evidence_refs"] = ["E9999"]
                else:
                    output["dialogue_readings"][0]["clarity"] = "ambiguous"
        elif "scene_plan" in payload:
            self.drafts += 1
            output = deepcopy(self.raw)
            if self.drafts > 1:
                # A new complete model response can reorganize the whole script.
                output["title"] = "完整第二稿"
                output["beats"][0]["steps"][0]["text"] = "公司决定让你离开，今天想请你在这张申请上签字。"
                output["beats"][0]["steps"] += output["beats"][1]["steps"]
                del output["beats"][1]
                for i, beat in enumerate(output["beats"], 1):
                    beat["id"] = "NEW" + str(i)
        else:
            output = plan_for(contract.compile_script(self.raw, self.brief), self.brief)
        metadata = {"finish_reason": "tool_calls", "output_mode": "tool_call", "total_tokens": 100,
                    "response_id": "isolated_mock_" + str(ordinal), "response_body_complete": True}
        if ordinal == self.usage_unknown_at:
            metadata.pop("total_tokens")
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=metadata, response_payload={"mock": True})


def test_runner_automatically_runs_two_whole_drafts_and_two_reviews_without_manual_decision(pipeline_workspace):
    import json
    runner, root, parent, brief, raw, script = pipeline_workspace
    parent_before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockTextService(brief, raw, failure="ambiguous")
    op = runner.Pipeline(root, client_factory=lambda: service)
    result = op.run()
    assert result["status"] == "text_ready_for_director"
    assert result["full_draft_versions"] == 2
    assert len(service.requests) == 5
    assert [r["role"] for r in service.requests] == ["writer", "writer", "director", "writer", "director"]
    revision_request = service.requests[3]["payload"]
    assert revision_request["previous_complete_script"] == script
    assert any(r["code"] == "DIALOGUE_AMBIGUOUS" for r in revision_request["revision_requirements"])
    final_script = json.loads((root / "DELIVERABLE" / "FULL_SCRIPT.json").read_text(encoding="utf-8"))
    final_raw = json.loads((root / "DELIVERABLE" / "RAW_MODEL_SCRIPT.json").read_text(encoding="utf-8"))
    assert final_script == contract.compile_script(final_raw, brief)
    assert len(final_script["beats"]) == 3
    assert [b["id"] for b in final_script["beats"]] == ["NEW1", "NEW2", "NEW3"]
    assert service.requests[4]["payload"]["full_current_script"] == final_script
    assert all(r["payload"]["reference_fulltext"] for r in service.requests)
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert result["spend"]["effective_calls_started"] == 438
    assert result["spend"]["effective_reported_tokens"] == 6803710
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert (parent / "CALL_LEDGER.json").read_bytes() == parent_before
    assert result["human_quality_approved"] is False and result["video_calls"] == 0
    assert all(r["payload"]["quality_criteria"] == contract.CRITERIA for r in service.requests)


def test_completed_runner_restart_replays_receipts_without_redispatch(pipeline_workspace):
    runner, root, _, brief, raw, _ = pipeline_workspace
    service = MockTextService(brief, raw, failure="ambiguous")
    first = runner.Pipeline(root, client_factory=lambda: service).run()
    calls = len(service.requests)
    second = runner.Pipeline(root, client_factory=lambda: service).run()
    assert first["status"] == second["status"] == "text_ready_for_director"
    assert len(service.requests) == calls == 5
    assert first["spend"] == second["spend"]


@pytest.mark.parametrize("unknown_at", [1, 2, 3])
def test_unknown_service_outcome_stops_and_restart_does_not_dispatch(unknown_at, pipeline_workspace):
    runner, root, _, brief, raw, _ = pipeline_workspace
    service = MockTextService(brief, raw, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown"
    assert len(service.requests) == unknown_at
    second = runner.Pipeline(root, client_factory=lambda: service).run()
    assert second["status"] == result["status"] and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 433 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 6803210 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117
    assert result["spend"]["old_budget_reset"] is False
    assert not (root / "DELIVERABLE").exists()


def test_unknown_usage_stops_before_next_dispatch_and_preserves_inherited_spend(pipeline_workspace):
    runner, root, _, brief, raw, _ = pipeline_workspace
    service = MockTextService(brief, raw, usage_unknown_at=2)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_usage_unknown"
    assert len(service.requests) == 2
    assert result["spend"]["effective_calls_started"] == 435
    assert result["spend"]["effective_reported_tokens"] == 6803310
    assert result["spend"]["unknown_token_reservations"] > 93117
    second = runner.Pipeline(root, client_factory=lambda: service).run()
    assert second["status"] == "halt_usage_unknown" and len(service.requests) == 2


def test_unknown_quality_halts_without_automatic_revision(pipeline_workspace):
    runner, root, _, brief, raw, _ = pipeline_workspace
    service = MockTextService(brief, raw, failure="unknown")
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_review_uncertain"
    assert len(service.requests) == 3
    assert service.drafts == service.reviews == 1
    assert not (root / "DELIVERABLE").exists()


@pytest.mark.parametrize("failure", ["missing_criterion", "fake_reference"])
def test_invalid_review_blocks_handoff_and_does_not_generate_another_draft(failure, pipeline_workspace):
    runner, root, _, brief, raw, _ = pipeline_workspace
    service = MockTextService(brief, raw, failure=failure)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_contract_rejected"
    assert len(service.requests) == 3
    assert not (root / "DELIVERABLE").exists()


def test_repeated_same_defect_stops_with_complete_receipts_instead_of_looping(pipeline_workspace):
    runner, root, _, brief, raw, _ = pipeline_workspace
    service = MockTextService(brief, raw, failure="ambiguous", repeated_failure=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "creative_stalled"
    assert result["full_draft_versions"] == 2 and len(service.requests) == 5
    assert not (root / "DELIVERABLE").exists()
