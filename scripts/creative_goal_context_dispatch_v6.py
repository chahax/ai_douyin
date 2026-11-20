"""Independent capacity for two native full-review parts per whole screenplay.

Frozen v5 and every inherited ledger remain unchanged. The coordinator owns
part identities; this runtime only bounds the aggregate new-run dispatches.
"""
from copy import deepcopy
from scripts.creative_goal_context_dispatch_v5 import GoalContextRuntime as PriorRuntime

LIMIT_CEILINGS = {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6}


class GoalContextRuntime(PriorRuntime):
    def __init__(self, *args, stage_limits=None, **kwargs):
        limits = deepcopy(stage_limits if stage_limits is not None else LIMIT_CEILINGS)
        if set(limits) != set(LIMIT_CEILINGS) or any(
                type(value) is not int or not 0 <= value <= LIMIT_CEILINGS[key]
                for key, value in limits.items()):
            raise ValueError("split-review run limits exceed independent ceilings")
        # The old constructor receives its own legal subset. It initializes the
        # shared machinery without rewriting its ceilings or inherited spend.
        super().__init__(*args, stage_limits={key: min(value, 3) for key, value in limits.items()}, **kwargs)
        self.stage_limits = limits

    def _policy(self):
        result = super()._policy()
        result["schema"] = "creative_goal_context_dispatch/v6/policy"
        result["full_review_parts_per_complete_script"] = 2
        result["native_review_part_claims_owned_by_frozen_coordinator"] = True
        return result
