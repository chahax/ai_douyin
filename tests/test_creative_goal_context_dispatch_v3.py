"""V3 native-exception tests plus the unchanged fake dispatch gate suite.

All imported V2 gate tests run against the V3 runtime through a scoped module
replacement. No frozen V2 source, test, production receipt or ledger is edited.
"""
from copy import deepcopy

import pytest

from scripts import creative_goal_context_dispatch_v3 as adapter
from src.content_factory.creative_goal_source_contract_v2 import GoalContractError
from tests import test_creative_goal_context_dispatch_v2 as shared_tests


# Re-run the exact existing fault/claim assertions against the independent new
# adapter rather than duplicating the test implementations in another file.
for _name, _test in vars(shared_tests).items():
    if _name.startswith("test_") and callable(_test):
        globals()[_name] = _test


@pytest.fixture(autouse=True)
def v3_runtime_and_no_network(monkeypatch):
    monkeypatch.setattr(shared_tests, "adapter", adapter)
    def deny(*args, **kwargs):
        raise AssertionError("V3 unit tests cannot connect to any provider")
    monkeypatch.setattr(shared_tests.socket.socket, "connect", deny)
    monkeypatch.setattr(shared_tests.socket, "create_connection", deny)


@pytest.mark.parametrize("code", ["GOAL_SCHEMA_INVALID", "GOAL_ORIGIN_CLASS_MISMATCH",
                                   "GOAL_INITIAL_HOLDER_SUPPORT_CONFLICT", "GOAL_ENDING_UNTRACED"])
def test_native_goal_error_string_detail_is_saved_as_known_contract_failure(tmp_path, code):
    runtime, profile, sends, _ = shared_tests.temporary_runtime(tmp_path)
    native_detail = "本轮原生合同的具体来源/前提不相容；没有手工修正文。"
    def reject(value):
        raise GoalContractError(code, native_detail)
    first = runtime.dispatch("goal_01", shared_tests.request(profile), reject)
    assert first["status"] == "contract_rejected"
    assert first["failure"]["code"] == code and first["failure"]["category"] == "state_contract"
    assert first["validation_error"]["native_detail"] == native_detail
    assert first["validation_error"]["detail"] == {"code": code, "native_detail": native_detail}
    assert first["output"] == {"value": "goal_plan"} and first["response_metadata"]["total_tokens"] == 100
    assert runtime.summary()["new_unknown_token_reservations"] == 0
    assert not runtime.shared_lock.exists()
    second = runtime.dispatch("goal_02", shared_tests.request(profile, version=2), shared_tests.accept)
    assert second["status"] == "contract_valid" and len(sends) == 2
    original = adapter.read(runtime.root / adapter.read(runtime.ledger)["calls"][0]["receipt"])
    assert original == first and runtime.summary()["new_reported_tokens"] == 200


@pytest.mark.parametrize("detail", [None, ["origin", "missing"], 7, False])
def test_non_object_native_details_are_not_assumed_to_have_get(detail):
    class NativeError(ValueError):
        code = "GOAL_REFERENCE_UNKNOWN"
    error = NativeError("missing source reference")
    error.detail = deepcopy(detail)
    result = adapter.classify_validation_exception(error)
    assert result["failure"]["code"] == "GOAL_REFERENCE_UNKNOWN"
    assert result["validation_error"]["native_detail"] == detail
    assert result["validation_error"]["detail"]["native_detail"] == detail
    assert result["failure"]["automatic_retry"] is False


def test_declared_exception_code_has_precedence_but_dict_detail_remains_native():
    class NativeError(ValueError):
        code = "GOAL_DUPLICATE_ID"
        detail = {"code": "other_field", "ids": ["C1", "C1"]}
    error = NativeError("same ID twice")
    before = deepcopy(error.detail)
    result = adapter.classify_validation_exception(error)
    assert result["failure"]["code"] == "GOAL_DUPLICATE_ID"
    assert result["validation_error"]["detail"] == before
    assert error.detail == before


@pytest.mark.parametrize("code,category", [("MODULE_SCHEMA_INVALID", "state_contract"),
                                           ("PLAN_SCHEMA_INVALID", "state_contract"),
                                           ("EXPRESSION_WINDOW_INVALID", "compilation")])
def test_previous_structured_error_categories_are_preserved(code, category):
    class NativeError(ValueError):
        pass
    error = NativeError(code + ": explicit known failure")
    error.detail = {"code": code, "source": "offline"}
    result = adapter.classify_validation_exception(error)
    assert result["failure"]["code"] == code and result["failure"]["category"] == category
    assert result["validation_error"]["detail"] == error.detail


def test_plain_validation_error_without_detail_remains_known_failure(tmp_path):
    runtime, profile, _, _ = shared_tests.temporary_runtime(tmp_path)
    def reject(value):
        raise ValueError("known native value rejected")
    receipt = runtime.dispatch("goal_01", shared_tests.request(profile), reject)
    assert receipt["status"] == "contract_rejected"
    assert receipt["validation_error"]["detail"] == {}
    assert runtime.summary()["new_unknown_token_reservations"] == 0
