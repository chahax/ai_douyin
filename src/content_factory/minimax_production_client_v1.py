"""Permanent MiniMax-M3.1-Flash policy for new corpus tasks only."""
from copy import deepcopy

from .minimax_text_trial_client_v1 import MiniMaxTextTrialClient, MODEL
from .creative_workflow_roles import RoleResult

VERSION = 'minimax_production_client/v1'
REQUEST_POLICY = {
    'model': MODEL, 'thinking': 'adaptive', 'reasoning_effort': 'medium',
    'reasoning_split': True, 'response_format': None,
    'sampling': 'provider_fixed', 'automatic_transport_retries': 0,
    'max_completion_tokens_includes_reasoning': True,
}


class MiniMaxProductionClient:
    """Translate the legacy ledger's generic options into the frozen M3.1 policy.

    The tested native-response validator is shared, not copied or weakened.
    Effective provider parameters are preserved beside the full native response.
    """
    def __init__(self, native_client=None):
        self.native = native_client or MiniMaxTextTrialClient(model=MODEL, reasoning_effort='medium')

    def call(self, role, messages, *, max_tokens=16384, temperature=None,
             thinking=None, response_format=None):
        if role != 'writer':
            raise ValueError('minimax_production_writer_role_required')
        if thinking not in (None, 'disabled', 'adaptive'):
            raise ValueError('unsupported_ledger_thinking_option')
        if response_format not in (None, {'type': 'json_object'}):
            raise ValueError('unsupported_ledger_output_mode')
        result = self.native.call('writer', messages, max_tokens=max_tokens, thinking='adaptive')
        metadata = {**result.metadata, 'production_client_version': VERSION,
                    'effective_request_policy': deepcopy(REQUEST_POLICY),
                    'effective_max_completion_tokens': max_tokens}
        return RoleResult(result.text, metadata, result.response_payload)
