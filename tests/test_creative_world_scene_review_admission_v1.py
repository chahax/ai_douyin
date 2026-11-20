"""Pure newly granted scope controls; real v6 validators, no provider calls."""
from copy import deepcopy
from pathlib import Path
import socket

import pytest

from scripts import creative_world_scene_review_admission_v1 as admission
from tests.test_creative_full_review_protocol_v6 import case as source_case, synthetic_full_reports, CONTEXTS


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("scope admission tests cannot contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def case():
    inputs, raw, views, law = source_case.__wrapped__()
    scope = inputs["production_preferences"]["prior_story_scope"]
    root = str(Path(__file__).resolve().parents[1] / "data/qa/creative_world_scene_live_review_20261015/synthetic_run")
    grant = {"schema": "OFFLINE_synthetic_user_scope_not_a_grant", "root": root, "grant_id": "synthetic_scope_control",
        "inputs_sha256": admission.digest(inputs), "text_same_story_allowed": True,
        "new_director_scope_limit": 3, "prior_scope_sha256": admission.digest(scope)}
    adapter = admission.make_review_adapter(grant, expected_user_scope_sha256=admission.digest(grant),
        prior_story_scope=scope, expected_root=root, expected_inputs_sha256=admission.digest(inputs))
    reports = synthetic_full_reports(views, law, prior_story_scope=scope)
    reports["semantic"]["prior_story_relation"]["relation"] = "same_story"
    return inputs, raw, views, law, grant, adapter, reports


def part(case, part="semantic", *, adapter=None, prior_scope=None):
    inputs, _, v, law, _, bound, reports = case
    return (adapter or bound).validate_part(reports[part], part, v["compiled_script"], v["brief"], v["plan"], law,
        context_sha256=CONTEXTS[part], goal_contract=v["goal"], opening_setup=v["opening_setup"],
        prior_story_scope=prior_scope or inputs["production_preferences"]["prior_story_scope"])


def bundle(case):
    inputs, _, v, law, _, adapter, reports = case
    return adapter.validate_bundle(adapter.build_review_bundle(reports["semantic"], reports["physical"]),
        v["compiled_script"], v["brief"], v["plan"], law, semantic_context_sha256=CONTEXTS["semantic"],
        physical_context_sha256=CONTEXTS["physical"], goal_contract=v["goal"], opening_setup=v["opening_setup"],
        prior_story_scope=inputs["production_preferences"]["prior_story_scope"])


def test_same_story_new_scope_proceeds_to_physical_without_relabelling_v6_pass(case):
    before = deepcopy(case[6]); result = part(case)
    assert result["valid"] and not result["accepted"]
    assert result["status"] == admission.OLD_QUOTA_STOP and result["revision_dispatch_blocked"]
    assert result["content_checks_satisfied"] and result["new_scope_admitted"]
    assert not result["native_v6_review_accepted"] and not result["capacity_consumed_here"]
    assert result["underlying_v6_decision"]["accepted"] is False
    physical = part(case, "physical")
    assert physical["accepted"] and physical["content_checks_satisfied"]
    complete = bundle(case)
    assert complete["valid"] and not complete["accepted"] and complete["new_scope_admitted"]
    assert complete["underlying_v6_decision"]["status"] == admission.OLD_QUOTA_STOP
    assert case[6] == before


def test_content_failure_is_only_bounded_complete_revision_not_content_admission(case):
    native = case[6]["semantic"]
    row = next(iter(native["fact_checks"].values()))
    row.update(status="fail", required_revision="OFFLINE explicit functional gap")
    native["revision_target"] = "script"
    result = part(case)
    assert result["valid"] and result["findings"] and not result["accepted"]
    assert result["new_scope_revision_admitted"] and not result["content_checks_satisfied"] and not result["new_scope_admitted"]
    assert result["underlying_v6_decision"]["revision_dispatch_blocked"] is True
    assert bundle(case)["new_scope_revision_admitted"]
    native["revision_target"] = "plan"
    result = part(case)
    assert result["valid"] and result["requires_new_goal_plan"] and result["new_scope_requires_new_goal_plan"]
    assert not result["new_scope_revision_admitted"] and not result["content_checks_satisfied"]


@pytest.mark.parametrize("fault", ["unknown_relation", "unknown_content", "missing_new_table", "physical_failure"])
def test_unknown_incomplete_and_physical_failures_never_admitted(case, fault):
    reports = case[6]
    if fault == "unknown_relation": reports["semantic"]["prior_story_relation"]["relation"] = "unknown"
    elif fault == "unknown_content": next(iter(reports["semantic"]["fact_checks"].values()))["status"] = "unknown"
    elif fault == "missing_new_table": reports["semantic"].pop("world_scene_checks")
    else:
        row = next(iter(reports["physical"]["action_checks"].values()))
        row.update(status="fail", required_revision="OFFLINE actual physical problem")
        reports["physical"]["revision_target"] = "script"
    result = bundle(case)
    assert not result["content_checks_satisfied"] and not result["new_scope_admitted"]
    assert result["new_scope_revision_admitted"] is (fault == "physical_failure")
    # A physical fail may be known content to repair, never a quota-only pass.
    assert not result["accepted"]


def test_unknown_identity_stays_unknown_even_if_body_is_deterministically_equal(case):
    inputs, _, views, law, grant, _, _ = case
    prior = deepcopy(inputs["production_preferences"]["prior_story_scope"])
    prior.update(full_prior_script=deepcopy(views["compiled_script"]), prior_script_sha256=admission.digest(views["compiled_script"]))
    grant = {**deepcopy(grant), "prior_scope_sha256": admission.digest(prior)}
    adapter = admission.make_review_adapter(grant, expected_user_scope_sha256=admission.digest(grant),
        prior_story_scope=prior, expected_root=grant["root"], expected_inputs_sha256=admission.digest(inputs))
    reports = synthetic_full_reports(views, law, prior_story_scope=prior)
    reports["semantic"]["prior_story_relation"]["relation"] = "unknown"
    result = adapter.validate_part(reports["semantic"], "semantic", views["compiled_script"], views["brief"], views["plan"], law,
        context_sha256=CONTEXTS["semantic"], goal_contract=views["goal"], opening_setup=views["opening_setup"], prior_story_scope=prior)
    assert result["underlying_v6_decision"]["status"] == admission.OLD_QUOTA_STOP
    assert not result["new_scope_admitted"] and not result["new_scope_revision_admitted"]


@pytest.mark.parametrize("fault", ["digest", "root", "prior", "bool_limit", "inputs"])
def test_grant_and_original_scope_identity_are_not_external_passed_flags(case, fault):
    inputs, _, _, _, grant, _, _ = case
    changed = deepcopy(grant); kwargs = {"expected_user_scope_sha256": admission.digest(changed),
        "prior_story_scope": inputs["production_preferences"]["prior_story_scope"], "expected_root": grant["root"],
        "expected_inputs_sha256": admission.digest(inputs)}
    if fault == "digest": kwargs["expected_user_scope_sha256"] = "0" * 64
    elif fault == "root": kwargs["expected_root"] = str(Path(grant["root"]) / "other")
    elif fault == "prior": changed["prior_scope_sha256"] = "0" * 64
    elif fault == "bool_limit": changed["new_director_scope_limit"] = True
    else: changed["inputs_sha256"] = "0" * 64
    if fault not in ("digest", "root"): kwargs["expected_user_scope_sha256"] = admission.digest(changed)
    with pytest.raises(ValueError): admission.make_review_adapter(changed, **kwargs)
    assert not part(case, prior_scope={**kwargs["prior_story_scope"], "purpose": "changed"})["valid"]


def test_live_sdk_default_adapter_whole_rewrite_then_same_story_two_reviews_and_handoff(tmp_path, monkeypatch):
    """All HTTP is MockTransport; exercise the production default adapter path."""
    from dataclasses import replace
    from tests import test_creative_world_scene_live_session_v1 as harness
    from scripts import creative_world_scene_live_session_v1 as live
    harness.offline.__wrapped__(monkeypatch)
    session, seen, _, _, scenario = harness.setup_session(tmp_path, monkeypatch)
    session.config = replace(session.config, review_admission_module="scripts.creative_world_scene_review_admission_v1")
    session.injected_review_adapter = None
    for version in (1, 2):
        scenario["documents"][f"full_review_semantic_{version:02}"]["output"]["prior_story_relation"]["relation"] = "same_story"
    harness.prepare(session)
    result = session.run()
    assert result["status"] == "text_ready_for_director", result
    assert len(seen) == 11 and "full_review_physical_01" not in [row["label"] for row in seen]
    ledger = live.read(session.root / "CALL_LEDGER.json")
    native_reviews = [live.read(session.root / row["receipt"]) for row in ledger["calls"] if row["label"].startswith("full_review_semantic_")]
    first, second = [row["validation"] for row in native_reviews]
    assert first["new_scope_revision_admitted"] and not first["content_checks_satisfied"]
    assert second["new_scope_admitted"] and second["content_checks_satisfied"]
    assert not first["accepted"] and not second["accepted"]
    assert all(row["status"] == admission.OLD_QUOTA_STOP for row in (first, second))
    monkeypatch.setattr(live.Session, "open", classmethod(lambda cls, root, **kwargs: session))
    verified = live.verify_text_handoff(session.root)
    assert verified["accepted"] and not verified["authorizes_media_dispatch"]
    handoff = live.read(session.root / "TEXT_HANDOFF.json")
    assert handoff["decision"]["underlying_v6_decision"]["accepted"] is False
    assert handoff["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
