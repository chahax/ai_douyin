"""Three isolated dispatch roots; original ancestors are explicitly stubbed."""
from copy import deepcopy
from dataclasses import replace
import pytest

from scripts import creative_registered_review_ab_spend_anchor_v1 as spend
from test_creative_registered_review_ab_probe_v1 import setup_probe, prepare, offline, REAL


def settled_fixture(tmp_path, monkeypatch, fault):
    probe, seen, _, _ = setup_probe(tmp_path, monkeypatch, fault=fault)
    # Copy only real636 accounting shape, never claim an SDK ancestor was run.
    shape = spend.read(REAL / "data/qa/creative_paired_live_diagnostic_20261015/PROBE636_SPEND_ANCHOR_v1.json")
    parent = spend.read(probe.config.parent_anchor_path)
    for key in ("stage_calls", "accounted_stage_calls_after_probe", "inherited_unspent_original_stage_capacity",
        "inherited_whole_goal_candidates_used"):
        parent[key] = deepcopy(shape[key])
    spend.flow.write(probe.config.parent_anchor_path, parent)
    probe = spend.flow.Probe(replace(probe.config, parent_anchor_sha256=spend.digest(parent)),
        parent_verifier=probe.parent_verifier, source_gate=probe.source_gate, client_factory_builder=probe.client_factory_builder)
    monkeypatch.setattr(spend, "PROJECT", tmp_path)
    monkeypatch.setattr(spend, "verify_parent", probe.parent_verifier)
    prepare(probe); result = probe.run()
    return probe, seen, result


def test_two_known_results_fully_account_original_sql_sdk_and_tamper(tmp_path, monkeypatch):
    probe, seen, result = settled_fixture(tmp_path, monkeypatch, "contract")
    anchor = spend.build_anchor(probe.root)
    assert len(seen) == 2 and result["status"] == "diagnostic_completed_not_creative"
    assert anchor["inherited"] == {"calls_started": 638, "reported_tokens": 13409016, "calls_with_known_usage": 636,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    assert anchor["registered_ab_calls_used"] == anchor["registered_ab_call_limit"] == 2
    assert anchor["registered_ab_unused_calls"] == 0
    assert anchor["whole_goal_candidates_used"] == 4 and anchor["old_director_capacity"]["remaining"] == 0
    assert anchor["accounted_stage_calls_after_probe"] == {"goal_plan": 3, "goal_audit": 7, "complete_script": 1, "full_review": 1}
    assert not anchor["current_source_freshness_verified"] and not anchor["authorizes_new_dispatch"]
    assert spend.verify_anchor(anchor, expected_anchor_sha256=spend.digest(anchor))["verified"]
    # Tamper only this synthetic completed root; no additional SDK dispatch.
    state_path = probe.root / "STATE.json"; original = state_path.read_bytes()
    state = spend.read(state_path); state["spend"]["effective_reported_tokens"] -= 100
    spend.flow.write(state_path, state)
    with pytest.raises(ValueError, match="known spend"): spend.build_anchor(probe.root)
    state_path.write_bytes(original)
    snapshot = probe.root / "source_at_dispatch" / "PROFILE.json"
    snapshot.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match="frozen file changed"): spend.build_anchor(probe.root)
    assert len(seen) == 2


def test_one_known_protocol_rejection_retains_unused_b_as_accounting_only(tmp_path, monkeypatch):
    probe, seen, result = settled_fixture(tmp_path, monkeypatch, "missing_tool")
    anchor = spend.build_anchor(probe.root)
    assert len(seen) == 1 and result["status"] == "halt_protocol_requires_diagnosis"
    assert anchor["inherited"]["calls_started"] == 637 and anchor["inherited"]["reported_tokens"] == 13408916
    assert anchor["registered_ab_calls_used"] == anchor["registered_ab_unused_calls"] == 1
    assert [row["used"] for row in anchor["registered_representations"]] == [True, False]
    assert not anchor["unused_calls_authorize_dispatch"] and anchor["capacity_is_accounting_only_not_regranted"]
    assert not anchor["new_native_goal_created"] and anchor["latest_native_goal_receipt"]["ordinal"] == 627


def test_unknown_cannot_be_settled_even_if_state_is_renamed_completed(tmp_path, monkeypatch):
    probe, seen, result = settled_fixture(tmp_path, monkeypatch, "transport")
    assert len(seen) == 1 and result["status"] == "halt_interface_or_unknown"
    with pytest.raises(ValueError, match="settled"): spend.build_anchor(probe.root)
    state = spend.read(probe.root / "STATE.json"); state["status"] = "diagnostic_completed_not_creative"
    spend.flow.write(probe.root / "STATE.json", state)
    with pytest.raises(ValueError, match="unsettled"): spend.build_anchor(probe.root)
