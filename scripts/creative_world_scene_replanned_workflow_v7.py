"""Source-bound native payloads, frozen full7 and explicit writer projection."""
from scripts import creative_world_scene_replanned_workflow_v4 as prior
from scripts import creative_isolated_event_entailment_v3 as isolated
from scripts import creative_isolated_writer_projection_v1 as writer_projection

VERSION = "creative_world_scene_replanned_workflow/v7"


class ReviewWorkflow(prior.ReviewWorkflow):
    prepare_observable_events_request = staticmethod(isolated.prepare_events)
    validate_observable_events = staticmethod(isolated.validate_events)
    prepare_event_entailment_request = staticmethod(isolated.prepare_entailment)
    validate_event_entailment = staticmethod(isolated.validate_entailment)
    build_event_entailment_review_packet = staticmethod(isolated.build_review_packet)
    build_event_entailment_repair_feedback = staticmethod(isolated.build_repair_feedback)

    def prepare_script_request(self, inputs, profile, goal, audit, **kwargs):
        return writer_projection.prepare(self, super().prepare_script_request, isolated, VERSION, inputs, profile, goal, audit, **kwargs)
