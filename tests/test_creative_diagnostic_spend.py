import hashlib
import json
import os

import pytest

from src.content_factory import creative_diagnostic_spend as spend


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(spend, "SHARED_DIAGNOSTIC_DIRECTORY", tmp_path / "registry")
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "state.json").write_text('{"calls_started":21,"max_calls":24}', encoding="utf-8")
    return parent


def write_ledger(parent, calls):
    path = spend.shared_diagnostic_root(parent) / "CALL_LEDGER.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": spend.LEDGER_SCHEMA,
        "parent_run": str(parent.resolve()), "calls": calls}), encoding="utf-8")
    return path


def call(status="pending_response"):
    return {"ordinal": 22, "status": status, "token_reservation": 1300,
            "response_metadata": {}}


def test_missing_registry_allows_without_creating_files(registry):
    spend.assert_no_unreconciled_diagnostic_spend(registry)
    assert not spend.SHARED_DIAGNOSTIC_DIRECTORY.exists()


def test_valid_empty_ledger_allows(registry):
    path = write_ledger(registry, [])
    before = path.read_bytes()
    spend.assert_no_unreconciled_diagnostic_spend(registry)
    assert path.read_bytes() == before


@pytest.mark.parametrize("status", sorted(spend.CALL_STATUSES))
def test_every_reserved_outcome_blocks_without_changing_history(registry, status):
    path = write_ledger(registry, [call(status)])
    before = path.read_bytes()
    history = (registry / "state.json").read_bytes()
    with pytest.raises(spend.SharedDiagnosticSpendError, match="共享实际预算") as rejected:
        spend.assert_no_unreconciled_diagnostic_spend(registry)
    assert rejected.value.provider_dispatch_started is False
    assert path.read_bytes() == before
    assert (registry / "state.json").read_bytes() == history


def test_root_uses_resolved_absolute_normcase_parent(registry):
    alias = registry / ".." / registry.name
    assert spend.shared_diagnostic_root(alias) == spend.shared_diagnostic_root(registry)
    expected = hashlib.sha256(os.path.normcase(str(registry.resolve())).encode("utf-8")).hexdigest()[:24]
    assert spend.shared_diagnostic_root(registry).name == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows case normalization")
def test_windows_case_variants_share_one_registry(registry):
    assert spend.shared_diagnostic_root(str(registry).upper()) == spend.shared_diagnostic_root(str(registry).lower())


@pytest.mark.parametrize("change", [
    {"schema": "wrong"}, {"parent_run": "relative/parent"},
    {"parent_run": None}, {"calls": None}, {"calls": {}}, {"calls": [None]},
    {"calls": [{"ordinal": True, "status": "pending_response", "token_reservation": 10, "response_metadata": {}}]},
    {"calls": [{"ordinal": 22, "status": "unexpected", "token_reservation": 10, "response_metadata": {}}]},
    {"calls": [{"ordinal": 22, "status": "pending_response", "token_reservation": -1, "response_metadata": {}}]},
    {"calls": [{"ordinal": 22, "status": "pending_response", "token_reservation": True, "response_metadata": {}}]},
    {"calls": [{"ordinal": 22, "status": "pending_response", "token_reservation": 10, "response_metadata": []}]},
])
def test_malformed_ledger_fails_closed(registry, change):
    path = write_ledger(registry, [])
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(change)
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(spend.SharedDiagnosticSpendError) as rejected:
        spend.assert_no_unreconciled_diagnostic_spend(registry)
    assert rejected.value.provider_dispatch_started is False


def test_other_absolute_parent_fails_closed(registry):
    path = write_ledger(registry, [])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["parent_run"] = str(registry.parent / "other")
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(spend.SharedDiagnosticSpendError):
        spend.assert_no_unreconciled_diagnostic_spend(registry)


@pytest.mark.parametrize("body", [b"{broken", b"[]", b"\xff\xfe"])
def test_invalid_json_or_encoding_fails_closed(registry, body):
    path = write_ledger(registry, [])
    path.write_bytes(body)
    with pytest.raises(spend.SharedDiagnosticSpendError):
        spend.assert_no_unreconciled_diagnostic_spend(registry)


def test_unreadable_ledger_location_fails_closed(registry):
    path = spend.shared_diagnostic_root(registry) / "CALL_LEDGER.json"
    path.mkdir(parents=True)
    with pytest.raises(spend.SharedDiagnosticSpendError):
        spend.assert_no_unreconciled_diagnostic_spend(registry)

def test_registry_access_error_is_not_treated_as_absent(registry, monkeypatch):
    path = write_ledger(registry, [])
    original = type(path).lstat
    def unreadable(candidate):
        if candidate == path:
            raise PermissionError("fixture access denied")
        return original(candidate)
    monkeypatch.setattr(type(path), "lstat", unreadable)
    with pytest.raises(spend.SharedDiagnosticSpendError) as rejected:
        spend.assert_no_unreconciled_diagnostic_spend(registry)
    assert rejected.value.provider_dispatch_started is False