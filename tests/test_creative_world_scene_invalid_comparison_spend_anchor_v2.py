from copy import deepcopy
import pytest
from scripts import creative_world_scene_invalid_comparison_spend_anchor_v2 as bridge


def test_machine_latest_aliases_equal_real_accepted683_and_leave_native_cost_intact():
    original = bridge.read(bridge.ORIGINAL_PATH); before = bridge.digest(original)
    projected = bridge.project_aliases(original, bridge.original.evidence.Reader())
    aliases = {"latest_observable_events_" + key for key in ("receipt", "prepared_ref", "decision_ref")}
    for key in ("receipt", "prepared_ref", "decision_ref"):
        assert projected["latest_observable_events_" + key] == original["accepted_observable_events_" + key]
    assert {k:v for k,v in projected.items() if k not in aliases} == {k:v for k,v in original.items() if k not in aliases}
    assert bridge.digest(original) == before


def test_changed_certificate_or_resigned_wrong_alias_cannot_pass(monkeypatch):
    original = bridge.read(bridge.ORIGINAL_PATH); changed = deepcopy(original); changed["schema"] = "other/v1"
    with pytest.raises(ValueError, match="certificate/verifier"): bridge.project_aliases(changed, bridge.original.evidence.Reader())
    projected = bridge.project_aliases(original, bridge.original.evidence.Reader()); projected["schema"] = bridge.VERSION
    monkeypatch.setattr(bridge, "build_anchor", lambda *args, **kwargs: deepcopy(projected))
    changed = deepcopy(projected); changed["latest_observable_events_decision_ref"] = deepcopy(original["latest_observable_events_decision_ref"])
    with pytest.raises(ValueError, match="alias projection changed"):
        bridge.verify_anchor(changed, expected_anchor_sha256=bridge.digest(changed))
