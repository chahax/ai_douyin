"""Read a rejected, known native answer as repair input, never as accepted output."""
import json
from copy import deepcopy
from .narrative_revision import diagnose
from src.content_factory.corpus_screenplay_v1 import digest


def reuse_feedback(previous_input, current_input):
    keys=('complete_source','target_chapters','identities','places','scene_order','scene_objectives','editorial_brief')
    if any(previous_input.get(k)!=current_input.get(k) for k in keys):
        raise ValueError('repair_feedback_context_changed')
    feedback=previous_input.get('repair_feedback')
    if not isinstance(feedback,dict) or feedback.get('accepted') is not False or not feedback.get('native_receipt_sha256'):
        raise ValueError('missing_rejected_feedback_provenance')
    return deepcopy(feedback)


def rejected_feedback(receipt, state, plan, source, packet, design, maximum_seconds):
    if state.get('pending') is not None or state.get('status')!='needs_attention':
        raise ValueError('feedback_requires_known_failed_run')
    native=receipt['native'];choices=native.get('choices',[]);usage=native.get('usage',{})
    if not native.get('id') or native.get('model')!=plan['routes']['writer']['model']:
        raise ValueError('feedback_native_identity_invalid')
    if len(choices)!=1 or choices[0].get('finish_reason')!='stop' or choices[0]['message'].get('tool_calls'):
        raise ValueError('feedback_requires_complete_plain_json')
    if (not all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens'))
            or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']):
        raise ValueError('feedback_usage_unknown')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('feedback_duplicate_key')
            result[key]=value
        return result
    candidate=json.loads(choices[0]['message']['content'],object_pairs_hook=unique)
    report=diagnose(candidate,source,packet,design,maximum_seconds)
    return {'native_receipt_sha256':digest(receipt),'rejected_candidate':candidate,
            'structural_diagnosis':report,'accepted':False,
            'transport_issue':'Use submit_result with result_json; plain message was rejected.',
            'repair_instruction':'Revise this rejected draft against the complete source and all reported issues. Do not merely shorten seconds while retaining excessive speech. Return the complete screenplay, not diagnostic commentary.'}
