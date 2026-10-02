"""Pure experiment invariants: no SDK, network or authorization mutation."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
from scripts import prepare_minimax_rule_probe as probe

def test_all_six_messages_and_provider_parameters_are_identical():
    cases=probe.variants()
    assert [c["case_id"] for c in cases]==list("ABCDEF")
    common=deepcopy(cases[0]["request"]);common.pop("tools")
    for c in cases:
        wire=deepcopy(c["request"]);wire.pop("tools")
        assert wire==common
        assert c["input_context_sha256"]==probe.digest(probe.CONTEXT)
    assert {c["compare_to"] for c in cases if c["case_id"]=="D"}=={"B"}

def test_language_and_example_only_change_schema_description():
    cases={c["case_id"]:c for c in probe.variants()}
    def shape(label):
        v=deepcopy(cases[label]["request"]["tools"][0]["function"]["parameters"])
        v.pop("description",None)
        return v
    assert shape("A")==shape("B")==shape("C")
    assert cases["A"]["request"]["tools"][0]["function"]["parameters"].get("description") is None
    assert cases["B"]["request"]["tools"][0]["function"]["parameters"]["description"]!=cases["C"]["request"]["tools"][0]["function"]["parameters"]["description"]

@pytest.mark.parametrize("case_id",list("ABCDEF"))
def test_all_schemas_accept_exact_target(case_id):
    c=next(c for c in probe.variants() if c["case_id"]==case_id)
    Draft202012Validator(c["request"]["tools"][0]["function"]["parameters"]).validate(probe.EXPECTED)

@pytest.mark.parametrize("relation",["before","during","after","wrong"])
def test_prefix_reexpression_is_equivalent_to_common_items(relation):
    value=deepcopy(probe.EXPECTED)
    value["beats"][0]["performance_requirements"][0]["relation"]=relation
    d=Draft202012Validator(probe.flat_schema()).is_valid(value)
    e=Draft202012Validator(probe.prefix_schema()).is_valid(value)
    assert d==e

def test_conditional_schema_rejects_event_during_and_keeps_dialogue_during():
    valid=deepcopy(probe.EXPECTED)
    assert Draft202012Validator(probe.conditional_schema()).is_valid(valid)
    valid["beats"][0]["performance_requirements"][0]["relation"]="during"
    assert Draft202012Validator(probe.prefix_schema()).is_valid(valid)
    assert not Draft202012Validator(probe.conditional_schema()).is_valid(valid)

def test_wrong_object_wrapper_is_rejected_without_unwrapping():
    value=deepcopy(probe.EXPECTED)
    value["beats"][0]["performance_requirements"]={"item":value["beats"][0]["performance_requirements"]}
    before=deepcopy(value)
    result=probe.evaluate(value)
    assert result["status"]=="schema_rejected"
    assert result["checks"]["sources"]["passed"] is None
    assert value==before

@pytest.mark.parametrize("field,value",[
    ("stimulus_source","甲放杯之后"),
    ("subject","C99"),("minimum_seconds",3),("relation","before"),
])
def test_format_success_is_not_task_success(field,value):
    output=deepcopy(probe.EXPECTED)
    output["beats"][0]["performance_requirements"][0][field]=value
    result=probe.evaluate(output)
    assert result["checks"]["base_shape"]["passed"] is True
    assert result["status"]=="rule_rejected"

def test_example_is_valid_shape_but_cannot_be_adopted_as_target():
    Draft202012Validator(probe.base_schema()).validate(probe.EXAMPLE)
    assert probe.evaluate(probe.EXAMPLE)["status"]=="rule_rejected"

def test_preparation_carries_budget_history_without_authorizing_or_resetting(tmp_path):
    result=probe.prepare(tmp_path)
    plan=json.loads((tmp_path/"TEST_PLAN.json").read_text(encoding="utf-8"))
    assert result["paid_calls"]==0 and plan["dispatch_enabled"] is False
    assert plan["budget"]["effective_calls_started"]==24
    assert plan["budget"]["current_reported_tokens"]==379026
    assert plan["budget"]["old_budget_reset"] is False
    assert plan["budget"]["new_call_authorization"] is None
    assert plan["conservative_tokens_all_18"]<plan["budget"]["remaining_tokens"]
    assert all(len(plan["repeat_plan"][k])==6 and set(plan["repeat_plan"][k])==set("ABCDEF")
               for k in ("first_round","second_round","third_round"))
    assert probe.prepare(tmp_path)==result

def test_existing_preview_cannot_be_silently_overwritten(tmp_path):
    probe.prepare(tmp_path)
    path=tmp_path/"TEST_PLAN.json"
    plan=json.loads(path.read_text(encoding="utf-8"));plan["budget"]["new_call_authorization"]="forged"
    path.write_text(json.dumps(plan),encoding="utf-8")
    with pytest.raises(RuntimeError,match="preserve original"):
        probe.prepare(tmp_path)


def test_task_explicit_order_is_preserved_in_evaluation():
    output=deepcopy(probe.EXPECTED)
    output["beats"][0]["performance_requirements"].reverse()
    result=probe.evaluate(output)
    assert result["checks"]["base_shape"]["passed"] is True
    assert result["checks"]["sources"]["passed"] is True
    assert result["checks"]["task_values"]["passed"] is False
