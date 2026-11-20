"""Independent scope for two candidates with two necessary audit passes each."""
from copy import deepcopy
from scripts.creative_goal_context_dispatch_v3 import GoalContextRuntime as PriorRuntime

LIMIT_CEILINGS = {"goal_plan": 2, "goal_audit": 4, "complete_script": 3, "full_review": 3}
DEFAULT_STAGE_LIMITS = deepcopy(LIMIT_CEILINGS)


class GoalContextRuntime(PriorRuntime):
    def __init__(self, *args, stage_limits=None, **kwargs):
        limits = deepcopy(stage_limits if stage_limits is not None else LIMIT_CEILINGS)
        if set(limits) != set(LIMIT_CEILINGS) or any(type(value) is not int or not 0 <= value <= LIMIT_CEILINGS[key]
                for key, value in limits.items()):
            raise ValueError("explicit split-review limits exceed independent ceilings")
        super().__init__(*args, stage_limits={key: min(value, 3) for key, value in limits.items()}, **kwargs)
        self.stage_limits = limits

    def _policy(self):
        result = super()._policy()
        result["schema"] = "creative_goal_context_dispatch/v4/policy"
        result["separate_source_and_drama_audits"] = True
        return result
