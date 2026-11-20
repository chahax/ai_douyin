"""Independent focused planning audit capacity; frozen v6 ceilings unchanged."""
from copy import deepcopy
from scripts.creative_goal_context_dispatch_v6 import GoalContextRuntime as PriorRuntime
LIMIT_CEILINGS={"goal_plan":4,"goal_audit":6,"complete_script":3,"full_review":6}
class GoalContextRuntime(PriorRuntime):
    def __init__(self,*args,stage_limits=None,**kwargs):
        limits=deepcopy(stage_limits if stage_limits is not None else LIMIT_CEILINGS)
        if set(limits)!=set(LIMIT_CEILINGS) or any(type(v)is not int or not 0<=v<=LIMIT_CEILINGS[k] for k,v in limits.items()):
            raise ValueError("focused review run limits exceed independent ceilings")
        super().__init__(*args,stage_limits={k:min(v,4) for k,v in limits.items()},**kwargs)
        self.stage_limits=limits
    def _policy(self):
        value=super()._policy()
        value.update(schema="creative_goal_context_dispatch/v7/policy",native_goal_audit_parts_per_plan=3,
            full_review_parts_per_complete_script=2)
        return value
