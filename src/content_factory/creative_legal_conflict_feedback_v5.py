"""Use verified production parameters after v4 pre-dispatch rejection; no model switch."""
from src.content_factory.creative_legal_conflict_feedback_v4 import build_wire as prior,validate_current_script
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs)
 req['parameters']['temperature']=.4
 req['operator_version']='legal_conflict_feedback_complete_revision/v5_verified_parameters'
 req['input_provenance']['unverified_parameter_change_removed_before_dispatch']=True
 return req

