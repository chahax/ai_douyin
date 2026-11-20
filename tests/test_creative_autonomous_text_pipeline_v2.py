"""V2 false-positive routing tests; no provider or media calls.

Literal facts and states are semantic model judgments in these fixtures, not
locally inferred quality golds. The tests prove complete coverage and routing.
"""
from copy import deepcopy

import pytest

from src.content_factory import creative_autonomous_text_contract_v2 as contract
from tests.test_creative_autonomous_text_pipeline_v1 import case, review_for, plan_for


def case_v2(topic="legal"):
    brief, raw, _ = case(topic)
    states = {"character_states": [{"id": p["id"], "expected_state": "已在当前场景中，尚未发生本场交锋。"} for p in brief["characters"]], "prop_states": []}
    if topic == "legal":
        states["prop_states"] = [
            {"id": "application", "expected_state": "面朝上放在周姐面前，个人原因已填，签名空白。"},
            {"id": "pen", "expected_state": "在申请旁，无人持笔。"},
            {"id": "folder", "expected_state": "在周姐一侧，用于最后收回材料。"}]
    elif topic == "family":
        states["prop_states"] = [{"id": "umbrella", "expected_state": "伞在母亲手边，女儿尚未取得伞。"}]
    else:
        states["prop_states"] = [{"id": "lamp", "expected_state": "台灯在书桌旁，尚未打开。"}]
    brief["initial_state"] = states
    return brief, raw, contract.compile_script(raw, brief)


def checks_for(script, brief):
    refs = list(contract.evidence_catalog(script))
    facts = [{"fact_id": row["id"], "expected_fact": row["text"], "observed_fact": "当前实际正文中可追溯，夹具仅测状态路由。", "status": "pass", "evidence_refs": [refs[0]], "required_revision": ""} for row in brief["facts"]]
    states = []
    for kind, key in [("character", "character_states"), ("prop", "prop_states")]:
        for row in brief["initial_state"][key]:
            states.append({"entity_type": kind, "entity_id": row["id"], "expected_state": row["expected_state"], "observed_state": "当前正文从所给起态推进；夹具不判断演技。", "status": "pass", "evidence_refs": [refs[0]], "required_revision": ""})
    return {"fact_checks": facts, "initial_state_checks": states}


def review_v2(script, brief):
    value = review_for(script, brief)
    value["criteria"].append({"criterion": "language_integrity", "status": "pass", "explanation": "当前字面完整，未发现错字；仅作路由输入。", "evidence_refs": [next(iter(contract.evidence_catalog(script)))], "required_revision": ""})
    value.update(checks_for(script, brief))
    return value


def audit_v2(script, brief):
    events = []
    for ref, row in contract.evidence_catalog(script).items():
        text = row["quote"]
        function = ("action" if row["kind"] == "action" else "question" if "？" in text else "refusal" if "不签" in text else "request" if "签一下" in text else "statement")
        events.append({"source_ref": ref, "kind": row["kind"], "speaker": row["speaker"], "event_type": "实际动作或言语行动", "actual_action": text, "speech_function": function, "negative_or_refusal": function == "refusal", "props_origin": "" if row["kind"] == "dialogue" else "当前声明位置", "props_destination": "" if row["kind"] == "dialogue" else "当前动作结果位置"})
    return {"script_sha256": contract._digest(script), **checks_for(script, brief), "literal_events": events}


@pytest.mark.parametrize("topic,count", [("legal", 4), ("family", 3), ("product", 2)])
def test_v2_generic_fact_initial_coverage_accepts_variable_topics_and_beats(topic, count):
    brief, raw, script = case_v2(topic)
    assert len(script["beats"]) == count
    assert contract.compile_script(raw, brief) == script
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    assert contract.validate_review(review, script, brief)["fact_count"] == len(brief["facts"])
    assert contract.validate_audit(audit, script, brief)["initial_entity_count"] == sum(len(rows) for rows in brief["initial_state"].values())
    result = contract.combine_decisions(review, audit, script, brief)
    assert result["status"] == "text_ready_for_director"
    assert result["both_same_source_checks_required"] is True
    assert result["human_approved"] is False and result["automatic_media_submit"] is False


def test_primary_review_pass_literal_audit_fail_causes_whole_revision():
    brief, _, script = case_v2()
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    audit["fact_checks"][0].update(status="fail", observed_fact="当前实际只有质问，未演出来源要求的拒绝。", required_revision="生成模型完整新稿补足当面拒绝及后续应答，不补摘要。")
    audit["initial_state_checks"][-3].update(status="fail", observed_state="纸从文件夹取出而不是起态面朝上放在桌上。", required_revision="完整新稿从当前纸的已定位置推进。")
    assert contract.decide_review(review, script, brief)["status"] == "text_ready_for_director"
    result = contract.combine_decisions(review, audit, script, brief)
    assert result["status"] == "needs_whole_revision"
    codes = [r["code"] for r in result["revision_requirements"]]
    assert "FACT_company_decision" in codes
    assert "INITIAL_PROP_application" in codes
    assert result["human_approved"] is False


@pytest.mark.parametrize("checker", ["review", "audit"])
@pytest.mark.parametrize("table", ["fact_checks", "initial_state_checks"])
def test_missing_fact_or_initial_entity_cannot_pass(checker, table):
    brief, _, script = case_v2()
    value = review_v2(script, brief) if checker == "review" else audit_v2(script, brief)
    value[table].pop()
    validate = contract.validate_review if checker == "review" else contract.validate_audit
    with pytest.raises(ValueError):
        validate(value, script, brief)


@pytest.mark.parametrize("checker", ["review", "audit"])
@pytest.mark.parametrize("table,expected_field", [("fact_checks", "expected_fact"), ("initial_state_checks", "expected_state")])
def test_checker_cannot_rewrite_expected_brief_source_to_match_bad_draft(checker, table, expected_field):
    brief, _, script = case_v2()
    value = review_v2(script, brief) if checker == "review" else audit_v2(script, brief)
    value[table][0][expected_field] = "删去原约束后的新要求"
    validate = contract.validate_review if checker == "review" else contract.validate_audit
    with pytest.raises(ValueError, match="changed the brief"):
        validate(value, script, brief)


@pytest.mark.parametrize("table", ["fact_checks", "initial_state_checks"])
def test_unknown_literal_fact_or_initial_state_stops_even_when_review_passes(table):
    brief, _, script = case_v2()
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    audit[table][0]["status"] = "unknown"
    result = contract.combine_decisions(review, audit, script, brief)
    assert result["status"] == "halt_review_uncertain" and result["uncertainties"]


def test_every_action_and_dialogue_needs_literal_reconstruction():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    assert len(audit["literal_events"]) == len(contract.evidence_catalog(script))
    audit["literal_events"].pop()
    with pytest.raises(ValueError):
        contract.validate_audit(audit, script, brief)


def test_duplicate_literal_event_cannot_cover_missing_step():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    audit["literal_events"][-1] = deepcopy(audit["literal_events"][0])
    with pytest.raises(ValueError, match="exactly once"):
        contract.validate_audit(audit, script, brief)


@pytest.mark.parametrize("field,value", [("kind", "action"), ("speaker", "worker")])
def test_literal_reconstruction_cannot_change_original_kind_or_speaker(field, value):
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    audit["literal_events"][0][field] = value
    with pytest.raises(ValueError, match="changed the actual source"):
        contract.validate_audit(audit, script, brief)


def test_literal_action_is_not_a_spoken_refusal():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    action = next(r for r in audit["literal_events"] if r["kind"] == "action")
    action.update(speech_function="refusal", negative_or_refusal=True)
    with pytest.raises(ValueError, match="action cannot"):
        contract.validate_audit(audit, script, brief)


def test_explicit_literal_refusal_requires_negative_flag():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    refusal = next(r for r in audit["literal_events"] if r["speech_function"] == "refusal")
    refusal["negative_or_refusal"] = False
    with pytest.raises(ValueError, match="refusal conflicts"):
        contract.validate_audit(audit, script, brief)


def test_literal_question_stays_question_in_fixture_not_an_invented_second_refusal():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    question = next(r for r in audit["literal_events"] if "？" in r["actual_action"])
    assert question["speech_function"] == "question" and question["negative_or_refusal"] is False
    contract.validate_audit(audit, script, brief)


def test_audit_and_review_must_bind_same_complete_script():
    brief, _, script = case_v2()
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    audit["script_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        contract.combine_decisions(review, audit, script, brief)


def test_false_literal_reference_is_blocked():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    audit["literal_events"][0]["source_ref"] = "E9999"
    with pytest.raises(ValueError):
        contract.validate_audit(audit, script, brief)


def test_identified_typo_in_suggestion_must_trigger_whole_revision():
    brief, _, script = case_v2()
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    review["suggestions"] = [{"code": "typo", "evidence_refs": ["E0001"], "assessment": "已识别的语境错字不能仅作风格建议。", "finding_type": "language_error"}]
    assert review["issues"] == [] and all(r["status"] == "pass" for r in review["criteria"])
    result = contract.combine_decisions(review, audit, script, brief)
    assert result["status"] == "needs_whole_revision"
    assert any(r["code"] == "LANGUAGE_ERROR_typo" for r in result["revision_requirements"])


def test_optional_style_suggestion_still_does_not_force_rewrite():
    brief, _, script = case_v2()
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    review["suggestions"] = [{"code": "tone", "evidence_refs": ["E0001"], "assessment": "可以选择更克制的语气，并非语言错误。", "finding_type": "optional_style"}]
    assert contract.combine_decisions(review, audit, script, brief)["status"] == "text_ready_for_director"


def test_language_integrity_fail_cannot_be_overridden_by_six_other_pass_rows():
    brief, _, script = case_v2()
    review, audit = review_v2(script, brief), audit_v2(script, brief)
    next(r for r in review["criteria"] if r["criterion"] == "language_integrity")["status"] = "fail"
    assert contract.combine_decisions(review, audit, script, brief)["status"] == "needs_whole_revision"


def test_literal_events_cannot_reorder_complete_actual_source():
    brief, _, script = case_v2()
    audit = audit_v2(script, brief)
    audit["literal_events"][0], audit["literal_events"][1] = audit["literal_events"][1], audit["literal_events"][0]
    with pytest.raises(ValueError, match="actual source order"):
        contract.validate_audit(audit, script, brief)


@pytest.fixture
def pipeline_workspace_v2(monkeypatch):
    import json
    import tempfile
    from pathlib import Path
    from scripts import run_autonomous_text_pipeline_v2 as runner
    qa = runner.PROJECT / "data" / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autonomous_text_v2_mock_", dir=qa) as name:
        workspace = Path(name).resolve()
        assert workspace.is_relative_to(qa.resolve())
        parent, root = workspace / "parent", workspace / "run"
        parent.mkdir(); root.mkdir()
        inherited = {"calls_started": 436, "reported_tokens": 6823688, "calls_with_known_usage": 434,
                     "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]}
        models = {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-v4-flash"}}
        import hashlib
        auth = {"schema": "authorized_creative_continuation/v3", "starting_spend": inherited, "max_total_tokens": None, "old_budget_reset": False}
        (parent / "AUTHORIZATION.json").write_text(json.dumps(auth), encoding="utf-8")
        source = workspace / "parent_source.txt"
        source.write_text("mock parent frozen evidence", encoding="utf-8")
        relative = source.relative_to(runner.PROJECT).as_posix()
        snapshot = parent / "source_at_dispatch" / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(source.read_bytes())
        ledger = {"source_manifest": {relative: hashlib.sha256(source.read_bytes()).hexdigest()}, "calls": [], "starting_spend": inherited, "model_configs": models,
                  "authorization_sha256": hashlib.sha256((parent / "AUTHORIZATION.json").read_bytes()).hexdigest()}
        (parent / "CALL_LEDGER.json").write_text(json.dumps(ledger), encoding="utf-8")
        setup = {"parent_text_directory": parent.relative_to(runner.PROJECT).as_posix(), "max_full_drafts": 3}
        (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
        brief, raw, script = case_v2()
        x = {"brief": brief, "reference_fulltext": {"R01": "表达机制参考：刺激改变尝试，后果由实际动作兑现。"}, "user_goal": "事实及初态逐项自动核对，与全文审查联合决策；不依赖人工decision。"}
        (root / "INPUT.json").write_text(json.dumps(x, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(runner.identity, "SHARED_LOCK", workspace / "shared.lock")
        yield runner, root, parent, brief, raw, script


class MockTextServiceV2:
    def __init__(self, brief, raw, *, first_audit_fail=True, unknown_at=None, usage_unknown_at=None, audit_unknown=False, bad_order=False, review_unknown=False):
        self.brief, self.raw = deepcopy(brief), deepcopy(raw)
        self.first_audit_fail, self.unknown_at, self.usage_unknown_at = first_audit_fail, unknown_at, usage_unknown_at
        self.audit_unknown, self.bad_order, self.review_unknown = audit_unknown, bad_order, review_unknown
        self.requests = []
        self.drafts = self.reviews = self.audits = 0

    def call(self, role, messages, **kwargs):
        import json
        from scripts.creative_evidenced_role_clients_v1 import EvidenceCallError
        from src.content_factory.creative_workflow_roles import RoleResult
        payload = json.loads(messages[-1]["content"])
        properties = kwargs["structured_schema"]["properties"]
        self.requests.append({"role": role, "messages": deepcopy(messages), "payload": payload, "schema": deepcopy(kwargs["structured_schema"])})
        ordinal = len(self.requests)
        if ordinal == self.unknown_at:
            raise EvidenceCallError("MOCK_TIMEOUT_AFTER_SEND", started=True, received=False, outcome_known=False)
        if "literal_events" in properties:
            self.audits += 1
            output = audit_v2(payload["full_current_script"], self.brief)
            if self.first_audit_fail and self.audits == 1:
                output["initial_state_checks"][-3].update(status="fail", observed_state="当前动作从文件夹拿出纸，但来源起态是纸已在桌上面朝上。", required_revision="完整新稿依据声明起态，不凭空取纸或翻面。")
            if self.audit_unknown:
                output["fact_checks"][0]["status"] = "unknown"
            if self.bad_order:
                output["literal_events"][0], output["literal_events"][1] = output["literal_events"][1], output["literal_events"][0]
        elif "dialogue_readings" in properties:
            self.reviews += 1
            output = review_v2(payload["full_current_script"], self.brief)
            if self.review_unknown:
                output["criteria"][0]["status"] = "unknown"
        elif "scene_plan" in payload:
            self.drafts += 1
            output = deepcopy(self.raw)
            if self.drafts > 1:
                output["title"] = "完整第二稿"
                output["beats"][0]["steps"][0]["text"] = "公司决定让你离开，今天请你看一下眼前这张申请。"
                output["beats"][0]["steps"] += output["beats"][1]["steps"]
                del output["beats"][1]
                for i, beat in enumerate(output["beats"], 1):
                    beat["id"] = "V2_NEW" + str(i)
        else:
            output = plan_for(contract.compile_script(self.raw, self.brief), self.brief)
        metadata = {"finish_reason": "tool_calls", "output_mode": "tool_call", "total_tokens": 100,
                    "response_id": "isolated_v2_mock_" + str(ordinal), "response_body_complete": True}
        if ordinal == self.usage_unknown_at:
            metadata.pop("total_tokens")
        return RoleResult(text=json.dumps(output, ensure_ascii=False), metadata=metadata, response_payload={"mock": True})


def test_v2_runner_review_pass_audit_fail_automatically_rewrites_and_dual_checks_without_manual_gate(pipeline_workspace_v2):
    import json
    runner, root, parent, brief, raw, script = pipeline_workspace_v2
    parent_before = (parent / "CALL_LEDGER.json").read_bytes()
    service = MockTextServiceV2(brief, raw)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "text_ready_for_director" and result["full_draft_versions"] == 2
    assert len(service.requests) == 7
    assert [r["role"] for r in service.requests] == ["writer", "writer", "director", "director", "writer", "director", "director"]
    first = json.loads((root / "versions" / "01" / "AUTOMATIC_DECISION.json").read_text(encoding="utf-8"))
    assert first["status"] == "needs_whole_revision"
    assert any(r["code"] == "INITIAL_PROP_application" for r in first["revision_requirements"])
    repair = service.requests[4]["payload"]
    assert repair["previous_complete_script"] == script
    assert repair["revision_requirements"] == first["revision_requirements"]
    for index in [3, 6]:
        assert "scene_plan" not in service.requests[index]["payload"]
        assert "full_current_script" in service.requests[index]["payload"]
    final_script = json.loads((root / "DELIVERABLE" / "FULL_SCRIPT.json").read_text(encoding="utf-8"))
    final_raw = json.loads((root / "DELIVERABLE" / "RAW_MODEL_SCRIPT.json").read_text(encoding="utf-8"))
    assert final_script == contract.compile_script(final_raw, brief)
    assert len(final_script["beats"]) == 3
    assert service.requests[5]["payload"]["full_current_script"] == service.requests[6]["payload"]["full_current_script"] == final_script
    assert (root / "DELIVERABLE" / "LITERAL_AUDIT.json").exists()
    assert all(service.requests[i]["payload"]["reference_fulltext"] for i in [0, 1, 2, 4, 5])
    assert all(set(service.requests[i]["payload"]) == {"brief", "full_current_script", "evidence_catalog"} for i in [3, 6])
    assert not list(root.rglob("*assistant_decision*")) and not list(root.rglob("*human_decision*"))
    assert (parent / "CALL_LEDGER.json").read_bytes() == parent_before
    assert result["spend"]["effective_calls_started"] == 443
    assert result["spend"]["effective_reported_tokens"] == 6824388
    assert result["spend"]["unknown_token_reservations"] == 93117
    assert result["human_quality_approved"] is False and result["video_calls"] == 0


def test_v2_completed_restart_reuses_all_seven_receipts(pipeline_workspace_v2):
    runner, root, _, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw)
    first = runner.Pipeline(root, client_factory=lambda: service).run()
    second = runner.Pipeline(root, client_factory=lambda: service).run()
    assert first["status"] == second["status"] == "text_ready_for_director"
    assert len(service.requests) == 7
    assert first["spend"] == second["spend"]


@pytest.mark.parametrize("unknown_at", [1, 2, 3, 4])
def test_v2_unknown_outcome_including_literal_audit_stops_without_redispatch(unknown_at, pipeline_workspace_v2):
    runner, root, _, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw, unknown_at=unknown_at)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_outcome_unknown"
    assert len(service.requests) == unknown_at
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == result["status"] and len(service.requests) == unknown_at
    assert result["spend"]["effective_calls_started"] == 436 + unknown_at
    assert result["spend"]["effective_reported_tokens"] == 6823688 + 100 * (unknown_at - 1)
    assert result["spend"]["unknown_token_reservations"] > 93117
    assert result["spend"]["old_budget_reset"] is False and not (root / "DELIVERABLE").exists()


def test_v2_unknown_audit_usage_stops_before_repair_and_preserves_spend(pipeline_workspace_v2):
    runner, root, _, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw, usage_unknown_at=4)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_usage_unknown" and len(service.requests) == 4
    restart = runner.Pipeline(root, client_factory=lambda: service).run()
    assert restart["status"] == "halt_usage_unknown" and len(service.requests) == 4
    assert result["spend"]["effective_calls_started"] == 440
    assert result["spend"]["effective_reported_tokens"] == 6823988
    assert result["spend"]["unknown_token_reservations"] > 93117


def test_v2_audit_unknown_does_not_get_overridden_by_review_pass(pipeline_workspace_v2):
    runner, root, _, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw, audit_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_review_uncertain" and len(service.requests) == 4
    assert not (root / "DELIVERABLE").exists()


def test_v2_false_literal_order_blocks_handoff_without_local_patch(pipeline_workspace_v2):
    runner, root, _, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw, bad_order=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_contract_rejected" and len(service.requests) == 4
    assert not (root / "DELIVERABLE").exists()


def test_v2_blind_regression_probe_expectations_not_sent_and_failed_detection_stops_before_plan(pipeline_workspace_v2):
    import json
    runner, root, _, brief, raw, script = pipeline_workspace_v2
    setup = json.loads((root / "SETUP.json").read_text(encoding="utf-8"))
    setup["regression_probe_file"] = "KNOWN_FAILURE_PROBE.json"
    (root / "SETUP.json").write_text(json.dumps(setup), encoding="utf-8")
    fixture = {"full_script": script, "expected_fail_codes": ["INITIAL_PROP_application"], "source_identity": {"kind": "known failure routing fixture, not quality gold"}}
    (root / "KNOWN_FAILURE_PROBE.json").write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    service = MockTextServiceV2(brief, raw, first_audit_fail=False)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_gate_regression_failed"
    assert len(service.requests) == 1 and service.drafts == 0
    payload = service.requests[0]["payload"]
    assert "expected_fail_codes" not in payload and "INITIAL_PROP_application" not in json.dumps(payload)
    assert "scene_plan" not in payload and "previous_full_review" not in payload
    assert (root / "REGRESSION_PROBE.json").exists()
    assert not (root / "DELIVERABLE").exists()


@pytest.mark.parametrize("after_prepare", [False, True])
def test_parent_authorization_tamper_blocks_new_calls(after_prepare, pipeline_workspace_v2):
    runner, root, parent, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw)
    op = runner.Pipeline(root, client_factory=lambda: service)
    if after_prepare:
        op.prepare()
    (parent / "AUTHORIZATION.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="authorization changed|source binding changed"):
        op.run()
    assert service.requests == []


@pytest.mark.parametrize("after_prepare", [False, True])
def test_parent_frozen_snapshot_tamper_blocks_new_calls(after_prepare, pipeline_workspace_v2):
    import json
    runner, root, parent, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw)
    op = runner.Pipeline(root, client_factory=lambda: service)
    if after_prepare:
        op.prepare()
    ledger = json.loads((parent / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    source = next(iter(ledger["source_manifest"]))
    (parent / "source_at_dispatch" / source).write_text("tampered snapshot", encoding="utf-8")
    with pytest.raises(RuntimeError, match="source binding changed"):
        op.run()
    assert service.requests == []


@pytest.mark.parametrize("bad_field", ["negative_tokens", "changed_ordinal", "duplicate_receipts", "orphan_receipt"])
def test_parent_receipt_spend_and_identity_cannot_be_bypassed(bad_field, pipeline_workspace_v2):
    import json
    import hashlib
    runner, root, parent, brief, raw, _ = pipeline_workspace_v2
    ledger_path = parent / "CALL_LEDGER.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    receipt = {"status": "contract_valid", "response_metadata": {"total_tokens": -1 if bad_field == "negative_tokens" else 100}}
    name = "call_437_parent_mock.json"
    (parent / name).write_text(json.dumps(receipt), encoding="utf-8")
    row = {"ordinal": 438 if bad_field == "changed_ordinal" else 437, "receipt": name,
           "receipt_sha256": hashlib.sha256((parent / name).read_bytes()).hexdigest()}
    ledger["calls"] = [row]
    if bad_field == "duplicate_receipts":
        ledger["calls"].append(deepcopy(row))
    if bad_field == "orphan_receipt":
        (parent / "call_438_orphan.json").write_text(json.dumps(receipt), encoding="utf-8")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    service = MockTextServiceV2(brief, raw)
    with pytest.raises(RuntimeError, match="parent unresolved|parent ordinal|parent duplicate|parent orphan"):
        runner.Pipeline(root, client_factory=lambda: service).run()
    assert service.requests == [] and not (root / "DELIVERABLE").exists()


def test_primary_review_unknown_stops_before_literal_audit(pipeline_workspace_v2):
    runner, root, _, brief, raw, _ = pipeline_workspace_v2
    service = MockTextServiceV2(brief, raw, review_unknown=True)
    result = runner.Pipeline(root, client_factory=lambda: service).run()
    assert result["status"] == "halt_review_uncertain" and len(service.requests) == 3
    assert service.audits == 0 and not (root / "DELIVERABLE").exists()


def test_audit_request_metadata_and_payload_do_not_claim_reference_or_plan(pipeline_workspace_v2):
    runner, root, _, brief, _, script = pipeline_workspace_v2
    op = runner.Pipeline(root)
    op.prepare()
    request = op.request("audit", script=script)
    import json
    payload = json.loads(request["messages"][-1]["content"])
    assert set(payload) == {"brief", "full_current_script", "evidence_catalog"}
    assert request["input_provenance"]["reference_fulltext_in_actual_messages"] is False
    assert request["input_provenance"]["reference_fulltext_sha256"] is None
    assert request["input_provenance"]["whole_script_sha256"] == contract._digest(script)


def test_finish_recomputes_combined_decision_and_rejects_added_unproved_fields(pipeline_workspace_v2):
    runner, root, _, brief, raw, script = pipeline_workspace_v2
    op = runner.Pipeline(root)
    op.prepare()
    review_value, audit_value = review_v2(script, brief), audit_v2(script, brief)
    decision = contract.combine_decisions(review_value, audit_value, script, brief)
    forged = {**decision, "unproved_approval": True}
    review = {"output": review_value, "validation": {"script_sha256": contract._digest(script)}, "ordinal": 439}
    audit = {"output": audit_value, "validation": {"script_sha256": contract._digest(script)}, "ordinal": 440}
    draft = {"output": raw, "ordinal": 438}
    with pytest.raises(ValueError, match="derive from these two complete"):
        op.finish(script, plan_for(script, brief), draft, review, audit, forged, 1)
    assert not (root / "DELIVERABLE").exists()
