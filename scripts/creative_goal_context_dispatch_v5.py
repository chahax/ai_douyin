"""Independent modular run capacity; no inherited allowance is reset."""
from copy import deepcopy
from scripts.creative_goal_context_dispatch_v3 import GoalContextRuntime as PriorRuntime

LIMIT_CEILINGS = {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 3}


class GoalContextRuntime(PriorRuntime):
    def __init__(self, *args, stage_limits=None, **kwargs):
        limits = deepcopy(stage_limits if stage_limits is not None else LIMIT_CEILINGS)
        if set(limits) != set(LIMIT_CEILINGS) or any(
                type(value) is not int or not 0 <= value <= LIMIT_CEILINGS[key]
                for key, value in limits.items()):
            raise ValueError("modular run limits exceed independent ceilings")
        super().__init__(*args, stage_limits={key: min(value, 3) for key, value in limits.items()}, **kwargs)
        self.stage_limits = limits

    def _policy(self):
        result = super()._policy()
        result["schema"] = "creative_goal_context_dispatch/v5/policy"
        result["whole_goal_and_opening_setup_share_writer_stage_capacity"] = True
        result["substage_capacity_owned_by_frozen_coordinator"] = True
        return result

    def _validate_output(self, receipt, wire, validator):
        result = super()._validate_output(receipt, wire, validator)
        failure = result.get("failure")
        if isinstance(failure, dict) and str(failure.get("code", "")).startswith("OPENING_SETUP_"):
            failure["category"] = "state_contract"
            failure["next_action"] = "complete_new_native_opening_setup_then_full_validation"
        return result
