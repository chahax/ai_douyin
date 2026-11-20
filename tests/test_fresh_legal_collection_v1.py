from contextlib import contextmanager
from types import SimpleNamespace
import json
import pytest
from scripts import run_fresh_legal_collection_v1 as job


def setup(tmp_path, monkeypatch, *, healthy=True):
    monkeypatch.setattr(job, "PROJECT", tmp_path)
    root = tmp_path / "data/production_trials/new"
    plan = tmp_path / "seed.json"
    plan.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(job.sys, "argv", ["job", str(root), str(plan)])
    events = []
    context = SimpleNamespace(account_key="account01", profile=SimpleNamespace(profile_version=1),
        binding=SimpleNamespace(public_uid="expected"),
        create_browser_session=lambda **kw: SimpleNamespace(stop=lambda: events.append("closed")))
    class Service:
        def resolve(self, account):
            events.append("resolved")
            return context
        @contextmanager
        def operation_lease(self, ctx, **kwargs):
            assert kwargs["operation"] == "fresh_legal_identity_check"
            yield
        def verify_identity(self, ctx, *, session):
            return SimpleNamespace(healthy=healthy, status="active" if healthy else "login_expired",
                actual=SimpleNamespace(public_uid="expected") if healthy else None)
    monkeypatch.setattr(job, "AccountRuntimeService", Service)
    return root, events


def test_failed_identity_never_dispatches_collector(tmp_path, monkeypatch):
    root, events = setup(tmp_path, monkeypatch, healthy=False)
    monkeypatch.setattr(job.subprocess, "run", lambda *a, **kw: pytest.fail("must not collect"))
    assert job.main() == 1
    result = json.loads((root / "COLLECTION_RESULT.json").read_text(encoding="utf-8"))
    assert result["collection_submitted"] is False and result["status"] == "human_required"
    assert events == ["resolved", "closed"]


def test_exact_fresh_metadata_command_and_identity_fields(tmp_path, monkeypatch):
    root, events = setup(tmp_path, monkeypatch)
    def collect(args, **kw):
        assert "--headless" in args and "--legal-core-plan" in args
        assert not set(args) & {"--generate-script-pair", "--resume-collection-run", "--run-local-toolchain"}
        return SimpleNamespace(stdout=json.dumps({"status":"completed","collection_run_id":"new_batch","sample_gate":{"passed":True}}), stderr="", returncode=0)
    monkeypatch.setattr(job.subprocess, "run", collect)
    assert job.main() == 0
    identity = json.loads((root / "LIVE_IDENTITY_CHECK.json").read_text(encoding="utf-8"))
    assert identity["actual_public_id"] == identity["expected_public_id"] == "expected"
    assert events == ["resolved", "closed"]


def test_restart_does_not_verify_or_collect_again(tmp_path, monkeypatch):
    root, events = setup(tmp_path, monkeypatch, healthy=False)
    assert job.main() == 1
    with pytest.raises(FileExistsError):
        job.main()
    assert events == ["resolved", "closed"]


def test_non_json_result_stops_without_repeating_collection(tmp_path, monkeypatch):
    root, events = setup(tmp_path, monkeypatch)
    calls = []
    def collect(*a, **kw):
        calls.append(1)
        return SimpleNamespace(stdout="provider result unknown",stderr="",returncode=1)
    monkeypatch.setattr(job.subprocess, "run", collect)
    assert job.main() == 1
    assert len(calls) == 1 and (root / "COLLECTION.stdout.log").read_text() == "provider result unknown"
