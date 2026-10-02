"""Read-only replay of actual paid receipts; never dispatch or repair model text."""
import hashlib
import json
from pathlib import Path
import pytest
from src.content_factory.creative_modular_contract import build_direction_schema, validate_direction
from src.content_factory.creative_response_contract import validation_failure
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_diagnostic_spend import assert_no_unreconciled_diagnostic_spend, SharedDiagnosticSpendError

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/"data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299"
pytestmark=pytest.mark.skipif(not (ROOT/"call_024_direction_source_enum.json").exists(),
                            reason="actual production receipts not installed")
def read(path): return json.loads(path.read_text(encoding="utf-8"))
def receipt(number,label): return read(ROOT/f"call_{number:03}_{label}.json")

def test_current_core_schema_is_exactly_the_schema_tested_in_call24():
    context=read(ROOT/"CONTEXT.json")
    actual=receipt(24,"direction_source_enum")["request"]["structured_schema"]
    assert build_direction_schema(context)==actual

def test_complete_tool_result_with_wrong_array_type_is_rejected_without_unwrapping():
    path=ROOT/"call_024_direction_source_enum.json"
    before=path.read_bytes()
    record=read(path)
    assert record["response_metadata"]["finish_reason"]=="tool_calls"
    output=json.loads(record["response_text"])
    assert isinstance(output["beats"][0]["performance_requirements"],dict)
    with pytest.raises(CreativeContractError) as error:
        validate_direction(output,read(ROOT/"CONTEXT.json"))
    failure=validation_failure(error.value)
    assert failure["code"]=="MODULE_SCHEMA_INVALID"
    assert failure["category"]=="state_contract"
    assert failure["next_action"]=="complete_new_draft_then_full_review"
    assert failure["automatic_retry"] is False
    assert path.read_bytes()==before

def test_call23_replay_has_correct_module_fault_category_and_preserves_original():
    path=ROOT/"call_023_direction.json"
    before=path.read_bytes()
    output=json.loads(read(path)["response_text"])
    with pytest.raises(CreativeContractError) as error:
        validate_direction(output,read(ROOT/"CONTEXT.json"))
    failure=validation_failure(error.value)
    assert failure["code"]=="MODULE_REQUIREMENT_SOURCE"
    assert failure["category"]=="state_contract"
    assert path.read_bytes()==before

@pytest.mark.parametrize("code",["MODULE_SCHEMA_INVALID","MODULE_REQUIREMENT_SOURCE",
                                "MODULE_STALE_INPUT","MODULE_WINDOW_COVERAGE"])
def test_module_faults_require_complete_new_draft_and_full_review(code):
    error=CreativeContractError(code+": fixture")
    error.detail={"code":code}
    failure=validation_failure(error)
    assert failure["category"]=="state_contract"
    assert failure["next_action"]=="complete_new_draft_then_full_review"
    assert not failure["automatic_retry"]

def test_single_variable_case_preserves_messages_and_generation_settings():
    a=receipt(23,"direction")["request"]
    b=receipt(24,"direction_source_enum")["request"]
    assert a["messages"]==b["messages"]
    assert a["parameters"]==b["parameters"]
    assert a["structured_schema"]!=b["structured_schema"]
    context=json.loads(b["messages"][1]["content"])["context"]
    assert context==read(ROOT/"CONTEXT.json")
    evidence=read(ROOT/"CALL_LEDGER.json")["reference_evidence"][0]
    assert hashlib.sha256(context["reference_pack"][0]["text"].encode("utf-8")).hexdigest()==evidence["text_sha256"]

def test_frozen_budget_and_effective_spend_remain_distinct_and_old_runner_is_blocked():
    result=read(ROOT/"RESULT.json")
    assert result["frozen_parent_calls"]==21 and result["effective_calls_started"]==24
    assert result["diagnostic_reported_tokens"]==24698 and result["effective_reported_tokens"]==379026
    assert result["remaining_calls"]==0 and result["unknown_token_reservations"]==0
    parent=Path(read(ROOT/"CALL_LEDGER.json")["parent_run"])
    assert read(parent/"state.json")["calls_started"]==21
    with pytest.raises(SharedDiagnosticSpendError) as error:
        assert_no_unreconciled_diagnostic_spend(parent)
    assert error.value.provider_dispatch_started is False


def test_actual_invalid_seat_is_rejected_from_unmodified_initial_projection():
    from src.content_factory.creative_action_plan_v2 import check_sit_preconditions
    raw=json.loads(receipt(24,"direction_source_enum")["response_text"])
    before=json.dumps(raw,ensure_ascii=False,sort_keys=True)
    # This projects only configuration to a checker. It does not unwrap or adopt a draft.
    with pytest.raises(CreativeContractError) as error:
        check_sit_preconditions({"initial_state":raw["initial_state"],
                                "spatial_contract":raw["spatial_contract"],"beats":[]},
                               read(ROOT/"CONTEXT.json")["static_visual_manifest"])
    assert error.value.detail["code"]=="PLAN_SEAT_ACCESS_INVALID"
    assert error.value.detail["path"]=="spatial_contract.seats.0"
    assert json.dumps(raw,ensure_ascii=False,sort_keys=True)==before
